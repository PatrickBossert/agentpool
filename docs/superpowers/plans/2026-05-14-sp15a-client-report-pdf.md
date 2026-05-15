# SP15a — Client Report PDF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a print-to-PDF report page at `/:slug/report` that renders value propositions, initiative register, financial summary, and document references in a polished A4 layout — accessed via an "Export Report" button on the Dashboard.

**Architecture:** A standalone `Report.tsx` page registered as a top-level route (outside `AppLayout`, with `ProtectedRoute`). It fires four parallel `useQuery` calls on mount, renders five sections (cover, value propositions, initiative register, financial summary, document reference), then auto-triggers `window.print()` after 300ms. Print styles live in a companion `Report.css` file using `@media print`.

**Tech Stack:** React 18, TanStack Query v5, React Router v6, recharts (already installed), Tailwind CSS + `@media print` in `Report.css`, Vitest + Testing Library for tests.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `ui/src/pages/Report.tsx` | **Create** | Full report page — all 5 sections, data fetching, auto-print |
| `ui/src/pages/Report.css` | **Create** | Print-specific styles (white bg, A4 sizing, page breaks) |
| `ui/src/router.tsx` | **Modify** | Add `/:slug/report` route outside AppLayout |
| `ui/src/pages/Dashboard.tsx` | **Modify** | Add "Export Report" button near "View Last Run →" |
| `ui/src/__tests__/Report.test.tsx` | **Create** | Smoke tests — renders cover, sections, no crash when data missing |

---

## Task 1: Report.tsx + Report.css + route

**Files:**
- Create: `ui/src/pages/Report.tsx`
- Create: `ui/src/pages/Report.css`
- Modify: `ui/src/router.tsx`
- Create: `ui/src/__tests__/Report.test.tsx`

### Step 1 — Write the failing tests

- [ ] Create `ui/src/__tests__/Report.test.tsx`:

```tsx
// ui/src/__tests__/Report.test.tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import Report from '../pages/Report'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getSettings: vi.fn().mockResolvedValue({
      sector: 'Transport',
      llm_mode: 'standard',
      stakeholder_groups: [],
      value_stream_labels: [],
      roadmap_time_axis: 'quarters',
      crews_enabled: [],
      review_gates: false,
      slack_channel: '',
      discovery_brief: '',
      discovery_links: [],
      discovery_document_ids: [],
      interview_method: 'none',
    }),
    financialSummary: vi.fn().mockResolvedValue({
      npv: 1200000,
      irr: 0.18,
      payback_period: '18 months',
      max_borrowing: 500000,
      total_investment: 800000,
      total_benefits: 2000000,
    }),
    portfolioRegister: vi.fn().mockResolvedValue([
      {
        rank: 1,
        id: 'vp1',
        title: 'Improve customer onboarding',
        change_articulation: 'Reduce friction in signup',
        impacted_stakeholder_groups: ['customers'],
        value_estimate: 'High',
        score_financial: 7,
        score_financial_rationale: '',
        score_financial_unit: '',
        score_manufactured: 5,
        score_manufactured_rationale: '',
        score_manufactured_unit: '',
        score_intellectual: 6,
        score_intellectual_rationale: '',
        score_intellectual_unit: '',
        score_human: 8,
        score_human_rationale: '',
        score_human_unit: '',
        score_social_relationship: 7,
        score_social_relationship_rationale: '',
        score_social_relationship_unit: '',
        score_natural: 3,
        score_natural_rationale: '',
        score_natural_unit: '',
        score_safety: 4,
        score_safety_rationale: '',
        score_safety_unit: '',
        score_performance: 8,
        score_performance_rationale: '',
        score_performance_unit: '',
        total_score: 6.5,
        weights_used: { financial: 1, manufactured: 1, intellectual: 1, human: 1, social_relationship: 1, natural: 1, safety: 1, performance: 1 },
      },
    ]),
    roadmapData: vi.fn().mockResolvedValue({
      periods: ['Q1 2026'],
      value_streams: ['Customer Experience'],
      stakeholder_groups: [],
      initiatives: [
        {
          id: 'i1',
          title: 'CRM Upgrade',
          description: 'Upgrade the CRM system',
          proposition_ids: [],
          capability_uplifts: [],
          initiative_type: 'enabler',
          enabler_dependencies: [],
          change_dependencies: [],
          complexity_score: 3,
          complexity_rationale: '',
          cost_estimate: { low: 100000, high: 150000, currency: 'GBP', rationale: '' },
          related_requirements: [],
          value_streams: ['Customer Experience'],
          period: 'Q1 2026',
        },
      ],
      propositions: [],
    }),
    outputs: vi.fn().mockResolvedValue([
      { id: 1, agent_name: 'business_plan_generator', output_type: 'docx', file_path: '/outputs/plan.docx', version: 1, review_status: 'approved', created_at: '2026-05-14T10:00:00' },
    ]),
  },
}))

vi.mock('../context/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => ({ token: 'test-token', user: null, login: vi.fn(), logout: vi.fn() }),
}))

function renderReport() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/smoke-test/report']}>
          <Routes>
            <Route path="/:slug/report" element={<Report />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

describe('Report', () => {
  it('renders the project slug on the cover', async () => {
    renderReport()
    expect(await screen.findByText(/smoke-test/i)).toBeInTheDocument()
  })

  it('renders the financial summary section heading', async () => {
    renderReport()
    expect(await screen.findByText(/financial summary/i)).toBeInTheDocument()
  })

  it('renders value propositions section heading', async () => {
    renderReport()
    expect(await screen.findByText(/value propositions/i)).toBeInTheDocument()
  })

  it('renders initiative register section heading', async () => {
    renderReport()
    expect(await screen.findByText(/initiative register/i)).toBeInTheDocument()
  })

  it('renders document reference section heading', async () => {
    renderReport()
    expect(await screen.findByText(/deliverables/i)).toBeInTheDocument()
  })
})
```

