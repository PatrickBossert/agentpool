# Stakeholder Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "do we have representatives in governance and in the value-creating activities?" answerable continuously, and answerable in one place.

**Architecture:** Tasks 1-4 are Python and build on each other - roles, then assignments keyed on identity, then coverage intent, then the one calculation that reads all three. Task 5 is Jordan's view and Task 6 is PAM's report; both consume Task 4's endpoint and neither consumes the other.

**Tech Stack:** FastAPI, aiosqlite, pytest. React 18, TypeScript, Tailwind v3, Vitest, Testing Library, Lucide React.

## Global Constraints

- British English (`-ise`, `-our`, `-re`) in comments, copy, prompts, and test names.
- Spaced hyphen ` - ` in prose, never an em dash `—`. Hyphenated compound adjectives are fine.
- Lucide React SVG icons only. **No emoji in rendered content.**
- Never `sky-*` or `blue-*` Tailwind classes. Brand and surface tokens; amber is the warning convention.
- All raw SQL lives in `api/database.py`. `agents/tools/human_input.py` must not be modified.
- **Coverage is computed once, in the backend.** Two implementations of one calculation disagree the first time either changes - it happened twice in one day to the milestone arithmetic.
- Backend: `./venv/bin/pytest -q --ignore=tests/integration` (NOT bare `pytest`). Frontend: `npx vitest run` and `npx tsc --noEmit` from `ui/`.
- **Baselines: backend 853 passed / 2 skipped, frontend 340 passed.** Report both actual totals every task.
- Never `git add -A` or `git add .`. Stage by name.

---

### Task 1: A stakeholder can hold the role they actually have

**Files:**
- Modify: `ui/src/pages/StakeholderForm.tsx` - `LEVEL_OPTIONS`
- Modify: `ui/src/types.ts` if the role is typed narrowly
- Test: `ui/src/__tests__/StakeholderFormOrgs.test.tsx` (extend)

**Interfaces:**
- Consumes: nothing.
- Produces: the role vocabulary every later task keys on - `L0`, `L1`, `L2`, `L3`, `C`, `A`, `F`, `S`.

**Why:** Maya already writes `interview_scripts_c`, `_a`, `_f` and `_caf`. The instruments exist for eight roles and `LEVEL_OPTIONS` offers four, so a customer, regulator, frontline worker or corporate-services respondent cannot be recorded as one - let alone assigned or counted.

- [ ] **Step 1: Write the failing test**

```tsx
it('offers every role Maya writes an instrument for', async () => {
  renderForm()
  // Four seniority levels against a node, and four role-shaped types that attach to an
  // entity. Maya's scripts on disk cover all eight; the record covered half.
  for (const role of ['L0', 'L1', 'L2', 'L3', 'C', 'A', 'F', 'S']) {
    await waitFor(() =>
      expect(screen.getByRole('option', { name: new RegExp(`^${role}\\b`) })).toBeInTheDocument())
  }
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/StakeholderFormOrgs.test.tsx`
Expected: FAIL - no option matches `C`.

- [ ] **Step 3: Extend the vocabulary**

```tsx
const LEVEL_OPTIONS = [
  { value: '',   label: '- Select role -' },
  { value: 'L0', label: 'L0 - Executive / Board' },
  { value: 'L1', label: 'L1 - General Manager / VP' },
  { value: 'L2', label: 'L2 - Manager / Senior' },
  { value: 'L3', label: 'L3 - Operational / Analyst' },
  // Role-shaped rather than seniority-shaped: these attach to an entity rather than to a
  // position in the hierarchy. F and S carry a ground-truth execution rationale - what
  // actually happens, as against what the process says - whatever activities they support.
  { value: 'C',  label: 'C - Customer' },
  { value: 'A',  label: 'A - Auditor / Regulator' },
  { value: 'F',  label: 'F - Frontline worker' },
  { value: 'S',  label: 'S - Corporate services' },
]
```

