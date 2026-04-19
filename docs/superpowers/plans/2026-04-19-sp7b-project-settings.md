# SP7b — Project Settings Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Settings page where users can view and edit all 8 editable project config fields, accessible via a ⚙ icon next to the active project in the sidebar.

**Architecture:** Two new FastAPI endpoints (`GET`/`PATCH /projects/{slug}/settings`) read and write `config_json` from SQLite and atomically rewrite `config.yaml` on disk. A new `Settings.tsx` React page fetches the current config on mount and PATCHes on Save. The ⚙ icon is added to the sidebar in `AppLayout.tsx`.

**Tech Stack:** FastAPI, aiosqlite, Pydantic v2, React 18, TanStack Query v5, React Router v6, Tailwind CSS

---

## File Map

| File | Change |
|---|---|
| `api/models.py` | Add `ProjectSettings` Pydantic model |
| `api/database.py` | Add `update_project_config` helper |
| `api/services/project_service.py` | Add `get_project_settings`, `update_project_settings` |
| `api/routers/projects.py` | Add `GET`/`PATCH /{slug}/settings` endpoints |
| `tests/test_database.py` | Add `test_update_project_config` |
| `tests/test_projects_settings.py` | New — 5 HTTP tests |
| `ui/src/types.ts` | Add `ProjectSettings` interface |
| `ui/src/api/endpoints.ts` | Add `getSettings`, `updateSettings` |
| `ui/src/pages/Settings.tsx` | New settings form page |
| `ui/src/components/AppLayout.tsx` | Add ⚙ icon to active project row |
| `ui/src/router.tsx` | Register `/:slug/settings` route |

---

## Task 1: Backend Model + DB Helper

**Files:**
- Modify: `api/models.py`
- Modify: `api/database.py`
- Modify: `tests/test_database.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_database.py`:

```python
@pytest.mark.asyncio
async def test_update_project_config(db):
    from api.database import insert_project, fetch_project, update_project_config
    await insert_project(db, slug="cfg-test", llm_mode="standard", sector="rail", config_json='{"sector":"rail"}')
    project = await fetch_project(db, slug="cfg-test")
    await update_project_config(
        db,
        project_id=project["id"],
        llm_mode="sensitive",
        sector="energy",
        config_json='{"sector":"energy","llm_mode":"sensitive"}',
    )
    updated = await fetch_project(db, slug="cfg-test")
    assert updated["llm_mode"] == "sensitive"
    assert updated["sector"] == "energy"
    assert updated["config_json"] == '{"sector":"energy","llm_mode":"sensitive"}'
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_database.py::test_update_project_config -v
```

Expected: `FAILED` — `ImportError: cannot import name 'update_project_config'`

- [ ] **Step 3: Add `ProjectSettings` to `api/models.py`**

Append after the `ProjectCreate` class (after line 17):

```python
class ProjectSettings(BaseModel):
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

- [ ] **Step 4: Add `update_project_config` to `api/database.py`**

Append after the `fetch_documents` function (after line 227):

```python
async def update_project_config(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    llm_mode: str,
    sector: str,
    config_json: str,
) -> None:
    await conn.execute(
        "UPDATE projects SET llm_mode=?, sector=?, config_json=? WHERE id=?",
        (llm_mode, sector, config_json, project_id),
    )
    await conn.commit()
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_database.py::test_update_project_config -v
```

Expected: `PASSED`

- [ ] **Step 6: Run full database test suite to check for regressions**

```bash
pytest tests/test_database.py -v
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add api/models.py api/database.py tests/test_database.py
git commit -m "feat: add ProjectSettings model and update_project_config DB helper"
```

---

## Task 2: Service Functions + Router Endpoints

**Files:**
- Modify: `api/services/project_service.py`
- Modify: `api/routers/projects.py`
- Create: `tests/test_projects_settings.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_projects_settings.py`:

```python
import shutil
import yaml
import pytest
from pathlib import Path
from api.config import get_settings

