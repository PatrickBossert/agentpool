# Value Chain Grid of Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the value chain Structure table with a grid of activity cards arranged across party swimlanes, where a card can be dragged between sparse column positions and an activity can be attributed to a second party.

**Architecture:** One CSS Grid per segment - rows are party lanes, columns are the segment's sparse column positions, and a card sits at an explicit `gridColumn`/`gridRow`. Snapping needs no implementation because a grid cell is the only place a card can be. Model types and every pure operation move out of the component into `ui/src/utils/valueChainModel.ts`, so views are thin and the operations are testable without rendering.

**Tech Stack:** React 18, TypeScript, Vite, Tailwind v3, Vitest + Testing Library, Lucide React icons, TanStack Query. Backend: FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-07-30-value-chain-grid-design.md`

## Global Constraints

- **British English** (`-ise`, `-our`, `-re`) in all prose, comments, docstrings, test names, and UI copy.
- **Spaced hyphen ` - ` in prose, never an em dash `—`.** Applies to prose, not hyphenated compound adjectives. Do not alter pre-existing em dashes in lines you are not otherwise changing.
- **Lucide React SVG icons only. No emoji in rendered content.**
- **Never `sky-*` or `blue-*` Tailwind classes** - deliberately removed from this codebase. Prefer brand tokens: `text-brand`, `bg-brand`, `bg-surface`, `bg-surface-raised`, `bg-surface-card`, `text-primary`, `text-secondary`, `text-muted`. `text-red-400` for error text is an accepted convention.
- **All raw SQL lives in `api/database.py`** - none in service or router modules.
- **`agents/tools/human_input.py` must not be modified.**
- **Stable `Ln.n.n` IDs are never changed or reused.**
- Frontend tests: `npx vitest run` from `ui/`. Also `npx tsc --noEmit`, which must be clean.
- Backend tests: `./venv/bin/pytest -q --ignore=tests/integration` - **not** bare `pytest`.
- **Baselines entering this plan: 112 frontend tests, 732 backend tests.**
- **Stage files explicitly by name. Never `git add -A` or `git add .`** - the working tree holds unrelated untracked files (screenshots, `.docx`) that must not be swept in.

## File Structure

| File | Responsibility |
|---|---|
| `ui/src/utils/valueChainModel.ts` | **Create.** Model types plus every pure operation. No React import. |
| `ui/src/components/ValueChainGrid.tsx` | **Create.** One grid per segment: gutter, column headers, lane rows, cells, drop handling. |
| `ui/src/components/ContributionCard.tsx` | **Create.** One card: header (focus/move/open), description input, party menu. |
| `ui/src/components/StructureTab.tsx` | **Create.** The Structure tab lifted out of `ValueChain.tsx`. |
| `ui/src/components/ContributionPanel.tsx` | **Modify.** Same filtering, presented as a modal. |
| `ui/src/components/ValueChainTable.tsx` | **Delete** in Task 5. |
| `api/services/value_chain_model.py` | **Modify.** Add the zero-contribution activity rule. |
| `api/services/value_chain_migration.py` | **Modify.** Give a childless activity a cascade-attributed contribution. |

**Task order and why:** the pure model comes first so the UI has something correct to build on (Tasks 1-2); the backend rule is independent (Task 3); `StructureTab` is extracted before the grid exists so the swap in Task 5 is a small diff in a small file (Task 4); the grid replaces the table **at feature parity in one task** so the application is never left without an editor (Task 5); then drag (6), the modal (7), and the new party operations (8).

**No task leaves a component that nothing imports.** This branch's predecessor shipped `ContributionPanel.tsx` importable from nowhere, and the sprint before that shipped `ReviewQueue.tsx` holding the only commit control in the product, reachable by nothing. Every task below wires its component into the page in the same task that creates it.

---

## Existing test IDs to preserve

Tasks 5-8 keep these `data-testid` values from the table, so the tests transferred from `ValueChainTable.test.tsx` and `ValueChainEditing.test.tsx` need minimal change:

- `cell-<partyId>-<column>` - a grid cell, occupied or empty
- `description-<activityId>-<partyId>` - the description input
- `move-left-<activityId>-<partyId>` / `move-right-<activityId>-<partyId>`
- `select-<activityId>-<partyId>` - becomes the card header's open control
- `contribution-panel`, `contribution-panel-placeholder`
- `unsaved-changes`, `migration-counts`

New in this plan: `grid-segment-<segmentId>`, `segment-gutter-<segmentId>`, `lane-<partyId>`, `lane-count-<partyId>`, `column-header-<column>`, `card-<activityId>-<partyId>`, `card-header-<activityId>-<partyId>`, `derived-<activityId>-<partyId>`, `confirm-attribution-<activityId>-<partyId>`, `task-count-<activityId>-<partyId>`, `proposition-count-<activityId>-<partyId>`, `party-menu-<activityId>-<partyId>`, `add-party-<activityId>-<partyId>-<targetPartyId>`, `remove-party-<activityId>-<partyId>`, `confirm-remove`, `cancel-remove`.

---

## Task 1: Extract the model module

**Files:**
- Create: `ui/src/utils/valueChainModel.ts`
- Create: `ui/src/__tests__/valueChainModel.test.ts`
- Modify: `ui/src/components/ValueChainTable.tsx` - remove the types and pure functions, import them instead
- Modify: `ui/src/components/ContributionPanel.tsx:6`, `ui/src/pages/ValueChain.tsx:10`
- Modify: `ui/src/__tests__/ValueChainContributionPanel.test.tsx:12`, `ui/src/__tests__/ValueChainTable.test.tsx:4`, `ui/src/__tests__/ValueChainEditing.test.tsx:6`, `ui/src/__tests__/ValueChainSave.test.tsx:13`

**Interfaces:**
- Produces: from `ui/src/utils/valueChainModel.ts` - types `ValueChainAttribution`, `ValueChainParty`, `ValueChainSegment`, `ValueChainActivity`, `ValueChainContribution`, `ValueChainTask`, `ValueChainProposition`, `ValueChainLink`, `ValueChainModel`, `ValueChainSelection`; constant `COLUMN_STEP = 10`; functions `columnRange(usedColumns: number[]): number[]`, `moveContribution(model, activityId, partyId, direction: 'left' | 'right'): ValueChainModel`, `updateDescription(model, activityId, partyId, description: string): ValueChainModel`.

This is a **pure move**. The bodies of `columnRange`, `moveContribution` and `updateDescription` are copied verbatim from `ValueChainTable.tsx` including their comments, which explain two defects already paid for on this branch and must not be lost. `ValueChainSelection` moves too - it currently lives at `ValueChainTable.tsx:151`.

- [ ] **Step 1: Write the failing tests**

These operations are currently tested only through the rendered table. Direct unit tests are what let Task 2 add siblings without mounting anything.

Create `ui/src/__tests__/valueChainModel.test.ts`:

```ts
// ui/src/__tests__/valueChainModel.test.ts
import { describe, it, expect } from 'vitest'

import {
  COLUMN_STEP,
  columnRange,
  moveContribution,
  updateDescription,
  type ValueChainModel,
} from '../utils/valueChainModel'

function model(): ValueChainModel {
  return {
    model_version: 1,
    parties: [
      { id: 'sp', label: 'SP-GS', colour: '#1a5276' },
      { id: 'iss', label: 'ISS', colour: '#c0392b' },
    ],
    segments: [{ id: '1', label: 'Property Value Chain' }],
    activities: [
      { id: '1.1', segment_id: '1', label: 'Strategy' },
      { id: '1.2', segment_id: '1', label: 'Acquisition' },
      { id: '1.3', segment_id: '1', label: 'Delivery' },
    ],
    contributions: [
      { activity_id: '1.1', party_id: 'sp', column: 10, description: 'first', attribution: 'stated' },
      { activity_id: '1.2', party_id: 'sp', column: 20, description: 'second', attribution: 'stated' },
      { activity_id: '1.3', party_id: 'sp', column: 30, description: 'third', attribution: 'derived' },
    ],
    tasks: [],
    propositions: [],
    links: [],
  }
}

describe('columnRange', () => {
  it('is empty for no columns', () => {
    expect(columnRange([])).toEqual([])
  })

  it('fills whole steps between occupied columns so a gap stays visible', () => {
    expect(columnRange([10, 30])).toEqual([10, 20, 30])
  })

  it('includes a column that is not a multiple of the step', () => {
    // Sparse columns exist so an insert between neighbours picks an intermediate value.
    // An implementation generating min, min+10, min+20... drops 15 entirely.
    expect(columnRange([10, 15, 20])).toEqual([10, 15, 20])
  })

  it('deduplicates and sorts, so lane order in the model does not matter', () => {
    expect(columnRange([30, 10, 30])).toEqual([10, 20, 30])
  })
})

describe('moveContribution', () => {
  it('does not mutate the model it was given', () => {
    const before = model()
    const snapshot = structuredClone(before)
    moveContribution(before, '1.1', 'sp', 'right')
    expect(before).toEqual(snapshot)
  })

  it('exchanges columns with an occupant and changes nothing else on either side', () => {
    const next = moveContribution(model(), '1.1', 'sp', 'right')
    const moved = next.contributions.find((c) => c.activity_id === '1.1')!
    const swapped = next.contributions.find((c) => c.activity_id === '1.2')!
    expect(moved).toEqual({ ...model().contributions[0], column: 20 })
    expect(swapped).toEqual({ ...model().contributions[1], column: 10 })
  })

  it('never collides two contributions in a three-column lane moving right', () => {
    // A two-column fixture cannot discriminate the correct behaviour from the leapfrog
    // arithmetic that shipped first on this branch: with columns 10 and 20 both produce 30.
    const next = moveContribution(model(), '1.1', 'sp', 'right')
    const columns = next.contributions.map((c) => c.column)
    expect(new Set(columns).size).toBe(columns.length)
    expect(columns.sort((a, b) => a - b)).toEqual([10, 20, 30])
  })

  it('never collides two contributions in a three-column lane moving left', () => {
    const next = moveContribution(model(), '1.3', 'sp', 'left')
    const columns = next.contributions.map((c) => c.column)
    expect(new Set(columns).size).toBe(columns.length)
    expect(columns.sort((a, b) => a - b)).toEqual([10, 20, 30])
  })

  it('steps into an empty column rather than leapfrogging to the next occupied one', () => {
    const m = model()
    m.contributions = [
      { activity_id: '1.1', party_id: 'sp', column: 10, attribution: 'stated' },
      { activity_id: '1.3', party_id: 'sp', column: 30, attribution: 'stated' },
    ]
    const next = moveContribution(m, '1.1', 'sp', 'right')
    expect(next.contributions.find((c) => c.activity_id === '1.1')!.column).toBe(20)
  })

  it('ignores an occupant in another party lane', () => {
    const m = model()
    m.contributions.push({
      activity_id: '1.2', party_id: 'iss', column: 20, attribution: 'stated',
    })
    const next = moveContribution(m, '1.1', 'sp', 'right')
    expect(next.contributions.find((c) => c.activity_id === '1.2' && c.party_id === 'iss')!.column).toBe(20)
  })
})