The column is `TEXT` already, so no migration.

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, `tsc` clean.

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/StakeholderForm.tsx ui/src/__tests__/StakeholderFormOrgs.test.tsx ui/src/types.ts
git commit -m "feat(stakeholders): the eight roles Maya writes instruments for"
```

---

### Task 2: An assignment survives a rename

**Files:**
- Modify: `api/database.py` - `_migrate_stakeholder_node_assignments`, the helpers
- Modify: `api/routers/stakeholders.py` - the assignment endpoints
- Modify: `ui/src/api/endpoints.ts`
- Test: `tests/test_stakeholder_assignments.py` (create)

**Interfaces:**
- Consumes: Task 1's roles.
- Produces:

```
stakeholder_node_assignments
  project_id      existing
  stakeholder_id  existing
  node_id         'n' | 'n.n' | 'n.n.n' - the stable id
  node_level      'L1' | 'L2' | 'L3'    - which kind of node node_id names
  party_id        the entity whose work it is
  UNIQUE(project_id, stakeholder_id, node_id)
```

Plus `add_stakeholder_assignment` and `remove_stakeholder_assignment` alongside the existing bulk replace, and `POST`/`DELETE` endpoints for them.

**Why:** `node_key` is `'L2:Strategic Planning'` - level plus **label**. Rename an activity and every assignment to it silently stops matching; the stakeholder covers nothing and nothing says so. The value chain's stable ids exist for exactly this join and it does not use them.

The bulk `upsert` deletes every row and re-inserts, which is right for a full replace and wrong for one drag of one person onto one node - the view needs single-row operations or a dropped connection loses the lot.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stakeholder_assignments.py`, following the project fixture in `tests/test_milestone_baseline.py`.

```python
@pytest.mark.asyncio
async def test_an_assignment_survives_a_rename_of_its_node(client):
    """The defect the old key had. A stakeholder assigned to '1.1' is still assigned to it
    when Alex renames it - the label was never the identity."""
    await _project(client)
    s = await _stakeholder(client, level="L2")
    await _assign(client, s["id"], node_id="1.1", node_level="L2", party_id="GSUK")

    await _save_model(client, _model(activity_label="Renamed entirely"))

    assert [a["node_id"] for a in await _assignments(client)] == ["1.1"]


@pytest.mark.asyncio
async def test_an_assignment_records_the_party_that_owns_the_node(client):
    # Coverage and the drop guard both need it, and deriving it later from the model would
    # be wrong the moment a contribution moves.
    await _project(client)
    s = await _stakeholder(client, level="L2")
    await _assign(client, s["id"], node_id="1.1", node_level="L2", party_id="ISS")
    assert (await _assignments(client))[0]["party_id"] == "ISS"


@pytest.mark.asyncio
async def test_one_assignment_can_be_removed_without_touching_the_others(client):
    # The bulk replace deletes every row first. A drag that removes one person must not put
    # every other assignment at risk of a dropped connection.
    ...


@pytest.mark.asyncio
async def test_assigning_the_same_person_to_the_same_node_twice_is_idempotent(client):
    ...


@pytest.mark.asyncio
async def test_an_existing_label_keyed_assignment_is_migrated_to_its_id(client):
    """Existing rows are resolved against the current model, not discarded. A migration
    that silently dropped them would lose real work with no error."""
    ...


@pytest.mark.asyncio
async def test_a_label_that_no_longer_resolves_is_kept_and_reported(client):
    """A label matching nothing in the current model cannot be resolved, and dropping it
    silently is the failure mode this whole task exists to remove. It is preserved with a
    null node_id so somebody can decide."""
    ...
```

