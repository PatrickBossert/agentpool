# Value Chain Card Legibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a value chain card readable - a visible edge, three lines of description, and its `n.n.n` activities listed rather than counted, each opening the existing detail dialog on itself.

**Architecture:** All five tasks are frontend-only and touch four files. Tasks 1 and 2 change `ContributionCard.tsx`; Task 2's new `onSelect` argument ripples through `ValueChainGrid.tsx` and `StructureTab.tsx` to `ContributionPanel.tsx`, which Task 3 changes. Tasks 4 and 5 are independent changes to `ValueChainGrid.tsx`. No backend, no API, no model change.

**Tech Stack:** React 18, TypeScript, Tailwind CSS v3, Vitest, Testing Library, Lucide React.

## Global Constraints

- British English (`-ise`, `-our`, `-re`) in comments, UI copy, and test names.
- Spaced hyphen ` - ` in prose, never an em dash `—`. Hyphenated compound adjectives are fine.
- Lucide React SVG icons only. **No emoji in rendered content.**
- Never `sky-*` or `blue-*` Tailwind classes. Brand tokens only: `text-brand`, `bg-brand`, `bg-surface`, `bg-surface-raised`, `bg-surface-card`, `text-primary`, `text-secondary`, `text-muted`. Amber is the codebase's warning convention.
- The description field is **strictly controlled** - `value`, never `defaultValue`. A `defaultValue` on a column-keyed input silently corrupted saved data on SP22a; this is a standing defence, not a preference.
- Cards are keyed on `contributionKey(activity.id, party.id)`, never on column or list index.
- Stable `Ln.n.n` IDs are never changed or reused.
- Never `git add -A` or `git add .` - the working tree holds unrelated untracked screenshots and `.docx` files. Stage by name.
- Tests: `npx vitest run` from `ui/`, and `npx tsc --noEmit` must be clean.
- **Baselines: frontend 265 passed, backend 794 passed / 2 skipped.** Backend must not move; run `./venv/bin/pytest -q --ignore=tests/integration` (NOT bare `pytest`) once at the end of the last task to confirm.

---

### Task 1: The card gains an edge and three lines of description

**Files:**
- Modify: `ui/src/components/ContributionCard.tsx:65-67` (border), `:120-133` (description field)
- Test: `ui/src/__tests__/ValueChainGrid.test.tsx`
- Modify (casts only): `ui/src/__tests__/ValueChainGrid.test.tsx:46`, `ui/src/__tests__/ValueChainEditing.test.tsx:82`, `ui/src/__tests__/ValueChainDrag.test.tsx:120,123`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing later tasks depend on. The `description-<activityId>-<partyId>` test id is unchanged; only the element type changes from `input` to `textarea`.

- [ ] **Step 1: Write the failing tests**

Add to `ui/src/__tests__/ValueChainGrid.test.tsx`, inside the existing `describe('ValueChainGrid layout', ...)` block:

```tsx
  it('gives an unselected card a visible edge, so one card separates from the next', () => {
    render(<ValueChainGrid model={MODEL} onSelect={() => {}} />)
    // The defect was border-transparent: a card had a border box with no visible edge, so
    // it read as a floating patch of surface. Asserting only that a *selected* card is
    // border-brand passes on that broken behaviour, so the unselected case is the one that
    // has to be asserted.
    expect(screen.getByTestId('card-1.1-sp')).toHaveClass('border-surface')
    expect(screen.getByTestId('card-1.1-sp')).not.toHaveClass('border-transparent')
  })

  it('marks selection by the border colour, not by the border appearing', () => {
    render(
      <ValueChainGrid
        model={MODEL}
        onSelect={() => {}}
        selected={{ activityId: '1.1', partyId: 'sp' }}
      />,
    )
    expect(screen.getByTestId('card-1.1-sp')).toHaveClass('border-brand')
    // The neighbour still has an edge - selection changed a colour, it did not add an edge.
    expect(screen.getByTestId('card-1.2-sp')).toHaveClass('border-surface')
  })

  it('shows the description over three lines rather than one', () => {
    render(<ValueChainGrid model={MODEL} onSelect={() => {}} />)
    const field = screen.getByTestId('description-1.1-sp')
    expect(field.tagName).toBe('TEXTAREA')
    expect(field).toHaveAttribute('rows', '3')
  })

  it('keeps the description controlled after becoming a textarea', async () => {
    // The element changed; the SP22a defence must not have. A textarea rendered with
    // defaultValue would pass the tagName test above and silently corrupt saved data.
    render(<Stateful />)
    await userEvent.type(screen.getByTestId('description-1.1-sp'), '!')
    expect(fieldValue('1.1', 'sp')).toBe('first!')
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ValueChainGrid.test.tsx`
Expected: the first three FAIL - `border-transparent` present, `tagName` is `INPUT`, no `rows` attribute. The fourth passes already (the input is controlled today); it is a regression guard, not a new behaviour.

