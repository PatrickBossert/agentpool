# SP10a Stakeholder Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full stakeholder registry to each project — a `stakeholders` table with rich attribution, CRUD endpoints, CSV bulk import, a searchable list page, and a full-page add/edit form.

**Architecture:** Per-project SQLite table (`stakeholders`) migrated via `_migrate_stakeholders` called from `get_connection`. JSON text columns store multi-value arrays (`value_streams`, `stakeholder_groups`). Service + router follow the same thin-layer pattern as `runs.py`/`reviews.py`. Frontend has a list page at `/:slug/stakeholders` and a shared add/edit page at `/:slug/stakeholders/new` and `/:slug/stakeholders/:id/edit`. Country selection auto-fills timezone, currency, and language from a bundled `countryData.ts` static map.

**Tech Stack:** Python 3.14, FastAPI, aiosqlite, pytest-asyncio, React 18, TypeScript, TanStack Query v5, React Router v6, Tailwind CSS

**Working directory:** `/Users/pboagents/Documents/agentpool1/.worktrees/sp10a-stakeholder-registry`

---

## Codebase context (read before implementing)

**Test setup** — `tests/conftest.py` provides:
- `client` fixture: async HTTPX client pointed at the FastAPI app
- Env vars set to `/tmp/agentpool_test` for DB dir, `test-secret` for JWT, etc.
- Each test file adds its own `autouse=True` fixture to delete its test DB before/after

**Migration pattern** — see `api/database.py`:
```python
async def _migrate_crew_runs(conn: aiosqlite.Connection) -> None:
    async with conn.execute("PRAGMA table_info(crew_runs)") as cur:
        cols = [row["name"] async for row in cur]
    if "orchestration_run_id" not in cols:
        await conn.execute("ALTER TABLE crew_runs ADD COLUMN ...")
        await conn.commit()
```
Then add the call to `get_connection` after `await _migrate_crew_runs(conn)`.

**DB helper pattern** — helpers use keyword-only args, `aiosqlite.Row` factory (already set in `get_connection`), `dict(row)` to return dicts.

**Service pattern** — see `api/services/project_service.py::get_run_history`:
- Check `get_db_path(slug).exists()` first → return `None` if missing
- Open `get_connection(slug)`, call `fetch_project`, call DB helper

**Router pattern** — see `api/routers/runs.py`. Register in `api/main.py` alongside other routers.

**JSON array fields** — `stakeholder_groups` and `value_streams` are stored as JSON strings in SQLite (e.g. `'["ops","customer"]'`). DB helpers call `json.dumps` on write and `json.loads` on read so all callers work with Python lists.

**Route ordering** — FastAPI matches routes top-to-bottom. Register `POST /{slug}/stakeholders/import` **before** `GET/PUT/DELETE /{slug}/stakeholders/{stakeholder_id}` to prevent `/import` being matched as an integer id.

**Frontend API client** — `ui/src/api/endpoints.ts` exports `projectsApi` and (new) `stakeholdersApi`. Uses `apiClient` from `./client`.

---

## Files created / modified

**Backend:**
- Create: `api/services/stakeholder_service.py`
- Create: `api/routers/stakeholders.py`
- Modify: `api/database.py` — add `_migrate_stakeholders` + 5 DB helpers + call migration in `get_connection`
- Modify: `api/main.py` — register stakeholders router

**Tests:**
- Create: `tests/test_stakeholders_api.py`

**Frontend:**
- Create: `ui/src/utils/countryData.ts`
- Create: `ui/src/pages/Stakeholders.tsx`
- Create: `ui/src/pages/StakeholderForm.tsx`
- Modify: `ui/src/types.ts` — add `Stakeholder`, `StakeholderImportResult`
- Modify: `ui/src/api/endpoints.ts` — add `stakeholdersApi`
- Modify: `ui/src/components/AppLayout.tsx` — add Stakeholders nav item
- Modify: `ui/src/router.tsx` — add three new routes

---

## Task 1: DB migration + helpers

**Files:**
- Modify: `api/database.py`
- Test: `tests/test_stakeholders_api.py` (partial — DB-level tests)

- [ ] **Step 1: Write failing tests for the migration and DB helpers**

Create `tests/test_stakeholders_api.py`:

```python
import json
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import (
    get_connection,
    fetch_project,
    insert_stakeholder,
    fetch_stakeholders,
    fetch_stakeholder,
    update_stakeholder,
    delete_stakeholder,
)

SLUG = "stakeholders-test"
PROJECT = {"client_slug": SLUG, "llm_mode": "standard", "sector": "rail"}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


STAKEHOLDER = {
    "name": "Jane Smith",
    "job_title": "CFO",
    "organisation": "Acme Corp",
    "email": "jane@acme.com",
    "slack_handle": "@jane",
    "stakeholder_groups": ["Finance"],
    "project_role": "governing",
    "value_streams": ["Customer Onboarding"],
    "value_chain_stage": "Billing",
    "activity": "Invoice processing",
    "disposition": "champion",
    "location": "United Kingdom",
    "country_code": "GB",
    "timezone": "Europe/London",
    "preferred_language": "English",
    "currency": "GBP",
}


@pytest.mark.asyncio
async def test_migration_creates_stakeholders_table(client):
    # Hitting any endpoint that calls get_connection triggers migration
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stakeholders'"
        ) as cur:
            row = await cur.fetchone()
    assert row is not None, "stakeholders table should exist after migration"


@pytest.mark.asyncio
async def test_insert_and_fetch_stakeholders(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        sid = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)
        rows = await fetch_stakeholders(conn, project_id=project["id"])
    assert len(rows) == 1
    assert rows[0]["id"] == sid
    assert rows[0]["name"] == "Jane Smith"
    assert rows[0]["stakeholder_groups"] == ["Finance"]
    assert rows[0]["value_streams"] == ["Customer Onboarding"]


@pytest.mark.asyncio
async def test_fetch_stakeholder_by_id(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        sid = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)
        row = await fetch_stakeholder(conn, stakeholder_id=sid, project_id=project["id"])
    assert row is not None
    assert row["email"] == "jane@acme.com"


@pytest.mark.asyncio
async def test_fetch_stakeholder_wrong_project_returns_none(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        sid = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)
        row = await fetch_stakeholder(conn, stakeholder_id=sid, project_id=9999)
    assert row is None


@pytest.mark.asyncio
async def test_update_stakeholder(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        sid = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)
        ok = await update_stakeholder(conn, stakeholder_id=sid, name="Jane Updated", disposition="neutral")
        row = await fetch_stakeholder(conn, stakeholder_id=sid, project_id=project["id"])
    assert ok is True
    assert row["name"] == "Jane Updated"
    assert row["disposition"] == "neutral"


@pytest.mark.asyncio
async def test_delete_stakeholder(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        sid = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)
        ok = await delete_stakeholder(conn, stakeholder_id=sid)
        rows = await fetch_stakeholders(conn, project_id=project["id"])
    assert ok is True
    assert rows == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/pboagents/Documents/agentpool1/.worktrees/sp10a-stakeholder-registry
python3 -m pytest tests/test_stakeholders_api.py::test_migration_creates_stakeholders_table tests/test_stakeholders_api.py::test_insert_and_fetch_stakeholders -v 2>&1 | tail -20
```

