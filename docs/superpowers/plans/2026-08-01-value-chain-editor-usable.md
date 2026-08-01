# Making the Value Chain Editor Usable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The whole value chain is visible as one grid of entity rows that can be zoomed, a collided model can be repaired by dragging, and an agent cannot store an invalid one in the first place.

**Architecture:** The per-segment grids merge into one whose columns are `(segment_id, column)` pairs ordered left to right, so the model needs no change and the existing uniqueness rule keeps its meaning. `SQLiteStateTool` gains a key-to-validator map and refuses an invalid write, returning the problems as its result so the agent can correct itself. A cell holding several contributions renders them stacked rather than showing one and hiding the rest.

**Tech Stack:** React 18, TypeScript, Vite, Tailwind v3, Vitest + Testing Library. Backend: Python, pytest.

**Spec:** `docs/superpowers/specs/2026-08-01-value-chain-editor-usable-design.md`

## Global Constraints

- **British English** (`-ise`, `-our`, `-re`) in all prose, comments, docstrings, test names, and UI copy.
- **Spaced hyphen ` - ` in prose, never an em dash `—`.** Applies to prose, not hyphenated compound adjectives. Do not alter pre-existing em dashes on lines you are not otherwise changing.
- **Lucide React SVG icons only. No emoji in rendered content.**
- **Never `sky-*` or `blue-*` Tailwind classes.** Brand tokens preferred: `text-brand`, `bg-brand`, `bg-surface`, `bg-surface-raised`, `bg-surface-card`, `text-primary`, `text-secondary`, `text-muted`. `text-red-400` for errors and `amber-*` for warnings are established.
- **All raw SQL lives in `api/database.py`** - none in service, router or tool modules.
- **`agents/tools/human_input.py` must not be modified.**
- Backend tests: `./venv/bin/pytest -q --ignore=tests/integration` - **not** bare `pytest`.
- Frontend tests: `npx vitest run` from `ui/`, plus `npx tsc --noEmit` which must be clean.
- **Baselines: 784 backend, 248 frontend.** Report actual counts; predicted figures are estimates to reconcile, not gates.
- **Stage files explicitly by name. Never `git add -A` or `git add .`** - the working tree holds unrelated untracked files (screenshots, `.docx`) that must not be swept in.

## File Structure

| File | Responsibility |
|---|---|
| `api/services/value_chain_model.py` | **Modify.** The collision problem names the activities involved, once per cell. |
| `agents/tools/sqlite_state.py` | **Modify.** A key-to-validator map; an invalid write is refused and the problems returned. |
| `ui/src/components/ValueChainGrid.tsx` | **Modify.** One continuous grid, entity rows, segment bands, stacked cells, zoom. |
| `ui/src/utils/valueChainModel.ts` | **Modify.** A helper producing the ordered `(segment_id, column)` column list. |

**Task order.** The two backend tasks are independent of everything and of each other. The grid restructure (Task 3) must precede stacking (Task 4) and zoom (Task 5), which both build on its cell rendering. Task 4 is what unblocks the currently-stored invalid model, so it comes before the zoom enhancement.

**A live fixture worth using.** `projects/sp-gs-am/outputs/value_chain_model_v2.json` is a real agent-written model with a real five-way collision in segment 5. Tasks 1, 2 and 4 should each exercise it rather than only synthetic data - it is the exact input that produced this work.

---

## Task 1: The collision problem names the activities

**Files:**
- Modify: `api/services/value_chain_model.py`
- Test: `tests/test_value_chain_model.py`

**Interfaces:**
- Produces: no signature change. `validate_model` reports one problem per over-occupied cell instead of one per duplicate, and names every activity in it.

**The current behaviour, and why it is not enough.** `validate_model` tracks a `seen_cells` set and appends a problem each time a cell repeats:

```python
cell = (activity_segment[activity_id], party_id, column)
if cell in seen_cells:
    problems.append(
        f"two contributions occupy column {column} in party {party_id}'s lane"
    )
seen_cells.add(cell)
```

