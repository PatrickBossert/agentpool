# SP9d — Run History
## Design Specification
**Date:** 2026-05-09
**Status:** Approved for implementation planning
**Branch base:** `master`
**Working directory:** `/Users/pboagents/Documents/agentpool1`

---

## 1. Scope

Give the consultant a browsable history of past pipeline runs at `/:slug/runs`. Each entry shows the orchestration run status and expands inline to reveal its crew breakdown.

**In scope:**
- `ALTER TABLE crew_runs ADD COLUMN orchestration_run_id INTEGER REFERENCES orchestration_runs(id)` migration
- `insert_crew_run` updated to accept optional `orchestration_run_id`
- `RunCrewTool._arun` passes `self.orchestration_run_id` to `insert_crew_run`
- `fetch_all_orchestration_runs(conn, *, project_id)` — new DB helper (LEFT JOIN crew_runs)
- `get_run_history(slug)` — new service function
- `GET /projects/{slug}/runs` — new endpoint in `api/routers/runs.py`
- `OrchestrationRunHistory` TypeScript interface in `ui/src/types.ts`
- `projectsApi.listRuns(slug)` in `ui/src/api/endpoints.ts`
- `ui/src/pages/Runs.tsx` — new page with accordion rows
- `ui/src/components/AppLayout.tsx` — "Runs" nav item (between Reviews and Documents)
- `ui/src/router.tsx` — `/:slug/runs` route
- Backend tests in `tests/test_runs_api.py`

**Out of scope:**
- Updating `RunDetail` to show a specific historical run (it remains live-only)
- Linking `api/routers/run.py` single-crew dispatch to an orch run (no orchestration, so `orchestration_run_id` stays NULL)
- Linking `chainlit_app/app.py` crew runs to orch runs (standalone, stays NULL)
- Deleting or re-running past runs
- Pagination (show all runs, no limit)

---

## 2. Background: How runs flow today

```
POST /orchestrate
  → insert_orchestration_run (id=N)
  → asyncio.create_task(run_pam_crew(slug, N))
       → create_pam_crew(slug, orchestration_run_id=N)
            → RunCrewTool(slug=slug, orchestration_run_id=N)
                 → insert_crew_run(project_id, crew_name, status)  ← no FK today
```

`RunCrewTool` already holds `orchestration_run_id` as a Pydantic field. It just doesn't pass it to `insert_crew_run`. The fix is one line in `_arun`.

Crew runs inserted by `api/routers/run.py` (single crew dispatch) or `chainlit_app/app.py` have no parent orchestration run — `orchestration_run_id` stays `NULL` and they are excluded from the history view.

---

## 3. Backend Changes

### 3.1 `api/database.py` — migration

In `init_db`, after the existing `human_reviews` migration block, add:

```python
# SP9d: orchestration_run_id FK on crew_runs
crew_cols = [row[1] async for row in await conn.execute("PRAGMA table_info(crew_runs)")]
if "orchestration_run_id" not in crew_cols:
    await conn.execute(
        "ALTER TABLE crew_runs ADD COLUMN orchestration_run_id INTEGER REFERENCES orchestration_runs(id)"
    )
    await conn.commit()
```

### 3.2 `api/database.py` — `insert_crew_run`

Add optional keyword argument `orchestration_run_id: int | None = None`:

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

All existing call sites pass no `orchestration_run_id` — they default to `None` (NULL). No other changes needed.

### 3.3 `agents/tools/run_crew.py` — `_arun`

Pass `orchestration_run_id=self.orchestration_run_id` to `insert_crew_run`:

```python
run_id = await insert_crew_run(
    conn,
    project_id=project["id"],
    crew_name=crew_name,
    status="running",
    orchestration_run_id=self.orchestration_run_id,
)
```

### 3.4 `api/database.py` — `fetch_all_orchestration_runs`

New helper returning every orchestration run for a project with a summary of its linked crew_runs:

```python
async def fetch_all_orchestration_runs(
    conn: aiosqlite.Connection, *, project_id: int
) -> list[dict]:
    """Return all orchestration_runs for a project (newest first) with crew summaries."""
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

    # Group crew_runs per orchestration run, preserving order
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

### 3.5 `api/services/project_service.py` — `get_run_history`

```python
from api.database import fetch_all_orchestration_runs   # add to imports

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

### 3.6 `api/routers/runs.py` — new file

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

Register in `api/main.py` alongside the other routers:
```python
from api.routers.runs import router as runs_router
app.include_router(runs_router)
```

### 3.7 Testing — `tests/test_runs_api.py`

Four tests following the pattern from `tests/test_reviews_api.py`:

1. **`test_list_runs_empty`** — project exists, no orchestration runs → `GET /projects/{slug}/runs` returns `[]`
2. **`test_list_runs_returns_history`** — insert orchestration run + 2 crew_runs with `orchestration_run_id` set → response contains 1 item with `crew_runs` list of 2
3. **`test_list_runs_excludes_unlinked_crew_runs`** — insert orch run + crew run with `orchestration_run_id=NULL` → crew_runs list is empty (the orphan is excluded)
4. **`test_list_runs_unknown_project_404`** — unknown slug → 404

---

## 4. Frontend Changes

### 4.1 `ui/src/types.ts`

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

### 4.2 `ui/src/api/endpoints.ts`

Add to `projectsApi`:

```typescript
listRuns: (slug: string): Promise<OrchestrationRunHistory[]> =>
  apiClient.get<OrchestrationRunHistory[]>(`/projects/${slug}/runs`).then((r) => r.data),
```

Import `OrchestrationRunHistory` in the import block.

### 4.3 `ui/src/pages/Runs.tsx` — new file

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
      {/* Summary row */}
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

      {/* Expanded crew breakdown */}
      {open && (
        <div className="border-t border-slate-800 px-4 py-3 space-y-1.5">
          {run.crew_runs.length === 0 ? (
            <p className="text-xs text-slate-500">No crew runs linked to this orchestration run.</p>
          ) : (
            run.crew_runs.map((cr) => (
              <div
                key={cr.crew_name}
                className="flex items-center justify-between py-1"
              >
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

**Polling:** `refetchInterval` polls every 5 s only while any run has `status === 'running'`; stops once all runs are terminal.

### 4.4 `ui/src/components/AppLayout.tsx`

Add to `navItems` between Reviews and Documents:

```typescript
{ to: `/${slug}/runs`, label: 'Runs' },
```

### 4.5 `ui/src/router.tsx`

```typescript
import Runs from './pages/Runs'

// inside children after reviews:
{ path: ':slug/runs', element: <Runs /> },
```

---

## 5. Notes

- `fetch_all_orchestration_runs` uses a LEFT JOIN — orch runs with no linked crew_runs still appear (with `crew_runs: []`).
- The `ORDER BY o.started_at DESC, cr.id ASC` ensures newest orch run first, crew rows in insertion order within each run.
- Grouping in Python (dict keyed by `o.id`) is safe because SQLite returns rows ordered by orch run (DESC), meaning we won't revisit a completed orch-run key after moving to a newer one.
- `StatusBadge` is already a shared component — no new component needed.
- The accordion uses local `open` state per row (not a URL param) — simple, no persistence required.
- `OrchestrationRunHistory` is distinct from the existing `OrchestrationRun` interface (which has no `crew_runs` field) — both coexist in `types.ts`.
- `api/routers/run.py` single-crew dispatch and `chainlit_app/app.py` continue to call `insert_crew_run` without `orchestration_run_id` — they default to `None` and are excluded from history by the JOIN condition.
