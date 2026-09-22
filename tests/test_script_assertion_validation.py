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


def test_a_withdrawn_synthesis_field_is_not_a_finding(defective):
    """Deliberately reversed, and the measurement is the argument.

    `synthesis_prompt` is commented out of `VoiceInterview.tsx` and no participant hears it,
    so a marker there is not this guard's finding - the rule `_spoken_strings` states in its
    own first line. Watching it cost 44 standing findings on the live `interview_scripts_v38`,
    which `_merge_with_current` accumulates and the owner has decided to keep: a warner firing
    on every write for ever, at a measure a dismissal cannot settle.

    The half that keeps this honest is
    test_every_synthesis_field_the_interview_speaks_is_watched below - if the field is ever
    spoken again, it comes straight back under the guard and this test fails with it.
    """
    where = {(s, w) for s, w, _ in find_asserted_summaries(defective)}
    assert ("SC-901", "synthesis_check.synthesis_prompt") not in where


def test_the_one_synthesis_field_the_participant_hears_is_watched(defective):
    """`peer_referral` is spoken, so a summary smuggled into it is a finding.

    The necessary other half: an exclusion proved only by absence is satisfied by a guard
    that looks at nothing in `synthesis_check` at all.
    """
    smuggled = json.loads(json.dumps(defective))
    smuggled["SC-901"]["synthesis_check"]["peer_referral"] = (
        "Here's my summary of your position - who else should I speak to?"
    )
    where = {(s, w) for s, w, _ in find_asserted_summaries(smuggled)}
    assert ("SC-901", "synthesis_check.peer_referral") in where


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


def test_asking_an_auditor_where_their_findings_go_is_not_a_promise():
    """The same argument as `unfiltered`, one phrase over, and latent rather than live.

    "Does this go straight to the board, or through management?" is a question about the
    organisation's reporting line - a perfectly good thing to ask an internal auditor, and
    nothing to do with what happens to her answers. Matched everywhere, it made the warner
    cry wolf on a correct question, on the write path, on every run.
    """
    question = {"SC-1": {"sections": [{"questions": [
        {"id": "Q1", "text": "Does this go straight to the board, or through management?"},
        {"id": "Q2", "text": "Are findings reported directly to the board, or filtered?"},
    ]}]}}
    assert find_false_handling_promises(question) == []


def test_promising_an_auditor_her_words_go_straight_to_the_board_is_still_caught():
    """The other direction, and the reason the phrases are restricted rather than deleted.

    In a welcome or a closing there is no innocent reading: it is a promise about handling,
    made where handling is described, and it is false - answers are synthesised first.
    """
    promise = {"SC-1": {
        "welcome_message": "What you say goes straight to the board.",
        "closing_message": "Your words go directly to the board, unedited.",
    }}
    where = {(w, m) for _, w, m in find_false_handling_promises(promise)}
    assert ("welcome_message", "straight to the board") in where
    assert ("closing_message", "directly to the board") in where


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
    #
    # This case read "goes directly to the board", and that phrase turned out to belong on
    # the other side of this very test: "Are findings reported directly to the board, or
    # filtered?" is the identical legitimate audit question as the `unfiltered` one above.
    # So the phrase moved to the field-scoped set and the control moved to one with no
    # innocent reading at all. The PROPERTY is unchanged - what changed is the example, which
    # had been chosen to be unambiguous and was not.
    phrase_in_question = {
        "SC-C": {"sections": [{"questions": [
            {"text": "You know this reaches the board exactly as you said it - does that "
                     "change your answer?"}
        ]}]}
    }
    assert find_false_handling_promises(phrase_in_question), (
        "scoping the ambiguous words must not have narrowed the unambiguous phrases"
    )


# ── the allow-list is held against the runtime, not against a comment ──────────────────────
#
# `_SPOKEN_SYNTHESIS_FIELDS` names the `synthesis_check` fields a participant actually hears,
# and everything else in that block is outside the guard. An allow-list has one hazard - a NEW
# spoken field goes unwatched - and that is precisely the "re-implementation under a different
# name" this module exists for. So the list is not explained, it is established: the walk below
# is a pure function over given text, driven both gated and ungated, and then run against
# `VoiceInterview.tsx` itself.

import re

_SPEAKS = re.compile(
    r"speakText\(\s*(?:sc|script\.synthesis_check)\.([A-Za-z_][A-Za-z0-9_]*)"
)


def spoken_synthesis_fields(source: str) -> set[str]:
    """Which `synthesis_check` fields the given TypeScript speaks.

    Pure over given text so it can be asked what it saw. Line comments only - this file uses
    `//` for every withdrawal and nothing is wrapped in `/* */`, and a walk that claimed to
    handle block comments without being driven on one would be describing its reach rather
    than establishing it.
    """
    found: set[str] = set()
    for line in source.splitlines():
        if line.strip().startswith("//"):
            continue
        match = _SPEAKS.search(line)
        if match:
            found.add(match.group(1))
    return found


