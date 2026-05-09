# SP10e — Dashboard Retheme, Org Chart & Interview Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Swap brand accent from purple to Future Edge teal/green, replace the Dashboard with an org chart + live info card, and add a campaign-linked stakeholder interview import/export/reminder workflow.

**Architecture:** Three sequential groups — (1) CSS token swap (tailwind.config.js + hardcoded sky-* class replacement), (2) Dashboard rewrite using two new pure components (OrgChart, InfoCard), (3) backend campaigns feature (DB → service → router) + Discovery page Interviews section + Reviews page reminder email rendering.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, FastAPI, aiosqlite, pytest-asyncio

---

## File Map

### New files
- `ui/src/components/OrgChart.tsx`
- `ui/src/components/InfoCard.tsx`
- `ui/src/api/campaigns.ts`
- `api/routers/campaigns.py`
- `api/services/campaign_service.py`
- `tests/test_campaigns.py`

### Modified files
- `ui/tailwind.config.js` — brand token values
- `ui/src/components/AppLayout.tsx` — sky-* → brand
- `ui/src/pages/Dashboard.tsx` — full rewrite
- `ui/src/pages/Discovery.tsx` — add Interviews section
- `ui/src/pages/Reviews.tsx` — add reminder email section
- `ui/src/types.ts` — Campaign, ReminderEmail, InterviewSummary types
- `ui/src/api/endpoints.ts` — import campaignsApi
- `api/database.py` — _migrate_campaigns() + 6 new helpers
- `api/main.py` — include campaigns router

---

## Task 1: Brand token swap

**Files:**
- Modify: `ui/tailwind.config.js`
- Modify: `ui/src/components/AppLayout.tsx`
- Modify: `ui/src/pages/Dashboard.tsx`
- Modify: `ui/src/pages/Discovery.tsx`

- [ ] **Step 1: Update tailwind.config.js**

Replace the entire file:

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#19d4e8',
          light: '#7eedf6',
          dark: '#0fa8b8',
          green: '#47c247',
        },
        surface: {
          DEFAULT: '#1a1825',
          raised: '#221f33',
          card: '#2a2640',
        },
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 2: Grep for hardcoded sky-* classes to replace**

```bash
grep -rn "sky-" ui/src --include="*.tsx" | grep -v node_modules
```

Expected matches in: `AppLayout.tsx`, `Dashboard.tsx`, `Discovery.tsx`, `Reviews.tsx`.

- [ ] **Step 3: Update AppLayout.tsx — active nav + sidebar**

In `ui/src/components/AppLayout.tsx`, replace all sky- references:

Line 64–65 (active nav link class):
```tsx
// OLD:
isActive
  ? 'text-sky-300 border-sky-300'
  : 'text-slate-400 border-transparent hover:text-slate-200'
// NEW:
isActive
  ? 'text-brand border-brand'
  : 'text-slate-400 border-transparent hover:text-slate-200'
```

Line 118–121 (sidebar active project):
```tsx
// OLD:
slug === p.slug
  ? 'bg-sky-900/40 text-sky-300'
  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
// NEW:
slug === p.slug
  ? 'bg-brand/10 text-brand'
  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
```

- [ ] **Step 4: Update Dashboard.tsx — Run Pipeline button + links**

In `ui/src/pages/Dashboard.tsx` replace:
- `bg-sky-600 hover:bg-sky-500` → `bg-brand hover:bg-brand-dark`
- `text-sky-400 hover:text-sky-300` → `text-brand hover:text-brand-light`
- `border border-sky-900/40` → `border border-brand/20`

- [ ] **Step 5: Update Discovery.tsx — inputs + Add button**

In `ui/src/pages/Discovery.tsx` replace:
- `focus:border-sky-600` → `focus:border-brand`
- `bg-sky-700 hover:bg-sky-600` → `bg-brand hover:bg-brand-dark`
- `accent-sky-500` → `accent-brand`
- `text-sky-400` → `text-brand`

- [ ] **Step 6: Verify no remaining sky- in source (except intentional semantic uses)**

```bash
grep -rn "sky-" ui/src --include="*.tsx" | grep -v "node_modules"
```

Review any remaining hits — `sky-` in semantic contexts (e.g. `text-sky-*` in data visualisation) can stay; brand accent uses must be `brand`.

- [ ] **Step 7: Commit**

```bash
git add ui/tailwind.config.js ui/src/components/AppLayout.tsx ui/src/pages/Dashboard.tsx ui/src/pages/Discovery.tsx
git commit -m "style: swap brand tokens to Future Edge teal/green, replace sky- nav classes"
```

---

## Task 2: OrgChart component

**Files:**
- Create: `ui/src/components/OrgChart.tsx`

- [ ] **Step 1: Create the file**

```tsx
// ui/src/components/OrgChart.tsx
import type { CrewRun } from '../types'

export const CREW_ORDER = [
  'discovery',
  'value_design',
  'architecture',
  'delivery',
  'business_plan',
] as const

export type CrewName = (typeof CREW_ORDER)[number]

export const CREW_LABELS: Record<CrewName, string> = {
  discovery: 'Discovery',
  value_design: 'Value Design',
  architecture: 'Architecture',
  delivery: 'Delivery',
  business_plan: 'Business Plan',
}

export const CREW_AGENTS: Record<CrewName, string[]> = {
  discovery: ['Value Chain Mapper', 'Industry Analyst', 'Document Analyst'],
  value_design: ['Value Prop Generator', 'Portfolio Manager'],
  architecture: ['Solution Architect', 'Tech Evaluator'],
  delivery: ['Delivery Planner', 'Risk Analyst'],
  business_plan: ['Financial Modeller', 'Report Writer'],
}

type AgentStatus = 'completed' | 'running' | 'queued'

function inferAgentStatuses(agents: string[], logs: string[]): AgentStatus[] {
  const joined = logs.join('\n').toLowerCase()
  let lastIdx = -1
  agents.forEach((agent, idx) => {
    if (joined.includes(agent.toLowerCase())) lastIdx = idx
  })
  return agents.map((_, idx) => {
    if (lastIdx === -1) return 'queued'
    if (idx < lastIdx) return 'completed'
    if (idx === lastIdx) return 'running'
    return 'queued'
  })
}

interface CrewNodeProps {
  name: CrewName
  crewRun: CrewRun | undefined
  isActive: boolean
  isIdle: boolean
  logs: string[]
  interviewBadge?: string | null
  onClick: () => void
}

function CrewNode({ name, crewRun, isActive, isIdle, logs, interviewBadge, onClick }: CrewNodeProps) {
  const status = crewRun?.status ?? 'queued'
  const agents = CREW_AGENTS[name]
  const agentStatuses = isActive ? inferAgentStatuses(agents, logs) : null

  const borderClass =
    status === 'completed'
      ? 'border-brand-green'
      : isActive
        ? 'border-brand'
        : 'border-slate-700'

  const bgClass =
    status === 'completed'
      ? 'bg-brand-green/5'
      : isActive
        ? 'bg-brand/5'
        : 'bg-surface-card'

  const opacityClass = isIdle || (!isActive && status === 'queued') ? 'opacity-50' : ''

  return (
    <div className={`flex flex-col gap-1 ${opacityClass}`}>
      <button
        onClick={onClick}
        className={`relative border ${borderClass} ${bgClass} rounded-lg px-3 py-2.5 text-left transition-all min-w-[110px]`}
      >
        {isActive && (
          <span className="absolute top-2 right-2 w-2 h-2 rounded-full bg-brand animate-pulse" />
        )}
        {status === 'completed' && (
          <span className="absolute top-2 right-2 text-brand-green text-xs">✓</span>
        )}
        <p className="text-xs font-semibold text-slate-200 pr-4">{CREW_LABELS[name]}</p>
        {interviewBadge && name === 'discovery' && (
          <p className="text-[10px] text-brand mt-0.5">{interviewBadge}</p>
        )}
      </button>

      {isActive && agentStatuses && (
        <div className="ml-3 flex flex-col gap-1 border-l-2 border-brand/30 pl-2">
          {agents.map((agent, idx) => {
            const s = agentStatuses[idx]
            return (
              <div key={agent} className="flex items-center gap-1.5">
                <span className={`text-[10px] ${
                  s === 'completed' ? 'text-brand-green' :
                  s === 'running' ? 'text-brand' :
                  'text-slate-600'
                }`}>
                  {s === 'completed' ? '✓' : s === 'running' ? '▶' : '○'}
                </span>
                <span className={`text-[10px] ${
                  s === 'completed' ? 'text-slate-400' :
                  s === 'running' ? 'text-slate-200 font-medium' :
                  'text-slate-600'
                }`}>{agent}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

interface OrgChartProps {
  crewRuns: CrewRun[]
  isPipelineActive: boolean
  logs: string[]
  interviewBadge?: string | null
  onCrewClick?: (name: CrewName) => void
}

export default function OrgChart({ crewRuns, isPipelineActive, logs, interviewBadge, onCrewClick }: OrgChartProps) {
  const runMap = new Map(crewRuns.map((r) => [r.crew_name, r]))
  const activeCrewName = crewRuns.find((r) => r.status === 'running')?.crew_name as CrewName | undefined

  return (
    <div className="flex flex-col items-center gap-2">
      {/* PAM node */}
      <div className={`border rounded-lg px-4 py-2 text-center transition-all ${
        isPipelineActive
          ? 'border-brand bg-brand/5'
          : 'border-slate-700 bg-surface-card opacity-50'
      }`}>
        <div className="flex items-center gap-2">
          {isPipelineActive && (
            <span className="w-2 h-2 rounded-full bg-brand animate-pulse" />
          )}
          <p className="text-xs font-bold text-slate-200">PAM</p>
          {isPipelineActive && (
            <span className="w-2 h-2 rounded-full bg-brand animate-pulse" />
          )}
        </div>
        <p className="text-[10px] text-slate-500 mt-0.5">Orchestrator</p>
      </div>

      {/* Connector line */}
      <div className={`w-px h-4 ${isPipelineActive ? 'bg-brand/30' : 'bg-slate-700'}`} />

      {/* Horizontal bar */}
      <div className={`w-full h-px ${isPipelineActive ? 'bg-brand/30' : 'bg-slate-700'}`} />

      {/* Crew nodes */}
      <div className="flex gap-3 items-start justify-center w-full pt-1">
        {CREW_ORDER.map((name) => (
          <CrewNode
            key={name}
            name={name}
            crewRun={runMap.get(name)}
            isActive={activeCrewName === name}
            isIdle={!isPipelineActive}
            logs={logs}
            interviewBadge={interviewBadge}
            onClick={() => onCrewClick?.(name)}
          />
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add ui/src/components/OrgChart.tsx
git commit -m "feat: add OrgChart component with agent sub-nodes and interview badge"
```