describe('updateDescription', () => {
  it('changes only the named contribution and does not mutate the input', () => {
    const before = model()
    const snapshot = structuredClone(before)
    const next = updateDescription(before, '1.2', 'sp', 'revised')
    expect(before).toEqual(snapshot)
    expect(next.contributions.find((c) => c.activity_id === '1.2')!.description).toBe('revised')
    expect(next.contributions.find((c) => c.activity_id === '1.1')!.description).toBe('first')
  })

  it('never promotes a derived attribution to stated', () => {
    // The distinction feeds stakeholder allocation and interview design later, so a
    // migration guess must not silently harden into a fact by being edited.
    const next = updateDescription(model(), '1.3', 'sp', 'revised')
    expect(next.contributions.find((c) => c.activity_id === '1.3')!.attribution).toBe('derived')
  })
})

describe('COLUMN_STEP', () => {
  it('is ten, matching the backend', () => {
    expect(COLUMN_STEP).toBe(10)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/valueChainModel.test.ts`
Expected: FAIL - `Failed to resolve import "../utils/valueChainModel"`.

- [ ] **Step 3: Create the module**

Create `ui/src/utils/valueChainModel.ts`. Move lines 4-64 (the type declarations), line 66 (`COLUMN_STEP`), lines 68-92 (`columnRange` with its comment), lines 94-135 (`moveContribution` with its comment), lines 137-149 (`updateDescription`) and lines 151-154 (`ValueChainSelection`) out of `ui/src/components/ValueChainTable.tsx` and into it, unchanged. Export `COLUMN_STEP`, `columnRange`, `moveContribution` and `updateDescription` - they are currently module-private.

Start the file with:

```ts
// ui/src/utils/valueChainModel.ts
// The value chain model and every pure operation on it. No React import: the operations are
// what the views are built from, and keeping them here means they can be tested without
// rendering anything, and that deleting a view does not move the types.
```

- [ ] **Step 4: Point every importer at the new module**

In `ui/src/components/ValueChainTable.tsx`, replace the removed declarations with:

```ts
import {
  COLUMN_STEP,
  columnRange,
  moveContribution,
  updateDescription,
  type ValueChainModel,
  type ValueChainSelection,
} from '../utils/valueChainModel'
```

Re-export the types so the six existing importers keep compiling in this task:

```ts
// Re-exported for now: Task 5 deletes this component, and every importer moves to
// utils/valueChainModel then. Re-exporting here keeps this task a pure move with no
// behaviour change and no churn in files it does not otherwise touch.
export type { ValueChainModel, ValueChainSelection } from '../utils/valueChainModel'
```

`COLUMN_STEP` is unused in the component after the move if `columnRange` and `moveContribution` both left - remove it from the import if `tsc` reports it unused.

- [ ] **Step 5: Run the full frontend suite and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: 112 existing + 15 new = **127 passing**, `tsc` clean. No existing test changes behaviour - this task moves code without altering it.

- [ ] **Step 6: Commit**

```bash
git add ui/src/utils/valueChainModel.ts ui/src/__tests__/valueChainModel.test.ts ui/src/components/ValueChainTable.tsx
git commit -m "refactor: move the value chain model and its operations out of the table component"
```

---

## Task 2: The new pure operations

**Files:**
- Modify: `ui/src/utils/valueChainModel.ts`
- Modify: `ui/src/__tests__/valueChainModel.test.ts`

**Interfaces:**
- Consumes: everything Task 1 produced.
- Produces: `addParty(model, activityId, partyId): ValueChainModel`, `removeParty(model, activityId, partyId): ValueChainModel`, `confirmAttribution(model, activityId, partyId): ValueChainModel`, `contributionKey(activityId: string, partyId: string): string`, `taskCount(model, activityId, partyId): number`, `propositionCount(model, activityId): number`, `partiesNotContributing(model, activityId): ValueChainParty[]`, `isLastContribution(model, activityId): boolean`.

No UI in this task. The operations are correct before anything renders them.

- [ ] **Step 1: Write the failing tests**

Append to `ui/src/__tests__/valueChainModel.test.ts`:

```ts
import {
  addParty,
  removeParty,
  confirmAttribution,
  contributionKey,
  taskCount,
  propositionCount,
  partiesNotContributing,
  isLastContribution,
} from '../utils/valueChainModel'

function jointModel(): ValueChainModel {
  const m = model()
  m.tasks = [
    { activity_id: '1.2', party_id: 'sp', id: '1.2.1', label: 'Raise works order' },
    { activity_id: '1.2', party_id: 'sp', id: '1.2.2', label: 'Approve spend' },
  ]
  m.propositions = [{ id: 'p1', activity_id: '1.2', description: 'Paperless works orders' }]
  return m
}

describe('contributionKey', () => {
  it('is the composite identity, not a new ID space', () => {
    expect(contributionKey('1.1.2', 'sp')).toBe('1.1.2@sp')
  })
})

describe('addParty', () => {
  it('adds a contribution at the same column, because same column means concurrent', () => {
    const next = addParty(model(), '1.2', 'iss')
    const added = next.contributions.find((c) => c.activity_id === '1.2' && c.party_id === 'iss')!
    expect(added.column).toBe(20)
  })

  it('marks a human-created contribution stated, never derived', () => {
    // Only migration produces derived. A person attributing an activity is stating it.
    const next = addParty(model(), '1.2', 'iss')
    expect(next.contributions.find((c) => c.party_id === 'iss')!.attribution).toBe('stated')
  })

  it('leaves the existing contribution untouched', () => {
    const next = addParty(model(), '1.2', 'iss')
    expect(next.contributions.find((c) => c.activity_id === '1.2' && c.party_id === 'sp')).toEqual(
      model().contributions[1],
    )
  })

  it('does nothing when that party already contributes', () => {
    const next = addParty(model(), '1.2', 'sp')
    expect(next.contributions.filter((c) => c.activity_id === '1.2')).toHaveLength(1)
  })

  it('does not mutate the model it was given', () => {
    const before = model()
    const snapshot = structuredClone(before)
    addParty(before, '1.2', 'iss')
    expect(before).toEqual(snapshot)
  })
})

describe('removeParty', () => {
  it('removes the contribution and its tasks together', () => {
    // validate_model rejects a task whose contribution does not exist, so leaving the tasks
    // behind would turn into a 422 discovered long after the decision was made.
    const next = removeParty(jointModel(), '1.2', 'sp')
    expect(next.contributions.filter((c) => c.activity_id === '1.2')).toHaveLength(0)
    expect(next.tasks.filter((t) => t.activity_id === '1.2' && t.party_id === 'sp')).toHaveLength(0)
  })

  it('leaves another party's tasks on the same activity alone', () => {
    const m = jointModel()
    m.contributions.push({ activity_id: '1.2', party_id: 'iss', column: 20, attribution: 'stated' })
    m.tasks.push({ activity_id: '1.2', party_id: 'iss', id: '1.2.7', label: 'Execute repair' })
    const next = removeParty(m, '1.2', 'sp')
    expect(next.tasks.map((t) => t.id)).toEqual(['1.2.7'])
  })

  it('leaves the activity's propositions alone, because they attach to the activity', () => {
    const m = jointModel()
    m.contributions.push({ activity_id: '1.2', party_id: 'iss', column: 20, attribution: 'stated' })
    const next = removeParty(m, '1.2', 'sp')
    expect(next.propositions).toHaveLength(1)
  })

  it('does not mutate the model it was given', () => {
    const before = jointModel()
    const snapshot = structuredClone(before)
    removeParty(before, '1.2', 'sp')
    expect(before).toEqual(snapshot)
  })
})

describe('isLastContribution', () => {
  it('is true when the activity has exactly one contribution', () => {
    expect(isLastContribution(model(), '1.2')).toBe(true)
  })

  it('is false when two parties contribute', () => {
    expect(isLastContribution(addParty(model(), '1.2', 'iss'), '1.2')).toBe(false)
  })
})

describe('confirmAttribution', () => {
  it('promotes derived to stated', () => {
    const next = confirmAttribution(model(), '1.3', 'sp')
    expect(next.contributions.find((c) => c.activity_id === '1.3')!.attribution).toBe('stated')
  })

  it('changes nothing else on the contribution', () => {
    const next = confirmAttribution(model(), '1.3', 'sp')
    expect(next.contributions.find((c) => c.activity_id === '1.3')).toEqual({
      ...model().contributions[2],
      attribution: 'stated',
    })
  })

  it('does not mutate the model it was given', () => {
    const before = model()
    const snapshot = structuredClone(before)
    confirmAttribution(before, '1.3', 'sp')
    expect(before).toEqual(snapshot)
  })
})

describe('counts and available parties', () => {
  it('counts only that contribution's tasks', () => {
    const m = jointModel()
    m.contributions.push({ activity_id: '1.2', party_id: 'iss', column: 20, attribution: 'stated' })
    m.tasks.push({ activity_id: '1.2', party_id: 'iss', id: '1.2.7' })
    expect(taskCount(m, '1.2', 'sp')).toBe(2)
    expect(taskCount(m, '1.2', 'iss')).toBe(1)
  })

  it('counts propositions per activity, shared across its parties', () => {
    expect(propositionCount(jointModel(), '1.2')).toBe(1)
    expect(propositionCount(jointModel(), '1.1')).toBe(0)
  })

  it('lists only parties not already contributing to that activity', () => {
    expect(partiesNotContributing(model(), '1.2').map((p) => p.id)).toEqual(['iss'])
    expect(partiesNotContributing(addParty(model(), '1.2', 'iss'), '1.2')).toEqual([])
  })
})
```

Note: the three test names containing an apostrophe (`another party's tasks`, `the activity's propositions`, `only that contribution's tasks`) must use double quotes for the string, e.g. `it("leaves another party's tasks on the same activity alone", ...)`. A single-quoted string breaks on the apostrophe.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/valueChainModel.test.ts`
Expected: FAIL - `addParty is not exported by ../utils/valueChainModel`.

- [ ] **Step 3: Implement the operations**

Append to `ui/src/utils/valueChainModel.ts`:

```ts
// A contribution's identity is the composite (activity_id, party_id) - deliberately not a
// new ID space needing its own never-reuse discipline. This is also the React key for a
// card: keying on column instead lets a move change which contribution sits behind a key,
// and React then reuses a dirty input against the wrong one.
export function contributionKey(activityId: string, partyId: string): string {
  return `${activityId}@${partyId}`
}

function find(model: ValueChainModel, activityId: string, partyId: string) {
  return model.contributions.find(
    (c) => c.activity_id === activityId && c.party_id === partyId,
  )
}

// Attributing a further party to an activity needs no new ID and does not touch the
// activity's own ID or its parentage. The new contribution takes the same column as an
// existing one, because two contributions of one activity in the same column mean the
// parties act concurrently - the reasonable default for "both of these parties do this".
// Dragging it aside afterwards turns it into a handoff.
export function addParty(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
): ValueChainModel {
  const next = structuredClone(model)
  if (find(next, activityId, partyId)) return next

  const sibling = next.contributions.find((c) => c.activity_id === activityId)
  next.contributions.push({
    activity_id: activityId,
    party_id: partyId,
    column: sibling ? sibling.column : COLUMN_STEP,
    description: '',
    // A person attributing an activity is stating it. Only migration produces 'derived'.
    attribution: 'stated',
  })
  return next
}

// Tasks are keyed (activity_id, party_id), so they belong to the contribution rather than
// to the activity. Removing the contribution without them leaves tasks that validate_model
// rejects - "task X belongs to contribution Y, which does not exist" - so they go together.
// Propositions attach to the activity and are left alone.
export function removeParty(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
): ValueChainModel {
  const next = structuredClone(model)
  next.contributions = next.contributions.filter(
    (c) => !(c.activity_id === activityId && c.party_id === partyId),
  )
  next.tasks = next.tasks.filter(
    (t) => !(t.activity_id === activityId && t.party_id === partyId),
  )
  return next
}

// An activity with no contribution appears in no lane, so it vanishes from the grid while
// remaining in model.activities, with no way to recover it. validate_model rejects that
// state; this is what lets the UI refuse before offering the action.
export function isLastContribution(model: ValueChainModel, activityId: string): boolean {
  return model.contributions.filter((c) => c.activity_id === activityId).length <= 1
}

// A derived attribution is the migration's guess. Someone checking the guess and saying so
// is the act that resolves it - without this the marker stays on forever and stops meaning
// anything. There is no reverse operation: nothing turns a stated attribution into a guess.
export function confirmAttribution(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
): ValueChainModel {
  const next = structuredClone(model)
  const contribution = find(next, activityId, partyId)
  if (contribution) contribution.attribution = 'stated'
  return next
}

export function taskCount(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
): number {
  return model.tasks.filter(
    (t) => t.activity_id === activityId && t.party_id === partyId,
  ).length
}

export function propositionCount(model: ValueChainModel, activityId: string): number {
  return model.propositions.filter((p) => p.activity_id === activityId).length
}

export function partiesNotContributing(
  model: ValueChainModel,
  activityId: string,
): ValueChainParty[] {
  const contributing = new Set(
    model.contributions.filter((c) => c.activity_id === activityId).map((c) => c.party_id),
  )
  return model.parties.filter((p) => !contributing.has(p.id))
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && npx vitest run src/__tests__/valueChainModel.test.ts && npx tsc --noEmit`
Expected: PASS, `tsc` clean.

- [ ] **Step 5: Run the full frontend suite**

Run: `cd ui && npx vitest run`
Expected: **148 passing** (127 + 21 new).

- [ ] **Step 6: Commit**

```bash
git add ui/src/utils/valueChainModel.ts ui/src/__tests__/valueChainModel.test.ts
git commit -m "feat: add party attribution, removal and attribution-confirming operations"
```

---

## Task 3: An activity must have at least one contribution

**Files:**
- Modify: `api/services/value_chain_model.py` - add the rule after the contributions loop
- Modify: `api/services/value_chain_migration.py` - give a childless activity a contribution
- Test: `tests/test_value_chain_model.py`, `tests/test_value_chain_migration.py`

**Interfaces:**
- Produces: no signature changes. `validate_model` reports one additional problem type.

**These two changes must ship together.** The rule alone breaks migration. Verified: a registry whose L2 has no L3 children produces that activity with **zero** contributions, because contributions are derived from task attribution. Adding the rule without the migration fix makes `POST /projects/{slug}/value-chain-model/migrate` return 422 for any project containing a childless activity. `sp-gs-am` has none, so real-data tests would pass while other projects silently broke.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_value_chain_model.py`:

```python
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
```

Add to `tests/test_value_chain_migration.py`:

```python
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
```

If `tests/test_value_chain_migration.py` already imports `migrate` and defines module-level `REGISTRY`/`MERMAID` constants, use the local fixtures above rather than those - these tests need a registry shaped specifically to have a childless activity, which the shared constants do not.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_value_chain_model.py::test_an_activity_with_no_contribution_is_a_problem tests/test_value_chain_migration.py::test_an_activity_with_no_tasks_still_gets_a_contribution -v`
Expected: both FAIL. The first because `validate_model` returns `[]`. The second with `len(childless) == 1` failing on `0`.

- [ ] **Step 3: Add the validation rule**

In `api/services/value_chain_model.py`, immediately after the `for contribution in model.get("contributions", []):` loop ends and before the `for task in ...` loop, add:

```python
    # An activity with no contribution belongs to no lane, so it disappears from the grid
    # while remaining in model["activities"] - and nothing in the UI can bring it back.
    # This became reachable when removing a party's contribution became possible.
    contributed_activity_ids = {activity_id for activity_id, _ in contribution_ids}
    for activity in model.get("activities", []):
        if activity.get("id") not in contributed_activity_ids:
            problems.append(
                f"activity {activity.get('id')} has no contribution - it would not appear "
                "in the grid and could not be recovered"
            )
```

- [ ] **Step 4: Give a childless activity a contribution in the migration**

In `api/services/value_chain_migration.py`, the contributions are built by this loop near the end of `migrate`:

```python
    columns = _columns_by_activity(model["activities"])
    for activity_id, party in sorted(stated_pairs | derived_pairs):
        model["contributions"].append({...})
```

Insert the new pass **immediately before** the `columns = _columns_by_activity(...)` line, adding the childless activities into `derived_pairs` rather than appending contributions directly. The existing loop then builds them like any other, so the column assignment and the `sorted()` ordering both come for free - and an existing test asserts a re-run is byte-identical, which a second append site placed after the loop would put at risk.

```python
    # An activity with no L3 children got no task, and contributions are built from task
    # attribution - so it got no contribution either, which validate_model now rejects
    # because such an activity appears in no lane and vanishes from the grid. The cascade
    # already answers "which party, when nothing states one" for an unmatched node; a
    # childless activity is the same question with no node at all, so it takes the same
    # answer, and lands in derived_pairs because nothing stated it.
    contributed = {activity_id for activity_id, _ in stated_pairs | derived_pairs}
    for activity in model["activities"]:
        if activity["id"] in contributed:
            continue
        party = _dominant(per_segment.get(activity["segment_id"], {})) or project_dominant
        if party is not None:
            # None means nothing in the project is attributed at all - a fresh project with
            # no diagram to recover from, where the tasks were dropped for the same reason.
            derived_pairs.add((activity["id"], party))
```

`per_segment`, `project_dominant` and `_dominant` are the module's existing identifiers, already in scope at that point - do not introduce a second cascade implementation, because two versions of a tie-break will eventually disagree.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_value_chain_model.py tests/test_value_chain_migration.py -v`
Expected: PASS, including the pre-existing idempotence and real-data tests.

- [ ] **Step 6: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: **737 passing** (732 + 5 new).

- [ ] **Step 7: Commit**

```bash
git add api/services/value_chain_model.py api/services/value_chain_migration.py tests/test_value_chain_model.py tests/test_value_chain_migration.py
git commit -m "feat: require every activity to have a contribution, and give childless activities one"
```

---

## Task 4: Extract the Structure tab

**Files:**
- Create: `ui/src/components/StructureTab.tsx`
- Modify: `ui/src/pages/ValueChain.tsx` - remove the model state and the `activeTab === 'structure'` block

**Interfaces:**
- Consumes: `valueChainApi` from `ui/src/api/endpoints.ts` (`get`, `save`, `migrate`); types from `ui/src/utils/valueChainModel`.
- Produces: `StructureTab({ slug }: { slug: string })`.

A **pure refactor** - no behaviour change, no test changes, no new tests. `ValueChain.tsx` is 692 lines holding three tabs; the grid adds drag state, modal state, a party menu and a confirmation dialog, which would push it past 850. Doing this before the grid exists makes Task 5's swap a small diff in a small file.

- [ ] **Step 1: Confirm the current suite is green, as the baseline this task must not move**

Run: `cd ui && npx vitest run`
Expected: **148 passing**. Record the number - this task must end on exactly the same one.

- [ ] **Step 2: Create the component and move the code**

Create `ui/src/components/StructureTab.tsx` and move into it, unchanged:

- `migrateMutation` (`ValueChain.tsx:149-155`)
- the model state: `editedModel`, `hasUnsavedChanges`, `changeSummary`, `saveProblems`, `selectedContribution` and the effect that seeds `editedModel` from the query (`:156-179`)
- `saveModelMutation` (`:181-201`)
- the `beforeunload` effect (`:203-209`)
- the entire `activeTab === 'structure' && (...)` JSX block (`:573` to its close), as the component's return value with the `activeTab` condition removed
- the model query itself (the `useQuery` for `valueChainApi.get`) and whatever `modelLoading` / `modelError` / `modelMissing` derive from it

Header comment:

```tsx
// ui/src/components/StructureTab.tsx
// The Structure tab: the value chain model, the edits held against it, and the controls
// that commit them. Lifted out of ValueChain.tsx, which holds three unrelated tabs and had
// grown past the point where one more feature could be added to it safely.
```

- [ ] **Step 3: Render it from the page**

In `ui/src/pages/ValueChain.tsx`, replace the removed block with:

```tsx
      {activeTab === 'structure' && <StructureTab slug={slug!} />}
```

and add `import { StructureTab } from '../components/StructureTab'`. Remove every import that is now unused - `tsc --noEmit` names them.

- [ ] **Step 4: Verify nothing changed**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: **148 passing** - the same number as Step 1, with no test file modified. `tsc` clean.

If a test fails, the move was not faithful. The likely cause is state that the Setup or Templates tab also reads, or the auto-switch effect keying on the model query. Do not adjust the test - find what moved that should not have.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/StructureTab.tsx ui/src/pages/ValueChain.tsx
git commit -m "refactor: extract the Structure tab from the value chain page"
```

---

## Task 5: The grid replaces the table

**Files:**
- Create: `ui/src/components/ValueChainGrid.tsx`
- Create: `ui/src/components/ContributionCard.tsx`
- Create: `ui/src/__tests__/ValueChainGrid.test.tsx`
- Modify: `ui/src/components/StructureTab.tsx` - render the grid
- Modify: `ui/src/components/ContributionPanel.tsx` - import types from `utils/valueChainModel`
- Modify: `ui/src/__tests__/ValueChainEditing.test.tsx`, `ui/src/__tests__/ValueChainContributionPanel.test.tsx`, `ui/src/__tests__/ValueChainSave.test.tsx` - import the grid and the types from their new homes
- Delete: `ui/src/components/ValueChainTable.tsx`
- Delete: `ui/src/__tests__/ValueChainTable.test.tsx` after transferring its assertions into `ValueChainGrid.test.tsx`

**Interfaces:**
- Consumes: everything from `ui/src/utils/valueChainModel`.
- Produces: `ValueChainGrid({ model, onChange, selected, onSelect })` with the same prop shape the table had, so `StructureTab` changes by one identifier; `ContributionCard({ model, activity, contribution, onChange, selected, onSelect })`.

**Feature parity in one task.** The grid arrives with description editing, arrow-button moves, the derived marker and selection already working, and the table goes in the same commit. Splitting rendering from editing would leave the application without an editor for a task, and would leave a component nothing imports - the failure this branch has already had twice.

Drag arrives in Task 6. The arrow buttons stay permanently: they are how the grid is operated without a mouse.

- [ ] **Step 1: Write the failing tests**

Create `ui/src/__tests__/ValueChainGrid.test.tsx`. The first four tests transfer from `ValueChainTable.test.tsx`; the rest are new to the grid.

```tsx
// ui/src/__tests__/ValueChainGrid.test.tsx
import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect } from 'vitest'

