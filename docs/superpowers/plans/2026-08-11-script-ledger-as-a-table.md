# Script Ledger as a Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the interview script ledger from a JSON artefact an agent must remember to write into a table the write path maintains, and bring review down from the whole artefact to the individual script.

**Architecture:** A new `interview_script_ledger` table, one row per `script_id`, upserted as a side effect of every `interview_scripts` write - inserting new ids and never changing an existing `node_id`, so the succession guard is untouched. The `interview_script_registry` JSON artefact retires. A second table, `script_reviews`, holds one row per review event, with the ledger row carrying the derived current state. Authority and notification reuse the existing stakeholder `is_reviewer` / `is_approver` machinery.

**Tech Stack:** Python 3.13, FastAPI, aiosqlite (raw SQL, no ORM), CrewAI, React 18 + TypeScript + Vite + Tailwind v3, pytest, Vitest.

## Global Constraints

- British English throughout: `-ise` not `-ize`, `-our` not `-or` - organise, behaviour, artefact, favour, centre.
- Short en dash ` - ` with spaces in prose. Never an em dash (`—`).
- Oxford comma in lists of three or more items.
- No emoji in rendered web content. Stylised Lucide React icons only.
- Tailwind `brand` / `surface` / `text-*` tokens. **Never `sky-*` or `blue-*`.**
- Python 3.13 only: `./venv/bin/pytest`, `./venv/bin/python`. Never system python.
- Frontend commands run from `ui/`: `npx vitest run`, `npx tsc --noEmit`.
- **Never run `pytest -m integration`** - it calls the real Anthropic API and costs money.
- **Run the backend suite twice** and confirm identical counts. `tests/conftest.py` points `DATABASE_DIR` at a fixed path that persists between runs, so a test writing a hardcoded row id passes once and fails ever after.
- Adding a `_migrate_*` function **requires** bumping `_SCHEMA_VERSION` in `api/database.py` in the same change and adding the call to the migration block in `get_connection`. Forgetting fails silently on every database already opened at the current version.
- Do not restart the API server while a crew run is in flight.
- bcrypt direct, never passlib.

---

## File Structure

| File | Responsibility |
|---|---|
| `api/database.py` | `_migrate_interview_script_ledger`, `_SCHEMA_VERSION` bump, async ledger and review helpers |
| `agents/tools/_db.py` | `register_scripts_sync`, `current_script_ledger_sync` - the sync half the tool path needs |
| `agents/tools/sqlite_state.py` | calls `register_scripts_sync` after a scripts write; guard reads the table |
| `agents/tools/ownership.py` | loses the `interview_script_registry` entry |
| `api/services/script_review_service.py` | new - review state machine, approve-once, send-back targets |
| `api/routers/script_reviews.py` | new - per-script review endpoints |
| `api/routers/projects.py` | rebuilt `GET`/`PATCH /interview-scripts/{script_id}` |
| `agents/discovery/interaction_designer.py` | ledger instructions removed, revision clause added |
| `ui/src/components/tabs/MayaOutputExtra.tsx` | per-script review controls |
| `ui/src/api/endpoints.ts` | review client calls |

---

### Task 1: The ledger table and its backfill

**Files:**
- Modify: `api/database.py` (add `_migrate_interview_script_ledger`, bump `_SCHEMA_VERSION`, add to the `get_connection` migration block)
- Test: `tests/test_script_ledger_table.py`

**Interfaces:**
- Consumes: nothing.
- Produces: table `interview_script_ledger` with columns `script_id TEXT PRIMARY KEY`, `project_id INTEGER`, `node_id TEXT NOT NULL`, `node_label TEXT`, `active INTEGER DEFAULT 1`, `review_status TEXT DEFAULT 'pending'`, `reviewed_at_version INTEGER`, `review_return_to TEXT`, `last_version INTEGER`, `last_author TEXT`, `created_at`, `updated_at`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_script_ledger_table.py
import pytest
from api.database import get_connection, fetch_project