PROJECT = {
    "client_slug": "settings-test",
    "llm_mode": "standard",
    "sector": "rail",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "roadmap_time_axis": "quarters",
    "crews_enabled": ["discovery", "value_design"],
    "review_gates": True,
    "slack_channel": "#rail",
}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / "settings-test.db"
    proj_dir = Path(settings.projects_dir) / "settings-test"
    db_path.unlink(missing_ok=True)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)


@pytest.mark.asyncio
async def test_get_settings_returns_config(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get("/projects/settings-test/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sector"] == "rail"
    assert data["llm_mode"] == "standard"
    assert data["stakeholder_groups"] == ["Operations"]
    assert data["review_gates"] is True
    assert "client_slug" not in data


@pytest.mark.asyncio
async def test_get_settings_unknown_project_404(client):
    resp = await client.get("/projects/ghost/settings")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_settings_updates_db(client):
    await client.post("/projects", json=PROJECT)
    patch_body = {
        "llm_mode": "sensitive",
        "sector": "energy",
        "stakeholder_groups": ["Finance"],
        "value_stream_labels": [],
        "roadmap_time_axis": "years",
        "crews_enabled": ["discovery"],
        "review_gates": False,
        "slack_channel": "#energy",
    }
    resp = await client.patch("/projects/settings-test/settings", json=patch_body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["sector"] == "energy"
    assert data["llm_mode"] == "sensitive"
    assert data["review_gates"] is False
    # Verify persisted via GET
    get_resp = await client.get("/projects/settings-test/settings")
    assert get_resp.json()["sector"] == "energy"
    assert get_resp.json()["llm_mode"] == "sensitive"


@pytest.mark.asyncio
async def test_patch_settings_rewrites_yaml(client):
    await client.post("/projects", json=PROJECT)
    patch_body = {
        "llm_mode": "standard",
        "sector": "energy",
        "stakeholder_groups": [],
        "value_stream_labels": [],
        "roadmap_time_axis": "quarters",
        "crews_enabled": ["discovery"],
        "review_gates": True,
        "slack_channel": "",
    }
    await client.patch("/projects/settings-test/settings", json=patch_body)
    settings = get_settings()
    yaml_path = Path(settings.projects_dir) / "settings-test" / "config.yaml"
    with yaml_path.open() as f:
        config = yaml.safe_load(f)
    assert config["sector"] == "energy"
    assert config["client_slug"] == "settings-test"


@pytest.mark.asyncio
async def test_patch_settings_unknown_project_404(client):
    patch_body = {
        "llm_mode": "standard",
        "sector": "rail",
        "stakeholder_groups": [],
        "value_stream_labels": [],
        "roadmap_time_axis": "quarters",
        "crews_enabled": ["discovery"],
        "review_gates": True,
        "slack_channel": "",
    }
    resp = await client.patch("/projects/ghost/settings", json=patch_body)
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_projects_settings.py -v
```

Expected: `FAILED` — `404` responses (endpoints not yet defined)

- [ ] **Step 3: Add service functions to `api/services/project_service.py`**

Add `update_project_config` to the database imports (all other imports — `json`, `os`, `tempfile`, `yaml`, `Path`, `get_settings`, `get_connection`, `get_db_path`, `fetch_project` — are already present):

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
    update_project_config,
)
```

Add `ProjectSettings` to the models import:

```python
from api.models import ProjectCreate, ProjectSettings
```

Append the two new service functions after `list_all_projects`:

```python
async def get_project_settings(slug: str) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        config = json.loads(project["config_json"])
        config.pop("client_slug", None)
        return config


async def update_project_settings(slug: str, settings: ProjectSettings) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    settings_dict = settings.model_dump()
    full_config = {"client_slug": slug, **settings_dict}
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        await update_project_config(
            conn,
            project_id=project["id"],
            llm_mode=settings.llm_mode,
            sector=settings.sector,
            config_json=json.dumps(full_config),
        )
    project_dir = Path(get_settings().projects_dir) / slug
    config_path = project_dir / "config.yaml"
    fd, tmp_path = tempfile.mkstemp(dir=project_dir, suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(full_config, f, default_flow_style=False)
        os.replace(tmp_path, config_path)
    except Exception:
        os.unlink(tmp_path)
        raise
    return settings_dict
```

- [ ] **Step 4: Add endpoints to `api/routers/projects.py`**

Update the imports at the top of `api/routers/projects.py`:

```python
from api.models import ProjectCreate, ProjectSettings, StatusResponse, ProjectResponse
from api.services.project_service import (
    create_project,
    get_project_status,
    list_all_projects,
    get_project_settings,
    update_project_settings,
)
```

Append the two new endpoints at the end of the file:

```python
@router.get("/{slug}/settings", response_model=ProjectSettings)
async def get_settings_endpoint(slug: str):
    result = await get_project_settings(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.patch("/{slug}/settings", response_model=ProjectSettings)
async def patch_settings_endpoint(slug: str, req: ProjectSettings):
    result = await update_project_settings(slug, req)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_projects_settings.py -v
```

Expected: all 5 tests `PASSED`

- [ ] **Step 6: Run full backend test suite to check for regressions**

```bash
pytest tests/ -v --ignore=tests/integration -q
```

Expected: all tests pass (26 existing + 5 new = 31 passing)

- [ ] **Step 7: Commit**

```bash
git add api/models.py api/services/project_service.py api/routers/projects.py tests/test_projects_settings.py
git commit -m "feat: add GET/PATCH /projects/{slug}/settings endpoints"
```

---

## Task 3: Frontend Types + API Layer

**Files:**
- Modify: `ui/src/types.ts`
- Modify: `ui/src/api/endpoints.ts`

No automated tests for this task — correctness verified in Task 4 when the Settings page compiles and runs.

- [ ] **Step 1: Add `ProjectSettings` interface to `ui/src/types.ts`**

Append after the `ClientDocument` interface (after line 56):

```typescript
export interface ProjectSettings {
  llm_mode: 'standard' | 'sensitive' | 'fallback'
  sector: string
  stakeholder_groups: string[]
  value_stream_labels: string[]
  roadmap_time_axis: 'quarters' | 'years' | 'horizons'
  crews_enabled: string[]
  review_gates: boolean
  slack_channel: string
}
```

- [ ] **Step 2: Add `getSettings` and `updateSettings` to `ui/src/api/endpoints.ts`**

Update the type import at the top of `ui/src/api/endpoints.ts`:

```typescript
import type {
  Project,
  ProjectStatus,
  AgentOutput,
  ClientDocument,
  ProjectSettings,
  TokenResponse,
} from '../types'
```

Append inside the `projectsApi` object, after the `orchestrate` entry (before the closing `}`):

```typescript
  getSettings: (slug: string): Promise<ProjectSettings> =>
    apiClient.get<ProjectSettings>(`/projects/${slug}/settings`).then((r) => r.data),

  updateSettings: (slug: string, data: ProjectSettings): Promise<ProjectSettings> =>
    apiClient.patch<ProjectSettings>(`/projects/${slug}/settings`, data).then((r) => r.data),
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add ui/src/types.ts ui/src/api/endpoints.ts
git commit -m "feat: add ProjectSettings type and API methods"
```

---

## Task 4: Settings Page + Sidebar Gear + Router

**Files:**
- Create: `ui/src/pages/Settings.tsx`
- Modify: `ui/src/components/AppLayout.tsx`
- Modify: `ui/src/router.tsx`

- [ ] **Step 1: Create `ui/src/pages/Settings.tsx`**

```typescript
import { useEffect, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import type { ProjectSettings } from '../types'

const KNOWN_CREWS = ['discovery', 'value_design', 'architecture', 'delivery', 'business_plan']

const DEFAULTS: ProjectSettings = {
  llm_mode: 'standard',
  sector: '',
  stakeholder_groups: [],
  value_stream_labels: [],
  roadmap_time_axis: 'quarters',
  crews_enabled: [...KNOWN_CREWS],
  review_gates: true,
  slack_channel: '',
}

function TagInput({
  value,
  onChange,
}: {
  value: string[]
  onChange: (v: string[]) => void
}) {
  const [input, setInput] = useState('')

  function handleKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && input.trim()) {
      e.preventDefault()
      if (!value.includes(input.trim())) {
        onChange([...value, input.trim()])
      }
      setInput('')
    }
  }

  return (
    <div className="flex flex-wrap gap-1 p-2 bg-slate-900 border border-slate-700 rounded min-h-[36px]">
      {value.map((tag) => (
        <span
          key={tag}
          className="flex items-center gap-1 bg-sky-900/60 text-sky-300 text-xs px-2 py-0.5 rounded-full"
        >
          {tag}
          <button
            type="button"
            onClick={() => onChange(value.filter((t) => t !== tag))}
            className="text-sky-400 hover:text-white leading-none"
          >
            ×
          </button>
        </span>
      ))}
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKey}
        placeholder="Add…"
        className="bg-transparent text-sm text-slate-300 outline-none min-w-[80px] flex-1"
      />
    </div>
  )
}

export default function Settings() {
  const { slug } = useParams<{ slug: string }>()
  const qc = useQueryClient()
  const [form, setForm] = useState<ProjectSettings>(DEFAULTS)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug!),
    enabled: !!slug,
  })

  useEffect(() => {
    if (settings) setForm(settings)
  }, [settings])

  const mutation = useMutation({
    mutationFn: (data: ProjectSettings) => projectsApi.updateSettings(slug!, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings', slug] })
      setSaved(true)
      setError(null)
      setTimeout(() => setSaved(false), 2000)
    },
    onError: () => setError('Save failed. Please try again.'),
  })

  if (!slug) return null

  function toggleCrew(crew: string) {
    setForm((f) => ({
      ...f,
      crews_enabled: f.crews_enabled.includes(crew)
        ? f.crews_enabled.filter((c) => c !== crew)
        : [...f.crews_enabled, crew],
    }))
  }

  return (
    <div className="p-6 max-w-2xl space-y-6">
      <h2 className="text-lg font-semibold text-slate-100">Settings — {slug}</h2>

      {/* General */}
      <section className="space-y-4">
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest">General</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-slate-400 block mb-1">Sector</label>
            <input
              value={form.sector}
              onChange={(e) => setForm({ ...form, sector: e.target.value })}
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-sky-600"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">LLM Mode</label>
            <select
              value={form.llm_mode}
              onChange={(e) =>
                setForm({ ...form, llm_mode: e.target.value as ProjectSettings['llm_mode'] })
              }
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-sky-600"
            >
              <option value="standard">standard</option>
              <option value="sensitive">sensitive</option>
              <option value="fallback">fallback</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Roadmap Time Axis</label>
            <select
              value={form.roadmap_time_axis}
              onChange={(e) =>
                setForm({
                  ...form,
                  roadmap_time_axis: e.target.value as ProjectSettings['roadmap_time_axis'],
                })
              }
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-sky-600"
            >
              <option value="quarters">quarters</option>
              <option value="years">years</option>
              <option value="horizons">horizons</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Slack Channel</label>
            <input
              value={form.slack_channel}
              onChange={(e) => setForm({ ...form, slack_channel: e.target.value })}
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-sky-600"
            />
          </div>
        </div>
      </section>

      {/* Tag fields */}
      <section className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-slate-400 block mb-1">Stakeholder Groups</label>
          <TagInput
            value={form.stakeholder_groups}
            onChange={(v) => setForm({ ...form, stakeholder_groups: v })}
          />
        </div>
        <div>
          <label className="text-xs text-slate-400 block mb-1">Value Stream Labels</label>
          <TagInput
            value={form.value_stream_labels}
            onChange={(v) => setForm({ ...form, value_stream_labels: v })}
          />
        </div>
      </section>

      {/* Crews */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Crews Enabled
        </h3>
        <div className="flex flex-wrap gap-4">
          {KNOWN_CREWS.map((crew) => (
            <label key={crew} className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={form.crews_enabled.includes(crew)}
                onChange={() => toggleCrew(crew)}
              />
              {crew}
            </label>
          ))}
        </div>
      </section>

      {/* Review gates */}
      <section className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-200">Review Gates</p>
          <p className="text-xs text-slate-500">Pause pipeline for human review between crews</p>
        </div>
        <button
          type="button"
          onClick={() => setForm({ ...form, review_gates: !form.review_gates })}
          className={`relative inline-flex h-5 w-9 rounded-full transition-colors ${
            form.review_gates ? 'bg-sky-600' : 'bg-slate-700'
          }`}
        >
          <span
            className={`inline-block h-4 w-4 mt-0.5 rounded-full bg-white shadow transition-transform ${
              form.review_gates ? 'translate-x-4' : 'translate-x-0.5'
            }`}
          />
        </button>
      </section>

      {/* Footer */}
      <div className="border-t border-slate-800 pt-4 flex items-center justify-between">
        {error ? <p className="text-sm text-red-400">{error}</p> : <span />}
        <button
          onClick={() => mutation.mutate(form)}
          disabled={mutation.isPending}
          className="px-4 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm rounded"
        >
          {saved ? 'Saved!' : mutation.isPending ? 'Saving…' : 'Save Settings'}
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Update the sidebar in `ui/src/components/AppLayout.tsx`**

Replace the `projects.map(...)` block (lines 93–105) with a version that adds the ⚙ icon to the active project row:

```typescript
          {projects.map((p) => (
            <div key={p.slug} className="flex items-center gap-1">
              <button
                onClick={() => navigate(`/${p.slug}`)}
                className={`flex-1 text-left text-sm px-2 py-1.5 rounded transition-colors ${
                  slug === p.slug
                    ? 'bg-sky-900/40 text-sky-300'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`}
              >
                {p.slug}
              </button>
              {slug === p.slug && (
                <button
                  onClick={() => navigate(`/${p.slug}/settings`)}
                  className="text-slate-500 hover:text-slate-300 text-sm px-1 flex-shrink-0"
                  title="Settings"
                >
                  ⚙
                </button>
              )}
            </div>
          ))}
```

- [ ] **Step 3: Register the route in `ui/src/router.tsx`**

Add the Settings import alongside the other page imports:

```typescript
import Settings from './pages/Settings'
```

Append the route inside the `children` array, after the `RunDetail` entry:

```typescript
      { path: ':slug/settings', element: <Settings /> },
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 5: Manual smoke test**

Start the dev server:

```bash
cd ui && npm run dev
```

1. Navigate to `http://localhost:5173` and select a project
2. Confirm the ⚙ icon appears next to the active project slug in the sidebar
3. Click ⚙ — confirm you land on `/:slug/settings` and the form loads with the project's current values
4. Edit `sector` to something new, click **Save Settings**
5. Confirm the button briefly shows "Saved!"
6. Refresh the page — confirm the edited sector value persists

- [ ] **Step 6: Commit**

```bash
git add ui/src/pages/Settings.tsx ui/src/components/AppLayout.tsx ui/src/router.tsx
git commit -m "feat: add Settings page with gear icon in sidebar"
```

---

## Run Command (full backend suite)

```bash
pytest tests/ -v --ignore=tests/integration -q
```

Expected: 31 tests passing (26 pre-existing + 5 new in `test_projects_settings.py`)
