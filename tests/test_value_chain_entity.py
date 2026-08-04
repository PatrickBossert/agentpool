# tests/test_value_chain_entity.py
"""The L0 entity: the organisation itself, as a node.

A regulator regulates the entity and a customer of the entity may sit in another company
entirely, so neither has a position in any value chain. Without a node to anchor to, their
interview scripts have no position at all - which is why every A and C script today names
itself rather than a node.
"""
from api.services.value_chain_model import (
    ENTITY_ID,
    validate_against_registry,
    validate_entity,
    validate_has_entity,
)


def _model(**over) -> dict:
    base = {
        "entity": {"id": "0", "label": "SP-GS", "description": "The organisation."},
        "segments": [{"id": "1", "label": "Property", "description": "d"}],
        "parties": [], "activities": [], "contributions": [], "tasks": [],
        "propositions": [], "links": [],
    }
    base.update(over)
    return base


def test_the_reserved_id_is_the_string_zero():
    # Pinned because everything else joins on it. An int 0 would compare unequal to every
    # registry entry, which are strings, and fail silently rather than loudly.
    assert ENTITY_ID == "0"


def test_a_valid_entity_raises_nothing():
    assert validate_entity(_model()) == []


def test_an_entity_with_the_wrong_id_is_refused():
    problems = validate_entity(_model(entity={"id": "L0", "label": "SP-GS"}))
    assert len(problems) == 1
    assert "0" in problems[0]


def test_a_value_chain_may_not_take_the_reserved_id():
    """The collision that matters: a chain numbered 0 makes every anchor ambiguous, and
    nothing downstream could tell an entity-level interview from a chain-level one."""
    problems = validate_entity(_model(segments=[{"id": "0", "label": "Property"}]))
    assert len(problems) == 1
    assert "reserved" in problems[0]


def test_a_model_with_no_entity_still_validates_for_the_editor():
    """Every existing model lacks one. Refusing them in validate_model would refuse to save
    any project until its chain was rebuilt."""
    model = _model()
    del model["entity"]
    assert validate_entity(model) == []


def test_but_a_deliverable_without_an_entity_is_incomplete():
    # The agent write path holds a stricter rule than the editor, exactly as
    # validate_contributions_have_tasks already does.
    model = _model()
    del model["entity"]
    assert len(validate_has_entity(model)) == 1
    assert validate_has_entity(_model()) == []


def test_the_registry_check_covers_the_entity_too():
    """Without this the entity is the one node whose id could be silently redefined - the
    three arrays are checked and a dict is not an array."""
    registry = {"activities": [{"id": "0", "label": "SP-GS", "level": "L0", "active": True}]}
    clean = validate_against_registry(_model(), registry)
    assert clean == []

    renamed = _model(entity={"id": "0", "label": "Something Else"})
    problems = validate_against_registry(renamed, registry)
    assert len(problems) == 1
    assert "SP-GS" in problems[0]


def test_the_entity_id_registered_at_another_level_is_refused():
    # id 0 arriving as an L1 is the same defect the three arrays already catch.
    registry = {"activities": [{"id": "0", "label": "Property", "level": "L1", "active": True}]}
    problems = validate_against_registry(_model(segments=[]), registry)
    assert any("L1" in p for p in problems)