@pytest.mark.asyncio
async def test_the_ledger_table_exists_with_script_id_as_primary_key(tmp_path, monkeypatch):
    """script_id as a PRIMARY KEY is the whole point: one id, one node, enforced by the
    database rather than by an instruction an agent has to remember."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        async with get_connection("ledger-test") as conn:
            cur = await conn.execute("PRAGMA table_info(interview_script_ledger)")
            cols = {r[1]: r for r in await cur.fetchall()}
            assert "script_id" in cols, "table missing"
            assert cols["script_id"][5] == 1, "script_id must be the primary key"
            for name in ("node_id", "active", "review_status", "reviewed_at_version",
                         "review_return_to", "last_version", "last_author"):
                assert name in cols, f"missing column {name}"

            await conn.execute(
                "INSERT INTO interview_script_ledger (script_id, project_id, node_id)"
                " VALUES ('SC-001', 1, '1.2')")
            await conn.commit()
            with pytest.raises(Exception):
                await conn.execute(
                    "INSERT INTO interview_script_ledger (script_id, project_id, node_id)"
                    " VALUES ('SC-001', 1, '9.9')")
                await conn.commit()
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/bin/pytest tests/test_script_ledger_table.py -v`
Expected: FAIL - `assert "script_id" in cols` with an empty `cols`, because the table does not exist.

- [ ] **Step 3: Add the migration**

Add to `api/database.py`, following the house style of `_migrate_stakeholder_node_assignments` at line 724:

```python
async def _migrate_interview_script_ledger(conn: aiosqlite.Connection) -> None:
    """Create the interview script ledger if it does not exist.

    One row per script id, and script_id is the PRIMARY KEY rather than an indexed
    column: "one id means one node for the life of the project" becomes a constraint
    the database enforces instead of a rule an agent must honour. Rows are retired
    with active = 0 and never deleted - a deleted row is an id free to be handed to a
    different script, and every stored answer citing it then resolves to the wrong
    instrument.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS interview_script_ledger (
            script_id           TEXT PRIMARY KEY,
            project_id          INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            node_id             TEXT NOT NULL,
            node_label          TEXT NOT NULL DEFAULT '',
            active              INTEGER NOT NULL DEFAULT 1,
            review_status       TEXT NOT NULL DEFAULT 'pending',
            reviewed_at_version INTEGER,
            review_return_to    TEXT,
            last_version        INTEGER,
            last_author         TEXT NOT NULL DEFAULT '',
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()
```

- [ ] **Step 4: Bump the schema version and register the migration**

In `api/database.py`, change `_SCHEMA_VERSION = 2` (line 1258) to `_SCHEMA_VERSION = 3`, and add this line to the migration block in `get_connection`, immediately after `await _migrate_agent_chat_history(conn)`:

```python
            await _migrate_interview_script_ledger(conn)
```

Both are required. Adding the function without bumping the version means it never runs on any database already opened at version 2 - no error, no warning.

- [ ] **Step 5: Run the test to verify it passes**

Run: `./venv/bin/pytest tests/test_script_ledger_table.py -v`
Expected: PASS

- [ ] **Step 6: Write the failing backfill test**

```python
# append to tests/test_script_ledger_table.py
@pytest.mark.asyncio
async def test_the_backfill_loads_the_existing_json_ledger(tmp_path, monkeypatch):
    """The live project has 86 reconciled entries in interview_script_registry_v4.json.
    The table starts from those, not from zero, or every id already issued falls outside
    the guarantee the moment the artefact retires."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.services.script_ledger_backfill import backfill_script_ledger
        registry = {"scripts": [
            {"id": "SC-001", "node_id": "0", "node_label": "Organisation", "active": True},
            {"id": "SC-002", "node_id": "1", "node_label": "Property", "active": False},
        ]}
        async with get_connection("backfill-test") as conn:
            await conn.execute("INSERT INTO projects (slug) VALUES ('backfill-test')")
            await conn.commit()
            n = await backfill_script_ledger(conn, project_id=1, registry=registry)
            assert n == 2
            cur = await conn.execute(
                "SELECT script_id, node_id, active FROM interview_script_ledger ORDER BY script_id")
            rows = await cur.fetchall()
        assert [tuple(r) for r in rows] == [("SC-001", "0", 1), ("SC-002", "1", 0)]
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 7: Run it to verify it fails**

Run: `./venv/bin/pytest tests/test_script_ledger_table.py::test_the_backfill_loads_the_existing_json_ledger -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'api.services.script_ledger_backfill'`

- [ ] **Step 8: Write the backfill**

Create `api/services/script_ledger_backfill.py`:

```python
"""One-time load of the JSON script ledger into interview_script_ledger.

The artefact is retiring, but every id it holds has already been issued and may already
be cited by a stakeholder assignment or a stored answer. Starting the table empty would
put all of them outside the succession guarantee at once.
"""
import aiosqlite


async def backfill_script_ledger(
    conn: aiosqlite.Connection, *, project_id: int, registry: dict
) -> int:
    """Insert a ledger row per registry entry. Returns the number inserted.

    INSERT OR IGNORE, so running it twice is harmless and a row already present - one
    the write path has since registered - is never overwritten by older JSON.
    """
    entries = registry.get("scripts", []) if isinstance(registry, dict) else (registry or [])
    inserted = 0
    for entry in entries:
        script_id = entry.get("id")
        node_id = entry.get("node_id")
        if not script_id or not node_id:
            continue
        cur = await conn.execute(
            "INSERT OR IGNORE INTO interview_script_ledger"
            " (script_id, project_id, node_id, node_label, active, last_author)"
            " VALUES (?,?,?,?,?,?)",
            (script_id, project_id, node_id, entry.get("node_label", ""),
             1 if entry.get("active", True) else 0, "interaction_designer"),
        )
        inserted += cur.rowcount
    await conn.commit()
    return inserted
```

- [ ] **Step 9: Run both tests to verify they pass**

Run: `./venv/bin/pytest tests/test_script_ledger_table.py -v`
Expected: 2 passed

- [ ] **Step 10: Run the full suite twice, then commit**

Run: `./venv/bin/pytest -q` twice. Expected: identical counts both runs.

```bash
git add api/database.py api/services/script_ledger_backfill.py tests/test_script_ledger_table.py
git commit -m "feat(ledger): the script ledger becomes a table with script_id as its key"
```

---

### Task 2: Registration becomes a side effect of the write

**Files:**
- Modify: `agents/tools/_db.py` (add `register_scripts_sync`, `current_script_ledger_sync`)
- Modify: `agents/tools/sqlite_state.py:384-392` (call it after `insert_agent_output_sync`)
- Test: `tests/test_script_ledger_registration.py`

**Interfaces:**
- Consumes: table `interview_script_ledger` from Task 1.
- Produces: `register_scripts_sync(slug: str, scripts: dict, version: int, author: str) -> int` returning the count of newly registered ids; `current_script_ledger_sync(slug: str) -> dict` returning `{"scripts": [{"id": str, "node_id": str, "active": bool}, ...]}` - deliberately the same shape `validate_scripts_against_script_registry` already consumes, so that pure function needs no change.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_script_ledger_registration.py
import json
import pytest
from agents.tools.sqlite_state import SQLiteStateTool


def _script(node_id, label):
    return {"node_id": node_id, "node_label": label, "level": "L2", "sections": []}


def test_a_scripts_write_registers_its_new_ids(script_project):
    """Driven through SQLiteStateTool's real write, not by calling the upsert. A
    registration path the write does not reach is the exact defect this work exists to
    remove - run 32 wrote 41 scripts and registered none of them."""
    slug = script_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)
    out = tool._run(operation="write", key="interview_scripts",
                    agent_name="interaction_designer",
                    value=json.dumps({"SC-001": _script("1.2", "Works Programming")}))
    assert out.startswith("Written to"), out

    from agents.tools._db import current_script_ledger_sync
    ledger = current_script_ledger_sync(slug)
    assert [(e["id"], e["node_id"]) for e in ledger["scripts"]] == [("SC-001", "1.2")]


def test_a_second_batch_registers_only_the_new_ids(script_project):
    """Run 32's shape: batches land one after another and each must leave every script
    written so far registered, because the run can stop at any point."""
    slug = script_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)
    tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
              value=json.dumps({"SC-001": _script("1.2", "Works Programming")}))
    tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
              value=json.dumps({"SC-002": _script("1.3", "Pipeline Design")}))

    from agents.tools._db import current_script_ledger_sync
    ids = {e["id"]: e["node_id"] for e in current_script_ledger_sync(slug)["scripts"]}
    assert ids == {"SC-001": "1.2", "SC-002": "1.3"}


def test_registration_never_moves_an_id_that_is_already_registered(script_project):
    """The property most likely to be destroyed by making registration automatic, and the
    one whose loss would be invisible: the write would succeed and the ledger would agree
    with it. Append-only is what keeps the succession guard meaningful."""
    slug = script_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)
    tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
              value=json.dumps({"SC-001": _script("1.2", "Works Programming")}))
    out = tool._run(operation="write", key="interview_scripts",
                    agent_name="interaction_designer",
                    value=json.dumps({"SC-001": _script("2.7", "Somewhere Else")}))

    assert out.startswith("Error:"), f"a moved id must be refused, got: {out}"
    from agents.tools._db import current_script_ledger_sync
    ids = {e["id"]: e["node_id"] for e in current_script_ledger_sync(slug)["scripts"]}
    assert ids == {"SC-001": "1.2"}, "the ledger must not have followed the moved id"
```

Add this fixture at the top of the same file:

```python
@pytest.fixture
def script_project(tmp_path, monkeypatch):
    """An isolated project with the registry a scripts write validates against."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from api.config import get_settings
    get_settings.cache_clear()
    slug = "reg-test"
    (tmp_path / "db").mkdir(parents=True, exist_ok=True)
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    import sqlite3
    from api.database import get_db_path
    import asyncio
    from api.database import get_connection

    async def _init():
        async with get_connection(slug) as conn:
            await conn.execute("INSERT INTO projects (slug) VALUES (?)", (slug,))
            await conn.commit()
    asyncio.run(_init())

    registry = {"activities": [
        {"id": "1.2", "label": "Works Programming", "level": "L2", "active": True},
        {"id": "1.3", "label": "Pipeline Design", "level": "L2", "active": True},
        {"id": "2.7", "label": "Somewhere Else", "level": "L2", "active": True},
    ]}
    (outputs / "value_chain_registry.json").write_text(json.dumps(registry))
    from agents.tools._db import insert_agent_output_sync
    insert_agent_output_sync(slug=slug, agent_name="value_chain_mapper",
                             output_type="value_chain_registry",
                             file_path=str(outputs / "value_chain_registry.json"))
    yield slug
    get_settings.cache_clear()
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_script_ledger_registration.py -v`
Expected: FAIL - `ImportError: cannot import name 'current_script_ledger_sync'`

- [ ] **Step 3: Add the sync helpers**

Append to `agents/tools/_db.py`:

```python
def current_script_ledger_sync(slug: str) -> dict:
    """The script ledger in force, in the shape the scripts-door guard already consumes.

    Returning {"scripts": [...]} rather than a friendlier shape is deliberate:
    validate_scripts_against_script_registry stays a pure function over a mapping and does
    not change at all, so moving the ledger from a file to a table has no blast radius
    beyond the loader.
    """
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        rows = conn.execute(
            "SELECT script_id, node_id, active FROM interview_script_ledger"
        ).fetchall()
    return {"scripts": [{"id": r[0], "node_id": r[1], "active": bool(r[2])} for r in rows]}


def register_scripts_sync(slug: str, scripts: dict, version: int, author: str) -> int:
    """Register any script id not already held. Returns how many were added.

    INSERT OR IGNORE, never UPDATE of node_id. That is what makes automatic registration
    safe: the succession rule forbids exactly two things, redefining an id and dropping
    one, and appending does neither. A batch that moves a registered id is refused by the
    validator before this ever runs, so the ledger cannot be talked into agreeing with it.

    last_version and last_author are refreshed for every id in the batch, including ids
    already registered, because those record which version last changed this script and
    who wrote it - which is a different question from where the id is anchored.
    """
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        row = conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()
        if not row:
            raise ValueError(f"Project not found: {slug}")
        project_id = row[0]
        added = 0
        for key, script in scripts.items():
            if not isinstance(script, dict):
                continue
            script_id = script.get("script_id") or key
            node_id = script.get("node_id")
            if not script_id or not node_id:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO interview_script_ledger"
                " (script_id, project_id, node_id, node_label, last_version, last_author)"
                " VALUES (?,?,?,?,?,?)",
                (script_id, project_id, node_id, script.get("node_label", ""),
                 version, author),
            )
            added += cur.rowcount
            conn.execute(
                "UPDATE interview_script_ledger"
                " SET last_version=?, last_author=?, updated_at=CURRENT_TIMESTAMP"
                " WHERE script_id=?",
                (version, author, script_id),
            )
        conn.commit()
    return added
