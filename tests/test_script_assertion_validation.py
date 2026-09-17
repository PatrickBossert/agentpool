"""The guard over Maya's artefact, driven in both directions.

`ui/src/__tests__/synthesisWithdrawn.test.ts` is a source walk over the runtime and says in its
own header that it cannot see "a re-implementation under a different name". That is what
happened: Maya wrote the synthesis a second time as a section question, in the artefact, and an
internal auditor endorsed a fabrication composed weeks before she spoke. This is the guard at
the layer that broke.

Driven BOTH WAYS on committed fixtures, because a one-sided test passes against a walk that
reports everything and against one that reports nothing. The fixtures hold real text - the
defect is transcribed from the artefact that caused the incident - so what is asserted is that
the guard catches the thing that actually happened, not a thing written to be caught.
"""
import json
from pathlib import Path

import pytest
import pytest_asyncio

from agents.tools._db import current_output_path
from api.config import get_settings
from api.database import fetch_validation_warnings, get_connection
from api.services.script_assertion_validation import (
    find_asserted_summaries,
    find_false_handling_promises,
    validate_script_assertions,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    # Committed, and resolved relative to this file rather than the working directory. Four
    # tests on this project read a bare relative Path("projects/...") and are silently dark on
    # every clean checkout and from any cwd but the repository root; this must not join them.
    data = json.loads((_FIXTURES / f"{name}.json").read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


@pytest.fixture
def defective() -> dict:
    return _load("interview_scripts_prewritten_synthesis")


@pytest.fixture
def clean() -> dict:
    return _load("interview_scripts_open_wrap_up")


# ── the fixtures are what they claim to be ──────────────────────────────────────────────────
# Without these, a fixture quietly emptied by a bad edit would make every assertion below pass.

def test_the_defective_fixture_holds_the_two_places_maya_wrote_the_synthesis(defective):
    assert set(defective) == {"SC-013", "SC-901"}
    # The section question - the one nothing guarded, and the one that reached a person.
    assert "let me offer a synthesis" in defective["SC-013"]["sections"][0]["questions"][0]["text"]
    # The synthesis_check field - the one the 4 September withdrawal covered.
    assert "here's how I see" in defective["SC-901"]["synthesis_check"]["synthesis_prompt"]


def test_the_clean_fixture_holds_a_real_wrap_up_question(clean):
    assert set(clean) == {"SC-801", "SC-802", "SC-803", "SC-804"}
    assert "most want to reach the board" in clean["SC-801"]["sections"][0]["questions"][0]["text"]


# ── it catches the thing that happened ──────────────────────────────────────────────────────

def test_the_question_an_auditor_was_read_is_caught(defective):
    """The live defect. A section question, which the runtime guard cannot see."""
    found = find_asserted_summaries(defective)
    assert ("SC-013", "SC-013.S10.Q1.text", "let me offer a synthesis") in found


def test_the_withdrawn_synthesis_field_is_caught_as_well(defective):
    """Both copies, not just the one the runtime already refuses to speak."""
    where = {(s, w) for s, w, _ in find_asserted_summaries(defective)}
    assert ("SC-901", "synthesis_check.synthesis_prompt") in where


def test_a_confirmation_request_is_caught_even_without_an_assertion_marker():
    """'Does that match your assessment?' presupposes a summary was offered.

    This is the half that survives a rephrasing. An agent that stops writing "here's how I see"
    and writes "my read of this cluster is [...]" leaves no assertion marker, and the request to
    confirm it is what remains visible.
    """
    scripts = {"SC-1": {"sections": [{"questions": [
        {"id": "Q1", "text": "My read of this cluster is that maturity is Repeatable. "
                             "Does that match your assessment?"},
    ]}]}}
    assert [m for _, _, m in find_asserted_summaries(scripts)] == ["does that match your assessment"]


def test_the_unfiltered_promise_is_caught(defective):
    """SC-013's closing, and its welcome. Both said 'unfiltered'; neither was true."""
    where = {(s, w) for s, w, _ in find_false_handling_promises(defective)}
    assert ("SC-013", "closing_message") in where
    assert ("SC-013", "welcome_message") in where


def test_both_defects_are_reported_as_warnings_with_their_own_codes(defective):
    codes = {w["code"] for w in validate_script_assertions(defective)}
    assert codes == {"prewritten_synthesis", "false_handling_promise"}


def test_the_warning_names_where_to_look(defective):
    detail = next(
        w["detail"] for w in validate_script_assertions(defective)
        if w["code"] == "prewritten_synthesis"
    )
    assert "SC-013.S10.Q1.text" in detail


# ── and it leaves a legitimate close alone ──────────────────────────────────────────────────

def test_an_open_wrap_up_question_passes(clean):
    """The control that decides whether this guard is usable.

    If it fires here it fires on the repaired prompt's own output, and it gets switched off.
    """
    assert validate_script_assertions(clean) == []


def test_a_retrospective_prefix_that_asks_rather_than_asserts_passes(clean):
    """'Based on our conversation, what would you prioritise?' asserts nothing.

    The rule deliberately does not trigger on a retrospective prefix alone. Every real instance
    carries an assertion or a confirmation request as well, so including it would buy nothing
    and cost a false positive on a perfectly good question.
    """
    assert find_asserted_summaries({"SC-802": clean["SC-802"]}) == []


def test_the_interviewers_own_notes_are_not_searched(clean):
    """`probing_instructions` legitimately says "summarise what they have said back to them".

    A marker in a field nobody speaks is not this guard's finding - the defect is a participant
    hearing it. SC-803 also carries markers in research_brief and study_objectives.
    """
    assert find_asserted_summaries({"SC-803": clean["SC-803"]}) == []


def test_saying_truthfully_how_answers_are_handled_passes(clean):
    """'goes directly into the improvement plan' promises nothing false about attribution.

    'directly' and 'unchanged' are ordinary words, so they are matched only where they are bound
    to a destination.
    """
    assert find_false_handling_promises({"SC-804": clean["SC-804"]}) == []


# ── it does not fall over on the shapes a real artefact takes ───────────────────────────────

@pytest.mark.parametrize("scripts", [
    {},
    {"SC-1": None},
    {"SC-1": {}},
    {"SC-1": {"sections": "not a list"}},
    {"SC-1": {"sections": [{"questions": [None, "text"]}]}},
    {"SC-1": {"synthesis_check": None}},
], ids=["empty", "null script", "no fields", "sections wrong type",
        "question wrong type", "null synthesis_check"])
def test_a_malformed_artefact_warns_nothing_rather_than_raising(scripts):
    """The warner runs after a write has already landed, so raising here would be noise about
    an artefact that is durable either way - and shape is the schema's problem."""
    assert validate_script_assertions(scripts) == []


def test_one_defective_template_produces_one_warning_not_one_per_script():
    """A bad template writes the same line into every script it produced. 86 findings would
    bury the surface they are reported into; the actionable fact is the set."""
    scripts = {
        f"SC-{i:03d}": {"sections": [{"questions": [
            {"id": f"Q{i}", "text": "To recap what I heard, the biggest constraint is data."},
        ]}]}
        for i in range(40)
    }
    warnings = validate_script_assertions(scripts)
    assert len(warnings) == 1
    assert warnings[0]["measure"] == 40


# ── what calls this, and is THAT tested? ────────────────────────────────────────────────────
# The whole reason this guard exists is that the last one was proven and its caller was not.
# Everything above proves the function. These prove the write path acts on it.

@pytest_asyncio.fixture
async def script_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "script-assertion-test"
    (tmp_path / "projects" / slug / "outputs").mkdir(parents=True, exist_ok=True)
    async with get_connection(slug) as conn:
        await conn.execute("INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id
    get_settings.cache_clear()


def _write_scripts(slug: str, scripts: dict, run_id: int = 11) -> str:
    from agents.tools.sqlite_state import SQLiteStateTool

    return SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=run_id)._run(
        operation="write", key="interview_scripts",
        agent_name="interaction_designer", value=json.dumps(scripts))


@pytest.mark.asyncio
async def test_writing_a_defective_artefact_records_the_warning_and_still_writes(
    script_project, defective
):
    """Warn, never refuse. The artefact is ~400KB across batched writes and a refusal loses
    the run's work - so the write must land and the finding must be recorded beside it."""
    slug, project_id = script_project
    result = _write_scripts(slug, defective)

    assert not result.startswith("Error"), result
    resolved = current_output_path(slug, "interview_scripts")
    assert resolved is not None, "the write must land despite the warning"

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["script_assertion"])
    assert {r["code"] for r in rows} == {"prewritten_synthesis", "false_handling_promise"}
    assert rows[0]["run_id"] == 11


@pytest.mark.asyncio
async def test_writing_a_clean_artefact_records_nothing(script_project, clean):
    slug, project_id = script_project
    _write_scripts(slug, clean)
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["script_assertion"])
    assert rows == []


