# Value Chain Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover the three-chain value chain structure, correct the party model, make the two broken rules enforceable, and reshape the grid and card to match.

**Architecture:** Tasks 1-3 and 7 are Python; 4-6 are React. Task 1 adds a model rule, Task 2 makes the registry an enforced authority at the agent's write path, Task 3 performs the one-time recovery, Tasks 4-6 reshape the UI, Task 7 rewrites the instructions that produced the problem. Tasks 1, 2 and 7 are independent of 4-6; Task 3 depends on 1.

**Tech Stack:** FastAPI, aiosqlite, pure-Python service modules, pytest. React 18, TypeScript, Tailwind v3, Vitest, Testing Library, Lucide React.

## Global Constraints

- British English (`-ise`, `-our`, `-re`) in comments, copy, prompts, and test names.
- Spaced hyphen ` - ` in prose, never an em dash `—`. Hyphenated compound adjectives are fine.
- Lucide React SVG icons only. **No emoji in rendered content.**
- Never `sky-*` or `blue-*` Tailwind classes. Brand and surface tokens only.
- Controlled inputs only - `value`, never `defaultValue`. This guards a defect that silently corrupted saved data.
- Stable `n.n.n` IDs are never changed or reused. There is no alpha prefix; L1 is a number denoting the value chain.
- All raw SQL lives in `api/database.py`. `agents/tools/human_input.py` must not be modified.
- Backend tests: `./venv/bin/pytest -q --ignore=tests/integration` (NOT bare `pytest`). Frontend: `npx vitest run` and `npx tsc --noEmit` from `ui/`.
- **Baselines: backend 794 passed / 2 skipped, frontend 281 passed.** Report both actual totals every task.
- Never `git add -A` or `git add .` - the tree holds unrelated untracked screenshots and `.docx` files. Stage by name.

---

### Task 1: One activity, one column

**Files:**
- Modify: `api/services/value_chain_model.py` - `validate_model`, after the cell-occupancy loop
- Test: `tests/test_value_chain_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a new problem string shape, consumed by Task 2's fixture and by the editor's 422 body. Format: `activity <id> is split across columns: <party> at <col>, <party> at <col>` with the pairs ordered by column then party id.

**Why:** `column` lives on the contribution, so nothing requires two parties doing one activity to share a position. Five of v2's twelve joint activities stagger. This is the rule that makes partner lanes line up by construction.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_value_chain_model.py`:

```python
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
        "tasks": [], "propositions": [], "links": [],
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
    # Three parties in three columns is one problem, not two or three. A two-party
    # fixture cannot tell "report once per activity" from "report once per extra party".
    problems = validate_model(_joint_model({"GSUK": 10, "ISS": 20, "DXI": 30}))
    assert len(problems) == 1
    assert all(p in problems[0] for p in ("GSUK", "ISS", "DXI"))


def test_alignment_and_lane_uniqueness_are_separate_rules():
    # One party holding two columns in one segment breaks lane-uniqueness, not alignment.
    # A model breaking one must never be reported as breaking the other, or the message
    # sends the reader to the wrong place.
    model = _joint_model({"GSUK": 10})
    model["activities"].append({"id": "1.2", "segment_id": "1", "label": "Acquisition"})
    model["contributions"].append(
        {"activity_id": "1.2", "party_id": "GSUK", "column": 10, "attribution": "stated"}
    )
    problems = validate_model(model)
    assert len(problems) == 1
    assert "is split across columns" not in problems[0]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `./venv/bin/pytest tests/test_value_chain_model.py -q -k "column or alignment"`
Expected: the two split-activity tests FAIL (0 problems returned); the share-a-column and separate-rules tests already pass.

- [ ] **Step 3: Implement the rule**

In `validate_model`, collect alongside `cell_occupants` (inside the same contribution loop, in the `activity_known and party_known and column_known` branch):

```python
            activity_columns.setdefault(activity_id, []).append((column, party_id))
```

declaring `activity_columns: dict[str, list[tuple[int, str]]] = {}` beside `cell_occupants`, and after the cell-overlap loop:

```python
    # An activity is one thing, so it occupies one position in the chain. Its parties'
    # contributions therefore share its column - offset columns between two parties on one
    # activity used to mean a handoff, and now mean two activities or two tasks of one.
    # Reported once per activity naming every party and column: a reader's next action is
    # to move one of them, and a message that named neither could not be acted on.
    for activity_id, placements in activity_columns.items():
        if len({column for column, _ in placements}) > 1:
            listed = ", ".join(
                f"{party_id} at {column}"
                for column, party_id in sorted(placements)
            )
            problems.append(f"activity {activity_id} is split across columns: {listed}")
