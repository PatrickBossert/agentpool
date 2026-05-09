# SP9d Run History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/:slug/runs` page showing all past orchestration runs with inline accordion crew breakdown, backed by a new `orchestration_run_id` FK on `crew_runs` and a `GET /projects/{slug}/runs` endpoint.

**Architecture:** Three layered tasks — (1) DB migration + `insert_crew_run` update + `RunCrewTool` fix, (2) `fetch_all_orchestration_runs` helper + service + endpoint + router registration + API tests, (3) all frontend (types, API method, Runs page, nav item, route). Each task is independently committable.

**Tech Stack:** Python 3.12 / aiosqlite / FastAPI (backend); React 18 / TypeScript / TanStack Query v5 / Tailwind CSS (frontend)

---

## Context for the implementer

**Working directory:** `/Users/pboagents/Documents/agentpool1`

Key existing files to understand before starting:
- `api/database.py` — all DB helpers. Migration pattern: `_migrate_human_reviews` is called from `get_connection` (line 129). Follow the same pattern.
- `api/database.py:157` — `insert_crew_run(conn, *, project_id, crew_name, status)` — returns `int`
- `agents/tools/run_crew.py` — `RunCrewTool` already has `orchestration_run_id: int` as a Pydantic field but doesn't pass it to `insert_crew_run` yet
- `api/services/project_service.py` — service layer. `get_pending_reviews` is the pattern to follow.
- `api/routers/reviews.py` — router pattern to follow for the new runs router
- `api/main.py:7-11,32-39` — how routers are imported and registered
- `tests/test_reviews_api.py` — the exact test pattern to follow (fixture, async helpers, client)
- `ui/src/components/AppLayout.tsx:37-46` — navItems array where "Runs" must be inserted
- `ui/src/router.tsx` — where the route is added
- `ui/src/components/StatusBadge.tsx` — reusable status badge, already imported in RunDetail

---

### Task 1: DB migration + `insert_crew_run` update + `RunCrewTool` fix

**Files:**
- Modify: `api/database.py`
- Modify: `agents/tools/run_crew.py`

- [ ] **Step 1: Add `_migrate_crew_runs` function to `api/database.py`**

After the `_migrate_human_reviews` function (around line 119), add:

```python
async def _migrate_crew_runs(conn: aiosqlite.Connection) -> None:
    """Add orchestration_run_id FK column to crew_runs on existing DBs."""
    async with conn.execute("PRAGMA table_info(crew_runs)") as cur:
        cols = [row["name"] async for row in cur]
    if "orchestration_run_id" not in cols:
        await conn.execute(
            "ALTER TABLE crew_runs ADD COLUMN orchestration_run_id INTEGER REFERENCES orchestration_runs(id)"
        )
        await conn.commit()
```

- [ ] **Step 2: Call `_migrate_crew_runs` from `get_connection`**

In `get_connection` (around line 121), after `await _migrate_human_reviews(conn)`, add:

```python
await _migrate_crew_runs(conn)
```

The updated `get_connection` body becomes:
```python
@asynccontextmanager
async def get_connection(slug: str):
    path = get_db_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await init_db(conn)
        await _migrate_human_reviews(conn)
        await _migrate_crew_runs(conn)
        yield conn
```

- [ ] **Step 3: Update `insert_crew_run` to accept `orchestration_run_id`**

Replace the existing `insert_crew_run` function (lines 157–163):

```python
async def insert_crew_run(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    crew_name: str,
    status: str,
    orchestration_run_id: int | None = None,
) -> int:
    cur = await conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status, started_at, orchestration_run_id) "
        "VALUES (?,?,?, CURRENT_TIMESTAMP, ?)",
        (project_id, crew_name, status, orchestration_run_id),
    )
    await conn.commit()
    return cur.lastrowid
```

- [ ] **Step 4: Update `RunCrewTool._arun` to pass `orchestration_run_id`**

In `agents/tools/run_crew.py`, replace the `insert_crew_run` call (lines 31–33):