Two consequences, both real on the live data. Five contributions in one cell produce **four** identical messages, because the first occupant is never reported. And no message names an activity, so a person reading "two contributions occupy column 10 in party GSUK's lane" has to go and find which. Their next action is to move those activities; the message should tell them which ones.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_value_chain_model.py`:

```python
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
    """One message per over-occupied cell, not one per model."""
    model = empty_model()
    model["segments"] = [{"id": "1", "label": "Segment"}]
    model["parties"] = [{"id": "sp", "label": "SP-GS"}, {"id": "iss", "label": "ISS"}]
    model["activities"] = [
        {"id": f"1.{n}", "segment_id": "1", "label": str(n)} for n in range(1, 5)
    ]
    model["contributions"] = [
        {"activity_id": "1.1", "party_id": "sp", "column": 10, "attribution": "stated"},
        {"activity_id": "1.2", "party_id": "sp", "column": 10, "attribution": "stated"},
        {"activity_id": "1.3", "party_id": "iss", "column": 20, "attribution": "stated"},
        {"activity_id": "1.4", "party_id": "iss", "column": 20, "attribution": "stated"},
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
```

Import `pytest` at the top of that file if it is not already imported.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_value_chain_model.py -k collision -v`
Expected: FAIL - the first test finds two messages, not one, and neither names an activity.

- [ ] **Step 3: Report per cell rather than per duplicate**

In `api/services/value_chain_model.py`, replace the `seen_cells` set with a mapping from cell to the activities occupying it, and report after the loop. The contributions loop currently does:

```python
        if activity_known and party_known and column_known:
            cell = (activity_segment[activity_id], party_id, column)
            if cell in seen_cells:
                problems.append(
                    f"two contributions occupy column {column} in party {party_id}'s lane"
                )
            seen_cells.add(cell)
```

Replace `seen_cells: set[...] = set()` with `cell_occupants: dict[tuple[str, str, int], list[str]] = {}` and inside the loop:

```python
        if activity_known and party_known and column_known:
            cell = (activity_segment[activity_id], party_id, column)
            cell_occupants.setdefault(cell, []).append(str(activity_id))
```

Then after the contributions loop, before the tasks loop, report each over-occupied cell once:

```python
    # One problem per over-occupied cell, naming every activity in it. The previous form
    # appended a message each time a cell repeated, so five contributions in one cell
    # produced four identical messages that named none of the five - and the reader's next
    # action is to go and move those activities.
    for (segment_id, party_id, column), occupants in cell_occupants.items():
        if len(occupants) > 1:
            problems.append(
                f"{len(occupants)} contributions occupy column {column} in party "
                f"{party_id}'s lane in segment {segment_id}: {', '.join(sorted(occupants))}"
            )
```

`sorted(occupants)` keeps the message stable across runs, which matters because an existing test asserts a re-run of the migration is byte-identical.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_value_chain_model.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 784 plus the new tests. **Existing tests asserting the old wording will fail** - update them to the new message rather than reverting the wording, and list which you changed in your report.

- [ ] **Step 6: Commit**

```bash
git add api/services/value_chain_model.py tests/test_value_chain_model.py
git commit -m "fix: name the activities that collide, once per cell"
```

---

## Task 2: An agent cannot store an invalid model

**Files:**
- Modify: `agents/tools/sqlite_state.py`
- Test: `tests/test_sqlite_state_validation.py`

**Interfaces:**
- Produces: `_VALIDATORS: dict[str, Callable[[dict], list[str]]]` in `agents/tools/sqlite_state.py`, mapping an output key to a validator returning a list of problems.

**Why this exists.** `SQLiteStateTool._run` validates that the value is JSON and then writes it, recording `output_type=key`. Nothing checks the *content*. That is how an invalid `value_chain_model` reached storage: SP23a added an instruction to the mapper's task text saying a party must not repeat a column within a segment, and the agent violated it anyway. An instruction is not an invariant.

The tool returns a string, and CrewAI surfaces that string to the agent as the tool's result - which is how a tool reports failure. So refusing the write and returning the problems gives the agent the chance to correct itself **within the same run**, rather than a person discovering it days later through a Save button that appears to do nothing.

**This does not replace `save_model`'s validation.** A person editing in the grid can still construct an invalid model, and that path must keep refusing. The two checks guard different writers.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sqlite_state_validation.py`:

```python
# tests/test_sqlite_state_validation.py
"""An agent cannot store a structurally invalid model.

The tool returns a string and CrewAI hands that back to the agent, so a refusal that
names the problems is something the agent can act on inside the same run.
"""
import json
from pathlib import Path

import pytest

from agents.tools.sqlite_state import SQLiteStateTool

SLUG = "sqlite-state-validation-test"


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    """Point the tool at a temporary projects directory so nothing touches real data."""
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    yield
    get_settings.cache_clear()


def _valid_model() -> dict:
    return {
        "model_version": 1,
        "segments": [{"id": "1", "label": "Segment"}],
        "parties": [{"id": "sp", "label": "SP-GS"}],
        "activities": [{"id": "1.1", "segment_id": "1", "label": "A"}],
        "contributions": [
            {"activity_id": "1.1", "party_id": "sp", "column": 10, "attribution": "stated"}
        ],
        "tasks": [],
        "propositions": [],
        "links": [],
    }


def test_a_valid_model_is_written():
    tool = SQLiteStateTool(slug=SLUG)
    result = tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=json.dumps(_valid_model()),
    )
    assert "Written to" in result


def test_an_invalid_model_is_refused_and_the_problems_are_returned():
    """The returned string is what the agent reads and acts on - a bare refusal would
    tell it nothing it could use."""
    model = _valid_model()
    model["activities"].append({"id": "1.2", "segment_id": "1", "label": "B"})
    model["contributions"].append(
        {"activity_id": "1.2", "party_id": "sp", "column": 10, "attribution": "stated"}
    )

    tool = SQLiteStateTool(slug=SLUG)
    result = tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=json.dumps(model),
    )

    assert "Written to" not in result
    assert "column 10" in result
    assert "1.1" in result and "1.2" in result


def test_an_invalid_model_writes_no_file():
    """Refusing but writing anyway would be worse than not checking at all."""
    model = _valid_model()
    model["contributions"][0]["attribution"] = "guessed"

    tool = SQLiteStateTool(slug=SLUG)
    tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=json.dumps(model),
    )

    from api.config import get_settings
    path = Path(get_settings().projects_dir) / SLUG / "outputs" / "value_chain_model.json"
    assert not path.exists()


def test_a_key_with_no_validator_is_written_unchanged():
    """The tool stays general - only registered keys are checked."""
    tool = SQLiteStateTool(slug=SLUG)
    result = tool._run(
        operation="write", key="interview_scripts",
        agent_name="interaction_designer", value=json.dumps({"anything": True}),
    )
    assert "Written to" in result


def test_the_real_agent_written_model_would_have_been_refused():
    """The model that prompted this work. Had this check existed, Alex would have been
    told inside his own run rather than a person finding it days later."""
    path = Path("projects/sp-gs-am/outputs/value_chain_model_v2.json")
    if not path.exists():
        pytest.skip("sp-gs-am fixtures not present in this checkout")

    tool = SQLiteStateTool(slug=SLUG)
    result = tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=path.read_text(),
    )

    assert "Written to" not in result
    assert "5.1" in result
```

`api/config.py:20` declares `projects_dir: str = "./projects"` on a pydantic-settings model, so the environment variable is `PROJECTS_DIR`. The `get_settings.cache_clear()` either side matters - the settings object is cached, so without it the tool writes into the real projects directory.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_sqlite_state_validation.py -v`
Expected: FAIL - the invalid-model tests report "Written to", because nothing checks the content.

- [ ] **Step 3: Add the validator map and the check**

In `agents/tools/sqlite_state.py`, above the class:

```python
# Keys whose content is checked before it is stored. The tool returns a string and CrewAI
# hands that back to the agent, so refusing a write and returning the problems lets the
# agent correct itself inside the same run - rather than the fault surfacing days later
# through a Save button that appears to do nothing.
#
# This does not replace save_model's validation: a person editing in the grid can also
# construct an invalid model, and that path must keep refusing. The two guard different
# writers.
def _validate_value_chain_model(parsed: dict) -> list[str]:
    from api.services.value_chain_model import validate_model
    return validate_model(parsed)


_VALIDATORS: dict[str, Callable[[dict], list[str]]] = {
    "value_chain_model": _validate_value_chain_model,
}
```

Import `Callable` from `typing`. The import of `validate_model` is inside the function deliberately - `agents/` importing `api/` at module level risks a circular import at collection time.

Then in `_run`'s write branch, replace the JSON check so the parsed value is kept:

```python
        if operation == "write":
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as e:
                return f"Error: value is not valid JSON — {e}"

            validator = _VALIDATORS.get(key)
            if validator is not None:
                problems = validator(parsed)
                if problems:
                    return (
                        f"Error: {key} was not written - it is structurally invalid. "
                        f"Fix these and write it again: " + "; ".join(problems)
                    )
```

Leave the existing em dash in the JSON error message alone - it is pre-existing on a line you are not otherwise changing.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_sqlite_state_validation.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: all passing. Report the count.

- [ ] **Step 6: Commit**

```bash
git add agents/tools/sqlite_state.py tests/test_sqlite_state_validation.py
git commit -m "feat: refuse an agent's write when the model is structurally invalid"
```

---

## Task 3: One continuous grid

**Files:**
- Modify: `ui/src/utils/valueChainModel.ts`
- Modify: `ui/src/components/ValueChainGrid.tsx`
- Test: `ui/src/__tests__/ValueChainGrid.test.tsx`

**Interfaces:**
- Produces: `chainColumns(model: ValueChainModel): { segmentId: string; column: number }[]` in `ui/src/utils/valueChainModel.ts` - every occupied column across the whole chain, ordered by segment order then column value, with the gaps within each segment filled as `columnRange` already does.

**What changes and what does not.** Today the component maps over `model.segments` and renders a separate grid for each. It becomes **one** grid: rows are parties, columns are the entries of `chainColumns`, and a band above the columns names the segment each group belongs to.

The model is unchanged. A cell is still found by `(party_id, column)` - but scoped to the segment of that column, which is what makes segment 1's column 10 and segment 2's column 10 different physical columns.

**Every party gets a row across the whole chain**, not only in segments where it contributes. A party with nothing in a segment shows empty cells there, which is information the per-segment grids could not express.

- [ ] **Step 1: Write the failing tests**

Add to `ui/src/__tests__/ValueChainGrid.test.tsx`. The existing `MODEL` fixture is single-segment; these need two.

```tsx
const TWO_SEGMENTS: ValueChainModel = {
  model_version: 1,
  parties: [
    { id: 'sp', label: 'SP-GS', colour: '#1a5276' },
    { id: 'iss', label: 'ISS', colour: '#c0392b' },
  ],
  segments: [
    { id: '1', label: 'Property' },
    { id: '2', label: 'Fleet' },
  ],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Strategy' },
    { id: '1.2', segment_id: '1', label: 'Acquisition' },
    { id: '2.1', segment_id: '2', label: 'Maintenance' },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, attribution: 'stated' },
    { activity_id: '1.2', party_id: 'iss', column: 20, attribution: 'stated' },
    // Segment 2's column 10 is a DIFFERENT physical column from segment 1's.
    { activity_id: '2.1', party_id: 'sp', column: 10, attribution: 'stated' },
  ],
  tasks: [], propositions: [], links: [],
}

