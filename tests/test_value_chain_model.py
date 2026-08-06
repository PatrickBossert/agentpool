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
    validate_against_registry,
    validate_contributions_have_tasks,
    validate_registry_succession,
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


# ---------------------------------------------------------------------------
# Alignment: one activity, one column.
#
# Distinct from lane uniqueness, which is about one *party* across many activities. This is
# about one *activity* across many parties. A model can break either alone, and a message
# naming the wrong one sends the reader to the wrong place.
# ---------------------------------------------------------------------------


def _joint_model(columns: dict[str, int]) -> dict:
    """One activity, one party per entry in `columns`, each at the column given."""
    return {
        "model_version": 1,
        "parties": [{"id": p} for p in columns],
        "segments": [{"id": "1", "label": "Property"}],
        "activities": [{"id": "1.1", "segment_id": "1", "label": "Strategy"}],
        "contributions": [
            {"activity_id": "1.1", "party_id": p, "column": c, "attribution": "stated"}
            for p, c in columns.items()
        ],
        "tasks": [],
        "propositions": [],
        "links": [],
    }


def test_two_parties_on_one_activity_may_share_a_column():
    assert validate_model(_joint_model({"GSUK": 10, "ISS": 10})) == []


def test_two_parties_on_one_activity_may_not_sit_in_different_columns():
    problems = validate_model(_joint_model({"GSUK": 40, "ISS": 30}))
    assert len(problems) == 1
    # The reader's next action is to move one of them, so the message has to name which
    # parties and which columns. "activity 1.1 is misaligned" would not be actionable.
    assert "1.1" in problems[0]
    assert "GSUK" in problems[0] and "ISS" in problems[0]
    assert "40" in problems[0] and "30" in problems[0]


def test_a_split_activity_is_reported_once_naming_every_party():
    # Three parties in three columns is one problem, not two or three. A two-party fixture
    # cannot tell "report once per activity" from "report once per extra party".
    problems = validate_model(_joint_model({"GSUK": 10, "ISS": 20, "DXI": 30}))
    assert len(problems) == 1
    assert all(p in problems[0] for p in ("GSUK", "ISS", "DXI"))


def test_alignment_and_lane_uniqueness_are_separate_rules():
    # One party holding two columns in one segment breaks lane uniqueness, not alignment.
    model = _joint_model({"GSUK": 10})
    model["activities"].append({"id": "1.2", "segment_id": "1", "label": "Acquisition"})
    model["contributions"].append(
        {"activity_id": "1.2", "party_id": "GSUK", "column": 10, "attribution": "stated"}
    )
    problems = validate_model(model)
    assert len(problems) == 1
    assert "is split across columns" not in problems[0]


# ---------------------------------------------------------------------------
# The registry as an ID authority.
#
# Every stable ID appearing in both the migrated model and Alex's rebuild was reused for a
# different activity - 14 of 14. The instruction forbidding it has now failed twice, so the
# comparison lives here, pure, and the caller supplies the registry.
# ---------------------------------------------------------------------------


def _registry(*entries: tuple[str, str, str]) -> dict:
    return {
        "schema_version": 2,
        "activities": [
            {"id": i, "label": l, "level": v, "active": True} for i, l, v in entries
        ],
    }


def _named_model() -> dict:
    return {
        "model_version": 1,
        "parties": [{"id": "GSUK"}],
        "segments": [{"id": "1", "label": "Property"}],
        "activities": [{"id": "1.1", "segment_id": "1", "label": "Strategy"}],
        "contributions": [
            {"activity_id": "1.1", "party_id": "GSUK", "column": 10, "attribution": "stated"}
        ],
        "tasks": [{"id": "1.1.1", "activity_id": "1.1", "party_id": "GSUK", "label": "Set it"}],
        "propositions": [],
        "links": [],
    }


def test_a_model_matching_the_registry_has_no_problems():
    registry = _registry(
        ("1", "Property", "L1"), ("1.1", "Strategy", "L2"), ("1.1.1", "Set it", "L3")
    )
    assert validate_against_registry(_named_model(), registry) == []


