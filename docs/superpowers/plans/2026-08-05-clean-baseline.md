# Clean Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the dead code and the fragmented, superseded output rows so the project has a clean baseline to work from.

**Architecture:** Two independent halves. The code half deletes modules nothing imports, together with the tests and registry entry that only existed to serve them. The data half adds one tested helper in `api/database.py` that deletes `agent_outputs` rows of named types along with their dependent rows, and a script holding the literal list of types to prune - explicit rather than pattern-matched, so a reviewer can audit exactly what goes.

**Tech Stack:** Python 3.13, FastAPI, aiosqlite (raw SQL, no ORM), React 18 + TypeScript + Vite, Vitest.

**Baseline:** 1054 backend passed / 2 skipped, 360 frontend passed, `tsc --noEmit` silent. Branch `chore/clean-baseline`, forked from `master` at `2a7da989`.

## Global Constraints

- **British English throughout** - `-ise` not `-ize`, `-our` not `-or`, `-re` not `-er`, `-ogue` not `-og`.
- **Spaced hyphen ` - ` in all content, never an em dash.** Oxford comma in lists of three or more.
- **All raw SQL lives in `api/database.py`.**
- **Never modify `agents/tools/human_input.py`.**
- **Never run `git add -A` or `git add .`** - stage the exact paths each task lists.
- **Backend tests:** `./venv/bin/pytest -q --ignore=tests/integration`
- **Frontend tests:** `cd ui && npx vitest run` and `cd ui && npx tsc --noEmit`
- **Both suites pass before every commit.**
- **Run the backend suite twice before claiming green.** A single green run on this repository proves less than it looks: `tests/conftest.py` points `DATABASE_DIR` at a fixed `/tmp/agentpool_test` that persists between runs, so a test that poisons its own database passes once and fails afterwards. This exact defect shipped undetected through eight task reviews on the previous branch.
- **Never execute anything against `data/sp-gs-am.db` or `projects/` except where Task 4 explicitly says to.** That is live client data.

## Not in this plan

**`visual_illustrator`.** It looks like dead code - it owns `illustration_briefs`, is called by `business_plan_crew.py`, and has no `registry.py` `tool_map` entry, so `build_and_run_crew("business_plan")` raises `ValueError`. The role is deliberately unconfigured pending the value chain, value levers, value propositions, roadmap, and financials outputs. **Do not remove any part of it.**

**`api/services/interview_coverage.py` and `ui/src/utils/voiceLocale.ts`.** Both are unreferenced and both are deliberate groundwork - Jordan's coverage role and multi-locale voice respectively. **Keep them.**

**`pam_report` and the seven `*_interview_summaries` types.** Absent from `OUTPUT_OWNERS` because they are not written through `SQLiteStateTool`, not because they are junk. `pam_report` holds four real orchestration reports; the summaries hold genuine synthesis with history to v42. **Keep every row.**

**`revert_to_version`'s remaining foreign key gap.** It still does not clear `approval_commit_outputs.output_id` or `output_changes.output_id`, so reverting past a version frozen into an approval commit raises `IntegrityError`. Real, recorded, and a separate piece of work - Task 3's helper handles both tables for its own deletes, which does not fix `revert_to_version`.

## File Structure

| File | Responsibility |
|---|---|
| `api/database.py` | `prune_output_types` - delete rows of named output types with their dependents, returning the file paths to archive. |
| `scripts/prune_fragmented_outputs.py` (create) | The literal list of types to prune, the archive step, and the live run. |
| `tests/test_prune_output_types.py` (create) | Covers the helper against temporary databases. |
| `agents/tools/registry.py` | Drops the `interview_script_designer` `tool_map` entry. |

---

### Task 1: Remove the three dead UI components

**Files:**
- Delete: `ui/src/components/AgentChatDrawer.tsx`, `ui/src/components/AgentGrid.tsx`, `ui/src/components/InfoCard.tsx`

**Interfaces:**
- Produces: nothing. Removes code no module imports.

**Why:** all three are unreferenced by any non-test source and have no tests of their own. `AgentChatDrawer` was superseded by `AgentDetailPanel.tsx`, `AgentGrid` by the OrgChart work, and `InfoCard` infers the running agent by scraping log text, which the run status now reports directly.