describe('the continuous chain', () => {
  it('renders one grid for the whole chain, not one per segment', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    expect(screen.getAllByTestId(/^chain-grid$/)).toHaveLength(1)
  })

  it('names each segment in a band above its own columns', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    expect(screen.getByTestId('segment-band-1')).toHaveTextContent('Property')
    expect(screen.getByTestId('segment-band-2')).toHaveTextContent('Fleet')
  })

  it('keeps two segments’ column 10 as two distinct cells', () => {
    // A single-segment fixture cannot tell a correct implementation from one that keys
    // cells on column alone - both put one card in one place.
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    expect(screen.getByTestId('cell-1-sp-10')).toContainElement(screen.getByTestId('card-1.1-sp'))
    expect(screen.getByTestId('cell-2-sp-10')).toContainElement(screen.getByTestId('card-2.1-sp'))
  })

  it('gives every party a row across the whole chain, even where it does nothing', () => {
    // ISS contributes only in segment 1. The per-segment grids gave it no row in segment 2
    // at all; here its absence is visible as empty cells.
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    expect(screen.getByTestId('lane-iss')).toBeInTheDocument()
    expect(screen.getByTestId('cell-2-iss-10')).toBeInTheDocument()
    expect(screen.getByTestId('cell-2-iss-10')).toHaveTextContent('')
  })
})
```

Cell test ids gain the segment: `cell-<segmentId>-<partyId>-<column>`. Update the existing tests that use the old `cell-<partyId>-<column>` form - **migrate them, do not delete them**, and list what you changed in your report.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ValueChainGrid.test.tsx`
Expected: FAIL - `chain-grid` and `segment-band-1` do not exist; the component still renders a grid per segment.

