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


# ── Casey's themes ────────────────────────────────────────────────────────────────

def _seed_registry(outputs, activities):
    (outputs / "value_chain_registry_v1.json").write_text(
        json.dumps({"activities": activities}))


async def _register(slug, outputs, output_type, filename):
    async with get_connection(slug) as conn:
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            pid = (await cur.fetchone())[0]
        await conn.execute(
            "INSERT INTO agent_outputs"
            " (project_id, agent_name, output_type, file_path, version, is_current)"
            " VALUES (?,?,?,?,1,1)",
            (pid, "a", output_type, str(outputs / filename)))
        await conn.commit()


def _write_themes(slug, themes, run_id=11):
    from agents.tools.sqlite_state import SQLiteStateTool
    return SQLiteStateTool(slug=slug, agent_name="synthesis_analyst", run_id=run_id)._run(
        operation="write", key="themes",
        agent_name="synthesis_analyst", value=json.dumps(themes))


SKEWED = [
    {"id": f"TH-{i:02d}", "kind": "horizontal", "theme": "t", "description": "d",
     "anchors": ["1.1.1"]}
    for i in range(6)
]

BALANCED = [
    {"id": "TH-01", "kind": "vertical", "theme": "t", "description": "d",
     "anchors": ["0"]},
    {"id": "TH-02", "kind": "horizontal", "theme": "t", "description": "d",
     "anchors": ["1"]},
    {"id": "TH-03", "kind": "horizontal", "theme": "t", "description": "d",
     "anchors": ["1.1"]},
    {"id": "TH-04", "kind": "horizontal", "theme": "t", "description": "d",
     "anchors": ["1.1.1"]},
    {"id": "TH-05", "kind": "horizontal", "theme": "t", "description": "d",
     "anchors": ["1.1"]},
]

ACTIVITIES = [
    {"id": "0", "level": "L0", "active": True},
    {"id": "1", "level": "L1", "active": True},
    {"id": "1.1", "level": "L2", "active": True},
    {"id": "1.1.1", "level": "L3", "active": True},
]


@pytest.mark.asyncio
async def test_skewed_themes_are_written_and_warned_about(tool_project):
    """Casey's half of the same contract: the write lands, the finding is recorded."""
    slug, project_id, outputs = tool_project
    _seed_registry(outputs, ACTIVITIES)
    await _register(slug, outputs, "value_chain_registry", "value_chain_registry_v1.json")

    result = _write_themes(slug, SKEWED)
    assert not result.startswith("Error"), result
    assert current_output_path(slug, "themes") is not None, "the write must land"

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["theme_anchor"])
    assert [r["code"] for r in rows] == ["l3_skew"]
    assert rows[0]["measure"] == 1.0
    assert rows[0]["subject"] is None
    assert rows[0]["run_id"] == 11


@pytest.mark.asyncio
async def test_balanced_themes_record_nothing(tool_project):
    slug, project_id, outputs = tool_project
    _seed_registry(outputs, ACTIVITIES)
    await _register(slug, outputs, "value_chain_registry", "value_chain_registry_v1.json")

    _write_themes(slug, BALANCED)
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["theme_anchor"])
    assert rows == [], [r["detail"] for r in rows]


@pytest.mark.asyncio
async def test_themes_written_before_any_registry_exists_are_not_blocked(tool_project):
    """Casey may legitimately run on a project whose value chain is not built yet."""
    slug, project_id, _ = tool_project
    result = _write_themes(slug, SKEWED)
    assert not result.startswith("Error"), result
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["theme_anchor"])
    assert rows == []


@pytest.mark.asyncio
async def test_a_tree_warning_and_a_theme_warning_are_told_apart(tool_project):
    """source is what lets a reviewer see a tree finding separately from a theme one."""
    slug, project_id, outputs = tool_project
    _seed_registry(outputs, ACTIVITIES)
    await _register(slug, outputs, "value_chain_registry", "value_chain_registry_v1.json")

    _write_tree(slug, ROOTLESS)
    _write_themes(slug, SKEWED)

    async with get_connection(slug) as conn:
        tree = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["value_chain_tree"])
        theme = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["theme_anchor"])
    assert [r["code"] for r in tree] == ["missing_l0"]
    assert [r["code"] for r in theme] == ["l3_skew"]


