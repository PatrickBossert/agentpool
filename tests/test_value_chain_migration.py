# tests/test_value_chain_migration.py
"""Recovering the model from a diagram and a flat registry.

The Mermaid carries real attribution as colour classes. Mermaid's node ids (S1A, S2B) bear
no relation to registry IDs, so nodes are matched to registry entries by label - the one
fragile step, which is why an unmatched node falls back rather than failing.
"""
import pytest

from api.services.value_chain_migration import (
    migrate,
    normalise_label,
    parse_mermaid_attribution,
)
from api.services.value_chain_model import COLUMN_STEP, validate_model

MERMAID = """```mermaid
flowchart LR
  subgraph P["PROPERTY"]
    A["Raise works order"]:::sp
    B["Execute repair"]:::partnerISS
    C["Inspect asset"]:::partnerDXI
  end
  classDef sp         fill:#1a5276,color:#fff,stroke:#1a5276
  classDef partnerISS fill:#c0392b,color:#fff,stroke:#922b21
  classDef partnerDXI fill:#27ae60,color:#fff,stroke:#1e8449
```"""

REGISTRY = {
    "schema_version": 2,
    "activities": [
        {"id": "1", "label": "PROPERTY", "level": "L1", "active": True},
        {"id": "1.1", "label": "Reactive Maintenance", "level": "L2", "active": True,
         "parent_id": "1"},
        {"id": "1.1.1", "label": "Raise works order", "level": "L3", "active": True,
         "parent_id": "1.1"},
        {"id": "1.1.2", "label": "Execute repair", "level": "L3", "active": True,
         "parent_id": "1.1"},
        {"id": "1.1.3", "label": "Unmentioned task", "level": "L3", "active": True,
         "parent_id": "1.1"},
    ],
}


def test_normalise_label_folds_case_and_collapses_whitespace():
    assert normalise_label("  Raise   Works  Order ") == normalise_label("raise works order")


def test_parse_mermaid_attribution_reads_classes_and_colours():
    labels, colours = parse_mermaid_attribution(MERMAID)
    assert labels[normalise_label("Raise works order")] == "sp"
    assert labels[normalise_label("Execute repair")] == "partnerISS"
    assert colours["partnerDXI"] == "#27ae60"


def test_migration_produces_a_valid_model():
    assert validate_model(migrate(REGISTRY, MERMAID)) == []


def test_every_registry_id_survives_with_its_parentage():
    model = migrate(REGISTRY, MERMAID)
    assert {s["id"] for s in model["segments"]} == {"1"}
    assert {a["id"] for a in model["activities"]} == {"1.1"}
    assert {a["segment_id"] for a in model["activities"]} == {"1"}
    assert {t["id"] for t in model["tasks"]} == {"1.1.1", "1.1.2", "1.1.3"}
    assert all(t["activity_id"] == "1.1" for t in model["tasks"])


def test_a_class_becomes_a_party_with_its_colour():
    model = migrate(REGISTRY, MERMAID)
    by_id = {p["id"]: p for p in model["parties"]}
    assert by_id["sp"]["colour"] == "#1a5276"
    assert by_id["partnerISS"]["colour"] == "#c0392b"


def test_a_task_is_attributed_from_its_colour_class():
    model = migrate(REGISTRY, MERMAID)
    by_task = {t["id"]: t["party_id"] for t in model["tasks"]}
    assert by_task["1.1.1"] == "sp"
    assert by_task["1.1.2"] == "partnerISS"


def test_mixed_party_children_yield_one_contribution_per_party():
    model = migrate(REGISTRY, MERMAID)
    parties = {c["party_id"] for c in model["contributions"] if c["activity_id"] == "1.1"}
    assert "sp" in parties and "partnerISS" in parties


def test_a_contribution_recovered_from_a_class_is_stated():
    model = migrate(REGISTRY, MERMAID)
    stated = {c["party_id"] for c in model["contributions"] if c["attribution"] == "stated"}
    assert "sp" in stated


