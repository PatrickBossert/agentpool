# tests/test_interview_service.py
"""Unit tests for api/services/interview_service.py."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. get_session_with_script — session not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_session_with_script_returns_none_when_not_found():
    with patch(
        "api.services.interview_service._find_session_db", new_callable=AsyncMock
    ) as mock_find:
        mock_find.return_value = None

        from api.services.interview_service import get_session_with_script

        result = await get_session_with_script("nonexistent-token")

    assert result is None


# ---------------------------------------------------------------------------
# 2. get_session_with_script — returns session and script
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_session_with_script_returns_session_and_script(tmp_path):
    """Mock DB lookup and the scripts file on disk."""
    # Create a fake scripts JSON file
    slug = "fake-project"
    outputs_dir = tmp_path / "projects" / slug / "outputs"
    outputs_dir.mkdir(parents=True)
    scripts = {"exec_interview": {"questions": ["Q1", "Q2"], "voice_id": "abc123"}}
    (outputs_dir / "interview_scripts.json").write_text(json.dumps(scripts))

    # Fake DB path (stem = slug)
    fake_db = tmp_path / "data" / f"{slug}.db"
    fake_db.parent.mkdir(parents=True)
    fake_db.touch()

    fake_session = {
        "id": 1,
        "session_token": "tok-abc",
        "node_label": "exec_interview",
        "status": "pending",
    }

    with (
        patch(
            "api.services.interview_service._find_session_db", new_callable=AsyncMock
        ) as mock_find,
        patch(
            "api.services.interview_service.fetch_interview_session",
            new_callable=AsyncMock,
        ) as mock_fetch,
        patch("api.services.interview_service.get_settings") as mock_settings,
        patch("aiosqlite.connect"),
    ):
        mock_find.return_value = str(fake_db)
        mock_fetch.return_value = fake_session
        settings_obj = MagicMock()
        settings_obj.projects_dir = str(tmp_path / "projects")
        mock_settings.return_value = settings_obj

        from api.services.interview_service import get_session_with_script

        result = await get_session_with_script("tok-abc")

    assert result is not None
    assert result["session"]["node_label"] == "exec_interview"
    assert result["script"] == scripts["exec_interview"]


# ---------------------------------------------------------------------------
# 3. generate_deepgram_token — raises when key not set
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_deepgram_token_raises_without_key():
    with patch("api.services.interview_service.get_settings") as mock_settings:
        settings_obj = MagicMock()
        settings_obj.deepgram_api_key = ""
        mock_settings.return_value = settings_obj

        from api.services.interview_service import generate_deepgram_token

        with pytest.raises(ValueError, match="DEEPGRAM_API_KEY"):
            await generate_deepgram_token()


# ---------------------------------------------------------------------------
# 4. speak — raises when key not set
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_speak_raises_without_key():
    with patch("api.services.interview_service.get_settings") as mock_settings:
        settings_obj = MagicMock()
        settings_obj.elevenlabs_api_key = ""
        mock_settings.return_value = settings_obj

        from api.services.interview_service import speak

        with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
            await speak("Hello", "voice-xyz")


# ---------------------------------------------------------------------------
# 5. elaboration_press — returns a string
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_elaboration_press_returns_string():
    fake_text = "Could you elaborate on that point?"

    mock_content_block = MagicMock()
    mock_content_block.text = fake_text

    mock_response = MagicMock()
    mock_response.content = [mock_content_block]

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    mock_async_anthropic_cls = MagicMock(return_value=mock_client)
    mock_anthropic_module = MagicMock()
    mock_anthropic_module.AsyncAnthropic = mock_async_anthropic_cls

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
        import importlib
        import api.services.interview_service as svc_module
        importlib.reload(svc_module)

        result = await svc_module.elaboration_press(
            question_text="What are the main challenges?",
            response_text="It's complicated.",
            probing_instructions="Ask for specific examples.",
            stakeholder_name="Alice",
        )

    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# 6. complete_session — returns False when session not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_session_returns_false_when_not_found():
    with patch(
        "api.services.interview_service._find_session_db", new_callable=AsyncMock
    ) as mock_find:
        mock_find.return_value = None

        from api.services.interview_service import complete_session

        result = await complete_session("missing-token", [{"q": "x", "a": "y"}])

    assert result is False