- [ ] **Step 3: Add `chainColumns`**

Append to `ui/src/utils/valueChainModel.ts`:

```ts
// Every occupied column across the whole chain, ordered by segment order then by column
// value, with the gaps inside each segment filled as columnRange does.
//
// This is what makes one continuous grid possible without touching the model: segment 1's
// column 10 and segment 2's column 10 become different entries, so they render as different
// physical columns while the uniqueness rule - no two contributions of one party within one
// segment share a column - keeps exactly its current meaning.
export function chainColumns(
  model: ValueChainModel,
): { segmentId: string; column: number }[] {
  const out: { segmentId: string; column: number }[] = []
  for (const segment of model.segments) {
    const activityIds = new Set(
      model.activities.filter(a => a.segment_id === segment.id).map(a => a.id),
    )
    const used = model.contributions
      .filter(c => activityIds.has(c.activity_id))
      .map(c => c.column)
    for (const column of columnRange(used)) {
      out.push({ segmentId: segment.id, column })
    }
  }
  return out
}
```

- [ ] **Step 4: Render one grid**

In `ui/src/components/ValueChainGrid.tsx`, replace the `model.segments.map(...)` structure with a single grid.

- The container carries `data-testid="chain-grid"` and
  `gridTemplateColumns: \`${GUTTER} repeat(${columns.length}, minmax(${COLUMN_WIDTH}, 1fr))\``
  where `columns` is `chainColumns(model)`.
