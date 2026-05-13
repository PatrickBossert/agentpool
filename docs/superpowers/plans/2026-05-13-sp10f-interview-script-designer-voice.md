# SP10f — Interview Script Designer + Voice Interviews Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Interview Script Designer agent (one structured script per value chain node) and a browser-based voice interview page (ElevenLabs TTS + Deepgram STT) to the Discovery Interviews crew.

**Architecture:** The crew grows from 3 to 4 agents: Script Designer → Coordinator → Interviewer → Synthesis Analyst. The Coordinator's job narrows to mapping stakeholders to their node's pre-built script and generating session tokens. The Interviewer creates DB session rows and presents URLs instead of conducting text Q&A. A new public FastAPI router (`/interviews/{token}`) serves six endpoints consumed by the browser-based VoiceInterview.tsx page.

**Tech Stack:** Python/CrewAI (agents), FastAPI + aiosqlite (API), sqlite3 sync (_db.py pattern for tool), React + TypeScript + @deepgram/sdk (frontend), ElevenLabs REST API (TTS), Deepgram REST API (streaming token), Anthropic API (elaboration press).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `api/database.py` | Modify | `interview_sessions` table migration + 6 async helpers |
| `agents/tools/interview_session_tool.py` | **Create** | Sync CrewAI tool wrapping interview_sessions (4 operations) |
| `agents/discovery/interview_script_designer.py` | **Create** | Script Designer agent + task factory |
| `agents/discovery/interview_coordinator.py` | Modify | Narrowed task: map stakeholders→scripts, generate session entries |
| `agents/discovery/stakeholder_interviewer.py` | Modify | 3-phase task: create sessions, HITL wait, collect transcripts |
| `agents/crews/discovery_interviews_crew.py` | Modify | 4-agent crew; add `discovery_brief` param; Script Designer prepended |
| `agents/tools/registry.py` | Modify | Add `interview_script_designer`; add `InterviewSessionTool` to coordinator + interviewer |
| `api/config.py` | Modify | Add `elevenlabs_api_key`, `deepgram_api_key` optional settings |
| `api/services/run_service.py` | Modify | Pass `discovery_brief` to `create_discovery_interviews_crew` |
| `api/services/interview_service.py` | **Create** | Service functions: load session+script, TTS, Deepgram token, elaboration press, complete |
| `api/routers/interviews.py` | **Create** | 6 public endpoints (no auth) |
| `api/main.py` | Modify | Register interviews router |
| `ui/src/utils/voiceLocale.ts` | **Create** | `{language, country_code}` → ElevenLabs voice ID lookup |
| `ui/src/types.ts` | Modify | Add `InterviewSession`, `InterviewScript`, `InterviewQuestion`, `VoiceConfig` |
| `ui/src/pages/VoiceInterview.tsx` | **Create** | Public browser voice interview page |
| `ui/src/router.tsx` | Modify | Add public `/interview/:sessionToken` route (outside ProtectedRoute) |
| `.env.example` | Modify | Add `ELEVENLABS_API_KEY`, `DEEPGRAM_API_KEY` |
| `tests/test_interview_script_designer.py` | **Create** | Agent task description tests |
| `tests/test_interview_session_tool.py` | **Create** | Tool operation tests |
| `tests/test_interview_service.py` | **Create** | Service + endpoint tests |
| `tests/test_discovery_interviews_agents.py` | Modify | Update coordinator test (reads interview_scripts not value_chain_tree) |
| `tests/test_discovery_interviews_crew.py` | Modify | Update agent/task count from 3→4; add discovery_brief param test |

---

## Task 1: DB migration — interview_sessions table + 6 async helpers

**Files:**
- Modify: `api/database.py`
- Create: `tests/test_interview_session_tool.py` (partial — DB helper tests only)

- [ ] **Step 1: Write the failing tests for DB helpers**

Create `tests/test_interview_session_tool.py`:

```python
# tests/test_interview_session_tool.py
"""Tests for InterviewSessionTool and interview_sessions DB helpers."""
import pytest
import aiosqlite
from api.database import (
    insert_interview_session,
    fetch_interview_session,
    fetch_interview_sessions_status,
    fetch_interview_transcripts,
    update_interview_session_status,
    complete_interview_session,
)


@pytest.fixture
async def db(tmp_path):
    """In-memory aiosqlite connection with schema applied."""
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        # Create minimal schema for tests
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                llm_mode TEXT NOT NULL DEFAULT 'standard',
                sector TEXT,
                config_json TEXT,
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
        # Seed minimal data
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/pboagents/Documents/agentpool1
python -m pytest tests/test_interview_session_tool.py -v 2>&1 | head -30
```

Expected: ImportError or AttributeError — `insert_interview_session` does not exist yet.

- [ ] **Step 3: Add migration function and 6 async helpers to api/database.py**

In `api/database.py`, add the migration function after `_migrate_stakeholder_assignments`:

```python
async def _migrate_interview_sessions(conn: aiosqlite.Connection) -> None:
    """Create interview_sessions table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS interview_sessions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id            INTEGER NOT NULL REFERENCES projects(id),
            orchestration_run_id  INTEGER REFERENCES orchestration_runs(id),
            stakeholder_id        INTEGER NOT NULL REFERENCES stakeholders(id),
            node_label            TEXT NOT NULL,
            session_token         TEXT NOT NULL UNIQUE,
            status                TEXT NOT NULL DEFAULT 'pending',
            transcript_json       TEXT,
            started_at            TEXT,
            completed_at          TEXT,
            created_at            DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()
```

Then wire it into `get_connection` — add `await _migrate_interview_sessions(conn)` after `await _migrate_stakeholder_assignments(conn)`:

```python
        await _migrate_stakeholder_assignments(conn)
        await _migrate_interview_sessions(conn)
        yield conn
```

Then add the 6 async helper functions (append to end of file):

```python
async def insert_interview_session(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    orchestration_run_id: int | None,
    stakeholder_id: int,
    node_label: str,
    session_token: str,
) -> int:
    cur = await conn.execute(
        "INSERT INTO interview_sessions "
        "(project_id, orchestration_run_id, stakeholder_id, node_label, session_token) "
        "VALUES (?,?,?,?,?)",
        (project_id, orchestration_run_id, stakeholder_id, node_label, session_token),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_interview_session(
    conn: aiosqlite.Connection, session_token: str
) -> dict | None:
    async with conn.execute(
        "SELECT * FROM interview_sessions WHERE session_token=?", (session_token,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def fetch_interview_sessions_status(
    conn: aiosqlite.Connection, *, orchestration_run_id: int
) -> dict:
    """Return counts of sessions by status for a given orchestration run."""
    counts = {"pending": 0, "active": 0, "completed": 0, "abandoned": 0}
    async with conn.execute(
        "SELECT status, COUNT(*) as n FROM interview_sessions "
        "WHERE orchestration_run_id=? GROUP BY status",
        (orchestration_run_id,),
    ) as cur:
        async for row in cur:
            status = row["status"]
            if status in counts:
                counts[status] = row["n"]
    return counts


async def fetch_interview_transcripts(
    conn: aiosqlite.Connection, *, orchestration_run_id: int
) -> list[dict]:
    """Return completed sessions with stakeholder name for transcript assembly."""
    async with conn.execute(
        "SELECT s.name, is_.stakeholder_id, is_.node_label, is_.transcript_json "
        "FROM interview_sessions is_ "
        "JOIN stakeholders s ON s.id = is_.stakeholder_id "
        "WHERE is_.orchestration_run_id=? AND is_.status='completed'",
        (orchestration_run_id,),
    ) as cur:
        return [dict(row) async for row in cur]


async def update_interview_session_status(
    conn: aiosqlite.Connection, session_token: str, status: str
) -> None:
    await conn.execute(
        "UPDATE interview_sessions SET status=? WHERE session_token=?",
        (status, session_token),
    )
    await conn.commit()


async def complete_interview_session(
    conn: aiosqlite.Connection, session_token: str, transcript_json: str
) -> None:
    await conn.execute(
        "UPDATE interview_sessions "
        "SET status='completed', transcript_json=?, completed_at=datetime('now') "
        "WHERE session_token=?",
        (transcript_json, session_token),
    )
    await conn.commit()
```

