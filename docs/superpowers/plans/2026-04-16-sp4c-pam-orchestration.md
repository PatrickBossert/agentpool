# SP4c — PAM Orchestration + n8n/Slack Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire PAM (Programme Architecture Manager) as a CrewAI agent that runs all five specialist crews sequentially, notify Slack after each via n8n, and expose a `POST /projects/{slug}/orchestrate` REST endpoint.

**Architecture:** PAM is a single CrewAI agent (Opus 4.6) with 5 sequential tasks; each task calls `RunCrewTool` (blocks until the sub-crew finishes) then `SlackNotifyTool` (fire-and-forget to n8n webhook). A new `/orchestrate` endpoint fires PAM asynchronously and returns 202. `build_and_run_crew()` is extracted from `run_service.py` so both the REST per-crew path and `RunCrewTool` share the same crew-building logic.

**Tech Stack:** Python 3.13, FastAPI, CrewAI (Crew/Agent/Task/Process), aiosqlite, httpx (sync), n8n (self-hosted Docker), Slack app w/ slash commands

---

## File layout

| Action | Path |
|--------|------|
| Modify | `api/database.py` |
| Modify | `api/services/run_service.py` |
| Create | `agents/tools/slack_notify.py` |
| Create | `agents/tools/run_crew.py` |
| Create | `agents/pam/__init__.py` |
| Create | `agents/pam/pam_agent.py` |
| Modify | `agents/tools/registry.py` |
| Create | `agents/crews/pam_crew.py` |
| Create | `api/services/orchestration_service.py` |
| Create | `api/routers/orchestrate.py` |
| Modify | `api/main.py` |
| Create | `workflows/agentpool-notifications.json` |
| Create | `workflows/slack-run-command.json` |
| Create | `tests/test_slack_notify_tool.py` |
| Create | `tests/test_run_crew_tool.py` |
| Create | `tests/test_pam_crew.py` |
| Create | `tests/test_orchestration_service.py` |

**Test runner** (use throughout):
```bash
cd /Users/pboagents/Documents/agentpool1
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest --ignore=tests/integration -q
```

Starting count: **145 tests passing**.

---

## Task 1: DB migration — `orchestration_runs` table + 3 helpers

**Files:**
- Modify: `api/database.py`
- Test: `tests/test_database.py` (append)

### Step 1.1: Write the failing tests

Append to `tests/test_database.py`:

```python
@pytest.mark.asyncio
async def test_init_db_creates_orchestration_runs_table(db):
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) as cur:
        tables = {row[0] async for row in cur}
    assert "orchestration_runs" in tables


@pytest.mark.asyncio
async def test_insert_and_fetch_orchestration_run(db):
    from api.database import insert_project, insert_orchestration_run, fetch_orchestration_run
    await insert_project(db, slug="orch-test", llm_mode="standard", sector="rail", config_json='{}')
    project_row = await db.execute("SELECT id FROM projects WHERE slug='orch-test'")
    project_id = (await project_row.fetchone())[0]

    run_id = await insert_orchestration_run(db, project_id=project_id)
    assert isinstance(run_id, int)

    run = await fetch_orchestration_run(db, run_id=run_id)
    assert run is not None
    assert run["status"] == "running"
    assert run["project_id"] == project_id


@pytest.mark.asyncio
async def test_update_orchestration_run_status_sets_completed_at(db):
    from api.database import insert_project, insert_orchestration_run, update_orchestration_run_status, fetch_orchestration_run
    await insert_project(db, slug="orch-update-test", llm_mode="standard", sector="rail", config_json='{}')
    project_row = await db.execute("SELECT id FROM projects WHERE slug='orch-update-test'")
    project_id = (await project_row.fetchone())[0]

    run_id = await insert_orchestration_run(db, project_id=project_id)
    await update_orchestration_run_status(db, run_id=run_id, status="completed")

    run = await fetch_orchestration_run(db, run_id=run_id)
    assert run["status"] == "completed"
    assert run["completed_at"] is not None


@pytest.mark.asyncio
async def test_update_orchestration_run_status_running_leaves_completed_at_null(db):
    from api.database import insert_project, insert_orchestration_run, update_orchestration_run_status, fetch_orchestration_run
    await insert_project(db, slug="orch-null-test", llm_mode="standard", sector="rail", config_json='{}')
    project_row = await db.execute("SELECT id FROM projects WHERE slug='orch-null-test'")
    project_id = (await project_row.fetchone())[0]

    run_id = await insert_orchestration_run(db, project_id=project_id)
    # status stays 'running' — completed_at should remain NULL
    run = await fetch_orchestration_run(db, run_id=run_id)
    assert run["completed_at"] is None
```

