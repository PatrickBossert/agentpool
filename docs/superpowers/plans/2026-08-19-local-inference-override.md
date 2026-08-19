# Forcing local inference without moving the vector store - implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A project may be told to use local models while keeping its vector store where it is, so local model performance can be measured on a project whose documents live in Chroma Cloud.

**Architecture:** A per-project `force_local_inference` flag that **removes** `HOSTED_INFERENCE` from whatever the project's mode grants, and can never add a capability. `project_permits(slug, capability)` joins `permits(mode, capability)` beside it; the two egress routers move onto it. The privacy page renders the resolved grants rather than the mode's declared row.

**Spec:** `docs/superpowers/specs/2026-08-19-local-inference-override-design.md`

## Global Constraints

- **British English** - `-ise`, `-our`, `-re`, Oxford comma, spaced en dash ` - `, never an em dash. Binds page copy a client or auditor may read.
- **`brand` tokens only**, never `sky-*`/`blue-*`. Lucide icons, no emoji. `describeError` from `ui/src/utils/describeError.ts`.
- **Python 3.13** via `./venv/bin/python`. No ORM - raw SQL in `api/database.py`.
- **This adds a column to a PROJECT table.** A new `_migrate_*` must bump `_SCHEMA_VERSION` (currently **13**) in the same change and join the block `get_connection` runs; add the column to `CREATE TABLE` and to every test fixture building `projects` by hand. `tests/test_stakeholder_synthetic_migration.py` shows how to make a missed bump catchable - copy it. **This is the opposite of the `system.db` rule**, where `init_system_db` has no version gate.
- **Backend suite twice with identical counts.** Baseline **2303 passed, 2 skipped, 12 deselected**. Frontend **638**, `tsc --noEmit` clean. Establish both from HEAD yourself - counts in documents on this project have been stale five times.
- **Narrowing only.** The flag is expressed as set difference. A union anywhere in this path is the defect.
- **Enforce in the service, not the router.**
- **Power-check each property separately.** Commit before the first mutation; clear `__pycache__` between a mutation and its revert.
- Stage explicit paths. **Never `git add -A`.** Write nothing to `data/`. Do not restart the servers on :8000 or :3000.

---

### Task 1: The flag, and a resolved grant per project

**Files:** Modify `api/database.py`, `api/services/deployment_modes.py`, `api/services/chroma_client.py`, `agents/model_registry.py`, `api/models.py`; Test: new `tests/test_local_inference_override.py`

**Interfaces:**
- Produces: `project_grants(slug) -> frozenset[Capability]` and `project_permits(slug, capability) -> bool`. Tasks 2, 3 consume both.

- [ ] **Step 1: Report the current shape before changing it.** `permits(mode, capability)` takes a mode string, so the flag cannot be consulted inside it. Confirm the two call sites - `agents/model_registry.py:164` and `api/services/chroma_client.py:128` - and confirm both already hold the slug. Report anything that disagrees with this plan.

- [ ] **Step 2: Add the column.** `projects.force_local_inference INTEGER NOT NULL DEFAULT 0`, with the migration, the `_SCHEMA_VERSION` bump, the `CREATE TABLE` entry, and the fixtures. Make a missed bump catchable, as the sibling migration test does.

- [ ] **Step 3: Write the failing tests - the cell this exists for, and the one that must stay impossible**

```python
def test_a_standard_project_forced_local_keeps_cloud_vectors():
    # The whole point: local models, Chroma Cloud untouched.
    grants = project_grants(slug)          # standard project, flag set
    assert Capability.CLOUD_VECTOR_STORE in grants
    assert Capability.HOSTED_INFERENCE not in grants

def test_the_flag_can_never_grant_a_sensitive_project_hosted_inference():
    # Narrowing only, asserted rather than trusted.
    for flag in (True, False):
        assert project_grants(sensitive_slug) == frozenset()
```

- [ ] **Step 4: Write the resolver.** Synchronous, because both routers are - `interview_url`'s constraint one branch over is the same one. Cache it, and **register the cache with `process_cache`** so suite isolation covers it without anybody remembering. Reading it in the same query as `llm_mode` is worth considering, since every caller wanting one wants the other; say what you chose.

- [ ] **Step 5: Move both routers to `project_permits(slug, ...)`.** `permits(mode, ...)` stays - the declared question is still real, and the mode-name inventory guards it.

- [ ] **Step 6: Assert what is built, not what a helper returns.** The properties are which Chroma client comes back and which `LLM` is constructed. Power-check each router separately - a shared resolver lets one site's test cover another's, which has bitten this project twice. Commit.

---

