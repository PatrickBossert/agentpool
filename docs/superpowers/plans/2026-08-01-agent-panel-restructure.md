# Agent Panel Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An agent's Output tab holds only its current primary artefact, edited in place; its Status tab holds everything that has happened to it; and a notification link lands the reader on that Output tab.

**Architecture:** The existing `CREW_OUTPUT_TYPE` map moves to a shared module and becomes the declaration of each agent's primary artefact, joined by a new `CREW_OUTPUT_EDITOR` beside the per-crew maps `AgentDetailPanel.tsx` already has. The panel's Output and Status branches are extracted into their own components, the value chain page dissolves into Alex's and Maya's tabs, and the Dashboard learns to select a crew and tab from the URL.

**Tech Stack:** React 18, TypeScript, Vite, Tailwind v3, Vitest + Testing Library, TanStack Query, React Router v6. Backend: FastAPI (one link-building change).

**Spec:** `docs/superpowers/specs/2026-08-01-agent-panel-restructure-design.md`

## Global Constraints

- **British English** (`-ise`, `-our`, `-re`) in all prose, comments, docstrings, test names, and UI copy.
- **Spaced hyphen ` - ` in prose, never an em dash `—`.** Applies to prose, not hyphenated compound adjectives. Do not alter pre-existing em dashes on lines you are not otherwise changing.
- **Lucide React SVG icons only. No emoji in rendered content.**
- **Never `sky-*` or `blue-*` Tailwind classes.** Brand tokens preferred: `text-brand`, `bg-brand`, `bg-surface`, `bg-surface-raised`, `bg-surface-card`, `text-primary`, `text-secondary`, `text-muted`. `text-red-400` for errors and `amber-*` for warnings are established conventions.
- **All raw SQL lives in `api/database.py`** - none in service or router modules.
- **`agents/tools/human_input.py` must not be modified.**
- Frontend tests: `npx vitest run` from `ui/`, plus `npx tsc --noEmit` which must be clean.
- Backend tests: `./venv/bin/pytest -q --ignore=tests/integration` - **not** bare `pytest`.
- **Baselines: 216 frontend, 771 backend.** Report actual counts; predicted figures are estimates to reconcile, not gates.
- **Stage files explicitly by name. Never `git add -A` or `git add .`** - the working tree holds unrelated untracked files (screenshots, `.docx`) that must not be swept in.

## File Structure

| File | Responsibility |
|---|---|
| `ui/src/components/AgentOutputTab.tsx` | **Create.** The current primary output, through its editor. |
| `ui/src/components/AgentStatusTab.tsx` | **Create.** Runs, changes, summary card, non-primary outputs, version actions. |
| `ui/src/components/AgentDetailPanel.tsx` | **Modify.** Keeps the tab strip, shared queries, and the per-crew maps. Currently 1745 lines. |
| `ui/src/components/StructureTab.tsx` | **Modify.** Becomes Alex's output editor. |
| `ui/src/components/tabs/MayaSetupTab.tsx` | **Modify.** Gains the node template assignment section. |
| `ui/src/components/ReviewDialog.tsx` | **Modify.** `CREW_OUTPUT_TYPE` for `discovery_mapping`. |
| `ui/src/pages/ValueChain.tsx` | **Delete.** Structure to Alex, Templates to Maya, Setup is a duplicate. |
| `ui/src/router.tsx` | **Modify.** The old route redirects. |
| `ui/src/pages/Dashboard.tsx` | **Modify.** Accepts `crew` and `tab` from the URL. |
| `api/services/commit_notify_service.py` | **Modify.** The link carries the crew. |

**Why the split.** `AgentDetailPanel.tsx` is 1745 lines and this makes Status substantially bigger. Extracting the two tab bodies is the same move that took `StructureTab` out of `ValueChain.tsx` on the previous branch. Without it the file lands past 2000 lines and the next change to it is worse than this one.

**Task order.** The panel split comes first (Task 1) so later tasks have somewhere to plug into. The value chain dissolution (Task 2) needs the editor slot to exist. The Dashboard preview (Task 3) and the deep links (Task 4) are independent of each other and could swap.

**Task 1 is deliberately one task, not two.** It extracts both tab bodies and rehomes every assertion it displaces. Splitting it would leave the suite red between the halves, and a reviewer cannot meaningfully approve the Output half while rejecting the Status half - neither works alone. It carries **one commit**, taken once the suite is green.

---

## Task 1: Split the panel into an Output tab and a Status tab