### Step 1.2: Run tests to confirm they fail

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_database.py -q --ignore=tests/integration
```

Expected: 4 failures — `insert_orchestration_run`, `fetch_orchestration_run`, `update_orchestration_run_status` not yet defined.

### Step 1.3: Add the table + 3 helpers to `api/database.py`

**In `init_db()`**, add the new table to the existing `executescript` block (after the `client_documents` table, before the closing `"""`):

```python
        CREATE TABLE IF NOT EXISTS orchestration_runs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id),
            status       TEXT NOT NULL DEFAULT 'running',
            started_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME
        );
```

**Append these three helpers** at the end of `api/database.py` (before the system DB section, after `update_crew_run_status`):

```python
async def insert_orchestration_run(conn: aiosqlite.Connection, *, project_id: int) -> int:
    cur = await conn.execute(
        "INSERT INTO orchestration_runs (project_id, status) VALUES (?, 'running')",
        (project_id,),
    )
    await conn.commit()
    return cur.lastrowid


async def update_orchestration_run_status(
    conn: aiosqlite.Connection, *, run_id: int, status: str
) -> None:
    if status in ("completed", "failed"):
        await conn.execute(
            "UPDATE orchestration_runs SET status=?, completed_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, run_id),
        )
    else:
        await conn.execute(
            "UPDATE orchestration_runs SET status=? WHERE id=?",
            (status, run_id),
        )
    await conn.commit()


async def fetch_orchestration_run(conn: aiosqlite.Connection, *, run_id: int) -> dict | None:
    async with conn.execute(
        "SELECT * FROM orchestration_runs WHERE id=?", (run_id,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None
```

### Step 1.4: Run tests to confirm they pass

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_database.py -q --ignore=tests/integration
```

Expected: all database tests pass (was N, now N+4).

### Step 1.5: Run full suite

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest --ignore=tests/integration -q
```

Expected: 149 tests passing, 0 failures.

### Step 1.6: Commit

```bash
git add api/database.py tests/test_database.py
git commit -m "feat(db): add orchestration_runs table and helpers (SP4c)"
```

---

## Task 2: `run_service.py` refactor — extract `build_and_run_crew`

**Files:**
- Modify: `api/services/run_service.py`

The goal: extract a public async helper `build_and_run_crew(slug, crew_name, run_id)` that `dispatch_crew` and `RunCrewTool` can both call. The five private `_run_*` functions collapse into this helper.

> **No new test file needed** — the existing `test_run_api.py` tests all mock `dispatch_crew` and will continue to pass. We add two targeted unit tests to verify the new helper dispatches correctly and raises on unknown crew names.

### Step 2.1: Write the failing tests

Create `tests/test_run_service.py`:

```python
# tests/test_run_service.py
"""Unit tests for the build_and_run_crew shared helper."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def fake_config(tmp_path, monkeypatch):
    """Write a minimal config.yaml and point PROJECTS_DIR at tmp_path."""
    import api.config as cfg
    cfg.get_settings.cache_clear()
    import yaml, os
    project_dir = tmp_path / "acme"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(
        yaml.dump({
            "llm_mode": "standard",
            "sector": "transport",
            "value_stream_labels": ["Ops"],
            "stakeholder_groups": ["IT"],
            "roadmap_time_axis": "quarters",
        })
    )
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    cfg.get_settings.cache_clear()
    yield tmp_path
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_build_and_run_crew_dispatches_discovery(fake_config):
    mock_crew = MagicMock()
    mock_crew.kickoff_async = AsyncMock(return_value="done")
    with patch("agents.crews.discovery_crew.create_discovery_crew", return_value=mock_crew) as mock_factory:
        from api.services.run_service import build_and_run_crew
        result = await build_and_run_crew("acme", "discovery", run_id=1)
    mock_factory.assert_called_once()
    mock_crew.kickoff_async.assert_awaited_once()
    assert result == "done"


@pytest.mark.asyncio
async def test_build_and_run_crew_raises_on_unknown_crew(fake_config):
    from api.services.run_service import build_and_run_crew
    with pytest.raises(ValueError, match="Unknown crew"):
        await build_and_run_crew("acme", "nonexistent_crew", run_id=1)
```

### Step 2.2: Run tests to confirm they fail

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_run_service.py -q
```

Expected: 2 failures — `build_and_run_crew` does not exist yet.

### Step 2.3: Rewrite `api/services/run_service.py`

```python
# api/services/run_service.py
"""
Crew dispatch and build helpers.

build_and_run_crew() is a shared helper used by both dispatch_crew (REST path)
and RunCrewTool (PAM orchestration path).
dispatch_crew() is called by the run router via asyncio.create_task().
"""
import json
from pathlib import Path
from typing import Any
from api.config import get_settings, load_project_config
from api.database import get_connection, update_crew_run_status
from api.routers.ws import push_log


async def build_and_run_crew(slug: str, crew_name: str, run_id: int) -> Any:
    """Build the named crew, run it, and return the result. Does not update DB status."""
    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    llm_mode = config.get("llm_mode", "standard")
    sector = config.get("sector", "")

    if crew_name == "discovery":
        from agents.crews.discovery_crew import create_discovery_crew
        crew = create_discovery_crew(slug=slug, run_id=run_id, llm_mode=llm_mode, sector=sector)

    elif crew_name == "value_design":
        from agents.crews.value_design_crew import create_value_design_crew
        crew = create_value_design_crew(slug=slug, run_id=run_id, llm_mode=llm_mode, sector=sector)

    elif crew_name == "architecture":
        from agents.crews.architecture_crew import create_architecture_crew
        crew = create_architecture_crew(slug=slug, run_id=run_id, llm_mode=llm_mode, sector=sector)

    elif crew_name == "delivery":
        value_stream_labels = config.get("value_stream_labels", [])
        stakeholder_groups = config.get("stakeholder_groups", [])
        roadmap_time_axis = config.get("roadmap_time_axis", "quarters")
        if not value_stream_labels:
            raise ValueError("Project config is missing 'value_stream_labels' — required for Delivery crew")
        if not stakeholder_groups:
            raise ValueError("Project config is missing 'stakeholder_groups' — required for Delivery crew")
        from agents.crews.delivery_crew import create_delivery_crew
        crew = create_delivery_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            value_stream_labels=value_stream_labels,
            stakeholder_groups=stakeholder_groups,
            roadmap_time_axis=roadmap_time_axis,
        )

    elif crew_name == "business_plan":
        from agents.crews.business_plan_crew import create_business_plan_crew
        crew = create_business_plan_crew(slug=slug, run_id=run_id, llm_mode=llm_mode, sector=sector)

    else:
        raise ValueError(f"Unknown crew: '{crew_name}'")

    return await crew.kickoff_async()


async def dispatch_crew(slug: str, crew_name: str, run_id: int) -> None:
    """Entry point called by asyncio.create_task. Runs the named crew and updates status."""
    try:
        await push_log(slug, json.dumps({"type": "crew_started", "crew": crew_name, "run_id": run_id}))
        await build_and_run_crew(slug, crew_name, run_id)
        async with get_connection(slug) as conn:
            await update_crew_run_status(conn, run_id=run_id, status="completed")
        await push_log(slug, json.dumps({"type": "crew_completed", "crew": crew_name, "run_id": run_id}))
    except Exception as e:
        try:
            async with get_connection(slug) as conn:
                await update_crew_run_status(
                    conn,
                    run_id=run_id,
                    status="failed",
                    result_json=json.dumps({"error": str(e)}),
                )
        except Exception:
            pass  # Best-effort — don't mask the original exception
        await push_log(slug, json.dumps({"type": "crew_failed", "crew": crew_name, "error": str(e)}))
        raise
```

### Step 2.4: Run the new tests

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_run_service.py -q
```

Expected: 2 passing.

### Step 2.5: Run full suite — confirm no regressions

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest --ignore=tests/integration -q
```

Expected: 151 tests passing, 0 failures.

### Step 2.6: Commit

```bash
git add api/services/run_service.py tests/test_run_service.py
git commit -m "refactor(run_service): extract build_and_run_crew shared helper (SP4c)"
```

---

## Task 3: `SlackNotifyTool`

**Files:**
- Create: `agents/tools/slack_notify.py`
- Create: `tests/test_slack_notify_tool.py`

