# tests/test_blocked_writes.py
"""A refused write is a finding, not just a rejection."""
import json

import pytest
import pytest_asyncio

from api.database import fetch_blocked_writes, get_connection, insert_project

SLUG = "blocked-writes-test"


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_refused_write_leaves_a_row(project):
    from agents.tools.sqlite_state import SQLiteStateTool

    tool = SQLiteStateTool(slug=SLUG, agent_name="interaction_designer", run_id=7)
    tool._run(
        operation="write", key="value_chain_registry",
        agent_name="interaction_designer", value=json.dumps({"activities": []}),
    )

    async with get_connection(SLUG) as conn:
        rows = await fetch_blocked_writes(conn)

    assert len(rows) == 1
    assert rows[0]["agent_name"] == "interaction_designer"
    assert rows[0]["key"] == "value_chain_registry"
    assert rows[0]["owner"] == "value_chain_mapper"
    assert rows[0]["run_id"] == 7


@pytest.mark.asyncio
async def test_the_agent_is_still_told(project):
    """Recording instead of telling would leave the agent looping on a write it cannot see
    failing."""
    from agents.tools.sqlite_state import SQLiteStateTool

    tool = SQLiteStateTool(slug=SLUG, agent_name="interaction_designer", run_id=7)
    result = tool._run(
        operation="write", key="value_chain_registry",
        agent_name="interaction_designer", value=json.dumps({}),
    )

    assert "value_chain_mapper" in result


@pytest.mark.asyncio
async def test_an_unowned_key_records_no_owner_rather_than_a_wrong_one(project):
    from agents.tools.sqlite_state import SQLiteStateTool

    tool = SQLiteStateTool(slug=SLUG, agent_name="interaction_designer", run_id=7)
    tool._run(
        operation="write", key="interview_scripts_batch1",
        agent_name="interaction_designer", value=json.dumps({}),
    )

    async with get_connection(SLUG) as conn:
        rows = await fetch_blocked_writes(conn)
    assert rows[0]["owner"] is None


@pytest.mark.asyncio
async def test_recording_failure_never_costs_the_refusal(project, monkeypatch):
    """The refusal is the load-bearing half. If bookkeeping fails, the write must still be
    refused rather than let through."""
    import agents.tools.sqlite_state as mod
    from agents.tools.sqlite_state import SQLiteStateTool

    def boom(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(mod, "record_blocked_write_sync", boom)

    tool = SQLiteStateTool(slug=SLUG, agent_name="interaction_designer", run_id=7)
    result = tool._run(
        operation="write", key="value_chain_registry",
        agent_name="interaction_designer", value=json.dumps({}),
    )

    assert "Written to" not in result
