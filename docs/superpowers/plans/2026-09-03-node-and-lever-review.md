# Per-node and per-lever review - implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reviewer can send back a single value chain node or a single value lever, and the next `discovery_mapping` run regenerates that item alone - the loop that already works for Maya's interview scripts.

**Architecture:** Two ledgers keyed on permanent ids - `value_chain_ledger` (node id) and `value_lever_ledger` (lever id) - each carrying `review_status` and `review_return_to` beside the item's own fields, maintained by the write path with `ON CONFLICT DO NOTHING`. A per-agent pending block is injected into `discovery_mapping` runs. Review surfaces mirror `ScriptReviewPanel`.

**Spec:** `docs/superpowers/specs/2026-09-03-node-and-lever-review-design.md`

## Global Constraints

- **British English** - `-ise`, `-our`, `-re`, Oxford comma, spaced en dash ` - `, never an em dash. Client-facing surfaces.
- **`brand` tokens only**, never `sky-*`/`blue-*`. Lucide icons, no emoji. `describeError` from `ui/src/utils/describeError.ts`.
- **Python 3.13** via `./venv/bin/python`. No ORM - raw SQL in `api/database.py`.
- **These are PROJECT tables.** A new `_migrate_*` bumps `_SCHEMA_VERSION` (currently **14**) in the same change and joins the block `get_connection` runs; add the columns to `CREATE TABLE` and to fixtures building those tables by hand. Guard each migration with `PRAGMA table_info` and skip *itself* rather than the block - a migration that raises takes every later one down with it.
- **`ON CONFLICT(<id>) DO NOTHING`, never `INSERT OR IGNORE`.** `register_scripts_sync` documents why: `INSERT OR IGNORE` swallows every constraint violation on the row, not only the key conflict, so a malformed field is silently dropped from the whole batch.
- **Backend suite twice with identical counts.** Baseline **2366 passed, 2 skipped, 12 deselected**. Frontend **662**, `tsc --noEmit` clean. Establish both from HEAD yourself - counts in documents here have been stale six times.
- **Power-check each property separately**, confirm each mutation **landed**, and check **which** test caught it. All three have failed on this codebase.
- Stage explicit paths. **Never `git add -A`.** Write nothing to `data/`. Do not restart the servers on :8000 or :3000.

---

### Task 1: The node ledger

**Files:** Modify `api/database.py`, `agents/tools/_db.py`, `agents/tools/derive_registry.py`; Test: new `tests/test_value_chain_ledger.py`

**Interfaces:**
- Produces: `value_chain_ledger` table and `register_nodes_sync(slug, activities, version, author) -> int`. Tasks 3 and 4 consume it.

- [ ] **Step 1: Report the current shape.** `value_chain_registry` is a JSON artefact - `{"schema_version": ..., "activities": [{"id","label","level","active"}, ...]}`, 89 entries on `sp-gs-am`. Confirm, and report every writer of that output type.

- [ ] **Step 2: Add the table.**

```sql
CREATE TABLE IF NOT EXISTS value_chain_ledger (
    node_id           TEXT PRIMARY KEY,
    project_id        INTEGER NOT NULL,
    label             TEXT NOT NULL,
    level             TEXT,
    active            INTEGER NOT NULL DEFAULT 1,
    review_status     TEXT NOT NULL DEFAULT 'pending',
    review_return_to  TEXT,
    last_version      INTEGER,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Mirror `interview_script_ledger`'s columns where they mean the same thing - a reader who knows one should not have to learn the other.

- [ ] **Step 3: Write the failing test - registration never moves an id**

```python
def test_registering_an_existing_node_never_moves_its_label():
    register_nodes_sync(slug, [{"id": "3.3.3", "label": "Original", "level": "L3", "active": True}], 1, "alex")
    register_nodes_sync(slug, [{"id": "3.3.3", "label": "Rewritten", "level": "L3", "active": True}], 2, "alex")
    assert label_of(slug, "3.3.3") == "Original"
```

- [ ] **Step 4: Write `register_nodes_sync`** with `ON CONFLICT(node_id) DO NOTHING`, following `register_scripts_sync` including its reason for not using `INSERT OR IGNORE`. Call it from every `value_chain_registry` write.

- [ ] **Step 5: Backfill the existing 89 from the current artefact** - a script, not a migration, following `scripts/backfill_project_registry.py`. `get_connection(slug)` migrates any slug handed to it, so a backfill that walks `data/` would materialise databases for slugs that are not projects. Dry run by default.

- [ ] **Step 6: Suites twice. Power-check registration and the no-move rule separately. Commit.**

---

### Task 2: Levers get permanent ids, then a ledger

**Files:** Modify `api/database.py`, `agents/tools/_db.py`, Morgan's agent module; Test: new

**Interfaces:**
- Produces: `value_lever_ledger` and `register_levers_sync`. Tasks 3 and 4 consume it.

- [ ] **Step 1: Establish the problem before fixing it.** `value_levers` is a list of 10 whose key is `lever` - a full sentence. Report what identifies a lever today and confirm nothing stable exists.

- [ ] **Step 2: Assign ids to the existing ten, once.** `LV-001`..`LV-010` against the current artefact, recorded in the ledger. **Never re-derived from position or title** - a lever reordered or reworded keeps its id, which is the entire point. Say in the report how you fixed the assignment so a re-run cannot renumber them.

- [ ] **Step 3: Morgan emits the id.** His output carries `lever_id` alongside `lever`; the title becomes a label, the id becomes the key. Update his task text so a regenerated lever keeps the id it was sent back under.

- [ ] **Step 4: Write the failing test**

```python
def test_a_levers_id_survives_its_title_being_rewritten():
    register_levers_sync(slug, [{"lever_id": "LV-001", "lever": "Original title"}], 1, "morgan")
    register_levers_sync(slug, [{"lever_id": "LV-001", "lever": "Completely different wording"}], 2, "morgan")
    assert lever_ids(slug) == ["LV-001"]
