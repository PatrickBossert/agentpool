# SP10a — Stakeholder Registry
## Design Specification
**Date:** 2026-05-09
**Status:** Approved for implementation planning
**Branch base:** `master`
**Working directory:** `/Users/pboagents/Documents/agentpool1`

---

## 1. Scope

Add a full stakeholder registry to each project: a browsable, searchable table of stakeholders with rich attribution, a full-page add/edit form, and CSV bulk import. This is the data foundation for SP10b (StakeholderContextTool) and SP10c (outbound comms).

**In scope:**
- `stakeholders` table migration (per-project SQLite DB)
- DB helpers: `insert_stakeholder`, `update_stakeholder`, `delete_stakeholder`, `fetch_stakeholders`, `fetch_stakeholder`
- `api/services/stakeholder_service.py` — thin service layer
- `api/routers/stakeholders.py` — 5 endpoints (list, create, update, delete, CSV import)
- Register router in `api/main.py`
- `ui/src/types.ts` — `Stakeholder` and `StakeholderImportResult` interfaces
- `ui/src/api/endpoints.ts` — `stakeholdersApi` object
- `ui/src/pages/Stakeholders.tsx` — list page with search, add button, CSV import
- `ui/src/pages/StakeholderForm.tsx` — shared add/edit full-page form
- `ui/src/utils/countryData.ts` — static mapping of country code → timezone, currency, language
- `AppLayout.tsx` — "Stakeholders" nav item (between Roadmap and Business Plan)
- `ui/src/router.tsx` — three new routes
- `tests/test_stakeholders_api.py` — 8 tests

**Out of scope:**
- StakeholderContextTool (SP10b)
- Outbound/inbound comms (SP10c, SP10d)
- Linking stakeholders to specific crew run outputs
- Stakeholder export to CSV (can add later)
- Soft delete / archive (hard delete only for now)

---

## 2. Data Model

### 2.1 `stakeholders` table (per-project DB)

```sql
CREATE TABLE IF NOT EXISTS stakeholders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    job_title       TEXT NOT NULL DEFAULT '',
    organisation    TEXT NOT NULL DEFAULT '',
    email           TEXT NOT NULL DEFAULT '',
    slack_handle    TEXT NOT NULL DEFAULT '',
    stakeholder_groups  TEXT NOT NULL DEFAULT '[]',  -- JSON array of strings
    project_role    TEXT NOT NULL DEFAULT 'recipient',  -- recipient | governing | actor
    value_streams   TEXT NOT NULL DEFAULT '[]',  -- JSON array of L1 label strings
    value_chain_stage   TEXT NOT NULL DEFAULT '',  -- L2 free text
    activity        TEXT NOT NULL DEFAULT '',  -- L3 free text
    disposition     TEXT NOT NULL DEFAULT 'neutral',  -- champion|supporter|neutral|skeptic|blocker
    location        TEXT NOT NULL DEFAULT '',  -- country display name
    country_code    TEXT NOT NULL DEFAULT '',  -- ISO 3166-1 alpha-2
    timezone        TEXT NOT NULL DEFAULT '',  -- IANA tz string e.g. "Europe/London"
    preferred_language  TEXT NOT NULL DEFAULT '',
    currency        TEXT NOT NULL DEFAULT '',  -- ISO 4217 e.g. "GBP"
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
```

Multi-value fields (`stakeholder_groups`, `value_streams`) stored as JSON arrays. Consistent with how project config stores arrays.

`email` is used as the upsert key during CSV import (duplicate email → update existing row).

### 2.2 Migration

Add `_migrate_stakeholders(conn)` in `api/database.py`, called from `get_connection` alongside `_migrate_human_reviews` and `_migrate_crew_runs`:

