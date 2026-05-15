# SP6a — UI: Project Creation + Pipeline Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire project creation (minimal 3-field form) and PAM pipeline orchestration (Run Pipeline button + Run Detail page) into the existing React UI.

**Architecture:** Backend gains one new DB helper (`fetch_latest_orchestration_run`) and one new field on the status response (`latest_orchestration_run`). Frontend gains a New Project modal in the sidebar, a Run Pipeline button with four states on the Dashboard, and a new RunDetail page that polls for live progress.

**Tech Stack:** Python/FastAPI/aiosqlite (backend), React 18 + TypeScript + Tailwind + TanStack Query v5 (frontend)

---

## File Map

| File | Change |
|---|---|
| `api/models.py` | Add `OrchestrationRunStatus` model; add defaults to `ProjectCreate`; add field to `StatusResponse` |
| `api/database.py` | Add `fetch_latest_orchestration_run` helper |
| `api/services/project_service.py` | Extend `get_project_status` to include latest orchestration run |
| `tests/test_database.py` | Two new tests for `fetch_latest_orchestration_run` |
| `tests/test_project_service.py` | One new test for extended status |
| `tests/test_projects_api.py` | Two new tests: minimal POST payload + status field presence |
| `ui/src/types.ts` | Add `OrchestrationRun`; extend `ProjectStatus` |
| `ui/src/api/endpoints.ts` | Add `create` and `orchestrate` to `projectsApi` |
| `ui/src/components/AppLayout.tsx` | Add New Project button + modal mount |
| `ui/src/components/NewProjectModal.tsx` | New modal component (create) |
| `ui/src/pages/Dashboard.tsx` | Add Run Pipeline button (4 states) |
| `ui/src/pages/RunDetail.tsx` | New run detail page (create) |
| `ui/src/router.tsx` | Add `/:slug/runs/:runId` route |

---

### Task 1: Backend — DB helper, status extension, model defaults

**Files:**
- Modify: `api/database.py`
- Modify: `api/models.py`
- Modify: `api/services/project_service.py`
- Test: `tests/test_database.py`, `tests/test_project_service.py`, `tests/test_projects_api.py`

---

- [ ] **Step 1: Write failing tests for `fetch_latest_orchestration_run`**

Add to `tests/test_database.py` (append after the existing tests):

```python
@pytest.mark.asyncio
async def test_fetch_latest_orchestration_run_returns_none_when_empty(db):
    from api.database import insert_project, fetch_latest_orchestration_run
    await insert_project(db, slug="orch-none", llm_mode="standard", sector="rail", config_json="{}")
    async with db.execute("SELECT id FROM projects WHERE slug='orch-none'") as cur:
        project_id = (await cur.fetchone())["id"]
    result = await fetch_latest_orchestration_run(db, project_id=project_id)
    assert result is None


@pytest.mark.asyncio
async def test_fetch_latest_orchestration_run_returns_most_recent(db):
    from api.database import insert_project, fetch_latest_orchestration_run
    await insert_project(db, slug="orch-latest", llm_mode="standard", sector="rail", config_json="{}")
    async with db.execute("SELECT id FROM projects WHERE slug='orch-latest'") as cur:
        project_id = (await cur.fetchone())["id"]
    await db.execute(
        "INSERT INTO orchestration_runs (project_id, status, started_at) VALUES (?, 'completed', '2026-01-01 10:00:00')",
        (project_id,),
    )
    await db.execute(
        "INSERT INTO orchestration_runs (project_id, status, started_at) VALUES (?, 'running', '2026-01-02 10:00:00')",
        (project_id,),
    )
    await db.commit()
    result = await fetch_latest_orchestration_run(db, project_id=project_id)
    assert result is not None
    assert result["status"] == "running"
```

- [ ] **Step 2: Run to verify they fail**

```bash
python3.13 -m pytest tests/test_database.py::test_fetch_latest_orchestration_run_returns_none_when_empty tests/test_database.py::test_fetch_latest_orchestration_run_returns_most_recent -v
```

Expected: `FAILED` — `ImportError: cannot import name 'fetch_latest_orchestration_run'`

