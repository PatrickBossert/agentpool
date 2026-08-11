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


def test_a_null_node_label_does_not_silently_break_registration(script_project):
    """Task 2 review, Critical 1: INSERT OR IGNORE suppresses every constraint violation on
    the row, not only the primary-key conflict it was written for. node_label is NOT NULL
    (api/database.py's _migrate_interview_script_ledger), and a script whose JSON carries an
    explicit "node_label": null - which a model emitting JSON does - hit that constraint and
    was dropped from the whole batch with no error and no ledger row. The *next* batch then
    found the id unregistered and moved it unrefused: SC-001 published at 1.2, silently
    re-anchored to 2.7, with the write path reporting "Written to" both times. This test
    reproduces exactly that shape and would have failed against the pre-fix code with the
    second write succeeding instead of being refused."""
    slug = script_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)
    first = _script("SC-001", "1.2", "Works Programming")
    first["node_label"] = None
    out1 = tool._run(operation="write", key="interview_scripts",
                     agent_name="interaction_designer", value=json.dumps({"SC-001": first}))
    assert out1.startswith("Written to"), out1

    out2 = tool._run(operation="write", key="interview_scripts",
                     agent_name="interaction_designer",
                     value=json.dumps({"SC-001": _script("SC-001", "2.7", "Somewhere Else")}))
    assert out2.startswith("Error:"), f"a moved id must be refused, got: {out2}"

    from agents.tools._db import current_script_ledger_sync
    ids = {e["id"]: e["node_id"] for e in current_script_ledger_sync(slug)["scripts"]}
    assert ids == {"SC-001": "1.2"}, "the null-label batch must still have registered SC-001"


def test_last_version_reflects_only_ids_the_batch_actually_touched(script_project):
    """Task 2 review, Important 2: interview_scripts merges before validation, so `parsed`
    at the registration hook is the whole accumulated artefact, not the fragment this call
    wrote. register_scripts_sync must be called with the pre-merge batch, or every earlier
    script's last_version is bumped by every later, unrelated batch - and a staleness signal
    every batch resets is not a signal."""
    slug = script_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)
    tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
              value=json.dumps({"SC-001": _script("SC-001", "1.2", "Works Programming")}))
    tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
              value=json.dumps({"SC-002": _script("SC-002", "1.3", "Pipeline Design")}))

    import sqlite3
    from agents.tools._db import _db_path
    with sqlite3.connect(_db_path(slug)) as conn:
        rows = dict(conn.execute(
            "SELECT script_id, last_version FROM interview_script_ledger"
        ).fetchall())
    assert rows["SC-001"] == 1, f"SC-001 was not in batch 2 - its last_version must stay 1, got {rows}"
    assert rows["SC-002"] == 2


def test_a_first_registration_through_interview_scripts_honours_an_explicit_active(script_project):
    """Repointed from the retired interview_script_registry door (Task 3, code review round
    1, Important 2). Restated because it covers a real path with no other test on it:
    register_scripts_sync (agents/tools/_db.py) applies whatever active value a first-time
    entry names rather than always defaulting to True - a script body carrying
    "active": false must land retired even on its first registration, exactly as it did
    through the door that has since closed."""
    slug = script_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)
    script = _script("SC-500", "1.2", "Retired on arrival")
    script["active"] = False
    tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
              value=json.dumps({"SC-500": script}))

    from agents.tools._db import current_script_ledger_sync
    entry = next(e for e in current_script_ledger_sync(slug)["scripts"] if e["id"] == "SC-500")
    assert entry["active"] is False


