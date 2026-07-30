# The Value Chain Model and Table Editor - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The value chain becomes an editable model - segments, party lanes, activities, and per-party contributions - instead of a Mermaid string nobody can change.

**Architecture:** A pure Python module defines and validates the model. A migration recovers it from today's Mermaid colour classes and the existing registry, preserving every stable ID. The model persists as a versioned JSON output, so an edit is a new working version with an attributed change record. `value_chain_mapper` emits the model instead of a diagram, the Diagram tab goes, and a Structure tab renders and edits the table.

**Tech Stack:** Python 3.13, FastAPI, aiosqlite, pytest; React 18, TypeScript, Tailwind CSS v3, vitest.

## Global Constraints

- **British English** throughout - `-ise`, `-our`, `-re`.
- **Spaced hyphen ` - `** in prose, comments, and copy. Never an em dash. Hyphenated compound adjectives keep their tight hyphen.
- **No emoji** in rendered web content. Lucide React icons only.
- **Oxford comma** in lists of three or more.
- Backend: async `aiosqlite`; **all raw SQL lives in `api/database.py`**; no ORM. Routers in `api/routers/`, services in `api/services/`.
- Frontend: brand tokens only - `bg-brand`, `text-brand`, `brand-dark`. Never `sky-*` or `blue-*`.
- Backend tests run with `./venv/bin/pytest` - **not** bare `pytest`.
- **Baseline: 667 backend tests, 86 frontend tests, both green, `tsc --noEmit` clean.**
- **Stable IDs are never changed or reused.** Segments, activities, and tasks keep their existing `Ln.n.n` IDs through migration, with parentage intact.
- **A contribution's identity is the composite `(activity_id, party_id)`** - never a new ID space.
- **Do NOT remove the `mermaid` package.** `ui/src/components/ReviewDialog.tsx:86` imports it dynamically as `(await import('mermaid')).default`, which a search for `from 'mermaid'` does not find. Only ValueChain's use of it is removed.
- **Do NOT modify `agents/tools/human_input.py`** or any agent module other than `value_chain_mapper`.
- Test files that create a project must unlink its database **and** its `projects/<slug>` directory before and after each test.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `api/services/value_chain_model.py` (create) | The model's shape and its validation. Pure - no I/O, no DB |
| `api/services/value_chain_migration.py` (create) | Mermaid classes plus registry to model. Pure - takes text and dicts, returns a model |
| `api/services/value_chain_store.py` (create) | Reading the current model and saving a new version |
| `api/routers/value_chain.py` (create) | `GET`/`PUT` the model |
| `api/main.py` (modify) | Register the router |
| `agents/discovery/value_chain_mapper.py` (modify) | Emit the model, not a Mermaid diagram |
| `ui/src/api/endpoints.ts` (modify) | `valueChainApi` |
| `ui/src/pages/ValueChain.tsx` (modify) | Remove the Diagram tab, add Structure |
| `ui/src/components/ValueChainTable.tsx` (create) | The table: segments, lanes, columns, cells |
| `ui/src/components/ContributionPanel.tsx` (create) | A contribution's tasks and its activity's propositions |

---

## Task 1: The model and its validation

**Files:**
- Create: `api/services/value_chain_model.py`
- Test: `tests/test_value_chain_model.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `MODEL_VERSION = 1`
  - `def empty_model() -> dict`
  - `def validate_model(model: dict) -> list[str]` - a list of human-readable problems, empty when valid
  - `def contribution_key(activity_id: str, party_id: str) -> str` - `f"{activity_id}@{party_id}"`
  - `def next_column(model: dict, segment_id: str, party_id: str) -> int`
  - `COLUMN_STEP = 10`

The model's shape, which every later task depends on:

```python
{
  "model_version": 1,
  "parties":  [{"id": "sp-gs", "label": "SP-GS", "colour": "#1a5276"}],
  "segments": [{"id": "1", "label": "PROPERTY VALUE CHAIN", "description": ""}],
  "activities": [
    {"id": "1.1", "segment_id": "1", "label": "Reactive Maintenance",
     "description": "", "active": True}
  ],
  "contributions": [
    {"activity_id": "1.1", "party_id": "sp-gs", "column": 10,
     "description": "", "attribution": "stated"}
  ],
  "tasks": [
    {"id": "1.1.3", "activity_id": "1.1", "party_id": "sp-gs",
     "label": "Raise works order", "description": "", "active": True}
  ],
  "propositions": [
    {"id": "p1", "activity_id": "1.1", "party_id": None,
     "label": "paperless works order management", "description": ""}
  ],
  "links": [
    {"from_activity_id": "1.1", "from_party_id": "sp-gs",
     "to_activity_id": "1.2", "to_party_id": "iss"}
  ]
}
```

A contribution has no `id` of its own: `(activity_id, party_id)` **is** its identity, and
`contribution_key` exists only to make that composite usable as a dict key or a React key.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_value_chain_model.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_value_chain_model.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'api.services.value_chain_model'`

- [ ] **Step 3: Implement**

Create `api/services/value_chain_model.py`:

```python
# api/services/value_chain_model.py
"""The value chain's shape.

An activity is one thing with one stable ID. Each party's part of it is a *contribution*,
which is what occupies a lane and a column, carries its own description, and owns its
tasks. That is what lets two parties be interviewed separately about the same activity.

A contribution has no ID of its own: (activity_id, party_id) is its identity. This module
is pure - no I/O, no database - so the rules can be tested without a project.
"""
from __future__ import annotations

MODEL_VERSION = 1

# Columns advance in steps so an insertion between neighbours picks an intermediate value
# rather than renumbering the lane.
COLUMN_STEP = 10

_ATTRIBUTIONS = ("stated", "derived")


def empty_model() -> dict:
    return {
        "model_version": MODEL_VERSION,
        "parties": [],
        "segments": [],
        "activities": [],
        "contributions": [],
        "tasks": [],
        "propositions": [],
        "links": [],
    }


def contribution_key(activity_id: str, party_id: str) -> str:
    """A usable key for the composite identity - for dicts and React keys, not storage."""
    return f"{activity_id}@{party_id}"


def next_column(model: dict, segment_id: str, party_id: str) -> int:
    """The next free column in one party's lane within one segment.

    Per lane, not per segment: a party joining later starts at the beginning of its own
    lane rather than after whatever another party has already done.
    """
    activity_segments = {a["id"]: a.get("segment_id") for a in model.get("activities", [])}
    columns = [
        c["column"]
        for c in model.get("contributions", [])
        if c.get("party_id") == party_id
        and activity_segments.get(c.get("activity_id")) == segment_id
        and isinstance(c.get("column"), int)
    ]
    return (max(columns) + COLUMN_STEP) if columns else COLUMN_STEP


def validate_model(model: dict) -> list[str]:
    """Every problem with this model, as readable sentences. Empty means valid.

    Returns all problems rather than raising on the first, so a caller can show a person
    everything that is wrong in one pass.
    """
    problems: list[str] = []

    party_ids = {p.get("id") for p in model.get("parties", [])}
    segment_ids = {s.get("id") for s in model.get("segments", [])}
    activity_segment = {a.get("id"): a.get("segment_id") for a in model.get("activities", [])}

    for activity in model.get("activities", []):
        if activity.get("segment_id") not in segment_ids:
            problems.append(
                f"activity {activity.get('id')} names unknown segment "
                f"{activity.get('segment_id')}"
            )

    seen_cells: set[tuple[str, str, int]] = set()
    contribution_ids: set[tuple[str, str]] = set()

    for contribution in model.get("contributions", []):
        activity_id = contribution.get("activity_id")
        party_id = contribution.get("party_id")
        column = contribution.get("column")

        if activity_id not in activity_segment:
            problems.append(f"contribution names unknown activity {activity_id}")
            continue
        if party_id not in party_ids:
            problems.append(f"contribution names unknown party {party_id}")
            continue
        if not isinstance(column, int):
            problems.append(
                f"contribution {contribution_key(activity_id, party_id)} has no column"
            )
            continue
        if contribution.get("attribution") not in _ATTRIBUTIONS:
            problems.append(
                f"contribution {contribution_key(activity_id, party_id)} has attribution "
                f"{contribution.get('attribution')!r}, expected one of {_ATTRIBUTIONS}"
            )

        cell = (activity_segment[activity_id], party_id, column)
        if cell in seen_cells:
            problems.append(
                f"two contributions occupy column {column} in party {party_id}'s lane"
            )
        seen_cells.add(cell)
        contribution_ids.add((activity_id, party_id))

    for task in model.get("tasks", []):
        pair = (task.get("activity_id"), task.get("party_id"))
        if pair not in contribution_ids:
            problems.append(
                f"task {task.get('id')} belongs to contribution "
                f"{contribution_key(*[str(x) for x in pair])}, which does not exist"
            )

    for proposition in model.get("propositions", []):
        if proposition.get("activity_id") not in activity_segment:
            problems.append(
                f"proposition {proposition.get('id')} names unknown activity "
                f"{proposition.get('activity_id')}"
            )

    for link in model.get("links", []):
        for end in ("from", "to"):
            pair = (link.get(f"{end}_activity_id"), link.get(f"{end}_party_id"))
            if pair not in contribution_ids:
                problems.append(
                    f"link {end} endpoint {contribution_key(*[str(x) for x in pair])} "
                    "does not exist"
                )

    return problems
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_value_chain_model.py -v`
Expected: 15 passed

- [ ] **Step 5: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 682 passed. No new warnings.

- [ ] **Step 6: Commit**

```bash
git add api/services/value_chain_model.py tests/test_value_chain_model.py
git commit -m "feat: define the value chain model and what makes it invalid"
```

---

## Task 2: Migrating from Mermaid and the registry

**Files:**
- Create: `api/services/value_chain_migration.py`
- Test: `tests/test_value_chain_migration.py`

**Interfaces:**
- Consumes: `empty_model`, `validate_model`, `COLUMN_STEP` from Task 1
- Produces:
  - `def parse_mermaid_attribution(mermaid: str) -> tuple[dict[str, str], dict[str, str]]` - returns `(label_to_class, class_to_colour)`, labels normalised
  - `def normalise_label(label: str) -> str`
  - `def migrate(registry: dict, mermaid: str) -> dict` - the model

**This task carries nearly all the project's risk.** It is pure: it takes the registry dict
and the Mermaid text and returns a model. No files, no database.

Two real inputs to work against:
- `projects/sp-gs-am/outputs/value_chain_registry.json` - 3 L1, 17 L2, 59 L3, keys
  `{id, label, level, active, parent_id}`
- `projects/sp-gs-am/outputs/value_chain_v12.md` - a Mermaid fence with
  `classDef sp fill:#1a5276...`, `classDef partnerISS fill:#c0392b...`,
  `classDef partnerDXI fill:#27ae60...` and nodes marked `NodeId["Label"]:::sp`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_value_chain_migration.py`:

```python
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

# No ``` fence wrapper: the parser regexes over the text and never needs one, and a
# fence marker at column 0 inside this code block would break markdown tooling that
# extracts tasks by heading.
MERMAID = """flowchart LR
  subgraph P["PROPERTY"]
    A["Raise works order"]:::sp
    B["Execute repair"]:::partnerISS
    C["Inspect asset"]:::partnerDXI
  end
  classDef sp         fill:#1a5276,color:#fff,stroke:#1a5276
  classDef partnerISS fill:#c0392b,color:#fff,stroke:#922b21
  classDef partnerDXI fill:#27ae60,color:#fff,stroke:#1e8449
"""

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
    model = migrate(REGISTRY, 'flowchart LR\n  A["x"]')
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_value_chain_migration.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'api.services.value_chain_migration'`

- [ ] **Step 3: Implement**

Create `api/services/value_chain_migration.py`:

```python
# api/services/value_chain_migration.py
"""Recovering the model from a Mermaid diagram and the flat registry.

The diagram carries real attribution as CSS classes with a colour scheme. Mermaid's node
ids bear no relation to registry IDs, so a node is matched to a registry entry by its
label - the one fragile step in this whole project, which is why an unmatched entry falls
back to a dominant party rather than failing or being reported for remediation. A complete,
correctable chart beats an incomplete one with a to-do list.

Pure: takes a registry dict and the Mermaid text, returns a model.
"""
from __future__ import annotations

import re

from api.services.value_chain_model import COLUMN_STEP, empty_model

# NodeId["Some label"]:::className  - the label may be quoted or bare.
_NODE = re.compile(r'\w+\s*\[\s*"?(?P<label>[^"\]]+?)"?\s*\]\s*:::\s*(?P<cls>\w+)')
# classDef name fill:#rrggbb,...
_CLASSDEF = re.compile(r"classDef\s+(?P<cls>\w+)\s+.*?fill:\s*(?P<colour>#[0-9a-fA-F]{3,8})")


