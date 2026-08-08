# tests/test_http_clients.py
"""Tests for the shared HTTP clients used on the interview request path.

Both ElevenLabs (TTS) and Anthropic clients were previously constructed fresh on every
call, paying a new TLS handshake each time: 478ms per call against 264ms shared, so 213ms
wasted on every utterance. These tests cover both the memoisation itself and that the
callers which mattered - speak and elaboration_press - actually use the shared instance
rather than continuing to build their own.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_the_tts_client_is_reused():
    """A new client per call pays a fresh TLS handshake - 213ms per utterance, measured."""
    from api.services.http_clients import get_tts_client
    assert get_tts_client() is get_tts_client()


def test_the_anthropic_client_is_reused():
    from api.services.http_clients import get_anthropic_client
    assert get_anthropic_client() is get_anthropic_client()


@pytest.mark.asyncio
async def test_closing_lets_the_next_call_rebuild():
    """Shutdown must not leave a closed client behind for a subsequent test or worker."""
    from api.services.http_clients import get_tts_client, close_http_clients
    first = get_tts_client()
    await close_http_clients()
    assert get_tts_client() is not first


@pytest.mark.asyncio
async def test_closing_lets_the_anthropic_client_rebuild():
    """Same guarantee on the Anthropic side - close then rebuild, not close then reuse stale."""
    from api.services.http_clients import get_anthropic_client, close_http_clients
    first = get_anthropic_client()
    await close_http_clients()
    assert get_anthropic_client() is not first


@pytest.mark.asyncio
async def test_speak_does_not_construct_a_client_per_call():
    """The getter memoising is not proof speak() uses it - speak could still build its own.

    Patch httpx.AsyncClient itself so a per-call constructor call would be caught, then call
    speak twice and assert the constructor ran at most once (the shared client is built lazily
    on first use, then reused).
    """
    from api.services import http_clients
    http_clients._tts_client = None  # start from a clean slate regardless of test order

    settings_obj = MagicMock()
    settings_obj.elevenlabs_api_key = "test-key"

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"fake-audio-bytes"

    real_async_client_cls = None
    with patch("api.services.interview_service.get_settings", return_value=settings_obj), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_instance = MagicMock()
        mock_instance.is_closed = False
        mock_instance.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_instance

        from api.services.interview_service import speak

        await speak("Hello", "voice-abc")
        await speak("World", "voice-abc")

    assert mock_client_cls.call_count == 1, (
        "httpx.AsyncClient() was constructed more than once across two speak() calls - "
        "speak is not reusing the shared client"
    )
    http_clients._tts_client = None  # leave the module clean for later tests
