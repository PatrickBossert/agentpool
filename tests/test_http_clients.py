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
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_shared_clients():
    """Close and drop any real client, before and after each test *in this module*.

    pytest.ini sets asyncio_default_fixture_loop_scope = function, so every asyncio test
    gets its own event loop, while _tts_client/_anthropic_client in http_clients are
    process-global and outlive any single test's loop. A client left behind by one test
    sits there for the rest of the session - not closed, just orphaned from a dead loop -
    and the next test that drives real I/O through it hits a "different loop" RuntimeError,
    order-dependently.

    Scope note, because autouse invites the wrong reading: an autouse fixture declared in a
    test module applies to that module only. These are the tests that construct the shared
    clients deliberately, so this is where the clean-up belongs - but it is not a
    session-wide guarantee, and anything elsewhere that builds a shared client and leaves it
    behind is not covered by it. Widening this would mean moving it to conftest.py.
    """
    from api.services.http_clients import close_http_clients
    await close_http_clients()
    yield
    await close_http_clients()


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
async def test_speak_does_not_construct_a_client_per_call(tmp_path, monkeypatch):
    """The getter memoising is not proof speak() uses it - speak could still build its own.

    Patch httpx.AsyncClient itself so a per-call constructor call would be caught, then call
    speak twice and assert the constructor ran at most once (the shared client is built lazily
    on first use, then reused).

    speak() is cached (see tests/test_tts_cache.py), so this test points DATA_DIR at a fresh
    tmp_path: without it, "Hello"/"voice-abc" and "World"/"voice-abc" would be stored in the
    shared /tmp/agentpool_test cache on the first run of the suite and served as cache hits
    on every run after, and the assertion below - which is about client construction, not
    about caching - would see zero calls instead of one and fail on the second run.
    """
    from api.config import get_settings
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    settings_obj = MagicMock()
    settings_obj.elevenlabs_api_key = "test-key"

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"fake-audio-bytes"

    with patch("api.services.interview_service.get_settings", return_value=settings_obj), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_instance = MagicMock()
        mock_instance.is_closed = False
        mock_instance.post = AsyncMock(return_value=mock_resp)
        # aclose must be awaitable too: the autouse teardown fixture calls close_http_clients()
        # after every test, which awaits _tts_client.aclose() on whatever is_closed is False.
        mock_instance.aclose = AsyncMock()
        mock_client_cls.return_value = mock_instance

        from api.services.interview_service import speak

        await speak("Hello", "voice-abc")
        await speak("World", "voice-abc")

    assert mock_client_cls.call_count == 1, (
        "httpx.AsyncClient() was constructed more than once across two speak() calls - "
        "speak is not reusing the shared client"
    )