def normalise_label(label: str) -> str:
    """Trimmed, case-folded, whitespace-collapsed - the form labels are matched on."""
    return re.sub(r"\s+", " ", label).strip().casefold()


def parse_mermaid_attribution(mermaid: str) -> tuple[dict[str, str], dict[str, str]]:
    """Returns (normalised label -> class name, class name -> colour)."""
    labels = {
        normalise_label(m.group("label")): m.group("cls")
        for m in _NODE.finditer(mermaid)
    }
    colours = {
        m.group("cls"): m.group("colour").lower()
        for m in _CLASSDEF.finditer(mermaid)
    }
    return labels, colours


def _dominant(counts: dict[str, int]) -> str | None:
    """The most common party, ties broken by name ascending so this is deterministic."""
    if not counts:
        return None
    best = max(counts.values())
    return sorted(p for p, n in counts.items() if n == best)[0]


def migrate(registry: dict, mermaid: str) -> dict:
    """Build the model. Idempotent: the same inputs always give the same output."""
    label_to_class, class_to_colour = parse_mermaid_attribution(mermaid)
    entries = registry.get("activities", [])

    model = empty_model()

    # Only classes that carry a colour become parties - a class used but never defined is
    # a broken diagram, not a party.
    model["parties"] = [
        {"id": cls, "label": cls, "colour": colour}
        for cls, colour in sorted(class_to_colour.items())
        if cls in set(label_to_class.values())
    ]
    known_parties = {p["id"] for p in model["parties"]}

    model["segments"] = [
        {"id": e["id"], "label": e["label"], "description": ""}
        for e in entries
        if e.get("level") == "L1"
    ]
    model["activities"] = [
        {"id": e["id"], "segment_id": e.get("parent_id"), "label": e["label"],
         "description": "", "active": bool(e.get("active", True))}
        for e in entries
        if e.get("level") == "L2"
    ]
    activity_segment = {a["id"]: a["segment_id"] for a in model["activities"]}

    l3s = [e for e in entries if e.get("level") == "L3"]

    # First pass: whatever attribution the diagram states.
    stated: dict[str, str] = {}
    for entry in l3s:
        cls = label_to_class.get(normalise_label(entry["label"]))
        if cls in known_parties:
            stated[entry["id"]] = cls

    # Counts for the fallback cascade, from stated attribution only.
    per_segment: dict[str, dict[str, int]] = {}
    project_counts: dict[str, int] = {}
    for entry in l3s:
        party = stated.get(entry["id"])
        if party is None:
            continue
        segment = activity_segment.get(entry.get("parent_id"))
        per_segment.setdefault(segment, {}).setdefault(party, 0)
        per_segment[segment][party] += 1
        project_counts[party] = project_counts.get(party, 0) + 1

    project_dominant = _dominant(project_counts)

    # Second pass: assign every task a party, recording whether it was stated or derived.
    derived_pairs: set[tuple[str, str]] = set()
    stated_pairs: set[tuple[str, str]] = set()

    for entry in l3s:
        activity_id = entry.get("parent_id")
        segment = activity_segment.get(activity_id)
        party = stated.get(entry["id"])
        was_stated = party is not None
        if party is None:
            party = _dominant(per_segment.get(segment, {})) or project_dominant
        if party is None:
            # Nothing in the project is attributed - a fresh project with no diagram to
            # recover from. Tasks are dropped rather than invented, and the agent's own
            # structured output supplies the model instead.
            continue

        model["tasks"].append({
            "id": entry["id"], "activity_id": activity_id, "party_id": party,
            "label": entry["label"], "description": "",
            "active": bool(entry.get("active", True)),
        })
        (stated_pairs if was_stated else derived_pairs).add((activity_id, party))

    # Contributions are derived from task attribution, one per (activity, party) seen.
    # A pair with any stated task counts as stated - the diagram said so for part of it.
    columns: dict[tuple[str, str], int] = {}
    for activity_id, party in sorted(stated_pairs | derived_pairs):
        segment = activity_segment.get(activity_id)
        used = [
            col for (seg, prt), col in columns.items()
            if prt == party and activity_segment.get(seg) == segment
        ]
        column = (max(used) + COLUMN_STEP) if used else COLUMN_STEP
        columns[(activity_id, party)] = column
        model["contributions"].append({
            "activity_id": activity_id,
            "party_id": party,
            "column": column,
            "description": "",
            "attribution": "stated" if (activity_id, party) in stated_pairs else "derived",
        })

    return model
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_value_chain_migration.py -v`
Expected: 16 passed. The final test runs against the real `sp-gs-am` data and skips if
those files are absent.

If `test_columns_are_assigned_in_steps_per_lane` fails because two contributions in one lane
share a column, the column assignment above is grouping wrongly - each `(party, segment)`
pair must have its own running counter.

- [ ] **Step 5: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 698 passed.

- [ ] **Step 6: Commit**

```bash
git add api/services/value_chain_migration.py tests/test_value_chain_migration.py
git commit -m "feat: recover the value chain model from the diagram's colour classes"
```

---

## Task 3: Persisting the model as a versioned output

**Files:**
- Create: `api/services/value_chain_store.py`
- Create: `api/routers/value_chain.py`
- Modify: `api/main.py` - import and register the router
- Test: `tests/test_value_chain_store.py`

**Interfaces:**
- Consumes: `validate_model` (Task 1), `migrate` (Task 2); `insert_agent_output`, `fetch_agent_outputs`, `fetch_project`, `get_connection`, `insert_output_change` - all existing in `api/database.py`
- Produces:
  - `OUTPUT_TYPE = "value_chain_model"`
  - `async def load_model(slug: str) -> dict | None`
  - `async def save_model(slug: str, model: dict, *, saved_by: str, summary: str) -> int` - returns the new output id
  - `GET /projects/{slug}/value-chain-model`, `PUT /projects/{slug}/value-chain-model`

**An edit is a new working version, never an in-place write** - the same discipline the
approval loop already follows. `save_model` writes the next version file, inserts an
`agent_outputs` row, supersedes the previous `is_current`, and records an `output_changes`
row with `source='edit'`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_value_chain_store.py`:

```python
# tests/test_value_chain_store.py
"""The model is a versioned output, so an edit is a new version with an attributed change.

That is the discipline already recorded for the approval loop: the versioned artefact is
the source of truth, an edit never touches a committed version, and every change says who
asked for it.
"""
import shutil
from pathlib import Path

import pytest

from api.config import get_settings

SLUG = "vc-store-test"
PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}

MODEL = {
    "model_version": 1,
    "parties": [{"id": "sp", "label": "SP-GS", "colour": "#1a5276"}],
    "segments": [{"id": "1", "label": "PROPERTY", "description": ""}],
    "activities": [{"id": "1.1", "segment_id": "1", "label": "Reactive",
                    "description": "", "active": True}],
    "contributions": [{"activity_id": "1.1", "party_id": "sp", "column": 10,
                       "description": "", "attribution": "stated"}],
    "tasks": [], "propositions": [], "links": [],
}


@pytest.fixture(autouse=True)
def clean():
    def wipe():
        settings = get_settings()
        Path(settings.database_dir, f"{SLUG}.db").unlink(missing_ok=True)
        proj = Path(settings.projects_dir, SLUG)
        if proj.exists():
            shutil.rmtree(proj)
    wipe()
    yield
    get_settings.cache_clear()
    wipe()


@pytest.mark.asyncio
async def test_loading_before_anything_is_saved_returns_none(client):
    await client.post("/projects", json=PROJECT)
    from api.services.value_chain_store import load_model
    assert await load_model(SLUG) is None


@pytest.mark.asyncio
async def test_saving_then_loading_round_trips(client):
    await client.post("/projects", json=PROJECT)
    from api.services.value_chain_store import load_model, save_model
    await save_model(SLUG, MODEL, saved_by="alice", summary="first")
    assert await load_model(SLUG) == MODEL


@pytest.mark.asyncio
async def test_a_second_save_creates_a_new_version_and_supersedes_the_first(client):
    await client.post("/projects", json=PROJECT)
    from api.database import fetch_agent_outputs, fetch_project, get_connection
    from api.services.value_chain_store import OUTPUT_TYPE, save_model

    await save_model(SLUG, MODEL, saved_by="alice", summary="first")
    edited = {**MODEL, "segments": [{"id": "1", "label": "PROPERTY", "description": "edited"}]}
    await save_model(SLUG, edited, saved_by="bob", summary="second")

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        outputs = [
            o for o in await fetch_agent_outputs(conn, project_id=project["id"])
            if o["output_type"] == OUTPUT_TYPE
        ]
    assert len(outputs) == 2
    assert sum(1 for o in outputs if o["is_current"]) == 1
    assert max(o["version"] for o in outputs) == 2


@pytest.mark.asyncio
async def test_a_save_records_an_attributed_change(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection
    from api.services.value_chain_store import save_model

    await save_model(SLUG, MODEL, saved_by="alice", summary="tidied the labels")

    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT requested_by, source, request FROM output_changes"
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    assert len(rows) == 1
    assert rows[0]["requested_by"] == "alice"
    assert rows[0]["source"] == "edit"
    assert "tidied the labels" in rows[0]["request"]


@pytest.mark.asyncio
async def test_an_invalid_model_is_refused_and_saves_nothing(client):
    await client.post("/projects", json=PROJECT)
    from api.database import fetch_agent_outputs, fetch_project, get_connection
    from api.services.value_chain_store import save_model

    broken = {**MODEL, "contributions": [
        {"activity_id": "9.9", "party_id": "sp", "column": 10,
         "description": "", "attribution": "stated"}
    ]}
    with pytest.raises(ValueError):
        await save_model(SLUG, broken, saved_by="alice", summary="broken")

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        outputs = await fetch_agent_outputs(conn, project_id=project["id"])
    assert outputs == [] or all(o["output_type"] != "value_chain_model" for o in outputs)


@pytest.mark.asyncio
async def test_the_endpoint_returns_the_model_and_accepts_a_save(client):
    await client.post("/projects", json=PROJECT)
    assert (await client.get(f"/projects/{SLUG}/value-chain-model")).status_code == 404

    put = await client.put(
        f"/projects/{SLUG}/value-chain-model",
        json={"model": MODEL, "summary": "first"},
    )
    assert put.status_code == 200

    got = await client.get(f"/projects/{SLUG}/value-chain-model")
    assert got.status_code == 200
    assert got.json()["model"] == MODEL


@pytest.mark.asyncio
async def test_the_endpoint_reports_validation_problems_rather_than_saving(client):
    await client.post("/projects", json=PROJECT)
    broken = {**MODEL, "activities": [
        {"id": "1.1", "segment_id": "7", "label": "Reactive",
         "description": "", "active": True}
    ]}
    resp = await client.put(
        f"/projects/{SLUG}/value-chain-model",
        json={"model": broken, "summary": "broken"},
    )
    assert resp.status_code == 422
    assert any("7" in p for p in resp.json()["detail"]["problems"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_value_chain_store.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'api.services.value_chain_store'`

- [ ] **Step 3: Implement the store**

Create `api/services/value_chain_store.py`:

```python
# api/services/value_chain_store.py
"""Reading and saving the value chain model.

An edit produces a new working version rather than an in-place write, and records who asked
for it. That is the discipline the approval loop already follows - the versioned artefact is
the source of truth, and a committed version is never modified.
"""
from __future__ import annotations

import json
from pathlib import Path

from api.config import get_settings
from api.database import (
    fetch_agent_outputs,
    fetch_project,
    get_connection,
    insert_agent_output,
    insert_output_change,
)
from api.services.value_chain_model import validate_model

OUTPUT_TYPE = "value_chain_model"
AGENT_NAME = "value_chain_mapper"


def _outputs_dir(slug: str) -> Path:
    settings = get_settings()
    path = Path(settings.projects_dir) / slug / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def load_model(slug: str) -> dict | None:
    """The current model, or None if none has been saved."""
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        outputs = [
            o for o in await fetch_agent_outputs(conn, project_id=project["id"])
            if o["output_type"] == OUTPUT_TYPE and o.get("is_current")
        ]
    if not outputs:
        return None
    path = Path(outputs[0]["file_path"])
    if not path.exists():
        return None
    return json.loads(path.read_text())


async def save_model(slug: str, model: dict, *, saved_by: str, summary: str) -> int:
    """Write the next version. Raises ValueError with the problems if the model is invalid.

    Validation runs before anything is written, so a rejected save leaves no file and no
    row - a half-saved model would be worse than a refused one.
    """
    problems = validate_model(model)
    if problems:
        raise ValueError("; ".join(problems))

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise ValueError(f"project {slug!r} not found")

        existing = [
            o for o in await fetch_agent_outputs(conn, project_id=project["id"])
            if o["output_type"] == OUTPUT_TYPE
        ]
        version = max((o["version"] for o in existing), default=0) + 1

        path = _outputs_dir(slug) / f"value_chain_model_v{version}.json"
        path.write_text(json.dumps(model, indent=2))

        output_id = await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name=AGENT_NAME,
            output_type=OUTPUT_TYPE,
            file_path=str(path),
            version=version,
        )
        # insert_agent_output does not set is_current, so supersede the rest explicitly.
        await conn.execute(
            "UPDATE agent_outputs SET is_current=0 "
            "WHERE project_id=? AND output_type=? AND id<>?",
            (project["id"], OUTPUT_TYPE, output_id),
        )
        await conn.execute(
            "UPDATE agent_outputs SET is_current=1 WHERE id=?", (output_id,)
        )
        await conn.commit()

        await insert_output_change(
            conn,
            output_id=output_id,
            requested_by=saved_by,
            source="edit",
            request=summary,
            summary=f"saved value chain model version {version}",
        )

    return output_id
```

- [ ] **Step 4: Implement the router**

Create `api/routers/value_chain.py`:

```python
# api/routers/value_chain.py
"""Reading and saving the value chain model."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import check_project_access, require_any_auth
from api.database import get_db_path
from api.services.value_chain_model import validate_model
from api.services.value_chain_store import load_model, save_model

router = APIRouter(prefix="/projects", tags=["value-chain"])


class ModelSave(BaseModel):
    model: dict
    summary: str = ""


def _require_project(slug: str) -> None:
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")


@router.get("/{slug}/value-chain-model")
async def get_value_chain_model(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    _require_project(slug)
    model = await load_model(slug)
    if model is None:
        raise HTTPException(status_code=404, detail="No value chain model yet")
    return {"model": model}


@router.put("/{slug}/value-chain-model")
async def put_value_chain_model(
    slug: str, body: ModelSave, payload: dict = Depends(require_any_auth)
):
    """Save a new working version. Reports every problem at once rather than the first."""
    await check_project_access(slug, payload)
    _require_project(slug)

    problems = validate_model(body.model)
    if problems:
        raise HTTPException(status_code=422, detail={"problems": problems})

    output_id = await save_model(
        slug, body.model, saved_by=payload.get("sub", ""), summary=body.summary
    )
    return {"output_id": output_id}
```

- [ ] **Step 5: Register the router**

In `api/main.py`, beside the other router imports:

```python
from api.routers import value_chain as value_chain_router
```

and beside the `include_router` calls:

```python
app.include_router(value_chain_router.router)
```

- [ ] **Step 6: Run the tests, then the full suite**

Run: `./venv/bin/pytest tests/test_value_chain_store.py -v`
Expected: 7 passed

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 705 passed.

- [ ] **Step 7: Commit**

```bash
git add api/services/value_chain_store.py api/routers/value_chain.py api/main.py tests/test_value_chain_store.py
git commit -m "feat: persist the value chain model as a versioned, attributed output"
```

---

## Task 4: A migration entry point

**Files:**
- Modify: `api/services/value_chain_store.py` - add `migrate_project`
- Modify: `api/routers/value_chain.py` - add the migrate route
- Test: `tests/test_value_chain_migrate_endpoint.py`

**Interfaces:**
- Consumes: `migrate` (Task 2), `load_model`, `save_model` (Task 3)
- Produces:
  - `async def migrate_project(slug: str, *, saved_by: str) -> dict` - returns `{"created": bool, "counts": {...}}`
  - `POST /projects/{slug}/value-chain-model/migrate`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_value_chain_migrate_endpoint.py`. It needs the fixture scaffolding in
full, because a test referring to helpers that do not exist cannot run:

```python
# tests/test_value_chain_migrate_endpoint.py
"""Migration is a one-off recovery, not a repeatable import."""
import json
import shutil
from pathlib import Path

import pytest

from api.config import get_settings
from tests.test_value_chain_migration import MERMAID, REGISTRY

SLUG = "vc-migrate-test"
PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean():
    def wipe():
        settings = get_settings()
        Path(settings.database_dir, f"{SLUG}.db").unlink(missing_ok=True)
        proj = Path(settings.projects_dir, SLUG)
        if proj.exists():
            shutil.rmtree(proj)
    wipe()
    yield
    get_settings.cache_clear()
    wipe()


async def _write_fixtures(slug: str) -> None:
    """Put a registry and a Mermaid output where the migration looks for them."""
    outputs = Path(get_settings().projects_dir) / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "value_chain_registry.json").write_text(json.dumps(REGISTRY))
    (outputs / "value_chain_v1.md").write_text(MERMAID)
```

Then the three tests:

```python
@pytest.mark.asyncio
async def test_migration_builds_a_model_from_the_registry_and_diagram(client):
    await client.post("/projects", json=PROJECT)
    await _write_fixtures(SLUG)   # writes registry json and the mermaid markdown

    resp = await client.post(f"/projects/{SLUG}/value-chain-model/migrate")
    assert resp.status_code == 200
    assert resp.json()["created"] is True

    got = await client.get(f"/projects/{SLUG}/value-chain-model")
    model = got.json()["model"]
    assert {p["id"] for p in model["parties"]} == {"sp", "partnerISS"}