**Files:**
- Create: `ui/src/components/crewOutputs.ts`, `ui/src/components/AgentOutputTab.tsx`, `ui/src/components/AgentStatusTab.tsx`
- Modify: `ui/src/components/AgentDetailPanel.tsx`, `ui/src/components/ReviewDialog.tsx`
- Test: `ui/src/__tests__/AgentOutputTab.test.tsx`, `ui/src/__tests__/AgentStatusTab.test.tsx`, plus any existing test whose assertions this displaces

**Interfaces:**
- Produces: `CREW_OUTPUT_TYPE` relocated to `ui/src/components/crewOutputs.ts` and re-exported from `ReviewDialog.tsx`; `CREW_OUTPUT_EDITOR: Partial<Record<string, SlotFC>>` exported from `AgentDetailPanel.tsx` beside the existing `CREW_SETUP_OVERRIDE` and `CREW_OUTPUT_EXTRA`; `AgentOutputTab({ slug, crewKey, outputs, locale })`.

**Background.** `SlotFC` is the existing type used by `CREW_SETUP_OVERRIDE` - find it in the file and reuse it rather than declaring a second one. `PAM` is exempt from all of this: its Output tab is labelled Overview and renders `PamReportView`. Leave that branch exactly as it is.

**The rule this task establishes:** the Output tab shows the **current version of one declared output type**, and nothing else. An agent with no declared editor renders that artefact read-only, which is what makes this a default rather than a special case for Alex.

- [ ] **Step 1: Write the failing tests**

Create `ui/src/__tests__/AgentOutputTab.test.tsx`. Follow the render helper and mocks in `ui/src/__tests__/Reviews.test.tsx` - it already mocks `projectsApi` and wraps in a QueryClientProvider; copy its shape rather than inventing one.

```tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

import { AgentOutputTab } from '../components/AgentOutputTab'

// Two output types, one primary and one not. A crew with a single output type cannot
// distinguish "shows the primary" from "shows everything it has", so this fixture is the
// minimum that discriminates.
const OUTPUTS = [
  { id: 1, agent_name: 'value_chain_mapper', output_type: 'value_chain_model',
    version: 3, is_current: 1, created_at: '2026-08-01 10:00:00', file_path: 'a.json' },
  { id: 2, agent_name: 'value_chain_mapper', output_type: 'value_chain_model',
    version: 2, is_current: 0, created_at: '2026-07-31 10:00:00', file_path: 'b.json' },
  { id: 3, agent_name: 'value_chain_mapper', output_type: 'value_chain_registry',
    version: 13, is_current: 1, created_at: '2026-08-01 09:00:00', file_path: 'c.json' },
]

describe('AgentOutputTab', () => {
  it('renders the declared primary output and not the others', () => {
    render(<AgentOutputTab slug="t" crewKey="discovery_mapping" outputs={OUTPUTS} />)
    expect(screen.getByTestId('primary-output-value_chain_model')).toBeInTheDocument()
    expect(screen.queryByTestId('primary-output-value_chain_registry')).not.toBeInTheDocument()
  })

  it('renders only the current version, not the version history', () => {
    render(<AgentOutputTab slug="t" crewKey="discovery_mapping" outputs={OUTPUTS} />)
    expect(screen.getByTestId('primary-output-value_chain_model')).toHaveAttribute('data-version', '3')
    expect(screen.queryByTestId('output-version-2')).not.toBeInTheDocument()
  })

  it('shows no revert, reject or revise control - those live in Status', () => {
    render(<AgentOutputTab slug="t" crewKey="discovery_mapping" outputs={OUTPUTS} />)
    expect(screen.queryByRole('button', { name: /revert/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /reject/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /revis/i })).not.toBeInTheDocument()
  })

  it("renders an agent's primary read-only when it has no declared editor", () => {
    // The case that proves this is a default and not a special case for Alex.
    const outputs = [{ ...OUTPUTS[0], agent_name: 'synthesis_analyst', output_type: 'synthesis' }]
    render(<AgentOutputTab slug="t" crewKey="discovery" outputs={outputs} />)
    expect(screen.getByTestId('primary-output-readonly')).toBeInTheDocument()
  })

  it('shows an empty state when the crew has no output of its primary type', () => {
    render(<AgentOutputTab slug="t" crewKey="discovery_mapping" outputs={[]} />)
    expect(screen.getByTestId('no-primary-output')).toBeInTheDocument()
  })
})
```