- Row 1 is the segment band. Group the columns into runs and span each:

```tsx
// chainColumns emits every column of a segment consecutively, so a run is a contiguous
// slice. Grouping rather than counting per segment keeps the band aligned even if a segment
// contributes no columns at all - it simply produces no band.
const bands: { segmentId: string; start: number; span: number }[] = []
columns.forEach((c, i) => {
  const last = bands[bands.length - 1]
  if (last && last.segmentId === c.segmentId) last.span += 1
  else bands.push({ segmentId: c.segmentId, start: i, span: 1 })
})
```

  Each band renders with `data-testid={\`segment-band-${b.segmentId}\`}` and
  `style={{ gridColumn: \`${b.start + 2} / span ${b.span}\`, gridRow: 1 }}` - the `+ 2`
  skips the gutter column and converts to CSS's 1-based indexing.
- Row 2 is the column headers, unchanged in content - `data-testid={\`column-header-${segmentId}-${column}\`}`.
- Rows 3 onward are the parties, one row each, taken from `model.parties` rather than from
  the parties contributing to a segment.
- A cell is `data-testid={\`cell-${segmentId}-${partyId}-${column}\`}`, and its contribution
  is found by matching party, column **and** the segment of the contribution's activity.
  Build that lookup once, as a named const, because Task 4 consumes it:

```tsx
// activity id -> segment id. A cell must scope by segment or segment 1's column 10 and
// segment 2's column 10 collapse into one.
const segmentOf = (activityId: string) =>
  model.activities.find(a => a.id === activityId)?.segment_id
```

Keep the empty-state branch for a model with no segments exactly as it is.

- [ ] **Step 5: Run the suite and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: all passing, `tsc` clean. Report the count against the 248 baseline, and name every migrated assertion.

- [ ] **Step 6: Commit**

```bash
git add ui/src/utils/valueChainModel.ts ui/src/components/ValueChainGrid.tsx ui/src/__tests__/ValueChainGrid.test.tsx
git commit -m "feat: render the whole value chain as one grid of entity rows"
```

---

## Task 4: A collided cell shows every card

**Files:**
- Modify: `ui/src/components/ValueChainGrid.tsx`
- Test: `ui/src/__tests__/ValueChainGrid.test.tsx`

**What this unblocks.** The stored `sp-gs-am` model has five activities on one column. The cell lookup returns the first match, so four cards render nowhere - and dragging is the only repair the editor offers, so an invisible card cannot be moved. The model is unsaveable and unfixable at once.

A cell that resolves to several contributions renders them **all**, stacked with a small offset and a marker showing the count. Every card stays draggable, so the stack can be pulled apart.

This is a rendering concession, not a model change. The model still says these contributions share a column and the display now says so too, rather than hiding all but one.

- [ ] **Step 1: Write the failing tests**

```tsx
describe('a cell holding more than one contribution', () => {
  const COLLIDED: ValueChainModel = {
    ...TWO_SEGMENTS,
    activities: [
      { id: '1.1', segment_id: '1', label: 'A' },
      { id: '1.2', segment_id: '1', label: 'B' },
      { id: '1.3', segment_id: '1', label: 'C' },
    ],
    contributions: [
      { activity_id: '1.1', party_id: 'sp', column: 10, attribution: 'stated' },
      { activity_id: '1.2', party_id: 'sp', column: 10, attribution: 'stated' },
      { activity_id: '1.3', party_id: 'sp', column: 10, attribution: 'stated' },
    ],
  }

  it('renders every card in the cell, not just the first', () => {
    // Assert the count. "a card renders" is true of the broken behaviour too.
    render(<ValueChainGrid model={COLLIDED} />)
    const cell = screen.getByTestId('cell-1-sp-10')
    expect(cell.querySelectorAll('[data-testid^="card-"]')).toHaveLength(3)
  })

  it('marks how many share the cell', () => {
    render(<ValueChainGrid model={COLLIDED} />)
    expect(screen.getByTestId('cell-overlap-1-sp-10')).toHaveTextContent('3')
  })

  it('leaves each card individually draggable so the stack can be pulled apart', () => {
    render(<ValueChainGrid model={COLLIDED} onChange={() => {}} />)
    for (const id of ['1.1', '1.2', '1.3']) {
      expect(screen.getByTestId(`card-header-${id}-sp`)).toHaveAttribute('draggable', 'true')
    }
  })

  it('shows no overlap marker when a cell holds one contribution', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    expect(screen.queryByTestId('cell-overlap-1-sp-10')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ValueChainGrid.test.tsx -t 'more than one contribution'`
Expected: FAIL - one card renders where three are expected.

- [ ] **Step 3: Render the stack**

In the cell renderer, replace the single `.find(...)` with a filter, and render every match. Offset each after the first so all are visible and clickable - a small `translate` per index, and a marker when the list is longer than one:

```tsx
// segmentOf comes from the lookup Task 3 already builds to scope a cell to its segment -
// reuse it rather than declaring a second. If Task 3 inlined that lookup, hoist it to a
// named const at the top of the component now, so both cell resolution and this filter read
// from one place.
const occupants = model.contributions.filter(
  c => c.party_id === party.id
    && c.column === column
    && segmentOf(c.activity_id) === segmentId,
)
```

Give the marker `data-testid={\`cell-overlap-${segmentId}-${partyId}-${column}\`}` and use `amber-*`, the established warning convention. Keep each card's own `key={contributionKey(activity.id, party.id)}` - identity keying is what stops a move putting a different contribution behind an existing input.

