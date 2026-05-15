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
                transcript_json TEXT, started_at TEXT, completed_at TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("INSERT INTO projects (slug) VALUES ('myslug')")
        conn.execute("INSERT INTO orchestration_runs (project_id) VALUES (1)")
        # crew_run with orchestration_run_id=1
        conn.execute("INSERT INTO crew_runs (project_id, crew_name, orchestration_run_id) VALUES (1, 'discovery_interviews', 1)")
        conn.execute("INSERT INTO stakeholders (project_id, name) VALUES (1, 'Bob')")
        conn.commit()
    return db_path


def test_interview_session_tool_create(tmp_path):
    db_path = _setup_sync_db(tmp_path)
    from agents.tools.interview_session_tool import InterviewSessionTool
    with patch("agents.tools.interview_session_tool._db_path", return_value=db_path), \
         patch("agents.tools.interview_session_tool.get_settings") as ms:
        ms.return_value.frontend_url = "https://app.example.com"
        tool = InterviewSessionTool(slug="myslug", orchestration_run_id=1)  # crew_run_id=1
        result = tool._run(
            operation="create",
            sessions=[{"stakeholder_id": 1, "name": "Bob", "node_label": "Goods-in",
                        "session_token": "abc-123"}],
            session_tokens=[],
        )
    assert "abc-123" in result
    assert "https://app.example.com" in result
    # verify DB state
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM interview_sessions WHERE session_token='abc-123'").fetchone()
        assert row is not None
        assert row["status"] == "pending"


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