### Step 2 — Run tests to confirm they fail

- [ ] Run: `cd /path/to/worktree/ui && npm test -- --run src/__tests__/Report.test.tsx`
- Expected: FAIL — "Cannot find module '../pages/Report'"

### Step 3 — Create Report.css

- [ ] Create `ui/src/pages/Report.css`:

```css
/* ui/src/pages/Report.css — print styles for client report */

/* Screen: preview container */
.report-root {
  min-height: 100vh;
  background: #1a1825;
  color: #e2e8f0;
  font-family: 'Inter', system-ui, sans-serif;
}

.report-print-btn {
  position: fixed;
  top: 1rem;
  right: 1rem;
  z-index: 50;
  padding: 0.5rem 1.25rem;
  background: #19d4e8;
  color: #0f172a;
  border: none;
  border-radius: 0.5rem;
  font-weight: 600;
  font-size: 0.875rem;
  cursor: pointer;
}

.report-print-btn:hover {
  background: #7eedf6;
}

/* Page sections */
.report-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 3rem 2rem;
}

.report-section {
  padding: 3rem 2rem;
  max-width: 900px;
  margin: 0 auto;
}

/* Cover page */
.report-cover {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
  padding: 4rem;
  border-bottom: 2px solid #19d4e8;
}

/* Section headers */
.report-section-title {
  font-size: 1.25rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #19d4e8;
  border-bottom: 1px solid #334155;
  padding-bottom: 0.5rem;
  margin-bottom: 1.5rem;
}

/* Metric cards */
.report-metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

.report-metric-card {
  background: #2a2640;
  border-radius: 0.5rem;
  padding: 1rem;
}

/* Initiative table */
.report-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}

.report-table th {
  text-align: left;
  padding: 0.5rem 0.75rem;
  background: #2a2640;
  color: #94a3b8;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: 0.7rem;
}

.report-table td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid #1e293b;
  vertical-align: top;
}

.report-table .group-header td {
  background: #1a1825;
  color: #64748b;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 0.75rem 0.75rem 0.25rem;
}

/* ── PRINT OVERRIDES ──────────────────────────────────────────────────── */
@media print {
  @page {
    size: A4;
    margin: 18mm 15mm;
  }

  body {
    background: white !important;
    color: #111 !important;
    font-size: 11pt;
  }

  .report-print-btn {
    display: none !important;
  }

  .report-root {
    background: white;
    color: #111;
  }

  .report-cover {
    border-bottom: 2px solid #19d4e8;
    page-break-after: always;
  }

  .report-section {
    page-break-before: always;
  }

  .report-section-title {
    color: #0891b2;
  }

  .report-metric-card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
  }

  .report-table th {
    background: #f1f5f9;
    color: #475569;
  }

  .report-table td {
    border-bottom: 1px solid #e2e8f0;
    color: #1e293b;
  }

  .report-table .group-header td {
    background: #f8fafc;
    color: #64748b;
  }
}
```