### Step 3.1: Write the failing tests

Create `tests/test_slack_notify_tool.py`:

```python
# tests/test_slack_notify_tool.py
"""Unit tests for SlackNotifyTool."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


@pytest.fixture(autouse=True)
def clear_settings():
    import api.config as cfg
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _make_tool(slug="acme"):
    from agents.tools.slack_notify import SlackNotifyTool
    return SlackNotifyTool(slug=slug)


def test_run_posts_to_webhook(tmp_path, monkeypatch):
    """_run posts a JSON body with event_type='crew_notification' to the n8n webhook."""
    import yaml
    project_dir = tmp_path / "acme"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(yaml.dump({"slack_channel": "#eng"}))

    import api.config as cfg
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("N8N_WEBHOOK_URL", "http://n8n.local/webhook/agentpool")
    cfg.get_settings.cache_clear()

    mock_resp = MagicMock()
    with patch("httpx.post", return_value=mock_resp) as mock_post:
        tool = _make_tool()
        result = tool._run("hello world")

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    payload = kwargs["json"]
    assert payload["event_type"] == "crew_notification"
    assert payload["project_slug"] == "acme"
    assert payload["slack_channel"] == "#eng"
    assert payload["message"] == "hello world"
    assert result == "notification sent"


def test_run_skipped_when_no_webhook(tmp_path, monkeypatch):
    """When N8N_WEBHOOK_URL is not set, _run returns a skip message without raising."""
    import api.config as cfg
    monkeypatch.delenv("N8N_WEBHOOK_URL", raising=False)
    cfg.get_settings.cache_clear()

    with patch("httpx.post") as mock_post:
        tool = _make_tool()
        result = tool._run("msg")

    mock_post.assert_not_called()
    assert "skipped" in result


def test_run_skipped_on_http_error(tmp_path, monkeypatch):
    """If httpx.post raises, _run returns a failure string rather than propagating."""
    import yaml, httpx
    project_dir = tmp_path / "acme"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(yaml.dump({"slack_channel": ""}))

    import api.config as cfg
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("N8N_WEBHOOK_URL", "http://n8n.local/webhook/agentpool")
    cfg.get_settings.cache_clear()

    with patch("httpx.post", side_effect=httpx.ConnectError("timeout")):
        tool = _make_tool()
        result = tool._run("msg")

    assert "non-fatal" in result or "failed" in result


def test_run_includes_slug_in_payload(tmp_path, monkeypatch):
    """The project_slug field in the payload matches the tool's slug."""
    import yaml
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(yaml.dump({"slack_channel": ""}))

    import api.config as cfg
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("N8N_WEBHOOK_URL", "http://n8n.local/webhook/agentpool")
    cfg.get_settings.cache_clear()

    captured = {}
    def fake_post(url, *, json, timeout):
        captured.update(json)
        return MagicMock()

    with patch("httpx.post", side_effect=fake_post):
        tool = _make_tool(slug="myproject")
        tool._run("test")

    assert captured["project_slug"] == "myproject"
```

### Step 3.2: Run tests to confirm they fail

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_slack_notify_tool.py -q
```

Expected: `ModuleNotFoundError: agents.tools.slack_notify`.

### Step 3.3: Implement `agents/tools/slack_notify.py`

```python
# agents/tools/slack_notify.py
"""SlackNotifyTool — fire-and-forget Slack notification via n8n webhook."""
from crewai.tools import BaseTool


class SlackNotifyTool(BaseTool):
    name: str = "SlackNotifyTool"
    description: str = "Send a notification message to the project's Slack channel via n8n."
    slug: str

    def _run(self, message: str) -> str:
        from api.config import get_settings, load_project_config
        from pathlib import Path
        settings = get_settings()
        if not settings.n8n_webhook_url:
            return "notification skipped (no webhook configured)"
        try:
            config = load_project_config(Path(settings.projects_dir) / self.slug)
            slack_channel = config.get("slack_channel", "")
            import httpx
            httpx.post(
                settings.n8n_webhook_url,
                json={
                    "event_type": "crew_notification",
                    "project_slug": self.slug,
                    "slack_channel": slack_channel,
                    "message": message,
                },
                timeout=5.0,
            )
            return "notification sent"
        except Exception as e:
            return f"notification failed (non-fatal): {e}"
```

### Step 3.4: Run tests

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_slack_notify_tool.py -q
```

Expected: 4 passing.