```

- [ ] **Step 4: Run the tests**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS. Report the total - it should be 794 plus the four new tests, with 2 skipped.

Existing tests may now fail if any fixture staggers a joint activity. If one does, that fixture was encoding the behaviour this task removes - fix the fixture to share a column, and say so in your report. Do not weaken the new rule to accommodate it.

- [ ] **Step 5: Commit**

```bash
git add api/services/value_chain_model.py tests/test_value_chain_model.py
git commit -m "feat(value-chain): an activity's contributions must share its column"
```

---

### Task 2: The registry becomes an enforced authority

**Files:**
- Modify: `api/services/value_chain_model.py` - add `validate_against_registry`
- Modify: `agents/tools/sqlite_state.py` - widen the validator signature, load the registry
- Test: `tests/test_value_chain_model.py`, `tests/test_sqlite_state_validation.py`

**Interfaces:**
- Consumes: the `_VALIDATORS` hook added by SP23c and the `isinstance(parsed, dict)` guard in front of it.
- Produces:
  - `validate_against_registry(model: dict, registry: dict) -> list[str]` - **pure**, no I/O.
  - `_VALIDATORS` values change signature from `Callable[[dict], list[str]]` to `Callable[[dict, str], list[str]]`, the second argument being the project slug. The tool has `self.slug` in scope at the call site.

**Why:** every stable ID appearing in both v1 and v2 was reused for a different activity - 14 of 14. The instruction forbidding it has failed twice. `validate_model` cannot check this because it is pure and the registry is a file; the tool already does I/O, so the load belongs there and the comparison stays pure.

**Registry shape** (`value_chain_registry_v<n>.json`):

```json
{"schema_version": 2,
 "activities": [{"id": "1", "label": "Property", "level": "L1", "active": true},
                {"id": "1.1", "label": "Strategy", "level": "L2", "active": true, "parent_id": "1"}]}
```

Levels map to model arrays: `L1` → `segments`, `L2` → `activities`, `L3` → `tasks`.

- [ ] **Step 1: Write the failing tests for the pure comparison**

In `tests/test_value_chain_model.py`:

```python
def _registry(*entries: tuple[str, str, str]) -> dict:
    return {"schema_version": 2,
            "activities": [{"id": i, "label": l, "level": v, "active": True}
                           for i, l, v in entries]}


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
        "propositions": [], "links": [],
    }


def test_a_model_matching_the_registry_has_no_problems():
    registry = _registry(("1", "Property", "L1"), ("1.1", "Strategy", "L2"),
                         ("1.1.1", "Set it", "L3"))
    assert validate_against_registry(_named_model(), registry) == []


def test_reusing_an_id_for_a_different_activity_is_refused():
    registry = _registry(("1", "Property", "L1"),
                         ("1.1", "Fleet Strategy & Policy Setting", "L2"),
                         ("1.1.1", "Set it", "L3"))
    problems = validate_against_registry(_named_model(), registry)
    assert len(problems) == 1
    # Both labels, because the agent's correction is to pick a different id for the new
    # thing - and it cannot do that without being told what the id already means.
    assert "1.1" in problems[0]
    assert "Fleet Strategy & Policy Setting" in problems[0]
    assert "Strategy" in problems[0]


def test_a_genuinely_new_id_is_accepted_so_the_chain_can_grow():
    registry = _registry(("1", "Property", "L1"), ("1.1", "Strategy", "L2"),
                         ("1.1.1", "Set it", "L3"))
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `./venv/bin/pytest tests/test_value_chain_model.py -q -k registry`
Expected: FAIL - `validate_against_registry` is not defined.

- [ ] **Step 3: Implement the pure comparison**

Append to `api/services/value_chain_model.py`:

```python
# Which model array each registry level governs. An entry's level is a claim about what
# kind of thing an id names, so an id registered as an L3 cannot arrive as an activity.
_LEVEL_ARRAYS = (("L1", "segments"), ("L2", "activities"), ("L3", "tasks"))


def validate_against_registry(model: dict, registry: dict) -> list[str]:
    """Every way this model contradicts the registry's ID ledger.

    Pure - the caller loads the registry. An id already in the ledger must still name the
    same thing; an id absent from it is a genuine addition and is allowed, so the chain can
    still grow. An empty ledger accepts anything, which is what a first run needs.
    """
    problems: list[str] = []
    known = {
        entry.get("id"): (entry.get("level"), entry.get("label"))
        for entry in registry.get("activities", [])
    }
    if not known:
        return problems

    for level, array in _LEVEL_ARRAYS:
        for item in model.get(array, []):
            registered = known.get(item.get("id"))
            if registered is None:
                continue
            registered_level, registered_label = registered
            if registered_level != level:
                problems.append(
                    f"{array[:-1]} {item.get('id')} is registered as a {registered_level}, "
                    f"not a {level} - use an unused id for it"
                )
            elif registered_label and item.get("label") != registered_label:
                problems.append(
                    f"id {item.get('id')} already means {registered_label!r} and cannot be "
                    f"reused for {item.get('label')!r} - take the next unused number instead"
                )
    return problems
```