They import from `./agentStatus` and `./OrgChart`, both of which stay - nine live components still use them, so removing these three orphans nothing.

- [ ] **Step 1: Confirm nothing imports them**

```bash
cd ui/src
grep -rn --include="*.tsx" --include="*.ts" -e "AgentChatDrawer" -e "AgentGrid" -e "InfoCard" . | grep -v "^./components/AgentChatDrawer.tsx" | grep -v "^./components/AgentGrid.tsx" | grep -v "^./components/InfoCard.tsx"
```

Expected: no output. If anything prints, **stop and report it** - the premise of this task is wrong.

- [ ] **Step 2: Delete the three files**

```bash
cd /Users/patrickbossert/Documents/Projects/agentpool1
git rm ui/src/components/AgentChatDrawer.tsx ui/src/components/AgentGrid.tsx ui/src/components/InfoCard.tsx
```

- [ ] **Step 3: Verify both suites**

Run: `cd ui && npx vitest run` - expect 360 passed, unchanged. These components had no tests, so the count must not move.
Run: `cd ui && npx tsc --noEmit` - expect silence. This is the check that matters: a dangling import would surface here.
Run: `./venv/bin/pytest -q --ignore=tests/integration` - expect 1054 passed / 2 skipped, unchanged.

If the frontend count changes, **stop and report** - it would mean a test was exercising one of these indirectly.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(ui): remove three components nothing imports"
```

---

### Task 2: Remove interview_script_designer and the completed backfill script

**Files:**
- Delete: `agents/discovery/interview_script_designer.py`, `tests/test_interview_script_designer.py`, `scripts/backfill_pre_perkey_output_types.py`
- Modify: `agents/tools/registry.py:115`, `tests/test_discovery_interviews_crew.py:100-106`

**Interfaces:**
- Produces: nothing. Removes an agent no crew dispatches.

**Why:** the agent was removed from `discovery_interviews` in commit `6dab668` and script design moved to the template-driven API path in `239e469`, as `tests/test_discovery_interviews_crew.py:30` records. The module and its `tool_map` entry were left behind. It is also a live trap: its prompt declares `operation='write', key='interview_scripts'`, a key now owned by `interaction_designer`, so every write it made would be refused if it were ever re-wired.

The backfill script is a completed one-off whose docstring claims supersession is scoped `(project, agent, output_type)` - made false by the previous branch.

- [ ] **Step 1: Confirm no crew dispatches it**

```bash
grep -c "interview_script_designer" api/services/run_service.py
grep -rn "interview_script_designer" agents/crews/
```

Expected: `0` from the first command, no output from the second. If either shows a dispatch, **stop and report** - this would be `visual_illustrator`'s situation, where an unwired agent is planned rather than dead.

- [ ] **Step 2: Delete the module, its test file, and the backfill script**

```bash
git rm agents/discovery/interview_script_designer.py tests/test_interview_script_designer.py scripts/backfill_pre_perkey_output_types.py
```

- [ ] **Step 3: Remove the tool_map entry**

In `agents/tools/registry.py`, delete the whole `"interview_script_designer": [ ... ],` entry beginning at line 115, including its tool list and any comment attached to it. Leave every other entry untouched.

- [ ] **Step 4: Remove the test that asserts the entry exists**

In `tests/test_discovery_interviews_crew.py`, delete `test_registry_has_interview_script_designer_entry` in full - the function, its decorator if any, and the blank line separating it from its neighbour. It begins at line 100 and ends at the `assert len(tools) > 0` on line 106.

Leave `test_registry_has_interview_coordinator_entry` immediately below it alone, and leave the docstring at line 30 that records the removal - it is the history explaining why this agent is gone.

- [ ] **Step 5: Run both suites**

Run: `./venv/bin/pytest -q --ignore=tests/integration`

Expected: **1046 passed / 2 skipped** - 1054 minus the 7 tests in `test_interview_script_designer.py` and the 1 registry test removed here.

Run it a **second** time and confirm the same number, per the Global Constraints.

Run: `cd ui && npx vitest run && npx tsc --noEmit` - expect 360 passed, tsc silent.

- [ ] **Step 6: Commit**

```bash
git add agents/tools/registry.py tests/test_discovery_interviews_crew.py
git commit -m "chore(agents): remove the interview_script_designer leftovers"
```

---

### Task 3: A helper that prunes output types with their dependents

**Files:**
- Modify: `api/database.py`
- Test: `tests/test_prune_output_types.py` (create)

**Interfaces:**
- Produces: `prune_output_types(conn, *, project_id: int, output_types: list[str]) -> dict` returning `{"deleted": int, "file_paths": list[str]}`. Task 4 consumes it.

**Why:** `agent_outputs` is referenced by seven foreign key columns across six tables, and `get_connection` enables enforcement, so a bare `DELETE` raises. Two delete paths on the previous branch broke this way and had to be fixed after the fact. This helper clears every dependent first, in one place, so the script in Task 4 cannot get it wrong.

It returns the file paths **collected before the delete**, because afterwards there is nothing left to ask.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_prune_output_types.py`:

```python
# tests/test_prune_output_types.py
"""Pruning an output type takes its dependent rows with it.

agent_outputs is referenced by seven foreign key columns and enforcement is on, so a bare
DELETE raises IntegrityError. Two delete paths shipped with exactly that defect before.
"""
import pytest
import pytest_asyncio

from api.database import get_connection, insert_project, prune_output_types

SLUG = "prune-test"


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield
    get_settings.cache_clear()


async def _output(conn, output_type, version, agent="value_chain_mapper"):
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
        " version, is_current, review_status) VALUES (1,?,?,?,?,1,'pending')",
        (agent, output_type, f"{output_type}_v{version}.json", version),
    )
    await conn.commit()
    return cur.lastrowid


@pytest.mark.asyncio
async def test_it_deletes_the_named_types_and_leaves_the_rest(project):
    async with get_connection(SLUG) as conn:
        await _output(conn, "interview_scripts_batch1", 1)
        await _output(conn, "state", 1)
        await _output(conn, "interview_scripts", 1)

        result = await prune_output_types(
            conn, project_id=1, output_types=["interview_scripts_batch1", "state"]
        )
        rows = await conn.execute_fetchall("SELECT output_type FROM agent_outputs")

    assert result["deleted"] == 2
    assert [r[0] for r in rows] == ["interview_scripts"]


@pytest.mark.asyncio
async def test_it_returns_the_file_paths_before_deleting_them(project):
    """The caller archives these. After the delete there is nothing left to ask."""
    async with get_connection(SLUG) as conn:
        await _output(conn, "state", 1)
        await _output(conn, "state", 2)
        result = await prune_output_types(conn, project_id=1, output_types=["state"])

    assert sorted(result["file_paths"]) == ["state_v1.json", "state_v2.json"]


@pytest.mark.asyncio
async def test_it_clears_dependents_so_the_delete_does_not_raise(project):
    """The whole reason this helper exists. Enforcement is on, so a bare DELETE raises."""
    async with get_connection(SLUG) as conn:
        doomed = await _output(conn, "state", 1)
        keeper = await _output(conn, "interview_scripts", 1)
        await conn.execute(
            "INSERT INTO human_reviews (output_id, decision) VALUES (?, 'pending')",
            (doomed,),
        )
        await conn.execute(
            "INSERT INTO run_inputs (run_id, agent_name, output_id) VALUES (5,'a',?)",
            (doomed,),
        )
        await conn.execute(
            "INSERT INTO output_lineage (output_id, input_output_id) VALUES (?,?)",
            (keeper, doomed),
        )
        await conn.commit()

        result = await prune_output_types(conn, project_id=1, output_types=["state"])
        left = await conn.execute_fetchall(
            "SELECT COUNT(*) FROM output_lineage WHERE input_output_id=?", (doomed,)
        )

    assert result["deleted"] == 1
    # The edge pointed AT the doomed row, not from it - both directions must be cleared.
    assert left[0][0] == 0


@pytest.mark.asyncio
async def test_running_it_twice_is_safe(project):
    """This script may be run again by someone unsure whether it already ran."""
    async with get_connection(SLUG) as conn:
        await _output(conn, "state", 1)
        first = await prune_output_types(conn, project_id=1, output_types=["state"])
        second = await prune_output_types(conn, project_id=1, output_types=["state"])

    assert first["deleted"] == 1
    assert second["deleted"] == 0
    assert second["file_paths"] == []


@pytest.mark.asyncio
async def test_an_empty_type_list_deletes_nothing(project):
    """Guards the caller passing an empty list - an unguarded IN () would be a syntax
    error at best and a full table delete at worst."""
    async with get_connection(SLUG) as conn:
        await _output(conn, "state", 1)
        result = await prune_output_types(conn, project_id=1, output_types=[])
        rows = await conn.execute_fetchall("SELECT COUNT(*) FROM agent_outputs")

    assert result == {"deleted": 0, "file_paths": []}
    assert rows[0][0] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_prune_output_types.py -q`