### Step 3.5: Run full suite

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest --ignore=tests/integration -q
```

Expected: 155 tests passing, 0 failures.

### Step 3.6: Commit

```bash
git add agents/tools/slack_notify.py tests/test_slack_notify_tool.py
git commit -m "feat(tools): add SlackNotifyTool for n8n notifications (SP4c)"
```

---

## Task 4: `RunCrewTool`

**Files:**
- Create: `agents/tools/run_crew.py`
- Create: `tests/test_run_crew_tool.py`

### Step 4.1: Write the failing tests

Create `tests/test_run_crew_tool.py`:

```python
# tests/test_run_crew_tool.py
"""Unit tests for RunCrewTool."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


def _make_tool(slug="acme", orchestration_run_id=99):
    from agents.tools.run_crew import RunCrewTool
    return RunCrewTool(slug=slug, orchestration_run_id=orchestration_run_id)


@pytest.mark.asyncio
async def test_arun_creates_crew_run_record(monkeypatch, tmp_path):
    """insert_crew_run is called before kickoff_async."""
    mock_project = {"id": 1}
    mock_run_id = 42

    with patch("api.database.get_connection") as mock_ctx, \
         patch("api.database.fetch_project", new_callable=AsyncMock, return_value=mock_project), \
         patch("api.database.insert_crew_run", new_callable=AsyncMock, return_value=mock_run_id), \
         patch("api.database.update_crew_run_status", new_callable=AsyncMock), \
         patch("api.services.run_service.build_and_run_crew", new_callable=AsyncMock, return_value="ok"):

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_conn

        tool = _make_tool()
        await tool._arun("discovery")

    from api.database import insert_crew_run
    insert_crew_run.assert_awaited()


@pytest.mark.asyncio
async def test_arun_marks_completed_on_success():
    """On success, update_crew_run_status is called with status='completed'."""
    mock_project = {"id": 1}

    with patch("api.database.get_connection") as mock_ctx, \
         patch("api.database.fetch_project", new_callable=AsyncMock, return_value=mock_project), \
         patch("api.database.insert_crew_run", new_callable=AsyncMock, return_value=10), \
         patch("api.database.update_crew_run_status", new_callable=AsyncMock) as mock_update, \
         patch("api.services.run_service.build_and_run_crew", new_callable=AsyncMock, return_value="done"):

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_conn

        tool = _make_tool()
        result = await tool._arun("discovery")

    calls = mock_update.call_args_list
    statuses = [c.kwargs.get("status") for c in calls]
    assert "completed" in statuses
    assert result == "done"


@pytest.mark.asyncio
async def test_arun_marks_failed_on_exception():
    """On exception, update_crew_run_status is called with status='failed' and error string returned."""
    mock_project = {"id": 1}

    with patch("api.database.get_connection") as mock_ctx, \
         patch("api.database.fetch_project", new_callable=AsyncMock, return_value=mock_project), \
         patch("api.database.insert_crew_run", new_callable=AsyncMock, return_value=10), \
         patch("api.database.update_crew_run_status", new_callable=AsyncMock) as mock_update, \
         patch("api.services.run_service.build_and_run_crew", new_callable=AsyncMock, side_effect=RuntimeError("boom")):

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_conn

        tool = _make_tool()
        result = await tool._arun("discovery")

    calls = mock_update.call_args_list
    statuses = [c.kwargs.get("status") for c in calls]
    assert "failed" in statuses
    assert "Error running discovery" in result
    assert "boom" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("crew_name", [
    "discovery", "value_design", "architecture", "delivery", "business_plan"
])
async def test_arun_calls_build_and_run_crew_with_correct_name(crew_name):
    """build_and_run_crew is called with the crew_name argument passed to _arun."""
    mock_project = {"id": 1}

    with patch("api.database.get_connection") as mock_ctx, \
         patch("api.database.fetch_project", new_callable=AsyncMock, return_value=mock_project), \
         patch("api.database.insert_crew_run", new_callable=AsyncMock, return_value=1), \
         patch("api.database.update_crew_run_status", new_callable=AsyncMock), \
         patch("api.services.run_service.build_and_run_crew", new_callable=AsyncMock, return_value="ok") as mock_build:

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_conn

        tool = _make_tool()
        await tool._arun(crew_name)

    first_call_args = mock_build.call_args
    assert first_call_args.args[1] == crew_name


@pytest.mark.asyncio
async def test_arun_returns_result_string():
    """The string result of build_and_run_crew is returned."""
    mock_project = {"id": 1}

    with patch("api.database.get_connection") as mock_ctx, \
         patch("api.database.fetch_project", new_callable=AsyncMock, return_value=mock_project), \
         patch("api.database.insert_crew_run", new_callable=AsyncMock, return_value=1), \
         patch("api.database.update_crew_run_status", new_callable=AsyncMock), \
         patch("api.services.run_service.build_and_run_crew", new_callable=AsyncMock, return_value="my result"):

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_conn

        tool = _make_tool()
        result = await tool._arun("business_plan")

    assert result == "my result"
```

### Step 4.2: Run tests to confirm they fail

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_run_crew_tool.py -q
```

Expected: `ModuleNotFoundError: agents.tools.run_crew`.

### Step 4.3: Implement `agents/tools/run_crew.py`

```python
# agents/tools/run_crew.py
"""RunCrewTool — runs a named sub-crew and waits for it to complete."""
from crewai.tools import BaseTool


class RunCrewTool(BaseTool):
    name: str = "RunCrewTool"
    description: str = (
        "Run a named crew for the current project and wait for it to complete. "
        "crew_name must be one of: discovery, value_design, architecture, delivery, business_plan"
    )
    slug: str
    orchestration_run_id: int

    async def _arun(self, crew_name: str) -> str:
        from api.database import (
            get_connection,
            fetch_project,
            insert_crew_run,
            update_crew_run_status,
        )
        from api.services.run_service import build_and_run_crew

        async with get_connection(self.slug) as conn:
            project = await fetch_project(conn, slug=self.slug)
            run_id = await insert_crew_run(
                conn, project_id=project["id"], crew_name=crew_name, status="running"
            )
        try:
            result = await build_and_run_crew(self.slug, crew_name, run_id)
            async with get_connection(self.slug) as conn:
                await update_crew_run_status(conn, run_id=run_id, status="completed")
            return str(result)
        except Exception as e:
            async with get_connection(self.slug) as conn:
                await update_crew_run_status(conn, run_id=run_id, status="failed")
            return f"Error running {crew_name}: {e}"
```

### Step 4.4: Run the new tests

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_run_crew_tool.py -q
```

Expected: 9 passing (5 parametrized + 4 single).

### Step 4.5: Run full suite

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest --ignore=tests/integration -q
```

Expected: 164 tests passing, 0 failures.

### Step 4.6: Commit

```bash
git add agents/tools/run_crew.py tests/test_run_crew_tool.py
git commit -m "feat(tools): add RunCrewTool for PAM sub-crew dispatch (SP4c)"
```

---

## Task 5: PAM agent + tasks

**Files:**
- Replace: `agents/pam.py` → `agents/pam/__init__.py` (move constants)
- Create: `agents/pam/pam_agent.py`

> No standalone tests for this task — the agent/task factories are tested via the PAM crew tests in Task 7. Task 5 is purely structural.
>
> **Important:** Python cannot have both `agents/pam.py` (module) and `agents/pam/` (package) with the same name. The existing `agents/pam.py` holds constants (`PAM_ROLE`, `PAM_GOAL`, etc.) that are not yet imported anywhere in the codebase. Task 5 migrates them into the package `__init__.py` and deletes the old module file.

### Step 5.1: Create `agents/pam/__init__.py` with constants (replaces `agents/pam.py`)

```python
# agents/pam/__init__.py
"""PAM (Programme Architecture Manager) configuration constants."""

PAM_NAME = "PAM"
PAM_MODEL = "anthropic/claude-opus-4-6"
PAM_ROLE = "Programme Architecture Manager"
PAM_GOAL = (
    "Orchestrate the end-to-end delivery of AI-assisted strategy consulting, "
    "coordinating specialist crews and ensuring quality outputs at each stage."
)
```

### Step 5.1b: Delete `agents/pam.py`

```bash
git rm agents/pam.py
```

(This removes the old module file and stages the deletion.)

### Step 5.2: Create `agents/pam/pam_agent.py`

The task descriptions must include the tool names literally (e.g. `"RunCrewTool"`, `"SlackNotifyTool"`) so CrewAI's agent knows to call them. Each task takes `context_tasks` so prior results flow forward.

```python
# agents/pam/pam_agent.py
"""PAM agent factory and task factories for the orchestration crew."""
from crewai import Agent, Task, LLM
from agents.pam import PAM_ROLE, PAM_GOAL


def create_pam_agent(slug: str, llm: LLM, tools: list) -> Agent:
    return Agent(
        role=PAM_ROLE,
        goal=PAM_GOAL,
        backstory=(
            "You are PAM, the Programme Architecture Manager for AgentPool. "
            "You orchestrate specialist crews in sequence to deliver end-to-end "
            "AI strategy consulting. You use RunCrewTool to run each crew and "
            "SlackNotifyTool to post progress updates."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
    )


def create_run_discovery_task(agent: Agent, slug: str) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='discovery' to run the Discovery crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Then use SlackNotifyTool to send: "
            f"'✓ Discovery complete for {slug}. Starting Value Design.'"
        ),
        expected_output="Confirmation that discovery crew completed and Slack notified.",
        agent=agent,
    )


def create_run_value_design_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='value_design' to run the Value Design crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Then use SlackNotifyTool to send: "
            f"'✓ Value Design complete for {slug}. Starting Architecture.'"
        ),
        expected_output="Confirmation that value_design crew completed and Slack notified.",
        agent=agent,
        context=context_tasks,
    )


def create_run_architecture_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='architecture' to run the Architecture crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Then use SlackNotifyTool to send: "
            f"'✓ Architecture complete for {slug}. Starting Delivery Planning.'"
        ),
        expected_output="Confirmation that architecture crew completed and Slack notified.",
        agent=agent,
        context=context_tasks,
    )


def create_run_delivery_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='delivery' to run the Delivery Planning crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Then use SlackNotifyTool to send: "
            f"'✓ Delivery Planning complete for {slug}. Starting Business Plan.'"
        ),
        expected_output="Confirmation that delivery crew completed and Slack notified.",
        agent=agent,
        context=context_tasks,
    )


def create_run_business_plan_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='business_plan' to run the Business Plan crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Then use SlackNotifyTool to send: "
            f"'✓ {slug} pipeline complete. All outputs ready.'"
        ),
        expected_output="Confirmation that business_plan crew completed and full pipeline notified.",
        agent=agent,
        context=context_tasks,
    )
```

### Step 5.3: Verify the imports work

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/python -c "from agents.pam.pam_agent import create_pam_agent; print('ok')"
```

Expected: `ok`

### Step 5.4: Run full suite — confirm no regressions

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest --ignore=tests/integration -q
```

Expected: 164 tests passing, 0 failures.

### Step 5.5: Commit

```bash
git add agents/pam/__init__.py agents/pam/pam_agent.py
# agents/pam.py deletion was staged by git rm in Step 5.1b
git commit -m "feat(pam): migrate constants to package, add PAM agent and 5 task factories (SP4c)"
```

---

## Task 6: Registry update — PAM entry

**Files:**
- Modify: `agents/tools/registry.py`

### Step 6.1: No new test needed

The registry change is covered by the PAM crew test in Task 7 (`test_pam_crew_tools_come_from_registry`). However, we can confirm the PAM entry shape by running the existing registry tests after the change.

### Step 6.2: Update the `"pam"` entry in `agents/tools/registry.py`

In `agents/tools/registry.py`, add the two new imports at the top of `get_tools_for_agent` (inside the function, alongside the existing imports):

```python
    from agents.tools.run_crew import RunCrewTool
    from agents.tools.slack_notify import SlackNotifyTool
```

Then replace the `"pam"` entry in `tool_map`:

Old:
```python
        "pam": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
```

New:
```python
        "pam": [
            RunCrewTool(slug=slug, orchestration_run_id=run_id),
            SlackNotifyTool(slug=slug),
            SQLiteStateTool(slug=slug),
        ],
```

> **Why:** PAM doesn't prompt for human input directly — HITL happens within each sub-crew. PAM only needs `RunCrewTool`, `SlackNotifyTool`, and `SQLiteStateTool` (for reading/writing shared state). The `run_id` passed to `get_tools_for_agent("pam", ...)` is the `orchestration_run_id`.

### Step 6.3: Run full suite

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest --ignore=tests/integration -q
```

Expected: 164 tests passing, 0 failures.

### Step 6.4: Commit

```bash
git add agents/tools/registry.py
git commit -m "feat(registry): update PAM entry with RunCrewTool + SlackNotifyTool (SP4c)"
```

---

## Task 7: PAM crew

**Files:**
- Create: `agents/crews/pam_crew.py`
- Create: `tests/test_pam_crew.py`

### Step 7.1: Write the failing tests

Create `tests/test_pam_crew.py`:

```python
# tests/test_pam_crew.py
"""Unit tests for the PAM orchestration crew."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM, Process


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


