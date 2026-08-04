# Interview Evidence Addressability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every interview answer addressable, tagged, and retrievable, so Casey groups themes and strategic requirements from stored facts rather than from prose.

**Architecture:** A reserved root node `0` gives A, C, and S scripts something to anchor to. Every script gains a registered opaque ID, a node ID, and a relationship, so citations survive renames. Maya tags each section with a discipline, a question intent, and an elicitation mode from closed vocabularies. Completed sessions write one `interview_answers` row per question, carrying denormalised tags fixed at answer time, plus a matching Chroma document for semantic recall. Exact grouping comes from SQL; recall comes from Chroma.

**Tech Stack:** Python 3.13, FastAPI, aiosqlite (raw SQL, no ORM), Pydantic v2, CrewAI, ChromaDB, React 18 + TypeScript + Vite + Tailwind v3, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-04-interview-evidence-addressability-design.md`

**Phase 1 of the spec (the requirement key split) is already implemented and committed as `6cf3557f`.** This plan covers phases 2 to 6. Do not redo phase 1.

## Global Constraints

- **British English throughout** - `-ise` not `-ize` (organise, prioritise, recognise), `-our` not `-or` (behaviour, colour), `-re` not `-er` (centre, fibre), `-ogue` not `-og` (catalogue, dialogue).
- **Spaced hyphen ` - ` in all content, never an em dash `—`.** Oxford comma in lists of three or more.
- **No emoji in rendered web content.** Lucide React icons only, imported from `lucide-react` in `ui/src/components/agentStatus.ts`.
- **Tailwind brand tokens only** - `text-brand`, `bg-brand`, `bg-surface`, `bg-surface-raised`, `bg-surface-card`, `text-primary`, `text-secondary`, `text-muted`. Never `sky-*` or `blue-*`.
- **All raw SQL lives in `api/database.py`.** No ORM. Schema changes are `CREATE TABLE IF NOT EXISTS` or `ALTER TABLE` run on connection open, and must also be added to any test fixture that creates that table by hand.
- **Stable IDs are never changed and never reused.** This applies to value chain `Ln.n.n` IDs and, from Task 2, to interview `script_id` values.
- **Never modify `agents/tools/human_input.py`.**
- **Never run `git add -A` or `git add .`** - the working tree holds unrelated untracked files (screenshots, `.docx`). Stage the exact paths listed in each task.
- **Backend tests:** `./venv/bin/pytest -q --ignore=tests/integration` (not bare `pytest`).
- **Frontend tests:** `cd ui && npx vitest run` and `cd ui && npx tsc --noEmit`.
- **Both suites must pass before every commit.** Current baseline: 898 backend passed, 2 skipped; 346 frontend passed; `tsc` clean.
- **Reserved value:** the L0 entity ID is the string `"0"`. It is never renumbered and no value chain may use it.

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `api/services/interview_script_model.py` | Pure validation of interview script structure, anchoring, and tag vocabularies. No I/O, mirroring `value_chain_model.py`. |
| `api/services/interview_answer_service.py` | Turning a completed session into `interview_answers` rows and Chroma documents. |
| `tests/test_value_chain_entity.py` | The reserved root node. |
| `tests/test_interview_script_model.py` | Script identity, anchoring, and question ID uniqueness. |
| `tests/test_interview_tag_vocabularies.py` | Discipline, question intent, and elicitation. |
| `tests/test_lever_elicitation.py` | The ordering rule and derived lever status. |
| `tests/test_interview_answers.py` | The answer store and the `qa_pairs` contract. |
| `tests/test_answer_citations.py` | Casey citing answer IDs. |

**Modified:**

| File | Change |
|---|---|
| `api/services/value_chain_model.py` | `ENTITY_ID`, `validate_entity`, `validate_has_entity`, entity handling in `validate_against_registry`. |
| `agents/tools/sqlite_state.py` | Validators for `interview_scripts` and `interview_script_registry`. |
| `agents/discovery/value_chain_mapper.py` | Alex writes the entity into the model and the tree. |
| `agents/discovery/interaction_designer.py` | Maya emits script IDs, anchors, tags, and the unaided-before-prompted order; reads `value_levers`. |
| `agents/discovery/value_lever_analyst.py` | Morgan's levers gain a derived status field. |
| `agents/discovery/synthesis_analyst.py` | Casey reads answers and cites answer IDs. |
| `api/database.py` | `interview_answers` table, its migration, and its helpers. |
| `api/services/auto_assign_service.py` | Keys on `script_id` and takes `activity_id` from the script's `node_id`. |
| `api/services/interview_service.py` | `complete_session` writes answer rows. |
| `api/routers/interviews.py` | `CompleteRequest.qa_pairs` carries `question_id` and `follow_up`. |
| `api/models.py` | `ProjectSettings.disciplines`. |
| `agents/tools/chroma_query.py` | `collection='interviews'`. |
| `ui/src/pages/VoiceInterview.tsx` | `qaRef` carries `question_id` and `follow_up`. |
| `ui/src/components/tabs/MayaSetupTab.tsx` | The discipline vocabulary editor. |

---

### Task 1: The reserved root node

**Files:**
- Modify: `api/services/value_chain_model.py`
- Modify: `agents/tools/sqlite_state.py:19-40` (`_validate_value_chain_model`)
- Modify: `agents/discovery/value_chain_mapper.py`
- Test: `tests/test_value_chain_entity.py` (create)

**Interfaces:**
- Produces: `ENTITY_ID = "0"`; `validate_entity(model: dict) -> list[str]`; `validate_has_entity(model: dict) -> list[str]`. Task 2 consumes `ENTITY_ID` and the registry's `L0` entry.

**Why:** A and C scripts must anchor to the L0 entity, and there is no such node. The model's top level is the three chains, and GS UK exists only as a *party*, which contributes to chains rather than being one.

`validate_entity` goes in `validate_model`, which gates the grid's Save. `validate_has_entity` goes only in the agent write path, following the rule already established by `validate_contributions_have_tasks`: a person may hold an incomplete state while working, a deliverable may not. Putting presence in `validate_model` would refuse to save any existing model, none of which has an entity yet.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_value_chain_entity.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_value_chain_entity.py -q`
Expected: FAIL with `ImportError: cannot import name 'ENTITY_ID'`

- [ ] **Step 3: Add the entity rules**

In `api/services/value_chain_model.py`, add near `_LEVEL_ARRAYS`:

```python
# The L0 entity is the organisation itself. Its id is reserved: A, C, and S interview
# scripts anchor here because a regulator regulates the entity and a customer of the entity
# may sit in another company entirely, so neither has a position in any chain.
ENTITY_ID = "0"

_LEVEL_NOUN = {"L0": "entity", "L1": "segment", "L2": "activity", "L3": "task"}


def validate_entity(model: dict) -> list[str]:
    """The reserved id is held, and no value chain takes it.

    In validate_model, which gates the grid's Save, because both rules are cheap and true
    of every model. Absence is NOT checked here - see validate_has_entity.
    """
    problems: list[str] = []
    entity = model.get("entity")
    if entity is not None and entity.get("id") != ENTITY_ID:
        problems.append(
            f"the L0 entity must have id {ENTITY_ID!r}, not {entity.get('id')!r} - the id is "
            "reserved and never renumbered"
        )
    for segment in model.get("segments", []):
        if segment.get("id") == ENTITY_ID:
            problems.append(
                f"id {ENTITY_ID} is reserved for the L0 entity and cannot be a value chain - "
                "take the next unused number"
            )
    return problems


def validate_has_entity(model: dict) -> list[str]:
    """The entity is present.

    Held to the agent, not to the editor, exactly as validate_contributions_have_tasks is.
    Every model built before this rule existed lacks an entity, and refusing those in
    validate_model would refuse to save any project until its chain was rebuilt.
    """
    if model.get("entity") is None:
        return [
            "the model has no L0 entity - add {\"entity\": {\"id\": \"0\", \"label\": ..., "
            "\"description\": ...}} naming the organisation itself, because interview "
            "scripts for regulators, customers, and corporate services anchor to it"
        ]
    return []
```

Replace the loop in `validate_against_registry` so the entity is checked alongside the arrays:

```python
    entity = model.get("entity")
    levels: list[tuple[str, list]] = [("L0", [entity] if entity else [])]
    levels += [(level, model.get(array, [])) for level, array in _LEVEL_ARRAYS]

    for level, items in levels:
        for item in items:
            registered = known.get(item.get("id"))
            if registered is None:
                continue
            registered_level, registered_label = registered
            if registered_level != level:
                problems.append(
                    f"{_LEVEL_NOUN[level]} {item.get('id')} is registered as a "
                    f"{registered_level}, not a {level} - use an unused id for it"
                )
            elif registered_label and item.get("label") and item["label"] != registered_label:
                problems.append(
                    f"id {item.get('id')} already means {registered_label!r} and cannot be "
                    f"reused for {item.get('label')!r} - take the next unused number instead"
                )
    return problems
```

Add `problems.extend(validate_entity(model))` to the end of `validate_model`, before its `return`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_value_chain_entity.py -q`
Expected: PASS, 8 tests.

- [ ] **Step 5: Hold the agent to the stricter rule**

In `agents/tools/sqlite_state.py`, extend `_validate_value_chain_model`'s import and body:

```python
    from api.services.value_chain_model import (
        validate_against_registry,
        validate_contributions_have_tasks,
        validate_has_entity,
        validate_model,
    )

    problems = validate_model(parsed)
    problems.extend(validate_contributions_have_tasks(parsed))
    # Same reasoning as contributions-have-tasks: the editor may hold a model with no
    # entity while a person works on it, but a deliverable that A and C scripts cannot
    # anchor to is not finished.
    problems.extend(validate_has_entity(parsed))
    problems.extend(validate_against_registry(parsed, _current_registry(slug)))
```

- [ ] **Step 6: Make Alex write the entity**

In `agents/discovery/value_chain_mapper.py`, find the step instructing the model write (search for `key='value_chain_model'`) and insert this immediately before it:

```python
            "Write the L0 entity as the model's `entity` field before anything else:\n"
            "   {\"entity\": {\"id\": \"0\", \"label\": \"<the organisation's own name>\", "
            "\"description\": \"<what this organisation is and what it is responsible for>\"}}\n"
            "   Id \"0\" is reserved for it and is never renumbered, and no value chain may "
            "use that number. Interview scripts for regulators, customers, and corporate "
            "services anchor to the entity because they concern the organisation as a whole "
            "rather than one chain.\n"
```

Find the step writing `value_chain_tree` and add:

```python
            "   The tree has a single root: the L0 entity, id \"0\", level \"L0\", with the "
            "value chains as its children. The registry is derived from the tree, so an "
            "entity absent from the tree is absent from the registry and nothing can anchor "
            "to it.\n"
