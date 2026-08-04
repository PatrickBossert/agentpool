# Milestone Baselines and Slippage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every milestone a baseline that survives re-planning, and make Progress Against Plan show slippage against it.

**Architecture:** Tasks 1 and 2 are Python - the column, the baselining at activation, and the non-destructive re-baseline. Task 3 is a pure TypeScript helper with no rendering. Tasks 4 and 5 consume it in the milestone list and in Progress Against Plan, on screen and in the export. Task 3 gates 4 and 5; 1 gates 2.

**Tech Stack:** FastAPI, aiosqlite, pytest. React 18, TypeScript, Tailwind v3, Vitest, Testing Library, Lucide React.

## Global Constraints

- British English (`-ise`, `-our`, `-re`) in comments, copy, and test names.
- Spaced hyphen ` - ` in prose, never an em dash `—`. Hyphenated compound adjectives are fine.
- Lucide React SVG icons only. **No emoji in rendered content.**
- Never `sky-*` or `blue-*` Tailwind classes. Brand and surface tokens; amber is the warning convention.
- All raw SQL lives in `api/database.py`. `agents/tools/human_input.py` must not be modified.
- Working-day intervals use `workingDaysBetween` from `ui/src/utils/holidays.ts` with the project's excluded set - never calendar days, and never a second implementation.
- Backend: `./venv/bin/pytest -q --ignore=tests/integration` (NOT bare `pytest`). Frontend: `npx vitest run` and `npx tsc --noEmit` from `ui/`.
- **Baselines: backend 830 passed / 2 skipped, frontend 319 passed.** Report both actual totals every task.
- Never `git add -A` or `git add .`. Stage by name.

---

### Task 1: A milestone carries what it was promised

**Files:**
- Modify: `api/database.py` - the `project_milestones` CREATE, `_migrate_project_milestones`, and a new `baseline_milestones`
- Modify: `api/models.py` - `Milestone`
- Modify: `api/routers/commits.py:135` - `activate_project`
- Test: `tests/test_milestone_baseline.py` (create)

**Interfaces:**
- Consumes: `set_project_status`, already called by activation.
- Produces: `async baseline_milestones(conn, *, slug) -> int` returning how many were baselined. Milestones gain `baseline_date: str | None`.

**Why:** `due_date` is editable, so re-planning after a slip overwrites the original commitment. A project that slips four times and is re-planned four times currently shows as perfectly on track.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_milestone_baseline.py`, following the fixture in `tests/test_milestone_completion.py` - it creates a project through `client` and wipes its database and directory around each test.

```python
@pytest.mark.asyncio
async def test_activation_baselines_a_milestone_that_has_a_due_date(client):
    await _project(client)
    m = await _milestone(client, title="Kickoff", due_date="2026-08-10")
    await client.post(f"/projects/{SLUG}/activate")
    assert (await _get(client, m["id"]))["baseline_date"] == "2026-08-10"


@pytest.mark.asyncio
async def test_activation_leaves_an_undated_milestone_unbaselined(client):
    # A fixture where every milestone has a date cannot tell "baselines those with a date"
    # from "baselines everything". An undated milestone was never promised anything, and
    # inventing a baseline would manufacture a commitment nobody made.
    await _project(client)
    m = await _milestone(client, title="Unscheduled", due_date=None)
    await client.post(f"/projects/{SLUG}/activate")
    assert (await _get(client, m["id"]))["baseline_date"] is None


@pytest.mark.asyncio
async def test_activating_again_does_not_move_a_baseline(client):
    """Re-activating an in-flight project would otherwise adopt the slipped plan as the
    promise - the exact failure the baseline exists to prevent, arriving through the
    mechanism meant to prevent it."""
    await _project(client)
    m = await _milestone(client, title="Kickoff", due_date="2026-08-10")
    await client.post(f"/projects/{SLUG}/activate")
    await client.patch(f"/projects/{SLUG}/milestones/{m['id']}", json={"due_date": "2026-08-20"})
    await client.post(f"/projects/{SLUG}/activate")
    assert (await _get(client, m["id"]))["baseline_date"] == "2026-08-10"