---

## Task 3: InfoCard component

**Files:**
- Create: `ui/src/components/InfoCard.tsx`

- [ ] **Step 1: Create the file**

```tsx
// ui/src/components/InfoCard.tsx
import type { CrewRun } from '../types'
import { CREW_AGENTS, CREW_LABELS, type CrewName } from './OrgChart'

function inferCurrentAgent(crewName: CrewName, logs: string[]): string | null {
  const agents = CREW_AGENTS[crewName]
  const joined = logs.join('\n').toLowerCase()
  let lastFound: string | null = null
  for (const agent of agents) {
    if (joined.includes(agent.toLowerCase())) lastFound = agent
  }
  return lastFound ?? agents[0] ?? null
}

function computeProgress(crewName: CrewName, logs: string[]): number {
  const agents = CREW_AGENTS[crewName]
  const joined = logs.join('\n').toLowerCase()
  let completed = 0
  for (const agent of agents) {
    if (joined.includes(agent.toLowerCase())) completed++
  }
  // At least one agent is active; don't show 100% unless crew_run.status = completed
  return Math.min(Math.round((completed / agents.length) * 100), 95)
}

interface InfoCardActiveProps {
  activeRun: CrewRun
  logs: string[]
  interviewBadge?: string | null
}

function ActiveState({ activeRun, logs, interviewBadge }: InfoCardActiveProps) {
  const crewName = activeRun.crew_name as CrewName
  const agent = inferCurrentAgent(crewName, logs)
  const progress = computeProgress(crewName, logs)

  return (
    <div className="flex flex-col gap-3 h-full">
      <div>
        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Active Crew</p>
        <p className="text-sm font-semibold text-brand">{CREW_LABELS[crewName] ?? crewName}</p>
        {agent && (
          <p className="text-xs text-slate-400 mt-0.5">↳ {agent}</p>
        )}
      </div>

      {/* Progress bar */}
      <div>
        <div className="flex justify-between text-[10px] text-slate-500 mb-1">
          <span>Progress</span>
          <span>{progress}%</span>
        </div>
        <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-brand rounded-full transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {interviewBadge && (
        <div className="text-[10px] text-brand border border-brand/20 rounded px-2 py-1 bg-brand/5">
          Stakeholder interviews: {interviewBadge}
        </div>
      )}

      {/* Live log */}
      <div className="flex-1 min-h-0">
        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Live Log</p>
        <div className="bg-black/40 rounded p-2 font-mono text-[10px] text-emerald-400 overflow-y-auto max-h-40 space-y-0.5">
          {logs.length === 0 ? (
            <p className="text-slate-600">Waiting for agent output…</p>
          ) : (
            logs.slice(-10).map((line, i) => <p key={i}>{line}</p>)
          )}
        </div>
      </div>
    </div>
  )
}

interface InfoCardIdleProps {
  lastRun?: { started_at: string | null; completed_at: string | null } | null
  onRun: () => void
  isRunning: boolean
}

function IdleState({ lastRun, onRun, isRunning }: InfoCardIdleProps) {
  function fmtDate(s: string | null) {
    if (!s) return '—'
    return new Date(s).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
  }

  function duration(started: string | null, completed: string | null): string {
    if (!started || !completed) return '—'
    const ms = new Date(completed).getTime() - new Date(started).getTime()
    const mins = Math.round(ms / 60000)
    return mins < 60 ? `${mins}m` : `${Math.floor(mins / 60)}h ${mins % 60}m`
  }

  return (
    <div className="flex flex-col gap-4 items-center justify-center h-full text-center">
      <div>
        <p className="text-sm font-semibold text-slate-300 mb-1">No pipeline running</p>
        {lastRun && (
          <p className="text-xs text-slate-500">
            Last run: {fmtDate(lastRun.started_at)} · {duration(lastRun.started_at, lastRun.completed_at)}
          </p>
        )}
      </div>
      <button
        onClick={onRun}
        disabled={isRunning}
        className="px-6 py-2 bg-brand text-surface text-sm font-semibold rounded-lg disabled:opacity-50 transition-all"
        style={{ boxShadow: '0 0 16px rgba(25,212,232,0.35)' }}
      >
        {isRunning ? 'Starting…' : 'Run Pipeline →'}
      </button>
    </div>
  )
}

interface InfoCardProps {
  activeRun: CrewRun | undefined
  isPipelineActive: boolean
  logs: string[]
  lastRun?: { started_at: string | null; completed_at: string | null } | null
  interviewBadge?: string | null
  onRun: () => void
  isRunPending: boolean
}

export default function InfoCard({ activeRun, isPipelineActive, logs, lastRun, interviewBadge, onRun, isRunPending }: InfoCardProps) {
  return (
    <div className="bg-surface-card border border-slate-700 rounded-xl p-4 h-full min-h-[260px]">
      {isPipelineActive && activeRun ? (
        <ActiveState activeRun={activeRun} logs={logs} interviewBadge={interviewBadge} />
      ) : (
        <IdleState lastRun={lastRun} onRun={onRun} isRunning={isRunPending} />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add ui/src/components/InfoCard.tsx
git commit -m "feat: add InfoCard component with active/idle states and live log"
```

---

## Task 4: Dashboard.tsx rewrite

**Files:**
- Modify: `ui/src/pages/Dashboard.tsx` (full rewrite)

- [ ] **Step 1: Rewrite Dashboard.tsx**

```tsx
// ui/src/pages/Dashboard.tsx
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { campaignsApi } from '../api/campaigns'
import ReviewQueue from '../components/ReviewQueue'
import OrgChart, { type CrewName } from '../components/OrgChart'
import InfoCard from '../components/InfoCard'
import { useWebSocket } from '../hooks/useWebSocket'
import type { CrewRun } from '../types'

export default function Dashboard() {
  const { slug } = useParams<{ slug?: string }>()
  const navigate = useNavigate()
  const logs = useWebSocket(slug)

  const { data: status } = useQuery({
    queryKey: ['status', slug],
    queryFn: () => projectsApi.status(slug!),
    enabled: !!slug,
    refetchInterval: 5_000,
  })

  const { data: outputs = [] } = useQuery({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.outputs(slug!),
    enabled: !!slug,
    refetchInterval: 5_000,
  })

  const { data: runs = [] } = useQuery({
    queryKey: ['runs', slug],
    queryFn: () => projectsApi.listRuns(slug!),
    enabled: !!slug,
  })

  const { data: interviewSummary } = useQuery({
    queryKey: ['interview-summary', slug],
    queryFn: () => campaignsApi.interviewSummary(slug!),
    enabled: !!slug,
    refetchInterval: 30_000,
  })

  const runMutation = useMutation({
    mutationFn: () => projectsApi.orchestrate(slug!),
    onSuccess: (data) => {
      navigate(`/${slug}/runs/${data.orchestration_run_id}`)
    },
  })

  if (!slug) {
    return (
      <div className="p-8 text-slate-400">
        <p>Select a project from the sidebar to begin.</p>
      </div>
    )
  }

  const crewRuns: CrewRun[] = status?.crew_runs ?? []
  const orch = status?.latest_orchestration_run
  const isPipelineActive = orch?.status === 'running'
  const activeRun = crewRuns.find((r) => r.status === 'running')
  const lastRun = runs[0] ?? null

  const interviewBadge: string | null = (() => {
    if (!interviewSummary || interviewSummary.total_stakeholders === 0) return null
    return `${interviewSummary.total_completed} / ${interviewSummary.total_stakeholders} ✓`
  })()

  function handleCrewClick(name: CrewName) {
    if (name === 'discovery') navigate(`/${slug}/discovery`)
  }

  return (
    <div className="p-6 space-y-6">
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

      {/* Org chart + info card */}
      <section className="grid grid-cols-[1fr_320px] gap-4 items-start">
        <div className="bg-surface-card border border-slate-700 rounded-xl p-4">
          <OrgChart
            crewRuns={crewRuns}
            isPipelineActive={isPipelineActive}
            logs={logs}
            interviewBadge={interviewBadge}
            onCrewClick={handleCrewClick}
          />
        </div>
        <InfoCard
          activeRun={activeRun}
          isPipelineActive={isPipelineActive}
          logs={logs}
          lastRun={lastRun}
          interviewBadge={interviewBadge}
          onRun={() => runMutation.mutate()}
          isRunPending={runMutation.isPending}
        />
      </section>

      {/* Review queue */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Review Queue
        </h3>
        <ReviewQueue slug={slug} outputs={outputs} />
      </section>
    </div>
  )
}
```

