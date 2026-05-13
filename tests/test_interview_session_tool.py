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
