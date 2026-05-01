# SP8b — Gantt Chart for the Roadmap Tab
## Design Specification
**Date:** 2026-05-01
**Status:** Approved for implementation planning
**Branch base:** `master` (post SP8a)
**Working directory:** `/Users/pboagents/Documents/agentpool1`

---

## 1. Scope

Fill the placeholder Gantt tab on the Roadmap page with a real implementation-focused chart. The chart reads structured roadmap JSON data (initiatives + periods) and renders a grouped timeline table in React — no external charting library.

**Design principle:** The visual tab is customer-facing (organised by value stream). The Gantt tab is implementation-facing (organised by initiative, grouped by category or value stream for project planning purposes).

**In scope:**
- Modify `agents/tools/html_roadmap.py` to also write `roadmap_data.json` alongside `roadmap.html` and insert a second `agent_outputs` row
- `GET /projects/{slug}/roadmap-data` — return parsed roadmap JSON to the frontend
- `ui/src/pages/Roadmap.tsx` — replace stub Gantt tab with a grouped table + group-by toggle + download button
- `ui/src/types.ts` — add `RoadmapData` and `Initiative` types
- `ui/src/api/endpoints.ts` — add `roadmapData()` API method
- Unit tests for the new backend endpoint and the HtmlRoadmapTool JSON output

**Out of scope:**
- Changes to the visual tab
- True start/end duration bars (initiatives have a single delivery period, not a date range)
- Filtering, search, or sorting beyond the group-by toggle
- Gantt export to image or PDF

---

## 2. Architecture

```
HtmlRoadmapTool._run(roadmap_data, ...)
  ├─ writes roadmap.html  (existing — output_type="html")
  └─ writes roadmap_data.json  (new — output_type="roadmap_data")
       └─ insert_agent_output_sync(..., output_type="roadmap_data")

GET /projects/{slug}/roadmap-data
  └─ get_roadmap_data(slug)
       ├─ fetch latest agent_output WHERE output_type="roadmap_data"
       └─ returns parsed JSON dict

Frontend (Roadmap.tsx — gantt tab):
  useQuery(['roadmap-data', slug])  →  roadmapData: RoadmapData | null
  groupBy: 'category' | 'value_stream'  (useState)
  grouped initiatives  →  <GanttTable>  (pure CSS table, no library)
  downloadOutput(slug, roadmapDataOutputId, 'roadmap_data.json', token)
```

---

## 3. Backend Changes

### 3.1 `agents/tools/html_roadmap.py`

After the existing `file_path.write_text(rendered, encoding="utf-8")` + `insert_agent_output_sync` calls, add:

```python
import json

# Write raw roadmap data as JSON for the Gantt tab
json_path = outputs_dir / (filename.replace(".html", "_data.json"))
json_path.write_text(json.dumps(roadmap_data, ensure_ascii=False), encoding="utf-8")
insert_agent_output_sync(
    slug=self.slug,
    agent_name=agent_name,
    output_type="roadmap_data",
    file_path=str(json_path),
)
```

The JSON filename mirrors the HTML filename: `roadmap.html` → `roadmap_data.json`.

### 3.2 `api/services/project_service.py`

New function (add `import json` to the top of `project_service.py` if not already present):

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

### 3.3 `api/routers/projects.py`

New endpoint (added after `get_roadmap`):

```python
from api.services.project_service import (
    ...,
    get_roadmap_data,
)

@router.get("/{slug}/roadmap-data")
async def get_roadmap_data_endpoint(slug: str):
    result = await get_roadmap_data(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No roadmap data found for project '{slug}'")
    if isinstance(result, dict) and result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Roadmap data file not found on disk")
    return result
```

No `response_model` — returns an arbitrary JSON dict.

---

## 4. Frontend Changes

### 4.1 `ui/src/types.ts`

Add two new interfaces:

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

### 4.2 `ui/src/api/endpoints.ts`

Add to `projectsApi`:

```typescript
roadmapData: (slug: string): Promise<RoadmapData> =>
  apiClient.get<RoadmapData>(`/projects/${slug}/roadmap-data`).then((r) => r.data),
```

Import `RoadmapData` in the import block.

### 4.3 `ui/src/pages/Roadmap.tsx`

**New state and query** (add alongside existing `tab` state):

```typescript
type GroupBy = 'category' | 'value_stream'
const [groupBy, setGroupBy] = useState<GroupBy>('category')

// Only fetch when on gantt tab
const { data: roadmapData } = useQuery({
  queryKey: ['roadmap-data', slug],
  queryFn: () => projectsApi.roadmapData(slug!),
  enabled: !!slug && tab === 'gantt',
})
```

**Category colour mapping** (matches `HtmlRoadmapTool`):

