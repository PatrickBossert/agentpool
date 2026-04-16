# SP6a — UI: Project Creation + Pipeline Orchestration
## Design Specification
**Date:** 2026-04-17
**Status:** Approved for implementation planning
**Branch base:** `master` (post SP5a)
**Working directory:** `/Users/pboagents/Documents/agentpool1`

---

## 1. Scope

Wire two missing user journeys into the existing React UI:

1. **Create a project** — minimal form (slug, sector, LLM mode) that calls `POST /projects`
2. **Run the PAM pipeline** — "Run Pipeline" button on the Dashboard that calls `POST /projects/{slug}/orchestrate`, shows run status inline, and navigates to a dedicated Run Detail page

**In scope:**
- `api/models.py` — defaults on `ProjectCreate`; `latest_orchestration_run` field on `StatusResponse`
- `api/database.py` — `fetch_latest_orchestration_run` helper
- `api/services/project_service.py` — extend `get_project_status`
- `ui/src/types.ts` — `OrchestrationRun` type, extend `ProjectStatus`
- `ui/src/api/endpoints.ts` — `orchestrate(slug)` function
- `ui/src/components/AppLayout.tsx` — "New Project" button in sidebar
- `ui/src/components/NewProjectModal.tsx` — new modal component
- `ui/src/pages/Dashboard.tsx` — Run Pipeline button with four states
- `ui/src/pages/RunDetail.tsx` — new Run Detail page
- `ui/src/router.tsx` — new route `/:slug/runs/:runId`

**Out of scope:**
- Project settings page (edit config fields after creation) — future sprint
- Stop / pause / resume pipeline — future sprint
- Full config fields in the New Project form (stakeholder groups, value streams, crews) — future sprint

---

## 2. Architecture

```
New Project flow
  AppLayout sidebar
    └─ "New Project" button → NewProjectModal
         ├─ slug (text, kebab-case validated)
         ├─ sector (text)
         ├─ llm_mode (select: standard / sensitive / fallback)
         └─ POST /projects → navigate /{slug}

Run Pipeline flow
  Dashboard
    └─ Run Pipeline button (4 states from latest_orchestration_run)
         └─ POST /projects/{slug}/orchestrate
              └─ navigate /{slug}/runs/{run_id}
  RunDetail (/:slug/runs/:runId)
    └─ polls GET /projects/{slug}/status every 3s while running
         ├─ orchestration status badge
         ├─ crew progress cards
         └─ live agent log (WebSocket)
```

---

## 3. Backend Changes

### 3.1 `api/models.py`

Add defaults to `ProjectCreate` so the minimal UI form only needs to send three fields:

```python
class ProjectCreate(BaseModel):
    client_slug: str
    llm_mode: Literal["standard", "sensitive", "fallback"] = "standard"
    sector: str
    stakeholder_groups: list[str] = []
    value_stream_labels: list[str] = []
    roadmap_time_axis: Literal["quarters", "years", "horizons"] = "quarters"
    crews_enabled: list[str] = [
        "discovery", "value_design", "architecture", "delivery", "business_plan"
    ]
    review_gates: bool = True
    slack_channel: str = ""
```

Add `OrchestrationRunStatus` to `StatusResponse`:

```python
class OrchestrationRunStatus(BaseModel):
    id: int
    status: str
    started_at: str | None
    completed_at: str | None

class StatusResponse(BaseModel):
    project_slug: str
    project_status: str
    crew_runs: list[dict]
    latest_orchestration_run: OrchestrationRunStatus | None = None
```

### 3.2 `api/database.py`

New helper (async, follows existing pattern):

```python
async def fetch_latest_orchestration_run(
    conn: aiosqlite.Connection, *, project_id: int
) -> dict | None:
    async with conn.execute(
        "SELECT id, status, started_at, completed_at "
        "FROM orchestration_runs WHERE project_id=? "
        "ORDER BY started_at DESC LIMIT 1",
        (project_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return dict(row)
```

### 3.3 `api/services/project_service.py`

Extend `get_project_status` to include the latest orchestration run:

```python
async def get_project_status(slug: str) -> dict | None:
    ...
    runs = await fetch_crew_runs(conn, project_id=project["id"])
    latest_orch = await fetch_latest_orchestration_run(conn, project_id=project["id"])
    return {
        "project_slug": slug,
        "project_status": project["status"],
        "crew_runs": runs,
        "latest_orchestration_run": latest_orch,
    }
```

---

## 4. Frontend Changes

