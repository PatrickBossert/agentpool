# SP7c — Output Viewer Improvements
## Design Specification
**Date:** 2026-04-19
**Status:** Approved for implementation planning
**Branch base:** `master` (post SP7b)
**Working directory:** `/Users/pboagents/Documents/agentpool1`

---

## 1. Scope

Make the ValueChain and Roadmap output pages display actual rendered content instead of raw metadata or placeholder text.

**In scope:**
- `GET /projects/{slug}/outputs/{id}/content` — serve raw file content for a given output record
- `ui/src/pages/ValueChain.tsx` — render Mermaid diagram via `mermaid.js`
- `ui/src/pages/Roadmap.tsx` — render HTML roadmap inside `<iframe srcDoc>`
- Unit tests for the new backend endpoint

**Out of scope:**
- Roadmap Gantt tab (existing placeholder remains)
- Editing or re-running outputs
- Any output type other than `value_chain` (Mermaid) and `roadmap` (HTML)

---

## 2. Architecture

```
GET /projects/{slug}/outputs/{id}/content
  └─ get_output_content(slug, output_id)
       ├─ fetch agent_output row WHERE id=? AND project slug matches
       ├─ read file at row["file_path"]
       └─ return { content, output_type }

ValueChain.tsx
  ├─ useQuery → GET /projects/{slug}/outputs/{id}/content
  └─ mermaid.render("vc-diagram", content) → SVG → injected via ref.innerHTML

Roadmap.tsx
  ├─ useQuery → GET /projects/{slug}/outputs/{id}/content
  └─ <iframe srcDoc={content} sandbox="allow-scripts" />
```

---

## 3. Backend Changes

### 3.1 `api/models.py`

New response model:

```python
class OutputContent(BaseModel):
    content: str
    output_type: str
```

### 3.2 `api/services/project_service.py`

New function:

```python
async def get_output_content(slug: str, output_id: int) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        row = await conn.execute_fetchone(
            "SELECT file_path, output_type FROM agent_outputs WHERE id=? AND project_id=?",
            (output_id, project["id"]),
        )
        if not row:
            return None
    file_path = Path(row["file_path"])
    if not file_path.exists():
        return {"not_found_on_disk": True}
    content = file_path.read_text(encoding="utf-8")
    return {"content": content, "output_type": row["output_type"]}
```

Notes:
- Uses the project's own SQLite DB (same pattern as all other service functions).
- The `project_id` check ensures an output belonging to a different project cannot be read via another slug.
- Returns a sentinel `{"not_found_on_disk": True}` so the router can distinguish 404-project vs 404-file.

### 3.3 `api/routers/projects.py`

New endpoint:

```python
from api.models import ProjectCreate, ProjectSettings, OutputContent, StatusResponse, ProjectResponse
from api.services.project_service import (
    create_project, get_project_status, list_all_projects,
    get_project_settings, update_project_settings, get_output_content,
)

@router.get("/{slug}/outputs/{output_id}/content", response_model=OutputContent)
async def get_output_content_endpoint(slug: str, output_id: int):
    result = await get_output_content(slug, output_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Output {output_id} not found for project '{slug}'")
    if result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Output file not found on disk")
    return result
```

---

## 4. Frontend Changes

### 4.1 `ui/src/types.ts`

```typescript
export interface OutputContent {
  content: string
  output_type: string
}
```

### 4.2 `ui/src/api/endpoints.ts`

```typescript
getOutputContent: (slug: string, outputId: number): Promise<OutputContent> =>
  api.get(`/projects/${slug}/outputs/${outputId}/content`).then(r => r.data),
```

### 4.3 `ui/src/pages/ValueChain.tsx`

Install dependency:

```bash
npm install mermaid
```

Module-level initialisation (runs once):

```typescript
import mermaid from 'mermaid'

mermaid.initialize({ startOnLoad: false, theme: 'dark' })
```

When a ValueChain output is selected (has `output_type === 'value_chain'`):

1. `useQuery(['outputContent', slug, selectedId], () => projectsApi.getOutputContent(slug!, selectedId))` fetches raw Mermaid source.
2. A `useRef<HTMLDivElement>(null)` (`svgContainerRef`) targets the diagram container.
3. `useEffect` watches `data?.content` — calls `mermaid.render('vc-' + selectedId, data.content)` (async, returns `{ svg }`), then sets `svgContainerRef.current.innerHTML = svg`.
   - The SVG here is **mermaid-generated** from our own agent-stored source (not user-supplied HTML), so direct innerHTML assignment is safe.
   - Wrap in try/catch — on mermaid parse error set an error state and show "Invalid diagram source".
4. Renders an empty `<div ref={svgContainerRef}>` inside a dark container below the output metadata row.
5. While loading: show a spinner / "Rendering…" placeholder.
6. On fetch error: show "Failed to load diagram".

### 4.4 `ui/src/pages/Roadmap.tsx`

When the Visual tab is active and an output exists (first output with `output_type === 'roadmap'`):

1. `useQuery(['outputContent', slug, outputId], () => projectsApi.getOutputContent(slug!, outputId))` fetches HTML string.
2. Renders:

```tsx
<iframe
  srcDoc={data.content}
  sandbox="allow-scripts"
  style={{ width: '100%', height: '520px', border: 'none', borderRadius: '6px' }}
  title="Roadmap"
/>
```

3. While loading: spinner.
4. On error: "Failed to load roadmap".
5. Gantt tab: existing placeholder text unchanged.

---

## 5. Testing

### `tests/test_outputs_content.py` (new)

Five tests using the existing `client` + tmp filesystem fixtures:

1. **`test_get_content_returns_mermaid_source`** — create project, write a `.md` file, insert `agent_outputs` row pointing to it, `GET /{slug}/outputs/{id}/content` → 200, `content` matches file, `output_type == "value_chain"`
2. **`test_get_content_unknown_project_404`** — GET for unknown slug → 404
3. **`test_get_content_unknown_output_404`** — valid project, output ID does not exist → 404
4. **`test_get_content_output_wrong_project_404`** — create two projects, use output ID from project A with project B's slug → 404
5. **`test_get_content_file_missing_on_disk_404`** — insert row with non-existent `file_path` → 404 with "Output file not found on disk"

### Run command

```bash
pytest tests/test_outputs_content.py -v
```

---

## 6. Notes

- `mermaid.render()` is async in mermaid v10+ and returns a Promise — `useEffect` must `await` it inside an async IIFE.
- The SVG produced by `mermaid.render()` is generated client-side from our own agent-stored Mermaid source (never raw user HTML input). It is injected via `ref.innerHTML` rather than React's `dangerouslySetInnerHTML` to keep the render path explicit.
- `<iframe sandbox="allow-scripts">` is intentionally restrictive — the roadmap HTML is self-contained (inline styles, no external resources) so it does not need `allow-same-origin` or `allow-forms`.
- The `output_id` path parameter is an integer — FastAPI validates this automatically; no extra guard needed in the router.
- Both frontend pages already fetch the output list via existing queries — this spec adds one additional query per selected output for its content.
