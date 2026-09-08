# One mechanism, and it has a scope - implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reviewer's correction becomes a proposed skill, and the reviewer decides at approval whether it applies to this engagement or to all of them. The notes mechanism retires.

**Architecture:** `skills` gains `scope` (`project` | `global`) beside the `source_project` it already carries. Injection filters on it. `ReviewDialog`'s existing `intent='skill'` - which currently sets a column nothing reads - routes into the proposal queue. `agent_skill_notes`, `create_skill_note` and the notes half of `_fetch_skill_notes` are deleted.

**Spec:** `docs/superpowers/specs/2026-09-08-one-mechanism-scoped-design.md`

## Global Constraints

- **British English** - `-ise`, `-our`, `-re`, Oxford comma, spaced ` - ` en dash, **never an em dash**.
- **`brand` tokens only**, never `sky-*`/`blue-*`. Lucide icons, **no emoji**. `describeError` imported from `ui/src/utils/describeError.ts`, never copied.
- **`skills` and `agent_skill_notes` are in `system.db`, which has NO version gate.** New columns go in `init_system_db` as `CREATE TABLE IF NOT EXISTS` plus `ALTER`. **Do not bump `_SCHEMA_VERSION`** - it gates *project* databases, and bumping it re-runs every project migration for a table in a database it does not govern. This is the opposite of the rule for a project table.
- **Baselines: backend 2779 passed / 2 skipped / 12 deselected, frontend 858 / 95 files, `tsc --noEmit` clean.** Establish all three yourself, twice, before changing anything.
- **Isolate every pytest run**: export `DATABASE_DIR`, `PROJECTS_DIR` and `DATA_DIR` to a private temporary directory. `tests/conftest.py` fixes them at a shared path and rmtree's it at import time.
- **An async fixture needs `@pytest_asyncio.fixture`.** `pytest.ini` sets `asyncio_mode = strict`, under which a plain `@pytest.fixture` on an `async def` is handed over as an un-awaited async generator - body never runs, setup and teardown both silently skipped.
- **Power-check each property separately**, confirm each mutation **landed** by reading the file back, clear `__pycache__` between mutation and revert, and report **which** test caught it.
- Stage explicit paths. **Never `git add -A`.** Write nothing to `data/`. Do not restart the server on :8000. No real third-party call.

---

### Task 1: A skill knows where it applies

**Files:** Modify `api/database.py`, `api/services/skills_service.py`, `api/services/run_service.py`; Test: new `tests/test_skill_scope.py`

**Interfaces:**
- Produces: `skills.scope`, `'project' | 'global'`, NOT NULL, defaulting to `'project'`. Tasks 2 and 3 consume it.

- [ ] **Step 1: Report the current shape.** `skills` holds 53 rows, all `approved`, all written when global was the only thing a skill could be. Confirm the count and report every reader of the table - `_fetch_skill_notes` in `run_service.py` is the one that injects.

- [ ] **Step 2: Add the column in `init_system_db`**, and **migrate the existing rows to `global`** - Patrick's decision, 8 September. New rows default to `project`. Those are two different values and the difference is the whole migration: the 53 are being affirmed as universal, and everything after them must earn it.

- [ ] **Step 3: Write the failing test - the migration and the default are not the same fact**

```python
async def test_the_existing_skills_are_global_and_a_new_one_is_not():
    # Two assertions because they are two decisions. A column defaulting to 'global' would
    # satisfy the first and silently make every future proposal universal.
    assert await scope_of(existing_skill_id) == "global"
    new_id = await propose_skill(...)
    assert await scope_of(new_id) == "project"
```

- [ ] **Step 4: Filter the injection.** `_fetch_skill_notes(crew_name, slug)` already takes the slug. A skill reaches a prompt when it is `approved` **and** (`scope='global'` **or** `source_project=slug`).

- [ ] **Step 5: Write the failing tests - three, and the middle one is the point**

A global skill reaches project A and project B. A project-scoped skill on A reaches A. **A project-scoped skill on A does not reach B** - assert the injected text, not the row. The third is the property; the first two are the controls without which a filter that dropped everything, or one that dropped nothing, would pass.

- [ ] **Step 6: An unattributable row.** A `project`-scoped skill with a NULL `source_project` matches no project and reaches nothing. Assert it, and say whether any writer can produce one.

- [ ] **Step 7: Suites twice. Power-check by inverting the filter, then by removing it. Commit.**

---

### Task 2: The reviewer decides the scope, and the default is narrow

**Files:** Modify `api/routers/skills.py`, `ui/src/pages/AdminSkills.tsx`, `ui/src/api/skills.ts`, `ui/src/types.ts`; Test: extend `tests/test_skill_proposal.py`, `ui/src/__tests__/AdminSkillsQueue.test.tsx`

**Interfaces:**
- Consumes: `scope` from Task 1.
- Produces: `PATCH /admin/skills/{id}` accepts `scope`; approving without one leaves `project`.

- [ ] **Step 1: Declare `scope` on the TypeScript type as required.** CLAUDE.md records four `ProjectSettings` fields that survived a save only on an untyped spread, and the fifth costs the same. A dropped key here silently widens a rule to every engagement.

