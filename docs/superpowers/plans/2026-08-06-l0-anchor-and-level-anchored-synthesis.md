# L0 Anchor and Level-Anchored Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the value chain tree an organisation-level root and role nodes, and let Casey anchor themes at the level where the insight lives - with a validator that makes structural drift visible instead of silent.

**Architecture:** Two pure validators (tree structure, theme anchors) hang off the write paths that already exist. Neither refuses a write; both record into one new `validation_warnings` table. Warnings surface to a reviewer for disposition, and flow back into the agent's next run through the same injection point that already carries skill notes and change requests.

**Tech Stack:** Python 3.13, FastAPI, aiosqlite (raw SQL, no ORM), CrewAI, React 18 + TypeScript + Vite + Tailwind v3, pytest, Vitest.

## Global Constraints

- British English throughout, `-ise` / `-our` / `-re` / `-ogue` spellings, Oxford comma. En dash ` - ` with spaces in web content, never an em dash.
- No emoji in rendered web content; Lucide React icons only.
- No `sky-*` or `blue-*` Tailwind classes - use `brand` and `surface` tokens.
- Python 3.13 only. Use `./venv/bin/pytest` and `./venv/bin/python`, never system Python.
- **Run the backend suite twice before believing it is green.** `tests/conftest.py` points `DATABASE_DIR` at a fixed `/tmp/agentpool_test` that persists between runs. Tests needing isolation must use `monkeypatch.setenv("DATABASE_DIR", str(tmp_path))` with `get_settings.cache_clear()` on both sides.
- Tests must assert the property where it holds, not one layer away. For each test ask: *what calls this, and is that tested?*
- Schema changes go in **both** the `CREATE TABLE` statement and an `ALTER TABLE` migration, and into any test fixture that builds the table by hand.
- The `l3_skew` threshold is **0.70**, the minimum theme count is **5**, and the dismissal re-raise delta is **0.10**. Each lives in exactly one named constant.

---

## Three decisions this plan makes that the spec did not

The spec says the tree validator "runs in `SQLiteStateTool`'s write path for `value_chain_tree`, beside the existing `_VALIDATORS` entries". Reading that path shows *beside* has to mean a separate mechanism, not another entry:

1. **`_VALIDATORS` refuses; the spec requires warn-and-record.** `sqlite_state.py` returns `"Error: {key} was not written…"` whenever a validator returns a non-empty list. Registering the tree validator there would block the run and lose the work - exactly what the spec forbids.
2. **`_VALIDATORS` rejects anything that is not a `dict`, and `value_chain_tree` is a JSON list.** Verified against `projects/sp-gs-am/outputs/value_chain_tree_v12.json`. Registering the tree there would refuse *every* tree write with "value must be a JSON object, got list".

   → Both are solved by a parallel `_WARNERS` map that runs **after** a successful write and records instead of refusing. Task 3.

3. **The dismissal re-raise rule needs a persisted measure.** The spec's DDL has no column for one, but "re-raises if the L3 proportion changes by more than ten percentage points" cannot be implemented without storing the proportion. This plan adds a single `measure REAL` column. It is the minimum addition that makes a rule the spec states explicitly actually work.

A fourth, found while reading `DeriveRegistryTool`: its `_sort_key` does `[int(p) for p in id.split(".")]` and falls back to `[0]` on `ValueError`. Every role ID (`0.A`, `1.C`) hits that fallback, so they all collapse to the same sort key and land ahead of the root. Task 4 fixes it by reusing the one implementation the codebase already designated for this.

---

## File Structure

| File | Responsibility |
|---|---|
| `api/services/tree_validation.py` *(new)* | Pure tree structure checks. No I/O. |
| `api/services/anchor_validation.py` *(new)* | Pure theme anchor checks. No I/O. |
| `api/database.py` | `validation_warnings` DDL + migration + async fetch/disposition helpers. |
| `agents/tools/_db.py` | `record_validation_warnings_sync` - the sync recorder the tool path uses. |
| `agents/tools/sqlite_state.py` | `_WARNERS` map and its post-write hook. |
| `agents/tools/derive_registry.py` | Role-ID-safe ordering. |
| `agents/discovery/value_chain_mapper.py` | Alex emits root + role nodes. |
| `agents/discovery/synthesis_analyst.py` | Casey's `anchors` schema and level expectations. |
| `api/services/run_service.py` | `_fetch_validation_warnings` and its injection. |
| `api/routers/validations.py` *(new)* | List and dispose of warnings. |
| `api/services/pam_report_service.py` | Warning counts per crew. |
| `ui/src/components/ValidationWarnings.tsx` *(new)* | One warning list, used by both surfaces. |

Both validators are pure and live in `api/services/` so the tool path, the API, and the tests all import the same function. Neither imports `agents.*` - the dependency runs one way.

---

## Task 1: The `validation_warnings` table and its recorder

**Files:**
- Modify: `api/database.py` (new `_migrate_validation_warnings`, registered in the migration list near line 1141; new async helpers)
- Modify: `agents/tools/_db.py` (new `record_validation_warnings_sync`, alongside `record_blocked_write_sync` at line 137)
- Test: `tests/test_validation_warnings.py` *(new)*

**Interfaces:**
- Produces: `record_validation_warnings_sync(slug: str, run_id: int, source: str, warnings: list[dict]) -> None` where each warning is `{"subject": str|None, "code": str, "detail": str, "measure": float|None}`; `fetch_validation_warnings(conn, *, project_id: int, sources: list[str]|None = None, dispositions: list[str]|None = None) -> list[dict]`; `dispose_validation_warning(conn, *, warning_id: int, disposition: str, note: str, by: str) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validation_warnings.py
import sqlite3
import pytest
from api.database import get_connection, fetch_validation_warnings, dispose_validation_warning


@pytest.mark.asyncio
async def test_recording_the_same_warning_twice_keeps_one_row(warn_project):
    slug, project_id = warn_project
    from agents.tools._db import record_validation_warnings_sync

    w = [{"subject": "0", "code": "missing_l0", "detail": "no root node", "measure": None}]
    record_validation_warnings_sync(slug, 1, "value_chain_tree", w)
    record_validation_warnings_sync(slug, 2, "value_chain_tree", w)

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert len(rows) == 1, "re-running must not duplicate a warning"
    assert rows[0]["run_id"] == 2, "the row tracks the most recent occurrence"
    assert rows[0]["disposition"] == "open"


@pytest.mark.asyncio
async def test_disposition_survives_a_re_occurrence(warn_project):
    slug, project_id = warn_project
    from agents.tools._db import record_validation_warnings_sync

    w = [{"subject": "0", "code": "missing_l0", "detail": "no root", "measure": None}]
    record_validation_warnings_sync(slug, 1, "value_chain_tree", w)
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
        assert await dispose_validation_warning(
            conn, warning_id=rows[0]["id"], disposition="acknowledged",
            note="real gap", by="consultant",
        )
    record_validation_warnings_sync(slug, 2, "value_chain_tree", w)
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert rows[0]["disposition"] == "acknowledged", "a re-occurrence must not reset a disposition"
    assert rows[0]["disposition_note"] == "real gap"


@pytest.mark.asyncio
async def test_fetch_filters_by_source_and_disposition(warn_project):
    slug, project_id = warn_project
    from agents.tools._db import record_validation_warnings_sync

    record_validation_warnings_sync(
        slug, 1, "value_chain_tree",
        [{"subject": "0", "code": "missing_l0", "detail": "d", "measure": None}])
    record_validation_warnings_sync(
        slug, 1, "theme_anchor",
        [{"subject": "TH-01", "code": "anchor_level_mismatch", "detail": "d", "measure": None}])

    async with get_connection(slug) as conn:
        tree = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["value_chain_tree"])
        open_only = await fetch_validation_warnings(
            conn, project_id=project_id, dispositions=["open"])
    assert [r["code"] for r in tree] == ["missing_l0"]
    assert len(open_only) == 2
```

Add this fixture to the same file:

```python
@pytest.fixture
async def warn_project(tmp_path, monkeypatch):
    """An isolated project database, so no test can see another's warnings."""
    from api.config import get_settings
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "warn-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, name, sector) VALUES (?,?,?)",
            (slug, "Warn Test", "test"),
        )
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id
    get_settings.cache_clear()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_validation_warnings.py -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_validation_warnings'`

- [ ] **Step 3: Add the migration**

In `api/database.py`, beside `_migrate_blocked_writes` (line 729):

```python
async def _migrate_validation_warnings(conn: aiosqlite.Connection) -> None:
    """Structural findings a validator raised but did not refuse.

    Deliberately not blocked_writes. That table means "an agent reached for something it
    does not own"; this one means "what an agent wrote is structurally suspect". Overloading
    one with the other would blur a distinction the ownership work paid to establish.

    measure is not in the design's DDL. It is here because the dismissal rule - re-raise
    when the L3 proportion moves more than ten percentage points - cannot compare against a
    number nobody stored. Null for codes that have no measure.

    The unique index is what makes a warning idempotent: a re-run updates the occurrence
    rather than appending a duplicate, so a reviewer's disposition survives the next run.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS validation_warnings (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id       INTEGER NOT NULL REFERENCES projects(id),
            run_id           INTEGER,
            source           TEXT NOT NULL,
            subject          TEXT,
            code             TEXT NOT NULL,
            detail           TEXT NOT NULL,
            measure          REAL,
            disposition      TEXT NOT NULL DEFAULT 'open',
            disposition_note TEXT,
            disposed_by      TEXT,
            disposed_at      DATETIME,
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_validation_warnings_occurrence
        ON validation_warnings (project_id, source, IFNULL(subject, ''), code)
    """)
    await conn.commit()
```

Register it in the migration list (after `await _migrate_nonworking_ranges(conn)`, line 1141):

```python
        await _migrate_validation_warnings(conn)
```

- [ ] **Step 4: Add the async helpers**

Append to `api/database.py`:

```python
async def fetch_validation_warnings(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    sources: list[str] | None = None,
    dispositions: list[str] | None = None,
) -> list[dict]:
    """Warnings for a project, newest occurrence first."""
    where = ["project_id = ?"]
    params: list = [project_id]
    if sources:
        where.append(f"source IN ({','.join('?' * len(sources))})")
        params.extend(sources)
    if dispositions:
        where.append(f"disposition IN ({','.join('?' * len(dispositions))})")
        params.extend(dispositions)
    sql = (
        "SELECT * FROM validation_warnings WHERE "
        + " AND ".join(where)
        + " ORDER BY updated_at DESC, id DESC"
    )
    async with conn.execute(sql, params) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def dispose_validation_warning(
    conn: aiosqlite.Connection,
    *,
    warning_id: int,
    disposition: str,
    note: str,
    by: str,
) -> bool:
    """Record a reviewer's judgement. Returns False when the id does not exist."""
    cur = await conn.execute(
        "UPDATE validation_warnings SET disposition=?, disposition_note=?, disposed_by=?,"
        " disposed_at=CURRENT_TIMESTAMP WHERE id=?",
        (disposition, note, by, warning_id),
    )
    await conn.commit()
    return cur.rowcount > 0
```