- [ ] **Step 2: Verify `projectsApi.listRuns` exists**

Check `ui/src/api/endpoints.ts` for `listRuns`. If missing, add:

```ts
listRuns: (slug: string): Promise<OrchestrationRunHistory[]> =>
  apiClient.get<OrchestrationRunHistory[]>(`/projects/${slug}/runs`).then((r) => r.data),
```

- [ ] **Step 3: Commit**

```bash
git add ui/src/pages/Dashboard.tsx ui/src/api/endpoints.ts
git commit -m "feat: rewrite Dashboard with OrgChart, InfoCard, and interview badge"
```

---

## Task 5: DB migration — campaigns, interview_responses, reminder_emails + stakeholder interview fields

**Files:**
- Modify: `api/database.py`

- [ ] **Step 1: Add `_migrate_campaigns` function to database.py**

Add the following function after `_migrate_stakeholders` (before the `get_connection` context manager):

```python
async def _migrate_campaigns(conn: aiosqlite.Connection) -> None:
    """Create campaigns, interview_responses, reminder_emails tables;
    add interview_status/interview_invited_at/interview_completed_at to stakeholders."""

    await conn.executescript("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id              INTEGER NOT NULL REFERENCES projects(id),
            value_stream_name       TEXT NOT NULL DEFAULT '',
            listenlabs_campaign_id  TEXT NOT NULL DEFAULT '',
            campaign_name           TEXT NOT NULL DEFAULT '',
            interview_start         TEXT,
            interview_close         TEXT,
            findings_summary        TEXT NOT NULL DEFAULT '',
            created_at              DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS interview_responses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            stakeholder_id  INTEGER NOT NULL REFERENCES stakeholders(id),
            campaign_id     INTEGER NOT NULL REFERENCES campaigns(id),
            raw_data        TEXT NOT NULL,
            imported_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reminder_emails (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id          INTEGER NOT NULL REFERENCES projects(id),
            campaign_id         INTEGER NOT NULL REFERENCES campaigns(id),
            stakeholder_id      INTEGER NOT NULL REFERENCES stakeholders(id),
            subject             TEXT NOT NULL DEFAULT '',
            body                TEXT NOT NULL DEFAULT '',
            escalation_level    TEXT NOT NULL DEFAULT 'gentle',
            status              TEXT NOT NULL DEFAULT 'pending',
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    await conn.commit()

    # Add interview columns to stakeholders if missing
    async with conn.execute("PRAGMA table_info(stakeholders)") as cur:
        cols = {row["name"] async for row in cur}

    for col, defn in [
        ("interview_status",       "TEXT"),
        ("interview_invited_at",   "DATETIME"),
        ("interview_completed_at", "DATETIME"),
    ]:
        if col not in cols:
            await conn.execute(f"ALTER TABLE stakeholders ADD COLUMN {col} {defn}")

    await conn.commit()
```

- [ ] **Step 2: Call `_migrate_campaigns` from `get_connection`**

Find the `get_connection` context manager and add the call after `_migrate_stakeholders`:

```python
@asynccontextmanager
async def get_connection(slug: str):
    path = get_db_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await init_db(conn)
        await _migrate_human_reviews(conn)
        await _migrate_crew_runs(conn)
        await _migrate_stakeholders(conn)
        await _migrate_campaigns(conn)   # ← add this line
        yield conn
```

- [ ] **Step 3: Commit**

```bash
git add api/database.py
git commit -m "feat: add _migrate_campaigns — campaigns, interview_responses, reminder_emails tables"
```

---

## Task 6: DB helpers — campaign CRUD + interview helpers + reminder email helpers

**Files:**
- Modify: `api/database.py` (append helpers at end of file, before the system DB section)

- [ ] **Step 1: Add campaign CRUD helpers**

Append to `api/database.py` (before `# ── System DB` comment):

```python
# ── Campaigns ─────────────────────────────────────────────────────────────────

async def insert_campaign(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    value_stream_name: str = '',
    listenlabs_campaign_id: str = '',
    campaign_name: str = '',
    interview_start: str | None = None,
    interview_close: str | None = None,
) -> int:
    cur = await conn.execute(
        """INSERT INTO campaigns
           (project_id, value_stream_name, listenlabs_campaign_id, campaign_name,
            interview_start, interview_close)
           VALUES (?,?,?,?,?,?)""",
        (project_id, value_stream_name, listenlabs_campaign_id, campaign_name,
         interview_start, interview_close),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_campaigns(conn: aiosqlite.Connection, *, project_id: int) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM campaigns WHERE project_id=? ORDER BY created_at ASC",
        (project_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def fetch_campaign(
    conn: aiosqlite.Connection, *, campaign_id: int, project_id: int
) -> dict | None:
    async with conn.execute(
        "SELECT * FROM campaigns WHERE id=? AND project_id=?",
        (campaign_id, project_id),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


_CAMPAIGN_UPDATABLE = frozenset({
    'value_stream_name', 'listenlabs_campaign_id', 'campaign_name',
    'interview_start', 'interview_close', 'findings_summary',
})


async def update_campaign(
    conn: aiosqlite.Connection, *, campaign_id: int, **fields
) -> bool:
    invalid = set(fields) - _CAMPAIGN_UPDATABLE
    if invalid:
        raise ValueError(f"Unknown campaign fields: {invalid}")
    if not fields:
        return False
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [campaign_id]
    cur = await conn.execute(
        f"UPDATE campaigns SET {set_clause} WHERE id=?", values
    )
    await conn.commit()
    return cur.rowcount > 0


async def delete_campaign(conn: aiosqlite.Connection, *, campaign_id: int) -> bool:
    cur = await conn.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
    await conn.commit()
    return cur.rowcount > 0


async def fetch_stakeholders_for_value_stream(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    value_stream_name: str,
    exclude_completed: bool = False,
) -> list[dict]:
    """Return stakeholders whose value_streams JSON array contains value_stream_name."""
    clause = "WHERE project_id=? AND value_streams LIKE ?"
    params: list = [project_id, f'%"{value_stream_name}"%']
    if exclude_completed:
        clause += " AND (interview_status IS NULL OR interview_status != 'completed')"
    async with conn.execute(
        f"SELECT * FROM stakeholders {clause} ORDER BY name ASC", params
    ) as cur:
        return [_deserialize_stakeholder(dict(r)) async for r in cur]


async def update_stakeholder_interview_status(
    conn: aiosqlite.Connection,
    *,
    stakeholder_id: int,
    status: str,
    completed_at: str | None = None,
    invited_at: str | None = None,
) -> bool:
    parts = ["interview_status=?"]
    vals: list = [status]
    if completed_at is not None:
        parts.append("interview_completed_at=?")
        vals.append(completed_at)
    if invited_at is not None:
        parts.append("interview_invited_at=?")
        vals.append(invited_at)
    vals.append(stakeholder_id)
    cur = await conn.execute(
        f"UPDATE stakeholders SET {', '.join(parts)} WHERE id=?", vals
    )
    await conn.commit()
    return cur.rowcount > 0


async def insert_interview_response(
    conn: aiosqlite.Connection,
    *,
    stakeholder_id: int,
    campaign_id: int,
    raw_data: str,
) -> int:
    cur = await conn.execute(
        "INSERT INTO interview_responses (stakeholder_id, campaign_id, raw_data) VALUES (?,?,?)",
        (stakeholder_id, campaign_id, raw_data),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_interview_responses(
    conn: aiosqlite.Connection, *, campaign_id: int
) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM interview_responses WHERE campaign_id=? ORDER BY imported_at ASC",
        (campaign_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def insert_reminder_email(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    campaign_id: int,
    stakeholder_id: int,
    subject: str,
    body: str,
    escalation_level: str,
) -> int:
    cur = await conn.execute(
        """INSERT INTO reminder_emails
           (project_id, campaign_id, stakeholder_id, subject, body, escalation_level)
           VALUES (?,?,?,?,?,?)""",
        (project_id, campaign_id, stakeholder_id, subject, body, escalation_level),
    )
    await conn.commit()
    return cur.lastrowid


async def fetch_reminder_emails(
    conn: aiosqlite.Connection, *, project_id: int, status: str = 'pending'
) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM reminder_emails WHERE project_id=? AND status=? ORDER BY created_at DESC",
        (project_id, status),
    ) as cur:
        return [dict(r) async for r in cur]


async def update_reminder_email(
    conn: aiosqlite.Connection,
    *,
    email_id: int,
    project_id: int,
    status: str,
    subject: str | None = None,
    body: str | None = None,
) -> bool:
    parts = ["status=?"]
    vals: list = [status]
    if subject is not None:
        parts.append("subject=?")
        vals.append(subject)
    if body is not None:
        parts.append("body=?")
        vals.append(body)
    vals += [email_id, project_id]
    cur = await conn.execute(
        f"UPDATE reminder_emails SET {', '.join(parts)} WHERE id=? AND project_id=?", vals
    )
    await conn.commit()
    return cur.rowcount > 0
```

