# tests/test_lever_elicitation.py
"""Unaided before prompted, and never the other way round.

Morgan reads the annual report and produces levers as hypotheses. Maya must reference them -
an untested hypothesis reaches value design looking established - and must not reference them
first, because naming a lever buys agreement rather than evidence.
"""
import pytest

from api.services.interview_script_model import (
    lever_status,
    validate_elicitation_order,
    validate_levers_unnamed_in_unaided_sections,
)


def _script(*elicitations, questions=None) -> dict:
    return {"SC-001": {
        "script_id": "SC-001", "node_id": "1.2", "level": "L2", "relationship": "internal",
        "node_label": "x",
        "sections": [
            {
                "section_id": f"S{i}", "title": f"Section {i}", "discipline": "data",
                "question_intent": "evidence", "elicitation": e,
                "questions": questions[i - 1] if questions else [{"id": "Q1", "text": "..."}],
            }
            for i, e in enumerate(elicitations, 1)
        ],
    }}


def test_unaided_then_prompted_is_accepted():
    assert validate_elicitation_order(_script("unprompted", "unprompted", "prompted")) == []


def test_prompted_before_unaided_is_refused():
    """The whole rule, and it is checkable - so it is checked rather than left to an
    instruction Maya may or may not follow."""
    problems = validate_elicitation_order(_script("prompted", "unprompted"))
    assert len(problems) == 1
    assert "S2" in problems[0] or "S1" in problems[0]


def test_an_all_unaided_script_is_accepted():
    # A frontline script may legitimately never prompt. Requiring a prompted section would
    # force one in where it does not belong.
    assert validate_elicitation_order(_script("unprompted", "unprompted")) == []


def test_naming_a_lever_in_an_unaided_section_is_refused():
    """The anchoring this design forbids, in its most direct form: the unaided section is
    unaided in name only if it contains the lever's own words."""
    levers = [{"lever": "Fleet availability", "hypothesis": "..."}]
    scripts = _script("unprompted", questions=[
        [{"id": "Q1", "text": "How well is fleet availability managed here?"}]])
    problems = validate_levers_unnamed_in_unaided_sections(scripts, levers)
    assert any("Fleet availability" in p for p in problems)


def test_naming_a_lever_in_a_prompted_section_is_the_point():
    levers = [{"lever": "Fleet availability", "hypothesis": "..."}]
    scripts = _script("prompted", questions=[
        [{"id": "Q1", "text": "Your annual report names fleet availability - does that match?"}]])
    assert validate_levers_unnamed_in_unaided_sections(scripts, levers) == []


def test_no_levers_blocks_nothing():
    # Morgan may not have run. Refusing every script then would block the pipeline on an
    # upstream artefact that is allowed to be absent.
    assert validate_levers_unnamed_in_unaided_sections(_script("unprompted"), []) == []


LEVER = {"lever": "Fleet availability"}


def _answer(elicitation, supports, text="fleet availability matters"):
    return {"question_text": text, "answer_text": "yes" if supports else "no",
            "elicitation": elicitation, "supports": supports}


@pytest.mark.parametrize("answers,expected", [
    ([], "untested"),
    ([_answer("prompted", True)], "confirmed_prompted"),
    ([_answer("unprompted", True)], "confirmed_unprompted"),
    ([_answer("prompted", False)], "contradicted"),
])
def test_lever_status_is_derived_from_the_answers(answers, expected):
    assert lever_status(LEVER, answers) == expected


def test_an_unprompted_mention_outweighs_a_prompted_agreement():
    """Order-independent. A status that depended on which answer was written last would make
    the strength of the evidence an accident of interview scheduling."""
    a = _answer("prompted", True)
    b = _answer("unprompted", True)
    assert lever_status(LEVER, [a, b]) == "confirmed_unprompted"
    assert lever_status(LEVER, [b, a]) == "confirmed_unprompted"


def test_a_contradiction_outranks_any_confirmation():
    # The finding a reader most needs. Reporting "confirmed" for a lever some interviewee
    # disputed is the failure this status exists to prevent.
    answers = [_answer("unprompted", True), _answer("prompted", False)]
    assert lever_status(LEVER, answers) == "contradicted"


def test_untested_is_reported_rather_than_assumed_absent():
    """The failure nothing can currently see: a lever that reached value design without a
    single interview touching it, looking exactly like an established finding."""
    assert lever_status({"lever": "Carbon reduction"}, [_answer("unprompted", True)]) == "untested"