- [ ] **Step 5: Add the sync recorder**

In `agents/tools/_db.py`, after `record_blocked_write_sync` (line 150):

```python
def record_validation_warnings_sync(
    slug: str, run_id: int, source: str, warnings: list[dict]
) -> None:
    """Best-effort, exactly as record_blocked_write_sync is best-effort.

    A validator that warns must never be able to fail the write it was inspecting - the
    whole point of warn-and-record over refuse is that the work survives. So this swallows
    nothing silently at the call site: the caller wraps it, and losing a warning is strictly
    better than losing the output.

    ON CONFLICT keeps one row per (project, source, subject, code) and refreshes the
    occurrence. disposition is deliberately absent from the SET list: a reviewer's judgement
    outlives the run that triggered it.
    """
    if not warnings:
        return
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        project_id = get_project_id(slug)
        for w in warnings:
            conn.execute(
                "INSERT INTO validation_warnings"
                " (project_id, run_id, source, subject, code, detail, measure)"
                " VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT (project_id, source, IFNULL(subject, ''), code) DO UPDATE SET"
                "   run_id=excluded.run_id, detail=excluded.detail,"
                "   measure=excluded.measure, updated_at=CURRENT_TIMESTAMP",
                (project_id, run_id or None, source, w.get("subject"),
                 w["code"], w["detail"], w.get("measure")),
            )
        conn.commit()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_validation_warnings.py -v`
Expected: 3 passed

- [ ] **Step 7: Run the full suite twice**

Run: `./venv/bin/pytest -q && ./venv/bin/pytest -q`
Expected: no *new* failures against the known baseline (10 pre-existing: 5 downstream-crew integration tests, 4 polluted `test_business_plan_crew.py` unit tests, and `test_sqlite_state_tool_round_trip`).

- [ ] **Step 8: Commit**

```bash
git add api/database.py agents/tools/_db.py tests/test_validation_warnings.py
git commit -m "feat(validation): a structural finding is recorded without refusing the write"
```

---

## Task 2: The tree structural validator

**Files:**
- Create: `api/services/tree_validation.py`
- Test: `tests/test_tree_validator.py` *(new)*

**Interfaces:**
- Consumes: nothing from earlier tasks - pure.
- Produces: `validate_tree_structure(tree: list, previous_registry: dict | None) -> list[dict]`, each warning `{"subject": str|None, "code": str, "detail": str, "measure": None}`. Codes: `missing_l0`, `missing_role_node`, `id_redefined`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tree_validator.py
from api.services.tree_validation import validate_tree_structure

GOOD_TREE = [
    {"id": "0", "label": "GS-UK", "level": "L0", "children": [
        {"id": "0.A", "label": "Audit", "level": "L0"},
        {"id": "0.S", "label": "Corporate Services frontline", "level": "L0"},
        {"id": "1", "label": "Property", "level": "L1", "children": [
            {"id": "1.C", "label": "Property customer", "level": "L1"},
            {"id": "1.F", "label": "Property frontline", "level": "L1"},
            {"id": "1.1", "label": "Strategic Planning", "level": "L2", "children": [
                {"id": "1.1.1", "label": "Asset Hierarchy", "level": "L3"},
            ]},
        ]},
    ]},
]

PREV = {"activities": [
    {"id": "0", "label": "GS-UK", "level": "L0", "active": True},
    {"id": "0.A", "label": "Audit", "level": "L0", "active": True},
    {"id": "0.S", "label": "Corporate Services frontline", "level": "L0", "active": True},
    {"id": "1", "label": "Property", "level": "L1", "active": True},
    {"id": "1.C", "label": "Property customer", "level": "L1", "active": True},
    {"id": "1.F", "label": "Property frontline", "level": "L1", "active": True},
    {"id": "1.1", "label": "Strategic Planning", "level": "L2", "active": True},
    {"id": "1.1.1", "label": "Asset Hierarchy", "level": "L3", "active": True},
]}


def _codes(warnings):
    return sorted(w["code"] for w in warnings)


def test_a_correct_tree_is_silent():
    assert validate_tree_structure(GOOD_TREE, PREV) == []


def test_a_rootless_tree_raises_missing_l0():
    rootless = GOOD_TREE[0]["children"][2:]   # the bare L1 list Alex actually produces
    warnings = validate_tree_structure(rootless, PREV)
    assert "missing_l0" in _codes(warnings)


def test_a_root_at_the_wrong_level_raises_missing_l0():
    wrong = [{"id": "0", "label": "GS-UK", "level": "L1", "children": []}]
    assert "missing_l0" in _codes(validate_tree_structure(wrong, None))


def test_an_l1_outside_the_root_raises_missing_l0():
    detached = list(GOOD_TREE) + [{"id": "9", "label": "Orphan", "level": "L1"}]
    warnings = validate_tree_structure(detached, PREV)
    assert "missing_l0" in _codes(warnings)
    assert any("9" in w["detail"] for w in warnings)


def test_a_dropped_role_node_raises_missing_role_node():
    import copy
    tree = copy.deepcopy(GOOD_TREE)
    prop = tree[0]["children"][2]
    prop["children"] = [c for c in prop["children"] if c["id"] != "1.F"]
    warnings = validate_tree_structure(tree, PREV)
    assert "missing_role_node" in _codes(warnings)
    assert any(w["subject"] == "1.F" for w in warnings)


def test_a_redefined_id_raises_id_redefined():
    import copy
    tree = copy.deepcopy(GOOD_TREE)
    tree[0]["children"][2]["label"] = "Something Else Entirely"
    warnings = validate_tree_structure(tree, PREV)
    assert "id_redefined" in _codes(warnings)
    assert any(w["subject"] == "1" for w in warnings)


def test_first_run_checks_only_the_root():
    """No previous registry means no baseline. Stated explicitly because a validator that
    passes silently when it has nothing to compare against looks identical to a broken one."""
    assert validate_tree_structure(GOOD_TREE, None) == []
    rootless = GOOD_TREE[0]["children"][2:]
    assert _codes(validate_tree_structure(rootless, None)) == ["missing_l0"]


def test_a_retired_node_is_not_a_redefinition():
    """The ledger may grow and may retire; only redefining is a finding."""
    import copy
    tree = copy.deepcopy(GOOD_TREE)
    prop = tree[0]["children"][2]
    prop["children"] = [c for c in prop["children"] if c["id"] != "1.1"]
    assert "id_redefined" not in _codes(validate_tree_structure(tree, PREV))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_tree_validator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.tree_validation'`

- [ ] **Step 3: Write the validator**

```python
# api/services/tree_validation.py
"""Structural checks on value_chain_tree, run when the tree is written.

Pure by design: tree and previous registry in, warnings out. No file reads, no database,
no settings. That is what lets the tool path, the API and the tests all exercise the same
function, and what makes the fixtures in tests/test_tree_validator.py sufficient evidence.

Every check warns. None refuses. A refusal would block the run and lose the work; a silent
pass would lose the signal. Recording makes the gap a finding.
"""
from __future__ import annotations

ROLE_SUFFIXES = ("A", "S", "C", "F")


def _walk(nodes: list, parent_id: str | None = None):
    """Yield (node, parent_id) depth-first. Tolerates a missing or non-list children key."""
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        yield node, parent_id
        yield from _walk(node.get("children") or [], str(node.get("id", "")))


def _is_role_id(node_id: str) -> bool:
    tail = str(node_id).rsplit(".", 1)[-1]
    return tail in ROLE_SUFFIXES


def validate_tree_structure(tree: list, previous_registry: dict | None) -> list[dict]:
    """Warnings about the new tree, judged against the previous registry.

    previous_registry is None on a first run. Only missing_l0 applies then - the root is
    required unconditionally, while the other two checks have no baseline to compare with
    and are skipped rather than guessed at.
    """
    warnings: list[dict] = []
    if not isinstance(tree, list):
        return [{
            "subject": None, "code": "missing_l0", "measure": None,
            "detail": f"the tree is a {type(tree).__name__}, not a list of root nodes",
        }]

    # ── missing_l0 ────────────────────────────────────────────────────────────────
    roots = [n for n in tree if isinstance(n, dict)]
    root = next((n for n in roots if str(n.get("id")) == "0"), None)
    if root is None:
        top_l1 = [str(n.get("id")) for n in roots if n.get("level") == "L1"]
        warnings.append({
            "subject": None, "code": "missing_l0", "measure": None,
            "detail": (
                "the tree has no root node with id '0'. The registry is derived from the "
                "tree, so nothing can anchor at organisation level. Top-level nodes found: "
                + (", ".join(top_l1) if top_l1 else "none")
            ),
        })
    elif root.get("level") != "L0":
        warnings.append({
            "subject": "0", "code": "missing_l0", "measure": None,
            "detail": f"the root node '0' has level {root.get('level')!r}, expected 'L0'",
        })
    else:
        detached = [
            str(n.get("id")) for n in roots
            if str(n.get("id")) != "0" and n.get("level") == "L1"
        ]
        if detached:
            warnings.append({
                "subject": None, "code": "missing_l0", "measure": None,
                "detail": (
                    "these L1 entities sit beside the root rather than under it, so they "
                    "do not descend from the L0: " + ", ".join(sorted(detached))
                ),
            })

    if previous_registry is None:
        return warnings

    prev = {
        str(a["id"]): a
        for a in (previous_registry.get("activities") or [])
        if isinstance(a, dict) and a.get("id") is not None
    }
    new_nodes = {str(n.get("id")): n for n, _ in _walk(tree) if n.get("id") is not None}

    # ── missing_role_node ─────────────────────────────────────────────────────────
    for node_id, entry in sorted(prev.items()):
        if not entry.get("active", True):
            continue
        if _is_role_id(node_id) and node_id not in new_nodes:
            warnings.append({
                "subject": node_id, "code": "missing_role_node", "measure": None,
                "detail": (
                    f"role node {node_id} ({entry.get('label', '')!r}) was in the previous "
                    f"registry and is absent from this tree. Role nodes are what give the "
                    f"outside-in and bottom-up view; dropping one silently removes a "
                    f"stakeholder category from assignment and from synthesis."
                ),
            })

    # ── id_redefined ──────────────────────────────────────────────────────────────
    for node_id, node in sorted(new_nodes.items()):
        entry = prev.get(node_id)
        if entry is None or not entry.get("active", True):
            continue
        old_label = str(entry.get("label", "")).strip()
        new_label = str(node.get("label", "")).strip()
        if old_label and new_label and old_label != new_label:
            warnings.append({
                "subject": node_id, "code": "id_redefined", "measure": None,
                "detail": (
                    f"id {node_id} meant {old_label!r} and now means {new_label!r}. "
                    f"The ledger may grow and may retire, but may not redefine - "
                    f"Architecture's capability model is built against these ids."
                ),
            })
    return warnings
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_tree_validator.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add api/services/tree_validation.py tests/test_tree_validator.py
git commit -m "feat(validation): tree structure checks for the root, role nodes and id succession"
```