Expected: FAIL with `ImportError: cannot import name 'insert_stakeholder'`

- [ ] **Step 3: Add `_migrate_stakeholders` to `api/database.py`**

After the `_migrate_crew_runs` function (around line 125), add:

```python
async def _migrate_stakeholders(conn: aiosqlite.Connection) -> None:
    """Create stakeholders table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS stakeholders (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id          INTEGER NOT NULL REFERENCES projects(id),
            name                TEXT NOT NULL,
            job_title           TEXT NOT NULL DEFAULT '',
            organisation        TEXT NOT NULL DEFAULT '',
            email               TEXT NOT NULL DEFAULT '',
            slack_handle        TEXT NOT NULL DEFAULT '',
            stakeholder_groups  TEXT NOT NULL DEFAULT '[]',
            project_role        TEXT NOT NULL DEFAULT 'recipient',
            value_streams       TEXT NOT NULL DEFAULT '[]',
            value_chain_stage   TEXT NOT NULL DEFAULT '',
            activity            TEXT NOT NULL DEFAULT '',
            disposition         TEXT NOT NULL DEFAULT 'neutral',
            location            TEXT NOT NULL DEFAULT '',
            country_code        TEXT NOT NULL DEFAULT '',
            timezone            TEXT NOT NULL DEFAULT '',
            preferred_language  TEXT NOT NULL DEFAULT '',
            currency            TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()
```

- [ ] **Step 4: Wire migration into `get_connection`**

In `api/database.py`, find the `get_connection` function. After `await _migrate_crew_runs(conn)`, add:

```python
        await _migrate_stakeholders(conn)
```

The block should now read:
```python
        await init_db(conn)
        await _migrate_human_reviews(conn)
        await _migrate_crew_runs(conn)
        await _migrate_stakeholders(conn)
        yield conn
```

- [ ] **Step 5: Add the 5 DB helpers to `api/database.py`**

Add these after `fetch_all_orchestration_runs` and before the system DB section (`# ── System DB`):

```python
import json as _json  # add to top-level imports if not already present


async def insert_stakeholder(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    name: str,
    job_title: str = '',
    organisation: str = '',
    email: str = '',
    slack_handle: str = '',
    stakeholder_groups: list = None,
    project_role: str = 'recipient',
    value_streams: list = None,
    value_chain_stage: str = '',
    activity: str = '',
    disposition: str = 'neutral',
    location: str = '',
    country_code: str = '',
    timezone: str = '',
    preferred_language: str = '',
    currency: str = '',
) -> int:
    """Insert a stakeholder row. Returns new id."""
    cur = await conn.execute(
        """INSERT INTO stakeholders
           (project_id, name, job_title, organisation, email, slack_handle,
            stakeholder_groups, project_role, value_streams, value_chain_stage,
            activity, disposition, location, country_code, timezone,
            preferred_language, currency)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            project_id, name, job_title, organisation, email, slack_handle,
            _json.dumps(stakeholder_groups or []),
            project_role,
            _json.dumps(value_streams or []),
            value_chain_stage, activity, disposition,
            location, country_code, timezone, preferred_language, currency,
        ),
    )
    await conn.commit()
    return cur.lastrowid


def _deserialize_stakeholder(row: dict) -> dict:
    """Convert JSON text columns back to Python lists."""
    row["stakeholder_groups"] = _json.loads(row.get("stakeholder_groups") or "[]")
    row["value_streams"] = _json.loads(row.get("value_streams") or "[]")
    return row


async def fetch_stakeholders(
    conn: aiosqlite.Connection, *, project_id: int
) -> list[dict]:
    """Return all stakeholders for a project, ordered by name ASC."""
    async with conn.execute(
        "SELECT * FROM stakeholders WHERE project_id=? ORDER BY name ASC",
        (project_id,),
    ) as cur:
        return [_deserialize_stakeholder(dict(r)) async for r in cur]


async def fetch_stakeholder(
    conn: aiosqlite.Connection, *, stakeholder_id: int, project_id: int
) -> dict | None:
    """Return one stakeholder; None if not found or belongs to different project."""
    async with conn.execute(
        "SELECT * FROM stakeholders WHERE id=? AND project_id=?",
        (stakeholder_id, project_id),
    ) as cur:
        row = await cur.fetchone()
    return _deserialize_stakeholder(dict(row)) if row else None


async def update_stakeholder(
    conn: aiosqlite.Connection, *, stakeholder_id: int, **fields
) -> bool:
    """Update stakeholder fields by id. Returns False if not found.

    JSON-serializes list fields automatically.
    """
    for key in ("stakeholder_groups", "value_streams"):
        if key in fields and isinstance(fields[key], list):
            fields[key] = _json.dumps(fields[key])

    if not fields:
        return False
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [stakeholder_id]
    cur = await conn.execute(
        f"UPDATE stakeholders SET {set_clause} WHERE id=?", values
    )
    await conn.commit()
    return cur.rowcount > 0


async def delete_stakeholder(
    conn: aiosqlite.Connection, *, stakeholder_id: int
) -> bool:
    """Hard delete. Returns False if not found."""
    cur = await conn.execute(
        "DELETE FROM stakeholders WHERE id=?", (stakeholder_id,)
    )
    await conn.commit()
    return cur.rowcount > 0
```

**Important:** `import json as _json` should be added at the top of `api/database.py` alongside `import aiosqlite`. Use the alias `_json` to avoid shadowing any local variables.

- [ ] **Step 6: Run DB-level tests to verify they pass**

```bash
python3 -m pytest tests/test_stakeholders_api.py::test_migration_creates_stakeholders_table tests/test_stakeholders_api.py::test_insert_and_fetch_stakeholders tests/test_stakeholders_api.py::test_fetch_stakeholder_by_id tests/test_stakeholders_api.py::test_fetch_stakeholder_wrong_project_returns_none tests/test_stakeholders_api.py::test_update_stakeholder tests/test_stakeholders_api.py::test_delete_stakeholder -v 2>&1 | tail -20
```

Expected: 6 passed

- [ ] **Step 7: Commit**

```bash
git add api/database.py tests/test_stakeholders_api.py
git commit -m "feat: add stakeholders table migration and DB helpers (SP10a)"
```

---

## Task 2: Service layer + router + API tests

**Files:**
- Create: `api/services/stakeholder_service.py`
- Create: `api/routers/stakeholders.py`
- Modify: `api/main.py`
- Modify: `tests/test_stakeholders_api.py` (append 8 API-level tests)

- [ ] **Step 1: Append API-level tests to `tests/test_stakeholders_api.py`**

Add these tests at the bottom of the file (after the DB-level tests):

