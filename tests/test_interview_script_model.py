# tests/test_interview_script_model.py
"""Scripts that can be cited.

`node_label` was the script's own title - "GS UK Internal Audit & Compliance Assessment
Interview" - so no script linked to a node, and question ids were section-relative `Q1.1`,
so all 17 L2 scripts emitted the same ones.
"""
import pytest

from api.services.interview_script_model import (
    LEVELS,
    RELATIONSHIPS,
    question_id,
    validate_script_registry_succession,
    validate_scripts,
    validate_scripts_against_registry,
)

REGISTRY = {"activities": [
    {"id": "0", "label": "SP-GS", "level": "L0", "active": True},
    {"id": "1", "label": "Property", "level": "L1", "active": True},
    {"id": "1.2", "label": "Planned Maintenance", "level": "L2", "active": True},
    {"id": "2", "label": "Fleet", "level": "L1", "active": True},
]}


def _script(script_id="SC-001", node_id="1.2", level="L2", relationship="internal",
            sections=None) -> dict:
    return {
        "script_id": script_id,
        "node_id": node_id,
        "level": level,
        "relationship": relationship,
        "node_label": "Planned Maintenance L2 Interview",
        # Tags are required from the moment the vocabularies exist, so the default fixture
        # carries them - a fixture the write path would refuse proves nothing about it.
        "sections": sections if sections is not None else [
            {"section_id": "S1", "title": "Opening", "discipline": "governance",
             "question_intent": "evidence", "elicitation": "unprompted", "questions": [
                {"id": "Q1", "text": "..."}, {"id": "Q2", "text": "..."},
            ]},
        ],
    }


def _scripts(*items) -> dict:
    return {s["script_id"]: s for s in items}


def test_a_well_formed_set_raises_nothing():
    assert validate_scripts(_scripts(_script())) == []


def test_question_ids_are_unique_across_two_scripts_at_the_same_level():
    """The test the old scheme could not fail. The fixture held one script per level, so
    `Q1.1` never met another `Q1.1` - a property of the sample, not of the scheme. Two L2
    scripts is the smallest fixture that can discriminate."""
    a = _script(script_id="SC-001", node_id="1.2")
    b = _script(script_id="SC-002", node_id="2")
    ids = [question_id(s["script_id"], sec["section_id"], i)
           for s in (a, b) for sec in s["sections"] for i, _ in enumerate(sec["questions"], 1)]
    assert len(ids) == len(set(ids)) == 4


def test_a_question_id_carries_its_script_and_section():
    assert question_id("SC-014", "S3", 2) == "SC-014.S3.Q2"


def test_two_scripts_may_not_share_a_script_id():
    scripts = {"a": _script(script_id="SC-001"), "b": _script(script_id="SC-001")}
    problems = validate_scripts(scripts)
    assert any("SC-001" in p for p in problems)


def test_a_script_with_no_node_id_is_refused():
    s = _script()
    del s["node_id"]
    assert any("node_id" in p for p in validate_scripts(_scripts(s)))


def test_a_section_with_no_id_is_refused():
    """Some live sections carry section_id: null. A theme citing "S1: Strategic Mandate"
    cites a string Maya may rewrite on her next run."""
    s = _script(sections=[{"title": "Opening", "discipline": "governance",
                           "question_intent": "evidence", "elicitation": "unprompted",
                           "questions": [{"id": "Q1", "text": "x"}]}])
    assert any("section_id" in p for p in validate_scripts(_scripts(s)))


def test_two_sections_in_one_script_may_not_share_a_section_id():
    tagged = {"discipline": "governance", "question_intent": "evidence",
              "elicitation": "unprompted"}
    s = _script(sections=[
        {"section_id": "S1", "title": "A", **tagged, "questions": [{"id": "Q1", "text": "x"}]},
        {"section_id": "S1", "title": "B", **tagged, "questions": [{"id": "Q1", "text": "y"}]},
    ])
    assert any("S1" in p for p in validate_scripts(_scripts(s)))


@pytest.mark.parametrize("bad", ["employee", "INTERNAL", "", None])
def test_an_unknown_relationship_is_refused(bad):
    assert any("relationship" in p for p in validate_scripts(_scripts(_script(relationship=bad))))


def test_the_relationship_vocabulary_is_closed():
    assert RELATIONSHIPS == frozenset(
        {"internal", "customer", "regulator", "supplier", "partner"})