- [ ] **Step 3: Add `fetch_latest_orchestration_run` to `api/database.py`**

Add after the `fetch_crew_runs` function (around line 170). Find the location by looking for `async def fetch_crew_runs` and add the new function immediately after its closing line:

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
    return dict(row) if row else None
```

- [ ] **Step 4: Run to verify they pass**

```bash
python3.13 -m pytest tests/test_database.py::test_fetch_latest_orchestration_run_returns_none_when_empty tests/test_database.py::test_fetch_latest_orchestration_run_returns_most_recent -v
```

Expected: `2 passed`

- [ ] **Step 5: Write failing test for extended status response**

Add to `tests/test_project_service.py`:

```python
@pytest.mark.asyncio
async def test_get_project_status_includes_latest_orchestration_run_none(tmp_path, monkeypatch):
    import api.config as cfg
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    cfg.get_settings.cache_clear()

    from api.services.project_service import create_project, get_project_status
    from api.models import ProjectCreate
    req = ProjectCreate(client_slug="orch-status-test", sector="rail")
    await create_project(req)
    status = await get_project_status("orch-status-test")
    assert status is not None
    assert "latest_orchestration_run" in status
    assert status["latest_orchestration_run"] is None
    cfg.get_settings.cache_clear()
```

- [ ] **Step 6: Run to verify it fails**

```bash
python3.13 -m pytest tests/test_project_service.py::test_get_project_status_includes_latest_orchestration_run_none -v
```

Expected: `FAILED` — either `KeyError: 'latest_orchestration_run'` or `AssertionError` because the field is missing, OR `ValidationError` because `ProjectCreate` still requires `stakeholder_groups`.

- [ ] **Step 7: Update `api/models.py`**

Replace the entire file content with:

```python
# api/models.py
from pydantic import BaseModel
from typing import Literal


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


class ProjectResponse(BaseModel):
    id: int
    slug: str
    llm_mode: str
    sector: str
    status: str


class RunRequest(BaseModel):
    crew: str | None = None  # None = trigger PAM (full run)


class RunResponse(BaseModel):
    run_id: int
    project_slug: str
    crew: str
    status: str


class OutputResponse(BaseModel):
    id: int
    agent_name: str
    output_type: str
    file_path: str
    version: int
    review_status: str


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

- [ ] **Step 8: Update `api/services/project_service.py`**