# ── Casey's evidence attribution ──────────────────────────────────────────────────
#
# THE TEST THAT WAS MISSING. `tests/test_theme_evidence_validation.py` has ten tests and
# every one of them drives the pure function; not one goes through `_warn_theme_evidence`
# or the recorder. So the suite was green while the validator emitted
# `{code, severity, message}` and `record_validation_warnings_sync` required `detail` -
# `w["detail"]` raised KeyError, the per-warner `except Exception: continue` swallowed it,
# and the raise landed before `commit` so the `complete=True` clearing did not run either.
#
# The warner worked only when it found NOTHING. A clean artefact recorded nothing and
# cleared correctly; a defective one recorded nothing at all, which is the one case it
# exists for. Would this test fail if the code were wrong? These ones would.

def _theme_with_evidence(evidence):
    return [{"id": "TH-01", "kind": "horizontal", "theme": "t", "description": "d",
             "anchors": ["1.1"], "evidence": evidence}]


async def _seed_answer(slug, answer_id, stakeholder_id):
    """One interview_answers row, with the stakeholder and session it really hangs off.

    Seeded through the foreign keys rather than around them: `_warn_theme_evidence` reads
    `interview_answers.stakeholder_id`, and a corpus assembled in a shape production cannot
    reach is a fake making a claim about this system (see the module header in
    tests/test_theme_evidence_validation.py's sibling).
    """
    async with get_connection(slug) as conn:
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            pid = (await cur.fetchone())[0]
        await conn.execute(
            "INSERT OR IGNORE INTO stakeholders (id, project_id, name) VALUES (?,?,?)",
            (stakeholder_id, pid, "A Person"))
        await conn.execute(
            "INSERT OR IGNORE INTO interview_sessions"
            " (id, project_id, stakeholder_id, node_label, session_token)"
            " VALUES (1,?,?,'1.1',?)",
            (pid, stakeholder_id, f"tok-{slug}"))
        await conn.execute(
            "INSERT INTO interview_answers"
            " (id, session_id, stakeholder_id, script_id, section_id, question_id,"
            "  question_text, node_id, level, relationship, discipline, question_intent,"
            "  elicitation)"
            " VALUES (?,1,?,'SC-001','S1','Q1','q','1.1','L2','1.F','d','i','e')",
            (answer_id, stakeholder_id))
        await conn.commit()


@pytest.mark.asyncio
async def test_defective_theme_evidence_lands_a_row_in_validation_warnings(tool_project):
    """The live defect, end to end: the first themes artefact filed the RELATIONSHIP in
    `stakeholder_id` on 68 of 68 rows. Here one such row must produce a stored warning."""
    slug, project_id, _ = tool_project
    await _seed_answer(slug, 812, 10)

    result = _write_themes(slug, _theme_with_evidence(
        [{"answer_id": 812, "stakeholder_id": "1.F"}]))
    assert not result.startswith("Error"), result
    assert current_output_path(slug, "themes") is not None, "the write must still land"

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["theme_evidence"])

    codes = sorted(r["code"] for r in rows)
    assert codes == ["no_relationship", "stakeholder_id_not_an_integer"], codes
    by_code = {r["code"]: r for r in rows}
    assert by_code["stakeholder_id_not_an_integer"]["run_id"] == 11
    assert by_code["stakeholder_id_not_an_integer"]["subject"] is None
    # measure is read by the dismissal-expiry rule; absent, that logic is inert.
    assert by_code["stakeholder_id_not_an_integer"]["measure"] == 1
    assert "1.F" in by_code["stakeholder_id_not_an_integer"]["detail"]


@pytest.mark.asyncio
async def test_evidence_naming_the_wrong_person_is_recorded(tool_project):
    """The other half of the corpus check, which needs the project database read in
    `_warn_theme_evidence` to have actually happened - an integer that is simply the wrong
    integer is invisible without it."""
    slug, project_id, _ = tool_project
    await _seed_answer(slug, 812, 10)

    _write_themes(slug, _theme_with_evidence(
        [{"answer_id": 812, "stakeholder_id": 99, "relationship": "1.F"}]))

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["theme_evidence"])
    assert [r["code"] for r in rows] == ["stakeholder_id_disagrees"], [
        (r["code"], r["detail"]) for r in rows]
    assert "99 for answer 812" in rows[0]["detail"]
    assert "whose own stakeholder is 10" in rows[0]["detail"]


