# SP11a — Nav Reorder and Workflow Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorder the nav to match the consulting workflow, move discovery inputs into the Value Chain page as a Setup tab, restructure Discovery into tabs (Interviews + Layer Map stub), and add a Value Propositions page backed by the portfolio register agent output.

**Architecture:** All changes are frontend-only except one new read-only backend endpoint (`GET /projects/{slug}/portfolio-register`) that reads `outputs/portfolio_register.json` from disk — the same pattern used by `roadmap-data` and `financial-summary`. No DB migrations, no agent changes.

**Tech Stack:** FastAPI (Python), React + TypeScript, TanStack Query, Tailwind CSS, React Router v6, pytest-asyncio.

---

## File Structure

| File | Change |
|---|---|
| `api/services/project_service.py` | Add `get_portfolio_register` function |
| `api/routers/projects.py` | Add `GET /{slug}/portfolio-register` endpoint |
| `tests/test_projects_api.py` | Add 2 tests for the new endpoint |
| `ui/src/types.ts` | Add `PortfolioItem` interface |
| `ui/src/api/endpoints.ts` | Add `portfolioRegister` method to `projectsApi` |
| `ui/src/components/AppLayout.tsx` | Reorder nav items, add Value Propositions item |
| `ui/src/router.tsx` | Import `ValuePropositions`, add route |
| `ui/src/pages/ValueChain.tsx` | Add Setup/Diagram tabs; absorb discovery inputs state + UI |
| `ui/src/pages/Discovery.tsx` | Remove inputs section; add Interviews/Layer Map tabs |
| `ui/src/pages/ValuePropositions.tsx` | **New file** — ranked VP register table |

---

## Task 1: Backend — portfolio-register service + endpoint + tests

**Files:**
- Modify: `api/services/project_service.py`
- Modify: `api/routers/projects.py`
- Test: `tests/test_projects_api.py`

Context: The portfolio register is written by the Portfolio Manager agent via `SQLiteStateTool` with `key='portfolio_register'`. This saves the JSON to `{PROJECTS_DIR}/{slug}/outputs/portfolio_register.json`. The endpoint reads that file directly — no DB query needed. Follow the same pattern as `get_roadmap_data` / `get_roadmap_data_endpoint` in the same files.

The test file uses `pytest.mark.asyncio`, an `async def client()` fixture from `conftest.py` (AsyncClient wrapping the FastAPI app), and a `clean_test_state` autouse fixture that wipes `/tmp/agentpool_test` and `/tmp/agentpool_test_projects` before each test. No auth headers needed — existing project endpoints have no auth requirement.

- [ ] **Step 1: Write two failing tests at the bottom of `tests/test_projects_api.py`**

```python
@pytest.mark.asyncio
async def test_portfolio_register_empty(client):
    """Returns [] when project exists but portfolio_register.json does not."""
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.get("/projects/test-rail/portfolio-register")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_portfolio_register_returns_data(client):
    """Returns parsed JSON array when portfolio_register.json exists on disk."""
    await client.post("/projects", json=PROJECT_PAYLOAD)

    register = [
        {
            "rank": 1,
            "id": "VP-001",
            "title": "Modernise Asset Management",
            "change_articulation": "Replaces manual inspection logs with IoT-driven data.",
            "impacted_stakeholder_groups": ["Operations", "Safety"],
            "value_estimate": "High",
            "score_value": 8.0,
            "score_feasibility": 7.0,
            "score_strategic_fit": 9.0,
            "score_value_rationale": "Direct cost reduction.",
            "score_feasibility_rationale": "APIs exist.",
            "score_strategic_fit_rationale": "Core strategy.",
            "total_score": 80.0,
            "weights_used": {"value": 5, "feasibility": 3, "strategic_fit": 2},
        }
    ]
    outputs_dir = Path("/tmp/agentpool_test_projects/test-rail/outputs")
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "portfolio_register.json").write_text(
        json.dumps(register), encoding="utf-8"
    )

    resp = await client.get("/projects/test-rail/portfolio-register")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "VP-001"
    assert data[0]["total_score"] == 80.0
```