Change only `get_project_status`. Find it (it's the function that starts `async def get_project_status`) and replace its body:

```python
async def get_project_status(slug: str) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        runs = await fetch_crew_runs(conn, project_id=project["id"])
        latest_orch = await fetch_latest_orchestration_run(conn, project_id=project["id"])
        return {
            "project_slug": slug,
            "project_status": project["status"],
            "crew_runs": runs,
            "latest_orchestration_run": latest_orch,
        }
```

Also add `fetch_latest_orchestration_run` to the import at the top of `project_service.py`. The existing import block currently reads:

```python
from api.database import (
    get_connection,
    get_db_path,
    insert_project,
    fetch_project,
    fetch_crew_runs,
    fetch_agent_outputs,
    list_projects,
)
```

Change it to:

```python
from api.database import (
    get_connection,
    get_db_path,
    insert_project,
    fetch_project,
    fetch_crew_runs,
    fetch_latest_orchestration_run,
    fetch_agent_outputs,
    list_projects,
)
```

- [ ] **Step 9: Run to verify tests pass**

```bash
python3.13 -m pytest tests/test_project_service.py::test_get_project_status_includes_latest_orchestration_run_none -v
```

Expected: `1 passed`

- [ ] **Step 10: Write and run tests for the API layer**

Add to `tests/test_projects_api.py`:

```python
@pytest.mark.asyncio
async def test_create_project_minimal_payload(client):
    """POST /projects with only client_slug + sector uses model defaults."""
    resp = await client.post("/projects", json={"client_slug": "minimal-co", "sector": "retail"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "minimal-co"
    assert data["status"] == "created"


@pytest.mark.asyncio
async def test_get_project_status_includes_orchestration_run_field(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.get("/projects/test-rail/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "latest_orchestration_run" in data
    assert data["latest_orchestration_run"] is None
```

Run them:

```bash
python3.13 -m pytest tests/test_projects_api.py::test_create_project_minimal_payload tests/test_projects_api.py::test_get_project_status_includes_orchestration_run_field -v
```

Expected: `2 passed`

- [ ] **Step 11: Run the full unit suite to check for regressions**

```bash
python3.13 -m pytest --ignore=tests/integration -q
```

Expected: same pass count as before this task (169+), zero new failures.

- [ ] **Step 12: Commit**

```bash
git add api/models.py api/database.py api/services/project_service.py \
        tests/test_database.py tests/test_project_service.py tests/test_projects_api.py
git commit -m "feat(api): add orchestration run status to project status response"
```

---

### Task 2: Frontend types + API layer

**Files:**
- Modify: `ui/src/types.ts`
- Modify: `ui/src/api/endpoints.ts`

No backend changes. No unit tests (no React component test suite exists).

---

- [ ] **Step 1: Update `ui/src/types.ts`**

Replace the entire file with:

```typescript
// ui/src/types.ts

export interface Project {
  id: number
  slug: string
  llm_mode: string
  sector: string
  status: string
}

export interface CrewRun {
  id: number
  project_id: number
  crew_name: string
  status: 'pending' | 'queued' | 'running' | 'completed' | 'failed'
  result_json: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface OrchestrationRun {
  id: number
  status: string  // 'running' | 'completed' | 'failed'
  started_at: string | null
  completed_at: string | null
}

export interface ProjectStatus {
  project_slug: string
  project_status: string
  crew_runs: CrewRun[]
  latest_orchestration_run: OrchestrationRun | null
}

export interface AgentOutput {
  id: number
  agent_name: string
  output_type: string
  file_path: string
  version: number
  review_status: string
  created_at: string
}

export interface ClientDocument {
  id: number
  project_id: number
  filename: string
  original_name: string
  file_path: string
  content_type: string
  size_bytes: number
  ingested: boolean
  uploaded_at: string
}

export interface Review {
  id: number
  output_id: number
  decision: string
  notes: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface UserPayload {
  sub: string
  role: string
  exp: number
}
```

- [ ] **Step 2: Update `ui/src/api/endpoints.ts`**

Replace the entire file with:

```typescript
// ui/src/api/endpoints.ts
import { apiClient } from './client'
import type {
  Project,
  ProjectStatus,
  AgentOutput,
  ClientDocument,
  TokenResponse,
} from '../types'

export const authApi = {
  login: (username: string, password: string): Promise<TokenResponse> => {
    const form = new URLSearchParams()
    form.append('username', username)
    form.append('password', password)
    return apiClient.post<TokenResponse>('/auth/login', form).then((r) => r.data)
  },
}

export const projectsApi = {
  list: (): Promise<Project[]> =>
    apiClient.get<Project[]>('/projects').then((r) => r.data),

  create: (payload: {
    client_slug: string
    sector: string
    llm_mode?: string
  }): Promise<Project> =>
    apiClient.post<Project>('/projects', payload).then((r) => r.data),

  status: (slug: string): Promise<ProjectStatus> =>
    apiClient.get<ProjectStatus>(`/projects/${slug}/status`).then((r) => r.data),

  outputs: (slug: string): Promise<AgentOutput[]> =>
    apiClient.get<AgentOutput[]>(`/projects/${slug}/outputs`).then((r) => r.data),

  documents: (slug: string): Promise<ClientDocument[]> =>
    apiClient.get<ClientDocument[]>(`/projects/${slug}/documents`).then((r) => r.data),

  uploadDocument: (slug: string, file: File): Promise<ClientDocument> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient
      .post<ClientDocument>(`/projects/${slug}/documents/upload`, form)
      .then((r) => r.data)
  },

  valueChain: (slug: string): Promise<AgentOutput[]> =>
    apiClient.get<AgentOutput[]>(`/projects/${slug}/value-chain`).then((r) => r.data),

  roadmap: (slug: string): Promise<AgentOutput[]> =>
    apiClient.get<AgentOutput[]>(`/projects/${slug}/roadmap`).then((r) => r.data),

  review: (slug: string, outputId: number, decision: string, notes = '') =>
    apiClient
      .post(`/projects/${slug}/review`, { output_id: outputId, decision, notes })
      .then((r) => r.data),

  orchestrate: (slug: string): Promise<{ orchestration_run_id: number; status: string }> =>
    apiClient.post(`/projects/${slug}/orchestrate`).then((r) => r.data),
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors related to `OrchestrationRun`, `ProjectStatus`, or the new `endpoints.ts` functions. (Ignore pre-existing errors if any — only care that the new types are clean.)

- [ ] **Step 4: Commit**

```bash
git add ui/src/types.ts ui/src/api/endpoints.ts
git commit -m "feat(ui): add OrchestrationRun type and orchestrate/create API functions"
```

---

### Task 3: New Project modal + sidebar button

**Files:**
- Create: `ui/src/components/NewProjectModal.tsx`
- Modify: `ui/src/components/AppLayout.tsx`

---

- [ ] **Step 1: Create `ui/src/components/NewProjectModal.tsx`**

```tsx
// ui/src/components/NewProjectModal.tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'

interface Props {
  onClose: () => void
}

export default function NewProjectModal({ onClose }: Props) {
  const [slug, setSlug] = useState('')
  const [sector, setSector] = useState('')
  const [llmMode, setLlmMode] = useState<'standard' | 'sensitive' | 'fallback'>('standard')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [serverError, setServerError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  function validate() {
    const e: Record<string, string> = {}
    if (!slug) e.slug = 'Required'
    else if (!/^[a-z0-9-]{2,}$/.test(slug)) e.slug = 'Lowercase letters, numbers, hyphens only (min 2 chars)'
    if (!sector || sector.trim().length < 2) e.sector = 'Required (min 2 characters)'
    return e
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const errs = validate()
    if (Object.keys(errs).length) {
      setErrors(errs)
      return
    }
    setSubmitting(true)
    setServerError('')
    try {
      await projectsApi.create({ client_slug: slug, sector: sector.trim(), llm_mode: llmMode })
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      onClose()
      navigate(`/${slug}`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to create project'
      setServerError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-surface-raised border border-slate-700 rounded-xl p-6 w-80 space-y-4">
        <h2 className="text-slate-100 font-semibold">New Project</h2>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Slug</label>
            <input
              className="w-full bg-surface border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-sky-500"
              placeholder="acme-rail"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
            />
            {errors.slug && <p className="text-xs text-red-400 mt-1">{errors.slug}</p>}
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Sector</label>
            <input
              className="w-full bg-surface border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-sky-500"
              placeholder="logistics"
              value={sector}
              onChange={(e) => setSector(e.target.value)}
            />
            {errors.sector && <p className="text-xs text-red-400 mt-1">{errors.sector}</p>}
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">LLM Mode</label>
            <select
              className="w-full bg-surface border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-sky-500"
              value={llmMode}
              onChange={(e) =>
                setLlmMode(e.target.value as 'standard' | 'sensitive' | 'fallback')
              }
            >
              <option value="standard">Standard (Claude API)</option>
              <option value="sensitive">Sensitive (Local only)</option>
              <option value="fallback">Fallback (Claude → Local)</option>
            </select>
          </div>
          {serverError && <p className="text-xs text-red-400">{serverError}</p>}
          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 text-sm text-slate-400 hover:text-slate-200 py-1.5"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex-1 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm rounded py-1.5"
            >
              {submitting ? 'Creating…' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Update `ui/src/components/AppLayout.tsx`**

Replace the entire file with:

```tsx
// ui/src/components/AppLayout.tsx
import { useState } from 'react'
import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import NewProjectModal from './NewProjectModal'
import type { Project } from '../types'

export default function AppLayout() {
  const { slug } = useParams<{ slug?: string }>()
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [showModal, setShowModal] = useState(false)

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    refetchInterval: 10_000,
  })

  function handleLogout() {
    logout()
    navigate('/login')
  }

  const navItems = slug
    ? [
        { to: `/${slug}`, label: 'Dashboard', end: true },
        { to: `/${slug}/value-chain`, label: 'Value Chain' },
        { to: `/${slug}/roadmap`, label: 'Roadmap' },
        { to: `/${slug}/documents`, label: 'Documents' },
      ]
    : [{ to: '/', label: 'Dashboard', end: true }]

  return (
    <div className="min-h-screen bg-surface flex flex-col">
      {/* Top nav */}
      <header className="bg-surface-raised border-b border-slate-800 px-4 h-12 flex items-center gap-6">
        <span className="font-bold text-brand-light text-sm tracking-wide">AgentPool</span>
        <nav className="flex gap-4">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `text-sm pb-0.5 border-b-2 transition-colors ${
                  isActive
                    ? 'text-sky-300 border-sky-300'
                    : 'text-slate-400 border-transparent hover:text-slate-200'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {slug && (
            <>
              <a
                href="http://localhost:8001"
                target="_blank"
                rel="noreferrer"
                className="text-xs text-slate-500 hover:text-slate-300"
              >
                Chainlit ↗
              </a>
              <a
                href="http://localhost:5678"
                target="_blank"
                rel="noreferrer"
                className="text-xs text-slate-500 hover:text-slate-300"
              >
                n8n ↗
              </a>
            </>
          )}
          <span className="text-xs text-slate-500">{user?.sub}</span>
          <button onClick={handleLogout} className="text-xs text-slate-500 hover:text-slate-300">
            Sign out
          </button>
        </div>
      </header>

      <div className="flex flex-1">
        {/* Sidebar */}
        <aside className="w-44 bg-surface-raised border-r border-slate-800 p-3 flex flex-col gap-1">
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-2">
            Projects
          </p>
          {projects.map((p) => (
            <button
              key={p.slug}
              onClick={() => navigate(`/${p.slug}`)}
              className={`w-full text-left text-sm px-2 py-1.5 rounded transition-colors ${
                slug === p.slug
                  ? 'bg-sky-900/40 text-sky-300'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              {p.slug}
            </button>
          ))}
          {projects.length === 0 && (
            <p className="text-xs text-slate-600 px-2">No projects yet</p>
          )}
          {/* New Project button — pinned to bottom of sidebar */}
          <div className="mt-auto pt-3">
            <button
              onClick={() => setShowModal(true)}
              className="w-full text-xs text-slate-500 hover:text-slate-200 border border-slate-700 hover:border-slate-500 rounded px-2 py-1.5 transition-colors text-left"
            >
              + New Project
            </button>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>

      {showModal && <NewProjectModal onClose={() => setShowModal(false)} />}
    </div>
  )
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors on `NewProjectModal.tsx` or the updated `AppLayout.tsx`.

- [ ] **Step 4: Start the dev server and verify manually**

```bash
cd ui && npm run dev
```

Open `http://localhost:3000`. Log in. Verify:
- Sidebar shows "+ New Project" button at the bottom
- Clicking it opens the modal
- Submitting an empty form shows validation errors
- Slug `ACME` fails validation (uppercase); `acme-rail` passes
- Cancel closes the modal

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/NewProjectModal.tsx ui/src/components/AppLayout.tsx
git commit -m "feat(ui): add New Project modal and sidebar button"
```

---

### Task 4: Dashboard Run Pipeline button

**Files:**
- Modify: `ui/src/pages/Dashboard.tsx`

---

- [ ] **Step 1: Replace `ui/src/pages/Dashboard.tsx`**

```tsx
// ui/src/pages/Dashboard.tsx
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import StatusBadge from '../components/StatusBadge'
import ReviewQueue from '../components/ReviewQueue'
import { useWebSocket } from '../hooks/useWebSocket'

export default function Dashboard() {
  const { slug } = useParams<{ slug?: string }>()
  const navigate = useNavigate()
  const logs = useWebSocket(slug)

  const { data: status } = useQuery({
    queryKey: ['status', slug],
    queryFn: () => projectsApi.status(slug!),
    enabled: !!slug,
    refetchInterval: 5_000,
  })

  const { data: outputs = [] } = useQuery({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.outputs(slug!),
    enabled: !!slug,
    refetchInterval: 5_000,
  })

  const runMutation = useMutation({
    mutationFn: () => projectsApi.orchestrate(slug!),
    onSuccess: (data) => {
      navigate(`/${slug}/runs/${data.orchestration_run_id}`)
    },
  })

  if (!slug) {
    return (
      <div className="p-8 text-slate-400">
        <p>Select a project from the sidebar to begin.</p>
      </div>
    )
  }

  const orch = status?.latest_orchestration_run

  return (
    <div className="p-6 space-y-6">
      {/* Project header + Run Pipeline control */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-100 mb-1">{slug}</h2>
          {status && (
            <div className="flex items-center gap-2">
              <StatusBadge status={status.project_status} />
            </div>
          )}
        </div>

        {/* Run Pipeline button — four states */}
        <div className="flex items-center gap-3">
          {!orch && (
            <button
              onClick={() => runMutation.mutate()}
              disabled={runMutation.isPending}
              className="px-4 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm rounded"
            >
              Run Pipeline
            </button>
          )}

          {orch?.status === 'running' && (
            <>
              <button
                disabled
                className="px-4 py-1.5 bg-slate-700 text-slate-400 text-sm rounded opacity-60 cursor-not-allowed flex items-center gap-2"
              >
                <span className="inline-block w-3 h-3 border-2 border-slate-400 border-t-transparent rounded-full animate-spin" />
                Running…
              </button>
              <button
                onClick={() => navigate(`/${slug}/runs/${orch.id}`)}
                className="text-sm text-sky-400 hover:text-sky-300"
              >
                View Run →
              </button>
            </>
          )}

          {(orch?.status === 'completed' || orch?.status === 'failed') && (
            <>
              <span
                className={`text-sm font-medium ${
                  orch.status === 'completed' ? 'text-emerald-400' : 'text-red-400'
                }`}
              >
                {orch.status === 'completed' ? 'Completed' : 'Failed'}
              </span>
              <button
                onClick={() => navigate(`/${slug}/runs/${orch.id}`)}
                className="text-sm text-sky-400 hover:text-sky-300"
              >
                View Last Run →
              </button>
              <button
                onClick={() => runMutation.mutate()}
                disabled={runMutation.isPending}
                className="px-4 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm rounded"
              >
                Run Again
              </button>
            </>
          )}
        </div>
      </div>

      {/* Crew progress */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Crew Progress
        </h3>
        {status?.crew_runs.length === 0 && (
          <p className="text-sm text-slate-500">No crew runs yet.</p>
        )}
        <div className="space-y-2">
          {status?.crew_runs.map((run) => (
            <div
              key={run.id}
              className="flex items-center justify-between bg-surface-card rounded-lg px-4 py-3"
            >
              <span className="text-sm text-slate-200">{run.crew_name}</span>
              <StatusBadge status={run.status} />
            </div>
          ))}
        </div>
      </section>

      {/* Review queue */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Review Queue
        </h3>
        <ReviewQueue slug={slug} outputs={outputs} />
      </section>

      {/* Live log */}
      {logs.length > 0 && (
        <section>
          <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
            Agent Log
          </h3>
          <div className="bg-black/40 rounded-lg p-4 font-mono text-xs text-emerald-400 space-y-0.5 max-h-48 overflow-y-auto">
            {logs.map((line, i) => (
              <p key={i}>{line}</p>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit 2>&1 | head -20
```

Expected: no new errors.

- [ ] **Step 3: Verify manually in browser**

With the dev server running (`npm run dev`), select a project. Verify:
- "Run Pipeline" button appears when no prior runs exist
- Button is right-aligned, project name is left-aligned

(Full end-to-end orchestration test happens after Task 5.)

- [ ] **Step 4: Commit**

```bash
git add ui/src/pages/Dashboard.tsx
git commit -m "feat(ui): add Run Pipeline button with four orchestration states"
```

---

### Task 5: Run Detail page + router

**Files:**
- Create: `ui/src/pages/RunDetail.tsx`
- Modify: `ui/src/router.tsx`

---

- [ ] **Step 1: Create `ui/src/pages/RunDetail.tsx`**

```tsx
// ui/src/pages/RunDetail.tsx
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import StatusBadge from '../components/StatusBadge'
import { useWebSocket } from '../hooks/useWebSocket'

export default function RunDetail() {
  const { slug, runId } = useParams<{ slug: string; runId: string }>()
  const navigate = useNavigate()
  const logs = useWebSocket(slug)

  const { data: status } = useQuery({
    queryKey: ['status', slug],
    queryFn: () => projectsApi.status(slug!),
    enabled: !!slug,
    refetchInterval: (query) => {
      const s = query.state.data?.latest_orchestration_run?.status
      return s === 'running' ? 3_000 : false
    },
  })

  const orch = status?.latest_orchestration_run

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate(`/${slug}`)}
          className="text-sm text-slate-400 hover:text-slate-200"
        >
          ← Back to Dashboard
        </button>
        <h2 className="text-lg font-semibold text-slate-100">Pipeline Run</h2>
        {orch && <StatusBadge status={orch.status} />}
      </div>

      {/* Crew progress */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Crew Progress
        </h3>
        {!status?.crew_runs.length && (
          <p className="text-sm text-slate-500">Waiting for crews to start…</p>
        )}
        <div className="space-y-2">
          {status?.crew_runs.map((run) => (
            <div
              key={run.id}
              className="flex items-center justify-between bg-surface-card rounded-lg px-4 py-3"
            >
              <span className="text-sm text-slate-200">{run.crew_name}</span>
              <StatusBadge status={run.status} />
            </div>
          ))}
        </div>
      </section>

      {/* Live agent log */}
      {logs.length > 0 && (
        <section>
          <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
            Agent Log
          </h3>
          <div className="bg-black/40 rounded-lg p-4 font-mono text-xs text-emerald-400 space-y-0.5 max-h-64 overflow-y-auto">
            {logs.map((line, i) => (
              <p key={i}>{line}</p>
            ))}
          </div>
        </section>
      )}

      {/* Completion notice */}
      {orch && orch.status !== 'running' && (
        <div
          className={`rounded-lg px-4 py-3 text-sm ${
            orch.status === 'completed'
              ? 'bg-emerald-900/30 text-emerald-300'
              : 'bg-red-900/30 text-red-300'
          }`}
        >
          {orch.status === 'completed'
            ? 'Pipeline completed successfully. All outputs are available in the Documents tab.'
            : 'Pipeline failed. Check the agent log above for details.'}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Update `ui/src/router.tsx`**

Replace the entire file with:

```tsx
// ui/src/router.tsx
import { createBrowserRouter, Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from './context/AuthContext'
import AppLayout from './components/AppLayout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Documents from './pages/Documents'
import ValueChain from './pages/ValueChain'
import Roadmap from './pages/Roadmap'
import RunDetail from './pages/RunDetail'

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <Login />,
  },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <Dashboard /> },
      { path: ':slug', element: <Dashboard /> },
      { path: ':slug/value-chain', element: <ValueChain /> },
      { path: ':slug/roadmap', element: <Roadmap /> },
      { path: ':slug/documents', element: <Documents /> },
      { path: ':slug/runs/:runId', element: <RunDetail /> },
    ],
  },
])
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit 2>&1 | head -20
```

Expected: no new errors.

- [ ] **Step 4: Verify the full flow manually**

With the dev server and FastAPI backend running, do a full end-to-end check:

1. Log in at `http://localhost:3000`
2. Click "+ New Project" — create a project with slug `test-ui`, sector `logistics`
3. Verify `test-ui` appears in the sidebar and you're navigated to its Dashboard
4. Click "Run Pipeline" — verify it navigates to `/test-ui/runs/{id}`
5. Verify RunDetail shows "Waiting for crews to start…" and then crew cards appear as they run
6. Verify "← Back to Dashboard" works
7. After run completes, go back to Dashboard — verify button shows "Completed" + "View Last Run →" + "Run Again"
8. Selecting a different project in the sidebar and coming back shows the correct button state

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/RunDetail.tsx ui/src/router.tsx
git commit -m "feat(ui): add RunDetail page and route for pipeline run monitoring"
```
