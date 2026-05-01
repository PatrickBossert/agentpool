# SP8b Gantt Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a working Gantt chart to the Roadmap page's "gantt" tab, reading structured JSON written by the HtmlRoadmapTool alongside the existing HTML output.

**Architecture:** `HtmlRoadmapTool` is extended to also write a `roadmap_data.json` file and insert a second `agent_outputs` row (`output_type="roadmap_data"`). A new `GET /projects/{slug}/roadmap-data` endpoint reads this JSON and returns it parsed. The Gantt tab in `Roadmap.tsx` fetches this endpoint, renders a grouped CSS table with a category/value-stream toggle, and offers a JSON download via the existing `downloadOutput` utility.

**Tech Stack:** Python/FastAPI backend, React + TanStack Query v5 + TypeScript frontend, pure CSS table (no charting library), existing `downloadOutput` utility from SP8a.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `agents/tools/html_roadmap.py` | Modify | Also write `roadmap_data.json` + insert second output row |
| `api/services/project_service.py` | Modify | Add `get_roadmap_data()` service function |
| `api/routers/projects.py` | Modify | Add `GET /{slug}/roadmap-data` endpoint |
| `ui/src/types.ts` | Modify | Add `Initiative` and `RoadmapData` interfaces |
| `ui/src/api/endpoints.ts` | Modify | Add `roadmapData()` API method |
| `ui/src/pages/Roadmap.tsx` | Modify | Replace stub Gantt tab with full chart + toggle + download |
| `tests/test_gantt.py` | Create | 4 tests: endpoint coverage + HtmlRoadmapTool JSON output |

---

### Task 1: Backend — `get_roadmap_data` service + endpoint + tests

**Files:**
- Modify: `api/services/project_service.py` (append after line 169)
- Modify: `api/routers/projects.py` (modify imports + append endpoint)
- Create: `tests/test_gantt.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gantt.py`:

```python
import json
import shutil
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, insert_agent_output, fetch_project

SLUG = "gantt-test"
PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "rail",
}

MINIMAL_ROADMAP = {
    "periods": ["Q1 2025", "Q2 2025"],
    "value_streams": ["Customer Portal"],
    "stakeholder_groups": [],
    "initiatives": [
        {
            "title": "Digital Onboarding",
            "value_streams": ["Customer Portal"],
            "period": "Q1 2025",
            "category": "enabling",
            "complexity_score": 7,
        }
    ],
    "propositions": [],
}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    proj_dir = Path(settings.projects_dir) / SLUG
    db_path.unlink(missing_ok=True)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)


async def _insert_roadmap_data(file_path: str) -> int:
    """Insert a roadmap_data agent_output row and return its ID."""
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        return await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name="test_agent",
            output_type="roadmap_data",
            file_path=file_path,
            version=1,
        )


@pytest.mark.asyncio
async def test_get_roadmap_data_returns_json(client):
    """Create project + write JSON + insert row → GET returns 200 with correct keys."""
    await client.post("/projects", json=PROJECT)
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / SLUG / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    json_file = outputs_dir / "roadmap_data.json"
    json_file.write_text(json.dumps(MINIMAL_ROADMAP), encoding="utf-8")
    await _insert_roadmap_data(str(json_file))

    resp = await client.get(f"/projects/{SLUG}/roadmap-data")
    assert resp.status_code == 200
    data = resp.json()
    assert "periods" in data
    assert "initiatives" in data
    assert data["periods"] == ["Q1 2025", "Q2 2025"]
    assert data["initiatives"][0]["title"] == "Digital Onboarding"


@pytest.mark.asyncio
async def test_get_roadmap_data_unknown_project_404(client):
    resp = await client.get("/projects/ghost-project/roadmap-data")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_roadmap_data_no_output_404(client):
    """Valid project with no roadmap_data output row → 404."""
    await client.post("/projects", json=PROJECT)
    resp = await client.get(f"/projects/{SLUG}/roadmap-data")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_roadmap_data_file_missing_on_disk_404(client):
    """Row exists but JSON file deleted → 404."""
    await client.post("/projects", json=PROJECT)
    await _insert_roadmap_data("/tmp/does-not-exist-sp8b-abc.json")

    resp = await client.get(f"/projects/{SLUG}/roadmap-data")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest tests/test_gantt.py -v
```

Expected: All 4 FAIL — `get_roadmap_data` not defined, endpoint not registered.

- [ ] **Step 3: Add `get_roadmap_data` to `api/services/project_service.py`**

Append after the last line of the file (after `get_output_file`, currently line ~195):