- [ ] **Step 2: Commit**

```bash
git add api/database.py
git commit -m "feat: add campaign, interview_response, reminder_email DB helpers"
```

---

## Task 7: Campaign service layer

**Files:**
- Create: `api/services/campaign_service.py`

- [ ] **Step 1: Create the service**

```python
# api/services/campaign_service.py
"""Campaign management — interview tracking service layer."""
import csv
import io
import json as _json
from datetime import datetime, timezone

from api.database import (
    get_connection,
    get_db_path,
    fetch_project,
    insert_campaign,
    fetch_campaigns,
    fetch_campaign,
    update_campaign,
    delete_campaign,
    fetch_stakeholders_for_value_stream,
    update_stakeholder_interview_status,
    insert_interview_response,
    fetch_interview_responses,
    insert_reminder_email,
    fetch_reminder_emails,
    update_reminder_email,
)

# ── Reminder templates ─────────────────────────────────────────────────────────

REMINDER_TEMPLATES = {
    "gentle": {
        "subject": "A quick reminder — we'd love your input",
        "body": (
            "Hi {name},\n\n"
            "We noticed you haven't yet completed your stakeholder interview for the "
            "{campaign_name} initiative. Your perspective is genuinely valuable to us "
            "and will directly shape the recommendations we make.\n\n"
            "The interview takes around 10–15 minutes and can be completed at a time "
            "that suits you. Please follow the link below to get started.\n\n"
            "Thank you for your time.\n\n"
            "Best regards,\nThe Project Team"
        ),
    },
    "firm": {
        "subject": "Reminder — your interview is still open",
        "body": (
            "Hi {name},\n\n"
            "We're still hoping to capture your perspective as part of the "
            "{campaign_name} stakeholder engagement. We'd really appreciate "
            "you completing the short interview when you get a chance.\n\n"
            "Your input helps us ensure the recommendations we make reflect "
            "the full range of stakeholder views.\n\n"
            "Best regards,\nThe Project Team"
        ),
    },
    "urgent": {
        "subject": "Final reminder — interview window closing soon",
        "body": (
            "Hi {name},\n\n"
            "This is a final reminder that the stakeholder interview window for "
            "{campaign_name} is closing very soon. After this date we will not "
            "be able to include your input in the analysis.\n\n"
            "Please take 10 minutes to complete the interview — your voice matters.\n\n"
            "Best regards,\nThe Project Team"
        ),
    },
}


def _escalation_level(invited_at_str: str) -> str:
    """Return 'gentle', 'firm', or 'urgent' based on days since invite."""
    try:
        invited = datetime.fromisoformat(invited_at_str.replace("Z", "+00:00"))
        if invited.tzinfo is None:
            invited = invited.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - invited).days
    except Exception:
        days = 0
    if days <= 7:
        return "gentle"
    if days <= 14:
        return "firm"
    return "urgent"


# ── Service functions ──────────────────────────────────────────────────────────

async def list_campaigns(slug: str) -> list[dict] | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await fetch_campaigns(conn, project_id=project["id"])


async def create_campaign_svc(slug: str, data: dict) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        cid = await insert_campaign(conn, project_id=project["id"], **data)
        return await fetch_campaign(conn, campaign_id=cid, project_id=project["id"])


async def update_campaign_svc(slug: str, campaign_id: int, data: dict) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        ok = await update_campaign(conn, campaign_id=campaign_id, **data)
        if not ok:
            return None
        return await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])


async def delete_campaign_svc(slug: str, campaign_id: int) -> bool | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        camp = await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])
        if not camp:
            return False
        return await delete_campaign(conn, campaign_id=campaign_id)


async def export_targets_csv(slug: str, campaign_id: int) -> str | None:
    """Return CSV string of interview targets (non-completed stakeholders) for campaign.
    Returns None if project/campaign not found.
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        camp = await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])
        if not camp:
            return None
        stakeholders = await fetch_stakeholders_for_value_stream(
            conn,
            project_id=project["id"],
            value_stream_name=camp["value_stream_name"],
            exclude_completed=True,
        )

    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=["name", "email", "country_code", "value_stream", "campaign_id"]
    )
    writer.writeheader()
    for s in stakeholders:
        writer.writerow({
            "name": s["name"],
            "email": s["email"],
            "country_code": s["country_code"],
            "value_stream": camp["value_stream_name"],
            "campaign_id": camp["listenlabs_campaign_id"],
        })
    return output.getvalue()


async def mark_invited_svc(slug: str, campaign_id: int) -> dict | None:
    """Set interview_invited_at = now() and interview_status = 'invited' for all
    non-completed stakeholders in the campaign's value stream.
    Returns {"marked": N} or None if not found.
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        camp = await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])
        if not camp:
            return None
        stakeholders = await fetch_stakeholders_for_value_stream(
            conn,
            project_id=project["id"],
            value_stream_name=camp["value_stream_name"],
            exclude_completed=True,
        )
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for s in stakeholders:
            if not s.get("interview_invited_at"):
                await update_stakeholder_interview_status(
                    conn,
                    stakeholder_id=s["id"],
                    status="invited",
                    invited_at=now,
                )
                count += 1
        return {"marked": count}


async def import_progress_svc(slug: str, campaign_id: int, content: str) -> dict | None:
    """Parse progress CSV (email, status) and update stakeholder interview_status.
    Returns {"updated": N, "skipped": M} or None if not found.
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        camp = await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])
        if not camp:
            return None

        reader = csv.DictReader(io.StringIO(content))
        rows = [{k.strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader]

        updated = 0
        skipped = 0
        now = datetime.now(timezone.utc).isoformat()

        for row in rows:
            email = row.get("email", "").strip()
            status_val = row.get("status", "").strip().lower()
            if not email:
                skipped += 1
                continue

            async with conn.execute(
                "SELECT id FROM stakeholders WHERE email=? AND project_id=?",
                (email, project["id"]),
            ) as cur:
                s = await cur.fetchone()

            if not s:
                skipped += 1
                continue

            if status_val == "completed":
                await update_stakeholder_interview_status(
                    conn,
                    stakeholder_id=s["id"],
                    status="completed",
                    completed_at=now,
                )
            else:
                await update_stakeholder_interview_status(
                    conn,
                    stakeholder_id=s["id"],
                    status="invited",
                )
            updated += 1

        return {"updated": updated, "skipped": skipped}


async def import_results_svc(slug: str, campaign_id: int, content: str) -> dict | None:
    """Parse results file (JSON array or CSV with email column) and store raw blobs.
    Returns {"imported": N, "unmatched": M} or None if not found.
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        camp = await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])
        if not camp:
            return None

        # Try JSON array first, fall back to CSV
        records: list[dict] = []
        try:
            parsed = _json.loads(content)
            if isinstance(parsed, list):
                records = parsed
            elif isinstance(parsed, dict):
                records = [parsed]
        except _json.JSONDecodeError:
            reader = csv.DictReader(io.StringIO(content))
            records = [{k.strip().lower(): v for k, v in r.items()} for r in reader]

        imported = 0
        unmatched = 0

        for record in records:
            email = str(record.get("email", "")).strip()
            if not email:
                unmatched += 1
                continue

            async with conn.execute(
                "SELECT id FROM stakeholders WHERE email=? AND project_id=?",
                (email, project["id"]),
            ) as cur:
                s = await cur.fetchone()

            if not s:
                unmatched += 1
                continue

            await insert_interview_response(
                conn,
                stakeholder_id=s["id"],
                campaign_id=campaign_id,
                raw_data=_json.dumps(record),
            )
            imported += 1

        return {"imported": imported, "unmatched": unmatched}


async def import_summary_svc(slug: str, campaign_id: int, content: str) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        ok = await update_campaign(
            conn, campaign_id=campaign_id, findings_summary=content
        )
        if not ok:
            return None
        return {"ok": True}


async def generate_reminders_svc(slug: str, campaign_id: int) -> dict | None:
    """Create reminder_email records for non-completed invited stakeholders.
    Returns {"created": N} or None if not found.
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        camp = await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])
        if not camp:
            return None

        stakeholders = await fetch_stakeholders_for_value_stream(
            conn,
            project_id=project["id"],
            value_stream_name=camp["value_stream_name"],
            exclude_completed=True,
        )

        count = 0
        for s in stakeholders:
            invited_at = s.get("interview_invited_at")
            if not invited_at:
                continue  # Skip un-invited stakeholders
            level = _escalation_level(invited_at)
            template = REMINDER_TEMPLATES[level]
            subject = template["subject"]
            body = template["body"].format(
                name=s["name"],
                campaign_name=camp["campaign_name"] or camp["value_stream_name"],
            )
            await insert_reminder_email(
                conn,
                project_id=project["id"],
                campaign_id=campaign_id,
                stakeholder_id=s["id"],
                subject=subject,
                body=body,
                escalation_level=level,
            )
            count += 1

        return {"created": count}


async def get_interview_summary(slug: str) -> dict | None:
    """Return aggregate completion counts across all campaigns with open windows."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        campaigns = await fetch_campaigns(conn, project_id=project["id"])
        today = datetime.now(timezone.utc).date().isoformat()

        total_stakeholders = 0
        total_completed = 0
        active_campaigns = []

        for camp in campaigns:
            start = camp.get("interview_start") or ""
            close = camp.get("interview_close") or ""
            window_open = bool(start and close and start <= today <= close)

            vs = camp["value_stream_name"]
            stakeholders = await fetch_stakeholders_for_value_stream(
                conn, project_id=project["id"], value_stream_name=vs
            )
            total = len(stakeholders)
            completed = sum(1 for s in stakeholders if s.get("interview_status") == "completed")

            active_campaigns.append({
                "id": camp["id"],
                "value_stream_name": vs,
                "total_stakeholders": total,
                "completed": completed,
                "window_open": window_open,
            })
            if window_open:
                total_stakeholders += total
                total_completed += completed

        return {
            "active_campaigns": active_campaigns,
            "total_stakeholders": total_stakeholders,
            "total_completed": total_completed,
        }


async def list_reminder_emails_svc(slug: str) -> list[dict] | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await fetch_reminder_emails(conn, project_id=project["id"])


async def update_reminder_email_svc(
    slug: str,
    email_id: int,
    status: str,
    subject: str | None = None,
    body: str | None = None,
) -> bool | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await update_reminder_email(
            conn,
            email_id=email_id,
            project_id=project["id"],
            status=status,
            subject=subject,
            body=body,
        )
```