@pytest.mark.asyncio
async def test_editing_the_plan_leaves_the_baseline_alone(client):
    # Assert the baseline explicitly. A test that only checks the new due date passes
    # while the baseline moves along with it, which is the whole defect.
    await _project(client)
    m = await _milestone(client, title="Kickoff", due_date="2026-08-10")
    await client.post(f"/projects/{SLUG}/activate")
    r = await client.patch(
        f"/projects/{SLUG}/milestones/{m['id']}", json={"due_date": "2026-08-20"}
    )
    assert r.json()["due_date"] == "2026-08-20"
    assert r.json()["baseline_date"] == "2026-08-10"


@pytest.mark.asyncio
async def test_a_milestone_added_after_activation_has_no_baseline(client):
    """Added scope is not on-plan delivery. Treating an absent baseline as no variance
    would report scope growth as success."""
    await _project(client)
    await client.post(f"/projects/{SLUG}/activate")
    m = await _milestone(client, title="New scope", due_date="2026-09-01")
    assert (await _get(client, m["id"]))["baseline_date"] is None
```

Write `_project`, `_milestone` and `_get` as small helpers over the existing endpoints. Activation is approver-gated by `caller_may_commit`, and the standard `client` fixture already satisfies it - `tests/test_commit_endpoint.py:75` calls `POST /projects/{slug}/activate` directly and then exercises approver-only routes. Follow that; do not weaken the gate to make a test pass.

- [ ] **Step 2: Run them to verify they fail**

Run: `./venv/bin/pytest tests/test_milestone_baseline.py -q`
Expected: FAIL - `baseline_date` is not a field.

- [ ] **Step 3: Add the column**

In `api/database.py`, add `baseline_date TEXT` to the `project_milestones` CREATE **and** to `_migrate_project_milestones`, guarded by the same `PRAGMA table_info` check the `completed_at` migration uses immediately above it. Comment it as what was promised, distinct from `due_date`, which is what is currently expected.

- [ ] **Step 4: Add the baselining helper**

```python
async def baseline_milestones(conn: aiosqlite.Connection, *, slug: str) -> int:
    """Record each dated milestone's current plan as what was promised.

    Only where no baseline exists: re-activating an in-flight project must not adopt its
    slipped plan as the promise. Only where a due date exists: an undated milestone was
    never promised anything.
    """
    cur = await conn.execute(
        "UPDATE project_milestones SET baseline_date = due_date "
        "WHERE slug = ? AND baseline_date IS NULL AND due_date IS NOT NULL",
        (slug,),
    )
    await conn.commit()
    return cur.rowcount
```

- [ ] **Step 5: Baseline on activation**

In `activate_project`, inside the existing `async with get_connection(slug) as conn:` block, call `baseline_milestones` alongside `set_project_status`, and return the count so the caller can report it:

```python
        await set_project_status(conn, slug=slug, status="active")
        baselined = await baseline_milestones(conn, slug=slug)
    return {"slug": slug, "status": "active", "milestones_baselined": baselined}
```

Add `baseline_date: str | None = None` to `Milestone` in `api/models.py`, beside `completed_at`.

- [ ] **Step 6: Run the tests**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS. Report the total.

- [ ] **Step 7: Commit**

```bash
git add api/database.py api/models.py api/routers/commits.py tests/test_milestone_baseline.py
git commit -m "feat(milestones): activation records what each milestone was promised"
```

---

### Task 2: Re-baselining, without destroying the original

**Files:**
- Modify: `api/database.py` - `milestone_baselines` table and `rebaseline_milestone`
- Modify: `api/models.py` - a request model
- Modify: `api/routers/milestones.py` - a new route
- Test: `tests/test_milestone_baseline.py`

**Interfaces:**
- Consumes: Task 1's `baseline_date`.
- Produces: `POST /projects/{slug}/milestones/{id}/rebaseline` taking `{baseline_date, reason}`, approver-gated like activation. `milestone_baselines` columns: `id`, `milestone_id`, `baseline_date`, `superseded_at`, `reason`, `set_by`.

**Why:** a change request that moves the plan is a legitimate event, but it must be its own deliberate action rather than a side effect of editing a date - and a baseline you can quietly overwrite is not a baseline.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_rebaselining_records_the_superseded_baseline(client):
    """Asserting only that the new baseline took effect proves nothing about whether the
    original survived, which is the entire reason for keeping a history."""
    await _project(client)
    m = await _milestone(client, title="Kickoff", due_date="2026-08-10")
    await client.post(f"/projects/{SLUG}/activate")

    r = await client.post(
        f"/projects/{SLUG}/milestones/{m['id']}/rebaseline",
        json={"baseline_date": "2026-08-24", "reason": "CR-014 approved"},
    )
    assert r.status_code in (200, 201)
    assert (await _get(client, m["id"]))["baseline_date"] == "2026-08-24"

    history = (await client.get(f"/projects/{SLUG}/milestones/{m['id']}/baselines")).json()
    assert [h["baseline_date"] for h in history] == ["2026-08-10"]
    assert history[0]["reason"] == "CR-014 approved"


@pytest.mark.asyncio
async def test_rebaselining_without_a_reason_is_refused(client):
    await _project(client)
    m = await _milestone(client, title="Kickoff", due_date="2026-08-10")
    await client.post(f"/projects/{SLUG}/activate")
    r = await client.post(
        f"/projects/{SLUG}/milestones/{m['id']}/rebaseline",
        json={"baseline_date": "2026-08-24", "reason": "  "},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_two_rebaselines_keep_both_originals_in_order(client):
    # One entry cannot distinguish "records the superseded baseline" from "records the
    # first baseline only", and a plan that moves twice is the normal case.
    ...
```