```python


async def get_roadmap_data(slug: str) -> dict | None:
    """Return parsed roadmap JSON for the Gantt tab.

    Returns:
        None — project not found or no roadmap_data output exists
        {"not_found_on_disk": True} — row exists but file deleted from disk
        dict — parsed roadmap_data JSON (periods, initiatives, etc.)
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        async with conn.execute(
            "SELECT file_path FROM agent_outputs "
            "WHERE project_id=? AND output_type=? ORDER BY version DESC LIMIT 1",
            (project["id"], "roadmap_data"),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
    file_path = Path(row["file_path"])
    if not file_path.exists():
        return {"not_found_on_disk": True}
    return json.loads(file_path.read_text(encoding="utf-8"))
```

Note: `json` is already imported at the top of `project_service.py`.

- [ ] **Step 4: Add the endpoint to `api/routers/projects.py`**

Update the `from api.services.project_service import (...)` block — add `get_roadmap_data` to the import list:

```python
from api.services.project_service import (
    create_project,
    get_project_status,
    list_all_projects,
    get_project_settings,
    update_project_settings,
    get_output_content,
    get_output_file,
    get_roadmap_data,
)
```

Then append after the last line of the file (after `download_output_endpoint`):

```python


@router.get("/{slug}/roadmap-data")
async def get_roadmap_data_endpoint(slug: str):
    result = await get_roadmap_data(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No roadmap data found for project '{slug}'")
    if isinstance(result, dict) and result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Roadmap data file not found on disk")
    return result
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest tests/test_gantt.py -v
```

Expected: All 4 PASS.

- [ ] **Step 6: Run full suite to check for regressions**

```bash
pytest tests/ --ignore=tests/integration --ignore=tests/test_auth.py --ignore=tests/test_powerpoint_output.py -q
```

Expected: 200+ passing, zero new failures.

- [ ] **Step 7: Commit**

```bash
git add api/services/project_service.py api/routers/projects.py tests/test_gantt.py
git commit -m "feat(sp8b): add roadmap-data endpoint and tests"
```

---

### Task 2: Crew tool — write JSON alongside HTML

**Files:**
- Modify: `agents/tools/html_roadmap.py`
- Test: `tests/test_gantt.py` (add one test to the existing file)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gantt.py`:

```python
@pytest.mark.asyncio
async def test_html_roadmap_tool_writes_json(client):
    """HtmlRoadmapTool._run() writes roadmap_data.json alongside roadmap.html."""
    await client.post("/projects", json=PROJECT)
    settings = get_settings()

    from agents.tools.html_roadmap import HtmlRoadmapTool
    tool = HtmlRoadmapTool(slug=SLUG)
    tool._run(
        roadmap_data=MINIMAL_ROADMAP,
        filename="roadmap.html",
        agent_name="test_roadmap_agent",
    )

    outputs_dir = Path(settings.projects_dir) / SLUG / "outputs"
    json_file = outputs_dir / "roadmap_data.json"
    assert json_file.exists(), "roadmap_data.json was not written"
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert "periods" in data
    assert "initiatives" in data
    assert "value_streams" in data
```

- [ ] **Step 2: Run the new test to confirm it fails**

```bash
pytest tests/test_gantt.py::test_html_roadmap_tool_writes_json -v
```

Expected: FAIL — `roadmap_data.json` does not exist.

- [ ] **Step 3: Modify `agents/tools/html_roadmap.py`**

Add `import json` at the top of the file (after the existing imports):

```python
import html
import json
from pathlib import Path
```

In the `_run` method, after the existing `insert_agent_output_sync` call (inside the `try` block), add:

```python
            # Also write raw JSON for the Gantt tab
            json_path = outputs_dir / filename.replace(".html", "_data.json")
            json_path.write_text(
                json.dumps(roadmap_data, ensure_ascii=False), encoding="utf-8"
            )
            insert_agent_output_sync(
                slug=self.slug,
                agent_name=agent_name,
                output_type="roadmap_data",
                file_path=str(json_path),
            )