- [ ] **Step 2: Commit**

```bash
git add api/services/campaign_service.py
git commit -m "feat: add campaign_service — CRUD, import/export, reminders, interview summary"
```

---

## Task 8: Campaign router + reminder emails router

**Files:**
- Create: `api/routers/campaigns.py`

- [ ] **Step 1: Create the router**

```python
# api/routers/campaigns.py
"""Campaign management, interview import/export, and reminder email endpoints."""
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from api.services.campaign_service import (
    list_campaigns,
    create_campaign_svc,
    update_campaign_svc,
    delete_campaign_svc,
    export_targets_csv,
    mark_invited_svc,
    import_progress_svc,
    import_results_svc,
    import_summary_svc,
    generate_reminders_svc,
    get_interview_summary,
    list_reminder_emails_svc,
    update_reminder_email_svc,
)

router = APIRouter(prefix="/projects", tags=["campaigns"])


def _404(detail: str = "Not found"):
    raise HTTPException(status_code=404, detail=detail)


class CampaignIn(BaseModel):
    value_stream_name: str = ""
    listenlabs_campaign_id: str = ""
    campaign_name: str = ""
    interview_start: str | None = None
    interview_close: str | None = None


class CampaignPatch(BaseModel):
    value_stream_name: str | None = None
    listenlabs_campaign_id: str | None = None
    campaign_name: str | None = None
    interview_start: str | None = None
    interview_close: str | None = None
    findings_summary: str | None = None


class ReminderEmailPatch(BaseModel):
    status: str  # 'approved' | 'dismissed'
    subject: str | None = None
    body: str | None = None


# ── Campaign CRUD ──────────────────────────────────────────────────────────────

@router.get("/{slug}/campaigns")
async def list_campaigns_endpoint(slug: str):
    result = await list_campaigns(slug)
    if result is None:
        _404(f"Project '{slug}' not found")
    return result


@router.post("/{slug}/campaigns", status_code=201)
async def create_campaign_endpoint(slug: str, body: CampaignIn):
    result = await create_campaign_svc(slug, body.model_dump(exclude_none=True))
    if result is None:
        _404(f"Project '{slug}' not found")
    return result


@router.patch("/{slug}/campaigns/{campaign_id}")
async def update_campaign_endpoint(slug: str, campaign_id: int, body: CampaignPatch):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    result = await update_campaign_svc(slug, campaign_id, data)
    if result is None:
        _404("Campaign not found")
    return result


@router.delete("/{slug}/campaigns/{campaign_id}", status_code=204)
async def delete_campaign_endpoint(slug: str, campaign_id: int):
    result = await delete_campaign_svc(slug, campaign_id)
    if result is None:
        _404(f"Project '{slug}' not found")
    if result is False:
        _404("Campaign not found")


# ── Import / Export ─────────────────────────────────────────────────────────────

@router.get("/{slug}/campaigns/{campaign_id}/export-targets")
async def export_targets_endpoint(slug: str, campaign_id: int):
    csv_content = await export_targets_csv(slug, campaign_id)
    if csv_content is None:
        _404("Project or campaign not found")
    filename = f"interview-targets-campaign-{campaign_id}.csv"

    def iter_csv():
        yield csv_content

    return StreamingResponse(
        iter_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{slug}/campaigns/{campaign_id}/mark-invited")
async def mark_invited_endpoint(slug: str, campaign_id: int):
    result = await mark_invited_svc(slug, campaign_id)
    if result is None:
        _404("Project or campaign not found")
    return result


@router.post("/{slug}/campaigns/{campaign_id}/import-progress")
async def import_progress_endpoint(slug: str, campaign_id: int, file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="replace")
    result = await import_progress_svc(slug, campaign_id, content)
    if result is None:
        _404("Project or campaign not found")
    return result


@router.post("/{slug}/campaigns/{campaign_id}/import-results")
async def import_results_endpoint(slug: str, campaign_id: int, file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="replace")
    result = await import_results_svc(slug, campaign_id, content)
    if result is None:
        _404("Project or campaign not found")
    return result


@router.post("/{slug}/campaigns/{campaign_id}/import-summary")
async def import_summary_endpoint(slug: str, campaign_id: int, file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="replace")
    result = await import_summary_svc(slug, campaign_id, content)
    if result is None:
        _404("Project or campaign not found")
    return result


# ── Reminder generation ─────────────────────────────────────────────────────────

@router.post("/{slug}/campaigns/{campaign_id}/generate-reminders")
async def generate_reminders_endpoint(slug: str, campaign_id: int):
    result = await generate_reminders_svc(slug, campaign_id)
    if result is None:
        _404("Project or campaign not found")
    return result


# ── Interview summary (for dashboard badge) ─────────────────────────────────────

@router.get("/{slug}/interview-summary")
async def interview_summary_endpoint(slug: str):
    result = await get_interview_summary(slug)
    if result is None:
        _404(f"Project '{slug}' not found")
    return result


# ── Reminder emails ─────────────────────────────────────────────────────────────

@router.get("/{slug}/reminder-emails")
async def list_reminder_emails_endpoint(slug: str):
    result = await list_reminder_emails_svc(slug)
    if result is None:
        _404(f"Project '{slug}' not found")
    return result


@router.patch("/{slug}/reminder-emails/{email_id}")
async def update_reminder_email_endpoint(slug: str, email_id: int, body: ReminderEmailPatch):
    result = await update_reminder_email_svc(
        slug, email_id, body.status, subject=body.subject, body=body.body
    )
    if result is None:
        _404(f"Project '{slug}' not found")
    if result is False:
        _404("Reminder email not found")
    return {"ok": True}
```

- [ ] **Step 2: Register router in main.py**

In `api/main.py`, add:

```python
from api.routers import campaigns as campaigns_router
```

And in the router registration block:

```python
app.include_router(campaigns_router.router)
```

- [ ] **Step 3: Commit**

```bash
git add api/routers/campaigns.py api/main.py
git commit -m "feat: add campaigns router — CRUD, import/export, reminders, interview summary"
```

---

## Task 9: Backend tests

**Files:**
- Create: `tests/test_campaigns.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_campaigns.py
"""Tests for campaign management, interview tracking, and reminder email endpoints."""
import csv
import io
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from api.config import get_settings
from api.database import get_connection, fetch_project, insert_stakeholder

SLUG = "campaigns-test"
PROJECT = {"client_slug": SLUG, "llm_mode": "standard", "sector": "rail"}

STAKEHOLDER_BASE = {
    "name": "Alice",
    "email": "alice@corp.com",
    "country_code": "GB",
    "value_streams": ["Digital Transformation"],
}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _setup_project_and_stakeholder(client) -> tuple[int, int]:
    """Create project + stakeholder in Digital Transformation value stream.
    Returns (project_id, stakeholder_id).
    """
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        sid = await insert_stakeholder(
            conn,
            project_id=project["id"],
            **STAKEHOLDER_BASE,
            value_streams=["Digital Transformation"],
        )
    return project["id"], sid


@pytest.mark.asyncio
async def test_migration_creates_campaign_tables(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        for table in ("campaigns", "interview_responses", "reminder_emails"):
            async with conn.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"
            ) as cur:
                row = await cur.fetchone()
            assert row is not None, f"{table} table should exist after migration"

        # interview_status column on stakeholders
        async with conn.execute("PRAGMA table_info(stakeholders)") as cur:
            cols = {row["name"] async for row in cur}
        assert "interview_status" in cols
        assert "interview_invited_at" in cols
        assert "interview_completed_at" in cols


@pytest.mark.asyncio
async def test_create_and_list_campaigns(client):
    await client.post("/projects", json=PROJECT)
    body = {
        "value_stream_name": "Digital Transformation",
        "listenlabs_campaign_id": "camp_abc",
        "campaign_name": "DT Stakeholder Survey",
        "interview_start": "2026-05-01",
        "interview_close": "2026-05-31",
    }
    r = await client.post(f"/projects/{SLUG}/campaigns", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["campaign_name"] == "DT Stakeholder Survey"
    assert data["listenlabs_campaign_id"] == "camp_abc"

    r2 = await client.get(f"/projects/{SLUG}/campaigns")
    assert r2.status_code == 200
    assert len(r2.json()) == 1


@pytest.mark.asyncio
async def test_update_campaign(client):
    await client.post("/projects", json=PROJECT)
    r = await client.post(f"/projects/{SLUG}/campaigns", json={"campaign_name": "Old"})
    cid = r.json()["id"]

    r2 = await client.patch(
        f"/projects/{SLUG}/campaigns/{cid}",
        json={"campaign_name": "New Name", "listenlabs_campaign_id": "camp_xyz"},
    )
    assert r2.status_code == 200
    assert r2.json()["campaign_name"] == "New Name"
    assert r2.json()["listenlabs_campaign_id"] == "camp_xyz"


@pytest.mark.asyncio
async def test_delete_campaign(client):
    await client.post("/projects", json=PROJECT)
    r = await client.post(f"/projects/{SLUG}/campaigns", json={"campaign_name": "To Delete"})
    cid = r.json()["id"]

    r2 = await client.delete(f"/projects/{SLUG}/campaigns/{cid}")
    assert r2.status_code == 204

    r3 = await client.get(f"/projects/{SLUG}/campaigns")
    assert r3.json() == []


@pytest.mark.asyncio
async def test_export_targets_csv(client):
    await _setup_project_and_stakeholder(client)
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={"value_stream_name": "Digital Transformation", "listenlabs_campaign_id": "c1"},
    )
    cid = r.json()["id"]

    r2 = await client.get(f"/projects/{SLUG}/campaigns/{cid}/export-targets")
    assert r2.status_code == 200
    assert "text/csv" in r2.headers["content-type"]

    reader = csv.DictReader(io.StringIO(r2.text))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["email"] == "alice@corp.com"
    assert rows[0]["country_code"] == "GB"
    assert rows[0]["value_stream"] == "Digital Transformation"
    assert rows[0]["campaign_id"] == "c1"


@pytest.mark.asyncio
async def test_mark_invited(client):
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(f"/projects/{SLUG}/campaigns", json={"value_stream_name": "Digital Transformation"})
    cid = r.json()["id"]

    r2 = await client.post(f"/projects/{SLUG}/campaigns/{cid}/mark-invited")
    assert r2.status_code == 200
    assert r2.json()["marked"] == 1

    # Second call should mark 0 (already invited)
    r3 = await client.post(f"/projects/{SLUG}/campaigns/{cid}/mark-invited")
    assert r3.json()["marked"] == 0


@pytest.mark.asyncio
async def test_import_progress(client):
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(f"/projects/{SLUG}/campaigns", json={"value_stream_name": "Digital Transformation"})
    cid = r.json()["id"]

    csv_content = "email,status\nalice@corp.com,completed\nunknown@x.com,completed\n"
    r2 = await client.post(
        f"/projects/{SLUG}/campaigns/{cid}/import-progress",
        files={"file": ("progress.csv", csv_content.encode(), "text/csv")},
    )
    assert r2.status_code == 200
    result = r2.json()
    assert result["updated"] == 1   # alice matched
    assert result["skipped"] == 1   # unknown@x.com unmatched

    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT interview_status FROM stakeholders WHERE id=?", (sid,)
        ) as cur:
            row = await cur.fetchone()
    assert row["interview_status"] == "completed"


@pytest.mark.asyncio
async def test_import_results_json(client):
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(f"/projects/{SLUG}/campaigns", json={"value_stream_name": "Digital Transformation"})
    cid = r.json()["id"]

    results = [{"email": "alice@corp.com", "q1": "answer1", "q2": "answer2"}]
    r2 = await client.post(
        f"/projects/{SLUG}/campaigns/{cid}/import-results",
        files={"file": ("results.json", json.dumps(results).encode(), "application/json")},
    )
    assert r2.status_code == 200
    assert r2.json()["imported"] == 1
    assert r2.json()["unmatched"] == 0


@pytest.mark.asyncio
async def test_import_summary(client):
    await client.post("/projects", json=PROJECT)
    r = await client.post(f"/projects/{SLUG}/campaigns", json={"campaign_name": "X"})
    cid = r.json()["id"]

    summary_text = "Overall finding: stakeholders want faster delivery."
    r2 = await client.post(
        f"/projects/{SLUG}/campaigns/{cid}/import-summary",
        files={"file": ("summary.txt", summary_text.encode(), "text/plain")},
    )
    assert r2.status_code == 200

    r3 = await client.get(f"/projects/{SLUG}/campaigns")
    camp = next(c for c in r3.json() if c["id"] == cid)
    assert camp["findings_summary"] == summary_text


@pytest.mark.asyncio
async def test_generate_reminders_gentle(client):
    """Stakeholder invited 3 days ago → gentle template."""
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={"value_stream_name": "Digital Transformation", "campaign_name": "DT Survey"},
    )
    cid = r.json()["id"]

    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    async with get_connection(SLUG) as conn:
        await conn.execute(
            "UPDATE stakeholders SET interview_invited_at=?, interview_status='invited' WHERE id=?",
            (three_days_ago, sid),
        )
        await conn.commit()

    r2 = await client.post(f"/projects/{SLUG}/campaigns/{cid}/generate-reminders")
    assert r2.status_code == 200
    assert r2.json()["created"] == 1

    r3 = await client.get(f"/projects/{SLUG}/reminder-emails")
    emails = r3.json()
    assert len(emails) == 1
    assert emails[0]["escalation_level"] == "gentle"
    assert "Alice" in emails[0]["body"]


@pytest.mark.asyncio
async def test_generate_reminders_firm(client):
    """Stakeholder invited 10 days ago → firm template."""
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={"value_stream_name": "Digital Transformation", "campaign_name": "DT Survey"},
    )
    cid = r.json()["id"]

    ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    async with get_connection(SLUG) as conn:
        await conn.execute(
            "UPDATE stakeholders SET interview_invited_at=?, interview_status='invited' WHERE id=?",
            (ten_days_ago, sid),
        )
        await conn.commit()

    await client.post(f"/projects/{SLUG}/campaigns/{cid}/generate-reminders")

    r2 = await client.get(f"/projects/{SLUG}/reminder-emails")
    assert r2.json()[0]["escalation_level"] == "firm"


@pytest.mark.asyncio
async def test_generate_reminders_urgent(client):
    """Stakeholder invited 20 days ago → urgent template."""
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={"value_stream_name": "Digital Transformation", "campaign_name": "DT Survey"},
    )
    cid = r.json()["id"]

    twenty_days_ago = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    async with get_connection(SLUG) as conn:
        await conn.execute(
            "UPDATE stakeholders SET interview_invited_at=?, interview_status='invited' WHERE id=?",
            (twenty_days_ago, sid),
        )
        await conn.commit()

    await client.post(f"/projects/{SLUG}/campaigns/{cid}/generate-reminders")

    r2 = await client.get(f"/projects/{SLUG}/reminder-emails")
    assert r2.json()[0]["escalation_level"] == "urgent"


@pytest.mark.asyncio
async def test_generate_reminders_skips_uninvited(client):
    """Stakeholder with no interview_invited_at is skipped."""
    await _setup_project_and_stakeholder(client)
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={"value_stream_name": "Digital Transformation"},
    )
    cid = r.json()["id"]
    # Do NOT mark invited — interview_invited_at is NULL

    r2 = await client.post(f"/projects/{SLUG}/campaigns/{cid}/generate-reminders")
    assert r2.json()["created"] == 0


@pytest.mark.asyncio
async def test_interview_summary(client):
    _, sid = await _setup_project_and_stakeholder(client)
    today = datetime.now(timezone.utc).date().isoformat()
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={
            "value_stream_name": "Digital Transformation",
            "interview_start": today,
            "interview_close": today,
        },
    )
    cid = r.json()["id"]

    # Mark stakeholder as completed
    csv_content = "email,status\nalice@corp.com,completed\n"
    await client.post(
        f"/projects/{SLUG}/campaigns/{cid}/import-progress",
        files={"file": ("p.csv", csv_content.encode(), "text/csv")},
    )

    r2 = await client.get(f"/projects/{SLUG}/interview-summary")
    assert r2.status_code == 200
    data = r2.json()
    assert data["total_stakeholders"] == 1
    assert data["total_completed"] == 1


@pytest.mark.asyncio
async def test_approve_reminder_email(client):
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={"value_stream_name": "Digital Transformation", "campaign_name": "DT Survey"},
    )
    cid = r.json()["id"]

    # Create a reminder via manual DB insert (to avoid date dependency)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        await conn.execute(
            """INSERT INTO reminder_emails
               (project_id, campaign_id, stakeholder_id, subject, body, escalation_level)
               VALUES (?,?,?,?,?,?)""",
            (project["id"], cid, sid, "Test subject", "Test body", "gentle"),
        )
        await conn.commit()

    emails = (await client.get(f"/projects/{SLUG}/reminder-emails")).json()
    eid = emails[0]["id"]

    r2 = await client.patch(
        f"/projects/{SLUG}/reminder-emails/{eid}",
        json={"status": "approved", "body": "Updated body text"},
    )
    assert r2.status_code == 200

    emails2 = (await client.get(f"/projects/{SLUG}/reminder-emails")).json()
    # Approved items no longer appear in pending list
    assert len(emails2) == 0
```