@pytest.mark.asyncio
async def test_repairing_the_offending_scripts_clears_the_finding(script_project, defective):
    """complete=True per source. A repaired artefact must not keep reporting the old defect.

    The repair rewrites the SAME script ids, because `interview_scripts` MERGES rather than
    replaces - `_merge_with_current` keys on script_id so a batch omitting a script means "not
    in this batch", never "delete this". Writing a different, clean set would leave the
    defective scripts in the merged artefact and the warning correctly standing, which is what
    the send-back loop does in practice: one script goes back, that one is rewritten.
    """
    slug, project_id = script_project
    _write_scripts(slug, defective)

    repaired = json.loads(json.dumps(defective))
    repaired["SC-013"]["sections"][0]["questions"][0]["text"] = (
        "Before we finish - what are the two or three findings from this conversation you "
        "would most want to reach the board and the audit committee?"
    )
    repaired["SC-013"]["welcome_message"] = "Thank you for making the time."
    repaired["SC-013"]["closing_message"] = (
        "Your observations will be analysed together with the other interviews."
    )
    sc = repaired["SC-901"]["synthesis_check"]
    del sc["synthesis_prompt"]
    sc["closing_invitation"] = (
        "Before we finish - what are the two or three things you would most want carried back?"
    )
    sc["response_probes"]["if_defensive"] = "What has nobody said yet?"
    _write_scripts(slug, repaired, run_id=12)

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["script_assertion"])
    assert rows == []


