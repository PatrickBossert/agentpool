# tests/test_interview_session_tool.py
"""Tests for InterviewSessionTool and interview_sessions DB helpers."""
import pytest
import pytest_asyncio
import aiosqlite
from api.database import (
    insert_interview_session,
    fetch_interview_session,
    fetch_interview_sessions_status,
    fetch_interview_transcripts,
    update_interview_session_status,
    complete_interview_session,
)


@pytest_asyncio.fixture
async def db(tmp_path):
    """In-memory aiosqlite connection with schema applied."""
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                llm_mode TEXT NOT NULL DEFAULT 'standard',
                sector TEXT, config_json TEXT,
                status TEXT NOT NULL DEFAULT 'created',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS orchestration_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                status TEXT NOT NULL DEFAULT 'running',
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            );
            CREATE TABLE IF NOT EXISTS stakeholders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL,
                job_title TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS interview_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                orchestration_run_id INTEGER REFERENCES orchestration_runs(id),
                stakeholder_id INTEGER NOT NULL REFERENCES stakeholders(id),
                node_label TEXT NOT NULL,
                session_token TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                voice_config TEXT,
                script_id TEXT,
                transcript_json TEXT,
                ratings_json TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.commit()
        await conn.execute("INSERT INTO projects (slug) VALUES ('testslug')")
        await conn.execute("INSERT INTO orchestration_runs (project_id) VALUES (1)")
        await conn.execute("INSERT INTO stakeholders (project_id, name) VALUES (1, 'Alice')")
        await conn.commit()
        yield conn


@pytest.mark.asyncio
async def test_insert_and_fetch_interview_session(db):
    sid = await insert_interview_session(
        db, project_id=1, orchestration_run_id=1,
        stakeholder_id=1, node_label="Goods-in", session_token="tok-001"
    )
    assert isinstance(sid, int)
    row = await fetch_interview_session(db, "tok-001")
    assert row is not None
    assert row["node_label"] == "Goods-in"
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_fetch_interview_session_missing_returns_none(db):
    row = await fetch_interview_session(db, "nonexistent")
    assert row is None


@pytest.mark.asyncio
async def test_fetch_interview_sessions_status(db):
    await insert_interview_session(db, project_id=1, orchestration_run_id=1,
        stakeholder_id=1, node_label="N1", session_token="tok-a")
    await insert_interview_session(db, project_id=1, orchestration_run_id=1,
        stakeholder_id=1, node_label="N2", session_token="tok-b")
    await update_interview_session_status(db, "tok-b", "completed")
    counts = await fetch_interview_sessions_status(db, orchestration_run_id=1)
    assert counts["pending"] == 1
    assert counts["completed"] == 1
    assert counts["active"] == 0
    assert counts["abandoned"] == 0


@pytest.mark.asyncio
async def test_complete_interview_session(db):
    await insert_interview_session(db, project_id=1, orchestration_run_id=1,
        stakeholder_id=1, node_label="N1", session_token="tok-c")
    await complete_interview_session(db, "tok-c", '[{"question":"Q1","answer":"A1"}]')
    row = await fetch_interview_session(db, "tok-c")
    assert row["status"] == "completed"
    assert row["transcript_json"] is not None


@pytest.mark.asyncio
async def test_fetch_interview_transcripts(db):
    await insert_interview_session(db, project_id=1, orchestration_run_id=1,
        stakeholder_id=1, node_label="N1", session_token="tok-d")
    await complete_interview_session(db, "tok-d", '[{"question":"Q1","answer":"A1"}]')
    transcripts = await fetch_interview_transcripts(db, orchestration_run_id=1)
    assert len(transcripts) == 1
    assert transcripts[0]["node_label"] == "N1"
    assert transcripts[0]["name"] == "Alice"


# ── InterviewSessionTool unit tests ──────────────────────────────────────────

import sqlite3
import contextlib
import json as _json
from unittest.mock import patch