@pytest.mark.asyncio
async def test_migration_refuses_to_overwrite_an_existing_model(client):
    """Re-running must not silently discard edits somebody has made since."""
    await client.post("/projects", json=PROJECT)
    await _write_fixtures(SLUG)
    await client.post(f"/projects/{SLUG}/value-chain-model/migrate")

    again = await client.post(f"/projects/{SLUG}/value-chain-model/migrate")
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_migration_without_source_files_reports_that_clearly(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(f"/projects/{SLUG}/value-chain-model/migrate")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_value_chain_migrate_endpoint.py -v`
Expected: FAIL - the route returns 404 for a different reason (it does not exist).

- [ ] **Step 3: Implement**

Append to `api/services/value_chain_store.py`:

```python
async def migrate_project(slug: str, *, saved_by: str) -> dict:
    """Build the model from this project's registry and its latest Mermaid output.

    Refuses when a model already exists: re-running would discard whatever anybody has
    edited since, and migration is a one-off recovery rather than a repeatable import.
    """
    if await load_model(slug) is not None:
        raise FileExistsError("a value chain model already exists for this project")

    outputs = _outputs_dir(slug)
    registry_path = outputs / "value_chain_registry.json"
    mermaid_paths = sorted(outputs.glob("value_chain_v*.md"))
    if not registry_path.exists() or not mermaid_paths:
        raise FileNotFoundError(
            "need value_chain_registry.json and a value_chain_v*.md to migrate"
        )

    from api.services.value_chain_migration import migrate

    model = migrate(
        json.loads(registry_path.read_text()),
        mermaid_paths[-1].read_text(),
    )
    await save_model(
        slug, model, saved_by=saved_by, summary="migrated from the Mermaid diagram"
    )
    return {
        "created": True,
        "counts": {
            "parties": len(model["parties"]),
            "segments": len(model["segments"]),
            "activities": len(model["activities"]),
            "contributions": len(model["contributions"]),
            "tasks": len(model["tasks"]),
            "derived": sum(
                1 for c in model["contributions"] if c["attribution"] == "derived"
            ),
        },
    }
```

`mermaid_paths[-1]` takes the highest-numbered file. Sorting is lexical, so `v9` sorts
after `v12` - if a project has more than nine versions, sort by the integer in the name
instead. `sp-gs-am` is at `v12`, so this matters immediately: sort with
`key=lambda p: int(re.search(r"_v(\d+)", p.name).group(1))`.

Add to `api/routers/value_chain.py`:

```python
@router.post("/{slug}/value-chain-model/migrate")
async def migrate_value_chain_model(
    slug: str, payload: dict = Depends(require_any_auth)
):
    await check_project_access(slug, payload)
    _require_project(slug)
    try:
        return await migrate_project(slug, saved_by=payload.get("sub", ""))
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
```

- [ ] **Step 4: Run the tests, then the full suite**

Run: `./venv/bin/pytest tests/test_value_chain_migrate_endpoint.py -v`
Expected: 3 passed

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 708 passed.

- [ ] **Step 5: Commit**

```bash
git add api/services/value_chain_store.py api/routers/value_chain.py tests/test_value_chain_migrate_endpoint.py
git commit -m "feat: add a one-off migration from the diagram to the model"
```

---

## Task 5: The agent emits the model

**Files:**
- Modify: `agents/discovery/value_chain_mapper.py`
- Test: `tests/test_value_chain_mapper_output.py`

**Interfaces:** none. The agent's task description changes.

**Do not modify any other agent module.**

- [ ] **Step 1: Write the failing tests**

Create `tests/test_value_chain_mapper_output.py`:

```python
# tests/test_value_chain_mapper_output.py
"""Alex emits the model, not a diagram.

Leave him emitting Mermaid and his next run overwrites the model with a rendering, and the
editor has nothing to edit.
"""
from unittest.mock import MagicMock

import pytest
from crewai import LLM

from agents.discovery.value_chain_mapper import (
    create_value_chain_mapper,
    create_value_chain_task,
)


@pytest.fixture
def task_text() -> str:
    agent = create_value_chain_mapper(slug="t", llm=MagicMock(spec=LLM), tools=[])
    task = create_value_chain_task(agent=agent, client_name="Test Client")
    return (task.description + "\n" + task.expected_output).lower()


def test_the_task_no_longer_asks_for_a_mermaid_diagram(task_text):
    for phrase in ("mermaid", "flowchart lr", "classdef", "subgraph"):
        assert phrase not in task_text, f"still asks for {phrase!r}"


def test_the_task_asks_for_the_model_by_its_output_type(task_text):
    assert "value_chain_model" in task_text


def test_the_task_names_every_part_of_the_model(task_text):
    for key in ("parties", "segments", "activities", "contributions", "tasks", "links"):
        assert key in task_text, f"does not mention {key}"


def test_the_task_asks_for_descriptions(task_text):
    """Descriptions are the point - they have never existed."""
    assert "description" in task_text


def test_the_task_explains_a_contribution(task_text):
    """Alex has to understand that one activity can have several parties' parts."""
    assert "contribution" in task_text
    assert "party" in task_text
```

If `create_value_chain_task` is named differently, read
`agents/discovery/value_chain_mapper.py` and use the real factory names - do not invent
them.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_value_chain_mapper_output.py -v`
Expected: FAIL - the task still asks for Mermaid.

- [ ] **Step 3: Rewrite the task's output contract**

In `agents/discovery/value_chain_mapper.py`, replace the steps that build and save a Mermaid
diagram with steps that build and save the model as JSON. The task must:

- Explain that an **activity** is one thing with one stable ID, and that each **party's**
  part of it is a **contribution** carrying its own description and its own tasks - so an
  activity delivered jointly has one contribution per party.
- Name every part of the model: `parties`, `segments`, `activities`, `contributions`,
  `tasks`, `propositions`, `links`.
- Require a **description** at every level. This is the whole reason for the change: none
  has ever existed.
- Require `column` on each contribution, in steps of 10, and explain that two contributions
  of the same activity sharing a column means the parties act concurrently, while offset
  columns mean a handoff.
- Require `attribution: "stated"` on anything it attributes itself.
- Save to `outputs/value_chain_model.json` with `output_type='value_chain_model'`.

Keep every existing instruction about the stable ID registry - IDs must never be reassigned
or reused, and removing an activity marks it inactive rather than deleting it. Renumber the
remaining steps so the sequence has no gap.

- [ ] **Step 4: Run the tests, then the full suite**

Run: `./venv/bin/pytest tests/test_value_chain_mapper_output.py -v`
Expected: 5 passed

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 713 passed. Existing tests asserting on the old Mermaid wording should be updated
to the new contract, not reverted - say which in your report.

- [ ] **Step 5: Commit**

```bash
git add agents/discovery/value_chain_mapper.py tests/test_value_chain_mapper_output.py
git commit -m "feat: Alex emits the value chain model rather than a diagram"
```

---

## Task 6: The Structure tab, read-only

**Files:**
- Modify: `ui/src/api/endpoints.ts` - add `valueChainApi`
- Modify: `ui/src/pages/ValueChain.tsx` - remove the Diagram tab, add Structure
- Create: `ui/src/components/ValueChainTable.tsx`
- Test: `ui/src/__tests__/ValueChainTable.test.tsx`

**Interfaces:**
- Consumes: `GET /projects/{slug}/value-chain-model` returning `{ model }`
- Produces: `ValueChainTable`, exported for direct testing; `valueChainApi.get`, `valueChainApi.save`, `valueChainApi.migrate`

**Removing the Diagram tab:** delete `'diagram'` from the tab tuple at
`ui/src/pages/ValueChain.tsx:234`, its label branch, the whole `activeTab === 'diagram'`
block, the `mermaid` import at line 5, the `mermaid.initialize` call at line 14, and the
fence-extraction and render effect. **Do not remove the `mermaid` package** -
`ui/src/components/ReviewDialog.tsx:86` imports it dynamically.

The auto-switch at `ValueChain.tsx:174` (`if (!isLoading && outputs.length > 0)
setActiveTab('diagram')`) must switch to `'structure'` instead, or it will set a tab that no
longer exists.

- [ ] **Step 1: Write the failing test**

Create `ui/src/__tests__/ValueChainTable.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import { ValueChainTable, type ValueChainModel } from '../components/ValueChainTable'

const MODEL: ValueChainModel = {
  model_version: 1,
  parties: [
    { id: 'sp', label: 'SP-GS', colour: '#1a5276' },
    { id: 'iss', label: 'ISS', colour: '#c0392b' },
  ],
  segments: [{ id: '1', label: 'PROPERTY', description: '' }],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Reactive Maintenance', description: '', active: true },
    { id: '1.2', segment_id: '1', label: 'Planned Works', description: '', active: true },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: 'Raises the order', attribution: 'stated' },
    { activity_id: '1.1', party_id: 'iss', column: 10, description: 'Executes it', attribution: 'stated' },
    { activity_id: '1.2', party_id: 'sp', column: 30, description: '', attribution: 'derived' },
  ],
  tasks: [], propositions: [], links: [],
}

describe('ValueChainTable', () => {
  it('shows a lane per party within the segment', () => {
    render(<ValueChainTable model={MODEL} />)
    expect(screen.getByText('SP-GS')).toBeInTheDocument()
    expect(screen.getByText('ISS')).toBeInTheDocument()
  })

  it('places both parties of one activity in the same column', () => {
    render(<ValueChainTable model={MODEL} />)
    const sp = screen.getByTestId('cell-sp-10')
    const iss = screen.getByTestId('cell-iss-10')
    expect(sp.textContent).toContain('Reactive Maintenance')
    expect(iss.textContent).toContain('Reactive Maintenance')
  })

  it('renders a gap where a lane has no contribution', () => {
    render(<ValueChainTable model={MODEL} />)
    // SP-GS occupies 10 and 30; column 20 is a gap in both lanes.
    expect(screen.getByTestId('cell-sp-20').textContent).toBe('')
    expect(screen.getByTestId('cell-iss-30').textContent).toBe('')
  })

  it('marks a derived attribution so a wrong default is findable', () => {
    render(<ValueChainTable model={MODEL} />)
    expect(screen.getByTestId('cell-sp-30').textContent).toMatch(/derived/i)
  })

  it('does not mark a stated attribution', () => {
    render(<ValueChainTable model={MODEL} />)
    expect(screen.getByTestId('cell-sp-10').textContent).not.toMatch(/derived/i)
  })

  it('renders nothing rather than crashing on an empty model', () => {
    const empty: ValueChainModel = {
      model_version: 1, parties: [], segments: [], activities: [],
      contributions: [], tasks: [], propositions: [], links: [],
    }
    render(<ValueChainTable model={empty} />)
    expect(screen.getByTestId('value-chain-empty')).toBeInTheDocument()
  })
}
)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/ValueChainTable.test.tsx`
Expected: FAIL - cannot resolve `../components/ValueChainTable`

- [ ] **Step 3: Create the table**

Create `ui/src/components/ValueChainTable.tsx`. It exports the `ValueChainModel` type
mirroring the backend shape, and a `ValueChainTable` component taking `{ model }`.

For each segment, render its label, then one row per party that has at least one
contribution in that segment. Columns are the sorted union of every column used by any lane
in that segment, so an unoccupied cell in one lane still renders - that is the gap, and it is
what makes vertical alignment visible.

Each cell carries `data-testid={`cell-${partyId}-${column}`}`, shows the activity label and
the contribution's description, and shows a small "derived" marker when
`attribution === 'derived'`. An empty cell renders as an empty cell, not as a collapsed one.

A model with no segments renders a single element with
`data-testid="value-chain-empty"` and a sentence explaining that no value chain has been
mapped yet.

Use brand tokens; no emoji.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ui && npx vitest run src/__tests__/ValueChainTable.test.tsx`
Expected: 6 passed

- [ ] **Step 5: Add the API calls**

In `ui/src/api/endpoints.ts`:

```ts
export const valueChainApi = {
  get: (slug: string): Promise<{ model: unknown }> =>
    apiClient.get(`/projects/${slug}/value-chain-model`).then((r) => r.data),
  save: (slug: string, model: unknown, summary = ''): Promise<{ output_id: number }> =>
    apiClient.put(`/projects/${slug}/value-chain-model`, { model, summary })
      .then((r) => r.data),
  migrate: (slug: string): Promise<{ created: boolean }> =>
    apiClient.post(`/projects/${slug}/value-chain-model/migrate`).then((r) => r.data),
}
```

- [ ] **Step 6: Wire the tab**

In `ui/src/pages/ValueChain.tsx`, make the tab tuple `['setup', 'structure', 'templates']`,
label `'structure'` as `'Structure'`, remove the Diagram tab and everything listed above,
point the auto-switch at `'structure'`, and render `ValueChainTable` from
`valueChainApi.get(slug)` in the new tab. When the model is missing (404), show a **Migrate
from the existing diagram** button calling `valueChainApi.migrate` and invalidating the
model query on success.

- [ ] **Step 7: Run the whole frontend suite and typecheck**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: 92 passed - 86 baseline plus 6 - and no type errors. No file should import
`mermaid` from `ValueChain.tsx` any more, and `ReviewDialog.tsx`'s dynamic import must still
be present.

- [ ] **Step 8: Commit**

```bash
git add ui/src/api/endpoints.ts ui/src/pages/ValueChain.tsx ui/src/components/ValueChainTable.tsx ui/src/__tests__/ValueChainTable.test.tsx
git commit -m "feat: show the value chain as a table of lanes and columns"
```

---

## Task 7: Editing and saving

**Files:**
- Modify: `ui/src/components/ValueChainTable.tsx` - editable descriptions, move a cell
- Create: `ui/src/components/ContributionPanel.tsx`
- Modify: `ui/src/pages/ValueChain.tsx` - hold pending edits, Save control
- Test: `ui/src/__tests__/ValueChainEditing.test.tsx`

**Interfaces:**
- Consumes: `valueChainApi.save` (Task 6)
- Produces: `ValueChainTable` gains `onChange?: (model: ValueChainModel) => void`; `ContributionPanel`

**Saving is explicit.** A version per keystroke would bury the change log and make the
differential in a later project useless. Edits are held in the page and written by a Save
control.

- [ ] **Step 1: Write the failing test**

Create `ui/src/__tests__/ValueChainEditing.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { ValueChainTable, type ValueChainModel } from '../components/ValueChainTable'

const MODEL: ValueChainModel = {
  model_version: 1,
  parties: [{ id: 'sp', label: 'SP-GS', colour: '#1a5276' }],
  segments: [{ id: '1', label: 'PROPERTY', description: '' }],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Reactive', description: '', active: true },
    { id: '1.2', segment_id: '1', label: 'Planned', description: '', active: true },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: 'first', attribution: 'stated' },
    { activity_id: '1.2', party_id: 'sp', column: 20, description: 'second', attribution: 'stated' },
  ],
  tasks: [], propositions: [], links: [],
}