- [ ] **Step 3: Give the card a visible edge**

In `ui/src/components/ContributionCard.tsx`, replace the card's `className` at line 65-67:

```tsx
      className={`bg-surface-card rounded-lg p-3 border ${
        selected ? 'border-brand' : 'border-surface'
      }`}
```

- [ ] **Step 4: Make the description three lines**

Replace the `<input>` at lines 120-133 with:

```tsx
      <textarea
        data-testid={`description-${activityId}-${partyId}`}
        rows={3}
        // Controlled, never defaultValue. Cards key on the contribution's identity so a
        // move cannot put a different contribution behind an existing field node, and this
        // is the second defence on the same defect - it silently corrupted saved data.
        value={contribution.description ?? ''}
        readOnly={!editable}
        placeholder={editable ? 'Describe this contribution' : ''}
        onChange={(e) =>
          onChange?.(updateDescription(model, activityId, partyId, e.target.value))
        }
        className="mt-2 w-full bg-surface rounded px-2 py-1 text-xs text-secondary resize-none"
      />
```

Note there is no `type` attribute on a textarea - drop `type="text"`.

- [ ] **Step 5: Fix the four element-type casts in existing tests**

These read `.value` through an `HTMLInputElement` cast, which `tsc --noEmit` will now reject:

- `ui/src/__tests__/ValueChainGrid.test.tsx:46` - `as HTMLInputElement` becomes `as HTMLTextAreaElement`
- `ui/src/__tests__/ValueChainEditing.test.tsx:82` - same
- `ui/src/__tests__/ValueChainDrag.test.tsx:120` and `:123` - same

Change only the cast. Do not change what any of these tests assert.

- [ ] **Step 6: Run the tests and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, 269 tests (265 + 4 new), `tsc` clean.

- [ ] **Step 7: Commit**

```bash
git add ui/src/components/ContributionCard.tsx ui/src/__tests__/ValueChainGrid.test.tsx ui/src/__tests__/ValueChainEditing.test.tsx ui/src/__tests__/ValueChainDrag.test.tsx
git commit -m "feat(value-chain): card gains a visible edge and three lines of description"
```

---

### Task 2: The card lists its `n.n.n` activities

**Files:**
- Modify: `ui/src/utils/valueChainModel.ts` - add `contributionTasks`, remove `taskCount`, extend `ValueChainSelection`
- Modify: `ui/src/components/ContributionCard.tsx:135-143` (the counts row), `:36-56` (props)
- Modify: `ui/src/components/ValueChainGrid.tsx:47` (the `onSelect` prop type)
- Modify: `ui/src/components/StructureTab.tsx:94` (the select handler)
- Test: `ui/src/__tests__/ValueChainGrid.test.tsx`, `ui/src/__tests__/valueChainModel.test.ts:339-340`

**Interfaces:**
- Consumes: Task 1's textarea (no API change).
- Produces:
  - `contributionTasks(model: ValueChainModel, activityId: string, partyId: string): ValueChainTask[]`
  - `ValueChainSelection` gains `taskId?: string`
  - `onSelect?: (activityId: string, partyId: string, taskId?: string) => void` - the third argument is what Task 3 consumes. `ContributionCard`, `ValueChainGrid`, and `StructureTab` all carry this signature.
  - Test id per task line: `task-line-<taskId>-<partyId>`. The party is in the id because one task belongs to exactly one contribution, but two parties' cards can sit in the same cell and a bare task id would be ambiguous to read in a failure message.