```

- [ ] **Step 7: Run both suites**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS, 906 passed, 2 skipped.

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, 346 tests, tsc silent.

- [ ] **Step 8: Mutation-test the reservation**

Confirm each mutation is killed by at least one test. Restore the file after each.

```bash
cp api/services/value_chain_model.py /tmp/vcm.bak
# M1: reservation dropped - a chain may take id 0
./venv/bin/python -c "
import pathlib;p=pathlib.Path('api/services/value_chain_model.py');s=p.read_text()
p.write_text(s.replace('if segment.get(\"id\") == ENTITY_ID:','if False:'))"
./venv/bin/pytest tests/test_value_chain_entity.py -q   # expect 1 failed
cp /tmp/vcm.bak api/services/value_chain_model.py
# M2: entity omitted from the registry comparison
./venv/bin/python -c "
import pathlib;p=pathlib.Path('api/services/value_chain_model.py');s=p.read_text()
p.write_text(s.replace('[(\"L0\", [entity] if entity else [])]','[(\"L0\", [])]'))"
./venv/bin/pytest tests/test_value_chain_entity.py -q   # expect 2 failed
cp /tmp/vcm.bak api/services/value_chain_model.py
./venv/bin/pytest tests/test_value_chain_entity.py -q   # expect 8 passed
```

- [ ] **Step 9: Commit**

```bash
git add api/services/value_chain_model.py agents/tools/sqlite_state.py \
  agents/discovery/value_chain_mapper.py tests/test_value_chain_entity.py
git commit -m "feat(value-chain): a reserved L0 entity node for scripts to anchor to"
```

---

### Task 2: Script identity and anchoring

**Files:**
- Create: `api/services/interview_script_model.py`
- Modify: `agents/tools/sqlite_state.py` (`_VALIDATORS`)
- Modify: `agents/discovery/interaction_designer.py`
- Test: `tests/test_interview_script_model.py` (create)

**Interfaces:**
- Consumes: `ENTITY_ID` from Task 1.
- Produces: `RELATIONSHIPS: frozenset[str]`; `LEVELS: frozenset[str]`; `question_id(script_id: str, section_id: str, question_no: int) -> str`; `validate_scripts(scripts: dict) -> list[str]`; `validate_scripts_against_registry(scripts: dict, registry: dict) -> list[str]`; `validate_script_registry_succession(current: dict, proposed: dict) -> list[str]`. Tasks 3, 4, 6, and 7 all consume `validate_scripts` and `question_id`.

**Why:** `node_label` is the script's own title in every case, so no script links to a node. Question IDs are `Q1.1`, section-relative, so all 17 L2 scripts emit `Q1.1`. Both must be fixed before an answer can be cited.

Script IDs are opaque (`SC-001`) rather than derived from the node, because node `0` carries several scripts at once - L0, A, C, and one per corporate services function - so a node-derived key collides on the very node this design exists to make usable.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_interview_script_model.py`:

```python
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
        "sections": sections if sections is not None else [
            {"section_id": "S1", "title": "Opening", "questions": [
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
    s = _script(sections=[{"title": "Opening", "questions": [{"id": "Q1", "text": "x"}]}])
    assert any("section_id" in p for p in validate_scripts(_scripts(s)))


def test_two_sections_in_one_script_may_not_share_a_section_id():
    s = _script(sections=[
        {"section_id": "S1", "title": "A", "questions": [{"id": "Q1", "text": "x"}]},
        {"section_id": "S1", "title": "B", "questions": [{"id": "Q1", "text": "y"}]},
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_interview_script_model.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.interview_script_model'`

- [ ] **Step 3: Write the model**

Create `api/services/interview_script_model.py`:

```python
# api/services/interview_script_model.py
"""Interview script structure, anchoring, and identity - pure, no I/O.

Mirrors api/services/value_chain_model.py: the caller loads the registry, this module only
compares. Every function returns all problems as readable sentences rather than raising on
the first, so a writer sees everything wrong in one pass.
"""
from __future__ import annotations

from api.services.value_chain_model import ENTITY_ID  # noqa: F401  (re-exported meaning)

RELATIONSHIPS = frozenset({"internal", "customer", "regulator", "supplier", "partner"})
LEVELS = frozenset({"L0", "L1", "L2", "L3", "C", "A", "F", "S"})


def question_id(script_id: str, section_id: str, question_no: int) -> str:
    """A question's global address.

    Unique by construction rather than by luck of the sample: the old `Q1.1` was
    section-relative, so every one of the 17 L2 scripts emitted the same ids.
    """
    return f"{script_id}.{section_id}.Q{question_no}"


def validate_scripts(scripts: dict) -> list[str]:
    """Every way this script set is unciteable or unanchored."""
    problems: list[str] = []
    seen_script_ids: set[str] = set()

    for key, script in scripts.items():
        script_id = script.get("script_id")
        label = script_id or key

        if not script_id:
            problems.append(f"script {key!r} has no script_id")
        elif script_id in seen_script_ids:
            problems.append(
                f"script_id {script_id} is used twice - ids are assigned in order and never "
                "reused, because stored citations resolve through them"
            )
        else:
            seen_script_ids.add(script_id)

        if not script.get("node_id"):
            problems.append(
                f"script {label} has no node_id - anchor it to a value chain node, or to "
                f"{ENTITY_ID!r} when it concerns the organisation as a whole"
            )
        if script.get("level") not in LEVELS:
            problems.append(
                f"script {label} has level {script.get('level')!r}, which is not one of "
                f"{sorted(LEVELS)}"
            )
        if script.get("relationship") not in RELATIONSHIPS:
            problems.append(
                f"script {label} has relationship {script.get('relationship')!r}, which is "
                f"not one of {sorted(RELATIONSHIPS)}"
            )

        seen_section_ids: set[str] = set()
        for section in script.get("sections", []):
            section_id = section.get("section_id")
            if not section_id:
                problems.append(
                    f"script {label} has a section with no section_id "
                    f"({section.get('title')!r}) - a citation to a title cites a string that "
                    "may be rewritten"
                )
                continue
            if section_id in seen_section_ids:
                problems.append(f"script {label} uses section_id {section_id} twice")
            seen_section_ids.add(section_id)

    return problems


def validate_scripts_against_registry(scripts: dict, registry: dict) -> list[str]:
    """Every script anchored to a node the registry does not hold.

    An empty registry accepts anything, which is what a first run needs and what a project
    with no registry yet must not be blocked by.
    """
    known = {entry.get("id") for entry in registry.get("activities", [])}
    if not known:
        return []
    return [
        f"script {script.get('script_id') or key} is anchored to node "
        f"{script.get('node_id')!r}, which is not in the value chain registry"
        for key, script in scripts.items()
        if script.get("node_id") not in known
    ]


def validate_script_registry_succession(current: dict, proposed: dict) -> list[str]:
    """Every way a proposed script ledger would break what the current one records.

    Same rules as the value chain registry. Growth is free and retirement is free with the
    meaning kept (`active: false`); redefining or dropping an id is refused. Dropping is the
    worst: the ledger forgets, so nothing stops the id being handed to something else later,
    and every stored citation through it silently resolves to the wrong script.
    """
    problems: list[str] = []
    proposed_entries = {e.get("id"): e for e in proposed.get("scripts", [])}

    for entry in current.get("scripts", []):
        entry_id = entry.get("id")
        successor = proposed_entries.get(entry_id)
        if successor is None:
            problems.append(
                f"script_id {entry_id} is in the registry and missing from this one - retire "
                "it with active: false rather than dropping it, so the id is never handed to "
                "another script"
            )
        elif successor.get("node_id") != entry.get("node_id"):
            problems.append(
                f"script_id {entry_id} is registered against node {entry.get('node_id')} and "
                f"this moves it to {successor.get('node_id')} - take an unused id for the new "
                "script, because stored answers cite this one"
            )
    return problems
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_interview_script_model.py -q`
Expected: PASS, 16 tests.

- [ ] **Step 5: Register the validators on the write path**

In `agents/tools/sqlite_state.py`, add above `_VALIDATORS`:

```python
def _current_script_registry(slug: str) -> dict:
    """The script ledger in force, or an empty one when there is none yet."""
    settings = get_settings()
    path = latest_output_path(
        Path(settings.projects_dir) / slug / "outputs" / "interview_script_registry.json"
    )
    if path is None:
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _validate_interview_scripts(parsed: dict, slug: str) -> list[str]:
    from api.services.interview_script_model import (
        validate_scripts,
        validate_scripts_against_registry,
    )

    problems = validate_scripts(parsed)
    problems.extend(validate_scripts_against_registry(parsed, _current_registry(slug)))
    return problems


def _validate_interview_script_registry(parsed: dict, slug: str) -> list[str]:
    from api.services.interview_script_model import validate_script_registry_succession

    return validate_script_registry_succession(_current_script_registry(slug), parsed)
```

and extend the map:

```python
_VALIDATORS: dict[str, Callable[[dict, str], list[str]]] = {
    "value_chain_model": _validate_value_chain_model,
    "value_chain_registry": _validate_value_chain_registry,
    "interview_scripts": _validate_interview_scripts,
    "interview_script_registry": _validate_interview_script_registry,
}
```

- [ ] **Step 6: Make Maya emit identity and anchors**

In `agents/discovery/interaction_designer.py`, find the step writing `key='interview_scripts'` and insert this immediately before it:

```python
            "Every script carries its identity and its anchor. The top-level key of the "
            "scripts object is the script_id.\n"
            "   {\"SC-001\": {\"script_id\": \"SC-001\", \"node_id\": \"1.2\", "
            "\"level\": \"L2\", \"relationship\": \"internal\", "
            "\"node_label\": \"<human title, for display only>\", \"sections\": [...]}}\n"
            "   - script_id: SC-001, SC-002, ... assigned in order. Never change one and "
            "never reuse one: stored interview answers cite scripts through these ids.\n"
            "   - node_id: the stable value chain id this script is about. L1 scripts anchor "
            "to a chain (\"1\"), L2 to a stage (\"1.2\"), L3 to an activity (\"1.2.3\"). L0, "
            "A (auditor or regulator), C (customer), and S (corporate services) scripts "
            "anchor to \"0\", the L0 entity - unless one is genuinely scoped to a single "
            "chain, such as a fleet operator-licence regulator, which anchors to that chain. "
            "F (frontline) scripts anchor to the L2 or L3 the person actually works in.\n"
            "   - relationship: internal, customer, regulator, supplier, or partner. This is "
            "what records that an interviewee is external and still speaking about this "
            "organisation. Without it an auditor's script and a board member's script both "
            "anchor to \"0\" and become indistinguishable.\n"
            "   - every section carries a section_id unique within its script (S1, S2, ...). "
            "A citation to a section title cites a string you may rewrite on your next run.\n"
            "Then use SQLiteStateTool with operation='write', "
            "key='interview_script_registry', agent_name='interaction_designer' to save the "
            "ledger: {\"scripts\": [{\"id\": \"SC-001\", \"node_id\": \"1.2\", "
            "\"active\": true}, ...]}. Retire a script you no longer need with "
            "active: false rather than dropping it.\n"
```

- [ ] **Step 7: Run both suites**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS, 922 passed, 2 skipped.

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, 346 tests, tsc silent.

- [ ] **Step 8: Mutation-test the uniqueness rules**