def test_reusing_an_id_for_a_different_activity_is_refused():
    registry = _registry(
        ("1", "Property", "L1"),
        ("1.1", "Fleet Strategy & Policy Setting", "L2"),
        ("1.1.1", "Set it", "L3"),
    )
    problems = validate_against_registry(_named_model(), registry)
    assert len(problems) == 1
    # Both labels, because the agent's correction is to pick a different id for the new
    # thing - and it cannot do that without being told what the id already means.
    assert "1.1" in problems[0]
    assert "Fleet Strategy & Policy Setting" in problems[0]
    assert "Strategy" in problems[0]


def test_a_genuinely_new_id_is_accepted_so_the_chain_can_grow():
    registry = _registry(
        ("1", "Property", "L1"), ("1.1", "Strategy", "L2"), ("1.1.1", "Set it", "L3")
    )
    model = _named_model()
    model["activities"].append({"id": "1.2", "segment_id": "1", "label": "Acquisition"})
    model["contributions"].append(
        {"activity_id": "1.2", "party_id": "GSUK", "column": 20, "attribution": "stated"}
    )
    assert validate_against_registry(model, registry) == []


def test_an_id_registered_at_another_level_is_refused():
    # "1.1" as an L3 is not the same claim as "1.1" as an L2, and silently accepting it
    # would let a task and an activity share an id.
    registry = _registry(("1", "Property", "L1"), ("1.1", "Strategy", "L3"))
    problems = validate_against_registry(_named_model(), registry)
    assert any("1.1" in p and "L3" in p for p in problems)


def test_an_empty_registry_accepts_anything_so_a_first_run_is_not_blocked():
    assert validate_against_registry(_named_model(), {"activities": []}) == []


def test_a_task_carrying_no_label_is_not_reported_as_renamed():
    # Live tasks carry a description and no label; every registry entry carries a label.
    # Comparing the two reported all 48 tasks of the real model as renamed, against a
    # registry written by the same run. Every fixture in this file gives tasks a label, so
    # only a fixture shaped like the live data can catch it.
    registry = _registry(
        ("1", "Property", "L1"), ("1.1", "Strategy", "L2"), ("1.1.1", "Set it", "L3")
    )
    model = _named_model()
    model["tasks"] = [
        {"id": "1.1.1", "activity_id": "1.1", "party_id": "GSUK", "description": "Set it up"}
    ]
    assert validate_against_registry(model, registry) == []


# ---------------------------------------------------------------------------
# Registry succession.
#
# validate_against_registry is only as good as the ledger it reads, and the agent that
# writes the model can also write the ledger. Run 14 got away with fourteen reused IDs by
# writing a fresh registry: nothing objected, and every later check was then vacuous.
# ---------------------------------------------------------------------------


def test_an_unchanged_registry_is_accepted():
    current = _registry(("1", "Property", "L1"), ("1.1", "Strategy", "L2"))
    assert validate_registry_succession(current, current) == []


def test_adding_an_entry_is_accepted_so_the_chain_can_grow():
    current = _registry(("1", "Property", "L1"))
    proposed = _registry(("1", "Property", "L1"), ("1.1", "Strategy", "L2"))
    assert validate_registry_succession(current, proposed) == []


def test_a_label_change_is_no_longer_refused_here():
    """It used to be, and that contradicted Alex's own brief - "IDs are assigned once and
    are permanent, even if labels are refined". Because he regenerates every label on every
    run, one typographic drift then blocked every future derivation: on 6 August the
    registry stuck at v5 while the tree moved to v12.

    The protection did not go away, it moved and got stronger. DeriveRegistryTool now keeps
    the label an id already carries, so the ledger cannot be rewritten at all (see
    tests/test_derive_registry.py), and tree_validation raises id_redefined for a human
    when the change is more than typographic - asserted here so this test still fails if
    that half is ever removed.
    """
    from api.services.text_stability import is_substantive_change

    current = _registry(("2.1", "Fleet Strategy & Policy Setting", "L2"))
    proposed = _registry(("2.1", "Multi-Year Work Packaging", "L2"))
    assert validate_registry_succession(current, proposed) == []
    assert is_substantive_change(
        "Fleet Strategy & Policy Setting", "Multi-Year Work Packaging"), \
        "a rename this large must still reach a human as a warning"


