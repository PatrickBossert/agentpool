import json
import pytest
from agents.tools.sqlite_state import SQLiteStateTool


@pytest.fixture
def script_project(tmp_path, monkeypatch):
    """An isolated project with the registry a scripts write validates against."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from api.config import get_settings
    get_settings.cache_clear()
    slug = "reg-test"
    (tmp_path / "db").mkdir(parents=True, exist_ok=True)
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    import asyncio
    from api.database import get_connection

    async def _init():
        async with get_connection(slug) as conn:
            await conn.execute("INSERT INTO projects (slug) VALUES (?)", (slug,))
            await conn.commit()
    asyncio.run(_init())

    registry = {"activities": [
        {"id": "1.2", "label": "Works Programming", "level": "L2", "active": True},
        {"id": "1.3", "label": "Pipeline Design", "level": "L2", "active": True},
        {"id": "2.7", "label": "Somewhere Else", "level": "L2", "active": True},
    ]}
    (outputs / "value_chain_registry.json").write_text(json.dumps(registry))
    from agents.tools._db import insert_agent_output_sync
    insert_agent_output_sync(slug=slug, agent_name="value_chain_mapper",
                             output_type="value_chain_registry",
                             file_path=str(outputs / "value_chain_registry.json"))
    yield slug
    get_settings.cache_clear()


def _script(script_id, node_id, label):
    # The brief's helper omitted script_id and relationship, both required by
    # validate_scripts (api/services/interview_script_model.py:94) - without them every
    # write in this file is refused before it reaches registration at all. Shape matched
    # to the working convention used across the other script-write tests, e.g.
    # tests/test_coverage_validation.py's test_an_incomplete_write_records_a_warning.
    return {
        "script_id": script_id, "node_id": node_id, "node_label": label,
        "level": "L2", "relationship": "internal", "sections": [],
    }


def test_a_scripts_write_registers_its_new_ids(script_project):
    """Driven through SQLiteStateTool's real write, not by calling the upsert. A
    registration path the write does not reach is the exact defect this work exists to
    remove - run 32 wrote 41 scripts and registered none of them."""
    slug = script_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)
    out = tool._run(operation="write", key="interview_scripts",
                    agent_name="interaction_designer",
                    value=json.dumps({"SC-001": _script("SC-001", "1.2", "Works Programming")}))
    assert out.startswith("Written to"), out

    from agents.tools._db import current_script_ledger_sync
    ledger = current_script_ledger_sync(slug)
    assert [(e["id"], e["node_id"]) for e in ledger["scripts"]] == [("SC-001", "1.2")]


def test_a_second_batch_registers_only_the_new_ids(script_project):
    """Run 32's shape: batches land one after another and each must leave every script
    written so far registered, because the run can stop at any point."""
    slug = script_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)
    tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
              value=json.dumps({"SC-001": _script("SC-001", "1.2", "Works Programming")}))
    tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
              value=json.dumps({"SC-002": _script("SC-002", "1.3", "Pipeline Design")}))

    from agents.tools._db import current_script_ledger_sync
    ids = {e["id"]: e["node_id"] for e in current_script_ledger_sync(slug)["scripts"]}
    assert ids == {"SC-001": "1.2", "SC-002": "1.3"}


def test_registration_never_moves_an_id_that_is_already_registered(script_project):
    """The property most likely to be destroyed by making registration automatic, and the
    one whose loss would be invisible: the write would succeed and the ledger would agree
    with it. Append-only is what keeps the succession guard meaningful."""
    slug = script_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)
    tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
              value=json.dumps({"SC-001": _script("SC-001", "1.2", "Works Programming")}))
    out = tool._run(operation="write", key="interview_scripts",
                    agent_name="interaction_designer",
                    value=json.dumps({"SC-001": _script("SC-001", "2.7", "Somewhere Else")}))

    assert out.startswith("Error:"), f"a moved id must be refused, got: {out}"
    from agents.tools._db import current_script_ledger_sync
    ids = {e["id"]: e["node_id"] for e in current_script_ledger_sync(slug)["scripts"]}
    assert ids == {"SC-001": "1.2"}, "the ledger must not have followed the moved id"