def _setup_sync_db(tmp_path):
    """Create a sync sqlite3 DB with minimal schema for tool tests."""
    db_path = str(tmp_path / "tool_test.db")
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                llm_mode TEXT NOT NULL DEFAULT 'standard',
                sector TEXT, config_json TEXT,
                status TEXT NOT NULL DEFAULT 'created',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS orchestration_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                status TEXT NOT NULL DEFAULT 'running',
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            );
            CREATE TABLE IF NOT EXISTS crew_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                crew_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                orchestration_run_id INTEGER REFERENCES orchestration_runs(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS stakeholders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL, job_title TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS interview_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                orchestration_run_id INTEGER REFERENCES orchestration_runs(id),
                stakeholder_id INTEGER NOT NULL REFERENCES stakeholders(id),
                node_label TEXT NOT NULL,
                session_token TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                voice_config TEXT, script_id TEXT,
                transcript_json TEXT, started_at TEXT, completed_at TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("INSERT INTO projects (slug) VALUES ('myslug')")
        conn.execute("INSERT INTO orchestration_runs (project_id) VALUES (1)")
        # crew_run with orchestration_run_id=1
        conn.execute("INSERT INTO crew_runs (project_id, crew_name, orchestration_run_id) VALUES (1, 'discovery_interviews', 1)")
        conn.execute("INSERT INTO stakeholders (project_id, name) VALUES (1, 'Bob')")
        conn.execute("INSERT INTO stakeholders (project_id, name) VALUES (1, 'Carol')")
        conn.commit()
    return db_path


@pytest.fixture
def seeded_tool_project(tmp_path):
    """Shared DB setup for InterviewSessionTool tests: a project, orchestration run, crew
    run and two stakeholders (assignments), with the tool's `_db_path` patched to point at
    it for the lifetime of the test.

    Yields (slug, crew_run_id) - the tool's `orchestration_run_id` field actually receives
    the crew_run_id and resolves the real orchestration_run_id from it internally, which is
    why every test in this file passes `orchestration_run_id=1` (crew_runs row id 1, whose
    own orchestration_run_id column also happens to be 1).
    """
    db_path = _setup_sync_db(tmp_path)
    with patch("agents.tools.interview_session_tool._db_path", return_value=db_path):
        yield "myslug", 1


def test_interview_session_tool_create(seeded_tool_project):
    """The tool builds its printed URLs via interview_service.interview_url(), imported
    inside _create() to dodge a circular import - so the setting that matters is
    platform_public_url() as interview_service looks it up (its own module-level
    `from ... import platform_public_url` binding), not the tool module's, and the
    expected string carries the /dashboard basename the SPA is served under.

    The session_token is minted in code (uuid.uuid4()) rather than supplied by the caller,
    so the persisted row is located by stakeholder_id/node_label rather than by a
    caller-chosen token.
    """
    slug, run_id = seeded_tool_project
    from agents.tools.interview_session_tool import InterviewSessionTool, _db_path
    with patch(
        "api.services.interview_service.platform_public_url",
        return_value="https://app.example.com",
    ):
        tool = InterviewSessionTool(slug=slug, orchestration_run_id=run_id)
        result = tool._run(
            operation="create",
            sessions=[{"stakeholder_id": 1, "name": "Bob", "node_label": "Goods-in"}],
            session_tokens=[],
        )
    assert "https://app.example.com/dashboard/interview/" in result
    # verify DB state
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM interview_sessions WHERE stakeholder_id=1 AND node_label='Goods-in'"
        ).fetchone()
        assert row is not None
        assert row["status"] == "pending"
        import uuid as _uuid
        assert _uuid.UUID(row["session_token"]).version == 4