```python
async def _migrate_stakeholders(conn: aiosqlite.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS stakeholders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            job_title       TEXT NOT NULL DEFAULT '',
            organisation    TEXT NOT NULL DEFAULT '',
            email           TEXT NOT NULL DEFAULT '',
            slack_handle    TEXT NOT NULL DEFAULT '',
            stakeholder_groups  TEXT NOT NULL DEFAULT '[]',
            project_role    TEXT NOT NULL DEFAULT 'recipient',
            value_streams   TEXT NOT NULL DEFAULT '[]',
            value_chain_stage   TEXT NOT NULL DEFAULT '',
            activity        TEXT NOT NULL DEFAULT '',
            disposition     TEXT NOT NULL DEFAULT 'neutral',
            location        TEXT NOT NULL DEFAULT '',
            country_code    TEXT NOT NULL DEFAULT '',
            timezone        TEXT NOT NULL DEFAULT '',
            preferred_language  TEXT NOT NULL DEFAULT '',
            currency        TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()
```

---

## 3. Backend Changes

### 3.1 `api/database.py` — DB helpers

```python
async def insert_stakeholder(conn, *, project_id: int, **fields) -> int:
    """Insert a stakeholder. fields maps to column names. Returns new id."""

async def update_stakeholder(conn, *, stakeholder_id: int, **fields) -> bool:
    """Update stakeholder by id. Returns False if not found."""

async def delete_stakeholder(conn, *, stakeholder_id: int) -> bool:
    """Hard delete. Returns False if not found."""

async def fetch_stakeholders(conn, *, project_id: int) -> list[dict]:
    """Return all stakeholders for a project, ordered by name ASC."""

async def fetch_stakeholder(conn, *, stakeholder_id: int, project_id: int) -> dict | None:
    """Return one stakeholder, None if not found or belongs to different project."""
```

JSON fields (`stakeholder_groups`, `value_streams`) are stored as JSON strings in SQLite. Helpers serialize on write (`json.dumps`) and deserialize on read (`json.loads`) so callers always see Python lists.

### 3.2 `api/services/stakeholder_service.py`

```python
from api.database import (
    fetch_stakeholders, fetch_stakeholder,
    insert_stakeholder, update_stakeholder, delete_stakeholder,
    fetch_project, get_connection,
)
from api.database import get_db_path

async def list_stakeholders(slug: str) -> list[dict] | None:
    """None = project not found."""

async def get_stakeholder(slug: str, stakeholder_id: int) -> dict | None:
    """None = not found."""

async def create_stakeholder(slug: str, data: dict) -> dict | None:
    """None = project not found. Returns created stakeholder."""

async def update_stakeholder_svc(slug: str, stakeholder_id: int, data: dict) -> dict | None:
    """None = not found."""

async def delete_stakeholder_svc(slug: str, stakeholder_id: int) -> bool:
    """False = not found."""

async def import_csv(slug: str, content: str) -> dict:
    """
    Parse CSV content, upsert rows by email.
    Returns {"created": N, "updated": M, "errors": [{"row": N, "reason": "..."}]}
    Errors skip that row and continue (non-aborting).
    """
```

### 3.3 `api/routers/stakeholders.py`

```python
# api/routers/stakeholders.py
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from api.services.stakeholder_service import (
    list_stakeholders, get_stakeholder, create_stakeholder,
    update_stakeholder_svc, delete_stakeholder_svc, import_csv,
)

router = APIRouter(prefix="/projects", tags=["stakeholders"])


class StakeholderIn(BaseModel):
    name: str
    job_title: str = ''
    organisation: str = ''
    email: str = ''
    slack_handle: str = ''
    stakeholder_groups: list[str] = []
    project_role: str = 'recipient'  # recipient | governing | actor
    value_streams: list[str] = []
    value_chain_stage: str = ''
    activity: str = ''
    disposition: str = 'neutral'  # champion|supporter|neutral|skeptic|blocker
    location: str = ''
    country_code: str = ''
    timezone: str = ''
    preferred_language: str = ''
    currency: str = ''


@router.get("/{slug}/stakeholders")
async def list_stakeholders_endpoint(slug: str): ...

@router.post("/{slug}/stakeholders", status_code=201)
async def create_stakeholder_endpoint(slug: str, body: StakeholderIn): ...

@router.put("/{slug}/stakeholders/{stakeholder_id}")
async def update_stakeholder_endpoint(slug: str, stakeholder_id: int, body: StakeholderIn): ...

@router.delete("/{slug}/stakeholders/{stakeholder_id}", status_code=204)
async def delete_stakeholder_endpoint(slug: str, stakeholder_id: int): ...

@router.post("/{slug}/stakeholders/import")
async def import_stakeholders(slug: str, file: UploadFile = File(...)): ...
```

