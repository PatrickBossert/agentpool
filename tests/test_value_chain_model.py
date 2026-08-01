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
    """Same activity, same column, different lanes - concurrent delivery. The whole point.

    Starts from one party's contribution, then adds a second party at the same column, and
    checks the model stays valid at each step. This would fail if the uniqueness key ever
    dropped the party and started comparing columns alone.
    """
    m = empty_model()
    m["parties"] = [{"id": "sp-gs", "label": "SP-GS", "colour": "#1a5276"}]
    m["segments"] = [{"id": "1", "label": "PROPERTY", "description": ""}]
    m["activities"] = [{"id": "1.1", "segment_id": "1", "label": "A",
                        "description": "", "active": True}]
    m["contributions"] = [
        {"activity_id": "1.1", "party_id": "sp-gs", "column": 10,
         "description": "", "attribution": "stated"},
    ]
    assert validate_model(m) == []

    m["parties"].append({"id": "iss", "label": "ISS", "colour": "#c0392b"})
    m["contributions"].append(
        {"activity_id": "1.1", "party_id": "iss", "column": 10,
         "description": "", "attribution": "stated"}
    )
    assert validate_model(m) == []


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


def test_a_contribution_with_two_defects_reports_both():
    """Independent checks - an unknown party must not swallow an invalid attribution."""
    m = _model()
    m["contributions"][0]["party_id"] = "nobody"
    m["contributions"][0]["attribution"] = "guessed"
    problems = validate_model(m)
    assert any("nobody" in p for p in problems)
    assert any("guessed" in p for p in problems)


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


def test_an_activity_with_no_contribution_is_a_problem():
    """Such an activity appears in no lane, so it vanishes from the grid while staying in
    model["activities"] - and nothing in the UI can bring it back. It validates cleanly
    today, which is what makes it a trap rather than an error."""
    model = empty_model()
    model["segments"] = [{"id": "1", "label": "Segment"}]
    model["parties"] = [{"id": "sp", "label": "SP-GS"}]
    model["activities"] = [
        {"id": "1.1", "segment_id": "1", "label": "Has one"},
        {"id": "1.2", "segment_id": "1", "label": "Has none"},
    ]
    model["contributions"] = [
        {"activity_id": "1.1", "party_id": "sp", "column": 10, "attribution": "stated"},
    ]

    problems = validate_model(model)

    assert any("1.2" in p and "no contribution" in p for p in problems)
    assert not any("1.1" in p for p in problems)


def test_an_empty_model_is_still_valid():
    """The rule must not fire on a model with no activities at all - that is the state a
    fresh project is in, and empty_model() is what the store writes first."""
    assert validate_model(empty_model()) == []


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


def test_a_collision_names_every_activity_in_the_cell():
    """A person reading this next has to go and move those activities, so the message
    has to say which. The old wording named none of them."""
    model = empty_model()
    model["segments"] = [{"id": "1", "label": "Segment"}]
    model["parties"] = [{"id": "sp", "label": "SP-GS"}]
    model["activities"] = [
        {"id": "1.1", "segment_id": "1", "label": "A"},
        {"id": "1.2", "segment_id": "1", "label": "B"},
        {"id": "1.3", "segment_id": "1", "label": "C"},
    ]
    model["contributions"] = [
        {"activity_id": a, "party_id": "sp", "column": 10, "attribution": "stated"}
        for a in ("1.1", "1.2", "1.3")
    ]

    problems = validate_model(model)

    collision = [p for p in problems if "column 10" in p]
    assert len(collision) == 1, f"expected one message for one cell, got {collision}"
    for activity in ("1.1", "1.2", "1.3"):
        assert activity in collision[0]


def test_two_separate_collisions_are_two_problems():
    """One message per over-occupied cell, not one per model.

    One cell holds three contributions, not two: with exactly two occupants per cell, the
    old "append on the second occupant" logic also produces one message per cell, so it
    cannot tell the fix apart from the bug it replaces. A third occupant in one cell makes
    the old logic append twice for that cell alone, giving three messages overall instead
    of two.
    """
    model = empty_model()
    model["segments"] = [{"id": "1", "label": "Segment"}]
    model["parties"] = [{"id": "sp", "label": "SP-GS"}, {"id": "iss", "label": "ISS"}]
    model["activities"] = [
        {"id": f"1.{n}", "segment_id": "1", "label": str(n)} for n in range(1, 6)
    ]
    model["contributions"] = [
        {"activity_id": "1.1", "party_id": "sp", "column": 10, "attribution": "stated"},
        {"activity_id": "1.2", "party_id": "sp", "column": 10, "attribution": "stated"},
        {"activity_id": "1.3", "party_id": "sp", "column": 10, "attribution": "stated"},
        {"activity_id": "1.4", "party_id": "iss", "column": 20, "attribution": "stated"},
        {"activity_id": "1.5", "party_id": "iss", "column": 20, "attribution": "stated"},
    ]

    problems = validate_model(model)

    assert len([p for p in problems if "occupy" in p]) == 2


def test_a_valid_model_reports_no_collision():
    """The positive anchor - without it, reporting nothing ever would pass the tests above."""
    model = empty_model()
    model["segments"] = [{"id": "1", "label": "Segment"}]
    model["parties"] = [{"id": "sp", "label": "SP-GS"}]
    model["activities"] = [
        {"id": "1.1", "segment_id": "1", "label": "A"},
        {"id": "1.2", "segment_id": "1", "label": "B"},
    ]
    model["contributions"] = [
        {"activity_id": "1.1", "party_id": "sp", "column": 10, "attribution": "stated"},
        {"activity_id": "1.2", "party_id": "sp", "column": 20, "attribution": "stated"},
    ]

    assert validate_model(model) == []


def test_collision_names_activities_in_numeric_not_lexical_order():
    """"5.9" must sort before "5.10" - a plain string sort would place "5.10" first, in a
    message whose whole purpose is helping someone find and move those activities."""
    model = empty_model()
    model["segments"] = [{"id": "5", "label": "Segment"}]
    model["parties"] = [{"id": "sp", "label": "SP-GS"}]
    model["activities"] = [
        {"id": "5.9", "segment_id": "5", "label": "Nine"},
        {"id": "5.10", "segment_id": "5", "label": "Ten"},
    ]
    model["contributions"] = [
        {"activity_id": a, "party_id": "sp", "column": 10, "attribution": "stated"}
        for a in ("5.10", "5.9")
    ]

    problems = validate_model(model)

    collision = [p for p in problems if "occupy" in p]
    assert len(collision) == 1
    assert collision[0].index("5.9") < collision[0].index("5.10")


def test_the_real_agent_written_model_reports_its_five_way_collision():
    """The model that prompted this work. Five activities on one column in segment 5."""
    from pathlib import Path
    import json

    path = Path("projects/sp-gs-am/outputs/value_chain_model_v2.json")
    if not path.exists():
        pytest.skip("sp-gs-am fixtures not present in this checkout")

    problems = validate_model(json.loads(path.read_text()))

    collision = [p for p in problems if "occupy" in p]
    assert len(collision) == 1
    for activity in ("5.1", "5.2", "5.3", "5.4", "5.5"):
        assert activity in collision[0]