import { ValueChainGrid } from '../components/ValueChainGrid'
import type { ValueChainModel } from '../utils/valueChainModel'

const MODEL: ValueChainModel = {
  model_version: 1,
  parties: [
    { id: 'sp', label: 'SP-GS', colour: '#1a5276' },
    { id: 'iss', label: 'ISS', colour: '#c0392b' },
  ],
  segments: [{ id: '1', label: 'Property Value Chain' }],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Strategy' },
    { id: '1.2', segment_id: '1', label: 'Acquisition' },
    { id: '1.5', segment_id: '1', label: 'Reactive Repair' },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: 'first', attribution: 'stated' },
    { activity_id: '1.2', party_id: 'sp', column: 20, description: 'second', attribution: 'stated' },
    { activity_id: '1.5', party_id: 'iss', column: 40, description: 'partner', attribution: 'derived' },
  ],
  tasks: [
    { activity_id: '1.1', party_id: 'sp', id: '1.1.1', label: 'Set strategy' },
    { activity_id: '1.1', party_id: 'sp', id: '1.1.2', label: 'Agree budget' },
  ],
  propositions: [{ id: 'p1', activity_id: '1.1', description: 'Paperless' }],
  links: [],
}

// The page owns the model; the grid reports changes upwards. Tests that edit must mirror
// that, or they assert against a prop that never updates.
function Stateful({ initial = MODEL }: { initial?: ValueChainModel }) {
  const [model, setModel] = useState(initial)
  return <ValueChainGrid model={model} onChange={setModel} onSelect={() => {}} />
}