### Step 4 — Create Report.tsx

- [ ] Create `ui/src/pages/Report.tsx`:

```tsx
// ui/src/pages/Report.tsx
import { useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
  ResponsiveContainer,
} from 'recharts'
import { projectsApi } from '../api/endpoints'
import type { PortfolioItem, Initiative, CostEstimate } from '../types'
import './Report.css'

// ── Constants ─────────────────────────────────────────────────────────────────

const DIMENSIONS = [
  { key: 'financial' as const,           label: 'Financial' },
  { key: 'manufactured' as const,        label: 'Manufactured' },
  { key: 'intellectual' as const,        label: 'Intellectual' },
  { key: 'human' as const,               label: 'Human' },
  { key: 'social_relationship' as const, label: 'Social' },
  { key: 'natural' as const,             label: 'Natural' },
  { key: 'safety' as const,              label: 'Safety' },
  { key: 'performance' as const,         label: 'Performance' },
]

type DimKey = typeof DIMENSIONS[number]['key']

const DELIVERABLE_TYPES: Record<string, string> = {
  docx: 'Business Plan',
  pptx: 'Executive Presentation',
  excel: 'Cost/Benefit Financial Model',
}

// ── Formatters ────────────────────────────────────────────────────────────────

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

function fmtCostRange(c: CostEstimate): string {
  return `${fmtCurrency(c.low)} – ${fmtCurrency(c.high)}`
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
}

function slugToTitle(slug: string): string {
  return slug.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

// ── Radar helpers ─────────────────────────────────────────────────────────────

function getScore(item: PortfolioItem, key: DimKey): number {
  const map: Record<DimKey, number> = {
    financial: item.score_financial,
    manufactured: item.score_manufactured,
    intellectual: item.score_intellectual,
    human: item.score_human,
    social_relationship: item.score_social_relationship,
    natural: item.score_natural,
    safety: item.score_safety,
    performance: item.score_performance,
  }
  return map[key]
}

function radarData(item: PortfolioItem) {
  return DIMENSIONS.map(({ key, label }) => ({
    dimension: label,
    score: getScore(item, key),
    neutral: 5,
  }))
}

// ── Sub-sections ──────────────────────────────────────────────────────────────

function CoverPage({ slug, sector }: { slug: string; sector: string }) {
  return (
    <div className="report-cover">
      <p className="text-sm font-mono uppercase tracking-widest mb-4" style={{ color: '#19d4e8' }}>
        Digital Modernisation Strategy
      </p>
      <h1 className="text-5xl font-bold mb-3 print:text-4xl print:text-black">
        {slugToTitle(slug)}
      </h1>
      <p className="text-xl mb-2 text-slate-400 print:text-slate-600">{sector}</p>
      <p className="text-sm text-slate-500 mt-8 print:text-slate-500">
        Generated {new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}
      </p>
      <p className="text-xs text-slate-600 mt-2 print:text-slate-400">Prepared by AgentPool</p>
    </div>
  )
}

function ValuePropositionsSection({ items }: { items: PortfolioItem[] }) {
  if (items.length === 0) {
    return (
      <div className="report-section">
        <h2 className="report-section-title">Value Propositions</h2>
        <p className="text-slate-500 text-sm">No value propositions generated yet.</p>
      </div>
    )
  }
  return (
    <div className="report-section">
      <h2 className="report-section-title">Value Propositions</h2>
      <div className="space-y-8">
        {items.map((item) => (
          <div key={item.id} className="border border-slate-700 rounded-xl p-4 print:border-slate-200">
            <div className="flex items-start justify-between mb-2">
              <h3 className="text-base font-semibold text-slate-100 print:text-black">
                {item.rank}. {item.title}
              </h3>
              <span className="text-xs font-mono text-slate-400 print:text-slate-500">
                Score {item.total_score.toFixed(1)}
              </span>
            </div>
            <p className="text-sm text-slate-400 mb-4 print:text-slate-600">{item.change_articulation}</p>
            <ResponsiveContainer width="100%" height={180}>
              <RadarChart data={radarData(item)}>
                <PolarGrid stroke="#334155" />
                <PolarAngleAxis dataKey="dimension" tick={{ fill: '#94a3b8', fontSize: 9 }} />
                <Radar name="neutral" dataKey="neutral" stroke="#475569" strokeDasharray="3 3" fill="none" dot={false} />
                <Radar name="score" dataKey="score" stroke="#19d4e8" fill="#19d4e8" fillOpacity={0.25} dot={false} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        ))}
      </div>
    </div>
  )
}

function InitiativeRegisterSection({ initiatives }: { initiatives: Initiative[] }) {
  if (initiatives.length === 0) {
    return (
      <div className="report-section">
        <h2 className="report-section-title">Initiative Register</h2>
        <p className="text-slate-500 text-sm">No initiatives generated yet.</p>
      </div>
    )
  }

  // Group by first value stream (or 'Unassigned')
  const groups: Record<string, Initiative[]> = {}
  for (const init of initiatives) {
    const key = init.value_streams && init.value_streams.length > 0 ? init.value_streams[0] : 'Unassigned'
    groups[key] = groups[key] ?? []
    groups[key].push(init)
  }

  return (
    <div className="report-section">
      <h2 className="report-section-title">Initiative Register</h2>
      <table className="report-table">
        <thead>
          <tr>
            <th>Initiative</th>
            <th>Type</th>
            <th>Cost Estimate</th>
            <th>Period</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(groups).map(([vs, inits]) => (
            <>
              <tr key={`group-${vs}`} className="group-header">
                <td colSpan={4}>{vs}</td>
              </tr>
              {inits.map((init) => (
                <tr key={init.id}>
                  <td>
                    <p className="font-medium text-slate-100 print:text-black">{init.title}</p>
                    <p className="text-slate-500 text-xs mt-0.5 print:text-slate-500 line-clamp-2">
                      {init.description}
                    </p>
                  </td>
                  <td>
                    <span className="capitalize">{init.initiative_type.replace('_', ' ')}</span>
                  </td>
                  <td>{fmtCostRange(init.cost_estimate)}</td>
                  <td>{init.period ?? '—'}</td>
                </tr>
              ))}
            </>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function FinancialSummarySection({ summary }: { summary: { npv: number | null; irr: number | null; payback_period: string | null; max_borrowing: number | null; total_investment: number | null; total_benefits: number | null } | null }) {
  const metrics = [
    { label: 'NPV', value: fmtCurrency(summary?.npv ?? null), colour: '#19d4e8' },
    { label: 'IRR', value: fmtPercent(summary?.irr ?? null), colour: '#19d4e8' },
    { label: 'Payback Period', value: summary?.payback_period ?? '—', colour: '#94a3b8' },
    { label: 'Total Investment', value: fmtCurrency(summary?.total_investment ?? null), colour: '#f87171' },
    { label: 'Total Benefits', value: fmtCurrency(summary?.total_benefits ?? null), colour: '#47c247' },
    { label: 'Max Borrowing', value: fmtCurrency(summary?.max_borrowing ?? null), colour: '#f59e0b' },
  ]

  return (
    <div className="report-section">
      <h2 className="report-section-title">Financial Summary</h2>
      <div className="report-metrics-grid">
        {metrics.map(({ label, value, colour }) => (
          <div key={label} className="report-metric-card">
            <p className="text-xs uppercase tracking-widest text-slate-500 mb-1 print:text-slate-400">{label}</p>
            <p className="text-2xl font-bold print:text-xl" style={{ color: colour }}>{value}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function DeliverablesSection({ outputs }: { outputs: { id: number; output_type: string; agent_name: string; version: number; created_at: string }[] }) {
  const deliverables = outputs.filter((o) => DELIVERABLE_TYPES[o.output_type])

  return (
    <div className="report-section">
      <h2 className="report-section-title">Deliverables</h2>
      {deliverables.length === 0 ? (
        <p className="text-slate-500 text-sm">No deliverable files generated yet.</p>
      ) : (
        <table className="report-table">
          <thead>
            <tr>
              <th>Document</th>
              <th>Format</th>
              <th>Version</th>
              <th>Generated</th>
            </tr>
          </thead>
          <tbody>
            {deliverables.map((o) => (
              <tr key={o.id}>
                <td className="text-slate-100 print:text-black">{DELIVERABLE_TYPES[o.output_type]}</td>
                <td className="uppercase font-mono text-xs text-slate-400">{o.output_type}</td>
                <td>v{o.version}</td>
                <td className="text-slate-400 print:text-slate-600">{fmtDate(o.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="text-xs text-slate-600 mt-4 print:text-slate-400">
        Full documents available in the AgentPool Documents tab for this project.
      </p>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Report() {
  const { slug } = useParams<{ slug: string }>()

  // Auto-trigger print dialog after short delay to allow render
  useEffect(() => {
    const timer = setTimeout(() => window.print(), 300)
    return () => clearTimeout(timer)
  }, [])

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug!),
    enabled: !!slug,
  })

  const { data: financialSummary = null } = useQuery({
    queryKey: ['financial-summary', slug],
    queryFn: () => projectsApi.financialSummary(slug!),
    enabled: !!slug,
  })

  const { data: propositions = [] } = useQuery({
    queryKey: ['portfolio-register', slug],
    queryFn: () => projectsApi.portfolioRegister(slug!),
    enabled: !!slug,
  })

  const { data: roadmapData } = useQuery({
    queryKey: ['roadmap-data', slug],
    queryFn: () => projectsApi.roadmapData(slug!),
    enabled: !!slug,
  })

  const { data: outputs = [] } = useQuery({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.outputs(slug!),
    enabled: !!slug,
  })

  const initiatives: Initiative[] = roadmapData?.initiatives ?? []

  return (
    <div className="report-root">
      <button className="report-print-btn" onClick={() => window.print()}>
        Print / Save as PDF
      </button>

      <CoverPage slug={slug ?? ''} sector={settings?.sector ?? ''} />
      <ValuePropositionsSection items={propositions} />
      <InitiativeRegisterSection initiatives={initiatives} />
      <FinancialSummarySection summary={financialSummary} />
      <DeliverablesSection outputs={outputs} />
    </div>
  )
}
```