```

- [ ] **Step 4: Call it from the write path**

In `agents/tools/sqlite_state.py`, inside `_run`'s write branch, immediately after the `insert_agent_output_sync` call succeeds and before the `_WARNERS` block:

```python
            if key == "interview_scripts" and isinstance(parsed, dict):
                # Registration is a side effect of the write, exactly as
                # insert_agent_output_sync maintains is_current, and for the same reason:
                # a correctness record whose maintenance is an agent's last instruction is
                # a record that goes missing when a run stops early. Run 32 wrote 41
                # scripts, hit the iteration ceiling before its ledger write, and reported
                # completed.
                try:
                    from agents.tools._db import register_scripts_sync
                    version = _output_version_sync(self.slug, new_output_id)
                    register_scripts_sync(self.slug, parsed, version, agent_name)
                except Exception:
                    # Never fail a durable write over the ledger. The next write re-derives
                    # it, and the validator refuses anything that would corrupt it meanwhile.
                    pass
```

Add this helper to `agents/tools/_db.py`:

```python
def _output_version_sync(slug: str, output_id: int) -> int:
    """The version of one agent_outputs row, or 0 if it has gone."""
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        row = conn.execute(
            "SELECT version FROM agent_outputs WHERE id=?", (output_id,)
        ).fetchone()
    return row[0] if row else 0
```

Import it in `sqlite_state.py` alongside the existing `_db` imports.

- [ ] **Step 5: Point the guard at the table**

In `agents/tools/sqlite_state.py`, replace the body of `_current_script_registry` (line 82) so the guard reads the table rather than the retiring artefact:

```python
def _current_script_registry(slug: str) -> dict:
    """The script ledger in force, or an empty one when there is none yet.

    Reads the interview_script_ledger table. It used to read the
    interview_script_registry artefact, which an agent wrote as the last step of a long
    run - so the guard was checking a record that could be up to a whole run out of date.
    """
    from agents.tools._db import current_script_ledger_sync
    try:
        return current_script_ledger_sync(slug)
    except Exception:
        return {}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_script_ledger_registration.py -v`
Expected: 3 passed

- [ ] **Step 7: Power-check the third test**

Change `INSERT OR IGNORE` to `INSERT OR REPLACE` in `register_scripts_sync`, run `test_registration_never_moves_an_id_that_is_already_registered`, and confirm it still passes - it will, because the validator refuses the batch first. Then additionally comment out the `validate_scripts_against_script_registry` line in `_validate_interview_scripts` and re-run: it must now FAIL. Restore both.

Record both observations in your report. This is the check that matters: the test's protection comes from the validator, and knowing that means nobody later "simplifies" the validator believing the ledger's append-only rule is a second line of defence.

- [ ] **Step 8: Run the full suite twice, then commit**

```bash
git add agents/tools/_db.py agents/tools/sqlite_state.py tests/test_script_ledger_registration.py
git commit -m "feat(ledger): the scripts write registers its own ids

Append-only, so the succession guard is untouched: the rule forbids redefining an id and
dropping one, and appending does neither."
```

---

### Task 3: The JSON registry retires

**Files:**
- Modify: `agents/tools/sqlite_state.py` (remove `_validate_interview_script_registry` and its `_VALIDATORS` entry)
- Modify: `agents/tools/ownership.py:21` (remove the `interview_script_registry` entry)
- Test: `tests/test_script_registry_retired.py`

**Interfaces:**
- Consumes: `current_script_ledger_sync` from Task 2.
- Produces: nothing new. `interview_script_registry` ceases to be a writable output type.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_script_registry_retired.py
import json
from agents.tools.sqlite_state import SQLiteStateTool
from tests.test_script_ledger_registration import script_project  # noqa: F401


def test_the_json_script_registry_is_no_longer_a_writable_output(script_project):  # noqa: F811
    """The artefact retires with the ownership entry that made it writable. Leaving the
    entry would let a run write a ledger nothing reads, which is worse than no ledger:
    it looks maintained."""
    tool = SQLiteStateTool(slug=script_project, agent_name="interaction_designer", run_id=1)
    out = tool._run(operation="write", key="interview_script_registry",
                    agent_name="interaction_designer",
                    value=json.dumps({"scripts": [{"id": "SC-001", "node_id": "9.9"}]}))
    assert out.startswith("Refused:"), f"expected an ownership refusal, got: {out}"


def test_the_ledger_the_guard_reads_is_unaffected_by_that_refusal(script_project):  # noqa: F811
    """The refusal must not be able to corrupt or clear the table - the guard's record
    now lives somewhere the refused write cannot reach."""
    tool = SQLiteStateTool(slug=script_project, agent_name="interaction_designer", run_id=1)
    tool._run(operation="write", key="interview_scripts", agent_name="interaction_designer",
              value=json.dumps({"SC-001": {"node_id": "1.2", "node_label": "Works",
                                           "level": "L2", "sections": []}}))
    tool._run(operation="write", key="interview_script_registry",
              agent_name="interaction_designer",
              value=json.dumps({"scripts": [{"id": "SC-001", "node_id": "9.9"}]}))

    from agents.tools._db import current_script_ledger_sync
    ids = {e["id"]: e["node_id"] for e in current_script_ledger_sync(script_project)["scripts"]}
    assert ids == {"SC-001": "1.2"}
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_script_registry_retired.py -v`
Expected: FAIL - the write succeeds and returns `Written to ...`, so the `Refused:` assertion fails.

- [ ] **Step 3: Remove the ownership entry**

In `agents/tools/ownership.py`, delete this line (line 21):

```python
    "interview_script_registry":   "interaction_designer",
```

- [ ] **Step 4: Remove the validator**

In `agents/tools/sqlite_state.py`, delete the whole `_validate_interview_script_registry` function and its entry in `_VALIDATORS`:

```python
    "interview_script_registry": _validate_interview_script_registry,
```

