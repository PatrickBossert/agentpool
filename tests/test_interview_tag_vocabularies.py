# tests/test_interview_tag_vocabularies.py
"""Closed vocabularies, so grouping is a query.

The scripts held 178 distinct section titles and maturity dimensions scoped to a single node
- "Decision Clarity - Strategic Planning & Standards" - so a vertical theme could only be
found by clustering prose.
"""
import pytest

from api.services.interview_script_model import (
    DEFAULT_DISCIPLINES,
    ELICITATIONS,
    QUESTION_INTENTS,
    resolve_tags,
    validate_scripts,
)


def _script(sections) -> dict:
    return {"SC-001": {
        "script_id": "SC-001", "node_id": "1.2", "level": "L2",
        "relationship": "internal", "node_label": "x", "sections": sections,
    }}


def _section(**over) -> dict:
    base = {
        "section_id": "S1", "title": "Governance", "discipline": "governance",
        "question_intent": "evidence", "elicitation": "unprompted",
        "questions": [{"id": "Q1", "text": "..."}],
    }
    base.update(over)
    return base


def test_the_vocabularies_are_closed_and_named():
    assert QUESTION_INTENTS == frozenset(
        {"context", "evidence", "maturity", "challenge", "opportunity"})
    assert ELICITATIONS == frozenset({"unprompted", "prompted"})
    assert "governance" in DEFAULT_DISCIPLINES and "data" in DEFAULT_DISCIPLINES
    assert len(DEFAULT_DISCIPLINES) == 9


def test_a_well_tagged_script_raises_nothing():
    assert validate_scripts(_script([_section()])) == []


def test_a_discipline_off_the_vocabulary_is_refused():
    problems = validate_scripts(_script([_section(discipline="synergy")]),
                                disciplines=DEFAULT_DISCIPLINES)
    assert any("synergy" in p for p in problems)


def test_a_project_may_configure_its_own_disciplines():
    """The list is per project. A discipline valid for one engagement is not for another,
    and hard-coding one vocabulary would make the tag wrong rather than closed."""
    scripts = _script([_section(discipline="hydrology")])
    assert validate_scripts(scripts, disciplines=("hydrology", "governance")) == []


@pytest.mark.parametrize("field,bad", [
    ("question_intent", "probing"),
    ("elicitation", "aided"),
])
def test_an_unknown_intent_or_elicitation_is_refused(field, bad):
    problems = validate_scripts(_script([_section(**{field: bad})]))
    assert any(bad in p for p in problems)


def test_a_question_inherits_its_sections_tags():
    section = _section()
    tags = resolve_tags(section=section, question=section["questions"][0])
    assert tags == {"discipline": "governance", "question_intent": "evidence",
                    "elicitation": "unprompted"}


def test_a_question_may_override_its_sections_discipline():
    section = _section(questions=[{"id": "Q1", "text": "...", "discipline": "data"}])
    tags = resolve_tags(section=section, question=section["questions"][0])
    assert tags["discipline"] == "data"
    # Only what it overrode. Inheriting all three from the section unless every one is
    # restated would make a single override silently blank the other two.
    assert tags["question_intent"] == "evidence"
    assert tags["elicitation"] == "unprompted"


def test_a_section_with_no_discipline_is_refused():
    section = _section()
    del section["discipline"]
    assert any("discipline" in p for p in validate_scripts(_script([section])))


def test_a_section_with_no_questions_still_has_its_tags_checked():
    """Otherwise a section can carry any nonsense so long as it is empty, and the moment a
    question is added to it the tags it inherits are already wrong."""
    section = _section(discipline="synergy", questions=[])
    assert any("synergy" in p for p in validate_scripts(_script([section])))