@pytest.mark.asyncio
async def test_well_attributed_theme_evidence_records_nothing(tool_project):
    """The control, and it is the one the broken shape also passed.

    A warner that raises before it inserts is indistinguishable from a warner that found
    nothing, so a clean case alone proves nothing about this path - which is exactly how
    ten green tests sat over a KeyError. Kept because an assertion of a default and its
    opposite is the pair; alone it is a test about the schema.
    """
    slug, project_id, _ = tool_project
    await _seed_answer(slug, 812, 10)

    _write_themes(slug, _theme_with_evidence(
        [{"answer_id": 812, "stakeholder_id": 10, "relationship": "1.F"}]))

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["theme_evidence"])
    assert rows == [], [(r["code"], r["detail"]) for r in rows]


@pytest.mark.asyncio
async def test_a_fixed_evidence_set_clears_the_stored_warning(tool_project):
    """`complete=True` never ran either, because the KeyError fired before the commit. So
    a finding could not clear once corrected - the shape of defect this codebase records as
    worse than no warning at all, since acting on it is the wrong move."""
    slug, project_id, _ = tool_project
    await _seed_answer(slug, 812, 10)

    _write_themes(slug, _theme_with_evidence([{"answer_id": 812, "stakeholder_id": "1.F"}]))
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["theme_evidence"])
    assert rows, "precondition: the defective write is warned about"

    _write_themes(slug, _theme_with_evidence(
        [{"answer_id": 812, "stakeholder_id": 10, "relationship": "1.F"}]))
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["theme_evidence"])
    assert rows == [], [(r["code"], r["detail"]) for r in rows]


@pytest.mark.asyncio
async def test_a_warner_that_raises_says_so_in_the_log(tool_project, caplog):
    """The swallow is right; the silence was not.

    `theme_evidence` emitted a shape the recorder could not store, so `w["detail"]` raised
    here on every defective write and the `except` returned the run to a state
    indistinguishable from a clean artefact. The write must still land - that half is
    deliberate and asserted below - but an operator must be able to find out.
    """
    import logging
    slug, project_id, _ = tool_project
    import agents.tools.sqlite_state as st

    def boom(*a, **k):
        raise KeyError("detail")
    st_record = st.record_validation_warnings_sync
    try:
        st.record_validation_warnings_sync = boom
        with caplog.at_level(logging.ERROR):
            result = _write_tree(slug, ROOTLESS)
    finally:
        st.record_validation_warnings_sync = st_record

    assert not result.startswith("Error"), result
    assert current_output_path(slug, "value_chain_tree") is not None, "the write must land"
    assert "value_chain_tree" in caplog.text
    assert "KeyError" in caplog.text


# ── Maya's batches, and the clearing that must not reach past them ────────────────
#
# `_warn_script_durations` judges the PRE-MERGE batch on purpose, and the recorder clears
# with complete=True. Unscoped, those two are in direct contradiction: a clean second batch
# re-derives nothing and the clearing deletes the first batch's findings, while the
# defective welcomes sit in the stored artefact unreported for the life of the project.
# Maya writes in batches - the live artefact went v33=77 -> v34=80 -> v35=86 scripts.

def _script(sid, stated_minutes, section_minutes):
    return {
        "script_id": sid, "node_id": "1.1", "node_label": "n", "level": "L2",
        "relationship": "internal",
        "welcome_message": f"This will take about {stated_minutes} minutes.",
        "framing_block": "f", "closing_message": "c",
        "sections": [{
            "section_id": "S1", "target_minutes": section_minutes,
            "discipline": "process", "question_intent": "context",
            "elicitation": "prompted",
            "questions": [{"id": "Q1", "text": "t", "discipline": "process",
                           "question_intent": "context", "elicitation": "prompted"}],
        }],
    }


def _write_scripts(slug, scripts, run_id=21):
    from agents.tools.sqlite_state import SQLiteStateTool
    return SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=run_id)._run(
        operation="write", key="interview_scripts",
        agent_name="interaction_designer", value=json.dumps(scripts))


async def _duration_subjects(slug, project_id):
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["script_duration"])
    return sorted(r["subject"] for r in rows)


@pytest.mark.asyncio
async def test_a_clean_batch_does_not_erase_an_earlier_batchs_findings(tool_project):
    """The defect, driven end to end through the tool that writes the artefact."""
    slug, project_id, _ = tool_project

    bad = {f"SC-00{i}": _script(f"SC-00{i}", 20, 40) for i in (1, 2, 3)}
    assert not _write_scripts(slug, bad).startswith("Error")
    assert await _duration_subjects(slug, project_id) == ["SC-001", "SC-002", "SC-003"]

    clean = {"SC-004": _script("SC-004", 50, 40)}
    assert not _write_scripts(slug, clean, run_id=22).startswith("Error")
    assert await _duration_subjects(slug, project_id) == ["SC-001", "SC-002", "SC-003"], \
        "a batch that never looked at SC-001..003 must not clear findings about them"