Expected: FAIL - `cannot import name 'prune_output_types' from 'api.database'`

- [ ] **Step 3: Write the helper**

Add to `api/database.py`, beside the other `agent_outputs` helpers:

```python
async def prune_output_types(
    conn: aiosqlite.Connection, *, project_id: int, output_types: list[str]
) -> dict:
    """Delete every agent_outputs row of the given types, with its dependent rows.

    Returns {"deleted": int, "file_paths": [...]}. The paths are collected before the
    delete, because afterwards there is nothing left to ask - the caller archives them.

    Dependents must go first. agent_outputs is referenced by human_reviews,
    approval_commit_outputs, output_changes, run_inputs, output_lineage on BOTH of its
    columns, and output_citations, and get_connection enables foreign key enforcement, so
    a bare delete raises. Missing input_output_id would leave the commoner case broken:
    a doomed row is more often something else was built from than something that built.
    """
    if not output_types:
        return {"deleted": 0, "file_paths": []}

    marks = ",".join("?" * len(output_types))
    params = (project_id, *output_types)

    async with conn.execute(
        f"SELECT DISTINCT file_path FROM agent_outputs"
        f" WHERE project_id=? AND output_type IN ({marks})",
        params,
    ) as cur:
        file_paths = [row[0] async for row in cur]

    doomed = (
        f"SELECT id FROM agent_outputs WHERE project_id=? AND output_type IN ({marks})"
    )
    for table, column in (
        ("human_reviews", "output_id"),
        ("approval_commit_outputs", "output_id"),
        ("output_changes", "output_id"),
        ("run_inputs", "output_id"),
        ("output_lineage", "output_id"),
        ("output_lineage", "input_output_id"),
        ("output_citations", "output_id"),
    ):
        await conn.execute(f"DELETE FROM {table} WHERE {column} IN ({doomed})", params)

    cur = await conn.execute(
        f"DELETE FROM agent_outputs WHERE project_id=? AND output_type IN ({marks})",
        params,
    )
    await conn.commit()
    return {"deleted": cur.rowcount, "file_paths": file_paths}
```

- [ ] **Step 4: Run to verify it passes**

Run: `./venv/bin/pytest tests/test_prune_output_types.py -q` - expect 5 passed.

- [ ] **Step 5: Mutation-test the dependent clearing**

The dependent clearing is the load-bearing part. Confirm the tests actually catch its removal:

```bash
cp api/database.py /tmp/db.bak
# Drop the input_output_id direction - the commoner case
./venv/bin/python -c "
import pathlib;p=pathlib.Path('api/database.py');s=p.read_text()
p.write_text(s.replace('        (\"output_lineage\", \"input_output_id\"),\n',''))"
./venv/bin/pytest tests/test_prune_output_types.py -q   # expect failure
cp /tmp/db.bak api/database.py
./venv/bin/pytest tests/test_prune_output_types.py -q   # expect 5 passed
```

Verify the restore took effect before continuing - `git diff --stat api/database.py` should show only your intended change.

- [ ] **Step 6: Run both suites and commit**

Run: `./venv/bin/pytest -q --ignore=tests/integration` **twice** - expect 1051 passed / 2 skipped both times (1046 from Task 2, plus 5).
Run: `cd ui && npx vitest run && npx tsc --noEmit` - expect 360 passed, tsc silent.