- [ ] **Step 4: Write the failing test for the tool wiring**

In `tests/test_sqlite_state_validation.py`, beside the existing refusal tests. Follow that file's existing fixture, which seeds its own `projects` and `agent_outputs` tables and points `PROJECTS_DIR` and `DATABASE_DIR` at its own `tmp_path`:

```python
def test_a_model_reusing_a_registered_id_is_refused_and_no_row_is_recorded(tool, tmp_path):
    """Write a registry first, then a model contradicting it."""
    # (Write value_chain_registry through the same tool so the _vN rename happens, then
    # write a model whose 1.1 carries a different label. Assert the result names both
    # labels, that no value_chain_model file exists, and that agent_outputs has no
    # value_chain_model row - asserting only the returned string proves nothing about
    # whether the write was actually refused.)


def test_a_model_is_written_when_no_registry_exists_yet(tool, tmp_path):
    """A first run has nothing to check against and must not be blocked."""
```

Fill both bodies against the file's existing helpers. The docstrings state the required behaviour; the assertions must cover the returned string **and** the absence of the file **and** the absence of the row.

- [ ] **Step 5: Widen the validator signature and load the registry**

In `agents/tools/sqlite_state.py`:

```python
def _validate_value_chain_model(parsed: dict, slug: str) -> list[str]:
    from api.services.value_chain_model import validate_against_registry, validate_model

    problems = validate_model(parsed)
    settings = get_settings()
    registry_path = latest_output_path(
        Path(settings.projects_dir) / slug / "outputs" / "value_chain_registry.json"
    )
    if registry_path is not None:
        try:
            registry = json.loads(registry_path.read_text())
        except (OSError, json.JSONDecodeError):
            # A registry we cannot read is not a reason to refuse a model - it would block
            # every write on a corrupt sidecar. The structural checks above still ran.
            registry = {}
        problems.extend(validate_against_registry(parsed, registry))
    return problems


_VALIDATORS: dict[str, Callable[[dict, str], list[str]]] = {
    "value_chain_model": _validate_value_chain_model,
}
```

Match the existing module's own expression for the outputs directory rather than inventing one - read how `_run` builds `file_path` and reuse that.

At the call site, `problems = validator(parsed)` becomes `problems = validator(parsed, self.slug)`.

- [ ] **Step 6: Run the tests**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS. Report the total.

- [ ] **Step 7: Commit**

```bash
git add api/services/value_chain_model.py agents/tools/sqlite_state.py tests/test_value_chain_model.py tests/test_sqlite_state_validation.py
git commit -m "feat(value-chain): the registry becomes an enforced ID authority at the write path"
```

---

### Task 3: Recover the three-chain model

**Files:**
- Create: `api/services/value_chain_recovery.py`
- Create: `tests/test_value_chain_recovery.py`

**Interfaces:**
- Consumes: `validate_model` (Task 1), `save_model` from `api/services/value_chain_store.py`.
- Produces:
  - `correct_parties(model: dict) -> dict` - pure
  - `registry_from_model(model: dict) -> dict` - pure
  - `async recover(slug: str, *, saved_by: str) -> dict` - I/O; returns the recovered model

**Why:** v1 holds the right three chains and 59 task labels. Its party model is wrong in a way that is recorded elsewhere and must not be left to Alex, who has got it wrong twice.

**The corrections, all evidenced by `value_chain_summary_v12.json`:**

| v1 | Becomes |
|---|---|
| party `sp`, label `"sp"` | id `GSUK`, label `"Scottish Power Group Services UK (GS UK)"` |
| party `partnerISS`, label `"partnerISS"` | id `ISS`, label `"ISS (FM subcontractor)"` |
| party `partnerDXI`, label `"partnerDXI"` | id `DXI`, label `"DXI (fleet maintenance subcontractor)"` |
| activity `2.5` label `"⑤ Fleet Maintenance Delivery (ISS)"` | `"Fleet Maintenance Delivery"` |
| segment labels carrying `— … \| Custodian: … · Maintainer: ISS` | `"Property"`, `"Fleet"`, `"Support Services"`, the detail moved to `description`, and fleet's maintainer named as DXI |
| labels prefixed `① ② ③ ④ ⑤ ⑥` | prefix stripped |

