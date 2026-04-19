# SP7c — Output Viewer Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render actual Mermaid diagrams on the Value Chain page and actual HTML on the Roadmap visual tab, served via a new `GET /projects/{slug}/outputs/{id}/content` backend endpoint.

**Architecture:** A new content endpoint reads a file from disk (identified by `agent_outputs.file_path`) and returns `{ content, output_type }`. ValueChain.tsx feeds that content to mermaid.js and injects the resulting SVG using `DOMParser` + `replaceChildren`; Roadmap.tsx feeds it into an `<iframe srcDoc>`.

**Tech Stack:** Python/FastAPI (backend), React + TanStack Query v5 + mermaid v10 (frontend)

---

## File Map

| File | Change |
|------|--------|
| `api/models.py` | Add `OutputContent` Pydantic model |
| `api/services/project_service.py` | Add `get_output_content(slug, output_id)` |
| `api/routers/projects.py` | Add `GET /{slug}/outputs/{output_id}/content` endpoint |
| `tests/test_outputs_content.py` | New — 5 backend tests |
| `ui/src/types.ts` | Add `OutputContent` interface |
| `ui/src/api/endpoints.ts` | Add `getOutputContent` method to `projectsApi` |
| `ui/src/pages/ValueChain.tsx` | Rewrite to fetch + render Mermaid SVG |
| `ui/src/pages/Roadmap.tsx` | Rewrite visual tab to render HTML in `<iframe srcDoc>` |

---

## Task 1: Backend — content endpoint + tests

**Files:**
- Modify: `api/models.py`
- Modify: `api/services/project_service.py`
- Modify: `api/routers/projects.py`
- Create: `tests/test_outputs_content.py`

---

- [ ] **Step 1: Write the failing tests**

Create `tests/test_outputs_content.py`:

```python
import shutil
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, insert_agent_output, fetch_project

SLUG = "content-test"
PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "rail",
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


async def _insert_output(file_path: str, output_type: str = "value_chain") -> int:
    """Helper: insert an agent_output row for SLUG and return its ID."""
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        return await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name="test_agent",
            output_type=output_type,
            file_path=file_path,
            version=1,
        )


@pytest.mark.asyncio
async def test_get_content_returns_mermaid_source(client):
    """Create a project + real file + output row → GET returns file content."""
    await client.post("/projects", json=PROJECT)
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / SLUG / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    md_file = outputs_dir / "value_chain.md"
    md_file.write_text("graph LR\n  A --> B", encoding="utf-8")
    output_id = await _insert_output(str(md_file), output_type="value_chain")

    resp = await client.get(f"/projects/{SLUG}/outputs/{output_id}/content")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "graph LR\n  A --> B"
    assert data["output_type"] == "value_chain"


@pytest.mark.asyncio
async def test_get_content_unknown_project_404(client):
    resp = await client.get("/projects/ghost-project/outputs/1/content")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_content_unknown_output_404(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get(f"/projects/{SLUG}/outputs/99999/content")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_content_output_wrong_project_404(client):
    """Output row belongs to SLUG — cannot be fetched via other_slug."""
    other_slug = "other-content-test"
    settings = get_settings()
    other_db = Path(settings.database_dir) / f"{other_slug}.db"
    other_dir = Path(settings.projects_dir) / other_slug
    try:
        await client.post("/projects", json={**PROJECT, "client_slug": other_slug})
        await client.post("/projects", json=PROJECT)

        outputs_dir = Path(settings.projects_dir) / SLUG / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        md_file = outputs_dir / "vc.md"
        md_file.write_text("graph LR\n  A-->B", encoding="utf-8")
        output_id = await _insert_output(str(md_file), output_type="value_chain")

        # Try to read SLUG's output via other_slug — should be 404
        resp = await client.get(f"/projects/{other_slug}/outputs/{output_id}/content")
        assert resp.status_code == 404
    finally:
        other_db.unlink(missing_ok=True)
        if other_dir.exists():
            shutil.rmtree(other_dir)


@pytest.mark.asyncio
async def test_get_content_file_missing_on_disk_404(client):
    """Row exists in DB but file was deleted from disk → 404."""
    await client.post("/projects", json=PROJECT)
    output_id = await _insert_output("/tmp/does-not-exist-sp7c-abc.md")

    resp = await client.get(f"/projects/{SLUG}/outputs/{output_id}/content")
    assert resp.status_code == 404
    assert "not found on disk" in resp.json()["detail"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest tests/test_outputs_content.py -v
```