Also add `import json` to the imports at the top of `tests/test_projects_api.py` if not already present.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/pboagents/Documents/agentpool1
python3 -m pytest tests/test_projects_api.py::test_portfolio_register_empty tests/test_projects_api.py::test_portfolio_register_returns_data -v
```

Expected: FAIL — `404 Not Found` (endpoint doesn't exist yet).

- [ ] **Step 3: Add `get_portfolio_register` to `api/services/project_service.py`**

Add after the `get_financial_summary` function (around line 280+). The existing imports already include `json`, `Path`, `get_settings`, and `get_db_path`.

```python
async def get_portfolio_register(slug: str) -> list | None:
    """Return the portfolio register JSON array for a project.

    Returns:
        None  — project DB does not exist (unknown project)
        []    — project exists but portfolio_register.json not on disk yet
        list  — parsed JSON array from outputs/portfolio_register.json
    """
    if not get_db_path(slug).exists():
        return None
    settings = get_settings()
    file_path = Path(settings.projects_dir) / slug / "outputs" / "portfolio_register.json"
    if not file_path.exists():
        return []
    return json.loads(file_path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Import and expose the function in `api/routers/projects.py`**

Add `get_portfolio_register` to the import from `api.services.project_service` at the top of the file (lines 7–17):

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
    get_portfolio_register,
)
```

Then add the endpoint after the `financial-summary` endpoint (after line 137):

```python
@router.get("/{slug}/portfolio-register")
async def get_portfolio_register_endpoint(slug: str):
    result = await get_portfolio_register(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_projects_api.py::test_portfolio_register_empty tests/test_projects_api.py::test_portfolio_register_returns_data -v
```

Expected: PASS — both tests green.

- [ ] **Step 6: Run the full test suite to check for regressions**

```bash
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All previously passing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add api/services/project_service.py api/routers/projects.py tests/test_projects_api.py
git commit -m "feat: add GET /projects/{slug}/portfolio-register endpoint"
```

---

## Task 2: Frontend types + API method

**Files:**
- Modify: `ui/src/types.ts`
- Modify: `ui/src/api/endpoints.ts`

Context: `PortfolioItem` matches exactly what `portfolio_manager.py` writes to `portfolio_register.json`. The `portfolioRegister` method follows the same pattern as `roadmapData` and `financialSummary` in the same file.

- [ ] **Step 1: Add `PortfolioItem` interface to `ui/src/types.ts`**

Append after the `ImportResult` interface at the end of the file:

```ts
export interface PortfolioItem {
  rank: number
  id: string                        // e.g. "VP-001"
  title: string
  change_articulation: string
  impacted_stakeholder_groups: string[]
  value_estimate: 'High' | 'Medium' | 'Low'
  score_value: number
  score_feasibility: number
  score_strategic_fit: number
  score_value_rationale: string
  score_feasibility_rationale: string
  score_strategic_fit_rationale: string
  total_score: number
  weights_used: { value: number; feasibility: number; strategic_fit: number }
}
```

- [ ] **Step 2: Add `portfolioRegister` method to `projectsApi` in `ui/src/api/endpoints.ts`**

Add `PortfolioItem` to the type import at the top of the file. Then add the method to the `projectsApi` object after the `financialSummary` method:

```ts
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
  HumanReview,
  OrchestrationRunHistory,
  Stakeholder,
  StakeholderImportResult,
  PortfolioItem,
} from '../types'
```

```ts
  portfolioRegister: (slug: string): Promise<PortfolioItem[]> =>
    apiClient.get<PortfolioItem[]>(`/projects/${slug}/portfolio-register`).then((r) => r.data),
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npm run build 2>&1 | grep -E "error|Error" | head -20
```

Expected: No TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add ui/src/types.ts ui/src/api/endpoints.ts
git commit -m "feat: add PortfolioItem type and portfolioRegister API method"
```

---

## Task 3: Nav reorder + router update

**Files:**
- Modify: `ui/src/components/AppLayout.tsx`
- Modify: `ui/src/router.tsx`

Context: `navItems` in `AppLayout.tsx` is an array defined inside the component (lines 37–49). The new order is: Dashboard, Value Chain, Discovery, Value Propositions, Roadmap, Business Plan, Stakeholders, Reviews, Runs, Documents. Stakeholders moves from position 5 to position 8 — it's a registry, not a workflow step.

- [ ] **Step 1: Replace the `navItems` array in `ui/src/components/AppLayout.tsx`**

Replace lines 37–49 (the `navItems` definition) with:

```tsx
  const navItems: NavItem[] = slug
    ? [
        { to: `/${slug}`, label: 'Dashboard', end: true },
        { to: `/${slug}/value-chain`, label: 'Value Chain' },
        { to: `/${slug}/discovery`, label: 'Discovery' },
        { to: `/${slug}/value-propositions`, label: 'Value Propositions' },
        { to: `/${slug}/roadmap`, label: 'Roadmap' },
        { to: `/${slug}/business-plan`, label: 'Business Plan' },
        { to: `/${slug}/stakeholders`, label: 'Stakeholders' },
        { to: `/${slug}/reviews`, label: 'Reviews', badge: pendingReviewCount > 0 ? pendingReviewCount : undefined },
        { to: `/${slug}/runs`, label: 'Runs' },
        { to: `/${slug}/documents`, label: 'Documents' },
      ]
    : [{ to: '/', label: 'Dashboard', end: true }]
```

- [ ] **Step 2: Add the ValuePropositions import and route to `ui/src/router.tsx`**

Add the import after the existing `Discovery` import:

```tsx
import ValuePropositions from './pages/ValuePropositions'
```