The `outputs` prop shape must match what `AgentDetailPanel` already passes down - read the existing `crewOutputs` derivation in that file and use the same type rather than inventing fields. If the real type has more fields than the fixture above, add them; do not narrow the component's prop type to fit the fixture.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/AgentOutputTab.test.tsx`
Expected: FAIL - `Failed to resolve import "../components/AgentOutputTab"`.

- [ ] **Step 3: Add the two maps**

**Do not declare a second map.** `ui/src/components/ReviewDialog.tsx` already has
`CREW_OUTPUT_TYPE`, mapping each crew to the output type that represents its work, used for
the Dashboard's inline preview. That is the same fact the Output tab needs, and two maps
stating it would drift the first time a crew's output type changed.

Move it to a shared module instead. Create `ui/src/components/crewOutputs.ts` - the codebase
already puts shared non-component logic beside components this way, see
`ui/src/components/agentStatus.ts`:

```ts
// ui/src/components/crewOutputs.ts
// Which output type represents each crew's work. One fact, one home: the Dashboard's inline
// preview and the agent panel's Output tab both need it, and two copies would drift the
// first time a crew's output type changed.
//
// PAM is deliberately absent - its Output tab is an Overview rendering PamReportView, not a
// versioned artefact, so it has no primary to declare and keeps its own branch.
export const CREW_OUTPUT_TYPE: Record<string, string> = {
  // ... moved verbatim from ReviewDialog.tsx, discovery_mapping unchanged for now
}
```

Move the constant as-is and re-export it from `ReviewDialog.tsx` so that file's existing
importers keep working. **Leave `discovery_mapping: 'value_chain'` alone in this task** -
Task 3 repoints it, and changing it here would make Task 4's failing test pass before it is
written.

Then in `AgentDetailPanel.tsx`, beside `CREW_SETUP_OVERRIDE` and `CREW_OUTPUT_EXTRA`, add
only the editor map:

```tsx
// The bespoke editor for an agent's primary output. An agent absent from this map renders
// its primary read-only - the structure arrives for every agent, the editors arrive one at
// a time.
export const CREW_OUTPUT_EDITOR: Partial<Record<string, SlotFC>> = {}
```

It is deliberately empty here; Task 2 registers Alex's. Leaving it empty is what makes the
read-only fallback test meaningful.

**Note for the tests in this task:** because `discovery_mapping` still maps to
`'value_chain'` until Task 4, the fixture's primary type is `'value_chain'`, not
`'value_chain_model'`. Use whichever the map actually holds when you write the test - a test
asserting the post-Task-3 value would fail for the wrong reason.

- [ ] **Step 4: Create the component**

Create `ui/src/components/AgentOutputTab.tsx`. It selects the crew's primary type, finds the current version of it, and renders through the declared editor or a read-only fallback.

```tsx
// ui/src/components/AgentOutputTab.tsx
// One agent's current primary artefact, and nothing else.
//
// The Output tab is where you change the artefact; the Status tab is where you see what has
// happened to it. Version lists, thumbnails, revert, reject and revise all act on *a
// version* rather than on the current artefact, so they live in Status.
```

Give the rendered artefact `data-testid={`primary-output-${primaryType}`}` and `data-version={String(current.version)}`, the read-only fallback `data-testid="primary-output-readonly"`, and the empty state `data-testid="no-primary-output"`.

Keep the existing empty-state visual - the avatar and "No outputs yet" copy currently in the Output branch of `AgentDetailPanel.tsx` - rather than inventing new copy.

- [ ] **Step 5: Render it from the panel**

In `AgentDetailPanel.tsx`, replace the body of the `tab === 'output' && crewKey !== 'PAM'` branch with `<AgentOutputTab slug={slug} crewKey={crewKey} outputs={crewOutputs} locale={locale} />`. Keep the `CREW_OUTPUT_EXTRA` block that follows it - that is separate content, not part of the primary artefact.

Leave the `tab === 'output' && crewKey === 'PAM'` branch untouched.

- [ ] **Step 6: Run the suite and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: the new file's tests pass and `tsc` is clean. **Existing tests that assert on the old Output tab's version list will fail** - that is expected, and Task 2 is where those assertions move. If a failing test asserts something that should survive, fix it here and say so; if it asserts the old structure, note it and leave it for Task 2 rather than deleting it.

---

### Part B of Task 1: move the history into the Status tab

**Files:**
- Create: `ui/src/components/AgentStatusTab.tsx`
- Modify: `ui/src/components/AgentDetailPanel.tsx`
- Test: `ui/src/__tests__/AgentStatusTab.test.tsx`