Fill the third test's body: baseline 10 Aug, re-baseline to 24 Aug, re-baseline to 31 Aug, and assert the history reads `["2026-08-10", "2026-08-24"]` in that order.

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_milestone_baseline.py -q -k rebaseline`
Expected: FAIL - 404, the route does not exist.

- [ ] **Step 3: Add the history table**

In `api/database.py`, a `_migrate_milestone_baselines` following the shape of `_migrate_project_milestones`, registered in the same place the other migrations are:

```sql
CREATE TABLE IF NOT EXISTS milestone_baselines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    milestone_id    INTEGER NOT NULL,
    baseline_date   TEXT NOT NULL,
    superseded_at   TEXT NOT NULL DEFAULT (datetime('now')),
    reason          TEXT NOT NULL,
    set_by          TEXT NOT NULL DEFAULT ''
)
```

- [ ] **Step 4: Add the operation**

`rebaseline_milestone(conn, *, milestone_id, slug, baseline_date, reason, set_by)`: read the current `baseline_date`, insert it into `milestone_baselines` **before** overwriting, then update. Return False when the milestone does not exist or has no baseline to supersede. Write the history row first - if the update fails afterwards the history holds a superseded date that is still current, which is recoverable; the reverse loses the original permanently.

- [ ] **Step 5: Add the routes**

In `api/routers/milestones.py`, `POST /{milestone_id}/rebaseline` and `GET /{milestone_id}/baselines`. Gate the POST with the same approver check activation uses - `caller_may_commit` - rather than a new rule. Reject a blank or whitespace-only reason with 422; a re-baseline nobody explained is indistinguishable from a mistake six months later.

- [ ] **Step 6: Run the tests**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS. Report the total.

- [ ] **Step 7: Commit**

```bash
git add api/database.py api/models.py api/routers/milestones.py tests/test_milestone_baseline.py
git commit -m "feat(milestones): re-baselining is explicit and keeps the original"
```

---

### Task 3: One variance calculation

**Files:**
- Modify: `ui/src/utils/milestones.ts`
- Modify: `ui/src/types.ts` - `Milestone` and `PamReportMilestone` gain `baseline_date`
- Test: `ui/src/__tests__/milestoneVariance.test.ts` (create)

**Interfaces:**
- Consumes: `workingDaysBetween` from `./holidays`, and the existing `daysLate`.
- Produces:

```ts
export type MilestoneVarianceState =
  | 'added_scope' | 'on_plan' | 'late' | 'at_risk' | 'recovered'

export interface MilestoneVariance {
  state: MilestoneVarianceState
  slip: number | null      // baseline -> actual, or -> current plan while outstanding
  replan: number | null    // baseline -> current plan
}

