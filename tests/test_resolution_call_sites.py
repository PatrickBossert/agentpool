"""The readers must use the resolver, not the glob.

tests/test_current_output_path.py proves the resolver in isolation. This proves the code
that actually feeds the agents calls it - the distinction behind this project's recurring
failure mode, where check_write was tested and the tool calling it was not.

Every fixture below publishes a v2 the ledger marks current and drops a v9 beside it on
disk. A reader still globbing returns the v9.
"""
import json
import re
import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings
from api.database import get_connection


@pytest_asyncio.fixture
async def shadowed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "callsite-test"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            pid = (await cur.fetchone())[0]

    async def publish(output_type, payload, shadow):
        (outputs / f"{output_type}_v2.json").write_text(json.dumps(payload))
        (outputs / f"{output_type}_v9.json").write_text(json.dumps(shadow))
        async with get_connection(slug) as conn:
            await conn.execute(
                "INSERT INTO agent_outputs"
                " (project_id, agent_name, output_type, file_path, version, is_current)"
                " VALUES (?,?,?,?,2,1)",
                (pid, "a", output_type, str(outputs / f"{output_type}_v2.json")))
            await conn.commit()

    yield slug, outputs, publish
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_registry_reader_uses_the_ledger(shadowed):
    slug, _, publish = shadowed
    await publish("value_chain_registry",
                  {"activities": [{"id": "1", "label": "Current", "level": "L1"}]},
                  {"activities": [{"id": "1", "label": "Stale", "level": "L1"}]})
    from agents.tools.sqlite_state import _current_registry
    assert _current_registry(slug)["activities"][0]["label"] == "Current"


@pytest.mark.asyncio
async def test_the_levers_reader_uses_the_ledger(shadowed):
    slug, _, publish = shadowed
    await publish("value_levers", [{"lever": "Current"}], [{"lever": "Stale"}])
    from agents.tools.sqlite_state import _current_levers
    assert _current_levers(slug)[0]["lever"] == "Current"


@pytest.mark.asyncio
async def test_the_script_registry_reader_uses_the_ledger(shadowed):
    """Adapted from the brief-predating original, which published a shadowed
    interview_script_registry artefact through insert_agent_output_sync and expected
    _current_script_registry to resolve through the file ledger.

    Task 2 of the script-ledger-as-a-table plan
    (.superpowers/sdd/2026-08-11-script-ledger-as-a-table/task-2-brief.md) retired that: the
    guard now reads agents.tools._db.current_script_ledger_sync, which is backed by the
    interview_script_ledger table, not by any file - so there is no glob for a shadow file
    to fool any more, and the file-publishing fixture below has nothing to seed with. What
    still matters, and is what this test now proves, is that the reader is live against the
    table (register_scripts_sync is the only writer left) rather than a cached snapshot.
    """
    slug, _, _ = shadowed
    from agents.tools._db import register_scripts_sync
    from agents.tools.sqlite_state import _current_script_registry

    register_scripts_sync(
        slug, {"SC-001": {"node_id": "1.2", "node_label": "Current"}}, 1, "tester"
    )
    assert [e["id"] for e in _current_script_registry(slug)["scripts"]] == ["SC-001"]


@pytest.mark.asyncio
async def test_merge_on_write_merges_into_the_ledgers_version(shadowed):
    """Merging into a shadowed version would resurrect superseded scripts."""
    slug, _, publish = shadowed
    await publish("interview_scripts", {"SC-001": {"node_label": "current"}},
                  {"SC-999": {"node_label": "stale"}})
    from agents.tools.sqlite_state import _merge_with_current
    merged = _merge_with_current(
        "interview_scripts", {"SC-002": {"node_label": "new"}}, slug)
    assert sorted(merged) == ["SC-001", "SC-002"], f"merged the shadow: {sorted(merged)}"


@pytest.mark.asyncio
async def test_the_tool_read_path_uses_the_ledger(shadowed):
    slug, _, publish = shadowed
    await publish("value_chain_tree", [{"id": "0", "label": "Current"}],
                  [{"id": "0", "label": "Stale"}])
    from agents.tools.sqlite_state import SQLiteStateTool
    out = SQLiteStateTool(slug=slug, agent_name="value_chain_mapper")._run(
        operation="read", key="value_chain_tree", agent_name="value_chain_mapper")
    assert json.loads(out)[0]["label"] == "Current"


@pytest.mark.asyncio
async def test_the_derive_tool_reads_the_ledgers_registry(shadowed):
    slug, _, publish = shadowed
    await publish("value_chain_registry",
                  {"activities": [{"id": "1", "label": "Current", "level": "L1"}]},
                  {"activities": [{"id": "1", "label": "Stale", "level": "L1"}]})
    from agents.tools.derive_registry import _latest_registry
    path = _latest_registry(slug)
    assert json.loads(path.read_text())["activities"][0]["label"] == "Current"


@pytest.mark.asyncio
async def test_the_interview_scripts_endpoint_uses_the_ledger(shadowed, client):
    slug, _, publish = shadowed
    await publish(
        "interview_scripts",
        {"SC-001": {"node_label": "Current", "level": "L0", "node_id": "0",
                    "sections": []}},
        {"SC-999": {"node_label": "Stale", "level": "L0", "node_id": "0",
                    "sections": []}})
    r = await client.get(f"/projects/{slug}/interview-scripts")
    assert r.status_code == 200
    assert sorted(r.json()) == ["SC-001"]


def test_no_reader_still_globs_the_disk():
    """A grep, because a call site added later is how this regresses."""
    for f in ("agents/tools/sqlite_state.py", "agents/tools/derive_registry.py",
              "api/routers/projects.py", "api/services/interview_answer_service.py"):
        src = Path(f).read_text()
        calls = re.findall(r"latest_output_path\s*\(", src)
        assert not calls, f"{f} still calls latest_output_path {len(calls)} time(s)"
