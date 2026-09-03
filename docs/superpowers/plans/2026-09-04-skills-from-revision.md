# Skills proposed from a revision - implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An agent that has just revised its work in response to a send-back proposes the general rule behind the correction, as a pending skill a human approves. A near-duplicate of an existing skill or pending suggestion increments a count rather than creating a row, so recurrence sorts evidence above guesswork.

**Architecture:** `SkillProposalTool`, available to any agent producing a reviewable output, writes `status='pending'` rows to the existing `skills` table in `system.db`. `_fetch_skill_notes` already reads `status='approved'`, so a proposal reaches no prompt until approved. Deduplication is by meaning, not string equality, and a match increments `occurrences`.

**Spec:** `docs/superpowers/specs/2026-09-04-skills-from-revision-design.md`

## Global Constraints

- **British English** - `-ise`, `-our`, `-re`, Oxford comma, spaced en dash ` - `, never an em dash.
- **`brand` tokens only**, never `sky-*`/`blue-*`. Lucide icons, no emoji. `describeError` from `ui/src/utils/describeError.ts`.
- **Python 3.13** via `./venv/bin/python`. No ORM - raw SQL in `api/database.py`.
- **`skills` is in `system.db`, which has NO version gate.** New columns go in `init_system_db` as `CREATE TABLE IF NOT EXISTS` plus `ALTER`. **Do not bump `_SCHEMA_VERSION`** - it gates *project* databases, and bumping it would re-run every project migration for a table it does not govern. This is the opposite of the rule for a project table; check which database you are touching.
- **Backend suite twice with identical counts.** Baseline **2366 passed, 2 skipped, 12 deselected**. Frontend **664**, `tsc --noEmit` clean. Establish both from HEAD yourself - counts in documents here have been stale six times.
- **Power-check each property separately**, confirm each mutation **landed**, and check **which** test caught it. All three have failed on this codebase.
- Stage explicit paths. **Never `git add -A`.** Write nothing to `data/`. Do not restart the servers on :8000 or :3000.

---

### Task 1: A proposal reaches the queue and never reaches a prompt

**Files:** Modify `api/database.py`, `api/services/skills_service.py`; Test: new `tests/test_skill_proposal.py`

**Interfaces:**
- Produces: `propose_skill(agent_name, description, source_project, source_ref) -> dict` returning what happened - created, or matched an existing row and incremented it. Tasks 2 and 3 consume it.

- [ ] **Step 1: Report the current shape.** `skills` holds 54 rows, all `status='approved'`, `source` of `baseline` (43) or `manual` (11), and `source_project` NULL on every one. Confirm, and report every reader of the table - `_fetch_skill_notes` in `run_service.py` is the one that matters.

- [ ] **Step 2: Add the columns** in `init_system_db`: `occurrences INTEGER NOT NULL DEFAULT 1` and `proposed_by_agent TEXT`. `source_project` already exists - populate it rather than adding another.

- [ ] **Step 3: Write the failing test - the safety property first**

```python
async def test_a_pending_proposal_never_reaches_a_prompt():
    await propose_skill("interaction_designer", "Some proposed rule", "sp-gs-am", "SC-014")
    injected = await _fetch_skill_notes("assessment_design")
    assert "Some proposed rule" not in injected
```

This is the property that makes free proposal safe. Assert **what reaches the prompt**, not what the table holds - CLAUDE.md records seven defects of exactly that shape.

- [ ] **Step 4: Write `propose_skill`**, inserting `status='pending'`. Nothing else changes: `_fetch_skill_notes` already filters on `approved`, so this step should require no change to it. **If it does, say so - that would mean the filter was not doing what the docstring claims.**

- [ ] **Step 5: Suites twice. Power-check by flipping the insert to `status='approved'` and confirming Step 3's test fails. Commit.**

---

### Task 2: A duplicate is evidence, not noise

**Files:** Modify `api/services/skills_service.py`; Test: extend

- [ ] **Step 1: Read `check_specificity` and `extract_skills_many` first and report what each does.** Both call Haiku and are currently reachable only from the admin page. You are adding a third question - "is this the same rule as one we already hold?" - and it belongs beside them.

- [ ] **Step 2: Write the failing test - and word the duplicate differently**

```python
async def test_a_differently_worded_duplicate_increments_rather_than_inserts():
    await propose_skill("interaction_designer",
        "Keep confidentiality in the welcome and purpose in the framing", "p1", "SC-014")
    before = await count_skills("interaction_designer")
    await propose_skill("interaction_designer",
        "The opening should state privacy; the framing should state what the interview covers",
        "p2", "SC-031")
    assert await count_skills("interaction_designer") == before
    assert await occurrences_of(...) == 2
```