def _build_crew(mock_llm):
    with patch("agents.crews.pam_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.pam_crew import create_pam_crew
        return create_pam_crew(
            slug="test",
            orchestration_run_id=1,
            llm_mode="standard",
            llm=mock_llm,
        )


def test_pam_crew_has_one_agent(mock_llm):
    crew = _build_crew(mock_llm)
    assert len(crew.agents) == 1


def test_pam_crew_has_five_tasks(mock_llm):
    crew = _build_crew(mock_llm)
    assert len(crew.tasks) == 5


def test_pam_crew_sequential_process(mock_llm):
    crew = _build_crew(mock_llm)
    assert crew.process == Process.sequential


def test_pam_crew_tasks_reference_all_five_crews(mock_llm):
    """Each of the 5 sub-crew names appears somewhere in the task descriptions."""
    crew = _build_crew(mock_llm)
    all_descriptions = " ".join(t.description for t in crew.tasks)
    for crew_name in ("discovery", "value_design", "architecture", "delivery", "business_plan"):
        assert crew_name in all_descriptions, f"'{crew_name}' missing from task descriptions"


def test_pam_crew_tools_come_from_registry(mock_llm):
    """get_tools_for_agent is called with 'pam' and the orchestration_run_id as run_id."""
    with patch("agents.crews.pam_crew.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.pam_crew import create_pam_crew
        create_pam_crew(
            slug="myslug",
            orchestration_run_id=77,
            llm_mode="standard",
            llm=mock_llm,
        )
    assert mock_reg.call_args_list, "get_tools_for_agent was never called"
    call = mock_reg.call_args_list[0]
    assert call.args[0] == "pam"
    assert call.kwargs.get("slug") == "myslug"
    assert call.kwargs.get("run_id") == 77
```

### Step 7.2: Run tests to confirm they fail

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_pam_crew.py -q
```

Expected: `ModuleNotFoundError: agents.crews.pam_crew`.

### Step 7.3: Implement `agents/crews/pam_crew.py`

```python
# agents/crews/pam_crew.py
"""PAM orchestration crew — runs all five sub-crews sequentially."""
from crewai import Crew, Process, LLM
from agents.llm import get_pam_llm
from agents.tools.registry import get_tools_for_agent
from agents.pam.pam_agent import (
    create_pam_agent,
    create_run_discovery_task,
    create_run_value_design_task,
    create_run_architecture_task,
    create_run_delivery_task,
    create_run_business_plan_task,
)


def create_pam_crew(
    slug: str,
    orchestration_run_id: int,
    llm_mode: str,
    llm: LLM | None = None,
) -> Crew:
    """
    Assemble and return the PAM orchestration Crew.

    Args:
        slug: Project slug.
        orchestration_run_id: orchestration_runs.id for this pipeline run.
            Passed as run_id to the tool registry so RunCrewTool has it.
        llm_mode: "standard" | "sensitive" — PAM always uses Opus 4.6 unless
            a test injects a mock LLM.
        llm: Optional LLM override for tests.
    """
    if llm is None:
        llm = get_pam_llm()

    tools = get_tools_for_agent("pam", slug=slug, run_id=orchestration_run_id)

    pam = create_pam_agent(slug=slug, llm=llm, tools=tools)

    t1 = create_run_discovery_task(agent=pam, slug=slug)
    t2 = create_run_value_design_task(agent=pam, slug=slug, context_tasks=[t1])
    t3 = create_run_architecture_task(agent=pam, slug=slug, context_tasks=[t2])
    t4 = create_run_delivery_task(agent=pam, slug=slug, context_tasks=[t3])
    t5 = create_run_business_plan_task(agent=pam, slug=slug, context_tasks=[t4])

    return Crew(
        agents=[pam],
        tasks=[t1, t2, t3, t4, t5],
        process=Process.sequential,
        verbose=True,
    )
```

### Step 7.4: Run the new tests

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_pam_crew.py -q
```

Expected: 5 passing.

### Step 7.5: Run full suite

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest --ignore=tests/integration -q
```

Expected: 169 tests passing, 0 failures.

### Step 7.6: Commit

```bash
git add agents/crews/pam_crew.py tests/test_pam_crew.py
git commit -m "feat(crews): add PAM orchestration crew (SP4c)"
```

---

## Task 8: Orchestration service + endpoint

**Files:**
- Create: `api/services/orchestration_service.py`
- Create: `api/routers/orchestrate.py`
- Modify: `api/main.py`
- Create: `tests/test_orchestration_service.py`

### Step 8.1: Write the failing tests

Create `tests/test_orchestration_service.py`:

```python
# tests/test_orchestration_service.py
"""Unit tests for start_orchestration service and the /orchestrate endpoint."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


PROJECT_PAYLOAD = {
    "client_slug": "orch-api-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Ops"],
    "value_stream_labels": ["Ops"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.mark.asyncio
async def test_start_orchestration_creates_db_record():
    """start_orchestration inserts a row in orchestration_runs and returns an integer id."""
    import aiosqlite
    from pathlib import Path
    import api.config as cfg
    cfg.get_settings.cache_clear()

    with patch("api.services.orchestration_service.run_pam_crew", new_callable=AsyncMock):
        with patch("asyncio.create_task") as mock_task:
            # We need a real DB with a project row
            from api.database import get_connection, insert_project, fetch_project
            async with get_connection("orch-svc-test") as conn:
                await insert_project(
                    conn, slug="orch-svc-test",
                    llm_mode="standard", sector="rail", config_json="{}"
                )

            from api.services.orchestration_service import start_orchestration
            run_id = await start_orchestration("orch-svc-test")

    assert isinstance(run_id, int)
    assert run_id > 0


@pytest.mark.asyncio
async def test_start_orchestration_returns_run_id():
    """The returned int is the primary key of the new orchestration_runs row."""
    with patch("asyncio.create_task"):
        with patch("api.services.orchestration_service.run_pam_crew", new_callable=AsyncMock):
            from api.database import get_connection, insert_project, fetch_orchestration_run
            async with get_connection("orch-return-test") as conn:
                await insert_project(
                    conn, slug="orch-return-test",
                    llm_mode="standard", sector="rail", config_json="{}"
                )

            from api.services.orchestration_service import start_orchestration
            run_id = await start_orchestration("orch-return-test")

    async with get_connection("orch-return-test") as conn:
        row = await fetch_orchestration_run(conn, run_id=run_id)

    assert row is not None
    assert row["id"] == run_id
    assert row["status"] == "running"


@pytest.mark.asyncio
async def test_start_orchestration_fires_background_task():
    """start_orchestration calls asyncio.create_task (fires PAM crew asynchronously)."""
    import asyncio
    with patch("asyncio.create_task") as mock_task, \
         patch("api.services.orchestration_service.run_pam_crew", new_callable=AsyncMock):
        from api.database import get_connection, insert_project
        async with get_connection("orch-bg-test") as conn:
            await insert_project(
                conn, slug="orch-bg-test",
                llm_mode="standard", sector="rail", config_json="{}"
            )

        from api.services.orchestration_service import start_orchestration
        await start_orchestration("orch-bg-test")

    mock_task.assert_called_once()


# ── /orchestrate endpoint ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrate_endpoint_returns_202(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    with patch("api.services.orchestration_service.start_orchestration", new_callable=AsyncMock, return_value=5):
        resp = await client.post("/projects/orch-api-test/orchestrate")
    assert resp.status_code == 202
    data = resp.json()
    assert data["orchestration_run_id"] == 5
    assert data["status"] == "running"


@pytest.mark.asyncio
async def test_orchestrate_endpoint_returns_404_for_unknown_project(client):
    resp = await client.post("/projects/nonexistent/orchestrate")
    assert resp.status_code == 404
```

### Step 8.2: Run tests to confirm they fail

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_orchestration_service.py -q
```

Expected: `ModuleNotFoundError` for `api.services.orchestration_service` and 404 test fails (router not registered).

### Step 8.3: Create `api/services/orchestration_service.py`

```python
# api/services/orchestration_service.py
"""Start and track full-pipeline PAM orchestration runs."""
import asyncio
from pathlib import Path
from api.config import get_settings, load_project_config
from api.database import (
    get_connection,
    fetch_project,
    insert_orchestration_run,
    update_orchestration_run_status,
)


async def start_orchestration(slug: str) -> int:
    """Insert an orchestration_run record and fire PAM crew as a background task.

    Returns the new orchestration_run_id.
    Raises ValueError if the project does not exist.
    """
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise ValueError(f"Project '{slug}' not found")
        orchestration_run_id = await insert_orchestration_run(conn, project_id=project["id"])

    asyncio.create_task(run_pam_crew(slug, orchestration_run_id))
    return orchestration_run_id


async def run_pam_crew(slug: str, orchestration_run_id: int) -> None:
    """Build and run the PAM crew; update status on completion or failure."""
    try:
        settings = get_settings()
        config = load_project_config(Path(settings.projects_dir) / slug)
        from agents.crews.pam_crew import create_pam_crew
        crew = create_pam_crew(
            slug=slug,
            orchestration_run_id=orchestration_run_id,
            llm_mode=config.get("llm_mode", "standard"),
        )
        await crew.kickoff_async()
        async with get_connection(slug) as conn:
            await update_orchestration_run_status(
                conn, run_id=orchestration_run_id, status="completed"
            )
    except Exception:
        async with get_connection(slug) as conn:
            await update_orchestration_run_status(
                conn, run_id=orchestration_run_id, status="failed"
            )
```

### Step 8.4: Create `api/routers/orchestrate.py`

```python
# api/routers/orchestrate.py
"""POST /projects/{slug}/orchestrate — start full PAM pipeline."""
from fastapi import APIRouter, HTTPException
from api.services.orchestration_service import start_orchestration

router = APIRouter(tags=["orchestration"])


@router.post("/projects/{slug}/orchestrate", status_code=202)
async def orchestrate_project(slug: str):
    try:
        orchestration_run_id = await start_orchestration(slug)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"orchestration_run_id": orchestration_run_id, "status": "running"}
```

### Step 8.5: Register the router in `api/main.py`

Add import and `include_router` call. The full updated `api/main.py`:

```python
# api/main.py
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.config import get_settings
from api.routers import projects, run, outputs, ws
from api.routers import auth as auth_router
from api.routers import documents as documents_router
from api.routers import reviews as reviews_router
from api.routers import orchestrate as orchestrate_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path(settings.database_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.projects_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="AgentPool API", version="0.1.0", lifespan=lifespan, favicon_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(run.router)
app.include_router(outputs.router)
app.include_router(ws.router)
app.include_router(auth_router.router)
app.include_router(documents_router.router)
app.include_router(reviews_router.router)
app.include_router(orchestrate_router.router)
```

### Step 8.6: Run the new tests

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_orchestration_service.py -q
```

Expected: 5 passing.

### Step 8.7: Run full suite

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest --ignore=tests/integration -q
```

Expected: 174 tests passing, 0 failures.

### Step 8.8: Commit

```bash
git add api/services/orchestration_service.py api/routers/orchestrate.py api/main.py tests/test_orchestration_service.py
git commit -m "feat(api): add /orchestrate endpoint + orchestration service (SP4c)"
```

---

## Task 9: n8n workflow JSON files

**Files:**
- Create: `workflows/agentpool-notifications.json`
- Create: `workflows/slack-run-command.json`

These are static JSON files imported into n8n. No unit tests — import and manual verification in n8n UI.

### Step 9.1: Create `workflows/` directory and `agentpool-notifications.json`

This workflow handles BOTH `hitl_review` (DM to consultant) and `crew_notification` (channel post) via a Switch node on `event_type`.

```bash
mkdir -p /Users/pboagents/Documents/agentpool1/workflows
```

Create `workflows/agentpool-notifications.json`:

```json
{
  "name": "AgentPool Notifications",
  "nodes": [
    {
      "parameters": {
        "httpMethod": "POST",
        "path": "agentpool",
        "responseMode": "responseNode",
        "options": {}
      },
      "id": "a1b2c3d4-0001-0001-0001-000000000001",
      "name": "Webhook",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [240, 300],
      "webhookId": "agentpool-webhook"
    },
    {
      "parameters": {
        "rules": {
          "rules": [
            {
              "conditions": {
                "options": {"caseSensitive": true, "leftValue": "", "typeValidation": "strict"},
                "conditions": [
                  {
                    "id": "rule-hitl",
                    "leftValue": "={{ $json.event_type }}",
                    "rightValue": "hitl_review",
                    "operator": {"type": "string", "operation": "equals", "name": "filter.operator.equals"}
                  }
                ],
                "combinator": "and"
              },
              "renameOutput": true,
              "outputKey": "hitl_review"
            },
            {
              "conditions": {
                "options": {"caseSensitive": true, "leftValue": "", "typeValidation": "strict"},
                "conditions": [
                  {
                    "id": "rule-notify",
                    "leftValue": "={{ $json.event_type }}",
                    "rightValue": "crew_notification",
                    "operator": {"type": "string", "operation": "equals", "name": "filter.operator.equals"}
                  }
                ],
                "combinator": "and"
              },
              "renameOutput": true,
              "outputKey": "crew_notification"
            }
          ]
        },
        "options": {}
      },
      "id": "a1b2c3d4-0002-0002-0002-000000000002",
      "name": "Switch",
      "type": "n8n-nodes-base.switch",
      "typeVersion": 3,
      "position": [460, 300]
    },
    {
      "parameters": {
        "authentication": "oAuth2",
        "resource": "message",
        "operation": "post",
        "channel": "={{ $json.reviewer_slack_id || $json.project_slug }}",
        "text": "=*Review needed for {{ $json.project_slug }}*\n\n{{ $json.prompt }}\n\n→ {{ $json.review_url }}",
        "otherOptions": {}
      },
      "id": "a1b2c3d4-0003-0003-0003-000000000003",
      "name": "Slack HITL DM",
      "type": "n8n-nodes-base.slack",
      "typeVersion": 2.2,
      "position": [680, 200],
      "credentials": {
        "slackOAuth2Api": {
          "id": "REPLACE_WITH_CREDENTIAL_ID",
          "name": "AgentPool Slack"
        }
      }
    },
    {
      "parameters": {
        "authentication": "oAuth2",
        "resource": "message",
        "operation": "post",
        "channel": "={{ $json.slack_channel }}",
        "text": "={{ $json.message }}",
        "otherOptions": {}
      },
      "id": "a1b2c3d4-0004-0004-0004-000000000004",
      "name": "Slack Channel Notify",
      "type": "n8n-nodes-base.slack",
      "typeVersion": 2.2,
      "position": [680, 400],
      "credentials": {
        "slackOAuth2Api": {
          "id": "REPLACE_WITH_CREDENTIAL_ID",
          "name": "AgentPool Slack"
        }
      }
    },
    {
      "parameters": {
        "respondWith": "json",
        "responseBody": "={\"ok\": true}"
      },
      "id": "a1b2c3d4-0005-0005-0005-000000000005",
      "name": "Respond 200",
      "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1,
      "position": [900, 300]
    }
  ],
  "connections": {
    "Webhook": {
      "main": [
        [{"node": "Switch", "type": "main", "index": 0}]
      ]
    },
    "Switch": {
      "main": [
        [{"node": "Slack HITL DM", "type": "main", "index": 0}],
        [{"node": "Slack Channel Notify", "type": "main", "index": 0}]
      ]
    },
    "Slack HITL DM": {
      "main": [
        [{"node": "Respond 200", "type": "main", "index": 0}]
      ]
    },
    "Slack Channel Notify": {
      "main": [
        [{"node": "Respond 200", "type": "main", "index": 0}]
      ]
    }
  },
  "active": false,
  "settings": {
    "executionOrder": "v1"
  },
  "versionId": "sp4c-v1",
  "meta": {
    "templateCredsSetupCompleted": false
  }
}
```

### Step 9.2: Create `workflows/slack-run-command.json`

This workflow receives the `/run <slug>` Slack slash command and triggers `POST /projects/{slug}/orchestrate`.

```json
{
  "name": "AgentPool Slack Run Command",
  "nodes": [
    {
      "parameters": {
        "triggerOn": "slash_command",
        "command": "/run"
      },
      "id": "b1c2d3e4-0001-0001-0001-000000000001",
      "name": "Slack Trigger",
      "type": "n8n-nodes-base.slackTrigger",
      "typeVersion": 1,
      "position": [240, 300],
      "webhookId": "slack-run-trigger",
      "credentials": {
        "slackOAuth2Api": {
          "id": "REPLACE_WITH_CREDENTIAL_ID",
          "name": "AgentPool Slack"
        }
      }
    },
    {
      "parameters": {
        "method": "POST",
        "url": "=http://host.docker.internal:8000/projects/{{ $json.text.trim() }}/orchestrate",
        "sendHeaders": true,
        "headerParameters": {
          "parameters": [
            {"name": "Content-Type", "value": "application/json"}
          ]
        },
        "sendBody": true,
        "bodyContentType": "json",
        "jsonBody": "{}",
        "options": {}
      },
      "id": "b1c2d3e4-0002-0002-0002-000000000002",
      "name": "HTTP Orchestrate",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [460, 300]
    },
    {
      "parameters": {
        "authentication": "oAuth2",
        "resource": "message",
        "operation": "post",
        "channel": "={{ $('Slack Trigger').item.json.channel_id }}",
        "text": "=⚙ Starting pipeline for *{{ $('Slack Trigger').item.json.text.trim() }}*…",
        "otherOptions": {}
      },
      "id": "b1c2d3e4-0003-0003-0003-000000000003",
      "name": "Slack Confirm",
      "type": "n8n-nodes-base.slack",
      "typeVersion": 2.2,
      "position": [680, 300],
      "credentials": {
        "slackOAuth2Api": {
          "id": "REPLACE_WITH_CREDENTIAL_ID",
          "name": "AgentPool Slack"
        }
      }
    }
  ],
  "connections": {
    "Slack Trigger": {
      "main": [
        [{"node": "HTTP Orchestrate", "type": "main", "index": 0}]
      ]
    },
    "HTTP Orchestrate": {
      "main": [
        [{"node": "Slack Confirm", "type": "main", "index": 0}]
      ]
    }
  },
  "active": false,
  "settings": {
    "executionOrder": "v1"
  },
  "versionId": "sp4c-v1",
  "meta": {
    "templateCredsSetupCompleted": false
  }
}
```

### Step 9.3: Run full suite — confirm still passing

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest --ignore=tests/integration -q
```

Expected: 174 tests passing, 0 failures.

### Step 9.4: Commit

```bash
git add workflows/agentpool-notifications.json workflows/slack-run-command.json
git commit -m "feat(workflows): add n8n workflow JSON files for notifications and slash command (SP4c)"
```

---

## Post-implementation verification

### Final test run

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest --ignore=tests/integration -q
```

Expected: **174 tests passing** (was 145, added 29), 0 failures.

### n8n import steps (manual, one-time)

1. Open n8n UI at `http://localhost:5678`
2. **Import `agentpool-notifications.json`:** Workflows → Import → select file
3. **Import `slack-run-command.json`:** Workflows → Import → select file
4. **Add Slack credential:** Credentials → New → Slack OAuth2 API → paste Bot User OAuth Token
5. **Update credential IDs:** In each workflow, click the Slack nodes and select the "AgentPool Slack" credential from the dropdown (replacing `REPLACE_WITH_CREDENTIAL_ID`)
6. **Activate both workflows**
7. Test: send `POST http://localhost:8000/projects/{slug}/orchestrate` — confirm n8n receives the `crew_notification` events and posts to Slack

---

## Summary

| Task | New tests | Files changed |
|------|-----------|---------------|
| 1. DB migration | 4 | `api/database.py`, `tests/test_database.py` |
| 2. run_service refactor | 2 | `api/services/run_service.py`, `tests/test_run_service.py` |
| 3. SlackNotifyTool | 4 | `agents/tools/slack_notify.py`, `tests/test_slack_notify_tool.py` |
| 4. RunCrewTool | 9 | `agents/tools/run_crew.py`, `tests/test_run_crew_tool.py` |
| 5. PAM agent + tasks | 0 | `agents/pam/__init__.py` (replaces `agents/pam.py`), `agents/pam/pam_agent.py` |
| 6. Registry update | 0 | `agents/tools/registry.py` |
| 7. PAM crew | 5 | `agents/crews/pam_crew.py`, `tests/test_pam_crew.py` |
| 8. Orchestration service + endpoint | 5 | `api/services/orchestration_service.py`, `api/routers/orchestrate.py`, `api/main.py`, `tests/test_orchestration_service.py` |
| 9. n8n workflow JSON files | 0 | `workflows/agentpool-notifications.json`, `workflows/slack-run-command.json` |
| **Total** | **29** | **17 files** |