Fill the four bodies. The last two are the migration and matter most: write them before touching the schema.

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_stakeholder_assignments.py -q`
Expected: FAIL.

- [ ] **Step 3: Re-key the table**

In `_migrate_stakeholder_node_assignments`, add `node_id`, `node_level` and `party_id` guarded by `PRAGMA table_info`, following the `completed_at`/`baseline_date` idiom. Keep `node_key` for now: it is the only record of what an unresolvable row once meant.

Back-fill in the same migration by splitting `node_key` on `:` into level and label, then resolving the label against the current model's segments, activities and tasks. Resolved rows get `node_id` and `party_id`; unresolved rows keep a null `node_id` and their original `node_key`.

- [ ] **Step 4: Single-row operations and endpoints**

`add_stakeholder_assignment(conn, *, project_id, stakeholder_id, node_id, node_level, party_id)` - idempotent through the UNIQUE constraint, so a repeated drag is not an error.

`remove_stakeholder_assignment(conn, *, project_id, stakeholder_id, node_id)`.

`POST` and `DELETE /projects/{slug}/stakeholder-assignments/{stakeholder_id}/{node_id}`, and the matching client functions.

- [ ] **Step 5: Run the tests**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: PASS. Report the total, and say in your report how many rows the live `sp-gs-am` migration resolved and how many it could not - it currently holds zero, so a non-zero unresolved count means the resolver is wrong.

- [ ] **Step 6: Commit**

```bash
git add api/database.py api/routers/stakeholders.py ui/src/api/endpoints.ts tests/test_stakeholder_assignments.py
git commit -m "feat(stakeholders): assignments key on the node's id, not its label"
```

---

### Task 3: A deliberate exclusion is not a gap

**Files:**
- Modify: `api/database.py` - `_migrate_node_coverage_intent` and helpers
- Modify: `api/models.py`, `api/routers/stakeholders.py`
- Test: `tests/test_coverage_intent.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:

```
node_coverage_intent
  project_id  node_id  node_level  intent ('included'|'excluded')  reason  set_by  set_at
  UNIQUE(project_id, node_id)
```

`PUT /projects/{slug}/coverage-intent/{node_id}` taking `{node_level, intent, reason}`.

**Why:** on an 80-node chain a real programme interviews 30 to 40 people, so around half the chain is deliberately not interviewed. With no way to say so, every project reports a permanent shortfall - and a permanent shortfall stops being read.

**It is a table, not a field on the node.** Nodes live in `value_chain_model_v<n>.json`, which Alex rewrites on every run: an intent stored there would be erased by the next analysis. Keyed on the stable id in its own table, it survives every run Alex makes - which is what stable ids are for.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_a_node_is_included_by_default(client):
    # Absence of an opinion is not a decision to exclude.
    assert (await _intent(client, "1.1"))["intent"] == "included"


@pytest.mark.asyncio
async def test_excluding_a_node_requires_a_reason(client):
    """An exclusion nobody explained is indistinguishable from an oversight six months
    later, when the only evidence left is that nobody was assigned."""
    r = await _set_intent(client, "1.1", intent="excluded", reason="  ")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_an_exclusion_survives_a_value_chain_rewrite(client):
    # Alex rewrites the model on every run. An intent stored in it would not last a day.
    ...


@pytest.mark.asyncio
async def test_a_node_can_be_brought_back_into_scope(client):
    ...
