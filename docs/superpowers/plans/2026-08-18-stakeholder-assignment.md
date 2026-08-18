# Stakeholder assignment - a durable mapping, made by hand, reported on

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote stakeholder-to-value-chain assignment from a transient step inside an orchestration run to a durable project fact, made by hand in Jordan's setup tab, reported by Jordan, and flagged by PAM when coverage is poor in either direction.

**Architecture:** `stakeholder_assignments` is re-keyed from `orchestration_run_id` to the project, and references a value chain **node id** rather than a `node_label`. The existing `Assignment.tsx` surface moves into Jordan's setup tab. Coverage is computed from the assignments and the active value chain nodes, reported in Jordan's output and raised by PAM past a threshold.

**Tech Stack:** Python 3.13, aiosqlite, FastAPI, React 18 + TypeScript.

## Why

`stakeholder_assignments` is keyed on `orchestration_run_id`, so assignments are an event inside a run rather than a fact about the project: they cannot be made before the first run, they do not survive between runs, and nothing that is not a run can read them. The table holds **zero rows**. `Assignment.tsx` is routed at `/:slug/assignment` and reached from nowhere - no nav link, no tab.

That is why the Stakeholder Manager holds no tool that can read the mapping it exists to produce, and why `_resolve_script_id` has to guess a script from a `node_label`. Patrick: the mapping is "a vital part of the flow" - stakeholders are mapped to the value chain, and those mappings determine who is interviewed with which script.

**It stays manual.** Job titles do not carry enough detail to automate the mapping, so this is a human activity with machine reporting, not an agent task.

## Global Constraints

- **British English** - `-ise`, `-our`, `-re`, Oxford comma, spaced en dash ` - `, never an em dash.
- **`brand` tokens only**, never `sky-*`/`blue-*`. Lucide icons, no emoji. `describeError` from `ui/src/utils/describeError.ts`.
- **Python 3.13** via `./venv/bin/python`. No ORM - raw SQL in `api/database.py`.
- **A new `_migrate_*` function must bump `_SCHEMA_VERSION` in the same change** and be added to the block `get_connection` runs. CLAUDE.md: forgetting fails unsafe, not loudly.
- **Backend suite twice with identical counts.** Baseline **1915 passed, 2 skipped, 12 deselected**. Frontend **585**, `tsc` clean.
- **Seed synthetic stakeholders into `sp-gs-am` itself.** Patrick, 2026-08-18: it is a **test run ahead of a similar live project**, not a client engagement - which is why no interviews have been carried out yet. `dev_mode` is already `True` on it and `DEV_MODE_ADDRESS` is already his own address, so every interview invitation reaches him and nobody else. He will run the first interviews himself to feed real material into downstream synthesis.
  **Synthetic rows must be identifiable and removable** - they have to come out cleanly before the real engagement. Decide how and say.
  **Known blocker, his to clear, not yours:** `FROM_EMAIL` is `noreply@taskreimagination.ai` and the domain is unverified in Resend, so sends 403. It blocks the interview run, not this build.
- Clear `__pycache__` between a mutation and its revert. `git checkout` cannot revert a mutation to a new untracked file - copy it aside and verify with `diff`.
- Stage explicit paths. **Never `git add -A`.** Do not restart the servers on :8000 or :3000.

---

### Task 1: Assignments become a project fact

**Files:** Modify `api/database.py`, `api/routers/assignment.py`; Test: `tests/test_stakeholder_assignment.py` (create)

- [ ] **Step 1: Establish the current shape and report it**

`stakeholder_assignments` is `(id, orchestration_run_id, stakeholder_id, level, node_label, created_at)`, zero rows, written by a DELETE-then-INSERT in `api/database.py:3133`. Confirm that, find every reader and writer, and report them before changing anything. `fetch_stakeholder_assignments` is imported in `run_service.py`; establish what it feeds.

- [ ] **Step 2: Re-key to the project, and to a node id**

Drop `orchestration_run_id`, or keep it as nullable provenance and say which you chose. Replace `node_label` with the value chain **node id** - CLAUDE.md: ids are a permanent contract, and label-matching is what makes `publish` 404. Keep `level` only if something reads it; report if nothing does.

The table is empty, so this is a free re-key: no backfill, no migration of rows. The **stakeholders** table is not touched.

