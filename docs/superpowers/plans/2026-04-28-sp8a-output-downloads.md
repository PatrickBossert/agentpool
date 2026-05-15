# SP8a Output File Downloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authenticated file download for agent-generated outputs — a backend streaming endpoint plus download buttons on ValueChain, Roadmap, and Documents pages.

**Architecture:** A new `GET /projects/{slug}/outputs/{output_id}/download` FastAPI endpoint returns a `FileResponse` with correct MIME type and `Content-Disposition: attachment`. The frontend uses a shared `downloadOutput()` utility that fetches the file with a Bearer token, creates a Blob URL, and triggers a synthetic anchor click to open the browser save dialog.

**Tech Stack:** FastAPI `FileResponse` (Starlette), Python `pathlib.Path`, TypeScript `fetch` + `Blob` + `URL.createObjectURL`, React + TanStack Query v5, `useAuth()` from `AuthContext.tsx`.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `api/services/project_service.py` | Modify | Add `get_output_file()` service function |
| `api/routers/projects.py` | Modify | Add `_CONTENT_TYPES`, `_content_type()`, download endpoint |
| `ui/src/utils/download.ts` | Create | Shared `downloadOutput()` fetch+Blob utility |
| `ui/src/pages/Documents.tsx` | Modify | Add download button to Agent Outputs rows |
| `ui/src/pages/ValueChain.tsx` | Modify | Add download button to metadata row |
| `ui/src/pages/Roadmap.tsx` | Modify | Add download button header on visual tab |
| `tests/test_outputs_download.py` | Create | 5 tests for the download endpoint |

---

### Task 1: Backend — service function, router endpoint, and tests

**Files:**
- Modify: `api/services/project_service.py` (append after line 169)
- Modify: `api/routers/projects.py` (append after line 83)
- Create: `tests/test_outputs_download.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_outputs_download.py`:

```python
import shutil
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, insert_agent_output, fetch_project

SLUG = "download-test"
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
async def test_download_returns_file_bytes(client):
    """Create project + write file + insert row → GET returns file bytes with correct headers."""
    await client.post("/projects", json=PROJECT)
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / SLUG / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    md_file = outputs_dir / "value_chain.md"
    md_file.write_bytes(b"graph LR\n  A --> B")
    output_id = await _insert_output(str(md_file), output_type="value_chain")

    resp = await client.get(f"/projects/{SLUG}/outputs/{output_id}/download")
    assert resp.status_code == 200
    assert resp.content == b"graph LR\n  A --> B"
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["x-filename"] == "value_chain.md"


@pytest.mark.asyncio
async def test_download_unknown_project_404(client):
    resp = await client.get("/projects/ghost-project/outputs/1/download")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_unknown_output_404(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get(f"/projects/{SLUG}/outputs/99999/download")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_output_wrong_project_404(client):
    """Output belongs to SLUG — cannot be fetched via other_slug."""
    other_slug = "other-download-test"
    settings = get_settings()
    other_db = Path(settings.database_dir) / f"{other_slug}.db"
    other_dir = Path(settings.projects_dir) / other_slug
    try:
        await client.post("/projects", json={**PROJECT, "client_slug": other_slug})
        await client.post("/projects", json=PROJECT)

        outputs_dir = Path(settings.projects_dir) / SLUG / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        md_file = outputs_dir / "vc.md"
        md_file.write_bytes(b"graph LR\n  A-->B")
        output_id = await _insert_output(str(md_file), output_type="value_chain")

        resp = await client.get(f"/projects/{other_slug}/outputs/{output_id}/download")
        assert resp.status_code == 404
    finally:
        other_db.unlink(missing_ok=True)
        if other_dir.exists():
            shutil.rmtree(other_dir)


@pytest.mark.asyncio
async def test_download_file_missing_on_disk_404(client):
    """Row exists in DB but file deleted from disk → 404 with 'not found on disk'."""
    await client.post("/projects", json=PROJECT)
    output_id = await _insert_output("/tmp/does-not-exist-sp8a-abc.md")

    resp = await client.get(f"/projects/{SLUG}/outputs/{output_id}/download")
    assert resp.status_code == 404
    assert "not found on disk" in resp.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest tests/test_outputs_download.py -v
```

Expected: All 5 tests FAIL — `get_output_file` not defined, endpoint not registered.

- [ ] **Step 3: Add `get_output_file` to `api/services/project_service.py`**

Append after the last line (line 169, end of `get_output_content`):

```python


async def get_output_file(slug: str, output_id: int) -> dict | None:
    """Locate the file for a given output record.

    Returns:
        None — project not found or output not found in this project's DB
        {"not_found_on_disk": True} — row exists but file deleted from disk
        {"file_path": Path, "filename": str} — success
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        async with conn.execute(
            "SELECT file_path FROM agent_outputs WHERE id=? AND project_id=?",
            (output_id, project["id"]),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
    file_path = Path(row["file_path"])
    if not file_path.exists():
        return {"not_found_on_disk": True}
    return {"file_path": file_path, "filename": file_path.name}
```