Add the route in the `children` array, after the `value-chain` route:

```tsx
{ path: ':slug/value-propositions', element: <ValuePropositions /> },
```

The full updated children array becomes:

```tsx
children: [
  { index: true, element: <Dashboard /> },
  { path: ':slug', element: <Dashboard /> },
  { path: ':slug/discovery', element: <Discovery /> },
  { path: ':slug/value-chain', element: <ValueChain /> },
  { path: ':slug/value-propositions', element: <ValuePropositions /> },
  { path: ':slug/roadmap', element: <Roadmap /> },
  { path: ':slug/stakeholders', element: <Stakeholders /> },
  { path: ':slug/stakeholders/new', element: <StakeholderForm /> },
  { path: ':slug/stakeholders/:id/edit', element: <StakeholderForm /> },
  { path: ':slug/business-plan', element: <BusinessPlan /> },
  { path: ':slug/reviews', element: <Reviews /> },
  { path: ':slug/runs', element: <Runs /> },
  { path: ':slug/documents', element: <Documents /> },
  { path: ':slug/runs/:runId', element: <RunDetail /> },
  { path: ':slug/settings', element: <Settings /> },
],
```

Note: `ValuePropositions` page does not exist yet — the TypeScript compiler will error until Task 4 creates it. That's expected; do not run the build check until after Task 4.

- [ ] **Step 3: Commit**

```bash
git add ui/src/components/AppLayout.tsx ui/src/router.tsx
git commit -m "feat: reorder nav and add value-propositions route"
```

---

## Task 4: Value Propositions page

**Files:**
- Create: `ui/src/pages/ValuePropositions.tsx`

Context: Reads from `GET /projects/{slug}/portfolio-register` (Task 1). Returns `[]` when no run has completed. Shows a ranked table when data is present. Each row is clickable to expand a detail panel with rationales. Uses `PortfolioItem` type from Task 2.

- [ ] **Step 1: Create `ui/src/pages/ValuePropositions.tsx`**

```tsx
// ui/src/pages/ValuePropositions.tsx
import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import type { PortfolioItem } from '../types'

export default function ValuePropositions() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: items = [], isLoading } = useQuery<PortfolioItem[]>({
    queryKey: ['portfolio-register', slug],
    queryFn: () => projectsApi.portfolioRegister(slug!),
    enabled: !!slug,
  })

  function toggleRow(id: string) {
    setExpandedId((prev) => (prev === id ? null : id))
  }

  function valueEstimateColour(v: string) {
    if (v === 'High') return 'text-brand-green'
    if (v === 'Medium') return 'text-amber-400'
    return 'text-slate-400'
  }

  if (isLoading) {
    return (
      <div className="p-6">
        <p className="text-sm text-slate-500">Loading…</p>
      </div>
    )
  }

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold text-slate-100 mb-1">Value Propositions</h2>
      <p className="text-slate-400 text-sm mb-6">Scored and ranked by the Portfolio Manager agent.</p>

      {items.length === 0 ? (
        <div className="bg-surface-card rounded-xl p-8 text-center max-w-lg">
          <p className="text-slate-300 text-sm font-medium mb-2">No value propositions yet</p>
          <p className="text-slate-500 text-xs leading-relaxed mb-4">
            The Portfolio Manager agent scores and ranks propositions after the Value Design crew
            completes. Run the pipeline from the Dashboard.
          </p>
          <button
            onClick={() => navigate(`/${slug}`)}
            className="px-4 py-2 bg-brand hover:bg-brand-dark text-white text-sm rounded"
          >
            Run Pipeline →
          </button>
        </div>
      ) : (
        <>
          <div className="mb-4 rounded-lg border border-amber-800/40 bg-amber-900/10 px-4 py-3 text-xs text-amber-400 leading-relaxed">
            Scoring dimensions: value impact, feasibility, strategic fit. Six Capitals scoring
            (IIRC framework + safety + performance) coming in a future sprint.
          </div>

          <div className="bg-surface-card rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-xs text-slate-500 uppercase tracking-wide">
                  <th className="text-left px-4 py-3 w-10">#</th>
                  <th className="text-left px-4 py-3 w-16">ID</th>
                  <th className="text-left px-4 py-3">Title</th>
                  <th className="text-left px-4 py-3 w-20">Est.</th>
                  <th className="text-right px-4 py-3 w-16">Value</th>
                  <th className="text-right px-4 py-3 w-16">Feas.</th>
                  <th className="text-right px-4 py-3 w-20">Strat. Fit</th>
                  <th className="text-right px-4 py-3 w-16">Total</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <>
                    <tr
                      key={item.id}
                      onClick={() => toggleRow(item.id)}
                      className="border-b border-slate-800 hover:bg-slate-800/40 cursor-pointer transition-colors"
                    >
                      <td className="px-4 py-3 text-slate-500">{item.rank}</td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400">{item.id}</td>
                      <td className="px-4 py-3 text-slate-200 font-medium">{item.title}</td>
                      <td className={`px-4 py-3 text-xs font-semibold ${valueEstimateColour(item.value_estimate)}`}>
                        {item.value_estimate}
                      </td>
                      <td className="px-4 py-3 text-right text-slate-300">{item.score_value.toFixed(1)}</td>
                      <td className="px-4 py-3 text-right text-slate-300">{item.score_feasibility.toFixed(1)}</td>
                      <td className="px-4 py-3 text-right text-slate-300">{item.score_strategic_fit.toFixed(1)}</td>
                      <td className="px-4 py-3 text-right font-semibold text-brand">{item.total_score.toFixed(1)}</td>
                    </tr>
                    {expandedId === item.id && (
                      <tr key={`${item.id}-detail`} className="border-b border-slate-800 bg-slate-900/40">
                        <td colSpan={8} className="px-6 py-4 space-y-3">
                          <p className="text-sm text-slate-300 leading-relaxed">{item.change_articulation}</p>
                          <p className="text-xs text-slate-500">
                            <span className="font-semibold text-slate-400">Stakeholders: </span>
                            {item.impacted_stakeholder_groups.join(', ')}
                          </p>
                          <div className="grid grid-cols-3 gap-4 text-xs text-slate-500">
                            <div>
                              <span className="font-semibold text-slate-400">Value: </span>
                              {item.score_value_rationale}
                            </div>
                            <div>
                              <span className="font-semibold text-slate-400">Feasibility: </span>
                              {item.score_feasibility_rationale}
                            </div>
                            <div>
                              <span className="font-semibold text-slate-400">Strategic fit: </span>
                              {item.score_strategic_fit_rationale}
                            </div>
                          </div>
                          <p className="text-xs text-slate-600">
                            Weights — Value ×{item.weights_used.value}, Feasibility ×{item.weights_used.feasibility}, Strategic Fit ×{item.weights_used.strategic_fit}
                          </p>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npm run build 2>&1 | grep -E "error TS" | head -20
```