### Step 5 — Add route to router.tsx

- [ ] Open `ui/src/router.tsx`. Add the import and route.

At the top of the file, add the import after the existing imports:
```tsx
import Report from './pages/Report'
```

Inside the `createBrowserRouter([...])` array, add a new top-level entry BEFORE the `'/'` catch-all route:
```tsx
{
  path: '/:slug/report',
  element: (
    <ProtectedRoute>
      <Report />
    </ProtectedRoute>
  ),
},
```

The full updated router.tsx will look like:
```tsx
// ui/src/router.tsx
import { createBrowserRouter, Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from './context/AuthContext'
import AppLayout from './components/AppLayout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Documents from './pages/Documents'
import ValueChain from './pages/ValueChain'
import Roadmap from './pages/Roadmap'
import RunDetail from './pages/RunDetail'
import Settings from './pages/Settings'
import BusinessPlan from './pages/BusinessPlan'
import Reviews from './pages/Reviews'
import Runs from './pages/Runs'
import Stakeholders from './pages/Stakeholders'
import StakeholderForm from './pages/StakeholderForm'
import Discovery from './pages/Discovery'
import ValuePropositions from './pages/ValuePropositions'
import Assignment from './pages/Assignment'
import VoiceInterview from './pages/VoiceInterview'
import Templates from './pages/Templates'
import Report from './pages/Report'

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <Login />,
  },
  {
    path: '/interview/:sessionToken',
    element: <VoiceInterview />,
  },
  {
    path: '/:slug/report',
    element: (
      <ProtectedRoute>
        <Report />
      </ProtectedRoute>
    ),
  },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
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
      { path: ':slug/assignment', element: <Assignment /> },
      { path: ':slug/templates', element: <Templates /> },
      { path: ':slug/settings', element: <Settings /> },
    ],
  },
])
```