function fieldValue(activityId: string, partyId: string): string {
  return (screen.getByTestId(`description-${activityId}-${partyId}`) as HTMLInputElement).value
}

describe('ValueChainGrid layout', () => {
  it('names the segment in a left gutter, not as a heading', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('segment-gutter-1')).toHaveTextContent('Property Value Chain')
  })

  it('shows each lane's party and its contribution count for the segment', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('lane-sp')).toHaveTextContent('SP-GS')
    expect(screen.getByTestId('lane-count-sp')).toHaveTextContent('2')
    expect(screen.getByTestId('lane-count-iss')).toHaveTextContent('1')
  })

  it('labels every column with its position number, so a gap is legible as a position', () => {
    render(<ValueChainGrid model={MODEL} />)
    for (const column of [10, 20, 30, 40]) {
      expect(screen.getByTestId(`column-header-${column}`)).toHaveTextContent(String(column))
    }
  })

  it('renders an unoccupied column as an empty cell rather than collapsing it', () => {
    render(<ValueChainGrid model={MODEL} />)
    // Column 30 is occupied by nobody: SP-GS stops at 20 and ISS starts at 40. It must
    // still exist in both lanes, because the gap is what shows the handoff.
    expect(screen.getByTestId('cell-sp-30')).toBeInTheDocument()
    expect(screen.getByTestId('cell-sp-30')).toHaveTextContent('')
    expect(screen.getByTestId('cell-iss-30')).toBeInTheDocument()
  })

  it('renders a column that is not a multiple of ten', () => {
    // Sparse columns exist so an insert picks an intermediate value. An implementation
    // generating min, min+10, min+20... hides 15 entirely - it happened on this branch.
    const model = structuredClone(MODEL)
    model.contributions.push({
      activity_id: '1.2', party_id: 'iss', column: 15, attribution: 'stated',
    })
    render(<ValueChainGrid model={model} />)
    expect(screen.getByTestId('cell-iss-15')).toBeInTheDocument()
    expect(screen.getByTestId('card-1.2-iss')).toBeInTheDocument()
  })

  it('shows an empty state when nothing has been mapped', () => {
    const empty: ValueChainModel = { ...MODEL, segments: [], activities: [], contributions: [] }
    render(<ValueChainGrid model={empty} />)
    expect(screen.getByTestId('value-chain-empty')).toBeInTheDocument()
  })
})

describe('ContributionCard content', () => {
  it('shows the activity ID and label', () => {
    render(<ValueChainGrid model={MODEL} />)
    const card = screen.getByTestId('card-1.1-sp')
    expect(card).toHaveTextContent('1.1')
    expect(card).toHaveTextContent('Strategy')
  })

  it('shows the task and proposition counts, including a zero', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('task-count-1.1-sp')).toHaveTextContent('2')
    expect(screen.getByTestId('proposition-count-1.1')).toHaveTextContent('1')
    // A zero is information: it says this activity has no propositions recorded.
    expect(screen.getByTestId('task-count-1.2-sp')).toHaveTextContent('0')
  })

  it('marks a derived attribution and leaves a stated one unmarked', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('derived-1.5-iss')).toBeInTheDocument()
    expect(screen.queryByTestId('derived-1.1-sp')).not.toBeInTheDocument()
  })
})

describe('ValueChainGrid editing', () => {
  it('reports an edited description without mutating the model it was given', async () => {
    const original = structuredClone(MODEL)
    render(<Stateful />)
    await userEvent.type(screen.getByTestId('description-1.1-sp'), '!')
    expect(MODEL).toEqual(original)
    expect(fieldValue('1.1', 'sp')).toBe('first!')
  })

  it('keeps descriptions with the right activities after a move', async () => {
    // The defect this guards: cards keyed by column meant a move changed which
    // contribution sat behind a key, React reused the input node, and the field showed the
    // wrong activity's text while the next keystroke overwrote another's description.
    render(<Stateful />)
    await userEvent.clear(screen.getByTestId('description-1.1-sp'))
    await userEvent.type(screen.getByTestId('description-1.1-sp'), 'revised')
    await userEvent.click(screen.getByTestId('move-right-1.1-sp'))

    expect(fieldValue('1.1', 'sp')).toBe('revised')
    expect(fieldValue('1.2', 'sp')).toBe('second')
  })

  it('does not overwrite a neighbour's description with the next keystroke after a move', async () => {
    render(<Stateful />)
    await userEvent.clear(screen.getByTestId('description-1.1-sp'))
    await userEvent.type(screen.getByTestId('description-1.1-sp'), 'revised')
    await userEvent.click(screen.getByTestId('move-right-1.1-sp'))
    await userEvent.type(screen.getByTestId('description-1.2-sp'), 'X')

    expect(fieldValue('1.2', 'sp')).toBe('secondX')
    expect(fieldValue('1.1', 'sp')).toBe('revised')
  })

  it('moving a contribution changes only its column', async () => {
    let latest: ValueChainModel = MODEL
    function Capture() {
      const [model, setModel] = useState(MODEL)
      latest = model
      return <ValueChainGrid model={model} onChange={setModel} />
    }
    render(<Capture />)
    await userEvent.click(screen.getByTestId('move-right-1.1-sp'))

    const moved = latest.contributions.find((c) => c.activity_id === '1.1')!
    expect(moved).toEqual({ ...MODEL.contributions[0], column: 20 })
  })

  it('typing in a description does not move the card', async () => {
    // The move handler is on the card header, never on the card container - a handler above
    // a text input swallows keystrokes typed into it.
    render(<Stateful />)
    const field = screen.getByTestId('description-1.1-sp')
    await userEvent.click(field)
    await userEvent.keyboard('{ArrowRight}{ArrowRight}')
    expect(screen.getByTestId('cell-sp-10')).toContainElement(screen.getByTestId('card-1.1-sp'))
  })

  it('is read-only when no onChange is given', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.queryByTestId('move-right-1.1-sp')).not.toBeInTheDocument()
    expect(screen.getByTestId('description-1.1-sp')).toHaveAttribute('readonly')
  })
})
```

Test names containing an apostrophe must use double-quoted strings.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ValueChainGrid.test.tsx`
Expected: FAIL - `Failed to resolve import "../components/ValueChainGrid"`.