export function milestoneVariance(
  m: { baseline_date?: string | null; due_date: string | null;
       completed_at?: string | null; status: string },
  excluded?: Set<string>,
): MilestoneVariance
```

**Why:** three consumers need the same arithmetic - the milestone list, Progress Against Plan, and the export. Three implementations would disagree the first time one changed, which has already happened once on the export path.

- [ ] **Step 1: Write the failing tests**

```ts
const base = { status: 'pending', baseline_date: '2026-08-14', due_date: '2026-08-14',
               completed_at: null }

it('reports work with no baseline as added scope, never as on plan', () => {
  // A project that adds five milestones and delivers them against no baseline has not
  // delivered its plan. Treating an absent baseline as no variance reports scope growth
  // as success.
  expect(milestoneVariance({ ...base, baseline_date: null }).state).toBe('added_scope')
})

it('reports an outstanding milestone already past its baseline as at risk', () => {
  // The state today's view cannot express: not yet due, so it renders green, while its
  // current plan has already moved past what was promised.
  const v = milestoneVariance({ ...base, due_date: '2026-08-21' })
  expect(v.state).toBe('at_risk')
  expect(v.slip).toBe(5)
})

it('measures slip against the actual date once complete', () => {
  const v = milestoneVariance({ ...base, status: 'complete', completed_at: '2026-08-19' })
  expect(v.state).toBe('late')
  expect(v.slip).toBe(3)
})

it('measures slip against the current plan while outstanding', () => {
  // A fixture of only completed milestones cannot tell the two apart, and the outstanding
  // case is the one that gives warning.
  expect(milestoneVariance({ ...base, due_date: '2026-08-19' }).slip).toBe(3)
})

it('separates re-planning from delivery', () => {
  // Delivered exactly on a revised plan: no delivery slip against that plan, three days
  // against what was promised. One number cannot carry both answers.
  const v = milestoneVariance({
    ...base, due_date: '2026-08-19', status: 'complete', completed_at: '2026-08-19',
  })
  expect(v.replan).toBe(3)
  expect(v.slip).toBe(3)
})

it('reports a milestone re-planned late but delivered on the promise as recovered', () => {
  const v = milestoneVariance({
    ...base, due_date: '2026-08-21', status: 'complete', completed_at: '2026-08-14',
  })
  expect(v.state).toBe('recovered')
  expect(v.slip).toBeNull()
})

it('is on plan when nothing moved', () => {
  expect(milestoneVariance({ ...base, status: 'complete', completed_at: '2026-08-14' })
    .state).toBe('on_plan')
})