```

- [ ] **Step 2: Run to verify they fail, then implement**

Run: `./venv/bin/pytest tests/test_coverage_intent.py -q`
Expected: FAIL - no route.

Migration in the established idiom; reason required and non-blank, rejected with 422, matching the re-baseline rule.

- [ ] **Step 3: Run the tests and commit**

```bash
git add api/database.py api/models.py api/routers/stakeholders.py tests/test_coverage_intent.py
git commit -m "feat(coverage): a node can be deliberately excluded, with a reason"
```

---

### Task 4: One coverage calculation

**Files:**
- Create: `api/services/coverage_service.py`
- Modify: `api/routers/stakeholders.py` - `GET /projects/{slug}/coverage`
- Test: `tests/test_coverage_service.py` (create)

**Interfaces:**
- Consumes: Tasks 2 and 3, plus the current model from `value_chain_store.load_model`.
- Produces:

```python
async def coverage_report(slug: str) -> dict
# {"levels": {"L1": {"assigned": 2, "unassigned": 1, "excluded": 0, "total": 3}, ...},
#  "nodes": [{"node_id": "1.1", "node_level": "L2", "party_id": "GSUK",
#             "label": "...", "assigned": [stakeholder_id, ...],
#             "intent": "included", "reason": ""}]}
```

**Why:** Jordan's view and PAM's report both need it, PAM reports daily and Jordan runs rarely - so reading his artefact would always give her the older answer. One implementation, one endpoint, two consumers.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_node_with_nobody_on_it_is_unassigned(): ...

def test_coverage_does_not_inherit_down_the_tree():
    """An executive on an L0 script is never asked the L2 or L3 questions, so covering a
    chain covers nothing beneath it. A fixture assigned at every level cannot tell an
    inheriting implementation from a correct one - this one assigns only at L1."""
    ...

def test_an_excluded_node_is_not_counted_as_unassigned():
    # And is still reported, with its reason. A test asserting only that it is absent from
    # the gap count would pass on an implementation that simply hid it.
    ...

def test_the_three_numbers_account_for_every_node():
    # assigned + unassigned + excluded == total, at every level. A node falling through
    # the classification would make every percentage quietly wrong.
    ...

def test_a_node_carries_the_party_that_owns_it():
    # The view needs it to guard the drop.
    ...
```

- [ ] **Step 2: Run to verify they fail, then implement**

Levels are counted separately and never merged into a single percentage: 35 of 80 with 40 excluded is a healthy programme and 35 of 80 with nothing excluded is not, and one figure cannot tell them apart.

- [ ] **Step 3: Run the tests and commit**

```bash
git add api/services/coverage_service.py api/routers/stakeholders.py tests/test_coverage_service.py
git commit -m "feat(coverage): one calculation, three numbers per level"
```

---

### Task 5: Jordan's Setup tab

**Files:**
- Create: `ui/src/components/tabs/JordanCoverageMap.tsx`
- Modify: `ui/src/components/AgentDetailPanel.tsx` - register it

**Settled:** the map is Jordan's **Setup** tab. Stakeholder assignment is configuration, not
a deliverable. His Output tab is reserved for reviewing stakeholder communications and
approvals, which is future functionality and not touched here.

**This displaces `TaylorSetupTab`**, which is currently registered against
`stakeholder_management` - Jordan's crew - and holds *Taylor's* invite chase rules. Jordan
must not define configuration for another agent. Move those rules out as part of this task;
where they go is recorded below and is not this task's to decide.

**Interfaces:**
- Consumes: Task 4's endpoint and Task 2's single-row assignment operations.
- Produces: test ids `coverage-node-<nodeId>`, `coverage-gap-<nodeId>`, `unassigned-stakeholder-<id>`.

**Why:** a stored answer to "who covers what" is wrong the moment the chain changes, and nothing says so. The map is derived on every render, so an activity Alex adds appears as a gap immediately, with no run by anybody.

- [ ] **Step 1: Write the failing tests**

```tsx
it('shows a node Alex has just added as a gap, with no run', async () => {
  // The whole point of a view. The fixture's model carries a node no assignment mentions.
  ...
})

it('highlights a stakeholder assigned to nothing', async () => {
  // As much a defect as an uncovered node: someone in the directory covering nothing is
  // either mis-recorded or was never needed.
  ...
})

it('does not accept a stakeholder onto a node another party owns', async () => {
  // 3.1@ISS is ISS's work. The entity list stops being a lookup and becomes a guard.
  ...
})

it('shows an excluded node as excluded rather than as a gap', async () => { ... })
```

- [ ] **Step 2: Run to verify they fail, then build**

The tab shows the governance team by role - question (a), answered by role not by node - the chain as a tree with each node's assignments, owner and intent, and the stakeholder directory beside it. People are dragged from the directory onto nodes. Both kinds of gap are highlighted.