- [ ] **Step 4: Add the download endpoint to `api/routers/projects.py`**

First, update the imports at the top of the file. The current imports block is:

```python
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

Replace with:

```python
from pathlib import Path
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from api.database import get_db_path, get_connection, fetch_project, fetch_outputs_by_type
from api.models import ProjectCreate, ProjectSettings, OutputContent, StatusResponse, ProjectResponse
from api.services.project_service import (
    create_project,
    get_project_status,
    list_all_projects,
    get_project_settings,
    update_project_settings,
    get_output_content,
    get_output_file,
)
```

Then append after the last line of the file (line 83, end of `get_output_content_endpoint`):

```python


_CONTENT_TYPES = {
    ".md":   "text/markdown",
    ".html": "text/html",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


@router.get("/{slug}/outputs/{output_id}/download")
async def download_output_endpoint(slug: str, output_id: int):
    result = await get_output_file(slug, output_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Output {output_id} not found for project '{slug}'")
    if result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Output file not found on disk")
    file_path: Path = result["file_path"]
    filename: str = result["filename"]
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=_content_type(file_path),
        headers={"X-Filename": filename},
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_outputs_download.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 6: Run full suite to check for regressions**

```bash
pytest tests/ -x --ignore=tests/integration -q
```

Expected: Same pass/fail ratio as baseline (199 passing, 12 pre-existing failures on integration/auth/pptx).

- [ ] **Step 7: Commit**

```bash
git add api/services/project_service.py api/routers/projects.py tests/test_outputs_download.py
git commit -m "feat(sp8a): add output file download endpoint and tests"
```

---

### Task 2: Frontend download utility and Documents page button

**Files:**
- Create: `ui/src/utils/download.ts`
- Modify: `ui/src/pages/Documents.tsx`

- [ ] **Step 1: Create `ui/src/utils/download.ts`**

The frontend API client (`ui/src/api/client.ts`) uses `API_BASE = 'http://localhost:8000'` directly — there is no `/api` proxy prefix. The fetch URL must match this pattern.

```typescript
// ui/src/utils/download.ts
const API_BASE = 'http://localhost:8000'

export async function downloadOutput(
  slug: string,
  outputId: number,
  filename: string,
  token: string,
): Promise<void> {
  const resp = await fetch(
    `${API_BASE}/projects/${slug}/outputs/${outputId}/download`,
    { headers: { Authorization: `Bearer ${token}` } },
  )
  if (!resp.ok) throw new Error(`Download failed: ${resp.status}`)
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
```

- [ ] **Step 2: Add download button to `ui/src/pages/Documents.tsx`**

Add `useAuth` import and `downloadOutput` import at the top. The current imports are:

```typescript
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, ChangeEvent } from 'react'
import { projectsApi } from '../api/endpoints'
import type { ClientDocument, AgentOutput } from '../types'
```

Replace with:

```typescript
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, ChangeEvent } from 'react'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { downloadOutput } from '../utils/download'
import type { ClientDocument, AgentOutput } from '../types'
```

Add `const { token } = useAuth()` inside the `Documents` component, right after the `const qc = useQueryClient()` line:

```typescript
  const qc = useQueryClient()
  const { token } = useAuth()
```

Replace the Agent Outputs row (lines 105-115) — the inner content of the `{agentOutputs.map(...)}` block:

Current:
```tsx
              <div
                key={o.id}
                className="flex items-center justify-between bg-surface-card rounded-lg px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-slate-200">{o.agent_name}</p>
                  <p className="text-xs text-slate-500">{o.output_type} · v{o.version}</p>
                </div>
                <span className="text-xs text-slate-500">{o.review_status}</span>
              </div>
```

Replace with:
```tsx
              <div
                key={o.id}
                className="flex items-center justify-between bg-surface-card rounded-lg px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-slate-200">{o.agent_name}</p>
                  <p className="text-xs text-slate-500">{o.output_type} · v{o.version} · {o.review_status}</p>
                </div>
                <button
                  onClick={() => downloadOutput(slug, o.id, o.file_path.split('/').pop()!, token!)}
                  className="text-xs text-sky-400 hover:text-sky-300 transition-colors"
                >
                  ↓ Download
                </button>
              </div>
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npm run build 2>&1 | tail -20
```

Expected: Build succeeds with no TypeScript errors. If `AgentOutput` type is missing `file_path`, check `ui/src/types/index.ts` and add the field: `file_path: string`.

- [ ] **Step 4: Commit**

```bash
cd /Users/pboagents/Documents/agentpool1
git add ui/src/utils/download.ts ui/src/pages/Documents.tsx ui/src/types/index.ts
git commit -m "feat(sp8a): add downloadOutput utility and Documents page download buttons"
```

---

### Task 3: ValueChain and Roadmap download buttons

**Files:**
- Modify: `ui/src/pages/ValueChain.tsx`
- Modify: `ui/src/pages/Roadmap.tsx`

- [ ] **Step 1: Add download button to `ui/src/pages/ValueChain.tsx`**

Add imports at the top. Current imports end at line 6:

```typescript
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import mermaid from 'mermaid'
import { projectsApi } from '../api/endpoints'
```

Replace with:

```typescript
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import mermaid from 'mermaid'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { downloadOutput } from '../utils/download'
```

Add `const { token } = useAuth()` inside the component, right after the `const { slug } = useParams` line:

```typescript
  const { slug } = useParams<{ slug: string }>()
  const { token } = useAuth()
```

Replace the metadata row (lines 77-82 in the current file):

Current:
```tsx
          {/* Output metadata row */}
          <div className="flex justify-between items-center mb-4">
            <span className="text-sm text-slate-200">{latest.agent_name}</span>
            <span className="text-xs text-slate-500">
              v{latest.version} · {latest.review_status}
            </span>
          </div>
```

Replace with:
```tsx
          {/* Output metadata row */}
          <div className="flex justify-between items-center mb-4">
            <span className="text-sm text-slate-200">{latest.agent_name}</span>
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-500">
                v{latest.version} · {latest.review_status}
              </span>
              <button
                onClick={() => downloadOutput(slug!, latest.id, latest.file_path.split('/').pop()!, token!)}
                className="text-xs text-sky-400 hover:text-sky-300 transition-colors"
              >
                ↓ Download
              </button>
            </div>
          </div>
```

- [ ] **Step 2: Add download button to `ui/src/pages/Roadmap.tsx`**

Add imports at the top. Current imports end at line 5:

```typescript
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { projectsApi } from '../api/endpoints'
```

Replace with:

```typescript
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { downloadOutput } from '../utils/download'
```

Add `const { token } = useAuth()` inside the component, right after `const [tab, setTab] = useState<Tab>('visual')`:

```typescript
  const [tab, setTab] = useState<Tab>('visual')
  const { token } = useAuth()
```

Replace the visual tab content block (lines 67-84 in current file):

Current:
```tsx
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
```

Replace with:
```tsx
      {latest && tab === 'visual' && (
        <div className="bg-surface-card rounded-xl overflow-hidden">
          <div className="flex justify-between items-center px-4 py-3 border-b border-slate-800">
            <span className="text-sm text-slate-200">{latest.agent_name}</span>
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-500">v{latest.version} · {latest.review_status}</span>
              <button
                onClick={() => downloadOutput(slug!, latest.id, latest.file_path.split('/').pop()!, token!)}
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
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npm run build 2>&1 | tail -20
```

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 4: Run backend tests one final time**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest tests/test_outputs_download.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/pboagents/Documents/agentpool1
git add ui/src/pages/ValueChain.tsx ui/src/pages/Roadmap.tsx
git commit -m "feat(sp8a): add download buttons to ValueChain and Roadmap pages"
```

---

## Self-Review

**Spec coverage check:**
- ✅ `GET /projects/{slug}/outputs/{output_id}/download` — Task 1 Step 4
- ✅ `get_output_file` service function — Task 1 Step 3
- ✅ Content-Type mapping (`_CONTENT_TYPES` + `_content_type`) — Task 1 Step 4
- ✅ `FileResponse` with `filename=` + `X-Filename` header — Task 1 Step 4
- ✅ `ui/src/utils/download.ts` — Task 2 Step 1
- ✅ ValueChain download button — Task 3 Step 1
- ✅ Roadmap visual tab download button — Task 3 Step 2
- ✅ Documents page download buttons — Task 2 Step 2
- ✅ 5 tests (happy path + 4 error cases) — Task 1 Step 1

**URL path correction:** The spec document wrote `/api/projects/...` as the fetch URL. This is wrong — `ui/src/api/client.ts` uses `API_BASE = 'http://localhost:8000'` with no `/api` prefix. The plan correctly uses `http://localhost:8000/projects/${slug}/outputs/${outputId}/download`.

**Type consistency:** `AgentOutput` type in `ui/src/types/index.ts` must have `file_path: string`. Task 2 Step 3 includes a reminder to check and add this field if missing.

**`token!` non-null assertion:** `useAuth()` returns `token: string | null`. The `!` assertion is safe here because all output pages are behind authentication — the user cannot reach these pages without a valid session token.

**No placeholders found.**