it("honours the project's excluded dates", () => {
  const v = milestoneVariance({ ...base, due_date: '2026-08-18' }, new Set(['2026-08-17']))
  expect(v.slip).toBe(1)
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/milestoneVariance.test.ts`
Expected: FAIL - `milestoneVariance` is not exported.

- [ ] **Step 3: Implement**

Slip and re-plan both return null rather than zero when nothing moved, matching `daysLate`, so a caller renders a badge on truth rather than on a number. Order the state checks so `added_scope` wins over everything - without a baseline no other question can be answered.

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, `tsc` clean. Report the total.

- [ ] **Step 5: Commit**

```bash
git add ui/src/utils/milestones.ts ui/src/types.ts ui/src/__tests__/milestoneVariance.test.ts
git commit -m "feat(milestones): one variance calculation for every consumer"
```

---

### Task 4: The milestone list shows variance, not just lateness

**Files:**
- Modify: `ui/src/components/tabs/PamSetupTab.tsx` - `MilestoneRow`
- Test: `ui/src/__tests__/milestoneVariance.test.ts` (extend, if the row is testable without a harness) - otherwise state in your report that the row is verified by `tsc` and reading, as the rest of that file is

**Interfaces:**
- Consumes: `milestoneVariance` from Task 3.
- Produces: badge test ids `milestone-variance-<id>`.

**Why:** the row currently shows `N days late` from `daysLate`, which measures against the current plan and so cannot see a re-planned slip at all.

- [ ] **Step 1: Replace the lateness badge with a variance badge**

The `daysLate` badge becomes one driven by `milestoneVariance`:

| State | Badge | Colour |
|---|---|---|
| `added_scope` | `Added scope` | `bg-surface text-muted` |
| `late` | `N days late` | amber |
| `at_risk` | `N days at risk` | amber |
| `recovered` | `Recovered` | teal |
| `on_plan` | nothing | - |

Keep the existing state badge beside it - `Completed` and `3 days late` are both true and the reader needs both. Where a milestone has been re-planned, put the baseline in the `title` attribute so the promised date is recoverable on hover: `Promised <baseline_date>, planned <due_date>`.

- [ ] **Step 2: Show the baseline in the detail row**

The detail already shows Planned and Actual. Where `baseline_date` differs from `due_date`, add a third, read-only: **Promised**. Read-only deliberately - moving it is re-baselining, which is Task 2's approver-gated action and not a date picker.

- [ ] **Step 3: Run the tests and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, `tsc` clean.

- [ ] **Step 4: Commit**

```bash
git add ui/src/components/tabs/PamSetupTab.tsx ui/src/__tests__/
git commit -m "feat(milestones): the list shows variance against the promise"
```

---

### Task 5: Progress Against Plan shows the slip

**Files:**
- Modify: `ui/src/components/PamReportView.tsx` - headline, timeline, `buildPrintHtml`
- Modify: `ui/src/components/GanttReadOnly.tsx` - the baseline marker
- Test: `ui/src/__tests__/PamReportExport.test.ts`, `ui/src/__tests__/milestoneVariance.test.ts`

**Interfaces:**
- Consumes: `milestoneVariance`, and `scheduleContext` which already computes the excluded set once for both the screen and the export.
- Produces: `GanttMilestone` gains `baseline_date`; test id `delivery-movement`.

**Why:** per-milestone lateness answers "which one hurt us" and never "are we in trouble".

- [ ] **Step 1: Write the failing tests**

```ts
it('states how far delivery has moved, in working days', () => {
  const html = buildPrintHtml(report([
    milestone({ id: 1, baseline_date: '2026-08-14', due_date: '2026-08-14',
                completed_at: '2026-08-14', status: 'complete' }),
    milestone({ id: 2, baseline_date: '2026-08-21', due_date: '2026-08-28',
                completed_at: null, status: 'pending' }),
  ]))
  expect(html).toContain('5 working days')
})

it('reads the movement from the last baselined milestone, not the last one', () => {
  // A single piece of added scope on the end would otherwise silently become the
  // project's delivery date - a number put in front of a client measuring work nobody
  // committed to.
  const html = buildPrintHtml(report([
    milestone({ id: 1, baseline_date: '2026-08-14', due_date: '2026-08-21',
                completed_at: null, status: 'pending' }),
    milestone({ id: 2, baseline_date: null, due_date: '2026-12-01',
                completed_at: null, status: 'pending' }),
  ]))
  expect(html).toContain('5 working days')
  expect(html).not.toContain('December')
})

it('says delivery is on the promised date when nothing has moved', () => {
  ...
})
```

Fill the third. Add a matching on-screen test asserting `delivery-movement` renders the same figure, so screen and export cannot diverge - they did once already.

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/PamReportExport.test.ts`
Expected: FAIL.

- [ ] **Step 3: The headline**

Above the timeline, one line computed from the last milestone **with a baseline**, comparing its baseline against its actual or current plan: *"Delivery has moved 5 working days"*, or *"Delivery is on the promised date"*. Amber when it has moved, muted when it has not.

- [ ] **Step 4: The baseline marker on the Gantt**

`GanttMilestone` gains `baseline_date`. Where it differs from the date the marker is drawn at, render a hollow marker at the baseline position and shade the span between the two. Slippage then reads as a horizontal distance rather than a number - five milestones each slipping two days becomes a staircase drifting right.

Keep the existing marker as the solid one, so nothing already drawn moves.

- [ ] **Step 5: The export table**

The Progress Against Plan table gains a **Promised** column before Planned. The lateness cell uses `milestoneVariance` rather than `daysLate`, so a re-planned slip appears there too.

- [ ] **Step 6: Run everything**

Run: `cd ui && npx vitest run && npx tsc --noEmit`, then `./venv/bin/pytest -q --ignore=tests/integration`
Expected: both green. Report both totals - this is the last task, so the pair confirms nothing drifted.

- [ ] **Step 7: Commit**

```bash
git add ui/src/components/PamReportView.tsx ui/src/components/GanttReadOnly.tsx ui/src/__tests__/
git commit -m "feat(report): Progress Against Plan shows slippage against the promise"
```