- [ ] **Step 1: Write the failing tests**

`ValueChainGrid.test.tsx` - the `MODEL` fixture already gives `1.1`/`sp` two tasks and `1.2`/`sp` none, which is what these need. Add to `describe('ValueChainGrid layout', ...)`:

```tsx
  it('lists a contribution every n.n.n activity, rather than counting them', () => {
    render(<ValueChainGrid model={MODEL} onSelect={() => {}} />)
    // Assert the count of lines, not that a line exists - "a task line renders" is also
    // true of an implementation that renders only the first of the two.
    expect(screen.getAllByTestId(/^task-line-.*-sp$/)).toHaveLength(2)
    expect(screen.getByTestId('task-line-1.1.1-sp')).toHaveTextContent('1.1.1')
    expect(screen.getByTestId('task-line-1.1.1-sp')).toHaveTextContent('Set strategy')
  })

  it('renders no task lines for a contribution with no activities mapped', () => {
    render(<ValueChainGrid model={MODEL} onSelect={() => {}} />)
    expect(screen.queryByTestId(/^task-line-.*-sp$/)).not.toBeNull()
    expect(screen.queryByTestId('task-line-1.2.1-sp')).toBeNull()
  })

  it('reports the clicked task upwards, not just its contribution', async () => {
    const seen: Array<[string, string, string | undefined]> = []
    render(
      <ValueChainGrid
        model={MODEL}
        onSelect={(a, p, t) => seen.push([a, p, t])}
      />,
    )
    await userEvent.click(screen.getByTestId('task-line-1.1.2-sp'))
    expect(seen).toEqual([['1.1', 'sp', '1.1.2']])
  })

  it('reports no task when the card header is clicked', async () => {
    const seen: Array<[string, string, string | undefined]> = []
    render(
      <ValueChainGrid model={MODEL} onSelect={(a, p, t) => seen.push([a, p, t])} />,
    )
    await userEvent.click(screen.getByTestId('card-header-1.1-sp'))
    expect(seen).toEqual([['1.1', 'sp', undefined]])
  })
```

In `ui/src/__tests__/valueChainModel.test.ts`, replace the two `taskCount` assertions at lines 339-340 with the same coverage through the new helper:

```ts
    expect(contributionTasks(m, '1.2', 'sp')).toHaveLength(2)
    expect(contributionTasks(m, '1.2', 'iss')).toHaveLength(1)
```

and change the import at line 14 from `taskCount` to `contributionTasks`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ValueChainGrid.test.tsx src/__tests__/valueChainModel.test.ts`
Expected: FAIL - no `task-line-*` elements exist, and `contributionTasks` is not exported.

- [ ] **Step 3: Add the helper and extend the selection**

In `ui/src/utils/valueChainModel.ts`, add beside the existing counting helpers:

```ts
// The tasks belonging to one contribution. A task's owner is the composite
// (activity_id, party_id), the same identity the contribution itself carries.
export function contributionTasks(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
): ValueChainTask[] {
  return model.tasks.filter((t) => t.activity_id === activityId && t.party_id === partyId)
}
```

Delete `taskCount` - the card was its only caller and a tested-but-uncalled export is still dead code. Leave `propositionCount`, which the card keeps using.

Extend the selection interface at line 189:

```ts
export interface ValueChainSelection {
  activityId: string
  partyId: string
  // Set when the selection came from clicking one n.n.n activity on a card, so the dialog
  // can open on it. Absent when the card header opened the dialog.
  taskId?: string
}
```

- [ ] **Step 4: Replace the count with the list**

In `ui/src/components/ContributionCard.tsx`:

Change the import at lines 20-21 - drop `taskCount`, add `contributionTasks`. `ListTree` is no longer used on the card; drop it from the Lucide import at line 11 if nothing else uses it.

Widen the `onSelect` prop type at line 52:

```tsx
  onSelect?: (activityId: string, partyId: string, taskId?: string) => void
```

Add beside the other derived values near line 59:

```tsx
  const tasks = contributionTasks(model, activityId, partyId)