```

- [ ] **Step 5: The ledger**, mirroring Task 1's. Suites twice, power-check, commit.

---

### Task 3: A send-back reaches the right agent, and only that agent

**Files:** Modify `api/services/run_service.py`, `api/services/script_review_service.py` or a sibling; Test: new

- [ ] **Step 1: Read `_pending_script_revisions` and `_fetch_change_requests` first, and report how each scopes.** The first is Maya's precedent for injection; the second already enforces ownership per row on `agent_name`, which is what stops one crew inheriting another's requests. You need both behaviours at once.

- [ ] **Step 2: Write the failing test - the crew holds two agents**

```python
async def test_alex_is_not_handed_morgans_lever_notes():
    # one node and one lever both awaiting the agent
    block = await _pending_discovery_revisions(slug, "value_chain_mapper")
    assert "3.3.3" in block and "LV-001" not in block
```

- [ ] **Step 3: Build the injection**, per agent, and wire it into `build_and_run_crew` for `discovery_mapping` only - the way `_pending_script_revisions` returns `""` for any crew but `assessment_design`.

- [ ] **Step 4: `review_return_to='reviewer'` never reaches either agent.** Assert it, as the script path does.

- [ ] **Step 5: The block is absent when nothing is awaiting**, so an ordinary run is unchanged. Power-check each separately - a shared assembler lets one agent's test cover the other's. Commit.

---

### Task 4: The review surfaces

**Files:** Create node and lever review panels in `ui/src/components/tabs/`; Modify `AgentDetailPanel.tsx`; Test: frontend

- [ ] **Step 1: Read `ScriptReviewPanel` and `ScriptReviewRow` and follow them.** Three exits - `edited`, `changes_requested`, `reviewed` - each recording a review; `approved` excluded from the count so an approval cannot satisfy its own gate; the gate enforced in the service, not only by a disabled button.

- [ ] **Step 2: Register them.** `discovery_mapping` already has `StructureTab` in `CREW_OUTPUT_EDITOR`; these are review surfaces, so `CREW_OUTPUT_EXTRA` is the register that fits - confirm against the file rather than assuming.

- [ ] **Step 3: A node shows its id, label, level, and review state. A lever shows its id, title, and status.** The lever id is displayed because a reviewer needs to cite it; the node id already is, in the tree.

- [ ] **Step 4: Assert what is sent, not what renders.** `ui/src/__tests__/client.test.ts` is the axios-adapter pattern. Ten tests across recent branches passed without testing what they were named for; assume yours may be the eleventh until a mutation says otherwise.

- [ ] **Step 5: Frontend suite, `tsc` clean, power-check, commit.**

---

### Task 5: Prove the loop, and document it

**Files:** Test: new integration-shaped test; Modify `CLAUDE.md`

- [ ] **Step 1: Drive the whole loop in one test** - send a node back, run the injection, assert the block names it; send a lever back, assert Alex's block does not name it.

- [ ] **Step 2: Assert the byte-identical property *within the registry*.** A single-node send-back must leave the other 88 ledger rows untouched. **The tree and summary are derived and will legitimately move** - say so in the test's docstring, or the first reviewer will read a correct run as a leak.

- [ ] **Step 3: Document in `CLAUDE.md`**, beside the interview-script ledger material it parallels: the two new ledgers, why the registry artefact stopped being the authority, that lever ids are permanent and their titles are not, and that one crew holding two agents is why the injection is per-agent.

- [ ] **Step 4: Suites unchanged by the documentation commit. Both counts stated. Commit.**

---

## Self-Review

**Spec coverage:** node ledger (1), lever ids and ledger (2), per-agent injection (3), review surfaces (4), the loop proved and documented (5). The spec's "Morgan reads Alex" integrity check is deliberately **not** a task - it is worth doing once both ledgers exist, and doing it here would widen this plan into a validation change.

**Placeholder scan:** none. Tasks 1, 2 and 3 each open by establishing facts from the code, because briefs here have been wrong more than a dozen times, including a whole task premise two branches ago.

**Type consistency:** `register_nodes_sync(slug, activities, version, author) -> int` and `register_levers_sync(slug, levers, version, author) -> int` are defined in Tasks 1 and 2 and consumed in 3 and 4. Both mirror `register_scripts_sync`'s signature deliberately.

**Not in scope:** a manual editor for levers (decided: review only); retiring the `value_chain_registry` artefact, which can follow once the table is authoritative; per-node review for `value_chain_model`, which has its own editor.

**One ordering note:** Task 2 could precede Task 1, but Task 1 establishes the ledger shape both follow, and doing the one with existing stable ids first means the harder id-assignment problem is solved against a proven pattern.