Party **ids** change, so every `party_id` in `contributions`, `tasks`, `propositions` and `links` is remapped in the same pass. Activity and task **ids are untouched** - they are the stable IDs this whole plan exists to protect.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_value_chain_recovery.py`. Build the fixture from the shape of the real v1 - three segments, a `sp`/`partnerISS`/`partnerDXI` party list with labels equal to their ids, an activity `2.5` labelled `"⑤ Fleet Maintenance Delivery (ISS)"` attributed to `partnerDXI`, and at least one task and one contribution per party so the remap has something to miss.

```python
def test_party_ids_are_remapped_everywhere_they_are_referenced():
    out = correct_parties(_v1_like())
    ids = {p["id"] for p in out["parties"]}
    assert ids == {"GSUK", "ISS", "DXI"}
    # The remap is only correct if nothing still points at the old ids. Asserting the
    # party list alone would pass while every contribution dangled.
    for array in ("contributions", "tasks", "propositions", "links"):
        for item in out.get(array, []):
            for field in ("party_id", "from_party_id", "to_party_id"):
                if field in item:
                    assert item[field] in ids


def test_every_party_gains_a_label_that_is_not_its_id():
    out = correct_parties(_v1_like())
    for party in out["parties"]:
        assert party["label"] and party["label"] != party["id"]


def test_fleet_maintenance_loses_the_iss_suffix_and_stays_with_dxi():
    out = correct_parties(_v1_like())
    activity = next(a for a in out["activities"] if a["id"] == "2.5")
    assert "ISS" not in activity["label"]
    assert next(c for c in out["contributions"]
                if c["activity_id"] == "2.5")["party_id"] == "DXI"


def test_activity_and_task_ids_are_untouched():
    before = _v1_like()
    out = correct_parties(before)
    assert [a["id"] for a in out["activities"]] == [a["id"] for a in before["activities"]]
    assert [t["id"] for t in out["tasks"]] == [t["id"] for t in before["tasks"]]


def test_the_recovered_model_validates():
    assert validate_model(correct_parties(_v1_like())) == []


def test_the_registry_is_built_from_the_model_at_the_right_levels():
    registry = registry_from_model(correct_parties(_v1_like()))
    by_id = {e["id"]: e for e in registry["activities"]}
    assert by_id["1"]["level"] == "L1"
    assert by_id["2.5"]["level"] == "L2"
    assert by_id["2.5"]["parent_id"] == "2"
    assert all(e["active"] for e in registry["activities"])