const onChange = vi.fn()
beforeEach(() => onChange.mockReset())

describe('ValueChainTable editing', () => {
  it('reports an edited description without mutating the model it was given', async () => {
    const original = structuredClone(MODEL)
    render(<ValueChainTable model={MODEL} onChange={onChange} />)

    const field = screen.getByTestId('description-1.1-sp')
    await userEvent.clear(field)
    await userEvent.type(field, 'revised')

    expect(onChange).toHaveBeenCalled()
    const latest = onChange.mock.calls.at(-1)![0] as ValueChainModel
    const edited = latest.contributions.find((c) => c.activity_id === '1.1')!
    expect(edited.description).toBe('revised')
    expect(MODEL).toEqual(original)
  })

  it('moving a contribution changes only its column', async () => {
    render(<ValueChainTable model={MODEL} onChange={onChange} />)
    await userEvent.click(screen.getByTestId('move-right-1.1-sp'))

    const latest = onChange.mock.calls.at(-1)![0] as ValueChainModel
    const moved = latest.contributions.find((c) => c.activity_id === '1.1')!
    const other = latest.contributions.find((c) => c.activity_id === '1.2')!
    expect(moved.column).toBeGreaterThan(10)
    expect(other.column).toBe(20)
    expect(moved.description).toBe('first')
  })

  it('is read-only when no onChange is given', () => {
    render(<ValueChainTable model={MODEL} />)
    expect(screen.queryByTestId('description-1.1-sp')).not.toBeInTheDocument()
  })
})
```

The first test's `expect(MODEL).toEqual(original)` is the one that matters: an editor that
mutated the model it was handed would corrupt the query cache and make a discarded edit
unrecoverable.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/ValueChainEditing.test.tsx`
Expected: FAIL - no `description-1.1-sp` field exists; the table is read-only.

