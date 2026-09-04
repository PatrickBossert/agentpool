# tests/test_interviews_router.py
"""Tests for public interview API endpoints."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.config import get_settings
from api.database import get_connection, insert_interview_session


# The session carries a stamp because a real one does: `InterviewSessionTool._create` writes
# the chosen interviewer's resolved voice and synthesis model onto the row, and
# `POST /{token}/speak` reads them off it rather than taking a voice from its caller. A
# fixture without one is not a simpler session, it is a broken one - and the door refuses it
# on purpose, so that a session created without a resolved configuration is visible rather
# than being conducted in a fallback voice nobody chose.
FAKE_SESSION = {
    "session": {
        "id": 1,
        "session_token": "test-token-abc",
        "node_label": "Stakeholder A",
        "status": "pending",
        "interviewer_agent_id": "stakeholder_interviewer",
        "voice_config": {
            "elevenlabs_voice_id": "stamped-voice-1",
            "language": "en",
            "country_code": "GB",
            "model_id": "eleven_turbo_v2",
        },
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
        json={"text": "Hello"},
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
            json={"text": "Hello there"},
        )

    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == fake_audio


# ---------------------------------------------------------------------------
# 5. POST /{session_token}/elaboration-press — success
# ---------------------------------------------------------------------------

class _FakeConfigCursor:
    """Stands in for the aiosqlite cursor the router reads config_json from."""

    def __init__(self, config_json):
        self._config_json = config_json

    async def fetchone(self):
        return {"config_json": self._config_json}


class _FakeConfigConn:
    def __init__(self, config_json):
        self._config_json = config_json

    async def execute(self, *args, **kwargs):
        return _FakeConfigCursor(self._config_json)


class _FakeConnCtx:
    """Stands in for get_connection(slug)'s async context manager."""

    def __init__(self, config_json=None):
        self._config_json = config_json

    async def __aenter__(self):
        return _FakeConfigConn(self._config_json)

    async def __aexit__(self, *exc_info):
        return False


@pytest.mark.asyncio
async def test_elaboration_press_success(client):
    # The endpoint now resolves the slug itself (from _find_session_db) and reads the
    # configured budget from projects.config_json before calling elaboration_press, so both
    # are faked here rather than the higher-level get_session_with_script this endpoint no
    # longer calls.
    with patch(
        "api.routers.interviews._find_session_db",
        new_callable=AsyncMock,
        return_value="/tmp/agentpool_test/test-proj.db",
    ), patch(
        "api.routers.interviews.get_connection",
        return_value=_FakeConnCtx(config_json=None),
    ), patch(
        "api.routers.interviews.elaboration_press",
        new_callable=AsyncMock,
        return_value="Could you expand on that point?",
    ) as mock_press:
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
    mock_press.assert_awaited_once_with(
        "What are your main challenges?",
        "Many things.",
        "Ask for specifics.",
        "Alice",
        slug="test-proj",
        timeout_seconds=8.0,
    )


@pytest.mark.asyncio
async def test_elaboration_press_not_found(client):
    with patch(
        "api.routers.interviews._find_session_db",
        new_callable=AsyncMock,
        return_value=None,
    ):
        r = await client.post(
            "/api/interviews/unknown-token-xyz/elaboration-press",
            json={
                "question_text": "What are your main challenges?",
                "response_text": "Many things.",
                "probing_instructions": "Ask for specifics.",
            },
        )

    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


@pytest.mark.asyncio
async def test_an_over_budget_press_is_reported_as_an_empty_string(client):
    """The contract the interview pages are built on: no press is "", not an error.

    elaboration_press returns "" when it runs out of budget, and the endpoint passes that
    through with a 200. Both pages now read that as "no press was produced" and skip the
    follow-up entirely; before, VoiceInterview's `data.press_text ?? fallback` treated "" as
    a press and spoke it, leaving the interviewee recording in silence in front of a blank
    question. Pinned here so the shape the pages depend on cannot drift to null, a 503, or
    an omitted key without a test saying so.
    """
    with patch(
        "api.routers.interviews._find_session_db",
        new_callable=AsyncMock,
        return_value="/tmp/agentpool_test/test-proj.db",
    ), patch(
        "api.routers.interviews.get_connection",
        return_value=_FakeConnCtx(config_json=None),
    ), patch(
        "api.routers.interviews.elaboration_press",
        new_callable=AsyncMock,
        return_value="",
    ):
        r = await client.post(
            "/api/interviews/test-token-abc/elaboration-press",
            json={
                "question_text": "What are your main challenges?",
                "response_text": "Many things.",
                "probing_instructions": "Ask for specifics.",
            },
        )

    assert r.status_code == 200
    assert r.json() == {"press_text": ""}