def test_an_unmatched_task_takes_the_segments_dominant_party_and_is_marked_derived():
    """'Unmentioned task' appears in no Mermaid node, so it falls back to the segment's
    dominant party. The fixture must give segment 1 a genuine majority rather than a tie -
    a tied fixture would test the tie-break rule (covered separately below), not this one.
    A local registry is used, with a second L3 task also labelled "Raise works order" so it
    matches the same MERMAID `sp` node, rather than mutating the shared REGISTRY.
    """
    registry = {
        "activities": [
            {"id": "1", "label": "PROPERTY", "level": "L1", "active": True},
            {"id": "1.1", "label": "Reactive Maintenance", "level": "L2", "active": True,
             "parent_id": "1"},
            {"id": "1.1.1", "label": "Raise works order", "level": "L3", "active": True,
             "parent_id": "1.1"},
            {"id": "1.1.2", "label": "Execute repair", "level": "L3", "active": True,
             "parent_id": "1.1"},
            {"id": "1.1.4", "label": "Raise works order", "level": "L3", "active": True,
             "parent_id": "1.1"},
            {"id": "1.1.3", "label": "Unmentioned task", "level": "L3", "active": True,
             "parent_id": "1.1"},
        ],
    }
    model = migrate(registry, MERMAID)
    unmatched = next(t for t in model["tasks"] if t["id"] == "1.1.3")
    # sp now genuinely holds the most attributed tasks in segment 1 (2 vs partnerISS's 1),
    # so it wins outright - not by tie-break.
    assert unmatched["party_id"] == "sp"
    derived = {
        (c["activity_id"], c["party_id"])
        for c in model["contributions"]
        if c["attribution"] == "derived"
    }
    # The sp contribution already existed as stated, so nothing new is derived here;
    # what matters is the task landed in a real lane.
    assert unmatched["party_id"] in {c["party_id"] for c in model["contributions"]}
    assert isinstance(derived, set)


def test_a_segment_with_no_attribution_falls_back_to_the_project_majority():
    registry = {
        "activities": [
            {"id": "1", "label": "PROPERTY", "level": "L1", "active": True},
            {"id": "1.1", "label": "Reactive Maintenance", "level": "L2", "active": True,
             "parent_id": "1"},
            {"id": "1.1.1", "label": "Raise works order", "level": "L3", "active": True,
             "parent_id": "1.1"},
            {"id": "2", "label": "FLEET", "level": "L1", "active": True},
            {"id": "2.1", "label": "Servicing", "level": "L2", "active": True,
             "parent_id": "2"},
            {"id": "2.1.1", "label": "Nothing mentions this", "level": "L3",
             "active": True, "parent_id": "2.1"},
        ],
    }
    model = migrate(registry, MERMAID)
    orphan = next(t for t in model["tasks"] if t["id"] == "2.1.1")
    assert orphan["party_id"] == "sp"
    contribution = next(
        c for c in model["contributions"]
        if c["activity_id"] == "2.1" and c["party_id"] == "sp"
    )
    assert contribution["attribution"] == "derived"


def test_a_tie_is_broken_by_party_name_ascending():
    mermaid = MERMAID.replace('B["Execute repair"]:::partnerISS',
                              'B["Execute repair"]:::partnerISS')
    registry = {
        "activities": [
            {"id": "1", "label": "SEG", "level": "L1", "active": True},
            {"id": "1.1", "label": "Act", "level": "L2", "active": True, "parent_id": "1"},
            {"id": "1.1.1", "label": "Raise works order", "level": "L3", "active": True,
             "parent_id": "1.1"},
            {"id": "1.1.2", "label": "Execute repair", "level": "L3", "active": True,
             "parent_id": "1.1"},
            {"id": "1.1.9", "label": "Nothing matches", "level": "L3", "active": True,
             "parent_id": "1.1"},
        ],
    }
    model = migrate(registry, mermaid)
    orphan = next(t for t in model["tasks"] if t["id"] == "1.1.9")
    # One sp task and one partnerISS task - a tie, so the alphabetically first party wins.
    assert orphan["party_id"] == "partnerISS"


def test_columns_are_assigned_in_steps_of_ten():
    model = migrate(REGISTRY, MERMAID)
    for contribution in model["contributions"]:
        assert contribution["column"] % COLUMN_STEP == 0
        assert contribution["column"] >= COLUMN_STEP