Leave `validate_script_registry_succession` in `api/services/interview_script_model.py` alone - it is still the statement of the rule the table now enforces structurally, and Task 9 cites it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_script_registry_retired.py -v`
Expected: 2 passed

- [ ] **Step 6: Run the full suite twice, then commit**

Expect failures in `tests/test_sqlite_state_validation.py` covering the removed validator. Delete those tests - the behaviour is gone by design, not broken - and say in your report exactly which you removed and why each is obsolete rather than inconvenient.

```bash
git add agents/tools/ownership.py agents/tools/sqlite_state.py tests/
git commit -m "refactor(ledger): retire the JSON script registry"
```

---

### Task 4: Review events and the derived state

**Files:**
- Modify: `api/database.py` (add `_migrate_script_reviews`, bump `_SCHEMA_VERSION` to 4, register it)
- Create: `api/services/script_review_service.py`
- Test: `tests/test_script_review_service.py`

**Interfaces:**
- Consumes: `interview_script_ledger` from Task 1.
- Produces: `record_script_review(conn, *, project_id: int, script_id: str, reviewer: str, decision: str, notes: str = "", at_version: int = 0, return_to: str | None = None) -> dict` returning the ledger row as a dict; raises `ValueError` on an invalid transition. Decisions are `reviewed`, `approved`, and `changes_requested`. `return_to` is `agent` or `reviewer` and is required when the decision is `changes_requested`.

- [ ] **Step 1: Add the review history table**

In `api/database.py`, add this migration and bump `_SCHEMA_VERSION` from 3 to 4, adding the call to the `get_connection` block after `_migrate_interview_script_ledger`:

```python
async def _migrate_script_reviews(conn: aiosqlite.Connection) -> None:
    """One row per review event on one script.

    Separate from the ledger because "reviewed many times by different people, approved
    once" is a history plus a current state, and collapsing them loses who said what.
    Nothing here is ever updated or deleted.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS script_reviews (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            script_id   TEXT    NOT NULL,
            reviewer    TEXT    NOT NULL DEFAULT '',
            decision    TEXT    NOT NULL,
            notes       TEXT    NOT NULL DEFAULT '',
            at_version  INTEGER,
            return_to   TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_script_review_service.py
import pytest
from api.database import get_connection
from api.services.script_review_service import record_script_review


@pytest.fixture
async def project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    async with get_connection("rev-test") as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES ('rev-test')")
        await conn.execute(
            "INSERT INTO interview_script_ledger (script_id, project_id, node_id, last_version)"
            " VALUES ('SC-001', 1, '1.2', 5)")
        await conn.commit()
        yield conn
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_review_stamps_the_version_that_was_read(project):
    """A tick is a statement about content, not about an id. Recording which version was
    read is what lets a later change show the tick as stale instead of silently wrong."""
    row = await record_script_review(project, project_id=1, script_id="SC-001",
                                     reviewer="ana", decision="reviewed", at_version=5)
    assert row["review_status"] == "reviewed"
    assert row["reviewed_at_version"] == 5


@pytest.mark.asyncio
async def test_a_script_can_be_reviewed_by_several_people(project):
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="ana", decision="reviewed", at_version=5)
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="bo", decision="reviewed", at_version=5)
    cur = await project.execute("SELECT reviewer FROM script_reviews ORDER BY id")
    assert [r[0] for r in await cur.fetchall()] == ["ana", "bo"]


@pytest.mark.asyncio
async def test_a_script_is_approved_only_once(project):
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="ana", decision="approved", at_version=5)
    with pytest.raises(ValueError, match="already approved"):
        await record_script_review(project, project_id=1, script_id="SC-001",
                                   reviewer="bo", decision="approved", at_version=5)


@pytest.mark.asyncio
async def test_a_send_back_clears_approval_and_records_its_target(project):
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="ana", decision="approved", at_version=5)
    row = await record_script_review(project, project_id=1, script_id="SC-001",
                                     reviewer="bo", decision="changes_requested",
                                     notes="the maturity anchors are wrong",
                                     at_version=5, return_to="agent")
    assert row["review_status"] == "changes_requested"
    assert row["review_return_to"] == "agent"


@pytest.mark.asyncio
async def test_a_send_back_must_say_where_it_is_going(project):
    """A send-back with no target would default to something, and either default is wrong:
    to the agent it rewrites an instrument a reviewer is about to re-read, to the reviewer
    it silently drops a request for regeneration."""
    with pytest.raises(ValueError, match="return_to"):
        await record_script_review(project, project_id=1, script_id="SC-001",
                                   reviewer="bo", decision="changes_requested", at_version=5)
```

- [ ] **Step 3: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_script_review_service.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'api.services.script_review_service'`

- [ ] **Step 4: Write the service**

Create `api/services/script_review_service.py`:

```python
"""Per-script review, in the vocabulary the crew-level loop already uses.