def test_the_registry_carries_the_corrected_labels_not_the_originals():
    # If the registry is built before the corrections, it re-registers "⑤ Fleet
    # Maintenance Delivery (ISS)" as the meaning of 2.5 and Task 2 then refuses every
    # subsequent write of the corrected label.
    registry = registry_from_model(correct_parties(_v1_like()))
    assert "ISS" not in next(e for e in registry["activities"] if e["id"] == "2.5")["label"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `./venv/bin/pytest tests/test_value_chain_recovery.py -q`
Expected: FAIL - the module does not exist.

- [ ] **Step 3: Implement the pure transforms**

Create `api/services/value_chain_recovery.py` with `correct_parties` and `registry_from_model` as specified above. Keep both pure - no file access, no database - so they can be tested without a project, matching `value_chain_model.py`'s own rule.

Strip the circled-number prefixes with an explicit character set rather than a general "leading non-alphanumeric" rule, which would eat a legitimate leading bracket or quote:

```python
_PREFIXES = "①②③④⑤⑥⑦⑧⑨⑩ "
```

- [ ] **Step 4: Implement `recover`**

```python
async def recover(slug: str, *, saved_by: str) -> dict:
    """Make the corrected three-chain model current and rebuild the registry from it."""
```

It reads the v1 model file, applies `correct_parties`, saves through `save_model` (which validates and versions), then writes the registry produced by `registry_from_model` as a new `value_chain_registry` output.

**Order matters and is asserted above:** correct first, then build the registry from the corrected model. Building it first registers the wrong labels, and Task 2 would then refuse every future write of the right ones.

- [ ] **Step 5: Run the tests**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS. Report the total.

- [ ] **Step 6: Commit**

```bash
git add api/services/value_chain_recovery.py tests/test_value_chain_recovery.py
git commit -m "feat(value-chain): recover the three-chain model and correct the party model"
```

---

### Task 4: Chains stack, each with its own lanes

**Files:**
- Modify: `ui/src/components/ValueChainGrid.tsx`
- Test: `ui/src/__tests__/ValueChainGrid.test.tsx`

**Interfaces:**
- Consumes: `chainColumns` from `ui/src/utils/valueChainModel.ts`, which currently returns one flat ordered list of `{segmentId, column}` across the whole model.
- Produces: no new exports. Test ids change: `segment-band-<id>` stays; `column-header-*` is **removed**; `cell-<segmentId>-<partyId>-<column>` and `lane-<partyId>` are unchanged in shape but `lane-<partyId>` now repeats once per chain the party contributes in, so lane test ids become `lane-<segmentId>-<partyId>`.

**Why:** today the three chains sit side by side on one horizontal line, so seeing Fleet means scrolling past the whole of Property, and one party's lane spans all three chains - meaningless when the chains have different parties.

- [ ] **Step 1: Write the failing tests**

Add a `THREE_CHAINS` fixture: segments `1` Property, `2` Fleet, `3` Support; parties `GSUK` (contributing in all three), `ISS` (Property only), `DXI` (Fleet only); one activity per party per chain, columns starting at 10 in each chain.

```tsx
  it('renders one block per chain, stacked, each starting at its own first column', () => {
    render(<ValueChainGrid model={THREE_CHAINS} />)
    // A single-chain fixture cannot tell a stacked layout from a side-by-side one.
    for (const id of ['1', '2', '3']) {
      expect(screen.getByTestId(`chain-grid-${id}`)).toBeInTheDocument()
    }
    expect(screen.queryByTestId('chain-grid')).toBeNull()
  })

  it('gives a chain lanes only for the parties that contribute in it', () => {
    render(<ValueChainGrid model={THREE_CHAINS} />)
    expect(screen.getByTestId('lane-1-ISS')).toBeInTheDocument()
    // ISS does no fleet work. An empty lane would say so, and we have decided it should
    // not be said - the view is for flow and who does what, in what order.
    expect(screen.queryByTestId('lane-2-ISS')).toBeNull()
    expect(screen.queryByTestId('lane-3-ISS')).toBeNull()
    expect(screen.getByTestId('lane-2-DXI')).toBeInTheDocument()
    expect(screen.queryByTestId('lane-1-DXI')).toBeNull()
  })

  it('names each chain above its own block', () => {
    render(<ValueChainGrid model={THREE_CHAINS} />)
    expect(screen.getByTestId('segment-band-2')).toHaveTextContent('2')
    expect(screen.getByTestId('segment-band-2')).toHaveTextContent('Fleet')
  })

  it('shows no column ruler, while still rendering an unoccupied column as a gap', () => {
    // The ruler goes; the gap does not. A column with nobody in it is a real position in
    // the flow, and removing the header must not remove the cell.
    const gapped = structuredClone(THREE_CHAINS)
    gapped.contributions.push({
      activity_id: '1.3', party_id: 'GSUK', column: 30, attribution: 'stated',
    })
    gapped.activities.push({ id: '1.3', segment_id: '1', label: 'Later' })
    render(<ValueChainGrid model={gapped} />)
    expect(screen.queryByTestId(/^column-header-/)).toBeNull()
    expect(screen.getByTestId('cell-1-GSUK-20')).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ValueChainGrid.test.tsx`
Expected: FAIL - there is one `chain-grid`, lanes are global, and column headers exist.

- [ ] **Step 3: Restructure the render**

The component maps over `model.segments`, rendering one block each. Per chain:

- its columns are that chain's own, ordered, with gaps filled - reuse `columnRange` on the columns used within that chain rather than slicing the global `chainColumns` list.
- its lanes are `model.parties.filter(p => that chain's contributions include p.id)`.
- `gridTemplateColumns` uses that chain's column count.
- the chain heading (`segment-band-<id>`) sits above its block, keeping its number and label.
- **row 2 disappears entirely** - no column headers.

One zoom transform wraps all the blocks together, so zooming still scales the whole view rather than one chain.

Keep the cross-segment drop guard. It becomes structurally harder to violate now that each chain is its own grid, but it is a guard against the model changing under the view, not against the pointer.

`chainColumns` in `ui/src/utils/valueChainModel.ts` loses its only caller if the per-chain columns are computed from `columnRange`. If so, delete it and its unit tests, and say so in your report - a tested but uncalled export is still dead code.

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, `tsc` clean. Several existing grid, drag and collision tests will need their `lane-*` ids and single-`chain-grid` assumptions updated. **Update the ids; do not weaken any assertion.** If a test can no longer express what it asserted, say so in your report rather than deleting it.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/ValueChainGrid.tsx ui/src/utils/valueChainModel.ts ui/src/__tests__/
git commit -m "feat(value-chain): chains stack, each with its own columns and lanes"
```

---

### Task 5: The card gets an edge, a shadow and a fixed height

**Files:**
- Modify: `ui/tailwind.config.js` - add `surface.border`
- Modify: `ui/src/components/ContributionCard.tsx`
- Test: `ui/src/__tests__/ValueChainGrid.test.tsx`

**Interfaces:**
- Consumes: Task 4's layout (independent of it in code; run after to avoid conflicting edits to the same test file).
- Produces: `surface.border` token; test id `task-overflow-<activityId>-<partyId>` for the remainder count.

**Why:** `bg-surface-card` is `#ffffff` and the page `surface.DEFAULT` is `#f9fafb`. SP24a set the card's resting border to `border-surface` - **the page background colour** - so the edge it added is a two per cent difference. The scale has no border token at all.

- [ ] **Step 1: Add the token**

In `ui/tailwind.config.js`, inside `colors.surface`:

```js
        surface: {
          DEFAULT: '#f9fafb',
          raised: '#ffffff',
          card: '#ffffff',
          border: '#e5e7eb',
        },
```

- [ ] **Step 2: Write the failing tests**

```tsx
  it('draws the card edge in something other than the page background', () => {
    render(<ValueChainGrid model={MODEL} />)
    const card = screen.getByTestId('card-1.1-sp')
    // The defect this replaces: the card carried border-surface, which IS surface.DEFAULT,
    // the page background. A test asserting "has a border class" passed while the edge was
    // invisible, so the assertion has to be that it is not that class.
    expect(card).not.toHaveClass('border-surface')
    expect(card).toHaveClass('border-surface-border')
    expect(card.className).toMatch(/\bshadow/)
  })

  it('gives every card the same height regardless of its content', () => {
    const uneven = structuredClone(MODEL)
    uneven.contributions[0].description = 'x'.repeat(400)
    uneven.contributions[1].description = 'short'
    render(<ValueChainGrid model={uneven} />)
    const a = screen.getByTestId('card-1.1-sp').className
    const b = screen.getByTestId('card-1.2-sp').className
    // jsdom does no layout, so this asserts the mechanism - one fixed height class shared
    // by both - rather than a measured height, which reads 0 here either way.
    const height = (c: string) => c.split(' ').find((x) => x.startsWith('h-'))
    expect(height(a)).toBeTruthy()
    expect(height(a)).toBe(height(b))
  })

  it('lists at most three activities and says how many more there are', () => {
    const many = structuredClone(MODEL)
    many.tasks = [1, 2, 3, 4, 5].map((n) => ({
      activity_id: '1.1', party_id: 'sp', id: `1.1.${n}`, label: `Step ${n}`,
    }))
    render(<ValueChainGrid model={many} />)
    expect(screen.getAllByTestId(/^task-line-.*-sp$/)).toHaveLength(3)
    // The count is the assertion. "renders three lines" is equally true of a silent
    // truncation, which states that this contribution has three activities - a false
    // statement rather than a shortened one.
    expect(screen.getByTestId('task-overflow-1.1-sp')).toHaveTextContent('2')
  })

  it('shows no overflow marker when every activity fits', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.queryByTestId('task-overflow-1.1-sp')).toBeNull()
  })
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ValueChainGrid.test.tsx`
Expected: FAIL on all four.

- [ ] **Step 4: Implement**

In `ContributionCard.tsx`:

- The card's className becomes `bg-surface-card rounded-lg p-3 border shadow-sm` with `selected ? 'border-brand' : 'border-surface-border'`, plus a fixed height class sized for a two-line header, three description lines, three activity lines and the controls row. Add `overflow-hidden` so nothing spills past the fixed height. Selection continues to change the border's **colour**, never to add an edge.
- Slice the task list to three, and where there are more, render the remainder:

```tsx
      {tasks.length > 3 && (
        <p data-testid={`task-overflow-${activityId}-${partyId}`} className="mt-1 text-xs text-muted">
          {tasks.length - 3} more
        </p>
      )}
```

- [ ] **Step 5: Run the tests and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, `tsc` clean. SP24a's `'gives an unselected card a visible edge'` test asserts `border-surface`; it is now asserting the defect. Replace its assertion with the one from Step 2 rather than keeping both.

- [ ] **Step 6: Commit**

```bash
git add ui/tailwind.config.js ui/src/components/ContributionCard.tsx ui/src/__tests__/ValueChainGrid.test.tsx
git commit -m "feat(value-chain): card gets a real edge, a shadow and a fixed height"
```

---

### Task 6: The card shows, the dialog edits

**Files:**
- Modify: `ui/src/components/ContributionCard.tsx` - lines become plain text, pencil added
- Modify: `ui/src/components/ContributionPanel.tsx` - becomes editable
- Modify: `ui/src/components/ValueChainGrid.tsx`, `ui/src/components/StructureTab.tsx`, `ui/src/utils/valueChainModel.ts` - remove the `taskId` plumbing
- Test: `ui/src/__tests__/ValueChainContributionPanel.test.tsx`, `ui/src/__tests__/ValueChainGrid.test.tsx`

**Interfaces:**
- Consumes: Task 5's card.
- Produces:
  - `ValueChainSelection.taskId` and `ContributionPanelProps.highlightTaskId` are **removed**; `onSelect` returns to `(activityId, partyId) => void`.
  - `ContributionPanel` gains `onChange?: (model: ValueChainModel) => void`; absent means read-only, matching the card's own convention.
  - New: `updateActivityLabel(model, activityId, label)` and `updateTaskLabel(model, taskId, label)` in `valueChainModel.ts`, both pure and non-mutating like their neighbours.
  - Test id `edit-<activityId>-<partyId>` for the pencil.

**Why:** this removes part of SP24a deliberately. The card's activity lines were made clickable two days ago, carrying a `taskId` up so the dialog opened highlighted on the one clicked. With the lines no longer interactive that plumbing has no producer, and unreachable code is worse than removed code.

- [ ] **Step 1: Write the failing tests**

In `ValueChainGrid.test.tsx`:

```tsx
  it('renders activity lines as text, not as controls', () => {
    render(<ValueChainGrid model={MODEL} onSelect={() => {}} />)
    const line = screen.getByTestId('task-line-1.1.1-sp')
    expect(line.tagName).not.toBe('BUTTON')
    expect(line.closest('button')).toBeNull()
  })

  it('opens the dialog from the pencil, and not from the card header', async () => {
    const seen: Array<[string, string]> = []
    render(<ValueChainGrid model={MODEL} onSelect={(a, p) => seen.push([a, p])} />)
    await userEvent.click(screen.getByTestId('card-header-1.1-sp'))
    expect(seen).toEqual([])
    await userEvent.click(screen.getByTestId('edit-1.1-sp'))
    expect(seen).toEqual([['1.1', 'sp']])
  })
```

In `ValueChainContributionPanel.test.tsx` - this file drives `StructureTab`, so it exercises the whole chain:

```tsx
  it('edits the stage label from the dialog and the change reaches the model', async () => {
    await openStructureTab()
    await userEvent.click(screen.getByTestId('edit-1.1-sp'))
    const field = screen.getByTestId('edit-activity-label-1.1')
    await userEvent.clear(field)
    await userEvent.type(field, 'Reactive Repair')
    expect(field).toHaveValue('Reactive Repair')
  })

  it('edits an activity label from the dialog', async () => {
    await openStructureTab()
    await userEvent.click(screen.getByTestId('edit-1.1-sp'))
    const field = screen.getByTestId('edit-task-label-t2')
    await userEvent.type(field, '!')
    // Controlled, never defaultValue - the same defence that guards the card's
    // description. An uncontrolled field would show the keystroke and lose it on save.
    expect(field).toHaveValue('Assess the damage!')
  })

  it('is read-only when the dialog is given no onChange', () => {
    // The card's own convention: no handler means no editing, rather than a separate flag
    // that can disagree with it.
  })
```

Fill the third test's body against the file's helpers.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ValueChainGrid.test.tsx src/__tests__/ValueChainContributionPanel.test.tsx`
Expected: FAIL - the lines are buttons, there is no pencil, and the dialog has no fields.

- [ ] **Step 3: Remove the `taskId` plumbing**

Delete `taskId` from `ValueChainSelection`, `highlightTaskId` from `ContributionPanelProps`, the third argument from every `onSelect` signature, the highlight ref and its effect, and the `border-brand` / `border-transparent` highlight classes on the dialog's list rows. Delete the tests that covered the highlight - they cover a mechanism that no longer exists. Name them in your report.

- [ ] **Step 4: Make the lines text and add the pencil**

Each activity line becomes a `<span>`/`<li>` with the same content and test id, no `onClick`, no `type="button"`. Add the pencil beside the Parties control, using Lucide `Pencil`:

```tsx
        <button
          type="button"
          data-testid={`edit-${activityId}-${partyId}`}
          aria-label={`Edit ${activity.label}`}
          onClick={() => onSelect?.(activityId, partyId)}
          className="text-secondary hover:text-brand"
        >
          <Pencil className="w-4 h-4" aria-hidden="true" />
        </button>
```

Remove the card header's `onClick`. It keeps `draggable` and its arrow-key handler; only the click goes.

The Parties control stays on the card, where the lane it acts on is visible.

- [ ] **Step 5: Make the dialog editable**

`ContributionPanel` takes `onChange`. When present it renders controlled text inputs for the activity's label (`edit-activity-label-<activityId>`) and each task's label (`edit-task-label-<taskId>`), each calling the matching pure helper and passing the new model up. When absent it renders exactly what it renders today.

Add the two helpers to `valueChainModel.ts` beside `updateDescription`, following its shape - `structuredClone`, mutate the clone, return it, never mutate the argument.

- [ ] **Step 6: Run the tests and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, `tsc` clean.

- [ ] **Step 7: Commit**

```bash
git add ui/src/components/ContributionCard.tsx ui/src/components/ContributionPanel.tsx ui/src/components/ValueChainGrid.tsx ui/src/components/StructureTab.tsx ui/src/utils/valueChainModel.ts ui/src/__tests__/
git commit -m "feat(value-chain): the card shows and the dialog edits"
```

---

### Task 7: Rewrite the instructions that produced this

**Files:**
- Modify: `agents/discovery/value_chain_mapper.py:95` and `:113-131`
- Test: `tests/test_value_chain_mapper.py` (create if absent)

**Interfaces:**
- Consumes: the rules enforced by Tasks 1 and 2.
- Produces: nothing importable.

**Why:** two of the five symptoms were the prompt being followed, not ignored. `:95` defines segments as *"the primary value chain lanes (e.g. Strategy/Planning, Acquisition, Delivery, Monitoring/Review)"* - a list of process stages, which is exactly what Alex produced. `:113-116` tells him offset columns between two parties on one activity *"mean a handoff from one party to the next"*, which Task 1 now refuses on save. **Leaving that sentence in place would have Alex writing models the tool rejects.**

- [ ] **Step 1: Write the failing test**

```python
def test_the_task_does_not_instruct_the_handoff_that_validation_refuses():
    task = create_value_chain_mapper_task(...)   # match the existing signature
    assert "handoff from one party to the next" not in task.description


def test_the_task_states_the_alignment_rule():
    task = create_value_chain_mapper_task(...)
    assert "same column" in task.description


def test_segments_are_described_as_value_chains_not_process_stages():
    task = create_value_chain_mapper_task(...)
    # The old wording listed Strategy/Planning, Acquisition, Delivery, Monitoring - process
    # stages - and Alex produced exactly that. A prompt test is brittle by nature; this one
    # earns its place because the wording it guards caused a rebuild of the whole chain.
    assert "Acquisition, Delivery, Monitoring" not in task.description
```

Read the real signature of `create_value_chain_mapper_task` and construct whatever it needs; do not guess it.

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_value_chain_mapper.py -q`
Expected: FAIL on the first and third.

- [ ] **Step 3: Rewrite the two passages**

`:95` - segments are **value chains**, not process stages: each is a distinct chain of value the client operates, with its own parties and its own left-to-right flow. Give the actual three as the example - Property, Fleet, Support Services - and say that the stages within a chain are that chain's own and are not shared between chains.

`:113-116` - the column is a position in the chain, and **every party contributing to one activity carries that activity's column**. Where one party's work genuinely follows another's, that is two activities or two tasks of one, not one activity at two columns. Keep the existing rule (ii) about a party not repeating a column within a segment - the two rules are different and both hold.

Add a third rule alongside them: an id already in the registry keeps its meaning; a new thing takes the next unused number.

- [ ] **Step 4: Run everything**

Run: `./venv/bin/pytest -q --ignore=tests/integration` and, from `ui/`, `npx vitest run && npx tsc --noEmit`
Expected: both green. Report both totals - this is the last task, so the pair confirms nothing drifted across the whole plan.

- [ ] **Step 5: Commit**

```bash
git add agents/discovery/value_chain_mapper.py tests/test_value_chain_mapper.py
git commit -m "fix(value-chain): segments are value chains, and one activity has one column"
```