**Interfaces:**
- Consumes: `CREW_OUTPUT_TYPE` from `ui/src/components/crewOutputs.ts` (Part A above).
- Produces: `AgentStatusTab({ slug, crewKey, crewRun, outputs, statusEvents, locale, primaryModel })`, where `primaryModel` is the already-fetched artefact when the crew's primary is a structured model and `undefined` otherwise - it is what the summary card counts, and passing it rather than refetching is what stops the count disagreeing with the artefact.

**This task must be lossless.** Every control that exists today has to exist afterwards and still work. The list, named individually rather than counted so a silent drop is a failure rather than a gap in a total: the **version list**, the **thumbnail**, **revert**, **reject**, **revise**, and the lazy content load behind them. They come from `OutputItem`, which splits here - its editor path is gone, its version-acting path moves.

The existing Status content stays: run timestamps, the error detail block, and the activity event log.

**New in Status:** the output summary card. For a `value_chain_model` that is a summary line computed **client-side from the model already fetched** - counting segments, activities, contributions and tasks - not a stored field. Nothing needs to persist it, and a count derived from the artefact cannot go stale against it.

- [ ] **Step 1: Write the failing tests**

Create `ui/src/__tests__/AgentStatusTab.test.tsx`, using the same render helper as Task 1.

```tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import { AgentStatusTab } from '../components/AgentStatusTab'

const OUTPUTS = [
  { id: 1, agent_name: 'value_chain_mapper', output_type: 'value_chain_model',
    version: 3, is_current: 1, created_at: '2026-08-01 10:00:00', file_path: 'a.json' },
  { id: 2, agent_name: 'value_chain_mapper', output_type: 'value_chain_model',
    version: 2, is_current: 0, created_at: '2026-07-31 10:00:00', file_path: 'b.json' },
  { id: 3, agent_name: 'value_chain_mapper', output_type: 'value_chain_registry',
    version: 13, is_current: 1, created_at: '2026-08-01 09:00:00', file_path: 'c.json' },
]

describe('AgentStatusTab', () => {
  it('lists prior versions of the primary output', () => {
    render(<AgentStatusTab slug="t" crewKey="discovery_mapping" outputs={OUTPUTS} statusEvents={[]} />)
    expect(screen.getByTestId('output-version-2')).toBeInTheDocument()
  })

  it('lists non-primary output types, which the Output tab does not show', () => {
    render(<AgentStatusTab slug="t" crewKey="discovery_mapping" outputs={OUTPUTS} statusEvents={[]} />)
    expect(screen.getByTestId('output-type-value_chain_registry')).toBeInTheDocument()
  })

  it('offers revert on a prior version', () => {
    render(<AgentStatusTab slug="t" crewKey="discovery_mapping" outputs={OUTPUTS} statusEvents={[]} />)
    expect(screen.getByTestId('revert-2')).toBeInTheDocument()
  })

  it('does not offer revert on the current version - there is nothing to revert to', () => {
    render(<AgentStatusTab slug="t" crewKey="discovery_mapping" outputs={OUTPUTS} statusEvents={[]} />)
    expect(screen.queryByTestId('revert-1')).not.toBeInTheDocument()
  })

  it('keeps the run timestamps and the error detail', () => {
    const run = { crew_name: 'discovery_mapping', status: 'failed',
                  started_at: '2026-08-01 10:00:00', finished_at: '2026-08-01 10:05:00',
                  error_detail: 'boom' }
    render(<AgentStatusTab slug="t" crewKey="discovery_mapping" crewRun={run} outputs={OUTPUTS} statusEvents={[]} />)
    expect(screen.getByText(/boom/)).toBeInTheDocument()
  })

  it('summarises a value chain model by counting what is in it', () => {
    // Computed from the artefact, so it cannot disagree with it.
    const model = {
      segments: [{ id: '1' }, { id: '2' }, { id: '3' }],
      activities: new Array(17).fill(0).map((_, i) => ({ id: `a${i}` })),
      contributions: new Array(17).fill(0).map((_, i) => ({ activity_id: `a${i}` })),
      tasks: new Array(59).fill(0).map((_, i) => ({ id: `t${i}` })),
      parties: [{ id: 'sp' }, { id: 'iss' }, { id: 'dxi' }],
      propositions: [], links: [], model_version: 1,
    }
    render(
      <AgentStatusTab slug="t" crewKey="discovery_mapping" outputs={OUTPUTS}
                      statusEvents={[]} primaryModel={model} />,
    )
    const card = screen.getByTestId('output-summary')
    expect(card).toHaveTextContent('3 segments')
    expect(card).toHaveTextContent('17 activities')
    expect(card).toHaveTextContent('17 contributions')
    expect(card).toHaveTextContent('59 tasks')
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/AgentStatusTab.test.tsx`
Expected: FAIL - `Failed to resolve import "../components/AgentStatusTab"`.