def test_retiring_an_already_registered_id_through_interview_scripts_reaches_the_table(script_project):
    """Repointed from the retired interview_script_registry door (Task 3, code review round
    1, Important 2). active is the one field register_scripts_sync still lets a later batch
    change on an id it already holds - node_id, node_label, last_version, and last_author may
    not move once set, but active may. Register SC-001 (active unspecified, defaults True),
    then retire it in a later batch - the ledger must show active: False afterwards, with
    node_id untouched."""
    slug = script_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)
    tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
              value=json.dumps({"SC-001": _script("SC-001", "1.2", "Works Programming")}))

    retired = _script("SC-001", "1.2", "Works Programming")
    retired["active"] = False
    out = tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
                    value=json.dumps({"SC-001": retired}))
    assert out.startswith("Written to"), out

    from agents.tools._db import current_script_ledger_sync
    entry = next(e for e in current_script_ledger_sync(slug)["scripts"] if e["id"] == "SC-001")
    assert entry["node_id"] == "1.2"
    assert entry["active"] is False


def test_a_non_string_node_label_is_refused_by_the_tool(script_project):
    """Task 2 review round 2, the Critical re-raised: round 1's coalesce only closed the
    null case. node_label as an object still reached sqlite3's bind for
    interview_script_ledger.node_label with no validation in between - the re-reviewer
    drove it through the real write path and got "Written to" both times, with SC-001
    published at 1.2, never registered (register_scripts_sync's exception was swallowed),
    and silently re-anchored to 2.7 on the second write.

    The fix is at the door, not in register_scripts_sync: validate_scripts now refuses a
    node_label that is neither a string nor null, so a batch that could break the bind is
    never written at all, and registration can never be reached with a value it cannot
    handle. This drives that through SQLiteStateTool._run (not the validator function
    directly), asserts the refusal, then separately establishes SC-001 legitimately and
    asserts a later batch still cannot move it - the ledger must never have been left in a
    state a bad write could exploit.
    """
    slug = script_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)

    bad = _script("SC-001", "1.2", "Works Programming")
    bad["node_label"] = {"not": "a string"}
    out1 = tool._run(operation="write", key="interview_scripts",
                     agent_name="interaction_designer", value=json.dumps({"SC-001": bad}))
    assert out1.startswith("Error:"), f"a non-string node_label must be refused, got: {out1}"
    assert "node_label" in out1

    from agents.tools._db import current_script_ledger_sync
    assert current_script_ledger_sync(slug)["scripts"] == [], (
        "a refused write must not have registered anything"
    )

    out2 = tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
                     value=json.dumps({"SC-001": _script("SC-001", "1.2", "Works Programming")}))
    assert out2.startswith("Written to"), out2

    out3 = tool._run(operation="write", key="interview_scripts",
                     agent_name="interaction_designer",
                     value=json.dumps({"SC-001": _script("SC-001", "2.7", "Somewhere Else")}))
    assert out3.startswith("Error:"), f"a moved id must be refused, got: {out3}"
    ids = {e["id"]: e["node_id"] for e in current_script_ledger_sync(slug)["scripts"]}
    assert ids == {"SC-001": "1.2"}


def test_a_registration_failure_is_recorded_not_silent(script_project, monkeypatch):
    """Task 2 review round 2: a registration exception must leave a trace, not vanish into
    a bare except. Forces register_scripts_sync to raise for reasons the door validation
    cannot anticipate (round 1's silent swallow is what let the node_label defect exist
    undetected in the first place) and asserts a validation_warnings row names the id."""
    import asyncio
    import agents.tools.sqlite_state as sqlite_state_mod
    from api.database import get_connection, fetch_validation_warnings

    def _boom(*a, **k):
        raise RuntimeError("simulated ledger failure")

    monkeypatch.setattr(sqlite_state_mod, "register_scripts_sync", _boom)

    slug = script_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)
    out = tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
                    value=json.dumps({"SC-001": _script("SC-001", "1.2", "Works Programming")}))
    assert out.startswith("Written to"), out   # the durable write must still succeed

    async def _read():
        async with get_connection(slug) as conn:
            cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (slug,))
            project_id = (await cur.fetchone())[0]
            return await fetch_validation_warnings(conn, project_id=project_id)
    rows = asyncio.run(_read())
    matches = [r for r in rows if r["code"] == "registration_failed"]
    assert len(matches) == 1
    assert "SC-001" in matches[0]["subject"] or "SC-001" in matches[0]["detail"]