@pytest.mark.asyncio
async def test_elaboration_press_reads_configured_budget(client):
    """The budget the endpoint hands elaboration_press must come from projects.config_json,
    not the default - otherwise Avery's settings page value is silently ignored."""
    with patch(
        "api.routers.interviews._find_session_db",
        new_callable=AsyncMock,
        return_value="/tmp/agentpool_test/budget-proj.db",
    ), patch(
        "api.routers.interviews.get_connection",
        return_value=_FakeConnCtx(config_json=json.dumps({"elaboration_press_timeout_seconds": 3})),
    ), patch(
        "api.routers.interviews.elaboration_press",
        new_callable=AsyncMock,
        return_value="",
    ) as mock_press:
        r = await client.post(
            "/api/interviews/test-token-abc/elaboration-press",
            json={
                "question_text": "Q?",
                "response_text": "short",
                "probing_instructions": "press",
            },
        )

    assert r.status_code == 200
    mock_press.assert_awaited_once_with(
        "Q?", "short", "press", "", slug="budget-proj", timeout_seconds=3.0,
    )


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
            json={"qa_pairs": [
                {"question_id": "SC-014.S3.Q1", "question": "What?", "answer": "This."}
            ]},
        )

    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_complete_interview_rejects_a_pair_with_no_question_id(client):
    """This payload - {"q": ..., "a": ...} - was accepted until the shape was typed.

    An answer that cannot name its question cannot be cited, grouped, or counted, and
    accepting it silently is how a session completes looking successful while producing
    evidence nothing can use.
    """
    r = await client.patch(
        "/api/interviews/test-token-abc/complete",
        json={"qa_pairs": [{"q": "What?", "a": "This."}]},
    )

    assert r.status_code == 422


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
# 10. GET /sessions/{slug} — requires auth, and still works with it
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_sessions_listing_requires_auth():
    """It returns every session_token for a project, and a token is the only credential
    the public interview API has. Anyone knowing a slug could answer anyone's interview.

    Built with a bare AsyncClient (no Authorization header) rather than the `client`
    fixture, which always attaches a sysadmin bearer token and so could never observe
    a refusal.
    """
    from httpx import AsyncClient, ASGITransport
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/interviews/sessions/any-slug")
    assert r.status_code in (401, 403), "session tokens are served without authentication"


@pytest.mark.asyncio
async def test_the_sessions_listing_works_with_auth(client):
    """A refusal-only test would also pass if the endpoint 403s for everybody - which
    would break the sessions view the consultant actually uses. Confirm the authenticated
    path still works (404 here, for an unknown slug, rather than 401/403)."""
    resp = await client.get("/api/interviews/sessions/nonexistent-slug-xyz")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 11. GET /sessions/{slug} — project exists but no orchestration runs
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
# 12. GET /sessions/{slug} — project with orchestration run and session data
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
    # Must carry the /dashboard basename the SPA is served under - a link built from
    # frontend_url instead of public_url, or missing /dashboard, 404s for the interviewee.
    assert session["interview_url"].endswith(f"/dashboard/interview/{session_token}")

    assert data["summary"]["completed"] == 1
    assert data["summary"]["pending"] == 0
    assert data["summary"]["active"] == 0
    assert data["summary"]["abandoned"] == 0


# ---------------------------------------------------------------------------
# 13. POST /{session_token}/email-transcript — destination must match the
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

    with patch("api.routers.interviews.send_project_mail", AsyncMock()) as mock_send:
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
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_email_transcript_allows_matching_destination(client, clean_email_transcript):
    """The invited stakeholder's own address still works, with edited content."""
    token = "email-token-match"
    await _seed_completed_session(client, token)

    with patch("api.routers.interviews.send_project_mail",
               AsyncMock(return_value=True)) as mock_send, \
         patch("api.routers.interviews.get_settings") as mock_settings:
        mock_settings.return_value.resend_api_key = "re_test"

        r = await client.post(
            f"/api/interviews/{token}/email-transcript",
            json={
                "email": _STAKEHOLDER_EMAIL,
                "qa_pairs": [{"question": "Q1", "answer": "edited answer"}],
            },
        )

    assert r.status_code == 200
    # The address the endpoint *intends* - which is the security control this test is
    # about. Where it actually lands is send_project_mail's decision, asserted against
    # a real transport in tests/test_outbound_mail_seam.py.
    assert mock_send.await_args.kwargs["to"] == [_STAKEHOLDER_EMAIL]
    # The caller's edited text is preserved — that feature must keep working
    assert "edited answer" in mock_send.await_args.kwargs["body"]
    assert mock_send.await_args.kwargs["slug"] == _EMAIL_SLUG