```bash
cp api/services/interview_script_model.py /tmp/ism.bak
# M1: duplicate script ids accepted
./venv/bin/python -c "
import pathlib;p=pathlib.Path('api/services/interview_script_model.py');s=p.read_text()
p.write_text(s.replace('elif script_id in seen_script_ids:','elif False:'))"
./venv/bin/pytest tests/test_interview_script_model.py -q   # expect 1 failed
cp /tmp/ism.bak api/services/interview_script_model.py
# M2: question ids drop the script, reintroducing the collision
./venv/bin/python -c "
import pathlib;p=pathlib.Path('api/services/interview_script_model.py');s=p.read_text()
p.write_text(s.replace('return f\"{script_id}.{section_id}.Q{question_no}\"','return f\"{section_id}.Q{question_no}\"'))"
./venv/bin/pytest tests/test_interview_script_model.py -q   # expect 2 failed
cp /tmp/ism.bak api/services/interview_script_model.py
# M3: a dropped script id passes succession
./venv/bin/python -c "
import pathlib;p=pathlib.Path('api/services/interview_script_model.py');s=p.read_text()
p.write_text(s.replace('if successor is None:','if False:'))"
./venv/bin/pytest tests/test_interview_script_model.py -q   # expect 1 failed
cp /tmp/ism.bak api/services/interview_script_model.py
./venv/bin/pytest tests/test_interview_script_model.py -q   # expect 16 passed
```

- [ ] **Step 9: Commit**

```bash
git add api/services/interview_script_model.py agents/tools/sqlite_state.py \
  agents/discovery/interaction_designer.py tests/test_interview_script_model.py
git commit -m "feat(interviews): scripts carry a registered id, a node anchor, and a relationship"
```

---

### Task 3: The consumers join on the anchor

**Files:**
- Modify: `api/services/auto_assign_service.py:38-90`
- Modify: `api/database.py` (`node_template_assignments` gains `script_id`)
- Test: `tests/test_auto_assign_anchor.py` (create)

**Interfaces:**
- Consumes: `validate_scripts` and the script shape from Task 2.
- Produces: `node_template_assignments.script_id`, which Task 7 reads to tag an answer.

**Why:** `auto_assign_interview_scripts` keys assignments on `node_label` and takes `activity_id` from whatever assignment already existed - so the node link is whatever a human last set, and renaming a script orphans its assignment. The script now states its own anchor, so the assignment takes it from there.

- [ ] **Step 1: Write the failing test**

Create `tests/test_auto_assign_anchor.py`:

```python
# tests/test_auto_assign_anchor.py
"""Assignments follow the script's own anchor.

auto_assign keyed on node_label - the script's title - and took activity_id from whatever
assignment already existed, so the node link was whatever a human last set and a retitled
script orphaned its assignment. The script now states its anchor, so it is the authority.
"""
import json
from pathlib import Path

import pytest

from api.config import get_settings
from api.database import fetch_node_template_assignments, fetch_project, get_connection
from api.services.auto_assign_service import auto_assign_interview_scripts

SLUG = "anchor-test"
PROJECT = {
    "client_slug": SLUG, "llm_mode": "standard", "sector": "utilities",
    "stakeholder_groups": [], "value_stream_labels": [], "crews_enabled": ["requirements"],
    "review_gates": True, "slack_channel": "",
}
SCRIPTS = {
    "SC-001": {
        "script_id": "SC-001", "node_id": "1.2", "level": "L2", "relationship": "internal",
        "node_label": "Planned Maintenance L2 Interview", "research_brief": "b",
        "sections": [{"section_id": "S1", "title": "Opening", "questions": []}],
    },
    "SC-010": {
        "script_id": "SC-010", "node_id": "0", "level": "A", "relationship": "regulator",
        "node_label": "Internal Audit Interview", "research_brief": "b",
        "sections": [{"section_id": "S1", "title": "Governance", "questions": []}],
    },
}


@pytest.fixture
def project(client):
    async def _make():
        await client.post("/projects", json=PROJECT)
        outputs = Path(get_settings().projects_dir) / SLUG / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "interview_scripts.json").write_text(json.dumps(SCRIPTS))
    return _make


@pytest.mark.asyncio
async def test_the_assignment_takes_the_node_from_the_script(project):
    await project()
    await auto_assign_interview_scripts(SLUG)
    async with get_connection(SLUG) as conn:
        proj = await fetch_project(conn, slug=SLUG)
        rows = await fetch_node_template_assignments(conn, proj["id"])
    by_script = {r["script_id"]: r for r in rows}
    assert by_script["SC-001"]["activity_id"] == "1.2"


@pytest.mark.asyncio
async def test_an_external_script_is_assigned_to_the_entity(project):
    """The case that had no answer before: an auditor's script named itself and anchored to
    nothing, so it appeared in no coverage figure at all."""
    await project()
    await auto_assign_interview_scripts(SLUG)
    async with get_connection(SLUG) as conn:
        proj = await fetch_project(conn, slug=SLUG)
        rows = await fetch_node_template_assignments(conn, proj["id"])
    audit = next(r for r in rows if r["script_id"] == "SC-010")
    assert audit["activity_id"] == "0"


@pytest.mark.asyncio
async def test_retitling_a_script_keeps_its_assignment(project):
    """The defect keying on node_label caused: a retitled script looked like a new node, so
    it gained a second assignment and the first was orphaned."""
    await project()
    await auto_assign_interview_scripts(SLUG)

    retitled = json.loads(json.dumps(SCRIPTS))
    retitled["SC-001"]["node_label"] = "Planned Maintenance - revised title"
    outputs = Path(get_settings().projects_dir) / SLUG / "outputs"
    (outputs / "interview_scripts.json").write_text(json.dumps(retitled))
    await auto_assign_interview_scripts(SLUG)

    async with get_connection(SLUG) as conn:
        proj = await fetch_project(conn, slug=SLUG)
        rows = await fetch_node_template_assignments(conn, proj["id"])
    assert len([r for r in rows if r["script_id"] == "SC-001"]) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_auto_assign_anchor.py -q`
Expected: FAIL - `script_id` is not a column on `node_template_assignments`.

- [ ] **Step 3: Add the column**

In `api/database.py`, find `_migrate_node_template_assignments` (search for `CREATE TABLE IF NOT EXISTS node_template_assignments`), add `script_id TEXT` to the `CREATE TABLE` statement, and add the migration for existing databases immediately after the `CREATE TABLE`:

```python
    async with conn.execute("PRAGMA table_info(node_template_assignments)") as cur:
        cols = {row["name"] async for row in cur}
    if "script_id" not in cols:
        await conn.execute(
            "ALTER TABLE node_template_assignments ADD COLUMN script_id TEXT"
        )
    await conn.commit()
```

Then change `upsert_node_template_assignment` to take and persist the script ID:

```python
async def upsert_node_template_assignment(
    conn: aiosqlite.Connection,
    project_id: int,
    node_label: str,
    interview_template_id: int | None,
    questionnaire_template_id: int | None,
    activity_id: str | None = None,
    script_id: str | None = None,
) -> None:
    """Match on script_id when there is one, on node_label when there is not.

    Rows written before script ids existed have none, and matching on the id alone would
    write a second assignment beside every one of them.
    """
    if script_id:
        where, params = "project_id = ? AND script_id = ?", (project_id, script_id)
    else:
        where, params = "project_id = ? AND node_label = ?", (project_id, node_label)

    async with conn.execute(
        f"SELECT id FROM node_template_assignments WHERE {where}", params
    ) as cur:
        existing = await cur.fetchone()

    if existing:
        await conn.execute(
            "UPDATE node_template_assignments SET node_label = ?, interview_template_id = ?, "
            "questionnaire_template_id = ?, activity_id = ?, script_id = ? WHERE id = ?",
            (node_label, interview_template_id, questionnaire_template_id, activity_id,
             script_id, existing["id"]),
        )
    else:
        await conn.execute(
            "INSERT INTO node_template_assignments (project_id, node_label, "
            "interview_template_id, questionnaire_template_id, activity_id, script_id) "
            "VALUES (?,?,?,?,?,?)",
            (project_id, node_label, interview_template_id, questionnaire_template_id,
             activity_id, script_id),
        )
    await conn.commit()
```

Keep the existing call sites working by passing `script_id=None` from `auto_assign_questionnaire_scripts`, which has no script IDs of its own.

- [ ] **Step 4: Repoint auto_assign**

In `api/services/auto_assign_service.py`, replace the assignment loop's key and anchor:

```python
        # Keyed on script_id, not node_label. The label is the script's own title, so
        # retitling one made it look like a new node: it gained a second assignment and the
        # first was orphaned. Rows written before script ids existed still key on the label.
        current = {
            (a.get("script_id") or a["node_label"]): a
            for a in await fetch_node_template_assignments(conn, project_id)
        }

        for script_key, script in scripts.items():
            script_id = script.get("script_id") or script_key
            node_label = script.get("node_label") or script_key
            # The script states its own anchor. Taking activity_id from the existing
            # assignment made the node link whatever a human last set, which is why A and C
            # scripts had none at all.
            activity_id = script.get("node_id") or current.get(script_id, {}).get("activity_id")
            assignment = current.get(script_id, {})
```

and pass `script_id=script_id` through to `upsert_node_template_assignment`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `./venv/bin/pytest tests/test_auto_assign_anchor.py -q`
Expected: PASS, 3 tests.

- [ ] **Step 6: Run both suites and commit**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS, 925 passed, 2 skipped.

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS.

```bash
git add api/database.py api/services/auto_assign_service.py tests/test_auto_assign_anchor.py
git commit -m "feat(interviews): assignments follow the script's own node anchor"
```

---

### Task 4: The tag vocabularies

**Files:**
- Modify: `api/services/interview_script_model.py`
- Modify: `api/models.py:20-50` (`ProjectSettings`)
- Modify: `agents/discovery/interaction_designer.py`
- Create: `ui/src/components/tabs/MayaSetupTab.tsx`
- Modify: `ui/src/components/tabs/CrewSetupSections.tsx`
- Test: `tests/test_interview_tag_vocabularies.py` (create)

**Interfaces:**
- Consumes: `validate_scripts` from Task 2, whose signature this task widens to
  `validate_scripts(scripts: dict, disciplines: tuple[str, ...] = DEFAULT_DISCIPLINES) -> list[str]`.
- Produces: `DEFAULT_DISCIPLINES: tuple[str, ...]`; `QUESTION_INTENTS: frozenset[str]`; `ELICITATIONS: frozenset[str]`; `resolve_tags(script: dict, section: dict, question: dict) -> dict` returning `{"discipline": str, "question_intent": str, "elicitation": str}`. Task 5 consumes `ELICITATIONS`; Task 7 consumes `resolve_tags`.

**Why:** the scripts contain 178 distinct section titles and maturity dimensions scoped to one node, so grouping "within a discipline" means clustering prose. A closed vocabulary makes Casey's vertical axis an exact-value query, and makes an off-vocabulary value fail at write the way an unknown value chain ID already does.

Tags are authored on the section and inherited by its questions, overridable per question - the section already carries a theme, so authoring per question would be repetitive without being more expressive.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_interview_tag_vocabularies.py`:

```python
# tests/test_interview_tag_vocabularies.py
"""Closed vocabularies, so grouping is a query.

The scripts held 178 distinct section titles and maturity dimensions scoped to a single node
- "Decision Clarity - Strategic Planning & Standards" - so a vertical theme could only be
found by clustering prose.
"""
import pytest

from api.services.interview_script_model import (
    DEFAULT_DISCIPLINES,
    ELICITATIONS,
    QUESTION_INTENTS,
    resolve_tags,
    validate_scripts,
)


def _script(sections) -> dict:
    return {"SC-001": {
        "script_id": "SC-001", "node_id": "1.2", "level": "L2",
        "relationship": "internal", "node_label": "x", "sections": sections,
    }}


