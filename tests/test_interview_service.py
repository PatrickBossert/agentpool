# tests/test_interview_service.py
"""Unit tests for api/services/interview_service.py."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings


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
    """Mock DB lookup and the ledger resolution script_for_session performs.

    Rewritten alongside the fix that made get_session_with_script resolve the script via
    script_for_session rather than a bare, node_label-keyed file: that file never exists once
    writes are versioned, so this test previously asserted a contract the code no longer (and
    should never again) implement.
    """
    slug = "fake-project"

    # Fake DB path (stem = slug)
    fake_db = tmp_path / "data" / f"{slug}.db"
    fake_db.parent.mkdir(parents=True)
    fake_db.touch()

    fake_session = {
        "id": 1,
        "project_id": 7,
        "session_token": "tok-abc",
        "node_label": "exec_interview",
        "status": "pending",
    }
    fake_script = {"script_id": "SC-001", "questions": ["Q1", "Q2"], "voice_id": "abc123"}

    with (
        patch(
            "api.services.interview_service._find_session_db", new_callable=AsyncMock
        ) as mock_find,
        patch(
            "api.services.interview_service.fetch_interview_session",
            new_callable=AsyncMock,
        ) as mock_fetch,
        patch(
            "api.services.interview_service.script_for_session",
            new_callable=AsyncMock,
        ) as mock_script,
        patch("api.services.interview_service.get_settings") as mock_settings,
        patch("aiosqlite.connect"),
    ):
        mock_find.return_value = str(fake_db)
        mock_fetch.return_value = fake_session
        mock_script.return_value = fake_script
        settings_obj = MagicMock()
        settings_obj.projects_dir = str(tmp_path / "projects")
        mock_settings.return_value = settings_obj

        from api.services.interview_service import get_session_with_script

        result = await get_session_with_script("tok-abc")

    assert result is not None
    assert result["session"]["node_label"] == "exec_interview"
    assert result["script"] == fake_script
    mock_script.assert_awaited_once()
    # The session dict passed through, not the raw row, so script_for_session can index it.
    assert mock_script.call_args.args[1] == slug
    assert mock_script.call_args.args[2]["node_label"] == "exec_interview"


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
    """elaboration_press must use the shared client from http_clients, not build its own.

    Previously this constructed AsyncAnthropic() per call, so the test patched sys.modules
    and reloaded interview_service to inject a fake class. Now the client is memoised in
    api.services.http_clients, so the getter itself is what must be mocked - patching
    sys.modules would miss it, since http_clients already holds its own AsyncAnthropic
    reference from import time.
    """
    fake_text = "Could you elaborate on that point?"

    mock_content_block = MagicMock()
    mock_content_block.text = fake_text

    mock_response = MagicMock()
    mock_response.content = [mock_content_block]

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch(
        "api.services.interview_service.get_anthropic_client", return_value=mock_client
    ):
        from api.services.interview_service import elaboration_press

        result = await elaboration_press(
            question_text="What are the main challenges?",
            response_text="It's complicated.",
            probing_instructions="Ask for specific examples.",
            stakeholder_name="Alice",
        )

    assert isinstance(result, str)
    assert len(result) > 0
    mock_client.messages.create.assert_awaited_once()


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


# ---------------------------------------------------------------------------
# 7. get_session_with_script — resolves through the ledger, not a bare path
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def served_project(tmp_path, monkeypatch):
    """A project with a versioned scripts artefact and one session, wired to the ledger."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "served"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True)

    # Keyed by script_id, as Maya actually writes it - not by node_label.
    scripts = {"SC-001": {"script_id": "SC-001", "node_id": "1.F",
                          "node_label": "Frontline Interview", "level": "F",
                          "relationship": "internal", "sections": []}}
    (outputs / "interview_scripts_v3.json").write_text(json.dumps(scripts))

    from api.database import get_connection
    async with get_connection(slug) as conn:
        await conn.execute("INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (slug,))
        pid = (await cur.fetchone())[0]
        # agent_outputs has no run_id column - only project_id, agent_name, output_type,
        # version, is_current and file_path are relevant to current_output_path resolution.
        await conn.execute(
            "INSERT INTO agent_outputs (project_id, agent_name, output_type, "
            "version, is_current, file_path) VALUES (?,?,?,?,?,?)",
            (pid, "interaction_designer", "interview_scripts", 3, 1,
             str(outputs / "interview_scripts_v3.json")),
        )
        await conn.execute(
            "INSERT INTO stakeholders (project_id, name) VALUES (?,?)", (pid, "Sam Stakeholder"),
        )
        await conn.commit()
        cur = await conn.execute("SELECT id FROM stakeholders WHERE project_id=?", (pid,))
        sid = (await cur.fetchone())[0]
        await conn.execute(
            "INSERT INTO interview_sessions (project_id, stakeholder_id, node_label, "
            "session_token, status) VALUES (?,?,?,?,?)",
            (pid, sid, "Frontline Interview", "tok-served", "pending"),
        )
        await conn.commit()
    yield slug
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_session_is_served_the_current_script(served_project):
    """The serving path must resolve through the ledger, as the completion path does.

    It previously read a bare interview_scripts.json, which versioning means never exists,
    and keyed the lookup by node_label against an artefact keyed by script_id. Two
    independent faults, either of which alone returns None - so every interviewee got a
    session with no questions.
    """
    from api.services.interview_service import get_session_with_script
    result = await get_session_with_script("tok-served")
    assert result is not None
    assert result["script"] is not None, "session served with no script"
    assert result["script"]["script_id"] == "SC-001"