@pytest.mark.asyncio
async def test_email_transcript_match_is_case_insensitive(client, clean_email_transcript):
    """Address comparison must not reject purely on casing."""
    token = "email-token-case"
    await _seed_completed_session(client, token)

    with patch("api.routers.interviews.send_project_mail",
               AsyncMock(return_value=True)), \
         patch("api.routers.interviews.get_settings") as mock_settings:
        mock_settings.return_value.resend_api_key = "re_test"

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

    with patch("api.routers.interviews.send_project_mail", AsyncMock()) as mock_send:
        r = await client.post(
            f"/api/interviews/{token}/email-transcript",
            json={
                "email": f"  {_STAKEHOLDER_EMAIL}  ",
                "qa_pairs": [{"question": "Q1", "answer": "A1"}],
            },
        )

    assert r.status_code == 422
    mock_send.assert_not_awaited()


# ---------------------------------------------------------------------------
# 14. PATCH /{session_token}/status and PATCH /{session_token}/checkpoint —
#    both moved from a raw aiosqlite.connect onto interview_db_connection.
#    Neither endpoint had any functional coverage before this - every other
#    test in this file mocks the service layer out from under the router - so
#    these seed a real session and check the write actually lands, not just
#    that the endpoint returns 200.
# ---------------------------------------------------------------------------

_STATUS_SLUG = "interview-status-test"


@pytest.fixture
def clean_status_checkpoint():
    db_path = Path(get_settings().database_dir) / f"{_STATUS_SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _seed_pending_session(client, token: str) -> None:
    """Create a project with one pending session - no completed/email trappings needed."""
    r = await client.post(
        "/projects",
        json={"client_slug": _STATUS_SLUG, "llm_mode": "standard", "sector": "test"},
    )
    assert r.status_code in (200, 201)

    async with get_connection(_STATUS_SLUG) as conn:
        async with conn.execute(
            "SELECT id FROM projects WHERE slug=?", (_STATUS_SLUG,)
        ) as cur:
            project_id = (await cur.fetchone())["id"]

        cur = await conn.execute(
            "INSERT INTO stakeholders (project_id, name) VALUES (?,?)",
            (project_id, "Sam Stakeholder"),
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
        await conn.commit()


@pytest.mark.asyncio
async def test_update_session_status_writes_through_interview_db_connection(
    client, clean_status_checkpoint
):
    """The write must land, not just return 200 - a mocked service layer couldn't tell the
    difference between a real interview_db_connection write and a silently swallowed one."""
    token = "status-token-01"
    await _seed_pending_session(client, token)

    r = await client.patch(f"/api/interviews/{token}/status", json={"status": "active"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    async with get_connection(_STATUS_SLUG) as conn:
        cur = await conn.execute(
            "SELECT status FROM interview_sessions WHERE session_token=?", (token,)
        )
        assert (await cur.fetchone())["status"] == "active"


@pytest.mark.asyncio
async def test_save_checkpoint_writes_through_interview_db_connection(
    client, clean_status_checkpoint
):
    """The autosave path - the highest-frequency write during a live interview, and the
    scenario this task's concurrency fix is squarely aimed at - still saves correctly once
    routed through interview_db_connection instead of a raw aiosqlite.connect."""
    token = "checkpoint-token-01"
    await _seed_pending_session(client, token)

    r = await client.patch(
        f"/api/interviews/{token}/checkpoint",
        json={"checkpoint": {"question_index": 3, "answers": {"q1": "A"}}},
    )
    assert r.status_code == 200
    assert r.json() == {"saved": True}

    async with get_connection(_STATUS_SLUG) as conn:
        cur = await conn.execute(
            "SELECT checkpoint_json FROM interview_sessions WHERE session_token=?", (token,)
        )
        row = await cur.fetchone()
    assert json.loads(row["checkpoint_json"]) == {"question_index": 3, "answers": {"q1": "A"}}