### Step 6 — Run tests to confirm they pass

- [ ] Run: `cd ui && npm test -- --run src/__tests__/Report.test.tsx`
- Expected: 5 tests pass

### Step 7 — Verify TypeScript compiles clean

- [ ] Run: `cd ui && npx tsc --noEmit 2>&1 | grep -E "Report" | head -20`
- Expected: no errors for Report.tsx

### Step 8 — Commit Task 1

- [ ] Run:
```bash
git add ui/src/pages/Report.tsx ui/src/pages/Report.css ui/src/router.tsx ui/src/__tests__/Report.test.tsx
git commit -m "feat(sp15a): Report page — cover, propositions, initiative register, financials, deliverables + print CSS + route"
```

---

## Task 2: Dashboard "Export Report" button + smoke test

**Files:**
- Modify: `ui/src/pages/Dashboard.tsx`

### Step 1 — Add Export Report button to Dashboard.tsx

- [ ] In `ui/src/pages/Dashboard.tsx`, find the project header section (lines 75–85):

```tsx
{/* Project header */}
<div className="flex items-center justify-between">
  <h2 className="text-lg font-semibold text-slate-100">{slug}</h2>
  {(orch?.status === 'completed' || orch?.status === 'failed') && (
    <button
      onClick={() => navigate(`/${slug}/runs/${orch.id}`)}
      className="text-xs text-brand hover:text-brand-light"
    >
      View Last Run →
    </button>
  )}
</div>
```