@pytest.mark.parametrize("source,expected", [
    ("      await speakText(sc.peer_referral)", {"peer_referral"}),
    ("      // await speakText(sc.synthesis_prompt)", set()),
    ("      await speakText(script.synthesis_check.peer_referral)", {"peer_referral"}),
    # Not hardcoded to the one field that happens to be right today.
    ("      await speakText(sc.closing_invitation)", {"closing_invitation"}),
    ("      setCurrentQuestion(sc.forward_roadmap)", set()),
    ("      await speakText(script.closing_message)", set()),
], ids=["spoken", "commented out", "long form", "some other field",
        "shown but not spoken", "not a synthesis field"])
def test_the_walk_reports_a_spoken_field_and_not_a_withdrawn_one(source, expected):
    """Both directions. A one-sided test passes against a walk reporting everything and
    against one reporting nothing."""
    assert spoken_synthesis_fields(source) == expected


def test_the_walk_tells_the_withdrawn_block_from_the_live_line_in_one_pass():
    """The real shape of the file: one live call among four commented-out ones."""
    source = "\n".join([
        "    if (script.synthesis_check) {",
        "      // WITHDRAWN: scripted synthesis check.",
        "      // await speakText(sc.synthesis_prompt)",
        "      await speakText(sc.peer_referral)",
        "      // await speakText(sc.forward_roadmap)",
        "      // if (sc.portfolio_options) { await speakText(sc.portfolio_options) }",
        "    }",
    ])
    assert spoken_synthesis_fields(source) == {"peer_referral"}


def test_every_synthesis_field_the_interview_speaks_is_watched():
    """The guard's allow-list and the runtime must name the same set.

    Wiring `closing_invitation` - which Maya's prompt already describes as spoken - would
    otherwise put a field carrying "here's how I see it" in front of a participant with
    nothing looking at it. This fails on the day that happens, rather than on the day
    somebody is read their own testimony back.
    """
    from api.services.script_assertion_validation import _SPOKEN_SYNTHESIS_FIELDS

    page = Path(__file__).resolve().parents[1] / "ui/src/pages/VoiceInterview.tsx"
    source = page.read_text()
    spoken = spoken_synthesis_fields(source)

    assert spoken, "precondition: the walk found something - a silent walk proves nothing"
    assert spoken == set(_SPOKEN_SYNTHESIS_FIELDS), (
        f"the interview speaks {sorted(spoken)} of synthesis_check while the assertion "
        f"guard watches {sorted(_SPOKEN_SYNTHESIS_FIELDS)}. Decide which is right and "
        f"change both - a spoken field outside the guard is the exact defect this module "
        f"was written for."
    )


def test_the_live_artefact_that_must_not_cry_wolf_yields_nothing():
    """Measured against the real file rather than a fixture, because the whole argument for
    narrowing the field list is a count taken from it.

    `interview_scripts_v38.json` yielded 67 findings across 26 of 86 scripts before this
    change, every one in a field no participant hears, on an artefact the owner has decided
    to keep - so the warner fired on every write for ever. Skipped rather than failed where
    the artefact is not checked out; `projects/` holds two tracked files, so a clean clone
    has none of this.
    """
    live = Path(__file__).resolve().parents[1] / (
        "projects/sp-gs-am/outputs/interview_scripts_v38.json")
    if not live.exists():
        pytest.skip("the live artefact is not in this checkout")
    scripts = json.loads(live.read_text())
    assert len(scripts) > 50, "precondition: this is the whole artefact, not a fragment"
    assert validate_script_assertions(scripts) == []


def test_the_live_artefact_that_carried_the_defects_still_yields_them():
    """The control for the test above, and the one that makes the narrowing safe.

    v37 holds all three real defects: SC-013's Q10.1 "let me offer a synthesis", its
    welcome's "unfiltered", and its closing's "directly into the board". A narrowing that
    silenced v38 by silencing the guard would pass that test and fail this one.
    """
    live = Path(__file__).resolve().parents[1] / (
        "projects/sp-gs-am/outputs/interview_scripts_v37.json")
    if not live.exists():
        pytest.skip("the live artefact is not in this checkout")
    scripts = json.loads(live.read_text())

    summaries = {(s, w, m) for s, w, m in find_asserted_summaries(scripts)}
    assert ("SC-013", "Q10.1.text", "let me offer a synthesis") in summaries

    promises = {(s, w, m) for s, w, m in find_false_handling_promises(scripts)}
    assert ("SC-013", "welcome_message", "unfiltered") in promises
    assert ("SC-013", "closing_message", "directly into the board") in promises