### 4.1 `ui/src/types.ts`

```typescript
export interface OrchestrationRun {
  id: number
  status: string  // 'running' | 'completed' | 'failed'
  started_at: string | null
  completed_at: string | null
}

// Extend existing ProjectStatus:
export interface ProjectStatus {
  project_slug: string
  project_status: string
  crew_runs: CrewRun[]
  latest_orchestration_run: OrchestrationRun | null
}
```

### 4.2 `ui/src/api/endpoints.ts`

Add to `projectsApi`:

```typescript
orchestrate: (slug: string): Promise<{ orchestration_run_id: number; status: string }> =>
  apiClient.post(`/projects/${slug}/orchestrate`).then((r) => r.data),
```

### 4.3 `ui/src/components/AppLayout.tsx`

Add a "New Project" button at the bottom of the sidebar. Clicking it sets local state `showNewProjectModal = true`, which renders `<NewProjectModal>`.

### 4.4 `ui/src/components/NewProjectModal.tsx`

Modal with three controlled inputs:

| Field | Type | Validation |
|---|---|---|
| Slug | text | Required; `/^[a-z0-9-]+$/`; min 2 chars |
| Sector | text | Required; min 2 chars |
| LLM Mode | select | standard / sensitive / fallback |

On submit:
1. Validates fields (inline error messages below each input)
2. Calls `projectsApi.create({ client_slug: slug, sector, llm_mode })` — backend fills remaining fields with defaults
3. On success: closes modal, calls `queryClient.invalidateQueries(['projects'])`, navigates to `/{slug}`
4. On error: shows server error message inline

### 4.5 `ui/src/pages/Dashboard.tsx`

Add a Run Pipeline control row beneath the project heading. Four states based on `status?.latest_orchestration_run`:

| Condition | UI |
|---|---|
| `null` | Blue "Run Pipeline" button |
| `status === "running"` | Disabled grey "Running…" + spinner + "View Run →" link to `/:slug/runs/:id` |
| `status === "completed"` | Green "Completed" badge + "View Last Run →" link + "Run Again" button |
| `status === "failed"` | Red "Failed" badge + "View Last Run →" link + "Run Again" button |

"Run Pipeline" / "Run Again" handler:
1. Calls `projectsApi.orchestrate(slug)`
2. Navigates to `/:slug/runs/:orchestration_run_id`

### 4.6 `ui/src/pages/RunDetail.tsx`

New page at `/:slug/runs/:runId`.

- Polls `GET /projects/{slug}/status` every 3 seconds while `latest_orchestration_run.status === "running"`; stops on `"completed"` or `"failed"`
- Layout:
  - Header: `"Pipeline Run"` + orchestration status badge + `"← Back to Dashboard"` link
  - Crew progress cards (same `StatusBadge` component as Dashboard)
  - Live agent log (same `useWebSocket` hook)

### 4.7 `ui/src/router.tsx`

Add inside the existing `AppLayout` children:

```typescript
{ path: ':slug/runs/:runId', element: <RunDetail /> },
```

---

## 5. Testing

**Backend unit tests** (`tests/`):

- `test_project_service.py` — extend existing tests to assert `latest_orchestration_run` is present in status response (None when no runs, dict when run exists)
- `test_database.py` — test `fetch_latest_orchestration_run`: returns `None` for no rows, returns correct row when multiple exist (latest by `started_at`)
- `test_projects_api.py` — test `POST /projects` with only `client_slug`, `sector`, `llm_mode` (omitting optional fields); assert 201 and correct defaults in response

**Frontend:** No new unit tests — existing pattern has no React component tests. Manual verification via dev server.

---

## 6. Run Command

```bash
# Backend
pytest tests/test_database.py tests/test_project_service.py tests/test_projects_api.py -v

# Frontend dev server
cd ui && npm run dev
```

---

## 7. Notes

- `projectsApi.create` is a new helper name — the existing `endpoints.ts` has no create function (only `list`, `status`, `outputs`, etc.). Add alongside existing methods.
- The `latest_orchestration_run` field is `None` when no pipeline has ever been run for a project. The UI shows the blue "Run Pipeline" button in this state.
- `RunDetail` uses `useParams` to get both `slug` and `runId`. It reads `latest_orchestration_run` from the status poll — it does not fetch by `runId` directly. The `runId` in the URL is used only for navigation context and a future "view historical run" feature.
- The `useWebSocket` hook already exists in `ui/src/hooks/` — `RunDetail` reuses it without modification.