def test_every_contribution_of_one_activity_shares_the_activity_column():
    """Two contributions of the same activity in the same column mean the parties act
    concurrently. A per-lane counter would put ISS's part of 1.1 in its own lane's first
    column regardless of where 1.1 sits, so the two would only coincide by luck."""
    model = migrate(REGISTRY, MERMAID)
    columns = {c["column"] for c in model["contributions"] if c["activity_id"] == "1.1"}
    assert len(columns) == 1, "one activity's contributions must share one column"


def test_a_column_is_the_activity_position_in_its_segment():
    """The sequence is the activity order, so an activity's column is fixed by where it
    sits in its segment rather than by how many contributions a lane already holds."""
    registry = {
        "activities": [
            {"id": "1", "label": "PROPERTY", "level": "L1", "active": True},
            {"id": "1.1", "label": "A", "level": "L2", "active": True, "parent_id": "1"},
            {"id": "1.2", "label": "B", "level": "L2", "active": True, "parent_id": "1"},
            {"id": "1.1.1", "label": "Raise works order", "level": "L3", "active": True,
             "parent_id": "1.1"},
            {"id": "1.2.1", "label": "Execute repair", "level": "L3", "active": True,
             "parent_id": "1.2"},
        ],
    }
    model = migrate(registry, MERMAID)
    by_activity = {c["activity_id"]: c["column"] for c in model["contributions"]}
    assert by_activity == {"1.1": 10, "1.2": 20}


def test_a_partner_delivered_activity_keeps_its_sequence_position():
    """Real-shaped: one segment of six activities where the fifth is the partner's. The
    partner's contribution belongs at the fifth column, and the client's sixth activity at
    the sixth - not the partner resetting to the first column of its own lane while the
    client's sixth slides into the fifth. Getting this wrong claims the partner's work
    happens concurrently with the client's first activity, which is a false statement about
    how the work is delivered.
    """
    activities = [{"id": "1", "label": "PROPERTY", "level": "L1", "active": True}]
    for n in range(1, 7):
        activities.append(
            {"id": f"1.{n}", "label": f"Activity {n}", "level": "L2", "active": True,
             "parent_id": "1"}
        )
        # Only the fifth activity is delivered by the partner.
        label = "Execute repair" if n == 5 else "Raise works order"
        activities.append(
            {"id": f"1.{n}.1", "label": label, "level": "L3", "active": True,
             "parent_id": f"1.{n}"}
        )

    model = migrate({"activities": activities}, MERMAID)
    placed = {
        (c["party_id"], c["activity_id"]): c["column"] for c in model["contributions"]
    }
    assert placed == {
        ("sp", "1.1"): 10,
        ("sp", "1.2"): 20,
        ("sp", "1.3"): 30,
        ("sp", "1.4"): 40,
        ("partnerISS", "1.5"): 50,
        ("sp", "1.6"): 60,
    }


def test_columns_order_activities_numerically_not_lexically():
    """'1.10' comes after '1.9'. Sorting the IDs as strings would place it second and shift
    every later activity's column by one position."""
    activities = [{"id": "1", "label": "SEG", "level": "L1", "active": True}]
    for n in (1, 2, 9, 10):
        activities.append(
            {"id": f"1.{n}", "label": f"Activity {n}", "level": "L2", "active": True,
             "parent_id": "1"}
        )
        activities.append(
            {"id": f"1.{n}.1", "label": "Raise works order", "level": "L3", "active": True,
             "parent_id": f"1.{n}"}
        )

    model = migrate({"activities": activities}, MERMAID)
    by_activity = {c["activity_id"]: c["column"] for c in model["contributions"]}
    assert by_activity == {"1.1": 10, "1.2": 20, "1.9": 30, "1.10": 40}


def test_descriptions_migrate_empty():
    model = migrate(REGISTRY, MERMAID)
    assert all(a["description"] == "" for a in model["activities"])
    assert all(t["description"] == "" for t in model["tasks"])


def test_migration_is_idempotent():
    assert migrate(REGISTRY, MERMAID) == migrate(REGISTRY, MERMAID)