@pytest.mark.asyncio
async def test_the_two_scripts_warners_do_not_clear_each_other(
    script_project, defective, tmp_path
):
    """The reason the source travels WITH the warner rather than being looked up per key.

    `record_validation_warnings_sync` runs complete=True per source, re-deriving everything for
    that source and clearing what is now absent. Sharing one source between the coverage check
    and this one would make each clean run wipe the other's findings - a silent loss, not a
    wrong label. Here one write leaves a registry node uncovered AND asserts a summary, so both
    findings must survive it.
    """
    slug, project_id = script_project
    outputs = tmp_path / "projects" / slug / "outputs"
    # Both fixture scripts' nodes, so the artefact is structurally valid, plus one node nobody
    # has scripted, so the coverage warner has something to say about the same write.
    (outputs / "value_chain_registry_v1.json").write_text(json.dumps({"activities": [
        {"id": "0.A", "label": "Internal Audit", "level": "L0", "active": True},
        {"id": "1.2", "label": "Asset Planning", "level": "L2", "active": True},
        {"id": "7.7", "label": "Nobody Has Scripted This", "level": "L2", "active": True},
    ]}))
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO agent_outputs"
            " (project_id, agent_name, output_type, file_path, version, is_current)"
            " VALUES (?,?,?,?,1,1)",
            (project_id, "value_chain_mapper", "value_chain_registry",
             str(outputs / "value_chain_registry_v1.json")))
        await conn.commit()

    _write_scripts(slug, defective)

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    by_source = {r["source"]: r["code"] for r in rows}
    assert by_source.get("script_assertion") is not None
    assert by_source.get("interview_coverage") == "incomplete_coverage"
    assert "prewritten_synthesis" in {r["code"] for r in rows}


# ── The false positive the live corpus found ─────────────────────────────────

def test_an_ambiguous_word_is_a_promise_in_the_closing_and_not_in_a_question():
    """`unfiltered` means two different things depending on who it is about.

    Found on SC-013 v38, the first script Maya regenerated after the send-back: she had
    correctly removed the false promise from the closing, and the script still contained
    the word - in a question asking *"are they getting the unfiltered picture or a
    management narrative?"*. That is about what the **board** sees, which is a good thing
    to ask an auditor, and nothing to do with what happens to her answers.

    It matters more than an ordinary false positive because this validator runs on the
    **write path**, not only in tests: the warning would have reached Maya on every run,
    inviting her to repair a question that was right. Both real instances of the defect
    were in `closing_message`, which is where a promise about handling is made.

    Driven in all three directions - the unambiguous phrase anywhere, the ambiguous word
    where a promise lives, and the ambiguous word where it does not. The third alone would
    pass against a validator that reported nothing at all.
    """
    from api.services.script_assertion_validation import find_false_handling_promises

    verbatim_question = {
        "SC-A": {"sections": [{"questions": [
            {"text": "Are they getting the unfiltered picture or a management narrative?"}
        ]}]}
    }
    assert find_false_handling_promises(verbatim_question) == [], (
        "a question about what the board sees was read as a promise to the interviewee"
    )

    promise_in_closing = {
        "SC-B": {"closing_message": "What you share goes to the board unfiltered."}
    }
    assert [m for _, _, m in find_false_handling_promises(promise_in_closing)] == ["unfiltered"]

    # The control: an unambiguous phrase is a promise wherever it is spoken, including in
    # a question, because it names the destination and cannot be read innocently.
    phrase_in_question = {
        "SC-C": {"sections": [{"questions": [
            {"text": "You know this goes directly to the board - does that change your answer?"}
        ]}]}
    }
    assert find_false_handling_promises(phrase_in_question), (
        "scoping the ambiguous words must not have narrowed the unambiguous phrases"
    )