```python
# ── API-level tests ──────────────────────────────────────────────────────────

STAKEHOLDER_PAYLOAD = {
    "name": "Jane Smith",
    "job_title": "CFO",
    "organisation": "Acme Corp",
    "email": "jane@acme.com",
    "slack_handle": "@jane",
    "stakeholder_groups": ["Finance"],
    "project_role": "governing",
    "value_streams": ["Customer Onboarding"],
    "value_chain_stage": "Billing",
    "activity": "Invoice processing",
    "disposition": "champion",
    "location": "United Kingdom",
    "country_code": "GB",
    "timezone": "Europe/London",
    "preferred_language": "English",
    "currency": "GBP",
}


@pytest.mark.asyncio
async def test_list_stakeholders_empty(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get(f"/projects/{SLUG}/stakeholders")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_stakeholder(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(f"/projects/{SLUG}/stakeholders", json=STAKEHOLDER_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Jane Smith"
    assert data["stakeholder_groups"] == ["Finance"]
    assert data["value_streams"] == ["Customer Onboarding"]
    assert "id" in data

    list_resp = await client.get(f"/projects/{SLUG}/stakeholders")
    assert len(list_resp.json()) == 1


@pytest.mark.asyncio
async def test_update_stakeholder_api(client):
    await client.post("/projects", json=PROJECT)
    create_resp = await client.post(f"/projects/{SLUG}/stakeholders", json=STAKEHOLDER_PAYLOAD)
    sid = create_resp.json()["id"]

    updated = {**STAKEHOLDER_PAYLOAD, "name": "Jane Updated", "disposition": "neutral"}
    resp = await client.put(f"/projects/{SLUG}/stakeholders/{sid}", json=updated)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Jane Updated"
    assert resp.json()["disposition"] == "neutral"


@pytest.mark.asyncio
async def test_delete_stakeholder_api(client):
    await client.post("/projects", json=PROJECT)
    create_resp = await client.post(f"/projects/{SLUG}/stakeholders", json=STAKEHOLDER_PAYLOAD)
    sid = create_resp.json()["id"]

    del_resp = await client.delete(f"/projects/{SLUG}/stakeholders/{sid}")
    assert del_resp.status_code == 204

    list_resp = await client.get(f"/projects/{SLUG}/stakeholders")
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_stakeholder_unknown_project_404(client):
    resp = await client.get("/projects/no-such-slug/stakeholders")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stakeholder_unknown_id_404(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.put(f"/projects/{SLUG}/stakeholders/9999", json=STAKEHOLDER_PAYLOAD)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_import_csv_creates_and_updates(client):
    await client.post("/projects", json=PROJECT)
    csv_content = (
        "name,job_title,organisation,email,stakeholder_groups,project_role,"
        "value_streams,value_chain_stage,activity,disposition,"
        "location,country_code,timezone,preferred_language,currency\n"
        "Jane Smith,CFO,Acme,jane@acme.com,Finance,governing,"
        "Customer Onboarding,Billing,Invoicing,champion,"
        "United Kingdom,GB,Europe/London,English,GBP\n"
        "Tom Jones,COO,Acme,tom@acme.com,Operations,actor,"
        "Operations,Delivery,,supporter,"
        "United States,US,America/New_York,English,USD\n"
    )
    resp = await client.post(
        f"/projects/{SLUG}/stakeholders/import",
        files={"file": ("stakeholders.csv", csv_content.encode(), "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 2
    assert data["updated"] == 0
    assert data["errors"] == []

    # Import again with same emails → both should update
    resp2 = await client.post(
        f"/projects/{SLUG}/stakeholders/import",
        files={"file": ("stakeholders.csv", csv_content.encode(), "text/csv")},
    )
    assert resp2.json()["created"] == 0
    assert resp2.json()["updated"] == 2


@pytest.mark.asyncio
async def test_import_csv_skips_bad_rows(client):
    await client.post("/projects", json=PROJECT)
    csv_content = (
        "name,email,disposition\n"
        "Valid Person,valid@acme.com,champion\n"
        "Bad Person,bad@acme.com,INVALID_DISPOSITION\n"
    )
    resp = await client.post(
        f"/projects/{SLUG}/stakeholders/import",
        files={"file": ("stakeholders.csv", csv_content.encode(), "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 1
    assert len(data["errors"]) == 1
    assert data["errors"][0]["row"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_stakeholders_api.py::test_list_stakeholders_empty tests/test_stakeholders_api.py::test_create_stakeholder -v 2>&1 | tail -10
```