def test_the_token_is_generated_in_code(seeded_tool_project):
    """Taylor's prompt (agents/discovery/interview_coordinator.py) used to ask the model to
    'Generate a UUID4' session_token. The uniqueness of the sole access credential for the
    entire public interview API must not depend on a language model, so _create() mints its
    own token - and must do so even if a caller's session dict tries to supply one.
    """
    import uuid
    slug, run_id = seeded_tool_project
    from agents.tools.interview_session_tool import InterviewSessionTool, _db_path

    tool = InterviewSessionTool(slug=slug, orchestration_run_id=run_id)
    tool._run(
        operation="create",
        sessions=[
            {"stakeholder_id": 1, "name": "Bob", "node_label": "Goods-in",
             "session_token": "not-a-real-uuid"},  # model-supplied token must be ignored
            {"stakeholder_id": 2, "name": "Carol", "node_label": "Packing"},
        ],
        session_tokens=[],
    )

    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        tokens = [r[0] for r in conn.execute(
            "SELECT session_token FROM interview_sessions WHERE orchestration_run_id=?",
            (run_id,),
        )]

    assert tokens, "create wrote no sessions - the fixture seeded no assignments"
    assert len(set(tokens)) == len(tokens), "duplicate session tokens"
    assert "not-a-real-uuid" not in tokens, (
        "a caller-supplied token was used instead of one generated in code"
    )
    for token in tokens:
        assert uuid.UUID(token).version == 4, f"{token} is not a uuid4"


def test_interview_session_tool_get_status(tmp_path):
    db_path = _setup_sync_db(tmp_path)
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO interview_sessions (project_id, orchestration_run_id, "
            "stakeholder_id, node_label, session_token) VALUES (1,1,1,'N1','tok-x')"
        )
        conn.commit()
    from agents.tools.interview_session_tool import InterviewSessionTool
    with patch("agents.tools.interview_session_tool._db_path", return_value=db_path):
        tool = InterviewSessionTool(slug="myslug", orchestration_run_id=1)
        result = tool._run(operation="get_status", sessions=[], session_tokens=[])
    assert "pending" in result
    assert "pending=1" in result


def test_interview_session_tool_mark_abandoned(tmp_path):
    db_path = _setup_sync_db(tmp_path)
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO interview_sessions (project_id, orchestration_run_id, "
            "stakeholder_id, node_label, session_token) VALUES (1,1,1,'N1','tok-y')"
        )
        conn.commit()
    from agents.tools.interview_session_tool import InterviewSessionTool
    with patch("agents.tools.interview_session_tool._db_path", return_value=db_path):
        tool = InterviewSessionTool(slug="myslug", orchestration_run_id=1)
        result = tool._run(operation="mark_abandoned", sessions=[], session_tokens=["tok-y"])
    assert "abandoned" in result.lower()
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute("SELECT status FROM interview_sessions WHERE session_token='tok-y'").fetchone()
    assert row[0] == "abandoned"


def test_interview_session_tool_unknown_operation(tmp_path):
    db_path = _setup_sync_db(tmp_path)
    from agents.tools.interview_session_tool import InterviewSessionTool
    with patch("agents.tools.interview_session_tool._db_path", return_value=db_path):
        tool = InterviewSessionTool(slug="myslug", orchestration_run_id=1)
        result = tool._run(operation="foobar", sessions=[], session_tokens=[])
    assert "unknown" in result.lower() or "Error" in result


def test_interview_session_tool_get_transcripts(tmp_path):
    db_path = _setup_sync_db(tmp_path)
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO interview_sessions (project_id, orchestration_run_id, "
            "stakeholder_id, node_label, session_token, status, transcript_json) "
            "VALUES (1,1,1,'N1','tok-z','completed','[{\"question\":\"Q1\",\"answer\":\"A1\"}]')"
        )
        conn.commit()
    from agents.tools.interview_session_tool import InterviewSessionTool
    with patch("agents.tools.interview_session_tool._db_path", return_value=db_path):
        tool = InterviewSessionTool(slug="myslug", orchestration_run_id=1)
        result = tool._run(operation="get_transcripts", sessions=[], session_tokens=[])
    data = _json.loads(result)
    assert len(data) == 1
    assert data[0]["node_label"] == "N1"