def _section(**over) -> dict:
    base = {
        "section_id": "S1", "title": "Governance", "discipline": "governance",
        "question_intent": "evidence", "elicitation": "unprompted",
        "questions": [{"id": "Q1", "text": "..."}],
    }
    base.update(over)
    return base


def test_the_vocabularies_are_closed_and_named():
    assert QUESTION_INTENTS == frozenset(
        {"context", "evidence", "maturity", "challenge", "opportunity"})
    assert ELICITATIONS == frozenset({"unprompted", "prompted"})
    assert "governance" in DEFAULT_DISCIPLINES and "data" in DEFAULT_DISCIPLINES
    assert len(DEFAULT_DISCIPLINES) == 9


def test_a_well_tagged_script_raises_nothing():
    assert validate_scripts(_script([_section()])) == []


def test_a_discipline_off_the_vocabulary_is_refused():
    problems = validate_scripts(_script([_section(discipline="synergy")]),
                                disciplines=DEFAULT_DISCIPLINES)
    assert any("synergy" in p for p in problems)


def test_a_project_may_configure_its_own_disciplines():
    """The list is per project. A discipline valid for one engagement is not for another,
    and hard-coding one vocabulary would make the tag wrong rather than closed."""
    scripts = _script([_section(discipline="hydrology")])
    assert validate_scripts(scripts, disciplines=("hydrology", "governance")) == []


@pytest.mark.parametrize("field,bad", [
    ("question_intent", "probing"),
    ("elicitation", "aided"),
])
def test_an_unknown_intent_or_elicitation_is_refused(field, bad):
    problems = validate_scripts(_script([_section(**{field: bad})]))
    assert any(bad in p for p in problems)


def test_a_question_inherits_its_sections_tags():
    section = _section()
    tags = resolve_tags(section=section, question=section["questions"][0])
    assert tags == {"discipline": "governance", "question_intent": "evidence",
                    "elicitation": "unprompted"}


def test_a_question_may_override_its_sections_discipline():
    section = _section(questions=[{"id": "Q1", "text": "...", "discipline": "data"}])
    tags = resolve_tags(section=section, question=section["questions"][0])
    assert tags["discipline"] == "data"
    # Only what it overrode. Inheriting all three from the section unless every one is
    # restated would make a single override silently blank the other two.
    assert tags["question_intent"] == "evidence"
    assert tags["elicitation"] == "unprompted"


def test_a_section_with_no_discipline_is_refused():
    section = _section()
    del section["discipline"]
    assert any("discipline" in p for p in validate_scripts(_script([section])))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_interview_tag_vocabularies.py -q`
Expected: FAIL with `ImportError: cannot import name 'DEFAULT_DISCIPLINES'`

- [ ] **Step 3: Add the vocabularies**

In `api/services/interview_script_model.py`, add:

```python
QUESTION_INTENTS = frozenset({"context", "evidence", "maturity", "challenge", "opportunity"})

# Whether the question named the thing it asked about. A separate axis from intent, and what
# makes a count readable: "six stakeholders raised data quality" means something entirely
# different if five of them were handed the phrase.
ELICITATIONS = frozenset({"unprompted", "prompted"})

# The starting vertical axis. Per project, because a discipline that matters in one
# engagement does not in another - hard-coding one list would make the tag wrong rather
# than closed.
DEFAULT_DISCIPLINES = (
    "governance", "data", "technology", "process", "people",
    "commercial", "assurance", "finance", "sustainability",
)

_TAG_FIELDS = ("discipline", "question_intent", "elicitation")


def resolve_tags(section: dict, question: dict) -> dict:
    """A question's three tags, inherited from its section unless it overrides one.

    Each field falls back independently. Inheriting all three only when the question
    restates none of them would let a single override silently blank the other two.
    """
    return {field: question.get(field, section.get(field)) for field in _TAG_FIELDS}
