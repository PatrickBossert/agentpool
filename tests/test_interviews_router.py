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


# ---------------------------------------------------------------------------
# 9. POST /{session_token}/email-transcript — destination must match the
#    stakeholder the session was created for.
#
#    The transcript body is deliberately caller-supplied (interviewees edit it
#    before sending), so the destination check is the control that stops a
#    leaked token being used to send attacker-controlled text from our
#    verified sending domain.
# ---------------------------------------------------------------------------

_EMAIL_SLUG = "email-transcript-test"
_STAKEHOLDER_EMAIL = "alice@example.com"


@pytest.fixture
def clean_email_transcript():
    db_path = Path(get_settings().database_dir) / f"{_EMAIL_SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _seed_completed_session(client, token: str) -> None:
    """Create a project with one completed session for _STAKEHOLDER_EMAIL."""
    r = await client.post(
        "/projects",
        json={"client_slug": _EMAIL_SLUG, "llm_mode": "standard", "sector": "test"},
    )
    assert r.status_code in (200, 201)

    async with get_connection(_EMAIL_SLUG) as conn:
        async with conn.execute(
            "SELECT id FROM projects WHERE slug=?", (_EMAIL_SLUG,)
        ) as cur:
            project_id = (await cur.fetchone())["id"]

        cur = await conn.execute(
            "INSERT INTO stakeholders (project_id, name, email) VALUES (?,?,?)",
            (project_id, "Alice Chen", _STAKEHOLDER_EMAIL),
        )
        await conn.commit()

        await insert_interview_session(
            conn,
            project_id=project_id,
            orchestration_run_id=None,
            stakeholder_id=cur.lastrowid,
            node_label="Goods-in Inspection",
            session_token=token,
        )
        await conn.execute(
            "UPDATE interview_sessions SET status='completed' WHERE session_token=?",
            (token,),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_email_transcript_rejects_foreign_destination(client, clean_email_transcript):
    """A valid completed token must not be usable to mail an arbitrary address."""
    token = "email-token-foreign"
    await _seed_completed_session(client, token)

    with patch("api.routers.interviews.httpx.AsyncClient") as mock_client:
        r = await client.post(
            f"/api/interviews/{token}/email-transcript",
            json={
                "email": "attacker@evil.example",
                "qa_pairs": [{"question": "Q", "answer": "attacker-controlled text"}],
            },
        )

    assert r.status_code == 403
    assert r.json()["detail"] == "Email does not match session"
    # Crucially: no outbound request was attempted
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_email_transcript_allows_matching_destination(client, clean_email_transcript):
    """The invited stakeholder's own address still works, with edited content."""
    token = "email-token-match"
    await _seed_completed_session(client, token)

    mock_resp = type("R", (), {"status_code": 200})()
    mock_ctx = AsyncMock()
    mock_ctx.post = AsyncMock(return_value=mock_resp)

    with patch("api.routers.interviews.httpx.AsyncClient") as mock_client, \
         patch("api.routers.interviews.get_settings") as mock_settings:
        mock_client.return_value.__aenter__.return_value = mock_ctx
        mock_settings.return_value.resend_api_key = "re_test"
        mock_settings.return_value.from_email = "T <noreply@example.com>"

        r = await client.post(
            f"/api/interviews/{token}/email-transcript",
            json={
                "email": _STAKEHOLDER_EMAIL,
                "qa_pairs": [{"question": "Q1", "answer": "edited answer"}],
            },
        )

    assert r.status_code == 200
    sent = mock_ctx.post.call_args.kwargs["json"]
    assert sent["to"] == [_STAKEHOLDER_EMAIL]
    # The caller's edited text is preserved — that feature must keep working
    assert "edited answer" in sent["text"]


@pytest.mark.asyncio
async def test_email_transcript_match_is_case_insensitive(client, clean_email_transcript):
    """Address comparison must not reject purely on casing."""
    token = "email-token-case"
    await _seed_completed_session(client, token)

    mock_resp = type("R", (), {"status_code": 200})()
    mock_ctx = AsyncMock()
    mock_ctx.post = AsyncMock(return_value=mock_resp)

    with patch("api.routers.interviews.httpx.AsyncClient") as mock_client, \
         patch("api.routers.interviews.get_settings") as mock_settings:
        mock_client.return_value.__aenter__.return_value = mock_ctx
        mock_settings.return_value.resend_api_key = "re_test"
        mock_settings.return_value.from_email = "T <noreply@example.com>"

        r = await client.post(
            f"/api/interviews/{token}/email-transcript",
            json={
                "email": "Alice@Example.COM",
                "qa_pairs": [{"question": "Q1", "answer": "A1"}],
            },
        )

    assert r.status_code == 200


@pytest.mark.asyncio
async def test_email_transcript_rejects_whitespace_padded_address(client, clean_email_transcript):
    """Padded addresses are rejected by the format validator before comparison."""
    token = "email-token-padded"
    await _seed_completed_session(client, token)

    with patch("api.routers.interviews.httpx.AsyncClient") as mock_client:
        r = await client.post(
            f"/api/interviews/{token}/email-transcript",
            json={
                "email": f"  {_STAKEHOLDER_EMAIL}  ",
                "qa_pairs": [{"question": "Q1", "answer": "A1"}],
            },
        )

    assert r.status_code == 422
    mock_client.assert_not_called()