Also add all 6 to the import list at the top of `api/database.py` — they live in the same file so nothing to import, but confirm they're exported by updating the import in the existing `run_service.py` (which currently imports from `api.database`). No change needed since these are new names.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_interview_session_tool.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/database.py tests/test_interview_session_tool.py
git commit -m "feat(sp10f): add interview_sessions table migration and 6 async DB helpers"
```

---

## Task 2: InterviewSessionTool

**Files:**
- Create: `agents/tools/interview_session_tool.py`
- Modify: `tests/test_interview_session_tool.py` (add tool tests)

- [ ] **Step 1: Write failing tool tests**

Append to `tests/test_interview_session_tool.py`:

```python
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
        conn.execute("INSERT INTO stakeholders (project_id, name) VALUES (1, 'Bob')")
        conn.commit()
    return db_path


def test_interview_session_tool_create(tmp_path):
    db_path = _setup_sync_db(tmp_path)
    from agents.tools.interview_session_tool import InterviewSessionTool
    with patch("agents.tools.interview_session_tool._db_path", return_value=db_path), \
         patch("agents.tools.interview_session_tool.get_settings") as ms:
        ms.return_value.frontend_url = "https://app.example.com"
        tool = InterviewSessionTool(slug="myslug", orchestration_run_id=1)
        result = tool._run(
            operation="create",
            sessions=[{"stakeholder_id": 1, "name": "Bob", "node_label": "Goods-in",
                        "session_token": "abc-123"}],
            session_tokens=[],
        )
    assert "abc-123" in result
    assert "https://app.example.com" in result


def test_interview_session_tool_get_status(tmp_path):
    db_path = _setup_sync_db(tmp_path)
    # Pre-insert a session
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
    assert "1" in result


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
    # Verify DB state
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute("SELECT status FROM interview_sessions WHERE session_token='tok-y'").fetchone()
    assert row[0] == "abandoned"


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
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_interview_session_tool.py::test_interview_session_tool_create -v
```

Expected: ImportError — `interview_session_tool` module does not exist.

- [ ] **Step 3: Implement InterviewSessionTool**

Create `agents/tools/interview_session_tool.py`:

```python
# agents/tools/interview_session_tool.py
"""CrewAI tool wrapping the interview_sessions DB table with four operations.

Runs synchronously (CrewAI thread pool) using sqlite3 directly.
"""
import contextlib
import json
import sqlite3
from pathlib import Path
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings


def _db_path(slug: str) -> str:
    return str(Path(get_settings().database_dir) / f"{slug}.db")


class InterviewSessionToolInput(BaseModel):
    operation: str = Field(
        description="'create' | 'get_status' | 'get_transcripts' | 'mark_abandoned'"
    )
    sessions: list[dict] = Field(
        default=[],
        description="For 'create': list of {stakeholder_id, name, node_label, session_token}",
    )
    session_tokens: list[str] = Field(
        default=[],
        description="For 'mark_abandoned': list of session tokens to abandon",
    )