- [ ] **Step 4: Run the suite and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: all passing, `tsc` clean.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/ValueChainGrid.tsx ui/src/__tests__/ValueChainGrid.test.tsx
git commit -m "feat: show every card in a collided cell so the stack can be repaired"
```

---

## Task 5: Zoom

**Files:**
- Modify: `ui/src/components/ValueChainGrid.tsx`
- Test: `ui/src/__tests__/ValueChainGrid.test.tsx`

**Why a transform.** Scaling the grid with CSS `transform: scale()` keeps every card a real DOM element, so drag, inline editing, the party menu and the pop-up all keep working at any zoom. A canvas or SVG rendering would buy sharper zoom and lose all of that - which is the same trade that made React Flow the wrong choice for this editor.

Scale the grid, not the page: the entity column and the segment band scale with it and the scroll container is unaffected.

- [ ] **Step 1: Write the failing tests**

```tsx
describe('zoom', () => {
  it('starts at 100%', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    expect(screen.getByTestId('zoom-level')).toHaveTextContent('100%')
  })

  it('scales the grid down when zoomed out', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    fireEvent.click(screen.getByTestId('zoom-out'))
    expect(screen.getByTestId('chain-grid')).toHaveStyle({ transform: 'scale(0.8)' })
  })

  it('keeps cards interactive after zooming', () => {
    // A test asserting only the style would pass on a grid that scaled itself out of use.
    render(<ValueChainGrid model={TWO_SEGMENTS} onChange={() => {}} />)
    fireEvent.click(screen.getByTestId('zoom-out'))
    expect(screen.getByTestId('card-header-1.1-sp')).toHaveAttribute('draggable', 'true')
    expect(screen.getByTestId('description-1.1-sp')).not.toHaveAttribute('readonly')
  })

  it('does not zoom below the floor', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    for (let i = 0; i < 10; i++) fireEvent.click(screen.getByTestId('zoom-out'))
    expect(screen.getByTestId('zoom-level')).toHaveTextContent('40%')
  })
})
```

Import `fireEvent` from `@testing-library/react` if it is not already imported.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ValueChainGrid.test.tsx -t zoom`
Expected: FAIL - no `zoom-level` control exists.

- [ ] **Step 3: Add the control**

Hold `const [zoom, setZoom] = useState(1)` in `ValueChainGrid`. Steps of `0.2`, floored at `0.4` and capped at `1.4`. Render a small control above the grid with Lucide `Minus` and `Plus` icons, `data-testid` values `zoom-out`, `zoom-in` and `zoom-level`, the last showing `${Math.round(zoom * 100)}%`.

Apply `style={{ transform: \`scale(${zoom})\`, transformOrigin: 'top left' }}` to the grid container. `transformOrigin: 'top left'` keeps the entity column anchored where the reader expects it rather than drifting toward the centre.

- [ ] **Step 4: Run both suites and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: all passing, `tsc` clean. Report both counts.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/ValueChainGrid.tsx ui/src/__tests__/ValueChainGrid.test.tsx
git commit -m "feat: zoom the value chain grid without losing interactivity"
```

---

## Notes carried from the previous four branches

- **Fixture sizing.** A single-segment fixture cannot distinguish a correct continuous grid from one that keys cells on column alone - both put one card in one place. Every test of the segment-scoping uses two segments. The last four branches shipped defects hidden by fixtures too small to tell right from wrong.
- **Count, do not check presence.** Task 4's "renders every card" asserts a count of three, because "a card renders" is true of the broken behaviour it exists to catch.
- **Absence needs a positive anchor.** Task 1's "a valid model reports no collision" pairs with the collision tests - without it, reporting nothing ever would pass them.
- **A live fixture beats a synthetic one where it exists.** `projects/sp-gs-am/outputs/value_chain_model_v2.json` is the real agent-written model that prompted this work; Tasks 1 and 2 both use it, guarded with `pytest.skip` because `projects/` is gitignored.