```typescript
const CATEGORY_COLOURS: Record<string, string> = {
  enabling: '#3b82f6',
  operating_model: '#f59e0b',
  business_change: '#22c55e',
}
```

**Grouping logic:**

- `groupBy === 'category'`: derive unique categories from `roadmapData.initiatives`, render one group header per category, list initiatives in that category beneath it
- `groupBy === 'value_stream'`: for each value stream in `roadmapData.value_streams`, list initiatives where `i.value_streams.includes(vs)` (an initiative may appear in multiple groups)

**Gantt tab JSX** (replaces the stub `{latest && tab === 'gantt' && ...}` block):

```tsx
{tab === 'gantt' && (
  <div className="bg-surface-card rounded-xl overflow-hidden">
    {/* Controls row */}
    <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
      <div className="flex items-center gap-3">
        <span className="text-xs text-slate-500 uppercase tracking-widest">Group by</span>
        <div className="flex rounded-lg overflow-hidden border border-slate-700">
          {(['category', 'value_stream'] as GroupBy[]).map((g) => (
            <button
              key={g}
              onClick={() => setGroupBy(g)}
              className={`px-3 py-1 text-xs capitalize transition-colors ${
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

    {/* Empty state */}
    {!roadmapData && (
      <p className="text-sm text-slate-500 p-4">
        Gantt chart will appear here once initiatives are identified.
      </p>
    )}

    {/* Gantt table */}
    {roadmapData && <GanttTable data={roadmapData} groupBy={groupBy} />}
  </div>
)}
```

**`roadmapDataOutput`** is derived from the existing `outputs` query:
```typescript
const roadmapDataOutput = outputs.find((o) => o.output_type === 'roadmap_data') ?? null
```

**`GanttTable` component** — extracted as a named function within the same file (not a separate file — it's only used here):

```tsx
function GanttTable({ data, groupBy }: { data: RoadmapData; groupBy: GroupBy }) {
  const groups =
    groupBy === 'category'
      ? [...new Set(data.initiatives.map((i) => i.category))]
      : data.value_streams

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-slate-900">
            <th className="px-4 py-2 text-left text-slate-500 font-medium min-w-[180px]">
              Initiative
            </th>
            {data.periods.map((p) => (
              <th key={p} className="px-3 py-2 text-center text-slate-500 font-medium min-w-[90px]">
                {p}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const members =
              groupBy === 'category'
                ? data.initiatives.filter((i) => i.category === group)
                : data.initiatives.filter((i) => i.value_streams.includes(group))
            const colour = groupBy === 'category'
              ? (CATEGORY_COLOURS[group] ?? '#9ca3af')
              : '#6366f1'
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
                {members.map((initiative) => (
                  <tr key={initiative.title} className="border-t border-slate-800">
                    <td className="px-4 py-2 text-slate-300">{initiative.title}</td>
                    {data.periods.map((p) => {
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
```

`Fragment` is imported from React alongside the existing imports.

---

## 5. Testing

### `tests/test_gantt.py` (new)

Four tests following the `test_outputs_content.py` pattern:

1. **`test_get_roadmap_data_returns_json`** — create project, write `roadmap_data.json`, insert `roadmap_data` output row → `GET /projects/{slug}/roadmap-data` returns 200 with `periods` and `initiatives` keys
2. **`test_get_roadmap_data_unknown_project_404`** — unknown slug → 404
3. **`test_get_roadmap_data_no_output_404`** — valid project, no `roadmap_data` row → 404
4. **`test_html_roadmap_tool_writes_json`** — call `HtmlRoadmapTool._run()` with minimal roadmap data → confirm `roadmap_data.json` file exists on disk and contains correct keys (`periods`, `initiatives`, `value_streams`)

### Run command

```bash
pytest tests/test_gantt.py -v
```

---

## 6. Notes

- `insert_agent_output_sync` in `HtmlRoadmapTool` uses an upsert pattern (update version if row exists, insert if not). Both the HTML and JSON outputs will version independently but always align — same agent call writes both.
- The `roadmapData` query is only enabled when `tab === 'gantt'`, so it doesn't fire on initial page load when the visual tab is shown.
- `roadmapDataOutput` is derived from the existing `outputs` query — no additional network request needed to get the output ID for the download button.
- Category colours in `CATEGORY_COLOURS` must match `_CATEGORY_COLOURS` in `html_roadmap.py` exactly (blue/amber/green).
- An initiative belonging to multiple value streams appears once per value stream group when `groupBy === 'value_stream'`. This is intentional — cross-cutting initiatives are visible in each relevant stream.
- `Fragment` must be imported from React: `import { useState, Fragment } from 'react'`.