---

## Task 3: Wire the tree warner into the write path

**Files:**
- Modify: `agents/tools/sqlite_state.py` (add `_WARNERS` beside `_VALIDATORS` at line 159; hook after the write succeeds)
- Test: `tests/test_sqlite_state_warnings.py` *(new)*

**Interfaces:**
- Consumes: `validate_tree_structure` (Task 2), `record_validation_warnings_sync` (Task 1).
- Produces: `_WARNERS: dict[str, Callable[[object, str], list[dict]]]` and `_WARNER_SOURCE: dict[str, str]`.

**This is the task the "one layer away" rule is aimed at.** Task 2 proves the validator; this proves the *tool that calls it* records what it returns and still writes the file.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sqlite_state_warnings.py
import json
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, fetch_validation_warnings


@pytest.fixture
async def tool_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "warner-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, name, sector) VALUES (?,?,?)",
            (slug, "Warner Test", "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id
    get_settings.cache_clear()


ROOTLESS = [{"id": "1", "label": "Property", "level": "L1", "children": []}]
ROOTED = [{"id": "0", "label": "GS-UK", "level": "L0", "children": [
    {"id": "1", "label": "Property", "level": "L1", "children": []}]}]


@pytest.mark.asyncio
async def test_a_rootless_tree_is_written_and_warned_about(tool_project):
    """Warn and record, never refuse - the work must survive the finding."""
    slug, project_id = tool_project
    from agents.tools.sqlite_state import SQLiteStateTool

    tool = SQLiteStateTool(slug=slug, agent_name="value_chain_mapper", run_id=7)
    result = tool._run(operation="write", key="value_chain_tree",
                       agent_name="value_chain_mapper", value=json.dumps(ROOTLESS))

    assert not result.startswith("Error"), result
    assert "value_chain_tree" in result

    read_back = tool._run(operation="read", key="value_chain_tree",
                          agent_name="value_chain_mapper")
    assert json.loads(read_back) == ROOTLESS, "the write must land despite the warning"

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert [r["code"] for r in rows] == ["missing_l0"]
    assert rows[0]["source"] == "value_chain_tree"
    assert rows[0]["run_id"] == 7


@pytest.mark.asyncio
async def test_a_rooted_tree_records_nothing(tool_project):
    slug, project_id = tool_project
    from agents.tools.sqlite_state import SQLiteStateTool

    tool = SQLiteStateTool(slug=slug, agent_name="value_chain_mapper", run_id=7)
    tool._run(operation="write", key="value_chain_tree",
              agent_name="value_chain_mapper", value=json.dumps(ROOTED))

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert rows == []


@pytest.mark.asyncio
async def test_a_recorder_failure_cannot_lose_the_write(tool_project, monkeypatch):
    """Bookkeeping must never turn a successful write into a failed one."""
    slug, _ = tool_project
    import agents.tools.sqlite_state as st

    def boom(*a, **k):
        raise RuntimeError("database is on fire")
    monkeypatch.setattr(st, "record_validation_warnings_sync", boom)

    tool = st.SQLiteStateTool(slug=slug, agent_name="value_chain_mapper", run_id=7)
    result = tool._run(operation="write", key="value_chain_tree",
                       agent_name="value_chain_mapper", value=json.dumps(ROOTLESS))
    assert not result.startswith("Error"), result
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_sqlite_state_warnings.py -v`
Expected: FAIL - `test_a_rootless_tree_is_written_and_warned_about` asserts `["missing_l0"]` but gets `[]`

- [ ] **Step 3: Add the `_WARNERS` map**

In `agents/tools/sqlite_state.py`, immediately after the `_VALIDATORS` dict (line 159):

```python
def _warn_value_chain_tree(parsed: object, slug: str) -> list[dict]:
    from api.services.tree_validation import validate_tree_structure
    from agents.tools.derive_registry import _latest_registry

    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / slug / "outputs"
    previous = _latest_registry(outputs_dir)
    prev_registry = None
    if previous is not None:
        try:
            prev_registry = json.loads(previous.read_text())
        except Exception:
            prev_registry = None   # a corrupt registry is no baseline, not a false baseline
    return validate_tree_structure(parsed, prev_registry)


# Warners differ from validators in two ways that matter, and both are why they are a
# separate map rather than another _VALIDATORS entry:
#
#   1. A validator REFUSES - the write never lands. A warner records and lets the write
#      through, because blocking the run would lose the work the run just did.
#   2. _VALIDATORS rejects any payload that is not a dict. value_chain_tree is a JSON
#      *list*, so registering it there would refuse every tree write ever made.
#
# They run after the write succeeds, so a recorded warning always refers to an output that
# actually exists.
_WARNERS: dict[str, Callable[[object, str], list[dict]]] = {
    "value_chain_tree": _warn_value_chain_tree,
}

# The `source` recorded against each warning, so a reviewer can tell a tree finding from a
# theme one without parsing the code.
_WARNER_SOURCE: dict[str, str] = {
    "value_chain_tree": "value_chain_tree",
}
```

Add the import at the top of the file, to the existing `from agents.tools._db import (...)` block:

```python
    record_validation_warnings_sync,
```

- [ ] **Step 4: Hook it into the write path**

In `_run`, immediately after the `insert_agent_output_sync` block succeeds and before the method returns its success string, insert:

```python
            warner = _WARNERS.get(key)
            if warner is not None:
                try:
                    found = warner(parsed, self.slug)
                    if found:
                        record_validation_warnings_sync(
                            self.slug, self.run_id, _WARNER_SOURCE[key], found
                        )
                except Exception:
                    pass  # a warning is never worth failing a completed write over
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_sqlite_state_warnings.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add agents/tools/sqlite_state.py tests/test_sqlite_state_warnings.py
git commit -m "feat(validation): the tool that writes the tree records what the validator found"
```

---

## Task 4: DeriveRegistryTool - role-node ordering and the L0 regression

**Files:**
- Modify: `agents/tools/derive_registry.py` (`_sort_key`, around line 108)
- Test: `tests/test_derive_registry_l0.py` *(new)*

**Interfaces:**
- Consumes: `api.services.value_chain_model.id_order(activity_id: str) -> tuple[int, ...]` (existing, line 27). It maps a non-numeric part to `_UNORDERABLE = 10**9`, so a role node sorts **after** its numbered siblings under the same parent: `1` < `1.1` < `1.1.1` < `1.2` < `1.C` < `1.F`. That is the spec's "role nodes simply do not interleave with their numbered siblings".
- Produces: no new interface - behaviour change only.

**The spec says `DeriveRegistryTool` needs no change. That is true of its recursion, which already handles arbitrary depth and `parent_id`. It is not true of its sorting:** `_sort_key` does `[int(p) for p in id.split(".")]` with `except ValueError: return [0]`, so `0.A`, `0.S`, `1.C` and `1.F` all collapse to the same key and sort ahead of the root.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_derive_registry_l0.py
import json
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection

TREE = [{"id": "0", "label": "GS-UK", "level": "L0", "children": [
    {"id": "0.A", "label": "Audit", "level": "L0"},
    {"id": "0.S", "label": "Corporate Services frontline", "level": "L0"},
    {"id": "1", "label": "Property", "level": "L1", "children": [
        {"id": "1.C", "label": "Property customer", "level": "L1"},
        {"id": "1.F", "label": "Property frontline", "level": "L1"},
        {"id": "1.1", "label": "Strategic Planning", "level": "L2", "children": [
            {"id": "1.1.1", "label": "Asset Hierarchy", "level": "L3"},
        ]},
        {"id": "1.2", "label": "Portfolio Optimisation", "level": "L2"},
    ]},
    {"id": "2", "label": "Fleet", "level": "L1", "children": [
        {"id": "2.F", "label": "Fleet frontline", "level": "L1"},
    ]},
]}]


@pytest.fixture
async def registry_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "registry-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, name, sector) VALUES (?,?,?)",
            (slug, "Registry Test", "test"))
        await conn.commit()
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "value_chain_tree.json").write_text(json.dumps(TREE))
    yield slug, outputs
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_root_and_role_nodes_reach_the_registry(registry_project):
    """The regression that started all of this: a node reaches the registry only if it is
    in the tree, and no registry written by value_chain_mapper has ever held an L0."""
    slug, outputs = registry_project
    from agents.tools.derive_registry import DeriveRegistryTool, _latest_registry

    result = DeriveRegistryTool(slug=slug)._run(agent_name="value_chain_mapper")
    assert not result.startswith("Error"), result

    registry = json.loads(_latest_registry(outputs).read_text())
    by_id = {a["id"]: a for a in registry["activities"]}

    assert by_id["0"]["level"] == "L0"
    assert "parent_id" not in by_id["0"], "the root has no parent"
    for role_id, parent in [("0.A", "0"), ("0.S", "0"), ("1.C", "1"),
                            ("1.F", "1"), ("2.F", "2")]:
        assert role_id in by_id, f"{role_id} missing from the registry"
        assert by_id[role_id]["parent_id"] == parent
    assert by_id["1"]["parent_id"] == "0", "every L1 descends from the L0"
    assert by_id["1.1.1"]["parent_id"] == "1.1"


@pytest.mark.asyncio
async def test_role_ids_sort_after_their_numbered_siblings(registry_project):
    """The root sorts first, and each role node trails its parent's numbered children
    rather than jumping ahead of them - id_order maps a non-numeric part to 10**9."""
    slug, outputs = registry_project
    from agents.tools.derive_registry import DeriveRegistryTool, _latest_registry

    DeriveRegistryTool(slug=slug)._run(agent_name="value_chain_mapper")
    ids = [a["id"] for a in json.loads(_latest_registry(outputs).read_text())["activities"]]

    assert ids[0] == "0", f"the root must sort first, got {ids[:4]}"
    assert ids.index("0.A") < ids.index("1"), "0.A belongs to the root's block"
    assert ids.index("1") < ids.index("1.1") < ids.index("1.1.1") < ids.index("1.2")
    assert ids.index("1.2") < ids.index("1.C") < ids.index("1.F"), \
        "role nodes trail the numbered siblings, not interleave with them"
    assert ids.index("1.F") < ids.index("2")
    assert ids.index("2") < ids.index("2.F")


@pytest.mark.asyncio
async def test_the_tool_does_not_synthesise_a_missing_root(registry_project):
    """The spec is explicit that DeriveRegistryTool must NOT invent a root it cannot also
    put in the tree. value_chain_tree is Alex's key, so the repair write would be refused
    by the ownership boundary - synthesising here would leave the registry holding an
    anchor the tree and the value chain UI cannot display."""
    slug, outputs = registry_project
    from agents.tools.derive_registry import DeriveRegistryTool, _latest_registry

    rootless = TREE[0]["children"][2:]          # the bare L1 list, no root
    (outputs / "value_chain_tree.json").write_text(json.dumps(rootless))
    DeriveRegistryTool(slug=slug)._run(agent_name="value_chain_mapper")

    ids = {a["id"] for a in json.loads(_latest_registry(outputs).read_text())["activities"]}
    assert "0" not in ids, "the registry must not invent a root the tree does not have"
    assert "1" in ids and "2" in ids
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_derive_registry_l0.py -v`
Expected: `test_role_ids_sort_beside_their_numbered_siblings` FAILS - the root does not sort first, because `0`, `0.A`, `0.S`, `1.C`, `1.F` and `2.F` all key to `[0]`

- [ ] **Step 3: Reuse the one ordering implementation**

In `agents/tools/derive_registry.py`, replace the local `_sort_key` (line ~108) and its use:

```python
        # Sort by the ID's numeric parts, sharing value_chain_model's implementation so the
        # registry, the collision messages and the migration never disagree about what
        # "1.10" means relative to "1.9". The local version raised ValueError on any
        # non-numeric part and fell back to [0], which put every role node (0.A, 1.C, 2.F)
        # ahead of the root and in arbitrary order relative to each other. id_order maps a
        # non-numeric part to 10**9 instead, so a role node trails its numbered siblings.
        from api.services.value_chain_model import id_order

        new_activities.sort(key=lambda a: id_order(a["id"]))
```

Delete the `def _sort_key(a: dict) -> list[int]:` block it replaces.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_derive_registry_l0.py -v`
Expected: 2 passed

- [ ] **Step 5: Run the existing registry tests for regressions**

Run: `./venv/bin/pytest tests/ -q -k "registry"`
Expected: no new failures

- [ ] **Step 6: Commit**

```bash
git add agents/tools/derive_registry.py tests/test_derive_registry_l0.py
git commit -m "fix(registry): role ids sort beside their siblings instead of ahead of the root"
```

---

## Task 5: Alex emits the root and the role nodes

**Files:**
- Modify: `agents/discovery/value_chain_mapper.py` (step 8, lines 176-196)
- Test: `tests/test_value_chain_mapper_prompt.py` *(new)*

**Interfaces:** none - prompt text only.

The root instruction has been in this prompt since 4 August and has been ignored on every run since (`value_chain_tree` v10 and v12 both have a bare L1 list). The prompt change here is necessary but **is not the mechanism** - Tasks 2 and 3 are, because they make the omission visible whether or not the prompt is followed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_value_chain_mapper_prompt.py
# The task factory is create_value_chain_mapper_task(...), which needs a live Agent to
# build. These assertions read the module source instead - the prompt text is the artefact
# under test, and reading it directly avoids constructing an LLM to inspect a string.


def test_the_prompt_names_the_role_node_scheme():
    """Alex cannot emit nodes nobody described to him."""
    import inspect
    from agents.discovery import value_chain_mapper
    source = inspect.getsource(value_chain_mapper)
    for token in ('"0.A"', '"0.S"', '<L1>.C', '<L1>.F'):
        assert token in source, f"the prompt never mentions {token}"
    assert "role node" in source.lower()


def test_the_prompt_still_requires_the_root():
    import inspect
    from agents.discovery import value_chain_mapper
    source = inspect.getsource(value_chain_mapper)
    assert 'single root' in source
    assert 'id "0"' in source
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_value_chain_mapper_prompt.py -v`
Expected: FAIL - `the prompt never mentions "0.A"`

- [ ] **Step 3: Extend step 8 of the prompt**

In `agents/discovery/value_chain_mapper.py`, after the existing sentence ending `"...nothing can anchor to it. "` and before `"EVERY L1, L2 and L3 node MUST include an 'id' field"`, insert:

```python
            "The root also carries two organisation-level ROLE NODES as direct children: "
            "id \"0.A\" level \"L0\" for Audit, and id \"0.S\" level \"L0\" for Corporate "
            "Services frontline. Each L1 entity carries the role nodes it warrants: "
            "id \"<L1>.C\" level \"L1\" for that entity's customer, and \"<L1>.F\" level "
            "\"L1\" for that entity's frontline - so \"1.C\", \"1.F\", \"2.C\", \"2.F\". "
            "Role nodes are ordinary activities: Jordan assigns stakeholders to them, Maya "
            "writes interview scripts for them, and Casey anchors themes to them. They give "
            "the outside-in and bottom-up view - C is what the organisation looks like from "
            "outside, F what it feels like from underneath. Audit and Corporate Services sit "
            "at L0 because they are organisation-level; customer and frontline sit at L1 "
            "because a Fleet customer and a Property customer need different interviews. "
            "Whether a given L1 warrants C or F is your judgement for this client - Support "
            "Services may warrant neither, since 0.S already covers corporate services "
            "frontline. Do NOT put role nuance on the node: that belongs on the stakeholder "
            "record, so one F programme serves both 1.F and 2.F while the answers differ.\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_value_chain_mapper_prompt.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add agents/discovery/value_chain_mapper.py tests/test_value_chain_mapper_prompt.py
git commit -m "feat(discovery): Alex is told to emit the L0 root's role nodes, not just the root"
```

---

## Task 6: Casey's theme schema - `activity_ids` becomes `anchors`

**Files:**
- Modify: `agents/discovery/synthesis_analyst.py` (theme schema line 64, strategic requirement schema line 85)
- Test: `tests/test_synthesis_analyst_prompt.py` *(new)*

**Interfaces:**
- Produces: the `themes` payload shape `{"id", "kind", "theme", "description", "anchors": [str], "evidence": [...]}` that Task 7's validator consumes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_synthesis_analyst_prompt.py
import inspect
from agents.discovery import synthesis_analyst


def _src():
    return inspect.getsource(synthesis_analyst)


def test_themes_carry_anchors_not_activity_ids():
    src = _src()
    assert '"anchors"' in src
    assert '\\"activity_ids\\"' not in src, "activity_ids is what confined every theme to L3"


def test_the_prompt_states_the_level_expectation():
    src = _src()
    for token in ("L0", "L1", "L2", "L3", "governance", "maturity", "tactical"):
        assert token in src, f"the level expectation never mentions {token}"


def test_the_prompt_says_anchors_may_be_any_registry_node():
    assert "any registry node" in _src()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_synthesis_analyst_prompt.py -v`
Expected: FAIL - `assert '"anchors"' in src`

- [ ] **Step 3: Replace the theme schema and add the level expectation**

In `agents/discovery/synthesis_analyst.py`, replace the theme schema line (line 64):

```python
            "   {\"id\": \"TH-01\", \"theme\": \"...\", \"kind\": \"horizontal|vertical\", "
            "\"description\": \"...\", \"anchors\": [\"0\", \"1.F\", \"2.4\"], "
            "\"evidence\": [{\"answer_id\": 812, \"stakeholder_id\": 1, \"quote\": \"...\"}]}\n"
            "   An anchor may be ANY registry node - the L0 organisation, an L0 role node, an "
            "L1 entity, an L1 role node, an L2 stage or an L3 activity. Anchor each theme at "
            "the level where the insight actually lives:\n"
            "     L0 (0, 0.A, 0.S) - governance, assurance, and vertical/maturity themes;\n"
            "     L1 (1, 1.C, 1.F) - functional: executive-level customer view, frontline "
            "sentiment, data and process governance, maturity rankings across vertical "
            "themes;\n"
            "     L2 (n.n) - decision: the bulk of effectiveness-related, data-enabled "
            "decision and maturity change;\n"
            "     L3 (n.n.n) - tactical and efficiency, with some effectiveness.\n"
            "   Anchoring everything at n.n.n loses resolution and systematically skews the "
            "value propositions built from your themes toward L3 efficiency. A governance "
            "theme anchored to an arbitrary L3 child is a governance theme nobody can act "
            "on at governance level.\n"
```

Replace the strategic requirement schema line (line 85) so it uses the same vocabulary:

```python
            "   {\"id\": \"SR-01\", \"statement\": \"...\", \"kind\": \"challenge|opportunity\", "
            "\"from_themes\": [\"TH-01\", ...], \"anchors\": [\"0\", \"1.2\"], "
            "\"priority\": \"High|Medium|Low\"}\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_synthesis_analyst_prompt.py -v`
Expected: 3 passed

- [ ] **Step 5: Check for readers of the old key**

Run: `./venv/bin/python -c "
import subprocess
print(subprocess.run(['grep','-rn','activity_ids','api/','ui/src/','agents/'],capture_output=True,text=True).stdout)"`

Every hit outside `value_lever_analyst.py` (which uses `related_activity_ids`, a different key) and `value_chain_model.py` (a local variable) must be updated to read `anchors`. If a UI reader exists, add it to Task 11's files.

- [ ] **Step 6: Commit**

```bash
git add agents/discovery/synthesis_analyst.py tests/test_synthesis_analyst_prompt.py
git commit -m "feat(synthesis): a theme anchors at the level its insight lives, not only at L3"
```

---

## Task 7: The anchor validator

**Files:**
- Create: `api/services/anchor_validation.py`
- Test: `tests/test_anchor_validator.py` *(new)*

**Interfaces:**
- Produces: `validate_theme_anchors(themes: list, registry: dict) -> list[dict]`; constants `L3_SKEW_THRESHOLD = 0.70`, `L3_SKEW_MIN_THEMES = 5`, `SKEW_RERAISE_DELTA = 0.10`. Codes: `anchor_level_mismatch`, `l3_skew`, `unknown_anchor`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_anchor_validator.py
from api.services.anchor_validation import (
    validate_theme_anchors, L3_SKEW_THRESHOLD, L3_SKEW_MIN_THEMES,
)

REGISTRY = {"activities": (
    [{"id": "0", "level": "L0", "active": True},
     {"id": "0.A", "level": "L0", "active": True},
     {"id": "1", "level": "L1", "active": True},
     {"id": "1.F", "level": "L1", "active": True}]
    + [{"id": f"1.{n}", "level": "L2", "active": True} for n in range(1, 6)]
    + [{"id": f"1.{n}.1", "level": "L3", "active": True} for n in range(1, 6)]
)}


def _codes(ws):
    return sorted(w["code"] for w in ws)


def _theme(tid, kind, anchors, name="t"):
    return {"id": tid, "kind": kind, "theme": name, "description": "d", "anchors": anchors}


def test_a_vertical_theme_below_l1_is_a_mismatch():
    ws = validate_theme_anchors([_theme("TH-01", "vertical", ["1.1.1"])], REGISTRY)
    assert "anchor_level_mismatch" in _codes(ws)
    assert ws[0]["subject"] == "TH-01"


def test_a_vertical_theme_at_l0_is_fine():
    assert validate_theme_anchors([_theme("TH-01", "vertical", ["0"])], REGISTRY) == []


def test_a_governance_theme_at_l3_is_a_mismatch():
    ws = validate_theme_anchors(
        [_theme("TH-01", "horizontal", ["1.2.1"], name="Data governance and assurance")],
        REGISTRY)
    assert "anchor_level_mismatch" in _codes(ws)


def test_the_distribution_check_fires_where_per_item_checks_cannot():
    """Eight of ten themes anchor only at L3 and every one is individually defensible.
    No per-theme rule can see this; only the population can."""
    themes = [_theme(f"TH-{i:02d}", "horizontal", [f"1.{(i % 5) + 1}.1"]) for i in range(8)]
    themes += [_theme("TH-09", "horizontal", ["1.2"]), _theme("TH-10", "vertical", ["0"])]
    ws = validate_theme_anchors(themes, REGISTRY)
    assert _codes(ws) == ["l3_skew"], "no individual theme should be flagged"
    skew = ws[0]
    assert skew["measure"] == 0.8
    assert skew["subject"] is None


def test_the_minimum_count_guard_suppresses_skew():
    """Four all-L3 themes are a small tactical engagement, not a skew."""
    themes = [_theme(f"TH-{i:02d}", "horizontal", [f"1.{i + 1}.1"]) for i in range(4)]
    assert len(themes) < L3_SKEW_MIN_THEMES
    assert "l3_skew" not in _codes(validate_theme_anchors(themes, REGISTRY))


def test_a_balanced_set_is_silent():
    themes = [
        _theme("TH-01", "vertical", ["0"]),
        _theme("TH-02", "horizontal", ["1"]),
        _theme("TH-03", "horizontal", ["1.2"]),
        _theme("TH-04", "horizontal", ["1.3.1"]),
        _theme("TH-05", "horizontal", ["1.F"]),
    ]
    assert validate_theme_anchors(themes, REGISTRY) == []


def test_a_theme_anchored_to_a_node_that_does_not_exist():
    ws = validate_theme_anchors([_theme("TH-01", "horizontal", ["9.9.9"])], REGISTRY)
    assert "unknown_anchor" in _codes(ws)


def test_a_theme_anchored_at_both_l3_and_above_does_not_count_as_l3_only():
    themes = [_theme(f"TH-{i:02d}", "horizontal", [f"1.{i + 1}.1", "1"]) for i in range(6)]
    assert "l3_skew" not in _codes(validate_theme_anchors(themes, REGISTRY))


def test_the_threshold_is_a_single_named_constant():
    assert L3_SKEW_THRESHOLD == 0.70
    assert L3_SKEW_MIN_THEMES == 5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_anchor_validator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.anchor_validation'`

- [ ] **Step 3: Write the validator**

```python
# api/services/anchor_validation.py
"""Checks on where Casey's themes anchor. Pure: themes and registry in, warnings out.

Two kinds of finding, and the second is the one that matters. A per-theme mismatch is an
individual mistake. A distribution skew is the signature of the bias this whole design
exists to remove - and when it happens, no individual theme looks wrong. Every L3 anchor
can be perfectly defensible while the set is badly skewed. Per-item validation cannot catch
an emergent property; only looking at the population can.
"""
from __future__ import annotations

# Starting values, not derived ones. Stated in one place each so the implementation does not
# invent its own and so they can be tuned once evidence exists.
L3_SKEW_THRESHOLD = 0.70
L3_SKEW_MIN_THEMES = 5
SKEW_RERAISE_DELTA = 0.10

# A theme naming any of these is about how the organisation governs itself, which is an L0
# or L1 conversation whatever activity prompted it.
_GOVERNANCE_TERMS = ("governance", "assurance", "compliance", "accountability", "oversight")


def _levels(registry: dict) -> dict[str, str]:
    return {
        str(a["id"]): str(a.get("level", ""))
        for a in (registry.get("activities") or [])
        if isinstance(a, dict) and a.get("id") is not None
    }


def _is_governance(theme: dict) -> bool:
    text = f"{theme.get('theme', '')} {theme.get('description', '')}".casefold()
    return any(term in text for term in _GOVERNANCE_TERMS)


def validate_theme_anchors(themes: list, registry: dict) -> list[dict]:
    levels = _levels(registry)
    warnings: list[dict] = []
    l3_only = 0
    counted = 0

    for theme in themes or []:
        if not isinstance(theme, dict):
            continue
        counted += 1
        tid = str(theme.get("id", ""))
        anchors = [str(a) for a in (theme.get("anchors") or [])]

        unknown = [a for a in anchors if a not in levels]
        if unknown:
            warnings.append({
                "subject": tid, "code": "unknown_anchor", "measure": None,
                "detail": (
                    f"theme {tid} anchors to {', '.join(sorted(unknown))}, which "
                    f"{'are' if len(unknown) > 1 else 'is'} not in the registry. An anchor "
                    f"that resolves to nothing cannot carry the theme downstream."
                ),
            })

        known = [levels[a] for a in anchors if a in levels]
        if known and all(lvl == "L3" for lvl in known):
            l3_only += 1

        if theme.get("kind") == "vertical" and known and all(
            lvl not in ("L0", "L1") for lvl in known
        ):
            warnings.append({
                "subject": tid, "code": "anchor_level_mismatch", "measure": None,
                "detail": (
                    f"theme {tid} is vertical - about maturity within a discipline - but "
                    f"anchors only at {', '.join(sorted(set(known)))}. Maturity is judged "
                    f"at L0 or L1; anchored lower it cannot be ranked across the chain."
                ),
            })
        elif _is_governance(theme) and known and all(lvl == "L3" for lvl in known):
            warnings.append({
                "subject": tid, "code": "anchor_level_mismatch", "measure": None,
                "detail": (
                    f"theme {tid} is about governance or assurance but anchors only at L3. "
                    f"A governance theme hung on a single activity is one nobody can act on "
                    f"at governance level."
                ),
            })

    if counted >= L3_SKEW_MIN_THEMES:
        proportion = l3_only / counted
        if proportion > L3_SKEW_THRESHOLD:
            warnings.append({
                "subject": None, "code": "l3_skew", "measure": round(proportion, 4),
                "detail": (
                    f"{l3_only} of {counted} themes ({proportion:.0%}) anchor exclusively at "
                    f"L3. Individually each may be sound; as a set this skews the value "
                    f"propositions built from them toward L3 efficiency, losing the "
                    f"governance, functional and decision altitudes entirely."
                ),
            })
    return warnings
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_anchor_validator.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add api/services/anchor_validation.py tests/test_anchor_validator.py
git commit -m "feat(validation): theme anchor checks, including the distribution skew"
```

---

## Task 8: Wire the anchor warner into the themes write path

**Files:**
- Modify: `agents/tools/sqlite_state.py` (extend `_WARNERS` and `_WARNER_SOURCE` from Task 3)
- Test: `tests/test_sqlite_state_warnings.py` (extend)

**Interfaces:**
- Consumes: `validate_theme_anchors` (Task 7), the `_WARNERS` hook (Task 3).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sqlite_state_warnings.py`:

```python
SKEWED_THEMES = [
    {"id": f"TH-{i:02d}", "kind": "horizontal", "theme": "t", "description": "d",
     "anchors": ["1.1.1"]}
    for i in range(6)
]


@pytest.mark.asyncio
async def test_skewed_themes_are_written_and_warned_about(tool_project):
    slug, project_id = tool_project
    from agents.tools.sqlite_state import SQLiteStateTool

    outputs = Path(get_settings().projects_dir) / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "value_chain_registry.json").write_text(json.dumps({"activities": [
        {"id": "1", "level": "L1", "active": True},
        {"id": "1.1", "level": "L2", "active": True},
        {"id": "1.1.1", "level": "L3", "active": True},
    ]}))

    tool = SQLiteStateTool(slug=slug, agent_name="synthesis_analyst", run_id=11)
    result = tool._run(operation="write", key="themes",
                       agent_name="synthesis_analyst", value=json.dumps(SKEWED_THEMES))
    assert not result.startswith("Error"), result

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=project_id, sources=["theme_anchor"])
    assert [r["code"] for r in rows] == ["l3_skew"]
    assert rows[0]["measure"] == 1.0
    assert rows[0]["subject"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_sqlite_state_warnings.py::test_skewed_themes_are_written_and_warned_about -v`
Expected: FAIL - `assert [] == ["l3_skew"]`

- [ ] **Step 3: Add the themes warner**

In `agents/tools/sqlite_state.py`, beside `_warn_value_chain_tree`:

```python
def _warn_themes(parsed: object, slug: str) -> list[dict]:
    from api.services.anchor_validation import validate_theme_anchors
    from agents.tools.derive_registry import _latest_registry

    if not isinstance(parsed, list):
        return []   # shape is the schema's problem, not the anchor validator's
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / slug / "outputs"
    registry_path = _latest_registry(outputs_dir)
    if registry_path is None:
        return []   # no registry means no levels to judge anchors against
    try:
        registry = json.loads(registry_path.read_text())
    except Exception:
        return []
    return validate_theme_anchors(parsed, registry)
```

Extend both maps:

```python
_WARNERS: dict[str, Callable[[object, str], list[dict]]] = {
    "value_chain_tree": _warn_value_chain_tree,
    "themes": _warn_themes,
}

_WARNER_SOURCE: dict[str, str] = {
    "value_chain_tree": "value_chain_tree",
    "themes": "theme_anchor",
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_sqlite_state_warnings.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add agents/tools/sqlite_state.py tests/test_sqlite_state_warnings.py
git commit -m "feat(validation): Casey's themes are checked for anchor level and skew on write"
```

---

## Task 9: The machine loop - warnings reach the agent's next run

**Files:**
- Modify: `api/services/run_service.py` (new `_fetch_validation_warnings`, injected beside `_fetch_change_requests` at line 445)
- Test: `tests/test_validation_warning_injection.py` *(new)*

**Interfaces:**
- Consumes: `fetch_validation_warnings` (Task 1).
- Produces: `_fetch_validation_warnings(slug: str, crew_name: str) -> str`.

`open` and `acknowledged` warnings reach the agent. `dismissed` ones do not - that is what a dismissal means.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validation_warning_injection.py
import pytest
from api.config import get_settings
from api.database import get_connection


@pytest.fixture
async def crew_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "inject-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, name, sector) VALUES (?,?,?)",
            (slug, "Inject Test", "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_open_and_acknowledged_warnings_reach_the_agent(crew_project):
    slug, project_id = crew_project
    from agents.tools._db import record_validation_warnings_sync
    from api.services.run_service import _fetch_validation_warnings
    from api.database import fetch_validation_warnings, dispose_validation_warning

    record_validation_warnings_sync(slug, 1, "value_chain_tree", [
        {"subject": None, "code": "missing_l0", "detail": "no root node", "measure": None},
        {"subject": "1.F", "code": "missing_role_node", "detail": "1.F dropped",
         "measure": None},
    ])
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
        ack = next(r for r in rows if r["code"] == "missing_role_node")
        await dispose_validation_warning(
            conn, warning_id=ack["id"], disposition="acknowledged",
            note="yes, fix it", by="consultant")

    text = await _fetch_validation_warnings(slug, "discovery_mapping")
    assert "no root node" in text
    assert "1.F dropped" in text
    assert "STRUCTURAL WARNINGS" in text


@pytest.mark.asyncio
async def test_a_dismissed_warning_does_not_reach_the_agent(crew_project):
    slug, project_id = crew_project
    from agents.tools._db import record_validation_warnings_sync
    from api.services.run_service import _fetch_validation_warnings
    from api.database import fetch_validation_warnings, dispose_validation_warning

    record_validation_warnings_sync(slug, 1, "value_chain_tree", [
        {"subject": None, "code": "missing_l0", "detail": "no root node", "measure": None}])
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
        await dispose_validation_warning(
            conn, warning_id=rows[0]["id"], disposition="dismissed",
            note="single-entity client, no L0 needed", by="consultant")

    assert await _fetch_validation_warnings(slug, "discovery_mapping") == ""


@pytest.mark.asyncio
async def test_warnings_are_scoped_to_the_crew_that_caused_them(crew_project):
    """Casey's skew must not be injected into Alex's run, and vice versa."""
    slug, _ = crew_project
    from agents.tools._db import record_validation_warnings_sync
    from api.services.run_service import _fetch_validation_warnings

    record_validation_warnings_sync(slug, 1, "theme_anchor", [
        {"subject": None, "code": "l3_skew", "detail": "8 of 10 at L3", "measure": 0.8}])

    assert await _fetch_validation_warnings(slug, "discovery_mapping") == ""
    assert "8 of 10 at L3" in await _fetch_validation_warnings(slug, "discovery_interviews")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_validation_warning_injection.py -v`
Expected: FAIL with `ImportError: cannot import name '_fetch_validation_warnings'`

- [ ] **Step 3: Add the fetcher**

In `api/services/run_service.py`, after `_fetch_change_requests` (ends line ~168):

```python
# Which crew is answerable for each warning source. A warning is only useful to the agent
# that can act on it: Alex cannot fix a theme skew and Casey cannot add a root node.
_WARNING_SOURCE_CREW: dict[str, str] = {
    "value_chain_tree": "discovery_mapping",
    "theme_anchor": "discovery_interviews",
}


async def _fetch_validation_warnings(slug: str, crew_name: str) -> str:
    """Structural warnings this crew is answerable for, as a prompt block.

    open and acknowledged both reach the agent; dismissed does not. That asymmetry is the
    whole meaning of a disposition - acknowledged says "this is real, fix it", dismissed
    says "this is a false positive", and re-injecting a dismissed warning would make the
    dismissal pointless.

    This is the machine half of the feedback loop: no reviewer involvement, just an agent
    seeing what its last output was flagged for. The human half - a reviewer's note - comes
    through _fetch_change_requests above.
    """
    from api.database import fetch_project, fetch_validation_warnings

    sources = [s for s, c in _WARNING_SOURCE_CREW.items() if c == crew_name]
    if not sources:
        return ""
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return ""
        rows = await fetch_validation_warnings(
            conn, project_id=project["id"], sources=sources,
            dispositions=["open", "acknowledged"],
        )
    if not rows:
        return ""
    lines = []
    for r in rows:
        subject = f"[{r['subject']}] " if r["subject"] else ""
        lines.append(f"- {subject}{r['detail']}")
    return (
        "STRUCTURAL WARNINGS (your last output was flagged for these; correct them):\n"
        + "\n".join(lines)
    )
```

- [ ] **Step 4: Inject it**

In `build_and_run_crew`, immediately after the `change_text` injection block (line ~448) and before `result = await crew.kickoff_async()`:

```python
    warning_text = await _fetch_validation_warnings(slug, crew_name)
    if warning_text:
        for task in crew.tasks:
            task.description = warning_text + "\n\n" + task.description
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_validation_warning_injection.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add api/services/run_service.py tests/test_validation_warning_injection.py
git commit -m "feat(validation): an agent sees what its last output was flagged for"
```

---

## Task 10: Dispositions - the API and the re-raise rule

**Files:**
- Create: `api/routers/validations.py`
- Modify: `api/main.py` (register the router beside `value_chain_router`, line 165)
- Modify: `agents/tools/_db.py` (`record_validation_warnings_sync` re-raise logic)
- Test: `tests/test_warning_dispositions.py` *(new)*

**Interfaces:**
- Produces: `GET /projects/{slug}/validation-warnings?source=&disposition=`; `PATCH /projects/{slug}/validation-warnings/{warning_id}` body `{"disposition": "acknowledged"|"dismissed"|"open", "note": str}`.

**The re-raise rule:** a `dismissed` warning returns to `open` when its measure moves by more than `SKEW_RERAISE_DELTA`. Without it, one dismissal blinds the check permanently - which is how a warning system dies.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_warning_dispositions.py
import pytest
from api.config import get_settings
from api.database import get_connection, fetch_validation_warnings, dispose_validation_warning
from agents.tools._db import record_validation_warnings_sync


@pytest.fixture
async def disp_project(tmp_path, monkeypatch):
    """Isolated, because the re-raise rule needs a database no other test writes to."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "disp-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, name, sector) VALUES (?,?,?)",
            (slug, "Disp Test", "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id
    get_settings.cache_clear()


def _skew(measure):
    return [{"subject": None, "code": "l3_skew", "detail": f"{measure:.0%} at L3",
             "measure": measure}]


@pytest.mark.asyncio
async def test_a_dismissed_warning_stays_dismissed_when_the_measure_barely_moves(disp_project):
    slug, project_id = disp_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.80))
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
        await dispose_validation_warning(
            conn, warning_id=rows[0]["id"], disposition="dismissed",
            note="all tactical this time", by="consultant")

    record_validation_warnings_sync(slug, 2, "theme_anchor", _skew(0.85))
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert rows[0]["disposition"] == "dismissed", "5pp is not a material move"


@pytest.mark.asyncio
async def test_a_dismissed_warning_re_raises_when_the_measure_moves_materially(disp_project):
    slug, project_id = disp_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.72))
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
        await dispose_validation_warning(
            conn, warning_id=rows[0]["id"], disposition="dismissed",
            note="borderline, fine", by="consultant")

    record_validation_warnings_sync(slug, 2, "theme_anchor", _skew(0.95))
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert rows[0]["disposition"] == "open", "23pp must re-raise"
    assert rows[0]["disposition_note"] is None


@pytest.mark.asyncio
async def test_an_acknowledged_warning_is_never_auto_reset(disp_project):
    slug, project_id = disp_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.72))
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
        await dispose_validation_warning(
            conn, warning_id=rows[0]["id"], disposition="acknowledged",
            note="real", by="consultant")

    record_validation_warnings_sync(slug, 2, "theme_anchor", _skew(0.99))
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    assert rows[0]["disposition"] == "acknowledged"
    assert rows[0]["disposition_note"] == "real"


@pytest.fixture
async def api_project():
    """A project on the DEFAULT settings, because the shared `client` fixture builds the app
    against them - a monkeypatched DATABASE_DIR would leave the client reading a different
    database from the one the test writes to. Every assertion below is scoped to the slug
    this fixture created, never to a global count or a hardcoded id."""
    slug = "disp-api-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO projects (slug, name, sector) VALUES (?,?,?)",
            (slug, "Disp API Test", "test"))
        await conn.execute("DELETE FROM validation_warnings")
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id


@pytest.mark.asyncio
async def test_the_endpoints_list_and_dispose(api_project, client):
    slug, project_id = api_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.80))

    listed = await client.get(f"/projects/{slug}/validation-warnings")
    assert listed.status_code == 200
    body = [w for w in listed.json() if w["code"] == "l3_skew"]
    assert len(body) == 1

    patched = await client.patch(
        f"/projects/{slug}/validation-warnings/{body[0]['id']}",
        json={"disposition": "dismissed", "note": "all tactical"})
    assert patched.status_code == 200

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    row = next(r for r in rows if r["code"] == "l3_skew")
    assert row["disposition"] == "dismissed"
    assert row["disposition_note"] == "all tactical"


@pytest.mark.asyncio
async def test_an_invalid_disposition_is_rejected(api_project, client):
    slug, project_id = api_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.80))
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    wid = next(r["id"] for r in rows if r["code"] == "l3_skew")

    r = await client.patch(
        f"/projects/{slug}/validation-warnings/{wid}",
        json={"disposition": "maybe", "note": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_a_dismissal_without_a_reason_is_rejected(api_project, client):
    """A dismissal with no reason is indistinguishable from nobody looking."""
    slug, project_id = api_project
    record_validation_warnings_sync(slug, 1, "theme_anchor", _skew(0.80))
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    wid = next(r["id"] for r in rows if r["code"] == "l3_skew")

    r = await client.patch(
        f"/projects/{slug}/validation-warnings/{wid}",
        json={"disposition": "dismissed", "note": "   "})
    assert r.status_code == 422
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_warning_dispositions.py -v`
Expected: FAIL - the re-raise tests fail (nothing resets a dismissal) and the endpoint tests 404

- [ ] **Step 3: Add the re-raise to the recorder**

In `agents/tools/_db.py`, replace the `ON CONFLICT` clause of `record_validation_warnings_sync` with a read-then-write, so the delta can be compared:

```python
        for w in warnings:
            subject = w.get("subject")
            measure = w.get("measure")
            row = conn.execute(
                "SELECT id, disposition, measure FROM validation_warnings"
                " WHERE project_id=? AND source=? AND IFNULL(subject,'')=? AND code=?",
                (project_id, source, subject or "", w["code"]),
            ).fetchone()

            if row is None:
                conn.execute(
                    "INSERT INTO validation_warnings"
                    " (project_id, run_id, source, subject, code, detail, measure)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (project_id, run_id or None, source, subject,
                     w["code"], w["detail"], measure),
                )
                continue

            warning_id, disposition, old_measure = row[0], row[1], row[2]
            # A dismissal says "this is a false positive at this magnitude". Once the
            # magnitude moves materially it is a different claim, so the dismissal expires.
            # Without this one dismissal blinds the check forever, which is how a warning
            # system dies. An acknowledgement is never auto-reset - it already says "real".
            reraise = (
                disposition == "dismissed"
                and measure is not None and old_measure is not None
                and abs(measure - old_measure) > SKEW_RERAISE_DELTA
            )
            if reraise:
                conn.execute(
                    "UPDATE validation_warnings SET run_id=?, detail=?, measure=?,"
                    " disposition='open', disposition_note=NULL, disposed_by=NULL,"
                    " disposed_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (run_id or None, w["detail"], measure, warning_id),
                )
            else:
                conn.execute(
                    "UPDATE validation_warnings SET run_id=?, detail=?, measure=?,"
                    " updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (run_id or None, w["detail"], measure, warning_id),
                )
        conn.commit()
```

Add the import at the top of `agents/tools/_db.py`:

```python
from api.services.anchor_validation import SKEW_RERAISE_DELTA
```

- [ ] **Step 4: Add the router**

```python
# api/routers/validations.py
"""List and dispose of structural validation warnings.

A warning nobody can see cannot inform a review decision, and a disposition nobody can
record cannot tell "we considered this and it is fine" from "nobody looked".
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_any_auth, check_project_access
from api.database import (
    get_connection, get_db_path, fetch_project,
    fetch_validation_warnings, dispose_validation_warning,
)

router = APIRouter(prefix="/projects", tags=["validations"])

_DISPOSITIONS = ("open", "acknowledged", "dismissed")


class DispositionRequest(BaseModel):
    disposition: str
    note: str = ""


@router.get("/{slug}/validation-warnings")
async def list_validation_warnings(
    slug: str,
    source: str | None = None,
    disposition: str | None = None,
    payload: dict = Depends(require_any_auth),
):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return await fetch_validation_warnings(
            conn,
            project_id=project["id"],
            sources=[source] if source else None,
            dispositions=[disposition] if disposition else None,
        )


@router.patch("/{slug}/validation-warnings/{warning_id}")
async def dispose_warning(
    slug: str,
    warning_id: int,
    req: DispositionRequest,
    payload: dict = Depends(require_any_auth),
):
    await check_project_access(slug, payload)
    if req.disposition not in _DISPOSITIONS:
        raise HTTPException(
            status_code=422,
            detail=f"disposition must be one of {', '.join(_DISPOSITIONS)}",
        )
    # A dismissal without a reason is indistinguishable from nobody looking, which is the
    # exact ambiguity the disposition exists to remove.
    if req.disposition == "dismissed" and not req.note.strip():
        raise HTTPException(
            status_code=422, detail="a dismissal must record why it is a false positive"
        )
    async with get_connection(slug) as conn:
        updated = await dispose_validation_warning(
            conn, warning_id=warning_id, disposition=req.disposition,
            note=req.note.strip(), by=payload.get("sub", "unknown"),
        )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Warning {warning_id} not found")
    return {"id": warning_id, "disposition": req.disposition, "note": req.note}
```

Register it in `api/main.py` after line 165:

```python
app.include_router(validations_router.router)
```

with the matching import beside the other router imports.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_warning_dispositions.py -v`
Expected: 5 passed

- [ ] **Step 6: Run the full suite twice**

Run: `./venv/bin/pytest -q && ./venv/bin/pytest -q`
Expected: no new failures against the baseline

- [ ] **Step 7: Commit**

```bash
git add api/routers/validations.py api/main.py agents/tools/_db.py tests/test_warning_dispositions.py
git commit -m "feat(validation): dispositions, and a dismissal that expires when the measure moves"
```

---

## Task 11: Warnings in the review dialog and the status tab

**Files:**
- Create: `ui/src/components/ValidationWarnings.tsx`
- Modify: `ui/src/api/endpoints.ts` (new `validationsApi`)
- Modify: `ui/src/types.ts` (new `ValidationWarning`)
- Modify: `ui/src/components/ReviewDialog.tsx` (render inside the dialog body, near `OutputPreview`)
- Modify: `ui/src/components/AgentStatusTab.tsx` (render in the artefact history)
- Test: `ui/src/__tests__/ValidationWarnings.test.tsx` *(new)*

**Interfaces:**
- Consumes: the endpoints from Task 10.
- Produces: `<ValidationWarnings slug source readOnly? />`.

**ReviewDialog is the load-bearing surface.** It is where a reviewer chooses `approve` or `changes_requested`, and a warning they never see cannot inform that decision.

- [ ] **Step 1: Write the failing test**

```tsx
// ui/src/__tests__/ValidationWarnings.test.tsx
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import ValidationWarnings from '../components/ValidationWarnings'
import { validationsApi } from '../api/endpoints'

vi.mock('../api/endpoints', () => ({
  validationsApi: { list: vi.fn(), dispose: vi.fn() },
}))

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const WARNING = {
  id: 1, source: 'value_chain_tree', subject: null, code: 'missing_l0',
  detail: 'the tree has no root node with id "0"', measure: null,
  disposition: 'open', disposition_note: null,
}

beforeEach(() => vi.clearAllMocks())

describe('ValidationWarnings', () => {
  it('shows the detail of an open warning', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([WARNING] as never)
    wrap(<ValidationWarnings slug="p" source="value_chain_tree" />)
    expect(await screen.findByText(/no root node/)).toBeInTheDocument()
    expect(screen.getByText('missing_l0')).toBeInTheDocument()
  })

  it('renders nothing when there are no warnings', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([] as never)
    const { container } = wrap(<ValidationWarnings slug="p" source="value_chain_tree" />)
    await waitFor(() => expect(validationsApi.list).toHaveBeenCalled())
    expect(container.textContent).toBe('')
  })

  it('sends the acknowledgement the reviewer chose', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([WARNING] as never)
    vi.mocked(validationsApi.dispose).mockResolvedValue({} as never)
    wrap(<ValidationWarnings slug="p" source="value_chain_tree" />)
    fireEvent.click(await screen.findByRole('button', { name: /acknowledge/i }))
    await waitFor(() =>
      expect(validationsApi.dispose).toHaveBeenCalledWith('p', 1, 'acknowledged', ''))
  })

  it('will not dismiss without a reason', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([WARNING] as never)
    wrap(<ValidationWarnings slug="p" source="value_chain_tree" />)
    fireEvent.click(await screen.findByRole('button', { name: /dismiss/i }))
    const send = await screen.findByRole('button', { name: /^dismiss$/i })
    expect(send).toBeDisabled()
    expect(validationsApi.dispose).not.toHaveBeenCalled()
  })

  it('shows a dismissed warning with its recorded reason', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([
      { ...WARNING, disposition: 'dismissed', disposition_note: 'single-entity client' },
    ] as never)
    wrap(<ValidationWarnings slug="p" source="value_chain_tree" />)
    expect(await screen.findByText(/single-entity client/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/ValidationWarnings.test.tsx`
Expected: FAIL - cannot resolve `../components/ValidationWarnings`

- [ ] **Step 3: Add the type and the API client**

In `ui/src/types.ts`:

```ts
export interface ValidationWarning {
  id: number
  source: string
  subject: string | null
  code: string
  detail: string
  measure: number | null
  disposition: 'open' | 'acknowledged' | 'dismissed'
  disposition_note: string | null
}
```

In `ui/src/api/endpoints.ts`, beside `valueChainApi`:

```ts
export const validationsApi = {
  list: (slug: string, source?: string): Promise<import('../types').ValidationWarning[]> =>
    apiClient
      .get(`/projects/${slug}/validation-warnings`, { params: source ? { source } : {} })
      .then((r) => r.data),
  dispose: (
    slug: string, warningId: number,
    disposition: 'open' | 'acknowledged' | 'dismissed', note: string,
  ): Promise<{ id: number }> =>
    apiClient
      .patch(`/projects/${slug}/validation-warnings/${warningId}`, { disposition, note })
      .then((r) => r.data),
}
```

- [ ] **Step 4: Write the component**

```tsx
// ui/src/components/ValidationWarnings.tsx
// Structural findings a validator raised on this artefact. Rendered in the review dialog,
// where a reviewer decides approve or changes_requested - a warning they never see cannot
// inform that decision - and in the agent's Status tab, this project's home for an
// artefact's history.
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, X } from 'lucide-react'
import { validationsApi } from '../api/endpoints'
import type { ValidationWarning } from '../types'

const TONE: Record<ValidationWarning['disposition'], string> = {
  open: 'border-amber-700/50 bg-amber-950/20',
  acknowledged: 'border-amber-700/50 bg-amber-950/20',
  dismissed: 'border-slate-700/50 bg-surface-card opacity-70',
}

export default function ValidationWarnings(
  { slug, source, readOnly = false }: { slug: string; source: string; readOnly?: boolean },
) {
  const qc = useQueryClient()
  const [dismissing, setDismissing] = useState<number | null>(null)
  const [reason, setReason] = useState('')

  const { data } = useQuery({
    queryKey: ['validation-warnings', slug, source],
    queryFn: () => validationsApi.list(slug, source),
  })

  const dispose = useMutation({
    mutationFn: ({ id, disposition, note }:
      { id: number; disposition: 'acknowledged' | 'dismissed'; note: string }) =>
      validationsApi.dispose(slug, id, disposition, note),
    onSuccess: () => {
      setDismissing(null)
      setReason('')
      qc.invalidateQueries({ queryKey: ['validation-warnings', slug, source] })
    },
  })

  const warnings = data ?? []
  if (warnings.length === 0) return null

  return (
    <div className="space-y-2">
      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
        Structural warnings
      </p>
      {warnings.map((w) => (
        <div key={w.id} className={`rounded-lg border p-3 ${TONE[w.disposition]}`}>
          <div className="flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-mono text-amber-400 uppercase tracking-wide">
                {w.code}{w.subject ? ` - ${w.subject}` : ''}
              </p>
              <p className="text-sm text-slate-300 mt-0.5">{w.detail}</p>
              {w.disposition === 'dismissed' && w.disposition_note && (
                <p className="text-xs text-muted mt-1">Dismissed: {w.disposition_note}</p>
              )}
              {w.disposition === 'acknowledged' && (
                <p className="text-xs text-muted mt-1">
                  Acknowledged - carried into the agent's next run.
                </p>
              )}

              {!readOnly && w.disposition === 'open' && dismissing !== w.id && (
                <div className="flex gap-2 mt-2">
                  <button
                    type="button"
                    onClick={() => dispose.mutate({ id: w.id, disposition: 'acknowledged', note: '' })}
                    className="text-xs px-2 py-1 rounded bg-brand/20 text-brand hover:bg-brand/30"
                  >
                    <Check className="w-3 h-3 inline mr-1" />Acknowledge
                  </button>
                  <button
                    type="button"
                    onClick={() => setDismissing(w.id)}
                    className="text-xs px-2 py-1 rounded bg-surface-raised text-secondary hover:text-primary"
                  >
                    <X className="w-3 h-3 inline mr-1" />Dismiss
                  </button>
                </div>
              )}

              {dismissing === w.id && (
                <div className="mt-2 space-y-2">
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Why is this a false positive?"
                    className="w-full text-xs bg-surface-raised rounded p-2 text-primary"
                    rows={2}
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={!reason.trim()}
                      onClick={() => dispose.mutate({
                        id: w.id, disposition: 'dismissed', note: reason.trim(),
                      })}
                      className="text-xs px-2 py-1 rounded bg-brand/20 text-brand disabled:opacity-40"
                    >
                      Dismiss
                    </button>
                    <button
                      type="button"
                      onClick={() => { setDismissing(null); setReason('') }}
                      className="text-xs px-2 py-1 rounded text-secondary"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 5: Mount it in both surfaces**

In `ui/src/components/ReviewDialog.tsx`, add near the other imports:

```tsx
import ValidationWarnings from './ValidationWarnings'

const CREW_WARNING_SOURCE: Record<string, string> = {
  discovery_mapping: 'value_chain_tree',
  discovery_interviews: 'theme_anchor',
}
```

and render it in the dialog body, directly above the approve / revise controls:

```tsx
{review.crew_name && CREW_WARNING_SOURCE[review.crew_name] && (
  <ValidationWarnings slug={slug} source={CREW_WARNING_SOURCE[review.crew_name]} />
)}
```

In `ui/src/components/AgentStatusTab.tsx`, add the import and a source map keyed by the agent whose tab is open, then render read-only above the artefact history:

```tsx
import ValidationWarnings from './ValidationWarnings'

const AGENT_WARNING_SOURCE: Record<string, string> = {
  value_chain_mapper: 'value_chain_tree',
  synthesis_analyst: 'theme_anchor',
}
```

```tsx
{AGENT_WARNING_SOURCE[agentKey] && (
  <ValidationWarnings slug={slug} source={AGENT_WARNING_SOURCE[agentKey]} readOnly />
)}
```

`agentKey` is the snake_case agent name this tab already has in scope - read the component's props before wiring it, and use whatever it calls that value rather than introducing a new one.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd ui && npx vitest run`
Expected: all suites pass, including the 5 new tests

- [ ] **Step 7: Commit**

```bash
git add ui/src/components/ValidationWarnings.tsx ui/src/api/endpoints.ts ui/src/types.ts ui/src/components/ReviewDialog.tsx ui/src/components/AgentStatusTab.tsx ui/src/__tests__/ValidationWarnings.test.tsx
git commit -m "feat(ui): a reviewer sees the structural warnings before choosing approve"
```

---

## Task 12: PAM reports on structurally suspect output

**Files:**
- Modify: `api/services/pam_report_service.py` (`build_pam_report`, line 68)
- Test: `tests/test_pam_report_warnings.py` *(new)*

**Interfaces:**
- Consumes: `fetch_validation_warnings` (Task 1).
- Produces: a `validation_warnings` key on the report dict: `{"open": int, "acknowledged": int, "by_crew": {crew: int}}`.

Pamela cannot report accurately on a crew whose output is structurally suspect.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pam_report_warnings.py
import pytest
from api.config import get_settings
from api.database import get_connection, fetch_validation_warnings, dispose_validation_warning
from agents.tools._db import record_validation_warnings_sync
from api.services.pam_report_service import build_pam_report


@pytest.fixture
async def pam_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "pam-warn"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, name, sector) VALUES (?,?,?)",
            (slug, "PAM Warn", "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_report_counts_warnings_by_crew(pam_project):
    slug, project_id = pam_project
    record_validation_warnings_sync(slug, 1, "value_chain_tree", [
        {"subject": None, "code": "missing_l0", "detail": "no root", "measure": None}])
    record_validation_warnings_sync(slug, 1, "theme_anchor", [
        {"subject": None, "code": "l3_skew", "detail": "8 of 10", "measure": 0.8}])

    report = await build_pam_report(slug)
    vw = report["validation_warnings"]
    assert vw["open"] == 2
    assert vw["acknowledged"] == 0
    assert vw["by_crew"]["discovery_mapping"] == 1
    assert vw["by_crew"]["discovery_interviews"] == 1


@pytest.mark.asyncio
async def test_a_dismissed_warning_is_not_counted(pam_project):
    slug, project_id = pam_project
    record_validation_warnings_sync(slug, 1, "value_chain_tree", [
        {"subject": None, "code": "missing_l0", "detail": "no root", "measure": None}])
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
        await dispose_validation_warning(
            conn, warning_id=rows[0]["id"], disposition="dismissed",
            note="single entity", by="consultant")

    report = await build_pam_report(slug)
    assert report["validation_warnings"]["open"] == 0
    assert report["validation_warnings"]["by_crew"] == {}


@pytest.mark.asyncio
async def test_the_key_is_present_when_there_are_no_warnings(pam_project):
    """A missing key and a zero count read the same to a consumer that uses .get()."""
    slug, _ = pam_project
    report = await build_pam_report(slug)
    assert report["validation_warnings"] == {"open": 0, "acknowledged": 0, "by_crew": {}}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_pam_report_warnings.py -v`
Expected: FAIL with `KeyError: 'validation_warnings'`

- [ ] **Step 3: Add the counts to the report**

In `api/services/pam_report_service.py`, inside `build_pam_report`'s `async with get_connection(slug) as conn:` block after the outputs query (line ~103):

```python
        # Pamela cannot report accurately on a crew whose output is structurally suspect,
        # so an open or acknowledged warning is part of project health. A dismissed one is
        # not - somebody looked and recorded why.
        from api.database import fetch_validation_warnings
        from api.services.run_service import _WARNING_SOURCE_CREW

        warning_rows = await fetch_validation_warnings(
            conn, project_id=project["id"], dispositions=["open", "acknowledged"],
        )
        by_crew: dict[str, int] = {}
        for w in warning_rows:
            crew = _WARNING_SOURCE_CREW.get(w["source"])
            if crew:
                by_crew[crew] = by_crew.get(crew, 0) + 1
        validation_warnings = {
            "open": sum(1 for w in warning_rows if w["disposition"] == "open"),
            "acknowledged": sum(1 for w in warning_rows if w["disposition"] == "acknowledged"),
            "by_crew": by_crew,
        }
```

Add `"validation_warnings": validation_warnings,` to the dict the function returns.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_pam_report_warnings.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add api/services/pam_report_service.py tests/test_pam_report_warnings.py
git commit -m "feat(pam): project health counts the structural warnings a crew has open"
```

---

## Task 13: Record the L3-bias factor in project context

**Files:**
- Modify: `CLAUDE.md` (new section after "Crew / agent conventions")

**Interfaces:** none.

`CLAUDE.md` is loaded into every session. The design doc is the fuller account; this is the line that must not be re-derived.

- [ ] **Step 1: Add the section**

Insert after the "Crew / agent conventions" section:

```markdown
---

## Anchoring: themes and requirements sit where the insight lives

Themes and requirements must anchor at the level where the insight lives - L0 for
governance, assurance and vertical themes; L1 for functional; L2 for decision and
effectiveness; L3 for tactical and efficiency. Anchoring everything at `n.n.n` loses
resolution and systematically skews value proposition generation toward L3 efficiency.

This is a pipeline-shaping property, not a formatting preference: L3 is the only altitude
the evidence is ever expressed at if nothing else is available to anchor to, so every
proposition built downstream inherits the bias.

The tree is the canonical spine. `0` is the organisation; `0.A` and `0.S` are its
organisation-level role nodes; each L1 entity carries the `<L1>.C` and `<L1>.F` role nodes
it warrants. L2 and L3 belong to exactly one L1 - nothing is shared or duplicated. IDs may
grow and may retire, but may never be redefined or forgotten: Architecture's capability
model is built against them.

Fuller account: `docs/superpowers/specs/2026-08-06-l0-anchor-and-level-anchored-synthesis-design.md`.
```

- [ ] **Step 2: Verify the file still reads correctly**

Run: `./venv/bin/python -c "
from pathlib import Path
t = Path('CLAUDE.md').read_text()
assert 'Anchoring: themes and requirements sit where the insight lives' in t
assert t.count('---') > 5
print('sections:', t.count(chr(10) + '## '))"`
Expected: prints a section count with no assertion error

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record why anchoring level shapes the whole downstream pipeline"
```

---

## Final verification

- [ ] **Run the backend suite twice**

Run: `./venv/bin/pytest -q && ./venv/bin/pytest -q`
Expected: identical results both times, no new failures against the baseline of 10 known.

- [ ] **Run the frontend suite**

Run: `cd ui && npx vitest run`
Expected: all pass (364 before this plan, plus 5 new).

- [ ] **Prove the regression that started this is closed, end to end**

Run a real `discovery_mapping` on `sp-gs-am` and check the tree, the registry and the warnings:

```bash
./venv/bin/python -c "
import json, sqlite3
from pathlib import Path
from agents.tools._db import latest_output_path

tree = json.loads(Path(latest_output_path(Path('projects/sp-gs-am/outputs/value_chain_tree.json'))).read_text())
roots = [n['id'] for n in tree]
print('root ids:', roots)
assert roots == ['0'], 'the tree must have a single L0 root'

reg = json.loads(Path(latest_output_path(Path('projects/sp-gs-am/outputs/value_chain_registry.json'))).read_text())
ids = {a['id'] for a in reg['activities']}
print('L0 in registry:', '0' in ids)
print('role nodes:', sorted(i for i in ids if i.rsplit('.',1)[-1] in ('A','S','C','F')))

c = sqlite3.connect('data/sp-gs-am.db')
print('warnings:', c.execute('SELECT source, code, disposition FROM validation_warnings').fetchall())
"
```

Expected: a single root `['0']`, `'0'` present in the registry, role nodes listed, and either no `missing_l0` warning or one whose presence correctly reflects a tree that still lacks the root.

---

## Sequencing note

Sub-project **C stage 1 is already built and merged** - `output_changes` carries `kind`, `status` and `applied_run_id`, and `_fetch_change_requests` injects open change requests into the crew that owns the output. That was the hard prerequisite for the human half of this design, so this plan can proceed.

C stages 2 and 3 (corrections to RAG, skills promotion) remain unbuilt. This plan does not depend on them: the machine loop in Task 9 is self-contained. The triage that turns an acknowledged warning into a durable agent skill is C's work, and Task 9's `acknowledged` disposition is the hook it will read.