- [ ] **Step 2: Write the failing test - assert what is SENT**

```ts
it('sends the scope the reviewer chose', async () => {
  // Not what the radio renders. CLAUDE.md records twelve assertions on this project that
  // passed without testing what they were named for, and one of them was a radio.
  renderQueue(); choose('applies everywhere'); click(approve)
  expect(vi.mocked(skillsApi.update).mock.calls[0][1]).toMatchObject({ scope: 'global' })
})
```

- [ ] **Step 3: The default is `project` when nothing is chosen**, asserted on the **stored row** rather than on the request - a body that omits the key and a body that sends `'project'` are different requests and must reach the same row.

- [ ] **Step 4: The control - a reviewer can still widen.** Without it, a form that hardcoded `project` would pass Step 3 perfectly.

- [ ] **Step 5: Say what widening means, next to the button that does it.** Approving a global skill changes that agent's behaviour on every engagement, including ones the reviewer has never seen. Bind the sentence to the control with `aria-describedby`, as the existing consequence note does.

- [ ] **Step 6: Suites, `tsc` clean, power-check Steps 2, 3 and 4 separately. Commit.**

---

### Task 3: The correction becomes a proposal, and the notes mechanism goes

**Files:** Modify `api/routers/reviews.py` (or wherever `intent` is handled), `api/services/skills_service.py`, `api/services/run_service.py`, `api/database.py`, `ui/src/components/ReviewDialog.tsx`; Delete `create_skill_note` and `agent_skill_notes`; Test: new `tests/test_review_intent_proposes.py`

- [ ] **Step 1: Report where `intent='skill'` goes today**, and confirm CLAUDE.md's claim that it sets `kind='skill'` on `output_changes` and nothing reads it. If anything does read it, say so - that changes this task.

- [ ] **Step 2: Route it.** `intent='skill'` calls `propose_skill` with the reviewer's text, the slug, and the agent it is about. `intent='change_request'` is unchanged and still reaches the agent through `_fetch_change_requests`.

- [ ] **Step 3: Write the failing test - the row, not the response**

`intent='skill'` has never produced anything, so a 200 proves nothing. Assert a pending row exists, carries the slug, and is scoped `project`.

- [ ] **Step 4: Assert the change-request path is untouched.** The same dialog, the other intent, still reaches the agent's next run. This is the half a careless routing change breaks silently - the reviewer asked for a revision and would get a skill proposal instead of one.

- [ ] **Step 5: Delete `agent_skill_notes`, `create_skill_note`, `_note_may_travel` and the notes half of `_fetch_skill_notes`.** One live row exists and it is test data. Nothing is lost: `run_service.py` states in its own comment that a reviewer's note reaches the agent through `_fetch_change_requests`.

- [ ] **Step 6: Write the failing test - the absence, by mechanism**

```python
def test_nothing_reads_the_notes_table():
    # Asserted over the source, not by the table being empty - an empty table passes against
    # a reader that would fill it on the next review.
    assert "agent_skill_notes" not in _non_test_sources()
```

- [ ] **Step 7: Suites twice, frontend and `tsc` clean. Power-check Steps 3, 4 and 6. Commit.**

---

### Task 4: Document it

**Files:** Modify `CLAUDE.md`

- [ ] **Step 1: State the rule.** One mechanism: a correction becomes a proposal, a human approves it, and the approval carries a scope. Project is the default and global is the deliberate act.

- [ ] **Step 2: Record what the four sp61 Criticals actually were** - one absence seen from four directions, material with no scope defaulting to the widest scope - and that the scope column is what closes the class rather than the four guards.

- [ ] **Step 3: Correct what retires.** The captured-not-routed `intent='skill'` paragraph, the notes half of the egress material, and `_note_may_travel`'s row in whatever table names it. A file that still describes a deleted mechanism is worse than one that never described it.

- [ ] **Step 4: Record the 53.** They are global because global was the only option when they were written, and no one re-read them. A reviewer who finds one that belonged to a single engagement demotes it.

- [ ] **Step 5: Suites unchanged. Both counts stated. Commit.**

---

## Self-Review

**Spec coverage:** scope column and injection filter (1), reviewer's choice and the narrow default (2), the correction becoming a proposal and notes retiring (3), documented (4). The spec's decision that an approved project-scoped skill is not offered as a deduplication candidate falls out of Task 1's filter and needs no separate task - but Task 1 Step 5's third assertion is what proves it.

**Placeholder scan:** none. Tasks 1 and 3 each open by establishing facts from the code, because a brief on this project has been wrong about the codebase more than a dozen times.

**Type consistency:** `scope: 'project' | 'global'` is produced in Task 1, declared required in TypeScript in Task 2, and written by Task 3's proposal path.

**Not in scope:** an approval gate for anything other than skills; retiring `output_changes.kind`; re-reading the 53.

**One ordering note:** Task 3 could precede Task 2, but a reviewer needs somewhere to choose a scope before the queue starts filling from a second source.