- [ ] **Step 3: Create the component and move `OutputItem`'s version half into it**

Create `ui/src/components/AgentStatusTab.tsx` with this header:

```tsx
// ui/src/components/AgentStatusTab.tsx
// What has happened to an agent's work: its runs, its versions, and the actions that act on
// a version rather than on the current artefact.
//
// Revert, reject, revise and the version list all moved here from the Output tab. Reverting
// is a fact about history, not an edit - and grouping the four keeps the rule stateable in
// one sentence: Output is where you change the artefact, Status is where you see what has
// happened to it.
```

Move the version-acting half of `OutputItem` across, keeping its lazy content load, its revision panel, its revert panel and its reject flow intact. Give the controls `data-testid` values of the form `revert-${output.id}`, and version rows `output-version-${output.version}`, non-primary type sections `output-type-${outputType}`, and the summary card `output-summary`.

Do not rewrite the moved logic. If something reads awkwardly in its new home, note it in your report rather than improving it in the same commit - a faithful move is reviewable, a move plus a rewrite is not.

- [ ] **Step 4: Render it from the panel and migrate the old assertions**

In `AgentDetailPanel.tsx`, replace the body of the `tab === 'status' && crewKey !== 'PAM'` branch with `<AgentStatusTab ... />`, passing the same `crewRun`, `statusEvents` and `crewOutputs` it already has in scope. Leave the PAM status branch untouched.

Then fix the tests Task 1 left failing: any assertion about the version list, thumbnails, revert, reject or revise now belongs against the Status tab. **Move each assertion; do not delete it.** In your report, list every assertion you moved and where it went, so a reviewer can check nothing was quietly dropped.

- [ ] **Step 5: Run the suite and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: all passing, `tsc` clean. Report the count against the 216 baseline.

- [ ] **Step 6: Commit**

```bash
git add ui/src/components/crewOutputs.ts ui/src/components/AgentOutputTab.tsx ui/src/components/AgentStatusTab.tsx ui/src/components/AgentDetailPanel.tsx ui/src/components/ReviewDialog.tsx ui/src/__tests__/AgentOutputTab.test.tsx ui/src/__tests__/AgentStatusTab.test.tsx
# plus every existing test file whose assertions you rehomed - list them explicitly
git commit -m "feat: split the agent panel into an Output tab and a Status tab"
```

---

## Task 2: Dissolve the value chain page

**Files:**
- Modify: `ui/src/components/AgentDetailPanel.tsx` - register Alex's editor
- Modify: `ui/src/components/StructureTab.tsx` - becomes the editor
- Modify: `ui/src/components/tabs/MayaSetupTab.tsx` - gains node template assignment
- Modify: `ui/src/router.tsx` - the old route redirects
- Delete: `ui/src/pages/ValueChain.tsx`
- Test: `ui/src/__tests__/ValueChainRoute.test.tsx`

**Interfaces:**
- Consumes: `CREW_OUTPUT_EDITOR` from Task 1.

**Three different fates, and the reasons differ:**

1. **Structure → Alex's editor.** `StructureTab.tsx` already holds the model query, the pending edits, Save, the migrate affordance and the removal dialog. Register it: `CREW_OUTPUT_EDITOR = { discovery_mapping: StructureTab }`.

2. **Setup → deleted.** `ui/src/components/tabs/AlexSetupTab.tsx` already exists as Alex's `CREW_SETUP_OVERRIDE` and already saves the identical field set - `discovery_brief`, `discovery_document_ids`, `discovery_links`, `standards_references`, `preferred_questionnaire_sections`, `preferred_questions_per_section`. The same configuration has been editable in two places. **Verify that equivalence yourself before deleting** - compare the two field-by-field and report any field the page saves that `AlexSetupTab` does not. If you find one, move it rather than dropping it.

3. **Templates → Maya's Setup, unchanged.** It maps stored templates onto individual nodes. The interview coverage model supersedes that mechanism, but the replacement is not built, so removing it now would take away control with nothing to fill the gap. Move it as-is into `MayaSetupTab.tsx` under its own heading. Do not redesign it.

