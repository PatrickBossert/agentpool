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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Contradicts test_a_tie_is_broken_by_party_name_ascending. Both tests build a "
        "single-segment registry with one sp-labelled task, one partnerISS-labelled task "
        "and one orphan, against the same Mermaid text - so stated counts are identically "
        "{'sp': 1, 'partnerISS': 1} in both. Per the documented rule ('ties broken by "
        "party name ascending'), sorted(['sp', 'partnerISS'])[0] == 'partnerISS' in both "
        "cases, matching the sibling test. This test's comment ('sp holds the most "
        "attributed tasks') is factually wrong for this fixture - it is a 1-1 tie, not a "
        "majority - so its assertion cannot hold without breaking the sibling test's. "
        "Kept verbatim per the task brief rather than edited, and marked xfail rather than "
        "silently skipped or forced to pass by weakening the tie-break rule."
    ),
)
def test_an_unmatched_task_takes_the_segments_dominant_party_and_is_marked_derived():
    """'Unmentioned task' appears in no Mermaid node, so it falls back."""
    model = migrate(REGISTRY, MERMAID)
    unmatched = next(t for t in model["tasks"] if t["id"] == "1.1.3")
    # sp holds the most attributed tasks in segment 1, so it wins.
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


def test_columns_are_assigned_in_steps_per_lane():
    model = migrate(REGISTRY, MERMAID)
    for contribution in model["contributions"]:
        assert contribution["column"] % COLUMN_STEP == 0
        assert contribution["column"] >= COLUMN_STEP


def test_descriptions_migrate_empty():
    model = migrate(REGISTRY, MERMAID)
    assert all(a["description"] == "" for a in model["activities"])
    assert all(t["description"] == "" for t in model["tasks"])


def test_migration_is_idempotent():
    assert migrate(REGISTRY, MERMAID) == migrate(REGISTRY, MERMAID)


def test_a_registry_with_no_mermaid_attribution_migrates_without_parties():
    """A fresh project has nothing to recover, and that is not an error."""
    model = migrate(REGISTRY, "```mermaid\nflowchart LR\n  A[\"x\"]\n```")
    assert model["parties"] == []
    assert model["contributions"] == []
    assert validate_model(model) == []


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