Expected: No TypeScript errors. (The nav now includes Value Propositions and the page exists.)

- [ ] **Step 3: Commit**

```bash
git add ui/src/pages/ValuePropositions.tsx
git commit -m "feat: add Value Propositions page with ranked portfolio register"
```

---

## Task 5: Value Chain page — Setup tab + Diagram tab

**Files:**
- Modify: `ui/src/pages/ValueChain.tsx`

Context: The Setup tab absorbs all state and UI currently in `Discovery.tsx` for the research brief, links, and source documents. The Diagram tab is the existing Mermaid render. The file is completely rewritten to add the tab structure; no logic is removed from the app — it moves.

Key detail: the `activeTab` default is `'setup'` initially. A `useEffect` watches `isLoading` and `outputs.length` — once outputs load, it switches to `'diagram'`. This means a first-time user sees Setup; a returning user with a run sees Diagram.

- [ ] **Step 1: Rewrite `ui/src/pages/ValueChain.tsx` in full**

```tsx
// ui/src/pages/ValueChain.tsx
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import mermaid from 'mermaid'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { downloadOutput } from '../utils/download'
import type { ProjectSettings, DiscoveryLink, ClientDocument } from '../types'

mermaid.initialize({ startOnLoad: false, theme: 'dark' })

export default function ValueChain() {
  const { slug } = useParams<{ slug: string }>()
  const { token } = useAuth()
  const qc = useQueryClient()

  // ── Setup tab state ──────────────────────────────────────────
  const [brief, setBrief] = useState('')
  const [links, setLinks] = useState<DiscoveryLink[]>([])
  const [selectedDocIds, setSelectedDocIds] = useState<number[]>([])
  const [newUrl, setNewUrl] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug!),
    enabled: !!slug,
  })

  const { data: documents = [] } = useQuery<ClientDocument[]>({
    queryKey: ['documents', slug],
    queryFn: () => projectsApi.documents(slug!),
    enabled: !!slug,
  })

  useEffect(() => {
    if (settings) {
      setBrief(settings.discovery_brief ?? '')
      setLinks(settings.discovery_links ?? [])
      setSelectedDocIds(settings.discovery_document_ids ?? [])
    }
  }, [settings])

  const mutation = useMutation({
    mutationFn: (updated: ProjectSettings) => projectsApi.updateSettings(slug!, updated),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings', slug] })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
    onError: (e: Error) => setError(e.message),
  })

  function handleSave() {
    if (!settings) return
    setError(null)
    mutation.mutate({
      ...settings,
      discovery_brief: brief,
      discovery_links: links,
      discovery_document_ids: selectedDocIds,
    })
  }

  function addLink() {
    const trimmedUrl = newUrl.trim()
    if (!trimmedUrl) return
    setLinks((prev) => [...prev, { url: trimmedUrl, label: newLabel.trim() }])
    setNewUrl('')
    setNewLabel('')
  }

  function removeLink(index: number) {
    setLinks((prev) => prev.filter((_, i) => i !== index))
  }

  function toggleDoc(id: number) {
    setSelectedDocIds((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id],
    )
  }

  // ── Diagram tab state ────────────────────────────────────────
  const { data: outputs = [], isLoading } = useQuery({
    queryKey: ['value-chain', slug],
    queryFn: () => projectsApi.valueChain(slug!),
    enabled: !!slug,
  })

  const latest = outputs[0] ?? null

  const { data: contentData, isLoading: contentLoading, isError: contentError } = useQuery({
    queryKey: ['outputContent', slug, latest?.id],
    queryFn: () => projectsApi.getOutputContent(slug!, latest!.id),
    enabled: !!slug && !!latest,
  })

  const svgContainerRef = useRef<HTMLDivElement>(null)
  const mountKey = useRef(Math.random().toString(36).slice(2))
  const [renderError, setRenderError] = useState(false)

  useEffect(() => {
    if (!contentData?.content || !svgContainerRef.current) return
    let cancelled = false
    const container = svgContainerRef.current
    setRenderError(false)
    ;(async () => {
      try {
        const renderId = 'vc-' + mountKey.current + '-' + (latest?.id ?? 0)
        const { svg } = await mermaid.render(renderId, contentData.content)
        if (cancelled) return
        const parser = new DOMParser()
        const svgDoc = parser.parseFromString(svg, 'image/svg+xml')
        const svgEl = svgDoc.documentElement
        container.replaceChildren(svgEl)
      } catch {
        if (!cancelled) setRenderError(true)
        if (!cancelled) container.replaceChildren()
      }
    })()
    return () => {
      cancelled = true
    }
  }, [contentData?.content, latest?.id])

  // ── Tab ──────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<'setup' | 'diagram'>('setup')

  // Switch to Diagram tab automatically once outputs are known to exist
  useEffect(() => {
    if (!isLoading && outputs.length > 0) setActiveTab('diagram')
  }, [isLoading, outputs.length])

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold text-slate-100 mb-4">Value Chain</h2>

      {/* Tab strip */}
      <div className="flex border-b border-slate-700 mb-6">
        {(['setup', 'diagram'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm capitalize border-b-2 transition-colors ${
              activeTab === tab
                ? 'text-brand border-brand'
                : 'text-slate-400 border-transparent hover:text-slate-200'
            }`}
          >
            {tab === 'setup' ? 'Setup' : 'Diagram'}
          </button>
        ))}
      </div>

      {/* ── Setup tab ─────────────────────────────────────────── */}
      {activeTab === 'setup' && (
        <div className="max-w-3xl">
          <p className="text-slate-400 text-sm mb-8">
            Configure what the Value Chain Mapper uses before it starts. Changes take effect on the next crew run.
          </p>

          {/* Research Brief */}
          <section className="mb-8">
            <h3 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Research Brief</h3>
            <p className="text-slate-500 text-xs mb-3">
              Any context the crew should know before it starts — strategic priorities, scope constraints, what the client has flagged.
            </p>
            <textarea
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              rows={5}
              placeholder="e.g. The client operates primarily in passenger rail in the UK. Focus on operational efficiency and safety compliance themes."
              className="w-full bg-slate-900 border border-slate-700 rounded p-3 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-brand resize-y"
            />
          </section>

          {/* Research Links */}
          <section className="mb-8">
            <h3 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Research Links</h3>
            <p className="text-slate-500 text-xs mb-3">
              URLs the crew will fetch and read before analysis. Add industry bodies, regulatory sites, company pages, or reports.
            </p>
            {links.length > 0 && (
              <ul className="mb-3 space-y-1">
                {links.map((link, i) => (
                  <li key={i} className="flex items-center gap-2 bg-slate-900 border border-slate-700 rounded px-3 py-2">
                    <span className="text-brand text-xs font-mono flex-1 truncate">{link.url}</span>
                    {link.label && <span className="text-slate-400 text-xs">{link.label}</span>}
                    <button
                      type="button"
                      onClick={() => removeLink(i)}
                      className="text-slate-500 hover:text-red-400 text-xs ml-2"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex gap-2">
              <input
                value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addLink()}
                placeholder="https://..."
                className="flex-1 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-brand"
              />
              <input
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addLink()}
                placeholder="Label (optional)"
                className="w-40 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-brand"
              />
              <button
                type="button"
                onClick={addLink}
                disabled={!newUrl.trim()}
                className="px-4 py-2 bg-brand hover:bg-brand-dark disabled:opacity-40 text-white text-sm rounded"
              >
                Add
              </button>
            </div>
          </section>

          {/* Source Documents */}
          <section className="mb-8">
            <h3 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Source Documents</h3>
            <p className="text-slate-500 text-xs mb-3">
              Select documents to prioritise. The crew will focus ChromaDB queries on these files.
            </p>
            {documents.length === 0 ? (
              <p className="text-slate-500 text-sm italic">No documents uploaded yet. Upload documents on the Documents page.</p>
            ) : (
              <ul className="space-y-1">
                {documents.map((doc) => (
                  <li key={doc.id} className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      id={`doc-${doc.id}`}
                      checked={selectedDocIds.includes(doc.id)}
                      onChange={() => toggleDoc(doc.id)}
                      className="accent-brand"
                    />
                    <label htmlFor={`doc-${doc.id}`} className="text-sm text-slate-300 cursor-pointer">
                      {doc.original_name}
                      <span className="text-slate-500 text-xs ml-2">
                        ({(doc.size_bytes / 1024).toFixed(0)} KB)
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={handleSave}
              disabled={mutation.isPending}
              className="px-6 py-2 bg-brand hover:bg-brand-dark disabled:opacity-50 text-white text-sm font-medium rounded"
            >
              {mutation.isPending ? 'Saving…' : 'Save'}
            </button>
            {saved && <span className="text-emerald-400 text-sm">Saved.</span>}
          </div>
        </div>
      )}

      {/* ── Diagram tab ───────────────────────────────────────── */}
      {activeTab === 'diagram' && (
        <>
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
              <div className="flex justify-between items-center mb-4">
                <span className="text-sm text-slate-200">{latest.agent_name}</span>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-500">
                    v{latest.version} · {latest.review_status}
                  </span>
                  <button
                    onClick={() =>
                      downloadOutput(
                        slug!,
                        latest.id,
                        latest.file_path.split('/').pop() ?? latest.output_type,
                        token!,
                      ).catch(console.error)
                    }
                    className="text-xs text-sky-400 hover:text-sky-300 transition-colors"
                  >
                    ↓ Download
                  </button>
                </div>
              </div>
              {contentLoading && <p className="text-sm text-slate-500">Rendering diagram…</p>}
              {contentError && !contentLoading && (
                <p className="text-sm text-red-400">Failed to load diagram.</p>
              )}
              {renderError && <p className="text-sm text-red-400">Invalid diagram source.</p>}
              {/* SVG inserted here via DOMParser + replaceChildren */}
              <div ref={svgContainerRef} className="overflow-auto" />
            </div>
          )}
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles with no errors**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npm run build 2>&1 | grep -E "error TS" | head -20
```

Expected: No TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add ui/src/pages/ValueChain.tsx
git commit -m "feat: add Setup/Diagram tabs to Value Chain page, absorb discovery inputs"
```

---

## Task 6: Discovery page — strip inputs, restructure into tabs

**Files:**
- Modify: `ui/src/pages/Discovery.tsx`

Context: Everything related to the research brief, links, and documents is removed (it now lives in ValueChain.tsx). What remains is the campaigns section, now placed inside an "Interviews" tab. A second "Layer Map" tab is added as a stub. The `useEffect`, `useMutation`, `useQueryClient` imports are removed since they're no longer needed.

- [ ] **Step 1: Rewrite `ui/src/pages/Discovery.tsx` in full**

```tsx
// ui/src/pages/Discovery.tsx
import { useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { campaignsApi } from '../api/campaigns'
import type { Campaign } from '../types'

export default function Discovery() {
  const { slug } = useParams<{ slug: string }>()
  const [activeTab, setActiveTab] = useState<'interviews' | 'layer-map'>('interviews')

  const { data: campaigns = [], refetch: refetchCampaigns } = useQuery<Campaign[]>({
    queryKey: ['campaigns', slug],
    queryFn: () => campaignsApi.list(slug!),
    enabled: !!slug,
  })

  const [campaignMsg, setCampaignMsg] = useState<Record<number, string>>({})
  const progressInputRef = useRef<Record<number, HTMLInputElement | null>>({})
  const resultsInputRef = useRef<Record<number, HTMLInputElement | null>>({})
  const summaryInputRef = useRef<Record<number, HTMLInputElement | null>>({})

  async function createCampaign() {
    await campaignsApi.create(slug!, { value_stream_name: '', campaign_name: 'New Campaign' })
    refetchCampaigns()
  }

  async function updateCampaignField(id: number, data: Partial<Campaign>) {
    await campaignsApi.update(slug!, id, data)
    refetchCampaigns()
  }

  async function deleteCampaign(id: number) {
    await campaignsApi.delete(slug!, id)
    refetchCampaigns()
  }

  async function markInvited(id: number) {
    const r = await campaignsApi.markInvited(slug!, id)
    setCampaignMsg((prev) => ({ ...prev, [id]: `${r.marked} stakeholders marked as invited.` }))
    setTimeout(() => setCampaignMsg((prev) => ({ ...prev, [id]: '' })), 4000)
  }

  async function generateReminders(id: number) {
    const r = await campaignsApi.generateReminders(slug!, id)
    setCampaignMsg((prev) => ({ ...prev, [id]: `${r.created} reminder email(s) added to review queue.` }))
    setTimeout(() => setCampaignMsg((prev) => ({ ...prev, [id]: '' })), 4000)
  }

  async function handleFileImport(
    id: number,
    kind: 'progress' | 'results' | 'summary',
    file: File,
  ) {
    let msg = ''
    if (kind === 'progress') {
      const r = await campaignsApi.importProgress(slug!, id, file)
      msg = `Progress imported: ${r.updated} updated, ${r.skipped} skipped.`
    } else if (kind === 'results') {
      const r = await campaignsApi.importResults(slug!, id, file)
      msg = `Results imported: ${r.imported} imported, ${r.unmatched} unmatched.`
    } else {
      await campaignsApi.importSummary(slug!, id, file)
      msg = 'Findings summary imported.'
      refetchCampaigns()
    }
    setCampaignMsg((prev) => ({ ...prev, [id]: msg }))
    setTimeout(() => setCampaignMsg((prev) => ({ ...prev, [id]: '' })), 5000)
  }

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-100 mb-4">Discovery</h1>

      {/* Tab strip */}
      <div className="flex border-b border-slate-700 mb-6">
        {([['interviews', 'Interviews'], ['layer-map', 'Layer Map']] as const).map(([tab, label]) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm border-b-2 transition-colors ${
              activeTab === tab
                ? 'text-brand border-brand'
                : 'text-slate-400 border-transparent hover:text-slate-200'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Interviews tab ────────────────────────────────────── */}
      {activeTab === 'interviews' && (
        <div className="max-w-3xl">
          <p className="text-slate-400 text-sm mb-6">
            Link a ListenLabs campaign to each value stream. Export interview targets, import
            results, and generate reminders.
          </p>

          {campaigns.length === 0 && (
            <p className="text-slate-500 text-sm italic mb-3">No campaigns linked yet.</p>
          )}

          <div className="space-y-4">
            {campaigns.map((camp) => (
              <div key={camp.id} className="border border-slate-700 rounded-lg p-4 space-y-3">
                {/* Campaign header row */}
                <div className="flex items-start gap-3">
                  <div className="flex-1 grid grid-cols-2 gap-2">
                    <input
                      defaultValue={camp.campaign_name}
                      onBlur={(e) => updateCampaignField(camp.id, { campaign_name: e.target.value })}
                      placeholder="Campaign name"
                      className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-brand"
                    />
                    <input
                      defaultValue={camp.listenlabs_campaign_id}
                      onBlur={(e) =>
                        updateCampaignField(camp.id, { listenlabs_campaign_id: e.target.value })
                      }
                      placeholder="ListenLabs campaign ID"
                      className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 font-mono outline-none focus:border-brand"
                    />
                    <input
                      defaultValue={camp.value_stream_name}
                      onBlur={(e) =>
                        updateCampaignField(camp.id, { value_stream_name: e.target.value })
                      }
                      placeholder="Value stream name (must match discovery output)"
                      className="col-span-2 bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-brand"
                    />
                    <input
                      type="date"
                      defaultValue={camp.interview_start ?? ''}
                      onBlur={(e) =>
                        updateCampaignField(camp.id, { interview_start: e.target.value || null })
                      }
                      className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-brand"
                    />
                    <input
                      type="date"
                      defaultValue={camp.interview_close ?? ''}
                      onBlur={(e) =>
                        updateCampaignField(camp.id, { interview_close: e.target.value || null })
                      }
                      className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-brand"
                    />
                  </div>
                  <button
                    onClick={() => deleteCampaign(camp.id)}
                    className="text-slate-500 hover:text-red-400 text-xs px-2 py-1 flex-shrink-0"
                  >
                    Remove
                  </button>
                </div>

                {/* Action buttons */}
                <div className="flex flex-wrap gap-2">
                  <a
                    href={campaignsApi.exportTargets(slug!, camp.id)}
                    download
                    className="text-xs px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-600"
                  >
                    Download Targets
                  </a>
                  <button
                    onClick={() => markInvited(camp.id)}
                    className="text-xs px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-600"
                  >
                    Mark as Invited
                  </button>

                  {/* Hidden file inputs */}
                  <input
                    type="file"
                    accept=".csv"
                    className="hidden"
                    ref={(el) => { progressInputRef.current[camp.id] = el }}
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) handleFileImport(camp.id, 'progress', f)
                      e.target.value = ''
                    }}
                  />
                  <input
                    type="file"
                    accept=".csv,.json"
                    className="hidden"
                    ref={(el) => { resultsInputRef.current[camp.id] = el }}
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) handleFileImport(camp.id, 'results', f)
                      e.target.value = ''
                    }}
                  />
                  <input
                    type="file"
                    accept=".txt,.json"
                    className="hidden"
                    ref={(el) => { summaryInputRef.current[camp.id] = el }}
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) handleFileImport(camp.id, 'summary', f)
                      e.target.value = ''
                    }}
                  />

                  <button
                    onClick={() => progressInputRef.current[camp.id]?.click()}
                    className="text-xs px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-600"
                  >
                    Import Progress
                  </button>
                  <button
                    onClick={() => resultsInputRef.current[camp.id]?.click()}
                    className="text-xs px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-600"
                  >
                    Import Results
                  </button>
                  <button
                    onClick={() => summaryInputRef.current[camp.id]?.click()}
                    className="text-xs px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-600"
                  >
                    Import Summary
                  </button>
                  <button
                    onClick={() => generateReminders(camp.id)}
                    className="text-xs px-3 py-1.5 bg-brand/10 hover:bg-brand/20 text-brand rounded border border-brand/30"
                  >
                    Generate Reminders
                  </button>
                </div>

                {campaignMsg[camp.id] && (
                  <p className="text-xs text-emerald-400">{campaignMsg[camp.id]}</p>
                )}

                {camp.findings_summary && (
                  <div>
                    <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">
                      Findings Summary
                    </p>
                    <pre className="text-xs text-slate-300 bg-slate-900 border border-slate-700 rounded p-3 whitespace-pre-wrap max-h-40 overflow-y-auto">
                      {camp.findings_summary}
                    </pre>
                  </div>
                )}
              </div>
            ))}
          </div>

          <button
            onClick={createCampaign}
            className="mt-3 text-xs text-slate-400 hover:text-slate-200 border border-slate-700 hover:border-slate-500 rounded px-3 py-1.5"
          >
            + Link Campaign
          </button>
        </div>
      )}

      {/* ── Layer Map tab (stub) ──────────────────────────────── */}
      {activeTab === 'layer-map' && (
        <div className="max-w-3xl">
          <div className="border border-slate-700 rounded-lg p-8 text-center">
            <p className="text-sm font-semibold text-slate-300 mb-2">Stakeholder Layer Assignment</p>
            <p className="text-xs text-slate-500 leading-relaxed max-w-md mx-auto">
              Stakeholders will be mapped to model layers here —
              investor → organisation → value stream → value chain → activity → customer.
              Interview findings will be displayed against each layer.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles with no errors**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npm run build 2>&1 | grep -E "error TS" | head -20
```

Expected: No TypeScript errors.

- [ ] **Step 3: Run the full backend test suite for regressions**

```bash
cd /Users/pboagents/Documents/agentpool1
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All tests pass (no backend changes in this task).

- [ ] **Step 4: Commit**

```bash
git add ui/src/pages/Discovery.tsx
git commit -m "feat: restructure Discovery into Interviews/Layer Map tabs, remove inputs section"
```

---

## Task 7: Smoke test

Manual verification — no code changes.

- [ ] **Step 1: Ensure both dev servers are running**

```bash
lsof -i :5173 -i :8000 | grep LISTEN
```

If either is missing, start them:

```bash
# Backend (from project root)
uvicorn api.main:app --reload --port 8000 &

# Frontend (from ui/)
cd ui && npm run dev &
```

- [ ] **Step 2: Navigate to the app and verify nav order**

Open `http://localhost:5173/smoke-test` in a browser.

Expected nav order (left to right):
`Dashboard · Value Chain · Discovery · Value Propositions · Roadmap · Business Plan · Stakeholders · Reviews · Runs · Documents`

- [ ] **Step 3: Verify Value Chain page — Setup tab**

Click **Value Chain**. Confirm:
- "Setup" tab is active by default (no previous run exists)
- Research brief textarea, links section, and source documents section are visible
- "Diagram" tab is present but clicking it shows "Awaiting Value Chain Mapper output"

- [ ] **Step 4: Verify Discovery page — tabs**

Click **Discovery**. Confirm:
- "Interviews" tab is active by default
- Campaign cards render (or "No campaigns linked yet" if none)
- "Layer Map" tab shows the stub placeholder panel
- No research brief, links, or documents section visible

- [ ] **Step 5: Verify Value Propositions page**

Click **Value Propositions**. Confirm:
- Page loads without error
- Shows "No value propositions yet" placeholder (no pipeline run completed)
- "Run Pipeline →" button navigates to Dashboard

- [ ] **Step 6: Final commit with run number**

```bash
cd /Users/pboagents/Documents/agentpool1
python3 -m pytest tests/ --tb=short -q 2>&1 | tail -5
git add -A
git commit -m "chore: SP11a complete — nav reorder, Value Chain tabs, Discovery tabs, Value Propositions page"
```
