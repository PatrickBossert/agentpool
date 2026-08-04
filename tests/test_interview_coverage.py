# tests/test_interview_coverage.py
"""Coverage is a query over stored anchors, not a judgement about job titles."""
from api.services.interview_coverage import coverage

REGISTRY = {"activities": [
    {"id": "0", "label": "SP-GS", "level": "L0", "active": True},
    {"id": "1", "label": "Property", "level": "L1", "active": True},
    {"id": "1.2", "label": "Planned Maintenance", "level": "L2", "active": True},
    {"id": "9", "label": "Retired chain", "level": "L1", "active": False},
]}


def _answer(node_id, relationship="internal"):
    return {"node_id": node_id, "relationship": relationship, "answered": 1}


def test_a_node_with_an_answer_is_covered():
    rows = {r["node_id"]: r for r in coverage(REGISTRY, [_answer("1.2")])}
    assert rows["1.2"]["covered"] is True


def test_an_entity_anchored_interview_does_not_cover_the_chains():
    """The rule this whole anchoring scheme depends on. An auditor speaking about the
    organisation says nothing about any particular stage, and counting it as chain coverage
    would report a fully covered value chain nobody had been interviewed about."""
    rows = {r["node_id"]: r for r in coverage(REGISTRY, [_answer("0", "regulator")])}
    assert rows["0"]["covered"] is True
    assert rows["1"]["covered"] is False
    assert rows["1.2"]["covered"] is False


def test_a_stage_interview_does_not_cover_the_entity_either():
    """No inheritance in either direction. Interviewing every process manager says nothing
    about what the board thinks it is doing."""
    rows = {r["node_id"]: r for r in coverage(REGISTRY, [_answer("1.2")])}
    assert rows["0"]["covered"] is False


def test_coverage_distinguishes_relationships():
    rows = {r["node_id"]: r for r in coverage(REGISTRY, [_answer("0", "internal")])}
    assert rows["0"]["relationships"] == {"internal"}
    # Covered by staff and by nobody outside: a different state from covered outright, and
    # a single boolean cannot say so.
    assert "customer" not in rows["0"]["relationships"]


def test_an_unanswered_question_does_not_count_as_coverage():
    """A blank row records that the question was asked. Treating it as coverage would report
    a node as covered because someone opened the session and said nothing."""
    rows = {r["node_id"]: r for r in coverage(REGISTRY, [{**_answer("1.2"), "answered": 0}])}
    assert rows["1.2"]["covered"] is False


def test_retired_nodes_are_not_reported_as_gaps():
    # A retired node reported as uncovered is a gap nobody can ever close, and it makes the
    # real gaps harder to see.
    assert not any(r["node_id"] == "9" for r in coverage(REGISTRY, []))


def test_every_active_node_appears_even_with_no_answers():
    """A node absent from the report reads as covered. Listing every node with zero answers
    explicitly is the difference between a coverage report and a list of what went well."""
    rows = coverage(REGISTRY, [])
    assert {r["node_id"] for r in rows} == {"0", "1", "1.2"}
    assert all(r["covered"] is False for r in rows)
