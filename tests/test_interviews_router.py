# tests/test_interviews_router.py
"""Tests for public interview API endpoints."""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.config import get_settings
from api.database import get_connection, insert_interview_session


FAKE_SESSION = {
    "session": {
        "id": 1,
        "session_token": "test-token-abc",
        "node_label": "Stakeholder A",
        "status": "pending",
    },
    "script": {"questions": []},
}


# ---------------------------------------------------------------------------
# 1. GET /{session_token} — not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_interview_session_not_found(client):
    r = await client.get("/api/interviews/unknown-token-xyz")
    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


# ---------------------------------------------------------------------------
# 2. GET /{session_token} — success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_interview_session_success(client):
    with patch(
        "api.routers.interviews.get_session_with_script",
        new_callable=AsyncMock,
        return_value=FAKE_SESSION,
    ):
        r = await client.get("/api/interviews/test-token-abc")
    assert r.status_code == 200
    data = r.json()
    assert data["session"]["session_token"] == "test-token-abc"
    assert "script" in data


# ---------------------------------------------------------------------------
# 3. POST /{session_token}/speak — not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_speak_not_found(client):
    r = await client.post(
        "/api/interviews/unknown-token-xyz/speak",
        json={"text": "Hello", "voice_id": "voice_123"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


# ---------------------------------------------------------------------------
# 4. POST /{session_token}/speak — success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_speak_success(client):
    fake_audio = b"\xff\xfb\x90\x00" * 16  # fake MP3 bytes

    with patch(
        "api.routers.interviews.get_session_with_script",
        new_callable=AsyncMock,
        return_value=FAKE_SESSION,
    ), patch(
        "api.routers.interviews.speak",
        new_callable=AsyncMock,
        return_value=fake_audio,
    ):
        r = await client.post(
            "/api/interviews/test-token-abc/speak",
            json={"text": "Hello there", "voice_id": "voice_123"},
        )

    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == fake_audio


# ---------------------------------------------------------------------------
# 5. POST /{session_token}/elaboration-press — success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_elaboration_press_success(client):
    with patch(
        "api.routers.interviews.get_session_with_script",
        new_callable=AsyncMock,
        return_value=FAKE_SESSION,
    ), patch(
        "api.routers.interviews.elaboration_press",
        new_callable=AsyncMock,
        return_value="Could you expand on that point?",
    ):
        r = await client.post(
            "/api/interviews/test-token-abc/elaboration-press",
            json={
                "question_text": "What are your main challenges?",
                "response_text": "Many things.",
                "probing_instructions": "Ask for specifics.",
                "stakeholder_name": "Alice",
            },
        )

    assert r.status_code == 200
    assert r.json() == {"press_text": "Could you expand on that point?"}


# ---------------------------------------------------------------------------
# 6. PATCH /{session_token}/complete — success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_interview_success(client):
    with patch(
        "api.routers.interviews.complete_session",
        new_callable=AsyncMock,
        return_value=True,
    ):
        r = await client.patch(
            "/api/interviews/test-token-abc/complete",
            json={"qa_pairs": [{"q": "What?", "a": "This."}]},
        )

    assert r.status_code == 200
    assert r.json() == {"ok": True}


# ---------------------------------------------------------------------------
# 7. PATCH /{session_token}/complete — with ratings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_with_ratings(client):
    with patch(
        "api.routers.interviews.complete_session",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_complete:
        r = await client.patch(
            "/api/interviews/test-token-abc/complete",
            json={
                "qa_pairs": [],
                "ratings": [{"section_id": "S1", "ratings": {"S1Q1": 3}, "commentary": "good"}],
            },
        )

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    mock_complete.assert_awaited_once_with(
        "test-token-abc",
        [],
        [{"section_id": "S1", "ratings": {"S1Q1": 3}, "commentary": "good"}],
    )


# ---------------------------------------------------------------------------
# 8. PATCH /{session_token}/complete — without ratings (defaults to None)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_without_ratings(client):
    with patch(
        "api.routers.interviews.complete_session",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_complete:
        r = await client.patch(
            "/api/interviews/test-token-abc/complete",
            json={"qa_pairs": []},
        )

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    mock_complete.assert_awaited_once_with("test-token-abc", [], None)


# ---------------------------------------------------------------------------
# 9. GET /sessions/{slug} — unknown slug returns 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_sessions_unknown_slug(client):
    resp = await client.get("/api/interviews/sessions/nonexistent-slug-xyz")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 8. GET /sessions/{slug} — project exists but no orchestration runs
# ---------------------------------------------------------------------------

_SESSIONS_SLUG_NO_RUNS = "sessions-no-runs-test"


@pytest.fixture
def clean_sessions_no_runs():
    db_path = Path(get_settings().database_dir) / f"{_SESSIONS_SLUG_NO_RUNS}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_get_sessions_no_runs(client, clean_sessions_no_runs):
    # Create the project (no orchestration runs)
    r = await client.post(
        "/projects",
        json={"client_slug": _SESSIONS_SLUG_NO_RUNS, "llm_mode": "standard", "sector": "test"},
    )
    assert r.status_code in (200, 201)

    r = await client.get(f"/api/interviews/sessions/{_SESSIONS_SLUG_NO_RUNS}")
    assert r.status_code == 200
    data = r.json()
    assert data["orchestration_run_id"] is None
    assert data["sessions"] == []
    assert data["summary"] == {"pending": 0, "active": 0, "completed": 0, "abandoned": 0}


# ---------------------------------------------------------------------------
# 8. GET /sessions/{slug} — project with orchestration run and session data
# ---------------------------------------------------------------------------

_SESSIONS_SLUG_WITH_DATA = "sessions-with-data-test"


@pytest.fixture
def clean_sessions_with_data():
    db_path = Path(get_settings().database_dir) / f"{_SESSIONS_SLUG_WITH_DATA}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_get_sessions_with_data(client, clean_sessions_with_data):
    # Create project via API to ensure full migration
    r = await client.post(
        "/projects",
        json={"client_slug": _SESSIONS_SLUG_WITH_DATA, "llm_mode": "standard", "sector": "test"},
    )
    assert r.status_code in (200, 201)

    # Insert orchestration run, stakeholder, and interview session directly
    async with get_connection(_SESSIONS_SLUG_WITH_DATA) as conn:
        async with conn.execute(
            "SELECT id FROM projects WHERE slug=?", (_SESSIONS_SLUG_WITH_DATA,)
        ) as cur:
            project_row = await cur.fetchone()
        project_id = project_row["id"]

        # Insert orchestration run
        cur = await conn.execute(
            "INSERT INTO orchestration_runs (project_id, status) VALUES (?, 'running')",
            (project_id,),
        )
        await conn.commit()
        orch_run_id = cur.lastrowid

        # Insert stakeholder
        cur = await conn.execute(
            "INSERT INTO stakeholders (project_id, name) VALUES (?, ?)",
            (project_id, "Alice Chen"),
        )
        await conn.commit()
        stakeholder_id = cur.lastrowid

        # Insert interview session
        session_token = "test-session-token-xyz"
        await insert_interview_session(
            conn,
            project_id=project_id,
            orchestration_run_id=orch_run_id,
            stakeholder_id=stakeholder_id,
            node_label="Goods-in Inspection",
            session_token=session_token,
        )
        # Mark as completed
        await conn.execute(
            "UPDATE interview_sessions SET status='completed' WHERE session_token=?",
            (session_token,),
        )
        await conn.commit()

    r = await client.get(f"/api/interviews/sessions/{_SESSIONS_SLUG_WITH_DATA}")
    assert r.status_code == 200
    data = r.json()
    assert data["orchestration_run_id"] == orch_run_id
    assert len(data["sessions"]) == 1

    session = data["sessions"][0]
    assert session["name"] == "Alice Chen"
    assert session["node_label"] == "Goods-in Inspection"
    assert session["session_token"] == session_token
    assert session["status"] == "completed"
    assert session["interview_url"].endswith(f"/interview/{session_token}")

    assert data["summary"]["completed"] == 1
    assert data["summary"]["pending"] == 0
    assert data["summary"]["active"] == 0
    assert data["summary"]["abandoned"] == 0