- [ ] **Step 2: Run tests to verify they fail (no implementation bug)**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest tests/test_campaigns.py -v 2>&1 | head -40
```

Expected: Tests fail with import errors or assertion failures — NOT with Python syntax errors.

- [ ] **Step 3: Run full test suite to check for regressions**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All previous tests still pass; new tests fail.

- [ ] **Step 4: Run tests again after Tasks 5–8 code is in place**

```bash
pytest tests/test_campaigns.py -v
```

Expected: All 16 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_campaigns.py
git commit -m "test: add test_campaigns.py — 16 tests for campaign CRUD, imports, reminders, summary"
```

---

## Task 10: Frontend types + campaign API client

**Files:**
- Modify: `ui/src/types.ts`
- Create: `ui/src/api/campaigns.ts`

- [ ] **Step 1: Add types to ui/src/types.ts**

Append to end of `ui/src/types.ts`:

```ts
export interface Campaign {
  id: number
  project_id: number
  value_stream_name: string
  listenlabs_campaign_id: string
  campaign_name: string
  interview_start: string | null
  interview_close: string | null
  findings_summary: string
  created_at: string
}

export interface ReminderEmail {
  id: number
  project_id: number
  campaign_id: number
  stakeholder_id: number
  subject: string
  body: string
  escalation_level: 'gentle' | 'firm' | 'urgent'
  status: 'pending' | 'approved' | 'dismissed'
  created_at: string
}

export interface InterviewSummary {
  active_campaigns: {
    id: number
    value_stream_name: string
    total_stakeholders: number
    completed: number
    window_open: boolean
  }[]
  total_stakeholders: number
  total_completed: number
}

export interface ImportResult {
  updated?: number
  imported?: number
  skipped?: number
  unmatched?: number
}
```

Also add `interview_status`, `interview_invited_at`, `interview_completed_at` to the `Stakeholder` interface (append after `currency`):

```ts
  interview_status: string | null
  interview_invited_at: string | null
  interview_completed_at: string | null
```

- [ ] **Step 2: Create ui/src/api/campaigns.ts**

```ts
// ui/src/api/campaigns.ts
import { apiClient } from './client'
import type { Campaign, ReminderEmail, InterviewSummary, ImportResult } from '../types'

export const campaignsApi = {
  list: (slug: string): Promise<Campaign[]> =>
    apiClient.get<Campaign[]>(`/projects/${slug}/campaigns`).then((r) => r.data),

  create: (slug: string, data: Partial<Campaign>): Promise<Campaign> =>
    apiClient.post<Campaign>(`/projects/${slug}/campaigns`, data).then((r) => r.data),

  update: (slug: string, id: number, data: Partial<Campaign>): Promise<Campaign> =>
    apiClient.patch<Campaign>(`/projects/${slug}/campaigns/${id}`, data).then((r) => r.data),

  delete: (slug: string, id: number): Promise<void> =>
    apiClient.delete(`/projects/${slug}/campaigns/${id}`).then(() => undefined),

  exportTargets: (slug: string, id: number): string =>
    `${apiClient.defaults.baseURL}/projects/${slug}/campaigns/${id}/export-targets`,

  markInvited: (slug: string, id: number): Promise<{ marked: number }> =>
    apiClient.post<{ marked: number }>(`/projects/${slug}/campaigns/${id}/mark-invited`).then((r) => r.data),

  importProgress: (slug: string, id: number, file: File): Promise<ImportResult> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<ImportResult>(`/projects/${slug}/campaigns/${id}/import-progress`, form).then((r) => r.data)
  },

  importResults: (slug: string, id: number, file: File): Promise<ImportResult> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<ImportResult>(`/projects/${slug}/campaigns/${id}/import-results`, form).then((r) => r.data)
  },

  importSummary: (slug: string, id: number, file: File): Promise<{ ok: boolean }> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<{ ok: boolean }>(`/projects/${slug}/campaigns/${id}/import-summary`, form).then((r) => r.data)
  },

  generateReminders: (slug: string, id: number): Promise<{ created: number }> =>
    apiClient.post<{ created: number }>(`/projects/${slug}/campaigns/${id}/generate-reminders`).then((r) => r.data),

  interviewSummary: (slug: string): Promise<InterviewSummary> =>
    apiClient.get<InterviewSummary>(`/projects/${slug}/interview-summary`).then((r) => r.data),

  listReminderEmails: (slug: string): Promise<ReminderEmail[]> =>
    apiClient.get<ReminderEmail[]>(`/projects/${slug}/reminder-emails`).then((r) => r.data),

  updateReminderEmail: (
    slug: string,
    id: number,
    payload: { status: string; subject?: string; body?: string }
  ): Promise<{ ok: boolean }> =>
    apiClient.patch<{ ok: boolean }>(`/projects/${slug}/reminder-emails/${id}`, payload).then((r) => r.data),
}
```

- [ ] **Step 3: Verify apiClient.defaults.baseURL is accessible**

Open `ui/src/api/client.ts` and confirm the axios instance is exported as `apiClient`. The `exportTargets` method constructs a direct URL for native `<a href>` download (avoids auth header issues with file downloads).

If `apiClient.defaults.baseURL` is not available, use the environment variable instead:

```ts
exportTargets: (slug: string, id: number): string =>
  `${import.meta.env.VITE_API_URL ?? 'http://localhost:8000'}/projects/${slug}/campaigns/${id}/export-targets`,
```

- [ ] **Step 4: Commit**

```bash
git add ui/src/types.ts ui/src/api/campaigns.ts
git commit -m "feat: add Campaign, ReminderEmail, InterviewSummary types + campaigns API client"
```

---

## Task 11: Discovery.tsx — Interviews section

**Files:**
- Modify: `ui/src/pages/Discovery.tsx`

- [ ] **Step 1: Add imports and campaign state to Discovery.tsx**

At the top of `Discovery.tsx`, add imports:

```tsx
import { useRef } from 'react'
import { campaignsApi } from '../api/campaigns'
import type { Campaign } from '../types'
```

Add additional queries and state after the existing `useQuery` hooks:

```tsx
const { data: campaigns = [], refetch: refetchCampaigns } = useQuery<Campaign[]>({
  queryKey: ['campaigns', slug],
  queryFn: () => campaignsApi.list(slug!),
  enabled: !!slug,
})

const [campaignMsg, setCampaignMsg] = useState<Record<number, string>>({})
const progressInputRef = useRef<Record<number, HTMLInputElement | null>>({})
const resultsInputRef = useRef<Record<number, HTMLInputElement | null>>({})
const summaryInputRef = useRef<Record<number, HTMLInputElement | null>>({})
```

- [ ] **Step 2: Add createCampaign and updateCampaign helpers**

Add inside the component function (after existing `handleSave`):

```tsx
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
  file: File
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
```

- [ ] **Step 3: Add Interviews section JSX**

In the `return` block of `Discovery.tsx`, add this section after the Source Documents section and before the Save button:

```tsx
{/* Section 4: Interviews */}
<section className="mb-8">
  <h2 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Interviews</h2>
  <p className="text-slate-500 text-xs mb-4">
    Link a ListenLabs campaign to each value stream. Export interview targets, import results, and generate reminders.
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
              onBlur={(e) => updateCampaignField(camp.id, { listenlabs_campaign_id: e.target.value })}
              placeholder="ListenLabs campaign ID"
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 font-mono outline-none focus:border-brand"
            />
            <input
              defaultValue={camp.value_stream_name}
              onBlur={(e) => updateCampaignField(camp.id, { value_stream_name: e.target.value })}
              placeholder="Value stream name (must match discovery output)"
              className="col-span-2 bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-brand"
            />
            <input
              type="date"
              defaultValue={camp.interview_start ?? ''}
              onBlur={(e) => updateCampaignField(camp.id, { interview_start: e.target.value || null })}
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-brand"
            />
            <input
              type="date"
              defaultValue={camp.interview_close ?? ''}
              onBlur={(e) => updateCampaignField(camp.id, { interview_close: e.target.value || null })}
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
          <input type="file" accept=".csv" className="hidden"
            ref={(el) => { progressInputRef.current[camp.id] = el }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileImport(camp.id, 'progress', f); e.target.value = '' }}
          />
          <input type="file" accept=".csv,.json" className="hidden"
            ref={(el) => { resultsInputRef.current[camp.id] = el }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileImport(camp.id, 'results', f); e.target.value = '' }}
          />
          <input type="file" accept=".txt,.json" className="hidden"
            ref={(el) => { summaryInputRef.current[camp.id] = el }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileImport(camp.id, 'summary', f); e.target.value = '' }}
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
</section>
```

- [ ] **Step 4: Commit**

```bash
git add ui/src/pages/Discovery.tsx
git commit -m "feat: add Interviews section to Discovery page — campaign CRUD, import/export, reminders"
```

---

## Task 12: Reviews.tsx — reminder email section

**Files:**
- Modify: `ui/src/pages/Reviews.tsx`

- [ ] **Step 1: Add reminder email imports and query to Reviews.tsx**

Add to the top of `Reviews.tsx`:

```tsx
import { campaignsApi } from '../api/campaigns'
import type { ReminderEmail } from '../types'
```

Add a second query inside `Reviews()` after the existing reviews query:

```tsx
const { data: reminderEmails = [], refetch: refetchReminders } = useQuery({
  queryKey: ['reminder-emails', slug],
  queryFn: () => campaignsApi.listReminderEmails(slug!),
  enabled: !!slug,
  refetchInterval: 10_000,
})
```

- [ ] **Step 2: Add ReminderEmailCard component**

Add before the `export default function Reviews()` declaration:

```tsx
function ReminderEmailCard({ item, slug }: { item: ReminderEmail; slug: string }) {
  const [subject, setSubject] = useState(item.subject)
  const [body, setBody] = useState(item.body)
  const [submitting, setSubmitting] = useState(false)
  const qc = useQueryClient()

  const levelColour =
    item.escalation_level === 'urgent' ? 'border-red-500' :
    item.escalation_level === 'firm' ? 'border-amber-400' :
    'border-brand'

  async function resolve(status: 'approved' | 'dismissed') {
    setSubmitting(true)
    try {
      await campaignsApi.updateReminderEmail(slug, item.id, { status, subject, body })
      qc.invalidateQueries({ queryKey: ['reminder-emails', slug] })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={`bg-surface rounded-xl border-l-4 ${levelColour} overflow-hidden`}>
      <div className="px-4 pt-3 pb-2 flex items-center gap-2">
        <span className="rounded px-2 py-0.5 text-xs font-bold tracking-wide bg-brand/10 text-brand uppercase">
          Reminder — {item.escalation_level}
        </span>
      </div>
      <div className="px-4 pb-2 space-y-2">
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Subject</p>
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="w-full bg-[#0f172a] border border-slate-800 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-slate-600"
          />
        </div>
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Body</p>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={6}
            className="w-full bg-[#0f172a] border border-slate-700 rounded-md text-slate-300 text-sm px-3 py-2 resize-y placeholder:text-slate-600 focus:outline-none focus:border-slate-500"
          />
        </div>
      </div>
      <div className="px-4 pb-4 flex gap-2 justify-end">
        <button
          disabled={submitting}
          onClick={() => resolve('dismissed')}
          className="text-xs px-4 py-1.5 rounded-md bg-slate-800 text-slate-400 hover:bg-slate-700 disabled:opacity-50 transition-colors"
        >
          Dismiss
        </button>
        <button
          disabled={submitting}
          onClick={() => resolve('approved')}
          className="text-xs px-4 py-1.5 rounded-md bg-brand/20 text-brand hover:bg-brand/30 disabled:opacity-50 transition-colors"
        >
          Approve & Send
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Render reminder emails section in Reviews return block**

Add after the existing `<div className="space-y-4">` block for reviews:

```tsx
{reminderEmails.length > 0 && (
  <>
    <h3 className="text-sm font-semibold text-slate-300 mt-6 mb-3">Reminder Emails</h3>
    <div className="space-y-4">
      {reminderEmails.map((item) => (
        <ReminderEmailCard key={item.id} item={item} slug={slug!} />
      ))}
    </div>
  </>
)}
```

- [ ] **Step 4: Commit**

```bash
git add ui/src/pages/Reviews.tsx
git commit -m "feat: add reminder email section to Reviews page with approve/dismiss actions"
```

---

## Task 13: Run full test suite + verify

- [ ] **Step 1: Run all backend tests**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest tests/ -v --tb=short
```

Expected: All tests PASS. Note total count (should be 237 + 16 = 253 or more).

- [ ] **Step 2: Start backend and verify no startup errors**

```bash
cd api && uvicorn api.main:app --reload --port 8000
```

Expected: Server starts with no import errors. Visit `http://localhost:8000/docs` and confirm `/projects/{slug}/campaigns` endpoints appear.

- [ ] **Step 3: Start frontend and check colour rendering**

```bash
cd ui && npm run dev
```

Open `http://localhost:5173`. Check:
- Nav active state: teal underline (not purple)
- Sidebar active project: teal highlight
- Buttons: teal (not purple or sky blue)
- Dashboard: OrgChart visible, InfoCard visible

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: SP10e complete — teal retheme, dashboard org chart, interview tracking"
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ §1 Colour system: Task 1
- ✅ §2 Org chart: Tasks 2–4
- ✅ §2.3 interview-summary for badge: Task 7 (`get_interview_summary`), Task 4 (Dashboard query)
- ✅ §3.1 DB tables: Task 5
- ✅ §3.2 All 12 API endpoints: Tasks 7–8
- ✅ §3.3 Export CSV: Task 7 (`export_targets_csv`)
- ✅ §3.4 Import progress: Task 7 (`import_progress_svc`)
- ✅ §3.5 Import results (JSON/CSV, extensible blob): Task 7 (`import_results_svc`)
- ✅ §3.6 Import summary: Task 7 (`import_summary_svc`)
- ✅ §3.7 Agent synthesis path: deferred (spec notes it as future; no task needed)
- ✅ §3.8 Reminder generation with 3 templates: Task 7 (`generate_reminders_svc`, `REMINDER_TEMPLATES`)
- ✅ §3.9 Discovery Interviews section: Task 11
- ✅ §4 Review queue reminder email type: Task 12
- ✅ `country_code` gap fix: already present in DB (`_migrate_stakeholders`), gap was only in `api/models.py` — `Stakeholder` model read path goes through `database.py` row dict, not `models.py`, so no model change needed

**Type consistency:**
- `Campaign.id` used in Task 10 and Task 11 ✅
- `campaignsApi.exportTargets` returns a URL string, called with `href=` in Task 11 ✅
- `ReminderEmail.status` values `'approved' | 'dismissed'` match `update_reminder_email_svc` ✅
- `_escalation_level` returns `'gentle' | 'firm' | 'urgent'` matching `REMINDER_TEMPLATES` keys ✅