```

Change `validate_scripts`'s signature to `validate_scripts(scripts: dict, disciplines: tuple[str, ...] = DEFAULT_DISCIPLINES) -> list[str]` and add inside the section loop, after the `section_id` checks:

```python
            allowed = {
                "discipline": set(disciplines),
                "question_intent": QUESTION_INTENTS,
                "elicitation": ELICITATIONS,
            }
            for question in section.get("questions", []):
                tags = resolve_tags(section, question)
                for field, values in allowed.items():
                    if tags[field] not in values:
                        problems.append(
                            f"script {label} section {section_id} has {field} "
                            f"{tags[field]!r}, which is not one of {sorted(values)}"
                        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_interview_tag_vocabularies.py -q`
Expected: PASS, 9 tests.

- [ ] **Step 5: Make the vocabulary configurable**

In `api/models.py`, add to `ProjectSettings` after `applicable_regulations`:

```python
    # The vertical axis Casey groups maturity themes by. Closed so that grouping is an
    # exact-value query rather than prose clustering, and per project because a discipline
    # that matters in one engagement does not in another.
    disciplines: list[str] = list(DEFAULT_DISCIPLINES)
```

with `from api.services.interview_script_model import DEFAULT_DISCIPLINES` at the top of the file.

In `agents/tools/sqlite_state.py`, make `_validate_interview_scripts` pass the project's list:

```python
def _validate_interview_scripts(parsed: dict, slug: str) -> list[str]:
    from api.config import load_project_config
    from api.services.interview_script_model import (
        DEFAULT_DISCIPLINES,
        validate_scripts,
        validate_scripts_against_registry,
    )

    settings = get_settings()
    try:
        config = load_project_config(Path(settings.projects_dir) / slug)
        disciplines = tuple(config.get("disciplines") or DEFAULT_DISCIPLINES)
    except Exception:
        # A missing or unreadable config is not a reason to refuse a write - that would
        # block every script on a sidecar file.
        disciplines = DEFAULT_DISCIPLINES

    problems = validate_scripts(parsed, disciplines=disciplines)
    problems.extend(validate_scripts_against_registry(parsed, _current_registry(slug)))
    return problems
```

- [ ] **Step 6: Instruct Maya to tag**

In `agents/discovery/interaction_designer.py`, extend the block added in Task 2 Step 6 with:

```python
            "   - every section carries three tags, which its questions inherit and may "
            "override individually:\n"
            "     discipline: one of the project's configured disciplines - governance, "
            "data, technology, process, people, commercial, assurance, finance, "
            "sustainability by default. This is the axis maturity themes are grouped by, so "
            "a section tagged loosely is a theme that cannot be found.\n"
            "     question_intent: context, evidence, maturity, challenge, or opportunity. "
            "Scene-setting questions are context and are kept out of the evidence base.\n"
            "     elicitation: unprompted or prompted - see the ordering rule below.\n"
```

- [ ] **Step 7: Add Maya's Setup section**

Create `ui/src/components/tabs/MayaSetupTab.tsx`:

```typescript
// ui/src/components/tabs/MayaSetupTab.tsx
// The vertical axis Casey groups maturity themes by, edited where it is designed.
//
// Closed on purpose: a discipline off this list fails at write, the way an unknown value
// chain id already does, because an open field would put the project back to clustering 178
// distinct section titles.
import { useEffect, useState } from 'react'
import { Plus, X } from 'lucide-react'

import { projectsApi } from '../../api/endpoints'

export default function MayaSetupTab({ slug }: { slug: string }) {
  const [disciplines, setDisciplines] = useState<string[]>([])
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    projectsApi.getSettings(slug).then(s => setDisciplines(s.disciplines ?? []))
  }, [slug])

  const commit = async (next: string[]) => {
    setDisciplines(next)
    setSaving(true)
    try {
      await projectsApi.patchSettings(slug, { disciplines: next })
    } finally {
      setSaving(false)
    }
  }

  const add = () => {
    const value = draft.trim().toLowerCase()
    // Silently dropping a duplicate would read as the add having failed.
    if (!value || disciplines.includes(value)) return
    setDraft('')
    void commit([...disciplines, value])
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-secondary">
        The disciplines interview sections are tagged with. Casey groups vertical themes by
        these, so a discipline missing here is a theme that cannot be found.
      </p>
      <ul className="space-y-1" data-testid="discipline-list">
        {disciplines.map(d => (
          <li key={d} className="flex items-center justify-between rounded bg-surface-card px-3 py-2">
            <span className="text-sm text-primary">{d}</span>
            <button
              type="button"
              aria-label={`Remove ${d}`}
              className="text-muted hover:text-primary"
              onClick={() => void commit(disciplines.filter(x => x !== d))}
            >
              <X className="h-4 w-4" />
            </button>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <input
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') add() }}
          placeholder="Add a discipline"
          className="flex-1 rounded bg-surface-raised px-3 py-2 text-sm text-primary"
        />
        <button
          type="button"
          onClick={add}
          disabled={saving}
          className="flex items-center gap-1 rounded bg-brand px-3 py-2 text-sm text-white disabled:opacity-50"
        >
          <Plus className="h-4 w-4" /> Add
        </button>
      </div>
    </div>
  )
}
```

If `projectsApi.getSettings` and `projectsApi.patchSettings` do not exist in `ui/src/api/endpoints.ts`, add them against `GET /projects/{slug}/settings` and `PATCH /projects/{slug}/settings`, following the shape of the calls already in that file.

Register it in `ui/src/components/tabs/CrewSetupSections.tsx`:

```typescript
export const AGENT_SETUP_SECTION: Record<string, SetupSectionFC> = {
  'Interaction Designer':   MayaSetupTab,
  'Interview Coordinator':  TaylorSetupTab,
  'Stakeholder Interviewer': AverySetupTab,
}
```

- [ ] **Step 8: Run both suites and commit**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS, 934 passed, 2 skipped.

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS.

```bash
git add api/services/interview_script_model.py api/models.py agents/tools/sqlite_state.py \
  agents/discovery/interaction_designer.py ui/src/components/tabs/MayaSetupTab.tsx \
  ui/src/components/tabs/CrewSetupSections.tsx tests/test_interview_tag_vocabularies.py
git commit -m "feat(interviews): closed discipline, intent, and elicitation vocabularies"
```

---

### Task 5: Morgan's levers reach Maya, unaided first

**Files:**
- Modify: `agents/discovery/interaction_designer.py`
- Modify: `agents/discovery/value_lever_analyst.py`
- Modify: `api/services/interview_script_model.py`
- Test: `tests/test_lever_elicitation.py` (create)

**Interfaces:**
- Consumes: `ELICITATIONS` and `validate_scripts` from Task 4.
- Produces: `validate_elicitation_order(scripts: dict) -> list[str]`; `validate_levers_unnamed_in_unaided_sections(scripts: dict, levers: list[dict]) -> list[str]`; `lever_status(lever: dict, answers: list[dict]) -> str` returning one of `contradicted`, `confirmed_unprompted`, `confirmed_prompted`, `untested`.

**Why:** Maya reads only the registry and the summary today, so Morgan's levers are never tested by anything - they flow to value design unverified, which is what framing them as hypotheses was meant to prevent. But naming a lever early buys agreement rather than evidence, most sharply from the junior and frontline voices that most need to be heard cleanly. Sequencing is the fix; omission is not.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lever_elicitation.py`:

```python
# tests/test_lever_elicitation.py
"""Unaided before prompted, and never the other way round.

Morgan reads the annual report and produces levers as hypotheses. Maya must reference them -
an untested hypothesis reaches value design looking established - and must not reference them
first, because naming a lever buys agreement rather than evidence.
"""
import pytest

from api.services.interview_script_model import (
    lever_status,
    validate_elicitation_order,
    validate_levers_unnamed_in_unaided_sections,
)


def _script(*elicitations, questions=None) -> dict:
    return {"SC-001": {
        "script_id": "SC-001", "node_id": "1.2", "level": "L2", "relationship": "internal",
        "node_label": "x",
        "sections": [
            {
                "section_id": f"S{i}", "title": f"Section {i}", "discipline": "data",
                "question_intent": "evidence", "elicitation": e,
                "questions": questions[i - 1] if questions else [{"id": "Q1", "text": "..."}],
            }
            for i, e in enumerate(elicitations, 1)
        ],
    }}


def test_unaided_then_prompted_is_accepted():
    assert validate_elicitation_order(_script("unprompted", "unprompted", "prompted")) == []


def test_prompted_before_unaided_is_refused():
    """The whole rule, and it is checkable - so it is checked rather than left to an
    instruction Maya may or may not follow."""
    problems = validate_elicitation_order(_script("prompted", "unprompted"))
    assert len(problems) == 1
    assert "S2" in problems[0] or "S1" in problems[0]


def test_an_all_unaided_script_is_accepted():
    # A frontline script may legitimately never prompt. Requiring a prompted section would
    # force one in where it does not belong.
    assert validate_elicitation_order(_script("unprompted", "unprompted")) == []


def test_naming_a_lever_in_an_unaided_section_is_refused():
    """The anchoring this design forbids, in its most direct form: the unaided section is
    unaided in name only if it contains the lever's own words."""
    levers = [{"lever": "Fleet availability", "hypothesis": "..."}]
    scripts = _script("unprompted", questions=[
        [{"id": "Q1", "text": "How well is fleet availability managed here?"}]])
    problems = validate_levers_unnamed_in_unaided_sections(scripts, levers)
    assert any("Fleet availability" in p for p in problems)


def test_naming_a_lever_in_a_prompted_section_is_the_point():
    levers = [{"lever": "Fleet availability", "hypothesis": "..."}]
    scripts = _script("prompted", questions=[
        [{"id": "Q1", "text": "Your annual report names fleet availability - does that match?"}]])
    assert validate_levers_unnamed_in_unaided_sections(scripts, levers) == []


def test_no_levers_blocks_nothing():
    # Morgan may not have run. Refusing every script then would block the pipeline on an
    # upstream artefact that is allowed to be absent.
    assert validate_levers_unnamed_in_unaided_sections(_script("unprompted"), []) == []


LEVER = {"lever": "Fleet availability"}


def _answer(elicitation, supports, text="fleet availability matters"):
    return {"question_text": text, "answer_text": "yes" if supports else "no",
            "elicitation": elicitation, "supports": supports}


@pytest.mark.parametrize("answers,expected", [
    ([], "untested"),
    ([_answer("prompted", True)], "confirmed_prompted"),
    ([_answer("unprompted", True)], "confirmed_unprompted"),
    ([_answer("prompted", False)], "contradicted"),
])
def test_lever_status_is_derived_from_the_answers(answers, expected):
    assert lever_status(LEVER, answers) == expected


def test_an_unprompted_mention_outweighs_a_prompted_agreement():
    """Order-independent. A status that depended on which answer was written last would make
    the strength of the evidence an accident of interview scheduling."""
    a = _answer("prompted", True)
    b = _answer("unprompted", True)
    assert lever_status(LEVER, [a, b]) == "confirmed_unprompted"
    assert lever_status(LEVER, [b, a]) == "confirmed_unprompted"


def test_a_contradiction_outranks_any_confirmation():
    # The finding a reader most needs. Reporting "confirmed" for a lever some interviewee
    # disputed is the failure this status exists to prevent.
    answers = [_answer("unprompted", True), _answer("prompted", False)]
    assert lever_status(LEVER, answers) == "contradicted"


def test_untested_is_reported_rather_than_assumed_absent():
    """The failure nothing can currently see: a lever that reached value design without a
    single interview touching it, looking exactly like an established finding."""
    assert lever_status({"lever": "Carbon reduction"}, [_answer("unprompted", True)]) == "untested"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_lever_elicitation.py -q`
Expected: FAIL with `ImportError: cannot import name 'lever_status'`

- [ ] **Step 3: Implement the rule and the status**

Add to `api/services/interview_script_model.py`:

```python
def validate_elicitation_order(scripts: dict) -> list[str]:
    """Unaided sections precede prompted ones, in every script.

    A script may be entirely unaided - a frontline instrument legitimately never prompts -
    but once it has prompted, an unaided section afterwards is unaided in name only: the
    interviewee has already been given the framing.
    """
    problems: list[str] = []
    for key, script in scripts.items():
        label = script.get("script_id") or key
        prompted_at: str | None = None
        for section in script.get("sections", []):
            elicitation = section.get("elicitation")
            if elicitation == "prompted":
                prompted_at = prompted_at or section.get("section_id")
            elif elicitation == "unprompted" and prompted_at is not None:
                problems.append(
                    f"script {label} asks unaided section {section.get('section_id')} after "
                    f"prompted section {prompted_at} - once a lever has been named the "
                    "interviewee cannot un-hear it, so unaided sections come first"
                )
                break
    return problems


def validate_levers_unnamed_in_unaided_sections(scripts: dict, levers: list[dict]) -> list[str]:
    """No unaided question contains a lever's own words.

    The ordering rule alone is not enough: a section tagged unprompted that quotes the annual
    report's phrasing is prompted in everything but the tag.
    """
    names = [str(lever.get("lever", "")).strip() for lever in levers]
    names = [n for n in names if n]
    if not names:
        return []

    problems: list[str] = []
    for key, script in scripts.items():
        label = script.get("script_id") or key
        for section in script.get("sections", []):
            if section.get("elicitation") != "unprompted":
                continue
            for question in section.get("questions", []):
                text = str(question.get("text", "")).lower()
                for name in names:
                    if name.lower() in text:
                        problems.append(
                            f"script {label} names the value lever {name!r} in unaided "
                            f"question {question.get('id')} of section "
                            f"{section.get('section_id')} - move it to a prompted section, "
                            "or the answer confirms the lever rather than testing it"
                        )
    return problems


def lever_status(lever: dict, answers: list[dict]) -> str:
    """What the interviews did to this hypothesis.

    Order-independent by construction: a status derived from whichever answer came last
    would make the strength of the evidence an accident of interview scheduling.
    Contradiction outranks every confirmation, because reporting "confirmed" for a lever an
    interviewee disputed is the failure this exists to prevent.
    """
    name = str(lever.get("lever", "")).strip().lower()
    if not name:
        return "untested"

    touching = [
        a for a in answers
        if name in f"{a.get('question_text', '')} {a.get('answer_text', '')}".lower()
    ]
    if not touching:
        return "untested"
    if any(not a.get("supports") for a in touching):
        return "contradicted"
    if any(a.get("elicitation") == "unprompted" for a in touching):
        return "confirmed_unprompted"
    return "confirmed_prompted"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_lever_elicitation.py -q`
Expected: PASS, 13 tests.

- [ ] **Step 5: Enforce both on Maya's write path**

In `agents/tools/sqlite_state.py`, extend `_validate_interview_scripts`:

```python
    from api.services.interview_script_model import (
        validate_elicitation_order,
        validate_levers_unnamed_in_unaided_sections,
    )

    problems.extend(validate_elicitation_order(parsed))
    problems.extend(validate_levers_unnamed_in_unaided_sections(parsed, _current_levers(slug)))
```

and add the loader beside `_current_registry`:

```python
def _current_levers(slug: str) -> list[dict]:
    """Morgan's levers, or none when she has not run.

    Absence is not a failure: Maya may legitimately design before the levers exist, and
    refusing her write then would block the pipeline on an upstream artefact.
    """
    settings = get_settings()
    path = latest_output_path(
        Path(settings.projects_dir) / slug / "outputs" / "value_levers.json"
    )
    if path is None:
        return []
    try:
        loaded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return loaded if isinstance(loaded, list) else []
```

- [ ] **Step 6: Give Maya the levers and the rule**

In `agents/discovery/interaction_designer.py`, add as a new first step of the task:

```python
            "1. Use SQLiteStateTool with operation='read', key='value_levers', "
            "agent_name='interaction_designer' to retrieve the value levers and KPIs the "
            "organisation itself uses. These are HYPOTHESES read from the client's own "
            "documents, not findings. Your instruments exist to test them.\n"
            "   Order every script so that unaided sections come first and prompted sections "
            "come last, and never the other way round:\n"
            "   - unaided sections (elicitation: 'unprompted') ask what gets in the way, what "
            "you would change, and what happens when it goes wrong. Do NOT name any value "
            "lever, KPI, or phrase from the client's documents in these questions - a lever "
            "nobody wrote down can only surface here, and naming one buys agreement rather "
            "than evidence.\n"
            "   - a late section (elicitation: 'prompted') names the levers directly: "
            "\"Your annual report names <lever> as a priority. Does that match what you see? "
            "Which is real and which is aspirational?\" An interviewee must be able to "
            "contradict the annual report - that is the outcome that makes this worth "
            "asking.\n"
            "   Ask interviewees for the challenge, its frequency, the workaround, and the "
            "consequence. Do not ask them to size the value: a depot manager knows the van "
            "has been off the road for nine days and does not know what that costs the "
            "business.\n"
```

Renumber the existing steps accordingly.

- [ ] **Step 7: Give Morgan's levers a status field**

In `agents/discovery/value_lever_analyst.py`, extend the lever schema in the task description with `"status": "untested"` and add:

```python
            "   `status` is always \"untested\" when you write it. The interviews decide it "
            "later: contradicted, confirmed_unprompted, confirmed_prompted, or untested. "
            "Never write a status claiming evidence you do not have.\n"
```

- [ ] **Step 8: Run both suites and commit**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS, 947 passed, 2 skipped.

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS.

```bash
git add api/services/interview_script_model.py agents/tools/sqlite_state.py \
  agents/discovery/interaction_designer.py agents/discovery/value_lever_analyst.py \
  tests/test_lever_elicitation.py
git commit -m "feat(interviews): unaided sections precede prompted ones, and levers gain a status"
```

---

### Task 6: The session records which question an answer belongs to

**Files:**
- Modify: `ui/src/pages/VoiceInterview.tsx:37,482-534`
- Modify: `api/routers/interviews.py:284-286`
- Test: `ui/src/__tests__/VoiceInterviewCapture.test.tsx` (create)

**Interfaces:**
- Consumes: `question_id` semantics from Task 2.
- Produces: the `qa_pairs` element shape `{question_id: string, question: string, answer: string, follow_up: 0 | 1}`, which Task 7 consumes.

**Why:** `qaRef` is `{question: string, answer: string}[]` - the question text and nothing else - so an answer cannot be traced to its question even within its own script. The array also mixes scripted questions, generated probes, pre-scripted branches, and section-level prompts without distinguishing them.

A follow-up carries its parent's ID and tags: a probe is further evidence about one question, not a new one. Counting probes as questions would overstate coverage and a theme's weight - an interviewee pressed three times on one point would read as three stakeholders' worth of agreement.

- [ ] **Step 1: Write the failing test**

Create `ui/src/__tests__/VoiceInterviewCapture.test.tsx` testing the pure ID helper rather than driving the whole voice flow:

```typescript
// ui/src/__tests__/VoiceInterviewCapture.test.tsx
// An answer that cannot name its question cannot be cited, grouped, or counted. qa_pairs
// carried question text alone, and mixed scripted questions with generated probes.
import { describe, it, expect } from 'vitest'
import { capturedPair } from '../pages/VoiceInterview'

describe('capturedPair', () => {
  it('gives a scripted question its own id', () => {
    expect(capturedPair('SC-014', 'S3', 2, 'Q?', 'A.')).toEqual({
      question_id: 'SC-014.S3.Q2', question: 'Q?', answer: 'A.', follow_up: 0,
    })
  })

  it('gives a generated probe its parent id with a suffix', () => {
    // A probe is more evidence about one question, not a new one. Its own id would make an
    // interviewee pressed three times read as three questions covered.
    expect(capturedPair('SC-014', 'S3', 2, 'Say more?', 'B.', { followUp: 'F', index: 1 }))
      .toEqual({
        question_id: 'SC-014.S3.Q2.F1', question: 'Say more?', answer: 'B.', follow_up: 1,
      })
  })

  it('gives a pre-scripted branch its parent id with a different suffix', () => {
    expect(capturedPair('SC-014', 'S3', 2, 'And?', 'C.', { followUp: 'B', index: 2 }))
      .toEqual({
        question_id: 'SC-014.S3.Q2.B2', question: 'And?', answer: 'C.', follow_up: 1,
      })
  })

  it('gives a section-level prompt the section id', () => {
    // The synthesis check, peer referral, and forward roadmap belong to the section rather
    // than to any one question.
    expect(capturedPair('SC-014', 'S3', null, 'Anything missed?', 'D.')).toEqual({
      question_id: 'SC-014.S3', question: 'Anything missed?', answer: 'D.', follow_up: 0,
    })
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/VoiceInterviewCapture.test.tsx`
Expected: FAIL - `capturedPair` is not exported.

- [ ] **Step 3: Add the helper and use it**

In `ui/src/pages/VoiceInterview.tsx`, add above the component:

```typescript
export interface CapturedPair {
  question_id: string
  question: string
  answer: string
  follow_up: 0 | 1
}

/**
 * One captured answer, addressed to the question that produced it.
 *
 * A follow-up carries its parent's id with a suffix rather than an id of its own: it is
 * further evidence about one question, and counting probes as questions would overstate both
 * coverage and the weight of any theme drawn from them.
 */
export function capturedPair(
  scriptId: string,
  sectionId: string,
  questionNo: number | null,
  question: string,
  answer: string,
  followUp?: { followUp: 'F' | 'B'; index: number },
): CapturedPair {
  const base = questionNo === null
    ? `${scriptId}.${sectionId}`
    : `${scriptId}.${sectionId}.Q${questionNo}`
  return {
    question_id: followUp ? `${base}.${followUp.followUp}${followUp.index}` : base,
    question,
    answer,
    follow_up: followUp ? 1 : 0,
  }
}
```

Change `qaRef` to `useRef<CapturedPair[]>([])` and replace each `qaRef.current.push({ question, answer })` with the matching `capturedPair(...)` call - the primary question at `capturedPair(scriptId, section.section_id, questionNo, question.text, answer)`, generated probes with `{followUp: 'F', index: followUpCount + 1}`, pre-scripted branches with `{followUp: 'B', index: followUpCount + 1}`, and the synthesis, referral, roadmap, and portfolio prompts with `questionNo` of `null`.

- [ ] **Step 4: Accept the richer shape on the API**

In `api/routers/interviews.py`, replace `CompleteRequest`:

```python
class CapturedPair(BaseModel):
    question_id: str
    question: str
    answer: str = ""
    follow_up: int = 0


class CompleteRequest(BaseModel):
    # Typed rather than list[dict]: an untyped payload accepted a pair with no question_id
    # silently, and the answer then had no question to be traced to.
    qa_pairs: list[CapturedPair]
    ratings: list[dict] | None = None
```

and pass `[p.model_dump() for p in body.qa_pairs]` to `complete_session`.

- [ ] **Step 5: Run both suites and commit**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, 350 tests.

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS, 947 passed, 2 skipped.

```bash
git add ui/src/pages/VoiceInterview.tsx ui/src/__tests__/VoiceInterviewCapture.test.tsx \
  api/routers/interviews.py
git commit -m "feat(interviews): captured answers name the question that produced them"
```

---

### Task 7: The answer store

**Files:**
- Modify: `api/database.py`
- Create: `api/services/interview_answer_service.py`
- Modify: `api/services/interview_service.py:226-241`
- Test: `tests/test_interview_answers.py` (create)

**Interfaces:**
- Consumes: `resolve_tags` (Task 4), the `CapturedPair` shape (Task 6), `node_template_assignments.script_id` (Task 3).
- Produces: `record_answers(conn, slug: str, session_id: int, qa_pairs: list[dict], script: dict) -> int` in `api/services/interview_answer_service.py`; `insert_interview_answer(conn, **fields) -> int` and `fetch_interview_answers(conn, **filters) -> list[dict]` in `api/database.py`.

**Why:** the answer store is the system of record for Casey's grouping. Tags are denormalised onto the row because every one is a fact fixed at the moment the answer was given - a later rename of a node must not retrospectively change what an interview was about.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_interview_answers.py`:

```python
# tests/test_interview_answers.py
"""One row per question per session, tagged at the moment it was answered."""
import pytest

from api.database import fetch_interview_answers, get_connection
from api.services.interview_answer_service import record_answers

SLUG = "answers-test"
PROJECT = {
    "client_slug": SLUG, "llm_mode": "standard", "sector": "utilities",
    "stakeholder_groups": [], "value_stream_labels": [], "crews_enabled": ["requirements"],
    "review_gates": True, "slack_channel": "",
}
SCRIPT = {
    "script_id": "SC-014", "node_id": "1.2", "level": "L2", "relationship": "internal",
    "node_label": "Planned Maintenance", "sections": [{
        "section_id": "S3", "title": "Data", "discipline": "data",
        "question_intent": "evidence", "elicitation": "unprompted",
        "questions": [{"id": "Q1", "text": "Is the record trusted?"},
                      {"id": "Q2", "text": "For investment?", "discipline": "governance"}],
    }],
}
PAIRS = [
    {"question_id": "SC-014.S3.Q1", "question": "Is the record trusted?",
     "answer": "For compliance, yes.", "follow_up": 0},
    {"question_id": "SC-014.S3.Q1.F1", "question": "Say more?",
     "answer": "Not for planning.", "follow_up": 1},
    {"question_id": "SC-014.S3.Q2", "question": "For investment?",
     "answer": "", "follow_up": 0},
]


@pytest.mark.asyncio
async def test_every_pair_becomes_a_row(client, seeded_session):
    async with get_connection(SLUG) as conn:
        written = await record_answers(conn, SLUG, seeded_session, PAIRS, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    assert written == 3
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_the_tags_come_from_the_script_not_from_the_answer(client, seeded_session):
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    by_qid = {r["question_id"]: r for r in rows}
    assert by_qid["SC-014.S3.Q1"]["discipline"] == "data"
    assert by_qid["SC-014.S3.Q1"]["node_id"] == "1.2"
    assert by_qid["SC-014.S3.Q1"]["relationship"] == "internal"


@pytest.mark.asyncio
async def test_a_question_override_wins_over_its_section(client, seeded_session):
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    q2 = next(r for r in rows if r["question_id"] == "SC-014.S3.Q2")
    assert q2["discipline"] == "governance"


@pytest.mark.asyncio
async def test_a_follow_up_carries_its_parents_tags_and_is_flagged(client, seeded_session):
    """A probe is more evidence about one question. Its own tags would let a generated
    follow-up land in a discipline nobody chose."""
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    probe = next(r for r in rows if r["question_id"] == "SC-014.S3.Q1.F1")
    assert probe["follow_up"] == 1
    assert probe["discipline"] == "data"


@pytest.mark.asyncio
async def test_a_probe_does_not_count_as_a_question_covered(client, seeded_session):
    """One question and one probe is one question covered, not two - otherwise pressing an
    interviewee inflates coverage."""
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    assert len([r for r in rows if not r["follow_up"]]) == 2


@pytest.mark.asyncio
async def test_an_unanswered_question_is_recorded_as_asked(client, seeded_session):
    """An absent row means "not asked" and a blank one means "asked and not answered".
    Coverage cannot tell an instrument that missed a topic from a stakeholder who declined
    it unless both are recorded."""
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    blank = next(r for r in rows if r["question_id"] == "SC-014.S3.Q2")
    assert blank["answered"] == 0
    assert blank["answer_text"] == ""


@pytest.mark.asyncio
async def test_an_entity_anchored_script_has_no_chain(client, seeded_session):
    """A query for everything about Fleet that swept in entity-level answers would attribute
    a board member's remark to a chain they never mentioned."""
    entity_script = {**SCRIPT, "node_id": "0", "level": "A", "relationship": "regulator"}
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS[:1], script=entity_script)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    assert rows[0]["chain"] is None
    assert rows[0]["relationship"] == "regulator"


@pytest.mark.asyncio
async def test_a_chain_anchored_script_records_its_chain(client, seeded_session):
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS[:1], script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    assert rows[0]["chain"] == "1"
```

Add this fixture at the top of the same file, below the constants:

```python
@pytest.fixture
async def seeded_session(client):
    """A project, a stakeholder, and one session - the minimum an answer row references."""
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await conn.execute_fetchall("SELECT id FROM projects LIMIT 1")
        project_id = project[0][0]
        cur = await conn.execute(
            "INSERT INTO stakeholders (project_id, name, email, role) VALUES (?,?,?,?)",
            (project_id, "Sam Example", "sam@example.com", "Manager"),
        )
        stakeholder_id = cur.lastrowid
        cur = await conn.execute(
            "INSERT INTO interview_sessions (project_id, stakeholder_id, node_label, "
            "session_token, status) VALUES (?,?,?,?,?)",
            (project_id, stakeholder_id, "Planned Maintenance", "tok-answers-test", "completed"),
        )
        await conn.commit()
        return cur.lastrowid
```

If `stakeholders` in this project's schema has different required columns, adjust the insert to match `api/database.py` - the fixture only needs a row the session can reference.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_interview_answers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.interview_answer_service'`

- [ ] **Step 3: Add the table**

In `api/database.py`, add a migration function and register it with the others that run on connection open:

```python
async def _migrate_interview_answers(conn: aiosqlite.Connection) -> None:
    """One row per question per session - the system of record for interview evidence.

    Tags are denormalised deliberately. Casey groups by an exact value without a four-way
    join, and every tag is a fact fixed at the moment the answer was given: a later rename of
    a node must not retrospectively change what an interview was about.

    Rows are append-only, which is what makes `id` usable as a citation token.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS interview_answers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL REFERENCES interview_sessions(id),
            stakeholder_id  INTEGER NOT NULL REFERENCES stakeholders(id),
            script_id       TEXT    NOT NULL,
            section_id      TEXT    NOT NULL,
            question_id     TEXT    NOT NULL,
            question_text   TEXT    NOT NULL,
            answer_text     TEXT    NOT NULL DEFAULT '',
            answered        INTEGER NOT NULL DEFAULT 1,
            follow_up       INTEGER NOT NULL DEFAULT 0,
            node_id         TEXT    NOT NULL,
            chain           TEXT,
            level           TEXT    NOT NULL,
            relationship    TEXT    NOT NULL,
            party_id        TEXT,
            discipline      TEXT    NOT NULL,
            question_intent TEXT    NOT NULL,
            elicitation     TEXT    NOT NULL,
            rating          INTEGER,
            answered_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_answers_session ON interview_answers(session_id)")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_answers_node ON interview_answers(node_id)")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_answers_discipline ON interview_answers(discipline)")
    await conn.commit()
```

and beside it the three helpers the service and the tests use:

```python
_ANSWER_COLUMNS = (
    "session_id", "stakeholder_id", "script_id", "section_id", "question_id",
    "question_text", "answer_text", "answered", "follow_up", "node_id", "node_label",
    "chain", "level", "relationship", "party_id", "discipline", "question_intent",
    "elicitation", "rating",
)


async def insert_interview_answer(conn: aiosqlite.Connection, **fields) -> int:
    """One answer row. Returns its id, which is the citation token."""
    columns = [c for c in _ANSWER_COLUMNS if c in fields]
    placeholders = ", ".join("?" for _ in columns)
    cur = await conn.execute(
        f"INSERT INTO interview_answers ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(fields[c] for c in columns),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_interview_answers(
    conn: aiosqlite.Connection,
    session_id: int | None = None,
    node_id: str | None = None,
    discipline: str | None = None,
) -> list[dict]:
    """Answers matching whichever filters are given, oldest first."""
    clauses, params = [], []
    for column, value in (("session_id", session_id), ("node_id", node_id),
                          ("discipline", discipline)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    async with conn.execute(
        f"SELECT * FROM interview_answers{where} ORDER BY id", tuple(params)
    ) as cur:
        return [dict(row) async for row in cur]


async def fetch_interview_session_by_id(
    conn: aiosqlite.Connection, session_id: int
) -> dict | None:
    """One session by primary key. The existing lookups are all by session_token, which the
    answer service does not hold - it is called after completion, with the row's id."""
    async with conn.execute(
        "SELECT * FROM interview_sessions WHERE id = ?", (session_id,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None
```

Add `node_label TEXT NOT NULL DEFAULT ''` to the `CREATE TABLE` above, between `node_id` and `chain`. It is a fact fixed at answer time like every other tag on the row, and Task 8 embeds it so a semantic hit names the node in words rather than as a number.

- [ ] **Step 4: Write the service**

Create `api/services/interview_answer_service.py`:

```python
# api/services/interview_answer_service.py
"""A completed session becomes tagged, addressable answers.

Written by the interview service rather than by an agent: what a person said in a session is
a fact of the session, not an opinion, and an agent that could rewrite it could rewrite the
evidence its own themes cite.
"""
from __future__ import annotations

from api.database import fetch_interview_session_by_id, insert_interview_answer
from api.services.interview_script_model import resolve_tags


def _parent_question_id(question_id: str) -> str:
    """A probe's parent. `SC-014.S3.Q2.F1` is more evidence about `SC-014.S3.Q2`."""
    parts = question_id.split(".")
    return ".".join(parts[:-1]) if parts[-1][:1] in ("F", "B") and parts[-1][1:].isdigit() else question_id


def _locate(script: dict, question_id: str) -> tuple[dict, dict]:
    """The section and question a captured pair belongs to.

    Falls back to an empty question rather than raising: a section-level prompt has no
    question of its own, and a generated probe resolves to its parent.
    """
    target = _parent_question_id(question_id)
    for index, section in enumerate(script.get("sections", []), 1):
        section_id = section.get("section_id")
        if not target.startswith(f"{script.get('script_id')}.{section_id}"):
            continue
        for question_no, question in enumerate(section.get("questions", []), 1):
            if target.endswith(f".Q{question_no}"):
                return section, question
        return section, {}
    return {}, {}


async def record_answers(
    conn, slug: str, session_id: int, qa_pairs: list[dict], script: dict
) -> int:
    """Write one row per captured pair. Returns the number written."""
    session = await fetch_interview_session_by_id(conn, session_id)
    node_id = script.get("node_id", "")
    # The chain is the root of the node id, and there is none for the entity: an interview
    # about the organisation is not about one chain.
    chain = node_id.split(".")[0] if node_id and node_id != "0" else None

    written = 0
    for pair in qa_pairs:
        section, question = _locate(script, pair["question_id"])
        tags = resolve_tags(section, question)
        answer_text = pair.get("answer", "") or ""
        await insert_interview_answer(
            conn,
            session_id=session_id,
            stakeholder_id=session["stakeholder_id"],
            script_id=script.get("script_id", ""),
            section_id=section.get("section_id", ""),
            question_id=pair["question_id"],
            question_text=pair.get("question", ""),
            answer_text=answer_text,
            answered=1 if answer_text.strip() else 0,
            follow_up=int(pair.get("follow_up", 0)),
            node_id=node_id,
            node_label=script.get("node_label", ""),
            chain=chain,
            level=script.get("level", ""),
            relationship=script.get("relationship", ""),
            party_id=session.get("party_id"),
            discipline=tags.get("discipline") or "",
            question_intent=tags.get("question_intent") or "",
            elicitation=tags.get("elicitation") or "",
            rating=None,
        )
        written += 1
    return written
```

- [ ] **Step 5: Call it on completion**

In `api/services/interview_service.py`, inside `complete_session`, after `complete_interview_session(...)`:

```python
        # The transcript blob stays for display; the rows are what anything queries.
        script = await _script_for_session(conn, session_token)
        if script:
            await record_answers(conn, slug, session["id"], qa_pairs, script=script)
```

and add the lookup to `api/services/interview_answer_service.py`:

```python
async def script_for_session(conn, slug: str, session: dict) -> dict | None:
    """The script this session was conducted from.

    By script_id through the node assignment, because that is the anchor Task 3 made
    authoritative. Sessions created before script ids existed fall back to node_label, which
    is what they were keyed on - and a session whose script has since been retired returns
    None rather than guessing, because tagging answers from the wrong script is worse than
    leaving them untagged.
    """
    path = latest_output_path(
        Path(get_settings().projects_dir) / slug / "outputs" / "interview_scripts.json"
    )
    if path is None:
        return None
    try:
        scripts = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    async with conn.execute(
        "SELECT script_id FROM node_template_assignments "
        "WHERE project_id = ? AND node_label = ?",
        (session["project_id"], session["node_label"]),
    ) as cur:
        row = await cur.fetchone()

    script_id = row["script_id"] if row else None
    if script_id and script_id in scripts:
        return scripts[script_id]
    for script in scripts.values():
        if script.get("node_label") == session["node_label"]:
            return script
    return None
```

with `import json`, `from pathlib import Path`, `from api.config import get_settings`, and `from api.database import latest_output_path` at the top. Then in `complete_session`:

```python
        session = await fetch_interview_session_by_token(conn, session_token)
        script = await script_for_session(conn, slug, session) if session else None
        if script:
            await record_answers(conn, slug, session["id"], qa_pairs, script=script)
```

A session with no resolvable script writes no answer rows and is logged at warning level. The
transcript blob is still saved either way, so nothing the interviewee said is lost, and the
rows can be backfilled once the script is found.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_interview_answers.py -q`
Expected: PASS, 8 tests.

- [ ] **Step 7: Run both suites and commit**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS, 955 passed, 2 skipped.

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS.

```bash
git add api/database.py api/services/interview_answer_service.py \
  api/services/interview_service.py tests/test_interview_answers.py
git commit -m "feat(interviews): completed sessions write tagged, addressable answers"
```

---

### Task 8: Answers are retrievable

**Files:**
- Modify: `api/services/interview_answer_service.py`
- Modify: `agents/tools/chroma_query.py:29-56`
- Test: `tests/test_interview_answer_retrieval.py` (create)

**Interfaces:**
- Consumes: `record_answers` from Task 7.
- Produces: `answer_document(row: dict) -> str` and `answer_metadata(row: dict) -> dict` in `api/services/interview_answer_service.py`; `collection='interviews'` on `ChromaQueryTool`.

**Why:** the interview corpus is large enough that Casey cannot read it whole. Exact grouping and coverage come from SQL; recall comes from Chroma. Neither does the other's job - counting how many stakeholders mentioned something is a fact, and a vector search is the wrong instrument for a fact.

The embedded text carries a context preamble so a semantic hit arrives with its own frame rather than as an orphan sentence.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_interview_answer_retrieval.py`:

```python
# tests/test_interview_answer_retrieval.py
"""What gets embedded, and what can be filtered before it ranks."""
from api.services.interview_answer_service import answer_document, answer_metadata

ROW = {
    "id": 812, "question_text": "Is the asset record trusted?",
    "answer_text": "For compliance, yes. For investment, no.",
    "node_id": "1.2", "chain": "1", "level": "L2", "relationship": "internal",
    "discipline": "data", "question_intent": "evidence", "elicitation": "unprompted",
    "script_id": "SC-014", "section_id": "S3", "question_id": "SC-014.S3.Q1",
    "stakeholder_id": 7, "follow_up": 0, "node_label": "Planned Maintenance",
}


def test_the_document_carries_its_own_frame():
    """A semantic hit arrives as a sentence with no context otherwise, and a reader cannot
    tell whose answer it was or what it was about."""
    doc = answer_document(ROW)
    assert "Planned Maintenance" in doc
    assert "1.2" in doc
    assert "data" in doc
    assert ROW["question_text"] in doc
    assert ROW["answer_text"] in doc


def test_the_metadata_carries_every_filterable_tag():
    """"Answers about data from customers of the Fleet chain" must be a filtered query rather
    than a hope about embedding similarity."""
    meta = answer_metadata(ROW)
    for field in ("node_id", "chain", "level", "relationship", "discipline",
                  "question_intent", "elicitation", "stakeholder_id", "answer_id"):
        assert field in meta, f"{field} missing - it cannot be filtered on"
    assert meta["answer_id"] == 812


def test_metadata_values_are_chroma_scalars():
    """Chroma rejects None and nested values. A row for an entity-anchored script has a null
    chain, which would fail the upsert for every such answer."""
    meta = answer_metadata({**ROW, "chain": None})
    assert all(isinstance(v, (str, int, float, bool)) for v in meta.values())
    assert meta["chain"] == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_interview_answer_retrieval.py -q`
Expected: FAIL with `ImportError: cannot import name 'answer_document'`

- [ ] **Step 3: Add the document and metadata shapes**

Add to `api/services/interview_answer_service.py`:

```python
_META_FIELDS = ("script_id", "section_id", "question_id", "node_id", "chain", "level",
                "relationship", "discipline", "question_intent", "elicitation",
                "stakeholder_id", "follow_up")


def answer_document(row: dict) -> str:
    """The text embedded for one answer, with a preamble so a hit carries its own frame."""
    node = row.get("node_label") or row.get("node_id")
    frame = (f"[{node} ({row.get('node_id')}) | {row.get('level')} | "
             f"{row.get('relationship')} | discipline: {row.get('discipline')}]")
    return f"{frame}\nQ: {row.get('question_text', '')}\nA: {row.get('answer_text', '')}"


def answer_metadata(row: dict) -> dict:
    """Filterable tags for one answer.

    Chroma accepts only scalars, and rejects None - an entity-anchored answer has a null
    chain, which would fail the upsert for every such row.
    """
    meta = {field: row.get(field) for field in _META_FIELDS}
    meta["answer_id"] = row.get("id")
    return {k: ("" if v is None else v) for k, v in meta.items()}
```

and the indexer:

```python
def index_answers(slug: str, rows: list[dict]) -> int:
    """Upsert one Chroma document per answer. Returns how many were indexed.

    Never raises. The SQLite rows are the system of record and can be re-indexed at any
    time, so a Chroma outage must cost the session nothing - failing here would lose an
    interview a person has already given.
    """
    if not rows:
        return 0
    try:
        collection = get_chroma_client().get_or_create_collection(name=f"{slug}_interviews")
        collection.upsert(
            documents=[answer_document(r) for r in rows],
            ids=[str(r["id"]) for r in rows],
            metadatas=[answer_metadata(r) for r in rows],
        )
        return len(rows)
    except Exception:
        _log.exception("index_answers[%s]: %d answers not indexed", slug, len(rows))
        return 0
```

with `import logging`, `_log = logging.getLogger(__name__)`, and
`from api.services.chroma_client import get_chroma_client` at the top.

Change `record_answers` to collect the ids it wrote and index them before returning:

```python
    written_ids.append(await insert_interview_answer(conn, ...))
    ...
    indexed = await fetch_interview_answers(conn, session_id=session_id)
    index_answers(slug, [r for r in indexed if r["id"] in set(written_ids)])
    return len(written_ids)
```

`record_answers` already takes `slug` as its second parameter from Task 7, so no call site
changes are needed here.

- [ ] **Step 4: Expose the collection to agents**

In `agents/tools/chroma_query.py`, replace the collection mapping:

```python
        collection_name = {
            "project": f"{self.slug}_docs",
            "interviews": f"{self.slug}_interviews",
        }.get(collection, f"sector_{self.sector}")
```

and extend the tool's description:

```python
        "Use collection='project' for ingested client documents; "
        "use collection='interviews' for interview answers, one document per question "
        "with its node, discipline, and relationship as metadata; "
        "use collection='sector' for the shared sector knowledge base."
```

- [ ] **Step 5: Run the tests, then both suites, and commit**

Run: `./venv/bin/pytest tests/test_interview_answer_retrieval.py -q`
Expected: PASS, 3 tests.

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS, 958 passed, 2 skipped.

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS.

```bash
git add api/services/interview_answer_service.py agents/tools/chroma_query.py \
  tests/test_interview_answer_retrieval.py
git commit -m "feat(interviews): answers are semantically retrievable with filterable tags"
```

---

### Task 9: Casey cites answers

**Files:**
- Modify: `agents/discovery/synthesis_analyst.py`
- Modify: `agents/tools/registry.py` (Casey gains an answer-reading tool)
- Test: `tests/test_answer_citations.py` (create)

**Interfaces:**
- Consumes: `fetch_interview_answers` (Task 7), `collection='interviews'` (Task 8).
- Produces: no importable interface - Casey's `themes` and `strategic_requirements` gain `evidence[].answer_id`.

**Why:** a theme citing a stakeholder and a node label cites strings that may be rewritten. An answer ID resolves to exactly one answer, in one session, on one node, and the row is append-only.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_answer_citations.py`:

```python
# tests/test_answer_citations.py
"""Themes cite answers, not prose.

A theme citing a stakeholder name and a node label cites two strings that may both be
rewritten. An answer id resolves to exactly one answer, in one session, on one node.
"""
from unittest.mock import MagicMock, patch

import pytest
from crewai import LLM


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


def _task():
    from agents.discovery.synthesis_analyst import create_synthesis_analyst_task
    agent = MagicMock()
    with patch("agents.discovery.synthesis_analyst.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_synthesis_analyst_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    return kwargs["description"]


def test_casey_reads_the_answer_store_rather_than_transcript_blobs():
    """The corpus is too large to read whole, and a blob cannot be filtered by discipline."""
    assert "collection='interviews'" in _task()


def test_a_theme_cites_answer_ids():
    description = _task()
    assert "answer_id" in description


def test_a_theme_still_requires_two_distinct_stakeholders():
    # Preserved from before the citation change: one voice is an individual perspective.
    assert "two evidence entries from different stakeholders" in _task()


def test_a_strategic_requirement_still_names_the_themes_it_derives_from():
    assert "from_themes" in _task()


def test_casey_weights_unprompted_evidence():
    """Six stakeholders raising data quality means something entirely different if five were
    handed the phrase - the tag exists so he does not have to infer it."""
    description = _task()
    assert "unprompted" in description
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_answer_citations.py -q`
Expected: FAIL - three of the five assertions.

- [ ] **Step 3: Point Casey at the answers**

In `agents/discovery/synthesis_analyst.py`, replace step 1 of the task description:

```python
            "1. Use ChromaQueryTool with collection='interviews' to retrieve the interview "
            "answers relevant to each area you are examining. Every answer carries its node, "
            "discipline, relationship, and elicitation as metadata, and its answer_id.\n"
```

and extend the theme schema:

```python
            "\"evidence\": [{\"answer_id\": 812, \"stakeholder_id\": 1, \"quote\": \"...\"}]}\n"
            "   Cite answer_id, not a node label or a section title - those are strings that "
            "may be rewritten, and an answer_id resolves to exactly one answer.\n"
            "   Weight evidence by elicitation: an unprompted mention is stronger than a "
            "prompted agreement, because a prompted question handed the interviewee the "
            "phrase. Say which when the distinction matters to the theme.\n"
```

- [ ] **Step 4: Give Casey the tool**

In `agents/tools/registry.py`, confirm `synthesis_analyst` holds `ChromaQueryTool(slug=slug, sector=sector)`; add it if absent.

- [ ] **Step 5: Run the tests, then both suites, and commit**

Run: `./venv/bin/pytest tests/test_answer_citations.py -q`
Expected: PASS, 5 tests.

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS, 963 passed, 2 skipped.

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS.

```bash
git add agents/discovery/synthesis_analyst.py agents/tools/registry.py \
  tests/test_answer_citations.py
git commit -m "feat(interviews): themes and strategic requirements cite answer ids"
```

---

### Task 10: Coverage follows the anchor

**Files:**
- Create: `api/services/interview_coverage.py`
- Test: `tests/test_interview_coverage.py` (create)

**Interfaces:**
- Consumes: the answer rows from Task 7 and the registry entries from Task 1.
- Produces: `coverage(registry: dict, answers: list[dict]) -> list[dict]`, each row
  `{"node_id": str, "level": str, "relationships": set[str], "covered": bool}`.

**Why:** anchoring A and C scripts to node `0` is only safe if it gives L0 coverage and not
chain coverage. Nothing checks that today, because no coverage function exists - it is
computed by agents from prose, which is exactly why "an executive interviewed with an L0
script covers the stages below them" was ever believable.

Coverage is per (node, relationship) so that "node `0` has internal coverage but no customer
coverage" is expressible. A node covered only by regulators is not the same as a node covered
by the people who run it, and one number cannot say so.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_interview_coverage.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_interview_coverage.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.interview_coverage'`

- [ ] **Step 3: Write the function**

Create `api/services/interview_coverage.py`:

```python
# api/services/interview_coverage.py
"""Which nodes have been interviewed about, and by whom - pure, no I/O.

Coverage used to be an agent's reading of a stakeholder list, which is how "an executive
interviewed with an L0 script covers the stages below them" was ever believable. It is a
query over stored anchors: an answer names the node it was given about, and nothing infers
a position from a job title.
"""
from __future__ import annotations


def coverage(registry: dict, answers: list[dict]) -> list[dict]:
    """One row per active registry node, with the relationships that have answered about it.

    Nodes with no answers are listed with `covered: False` rather than omitted - a node
    absent from the report reads as covered, and the gaps are the point of the report.
    """
    by_node: dict[str, set[str]] = {}
    for answer in answers:
        # A blank answer records that the question was asked, not that it was answered.
        # Counting it would report a node as covered because someone opened a session.
        if not answer.get("answered"):
            continue
        node_id = answer.get("node_id")
        if node_id:
            by_node.setdefault(node_id, set()).add(answer.get("relationship") or "internal")

    return [
        {
            "node_id": entry["id"],
            "level": entry.get("level", ""),
            # No inheritance in either direction. An entity-level interview says nothing
            # about a particular stage, and a stage-level one says nothing about the entity.
            "relationships": by_node.get(entry["id"], set()),
            "covered": bool(by_node.get(entry["id"])),
        }
        for entry in registry.get("activities", [])
        if entry.get("active", True)
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_interview_coverage.py -q`
Expected: PASS, 6 tests.

- [ ] **Step 5: Mutation-test the no-inheritance rule**

```bash
cp api/services/interview_coverage.py /tmp/cov.bak
# M1: entity coverage cascades to the chains - the exact failure the anchoring risks
./venv/bin/python -c "
import pathlib;p=pathlib.Path('api/services/interview_coverage.py');s=p.read_text()
p.write_text(s.replace('\"covered\": bool(by_node.get(entry[\"id\"])),','\"covered\": bool(by_node.get(entry[\"id\"]) or by_node.get(\"0\")),'))"
./venv/bin/pytest tests/test_interview_coverage.py -q   # expect 1 failed
cp /tmp/cov.bak api/services/interview_coverage.py
# M2: blank answers count as coverage
./venv/bin/python -c "
import pathlib;p=pathlib.Path('api/services/interview_coverage.py');s=p.read_text()
p.write_text(s.replace('if not answer.get(\"answered\"):','if False:'))"
./venv/bin/pytest tests/test_interview_coverage.py -q   # expect 1 failed
cp /tmp/cov.bak api/services/interview_coverage.py
./venv/bin/pytest tests/test_interview_coverage.py -q   # expect 6 passed
```

- [ ] **Step 6: Run both suites and commit**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS, 969 passed, 2 skipped.

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS.

```bash
git add api/services/interview_coverage.py tests/test_interview_coverage.py
git commit -m "feat(interviews): coverage is a query over anchors, with no inheritance"
```

---

## After the last task

Regenerate the interview scripts for any live project. The 26 existing script files have no
node IDs, no disciplines, inconsistent `section_id` including `null`, and 178 distinct section
titles, so they are regenerated under the new schema rather than migrated - migrating would
mean guessing an anchor for each one. No interviews have run, so nothing is lost.

Restart the API server. Schema migrations run on connection open, so a server started before
Task 7 has no `interview_answers` table.

## Not in this plan

**What Casey's themes actually say**, how strategic requirements are worded, and how Sage
weighs them - agent instructions rather than structure.

**Wiring the coverage query into what PAM and Jordan report.** Task 10 provides the function
and proves the no-inheritance rule; replacing the prose figures those agents produce today is
its own piece of work, with its own surfaces.

**Retiring `interview_sessions.transcript_json`.** It still backs the transcript review and
email screens, and removing it is a separate change with its own UI surface.