Replace with:

```tsx
{/* Project header */}
<div className="flex items-center justify-between">
  <h2 className="text-lg font-semibold text-slate-100">{slug}</h2>
  <div className="flex items-center gap-3">
    <button
      onClick={() => window.open(`/${slug}/report`, '_blank')}
      className="text-xs px-3 py-1.5 rounded bg-surface-card border border-slate-700 text-slate-300 hover:text-slate-100 hover:border-slate-500"
    >
      Export Report
    </button>
    {(orch?.status === 'completed' || orch?.status === 'failed') && (
      <button
        onClick={() => navigate(`/${slug}/runs/${orch.id}`)}
        className="text-xs text-brand hover:text-brand-light"
      >
        View Last Run →
      </button>
    )}
  </div>
</div>
```

### Step 2 — Verify TypeScript compiles

- [ ] Run: `cd ui && npx tsc --noEmit 2>&1 | grep -E "Dashboard" | head -10`
- Expected: no errors

### Step 3 — Smoke test in browser

- [ ] With the dev server running (`cd ui && npm run dev -- --port 3000`), navigate to `http://localhost:3000`
- [ ] Log in with `admin` / `changeme`
- [ ] Click the `smoke-test` project
- [ ] Confirm "Export Report" button is visible in the header area, to the left of "View Last Run →"
- [ ] Click "Export Report" — a new browser tab should open at `http://localhost:3000/smoke-test/report`
- [ ] The print dialog should fire automatically after ~300ms
- [ ] Cancel the dialog — inspect the page:
  - Cover page shows "Smoke Test" (slugToTitle applied), sector, and generation date
  - Value Propositions section heading visible
  - Initiative Register section heading visible
  - Financial Summary section heading visible
  - Deliverables section heading visible
- [ ] "Print / Save as PDF" button visible in top-right
- [ ] Click "Print / Save as PDF" — print dialog fires again

### Step 4 — Commit Task 2

- [ ] Run:
```bash
git add ui/src/pages/Dashboard.tsx
git commit -m "feat(sp15a): Export Report button on Dashboard — opens report in new tab"
```