- [ ] **Step 3: Create the card**

Create `ui/src/components/ContributionCard.tsx`:

```tsx
// ui/src/components/ContributionCard.tsx
// One party's contribution to one activity, as a card. Three sibling controls, never
// nested: the header (focus, move, open), the description input, and - from Task 8 - the
// party menu. A handler on the card itself would fire on every interaction with any of
// them, and one placed above the input would swallow keystrokes typed into it.
import { ChevronLeft, ChevronRight, ListTree, Lightbulb, Sparkles } from 'lucide-react'

import {
  moveContribution,
  propositionCount,
  taskCount,
  updateDescription,
  type ValueChainActivity,
  type ValueChainContribution,
  type ValueChainModel,
} from '../utils/valueChainModel'

export function ContributionCard({
  model,
  activity,
  contribution,
  onChange,
  selected,
  onSelect,
}: {
  model: ValueChainModel
  activity: ValueChainActivity
  contribution: ValueChainContribution
  onChange?: (model: ValueChainModel) => void
  selected?: boolean
  onSelect?: (activityId: string, partyId: string) => void
}) {
  const { activity_id: activityId, party_id: partyId } = contribution
  const editable = !!onChange

  return (
    <div
      data-testid={`card-${activityId}-${partyId}`}
      className={`bg-surface-card rounded-lg p-3 border ${
        selected ? 'border-brand' : 'border-transparent'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          data-testid={`card-header-${activityId}-${partyId}`}
          onClick={() => onSelect?.(activityId, partyId)}
          onKeyDown={(e) => {
            if (!editable) return
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
              e.preventDefault()
              onChange!(
                moveContribution(model, activityId, partyId, e.key === 'ArrowLeft' ? 'left' : 'right'),
              )
            }
          }}
          className="text-left flex-1"
        >
          <span className="block text-xs font-mono text-muted">{activityId}</span>
          <span className="block text-sm font-medium text-primary">{activity.label}</span>
        </button>

        {contribution.attribution === 'derived' && (
          <span
            data-testid={`derived-${activityId}-${partyId}`}
            title="Attributed by inference during migration, not stated in the source"
            className="flex items-center gap-1 text-xs text-secondary shrink-0"
          >
            <Sparkles className="w-3 h-3" aria-hidden="true" />
            Derived
          </span>
        )}
      </div>

      <input
        type="text"
        data-testid={`description-${activityId}-${partyId}`}
        // Controlled, never defaultValue. Cards key on the contribution's identity so a
        // move cannot put a different contribution behind an existing input node, and this
        // is the second defence on the same defect - it silently corrupted saved data.
        value={contribution.description ?? ''}
        readOnly={!editable}
        placeholder={editable ? 'Describe this contribution' : ''}
        onChange={(e) =>
          onChange?.(updateDescription(model, activityId, partyId, e.target.value))
        }
        className="mt-2 w-full bg-surface rounded px-2 py-1 text-xs text-secondary"
      />

      <div className="mt-2 flex items-center gap-3 text-xs text-muted">
        <span data-testid={`task-count-${activityId}-${partyId}`} className="flex items-center gap-1">
          <ListTree className="w-3 h-3" aria-hidden="true" />
          {taskCount(model, activityId, partyId)}
        </span>
        <span data-testid={`proposition-count-${activityId}`} className="flex items-center gap-1">
          <Lightbulb className="w-3 h-3" aria-hidden="true" />
          {propositionCount(model, activityId)}
        </span>

        {editable && (
          <span className="ml-auto flex items-center gap-1">
            <button
              type="button"
              data-testid={`move-left-${activityId}-${partyId}`}
              aria-label={`Move ${activity.label} left`}
              onClick={() => onChange!(moveContribution(model, activityId, partyId, 'left'))}
              className="text-secondary hover:text-brand"
            >
              <ChevronLeft className="w-4 h-4" aria-hidden="true" />
            </button>
            <button
              type="button"
              data-testid={`move-right-${activityId}-${partyId}`}
              aria-label={`Move ${activity.label} right`}
              onClick={() => onChange!(moveContribution(model, activityId, partyId, 'right'))}
              className="text-secondary hover:text-brand"
            >
              <ChevronRight className="w-4 h-4" aria-hidden="true" />
            </button>
          </span>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Create the grid**

Create `ui/src/components/ValueChainGrid.tsx`:

```tsx
// ui/src/components/ValueChainGrid.tsx
// One CSS Grid per segment: rows are party lanes, columns are the segment's sparse column
// positions, and a card sits at an explicit gridColumn/gridRow.
//
// The layout mechanism is the point. Snapping needs no implementation because a grid cell
// is the only place a card can be - there are no arbitrary coordinates to snap from, and
// nothing "between" two lanes to drop into. A free canvas has to be taught what a lane is,
// which is where the previous React Flow attempt spent its time.
//
// Every cell renders whether occupied or not, so a gap is a real position - and, from Task
// 6, a real drop target - rather than an absence.
import {
  columnRange,
  contributionKey,
  type ValueChainModel,
  type ValueChainSelection,
} from '../utils/valueChainModel'
import { ContributionCard } from './ContributionCard'

const GUTTER = '10rem'
const COLUMN_WIDTH = '13rem'

export function ValueChainGrid({
  model,
  onChange,
  selected,
  onSelect,
}: {
  model: ValueChainModel
  onChange?: (model: ValueChainModel) => void
  selected?: ValueChainSelection | null
  onSelect?: (activityId: string, partyId: string) => void
}) {
  if (model.segments.length === 0) {
    return (
      <div data-testid="value-chain-empty" className="bg-surface-card rounded-xl p-8 text-center">
        <p className="text-muted text-sm">No value chain has been mapped yet.</p>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {model.segments.map((segment) => {
        const activityIds = new Set(
          model.activities.filter((a) => a.segment_id === segment.id).map((a) => a.id),
        )
        const segmentContributions = model.contributions.filter((c) =>
          activityIds.has(c.activity_id),
        )
        const laneIds = Array.from(new Set(segmentContributions.map((c) => c.party_id)))
        const lanes = model.parties.filter((p) => laneIds.includes(p.id))
        const columns = columnRange(segmentContributions.map((c) => c.column))

        if (lanes.length === 0 || columns.length === 0) {
          return (
            <section key={segment.id} data-testid={`grid-segment-${segment.id}`}>
              <div data-testid={`segment-gutter-${segment.id}`} className="text-sm font-medium text-secondary uppercase tracking-wide">
                {segment.label}
              </div>
              <p className="text-muted text-sm italic mt-2">
                No activity has been mapped in this segment yet.
              </p>
            </section>
          )
        }

        return (
          <section key={segment.id} data-testid={`grid-segment-${segment.id}`} className="overflow-x-auto">
            <div
              className="grid gap-2 items-start"
              style={{
                gridTemplateColumns: `${GUTTER} repeat(${columns.length}, minmax(${COLUMN_WIDTH}, 1fr))`,
              }}
            >
              {/* Header row: the gutter names the segment, then a label per column. The
                  numbers are the model's real column values, which is what makes a gap
                  legible as a position rather than as whitespace. */}
              <div
                data-testid={`segment-gutter-${segment.id}`}
                className="text-sm font-medium text-secondary uppercase tracking-wide self-end pb-2"
                style={{ gridColumn: 1, gridRow: 1 }}
              >
                {segment.label}
              </div>
              {columns.map((column, index) => (
                <div
                  key={column}
                  data-testid={`column-header-${column}`}
                  className="text-xs text-muted font-mono pb-2 border-b border-surface"
                  style={{ gridColumn: index + 2, gridRow: 1 }}
                >
                  {column}
                </div>
              ))}

              {lanes.map((party, laneIndex) => {
                const laneContributions = segmentContributions.filter(
                  (c) => c.party_id === party.id,
                )
                return [
                  <div
                    key={`lane-${party.id}`}
                    data-testid={`lane-${party.id}`}
                    className="flex items-center gap-2 text-sm font-medium text-primary py-2"
                    style={{ gridColumn: 1, gridRow: laneIndex + 2 }}
                  >
                    {party.colour && (
                      <span
                        aria-hidden="true"
                        className="inline-block w-2 h-2 rounded-full shrink-0"
                        style={{ backgroundColor: party.colour }}
                      />
                    )}
                    <span>{party.label}</span>
                    <span data-testid={`lane-count-${party.id}`} className="text-muted text-xs">
                      {laneContributions.length}
                    </span>
                  </div>,
                  ...columns.map((column, index) => {
                    const contribution = laneContributions.find((c) => c.column === column)
                    const activity = contribution
                      ? model.activities.find((a) => a.id === contribution.activity_id)
                      : undefined

                    return (
                      <div
                        key={`cell-${party.id}-${column}`}
                        data-testid={`cell-${party.id}-${column}`}
                        className="min-h-[5rem] rounded-lg border border-dashed border-surface"
                        style={{ gridColumn: index + 2, gridRow: laneIndex + 2 }}
                      >
                        {contribution && activity && (
                          // Keyed on the contribution's identity, never on the column. Key
                          // on column and a move changes which contribution sits behind a
                          // key, so React reuses a dirty input against the wrong one.
                          <ContributionCard
                            key={contributionKey(activity.id, party.id)}
                            model={model}
                            activity={activity}
                            contribution={contribution}
                            onChange={onChange}
                            onSelect={onSelect}
                            selected={
                              selected?.activityId === activity.id &&
                              selected?.partyId === party.id
                            }
                          />
                        )}
                      </div>
                    )
                  }),
                ]
              })}
            </div>
          </section>
        )
      })}
    </div>
  )
}
```

Note the empty-segment branch renders `segment-gutter-<id>` and the main branch does too. Only one renders per segment, so `getByTestId` stays unambiguous - do not render both.

- [ ] **Step 5: Render the grid from the Structure tab and delete the table**

In `ui/src/components/StructureTab.tsx`, replace `<ValueChainTable ... />` with `<ValueChainGrid ... />` and update the import. The props are identical, so nothing else changes.

In `ui/src/components/ContributionPanel.tsx:6`, change the type import to `from '../utils/valueChainModel'`.

Update the type imports in `ValueChainEditing.test.tsx`, `ValueChainContributionPanel.test.tsx` and `ValueChainSave.test.tsx` to `../utils/valueChainModel`, and in `ValueChainEditing.test.tsx` swap `ValueChainTable` for `ValueChainGrid`. Its assertions transfer unchanged - the test IDs are the same.

Then delete `ui/src/components/ValueChainTable.tsx` and `ui/src/__tests__/ValueChainTable.test.tsx`. Before deleting the test file, check each of its assertions is represented in `ValueChainGrid.test.tsx`; the layout, empty-state, derived-marking and gap tests above cover them. **Do not delete an assertion that has no counterpart** - move it across instead.

- [ ] **Step 6: Run the full suite and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: **154 passing**, `tsc` clean. That is 148, minus the 9 tests in the deleted `ValueChainTable.test.tsx`, plus the 15 in `ValueChainGrid.test.tsx`. `ValueChainEditing.test.tsx` keeps its count - only its imports change.

If your figure differs, reconcile it before committing rather than adjusting the expectation. **No test may be lost without its assertion appearing elsewhere**, and a count that came out lower than 154 is the signal that one was.

- [ ] **Step 7: Commit**

```bash
git add ui/src/components/ValueChainGrid.tsx ui/src/components/ContributionCard.tsx ui/src/components/StructureTab.tsx ui/src/components/ContributionPanel.tsx ui/src/__tests__/ValueChainGrid.test.tsx ui/src/__tests__/ValueChainEditing.test.tsx ui/src/__tests__/ValueChainContributionPanel.test.tsx ui/src/__tests__/ValueChainSave.test.tsx
git rm ui/src/components/ValueChainTable.tsx ui/src/__tests__/ValueChainTable.test.tsx
git commit -m "feat: show the value chain as a grid of cards, replacing the table"
```

---

## Task 6: Drag a card between columns

**Files:**
- Modify: `ui/src/components/ValueChainGrid.tsx` - cells become drop targets
- Modify: `ui/src/components/ContributionCard.tsx` - the header becomes the drag handle
- Modify: `ui/src/utils/valueChainModel.ts` - add `moveToColumn`
- Modify: `ui/src/__tests__/valueChainModel.test.ts`
- Create: `ui/src/__tests__/ValueChainDrag.test.tsx`

**Interfaces:**
- Produces: `moveToColumn(model, activityId, partyId, column: number): ValueChainModel`.

`moveContribution` steps one position. Dragging lands on an arbitrary column, so it needs its own operation with the same invariant: after any move, no two contributions of the same party in the same segment share a column.

**The established pattern in this codebase** is `ui/src/pages/Assignment.tsx:94-105` - `preventDefault()` in `onDragOver`, set `dropEffect`, read the payload with `e.dataTransfer.getData(key)`, and hold an `isDragOver` boolean for the visual cue. Follow it.

**jsdom has no `DataTransfer`** - verified. Tests must pass a stub as the event's `dataTransfer`; `fireEvent` merges it onto the synthetic event.

- [ ] **Step 1: Write the failing test for the operation**

Append to `ui/src/__tests__/valueChainModel.test.ts`:

```ts
import { moveToColumn } from '../utils/valueChainModel'

describe('moveToColumn', () => {
  it('takes an empty column', () => {
    const next = moveToColumn(model(), '1.1', 'sp', 40)
    expect(next.contributions.find((c) => c.activity_id === '1.1')!.column).toBe(40)
  })

  it('exchanges columns with an occupant, changing nothing else on either side', () => {
    const next = moveToColumn(model(), '1.1', 'sp', 30)
    expect(next.contributions.find((c) => c.activity_id === '1.1')).toEqual({
      ...model().contributions[0], column: 30,
    })
    expect(next.contributions.find((c) => c.activity_id === '1.3')).toEqual({
      ...model().contributions[2], column: 10,
    })
  })

  it('leaves every column in the lane distinct, wherever the card lands', () => {
    for (const target of [10, 20, 30, 40, 15]) {
      const columns = moveToColumn(model(), '1.1', 'sp', target).contributions.map((c) => c.column)
      expect(new Set(columns).size).toBe(columns.length)
    }
  })

  it('is a no-op when the card is already there', () => {
    expect(moveToColumn(model(), '1.1', 'sp', 10)).toEqual(model())
  })

  it('ignores an occupant in another party lane', () => {
    const m = model()
    m.contributions.push({ activity_id: '1.2', party_id: 'iss', column: 40, attribution: 'stated' })
    const next = moveToColumn(m, '1.1', 'sp', 40)
    expect(next.contributions.find((c) => c.party_id === 'iss')!.column).toBe(40)
  })

  it('does not mutate the model it was given', () => {
    const before = model()
    const snapshot = structuredClone(before)
    moveToColumn(before, '1.1', 'sp', 40)
    expect(before).toEqual(snapshot)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/valueChainModel.test.ts`
Expected: FAIL - `moveToColumn is not exported`.

- [ ] **Step 3: Implement `moveToColumn`**

Append to `ui/src/utils/valueChainModel.ts`:

```ts
// Dragging lands on an arbitrary column rather than the adjacent step, so this is its own
// operation - but it holds the same invariant as moveContribution: after any move, no two
// contributions of the same party within a segment share a column. If the target is taken,
// the two exchange columns; otherwise the mover simply takes it.
export function moveToColumn(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
  column: number,
): ValueChainModel {
  const next = structuredClone(model)
  const contribution = find(next, activityId, partyId)
  if (!contribution || contribution.column === column) return next

  const activity = next.activities.find((a) => a.id === activityId)
  const segmentActivityIds = new Set(
    next.activities.filter((a) => a.segment_id === activity?.segment_id).map((a) => a.id),
  )
  const occupant = next.contributions.find(
    (c) =>
      c.party_id === partyId &&
      segmentActivityIds.has(c.activity_id) &&
      c.activity_id !== activityId &&
      c.column === column,
  )

  if (occupant) occupant.column = contribution.column
  contribution.column = column
  return next
}
```

- [ ] **Step 4: Write the failing drag tests**

Create `ui/src/__tests__/ValueChainDrag.test.tsx`:

```tsx
// ui/src/__tests__/ValueChainDrag.test.tsx
import { useState } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import { ValueChainGrid } from '../components/ValueChainGrid'
import type { ValueChainModel } from '../utils/valueChainModel'

const MODEL: ValueChainModel = {
  model_version: 1,
  parties: [
    { id: 'sp', label: 'SP-GS' },
    { id: 'iss', label: 'ISS' },
  ],
  segments: [{ id: '1', label: 'Property Value Chain' }],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Strategy' },
    { id: '1.2', segment_id: '1', label: 'Acquisition' },
    { id: '1.5', segment_id: '1', label: 'Reactive Repair' },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: 'first', attribution: 'stated' },
    { activity_id: '1.2', party_id: 'sp', column: 20, description: 'second', attribution: 'stated' },
    { activity_id: '1.5', party_id: 'iss', column: 40, description: 'partner', attribution: 'derived' },
  ],
  tasks: [],
  propositions: [],
  links: [],
}

// jsdom implements no DataTransfer, so tests supply a stub. It has to behave like the real
// thing for the payload the component actually writes and reads, or the test proves nothing
// about the component's own use of it.
function dataTransfer() {
  const store = new Map<string, string>()
  return {
    setData: (key: string, value: string) => store.set(key, value),
    getData: (key: string) => store.get(key) ?? '',
    dropEffect: '',
    effectAllowed: '',
  }
}

function Stateful() {
  const [model, setModel] = useState(MODEL)
  return <ValueChainGrid model={model} onChange={setModel} />
}

function columnOf(testId: string): number | null {
  // Reads which cell currently contains the card, so assertions are on the rendered
  // position rather than on internal state.
  for (const cell of Array.from(document.querySelectorAll('[data-testid^="cell-"]'))) {
    if (cell.querySelector(`[data-testid="${testId}"]`)) {
      return Number(cell.getAttribute('data-testid')!.split('-').pop())
    }
  }
  return null
}

describe('dragging a card', () => {
  it('moves the card to an empty column in the same lane', () => {
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-sp-30'), { dataTransfer: dt })

    expect(columnOf('card-1.1-sp')).toBe(30)
  })

  it('exchanges columns when dropped on an occupied cell', () => {
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-sp-20'), { dataTransfer: dt })

    expect(columnOf('card-1.1-sp')).toBe(20)
    expect(columnOf('card-1.2-sp')).toBe(10)
  })

  it('refuses a drop into another party's lane', () => {
    // A contribution's identity is (activity, party). Dropping across lanes would not
    // reposition it - it would replace it with a different contribution and orphan its
    // tasks. Re-attribution is the party menu's job, explicitly.
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-iss-30'), { dataTransfer: dt })

    expect(columnOf('card-1.1-sp')).toBe(10)
    expect(screen.queryByTestId('card-1.1-iss')).not.toBeInTheDocument()
  })

  it('carries the description with the card rather than leaving it behind', () => {
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-sp-20'), { dataTransfer: dt })

    expect(
      (screen.getByTestId('description-1.1-sp') as HTMLInputElement).value,
    ).toBe('first')
    expect(
      (screen.getByTestId('description-1.2-sp') as HTMLInputElement).value,
    ).toBe('second')
  })

  it('does not make cards draggable when read-only', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('card-header-1.1-sp')).not.toHaveAttribute('draggable', 'true')
  })
})
```

- [ ] **Step 5: Run the drag tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ValueChainDrag.test.tsx`
Expected: FAIL - the first test finds `card-1.1-sp` still at column 10, because nothing handles the drop yet.

- [ ] **Step 6: Make the header a drag handle**

In `ContributionCard.tsx`, add to the header `<button>`:

```tsx
          draggable={editable}
          onDragStart={(e) => {
            // The payload carries the lane so the drop target can refuse a cross-lane drop
            // without needing any shared state.
            e.dataTransfer.setData('contributionActivityId', activityId)
            e.dataTransfer.setData('contributionPartyId', partyId)
            e.dataTransfer.effectAllowed = 'move'
          }}
```

- [ ] **Step 7: Make cells drop targets**

In `ValueChainGrid.tsx`, add to each cell `<div>`:

```tsx
                        onDragOver={
                          onChange
                            ? (e) => {
                                e.preventDefault()
                                e.dataTransfer.dropEffect = 'move'
                              }
                            : undefined
                        }
                        onDrop={
                          onChange
                            ? (e) => {
                                e.preventDefault()
                                const activityId = e.dataTransfer.getData('contributionActivityId')
                                const draggedParty = e.dataTransfer.getData('contributionPartyId')
                                // A card may only land in its own lane: a contribution's
                                // identity is (activity, party), so a cross-lane drop would
                                // change what it is rather than where it sits.
                                if (!activityId || draggedParty !== party.id) return
                                onChange(moveToColumn(model, activityId, party.id, column))
                              }
                            : undefined
                        }
```

Import `moveToColumn` from `../utils/valueChainModel`.

- [ ] **Step 8: Run both new files, then the full suite**

Run: `cd ui && npx vitest run src/__tests__/ValueChainDrag.test.tsx src/__tests__/valueChainModel.test.ts`
Expected: PASS.

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: all passing, `tsc` clean. Report the count.

- [ ] **Step 9: Commit**

```bash
git add ui/src/utils/valueChainModel.ts ui/src/components/ValueChainGrid.tsx ui/src/components/ContributionCard.tsx ui/src/__tests__/valueChainModel.test.ts ui/src/__tests__/ValueChainDrag.test.tsx
git commit -m "feat: drag a contribution card between columns within its lane"
```

---

## Task 7: The tasks and propositions pop-up

**Files:**
- Modify: `ui/src/components/ContributionPanel.tsx` - a modal rather than a side panel
- Modify: `ui/src/components/StructureTab.tsx` - render it as an overlay, dismissible
- Modify: `ui/src/__tests__/ValueChainContributionPanel.test.tsx`

**Interfaces:**
- Consumes: `ContributionPanelProps` as it stands - `{ model, activityId, partyId }`.
- Produces: `ContributionPanel` gains `onClose: () => void`.

The panel's filtering is already correct and tested: tasks by `(activity_id, party_id)`, propositions by `activity_id`. This task changes only its presentation and how it is dismissed. **Content stays read-only** - editing task and proposition text is out of scope.

- [ ] **Step 1: Write the failing tests**

Add to `ui/src/__tests__/ValueChainContributionPanel.test.tsx`:

```tsx
  it('opens as a dialog when a card header is activated', async () => {
    render(<Wrapper />)
    await userEvent.click(await screen.findByRole('button', { name: 'Structure' }))
    await userEvent.click(await screen.findByTestId('card-header-1.1-sp'))

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('Log the fault')
  })

  it('closes on the close control', async () => {
    render(<Wrapper />)
    await userEvent.click(await screen.findByRole('button', { name: 'Structure' }))
    await userEvent.click(await screen.findByTestId('card-header-1.1-sp'))
    await userEvent.click(screen.getByTestId('close-contribution-panel'))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    render(<Wrapper />)
    await userEvent.click(await screen.findByRole('button', { name: 'Structure' }))
    await userEvent.click(await screen.findByTestId('card-header-1.1-sp'))
    await userEvent.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows the tasks of the party whose card was opened, not the other party's', async () => {
    // Tasks belong to the contribution, so opening ISS's card on a jointly-delivered
    // activity must not show SP-GS's tasks.
    render(<Wrapper />)
    await userEvent.click(await screen.findByRole('button', { name: 'Structure' }))
    await userEvent.click(await screen.findByTestId('card-header-1.1-sp'))

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('Log the fault')
    expect(dialog).not.toHaveTextContent('Execute repair')
  })
```

The existing `Wrapper` in that file must have a model where activity `1.1` has an `sp` task labelled `Log the fault` and an `iss` task labelled `Execute repair`, with contributions for both parties. Extend the fixture if it does not - the last test cannot discriminate otherwise.

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ValueChainContributionPanel.test.tsx`
Expected: FAIL - `Unable to find an accessible element with the role "dialog"`.

- [ ] **Step 3: Make the panel a dialog**

In `ContributionPanel.tsx`, wrap the existing content and add the close control. Keep the filtering and the two empty states exactly as they are.

```tsx
export function ContributionPanel({
  model,
  activityId,
  partyId,
  onClose,
}: ContributionPanelProps & { onClose: () => void }) {
  // ... existing tasks / propositions filtering, unchanged ...

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${activityId} detail`}
        data-testid="contribution-panel"
        className="bg-surface-raised rounded-xl max-w-lg w-full max-h-[80vh] overflow-y-auto p-5"
        // The backdrop closes on click; the dialog itself must not, or every interaction
        // inside it would dismiss the thing being interacted with.
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          {/* ... existing heading ... */}
          <button
            type="button"
            data-testid="close-contribution-panel"
            aria-label="Close"
            onClick={onClose}
            className="text-secondary hover:text-primary shrink-0"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        {/* ... existing tasks and propositions sections, unchanged ... */}
      </div>
    </div>
  )
}
```

Import `X` from `lucide-react`.

- [ ] **Step 4: Wire Escape and conditional rendering in the Structure tab**

In `StructureTab.tsx`, render the panel only when a contribution is selected, and clear the selection to close:

```tsx
  useEffect(() => {
    if (!selectedContribution) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setSelectedContribution(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedContribution])
```

```tsx
      {selectedContribution && editedModel && (
        <ContributionPanel
          model={editedModel}
          activityId={selectedContribution.activityId}
          partyId={selectedContribution.partyId}
          onClose={() => setSelectedContribution(null)}
        />
      )}
```

The `contribution-panel-placeholder` the side panel used when nothing was selected no longer has a place - a modal that is not open renders nothing. Remove it, and remove or rewrite the test that asserts it; a placeholder test kept alive by rendering an invisible element would be a test of nothing.

- [ ] **Step 5: Run the suite and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: all passing, `tsc` clean. Report the count and name any test removed with the reason.

- [ ] **Step 6: Commit**

```bash
git add ui/src/components/ContributionPanel.tsx ui/src/components/StructureTab.tsx ui/src/__tests__/ValueChainContributionPanel.test.tsx
git commit -m "feat: show a contribution's tasks and propositions in a dialog"
```

---

## Task 8: Attribute an activity to another party

**Files:**
- Modify: `ui/src/components/ContributionCard.tsx` - the party menu and the Confirm control
- Modify: `ui/src/components/StructureTab.tsx` - the removal confirmation dialog
- Create: `ui/src/__tests__/ValueChainParties.test.tsx`

**Interfaces:**
- Consumes: `addParty`, `removeParty`, `confirmAttribution`, `partiesNotContributing`, `isLastContribution`, `taskCount` from `ui/src/utils/valueChainModel`.
- Produces: `ContributionCard` gains `onRequestRemove?: (activityId: string, partyId: string) => void`, so the confirmation dialog lives in the tab rather than inside every card.

This makes joint delivery reachable. No activity in the real data has more than one party, so this is the first way to create the case the contribution model exists for.

- [ ] **Step 1: Write the failing tests**

Create `ui/src/__tests__/ValueChainParties.test.tsx`:

```tsx
// ui/src/__tests__/ValueChainParties.test.tsx
import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect } from 'vitest'