Register in `api/main.py`:
```python
from api.routers import stakeholders as stakeholders_router
app.include_router(stakeholders_router.router)
```

### 3.4 CSV import format

Expected columns (case-insensitive header matching, extras ignored):

```
name, job_title, organisation, email, slack_handle,
stakeholder_groups, project_role, value_streams,
value_chain_stage, activity, disposition,
location, country_code, timezone, preferred_language, currency
```

`stakeholder_groups` and `value_streams` columns: semicolon-separated values in a single cell, e.g. `"Customer Onboarding;Operations"`.

Upsert key: `email`. If email is blank, always insert (no upsert possible).

### 3.5 Testing — `tests/test_stakeholders_api.py`

Eight tests following the pattern from `tests/test_runs_api.py`:

1. `test_list_stakeholders_empty` — project exists, no stakeholders → `[]`
2. `test_create_stakeholder` — POST creates, GET returns it with all fields
3. `test_update_stakeholder` — PUT updates name/disposition, reflected on GET
4. `test_delete_stakeholder` — DELETE removes, subsequent GET returns `[]`
5. `test_stakeholder_404_unknown_project` — unknown slug → 404
6. `test_stakeholder_404_unknown_id` — known project, bad id → 404
7. `test_import_csv_creates_and_updates` — import CSV with 2 new rows + 1 duplicate email → `{"created":2,"updated":1,"errors":[]}`
8. `test_import_csv_skips_bad_rows` — row with invalid disposition value → `{"created":1,"updated":0,"errors":[{"row":2,"reason":"..."}]}`

---

## 4. Frontend Changes

### 4.1 `ui/src/utils/countryData.ts`

Static mapping used by the form to auto-fill timezone, currency, and suggested language when the consultant selects a country. Format:

```typescript
export interface CountryInfo {
  name: string          // display name e.g. "United Kingdom"
  timezone: string      // primary IANA tz e.g. "Europe/London"
  currency: string      // ISO 4217 e.g. "GBP"
  language: string      // primary language e.g. "English"
}

export const COUNTRY_DATA: Record<string, CountryInfo> = {
  GB: { name: 'United Kingdom', timezone: 'Europe/London', currency: 'GBP', language: 'English' },
  US: { name: 'United States', timezone: 'America/New_York', currency: 'USD', language: 'English' },
  AU: { name: 'Australia', timezone: 'Australia/Sydney', currency: 'AUD', language: 'English' },
  // ... ~60 most common business countries
}

export const COUNTRY_OPTIONS = Object.entries(COUNTRY_DATA)
  .map(([code, info]) => ({ code, name: info.name }))
  .sort((a, b) => a.name.localeCompare(b.name))
```

For countries with multiple timezones (US, AU, CN, etc.), the mapping uses the most populous/business-common zone as the default (auto-fillable, overridable by the consultant).

### 4.2 `ui/src/types.ts`

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

### 4.3 `ui/src/api/endpoints.ts`

Add `stakeholdersApi` object:

```typescript
export const stakeholdersApi = {
  list: (slug: string): Promise<Stakeholder[]> =>
    apiClient.get<Stakeholder[]>(`/projects/${slug}/stakeholders`).then(r => r.data),

  create: (slug: string, data: Omit<Stakeholder, 'id' | 'created_at'>): Promise<Stakeholder> =>
    apiClient.post<Stakeholder>(`/projects/${slug}/stakeholders`, data).then(r => r.data),

  update: (slug: string, id: number, data: Omit<Stakeholder, 'id' | 'created_at'>): Promise<Stakeholder> =>
    apiClient.put<Stakeholder>(`/projects/${slug}/stakeholders/${id}`, data).then(r => r.data),

  delete: (slug: string, id: number): Promise<void> =>
    apiClient.delete(`/projects/${slug}/stakeholders/${id}`).then(() => undefined),

  importCsv: (slug: string, file: File): Promise<StakeholderImportResult> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<StakeholderImportResult>(`/projects/${slug}/stakeholders/import`, form).then(r => r.data)
  },
}
```

Import `Stakeholder` and `StakeholderImportResult` in the import block.