@pytest.mark.asyncio
async def test_correcting_one_script_clears_that_script_alone(tool_project):
    """The other half. Clearing was never wrong - only its reach was - so a rewritten
    script must still stop being reported, and only that one."""
    slug, project_id, _ = tool_project

    _write_scripts(slug, {f"SC-00{i}": _script(f"SC-00{i}", 20, 40) for i in (1, 2, 3)})
    _write_scripts(slug, {"SC-002": _script("SC-002", 50, 40)}, run_id=22)

    assert await _duration_subjects(slug, project_id) == ["SC-001", "SC-003"]


@pytest.mark.asyncio
async def test_the_open_findings_match_the_scripts_the_stored_artefact_still_gets_wrong(
    tool_project,
):
    """The property underneath both tests above, stated once against the artefact itself.

    The warnings a reviewer sees must be exactly the scripts that are actually still wrong -
    not a subset erased by a later batch, and not a superset kept after a fix.
    """
    from api.services.script_duration_validation import find_duration_disagreements

    slug, project_id, _ = tool_project
    _write_scripts(slug, {f"SC-00{i}": _script(f"SC-00{i}", 20, 40) for i in (1, 2, 3)})
    _write_scripts(slug, {"SC-004": _script("SC-004", 50, 40)}, run_id=22)
    _write_scripts(slug, {"SC-002": _script("SC-002", 50, 40)}, run_id=23)

    stored = json.loads(current_output_path(slug, "interview_scripts").read_text())
    still_wrong = sorted(s for s, _, _ in find_duration_disagreements(stored))
    assert still_wrong == ["SC-001", "SC-003"], "precondition: the artefact is as expected"
    assert await _duration_subjects(slug, project_id) == still_wrong


@pytest.mark.asyncio
async def test_the_script_the_agent_is_told_to_fix_is_named_in_the_prompt(tool_project):
    """One layer on: a subject-keyed finding is worth nothing if Maya is handed a detail
    with no id in it. `_fetch_validation_warnings` prefixes the subject, so this asserts the
    text that actually reaches her."""
    from api.services.run_service import _fetch_validation_warnings

    slug, _, _ = tool_project
    _write_scripts(slug, {"SC-001": _script("SC-001", 20, 40)})

    text = await _fetch_validation_warnings(slug, "assessment_design")
    assert "[SC-001]" in text
    assert "50" in text, "the derived duration must be in the text she is asked to act on"


@pytest.mark.asyncio
async def test_a_whole_artefact_warner_still_clears_across_batches(tool_project):
    """The scoping must not leak to the merged-artefact warners.

    `script_assertion` judges the accumulated artefact, so a later batch that fixes a
    pre-written synthesis anywhere in it must clear the finding - and would not if this
    change had narrowed every warner's clearing to the ids in the batch.
    """
    slug, project_id, _ = tool_project

    bad = _script("SC-001", 50, 40)
    bad["closing_message"] = "Here's my summary of what you told me."
    _write_scripts(slug, {"SC-001": bad})
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["script_assertion"])
    assert [r["code"] for r in rows] == ["prewritten_synthesis"]

    # A LATER batch, naming a different script, that leaves the merged artefact clean.
    fixed = _script("SC-001", 50, 40)
    _write_scripts(slug, {"SC-001": fixed, "SC-002": _script("SC-002", 50, 40)}, run_id=22)
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["script_assertion"])
    assert rows == [], [(r["subject"], r["detail"]) for r in rows]


def test_the_theme_warners_are_whole_artefact_only_because_themes_do_not_merge():
    """`_warn_theme_evidence` reads the pre-merge batch, exactly as the duration warner does,
    and is nonetheless registered whole-artefact scoped. That is correct ONLY because
    `themes` is not in `_MERGE_ON_WRITE`, so a themes write replaces the artefact outright
    and its batch IS the whole of it.

    Asserted rather than assumed: adding `themes` to the merge set would silently give it the
    batch-erasure defect, with nothing else in the code to notice.
    """
    from agents.tools.sqlite_state import (
        _MERGE_ON_WRITE, _WARNERS, _the_whole_artefact,
    )

    assert "themes" not in _MERGE_ON_WRITE, (
        "themes now merge on write, so `theme_evidence` is judging a fragment while "
        "clearing the whole source - give it a batch scope, as script_duration has."
    )
    assert all(scope is _the_whole_artefact for _, _, scope in _WARNERS["themes"])
