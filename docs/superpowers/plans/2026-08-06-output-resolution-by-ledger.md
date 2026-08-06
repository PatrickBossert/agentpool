# Output Resolution by Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the current version of an output from `agent_outputs`, which already records it, instead of from the highest `_vN` on disk.

**Architecture:** A new sync resolver reads the ledger, falls back to the disk glob only when the ledger has nothing to say, and records a warning when the ledger names a file that is gone. `latest_output_path` survives as that fallback. One prerequisite lands first: a filename family must be claimed by exactly one output type, or a resolver keyed on type returns confidently wrong answers.

**Tech Stack:** Python 3.13, aiosqlite for the async API, raw `sqlite3` for the sync tool path, pytest.

## Global Constraints

- British English, `-ise` / `-our` / `-re`, Oxford comma. En dash ` - ` with spaces, never an em dash.
- Python 3.13 only. `./venv/bin/pytest`, `./venv/bin/python`.
- **Run the suite twice.** Isolate with `monkeypatch.setenv("DATABASE_DIR", str(tmp_path))` plus `get_settings.cache_clear()` on both sides. Async fixtures use `@pytest_asyncio.fixture` - `asyncio_mode = strict`.
- `projects` has **no `name` column**: insert with `(slug, sector)`.
- Assert the property where it holds. For each test: *what calls this, and is that tested?*
- Full backend suite is `./venv/bin/pytest -q --ignore=tests/integration` - the integration tests make real LLM calls and take ~10 minutes.

---

## Task 1: One output type per filename family

**Files:**
- Modify: `agents/tools/derive_registry.py:153` (`output_type="state"` → `"value_chain_registry"`)
- Modify: `api/database.py` (new `_migrate_registry_output_type`, registered after `_migrate_validation_warnings`)
- Test: `tests/test_output_type_families.py` *(new)*

**Interfaces:**
- Produces: no new symbol. The invariant "one filename family, one output type" becomes testable.

`DeriveRegistryTool` writes `value_chain_registry_vN.json` as `output_type="state"`, while `SQLiteStateTool` writes the same family as `"value_chain_registry"`. A resolver keyed on output type would look up `value_chain_registry`, find only the tool's rows, and miss every registry the derive tool wrote - confidently wrong rather than approximately right. This also explains why `state` legitimately carries two `is_current` rows and could never be pruned.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_output_type_families.py
"""A filename family belongs to exactly one output type.

DeriveRegistryTool wrote value_chain_registry_vN.json as output_type='state' while
SQLiteStateTool wrote the same family as 'value_chain_registry'. Two writers, one family,
two types - which is why the clean-baseline prune demoted value_chain_summary v12 to v4
and value_chain_tree v13 to v9, and why 'state' could never be pruned.
"""
import json
import re
import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings
from api.database import get_connection

_VERSIONED = re.compile(r"^(?P<stem>.+?)_v\d+$")


def _family(file_path: str) -> str:
    """The filename family a path belongs to: 'value_chain_registry_v5.json' -> the stem."""
    stem = Path(file_path).stem
    m = _VERSIONED.match(stem)
    return m.group("stem") if m else stem