def test_every_script_type_is_known():
    assert LEVELS == frozenset({"L0", "L1", "L2", "L3", "C", "A", "F", "S"})


def test_a_script_anchored_to_an_unknown_node_is_refused():
    problems = validate_scripts_against_registry(_scripts(_script(node_id="9.9")), REGISTRY)
    assert any("9.9" in p for p in problems)


def test_an_external_script_anchors_to_the_entity():
    """A regulator regulates the entity and a customer of the entity may sit in another
    company - both are still about node 0."""
    regulator = _script(script_id="SC-010", node_id="0", level="A", relationship="regulator")
    customer = _script(script_id="SC-011", node_id="0", level="C", relationship="customer")
    assert validate_scripts(_scripts(regulator, customer)) == []
    assert validate_scripts_against_registry(_scripts(regulator, customer), REGISTRY) == []


def test_an_empty_registry_blocks_nothing():
    # A first run has no registry, and refusing every script then would block the pipeline.
    assert validate_scripts_against_registry(_scripts(_script(node_id="9.9")), {}) == []


def test_a_script_id_may_not_be_redefined():
    current = {"scripts": [{"id": "SC-001", "node_id": "1.2", "active": True}]}
    proposed = {"scripts": [{"id": "SC-001", "node_id": "2", "active": True}]}
    problems = validate_script_registry_succession(current, proposed)
    assert any("SC-001" in p for p in problems)


def test_a_script_id_may_not_be_dropped():
    """Dropping is worse than redefining: the ledger forgets, and nothing then stops the id
    being handed to something else later, invalidating every stored citation."""
    current = {"scripts": [{"id": "SC-001", "node_id": "1.2", "active": True}]}
    problems = validate_script_registry_succession(current, {"scripts": []})
    assert any("SC-001" in p for p in problems)


def test_retiring_and_growing_are_both_free():
    current = {"scripts": [{"id": "SC-001", "node_id": "1.2", "active": True}]}
    proposed = {"scripts": [
        {"id": "SC-001", "node_id": "1.2", "active": False},
        {"id": "SC-002", "node_id": "2", "active": True},
    ]}
    assert validate_script_registry_succession(current, proposed) == []


def test_a_script_id_may_not_move_to_another_node():
    """The registry says SC-005 is node 1.2. A batch filing it against 2.7 must be refused.

    validate_script_registry_succession already refuses this - on writes to the registry. The
    write that carries the scripts never consulted it, so the batch landed and the merge, which
    keys on script_id, overwrote 1.2's script with 2.7's content.
    """
    from api.services.interview_script_model import validate_scripts_against_script_registry
    registry = {"scripts": [{"id": "SC-005", "node_id": "1.2", "active": True}]}
    scripts = {"SC-005": {"script_id": "SC-005", "node_id": "2.7"}}
    problems = validate_scripts_against_script_registry(scripts, registry)
    assert len(problems) == 1
    assert "SC-005" in problems[0] and "1.2" in problems[0] and "2.7" in problems[0]


def test_an_unregistered_script_id_is_free():
    """Growth is free. A new id is how every script starts."""
    from api.services.interview_script_model import validate_scripts_against_script_registry
    registry = {"scripts": [{"id": "SC-005", "node_id": "1.2", "active": True}]}
    scripts = {"SC-090": {"script_id": "SC-090", "node_id": "3.4"}}
    assert validate_scripts_against_script_registry(scripts, registry) == []


def test_a_registered_id_kept_on_its_own_node_is_free():
    """Re-emitting a script for the node it already serves is a revision, not a move."""
    from api.services.interview_script_model import validate_scripts_against_script_registry
    registry = {"scripts": [{"id": "SC-005", "node_id": "1.2", "active": True}]}
    scripts = {"SC-005": {"script_id": "SC-005", "node_id": "1.2"}}
    assert validate_scripts_against_script_registry(scripts, registry) == []


def test_an_empty_script_registry_accepts_anything():
    """A first run has no registry, and must not be blocked by one it has not written yet."""
    from api.services.interview_script_model import validate_scripts_against_script_registry
    scripts = {"SC-001": {"script_id": "SC-001", "node_id": "0"}}
    assert validate_scripts_against_script_registry(scripts, {}) == []
