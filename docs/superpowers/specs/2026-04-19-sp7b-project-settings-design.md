# SP7b — Project Settings Page
## Design Specification
**Date:** 2026-04-19
**Status:** Approved for implementation planning
**Branch base:** `master` (post SP7a)
**Working directory:** `/Users/pboagents/Documents/agentpool1`

---

## 1. Scope

Add a Settings page that lets users view and edit a project's configuration after creation. All 8 editable fields from `ProjectCreate` (everything except `client_slug`, which is immutable) are exposed. Changes are committed via a single Save button.

**In scope:**
- `GET /projects/{slug}/settings` — return current project config
- `PATCH /projects/{slug}/settings` — update config in SQLite + rewrite `config.yaml`
- `ui/src/pages/Settings.tsx` — settings form page
- ⚙ icon in sidebar next to active project, linking to `/:slug/settings`
- Unit tests for all new backend code

**Out of scope:**
- Changing `client_slug` (immutable — it is the directory name and DB key)
- Per-field auto-save or per-section save
- Config validation beyond Pydantic types (e.g. no check that `crews_enabled` entries are known crew names)
- Deleting a project

---

## 2. Architecture

```
GET /projects/{slug}/settings
  └─ get_project_settings(slug)
       └─ fetch_project(conn) → deserialize config_json → return ProjectSettings

PATCH /projects/{slug}/settings  (body: ProjectSettings)
  └─ update_project_settings(slug, settings)
       ├─ update_project_config(conn, ...)   → UPDATE projects SET config_json=?, llm_mode=?, sector=?
       └─ atomic rewrite of config.yaml      (tempfile + os.replace, same as create_project)

UI: Settings.tsx
  ├─ useQuery → GET /projects/{slug}/settings  (populates form)
  └─ useMutation → PATCH /projects/{slug}/settings  (Save button)
```

---

## 3. Backend Changes

### 3.1 `api/models.py`

New model — same fields as `ProjectCreate` minus `client_slug`:

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

### 3.2 `api/database.py`

New helper (follows keyword-only pattern):

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

### 3.3 `api/services/project_service.py`

Two new functions:

```python
async def get_project_settings(slug: str) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        config = json.loads(project["config_json"])
        # Strip client_slug — not part of ProjectSettings
        config.pop("client_slug", None)
        return config


async def update_project_settings(slug: str, settings: "ProjectSettings") -> dict | None:
    if not get_db_path(slug).exists():
        return None
    settings_dict = settings.model_dump()
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        # Rebuild full config (re-add slug for yaml consistency)
        full_config = {"client_slug": slug, **settings_dict}
        await update_project_config(
            conn,
            project_id=project["id"],
            llm_mode=settings.llm_mode,
            sector=settings.sector,
            config_json=json.dumps(full_config),
        )

    # Atomically rewrite config.yaml
    settings_dir = Path(get_settings().projects_dir) / slug
    config_path = settings_dir / "config.yaml"
    fd, tmp_path = tempfile.mkstemp(dir=settings_dir, suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(full_config, f, default_flow_style=False)
        os.replace(tmp_path, config_path)
    except Exception:
        os.unlink(tmp_path)
        raise

    return settings_dict
```

### 3.4 `api/routers/projects.py`

Two new endpoints:

```python
from api.models import ProjectCreate, ProjectSettings, StatusResponse, ProjectResponse
from api.services.project_service import (
    create_project, get_project_status, list_all_projects,
    get_project_settings, update_project_settings,
)

@router.get("/{slug}/settings", response_model=ProjectSettings)
async def get_settings(slug: str):
    result = await get_project_settings(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.patch("/{slug}/settings", response_model=ProjectSettings)
async def patch_settings(slug: str, req: ProjectSettings):
    result = await update_project_settings(slug, req)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result
```

---

## 4. Frontend Changes

### 4.1 `ui/src/types.ts`

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

### 4.2 `ui/src/api/endpoints.ts`

```typescript
getSettings: (slug: string): Promise<ProjectSettings> =>
  api.get(`/projects/${slug}/settings`).then(r => r.data),

updateSettings: (slug: string, data: ProjectSettings): Promise<ProjectSettings> =>
  api.patch(`/projects/${slug}/settings`, data).then(r => r.data),
```

### 4.3 `ui/src/pages/Settings.tsx` (new)

- `useQuery(['settings', slug], () => projectsApi.getSettings(slug!))` populates initial form state
- Local `useState<ProjectSettings>` tracks edits
- `useMutation` calls `projectsApi.updateSettings` on Save
- On success: invalidate `['settings', slug]` query and show a brief success state on the button ("Saved!")
- On error: show an inline error message
- Fields rendered:
  - **Sector** — `<input type="text">`
  - **LLM Mode** — `<select>` (standard / sensitive / fallback)
  - **Roadmap Time Axis** — `<select>` (quarters / years / horizons)
  - **Slack Channel** — `<input type="text">`
  - **Stakeholder Groups** — tag input (type + Enter to add, × to remove)
  - **Value Stream Labels** — tag input (type + Enter to add, × to remove)
  - **Crews Enabled** — checkboxes for each of the 5 known crew names
  - **Review Gates** — toggle (checkbox styled as a pill)
- Single **Save Settings** button at the bottom right

### 4.4 `ui/src/components/AppLayout.tsx`

In the sidebar project list, when a project is active (`slug === p.slug`), render a `⚙` link to `/:slug/settings` alongside the slug button:

```tsx
{slug === p.slug && (
  <button
    onClick={() => navigate(`/${p.slug}/settings`)}
    className="text-slate-500 hover:text-slate-300 text-xs"
    title="Settings"
  >
    ⚙
  </button>
)}
```

### 4.5 `ui/src/router.tsx`

```tsx
{ path: ':slug/settings', element: <Settings /> },
```

---

## 5. Testing

### `tests/test_projects_settings.py` (new)

Five tests using the existing `client` fixture pattern:

1. **`test_get_settings_returns_config`** — create project, GET `/{slug}/settings`, assert all fields match what was passed at creation
2. **`test_get_settings_unknown_project_404`** — GET `/{slug}/settings` for unknown slug → 404
3. **`test_patch_settings_updates_db`** — PATCH with changed `sector` and `llm_mode`, then GET → response reflects changes
4. **`test_patch_settings_rewrites_yaml`** — after PATCH, read `config.yaml` from disk, assert `sector` field matches patched value
5. **`test_patch_settings_unknown_project_404`** — PATCH for unknown slug → 404

### Run command

```bash
pytest tests/test_projects_settings.py -v
```

---

## 6. Notes

- `config.yaml` stores `client_slug` at the top level (written by `create_project`). On PATCH, the full config including `client_slug` is rewritten so the file stays consistent with what crew factories expect.
- The ⚙ icon only appears when a project is selected (i.e. `slug` is in the URL params). It is not shown on the empty-state sidebar.
- The Save button shows a brief "Saved!" label on success (no separate toast library needed — local `useState` suffices).
- Tag inputs are implemented as controlled components with a hidden `<input>` inside a styled `<div>` — no external dependency required.