- [ ] **Step 3: Many-to-many is the point.** Several stakeholders on one activity is expected - frontline workers especially - and is never a duplicate. A uniqueness constraint, if any, is on the *pair*.

- [ ] **Step 4: Test, power-check, commit.** Assert an assignment survives a second orchestration run, which the old shape could not do.

---

### Task 2: Synthetic stakeholders, in a scratch project

**Files:** Create `scripts/seed_synthetic_stakeholders.py`; Test: as above

- [ ] **Step 1: Seed `sp-gs-am`, and make the rows removable**

~60 synthetic stakeholders against its ~87 value chain activities. This is a test run, so seeding it directly is what is wanted - but the rows must carry something that identifies them as synthetic, so they can be removed cleanly before the real engagement. The two real stakeholders (Patrick Bossert, Dougie McCrone) must be untouched and must remain distinguishable.
  **Back up `data/sp-gs-am.db` before the first apply**, to `data/sp-gs-am.pre-synthetic-<date>.db`, matching the existing convention.

- [ ] **Step 2: Make them plausibly shaped** - names, job titles, organisations, entities and levels spread across the value chain, so the assignment UI and the coverage report are exercised at real scale rather than on three rows.

- [ ] **Step 3: Idempotent, and clearly synthetic.** Safe to run twice. A synthetic row must be identifiable as such - decide how and say.

- [ ] **Step 4: Test, commit.** Do not run it against `data/` beyond the scratch project you created.

---

### Task 3: Jordan's setup tab

**Files:** Modify `ui/src/pages/Assignment.tsx` and Jordan's setup tab component, `ui/src/router.tsx` if needed

- [ ] **Step 1: Find Jordan's setup tab.** Jordan Williams is `stakeholder_manager`. The agent panel's Setup tab is the established home for an agent's configuration - read how Maya's works before building.

- [ ] **Step 2: Move the assignment surface into it.** Assign stakeholders to value chain activities by hand, many-to-many, grouped usefully - CLAUDE.md notes Jordan's existing tool groups by entity so `ISS` and `ISS Ltd` sit together and drag together.

- [ ] **Step 3: It must work before any orchestration run**, which is the defect being fixed.

- [ ] **Step 4: Test what is sent**, not what renders - `ui/src/__tests__/client.test.ts` is the axios-adapter pattern. Power-check, commit.

---

### Task 4: Coverage, reported and raised

**Files:** Modify the stakeholder_management crew's output, `api/services/pam_report_service.py`; Test: as above

- [ ] **Step 1: Compute coverage from the assignments and the active value chain nodes**

Two proportions, both derived:

- activities with **no** stakeholder, over all active activities
- stakeholders assigned to **nothing**, over the roster

- [ ] **Step 2: Jordan reports the assignment in output.** The stakeholder_management crew's output carries the mapping and both proportions.

- [ ] **Step 3: PAM raises an issue past 10% in either direction, and reports the number**

Patrick: "if there's more than a 10% mismatch in proportion, either way, PAM should report the number as an issue." Report the count, not a verdict - a human judges. **100% coverage is not expected and its absence is not an issue**; many-to-one is normal and never counts as a mismatch.

Put the threshold in one named constant with a comment saying it is a judgement, not a law.

- [ ] **Step 4: Assert both directions independently** - a roster fully assigned with uncovered activities, and full activity coverage with unassigned stakeholders. **Revert each condition separately**: a shared threshold check can let one direction mask the other.

- [ ] **Step 5: Power-check, commit.**

---

## Self-Review

**Spec coverage:** durable re-key (1), node id not label (1), many-to-many (1), synthetic data (2), manual UI in Jordan's setup tab (3), Jordan reports (4), PAM raises past 10% either way (4).

**Placeholder scan:** none. Tasks 1, 2 and 3 each open by establishing facts from the code, because briefs on this project have been wrong about details ten times in recent slices.

**Type consistency:** the node id from Task 1 is what Tasks 3 and 4 read. The coverage proportions from Task 4 Step 1 are what Steps 2 and 3 both consume - one computation, two consumers.

**Not in scope:** `_resolve_script_id`'s label-matching, which a `script_id` on the assignment would eventually retire; the interview coordinator's per-session choice. Both become tractable once the mapping is durable, and neither should be attempted here.
