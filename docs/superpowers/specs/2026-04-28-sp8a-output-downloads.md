# SP8a — Output File Downloads
## Design Specification
**Date:** 2026-04-28
**Status:** Approved for implementation planning
**Branch base:** `master` (post SP7c)
**Working directory:** `/Users/pboagents/Documents/agentpool1`

---

## 1. Scope

Allow users to download any agent-generated output file (Mermaid `.md`, HTML, DOCX, XLSX, PPTX) directly from the UI. Downloads appear in two places: on the output-specific pages (ValueChain, Roadmap) and in a new "Generated Outputs" section on the Documents page.

**In scope:**
- `GET /projects/{slug}/outputs/{output_id}/download` — stream file with correct Content-Type and Content-Disposition headers
- `ui/src/utils/download.ts` — shared fetch + Blob download utility
- `ui/src/pages/ValueChain.tsx` — download button in metadata row
- `ui/src/pages/Roadmap.tsx` — download button on visual tab
- `ui/src/pages/Documents.tsx` — "Generated Outputs" section with download buttons
- Unit tests for the new backend endpoint

**Out of scope:**
- Bulk download / ZIP of all outputs
- Download of uploaded client documents (already downloadable via browser from their stored path)
- Preview of binary files (DOCX/XLSX/PPTX) — view-in-browser is not attempted

---

## 2. Architecture

```
GET /projects/{slug}/outputs/{output_id}/download
  └─ get_output_file(slug, output_id)
       ├─ same project/output guard as get_output_content
       └─ returns {"file_path": Path, "filename": str} | None | {"not_found_on_disk": True}

Router:
  └─ FileResponse(path, filename=..., media_type=..., headers={"X-Filename": filename})

Frontend:
  downloadOutput(slug, outputId, filename, token)
    ├─ fetch GET /api/projects/{slug}/outputs/{outputId}/download
    │    (Authorization: Bearer {token})
    ├─ response.blob() → Blob
    ├─ URL.createObjectURL(blob) → synthetic <a> click → save dialog
    └─ URL.revokeObjectURL(url)
```

---

## 3. Backend Changes

### 3.1 `api/services/project_service.py`

New function (same guard pattern as `get_output_content`):

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

### 3.2 Content-Type mapping

Used by the router to set the correct MIME type:

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
```

### 3.3 `api/routers/projects.py`

New endpoint (added after `get_output_content_endpoint`):

```python
from fastapi.responses import FileResponse
from api.services.project_service import (
    ...,
    get_output_file,
)

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

`FileResponse` sets `Content-Disposition: attachment; filename="{filename}"` automatically when `filename` is supplied.

---

## 4. Frontend Changes

### 4.1 `ui/src/utils/download.ts` (new)

```typescript
export async function downloadOutput(
  slug: string,
  outputId: number,
  filename: string,
  token: string,
): Promise<void> {
  const resp = await fetch(
    `/api/projects/${slug}/outputs/${outputId}/download`,
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

The `token` is sourced from `useAuth()` (already available in all pages). The `filename` is the basename of `agent_output.file_path` — passed in by each call site.

### 4.2 `ui/src/pages/ValueChain.tsx`

Replace the metadata row with:

```tsx
<div className="flex justify-between items-center mb-4">
  <span className="text-sm text-slate-200">{latest.agent_name}</span>
  <div className="flex items-center gap-3">
    <span className="text-xs text-slate-500">
      v{latest.version} · {latest.review_status}
    </span>
    <button
      onClick={() => downloadOutput(slug!, latest.id, latest.file_path.split('/').pop()!, token)}
      className="text-xs text-sky-400 hover:text-sky-300 transition-colors"
    >
      ↓ Download
    </button>
  </div>
</div>
```

Import `downloadOutput` from `../utils/download` and `token` from `useAuth()`.

### 4.3 `ui/src/pages/Roadmap.tsx`

On the visual tab, when `latest` exists, add a download button above the iframe:

```tsx
{latest && tab === 'visual' && (
  <div className="bg-surface-card rounded-xl overflow-hidden">
    <div className="flex justify-between items-center px-4 py-3 border-b border-slate-800">
      <span className="text-sm text-slate-200">{latest.agent_name}</span>
      <div className="flex items-center gap-3">
        <span className="text-xs text-slate-500">v{latest.version} · {latest.review_status}</span>
        <button
          onClick={() => downloadOutput(slug!, latest.id, latest.file_path.split('/').pop()!, token)}
          className="text-xs text-sky-400 hover:text-sky-300 transition-colors"
        >
          ↓ Download
        </button>
      </div>
    </div>
    {/* iframe content */}
    ...
  </div>
)}
```

### 4.4 `ui/src/pages/Documents.tsx`

Add a "Generated Outputs" section below the existing uploads list. Fetch outputs via the existing `projectsApi.outputs(slug)` query (already available — reuse or add a second `useQuery`):

```tsx
<section>
  <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
    Generated Outputs
  </h3>
  {outputs.length === 0 && (
    <p className="text-sm text-slate-500">No outputs yet — run the pipeline to generate artefacts.</p>
  )}
  <div className="space-y-2">
    {outputs.map((o) => (
      <div key={o.id} className="flex items-center justify-between bg-surface-card rounded-lg px-4 py-3">
        <div>
          <p className="text-sm font-medium text-slate-200">{o.agent_name}</p>
          <p className="text-xs text-slate-500">{o.output_type} · v{o.version} · {o.review_status}</p>
        </div>
        <button
          onClick={() => downloadOutput(slug!, o.id, o.file_path.split('/').pop()!, token)}
          className="text-xs text-sky-400 hover:text-sky-300 transition-colors"
        >
          ↓ Download
        </button>
      </div>
    ))}
  </div>
</section>
```

---

## 5. Testing

### `tests/test_outputs_download.py` (new)

Five tests using the existing `client` + tmp filesystem fixture pattern:

1. **`test_download_returns_file_bytes`** — create project, write a file, insert `agent_outputs` row, `GET /{slug}/outputs/{id}/download` → 200, response body matches file bytes, `Content-Disposition` header contains `attachment`, `X-Filename` header matches filename
2. **`test_download_unknown_project_404`** — GET for unknown slug → 404
3. **`test_download_unknown_output_404`** — valid project, output ID does not exist → 404
4. **`test_download_output_wrong_project_404`** — output belongs to project A, fetched via project B's slug → 404
5. **`test_download_file_missing_on_disk_404`** — row exists, file deleted → 404 with "not found on disk"

### Run command

```bash
pytest tests/test_outputs_download.py -v
```

---

## 6. Notes

- `FileResponse` from Starlette (included in FastAPI) handles chunked streaming automatically — no need to read the file into memory in the router.
- `filename.split('/').pop()!` on the frontend derives the basename from `AgentOutput.file_path`. This is safe because `file_path` is always an absolute server path written by agent tools — it always contains at least one `/`.
- The `X-Filename` header is included in the response so the frontend could also read it from `resp.headers.get('x-filename')` rather than computing it from `file_path`. Both approaches work; the call sites use `file_path.split('/').pop()` for simplicity.
- No `response_model` is set on the download endpoint — `FileResponse` is not a JSON response and does not need one.
- The Vite dev server proxies `/api/*` to `localhost:8000` — the fetch URL `/api/projects/...` resolves correctly in development. In production, the same proxy or nginx rule handles it.