class InterviewSessionTool(BaseTool):
    name: str = "InterviewSessionTool"
    description: str = (
        "Manage interview sessions in the database. "
        "Operations: 'create' (insert sessions, returns URL list), "
        "'get_status' (returns pending/active/completed/abandoned counts), "
        "'get_transcripts' (returns completed transcript JSON), "
        "'mark_abandoned' (marks listed tokens as abandoned)."
    )
    args_schema: type[BaseModel] = InterviewSessionToolInput
    slug: str
    orchestration_run_id: int

    def _run(self, operation: str, sessions: list[dict], session_tokens: list[str]) -> str:
        db = _db_path(self.slug)

        with contextlib.closing(sqlite3.connect(db)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")

            # Get project_id once
            row = conn.execute("SELECT id FROM projects WHERE slug=?", (self.slug,)).fetchone()
            if not row:
                return f"Error: project '{self.slug}' not found"
            project_id = row["id"]

            # Resolve actual orchestration_run_id from crew_run_id.
            # The registry passes crew_run_id as orchestration_run_id; resolve the real one.
            orch_row = conn.execute(
                "SELECT orchestration_run_id FROM crew_runs WHERE id=?", (self.orchestration_run_id,)
            ).fetchone()
            actual_orch_id = (
                orch_row["orchestration_run_id"]
                if (orch_row and orch_row["orchestration_run_id"])
                else self.orchestration_run_id
            )

            if operation == "create":
                return self._create(conn, project_id, actual_orch_id, sessions)
            elif operation == "get_status":
                return self._get_status(conn, actual_orch_id)
            elif operation == "get_transcripts":
                return self._get_transcripts(conn, actual_orch_id)
            elif operation == "mark_abandoned":
                return self._mark_abandoned(conn, session_tokens)
            else:
                return f"Error: unknown operation '{operation}'"

    def _create(self, conn: sqlite3.Connection, project_id: int, orchestration_run_id: int, sessions: list[dict]) -> str:
        settings = get_settings()
        base_url = settings.frontend_url.rstrip("/")
        urls = []
        for s in sessions:
            conn.execute(
                "INSERT OR IGNORE INTO interview_sessions "
                "(project_id, orchestration_run_id, stakeholder_id, node_label, session_token) "
                "VALUES (?,?,?,?,?)",
                (
                    project_id,
                    orchestration_run_id,
                    s["stakeholder_id"],
                    s["node_label"],
                    s["session_token"],
                ),
            )
            url = f"{base_url}/interview/{s['session_token']}"
            urls.append(f"- {s.get('name', 'Stakeholder')}: {url}")
        conn.commit()
        return "Sessions created. Interview URLs:\n" + "\n".join(urls)

    def _get_status(self, conn: sqlite3.Connection, orchestration_run_id: int) -> str:
        counts = {"pending": 0, "active": 0, "completed": 0, "abandoned": 0}
        rows = conn.execute(
            "SELECT status, COUNT(*) as n FROM interview_sessions "
            "WHERE orchestration_run_id=? GROUP BY status",
            (orchestration_run_id,),
        ).fetchall()
        for row in rows:
            if row["status"] in counts:
                counts[row["status"]] = row["n"]
        total = sum(counts.values())
        return (
            f"Status summary ({total} sessions): "
            f"pending={counts['pending']}, active={counts['active']}, "
            f"completed={counts['completed']}, abandoned={counts['abandoned']}"
        )

    def _get_transcripts(self, conn: sqlite3.Connection, orchestration_run_id: int) -> str:
        rows = conn.execute(
            "SELECT s.name, is_.stakeholder_id, is_.node_label, is_.transcript_json "
            "FROM interview_sessions is_ "
            "JOIN stakeholders s ON s.id = is_.stakeholder_id "
            "WHERE is_.orchestration_run_id=? AND is_.status='completed'",
            (orchestration_run_id,),
        ).fetchall()
        results = [
            {
                "stakeholder_id": row["stakeholder_id"],
                "name": row["name"],
                "node_label": row["node_label"],
                "transcript_json": row["transcript_json"],
            }
            for row in rows
        ]
        return json.dumps(results)

    def _mark_abandoned(self, conn: sqlite3.Connection, session_tokens: list[str]) -> str:
        for token in session_tokens:
            conn.execute(
                "UPDATE interview_sessions SET status='abandoned' WHERE session_token=?",
                (token,),
            )
        conn.commit()
        return f"Marked {len(session_tokens)} session(s) as abandoned."
```

- [ ] **Step 4: Run all tool tests**

```bash
python -m pytest tests/test_interview_session_tool.py -v
```

Expected: 9 tests pass (5 DB helper + 4 tool tests).

- [ ] **Step 5: Commit**

```bash
git add agents/tools/interview_session_tool.py tests/test_interview_session_tool.py
git commit -m "feat(sp10f): add InterviewSessionTool (create/get_status/get_transcripts/mark_abandoned)"
```

---

## Task 3: Interview Script Designer agent

**Files:**
- Create: `agents/discovery/interview_script_designer.py`
- Create: `tests/test_interview_script_designer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_interview_script_designer.py`:

```python
# tests/test_interview_script_designer.py
"""Unit tests for the Interview Script Designer agent module."""
from unittest.mock import MagicMock, patch
import pytest


def _mock_agent():
    return MagicMock()


def test_script_designer_task_reads_value_chain_tree():
    """Task description instructs agent to read value_chain_tree."""
    from agents.discovery.interview_script_designer import create_interview_script_designer_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_script_designer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_script_designer_task(agent=agent, stakeholder_assignments="", discovery_brief="")
    _, kwargs = MockTask.call_args
    assert "value_chain_tree" in kwargs["description"]


def test_script_designer_task_reads_value_chain_summary():
    """Task description instructs agent to read value_chain_summary."""
    from agents.discovery.interview_script_designer import create_interview_script_designer_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_script_designer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_script_designer_task(agent=agent, stakeholder_assignments="", discovery_brief="")
    _, kwargs = MockTask.call_args
    assert "value_chain_summary" in kwargs["description"]


def test_script_designer_task_writes_interview_scripts():
    """Task description instructs agent to write interview_scripts."""
    from agents.discovery.interview_script_designer import create_interview_script_designer_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_script_designer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_script_designer_task(agent=agent, stakeholder_assignments="", discovery_brief="")
    _, kwargs = MockTask.call_args
    assert "interview_scripts" in kwargs["description"]


def test_script_designer_task_includes_discovery_brief():
    """Discovery brief is injected into task description when provided."""
    from agents.discovery.interview_script_designer import create_interview_script_designer_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_script_designer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_script_designer_task(
            agent=agent,
            stakeholder_assignments="",
            discovery_brief="Transform the supply chain",
        )
    _, kwargs = MockTask.call_args
    assert "Transform the supply chain" in kwargs["description"]


def test_script_designer_task_includes_assignments():
    """Stakeholder assignments injected into task description."""
    from agents.discovery.interview_script_designer import create_interview_script_designer_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_script_designer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_script_designer_task(
            agent=agent,
            stakeholder_assignments="- Alice Chen (Head of Ops) → L2: Order Fulfilment",
            discovery_brief="",
        )
    _, kwargs = MockTask.call_args
    assert "Alice Chen" in kwargs["description"]


def test_script_designer_task_includes_hitl():
    """Task description includes HumanInputTool HITL approval step."""
    from agents.discovery.interview_script_designer import create_interview_script_designer_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_script_designer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_script_designer_task(agent=agent, stakeholder_assignments="", discovery_brief="")
    _, kwargs = MockTask.call_args
    assert "HumanInputTool" in kwargs["description"]


def test_script_designer_task_includes_sections_guidance():
    """Task description mentions sections, questions, follow-up branches."""
    from agents.discovery.interview_script_designer import create_interview_script_designer_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_script_designer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_script_designer_task(agent=agent, stakeholder_assignments="", discovery_brief="")
    _, kwargs = MockTask.call_args
    desc = kwargs["description"]
    assert "sections" in desc
    assert "follow_up_branches" in desc
    assert "evasion_signals" in desc
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_interview_script_designer.py -v 2>&1 | head -20
```

Expected: ImportError — module does not exist.

- [ ] **Step 3: Implement Interview Script Designer**

Create `agents/discovery/interview_script_designer.py`:

```python
# agents/discovery/interview_script_designer.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_interview_script_designer(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Interview Script Designer",
        goal=(
            "Produce one rich, structured interview script per value chain node that has "
            "stakeholder assignments. Scripts incorporate corporate context, include thematic "
            "sections, per-question follow-up branches, probing instructions, and evasion signals."
        ),
        backstory=(
            "You are a senior discovery consultant who designs interview programmes for digital "
            "transformation engagements. You produce scripts that surface process pain points, "
            "actors, needs, and capability gaps at each node of the value chain, guided by the "
            "overall engagement context and value chain structure."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_interview_script_designer_task(
    agent: Agent,
    stakeholder_assignments: str = "",
    discovery_brief: str = "",
    context_tasks: list[Task] | None = None,
) -> Task:
    brief_block = (
        f"Engagement context (discovery brief):\n{discovery_brief}\n\n"
        if discovery_brief
        else ""
    )
    assignments_block = (
        f"Stakeholder assignments (node_label → assigned stakeholders):\n{stakeholder_assignments}\n\n"
        if stakeholder_assignments
        else ""
    )
    return Task(
        description=(
            f"{brief_block}"
            f"{assignments_block}"
            "Design one structured interview script per value chain node that has at least one "
            "stakeholder assigned.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='value_chain_tree', "
            "agent_name='interview_script_designer' to retrieve the approved value chain.\n"
            "2. Use SQLiteStateTool with operation='read', key='value_chain_summary', "
            "agent_name='interview_script_designer' to retrieve the value chain narrative "
            "(corporate context for the engagement).\n"
            "3. For each node_label in the assignments above, produce a script object:\n"
            "   {\n"
            "     \"node_label\": \"Goods-in Inspection\",\n"
            "     \"level\": \"L3\",\n"
            "     \"research_brief\": \"2-3 sentences on the purpose of this interview\",\n"
            "     \"study_objectives\": [\"Identify biggest pain points at this stage\"],\n"
            "     \"welcome_message\": \"Hi [name], thank you for joining...\",\n"
            "     \"closing_message\": \"Thank you for your time and insights...\",\n"
            "     \"sections\": [\n"
            "       {\n"
            "         \"title\": \"Role & Context\",\n"
            "         \"questions\": [\n"
            "           {\n"
            "             \"id\": \"Q1\",\n"
            "             \"text\": \"Tell me about your role day-to-day.\",\n"
            "             \"follow_up_count\": 2,\n"
            "             \"probing_instructions\": \"Probe for responsibilities and decision authority.\",\n"
            "             \"follow_up_branches\": [\n"
            "               \"Could you walk me through a specific example?\",\n"
            "               \"What does that look like on a typical day?\"\n"
            "             ],\n"
            "             \"evasion_signals\": [\"not sure\", \"it varies\", \"hard to say\"]\n"
            "           }\n"
            "         ]\n"
            "       }\n"
            "     ]\n"
            "   }\n"
            "   Guidelines:\n"
            "   - 4-6 thematic sections per script (e.g. Role & Context, Current Process & Pain Points, "
            "Data & Decision-Making, Tools & Systems, Modernisation Priorities)\n"
            "   - 2-4 questions per section; 8-14 questions total\n"
            "   - Each question has 1-3 pre-generated follow_up_branches and evasion_signals\n"
            "   - follow_up_count is the number of follow-up exchanges to conduct (1-2 typically)\n"
            "   - welcome_message and closing_message are warm, professional, reference the engagement\n"
            "   - research_brief and study_objectives are tailored to the node's position in the value chain\n"
            "   - Incorporate the engagement context (discovery brief) and value chain summary throughout\n"
            "4. Build a JSON object keyed by node_label containing all scripts:\n"
            "   { \"Goods-in Inspection\": {...script...}, \"Invoice Processing\": {...script...} }\n"
            "5. Use SQLiteStateTool with operation='write', key='interview_scripts', "
            "agent_name='interview_script_designer' to save the scripts object.\n"
            "6. Use HumanInputTool with prompt: 'Please review the interview scripts saved at "
            "outputs/interview_scripts.json — one script per node. Reply \"approved\" to proceed, "
            "or provide revision notes.'\n"
            "7. If revision notes are received, revise the scripts and call HumanInputTool again. "
            "Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "A JSON object saved to outputs/interview_scripts.json keyed by node_label. "
            "Each value is a structured script with sections, questions, follow-up branches, "
            "evasion signals, welcome/closing messages. Confirmed approved by a human reviewer."
        ),
        agent=agent,
        context=context_tasks or [],
    )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_interview_script_designer.py -v
```

Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add agents/discovery/interview_script_designer.py tests/test_interview_script_designer.py
git commit -m "feat(sp10f): add Interview Script Designer agent and task factory"
```

---

## Task 4: Updated Interview Coordinator + Stakeholder Interviewer

**Files:**
- Modify: `agents/discovery/interview_coordinator.py`
- Modify: `agents/discovery/stakeholder_interviewer.py`
- Modify: `tests/test_discovery_interviews_agents.py`

- [ ] **Step 1: Update the test for interview_coordinator (it now reads interview_scripts, not value_chain_tree)**

In `tests/test_discovery_interviews_agents.py`, find:

```python
def test_interview_coordinator_task_reads_value_chain_tree():
    """Task description instructs agent to read value_chain_tree."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=agent, stakeholder_assignments="")
    _, kwargs = MockTask.call_args
    assert "value_chain_tree" in kwargs["description"]
```

Replace with:

```python
def test_interview_coordinator_task_reads_interview_scripts():
    """Task description instructs agent to read interview_scripts (not design questions)."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=agent, stakeholder_assignments="")
    _, kwargs = MockTask.call_args
    assert "interview_scripts" in kwargs["description"]


def test_interview_coordinator_task_includes_voice_config():
    """Task description instructs agent to produce voice_config per stakeholder."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=agent, stakeholder_assignments="")
    _, kwargs = MockTask.call_args
    assert "voice_config" in kwargs["description"]


def test_interview_coordinator_task_writes_session_tokens():
    """Task description instructs agent to write session_token per stakeholder."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=agent, stakeholder_assignments="")
    _, kwargs = MockTask.call_args
    assert "session_token" in kwargs["description"]
```

- [ ] **Step 2: Add stakeholder interviewer test for 3-phase task**

Append to `tests/test_discovery_interviews_agents.py`:

```python
def test_stakeholder_interviewer_task_creates_sessions():
    """Updated task description includes InterviewSessionTool create operation."""
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task
    agent = _mock_agent()
    with patch("agents.discovery.stakeholder_interviewer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_stakeholder_interviewer_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "InterviewSessionTool" in kwargs["description"]
    assert "create" in kwargs["description"]


def test_stakeholder_interviewer_task_collects_transcripts():
    """Updated task writes interview_transcripts from completed sessions."""
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task
    agent = _mock_agent()
    with patch("agents.discovery.stakeholder_interviewer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_stakeholder_interviewer_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "get_transcripts" in kwargs["description"]
    assert "interview_transcripts" in kwargs["description"]
```

- [ ] **Step 3: Run tests to see which fail**

```bash
python -m pytest tests/test_discovery_interviews_agents.py -v
```

Expected: `test_interview_coordinator_task_reads_interview_scripts`, `test_interview_coordinator_task_includes_voice_config`, `test_interview_coordinator_task_writes_session_tokens`, `test_stakeholder_interviewer_task_creates_sessions`, `test_stakeholder_interviewer_task_collects_transcripts` all fail (coordinator still has old description; interviewer has old description).

- [ ] **Step 4: Rewrite interview_coordinator.py task description**

Replace the entire file `agents/discovery/interview_coordinator.py`:

```python
# agents/discovery/interview_coordinator.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


# Voice locale lookup: {language}_{country_code} → ElevenLabs voice ID
# Replace voice IDs with actual IDs from your ElevenLabs account.
VOICE_LOCALE_MAP = {
    "en_GB": "pNInz6obpgDQGcFmaJgB",  # Replace with actual en-GB voice ID
    "en_US": "EXAVITQu4vr4xnSDxMaL",  # Replace with actual en-US voice ID
    "en_AU": "AZnzlk1XvdvUeBnXmlld",  # Replace with actual en-AU voice ID
    "en_NZ": "pNInz6obpgDQGcFmaJgB",  # Falls back to en-GB; replace with actual
    "en_CA": "EXAVITQu4vr4xnSDxMaL",  # Falls back to en-US; replace with actual
    "fr_FR": "ThT5KcBeYPX3keUQqHPh",  # Replace with actual fr-FR voice ID
    "de_DE": "flq6f7yk4E4fJM5XTYuZ",  # Replace with actual de-DE voice ID
    "es_ES": "GBv7mTt0atIp3Br8iCZE",  # Replace with actual es-ES voice ID
}
_FALLBACK_VOICE_ID = "pNInz6obpgDQGcFmaJgB"  # en-GB fallback


def _resolve_voice_id(language: str, country_code: str) -> str:
    key = f"{language}_{country_code}"
    return VOICE_LOCALE_MAP.get(key, _FALLBACK_VOICE_ID)


def create_interview_coordinator(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Interview Coordinator",
        goal=(
            "Map each assigned stakeholder to their value chain node's pre-built interview script "
            "and produce a session plan with unique session tokens and locale-matched voice configuration."
        ),
        backstory=(
            "You are a senior discovery consultant who coordinates stakeholder interview logistics. "
            "You match stakeholders to the right interview script and ensure each session is "
            "configured with the correct language and voice accent for the interviewee's locale."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_interview_coordinator_task(
    agent: Agent,
    stakeholder_assignments: str = "",
) -> Task:
    voice_table = "\n".join(
        f"  {k}: {v}" for k, v in VOICE_LOCALE_MAP.items()
    )
    assignments_block = (
        f"Stakeholder assignments:\n{stakeholder_assignments}\n\n"
        if stakeholder_assignments
        else ""
    )
    return Task(
        description=(
            f"{assignments_block}"
            "Map each stakeholder to their node's interview script and produce a session plan.\n\n"
            "Voice locale map (language_countrycode → elevenlabs_voice_id):\n"
            f"{voice_table}\n"
            f"Fallback voice ID (if locale not in map): {_FALLBACK_VOICE_ID}\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='interview_scripts', "
            "agent_name='interview_coordinator' to retrieve the pre-built scripts keyed by node_label.\n"
            "2. For each stakeholder in the assignments above:\n"
            "   a. Identify their node_label\n"
            "   b. Look up their node's script in interview_scripts\n"
            "   c. Generate a unique session_token (UUID4 format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx)\n"
            "   d. Resolve voice_config using the locale map above:\n"
            "      - language = the stakeholder's preferred_language (default 'en')\n"
            "      - country_code = the stakeholder's country_code (default 'GB')\n"
            "      - elevenlabs_voice_id = look up in the map above (fallback if not found)\n"
            "   e. Produce a session entry:\n"
            "      {\n"
            "        \"stakeholder_id\": 1,\n"
            "        \"name\": \"Alice Chen\",\n"
            "        \"node_label\": \"Goods-in Inspection\",\n"
            "        \"session_token\": \"<uuid4>\",\n"
            "        \"voice_config\": {\n"
            "          \"language\": \"en\",\n"
            "          \"country_code\": \"NZ\",\n"
            "          \"elevenlabs_voice_id\": \"<voice-id>\"\n"
            "        }\n"
            "      }\n"
            "3. Build a JSON array of all session entries.\n"
            "4. Use SQLiteStateTool with operation='write', key='interview_plan', "
            "agent_name='interview_coordinator' to save the session array.\n"
            "5. Use HumanInputTool with prompt: 'Please review the interview plan saved at "
            "outputs/interview_plan.json. Each entry includes a session_token and voice_config. "
            "Reply \"approved\" to proceed, or provide revision notes.'\n"
            "6. If revision notes are received, revise the plan and call HumanInputTool again. "
            "Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "A JSON interview plan saved to outputs/interview_plan.json containing one session entry "
            "per assigned stakeholder with node_label, session_token, and voice_config. "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
    )
```

- [ ] **Step 5: Rewrite stakeholder_interviewer.py task description (3-phase)**

Replace the entire file `agents/discovery/stakeholder_interviewer.py`:

```python
# agents/discovery/stakeholder_interviewer.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_stakeholder_interviewer(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Stakeholder Interviewer",
        goal=(
            "Create interview sessions in the database, present interview URLs to the consultant, "
            "wait for completion, then collect transcripts for synthesis."
        ),
        backstory=(
            "You are a discovery interview coordinator who manages the voice interview process. "
            "You create sessions, share URLs with consultants, wait for stakeholders to complete "
            "their browser-based voice interviews, and collect the resulting transcripts."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_stakeholder_interviewer_task(
    agent: Agent,
    context_tasks: list[Task],
) -> Task:
    return Task(
        description=(
            "Manage the voice interview process in three phases.\n\n"
            "--- PHASE 1: Create sessions ---\n"
            "1. Use SQLiteStateTool with operation='read', key='interview_plan', "
            "agent_name='stakeholder_interviewer' to retrieve the session plan.\n"
            "2. Use InterviewSessionTool with operation='create', sessions=[<the session entries "
            "from interview_plan>] to insert one database row per stakeholder and receive formatted "
            "interview URLs. Each session entry must include: stakeholder_id, name, node_label, "
            "session_token.\n"
            "3. Use HumanInputTool with prompt: 'Interview sessions are live. Please share these "
            "links with your stakeholders:\\n\\n[paste the URL list from InterviewSessionTool]\\n\\n"
            "Reply \"ready\" when all interviews are complete, or \"partial\" to proceed with "
            "whoever has responded so far.'\n\n"
            "--- PHASE 2: Verify completion ---\n"
            "4. Use InterviewSessionTool with operation='get_status' to retrieve the current "
            "counts: pending, active, completed, abandoned.\n"
            "5. If any sessions are still pending or active and the consultant replied 'ready', "
            "flag the discrepancy and use HumanInputTool to ask again: 'Some sessions are still "
            "pending/active. Please confirm when ready, or reply \"partial\" to proceed with "
            "completed sessions only.'\n\n"
            "--- PHASE 3: Collect transcripts ---\n"
            "6. Use InterviewSessionTool with operation='get_transcripts' to retrieve all completed "
            "transcripts. The result is a JSON array of {stakeholder_id, name, node_label, "
            "transcript_json} objects.\n"
            "7. For each transcript entry, parse transcript_json (a JSON array of "
            "{question, answer} pairs). Assemble the final transcript format:\n"
            "   [\n"
            "     {\n"
            "       \"stakeholder_id\": 1,\n"
            "       \"name\": \"Alice Chen\",\n"
            "       \"node_labels\": [\"Goods-in Inspection\"],\n"
            "       \"qa_pairs\": [{\"question\": \"...\", \"answer\": \"...\"}]\n"
            "     }\n"
            "   ]\n"
            "8. Use SQLiteStateTool with operation='write', key='interview_transcripts', "
            "agent_name='stakeholder_interviewer' to save the assembled transcripts array.\n"
        ),
        expected_output=(
            "A JSON transcript file saved to outputs/interview_transcripts.json containing all "
            "Q&A pairs for every completed voice interview session."
        ),
        agent=agent,
        context=context_tasks,
    )
```

- [ ] **Step 6: Run all agent tests**

```bash
python -m pytest tests/test_discovery_interviews_agents.py -v
```

Expected: all tests pass (old test replaced with 3 new coordinator tests; 2 new interviewer tests; synthesis tests unchanged).

- [ ] **Step 7: Commit**

```bash
git add agents/discovery/interview_coordinator.py agents/discovery/stakeholder_interviewer.py tests/test_discovery_interviews_agents.py
git commit -m "feat(sp10f): update interview coordinator (voice_config, session tokens) and stakeholder interviewer (3-phase)"
```

---

## Task 5: 4-agent crew factory + registry + run_service

**Files:**
- Modify: `agents/crews/discovery_interviews_crew.py`
- Modify: `agents/tools/registry.py`
- Modify: `api/services/run_service.py`
- Modify: `tests/test_discovery_interviews_crew.py`

- [ ] **Step 1: Update crew tests for 4 agents**

In `tests/test_discovery_interviews_crew.py`, update `_build_crew` and agent/task count tests:

Find and replace the `_build_crew` helper and the two count tests:

```python
def _build_crew(mock_llm, stakeholder_assignments=None, discovery_brief=""):
    with patch("agents.crews.discovery_interviews_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.discovery_interviews_crew import create_discovery_interviews_crew
        return create_discovery_interviews_crew(
            slug="test",
            run_id=1,
            llm_mode="standard",
            sector="logistics",
            stakeholder_assignments=stakeholder_assignments or [],
            discovery_brief=discovery_brief,
            llm=mock_llm,
        )


def test_discovery_interviews_crew_has_four_agents(mock_llm):
    crew = _build_crew(mock_llm)
    assert len(crew.agents) == 4


def test_discovery_interviews_crew_has_four_tasks(mock_llm):
    crew = _build_crew(mock_llm)
    assert len(crew.tasks) == 4
```

Also add a new test (append after `test_discovery_interviews_crew_injects_assignments`):

```python
def test_discovery_interviews_crew_injects_discovery_brief(mock_llm):
    """Script designer task description includes the discovery brief."""
    crew = _build_crew(mock_llm, discovery_brief="Transform the supply chain operations")
    script_designer_task = crew.tasks[0]
    assert "Transform the supply chain operations" in script_designer_task.description


def test_discovery_interviews_crew_registry_has_script_designer(mock_llm):
    """get_tools_for_agent is called for all four agent roles."""
    with patch(
        "agents.crews.discovery_interviews_crew.get_tools_for_agent", return_value=[]
    ) as mock_reg:
        from agents.crews.discovery_interviews_crew import create_discovery_interviews_crew
        create_discovery_interviews_crew(
            slug="myslug", run_id=5, llm_mode="standard", sector="rail",
            stakeholder_assignments=[], llm=mock_llm,
        )
    called_agents = {c.args[0] for c in mock_reg.call_args_list}
    assert "interview_script_designer" in called_agents
    assert "interview_coordinator" in called_agents
    assert "stakeholder_interviewer" in called_agents
    assert "synthesis_analyst" in called_agents
```

- [ ] **Step 2: Run crew tests to see failures**

```bash
python -m pytest tests/test_discovery_interviews_crew.py -v
```

Expected: `test_discovery_interviews_crew_has_four_agents`, `test_discovery_interviews_crew_has_four_tasks`, `test_discovery_interviews_crew_injects_discovery_brief`, `test_discovery_interviews_crew_registry_has_script_designer` fail.

- [ ] **Step 3: Rewrite discovery_interviews_crew.py**

Replace entire `agents/crews/discovery_interviews_crew.py`:

```python
# agents/crews/discovery_interviews_crew.py
"""Discovery Interviews crew — Script Designer → Coordinator → Interviewer → Synthesis Analyst."""
from crewai import Crew, Process, LLM
from agents.llm import get_pam_llm
from agents.tools.registry import get_tools_for_agent
from agents.discovery.interview_script_designer import (
    create_interview_script_designer,
    create_interview_script_designer_task,
)
from agents.discovery.interview_coordinator import (
    create_interview_coordinator,
    create_interview_coordinator_task,
)
from agents.discovery.stakeholder_interviewer import (
    create_stakeholder_interviewer,
    create_stakeholder_interviewer_task,
)
from agents.discovery.synthesis_analyst import (
    create_synthesis_analyst,
    create_synthesis_analyst_task,
)


def _format_assignments(stakeholder_assignments: list[dict]) -> str:
    """Format a list of assignment dicts into a human-readable block."""
    if not stakeholder_assignments:
        return "(No stakeholder assignments provided)"
    lines = []
    for a in stakeholder_assignments:
        stakeholder_id = a.get("stakeholder_id", "?")
        name = a.get("name", "Unknown")
        job_title = a.get("job_title", "")
        level = a.get("level", "")
        node_label = a.get("node_label", "")
        line = f"- [id:{stakeholder_id}] {name}"
        if job_title:
            line += f" ({job_title})"
        if level and node_label:
            line += f" → {level}: {node_label}"
        lines.append(line)
    return "\n".join(lines)


def create_discovery_interviews_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    stakeholder_assignments: list[dict],
    discovery_brief: str = "",
    llm: LLM | None = None,
    hitl_tool=None,
) -> Crew:
    """Create a sequential 4-agent crew: Script Designer → Coordinator → Interviewer → Analyst."""
    if llm is None:
        llm = get_pam_llm()

    assignments_str = _format_assignments(stakeholder_assignments)

    def _tools(agent_name: str):
        return get_tools_for_agent(agent_name, slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool)

    script_designer = create_interview_script_designer(slug=slug, llm=llm, tools=_tools("interview_script_designer"))
    coordinator = create_interview_coordinator(slug=slug, llm=llm, tools=_tools("interview_coordinator"))
    interviewer = create_stakeholder_interviewer(slug=slug, llm=llm, tools=_tools("stakeholder_interviewer"))
    analyst = create_synthesis_analyst(slug=slug, llm=llm, tools=_tools("synthesis_analyst"))

    t0 = create_interview_script_designer_task(
        agent=script_designer,
        stakeholder_assignments=assignments_str,
        discovery_brief=discovery_brief,
    )
    t1 = create_interview_coordinator_task(agent=coordinator, stakeholder_assignments=assignments_str)
    t1.context = [t0]
    t2 = create_stakeholder_interviewer_task(agent=interviewer, context_tasks=[t1])
    t3 = create_synthesis_analyst_task(agent=analyst, context_tasks=[t2])

    return Crew(
        agents=[script_designer, coordinator, interviewer, analyst],
        tasks=[t0, t1, t2, t3],
        process=Process.sequential,
        verbose=True,
    )
```

- [ ] **Step 4: Add interview_script_designer + InterviewSessionTool to registry**

In `agents/tools/registry.py`, add the import for `InterviewSessionTool` at the top of `get_tools_for_agent` lazy imports block:

```python
    from agents.tools.interview_session_tool import InterviewSessionTool
```

Then add to `tool_map`:

```python
        "interview_script_designer": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
```

And update `"interview_coordinator"` and `"stakeholder_interviewer"` entries to include `InterviewSessionTool`:

```python
        "interview_coordinator": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
            InterviewSessionTool(slug=slug, orchestration_run_id=run_id),
        ],
        "stakeholder_interviewer": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
            InterviewSessionTool(slug=slug, orchestration_run_id=run_id),
        ],
```

- [ ] **Step 5: Update run_service.py to pass discovery_brief**

In `api/services/run_service.py`, find the `create_discovery_interviews_crew` call (inside the `discovery_interviews` branch):

```python
        from agents.crews.discovery_interviews_crew import create_discovery_interviews_crew
        crew = create_discovery_interviews_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            stakeholder_assignments=stakeholder_assignments,
        )
```

Replace with:

```python
        from agents.crews.discovery_interviews_crew import create_discovery_interviews_crew
        discovery_brief = config.get("discovery_brief", "")
        crew = create_discovery_interviews_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            stakeholder_assignments=stakeholder_assignments,
            discovery_brief=discovery_brief,
        )
```

- [ ] **Step 6: Run all crew + registry tests**

```bash
python -m pytest tests/test_discovery_interviews_crew.py tests/test_discovery_interviews_agents.py -v
```

Expected: all pass.

- [ ] **Step 7: Run full test suite**

```bash
python -m pytest --tb=short -q
```

Expected: all previously passing tests still pass; new tests pass.

- [ ] **Step 8: Commit**

```bash
git add agents/crews/discovery_interviews_crew.py agents/tools/registry.py api/services/run_service.py tests/test_discovery_interviews_crew.py
git commit -m "feat(sp10f): 4-agent crew factory; registry adds interview_script_designer + InterviewSessionTool; run_service passes discovery_brief"
```

---

## Task 6: API settings, env, and interview service layer

**Files:**
- Modify: `api/config.py`
- Modify: `.env.example`
- Create: `api/services/interview_service.py`
- Create: `tests/test_interview_service.py` (service tests)

- [ ] **Step 1: Write failing service tests**

Create `tests/test_interview_service.py`:

```python
# tests/test_interview_service.py
"""Tests for interview service functions and API endpoints."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Service: _find_session_db ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_session_db_returns_none_for_unknown_token(tmp_path):
    """Returns None when token not found in any project DB."""
    from api.services.interview_service import _find_session_db
    with patch("api.services.interview_service.get_settings") as ms:
        ms.return_value.database_dir = str(tmp_path)
        result = await _find_session_db("nonexistent-token")
    assert result is None


# ── Service: complete_session ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_complete_session_writes_transcript(tmp_path):
    """complete_session calls complete_interview_session DB helper."""
    from api.services.interview_service import complete_session
    mock_complete = AsyncMock()
    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    with patch("api.services.interview_service._find_session_db", new=AsyncMock(return_value=("myslug", {"id": 1}))), \
         patch("api.services.interview_service.get_connection", return_value=mock_conn), \
         patch("api.services.interview_service.complete_interview_session", mock_complete):
        await complete_session("tok-abc", [{"question": "Q1", "answer": "A1"}])
    mock_complete.assert_called_once()
    call_kwargs = mock_complete.call_args
    assert "tok-abc" in str(call_kwargs)


# ── Endpoint tests ────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """FastAPI test client with interviews router."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from api.routers.interviews import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_get_interview_session_unknown_token_returns_404(client):
    with patch("api.routers.interviews.get_session_with_script", new=AsyncMock(return_value=None)):
        response = client.get("/interviews/unknown-token")
    assert response.status_code == 404


def test_patch_interview_status_unknown_token_returns_404(client):
    with patch("api.routers.interviews.update_session_status", new=AsyncMock(return_value=False)):
        response = client.patch("/interviews/unknown-token/status", json={"status": "active"})
    assert response.status_code == 404


def test_patch_interview_complete_unknown_token_returns_404(client):
    with patch("api.routers.interviews.complete_session", new=AsyncMock(side_effect=ValueError("not found"))):
        response = client.patch("/interviews/unknown-token/complete", json={"qa_pairs": []})
    assert response.status_code == 404
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_interview_service.py -v 2>&1 | head -30
```

Expected: ImportError — `interview_service` module does not exist.

- [ ] **Step 3: Add ElevenLabs and Deepgram keys to api/config.py**

In `api/config.py`, add to the `Settings` class:

```python
    elevenlabs_api_key: Optional[str] = None
    deepgram_api_key: Optional[str] = None
```

- [ ] **Step 4: Add keys to .env.example**

In `.env.example`, append:

```
ELEVENLABS_API_KEY=
DEEPGRAM_API_KEY=
```

- [ ] **Step 5: Create api/services/interview_service.py**

```python
# api/services/interview_service.py
"""Service functions for the public voice interview API."""
import json
from pathlib import Path
from typing import Any
import aiosqlite
import httpx
from anthropic import Anthropic
from api.config import get_settings
from api.database import (
    get_connection,
    fetch_interview_session,
    update_interview_session_status,
    complete_interview_session,
)


async def _find_session_db(session_token: str) -> tuple[str, dict] | None:
    """Scan all project DBs to find the session by token.

    Returns (slug, session_row) or None if not found.
    """
    settings = get_settings()
    db_dir = Path(settings.database_dir)
    if not db_dir.exists():
        return None
    for db_file in db_dir.glob("*.db"):
        slug = db_file.stem
        try:
            async with get_connection(slug) as conn:
                row = await fetch_interview_session(conn, session_token)
                if row is not None:
                    return slug, row
        except Exception:
            continue
    return None


async def get_session_with_script(session_token: str) -> dict | None:
    """Load session metadata and its node's interview script.

    Returns combined dict with session fields + 'script' key, or None if not found.
    """
    found = await _find_session_db(session_token)
    if not found:
        return None
    slug, session_row = found

    # Load interview_scripts from project outputs dir
    settings = get_settings()
    scripts_path = Path(settings.projects_dir) / slug / "outputs" / "interview_scripts.json"
    if not scripts_path.exists():
        return None

    try:
        scripts = json.loads(scripts_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    node_label = session_row["node_label"]
    script = scripts.get(node_label)
    if not script:
        return None

    return {**dict(session_row), "script": script, "slug": slug}


async def generate_deepgram_token() -> str | None:
    """Issue a short-lived Deepgram streaming token via the Deepgram API.

    Returns the token string or None if API key not configured.
    """
    settings = get_settings()
    if not settings.deepgram_api_key:
        return None
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.deepgram.com/v1/auth/grant",
            headers={"Authorization": f"Token {settings.deepgram_api_key}"},
            json={"ttl_seconds": 3600},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json().get("key")


async def speak(text: str, voice_id: str) -> bytes:
    """Call ElevenLabs TTS API and return audio bytes (MP3).

    Raises httpx.HTTPStatusError on API failure.
    """
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY not configured")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": settings.elevenlabs_api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.content


async def elaboration_press(
    question_text: str,
    response_text: str,
    probing_instructions: str,
    stakeholder_name: str,
) -> str:
    """Generate a polite elaboration press via a single LLM call.

    Returns the press text (one or two sentences).
    """
    client = Anthropic()
    prompt = (
        f"You are a polite but insistent interviewer conducting a discovery interview. "
        f"The participant ({stakeholder_name}) has given an insufficient or evasive answer. "
        f"Probing guidance: {probing_instructions}\n\n"
        f"Question asked: {question_text}\n"
        f"Participant's answer: {response_text}\n\n"
        f"Generate one natural follow-up question (maximum 2 sentences) that presses for "
        f"elaboration without being confrontational. Return only the follow-up question text, "
        f"no preamble."
    )
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


async def update_session_status(session_token: str, status: str) -> bool:
    """Set the status of a session. Returns False if session not found."""
    found = await _find_session_db(session_token)
    if not found:
        return False
    slug, _ = found
    async with get_connection(slug) as conn:
        await update_interview_session_status(conn, session_token, status)
    return True


async def complete_session(session_token: str, qa_pairs: list[dict]) -> None:
    """Write transcript and mark session completed. Raises ValueError if not found."""
    found = await _find_session_db(session_token)
    if not found:
        raise ValueError(f"Session not found: {session_token}")
    slug, _ = found
    transcript_json = json.dumps(qa_pairs)
    async with get_connection(slug) as conn:
        await complete_interview_session(conn, session_token, transcript_json)
```

- [ ] **Step 6: Run service tests**

```bash
python -m pytest tests/test_interview_service.py::test_find_session_db_returns_none_for_unknown_token tests/test_interview_service.py::test_complete_session_writes_transcript -v
```

Expected: pass (router tests will fail until Task 7).

- [ ] **Step 7: Commit**

```bash
git add api/config.py .env.example api/services/interview_service.py tests/test_interview_service.py
git commit -m "feat(sp10f): add interview service layer (session lookup, TTS, Deepgram token, elaboration press)"
```

---

## Task 7: API router + main.py registration

**Files:**
- Create: `api/routers/interviews.py`
- Modify: `api/main.py`

- [ ] **Step 1: Create interviews router**

Create `api/routers/interviews.py`:

```python
# api/routers/interviews.py
"""Public voice interview endpoints — no authentication required.

Session tokens (UUID4) serve as single-use access credentials.
"""
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from api.services.interview_service import (
    get_session_with_script,
    generate_deepgram_token,
    speak,
    elaboration_press,
    update_session_status,
    complete_session,
)

router = APIRouter(prefix="/interviews", tags=["interviews"])


class StatusBody(BaseModel):
    status: str


class CompleteBody(BaseModel):
    qa_pairs: list[dict]


class ElaborationBody(BaseModel):
    question_text: str
    response_text: str
    probing_instructions: str
    stakeholder_name: str = "the participant"


class SpeakBody(BaseModel):
    text: str
    voice_id: str


@router.get("/{session_token}")
async def get_interview_session(session_token: str):
    """Load session metadata and script for the given token."""
    data = await get_session_with_script(session_token)
    if data is None:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return data


@router.get("/{session_token}/deepgram-token")
async def get_deepgram_token(session_token: str):
    """Issue a short-lived Deepgram streaming token."""
    token = await generate_deepgram_token()
    if token is None:
        raise HTTPException(status_code=503, detail="Deepgram API key not configured")
    return {"token": token}


@router.post("/{session_token}/speak")
async def speak_text(session_token: str, body: SpeakBody):
    """Proxy text to ElevenLabs TTS and return audio bytes."""
    try:
        audio = await speak(body.text, body.voice_id)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS error: {e}")
    return Response(content=audio, media_type="audio/mpeg")


@router.post("/{session_token}/elaboration-press")
async def get_elaboration_press(session_token: str, body: ElaborationBody):
    """Generate a dynamic elaboration press question via LLM."""
    press = await elaboration_press(
        question_text=body.question_text,
        response_text=body.response_text,
        probing_instructions=body.probing_instructions,
        stakeholder_name=body.stakeholder_name,
    )
    return {"press_text": press}


@router.patch("/{session_token}/status")
async def update_status(session_token: str, body: StatusBody):
    """Update session status (e.g., set to 'active' on first interaction)."""
    updated = await update_session_status(session_token, body.status)
    if not updated:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return {"ok": True}


@router.patch("/{session_token}/complete")
async def complete_interview(session_token: str, body: CompleteBody):
    """Write transcript and mark session completed."""
    try:
        await complete_session(session_token, body.qa_pairs)
    except ValueError:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return {"ok": True}
```

- [ ] **Step 2: Register the router in api/main.py**

In `api/main.py`, add the import:

```python
from api.routers import interviews as interviews_router
```

And add the include:

```python
app.include_router(interviews_router.router)
```

- [ ] **Step 3: Run all interview service tests including endpoint tests**

```bash
python -m pytest tests/test_interview_service.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 4: Run full suite**

```bash
python -m pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/routers/interviews.py api/main.py
git commit -m "feat(sp10f): add /interviews public router (6 endpoints) and register in main.py"
```

---

## Task 8: TypeScript types + voiceLocale + VoiceInterview page + route

**Files:**
- Modify: `ui/src/types.ts`
- Create: `ui/src/utils/voiceLocale.ts`
- Create: `ui/src/pages/VoiceInterview.tsx`
- Modify: `ui/src/router.tsx`

- [ ] **Step 1: Add new TypeScript types to ui/src/types.ts**

Append to the end of `ui/src/types.ts`:

```typescript
export interface VoiceConfig {
  language: string
  country_code: string
  elevenlabs_voice_id: string
}

export interface InterviewQuestion {
  id: string
  text: string
  follow_up_count: number
  probing_instructions: string
  follow_up_branches: string[]
  evasion_signals: string[]
}

export interface InterviewSection {
  title: string
  questions: InterviewQuestion[]
}

export interface InterviewScript {
  node_label: string
  level: string
  research_brief: string
  study_objectives: string[]
  welcome_message: string
  closing_message: string
  sections: InterviewSection[]
}

export interface InterviewSession {
  id: number
  session_token: string
  stakeholder_id: number
  node_label: string
  status: 'pending' | 'active' | 'completed' | 'abandoned'
  script: InterviewScript
  voice_config: VoiceConfig
}

export interface QAPair {
  question: string
  answer: string
}
```

- [ ] **Step 2: Create voiceLocale.ts**

Create `ui/src/utils/voiceLocale.ts`:

```typescript
// ui/src/utils/voiceLocale.ts
// Maps {language, country_code} → ElevenLabs voice ID.
// Replace voice IDs with actual IDs from your ElevenLabs account.

const VOICE_LOCALE_MAP: Record<string, string> = {
  'en_GB': 'pNInz6obpgDQGcFmaJgB',
  'en_US': 'EXAVITQu4vr4xnSDxMaL',
  'en_AU': 'AZnzlk1XvdvUeBnXmlld',
  'en_NZ': 'pNInz6obpgDQGcFmaJgB', // falls back to en-GB; replace with actual
  'en_CA': 'EXAVITQu4vr4xnSDxMaL', // falls back to en-US; replace with actual
  'fr_FR': 'ThT5KcBeYPX3keUQqHPh',
  'de_DE': 'flq6f7yk4E4fJM5XTYuZ',
  'es_ES': 'GBv7mTt0atIp3Br8iCZE',
}

const FALLBACK_VOICE_ID = 'pNInz6obpgDQGcFmaJgB'

export function resolveVoiceId(language: string, countryCode: string): string {
  const key = `${language}_${countryCode}`
  return VOICE_LOCALE_MAP[key] ?? FALLBACK_VOICE_ID
}

export default VOICE_LOCALE_MAP
```

- [ ] **Step 3: Create VoiceInterview.tsx**

Create `ui/src/pages/VoiceInterview.tsx`:

```tsx
// ui/src/pages/VoiceInterview.tsx
// Public voice interview page — no authentication required.
// Stakeholders reach this page via a unique link containing their session token.

import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import type { InterviewSession, InterviewQuestion, QAPair } from '../types'

type Phase = 'loading' | 'ready' | 'interviewing' | 'done' | 'error'

const BASE = import.meta.env.VITE_API_URL ?? ''

async function apiGet(path: string) {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

async function apiPatch(path: string, body: unknown) {
  const r = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

async function apiPost(path: string, body: unknown) {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

async function speakText(sessionToken: string, text: string, voiceId: string): Promise<void> {
  const r = await fetch(`${BASE}/interviews/${sessionToken}/speak`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice_id: voiceId }),
  })
  if (!r.ok) return // Fail silently — don't block interview for TTS errors
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  await new Promise<void>((resolve) => {
    const audio = new Audio(url)
    audio.onended = () => resolve()
    audio.onerror = () => resolve() // Continue even if playback fails
    audio.play().catch(() => resolve())
  })
}

function isEvasive(answer: string, evasionSignals: string[]): boolean {
  const lower = answer.toLowerCase()
  return evasionSignals.some((signal) => lower.includes(signal.toLowerCase()))
}

function isThin(answer: string): boolean {
  return answer.trim().split(/\s+/).length < 20
}

export default function VoiceInterview() {
  const { sessionToken } = useParams<{ sessionToken: string }>()
  const [phase, setPhase] = useState<Phase>('loading')
  const [session, setSession] = useState<InterviewSession | null>(null)
  const [currentText, setCurrentText] = useState<string>('Loading your interview...')
  const [isListening, setIsListening] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string>('')
  const qaPairsRef = useRef<QAPair[]>([])
  const recognitionRef = useRef<SpeechRecognition | null>(null)

  useEffect(() => {
    if (!sessionToken) return
    apiGet(`/interviews/${sessionToken}`)
      .then((data: InterviewSession) => {
        setSession(data)
        setPhase('ready')
        setCurrentText(`Welcome! Your interview is ready. Click "Start Interview" to begin.`)
      })
      .catch(() => {
        setPhase('error')
        setErrorMsg('Interview session not found. Please check your link.')
      })
  }, [sessionToken])

  async function recordAnswer(): Promise<string> {
    return new Promise((resolve) => {
      const SpeechRecognitionAPI =
        (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
      if (!SpeechRecognitionAPI) {
        // Fallback: prompt text input if speech not available
        const answer = window.prompt('Please type your answer:') ?? ''
        resolve(answer)
        return
      }
      const recognition = new SpeechRecognitionAPI()
      recognitionRef.current = recognition
      recognition.lang = session?.script ? 'en-GB' : 'en-US'
      recognition.interimResults = false
      recognition.maxAlternatives = 1
      setIsListening(true)
      recognition.start()
      recognition.onresult = (event: SpeechRecognitionEvent) => {
        const transcript = event.results[0][0].transcript
        setIsListening(false)
        resolve(transcript)
      }
      recognition.onerror = () => {
        setIsListening(false)
        resolve('')
      }
      recognition.onend = () => {
        setIsListening(false)
      }
    })
  }

  async function runInterview() {
    if (!session || !sessionToken) return
    const { script, voice_config } = session
    const voiceId = voice_config.elevenlabs_voice_id

    // Mark active
    await apiPatch(`/interviews/${sessionToken}/status`, { status: 'active' })

    // Welcome message
    setCurrentText(script.welcome_message)
    await speakText(sessionToken, script.welcome_message, voiceId)

    // Iterate sections and questions
    for (const section of script.sections) {
      for (const question of section.questions) {
        await conductQuestion(sessionToken, question, voiceId)
      }
    }

    // Closing message
    setCurrentText(script.closing_message)
    await speakText(sessionToken, script.closing_message, voiceId)

    // Submit transcript
    await apiPatch(`/interviews/${sessionToken}/complete`, { qa_pairs: qaPairsRef.current })
    setPhase('done')
    setCurrentText('Thank you for completing your interview!')
  }

  async function conductQuestion(
    sessionToken: string,
    question: InterviewQuestion,
    voiceId: string,
  ) {
    if (!session) return

    // Ask main question
    setCurrentText(question.text)
    await speakText(sessionToken, question.text, voiceId)
    const mainAnswer = await recordAnswer()
    qaPairsRef.current.push({ question: question.text, answer: mainAnswer })

    // Check answer quality
    let followUpAnswer = ''
    if (isThin(mainAnswer) || isEvasive(mainAnswer, question.evasion_signals)) {
      // Dynamic elaboration press
      try {
        const { press_text } = await apiPost(`/interviews/${sessionToken}/elaboration-press`, {
          question_text: question.text,
          response_text: mainAnswer,
          probing_instructions: question.probing_instructions,
          stakeholder_name: session.script.node_label,
        })
        setCurrentText(press_text)
        await speakText(sessionToken, press_text, voiceId)
        followUpAnswer = await recordAnswer()
        qaPairsRef.current.push({ question: press_text, answer: followUpAnswer })
      } catch {
        // If elaboration press fails, continue with scripted follow-up
      }
    }

    // Scripted follow-up branches (up to follow_up_count)
    const branchesToAsk = Math.min(question.follow_up_count, question.follow_up_branches.length)
    for (let i = 0; i < branchesToAsk; i++) {
      const branch = question.follow_up_branches[i]
      setCurrentText(branch)
      await speakText(sessionToken, branch, voiceId)
      const branchAnswer = await recordAnswer()
      qaPairsRef.current.push({ question: branch, answer: branchAnswer })
    }
  }

  if (phase === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-gray-500">Loading your interview...</p>
      </div>
    )
  }

  if (phase === 'error') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-gray-800 mb-2">Interview Not Found</h1>
          <p className="text-gray-500">{errorMsg}</p>
        </div>
      </div>
    )
  }

  if (phase === 'done') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center max-w-md">
          <h1 className="text-3xl font-semibold text-teal-700 mb-4">Thank You</h1>
          <p className="text-gray-600">
            Your responses have been recorded. Thank you for contributing to this engagement.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 px-4">
      <div className="bg-white rounded-2xl shadow-md p-8 max-w-2xl w-full">
        {session && (
          <p className="text-sm text-gray-400 mb-4 uppercase tracking-wide">
            {session.script.node_label}
          </p>
        )}
        <p className="text-xl text-gray-800 leading-relaxed mb-6">{currentText}</p>
        {isListening && (
          <div className="flex items-center gap-2 text-teal-600 mb-4">
            <span className="w-3 h-3 rounded-full bg-teal-500 animate-pulse" />
            <span className="text-sm">Listening...</span>
          </div>
        )}
        {phase === 'ready' && (
          <button
            onClick={() => {
              setPhase('interviewing')
              runInterview()
            }}
            className="w-full bg-teal-600 hover:bg-teal-700 text-white font-semibold py-3 px-6 rounded-xl transition-colors"
          >
            Start Interview
          </button>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Add public route to router.tsx**

In `ui/src/router.tsx`, add the import:

```typescript
import VoiceInterview from './pages/VoiceInterview'
```

In the `createBrowserRouter` array, add a **top-level** public route (before the protected `/` route):

```typescript
  {
    path: '/interview/:sessionToken',
    element: <VoiceInterview />,
  },
```

The full router array should look like:

```typescript
export const router = createBrowserRouter([
  {
    path: '/login',
    element: <Login />,
  },
  {
    path: '/interview/:sessionToken',
    element: <VoiceInterview />,
  },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    children: [
      // ... existing children unchanged
    ],
  },
])
```

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add ui/src/types.ts ui/src/utils/voiceLocale.ts ui/src/pages/VoiceInterview.tsx ui/src/router.tsx
git commit -m "feat(sp10f): add VoiceInterview page, voiceLocale utility, new TS types, public route"
```

---

## Task 9: Final verification

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest --tb=short -q
```

Expected: all tests pass. Note the count increase vs SP10d baseline (307 tests).

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /Users/pboagents/Documents/agentpool1/ui && npx tsc --noEmit
```

Expected: no type errors.

- [ ] **Step 3: Verify all new files exist**

```bash
ls agents/discovery/interview_script_designer.py \
   agents/tools/interview_session_tool.py \
   api/routers/interviews.py \
   api/services/interview_service.py \
   ui/src/pages/VoiceInterview.tsx \
   ui/src/utils/voiceLocale.ts \
   tests/test_interview_script_designer.py \
   tests/test_interview_session_tool.py \
   tests/test_interview_service.py
```

Expected: all 9 files listed without error.

- [ ] **Step 4: Final commit with summary**

```bash
git add -u
git commit -m "feat(sp10f): complete Interview Script Designer + Voice Interviews implementation"
```
