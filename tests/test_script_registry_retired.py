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
    now lives somewhere the refused write cannot reach."""
    tool = SQLiteStateTool(slug=script_project, agent_name="interaction_designer", run_id=1)
    # The brief's payload omitted script_id and relationship, both required by
    # validate_scripts (api/services/interview_script_model.py) - without them this write is
    # refused before it ever reaches registration, and the test's premise (SC-001 already
    # registered) never holds. Same fix already applied in
    # tests/test_script_ledger_registration.py's _script() helper.
    tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
              value=json.dumps({"SC-001": {"script_id": "SC-001", "node_id": "1.2",
                                           "node_label": "Works", "level": "L2",
                                           "relationship": "internal", "sections": []}}))
    tool._run(operation="write", key="interview_script_registry",
              agent_name="interaction_designer",
              value=json.dumps({"scripts": [{"id": "SC-001", "node_id": "9.9"}]}))

    from agents.tools._db import current_script_ledger_sync
    ids = {e["id"]: e["node_id"] for e in current_script_ledger_sync(script_project)["scripts"]}
    assert ids == {"SC-001": "1.2"}