```bash
git add api/database.py tests/test_prune_output_types.py
git commit -m "feat(outputs): prune output types with their dependent rows"
```

---

### Task 4: Prune the fragmented and legacy outputs from sp-gs-am

**Files:**
- Create: `scripts/prune_fragmented_outputs.py`

**Interfaces:**
- Consumes: `prune_output_types` from Task 3.

**Why:** `sp-gs-am` holds 33 output types that are fragmented or superseded, across 59 rows and 46 files. The `interview_scripts_*` variants are the batching pathology the ownership map now prevents, and a proper `interview_scripts` with four versions already exists alongside them. `state` is a legacy catch-all whose 15 rows come from two agents pointing at unrelated files. `value_chain` is the legacy markdown superseded by `value_chain_model`, and its v1 to v7 rows all point at the same unversioned `value_chain.md`.

The type list is **literal, not pattern-matched**. A prefix rule would silently widen as new keys appear, and this operation is destructive.

Verified before writing this plan: no doomed file path is shared with a kept row, so archiving cannot destroy a live artefact. The only dependent rows are 5 in `human_reviews`; `approval_commit_outputs` and `output_changes` have none.

- [ ] **Step 1: Write the script**

Create `scripts/prune_fragmented_outputs.py`:

```python
# scripts/prune_fragmented_outputs.py
"""Remove the fragmented and superseded output types from a project.

The list is literal rather than pattern-matched. A rule like "everything starting
interview_scripts_" would silently widen as new keys appeared, and this deletes data.

Rows go first, then files. If the delete raises, nothing has moved and the run can simply
be repeated. Files are moved into a timestamped archive rather than unlinked - the point
is a clean baseline, not destroyed evidence.
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

from api.config import get_settings
from api.database import fetch_project, get_connection, prune_output_types

PRUNE_TYPES = [
    "interview_scripts_a",
    "interview_scripts_batch1",
    "interview_scripts_batch2",
    "interview_scripts_batch3",
    "interview_scripts_batch4",
    "interview_scripts_batch5",
    "interview_scripts_batch6",
    "interview_scripts_batch7",
    "interview_scripts_batch8",
    "interview_scripts_batch9",
    "interview_scripts_c",
    "interview_scripts_caf",
    "interview_scripts_customer_audit_frontline_corpservices",
    "interview_scripts_f",
    "interview_scripts_frontline",
    "interview_scripts_l0",
    "interview_scripts_l1",
    "interview_scripts_l1_fleet",
    "interview_scripts_l1_property",
    "interview_scripts_l2",
    "interview_scripts_l2_1",
    "interview_scripts_l2_2",
    "interview_scripts_l3",
    "interview_scripts_l3_1",
    "interview_scripts_part2",
    "interview_scripts_part3",
    "interview_scripts_part4",
    "interview_scripts_part5",
    "interview_scripts_part6",
    "interview_scripts_s",
    "state",
    "value_chain",
    "value_chain_model_raw",
]


async def main(slug: str, archive_name: str) -> None:
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise SystemExit(f"no such project: {slug}")
        result = await prune_output_types(
            conn, project_id=project["id"], output_types=PRUNE_TYPES
        )

    print(f"deleted rows: {result['deleted']}")

    root = Path(get_settings().projects_dir).parent
    archive = Path(get_settings().projects_dir) / slug / archive_name
    archive.mkdir(parents=True, exist_ok=True)

    moved = 0
    for rel in result["file_paths"]:
        source = root / rel
        if source.exists():
            shutil.move(str(source), str(archive / source.name))
            moved += 1
    print(f"archived files: {moved} of {len(result['file_paths'])} into {archive}")
    print("(a path with no file is normal - several rows shared one filename)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: prune_fragmented_outputs.py <slug> <archive-dir-name>")
    asyncio.run(main(sys.argv[1], sys.argv[2]))
```

- [ ] **Step 2: Confirm the list matches what is actually there**

Read-only. Run this before touching anything:

```bash
./venv/bin/python -c "
import sqlite3, sys
sys.path.insert(0,'.')
from scripts.prune_fragmented_outputs import PRUNE_TYPES
con = sqlite3.connect('file:data/sp-gs-am.db?mode=ro', uri=True)
q = ','.join('?'*len(PRUNE_TYPES))
n = con.execute(f'SELECT COUNT(*) FROM agent_outputs WHERE output_type IN ({q})', PRUNE_TYPES).fetchone()[0]
p = con.execute(f'SELECT COUNT(DISTINCT file_path) FROM agent_outputs WHERE output_type IN ({q})', PRUNE_TYPES).fetchone()[0]
print('types:', len(PRUNE_TYPES), 'rows:', n, 'files:', p)
print('interview_scripts itself in list?', 'interview_scripts' in PRUNE_TYPES)
con.close()"
```

Expected exactly: `types: 33 rows: 59 files: 46` and `interview_scripts itself in list? False`.

If any number differs, **stop and report**. The database has changed since this plan was written and the list must be re-derived rather than run as-is.

- [ ] **Step 3: Back up the live database**

Note before you run anything that opens a connection: `data/sp-gs-am.db` still carries the
old two-column `run_inputs` and `run_documents`, because nothing has opened it since the
ownership and lineage work merged. The first `get_connection("sp-gs-am")` - including the one
inside your own script - will run `_migrate_run_inputs_agent_scope` and rebuild both tables.
That is expected and safe; both are empty. Take the backup first regardless.

```bash
./venv/bin/python -c "
import sqlite3
src = sqlite3.connect('data/sp-gs-am.db'); dst = sqlite3.connect('/tmp/sp-gs-am.pre-prune.db')
with dst: src.backup(dst)
dst.close(); src.close(); print('backup written to /tmp/sp-gs-am.pre-prune.db')"
ls -la /tmp/sp-gs-am.pre-prune.db
```

Use SQLite's backup API as shown, not `cp` - the API server may hold the database open.

- [ ] **Step 4: Run it against sp-gs-am**

```bash
./venv/bin/python -m scripts.prune_fragmented_outputs sp-gs-am _archive_2026-08-05
```

Expected: `deleted rows: 59`, then an archived-files line. A count of zero means the prune did not run rather than that there was nothing to do - Step 2 confirmed 59 rows exist, so investigate before accepting it.

- [ ] **Step 5: Verify the result**

```bash
./venv/bin/python -c "
import sqlite3
con = sqlite3.connect('file:data/sp-gs-am.db?mode=ro', uri=True)
print('total rows now:', con.execute('SELECT COUNT(*) FROM agent_outputs').fetchone()[0])
print('output_types now:', con.execute('SELECT COUNT(DISTINCT output_type) FROM agent_outputs').fetchone()[0])
for t in ('pam_report','l0_interview_summaries','interview_scripts','value_chain_registry'):
    print(' kept', t, con.execute('SELECT COUNT(*) FROM agent_outputs WHERE output_type=?', (t,)).fetchone()[0])
for t in ('state','value_chain','interview_scripts_batch1'):
    print(' gone', t, con.execute('SELECT COUNT(*) FROM agent_outputs WHERE output_type=?', (t,)).fetchone()[0])
con.close()"
ls projects/sp-gs-am/outputs/value_chain_registry_v1.json
```

Expected: 63 rows across 15 output types; `pam_report` 4, `l0_interview_summaries` 4, `interview_scripts` 4, `value_chain_registry` 6; `state`, `value_chain` and `interview_scripts_batch1` all 0. The final `ls` must succeed - that file is the only evidence of the cross-agent overwrite and must survive.

- [ ] **Step 6: Run both suites and commit**

Run: `./venv/bin/pytest -q --ignore=tests/integration` **twice** - expect 1051 passed / 2 skipped both times, unchanged from Task 3. This task adds no tests; it runs a script.
Run: `cd ui && npx vitest run && npx tsc --noEmit` - expect 360 passed, tsc silent.

```bash
git add scripts/prune_fragmented_outputs.py
git commit -m "chore(outputs): prune the fragmented and legacy output types from sp-gs-am"
```

---

## After the last task

Restart the API server so it reads the pruned data.

The archive at `projects/sp-gs-am/_archive_2026-08-05/` is deliberately kept. `projects/*` is git-ignored, so it exists only on this machine - if the files matter beyond this session, copy them somewhere durable.