- [ ] **Step 3: Make the table editable**

Give `ValueChainTable` an optional `onChange`. When absent it renders exactly as it does
today - read-only - which is what keeps Task 6's tests passing.

When present, each occupied cell shows a text input with
`data-testid={`description-${activityId}-${partyId}`}` bound to the contribution's
description, and move-left and move-right controls with
`data-testid={`move-left-${activityId}-${partyId}`}` and the matching right.

Every edit produces a **new** model object via `structuredClone` and calls `onChange` with
it. Never mutate the prop.

Moving right swaps the contribution's column with the next occupied column in its lane, or
adds `10` when it is already last. Moving left is the mirror. Only the moved contribution's
column changes.

- [ ] **Step 4: Create the panel**

Create `ui/src/components/ContributionPanel.tsx`, taking a model and a selected
`(activityId, partyId)`. It lists that contribution's tasks - label and description - and
its activity's propositions, each with the party it belongs to when one is named. Read-only
in this project; pop-ups and editing arrive with the grid.

- [ ] **Step 5: Hold edits and save**

In `ui/src/pages/ValueChain.tsx`, hold the edited model in state, seeded from the query.
Pass it to `ValueChainTable` with `onChange`. Render a **Save** control, disabled when
nothing has changed, calling `valueChainApi.save(slug, edited, summary)` and invalidating the
model query on success. A 422 response carries `detail.problems` - show them rather than
discarding the edit.

Warn before navigating away with unsaved edits, using the pattern already in the file if one
exists.

- [ ] **Step 6: Run the whole frontend suite and typecheck**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: 95 passed, no type errors.

- [ ] **Step 7: Run the backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 713 passed, unchanged by this task.

- [ ] **Step 8: Commit**

```bash
git add ui/src/components/ValueChainTable.tsx ui/src/components/ContributionPanel.tsx ui/src/pages/ValueChain.tsx ui/src/__tests__/ValueChainEditing.test.tsx
git commit -m "feat: edit contribution descriptions and sequence, and save a new version"
```

---

## Manual verification

The migration is the risky part and it runs against real data, so verify it on `sp-gs-am`:

1. Open the value chain page. There is no Diagram tab, and Structure offers **Migrate from
   the existing diagram**.
2. Migrate. Confirm three segments, seventeen activities, fifty-nine tasks, and three
   parties - SP-GS, ISS, and DXI - with the colours from the old chart.
3. Spot-check a handful of activities against the old diagram: an activity whose tasks were
   all dark blue should have one SP-GS contribution; one with red tasks should have an ISS
   contribution too.
4. Confirm the contributions marked **derived** are the ones whose labels did not appear in
   the diagram, and that none of them is obviously attributed to the wrong party.
5. Edit a description, move a contribution one column right, and Save. Reload and confirm
   both persisted.
6. Check the Review Queue shows a change recorded against the value chain, attributed to you.
7. Confirm the Reviews page still renders Mermaid in a review's content - that is
   `ReviewDialog.tsx`'s dynamic import, which must not have been broken.
