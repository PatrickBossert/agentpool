# SP9a — Business Plan Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated Business Plan page (`/:slug/business-plan`) that surfaces the six financial summary metrics from the Excel workbook and provides download cards for the DOCX, PPTX, and XLSX outputs.

**Architecture:** A new `GET /projects/{slug}/financial-summary` endpoint reads Sheet 2 of the latest `excel` output with openpyxl and returns the six metrics. The frontend `BusinessPlan.tsx` page queries this endpoint plus the existing `outputs` list, renders a 3-column metrics grid and three output cards with download buttons. Nav and routing are wired in `AppLayout.tsx` and `router.tsx`.

**Tech Stack:** FastAPI, aiosqlite, openpyxl, React 18, TanStack Query v5, React Router v6, TypeScript, Tailwind CSS.

---

## File Map

| File | Change |
|------|--------|
| `tests/test_business_plan_api.py` | Create — 3 endpoint tests |
| `api/services/project_service.py` | Modify — add `get_financial_summary` |
| `api/routers/projects.py` | Modify — add endpoint + import |
| `ui/src/types.ts` | Modify — add `FinancialSummary` interface |
| `ui/src/api/endpoints.ts` | Modify — add `financialSummary` method + import |
| `ui/src/components/AppLayout.tsx` | Modify — add "Business Plan" nav item |
| `ui/src/router.tsx` | Modify — add import + route |
| `ui/src/pages/BusinessPlan.tsx` | Create — full page component |

---

## Task 1: Backend — financial-summary service, endpoint, and tests

**Files:**
- Create: `tests/test_business_plan_api.py`
- Modify: `api/services/project_service.py` (after `get_roadmap_data`)
- Modify: `api/routers/projects.py` (after `get_roadmap_data_endpoint`)

**Context:** The pattern matches `test_gantt.py` + `project_service.get_roadmap_data`. The `excel` output is produced by `FinancialModelTool`, which always writes a "Financial Summary" sheet as Sheet 2 with six labelled rows at positions 2–7, column B. The conftest fixture `client` is an async httpx test client available to all tests.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_business_plan_api.py`:

```python
import shutil
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, insert_agent_output, fetch_project

SLUG = "bp-test"
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


