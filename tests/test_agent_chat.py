# tests/test_agent_chat.py
"""Tests for POST /projects/{slug}/agent-chat."""
import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock


@pytest_asyncio.fixture
async def chat_project():
    """Seed /tmp/agentpool_test/chatproj.db for agent chat tests."""
    db_path = Path("/tmp/agentpool_test/chatproj.db")
    async with aiosqlite.connect(db_path) as conn:
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
                project_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            );
            CREATE TABLE IF NOT EXISTS crew_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                crew_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                result_json TEXT,
                started_at TEXT,
                finished_at TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS stakeholders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                job_title TEXT NOT NULL DEFAULT '',
                organisation TEXT NOT NULL DEFAULT '',
                stakeholder_groups TEXT DEFAULT '[]',
                project_role TEXT DEFAULT 'recipient',
                value_streams TEXT DEFAULT '[]',
                value_chain_stage TEXT DEFAULT '',
                activity TEXT DEFAULT '',
                disposition TEXT DEFAULT 'neutral',
                location TEXT DEFAULT '',
                country_code TEXT DEFAULT '',
                timezone TEXT DEFAULT '',
                preferred_language TEXT DEFAULT '',
                currency TEXT DEFAULT '',
                email TEXT DEFAULT '',
                slack_handle TEXT DEFAULT '',
                interview_status TEXT,
                interview_invited_at DATETIME,
                interview_completed_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS interview_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                orchestration_run_id INTEGER,
                stakeholder_id INTEGER NOT NULL,
                node_label TEXT NOT NULL,
                session_token TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                voice_config TEXT,
                transcript_json TEXT,
                ratings_json TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("INSERT OR IGNORE INTO projects (slug) VALUES ('chatproj')")
        await conn.execute(
            "INSERT OR IGNORE INTO stakeholders "
            "(project_id, name, job_title, organisation, interview_status) "
            "VALUES (1, 'Alice', 'CFO', 'Acme Ltd', 'completed')"
        )
        await conn.execute(
            "INSERT OR IGNORE INTO stakeholders "
            "(project_id, name, job_title, organisation, interview_status) "
            "VALUES (1, 'Bob', 'COO', 'Acme Ltd', NULL)"
        )
        await conn.execute(
            "INSERT OR IGNORE INTO interview_sessions "
            "(project_id, stakeholder_id, node_label, session_token, status) "
            "VALUES (1, 1, 'Goods-in', 'chat-tok-alpha', 'completed')"
        )
        await conn.execute(
            "INSERT OR IGNORE INTO interview_sessions "
            "(project_id, stakeholder_id, node_label, session_token, status) "
            "VALUES (1, 2, 'Goods-in', 'chat-tok-beta', 'pending')"
        )
        await conn.commit()
    yield
    db_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_agent_chat_unknown_agent_returns_404(client, chat_project):
    resp = await client.post(
        "/projects/chatproj/agent-chat",
        json={"agent_name": "Nonexistent Agent", "message": "hello", "history": []},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_chat_project_not_found_returns_404(client, chat_project):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="hi")]
    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls:
        inst = AsyncMock()
        inst.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = inst
        resp = await client.post(
            "/projects/doesnotexist/agent-chat",
            json={"agent_name": "Roadmap Generator", "message": "hello", "history": []},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_chat_returns_claude_response(client, chat_project):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Bob has not been interviewed yet.")]
    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls:
        inst = AsyncMock()
        inst.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = inst
        resp = await client.post(
            "/projects/chatproj/agent-chat",
            json={
                "agent_name": "Interview Coordinator",
                "message": "Who hasn't been interviewed?",
                "history": [],
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["response"] == "Bob has not been interviewed yet."


@pytest.mark.asyncio
async def test_agent_chat_interview_context_in_system_prompt(client, chat_project):
    """System prompt for interview_sessions agents must include stakeholder + session data."""
    captured: dict = {}

    async def fake_create(**kwargs):
        captured["system"] = kwargs.get("system", "")
        captured["messages"] = kwargs.get("messages", [])
        r = MagicMock()
        r.content = [MagicMock(text="ok")]
        return r

    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls:
        inst = AsyncMock()
        inst.messages.create = fake_create
        mock_cls.return_value = inst
        await client.post(
            "/projects/chatproj/agent-chat",
            json={
                "agent_name": "Interview Coordinator",
                "message": "Status?",
                "history": [],
            },
        )

    assert "Alice" in captured["system"]
    assert "Bob" in captured["system"]
    assert "completed" in captured["system"].lower() or "pending" in captured["system"].lower()


@pytest.mark.asyncio
async def test_agent_chat_passes_history_to_claude(client, chat_project):
    """Conversation history should appear as prior messages to Claude."""
    captured: dict = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages", [])
        r = MagicMock()
        r.content = [MagicMock(text="I remember")]
        return r

    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls:
        inst = AsyncMock()
        inst.messages.create = fake_create
        mock_cls.return_value = inst
        await client.post(
            "/projects/chatproj/agent-chat",
            json={
                "agent_name": "Roadmap Generator",
                "message": "And now?",
                "history": [
                    {"role": "user", "content": "First message"},
                    {"role": "agent", "content": "First reply"},
                ],
            },
        )

    msgs = captured["messages"]
    # First two are history, last is new user message
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "First message"
    assert msgs[1]["role"] == "assistant"   # 'agent' converted to 'assistant'
    assert msgs[1]["content"] == "First reply"
    assert msgs[2]["role"] == "user"
    assert msgs[2]["content"] == "And now?"