Expected: 5 errors — `404` for the missing endpoint (the routes don't exist yet).

- [ ] **Step 3: Add `OutputContent` model to `api/models.py`**

Open `api/models.py`. After the `ProjectSettings` class (after the `slack_channel` field, before `class ProjectResponse`), add:

```python
class OutputContent(BaseModel):
    content: str
    output_type: str
```

The section around the insertion point should look like:

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


class OutputContent(BaseModel):
    content: str
    output_type: str


class ProjectResponse(BaseModel):
    id: int
    slug: str
    llm_mode: str
    sector: str
    status: str
```

- [ ] **Step 4: Add `get_output_content` to `api/services/project_service.py`**

Change the models import line from:

```python
from api.models import ProjectCreate, ProjectSettings
```

to:

```python
from api.models import ProjectCreate, ProjectSettings, OutputContent  # noqa: F401
```

Then add this function at the very end of the file (after `update_project_settings`):

```python
async def get_output_content(slug: str, output_id: int) -> dict | None:
    """Return file content for a given output record.

    Returns:
        None — project not found or output not found in this project's DB
        {"not_found_on_disk": True} — row exists but file deleted from disk
        {"content": str, "output_type": str} — success
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        async with conn.execute(
            "SELECT file_path, output_type FROM agent_outputs WHERE id=? AND project_id=?",
            (output_id, project["id"]),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
    file_path = Path(row["file_path"])
    if not file_path.exists():
        return {"not_found_on_disk": True}
    content = file_path.read_text(encoding="utf-8")
    return {"content": content, "output_type": row["output_type"]}
```

- [ ] **Step 5: Add endpoint to `api/routers/projects.py`**

Replace the import block at the top of `api/routers/projects.py` with:

```python
# api/routers/projects.py
from fastapi import APIRouter, HTTPException, Response
from api.database import get_db_path, get_connection, fetch_project, fetch_outputs_by_type
from api.models import ProjectCreate, ProjectSettings, OutputContent, StatusResponse, ProjectResponse
from api.services.project_service import (
    create_project,
    get_project_status,
    list_all_projects,
    get_project_settings,
    update_project_settings,
    get_output_content,
)
```

Then add the following at the end of the file (after the `patch_settings_endpoint` function):

```python
@router.get("/{slug}/outputs/{output_id}/content", response_model=OutputContent)
async def get_output_content_endpoint(slug: str, output_id: int):
    result = await get_output_content(slug, output_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Output {output_id} not found for project '{slug}'")
    if result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Output file not found on disk")
    return result
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest tests/test_outputs_content.py -v
```

Expected output:
```
tests/test_outputs_content.py::test_get_content_returns_mermaid_source PASSED
tests/test_outputs_content.py::test_get_content_unknown_project_404 PASSED
tests/test_outputs_content.py::test_get_content_unknown_output_404 PASSED
tests/test_outputs_content.py::test_get_content_output_wrong_project_404 PASSED
tests/test_outputs_content.py::test_get_content_file_missing_on_disk_404 PASSED
5 passed
```

- [ ] **Step 7: Run full test suite to check for regressions**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest --tb=short -q
```

Expected: all previously passing tests still pass (189 + 5 new = 194 total).

- [ ] **Step 8: Commit**

```bash
git add api/models.py api/services/project_service.py api/routers/projects.py tests/test_outputs_content.py
git commit -m "feat(sp7c): add GET /projects/{slug}/outputs/{id}/content endpoint"
```

---

## Task 2: ValueChain page — mermaid rendering

**Files:**
- Modify: `ui/src/types.ts`
- Modify: `ui/src/api/endpoints.ts`
- Modify: `ui/src/pages/ValueChain.tsx`

No backend changes. No new frontend unit tests (mermaid requires full browser SVG support — jsdom does not support it).

---

- [ ] **Step 1: Install mermaid**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npm install mermaid
```

Expected: `mermaid` added to `dependencies` in `package.json`.

- [ ] **Step 2: Add `OutputContent` interface to `ui/src/types.ts`**

Open `ui/src/types.ts`. After the closing `}` of the `ProjectSettings` interface (after line 67), add:

```typescript
export interface OutputContent {
  content: string
  output_type: string
}
```

- [ ] **Step 3: Add `getOutputContent` to `ui/src/api/endpoints.ts`**

Replace the import at the top of `ui/src/api/endpoints.ts`:

```typescript
import type {
  Project,
  ProjectStatus,
  AgentOutput,
  ClientDocument,
  ProjectSettings,
  OutputContent,
  TokenResponse,
} from '../types'
```

Inside the `projectsApi` object, after the `updateSettings` entry, add:

```typescript
  getOutputContent: (slug: string, outputId: number): Promise<OutputContent> =>
    apiClient.get<OutputContent>(`/projects/${slug}/outputs/${outputId}/content`).then((r) => r.data),
```

- [ ] **Step 4: Rewrite `ui/src/pages/ValueChain.tsx`**

Replace the entire file with:

```typescript
// ui/src/pages/ValueChain.tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import mermaid from 'mermaid'
import { projectsApi } from '../api/endpoints'

mermaid.initialize({ startOnLoad: false, theme: 'dark' })

export default function ValueChain() {
  const { slug } = useParams<{ slug: string }>()

  const { data: outputs = [], isLoading } = useQuery({
    queryKey: ['value-chain', slug],
    queryFn: () => projectsApi.valueChain(slug!),
    enabled: !!slug,
  })

  // Pick the latest output record (API returns DESC order)
  const latest = outputs[0] ?? null

  const { data: contentData, isLoading: contentLoading, isError: contentError } = useQuery({
    queryKey: ['outputContent', slug, latest?.id],
    queryFn: () => projectsApi.getOutputContent(slug!, latest!.id),
    enabled: !!slug && !!latest,
  })

  const svgContainerRef = useRef<HTMLDivElement>(null)
  const [renderError, setRenderError] = useState(false)

  useEffect(() => {
    if (!contentData?.content || !svgContainerRef.current) return
    const container = svgContainerRef.current
    setRenderError(false)
    ;(async () => {
      try {
        const { svg } = await mermaid.render(
          'vc-diagram-' + (latest?.id ?? 0),
          contentData.content,
        )
        // Use DOMParser to safely parse the SVG string into a DOM node
        // (avoids innerHTML; mermaid's output is trusted — generated from
        // our own stored Mermaid source, not user-supplied HTML)
        const parser = new DOMParser()
        const svgDoc = parser.parseFromString(svg, 'image/svg+xml')
        const svgEl = svgDoc.documentElement
        container.replaceChildren(svgEl)
      } catch {
        setRenderError(true)
        container.replaceChildren()
      }
    })()
  }, [contentData?.content, latest?.id])

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold text-slate-100 mb-4">Value Chain</h2>

      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}

      {!isLoading && outputs.length === 0 && (
        <div className="bg-surface-card rounded-xl p-8 text-center">
          <p className="text-slate-400 text-sm">Awaiting Value Chain Mapper output.</p>
          <p className="text-slate-600 text-xs mt-2">
            Run the Discovery crew to generate the value chain analysis.
          </p>
        </div>
      )}

      {latest && (
        <div className="bg-surface-card rounded-xl p-4">
          {/* Output metadata row */}
          <div className="flex justify-between items-center mb-4">
            <span className="text-sm text-slate-200">{latest.agent_name}</span>
            <span className="text-xs text-slate-500">
              v{latest.version} · {latest.review_status}
            </span>
          </div>

          {/* Diagram area */}
          {contentLoading && (
            <p className="text-sm text-slate-500">Rendering diagram…</p>
          )}
          {contentError && !contentLoading && (
            <p className="text-sm text-red-400">Failed to load diagram.</p>
          )}
          {renderError && (
            <p className="text-sm text-red-400">Invalid diagram source.</p>
          )}
          {/* SVG inserted here via DOMParser + replaceChildren */}
          <div ref={svgContainerRef} className="overflow-auto" />
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Verify TypeScript compiles without errors**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/pboagents/Documents/agentpool1
git add ui/src/types.ts ui/src/api/endpoints.ts ui/src/pages/ValueChain.tsx ui/package.json ui/package-lock.json
git commit -m "feat(sp7c): render mermaid diagram in ValueChain page"
```

---

## Task 3: Roadmap page — iframe rendering

**Files:**
- Modify: `ui/src/pages/Roadmap.tsx`

`OutputContent` type and `getOutputContent` API method are already in place from Task 2.

---

- [ ] **Step 1: Rewrite `ui/src/pages/Roadmap.tsx`**

Replace the entire file with:

```typescript
// ui/src/pages/Roadmap.tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { projectsApi } from '../api/endpoints'

type Tab = 'visual' | 'gantt'

export default function Roadmap() {
  const { slug } = useParams<{ slug: string }>()
  const [tab, setTab] = useState<Tab>('visual')

  const { data: outputs = [], isLoading } = useQuery({
    queryKey: ['roadmap', slug],
    queryFn: () => projectsApi.roadmap(slug!),
    enabled: !!slug,
  })

  // Pick the latest output record (API returns DESC order)
  const latest = outputs[0] ?? null

  const { data: contentData, isLoading: contentLoading, isError: contentError } = useQuery({
    queryKey: ['outputContent', slug, latest?.id],
    queryFn: () => projectsApi.getOutputContent(slug!, latest!.id),
    // Only fetch when on the visual tab and an output exists
    enabled: !!slug && !!latest && tab === 'visual',
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

      {latest && tab === 'gantt' && (
        <div className="bg-surface-card rounded-xl p-4">
          <p className="text-sm text-slate-400">Gantt data available — full chart in SP4.</p>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles without errors**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Run full backend test suite to confirm no regressions**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest --tb=short -q
```

Expected: 194 tests passing, 0 failures.

- [ ] **Step 4: Commit**

```bash
cd /Users/pboagents/Documents/agentpool1
git add ui/src/pages/Roadmap.tsx
git commit -m "feat(sp7c): render HTML roadmap in iframe on Roadmap page"
```
