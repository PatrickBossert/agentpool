# tests/test_script_registry_retired.py
import json
from agents.tools.sqlite_state import SQLiteStateTool
from tests.test_script_ledger_registration import script_project  # noqa: F401


def test_the_json_script_registry_is_no_longer_a_writable_output(script_project):  # noqa: F811
    """The artefact retires with the ownership entry that made it writable. Leaving the
    entry would let a run write a ledger nothing reads, which is worse than no ledger:
    it looks maintained."""
    tool = SQLiteStateTool(slug=script_project, agent_name="interaction_designer", run_id=1)
    out = tool._run(operation="write", key="interview_script_registry",
                    agent_name="interaction_designer",
                    value=json.dumps({"scripts": [{"id": "SC-001", "node_id": "9.9"}]}))
    assert out.startswith("Refused:"), f"expected an ownership refusal, got: {out}"


def test_the_ledger_the_guard_reads_is_unaffected_by_that_refusal(script_project):  # noqa: F811
    """The refusal must not be able to corrupt or clear the table - the guard's record
    now lives somewhere the refused write cannot reach.

    Code review round 1, Important 3: the brief's original version moved SC-001 away from a
    node it already held. That is refused on the parent commit too - by
    validate_script_registry_succession, before anything is written - so the ledger and
    agent_outputs end up identical whether the door is open or closed, and the test cannot
    fail against the commit it exists to guard (verified: unmodified except for this
    docstring, it passes against the parent).

    SC-778 has never been registered anywhere, by any door. On the parent commit this is not
    a move at all - "growth is free", so a first-time id sails through succession - and the
    write actually lands: interview_script_registry.json is written, an agent_outputs row is
    created for it, and SC-778 is registered in the ledger at 9.9 (verified directly against
    the parent commit). That is the case that actually distinguishes "the door is closed"
    from "the door validated this and let it through", so it is what this test drives.
    """
    tool = SQLiteStateTool(slug=script_project, agent_name="interaction_designer", run_id=1)
    # Also register a real id through the surviving door, so the refusal below is proven not
    # to disturb it either - the guard's own record, not just an id the attack never touched.
    tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
              value=json.dumps({"SC-001": {"script_id": "SC-001", "node_id": "1.2",
                                           "node_label": "Works", "level": "L2",
                                           "relationship": "internal", "sections": []}}))

    out = tool._run(operation="write", key="interview_script_registry",
                    agent_name="interaction_designer",
                    value=json.dumps({"scripts": [
                        {"id": "SC-001", "node_id": "1.2", "node_label": "Works",
                         "active": True},
                        {"id": "SC-778", "node_id": "9.9"},
                    ]}))
    assert out.startswith("Refused:"), f"expected an ownership refusal, got: {out}"

    from agents.tools._db import current_script_ledger_sync
    ids = {e["id"]: e["node_id"] for e in current_script_ledger_sync(script_project)["scripts"]}
    assert ids == {"SC-001": "1.2"}, "the previously-registered id must be untouched"
    assert "SC-778" not in ids, "a growth-is-free write through the retired door must not register"

    import sqlite3
    from agents.tools._db import _db_path
    with sqlite3.connect(_db_path(script_project)) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM agent_outputs WHERE output_type='interview_script_registry'"
        ).fetchone()[0]
    assert count == 0, "a refused write must not have landed an agent_outputs row either"