The existing loop is not missing anything conceptually - it is at the wrong granularity.
agent_outputs.review_status and human_reviews.decision already carry approved,
changes_requested, dismissed, and rejected, but they apply to a whole artefact version,
and for Maya one version is all eighty-six scripts. Nobody reviews 1,711 questions in one
decision.
"""
import aiosqlite

VALID_DECISIONS = ("reviewed", "approved", "changes_requested")
VALID_RETURN_TO = ("agent", "reviewer")


async def record_script_review(
    conn: aiosqlite.Connection, *, project_id: int, script_id: str, reviewer: str,
    decision: str, notes: str = "", at_version: int = 0, return_to: str | None = None,
) -> dict:
    """Append a review event and update the ledger row's derived state.

    Approval is once per script: a second approval is refused while the row is already
    approved, and it must be sent back first. A send-back must name its target, because
    both defaults are wrong - to the agent it rewrites an instrument a reviewer is about
    to re-read, to the reviewer it silently drops a request for regeneration.
    """
    if decision not in VALID_DECISIONS:
        raise ValueError(f"unknown decision '{decision}'")
    if decision == "changes_requested":
        if return_to not in VALID_RETURN_TO:
            raise ValueError("changes_requested needs return_to of 'agent' or 'reviewer'")
    else:
        return_to = None

    cur = await conn.execute(
        "SELECT review_status FROM interview_script_ledger WHERE script_id=? AND project_id=?",
        (script_id, project_id),
    )
    row = await cur.fetchone()
    if row is None:
        raise ValueError(f"no ledger row for script_id '{script_id}'")
    if decision == "approved" and row[0] == "approved":
        raise ValueError(f"script {script_id} is already approved - send it back first")

    await conn.execute(
        "INSERT INTO script_reviews"
        " (project_id, script_id, reviewer, decision, notes, at_version, return_to)"
        " VALUES (?,?,?,?,?,?,?)",
        (project_id, script_id, reviewer, decision, notes, at_version, return_to),
    )
    await conn.execute(
        "UPDATE interview_script_ledger"
        " SET review_status=?, reviewed_at_version=?, review_return_to=?,"
        "     updated_at=CURRENT_TIMESTAMP"
        " WHERE script_id=? AND project_id=?",
        (decision, at_version, return_to, script_id, project_id),
    )
    await conn.commit()

    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
        "SELECT * FROM interview_script_ledger WHERE script_id=? AND project_id=?",
        (script_id, project_id),
    )
    return dict(await cur.fetchone())


async def scripts_awaiting_regeneration(conn: aiosqlite.Connection, *, project_id: int) -> list[dict]:
    """Ledger rows sent back to the agent, with the note that came with them.

    Only return_to = 'agent'. A return to reviewers is a human-to-human loop and must
    never reach Maya's differential.
    """
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
        "SELECT l.script_id, l.node_id, l.node_label,"
        "       (SELECT notes FROM script_reviews r WHERE r.script_id = l.script_id"
        "         ORDER BY r.id DESC LIMIT 1) AS notes"
        "  FROM interview_script_ledger l"
        " WHERE l.project_id=? AND l.review_status='changes_requested'"
        "   AND l.review_return_to='agent' AND l.active=1",
        (project_id,),
    )
    return [dict(r) for r in await cur.fetchall()]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_script_review_service.py -v`
Expected: 5 passed

- [ ] **Step 6: Add the send-back filter test**

```python
# append to tests/test_script_review_service.py
@pytest.mark.asyncio
async def test_only_a_send_back_to_the_agent_awaits_regeneration(project):
    """The load-bearing distinction. A return to reviewers must never reach Maya, or
    'please look at this again' rewrites the instrument out from under the reviewer."""
    from api.services.script_review_service import scripts_awaiting_regeneration
    await project.execute(
        "INSERT INTO interview_script_ledger (script_id, project_id, node_id) "
        "VALUES ('SC-002', 1, '1.3')")
    await project.commit()
    await record_script_review(project, project_id=1, script_id="SC-001", reviewer="bo",
                               decision="changes_requested", notes="regenerate this",
                               at_version=5, return_to="agent")
    await record_script_review(project, project_id=1, script_id="SC-002", reviewer="bo",
                               decision="changes_requested", notes="please re-read",
                               at_version=5, return_to="reviewer")
    pending = await scripts_awaiting_regeneration(project, project_id=1)
    assert [p["script_id"] for p in pending] == ["SC-001"]
    assert pending[0]["notes"] == "regenerate this"
```

- [ ] **Step 7: Run the tests, then the full suite twice, then commit**

```bash
git add api/database.py api/services/script_review_service.py tests/test_script_review_service.py
git commit -m "feat(review): per-script review events with a derived ledger state"
```

---

### Task 5: The review endpoints, authority, and notifications

**Files:**
- Create: `api/routers/script_reviews.py`
- Modify: `api/main.py` (register the router)
- Modify: `api/services/commit_notify_service.py` (add `notify_script_sent_back`)
- Test: `tests/test_script_review_endpoints.py`

**Interfaces:**
- Consumes: `record_script_review` and `scripts_awaiting_regeneration` from Task 4; `_caller_matches_stakeholder_flag` from `api/services/commit_service.py:45`.
- Produces: `GET /projects/{slug}/script-ledger` returning `list[dict]` of ledger rows; `POST /projects/{slug}/script-ledger/{script_id}/review` taking `{decision, notes, return_to}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_script_review_endpoints.py
def test_reviewing_a_script_requires_reviewer_or_approver_authority(client, seeded_script):
    """Authority comes from the stakeholder assignment - is_reviewer / is_approver - not
    from the login role. Reuses _caller_matches_stakeholder_flag so there is exactly one
    place this rule lives."""
    slug, script_id = seeded_script
    r = client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                    json={"decision": "reviewed"})
    assert r.status_code in (200, 403)


def test_approving_twice_is_refused_with_409(client, seeded_script):
    slug, script_id = seeded_script
    client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                json={"decision": "approved"})
    r = client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                    json={"decision": "approved"})
    assert r.status_code == 409, r.text
    assert "already approved" in r.text


def test_a_send_back_without_a_target_is_refused_with_422(client, seeded_script):
    slug, script_id = seeded_script
    r = client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                    json={"decision": "changes_requested", "notes": "no"})
    assert r.status_code == 422, r.text


def test_the_ledger_endpoint_returns_status_and_staleness_inputs(client, seeded_script):
    """The UI computes staleness from reviewed_at_version against last_version, so both
    must be on the wire - a server-side boolean would be stale the moment a write landed
    between the query and the render."""
    slug, _ = seeded_script
    r = client.get(f"/projects/{slug}/script-ledger")
    assert r.status_code == 200
    row = r.json()[0]
    for field in ("script_id", "node_id", "review_status",
                  "reviewed_at_version", "last_version", "last_author"):
        assert field in row
```

Write the `seeded_script` fixture in the same file, creating a project row, one ledger row via direct SQL, and returning `(slug, "SC-001")`. Read `tests/conftest.py` first and use the existing `client` fixture rather than building another - and scope every assertion to the row you created, never to a global count.

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_script_review_endpoints.py -v`
Expected: FAIL - 404 on every route, because the router does not exist.

- [ ] **Step 3: Write the router**

Create `api/routers/script_reviews.py`:

```python
"""Per-script review endpoints.