@pytest_asyncio.fixture
async def derive_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "family-test"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
    (outputs / "value_chain_tree.json").write_text(json.dumps(
        [{"id": "0", "label": "Org", "level": "L0", "children": [
            {"id": "1", "label": "Chain", "level": "L1"}]}]))
    yield slug, outputs, tmp_path
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_derived_registry_is_recorded_as_a_registry(derive_db):
    slug, outputs, _ = derive_db
    from agents.tools.derive_registry import DeriveRegistryTool

    assert not DeriveRegistryTool(slug=slug)._run().startswith("Error")

    async with get_connection(slug) as conn:
        async with conn.execute(
            "SELECT output_type, file_path FROM agent_outputs WHERE is_current=1"
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    reg = [r for r in rows if "value_chain_registry" in r["file_path"]]
    assert reg, "no row was written for the derived registry"
    assert reg[0]["output_type"] == "value_chain_registry", \
        f"derived registry recorded as {reg[0]['output_type']!r}"


@pytest.mark.asyncio
async def test_no_filename_family_is_claimed_by_two_output_types(derive_db):
    """The invariant the resolver depends on. A future writer that reintroduces the split
    fails here rather than in a demo."""
    slug, outputs, _ = derive_db
    from agents.tools.derive_registry import DeriveRegistryTool

    DeriveRegistryTool(slug=slug)._run()

    async with get_connection(slug) as conn:
        async with conn.execute(
            "SELECT output_type, file_path FROM agent_outputs") as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    families: dict[str, set] = {}
    for r in rows:
        families.setdefault(_family(r["file_path"]), set()).add(r["output_type"])
    split = {f: t for f, t in families.items() if len(t) > 1}
    assert not split, f"filename families claimed by more than one type: {split}"


@pytest.mark.asyncio
async def test_the_migration_retypes_existing_state_rows(derive_db):
    """A project migrated from before this change must end up with the same invariant."""
    slug, outputs, tmp = derive_db
    reg_file = outputs / "value_chain_registry_v3.json"
    reg_file.write_text(json.dumps({"activities": []}))
    other = outputs / "some_other_state_v1.json"
    other.write_text("{}")

    async with get_connection(slug) as conn:
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            pid = (await cur.fetchone())[0]
        for path in (reg_file, other):
            await conn.execute(
                "INSERT INTO agent_outputs"
                " (project_id, agent_name, output_type, file_path, version, is_current)"
                " VALUES (?,?,?,?,?,1)",
                (pid, "value_chain_mapper", "state", str(path), 3))
        await conn.commit()

    # Reopening runs the migrations.
    async with get_connection(slug) as conn:
        async with conn.execute(
            "SELECT output_type, file_path FROM agent_outputs"
            " WHERE file_path LIKE '%value_chain_registry%'") as cur:
            retyped = [dict(r) for r in await cur.fetchall()]
        async with conn.execute(
            "SELECT output_type FROM agent_outputs"
            " WHERE file_path LIKE '%some_other_state%'") as cur:
            untouched = [dict(r) for r in await cur.fetchall()]

    assert all(r["output_type"] == "value_chain_registry" for r in retyped), retyped
    assert all(r["output_type"] == "state" for r in untouched), \
        "a state row naming something else must be left alone"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_output_type_families.py -v`
Expected: FAIL - the derived registry is recorded as `'state'`

- [ ] **Step 3: Re-type the derive tool's write**

In `agents/tools/derive_registry.py`, at the `insert_agent_output_sync` call (line ~153):

```python
            insert_agent_output_sync(
                slug=self.slug,
                agent_name=agent_name,
                # Not "state". This tool and SQLiteStateTool both write the
                # value_chain_registry_vN family, and recording them under different types
                # made one filename family answer to two ledgers - which is why 'state'
                # carried two is_current rows, why it could never be pruned, and why
                # deleting rows of one type demoted files belonging to the other.
                output_type="value_chain_registry",
                file_path=str(registry_path),
            )
```

- [ ] **Step 4: Add the migration**

In `api/database.py`, beside the other migrations:

```python
async def _migrate_registry_output_type(conn: aiosqlite.Connection) -> None:
    """Re-type the registry rows DeriveRegistryTool wrote as 'state'.

    Matched on file_path, not on agent or version: the fault was always that the row's type
    disagreed with the family its file belongs to, and the file is the only witness to
    that. A 'state' row naming anything else is left alone - state is a real output type
    with real rows.
    """
    await conn.execute(
        "UPDATE agent_outputs SET output_type='value_chain_registry'"
        " WHERE output_type='state'"
        "   AND file_path LIKE '%value_chain_registry%'"
    )
    await conn.commit()
```

Register it after `_migrate_validation_warnings(conn)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_output_type_families.py -v`
Expected: 3 passed

- [ ] **Step 6: Check the live project for the split**

```bash
./venv/bin/python -c "
import sqlite3, re
from pathlib import Path
c = sqlite3.connect('data/sp-gs-am.db')
fam = {}
for t, p in c.execute('SELECT output_type, file_path FROM agent_outputs'):
    stem = Path(p).stem
    m = re.match(r'^(?P<s>.+?)_v\d+$', stem)
    fam.setdefault(m.group('s') if m else stem, set()).add(t)
split = {f: t for f, t in fam.items() if len(t) > 1}
print('split families:', split or 'none')
"
```

Expected: `none`. If any remain, they are further instances of the same fault and must be resolved before Task 2.

- [ ] **Step 7: Commit**

```bash
git add agents/tools/derive_registry.py api/database.py tests/test_output_type_families.py
git commit -m "fix(outputs): one filename family answers to one output type"
```

---

## Task 2: The ledger-backed resolver

**Files:**
- Modify: `agents/tools/_db.py` (new `current_output_path`, beside `latest_output_path`)
- Test: `tests/test_current_output_path.py` *(new)*

**Interfaces:**
- Consumes: `record_validation_warnings_sync` (already present), `get_project_id`.
- Produces: `current_output_path(slug: str, output_type: str, *, run_id: int = 0) -> Path | None`.

Sync and raw `sqlite3`, matching the other helpers in this module, because the tool path is not async.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_current_output_path.py
"""The ledger decides which version is current, not the highest number on disk.

value_chain_summary v5 was written on 6 August and marked current. v9, v11 and v12 from
mid-July sat beside it, so every agent read the 15 July file - which names DXI as fleet
maintainer, three weeks after a human corrected that to Fraikin.
"""
import json
import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, fetch_validation_warnings
from agents.tools._db import current_output_path, latest_output_path


@pytest_asyncio.fixture
async def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "ledger-test"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            pid = (await cur.fetchone())[0]

    async def add(output_type, version, current, write_file=True):
        p = outputs / f"{output_type}_v{version}.json"
        if write_file:
            p.write_text(json.dumps({"v": version}))
        async with get_connection(slug) as conn:
            await conn.execute(
                "INSERT INTO agent_outputs"
                " (project_id, agent_name, output_type, file_path, version, is_current)"
                " VALUES (?,?,?,?,?,?)",
                (pid, "value_chain_mapper", output_type, str(p), version,
                 1 if current else 0))
            await conn.commit()
        return p

    yield slug, outputs, pid, add
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_ledger_wins_over_a_higher_number_on_disk(ledger):
    """The value_chain_summary incident, as a test."""
    slug, outputs, _, add = ledger
    await add("value_chain_summary", 5, current=True)
    (outputs / "value_chain_summary_v12.json").write_text(json.dumps({"v": 12}))

    assert latest_output_path(outputs / "value_chain_summary.json").name \
        == "value_chain_summary_v12.json", "precondition: the glob prefers v12"
    resolved = current_output_path(slug, "value_chain_summary")
    assert resolved is not None and resolved.name == "value_chain_summary_v5.json"


@pytest.mark.asyncio
async def test_a_revert_is_honoured(ledger):
    """Newer files stay on disk; the ledger points at the reverted version."""
    slug, outputs, _, add = ledger
    await add("value_chain_tree", 12, current=False)
    await add("value_chain_tree", 4, current=True)

    assert (outputs / "value_chain_tree_v12.json").exists()
    assert current_output_path(slug, "value_chain_tree").name == "value_chain_tree_v4.json"


@pytest.mark.asyncio
async def test_no_row_falls_back_to_the_disk_glob(ledger):
    """A first write, or a hand-written file, must still resolve."""
    slug, outputs, _, _ = ledger
    (outputs / "hand_written_v2.json").write_text("{}")
    assert current_output_path(slug, "hand_written").name == "hand_written_v2.json"


@pytest.mark.asyncio
async def test_no_row_and_no_file_is_none(ledger):
    slug, _, _, _ = ledger
    assert current_output_path(slug, "never_written") is None


@pytest.mark.asyncio
async def test_a_dangling_row_returns_none_rather_than_a_stale_file(ledger):
    """Falling through to the glob is what turns a broken pointer into a wrong answer."""
    slug, outputs, _, add = ledger
    await add("value_chain_model", 9, current=True, write_file=False)
    (outputs / "value_chain_model_v2.json").write_text(json.dumps({"v": 2}))

    assert current_output_path(slug, "value_chain_model") is None, \
        "a lost current version must not silently resolve to an older one"


@pytest.mark.asyncio
async def test_a_dangling_row_records_the_way_out(ledger):
    """A warning that says only 'file missing' leaves the reader to do the investigation
    the warning existed to save."""
    slug, outputs, pid, add = ledger
    await add("value_chain_model", 9, current=True, write_file=False)
    (outputs / "value_chain_model_v2.json").write_text("{}")
    (outputs / "value_chain_model_v7.json").write_text("{}")

    current_output_path(slug, "value_chain_model", run_id=42)

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=pid, sources=["output_resolution"])
    assert len(rows) == 1
    w = rows[0]
    assert w["code"] == "current_file_missing"
    assert w["subject"] == "value_chain_model"
    assert "v9" in w["detail"] or "9" in w["detail"]
    assert "value_chain_model_v9.json" in w["detail"], "names the missing file"
    assert "2" in w["detail"] and "7" in w["detail"], \
        "names the versions still on disk, so reverting is a decision not an investigation"


@pytest.mark.asyncio
async def test_resolving_twice_does_not_duplicate_the_warning(ledger):
    slug, _, pid, add = ledger
    await add("value_chain_model", 9, current=True, write_file=False)
    current_output_path(slug, "value_chain_model")
    current_output_path(slug, "value_chain_model")
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=pid, sources=["output_resolution"])
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_an_unversioned_file_is_still_found(ledger):
    """latest_output_path prefers the un-suffixed path; the fallback must keep that."""
    slug, outputs, _, _ = ledger
    (outputs / "legacy_thing.json").write_text("{}")
    assert current_output_path(slug, "legacy_thing").name == "legacy_thing.json"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_current_output_path.py -v`
Expected: FAIL with `ImportError: cannot import name 'current_output_path'`

- [ ] **Step 3: Write the resolver**

In `agents/tools/_db.py`, immediately after `latest_output_path`:

```python
def current_output_path(
    slug: str, output_type: str, *, run_id: int = 0
) -> Path | None:
    """The file the ledger marks current for this output type.

    agent_outputs already records this and already maintains it: insert_agent_output_sync
    sweeps is_current and stores the versioned path, and revert_to_version repoints
    is_current to the reverted version. Reverting is exactly the case a filename-ordering
    scheme cannot express - the newer files are still on disk, and they are not the answer.

    Three outcomes, deliberately distinct:

      row + file exists  -> the file
      row, file missing  -> None, and a warning naming what survives. Falling through to
                            the glob here is what turns a broken pointer into a wrong
                            answer, which is how the 15 July summary was read for weeks.
      no row             -> latest_output_path, which covers a first write (the file is
                            written and renamed before its row exists), a hand-written
                            file, and projects predating versioning.
    """
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / slug / "outputs"
    base = outputs_dir / f"{output_type}.json"

    try:
        with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
            row = conn.execute(
                "SELECT version, file_path FROM agent_outputs"
                " WHERE project_id=? AND output_type=? AND is_current=1"
                " ORDER BY version DESC LIMIT 1",
                (get_project_id(slug), output_type),
            ).fetchone()
    except sqlite3.Error:
        return latest_output_path(base)   # an unreadable ledger is not an answer

    if row is None:
        return latest_output_path(base)

    version, file_path = row[0], Path(row[1])
    if file_path.exists():
        return file_path

    _record_missing_current(slug, output_type, version, file_path, outputs_dir, run_id)
    return None


def _record_missing_current(
    slug: str, output_type: str, version, file_path: Path, outputs_dir: Path, run_id: int
) -> None:
    """Name the output, the version, the missing file, and what is left to revert to.

    The reader has two remedies - revert to a version that still exists, or restore a
    backup by hand - and neither is possible without knowing what survives.
    """
    pattern = re.compile(rf"^{re.escape(output_type)}_v(\d+)\.json$")
    survivors = sorted(
        int(m.group(1))
        for p in outputs_dir.glob(f"{output_type}_v*.json")
        if (m := pattern.match(p.name))
    )
    available = ", ".join(f"v{v}" for v in survivors) if survivors else "none"
    try:
        record_validation_warnings_sync(slug, run_id, "output_resolution", [{
            "subject": output_type,
            "code": "current_file_missing",
            "measure": None,
            "detail": (
                f"{output_type} is marked current at v{version}, but {file_path.name} is "
                f"not on disk. Nothing resolved it to an older version, because reading a "
                f"superseded artefact silently is worse than reading none. Still present: "
                f"{available}. Revert to one of those, or restore the file from a backup."
            ),
        }])
    except Exception:
        pass   # a resolver must not fail because bookkeeping did
```

`re`, `contextlib`, `sqlite3`, `get_project_id` and `record_validation_warnings_sync` are all already imported in this module - no new imports are needed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_current_output_path.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add agents/tools/_db.py tests/test_current_output_path.py
git commit -m "feat(outputs): resolve the current version from the ledger that records it"
```

---

## Task 3: Migrate the call sites

**Files:**
- Modify: `agents/tools/sqlite_state.py` (lines 59, 87, 122, 190, 307)
- Modify: `agents/tools/derive_registry.py` (line 26)
- Modify: `api/routers/projects.py` (line 494)
- Modify: `api/services/interview_answer_service.py` (line 122)
- Test: `tests/test_resolution_call_sites.py` *(new)*

**Interfaces:**
- Consumes: `current_output_path` (Task 2).

Eight calls. Every one already has `slug` and the output type in scope, so each is a direct substitution of `latest_output_path(dir / f"{type}.json")` for `current_output_path(slug, type)`.

**This is the "one layer away" task.** Task 2 proves the resolver; this proves the callers use it. A resolver nobody calls fixes nothing.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resolution_call_sites.py
"""The readers must use the resolver, not the glob.

Task 2 proves the resolver in isolation. This proves the code that actually feeds the
agents calls it - the distinction that made 'validate check_write' pass while the tool
calling it went untested.
"""
import json
import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings
from api.database import get_connection


@pytest_asyncio.fixture
async def shadowed(tmp_path, monkeypatch):
    """A project whose ledger says v2 while a v9 sits beside it on disk."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "callsite-test"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            pid = (await cur.fetchone())[0]

    async def publish(output_type, current_version, payload, shadow_version, shadow):
        (outputs / f"{output_type}_v{current_version}.json").write_text(json.dumps(payload))
        (outputs / f"{output_type}_v{shadow_version}.json").write_text(json.dumps(shadow))
        async with get_connection(slug) as conn:
            await conn.execute(
                "INSERT INTO agent_outputs"
                " (project_id, agent_name, output_type, file_path, version, is_current)"
                " VALUES (?,?,?,?,?,1)",
                (pid, "a", output_type,
                 str(outputs / f"{output_type}_v{current_version}.json"),
                 current_version))
            await conn.commit()

    yield slug, outputs, publish
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_registry_reader_uses_the_ledger(shadowed):
    slug, _, publish = shadowed
    await publish("value_chain_registry", 2,
                  {"activities": [{"id": "1", "label": "Current", "level": "L1"}]},
                  9, {"activities": [{"id": "1", "label": "Stale", "level": "L1"}]})
    from agents.tools.sqlite_state import _current_registry
    assert _current_registry(slug)["activities"][0]["label"] == "Current"


@pytest.mark.asyncio
async def test_the_levers_reader_uses_the_ledger(shadowed):
    slug, _, publish = shadowed
    await publish("value_levers", 2, [{"lever": "Current"}], 9, [{"lever": "Stale"}])
    from agents.tools.sqlite_state import _current_levers
    assert _current_levers(slug)[0]["lever"] == "Current"


@pytest.mark.asyncio
async def test_the_script_registry_reader_uses_the_ledger(shadowed):
    slug, _, publish = shadowed
    await publish("interview_script_registry", 2, {"scripts": [{"id": "SC-001"}]},
                  9, {"scripts": [{"id": "SC-999"}]})
    from agents.tools.sqlite_state import _current_script_registry
    assert _current_script_registry(slug)["scripts"][0]["id"] == "SC-001"


@pytest.mark.asyncio
async def test_merge_on_write_merges_into_the_ledgers_version(shadowed):
    """Merging into a shadowed version would resurrect superseded scripts."""
    slug, _, publish = shadowed
    await publish("interview_scripts", 2, {"SC-001": {"node_label": "current"}},
                  9, {"SC-999": {"node_label": "stale"}})
    from agents.tools.sqlite_state import _merge_with_current
    merged = _merge_with_current("interview_scripts", {"SC-002": {"node_label": "new"}}, slug)
    assert sorted(merged) == ["SC-001", "SC-002"], f"merged the shadow: {sorted(merged)}"


@pytest.mark.asyncio
async def test_the_tool_read_path_uses_the_ledger(shadowed):
    slug, _, publish = shadowed
    await publish("value_chain_tree", 2, [{"id": "0", "label": "Current"}],
                  9, [{"id": "0", "label": "Stale"}])
    from agents.tools.sqlite_state import SQLiteStateTool
    out = SQLiteStateTool(slug=slug, agent_name="value_chain_mapper")._run(
        operation="read", key="value_chain_tree", agent_name="value_chain_mapper")
    assert json.loads(out)[0]["label"] == "Current"


@pytest.mark.asyncio
async def test_the_derive_tool_reads_the_ledgers_registry(shadowed):
    slug, outputs, publish = shadowed
    await publish("value_chain_registry", 2,
                  {"activities": [{"id": "1", "label": "Current", "level": "L1"}]},
                  9, {"activities": [{"id": "1", "label": "Stale", "level": "L1"}]})
    from agents.tools.derive_registry import _latest_registry
    assert json.loads(_latest_registry(slug).read_text())["activities"][0]["label"] \
        == "Current"


@pytest.mark.asyncio
async def test_the_interview_scripts_endpoint_uses_the_ledger(shadowed, client):
    slug, _, publish = shadowed
    await publish("interview_scripts", 2,
                  {"SC-001": {"node_label": "Current", "level": "L0", "node_id": "0",
                              "sections": []}},
                  9, {"SC-999": {"node_label": "Stale", "level": "L0", "node_id": "0",
                                 "sections": []}})
    r = await client.get(f"/projects/{slug}/interview-scripts")
    assert sorted(r.json()) == ["SC-001"]


def test_no_reader_still_globs_the_disk():
    """A grep, because a call site added later is the way this regresses."""
    import re
    for f in ("agents/tools/sqlite_state.py", "agents/tools/derive_registry.py",
              "api/routers/projects.py", "api/services/interview_answer_service.py"):
        src = Path(f).read_text()
        calls = re.findall(r"latest_output_path\s*\(", src)
        assert not calls, f"{f} still calls latest_output_path {len(calls)} time(s)"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_resolution_call_sites.py -v`
Expected: FAIL - readers return the stale v9

- [ ] **Step 3: Migrate `sqlite_state.py`**

Replace each of the five, e.g. `_current_registry`:

```python
def _current_registry(slug: str) -> dict:
    """The registry in force, or an empty ledger when there is none yet."""
    path = current_output_path(slug, "value_chain_registry")
    if path is None:
        return {}
```

Same shape for `_current_script_registry` (`"interview_script_registry"`), `_current_levers` (`"value_levers"`), and `_merge_with_current` (`current_output_path(slug, key)`). For the read path at 307, `current_output_path(self.slug, key, run_id=self.run_id)` - it has a run to attribute a warning to.

Update the import and drop `latest_output_path` where it becomes unused.

- [ ] **Step 4: Migrate the other three**

`derive_registry.py` - `_latest_registry` takes an `outputs_dir` today; change it to take `slug` and update both callers in that file:

```python
def _latest_registry(slug: str) -> Path | None:
    """The registry the ledger marks current, or None on a first run."""
    return current_output_path(slug, "value_chain_registry")
```

`api/routers/projects.py:494` - `current = current_output_path(slug, "interview_scripts")`.

`api/services/interview_answer_service.py:122` - `path = current_output_path(slug, "interview_scripts")`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_resolution_call_sites.py -v`
Expected: 8 passed

- [ ] **Step 6: Run the whole suite twice**

Run: `./venv/bin/pytest -q --ignore=tests/integration && ./venv/bin/pytest -q --ignore=tests/integration`

Expected: identical, no new failures.

`_latest_registry` changes signature from `(outputs_dir: Path)` to `(slug: str)`, which breaks **three existing test call sites** - `tests/test_derive_registry.py:17` and `tests/test_label_stability.py` lines 140 and 162. Update the calls; do not weaken the assertions. Both files assert on the *content* of the resolved registry, which is exactly what should keep passing.

- [ ] **Step 7: Commit**

```bash
git add agents/tools/sqlite_state.py agents/tools/derive_registry.py api/routers/projects.py api/services/interview_answer_service.py tests/test_resolution_call_sites.py tests/test_derive_registry.py tests/test_label_stability.py
git commit -m "fix(outputs): every reader resolves through the ledger"
```

---

## Task 4: Verify on the live project, and retire the patch

**Files:**
- Delete (if dead): `scripts/repair_registry_current.py`

- [ ] **Step 1: Confirm no split families and no shadows remain**

```bash
./venv/bin/python -c "
import sqlite3, re
from pathlib import Path
from agents.tools._db import current_output_path
c = sqlite3.connect('data/sp-gs-am.db'); c.row_factory = sqlite3.Row
bad = []
for r in c.execute('SELECT output_type, version, file_path FROM agent_outputs WHERE is_current=1'):
    resolved = current_output_path('sp-gs-am', r['output_type'])
    if resolved is None:
        bad.append((r['output_type'], 'MISSING', Path(r['file_path']).name)); continue
    if resolved.name != Path(r['file_path']).name:
        bad.append((r['output_type'], Path(r['file_path']).name, resolved.name))
print('mismatches:', bad or 'none')
"
```

Expected: `none`. A `MISSING` entry is a genuine dangling row and should now appear as a `current_file_missing` warning - check it names the surviving versions.

- [ ] **Step 2: Confirm the legacy shadows are inert**

The three `legacy_value_chain_summary_v*.json` files renamed out of the family on 6 August should no longer matter either way. Re-resolve `value_chain_summary` and confirm it returns v5 whether or not those files are present.

- [ ] **Step 3: Retire the patch script**

`scripts/repair_registry_current.py` calls `latest_output_path` zero times and exists only to repair the symptom this plan removes. Read it; if it does nothing the resolver does not now do, delete it and its tests. If it does something else, leave it and note what.

- [ ] **Step 4: Commit**

```bash
git commit -am "chore: retire the registry-current repair script"
```

---

## Sequencing

Lands before the first Alex-to-Casey run anyone intends to trust, since every agent input in that chain resolves through the function it replaces. Independent of the A+B and E plans, and safe to build alongside either.