```python
run_id = await insert_crew_run(
    conn,
    project_id=project["id"],
    crew_name=crew_name,
    status="running",
    orchestration_run_id=self.orchestration_run_id,
)
```

- [ ] **Step 5: Verify existing tests still pass**

```bash
cd /Users/pboagents/Documents/agentpool1
python3 -m pytest tests/test_database.py tests/test_reviews_api.py -v --tb=short 2>&1 | tail -20
```

Expected: all tests pass. `insert_crew_run` callers that don't pass `orchestration_run_id` default to `None` — backward-compatible.

- [ ] **Step 6: Commit**

```bash
git add api/database.py agents/tools/run_crew.py
git commit -m "feat: add orchestration_run_id FK to crew_runs + wire RunCrewTool (SP9d)"
```

---

### Task 2: `fetch_all_orchestration_runs` + service + endpoint + router registration + tests

**Files:**
- Modify: `api/database.py`
- Modify: `api/services/project_service.py`
- Create: `api/routers/runs.py`
- Modify: `api/main.py`
- Create: `tests/test_runs_api.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_runs_api.py`:

```python
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import (
    get_connection,
    fetch_project,
    insert_crew_run,
)

SLUG = "runs-test"
PROJECT = {"client_slug": SLUG, "llm_mode": "standard", "sector": "rail"}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _insert_orchestration_run(status: str = "completed") -> int:
    """Insert an orchestration_run row directly and return its id."""
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        assert project is not None
        cur = await conn.execute(
            "INSERT INTO orchestration_runs (project_id, status) VALUES (?, ?)",
            (project["id"], status),
        )
        await conn.commit()
        return cur.lastrowid


@pytest.mark.asyncio
async def test_list_runs_empty(client):
    client.post("/projects", json=PROJECT)
    resp = client.get(f"/projects/{SLUG}/runs")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_runs_returns_history(client):
    client.post("/projects", json=PROJECT)
    orch_id = await _insert_orchestration_run()
    # Insert two crew_runs linked to this orchestration run
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        assert project is not None
        await insert_crew_run(
            conn,
            project_id=project["id"],
            crew_name="discovery",
            status="completed",
            orchestration_run_id=orch_id,
        )
        await insert_crew_run(
            conn,
            project_id=project["id"],
            crew_name="value_design",
            status="completed",
            orchestration_run_id=orch_id,
        )

    resp = client.get(f"/projects/{SLUG}/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == orch_id
    assert data[0]["status"] == "completed"
    crew_names = [cr["crew_name"] for cr in data[0]["crew_runs"]]
    assert "discovery" in crew_names
    assert "value_design" in crew_names


@pytest.mark.asyncio
async def test_list_runs_excludes_unlinked_crew_runs(client):
    client.post("/projects", json=PROJECT)
    orch_id = await _insert_orchestration_run()
    # Crew run with no orchestration_run_id (NULL)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        assert project is not None
        await insert_crew_run(
            conn,
            project_id=project["id"],
            crew_name="orphan",
            status="completed",
            # no orchestration_run_id → NULL
        )

    resp = client.get(f"/projects/{SLUG}/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["crew_runs"] == []


@pytest.mark.asyncio
async def test_list_runs_unknown_project_404(client):
    resp = client.get("/projects/no-such-slug/runs")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_runs_api.py -v --tb=short 2>&1 | tail -20
```

Expected: FAIL — `404` or import errors because the endpoint doesn't exist yet.

- [ ] **Step 3: Add `fetch_all_orchestration_runs` to `api/database.py`**

After `fetch_latest_orchestration_run` (around line 183), add:

```python
async def fetch_all_orchestration_runs(
    conn: aiosqlite.Connection, *, project_id: int
) -> list[dict]:
    """Return all orchestration_runs for a project (newest first) with crew summaries.

    Uses LEFT JOIN so orch runs with no linked crew_runs still appear (crew_runs=[]).
    Crew runs with orchestration_run_id IS NULL are excluded by the JOIN condition.
    """
    async with conn.execute(
        """
        SELECT
            o.id,
            o.status,
            o.started_at,
            o.completed_at,
            cr.crew_name,
            cr.status AS crew_status
        FROM orchestration_runs o
        LEFT JOIN crew_runs cr ON cr.orchestration_run_id = o.id
        WHERE o.project_id = ?
        ORDER BY o.started_at DESC, cr.id ASC
        """,
        (project_id,),
    ) as cur:
        rows = await cur.fetchall()

    # Group crew_runs per orchestration run, preserving DESC order of orch runs
    runs: dict[int, dict] = {}
    for row in rows:
        r = dict(row)
        oid = r["id"]
        if oid not in runs:
            runs[oid] = {
                "id": oid,
                "status": r["status"],
                "started_at": r["started_at"],
                "completed_at": r["completed_at"],
                "crew_runs": [],
            }
        if r["crew_name"] is not None:
            runs[oid]["crew_runs"].append(
                {"crew_name": r["crew_name"], "status": r["crew_status"]}
            )
    return list(runs.values())
```

- [ ] **Step 4: Add `get_run_history` to `api/services/project_service.py`**

Add `fetch_all_orchestration_runs` to the import from `api.database` at the top of the file:

```python
from api.database import (
    fetch_project,
    fetch_crew_runs,
    fetch_latest_orchestration_run,
    fetch_agent_outputs,
    list_projects,
    fetch_pending_reviews,
    fetch_all_orchestration_runs,   # ← add this
)
```

Then add the service function at the end of the file:

```python
async def get_run_history(slug: str) -> list[dict] | None:
    """Return all orchestration runs with crew summaries. None = project not found."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await fetch_all_orchestration_runs(conn, project_id=project["id"])
```

- [ ] **Step 5: Create `api/routers/runs.py`**

```python
# api/routers/runs.py
"""GET /projects/{slug}/runs — list orchestration run history."""
from fastapi import APIRouter, HTTPException
from api.services.project_service import get_run_history

router = APIRouter(prefix="/projects", tags=["runs"])


@router.get("/{slug}/runs")
async def list_runs(slug: str):
    result = await get_run_history(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result
```

- [ ] **Step 6: Register the router in `api/main.py`**

Add the import after the existing router imports (around line 11):

```python
from api.routers import runs as runs_router
```

Add the `include_router` call after the existing ones (around line 39):

```python
app.include_router(runs_router.router)
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_runs_api.py -v --tb=short 2>&1 | tail -20
```

Expected: 4 tests pass.

- [ ] **Step 8: Run the full API test suite to check for regressions**

```bash
python3 -m pytest tests/test_runs_api.py tests/test_reviews_api.py tests/test_business_plan_api.py tests/test_projects_api.py tests/test_database.py -v --tb=short 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add api/database.py api/services/project_service.py api/routers/runs.py api/main.py tests/test_runs_api.py
git commit -m "feat: add GET /projects/{slug}/runs endpoint + fetch_all_orchestration_runs (SP9d)"
```

---

### Task 3: Frontend — types, API method, Runs page, nav item, route

**Files:**
- Modify: `ui/src/types.ts`
- Modify: `ui/src/api/endpoints.ts`
- Create: `ui/src/pages/Runs.tsx`
- Modify: `ui/src/components/AppLayout.tsx`
- Modify: `ui/src/router.tsx`

- [ ] **Step 1: Add interfaces to `ui/src/types.ts`**

At the end of the file, after `FinancialSummary`, add:

```typescript
export interface RunCrewSummary {
  crew_name: string
  status: string
}

export interface OrchestrationRunHistory {
  id: number
  status: string
  started_at: string | null
  completed_at: string | null
  crew_runs: RunCrewSummary[]
}
```

- [ ] **Step 2: Add `listRuns` to `ui/src/api/endpoints.ts`**

Add `OrchestrationRunHistory` to the import from `../types`:

```typescript
import type { ..., OrchestrationRunHistory } from '../types'
```

Add to `projectsApi` (after `listReviews`):

```typescript
listRuns: (slug: string): Promise<OrchestrationRunHistory[]> =>
  apiClient.get<OrchestrationRunHistory[]>(`/projects/${slug}/runs`).then((r) => r.data),
```

- [ ] **Step 3: Create `ui/src/pages/Runs.tsx`**

```tsx
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import StatusBadge from '../components/StatusBadge'
import type { OrchestrationRunHistory } from '../types'

function formatDuration(started: string | null, completed: string | null): string {
  if (!started || !completed) return '—'
  const ms = new Date(completed).getTime() - new Date(started).getTime()
  const mins = Math.floor(ms / 60000)
  const secs = Math.floor((ms % 60000) / 1000)
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`
}

function RunRow({ run }: { run: OrchestrationRunHistory }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="bg-surface-card rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-slate-200">Run #{run.id}</span>
          <StatusBadge status={run.status} />
          {run.crew_runs.length > 0 && (
            <span className="text-xs text-slate-500">
              {run.crew_runs.length} crew{run.crew_runs.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-500">
            {run.started_at ? new Date(run.started_at).toLocaleString() : '—'}
          </span>
          <span className="text-xs text-slate-500">
            {formatDuration(run.started_at, run.completed_at)}
          </span>
          <span className="text-slate-500 text-xs">{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div className="border-t border-slate-800 px-4 py-3 space-y-1.5">
          {run.crew_runs.length === 0 ? (
            <p className="text-xs text-slate-500">No crew runs linked to this orchestration run.</p>
          ) : (
            run.crew_runs.map((cr) => (
              <div key={cr.crew_name} className="flex items-center justify-between py-1">
                <span className="text-xs text-slate-300">{cr.crew_name}</span>
                <StatusBadge status={cr.status} />
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}

export default function Runs() {
  const { slug } = useParams<{ slug: string }>()

  const { data: runs = [], isLoading } = useQuery({
    queryKey: ['runs', slug],
    queryFn: () => projectsApi.listRuns(slug!),
    enabled: !!slug,
    refetchInterval: (query) => {
      const hasRunning = query.state.data?.some((r) => r.status === 'running')
      return hasRunning ? 5000 : false
    },
  })

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-slate-100">Run History</h2>
      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {!isLoading && runs.length === 0 && (
        <p className="text-sm text-slate-500">No pipeline runs yet.</p>
      )}
      <div className="space-y-3">
        {runs.map((run) => (
          <RunRow key={run.id} run={run} />
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Add "Runs" nav item to `ui/src/components/AppLayout.tsx`**

In the `navItems` array (around line 43), add between the Reviews and Documents entries:

```typescript
// Before:
{ to: `/${slug}/reviews`, label: 'Reviews', badge: pendingReviewCount > 0 ? pendingReviewCount : undefined },
{ to: `/${slug}/documents`, label: 'Documents' },

// After:
{ to: `/${slug}/reviews`, label: 'Reviews', badge: pendingReviewCount > 0 ? pendingReviewCount : undefined },
{ to: `/${slug}/runs`, label: 'Runs' },
{ to: `/${slug}/documents`, label: 'Documents' },
```

- [ ] **Step 5: Add route to `ui/src/router.tsx`**

Read `ui/src/router.tsx` to find where `:slug/reviews` is defined, then add after it:

```typescript
import Runs from './pages/Runs'

// inside children, after the reviews route:
{ path: ':slug/runs', element: <Runs /> },
```

- [ ] **Step 6: TypeScript check**

```bash
cd /Users/pboagents/Documents/agentpool1/ui && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd /Users/pboagents/Documents/agentpool1
git add ui/src/types.ts ui/src/api/endpoints.ts ui/src/pages/Runs.tsx ui/src/components/AppLayout.tsx ui/src/router.tsx
git commit -m "feat: add Run History page at /:slug/runs (SP9d)"
```