def test_moving_a_registered_id_to_another_level_is_refused():
    current = _registry(("1.1", "Strategy", "L2"))
    proposed = _registry(("1.1", "Strategy", "L3"))
    problems = validate_registry_succession(current, proposed)
    assert any("1.1" in p and "L2" in p and "L3" in p for p in problems)


def test_dropping_a_registered_id_is_refused_rather_than_silently_forgotten():
    # A dropped id is worse than a redefined one: the ledger forgets the meaning, and
    # nothing then stops the number being handed to something else next time.
    current = _registry(("1.1", "Strategy", "L2"), ("1.2", "Acquisition", "L2"))
    proposed = _registry(("1.1", "Strategy", "L2"))
    problems = validate_registry_succession(current, proposed)
    assert len(problems) == 1
    assert "1.2" in problems[0]
    assert "active" in problems[0]


def test_retiring_an_entry_is_accepted_when_its_meaning_is_kept():
    current = _registry(("1.2", "Acquisition", "L2"))
    proposed = {
        "schema_version": 2,
        "activities": [
            {"id": "1.2", "label": "Acquisition", "level": "L2", "active": False}
        ],
    }
    assert validate_registry_succession(current, proposed) == []


def test_a_first_registry_is_accepted_because_there_is_nothing_to_succeed():
    proposed = _registry(("1", "Property", "L1"))
    assert validate_registry_succession({"activities": []}, proposed) == []


# ---------------------------------------------------------------------------
# Every contribution needs at least one n.n.n activity.
#
# Not every *activity*: those already do, because tasks aggregate across parties. The gap
# is a party whose part is described and decomposed into nothing - 3.1 ISS states a
# contractual obligation to use two named systems and carries no task at all, so nothing
# downstream can interview about it, schedule it, or hold anyone to it.
#
# Enforced on the agent's write path only, not in validate_model. A person adding a party
# in the grid creates a contribution before its tasks exist, and refusing that save would
# make the editor unusable. A person may hold an incomplete state while working; a
# deliverable may not be incomplete.
# ---------------------------------------------------------------------------


def _contribution_model(tasks: list[dict]) -> dict:
    return {
        "model_version": 1,
        "parties": [{"id": "GSUK"}, {"id": "ISS"}],
        "segments": [{"id": "3", "label": "Support Services"}],
        "activities": [{"id": "3.1", "segment_id": "3", "label": "Technology & Digital"}],
        "contributions": [
            {"activity_id": "3.1", "party_id": "GSUK", "column": 10, "attribution": "stated"},
            {"activity_id": "3.1", "party_id": "ISS", "column": 10, "attribution": "stated"},
        ],
        "tasks": tasks,
        "propositions": [],
        "links": [],
    }


def test_a_contribution_with_no_activity_is_reported():
    problems = validate_contributions_have_tasks(
        _contribution_model([{"id": "3.1.1", "activity_id": "3.1", "party_id": "GSUK"}])
    )
    assert len(problems) == 1
    # Names the party and the activity: the agent's correction is to write a task for that
    # contribution, which it cannot do from "a contribution has no tasks".
    assert "3.1" in problems[0] and "ISS" in problems[0]


def test_every_contribution_having_one_is_accepted():
    assert validate_contributions_have_tasks(_contribution_model([
        {"id": "3.1.1", "activity_id": "3.1", "party_id": "GSUK"},
        {"id": "3.1.2", "activity_id": "3.1", "party_id": "ISS"},
    ])) == []


def test_tasks_on_one_party_do_not_cover_another():
    # The real defect: 3.1 had six tasks, all GS UK's, so a check counting tasks per
    # ACTIVITY saw nothing wrong while ISS's obligation was decomposed into nothing.
    problems = validate_contributions_have_tasks(_contribution_model([
        {"id": f"3.1.{n}", "activity_id": "3.1", "party_id": "GSUK"} for n in range(1, 7)
    ]))
    assert len(problems) == 1
    assert "ISS" in problems[0]


def test_the_editor_is_not_held_to_this():
    # validate_model gates the grid's Save, and adding a party creates a contribution
    # before its tasks exist. Holding that path to this rule would refuse the save that
    # created it.
    assert validate_model(_contribution_model([
        {"id": "3.1.1", "activity_id": "3.1", "party_id": "GSUK"}
    ])) == []