**The route redirects rather than 404s.** Notification emails already sent contain links into the app, and bookmarks exist. `/dashboard/:slug/value-chain` redirects to `/dashboard/:slug?crew=discovery_mapping&tab=output`.

- [ ] **Step 1: Write the failing test**

Create `ui/src/__tests__/ValueChainRoute.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'

describe('the retired value chain route', () => {
  it('redirects to the Dashboard with Alex selected rather than 404ing', async () => {
    // Bookmarks and already-sent emails point here. A 404 strands them.
    render(
      <MemoryRouter initialEntries={['/dashboard/acme/value-chain']}>
        <AppRoutes />
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('dashboard')).toBeInTheDocument()
  })
})
```

**`router.tsx` exports only `router`, built with `createBrowserRouter`**, so it cannot be mounted inside a `MemoryRouter`. Extract the route array into an exported `routes` constant and build the browser router from it, leaving `router` exported exactly as before so nothing that imports it changes. The test then does `createMemoryRouter(routes, { initialEntries: ['/dashboard/acme/value-chain'] })` and renders `<RouterProvider router={...} />`.

That extraction is the smallest change that makes routing testable at all, and both this task and Task 4 need it.

`data-testid="dashboard"` may not exist on the Dashboard yet; add it if not.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/ValueChainRoute.test.tsx`
Expected: FAIL - the route still renders the value chain page, so the Dashboard is not found.

- [ ] **Step 3: Register Alex's editor**

In `AgentDetailPanel.tsx`:

```tsx
import StructureTab from './StructureTab'

export const CREW_OUTPUT_EDITOR: Partial<Record<string, SlotFC>> = {
  discovery_mapping: StructureTab,
}
```

Check `StructureTab`'s current props against `SlotFC`'s signature. If they differ, adapt `StructureTab` to the slot signature rather than widening `SlotFC` - every other slot component in this file already conforms to it.

- [ ] **Step 4: Move Templates into Maya's Setup, verify Setup is a duplicate, delete the page**

Move the Templates tab's markup and its state - `nodeAssignments`, `interviewTemplates`, `questionnaireTemplates`, and the `listNodeTemplates` / `putNodeTemplate` / `publishNodeTemplate` calls - into `MayaSetupTab.tsx` under a heading naming what it is.

Then compare `ValueChain.tsx`'s Setup tab against `AlexSetupTab.tsx` field by field. Report the comparison. If they match, delete `ui/src/pages/ValueChain.tsx`.

- [ ] **Step 5: Redirect the route**

In `ui/src/router.tsx`, replace the `value-chain` route's element with a redirect to `/dashboard/:slug?crew=discovery_mapping&tab=output`, preserving the slug. Remove the now-unused import.

- [ ] **Step 6: Run the suite and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: all passing, `tsc` clean. Tests that mounted `ValueChain.tsx` directly must now mount the panel or the Structure tab instead - **migrate their assertions, do not delete them**, and list what moved.

- [ ] **Step 7: Commit**

```bash
git add ui/src/components/AgentDetailPanel.tsx ui/src/components/StructureTab.tsx ui/src/components/tabs/MayaSetupTab.tsx ui/src/router.tsx ui/src/__tests__/ValueChainRoute.test.tsx
git rm ui/src/pages/ValueChain.tsx
git commit -m "feat: dissolve the value chain page into Alex's and Maya's tabs"
```

---

## Task 3: Point the Dashboard preview at the model

**Files:**
- Modify: `ui/src/components/ReviewDialog.tsx` - `CREW_OUTPUT_TYPE`
- Modify: `ui/src/components/AgentDetailPanel.tsx` - `MERMAID_OUTPUT_TYPES`
- Test: `ui/src/__tests__/ReviewDialog.test.tsx` (create if absent)

**The defect this fixes.** `ReviewDialog.tsx`'s `CREW_OUTPUT_TYPE` maps `discovery_mapping` to `value_chain`, the legacy Mermaid type, and `AgentDetailPanel.tsx`'s `MERMAID_OUTPUT_TYPES` contains the same. So Alex's inline preview still renders a diagram from an output produced before the model existed - and once he is re-run, producing no `value_chain` output at all, it would show nothing.

A structured model has no diagram to draw. The summary card from Task 2 is the honest equivalent.

- [ ] **Step 1: Write the failing tests**

```tsx
import { describe, it, expect } from 'vitest'
import { CREW_OUTPUT_TYPE } from '../components/ReviewDialog'
import { MERMAID_OUTPUT_TYPES } from '../components/AgentDetailPanel'

