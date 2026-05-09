# SP11a — Nav Reorder and Workflow Restructure Design

## Overview

The current navigation order does not reflect the consulting workflow. Discovery inputs live on a page called "Discovery" but that label implies stakeholder work, not model setup. Value Propositions have no UI page at all. Stakeholders appear in the middle of the workflow nav as if they were a step, not a registry.

This sprint fixes the navigation order, moves content to match the workflow, and adds a stub Value Propositions page backed by the existing agent output.

**Intended workflow order (after this sprint):**

```
Dashboard → Value Chain → Discovery → Value Propositions → Roadmap → Business Plan → Stakeholders → Reviews → Runs → Documents
```

---

## 1. Nav Reorder

### File: `ui/src/components/AppLayout.tsx`

Change the `navItems` array order from:

```
Dashboard, Discovery, Value Chain, Roadmap, Stakeholders, Business Plan, Reviews, Runs, Documents
```

To:

```
Dashboard, Value Chain, Discovery, Value Propositions, Roadmap, Business Plan, Stakeholders, Reviews, Runs, Documents
```

The new "Value Propositions" nav item routes to `/:slug/value-propositions`.

### File: `ui/src/router.tsx`

Add import and route:

```tsx
import ValuePropositions from './pages/ValuePropositions'

// In children array, after value-chain:
{ path: ':slug/value-propositions', element: <ValuePropositions /> },
```

---

## 2. Value Chain Page — Two Tabs

### File: `ui/src/pages/ValueChain.tsx`

Add a tab strip with two tabs:

**Tab 1: Setup** (default when no value chain output exists)

Contains everything currently in `Discovery.tsx` that relates to discovery inputs:
- Research brief textarea
- Discovery links (add/remove/label)
- Priority document selector (checkbox list against uploaded documents)
- Save button (calls `PATCH /projects/{slug}/settings`)

All state, queries, and mutations currently in `Discovery.tsx` for these fields move here:
- `brief`, `links`, `selectedDocIds` state
- `useQuery(['settings', slug])` for initial load
- `useQuery(['documents', slug])` for document list
- `useMutation` calling `projectsApi.updateSettings`
- `saved` / `error` state

**Tab 2: Diagram** (default when a value chain output exists)

Existing Mermaid render and download button, unchanged.

**Default tab logic:**

```tsx
const [activeTab, setActiveTab] = useState<'setup' | 'diagram'>(
  outputs.length > 0 ? 'diagram' : 'setup'
)
```

`outputs` comes from the existing `useQuery(['value-chain', slug])`.

**Tab strip component** (inline, same pattern as Roadmap.tsx):

```tsx
<div className="flex border-b border-slate-700 mb-4">
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
```

---

## 3. Discovery Page — Two Tabs

### File: `ui/src/pages/Discovery.tsx`

**Remove** the entire top section: research brief, discovery links, priority document selector, save/error state, and all related queries/mutations. These move to `ValueChain.tsx`.

**Restructure** the remaining content into two tabs:

**Tab 1: Interviews** (default)

The existing campaign cards section (all SP10e work). No functional change — just now lives inside a tab panel.

**Tab 2: Layer Map** (stub)

A single placeholder panel:

```tsx
<div className="border border-slate-700 rounded-lg p-6 text-center">
  <p className="text-sm font-semibold text-slate-300 mb-2">Stakeholder Layer Assignment</p>
  <p className="text-xs text-slate-500 leading-relaxed max-w-md mx-auto">
    Stakeholders will be mapped to model layers here —
    investor → organisation → value stream → value chain → activity → customer.
    Interview findings will be displayed against each layer.
  </p>
</div>
```

Tab strip follows same pattern as Value Chain.

Default tab: `'interviews'`.

---

## 4. Value Propositions Page — New

### File: `ui/src/pages/ValuePropositions.tsx` (new)

**If portfolio register exists:** displays a ranked register table and expandable rows.

**If no data:** displays a placeholder with a Run Pipeline link.

#### Data source

`GET /projects/{slug}/portfolio-register` (new endpoint, see Section 5).

Returns `[]` when no register exists. Returns a JSON array of portfolio register items when it does.

#### Type (add to `ui/src/types.ts`)