import { ValueChainGrid } from '../components/ValueChainGrid'
import type { ValueChainModel } from '../utils/valueChainModel'

const MODEL: ValueChainModel = {
  model_version: 1,
  parties: [
    { id: 'sp', label: 'SP-GS' },
    { id: 'iss', label: 'ISS' },
    { id: 'dxi', label: 'DXI' },
  ],
  segments: [{ id: '1', label: 'Property Value Chain' }],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Strategy' },
    { id: '1.2', segment_id: '1', label: 'Reactive Maintenance' },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: 'first', attribution: 'stated' },
    { activity_id: '1.2', party_id: 'sp', column: 20, description: 'second', attribution: 'derived' },
  ],
  tasks: [
    { activity_id: '1.2', party_id: 'sp', id: '1.2.1', label: 'Raise works order' },
    { activity_id: '1.2', party_id: 'sp', id: '1.2.2', label: 'Approve spend' },
  ],
  propositions: [],
  links: [],
}

let latest: ValueChainModel = MODEL

function Stateful() {
  const [model, setModel] = useState(MODEL)
  latest = model
  return <ValueChainGrid model={model} onChange={setModel} />
}

describe('adding a party', () => {
  it('offers only parties not already contributing to that activity', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))

    expect(screen.getByTestId('add-party-1.2-sp-iss')).toBeInTheDocument()
    expect(screen.getByTestId('add-party-1.2-sp-dxi')).toBeInTheDocument()
    expect(screen.queryByTestId('add-party-1.2-sp-sp')).not.toBeInTheDocument()
  })

  it('puts the new contribution in the same column, meaning concurrent delivery', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('add-party-1.2-sp-iss'))

    expect(screen.getByTestId('cell-iss-20')).toContainElement(screen.getByTestId('card-1.2-iss'))
  })

  it('marks the new contribution stated, because a person stated it', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('add-party-1.2-sp-iss'))

    expect(screen.queryByTestId('derived-1.2-iss')).not.toBeInTheDocument()
    expect(
      latest.contributions.find((c) => c.activity_id === '1.2' && c.party_id === 'iss')!.attribution,
    ).toBe('stated')
  })
})