### Task 2: The flag is platform-tier, and nothing reads it behind the resolver's back

**Files:** Modify `api/routers/projects.py`, `api/models.py`; Test: extend

- [ ] **Step 1: Add `force_local_inference` to `_PLATFORM_TIER_SETTINGS`** and to `ProjectSettings`. Turning it **on** only narrows; turning it **off** widens, which is why a `project_admin` may not.

- [ ] **Step 2: Write the failing test.** A `project_admin` is refused with a 403 naming the field; a platform-tier caller succeeds. The existing guard compares the **transition**, not the field's presence, because the Settings tab round-trips the whole body - confirm that still holds with the new field rather than assuming it.

- [ ] **Step 3: Add the source-walk guard.** Nothing outside the resolver may read the flag directly - a site that does bypasses the narrowing and the cache at once. sp58 built two guards of exactly this shape (`test_forget_all_process_caches_has_no_production_caller`, `test_nothing_reads_public_url_off_settings_outside_the_accessor`); follow their form. **Name what the walk cannot see** in the docstring - sp58's first draft used substring matching and let `cfg = get_settings(); cfg.public_url` through, so the exemption must name what is *allowed* rather than guess at what is not.

- [ ] **Step 4: Suites twice. Power-check the guard by planting a direct read. Commit.**

---

### Task 3: The privacy page reports what is resolved, not what is declared

**Files:** Modify `api/services/data_architecture_service.py`, `agents/egress.py` if needed, `ui/src/pages/DataArchitecture.tsx`; Test: both suites

- [ ] **Step 1: Establish how the page derives its answer today and report it.** It reads the grants table. Say exactly which function, and whether it is given a mode or a slug.

- [ ] **Step 2: Write the failing test.** A `standard` project with the flag set must report inference as **local** and vectors as **Chroma Cloud**, on the page's own payload. Today it will say hosted for both.

- [ ] **Step 3: Make it so.** This is the largest piece: the page's purpose is telling an auditor where material goes, and a page that renders the declared row while the flag narrows the real one is wrong on the one surface whose job is being right.

- [ ] **Step 4: The two badges are already independent** - sp57 re-keyed `_DESTINATION` on `(Reach, granted)` and sp58's Task 2a made the pill badge `HOSTED_INFERENCE` and `CLOUD_VECTOR_STORE` separately. Confirm both still hold; do not reintroduce a collapsed binary.

- [ ] **Step 5: Suites twice, `tsc` clean, power-check, commit.**

---

### Task 4: The toggle

**Files:** Modify `ui/src/pages/Settings.tsx`, `ui/src/types.ts`; Test: frontend

- [ ] **Step 1: Find how `llm_mode` renders on the Settings page and follow it.** The flag sits beside it - both are platform-tier, both decide where this engagement's data is sent.

- [ ] **Step 2: Label it for what it does.** It forces local models; it does **not** move the vector store. A label implying otherwise is the mistake this whole change exists to correct, and an operator reading it must not expect their Chroma Cloud data to move.

- [ ] **Step 3: Assert what is sent, not what renders.** `ui/src/__tests__/client.test.ts` is the axios-adapter pattern. Six tests across the last two branches passed without testing what they were named for, every one found by mutation - assume yours may be the seventh.

- [ ] **Step 4: Show the refusal through `describeError`.** A `project_admin` gets a 403 naming the field; a fixed string cannot say which one.

- [ ] **Step 5: Frontend suite, `tsc` clean, power-check, commit.**

---

## Self-Review

**Spec coverage:** narrowing-only flag (1), storage as a project column with the bump (1), synchronous cached resolver registered with `process_cache` (1), both routers moved (1), the impossible case asserted (1), platform-tier authority (2), source-walk guard (2), privacy page resolves rather than declares (3), the toggle (4).

**Placeholder scan:** none. Tasks 1 and 3 each open by establishing facts from the code, because briefs on this project have been wrong about details more than a dozen times - including a whole task premise on the last branch but one.

**Type consistency:** `project_grants(slug) -> frozenset[Capability]` and `project_permits(slug, capability) -> bool` are defined in Task 1 and consumed in 2 and 3. `Capability` is the existing enum in `api/services/deployment_modes.py`.

**Not in scope:** sovereign mode; renaming `standard` to `global`; renaming `_TIER_SETTINGS`' second key; a reverse flag forcing hosted inference, which has no use and would break the guarantee narrowing provides.

**One ordering note:** Task 3 depends on Task 1's resolver and nothing else, so it could precede Task 2. It comes after because until the flag is platform-tier, a test that sets it is exercising a door that should not exist.
