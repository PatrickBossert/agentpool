# tests/test_theme_evidence_validation.py
"""A theme's evidence must say who it came from, in the fields that mean those things.

The first real themes artefact - run 39, three interviews, 229 answers - put the **relationship**
in `stakeholder_id` on **68 of 68** evidence rows: `"1.F"` where the answer's own stakeholder is
`10`. The agent was right and the schema was wrong, so `relationship` was added rather than the
agent corrected. This validator exists because that same run proves prose in a prompt does not
hold a schema on its own.

Every property is driven **both ways**. "A defective entry is reported" is satisfied by a
validator that reports everything; "a correct entry is not" by one that reports nothing.
"""
from __future__ import annotations

import pytest

from api.services.theme_evidence_validation import (
    find_evidence_defects,
    validate_theme_evidence,
)

# answer_id -> the stakeholder on that answer's own row
CORPUS = {812: 10, 813: 4, 814: 1}


def _theme(evidence: list[dict], theme_id: str = "TH-01") -> list[dict]:
    return [{"id": theme_id, "theme": "t", "kind": "vertical", "anchors": ["0"],
             "evidence": evidence}]


def _codes(themes, corpus=CORPUS) -> set[str]:
    return {code for _, code, _ in find_evidence_defects(themes, corpus)}


# ── The shape that is correct ─────────────────────────────────────────────────

def test_a_well_formed_entry_is_not_reported():
    """The control. Without it, a validator that flagged everything would pass every test below."""
    good = _theme([{"answer_id": 812, "stakeholder_id": 10, "relationship": "1.F", "quote": "q"}])
    assert find_evidence_defects(good, CORPUS) == []
    assert validate_theme_evidence(good, CORPUS) == []


def test_the_wrapped_array_shape_is_read_too():
    """An agent sometimes answers `{"themes": [...]}` rather than a bare array.

    Asserted because a validator that silently saw nothing in the wrapper would report a clean
    bill of health on every write - the worst way for this to fail.
    """
    good = {"themes": _theme(
        [{"answer_id": 812, "stakeholder_id": 10, "relationship": "1.F", "quote": "q"}])}
    bad = {"themes": _theme(
        [{"answer_id": 812, "stakeholder_id": "1.F", "relationship": "1.F", "quote": "q"}])}
    assert find_evidence_defects(good, CORPUS) == []
    assert _codes(bad) == {"stakeholder_id_not_an_integer"}


# ── The defect this was written for ───────────────────────────────────────────

def test_the_relationship_in_the_stakeholder_field_is_reported():
    """Verbatim what run 39 produced, 68 times."""
    themes = _theme([{"answer_id": 812, "stakeholder_id": "1.F", "quote": "q"}])
    assert _codes(themes) == {"stakeholder_id_not_an_integer", "no_relationship"}


def test_an_integer_that_is_not_the_answers_own_is_reported():
    """The subtler half: a plausible integer that belongs to somebody else.

    `stakeholder_id_not_an_integer` cannot catch this, so the two checks are separate rather
    than one 'is it valid' test - a type check would have passed this row.
    """
    themes = _theme([{"answer_id": 812, "stakeholder_id": 4, "relationship": "1.F", "quote": "q"}])
    assert _codes(themes) == {"stakeholder_id_disagrees"}


def test_a_missing_relationship_is_reported_even_when_the_ids_are_right():
    themes = _theme([{"answer_id": 812, "stakeholder_id": 10, "quote": "q"}])
    assert _codes(themes) == {"no_relationship"}


def test_an_invented_answer_id_is_reported():
    """Run 39 invented none of 68, which is worth keeping true."""
    themes = _theme([{"answer_id": 99999, "stakeholder_id": 10, "relationship": "1.F"}])
    assert _codes(themes) == {"unknown_answer"}


def test_a_boolean_is_not_an_integer_stakeholder():
    """`True` is an `int` in Python, so an `isinstance` check alone lets it through."""
    themes = _theme([{"answer_id": 812, "stakeholder_id": True, "relationship": "1.F"}])
    assert "stakeholder_id_not_an_integer" in _codes(themes)


# ── How it reports ────────────────────────────────────────────────────────────

def test_one_warning_per_code_however_many_rows_carry_it():
    """68 identical findings is a warner somebody turns off, taking its siblings with it."""
    themes = _theme([
        {"answer_id": 812, "stakeholder_id": "1.F", "relationship": "1.F"},
        {"answer_id": 813, "stakeholder_id": "0.A", "relationship": "0.A"},
        {"answer_id": 814, "stakeholder_id": "1.C", "relationship": "1.C"},
    ])
    warnings = validate_theme_evidence(themes, CORPUS)
    assert [w["code"] for w in warnings] == ["stakeholder_id_not_an_integer"]
    assert "3 evidence entries" in warnings[0]["message"]


def test_an_unreadable_corpus_still_checks_what_it_can():
    """The id checks need the corpus; the `relationship` check does not.

    Driven because the warner passes `{}` when the project database cannot be read, and a
    validator that gave up entirely there would report a clean bill of health on a write it
    had not examined.
    """
    themes = _theme([{"answer_id": 812, "stakeholder_id": 10, "quote": "q"}])
    assert _codes(themes, corpus={}) == {"no_relationship"}


@pytest.mark.parametrize("themes", [None, [], {}, "text", {"themes": []}, [{"id": "TH-01"}]])
def test_nothing_to_examine_is_not_a_defect(themes):
    """A warner must never be the thing that fails a write."""
    assert validate_theme_evidence(themes, CORPUS) == []