```ts
export interface PortfolioItem {
  rank: number
  id: string                       // "VP-001"
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

#### API method (add to `ui/src/api/endpoints.ts`)

```ts
portfolioRegister: (slug: string): Promise<PortfolioItem[]> =>
  apiClient.get<PortfolioItem[]>(`/projects/${slug}/portfolio-register`).then((r) => r.data),
```

#### Page layout

```
Page heading: "Value Propositions"
Sub-heading: "Scored and ranked by the Portfolio Manager agent"

[If empty]
  Placeholder card:
    "No value propositions yet"
    "The Portfolio Manager agent scores and ranks propositions after
     the Value Design crew completes. Run the pipeline from the Dashboard."
    [Run Pipeline →] button → navigate to /:slug

[If data]
  Note banner (amber):
    "Scoring dimensions: value impact, feasibility, strategic fit.
     Six Capitals scoring (IIRC framework + safety + performance) coming in a future sprint."

  Table columns:
    Rank | ID | Title | Value Est. | Score (V) | Score (F) | Score (SF) | Total

  Each row is clickable to expand an inline detail panel:
    change_articulation (paragraph)
    Stakeholders: comma-joined impacted_stakeholder_groups
    Score rationales: three labelled paragraphs
    Weights used: formatted as "Value ×N, Feasibility ×N, Strategic Fit ×N"
```

---

## 5. Backend — Portfolio Register Endpoint

### File: `api/services/project_service.py`

Add service function:

```python
async def get_portfolio_register(slug: str) -> list | None:
    """Return the portfolio register JSON array for a project.

    Returns:
        None  — project not found
        []    — project exists but no portfolio_register.json on disk
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

### File: `api/routers/projects.py`

Add endpoint after the `roadmap-data` endpoint:

```python
@router.get("/{slug}/portfolio-register")
async def portfolio_register(slug: str, _user=Depends(get_current_user)):
    data = await get_portfolio_register(slug)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return data
```

### File: `tests/test_projects_api.py`

Add two tests:

```python
async def test_portfolio_register_empty(client, project):
    """Returns empty list when no portfolio_register.json exists."""
    resp = await client.get(f"/projects/{project}/portfolio-register",
                            headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json() == []

async def test_portfolio_register_returns_data(client, project, tmp_path, monkeypatch):
    """Returns parsed JSON when portfolio_register.json exists."""
    # Write fixture file to outputs dir
    register = [{"rank": 1, "id": "VP-001", "title": "Test VP",
                 "total_score": 82.5, "value_estimate": "High",
                 "score_value": 8.0, "score_feasibility": 7.0,
                 "score_strategic_fit": 9.0,
                 "score_value_rationale": "...",
                 "score_feasibility_rationale": "...",
                 "score_strategic_fit_rationale": "...",
                 "change_articulation": "...",
                 "impacted_stakeholder_groups": ["Ops"],
                 "weights_used": {"value": 5, "feasibility": 3, "strategic_fit": 2}}]
    outputs_dir = Path(settings.projects_dir) / project / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "portfolio_register.json").write_text(json.dumps(register))

    resp = await client.get(f"/projects/{project}/portfolio-register",
                            headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "VP-001"
```

---

## 6. Files Affected

### Modified
- `ui/src/components/AppLayout.tsx` — nav order + Value Propositions item
- `ui/src/router.tsx` — import + route for ValuePropositions
- `ui/src/pages/ValueChain.tsx` — add Setup tab, absorb discovery inputs state
- `ui/src/pages/Discovery.tsx` — remove inputs section, add tabs (Interviews | Layer Map stub)
- `ui/src/api/endpoints.ts` — add `portfolioRegister` method
- `ui/src/types.ts` — add `PortfolioItem` interface
- `api/services/project_service.py` — add `get_portfolio_register`
- `api/routers/projects.py` — add `GET /{slug}/portfolio-register`
- `tests/test_projects_api.py` — add 2 tests

### New
- `ui/src/pages/ValuePropositions.tsx`

---

## 7. Out of Scope

- Six Capitals scoring framework (SP11b) — portfolio_manager agent still uses value/feasibility/strategic_fit; this sprint only exposes current output
- Investor → org → value stream → value chain → activity → customer model hierarchy (SP11c)
- Stakeholder → layer assignment (SP11c)
- Discovery findings mapped to model layers (SP11c)
- Any changes to agent tasks or prompts
