# SP9a — Business Plan Page
## Design Specification
**Date:** 2026-05-03
**Status:** Approved for implementation planning
**Branch base:** `master`
**Working directory:** `/Users/pboagents/Documents/agentpool1`

---

## 1. Scope

Add a dedicated Business Plan page (`/:slug/business-plan`) that gives the three business plan outputs (DOCX, PPTX, XLSX) prominent placement and surfaces the six financial summary metrics extracted server-side from the Excel workbook.

**In scope:**
- `GET /projects/{slug}/financial-summary` — reads Sheet 2 of the latest `excel` output with openpyxl, returns the 6 metrics as JSON
- `ui/src/pages/BusinessPlan.tsx` — new page with a financial metrics grid and three output cards
- `ui/src/types.ts` — add `FinancialSummary` interface
- `ui/src/api/endpoints.ts` — add `financialSummary(slug)` method
- `ui/src/components/AppLayout.tsx` — add "Business Plan" nav item after Roadmap
- `ui/src/router.tsx` — add `/:slug/business-plan` route
- Unit tests for the new backend endpoint

**Out of scope:**
- Inline DOCX/PPTX preview
- Editing or re-running the financial model from the UI
- Cashflow chart or per-period breakdown

---

## 2. Architecture

```
GET /projects/{slug}/financial-summary
  └─ get_financial_summary(slug)
       ├─ fetch latest agent_output WHERE output_type="excel"
       ├─ open file with openpyxl (read_only=True)
       ├─ read Sheet 2 ("Financial Summary") rows 2–7, column B
       └─ return FinancialSummaryResponse dict

Frontend (BusinessPlan.tsx):
  useQuery(['financial-summary', slug])  →  FinancialSummary | null
  useQuery(['outputs', slug])            →  OutputResponse[]  (already cached)
  docxOutput  = outputs.find(o => o.output_type === 'docx')
  pptxOutput  = outputs.find(o => o.output_type === 'pptx')
  excelOutput = outputs.find(o => o.output_type === 'excel')
  →  <FinancialMetricsGrid>  +  three <OutputCard> components
```

---

## 3. Backend Changes

### 3.1 `api/services/project_service.py`

New function (add `import openpyxl` inside the function body to avoid a top-level import):

```python
async def get_financial_summary(slug: str) -> dict | None:
    """Return parsed financial summary metrics from the latest excel output.

    Returns:
        None — project not found or no excel output exists
        {"not_found_on_disk": True} — row exists but file deleted
        dict — six metric keys extracted from Sheet 2
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        async with conn.execute(
            "SELECT file_path FROM agent_outputs "
            "WHERE project_id=? AND output_type=? ORDER BY created_at DESC LIMIT 1",
            (project["id"], "excel"),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
    file_path = Path(row["file_path"])
    if not file_path.exists():
        return {"not_found_on_disk": True}
    import openpyxl
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb["Financial Summary"]
    # Rows 2–7, column B — fixed structure written by FinancialModelTool
    keys = ["npv", "irr", "payback_period", "max_borrowing", "total_investment", "total_benefits"]
    return {key: ws.cell(row=i + 2, column=2).value for i, key in enumerate(keys)}
```

### 3.2 `api/routers/projects.py`

New endpoint (add after `get_roadmap_data_endpoint`):

```python
from api.services.project_service import (
    ...,
    get_financial_summary,
)

@router.get("/{slug}/financial-summary")
async def get_financial_summary_endpoint(slug: str):
    result = await get_financial_summary(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No financial model found for project '{slug}'")
    if isinstance(result, dict) and result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Financial model file not found on disk")
    return result
```

No `response_model` — returns an arbitrary dict.

---

## 4. Frontend Changes

### 4.1 `ui/src/types.ts`

Add one new interface:

```typescript
export interface FinancialSummary {
  npv: number | null
  irr: number | null
  payback_period: string | null
  max_borrowing: number | null
  total_investment: number | null
  total_benefits: number | null
}
```

### 4.2 `ui/src/api/endpoints.ts`

Add to `projectsApi`:

```typescript
financialSummary: (slug: string): Promise<FinancialSummary> =>
  apiClient.get<FinancialSummary>(`/projects/${slug}/financial-summary`).then((r) => r.data),
```

Import `FinancialSummary` in the import block.

### 4.3 `ui/src/components/AppLayout.tsx`

Add "Business Plan" to `navItems` after Roadmap:

```typescript
{ to: `/${slug}/roadmap`, label: 'Roadmap' },
{ to: `/${slug}/business-plan`, label: 'Business Plan' },
{ to: `/${slug}/documents`, label: 'Documents' },
```

### 4.4 `ui/src/router.tsx`

Add import and route:

```typescript
import BusinessPlan from './pages/BusinessPlan'

// inside children:
{ path: ':slug/business-plan', element: <BusinessPlan /> },
```

Add after the `':slug/roadmap'` route.

### 4.5 `ui/src/pages/BusinessPlan.tsx` (new file)

```tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { downloadOutput } from '../utils/download'
import type { FinancialSummary, OutputResponse } from '../types'

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmt_currency(v: number | null): string {
  if (v === null || v === undefined) return '—'
  const abs = Math.abs(v)
  if (abs >= 1_000_000) return `£${(v / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `£${(v / 1_000).toFixed(0)}k`
  return `£${v.toFixed(0)}`
}

function fmt_percent(v: number | null): string {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(1)}%`
}

// ── Sub-components ────────────────────────────────────────────────────────────

function MetricCard({
  label,
  value,
  colour,
}: {
  label: string
  value: string
  colour: string
}) {
  return (
    <div className="bg-surface rounded-lg p-3">
      <p className="text-xs text-slate-500 uppercase tracking-widest mb-1">{label}</p>
      <p className="text-xl font-bold" style={{ color: colour }}>
        {value}
      </p>
    </div>
  )
}

const OUTPUT_META: Record<string, { label: string; colour: string }> = {
  docx: { label: 'Business Plan', colour: '#3b82f6' },
  pptx: { label: 'Executive Presentation', colour: '#f59e0b' },
  excel: { label: 'Cost/Benefit Model', colour: '#22c55e' },
}

function OutputCard({
  output,
  slug,
  token,
}: {
  output: OutputResponse
  slug: string
  token: string
}) {
  const meta = OUTPUT_META[output.output_type] ?? { label: output.output_type, colour: '#6366f1' }
  const ext = output.output_type.toUpperCase()
  const filename = output.file_path.split('/').pop() ?? `${output.output_type}`
  return (
    <div className="bg-surface-card rounded-xl px-4 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span
          className="rounded px-2 py-0.5 text-xs font-bold tracking-wide"
          style={{ background: `${meta.colour}20`, color: meta.colour }}
        >
          {ext}
        </span>
        <div>
          <p className="text-sm text-slate-200 font-medium">{meta.label}</p>
          <p className="text-xs text-slate-500 mt-0.5">
            {output.agent_name} · v{output.version} · {output.review_status}
          </p>
        </div>
      </div>
      <button
        onClick={() => downloadOutput(slug, output.id, filename, token).catch(console.error)}
        className="text-xs text-sky-400 hover:text-sky-300 border border-sky-900/40 rounded px-2.5 py-1.5 transition-colors"
      >
        ↓ Download
      </button>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function BusinessPlan() {
  const { slug } = useParams<{ slug: string }>()
  const { token } = useAuth()

  const { data: summary } = useQuery({
    queryKey: ['financial-summary', slug],
    queryFn: () => projectsApi.financialSummary(slug!),
    enabled: !!slug,
    retry: false,
  })

  const { data: outputs = [] } = useQuery({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.outputs(slug!),
    enabled: !!slug,
  })

  const docxOutput = outputs.find((o) => o.output_type === 'docx') ?? null
  const pptxOutput = outputs.find((o) => o.output_type === 'pptx') ?? null
  const excelOutput = outputs.find((o) => o.output_type === 'excel') ?? null
  const hasOutputs = !!(docxOutput || pptxOutput || excelOutput)

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-slate-100">Business Plan</h2>

      {/* Financial metrics */}
      {summary && (
        <section>
          <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
            Financial Summary
          </h3>
          <div className="grid grid-cols-3 gap-3">
            <MetricCard label="NPV" value={fmt_currency(summary.npv)} colour="#22c55e" />
            <MetricCard label="IRR" value={fmt_percent(summary.irr)} colour="#22c55e" />
            <MetricCard
              label="Payback Period"
              value={summary.payback_period ?? '—'}
              colour="#f1f5f9"
            />
            <MetricCard
              label="Total Investment"
              value={fmt_currency(summary.total_investment)}
              colour="#f59e0b"
            />
            <MetricCard
              label="Total Benefits"
              value={fmt_currency(summary.total_benefits)}
              colour="#22c55e"
            />
            <MetricCard
              label="Max Borrowing"
              value={fmt_currency(summary.max_borrowing)}
              colour="#f87171"
            />
          </div>
        </section>
      )}

      {/* Output cards */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Outputs
        </h3>
        {!hasOutputs && (
          <p className="text-sm text-slate-500">
            Business plan outputs will appear here once the Business Plan Generator has run.
          </p>
        )}
        <div className="space-y-2">
          {docxOutput && (
            <OutputCard output={docxOutput} slug={slug!} token={token!} />
          )}
          {pptxOutput && (
            <OutputCard output={pptxOutput} slug={slug!} token={token!} />
          )}
          {excelOutput && (
            <OutputCard output={excelOutput} slug={slug!} token={token!} />
          )}
        </div>
      </section>
    </div>
  )
}
```

---

## 5. Testing

### `tests/test_business_plan_api.py` (new)

Three tests following the `test_gantt.py` pattern:

1. **`test_get_financial_summary_returns_metrics`** — create project, write a minimal valid XLSX with Sheet 2 containing the 6 rows, insert `excel` output row → `GET /projects/{slug}/financial-summary` returns 200 with all 6 keys
2. **`test_get_financial_summary_unknown_project_404`** — unknown slug → 404
3. **`test_get_financial_summary_no_output_404`** — valid project, no `excel` row → 404

```bash
pytest tests/test_business_plan_api.py -v
```

---

## 6. Notes

- `openpyxl` is already a project dependency (used by `FinancialModelTool`). Import it inside the function body to avoid loading it at module import time.
- `read_only=True, data_only=True` on `load_workbook` avoids formula evaluation and is faster for extraction.
- The `financial-summary` query uses `retry: false` — a 404 is expected when no business plan has been run yet, and React Query should not retry it.
- The `outputs` query is already cached from Dashboard polling; the Business Plan page benefits from this without an extra network request.
- `fmt_currency` formats values ≥ 1M as `£4.2M`, ≥ 1k as `£850k`, otherwise raw `£NNN`. This matches the mockup.
- `irr` is stored as a decimal (e.g. `0.234`) — multiply by 100 and format as `23.4%`.
- If `npv` is negative the green colour still renders; the value itself (e.g. `£-0.4M`) communicates the sign. No special negative-case colour logic needed.