Drag-and-drop follows the value chain grid's conventions: native HTML5 drag, the payload carrying what the drop target needs to decide, and a target that refuses rather than accepting and then undoing. Read `ValueChainGrid.tsx`'s `acceptsDrag` before writing this - it already solved the "do not promise a drop you will refuse" problem, including the trap where the drag-over cue and the drop guard disagree.

- [ ] **Step 3: Run the tests and commit**

```bash
git add ui/src/components/tabs/ ui/src/api/endpoints.ts ui/src/__tests__/CoverageMap.test.tsx
git commit -m "feat(coverage): Jordan's map is a live view with drag-and-drop assignment"
```

---

### Task 6: PAM reports coverage

**Files:**
- Modify: `api/services/pam_report_service.py`
- Modify: `ui/src/components/PamReportView.tsx`, `ui/src/types.ts`
- Test: `tests/test_pam_report_coverage.py` (create), `ui/src/__tests__/PamReportExport.test.ts`

**Interfaces:**
- Consumes: Task 4's `coverage_report`. **Not** Jordan's output.

**Why:** a gap is an issue PAM reports and it never blocks progress. She calls the calculation directly for the reason given in Task 4.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_the_report_carries_coverage_per_level(client): ...

@pytest.mark.asyncio
async def test_an_excluded_node_is_not_reported_as_a_shortfall(client):
    """Half a typical chain is deliberately not interviewed. Reporting that as a shortfall
    is how a report becomes something nobody reads."""
    ...

@pytest.mark.asyncio
async def test_coverage_is_read_from_the_service_not_from_jordans_output(client):
    # PAM reports daily and Jordan runs rarely. Reading his artefact would give her an
    # answer as old as his last run - and stale by construction after any change of Alex's.
    ...
```

- [ ] **Step 2: Implement, run everything**

Run: `./venv/bin/pytest -q --ignore=tests/integration`, then from `ui/`: `npx vitest run && npx tsc --noEmit`
Expected: both green. Report both totals - this is the last task, so the pair confirms nothing drifted.

- [ ] **Step 3: Commit**

```bash
git add api/services/pam_report_service.py ui/src/components/PamReportView.tsx ui/src/types.ts tests/test_pam_report_coverage.py ui/src/__tests__/PamReportExport.test.ts
git commit -m "feat(report): PAM reports coverage per level, excluding deliberate exclusions"
```

---

## Adjacent, deliberately not in this plan

**Taylor's tabs.** The invite chase rules displaced by Task 5 belong with Taylor, and his
Output tab should show a compact stakeholder list - invited / reminded[n] / completed - with
a burndown of the completion rate and a projected completion percentage.

Two things stop that being a task here.

**The panel is keyed by crew, not by agent.** `CREW_SETUP_OVERRIDE[crewKey]` gives one Setup
tab per crew, and Taylor shares `discovery_interviews` with the Stakeholder Interviewer and
the Synthesis Analyst - whose slot is already `AverySetupTab`, "voice interviewer
configuration". So Taylor's rules cannot get a tab of their own without either merging them
into a tab named for another agent - the same confusion this correction removes - or making
the panel agent-keyed, which is an architectural change affecting every crew.

The likely answer is that **crew-scoped tabs should be named and organised by crew**, with a
section per agent's concerns: `InterviewsSetupTab` holding Avery's voice configuration and
Taylor's chase rules as separate sections. Jordan and Alex are each alone in their crews, so
their tabs read as personal by coincidence rather than by design.

**The projection needs deciding, not guessing.** "Likely completion percentage" can be a
linear extrapolation of the current rate, a curve fitted to how each reminder round performed,
or a simple ratio against the interviews-complete milestone date. Those give materially
different numbers and a client will act on whichever is shown. That is a short design
conversation, not an implementation detail.

Until both are settled, Task 5 moves the chase rules to `discovery_interviews` unchanged, so
they stop being Jordan's without anything being redesigned in passing.