describe('the value chain preview', () => {
  it('previews the model, not the retired diagram', () => {
    expect(CREW_OUTPUT_TYPE.discovery_mapping).toBe('value_chain_model')
  })

  it('does not try to draw the model as a diagram', () => {
    // Alex no longer holds MermaidRenderTool, so a fresh run produces no value_chain
    // output at all - and a JSON model has no fence to render.
    expect(MERMAID_OUTPUT_TYPES.has('value_chain_model')).toBe(false)
  })

  it('still draws the output types that really are diagrams', () => {
    // The positive anchor: without it, deleting the whole set would pass the test above.
    expect(MERMAID_OUTPUT_TYPES.has('architecture')).toBe(true)
    expect(MERMAID_OUTPUT_TYPES.has('roadmap')).toBe(true)
  })
})
```

Both constants are currently module-private; export them.

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/ReviewDialog.test.tsx`
Expected: FAIL - the export does not exist, then the mapping is `'value_chain'`.

- [ ] **Step 3: Repoint the map and export both constants**

In `ReviewDialog.tsx`, change `discovery_mapping` to `'value_chain_model'` and export `CREW_OUTPUT_TYPE`. In `AgentDetailPanel.tsx`, export `MERMAID_OUTPUT_TYPES` and leave its members alone - `value_chain` stays in it, because legacy outputs still exist and still render correctly as diagrams in Status.

- [ ] **Step 4: Run the suite and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: all passing, `tsc` clean.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/ReviewDialog.tsx ui/src/components/AgentDetailPanel.tsx ui/src/__tests__/ReviewDialog.test.tsx
git commit -m "fix: preview the value chain model rather than the retired diagram"
```

---

## Task 4: Land a notification on the agent's Output tab

**Files:**
- Modify: `ui/src/pages/Dashboard.tsx` - read `crew` and `tab` from the URL
- Modify: `api/services/commit_notify_service.py` - the link carries the crew
- Test: `ui/src/__tests__/DashboardDeepLink.test.tsx`, `tests/test_commit_notification.py`

**The gotcha, and it is the substance of this task.** The panel restores its last tab from `localStorage` - see the initialiser around `AgentDetailPanel.tsx:1307`. An approver whose last visit ended on Chat would land on Chat no matter what the email said. **The URL wins when present**; the saved tab is consulted only when the URL says nothing.

A test that only checks "the URL works" would pass while the stored value silently won on a machine that had one. The test below sets `localStorage` to a *different* tab first, which is what makes it discriminating.

- [ ] **Step 1: Write the failing tests**

Create `ui/src/__tests__/DashboardDeepLink.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach } from 'vitest'

beforeEach(() => localStorage.clear())

describe('deep linking into an agent', () => {
  it('selects the crew named in the URL', async () => {
    render(
      <MemoryRouter initialEntries={['/dashboard/acme?crew=discovery_mapping&tab=output']}>
        <AppRoutes />
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('selected-crew-discovery_mapping')).toBeInTheDocument()
  })

  it('opens the tab named in the URL even when a different one was last used', async () => {
    // The whole defect. Without the pre-set value this test passes on a broken
    // implementation, because a fresh localStorage has nothing to lose to.
    localStorage.setItem('agentPanelTab', 'chat')
    render(
      <MemoryRouter initialEntries={['/dashboard/acme?crew=discovery_mapping&tab=output']}>
        <AppRoutes />
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('active-tab-output')).toBeInTheDocument()
  })

  it('falls back to the saved tab when the URL names none', async () => {
    localStorage.setItem('agentPanelTab', 'chat')
    render(
      <MemoryRouter initialEntries={['/dashboard/acme']}>
        <AppRoutes />
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('active-tab-chat')).toBeInTheDocument()
  })
})
```

**The key is not a constant, and this matters for the test.** `AgentDetailPanel.tsx:1303`
builds it per user, project and crew:

```tsx
const tabKey = user?.sub ? `ap_panel_tab:${user.sub}:${slug}:${crewKey}` : null
```

So the test must set `ap_panel_tab:<sub>:acme:discovery_mapping`, where `<sub>` is whatever
the mocked auth user's `sub` is - check how `Reviews.test.tsx` mocks `useAuth` and use the
same user. If no user is mocked, `tabKey` is `null`, the stored value is never read, **and
the test passes without proving anything**.

Note also that the initialiser already defaults to `'output'`. A fresh browser therefore
lands on Output anyway, so only a *saved* value for that exact user, project and crew
exposes the defect - which is precisely why the middle test seeds one.

Add `data-testid="selected-crew-<key>"` and `data-testid="active-tab-<tab>"` where they do
not exist.

Add to `tests/test_commit_notification.py`, following its existing pattern of patching `api.services.commit_notify_service._send_email` with an `AsyncMock` and calling `_set_dev_mode(SLUG, False)`:

```python
@pytest.mark.asyncio
async def test_the_notification_links_to_the_crew_it_is_about(client):
    """Three notices are built at three call sites, so the crew is asserted per notice
    rather than once - a link carrying the wrong crew is worse than one carrying none."""
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=False)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch("api.services.commit_notify_service._send_email", AsyncMock()) as send:
        await notify_crew_awaiting_commit(SLUG, "assessment_design")

    body = send.await_args.kwargs["body"]
    assert "crew=assessment_design" in body
    assert "tab=output" in body