describe('confirming a derived attribution', () => {
  it('offers Confirm on a derived contribution only', () => {
    render(<Stateful />)
    expect(screen.getByTestId('confirm-attribution-1.2-sp')).toBeInTheDocument()
    expect(screen.queryByTestId('confirm-attribution-1.1-sp')).not.toBeInTheDocument()
  })

  it('promotes it to stated and removes both the marker and the control', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('confirm-attribution-1.2-sp'))

    expect(screen.queryByTestId('derived-1.2-sp')).not.toBeInTheDocument()
    expect(screen.queryByTestId('confirm-attribution-1.2-sp')).not.toBeInTheDocument()
    expect(
      latest.contributions.find((c) => c.activity_id === '1.2')!.attribution,
    ).toBe('stated')
  })
})

describe('removing a party', () => {
  it('refuses when it is the activity's only contribution, and says why', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.1-sp'))

    const remove = screen.getByTestId('remove-party-1.1-sp')
    expect(remove).toBeDisabled()
    expect(remove).toHaveAccessibleDescription(/only party|would disappear/i)
  })

  it('names how many tasks will be deleted before doing anything', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('add-party-1.2-sp-iss'))
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('remove-party-1.2-sp'))

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('2')
    expect(dialog).toHaveTextContent(/task/i)
  })

  it('removes the contribution and its tasks together on confirm', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('add-party-1.2-sp-iss'))
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('remove-party-1.2-sp'))
    await userEvent.click(screen.getByTestId('confirm-remove'))

    expect(screen.queryByTestId('card-1.2-sp')).not.toBeInTheDocument()
    expect(latest.tasks.filter((t) => t.party_id === 'sp')).toHaveLength(0)
    expect(latest.contributions.filter((c) => c.activity_id === '1.2')).toHaveLength(1)
  })

  it('changes nothing on cancel', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('add-party-1.2-sp-iss'))
    const afterAdd = structuredClone(latest)

    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('remove-party-1.2-sp'))
    await userEvent.click(screen.getByTestId('cancel-remove'))

    expect(latest).toEqual(afterAdd)
    expect(screen.getByTestId('card-1.2-sp')).toBeInTheDocument()
  })
})
```

The removal confirmation dialog is rendered by whichever component owns the grid in this test - the grid itself, since these tests mount `ValueChainGrid` directly. Put the dialog in `ValueChainGrid.tsx` rather than `StructureTab.tsx` so it is reachable from the component that raises the request; the `onRequestRemove` prop on the card is how the card asks for it.

Test names containing an apostrophe must use double-quoted strings.

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ValueChainParties.test.tsx`
Expected: FAIL - `Unable to find an element by: [data-testid="party-menu-1.2-sp"]`.