Authority is the stakeholder assignment, not the login role: is_reviewer and is_approver
on the stakeholders table already drive who may commit and who may submit, through
_caller_matches_stakeholder_flag. Reusing it means there is one place this rule lives,
and it tightens automatically when real accounts exist - today every login is sysadmin
against an empty users table, so its first branch always fires and nothing is actually
restricted yet.
"""
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_any_auth, check_project_access
from api.database import get_connection, fetch_project
from api.services.commit_service import _caller_matches_stakeholder_flag
from api.services.script_review_service import record_script_review

router = APIRouter(prefix="/projects", tags=["script-reviews"])


class ScriptReviewRequest(BaseModel):
    decision: str
    notes: str = ""
    return_to: str | None = None


@router.get("/{slug}/script-ledger")
async def get_script_ledger(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM interview_script_ledger WHERE project_id=? ORDER BY script_id",
            (project["id"],),
        )
        return [dict(r) for r in await cur.fetchall()]


@router.post("/{slug}/script-ledger/{script_id}/review")
async def review_script(
    slug: str, script_id: str, body: ScriptReviewRequest,
    payload: dict = Depends(require_any_auth),
):
    await check_project_access(slug, payload)
    flags = ("is_approver",) if body.decision == "approved" else ("is_reviewer", "is_approver")
    if not await _caller_matches_stakeholder_flag(slug, payload, flags=flags):
        raise HTTPException(status_code=403, detail="Not permitted to review this script")

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT last_version FROM interview_script_ledger"
            " WHERE script_id=? AND project_id=?", (script_id, project["id"]))
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"No script '{script_id}'")
        try:
            updated = await record_script_review(
                conn, project_id=project["id"], script_id=script_id,
                reviewer=payload.get("sub", ""), decision=body.decision,
                notes=body.notes, at_version=row["last_version"] or 0,
                return_to=body.return_to,
            )
        except ValueError as e:
            # "already approved" is a conflict with stored state; everything else the
            # service refuses is a malformed request.
            raise HTTPException(
                status_code=409 if "already approved" in str(e) else 422, detail=str(e)
            )

    if body.decision == "changes_requested":
        from api.services.commit_notify_service import notify_script_sent_back
        await notify_script_sent_back(slug, script_id, body.return_to or "", body.notes)
    return updated
```

Register it in `api/main.py` beside the other routers.

- [ ] **Step 4: Add the notification**

Append to `api/services/commit_notify_service.py`, following the existing `_notify` calls:

```python
async def notify_script_sent_back(
    slug: str, script_id: str, return_to: str, notes: str
) -> None:
    """Tell the right audience that one script has been sent back. Never raises.

    A send-back to the agent notifies reviewers, because Maya will regenerate it and they
    will need to read it again. A send-back to reviewers notifies reviewers too - they are
    the audience either way, and the difference lies in what happens to the script, not in
    who hears about it.

    The reviewer fallback to approvers is inherited from notify_crew_awaiting_commit
    deliberately: a project whose governing stakeholders are all approvers and none
    reviewers would otherwise hear nothing. The reverse fallback is not applied anywhere,
    because with no approvers there is genuinely nobody who can approve.
    """
    await _notify(
        slug, script_id,
        flags=("is_reviewer",),
        fallback_flags=("is_approver",),
        subject=f"{slug}: interview script {script_id} was sent back",
        intro=(f"{script_id} has been sent back to the {return_to}. "
               f"Note: {notes}" if notes else f"{script_id} has been sent back to the {return_to}."),
        audience_label="reviewers",
    )
```

- [ ] **Step 5: Run the tests, then the full suite twice, then commit**

```bash
git add api/routers/script_reviews.py api/main.py api/services/commit_notify_service.py tests/test_script_review_endpoints.py
git commit -m "feat(review): per-script review endpoints using the stakeholder flags"
```

---

### Task 6: Maya stops writing a ledger and starts honouring revisions

**Files:**
- Modify: `agents/discovery/interaction_designer.py` (step 3, step 4, the ledger clause near line 3203, and `expected_output`)
- Modify: `api/services/run_service.py` (inject the regeneration list)
- Modify: `tests/test_interaction_designer_prompt.py:62-66`
- Test: `tests/test_maya_revision_differential.py`

**Interfaces:**
- Consumes: `scripts_awaiting_regeneration` from Task 4.
- Produces: nothing later tasks consume.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_maya_revision_differential.py
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_a_script_sent_back_to_the_agent_reaches_the_task_maya_receives():
    """Asserted on the description the task actually carries, not on the ledger row. The
    row is the mechanism; the prompt is the property. Without this clause a revision
    request arrives beside an instruction to skip every node that already has a script,
    and she ignores it."""
    seen = {}

    async def _fake_kickoff(self):
        seen["description"] = self.tasks[0].description
        return "ok"

    with patch("api.services.script_review_service.scripts_awaiting_regeneration",
               new=AsyncMock(return_value=[
                   {"script_id": "SC-042", "node_id": "3.3.2", "node_label": "Billing",
                    "notes": "the maturity anchors are wrong"}])):
        with patch("crewai.Crew.kickoff_async", new=_fake_kickoff):
            from api.services.run_service import build_and_run_crew
            await build_and_run_crew("rev-slug", "assessment_design", run_id=7)

    assert "SC-042" in seen["description"]
    assert "the maturity anchors are wrong" in seen["description"]
```

Read `build_and_run_crew`'s real signature before writing this and adapt the call - do not assume it takes those arguments positionally.

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_maya_revision_differential.py -v`
Expected: FAIL - `assert "SC-042" in seen["description"]`, because nothing injects the list.

- [ ] **Step 3: Inject the regeneration list**

In `api/services/run_service.py`, in the block that assembles the task description for `assessment_design`, add:

```python
    if crew_name == "assessment_design":
        from api.services.script_review_service import scripts_awaiting_regeneration
        async with get_connection(slug) as conn:
            project = await fetch_project(conn, slug=slug)
            pending = await scripts_awaiting_regeneration(
                conn, project_id=project["id"]) if project else []
        if pending:
            lines = "\n".join(
                f"- {p['script_id']} ({p['node_id']} {p['node_label']}): {p['notes']}"
                for p in pending)
            sections.append(
                "SCRIPTS SENT BACK FOR REVISION. Regenerate each of these in full, "
                "addressing the note. They already have a script, so step 4's differential "
                "would otherwise skip them - these are the exception:\n" + lines
            )
```

- [ ] **Step 4: Add the prompt clause**

In `agents/discovery/interaction_designer.py`, extend step 4 so the differential names both cases:

```python
            "4. Generate scripts ONLY for activities with no script yet, AND for any "
            "script listed under SCRIPTS SENT BACK FOR REVISION. Do not re-emit any other "
            "existing script. A sent-back script is regenerated in full, addressing the "
            "note that came with it, and keeps its existing script_id - it is the same "
            "instrument at the same node, revised.\n"
```

- [ ] **Step 5: Remove the ledger instructions**

Delete step 3's `interview_script_registry` read, the whole registry write instruction including the `THE LEDGER IS CUMULATIVE` clause near line 3203, and the `(2) interview_script_registry.json ...` clause from `expected_output`. The ledger is maintained by the write path now; instructing her to write one would produce a refused write on every run.

- [ ] **Step 6: Update the prompt regression tests**

Replace `test_the_prompt_states_the_ledger_is_cumulative_and_keyed_by_script_id` in `tests/test_interaction_designer_prompt.py` with:

```python
def test_the_prompt_no_longer_asks_maya_to_write_a_ledger():
    """The ledger is maintained by the write path. An instruction to write one would now
    produce a refused write on every run, because the output type lost its ownership entry
    when the artefact retired."""
    src = _src()
    assert "THE LEDGER IS CUMULATIVE" not in src
    assert "interview_script_registry" not in src


def test_the_prompt_tells_her_a_sent_back_script_is_the_differential_exception():
    """Step 4 says generate only what is missing. Without naming the exception, a revision
    request is an instruction she has been told to ignore."""
    src = _src()
    assert "SCRIPTS SENT BACK FOR REVISION" in src
    assert "keeps its existing script_id" in src
```

- [ ] **Step 7: Run the tests to verify they pass, then power-check**

Run: `./venv/bin/pytest tests/test_maya_revision_differential.py tests/test_interaction_designer_prompt.py -v`

Then revert only the step 4 edit, re-run, and confirm `test_the_prompt_tells_her_a_sent_back_script_is_the_differential_exception` FAILS. Restore. Report the observed failure text.

- [ ] **Step 8: Run the full suite twice, then commit**

```bash
git add agents/discovery/interaction_designer.py api/services/run_service.py tests/
git commit -m "feat(maya): the ledger is no longer hers to write, and a send-back is regenerated"
```

---

### Task 7: The human edit path is rebuilt

**Files:**
- Modify: `api/routers/projects.py:518-546` (replace both `{node_label}` routes with `{script_id}`)
- Modify: `ui/src/components/InterviewTemplateEditor.tsx:51,67`
- Test: `tests/test_interview_script_edit.py`

**Interfaces:**
- Consumes: `register_scripts_sync` from Task 2 (called for it by `SQLiteStateTool`).
- Produces: `GET /projects/{slug}/interview-scripts/{script_id}`, `PATCH /projects/{slug}/interview-scripts/{script_id}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interview_script_edit.py
def test_a_human_edit_produces_a_new_version_and_a_ledger_row_naming_the_person(
        client, seeded_scripts):
    """The old PATCH wrote outputs/interview_scripts.json - a bare, unversioned file that
    does not exist on a project Maya has run, keyed by node_label while the artefact is
    keyed by script_id. The edit went nowhere and nothing said so."""
    slug = seeded_scripts
    before = client.get(f"/projects/{slug}/interview-scripts").json()
    assert "SC-001" in before

    r = client.patch(f"/projects/{slug}/interview-scripts/SC-001",
                     json={"script": {**before["SC-001"], "node_label": "Edited Label"}})
    assert r.status_code == 200, r.text

    after = client.get(f"/projects/{slug}/interview-scripts").json()
    assert after["SC-001"]["node_label"] == "Edited Label"

    ledger = client.get(f"/projects/{slug}/script-ledger").json()
    row = next(x for x in ledger if x["script_id"] == "SC-001")
    assert row["last_author"] != "interaction_designer", "a human edit must name the person"
    assert row["last_version"] > 1, "the edit must have produced a new version"


def test_editing_a_reviewed_script_resets_its_review_status(client, seeded_scripts):
    """The tick described content that no longer exists."""
    slug = seeded_scripts
    client.post(f"/projects/{slug}/script-ledger/SC-001/review", json={"decision": "reviewed"})
    before = client.get(f"/projects/{slug}/interview-scripts").json()
    client.patch(f"/projects/{slug}/interview-scripts/SC-001",
                 json={"script": {**before["SC-001"], "node_label": "Changed"}})
    ledger = client.get(f"/projects/{slug}/script-ledger").json()
    assert next(x for x in ledger if x["script_id"] == "SC-001")["review_status"] == "pending"
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_interview_script_edit.py -v`
Expected: FAIL - 404 or 405, because the route is keyed by `node_label`.

- [ ] **Step 3: Replace both routes**

In `api/routers/projects.py`, replace `get_interview_script` and `patch_interview_script`:

```python
@router.get("/{slug}/interview-scripts/{script_id}")
async def get_interview_script(
    slug: str, script_id: str, payload: dict = Depends(require_any_auth)
):
    """One script from the current artefact, resolved through the ledger.

    Keyed by script_id because that is what the artefact is keyed by, what
    _merge_with_current merges on, and what stakeholder assignments and stored answers
    cite. The previous node_label form read a bare interview_scripts.json that
    insert_agent_output_sync renames away on every write.
    """
    await check_project_access(slug, payload)
    scripts = await list_interview_scripts(slug, payload)
    if script_id not in scripts:
        raise HTTPException(status_code=404, detail=f"No script '{script_id}'")
    return scripts[script_id]


@router.patch("/{slug}/interview-scripts/{script_id}")
async def patch_interview_script(
    slug: str, script_id: str, body: InterviewScriptPatch,
    payload: dict = Depends(require_org_admin_or_above),
):
    """Edit one script, through the same door the agent writes by.

    SQLiteStateTool gives the edit a version, the validators, and a ledger row recording
    last_author as the person. Writing the file directly would skip all three, which is
    what the previous implementation did.
    """
    await check_project_access(slug, payload)
    from agents.tools.sqlite_state import SQLiteStateTool

    scripts = await list_interview_scripts(slug, payload)
    if script_id not in scripts:
        raise HTTPException(status_code=404, detail=f"No script '{script_id}'")
    merged = {script_id: {**body.script, "script_id": script_id,
                          "node_id": scripts[script_id].get("node_id")}}

    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=0)
    result = tool._run(operation="write", key="interview_scripts",
                       agent_name="interaction_designer", value=json.dumps(merged))
    if not result.startswith("Written to"):
        raise HTTPException(status_code=422, detail=result)

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        await conn.execute(
            "UPDATE interview_script_ledger"
            " SET last_author=?, review_status='pending', review_return_to=NULL,"
            "     updated_at=CURRENT_TIMESTAMP"
            " WHERE script_id=? AND project_id=?",
            (payload.get("sub", "human"), script_id, project["id"]),
        )
        await conn.commit()
    updated = await auto_assign_interview_scripts(slug)
    return {"ok": True, "templates_updated": updated}
```

The `node_id` is taken from the stored script, not from the body: a human edit changes content, never the anchor, and letting the body carry `node_id` would reopen the id-moving hole from the outside.

- [ ] **Step 4: Point the editor at script_id**

In `ui/src/components/InterviewTemplateEditor.tsx`, change both calls at lines 51 and 67 from `nodeLabel` to a `scriptId` prop, and update its callers. Read the component and its call sites first.

- [ ] **Step 5: Run the tests, the frontend suite, then the backend twice, then commit**

Run: `./venv/bin/pytest tests/test_interview_script_edit.py -v`, then from `ui/`: `npx vitest run && npx tsc --noEmit`.

```bash
git add api/routers/projects.py ui/src/components/InterviewTemplateEditor.tsx tests/test_interview_script_edit.py
git commit -m "fix(scripts): the human edit path versions, validates, and lands where the app reads"
```

---

### Task 8: The minimal review UI

**Files:**
- Modify: `ui/src/components/tabs/MayaOutputExtra.tsx:289-330`
- Modify: `ui/src/api/endpoints.ts`
- Modify: `ui/src/types.ts`
- Test: `ui/src/__tests__/ScriptReviewRow.test.tsx`

**Interfaces:**
- Consumes: `GET /projects/{slug}/script-ledger` and `POST .../review` from Task 5.
- Produces: nothing later tasks consume.

- [ ] **Step 1: Add the client calls and type**

In `ui/src/api/endpoints.ts`:

```ts
  getScriptLedger: (slug: string): Promise<import('../types').ScriptLedgerRow[]> =>
    apiClient.get(`/projects/${slug}/script-ledger`).then((r) => r.data),

  reviewScript: (slug: string, scriptId: string,
                 body: { decision: string; notes?: string; return_to?: string }) =>
    apiClient.post(`/projects/${slug}/script-ledger/${scriptId}/review`, body).then((r) => r.data),
```

In `ui/src/types.ts`:

```ts
export interface ScriptLedgerRow {
  script_id: string
  node_id: string
  node_label: string
  review_status: 'pending' | 'reviewed' | 'approved' | 'changes_requested'
  reviewed_at_version: number | null
  review_return_to: 'agent' | 'reviewer' | null
  last_version: number | null
  last_author: string
}
```

- [ ] **Step 2: Write the failing test**

```tsx
// ui/src/__tests__/ScriptReviewRow.test.tsx
import { render, screen } from '@testing-library/react'
import { ScriptReviewRow } from '../components/tabs/ScriptReviewRow'

const base = {
  script_id: 'SC-001', node_id: '1.2', node_label: 'Works Programming',
  review_status: 'reviewed' as const, reviewed_at_version: 3,
  review_return_to: null, last_version: 5, last_author: 'interaction_designer',
}

it('marks a review as stale when the script changed after it was read', () => {
  // reviewed_at_version 3 against last_version 5: the tick describes content nobody has
  // read. Showing it as a plain tick is the failure this indicator exists to prevent.
  render(<ScriptReviewRow row={base} onReview={() => {}} />)
  expect(screen.getByText(/changed since/i)).toBeInTheDocument()
})

it('does not mark a review stale when it was read at the current version', () => {
  render(<ScriptReviewRow row={{ ...base, reviewed_at_version: 5 }} onReview={() => {}} />)
  expect(screen.queryByText(/changed since/i)).not.toBeInTheDocument()
})

it('shows an unreviewed script as awaiting review, not as stale', () => {
  render(<ScriptReviewRow
    row={{ ...base, review_status: 'pending', reviewed_at_version: null }}
    onReview={() => {}} />)
  expect(screen.queryByText(/changed since/i)).not.toBeInTheDocument()
  expect(screen.getByText(/awaiting review/i)).toBeInTheDocument()
})
```

- [ ] **Step 3: Run to verify it fails**

Run from `ui/`: `npx vitest run ScriptReviewRow`
Expected: FAIL - cannot resolve `../components/tabs/ScriptReviewRow`.

- [ ] **Step 4: Write the component**

Create `ui/src/components/tabs/ScriptReviewRow.tsx`:

```tsx
import { Check, CircleDashed, RotateCcw, ShieldCheck } from 'lucide-react'
import type { ScriptLedgerRow } from '../../types'

const LABEL: Record<ScriptLedgerRow['review_status'], string> = {
  pending: 'Awaiting review',
  reviewed: 'Reviewed',
  approved: 'Approved',
  changes_requested: 'Sent back',
}

const ICON: Record<ScriptLedgerRow['review_status'], typeof Check> = {
  pending: CircleDashed,
  reviewed: Check,
  approved: ShieldCheck,
  changes_requested: RotateCcw,
}

export function ScriptReviewRow(
  { row, onReview }: {
    row: ScriptLedgerRow
    onReview: (scriptId: string, decision: string, returnTo?: string) => void
  },
) {
  // Staleness is computed here from two numbers on the wire rather than sent as a boolean:
  // a server-side flag would be wrong the moment a write landed between query and render.
  const stale = row.reviewed_at_version !== null
    && row.last_version !== null
    && row.reviewed_at_version < row.last_version
  const Icon = ICON[row.review_status]

  return (
    <div className="flex items-center gap-2 py-1.5 text-xs border-b border-surface-raised">
      <Icon size={12} className="text-muted shrink-0" />
      <span className="font-mono text-muted w-16 shrink-0">{row.script_id}</span>
      <span className="text-secondary truncate flex-1">{row.node_label || row.node_id}</span>
      <span className="text-muted shrink-0">{LABEL[row.review_status]}</span>
      {stale && (
        <span className="text-amber-600 shrink-0">
          changed since (v{row.reviewed_at_version} → v{row.last_version})
        </span>
      )}
      <button onClick={() => onReview(row.script_id, 'reviewed')}
              className="text-brand hover:underline shrink-0">Mark reviewed</button>
      <button onClick={() => onReview(row.script_id, 'changes_requested', 'agent')}
              className="text-muted hover:underline shrink-0">Send back</button>
    </div>
  )
}
```

- [ ] **Step 5: Wire it into Maya's Output tab**

In `ui/src/components/tabs/MayaOutputExtra.tsx`, add a `useQuery` on `projectsApi.getScriptLedger(slug)` beside the existing `['interview-scripts', slug]` query, and render a `ScriptReviewRow` per row above the existing `vcScripts` / `extScripts` sections. `onReview` calls `projectsApi.reviewScript` and invalidates `['script-ledger', slug]`.

- [ ] **Step 6: Run the tests to verify they pass, then power-check**

Run from `ui/`: `npx vitest run ScriptReviewRow`

Then change `<` to `<=` in the `stale` computation and re-run: the second test must FAIL. Restore. Report the observed failure text - an off-by-one here shows every reviewed script as stale, which would train people to ignore the indicator.

- [ ] **Step 7: Run the full frontend suite and tsc, then commit**

```bash
git add ui/src/components/tabs/ScriptReviewRow.tsx ui/src/components/tabs/MayaOutputExtra.tsx ui/src/api/endpoints.ts ui/src/types.ts ui/src/__tests__/ScriptReviewRow.test.tsx
git commit -m "feat(ui): per-script review status, staleness, and send-back"
```

---

### Task 9: Backfill the live project, verify end to end, and record it

**Files:**
- Modify: `CLAUDE.md`
- Data: `data/sp-gs-am.db`

- [ ] **Step 1: Back up the live database first**

```bash
cp data/sp-gs-am.db "$CLAUDE_JOB_DIR/tmp/sp-gs-am.db.bak"
ls -la "$CLAUDE_JOB_DIR/tmp/sp-gs-am.db.bak"
```

- [ ] **Step 2: Back-fill the live ledger and verify against the artefact**

```bash
./venv/bin/python -c "
import asyncio, json
from pathlib import Path
from api.database import get_connection, fetch_project
from api.services.script_ledger_backfill import backfill_script_ledger
from agents.tools._db import current_script_ledger_sync

async def main():
    reg = json.loads(Path('projects/sp-gs-am/outputs/interview_script_registry_v4.json').read_text())
    async with get_connection('sp-gs-am') as conn:
        p = await fetch_project(conn, slug='sp-gs-am')
        print('inserted:', await backfill_script_ledger(conn, project_id=p['id'], registry=reg))
    led = {e['id']: e['node_id'] for e in current_script_ledger_sync('sp-gs-am')['scripts']}
    scr = json.loads(Path('projects/sp-gs-am/outputs/interview_scripts_v35.json').read_text())
    print('ledger rows:', len(led), '| scripts:', len(scr))
    print('unregistered:', sorted(set(scr) - set(led)) or 'none')
    print('mismatches  :', [(k, led[k], scr[k].get('node_id')) for k in led if k in scr and led[k] != scr[k].get('node_id')] or 'none')
asyncio.run(main())"
```

Expected: `inserted: 86`, `ledger rows: 86 | scripts: 86`, `unregistered: none`, `mismatches: none`. **If any of those differ, stop and report rather than proceeding** - the table is now the guard's only record, and a wrong backfill is worse than none.

- [ ] **Step 3: Prove a write registers against the live shape**

Do **not** run a crew. Write one existing script back through `SQLiteStateTool` on a copy of the database, confirm the ledger is unchanged at 86 rows and the id keeps its node, and confirm the write is refused if the node is altered. Report both.

- [ ] **Step 4: Run both suites**

Run `./venv/bin/pytest -q` twice with identical counts, then from `ui/`: `npx vitest run && npx tsc --noEmit`.

- [ ] **Step 5: Update CLAUDE.md**

Replace the two known-issues entries this work resolves - the `interview-scripts/{node_label}` endpoints entry - and add under **Crew / agent conventions**:

```markdown
The script ledger is a table, `interview_script_ledger`, with `script_id` as its primary
key. It is maintained by the write path: every `interview_scripts` write registers ids it
has not seen, and never moves one it has. Maya does not write it - the JSON
`interview_script_registry` artefact is retired, and the output type has no owner, so a
write to it is refused. Run 32 is why: it wrote 41 scripts, hit CrewAI's default
`max_iter` before its ledger write, and reported `completed` with 41 ids outside the
succession guarantee.

Review is per script, not per artefact version. `script_reviews` holds one row per review
event and the ledger row carries the derived state, because a script is reviewed by
several people and approved once. A send-back carries `review_return_to`: only `agent`
enters Maya's differential, because a return to `reviewer` that regenerated the script
would rewrite the instrument the reviewer was about to re-read.
```

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the script ledger table and per-script review"
```

---

## Self-Review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| Ledger becomes a table, `script_id` primary key | 1 |
| `_SCHEMA_VERSION` bumped with each migration | 1, 4 |
| Backfill from the reconciled JSON ledger | 1, 9 |
| Registration is a side effect of the write, append-only | 2 |
| Guard reads the table, pure function unchanged | 2 |
| JSON registry retires, ownership entry removed | 3 |
| Maya's ledger instructions removed | 6 |
| `script_reviews` history, derived state, approved once | 4 |
| `review_return_to`, only `agent` regenerates | 4, 6 |
| Authority from `is_reviewer` / `is_approver` | 5 |
| Asymmetric notification fallback inherited | 5 |
| Differential clause for sent-back scripts | 6 |
| Human edit versions, validates, records `last_author` | 7 |
| Editing resets review status | 7 |
| Minimal UI: list, status, tick, send back, staleness | 8 |
| Soft revert | none - deferred by the spec |
| Review workbench | none - deferred by the spec |

**Placeholder scan:** none. Four steps direct the implementer to read real code before writing - the `seeded_script` fixture in Task 5, `build_and_run_crew`'s signature in Task 6, `InterviewTemplateEditor`'s call sites in Task 7, and `MayaOutputExtra`'s query shape in Task 8 - stated explicitly because briefs on this project have been wrong about details repeatedly.

**Type consistency:** `register_scripts_sync(slug, scripts, version, author) -> int` is defined in Task 2 and called only from `sqlite_state.py` in the same task. `current_script_ledger_sync(slug) -> dict` is defined in Task 2 and consumed by Task 2's guard and Tasks 3 and 9's assertions, returning `{"scripts": [{"id", "node_id", "active"}]}` - the shape `validate_scripts_against_script_registry` already reads. `record_script_review(...) -> dict` and `scripts_awaiting_regeneration(...) -> list[dict]` are defined in Task 4 and consumed in Tasks 5 and 6. `ScriptLedgerRow` in Task 8 matches the columns Task 1 creates and Task 5 serialises.

**One ordering note:** Task 3 retires the JSON registry before Task 6 removes Maya's instruction to write it. That order is deliberate - between them a run would make a refused write, which is loud and harmless, whereas the reverse order leaves a window where she writes a ledger nothing reads, which is silent and looks fine.