```

The full updated `_run` method `try` block becomes:

```python
        try:
            rendered = self._render_html(roadmap_data)
            file_path.write_text(rendered, encoding="utf-8")
            insert_agent_output_sync(
                slug=self.slug,
                agent_name=agent_name,
                output_type="html",
                file_path=str(file_path),
            )
            # Also write raw JSON for the Gantt tab
            json_path = outputs_dir / filename.replace(".html", "_data.json")
            json_path.write_text(
                json.dumps(roadmap_data, ensure_ascii=False), encoding="utf-8"
            )
            insert_agent_output_sync(
                slug=self.slug,
                agent_name=agent_name,
                output_type="roadmap_data",
                file_path=str(json_path),
            )
        except (OSError, ValueError, KeyError) as e:
            return f"Error: render failed — {e}"
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
pytest tests/test_gantt.py::test_html_roadmap_tool_writes_json -v
```

Expected: PASS.

- [ ] **Step 5: Run full gantt test suite**

```bash
pytest tests/test_gantt.py -v
```

Expected: All 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/tools/html_roadmap.py tests/test_gantt.py
git commit -m "feat(sp8b): HtmlRoadmapTool writes roadmap_data.json alongside HTML"
```

---

### Task 3: Frontend — types, API method, and Gantt tab

**Files:**
- Modify: `ui/src/types.ts` (append two interfaces)
- Modify: `ui/src/api/endpoints.ts` (add `roadmapData` method)
- Modify: `ui/src/pages/Roadmap.tsx` (replace stub, add `GanttTable` component)

- [ ] **Step 1: Add types to `ui/src/types.ts`**

Append after the `OutputContent` interface (after line 72):

```typescript
export interface Initiative {
  title: string
  value_streams: string[]
  period: string
  category: string
  complexity_score: number | string
}

export interface RoadmapData {
  periods: string[]
  value_streams: string[]
  stakeholder_groups: string[]
  initiatives: Initiative[]
  propositions: unknown[]
}
```

- [ ] **Step 2: Add `roadmapData` to `ui/src/api/endpoints.ts`**

Add `RoadmapData` to the import block at the top:

```typescript
import type {
  Project,
  ProjectStatus,
  AgentOutput,
  ClientDocument,
  ProjectSettings,
  OutputContent,
  RoadmapData,
  TokenResponse,
} from '../types'
```

Add `roadmapData` to the `projectsApi` object, after `getOutputContent`:

```typescript
  roadmapData: (slug: string): Promise<RoadmapData> =>
    apiClient.get<RoadmapData>(`/projects/${slug}/roadmap-data`).then((r) => r.data),
```

- [ ] **Step 3: Rewrite `ui/src/pages/Roadmap.tsx`**

Read the current file first. Replace the entire file content with:

```tsx
// ui/src/pages/Roadmap.tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState, Fragment } from 'react'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { downloadOutput } from '../utils/download'
import type { RoadmapData, Initiative } from '../types'

type Tab = 'visual' | 'gantt'
type GroupBy = 'category' | 'value_stream'

const CATEGORY_COLOURS: Record<string, string> = {
  enabling: '#3b82f6',
  operating_model: '#f59e0b',
  business_change: '#22c55e',
}

function GanttTable({ data, groupBy }: { data: RoadmapData; groupBy: GroupBy }) {
  const groups =
    groupBy === 'category'
      ? [...new Set(data.initiatives.map((i: Initiative) => i.category))]
      : data.value_streams

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-slate-900">
            <th className="px-4 py-2 text-left text-slate-500 font-medium min-w-[180px]">
              Initiative
            </th>
            {data.periods.map((p: string) => (
              <th key={p} className="px-3 py-2 text-center text-slate-500 font-medium min-w-[90px]">
                {p}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((group: string) => {
            const members =
              groupBy === 'category'
                ? data.initiatives.filter((i: Initiative) => i.category === group)
                : data.initiatives.filter((i: Initiative) => i.value_streams.includes(group))
            const colour =
              groupBy === 'category' ? (CATEGORY_COLOURS[group] ?? '#9ca3af') : '#6366f1'
            return (
              <Fragment key={group}>
                <tr className="bg-slate-900/60 border-t-2 border-slate-800">
                  <td
                    colSpan={data.periods.length + 1}
                    className="px-4 py-1.5 text-xs font-semibold uppercase tracking-widest"
                    style={{ color: colour }}
                  >
                    ● {group.replace(/_/g, ' ')}
                  </td>
                </tr>
                {members.map((initiative: Initiative) => (
                  <tr key={initiative.title} className="border-t border-slate-800">
                    <td className="px-4 py-2 text-slate-300">{initiative.title}</td>
                    {data.periods.map((p: string) => {
                      const active = initiative.period === p
                      return (
                        <td
                          key={p}
                          className="px-1.5 py-1 border-l border-slate-800 text-center"
                          style={{ background: active ? `${colour}10` : undefined }}
                        >
                          {active && (
                            <div
                              className="rounded flex items-center justify-center h-5 text-white font-semibold"
                              style={{ background: colour, fontSize: '0.68rem' }}
                            >
                              {initiative.complexity_score}
                            </div>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function Roadmap() {
  const { slug } = useParams<{ slug: string }>()
  const [tab, setTab] = useState<Tab>('visual')
  const [groupBy, setGroupBy] = useState<GroupBy>('category')
  const { token } = useAuth()

  const { data: outputs = [], isLoading } = useQuery({
    queryKey: ['roadmap', slug],
    queryFn: () => projectsApi.roadmap(slug!),
    enabled: !!slug,
  })

  const latest = outputs[0] ?? null
  const roadmapDataOutput = outputs.find((o) => o.output_type === 'roadmap_data') ?? null

  const { data: contentData, isLoading: contentLoading, isError: contentError } = useQuery({
    queryKey: ['outputContent', slug, latest?.id],
    queryFn: () => projectsApi.getOutputContent(slug!, latest!.id),
    enabled: !!slug && !!latest && tab === 'visual',
  })

  const { data: roadmapData } = useQuery({
    queryKey: ['roadmap-data', slug],
    queryFn: () => projectsApi.roadmapData(slug!),
    enabled: !!slug && tab === 'gantt',
  })

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-100">Roadmap</h2>
        <div className="flex rounded-lg overflow-hidden border border-slate-700" role="tablist">
          {(['visual', 'gantt'] as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={`px-4 py-1.5 text-sm capitalize transition-colors ${
                tab === t
                  ? 'bg-brand text-white'
                  : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}

      {!isLoading && outputs.length === 0 && (
        <div className="bg-surface-card rounded-xl p-8 text-center">
          <p className="text-slate-400 text-sm">
            {tab === 'visual'
              ? 'Awaiting Roadmap Generator output — visual timeline will appear here.'
              : 'Gantt chart will appear here once initiatives are identified.'}
          </p>
          <p className="text-slate-600 text-xs mt-2">
            Run all Discovery, Value Design, and Architecture crews to generate roadmap data.
          </p>
        </div>
      )}

      {latest && tab === 'visual' && (
        <div className="bg-surface-card rounded-xl overflow-hidden">
          <div className="flex justify-between items-center px-4 py-3 border-b border-slate-800">
            <span className="text-sm text-slate-200">{latest.agent_name}</span>
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-500">v{latest.version} · {latest.review_status}</span>
              <button
                onClick={() => downloadOutput(slug!, latest.id, latest.file_path.split('/').pop() ?? latest.output_type, token!).catch(console.error)}
                className="text-xs text-sky-400 hover:text-sky-300 transition-colors"
              >
                ↓ Download
              </button>
            </div>
          </div>
          {contentLoading && (
            <p className="text-sm text-slate-500 p-4">Loading roadmap…</p>
          )}
          {contentError && !contentLoading && (
            <p className="text-sm text-red-400 p-4">Failed to load roadmap.</p>
          )}
          {contentData && (
            <iframe
              srcDoc={contentData.content}
              sandbox="allow-scripts"
              style={{ width: '100%', height: '520px', border: 'none' }}
              title="Roadmap"
            />
          )}
        </div>
      )}

      {tab === 'gantt' && (
        <div className="bg-surface-card rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-500 uppercase tracking-widest">Group by</span>
              <div className="flex rounded-lg overflow-hidden border border-slate-700">
                {(['category', 'value_stream'] as GroupBy[]).map((g) => (
                  <button
                    key={g}
                    onClick={() => setGroupBy(g)}
                    className={`px-3 py-1 text-xs transition-colors ${
                      groupBy === g ? 'bg-brand text-white' : 'text-slate-400 hover:bg-slate-800'
                    }`}
                  >
                    {g === 'value_stream' ? 'Value Stream' : 'Category'}
                  </button>
                ))}
              </div>
            </div>
            {roadmapDataOutput && (
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-500">
                  {roadmapDataOutput.agent_name} · v{roadmapDataOutput.version}
                </span>
                <button
                  onClick={() =>
                    downloadOutput(
                      slug!,
                      roadmapDataOutput.id,
                      'roadmap_data.json',
                      token!,
                    ).catch(console.error)
                  }
                  className="text-xs text-sky-400 hover:text-sky-300 transition-colors"
                >
                  ↓ Download JSON
                </button>
              </div>
            )}
          </div>
          {!roadmapData && (
            <p className="text-sm text-slate-500 p-4">
              Gantt chart will appear here once initiatives are identified.
            </p>
          )}
          {roadmapData && <GanttTable data={roadmapData} groupBy={groupBy} />}
        </div>
      )}

      {latest && tab === 'gantt' && !outputs.length && (
        <div className="bg-surface-card rounded-xl p-4">
          <p className="text-sm text-slate-400">
            Run all Discovery, Value Design, and Architecture crews to generate roadmap data.
          </p>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npx tsc --noEmit 2>&1 | head -20
```

Expected: No errors.

- [ ] **Step 5: Run full backend test suite**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest tests/test_gantt.py -v
```

Expected: All 5 PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/pboagents/Documents/agentpool1
git add ui/src/types.ts ui/src/api/endpoints.ts ui/src/pages/Roadmap.tsx
git commit -m "feat(sp8b): Gantt tab with group-by toggle and JSON download"
```

---

## Self-Review

**Spec coverage:**
- ✅ `HtmlRoadmapTool` writes `roadmap_data.json` + inserts `roadmap_data` output row — Task 2
- ✅ `get_roadmap_data(slug)` service function — Task 1 Step 3
- ✅ `GET /projects/{slug}/roadmap-data` endpoint — Task 1 Step 4
- ✅ `RoadmapData` and `Initiative` types — Task 3 Step 1
- ✅ `roadmapData()` API method in `endpoints.ts` — Task 3 Step 2
- ✅ Gantt tab with grouped table — Task 3 Step 3
- ✅ Group-by toggle (category / value stream) — Task 3 Step 3
- ✅ Download JSON button using `downloadOutput` — Task 3 Step 3
- ✅ 4 endpoint tests + 1 tool test — Tasks 1 and 2

**Placeholder scan:** No TBD, TODO, or vague steps. All code is complete.

**Type consistency:**
- `RoadmapData` defined in Task 3 Step 1, used in `GanttTable` props and `useQuery` return — consistent ✓
- `Initiative` defined in Task 3 Step 1, used in `GanttTable` filter/map — consistent ✓
- `roadmapData()` returns `Promise<RoadmapData>` in Task 3 Step 2, consumed as `RoadmapData | undefined` from `useQuery` — consistent ✓
- `GroupBy` type defined at top of `Roadmap.tsx`, used in `GanttTable` props and `useState` — consistent ✓
- `CATEGORY_COLOURS` keys (`enabling`, `operating_model`, `business_change`) match `_CATEGORY_COLOURS` in `html_roadmap.py` — consistent ✓

**One note:** The `outputs` query fetches all outputs for the project (via `projectsApi.roadmap`). Check `api/routers/projects.py` — the `/roadmap` endpoint returns only `output_type="html"` rows. This means `roadmapDataOutput = outputs.find(o => o.output_type === 'roadmap_data')` will always be `null` because the `roadmap` endpoint filters to HTML only.

**Fix:** The Gantt download button needs the `roadmapDataOutput`. Add a second query using `projectsApi.outputs(slug)` (which returns ALL outputs), or add a dedicated endpoint. The simpler fix: derive `roadmapDataOutput` from a separate `outputs` query.

Add to `Roadmap.tsx` (after the `outputs` query):

```typescript
  const { data: allOutputs = [] } = useQuery({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.outputs(slug!),
    enabled: !!slug && tab === 'gantt',
  })
  const roadmapDataOutput = allOutputs.find((o) => o.output_type === 'roadmap_data') ?? null
```

And remove the `roadmapDataOutput` line derived from `outputs` in the main component body.

**Updated Task 3 Step 3** — the Roadmap component should include this additional query. The corrected component body (the queries section only, replace from `const latest = ...`):

```typescript
  const latest = outputs[0] ?? null

  const { data: allOutputs = [] } = useQuery({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.outputs(slug!),
    enabled: !!slug && tab === 'gantt',
  })
  const roadmapDataOutput = allOutputs.find((o) => o.output_type === 'roadmap_data') ?? null

  const { data: contentData, isLoading: contentLoading, isError: contentError } = useQuery({
    queryKey: ['outputContent', slug, latest?.id],
    queryFn: () => projectsApi.getOutputContent(slug!, latest!.id),
    enabled: !!slug && !!latest && tab === 'visual',
  })

  const { data: roadmapData } = useQuery({
    queryKey: ['roadmap-data', slug],
    queryFn: () => projectsApi.roadmapData(slug!),
    enabled: !!slug && tab === 'gantt',
  })
```

This is the corrected version to implement — use it in Task 3 Step 3 instead of the version that derives `roadmapDataOutput` from `outputs`.