### 4.4 `ui/src/pages/Stakeholders.tsx`

List page at `/:slug/stakeholders`. Features:
- Search box — client-side filter on name, organisation, email (case-insensitive)
- Table columns: Name + Job Title, Organisation, Role badge, Disposition badge, Value Streams (comma-joined, truncated), Email, Edit link
- "Add Stakeholder" button → navigates to `/:slug/stakeholders/new`
- "Import CSV" button → hidden `<input type="file" accept=".csv">`, on change calls `stakeholdersApi.importCsv`, shows result toast: "Imported: 5 created, 2 updated" or lists errors
- Empty state: "No stakeholders yet. Add one or import a CSV."
- No server-side pagination — fetch all, filter client-side

Role badge colours: `actor` → sky, `governing` → amber, `recipient` → slate.
Disposition badge colours: `champion` → emerald, `supporter` → teal, `neutral` → slate, `skeptic` → orange, `blocker` → red.

### 4.5 `ui/src/pages/StakeholderForm.tsx`

Full-page form at `/:slug/stakeholders/new` and `/:slug/stakeholders/:id/edit`.

Back link: `← Back to Stakeholders`.

Sections (visually separated with headings):

**Identity**
- Name (required)
- Job Title
- Organisation

**Contact**
- Email
- Slack Handle
- Preferred Language (text input, pre-filled by country selection)

**Project Role**
- Project Role (select: recipient | governing | actor)
- Stakeholder Groups (multi-select checkboxes from project's `stakeholder_groups` setting — fetched via `projectsApi.getSettings`)
- Disposition (select: champion | supporter | neutral | skeptic | blocker)

**Value Chain Alignment**
- Value Streams (multi-select checkboxes from project's `value_stream_labels` setting)
- Value Chain Stage — L2 (text input)
- Activity — L3 (text input)

**Location**
- Country (searchable select from `COUNTRY_OPTIONS`)
- Timezone (text input, auto-filled on country change, editable)
- Currency (text input, auto-filled on country change, editable)

On country change:
```typescript
const info = COUNTRY_DATA[countryCode]
if (info) {
  setForm(f => ({
    ...f,
    location: info.name,
    timezone: f.timezone || info.timezone,     // don't override if already set
    currency: f.currency || info.currency,
    preferred_language: f.preferred_language || info.language,
  }))
}
```

Footer: Save button + Cancel (navigates back to list).

On save: calls `stakeholdersApi.create` or `stakeholdersApi.update`, then navigates to `/:slug/stakeholders`.

### 4.6 `ui/src/components/AppLayout.tsx`

Add to `navItems` between Roadmap and Business Plan:

```typescript
{ to: `/${slug}/stakeholders`, label: 'Stakeholders' },
```

### 4.7 `ui/src/router.tsx`

```typescript
import Stakeholders from './pages/Stakeholders'
import StakeholderForm from './pages/StakeholderForm'

// inside children:
{ path: ':slug/stakeholders', element: <Stakeholders /> },
{ path: ':slug/stakeholders/new', element: <StakeholderForm /> },
{ path: ':slug/stakeholders/:id/edit', element: <StakeholderForm /> },
```

---

## 5. Notes

- JSON array fields: helpers call `json.dumps` on write and `json.loads` on read. Callers (service, router) always work with Python lists / TypeScript arrays — never raw JSON strings.
- `fetch_stakeholder` checks both `id` and `project_id` to prevent cross-project access.
- CSV import: semicolon-separated values in `stakeholder_groups` and `value_streams` cells (commas conflict with CSV field delimiters).
- Country → timezone default uses the most common business timezone for multi-timezone countries. The field remains editable so consultants can correct it.
- `StakeholderForm` fetches project settings to populate the `stakeholder_groups` and `value_streams` multi-select options — uses the existing `projectsApi.getSettings` call.
- The `/:slug/stakeholders/import` route and `/:slug/stakeholders/:id/edit` route must be ordered carefully in FastAPI to avoid `/import` being matched as an integer `stakeholder_id`. Register the import route before the `{stakeholder_id}` routes.
- CORS: the running dev server is on port 3002. `api/main.py` already updated to allow this origin.
