# tests/test_value_chain_model.py
"""The model's shape, and what makes it invalid.

Validation is what the grid in a later project depends on: every contribution needs a lane
and a column, every task needs a contribution that exists, and every link needs both ends.
A gap here surfaces now rather than after the grid is built on top of it.
"""
import pytest

from api.services.value_chain_model import (
    COLUMN_STEP,
    MODEL_VERSION,
    contribution_key,
    empty_model,
    next_column,
    validate_model,
)


def _model() -> dict:
    return {
        "model_version": MODEL_VERSION,
        "parties": [
            {"id": "sp-gs", "label": "SP-GS", "colour": "#1a5276"},
            {"id": "iss", "label": "ISS", "colour": "#c0392b"},
        ],
        "segments": [{"id": "1", "label": "PROPERTY", "description": ""}],
        "activities": [
            {"id": "1.1", "segment_id": "1", "label": "Reactive Maintenance",
             "description": "", "active": True}
        ],
        "contributions": [
            {"activity_id": "1.1", "party_id": "sp-gs", "column": 10,
             "description": "", "attribution": "stated"},
            {"activity_id": "1.1", "party_id": "iss", "column": 10,
             "description": "", "attribution": "stated"},
        ],
        "tasks": [
            {"id": "1.1.1", "activity_id": "1.1", "party_id": "sp-gs",
             "label": "Raise works order", "description": "", "active": True}
        ],
        "propositions": [
            {"id": "p1", "activity_id": "1.1", "party_id": None,
             "label": "Paperless works orders", "description": ""}
        ],
        "links": [],
    }


def test_an_empty_model_is_valid():
    assert validate_model(empty_model()) == []


def test_a_complete_model_is_valid():
    assert validate_model(_model()) == []


def test_two_parties_may_occupy_the_same_column():
    """Same activity, same column, different lanes - concurrent delivery. The whole point."""
    assert validate_model(_model()) == []


def test_a_contribution_naming_an_unknown_activity_is_invalid():
    m = _model()
    m["contributions"][0]["activity_id"] = "9.9"
    problems = validate_model(m)
    assert any("9.9" in p for p in problems)


def test_a_contribution_naming_an_unknown_party_is_invalid():
    m = _model()
    m["contributions"][0]["party_id"] = "nobody"
    assert any("nobody" in p for p in validate_model(m))


def test_a_contribution_without_a_column_is_invalid():
    m = _model()
    del m["contributions"][0]["column"]
    assert validate_model(m) != []


def test_one_party_cannot_hold_two_contributions_in_the_same_column():
    """Within a lane, a column holds at most one card - otherwise they overlap."""
    m = _model()
    m["activities"].append({"id": "1.2", "segment_id": "1", "label": "Planned",
                            "description": "", "active": True})
    m["contributions"].append({"activity_id": "1.2", "party_id": "sp-gs", "column": 10,
                               "description": "", "attribution": "stated"})
    assert validate_model(m) != []


def test_a_task_whose_contribution_does_not_exist_is_invalid():
    m = _model()
    m["tasks"][0]["party_id"] = "iss"
    m["contributions"] = [c for c in m["contributions"] if c["party_id"] != "iss"]
    assert validate_model(m) != []


def test_a_link_with_a_missing_endpoint_is_invalid():
    m = _model()
    m["links"].append({"from_activity_id": "1.1", "from_party_id": "sp-gs",
                       "to_activity_id": "9.9", "to_party_id": "iss"})
    assert any("9.9" in p for p in validate_model(m))


def test_an_activity_in_an_unknown_segment_is_invalid():
    m = _model()
    m["activities"][0]["segment_id"] = "7"
    assert any("7" in p for p in validate_model(m))


def test_attribution_must_be_stated_or_derived():
    m = _model()
    m["contributions"][0]["attribution"] = "guessed"
    assert validate_model(m) != []


def test_every_level_accepts_a_description():
    m = _model()
    m["segments"][0]["description"] = "Facilities across 86 locations"
    m["activities"][0]["description"] = "Fixing things when they break"
    m["contributions"][0]["description"] = "Raises and approves the order"
    m["tasks"][0]["description"] = "Via Tririga"
    assert validate_model(m) == []


def test_contribution_key_is_the_composite():
    assert contribution_key("1.1", "sp-gs") == "1.1@sp-gs"


def test_next_column_starts_at_the_step_and_then_advances():
    m = empty_model()
    m["parties"] = [{"id": "sp-gs", "label": "SP-GS", "colour": "#1a5276"}]
    m["segments"] = [{"id": "1", "label": "PROPERTY", "description": ""}]
    assert next_column(m, "1", "sp-gs") == COLUMN_STEP

    m["activities"] = [{"id": "1.1", "segment_id": "1", "label": "A",
                        "description": "", "active": True}]
    m["contributions"] = [{"activity_id": "1.1", "party_id": "sp-gs", "column": 40,
                           "description": "", "attribution": "stated"}]
    assert next_column(m, "1", "sp-gs") == 50


def test_next_column_is_per_lane_not_per_segment():
    """ISS starting fresh gets the first column even though SP-GS is at 40."""
    m = empty_model()
    m["parties"] = [
        {"id": "sp-gs", "label": "SP-GS", "colour": "#1a5276"},
        {"id": "iss", "label": "ISS", "colour": "#c0392b"},
    ]
    m["segments"] = [{"id": "1", "label": "PROPERTY", "description": ""}]
    m["activities"] = [{"id": "1.1", "segment_id": "1", "label": "A",
                        "description": "", "active": True}]
    m["contributions"] = [{"activity_id": "1.1", "party_id": "sp-gs", "column": 40,
                           "description": "", "attribution": "stated"}]
    assert next_column(m, "1", "iss") == COLUMN_STEP