```

Write the equivalent for `notify_crew_ready_for_approval` and `notify_crew_failed` - all three build links, and asserting one proves nothing about the other two.

- [ ] **Step 2: Run both to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/DashboardDeepLink.test.tsx`
Run: `./venv/bin/pytest tests/test_commit_notification.py -v`
Expected: FAIL - the Dashboard ignores the query string; the link has no crew.

- [ ] **Step 3: Read the URL in the Dashboard**

`ui/src/pages/Dashboard.tsx` currently does `const [selectedCrew, setSelectedCrew] = useState<string>('PAM')` and takes only `slug` from `useParams`. Add `useSearchParams`, seed `selectedCrew` from `?crew=` when present, and pass `?tab=` down to the panel as a prop that **overrides** its stored value.

In `AgentDetailPanel.tsx`, the tab initialiser reads `localStorage`. Give it an optional `initialTab` prop and prefer it when set:

```tsx
// A deep link from a notification must beat whatever tab this browser last used, or an
// approver who ended their last visit on Chat lands on Chat however the email was written.
const [tab, setTab] = useState<Tab>(() => {
  if (initialTab) return initialTab
  // ... existing localStorage read, unchanged
})
```

- [ ] **Step 4: Carry the crew in the link**

In `api/services/commit_notify_service.py`, `_notify` already has `crew_name` in scope where it builds `link`. Change it to:

```python
        link = (
            f"{settings.public_url.rstrip('/')}/dashboard/{slug}"
            f"?crew={crew_name}&tab=output"
        )
```

The Reviews page is unaffected and keeps its own route - only where the notices point changes.

- [ ] **Step 5: Run both suites and the type check**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: all passing, `tsc` clean. Report both counts.

- [ ] **Step 6: Commit**

```bash
git add ui/src/pages/Dashboard.tsx ui/src/components/AgentDetailPanel.tsx ui/src/__tests__/DashboardDeepLink.test.tsx api/services/commit_notify_service.py tests/test_commit_notification.py
git commit -m "feat: a notification lands on the agent's output tab"
```

---

## Prerequisite - already done

`sp-gs-am`'s value chain model has been migrated: 3 segments, 17 activities, 17
contributions, 59 tasks, 3 parties, 0 derived. Alex's Output tab will render a grid rather
than the migrate prompt. No action needed; recorded so nobody repeats it or wonders why the
grid has data.

The API was also restarted - it had been running for over three days without `--reload` and
had none of the routes merged since. If the routes are missing again, that is why.

## Notes carried from the previous three branches

- **Fixture sizing.** An agent with exactly one output type cannot distinguish "shows the primary" from "shows everything it has". Every test of the primary-output rule uses a fixture with at least two types, one primary and one not. The last three branches shipped six defects hidden by fixtures too small to tell the correct implementation from the bug.
- **Absence needs a positive anchor.** Task 3's "does not draw the model as a diagram" is paired with "still draws the ones that really are diagrams" - without it, emptying the whole set would pass.
- **A move is not a rewrite.** Tasks 1 and 2 move substantial blocks. A faithful move is reviewable; a move plus an improvement is not. Note anything that reads awkwardly in its new home rather than fixing it in the same commit.
- **Migrated assertions get listed.** Tasks 1 and 2 both relocate existing tests. Report every assertion moved and where it went - a control dropped in a large diff is invisible otherwise.