def _write_excel_file(path: Path) -> None:
    """Write a minimal XLSX with the Financial Summary sheet that FinancialModelTool produces."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Cashflow Model"
    ws2 = wb.create_sheet("Financial Summary")
    rows = [
        ("NPV (£)", 4_200_000.0),
        ("IRR", 0.234),
        ("Payback Period", "Q3 2026"),
        ("Maximum Borrowing Requirement (£)", -1_100_000.0),
        ("Total Investment (£)", 2_800_000.0),
        ("Total Benefits over Horizon (£)", 9_600_000.0),
    ]
    for i, (label, value) in enumerate(rows, start=2):
        ws2.cell(row=i, column=1, value=label)
        ws2.cell(row=i, column=2, value=value)
    wb.save(path)


async def _insert_excel_output(file_path: str) -> int:
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        return await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name="test_agent",
            output_type="excel",
            file_path=file_path,
            version=1,
        )


@pytest.mark.asyncio
async def test_get_financial_summary_returns_metrics(client):
    """Create project + write XLSX + insert row → GET returns 200 with all 6 keys."""
    await client.post("/projects", json=PROJECT)
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / SLUG / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    xlsx_file = outputs_dir / "cost_benefit_model.xlsx"
    _write_excel_file(xlsx_file)
    await _insert_excel_output(str(xlsx_file))

    resp = await client.get(f"/projects/{SLUG}/financial-summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["npv"] == pytest.approx(4_200_000.0)
    assert data["irr"] == pytest.approx(0.234)
    assert data["payback_period"] == "Q3 2026"
    assert data["max_borrowing"] == pytest.approx(-1_100_000.0)
    assert data["total_investment"] == pytest.approx(2_800_000.0)
    assert data["total_benefits"] == pytest.approx(9_600_000.0)


@pytest.mark.asyncio
async def test_get_financial_summary_unknown_project_404(client):
    resp = await client.get("/projects/ghost-project/financial-summary")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_financial_summary_no_output_404(client):
    """Valid project with no excel output row → 404."""
    await client.post("/projects", json=PROJECT)
    resp = await client.get(f"/projects/{SLUG}/financial-summary")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_business_plan_api.py -v
```

Expected: 3 failures — `ImportError` or `404` on endpoint not yet defined.

- [ ] **Step 3: Add `get_financial_summary` to `api/services/project_service.py`**

Add after the `get_roadmap_data` function (around line 224). The existing imports already include `Path`, `get_db_path`, `get_connection`, `fetch_project`:

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
    keys = ["npv", "irr", "payback_period", "max_borrowing", "total_investment", "total_benefits"]
    return {key: ws.cell(row=i + 2, column=2).value for i, key in enumerate(keys)}
```

- [ ] **Step 4: Add the endpoint to `api/routers/projects.py`**

Update the import block at the top of the file (the `from api.services.project_service import (...)` block) to add `get_financial_summary`:

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
    get_financial_summary,
)
```

Then add the endpoint after `get_roadmap_data_endpoint` (at the end of the file):

```python
@router.get("/{slug}/financial-summary")
async def get_financial_summary_endpoint(slug: str):
    result = await get_financial_summary(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No financial model found for project '{slug}'")
    if isinstance(result, dict) and result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Financial model file not found on disk")
    return result
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest tests/test_business_plan_api.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add tests/test_business_plan_api.py api/services/project_service.py api/routers/projects.py
git commit -m "feat(sp9a): add financial-summary endpoint and service"
```

---

## Task 2: Frontend types and API layer

**Files:**
- Modify: `ui/src/types.ts` (append after `RoadmapData`)
- Modify: `ui/src/api/endpoints.ts` (add import + method)

**Context:** `ui/src/types.ts` currently ends with the `RoadmapData` interface added in SP8b. `ui/src/api/endpoints.ts` imports from `../types` and has a `projectsApi` object. The `financialSummary` method follows the same pattern as `roadmapData`.

- [ ] **Step 1: Add `FinancialSummary` to `ui/src/types.ts`**

Append after the `RoadmapData` interface:

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

- [ ] **Step 2: Add `financialSummary` to `ui/src/api/endpoints.ts`**

Add `FinancialSummary` to the import block:

```typescript
import type {
  Project,
  ProjectStatus,
  AgentOutput,
  ClientDocument,
  ProjectSettings,
  OutputContent,
  TokenResponse,
  RoadmapData,
  FinancialSummary,
} from '../types'
```

Add to `projectsApi` after `roadmapData`:

```typescript
financialSummary: (slug: string): Promise<FinancialSummary> =>
  apiClient.get<FinancialSummary>(`/projects/${slug}/financial-summary`).then((r) => r.data),
```

- [ ] **Step 3: Type-check**

```bash
cd ui && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add ui/src/types.ts ui/src/api/endpoints.ts
git commit -m "feat(sp9a): add FinancialSummary type and API method"
```

---

## Task 3: BusinessPlan page, nav, and route

**Files:**
- Create: `ui/src/pages/BusinessPlan.tsx`
- Modify: `ui/src/components/AppLayout.tsx` (add nav item)
- Modify: `ui/src/router.tsx` (add import + route)

**Context:** `AppLayout.tsx` has a `navItems` array. The current order is Dashboard, Value Chain, Roadmap, Documents. Business Plan goes after Roadmap. The router in `router.tsx` lists routes as children of the `AppLayout` route; add Business Plan after the roadmap route. The `useAuth` hook is at `../context/AuthContext` (note: `context`, not `contexts`). The `downloadOutput` utility is at `../utils/download`. `AgentOutput` is the type returned by `projectsApi.outputs()` — it has `id`, `agent_name`, `output_type`, `file_path`, `version`, `review_status`.

- [ ] **Step 1: Create `ui/src/pages/BusinessPlan.tsx`**

```tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { downloadOutput } from '../utils/download'
import type { FinancialSummary, AgentOutput } from '../types'

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtCurrency(v: number | null): string {
  if (v === null || v === undefined) return '—'
  const abs = Math.abs(v)
  if (abs >= 1_000_000) return `£${(v / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `£${(v / 1_000).toFixed(0)}k`
  return `£${v.toFixed(0)}`
}

function fmtPercent(v: number | null): string {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(1)}%`
}

// ── Sub-components ────────────────────────────────────────────────────────────

function MetricCard({ label, value, colour }: { label: string; value: string; colour: string }) {
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

function OutputCard({ output, slug, token }: { output: AgentOutput; slug: string; token: string }) {
  const meta = OUTPUT_META[output.output_type] ?? { label: output.output_type, colour: '#6366f1' }
  const ext = output.output_type.toUpperCase()
  const filename = output.file_path.split('/').pop() ?? output.output_type
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

  const { data: summary } = useQuery<FinancialSummary>({
    queryKey: ['financial-summary', slug],
    queryFn: () => projectsApi.financialSummary(slug!),
    enabled: !!slug,
    retry: false,
  })

  const { data: outputs = [] } = useQuery<AgentOutput[]>({
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

      {summary && (
        <section>
          <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
            Financial Summary
          </h3>
          <div className="grid grid-cols-3 gap-3">
            <MetricCard label="NPV" value={fmtCurrency(summary.npv)} colour="#22c55e" />
            <MetricCard label="IRR" value={fmtPercent(summary.irr)} colour="#22c55e" />
            <MetricCard
              label="Payback Period"
              value={summary.payback_period ?? '—'}
              colour="#f1f5f9"
            />
            <MetricCard
              label="Total Investment"
              value={fmtCurrency(summary.total_investment)}
              colour="#f59e0b"
            />
            <MetricCard
              label="Total Benefits"
              value={fmtCurrency(summary.total_benefits)}
              colour="#22c55e"
            />
            <MetricCard
              label="Max Borrowing"
              value={fmtCurrency(summary.max_borrowing)}
              colour="#f87171"
            />
          </div>
        </section>
      )}

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
          {docxOutput && <OutputCard output={docxOutput} slug={slug!} token={token!} />}
          {pptxOutput && <OutputCard output={pptxOutput} slug={slug!} token={token!} />}
          {excelOutput && <OutputCard output={excelOutput} slug={slug!} token={token!} />}
        </div>
      </section>
    </div>
  )
}
```

- [ ] **Step 2: Add "Business Plan" to `ui/src/components/AppLayout.tsx`**

Find the `navItems` array (around line 27). The current items are Dashboard, Value Chain, Roadmap, Documents. Add Business Plan after Roadmap:

```typescript
const navItems = slug
  ? [
      { to: `/${slug}`, label: 'Dashboard', end: true },
      { to: `/${slug}/value-chain`, label: 'Value Chain' },
      { to: `/${slug}/roadmap`, label: 'Roadmap' },
      { to: `/${slug}/business-plan`, label: 'Business Plan' },
      { to: `/${slug}/documents`, label: 'Documents' },
    ]
  : [{ to: '/', label: 'Dashboard', end: true }]
```

- [ ] **Step 3: Add the route and import to `ui/src/router.tsx`**

Add the import after the `Settings` import:

```typescript
import BusinessPlan from './pages/BusinessPlan'
```

Add the route after `':slug/roadmap'`:

```typescript
{ path: ':slug/roadmap', element: <Roadmap /> },
{ path: ':slug/business-plan', element: <BusinessPlan /> },
```

- [ ] **Step 4: Type-check**

```bash
cd ui && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Run backend tests to confirm no regressions**

```bash
pytest tests/test_business_plan_api.py tests/test_gantt.py tests/test_outputs_download.py tests/test_outputs_content.py -v
```

Expected: all passing (except the pre-existing `test_html_roadmap_tool_writes_json` crewai import failure).

- [ ] **Step 6: Commit**

```bash
git add ui/src/pages/BusinessPlan.tsx ui/src/components/AppLayout.tsx ui/src/router.tsx
git commit -m "feat(sp9a): add Business Plan page with financial metrics grid"
```