Expected: FAIL with `404` (routes don't exist yet)

- [ ] **Step 3: Create `api/services/stakeholder_service.py`**

```python
# api/services/stakeholder_service.py
"""Stakeholder registry — service layer."""
import csv
import io
from api.database import (
    get_connection,
    get_db_path,
    fetch_project,
    insert_stakeholder,
    fetch_stakeholders,
    fetch_stakeholder,
    update_stakeholder,
    delete_stakeholder,
)

VALID_ROLES = {"recipient", "governing", "actor"}
VALID_DISPOSITIONS = {"champion", "supporter", "neutral", "skeptic", "blocker"}


async def list_stakeholders(slug: str) -> list[dict] | None:
    """None = project not found."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await fetch_stakeholders(conn, project_id=project["id"])


async def create_stakeholder(slug: str, data: dict) -> dict | None:
    """None = project not found. Returns created stakeholder with id."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        sid = await insert_stakeholder(conn, project_id=project["id"], **data)
        return await fetch_stakeholder(conn, stakeholder_id=sid, project_id=project["id"])


async def update_stakeholder_svc(
    slug: str, stakeholder_id: int, data: dict
) -> dict | None:
    """None = not found (project or stakeholder)."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        ok = await update_stakeholder(conn, stakeholder_id=stakeholder_id, **data)
        if not ok:
            return None
        return await fetch_stakeholder(
            conn, stakeholder_id=stakeholder_id, project_id=project["id"]
        )


async def delete_stakeholder_svc(slug: str, stakeholder_id: int) -> bool | None:
    """None = project not found. False = stakeholder not found. True = deleted."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        # Verify ownership before delete
        row = await fetch_stakeholder(
            conn, stakeholder_id=stakeholder_id, project_id=project["id"]
        )
        if not row:
            return False
        return await delete_stakeholder(conn, stakeholder_id=stakeholder_id)


async def import_csv(slug: str, content: str) -> dict | None:
    """Parse CSV content and upsert rows by email.

    Returns {"created": N, "updated": M, "errors": [{"row": N, "reason": "..."}]}
    None = project not found.

    Multi-value columns (stakeholder_groups, value_streams): semicolon-separated.
    Upsert key: email. Blank email → always insert (no upsert).
    Invalid disposition → skip row with error.
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None

        created = 0
        updated = 0
        errors = []

        reader = csv.DictReader(io.StringIO(content))
        # Normalise header keys to lowercase stripped
        rows = []
        for raw_row in reader:
            rows.append({k.strip().lower(): (v or "").strip() for k, v in raw_row.items()})

        for i, row in enumerate(rows, start=1):
            # Validate disposition if provided
            disposition = row.get("disposition", "neutral") or "neutral"
            if disposition and disposition not in VALID_DISPOSITIONS:
                errors.append({"row": i, "reason": f"Invalid disposition '{disposition}'"})
                continue

            project_role = row.get("project_role", "recipient") or "recipient"
            if project_role and project_role not in VALID_ROLES:
                errors.append({"row": i, "reason": f"Invalid project_role '{project_role}'"})
                continue

            def split_semi(val: str) -> list[str]:
                return [v.strip() for v in val.split(";") if v.strip()] if val else []

            data = {
                "name": row.get("name", ""),
                "job_title": row.get("job_title", ""),
                "organisation": row.get("organisation", ""),
                "email": row.get("email", ""),
                "slack_handle": row.get("slack_handle", ""),
                "stakeholder_groups": split_semi(row.get("stakeholder_groups", "")),
                "project_role": project_role,
                "value_streams": split_semi(row.get("value_streams", "")),
                "value_chain_stage": row.get("value_chain_stage", ""),
                "activity": row.get("activity", ""),
                "disposition": disposition,
                "location": row.get("location", ""),
                "country_code": row.get("country_code", ""),
                "timezone": row.get("timezone", ""),
                "preferred_language": row.get("preferred_language", ""),
                "currency": row.get("currency", ""),
            }

            email = data["email"]
            # Upsert by email if present
            existing = None
            if email:
                async with conn.execute(
                    "SELECT id FROM stakeholders WHERE email=? AND project_id=?",
                    (email, project["id"]),
                ) as cur:
                    existing = await cur.fetchone()

            if existing:
                await update_stakeholder(conn, stakeholder_id=existing["id"], **data)
                updated += 1
            else:
                await insert_stakeholder(conn, project_id=project["id"], **data)
                created += 1

    return {"created": created, "updated": updated, "errors": errors}
```

- [ ] **Step 4: Create `api/routers/stakeholders.py`**

```python
# api/routers/stakeholders.py
"""CRUD + CSV import for project stakeholders."""
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from api.services.stakeholder_service import (
    list_stakeholders,
    create_stakeholder,
    update_stakeholder_svc,
    delete_stakeholder_svc,
    import_csv,
)

router = APIRouter(prefix="/projects", tags=["stakeholders"])


class StakeholderIn(BaseModel):
    name: str
    job_title: str = ""
    organisation: str = ""
    email: str = ""
    slack_handle: str = ""
    stakeholder_groups: list[str] = []
    project_role: str = "recipient"
    value_streams: list[str] = []
    value_chain_stage: str = ""
    activity: str = ""
    disposition: str = "neutral"
    location: str = ""
    country_code: str = ""
    timezone: str = ""
    preferred_language: str = ""
    currency: str = ""


def _404(slug: str):
    raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")


@router.get("/{slug}/stakeholders")
async def list_stakeholders_endpoint(slug: str):
    result = await list_stakeholders(slug)
    if result is None:
        _404(slug)
    return result


# IMPORTANT: /import must be registered BEFORE /{stakeholder_id} routes
@router.post("/{slug}/stakeholders/import")
async def import_stakeholders_endpoint(slug: str, file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="replace")
    result = await import_csv(slug, content)
    if result is None:
        _404(slug)
    return result


@router.post("/{slug}/stakeholders", status_code=201)
async def create_stakeholder_endpoint(slug: str, body: StakeholderIn):
    result = await create_stakeholder(slug, body.model_dump())
    if result is None:
        _404(slug)
    return result


@router.put("/{slug}/stakeholders/{stakeholder_id}")
async def update_stakeholder_endpoint(slug: str, stakeholder_id: int, body: StakeholderIn):
    result = await update_stakeholder_svc(slug, stakeholder_id, body.model_dump())
    if result is None:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    return result


@router.delete("/{slug}/stakeholders/{stakeholder_id}", status_code=204)
async def delete_stakeholder_endpoint(slug: str, stakeholder_id: int):
    result = await delete_stakeholder_svc(slug, stakeholder_id)
    if result is None:
        _404(slug)
    if result is False:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
```

- [ ] **Step 5: Register the router in `api/main.py`**

Add after the existing `from api.routers import runs as runs_router` line:

```python
from api.routers import stakeholders as stakeholders_router
```

Add after `app.include_router(runs_router.router)`:

```python
app.include_router(stakeholders_router.router)
```

- [ ] **Step 6: Run all API tests**

```bash
python3 -m pytest tests/test_stakeholders_api.py -v 2>&1 | tail -30
```

Expected: 14 passed (6 DB-level + 8 API-level)

- [ ] **Step 7: Run the full passing test suite to check for regressions**

```bash
python3 -m pytest tests/test_runs_api.py tests/test_reviews_api.py tests/test_database.py tests/test_project_service.py tests/test_stakeholders_api.py -q 2>&1 | tail -10
```

Expected: 39 passed

- [ ] **Step 8: Commit**

```bash
git add api/services/stakeholder_service.py api/routers/stakeholders.py api/main.py tests/test_stakeholders_api.py
git commit -m "feat: add stakeholder service, router, and API tests (SP10a)"
```

---

## Task 3: Frontend — types, countryData, API methods

**Files:**
- Modify: `ui/src/types.ts`
- Modify: `ui/src/api/endpoints.ts`
- Create: `ui/src/utils/countryData.ts`

- [ ] **Step 1: Add types to `ui/src/types.ts`**

Append to the end of `ui/src/types.ts`:

```typescript
export interface Stakeholder {
  id: number
  name: string
  job_title: string
  organisation: string
  email: string
  slack_handle: string
  stakeholder_groups: string[]
  project_role: 'recipient' | 'governing' | 'actor'
  value_streams: string[]
  value_chain_stage: string
  activity: string
  disposition: 'champion' | 'supporter' | 'neutral' | 'skeptic' | 'blocker'
  location: string
  country_code: string
  timezone: string
  preferred_language: string
  currency: string
  created_at: string
}

export interface StakeholderImportResult {
  created: number
  updated: number
  errors: { row: number; reason: string }[]
}
```

- [ ] **Step 2: Add `stakeholdersApi` to `ui/src/api/endpoints.ts`**

First, add `Stakeholder` and `StakeholderImportResult` to the import block at the top:

```typescript
import type {
  Project,
  ProjectStatus,
  AgentOutput,
  ClientDocument,
  ProjectSettings,
  OutputContent,
  TokenResponse,
  RoadmapData,
  FinancialSummary,
  HumanReview,
  OrchestrationRunHistory,
  Stakeholder,
  StakeholderImportResult,
} from '../types'
```

Then append `stakeholdersApi` after the closing `}` of `projectsApi`:

```typescript
export const stakeholdersApi = {
  list: (slug: string): Promise<Stakeholder[]> =>
    apiClient.get<Stakeholder[]>(`/projects/${slug}/stakeholders`).then((r) => r.data),

  create: (slug: string, data: Omit<Stakeholder, 'id' | 'created_at'>): Promise<Stakeholder> =>
    apiClient.post<Stakeholder>(`/projects/${slug}/stakeholders`, data).then((r) => r.data),

  update: (
    slug: string,
    id: number,
    data: Omit<Stakeholder, 'id' | 'created_at'>,
  ): Promise<Stakeholder> =>
    apiClient.put<Stakeholder>(`/projects/${slug}/stakeholders/${id}`, data).then((r) => r.data),

  remove: (slug: string, id: number): Promise<void> =>
    apiClient.delete(`/projects/${slug}/stakeholders/${id}`).then(() => undefined),

  importCsv: (slug: string, file: File): Promise<StakeholderImportResult> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient
      .post<StakeholderImportResult>(`/projects/${slug}/stakeholders/import`, form)
      .then((r) => r.data)
  },
}
```

- [ ] **Step 3: Create `ui/src/utils/countryData.ts`**

```typescript
// ui/src/utils/countryData.ts
// Static mapping of ISO 3166-1 alpha-2 country codes to timezone, currency, and language.
// For multi-timezone countries, the most common business timezone is used as the default.

export interface CountryInfo {
  name: string
  timezone: string  // IANA tz identifier
  currency: string  // ISO 4217 code
  language: string  // primary business language
}

export const COUNTRY_DATA: Record<string, CountryInfo> = {
  // Europe
  AT: { name: 'Austria', timezone: 'Europe/Vienna', currency: 'EUR', language: 'German' },
  BE: { name: 'Belgium', timezone: 'Europe/Brussels', currency: 'EUR', language: 'Dutch' },
  BG: { name: 'Bulgaria', timezone: 'Europe/Sofia', currency: 'BGN', language: 'Bulgarian' },
  CH: { name: 'Switzerland', timezone: 'Europe/Zurich', currency: 'CHF', language: 'German' },
  CY: { name: 'Cyprus', timezone: 'Asia/Nicosia', currency: 'EUR', language: 'Greek' },
  CZ: { name: 'Czech Republic', timezone: 'Europe/Prague', currency: 'CZK', language: 'Czech' },
  DE: { name: 'Germany', timezone: 'Europe/Berlin', currency: 'EUR', language: 'German' },
  DK: { name: 'Denmark', timezone: 'Europe/Copenhagen', currency: 'DKK', language: 'Danish' },
  EE: { name: 'Estonia', timezone: 'Europe/Tallinn', currency: 'EUR', language: 'Estonian' },
  ES: { name: 'Spain', timezone: 'Europe/Madrid', currency: 'EUR', language: 'Spanish' },
  FI: { name: 'Finland', timezone: 'Europe/Helsinki', currency: 'EUR', language: 'Finnish' },
  FR: { name: 'France', timezone: 'Europe/Paris', currency: 'EUR', language: 'French' },
  GB: { name: 'United Kingdom', timezone: 'Europe/London', currency: 'GBP', language: 'English' },
  GR: { name: 'Greece', timezone: 'Europe/Athens', currency: 'EUR', language: 'Greek' },
  HR: { name: 'Croatia', timezone: 'Europe/Zagreb', currency: 'EUR', language: 'Croatian' },
  HU: { name: 'Hungary', timezone: 'Europe/Budapest', currency: 'HUF', language: 'Hungarian' },
  IE: { name: 'Ireland', timezone: 'Europe/Dublin', currency: 'EUR', language: 'English' },
  IS: { name: 'Iceland', timezone: 'Atlantic/Reykjavik', currency: 'ISK', language: 'Icelandic' },
  IT: { name: 'Italy', timezone: 'Europe/Rome', currency: 'EUR', language: 'Italian' },
  LT: { name: 'Lithuania', timezone: 'Europe/Vilnius', currency: 'EUR', language: 'Lithuanian' },
  LU: { name: 'Luxembourg', timezone: 'Europe/Luxembourg', currency: 'EUR', language: 'French' },
  LV: { name: 'Latvia', timezone: 'Europe/Riga', currency: 'EUR', language: 'Latvian' },
  MT: { name: 'Malta', timezone: 'Europe/Malta', currency: 'EUR', language: 'English' },
  NL: { name: 'Netherlands', timezone: 'Europe/Amsterdam', currency: 'EUR', language: 'Dutch' },
  NO: { name: 'Norway', timezone: 'Europe/Oslo', currency: 'NOK', language: 'Norwegian' },
  PL: { name: 'Poland', timezone: 'Europe/Warsaw', currency: 'PLN', language: 'Polish' },
  PT: { name: 'Portugal', timezone: 'Europe/Lisbon', currency: 'EUR', language: 'Portuguese' },
  RO: { name: 'Romania', timezone: 'Europe/Bucharest', currency: 'RON', language: 'Romanian' },
  SE: { name: 'Sweden', timezone: 'Europe/Stockholm', currency: 'SEK', language: 'Swedish' },
  SI: { name: 'Slovenia', timezone: 'Europe/Ljubljana', currency: 'EUR', language: 'Slovenian' },
  SK: { name: 'Slovakia', timezone: 'Europe/Bratislava', currency: 'EUR', language: 'Slovak' },
  // Americas
  AR: { name: 'Argentina', timezone: 'America/Argentina/Buenos_Aires', currency: 'ARS', language: 'Spanish' },
  BR: { name: 'Brazil', timezone: 'America/Sao_Paulo', currency: 'BRL', language: 'Portuguese' },
  CA: { name: 'Canada', timezone: 'America/Toronto', currency: 'CAD', language: 'English' },
  CL: { name: 'Chile', timezone: 'America/Santiago', currency: 'CLP', language: 'Spanish' },
  CO: { name: 'Colombia', timezone: 'America/Bogota', currency: 'COP', language: 'Spanish' },
  MX: { name: 'Mexico', timezone: 'America/Mexico_City', currency: 'MXN', language: 'Spanish' },
  PE: { name: 'Peru', timezone: 'America/Lima', currency: 'PEN', language: 'Spanish' },
  US: { name: 'United States', timezone: 'America/New_York', currency: 'USD', language: 'English' },
  // Asia Pacific
  AU: { name: 'Australia', timezone: 'Australia/Sydney', currency: 'AUD', language: 'English' },
  CN: { name: 'China', timezone: 'Asia/Shanghai', currency: 'CNY', language: 'Mandarin' },
  HK: { name: 'Hong Kong', timezone: 'Asia/Hong_Kong', currency: 'HKD', language: 'English' },
  ID: { name: 'Indonesia', timezone: 'Asia/Jakarta', currency: 'IDR', language: 'Indonesian' },
  IN: { name: 'India', timezone: 'Asia/Kolkata', currency: 'INR', language: 'English' },
  JP: { name: 'Japan', timezone: 'Asia/Tokyo', currency: 'JPY', language: 'Japanese' },
  KR: { name: 'South Korea', timezone: 'Asia/Seoul', currency: 'KRW', language: 'Korean' },
  MY: { name: 'Malaysia', timezone: 'Asia/Kuala_Lumpur', currency: 'MYR', language: 'English' },
  NZ: { name: 'New Zealand', timezone: 'Pacific/Auckland', currency: 'NZD', language: 'English' },
  PH: { name: 'Philippines', timezone: 'Asia/Manila', currency: 'PHP', language: 'English' },
  SG: { name: 'Singapore', timezone: 'Asia/Singapore', currency: 'SGD', language: 'English' },
  TH: { name: 'Thailand', timezone: 'Asia/Bangkok', currency: 'THB', language: 'Thai' },
  TW: { name: 'Taiwan', timezone: 'Asia/Taipei', currency: 'TWD', language: 'Mandarin' },
  VN: { name: 'Vietnam', timezone: 'Asia/Ho_Chi_Minh', currency: 'VND', language: 'Vietnamese' },
  // Middle East & Africa
  AE: { name: 'United Arab Emirates', timezone: 'Asia/Dubai', currency: 'AED', language: 'Arabic' },
  EG: { name: 'Egypt', timezone: 'Africa/Cairo', currency: 'EGP', language: 'Arabic' },
  IL: { name: 'Israel', timezone: 'Asia/Jerusalem', currency: 'ILS', language: 'Hebrew' },
  KE: { name: 'Kenya', timezone: 'Africa/Nairobi', currency: 'KES', language: 'English' },
  NG: { name: 'Nigeria', timezone: 'Africa/Lagos', currency: 'NGN', language: 'English' },
  SA: { name: 'Saudi Arabia', timezone: 'Asia/Riyadh', currency: 'SAR', language: 'Arabic' },
  TR: { name: 'Turkey', timezone: 'Europe/Istanbul', currency: 'TRY', language: 'Turkish' },
  ZA: { name: 'South Africa', timezone: 'Africa/Johannesburg', currency: 'ZAR', language: 'English' },
}

export const COUNTRY_OPTIONS = Object.entries(COUNTRY_DATA)
  .map(([code, info]) => ({ code, name: info.name }))
  .sort((a, b) => a.name.localeCompare(b.name))
```

- [ ] **Step 4: Type-check the frontend**

```bash
cd /Users/pboagents/Documents/agentpool1/.worktrees/sp10a-stakeholder-registry/ui
npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors

- [ ] **Step 5: Commit**

```bash
cd /Users/pboagents/Documents/agentpool1/.worktrees/sp10a-stakeholder-registry
git add ui/src/types.ts ui/src/api/endpoints.ts ui/src/utils/countryData.ts
git commit -m "feat: add Stakeholder types, API methods, and countryData (SP10a)"
```

---

## Task 4: Stakeholders list page + nav + routes

**Files:**
- Create: `ui/src/pages/Stakeholders.tsx`
- Modify: `ui/src/components/AppLayout.tsx`
- Modify: `ui/src/router.tsx`

- [ ] **Step 1: Create `ui/src/pages/Stakeholders.tsx`**

```tsx
// ui/src/pages/Stakeholders.tsx
import { useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { stakeholdersApi } from '../api/endpoints'
import type { Stakeholder, StakeholderImportResult } from '../types'

const ROLE_COLOURS: Record<string, string> = {
  actor: 'bg-sky-900/60 text-sky-300',
  governing: 'bg-amber-900/60 text-amber-300',
  recipient: 'bg-slate-700 text-slate-300',
}

const DISPOSITION_COLOURS: Record<string, string> = {
  champion: 'bg-emerald-900/60 text-emerald-300',
  supporter: 'bg-teal-900/60 text-teal-300',
  neutral: 'bg-slate-700 text-slate-300',
  skeptic: 'bg-orange-900/60 text-orange-300',
  blocker: 'bg-red-900/60 text-red-300',
}

function Badge({ text, colours }: { text: string; colours: string }) {
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${colours}`}>{text}</span>
  )
}

export default function Stakeholders() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [importMsg, setImportMsg] = useState<string | null>(null)

  const { data: stakeholders = [], isLoading } = useQuery<Stakeholder[]>({
    queryKey: ['stakeholders', slug],
    queryFn: () => stakeholdersApi.list(slug!),
    enabled: !!slug,
  })

  const filtered = stakeholders.filter((s) => {
    const q = search.toLowerCase()
    return (
      s.name.toLowerCase().includes(q) ||
      s.organisation.toLowerCase().includes(q) ||
      s.email.toLowerCase().includes(q)
    )
  })

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !slug) return
    try {
      const result: StakeholderImportResult = await stakeholdersApi.importCsv(slug, file)
      const errMsg = result.errors.length > 0 ? ` (${result.errors.length} rows skipped)` : ''
      setImportMsg(`Imported: ${result.created} created, ${result.updated} updated${errMsg}`)
      qc.invalidateQueries({ queryKey: ['stakeholders', slug] })
    } catch {
      setImportMsg('Import failed. Check the file format.')
    }
    if (fileRef.current) fileRef.current.value = ''
    setTimeout(() => setImportMsg(null), 5000)
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-100">Stakeholders</h2>
        <div className="flex items-center gap-3">
          {importMsg && (
            <span className="text-xs text-emerald-400">{importMsg}</span>
          )}
          <label
            htmlFor="csv-import"
            className="cursor-pointer text-xs text-slate-400 hover:text-slate-200 border border-slate-700 hover:border-slate-500 rounded px-3 py-1.5 transition-colors"
          >
            Import CSV
          </label>
          <input
            id="csv-import"
            ref={fileRef}
            type="file"
            accept=".csv"
            onChange={handleImport}
            className="sr-only"
          />
          <button
            onClick={() => navigate(`/${slug}/stakeholders/new`)}
            className="text-xs bg-sky-600 hover:bg-sky-500 text-white rounded px-3 py-1.5 transition-colors"
          >
            + Add Stakeholder
          </button>
        </div>
      </div>

      {/* Search */}
      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by name, organisation, or email…"
        className="w-full max-w-sm bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 placeholder:text-slate-600 outline-none focus:border-sky-600"
      />

      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}

      {!isLoading && stakeholders.length === 0 && (
        <p className="text-sm text-slate-500">
          No stakeholders yet. Add one or import a CSV.
        </p>
      )}

      {filtered.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="bg-slate-900">
                <th className="px-4 py-2 text-left text-slate-500 font-medium">Name / Title</th>
                <th className="px-3 py-2 text-left text-slate-500 font-medium">Organisation</th>
                <th className="px-3 py-2 text-left text-slate-500 font-medium">Role</th>
                <th className="px-3 py-2 text-left text-slate-500 font-medium">Disposition</th>
                <th className="px-3 py-2 text-left text-slate-500 font-medium">Value Streams</th>
                <th className="px-3 py-2 text-left text-slate-500 font-medium">Email</th>
                <th className="px-3 py-2 text-left text-slate-500 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <tr key={s.id} className="border-t border-slate-800 hover:bg-white/[0.02]">
                  <td className="px-4 py-2.5">
                    <p className="text-slate-200 font-medium">{s.name}</p>
                    {s.job_title && <p className="text-slate-500 mt-0.5">{s.job_title}</p>}
                  </td>
                  <td className="px-3 py-2.5 text-slate-400">{s.organisation}</td>
                  <td className="px-3 py-2.5">
                    <Badge text={s.project_role} colours={ROLE_COLOURS[s.project_role] ?? ROLE_COLOURS.recipient} />
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge text={s.disposition} colours={DISPOSITION_COLOURS[s.disposition] ?? DISPOSITION_COLOURS.neutral} />
                  </td>
                  <td className="px-3 py-2.5 text-slate-400 max-w-[180px] truncate">
                    {s.value_streams.join(', ') || '—'}
                  </td>
                  <td className="px-3 py-2.5 text-slate-400">{s.email || '—'}</td>
                  <td className="px-3 py-2.5">
                    <button
                      onClick={() => navigate(`/${slug}/stakeholders/${s.id}/edit`)}
                      className="text-sky-400 hover:text-sky-300 transition-colors"
                    >
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add "Stakeholders" nav item to `ui/src/components/AppLayout.tsx`**

Find the `navItems` array. Add between Roadmap and Business Plan:

```typescript
{ to: `/${slug}/stakeholders`, label: 'Stakeholders' },
```

The array should read:
```typescript
const navItems: NavItem[] = slug
  ? [
      { to: `/${slug}`, label: 'Dashboard', end: true },
      { to: `/${slug}/value-chain`, label: 'Value Chain' },
      { to: `/${slug}/roadmap`, label: 'Roadmap' },
      { to: `/${slug}/stakeholders`, label: 'Stakeholders' },
      { to: `/${slug}/business-plan`, label: 'Business Plan' },
      { to: `/${slug}/reviews`, label: 'Reviews', badge: pendingReviewCount > 0 ? pendingReviewCount : undefined },
      { to: `/${slug}/runs`, label: 'Runs' },
      { to: `/${slug}/documents`, label: 'Documents' },
    ]
  : [{ to: '/', label: 'Dashboard', end: true }]
```

- [ ] **Step 3: Add the list route to `ui/src/router.tsx`**

Add the import at the top:
```typescript
import Stakeholders from './pages/Stakeholders'
```

Add the route inside `children` after the roadmap route:
```typescript
{ path: ':slug/stakeholders', element: <Stakeholders /> },
```

- [ ] **Step 4: Type-check**

```bash
cd /Users/pboagents/Documents/agentpool1/.worktrees/sp10a-stakeholder-registry/ui
npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 5: Commit**

```bash
cd /Users/pboagents/Documents/agentpool1/.worktrees/sp10a-stakeholder-registry
git add ui/src/pages/Stakeholders.tsx ui/src/components/AppLayout.tsx ui/src/router.tsx
git commit -m "feat: add Stakeholders list page, nav item, and route (SP10a)"
```

---

## Task 5: StakeholderForm — add/edit page

**Files:**
- Create: `ui/src/pages/StakeholderForm.tsx`
- Modify: `ui/src/router.tsx`

- [ ] **Step 1: Create `ui/src/pages/StakeholderForm.tsx`**

```tsx
// ui/src/pages/StakeholderForm.tsx
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { stakeholdersApi, projectsApi } from '../api/endpoints'
import { COUNTRY_DATA, COUNTRY_OPTIONS } from '../utils/countryData'
import type { Stakeholder } from '../types'

type FormData = Omit<Stakeholder, 'id' | 'created_at'>

const EMPTY: FormData = {
  name: '',
  job_title: '',
  organisation: '',
  email: '',
  slack_handle: '',
  stakeholder_groups: [],
  project_role: 'recipient',
  value_streams: [],
  value_chain_stage: '',
  activity: '',
  disposition: 'neutral',
  location: '',
  country_code: '',
  timezone: '',
  preferred_language: '',
  currency: '',
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-4 mt-6 first:mt-0">
      {children}
    </h3>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-xs text-slate-400 block mb-1">{label}</label>
      {children}
    </div>
  )
}

const INPUT = 'w-full bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-sky-600'
const SELECT = `${INPUT} cursor-pointer`

function MultiCheckbox({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: string[]
  value: string[]
  onChange: (v: string[]) => void
}) {
  function toggle(opt: string) {
    onChange(value.includes(opt) ? value.filter((v) => v !== opt) : [...value, opt])
  }
  return (
    <div>
      <label className="text-xs text-slate-400 block mb-2">{label}</label>
      {options.length === 0 ? (
        <p className="text-xs text-slate-600">
          None configured — add them in Settings first.
        </p>
      ) : (
        <div className="flex flex-wrap gap-x-6 gap-y-1.5">
          {options.map((opt) => (
            <label key={opt} className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={value.includes(opt)}
                onChange={() => toggle(opt)}
                className="accent-sky-500"
              />
              {opt}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

export default function StakeholderForm() {
  const { slug, id } = useParams<{ slug: string; id?: string }>()
  const navigate = useNavigate()
  const isEdit = !!id
  const [form, setForm] = useState<FormData>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Fetch settings to populate multi-select options
  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug!),
    enabled: !!slug,
  })

  // Fetch existing stakeholder when editing
  const { data: existing } = useQuery<Stakeholder[]>({
    queryKey: ['stakeholders', slug],
    queryFn: () => stakeholdersApi.list(slug!),
    enabled: !!slug && isEdit,
  })

  useEffect(() => {
    if (isEdit && existing && id) {
      const found = existing.find((s) => s.id === Number(id))
      if (found) {
        const { id: _id, created_at: _ca, ...rest } = found
        setForm(rest)
      }
    }
  }, [isEdit, existing, id])

  function set<K extends keyof FormData>(key: K, value: FormData[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function handleCountryChange(code: string) {
    const info = COUNTRY_DATA[code]
    set('country_code', code)
    if (info) {
      set('location', info.name)
      if (!form.timezone) set('timezone', info.timezone)
      if (!form.currency) set('currency', info.currency)
      if (!form.preferred_language) set('preferred_language', info.language)
    }
  }

  async function handleSave() {
    if (!form.name.trim()) {
      setError('Name is required.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      if (isEdit && id) {
        await stakeholdersApi.update(slug!, Number(id), form)
      } else {
        await stakeholdersApi.create(slug!, form)
      }
      navigate(`/${slug}/stakeholders`)
    } catch {
      setError('Save failed. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const groupOptions = settings?.stakeholder_groups ?? []
  const vsOptions = settings?.value_stream_labels ?? []

  return (
    <div className="p-6 max-w-2xl">
      <div className="mb-6">
        <button
          onClick={() => navigate(`/${slug}/stakeholders`)}
          className="text-sm text-slate-400 hover:text-slate-200 mb-2 block"
        >
          ← Back to Stakeholders
        </button>
        <h2 className="text-lg font-semibold text-slate-100">
          {isEdit ? 'Edit Stakeholder' : 'Add Stakeholder'}
        </h2>
      </div>

      <div className="space-y-4">
        {/* Identity */}
        <SectionHeading>Identity</SectionHeading>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Name *">
            <input value={form.name} onChange={(e) => set('name', e.target.value)} className={INPUT} />
          </Field>
          <Field label="Job Title">
            <input value={form.job_title} onChange={(e) => set('job_title', e.target.value)} className={INPUT} />
          </Field>
          <Field label="Organisation">
            <input value={form.organisation} onChange={(e) => set('organisation', e.target.value)} className={INPUT} />
          </Field>
        </div>

        {/* Contact */}
        <SectionHeading>Contact</SectionHeading>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Email">
            <input value={form.email} onChange={(e) => set('email', e.target.value)} className={INPUT} />
          </Field>
          <Field label="Slack Handle">
            <input value={form.slack_handle} onChange={(e) => set('slack_handle', e.target.value)} className={INPUT} placeholder="@handle" />
          </Field>
          <Field label="Preferred Language">
            <input value={form.preferred_language} onChange={(e) => set('preferred_language', e.target.value)} className={INPUT} />
          </Field>
        </div>

        {/* Project Role */}
        <SectionHeading>Project Role</SectionHeading>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Role">
            <select value={form.project_role} onChange={(e) => set('project_role', e.target.value as FormData['project_role'])} className={SELECT}>
              <option value="recipient">Recipient</option>
              <option value="governing">Governing</option>
              <option value="actor">Actor</option>
            </select>
          </Field>
          <Field label="Disposition">
            <select value={form.disposition} onChange={(e) => set('disposition', e.target.value as FormData['disposition'])} className={SELECT}>
              <option value="champion">Champion</option>
              <option value="supporter">Supporter</option>
              <option value="neutral">Neutral</option>
              <option value="skeptic">Skeptic</option>
              <option value="blocker">Blocker</option>
            </select>
          </Field>
        </div>
        <MultiCheckbox
          label="Stakeholder Groups"
          options={groupOptions}
          value={form.stakeholder_groups}
          onChange={(v) => set('stakeholder_groups', v)}
        />

        {/* Value Chain Alignment */}
        <SectionHeading>Value Chain Alignment</SectionHeading>
        <MultiCheckbox
          label="Value Streams (L1)"
          options={vsOptions}
          value={form.value_streams}
          onChange={(v) => set('value_streams', v)}
        />
        <div className="grid grid-cols-2 gap-4">
          <Field label="Value Chain Stage (L2)">
            <input value={form.value_chain_stage} onChange={(e) => set('value_chain_stage', e.target.value)} className={INPUT} placeholder="e.g. Billing" />
          </Field>
          <Field label="Activity (L3)">
            <input value={form.activity} onChange={(e) => set('activity', e.target.value)} className={INPUT} placeholder="e.g. Invoice processing" />
          </Field>
        </div>

        {/* Location */}
        <SectionHeading>Location</SectionHeading>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Country">
            <select
              value={form.country_code}
              onChange={(e) => handleCountryChange(e.target.value)}
              className={SELECT}
            >
              <option value="">— Select country —</option>
              {COUNTRY_OPTIONS.map(({ code, name }) => (
                <option key={code} value={code}>{name}</option>
              ))}
            </select>
          </Field>
          <Field label="Timezone">
            <input value={form.timezone} onChange={(e) => set('timezone', e.target.value)} className={INPUT} placeholder="e.g. Europe/London" />
          </Field>
          <Field label="Currency">
            <input value={form.currency} onChange={(e) => set('currency', e.target.value)} className={INPUT} placeholder="e.g. GBP" />
          </Field>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-8 border-t border-slate-800 pt-4 flex items-center justify-between">
        {error ? <p className="text-sm text-red-400">{error}</p> : <span />}
        <div className="flex gap-3">
          <button onClick={() => navigate(`/${slug}/stakeholders`)} className="text-sm text-slate-400 hover:text-slate-200 px-3 py-1.5">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm rounded"
          >
            {saving ? 'Saving…' : 'Save Stakeholder'}
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Add routes to `ui/src/router.tsx`**

Add the import at the top alongside the other page imports:
```typescript
import StakeholderForm from './pages/StakeholderForm'
```

Add two routes inside `children`, after `{ path: ':slug/stakeholders', element: <Stakeholders /> }`:
```typescript
{ path: ':slug/stakeholders/new', element: <StakeholderForm /> },
{ path: ':slug/stakeholders/:id/edit', element: <StakeholderForm /> },
```

- [ ] **Step 3: Type-check**

```bash
cd /Users/pboagents/Documents/agentpool1/.worktrees/sp10a-stakeholder-registry/ui
npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
cd /Users/pboagents/Documents/agentpool1/.worktrees/sp10a-stakeholder-registry
git add ui/src/pages/StakeholderForm.tsx ui/src/router.tsx
git commit -m "feat: add StakeholderForm add/edit page and routes (SP10a)"
```

---

## Self-review checklist

**Spec coverage:**
- ✅ `stakeholders` table with all 18 fields (incl. location, country_code, timezone, preferred_language, currency)
- ✅ `_migrate_stakeholders` + call in `get_connection`
- ✅ 5 DB helpers: insert, fetch_all, fetch_one, update, delete
- ✅ `stakeholder_service.py` — list, create, update, delete, import_csv
- ✅ 5 endpoints: GET list, POST create, PUT update, DELETE, POST import
- ✅ `/import` route registered before `/{stakeholder_id}` routes
- ✅ CSV import: upsert by email, semicolon multi-values, skip bad rows with errors
- ✅ `Stakeholder` + `StakeholderImportResult` types in `types.ts`
- ✅ `stakeholdersApi` in `endpoints.ts`
- ✅ `countryData.ts` with ~60 countries, country → timezone/currency/language
- ✅ `Stakeholders.tsx` list page with search, role/disposition badges, CSV import toast
- ✅ `StakeholderForm.tsx` full-page add/edit with 5 grouped sections
- ✅ Country change auto-fills timezone, currency, language (only if field empty)
- ✅ Multi-select checkboxes for stakeholder_groups and value_streams from project settings
- ✅ "Stakeholders" nav item between Roadmap and Business Plan
- ✅ Three routes: list, new, :id/edit
- ✅ 14 tests (6 DB-level + 8 API-level)

**Type consistency:** All method names in `stakeholdersApi` (`list`, `create`, `update`, `remove`, `importCsv`) match usage in `Stakeholders.tsx` and `StakeholderForm.tsx`. `Omit<Stakeholder, 'id' | 'created_at'>` used consistently in API methods and `FormData` type alias.