**The two strings must not match textually.** An exact-match test passes against a comparison that only catches identical text, which is not what duplicate means here - and the recurrence signal would then never fire.

- [ ] **Step 3: Check against approved skills AND pending suggestions.** The pending set is the one that matters for recurrence: the second occurrence of a rule nobody has approved yet is exactly the evidence the queue needs.

- [ ] **Step 4: A match increments `occurrences` and records the new provenance.** Decide how provenance accumulates - a second `source_project` column would be wrong; say what you chose.

- [ ] **Step 5: A genuinely new proposal creates a row with `occurrences` 1.** The control - without it, a comparison that called everything a duplicate would pass Step 2. Power-check each separately. Commit.

---

### Task 3: The agent proposes, and cannot damage the revision by doing so

**Files:** Create `agents/tools/skill_proposal.py`; Modify `agents/tools/registry.py`, the revision instruction; Test: new

- [ ] **Step 1: Read `_pending_script_revisions` in `run_service.py`.** It is the block telling an agent what was sent back. The proposal instruction belongs with it - the agent revises first, then proposes.

- [ ] **Step 2: Build `SkillProposalTool`** calling `propose_skill`. Register it for agents that produce a reviewable output, **not for Maya alone** - the requirement is that any agent which can be sent work back can propose.

- [ ] **Step 3: Write the failing test - a broken proposal must not break the revision**

```python
async def test_a_failing_proposal_does_not_fail_the_run():
    # propose_skill raises; the crew still completes and the artefact is unchanged
```

The reviewer asked for a revision, not a skill. Assert the artefact, not only the status.

- [ ] **Step 4: Instruct the agent to propose the general rule, not the note.** The worked example is real and belongs in the prompt: the SC-014 feedback was *"'not a performance review' appears twice, and the framing repeats the welcome"*; the rule is *"the welcome carries privacy and tone, the framing carries the interview's purpose"*. One is about a script, the other about every script.

- [ ] **Step 5: Suites twice. Power-check the failure isolation by making the tool raise. Commit.**

---

### Task 4: The queue, ordered by evidence

**Files:** Modify the admin skills page and its API; Test: frontend

- [ ] **Step 1: Report what the admin skills page shows today**, and whether it can display a `pending` row at all - all 54 existing rows are `approved`, so the pending path has never been exercised.

- [ ] **Step 2: Pending suggestions sort by `occurrences`, descending.** A rule seen three times sits above one seen once. Show the count and the provenance - a reviewer approving a global behaviour change should see what evidence it rests on.

- [ ] **Step 3: Approve and reject.** Approval flips `status`, at which point `_fetch_skill_notes` picks it up on the next run and the agent's behaviour changes on every engagement. Say that in the UI copy - it is the most consequential button on the page.

- [ ] **Step 4: Assert what is sent, not what renders.** Eleven tests across recent branches passed without testing what they were named for; assume yours may be the twelfth.

- [ ] **Step 5: Frontend suite, `tsc` clean, power-check, commit.**

---

### Task 5: Document the rule

**Files:** Modify `CLAUDE.md`

- [ ] **Step 1: State the requirement, not the instance.** *An agent that can be sent work back should propose the general rule behind the correction it just made.* Then: proposals are `pending` and reach no prompt until approved; a near-duplicate increments occurrences rather than inserting, so recurrence is the evidence a reviewer approves from; and the skills table is in `system.db`, so it takes no `_SCHEMA_VERSION` bump.

- [ ] **Step 2: Record what is still not connected.** The generic review door's `intent='skill'` sets `kind='skill'` on `output_changes` and nothing reads it; `kind` has only ever held `change_request` and `unclassified`. Leave it captured-not-routed and say so, rather than letting the next reader assume it works.

- [ ] **Step 3: Suites unchanged. Both counts stated. Commit.**

---

## Self-Review

**Spec coverage:** proposal is pending and never injected (1), duplicate detection by meaning (2), duplicates increment rather than insert (2), the tool is generic across agents (3), a failing proposal cannot damage the revision (3), the queue orders by evidence (4), the rule documented (5).

**Placeholder scan:** none. Tasks 1, 2 and 4 each open by establishing facts from the code, because briefs here have been wrong more than a dozen times.

**Type consistency:** `propose_skill(agent_name, description, source_project, source_ref) -> dict` is defined in Task 1 and consumed in 2 and 3. It returns what happened rather than a bare id, because a caller needs to distinguish created from incremented.

**Not in scope:** project-scoped skills; retiring or superseding an approved skill; measuring whether an approved skill changed the output - worth doing and needs a baseline this does not create; routing the generic door's `intent='skill'`.

**One ordering note:** Task 4 could precede Task 3, but the queue is easier to build against real pending rows than fabricated ones, and Task 3 is what produces them.