- [ ] **Step 3: Add the party menu and Confirm control to the card**

In `ContributionCard.tsx`, add local open state for the menu and render it as a third sibling. Add the props `onRequestRemove?: (activityId: string, partyId: string) => void`.

```tsx
  const [menuOpen, setMenuOpen] = useState(false)
  const available = partiesNotContributing(model, activityId)
  const lastOne = isLastContribution(model, activityId)
  const owned = taskCount(model, activityId, partyId)
```

Inside the card, after the counts row:

```tsx
      {editable && (
        <div className="mt-2 relative">
          <button
            type="button"
            data-testid={`party-menu-${activityId}-${partyId}`}
            aria-label={`Parties for ${activity.label}`}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
            className="flex items-center gap-1 text-xs text-secondary hover:text-brand"
          >
            <Users className="w-3 h-3" aria-hidden="true" />
            Parties
          </button>

          {menuOpen && (
            <div className="absolute z-10 mt-1 bg-surface-raised rounded-lg p-2 shadow-lg min-w-[12rem]">
              {available.length === 0 ? (
                <p className="text-muted text-xs italic px-1 py-1">
                  Every party already contributes to this activity.
                </p>
              ) : (
                available.map((party) => (
                  <button
                    key={party.id}
                    type="button"
                    data-testid={`add-party-${activityId}-${partyId}-${party.id}`}
                    onClick={() => {
                      onChange!(addParty(model, activityId, party.id))
                      setMenuOpen(false)
                    }}
                    className="block w-full text-left text-xs text-primary px-1 py-1 hover:text-brand"
                  >
                    Add {party.label}
                  </button>
                ))
              )}

              <button
                type="button"
                data-testid={`remove-party-${activityId}-${partyId}`}
                disabled={lastOne}
                aria-describedby={lastOne ? `remove-why-${activityId}-${partyId}` : undefined}
                onClick={() => {
                  onRequestRemove?.(activityId, partyId)
                  setMenuOpen(false)
                }}
                className="block w-full text-left text-xs px-1 py-1 mt-1 border-t border-surface text-red-400 disabled:text-muted"
              >
                Remove this party
              </button>
              {lastOne && (
                <p id={`remove-why-${activityId}-${partyId}`} className="text-muted text-xs px-1">
                  The only party on this activity - removing it would make the activity
                  disappear from the chain.
                </p>
              )}
            </div>
          )}
        </div>
      )}
```

And the Confirm control, beside the derived marker:

```tsx
        {contribution.attribution === 'derived' && editable && (
          <button
            type="button"
            data-testid={`confirm-attribution-${activityId}-${partyId}`}
            onClick={() => onChange!(confirmAttribution(model, activityId, partyId))}
            className="text-xs text-brand shrink-0"
          >
            Confirm
          </button>
        )}
```

Import `Users` from `lucide-react`, and `addParty`, `confirmAttribution`, `isLastContribution`, `partiesNotContributing` from `../utils/valueChainModel`. Add `useState` to the React import.

- [ ] **Step 4: Add the confirmation dialog to the grid**

In `ValueChainGrid.tsx`, hold the pending removal and render the dialog:

```tsx
  const [pendingRemoval, setPendingRemoval] = useState<{
    activityId: string
    partyId: string
  } | null>(null)
```

Pass `onRequestRemove={(activityId, partyId) => setPendingRemoval({ activityId, partyId })}` to each `ContributionCard`, and render at the end of the component:

```tsx
      {pendingRemoval && (() => {
        const activity = model.activities.find((a) => a.id === pendingRemoval.activityId)
        const party = model.parties.find((p) => p.id === pendingRemoval.partyId)
        const doomed = model.tasks.filter(
          (t) =>
            t.activity_id === pendingRemoval.activityId &&
            t.party_id === pendingRemoval.partyId,
        )
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div
              role="dialog"
              aria-modal="true"
              aria-label="Confirm removal"
              className="bg-surface-raised rounded-xl max-w-md w-full p-5"
            >
              <h3 className="text-sm font-medium text-primary">
                Remove {party?.label} from {activity?.label}?
              </h3>
              {/* Tasks belong to the contribution, so they go with it. Saying how many, and
                  which, is what makes this a decision rather than a surprise. */}
              {doomed.length > 0 && (
                <>
                  <p className="mt-2 text-xs text-secondary">
                    {party?.label} owns {doomed.length} task
                    {doomed.length === 1 ? '' : 's'} here. Removing the party deletes them.
                  </p>
                  <ul className="mt-2 text-xs text-muted space-y-1">
                    {doomed.map((task) => (
                      <li key={task.id}>
                        <span className="font-mono">{task.id}</span> {task.label ?? ''}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <p className="mt-3 text-xs text-muted">
                The saved version is unchanged until you save, so this can be reverted.
              </p>
              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  data-testid="cancel-remove"
                  onClick={() => setPendingRemoval(null)}
                  className="text-xs text-secondary px-3 py-1"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  data-testid="confirm-remove"
                  onClick={() => {
                    onChange!(
                      removeParty(model, pendingRemoval.activityId, pendingRemoval.partyId),
                    )
                    setPendingRemoval(null)
                  }}
                  className="text-xs bg-brand text-white rounded px-3 py-1"
                >
                  {doomed.length > 0
                    ? `Remove and delete ${doomed.length}`
                    : 'Remove'}
                </button>
              </div>
            </div>
          </div>
        )
      })()}
```

Import `useState` and `removeParty`.

- [ ] **Step 5: Run the new file, then the full suite**

Run: `cd ui && npx vitest run src/__tests__/ValueChainParties.test.tsx`
Expected: PASS.

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: all passing, `tsc` clean.

- [ ] **Step 6: Run the backend suite too, as this plan touched it in Task 3**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: **737 passing**.

- [ ] **Step 7: Commit**

```bash
git add ui/src/components/ContributionCard.tsx ui/src/components/ValueChainGrid.tsx ui/src/__tests__/ValueChainParties.test.tsx
git commit -m "feat: attribute an activity to another party, and confirm a derived attribution"
```

---

## Notes carried from the branch that built the model

Three defects on the SP22a branch cost fix rounds, and all three have counterparts here:

- **Fixtures too small to discriminate.** A single version file hid a lexical sort; a two-column lane hid a column collision. Every fixture in this plan is sized to its case - three columns for moves, three parties for the party menu, a non-multiple-of-ten column for the range, two parties for joint delivery. If a test passes on the first attempt without the implementation existing, the fixture is wrong.
- **Components nobody imports.** `ContributionPanel.tsx` shipped importable from nowhere and `ReviewQueue.tsx` held the only commit control in the product while being unreachable. Every task here wires its component in within the same task, and Task 5 explicitly forbids landing the grid without deleting the table.
- **Uncontrolled inputs behind changing keys.** `defaultValue` on a field inside a cell keyed by column showed the wrong contribution's text after a move and overwrote it on the next keystroke. This plan keys cards on `contributionKey(activity_id, party_id)` **and** controls the input.
