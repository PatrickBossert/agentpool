"""The tool that writes the tree records what the validator found, and still writes it.

tests/test_tree_validator.py proves the validator. This proves the tool calling it acts on
the result - the distinction this project keeps getting wrong, where check_write was tested
and the tool calling it was not.

Warn and record, never refuse: a refusal would block the run and lose the work, which is
exactly what happened when DeriveRegistryTool refused a label change and the registry stuck
at v5 for two days while the tree moved on.
"""
import json
import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, fetch_validation_warnings
from agents.tools._db import current_output_path


@pytest_asyncio.fixture
async def tool_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "warner-test"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id, outputs
    get_settings.cache_clear()


ROOTLESS = [{"id": "1", "label": "Property", "level": "L1", "children": []}]
ROOTED = [{"id": "0", "label": "GS-UK", "level": "L0", "children": [
    {"id": "1", "label": "Property", "level": "L1", "children": []}]}]


def _write_tree(slug, tree, run_id=7):
    from agents.tools.sqlite_state import SQLiteStateTool
    return SQLiteStateTool(slug=slug, agent_name="value_chain_mapper", run_id=run_id)._run(
        operation="write", key="value_chain_tree",
        agent_name="value_chain_mapper", value=json.dumps(tree))


@pytest.mark.asyncio
async def test_a_rootless_tree_is_written_and_warned_about(tool_project):
    slug, project_id, outputs = tool_project
    result = _write_tree(slug, ROOTLESS)

    assert not result.startswith("Error"), result
    resolved = current_output_path(slug, "value_chain_tree")
    assert resolved is not None, "the write must land despite the warning"
    assert json.loads(resolved.read_text()) == ROOTLESS

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert [r["code"] for r in rows] == ["missing_l0"]
    assert rows[0]["source"] == "value_chain_tree"
    assert rows[0]["run_id"] == 7


@pytest.mark.asyncio
async def test_a_rooted_tree_records_nothing(tool_project):
    slug, project_id, _ = tool_project
    _write_tree(slug, ROOTED)
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert rows == []


@pytest.mark.asyncio
async def test_a_substantive_relabel_is_warned_about(tool_project):
    """The live £350M case: an id that meant one thing now means another."""
    slug, project_id, outputs = tool_project
    (outputs / "value_chain_registry_v1.json").write_text(json.dumps({"activities": [
        {"id": "0", "label": "GS-UK", "level": "L0", "active": True},
        {"id": "1", "label": "Financial Control (£350M)", "level": "L1", "active": True},
    ]}))
    async with get_connection(slug) as conn:
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            pid = (await cur.fetchone())[0]
        await conn.execute(
            "INSERT INTO agent_outputs"
            " (project_id, agent_name, output_type, file_path, version, is_current)"
            " VALUES (?,?,?,?,1,1)",
            (pid, "value_chain_mapper", "value_chain_registry",
             str(outputs / "value_chain_registry_v1.json")))
        await conn.commit()

    _write_tree(slug, [{"id": "0", "label": "GS-UK", "level": "L0", "children": [
        {"id": "1", "label": "Financial Control (350M)", "level": "L1"}]}])

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert [r["code"] for r in rows] == ["id_redefined"]
    assert rows[0]["subject"] == "1"


@pytest.mark.asyncio
async def test_a_typographic_relabel_is_not_warned_about(tool_project):
    """Alex regenerates every label each run; an en dash becoming a hyphen is not news."""
    slug, project_id, outputs = tool_project
    (outputs / "value_chain_registry_v1.json").write_text(json.dumps({"activities": [
        {"id": "0", "label": "GS-UK", "level": "L0", "active": True},
        {"id": "1", "label": "Phases 0–7", "level": "L1", "active": True},
    ]}))
    async with get_connection(slug) as conn:
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            pid = (await cur.fetchone())[0]
        await conn.execute(
            "INSERT INTO agent_outputs"
            " (project_id, agent_name, output_type, file_path, version, is_current)"
            " VALUES (?,?,?,?,1,1)",
            (pid, "value_chain_mapper", "value_chain_registry",
             str(outputs / "value_chain_registry_v1.json")))
        await conn.commit()

    _write_tree(slug, [{"id": "0", "label": "GS-UK", "level": "L0", "children": [
        {"id": "1", "label": "Phases 0-7", "level": "L1"}]}])

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert rows == [], [r["detail"] for r in rows]


@pytest.mark.asyncio
async def test_a_recorder_failure_cannot_lose_the_write(tool_project, monkeypatch):
    """Bookkeeping must never turn a successful write into a failed one."""
    slug, _, _ = tool_project
    import agents.tools.sqlite_state as st

    def boom(*a, **k):
        raise RuntimeError("database is on fire")
    monkeypatch.setattr(st, "record_validation_warnings_sync", boom)

    result = _write_tree(slug, ROOTLESS)
    assert not result.startswith("Error"), result
    assert current_output_path(slug, "value_chain_tree") is not None