```

Replace the task-count `<span>` at lines 136-139 with nothing - the counts row keeps only the proposition count. Then insert the list immediately after that row's closing `</div>` (after line 167):

```tsx
      {tasks.length > 0 && (
        <ul data-testid={`task-list-${activityId}-${partyId}`} className="mt-2 space-y-1">
          {tasks.map((task) => (
            <li key={task.id}>
              <button
                type="button"
                data-testid={`task-line-${task.id}-${partyId}`}
                onClick={() => onSelect?.(activityId, partyId, task.id)}
                className="flex w-full items-baseline gap-2 text-left text-xs text-secondary hover:text-brand"
              >
                <span className="font-mono text-muted shrink-0">{task.id}</span>
                {/* No task in the live model carries a label - only a description - and
                    every task in the test fixtures carries a label and no description.
                    Both shapes are real, so both render; the number leads either way. */}
                <span className="truncate">{task.label ?? task.description ?? ''}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
```

The propositions keep their count and are not listed: a proposition attaches to the activity as a whole, so listing them per card would repeat one proposition across every party's card in that column.

- [ ] **Step 5: Carry the third argument through the grid and the tab**

`ui/src/components/ValueChainGrid.tsx:47`:

```tsx
  onSelect?: (activityId: string, partyId: string, taskId?: string) => void
```

The grid already passes `onSelect={onSelect}` straight to the card at line 345 - no other change there.

`ui/src/components/StructureTab.tsx:93-95`:

```tsx
  const handleSelectContribution = (activityId: string, partyId: string, taskId?: string) => {
    setSelectedContribution({ activityId, partyId, taskId })
  }
```

- [ ] **Step 6: Update the two count assertions that no longer have a subject**

`ui/src/__tests__/ValueChainGrid.test.tsx:127` and `:130` assert `task-count-1.1-sp` is `'2'` and `task-count-1.2-sp` is `'0'`. That element is gone. Delete those two assertions - the new list tests in Step 1 cover both cases, including the zero case. Keep any proposition-count assertion in the same test untouched.

- [ ] **Step 7: Run the tests and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, 273 tests (269 + 4 new), `tsc` clean.

- [ ] **Step 8: Commit**

```bash
git add ui/src/utils/valueChainModel.ts ui/src/components/ContributionCard.tsx ui/src/components/ValueChainGrid.tsx ui/src/components/StructureTab.tsx ui/src/__tests__/ValueChainGrid.test.tsx ui/src/__tests__/valueChainModel.test.ts
git commit -m "feat(value-chain): cards list their n.n.n activities instead of counting them"
```

---

### Task 3: The dialog opens on the clicked activity, and numbering leads

**Files:**
- Modify: `ui/src/components/ContributionPanel.tsx:11-15` (props), `:67-71` (heading), `:92-97` (task list)
- Modify: `ui/src/components/StructureTab.tsx:217-223` (pass the task through)
- Test: `ui/src/__tests__/ValueChainContributionPanel.test.tsx`

**Interfaces:**
- Consumes: `ValueChainSelection.taskId` from Task 2.
- Produces: `ContributionPanelProps` gains `highlightTaskId?: string`.

- [ ] **Step 1: Extend the fixture so the highlight test can discriminate**

`ui/src/__tests__/ValueChainContributionPanel.test.tsx:35-38` gives `1.1`/`sp` exactly one task. A one-task contribution cannot tell "highlights the task you clicked" from "highlights the first task" - they are the same task. Give `sp` three, and add one with no label so both task shapes render:

```tsx
    tasks: [
      { id: 't1', activity_id: '1.1', party_id: 'sp', label: 'Log the fault', description: 'Raise a ticket' },
      { id: 't2', activity_id: '1.1', party_id: 'sp', description: 'Assess the damage' },
      { id: 't3', activity_id: '1.1', party_id: 'sp', label: 'Close the job', description: 'Sign off' },
      { id: 't4', activity_id: '1.1', party_id: 'iss', label: 'Execute repair', description: 'Fix on site' },
    ],
```

Check the rest of that file for assertions that depend on `sp` having one task or on `t2` belonging to `iss`, and update them to match. Do not weaken what any of them assert.

- [ ] **Step 2: Write the failing tests**

```tsx
  it('highlights the activity that was clicked, not the first one', () => {
    // The middle task, deliberately: highlighting the first would pass with either
    // t1 or t3 clicked, so neither end discriminates.
    render(
      <ContributionPanel
        model={MODEL}
        activityId="1.1"
        partyId="sp"
        highlightTaskId="t2"
        onClose={() => {}}
      />,
    )
    expect(screen.getByTestId('task-t2')).toHaveClass('border-brand')
    expect(screen.getByTestId('task-t1')).not.toHaveClass('border-brand')
    expect(screen.getByTestId('task-t3')).not.toHaveClass('border-brand')
  })

  it('highlights nothing when the dialog was opened from the card header', () => {
    render(
      <ContributionPanel model={MODEL} activityId="1.1" partyId="sp" onClose={() => {}} />,
    )
    expect(screen.getByTestId('task-t1')).not.toHaveClass('border-brand')
  })

  it('leads each activity with its number, then its label when there is one', () => {
    render(
      <ContributionPanel model={MODEL} activityId="1.1" partyId="sp" onClose={() => {}} />,
    )
    // t1 has a label: number then label. The old `label ?? id` fallback showed the label
    // alone and dropped the number, which is invisible only while no task has a label.
    expect(screen.getByTestId('task-t1')).toHaveTextContent('t1')
    expect(screen.getByTestId('task-t1')).toHaveTextContent('Log the fault')
    // t2 has none: the number still leads, and the description follows it.
    expect(screen.getByTestId('task-t2')).toHaveTextContent('t2')
    expect(screen.getByTestId('task-t2')).toHaveTextContent('Assess the damage')
  })

  it('leads the heading with the activity number', () => {
    render(
      <ContributionPanel model={MODEL} activityId="1.1" partyId="sp" onClose={() => {}} />,
    )
    expect(screen.getByTestId('contribution-panel')).toHaveTextContent('1.1')
  })
```

This file also renders `StructureTab`, so add the end-to-end test there - beside the existing
`'returns focus to the card that opened it when it closes'` at roughly line 196, using
whatever helper that test uses to render the tab. Tasks 2 and 3 each test one half of the
chain; nothing yet tests that they are joined:

```tsx
  it('opens the dialog on the activity clicked from a card, and hands focus back to it', async () => {
    // The whole chain: card task line -> onSelect's third argument -> selection.taskId ->
    // the panel's highlightTaskId. Each half is unit-tested; only this fails if the two
    // are wired to different names.
    // Use a task that is neither the first nor the last of its contribution.
    await userEvent.click(screen.getByTestId('task-line-t2-sp'))
    expect(screen.getByTestId('task-t2')).toHaveClass('border-brand')

    await userEvent.click(screen.getByTestId('close-contribution-panel'))
    expect(screen.getByTestId('task-line-t2-sp')).toHaveFocus()
  })
```

Adjust the fixture ids to whatever that file's tab-level fixture uses - it may not be the
`MODEL` the panel-only tests use. The requirement is that the clicked task is a middle one.

- [ ] **Step 3: Run them to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ValueChainContributionPanel.test.tsx`
Expected: FAIL - `highlightTaskId` is not a prop, no `border-brand` on any task, `t1` shows its label with no number.

- [ ] **Step 4: Add the highlight**

In `ui/src/components/ContributionPanel.tsx`, extend the props at lines 11-15:

```tsx
export interface ContributionPanelProps {
  model: ValueChainModel
  activityId: string
  partyId: string
  // Set when the dialog was opened by clicking one n.n.n activity on a card. Absent when
  // the card header opened it, in which case nothing is highlighted.
  highlightTaskId?: string
}
```

and the signature at line 17-22 to destructure `highlightTaskId`.

Add a ref that scrolls the highlighted task into view, beside the existing focus effect:

```tsx
  const highlighted = useRef<HTMLLIElement>(null)
  useEffect(() => {
    // Optional call: jsdom does not implement scrollIntoView, and this is presentation -
    // a test environment without it should no-op, not throw.
    highlighted.current?.scrollIntoView?.({ block: 'nearest' })
  }, [highlightTaskId])
```

- [ ] **Step 5: Make the number lead, in the heading and on every task**

Replace the heading at lines 68-71:

```tsx
          <h4 className="text-sm font-medium text-primary">
            <span className="font-mono text-muted">{activityId}</span>{' '}
            {activity?.label ?? ''}
            {party && <span className="text-muted font-normal"> - {party.label}</span>}
          </h4>
```

Leave the `aria-label` at lines 55-59 alone. The comment above it records that "1.1 detail" told a screen reader nothing, and that still holds for the accessible name even now that the visible heading carries the number.

Replace the task `<li>` at lines 92-97:

```tsx
              {tasks.map((task) => {
                const isHighlighted = task.id === highlightTaskId
                return (
                  <li
                    key={task.id}
                    ref={isHighlighted ? highlighted : undefined}
                    data-testid={`task-${task.id}`}
                    className={`rounded border p-2 ${
                      isHighlighted ? 'border-brand' : 'border-transparent'
                    }`}
                  >
                    <p className="text-sm font-medium text-primary">
                      <span className="font-mono text-muted">{task.id}</span>
                      {task.label ? ` ${task.label}` : ''}
                    </p>
                    {task.description && <p className="text-muted text-xs">{task.description}</p>}
                  </li>
                )
              })}
```

`border-transparent` is correct here and wrong on a card: inside the dialog these are list rows where a resting edge would be noise, and the border exists only to carry the highlight.

- [ ] **Step 6: Pass the task through from the tab**

`ui/src/components/StructureTab.tsx:217-223`:

```tsx
            <ContributionPanel
              model={model}
              activityId={selectedContribution.activityId}
              partyId={selectedContribution.partyId}
              highlightTaskId={selectedContribution.taskId}
              onClose={() => setSelectedContribution(null)}
            />
```

Keep whatever the existing `model` prop expression is - only the new line is added.

- [ ] **Step 7: Run the tests and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, 277 tests (273 + 4 new), `tsc` clean.

- [ ] **Step 8: Commit**

```bash
git add ui/src/components/ContributionPanel.tsx ui/src/components/StructureTab.tsx ui/src/__tests__/ValueChainContributionPanel.test.tsx
git commit -m "feat(value-chain): dialog opens on the clicked activity and leads with its number"
```

---

### Task 4: The segment band carries its number

**Files:**
- Modify: `ui/src/components/ValueChainGrid.tsx:185-194`
- Test: `ui/src/__tests__/ValueChainGrid.test.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```tsx
  it('leads the segment band with the segment number', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} onSelect={() => {}} />)
    // toHaveTextContent is a substring match, so asserting the label alone - which the
    // existing band tests do - stays true when the number is missing. The number is what
    // this test is for, so assert the number.
    expect(screen.getByTestId('segment-band-1')).toHaveTextContent('1')
    expect(screen.getByTestId('segment-band-2')).toHaveTextContent('2')
  })
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/ValueChainGrid.test.tsx -t 'segment number'`
Expected: FAIL - the band renders the label only.

`TWO_SEGMENTS`' segment labels are `Property` and `Fleet`. Neither contains a digit, so the
substring assertion genuinely discriminates here - it cannot pass on the label alone.

- [ ] **Step 3: Put the number in the band**

```tsx
          {bands.map((b) => (
            <div
              key={`band-${b.segmentId}`}
              data-testid={`segment-band-${b.segmentId}`}
              className="text-sm font-medium text-secondary uppercase tracking-wide pb-2"
              style={{ gridColumn: `${b.start + 2} / span ${b.span}`, gridRow: 1 }}
            >
              <span className="font-mono">{b.segmentId}</span>{' '}
              {model.segments.find((s) => s.id === b.segmentId)?.label}
            </div>
          ))}
```

- [ ] **Step 4: Run the tests**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, 278 tests, `tsc` clean. The two existing band assertions at `:52` and `:236-237` are substring matches on the label and stay green.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/ValueChainGrid.tsx ui/src/__tests__/ValueChainGrid.test.tsx
git commit -m "feat(value-chain): segment band leads with its number"
```

---

### Task 5: The collision stack stops depending on card height

**Files:**
- Modify: `ui/src/components/ValueChainGrid.tsx:314-339`
- Test: `ui/src/__tests__/ValueChainGrid.test.tsx` (the existing collision tests live here)

**Interfaces:**
- Consumes: Tasks 1 and 2, which together roughly treble a card's height.
- Produces: nothing.

**Why:** the first occupant sits in normal flow and each later one is pulled up by a hard-coded `-mt-16`. That 4rem pull-up is subtracted from the card's height, so the cascade's step is **whatever is left over** - it grows with the card. After Tasks 1 and 2 a 3-deep collision would make its row about three cards tall, and every other row in the grid shares that row height.

- [ ] **Step 1: Write the failing test**

Add inside the same `describe` block that declares the `COLLIDED` fixture at
`ValueChainGrid.test.tsx:259` - three contributions of party `sp` sharing segment 1, column 10.
Do not build a second fixture.

```tsx
  it('stacks colliding cards without the cell growing with the stack', () => {
    render(<ValueChainGrid model={COLLIDED} />)
    const cell = screen.getByTestId('cell-1-sp-10')
    // The card-header-* exclusion is not optional: ContributionCard's own header testid
    // also starts with "card-", so the unqualified prefix selector matches both the card
    // and its header and would return six elements for three occupants. The sibling test
    // above carries the same filter for the same reason.
    const wrappers = [...cell.querySelectorAll('[data-testid^="card-"]')]
      .filter((el) => !el.getAttribute('data-testid')?.startsWith('card-header-'))
      .map((card) => card.parentElement as HTMLElement)
    expect(wrappers).toHaveLength(3)

    // Only the first occupant sits in flow, so the cell is one card tall whatever the
    // stack depth. jsdom does no layout, so this asserts the mechanism that produces that
    // - the buried cards are taken out of flow - rather than a measured height, which
    // would read 0 here whether the fix is present or not.
    expect(wrappers[0].className).toContain('relative')
    expect(wrappers[0].className).not.toContain('absolute')
    expect(wrappers[1].className).toContain('absolute')
    expect(wrappers[2].className).toContain('absolute')

    // Each buried card is stepped down by a distinct amount, so its header - the drag
    // handle the stacking exists to keep reachable - is not hidden under its neighbour's.
    expect(wrappers[1].style.top).toBeTruthy()
    expect(wrappers[1].style.top).not.toBe(wrappers[2].style.top)
  })
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/ValueChainGrid.test.tsx -t 'without the cell growing'`
Expected: FAIL - every wrapper is `relative`, and `style.top` is empty.

- [ ] **Step 3: Take the buried cards out of flow**

Add above the component, beside the zoom constants:

```tsx
// How far each buried card in a collision is stepped down. Its job is to leave the card
// beneath it showing its number and label line - the header, which is the drag handle that
// pulls the stack apart. Stated here rather than derived from the card's height, which is
// what the previous -mt-16 did by subtraction and which changed every time the card did.
const STACK_STEP_REM = 2
```

Replace the wrapper at lines 329-339:

```tsx
                        <div
                          key={contributionKey(activity.id, party.id)}
                          className={occupantIndex === 0 ? 'relative' : 'absolute inset-x-0'}
                          style={{
                            zIndex: occupantIndex + 1,
                            top:
                              occupantIndex > 0
                                ? `${occupantIndex * STACK_STEP_REM}rem`
                                : undefined,
                            marginLeft:
                              occupantIndex > 0 ? `${occupantIndex * 0.5}rem` : undefined,
                          }}
                        >
```

Update the comment above it (lines 325-328) so it describes stepping down out of flow rather than a diagonal translate, and keep the first two sentences about the React key unchanged - they are about a different defect.

The cell is already `relative` (line 252), so `absolute` positions against the cell.

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, 279 tests, `tsc` clean. The existing collision tests - three cards render, each is draggable, dragging one out leaves two - must all stay green; if any breaks, the stacking changed behaviour rather than only its mechanism.

- [ ] **Step 5: Confirm the backend has not moved**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 794 passed, 2 skipped - unchanged. No task in this plan touches Python; a change here means something was staged that should not have been.

- [ ] **Step 6: Commit**

```bash
git add ui/src/components/ValueChainGrid.tsx ui/src/__tests__/ValueChainGrid.test.tsx
git commit -m "fix(value-chain): collision stack no longer depends on card height"
```