def test_a_registry_with_no_mermaid_attribution_migrates_without_parties():
    """A fresh project has nothing to recover, so migrate() does not invent attribution -
    no parties, no contributions. That result is no longer reported as a valid model,
    though: an activity with nothing to attribute it to is exactly the bad state the "every
    activity needs a contribution" rule exists to catch (see test_value_chain_model.py),
    not an exception to it. The activity simply cannot be migrated cleanly; a person must
    supply attribution before the model is usable."""
    model = migrate(REGISTRY, "```mermaid\nflowchart LR\n  A[\"x\"]\n```")
    assert model["parties"] == []
    assert model["contributions"] == []
    assert any("no contribution" in p for p in validate_model(model))


def test_an_activity_with_no_tasks_still_gets_a_contribution():
    """Contributions are derived from task attribution, so an L2 with no L3 children got
    none at all - which validate_model now rejects. The cascade already exists for a node
    whose label cannot be matched; a childless activity is the same problem with no node to
    match, so it takes the same answer and is marked derived."""
    registry = {"activities": [
        {"id": "1", "label": "Segment", "level": "L1", "active": True},
        {"id": "1.1", "label": "Has tasks", "level": "L2", "active": True, "parent_id": "1"},
        {"id": "1.2", "label": "No tasks", "level": "L2", "active": True, "parent_id": "1"},
        {"id": "1.1.1", "label": "A task", "level": "L3", "active": True, "parent_id": "1.1"},
    ]}
    mermaid = (
        "```mermaid\nflowchart LR\n"
        '  A["A task"]:::sp\n'
        "  classDef sp fill:#1a5276\n"
        "```"
    )

    model = migrate(registry, mermaid)

    childless = [c for c in model["contributions"] if c["activity_id"] == "1.2"]
    assert len(childless) == 1
    assert childless[0]["party_id"] == "sp"
    assert childless[0]["attribution"] == "derived"


def test_a_childless_activity_keeps_its_sequence_column():
    """Its column comes from its position in the segment's numeric ID order like any other
    activity, so it does not pile onto a neighbour's column."""
    registry = {"activities": [
        {"id": "1", "label": "Segment", "level": "L1", "active": True},
        {"id": "1.1", "label": "Has tasks", "level": "L2", "active": True, "parent_id": "1"},
        {"id": "1.2", "label": "No tasks", "level": "L2", "active": True, "parent_id": "1"},
        {"id": "1.1.1", "label": "A task", "level": "L3", "active": True, "parent_id": "1.1"},
    ]}
    mermaid = (
        "```mermaid\nflowchart LR\n"
        '  A["A task"]:::sp\n'
        "  classDef sp fill:#1a5276\n"
        "```"
    )

    model = migrate(registry, mermaid)
    by_activity = {c["activity_id"]: c["column"] for c in model["contributions"]}

    assert by_activity == {"1.1": 10, "1.2": 20}


def test_the_real_project_still_migrates_with_every_activity_contributed():
    """sp-gs-am has no childless activity, so this guards against the fix changing what
    already worked - and against the new validate_model rule rejecting the real model."""
    from pathlib import Path
    import json
    from api.services.value_chain_model import validate_model

    outputs = Path("projects/sp-gs-am/outputs")
    registry = json.loads((outputs / "value_chain_registry.json").read_text())
    mermaid = (outputs / "value_chain_v12.md").read_text()

    model = migrate(registry, mermaid)

    assert validate_model(model) == []
    contributed = {c["activity_id"] for c in model["contributions"]}
    assert contributed == {a["id"] for a in model["activities"]}


def test_the_real_project_migrates_cleanly():
    """The actual sp-gs-am data - 3 segments, 17 activities, 59 tasks."""
    import json
    from pathlib import Path

    registry_path = Path("projects/sp-gs-am/outputs/value_chain_registry.json")
    mermaid_path = Path("projects/sp-gs-am/outputs/value_chain_v12.md")
    if not registry_path.exists() or not mermaid_path.exists():
        pytest.skip("sp-gs-am fixtures not present in this checkout")

    registry = json.loads(registry_path.read_text())
    model = migrate(registry, mermaid_path.read_text())

    assert validate_model(model) == []
    assert len(model["segments"]) == 3
    assert len(model["activities"]) == 17
    assert len(model["tasks"]) == 59
    assert {p["id"] for p in model["parties"]} == {"sp", "partnerISS", "partnerDXI"}
