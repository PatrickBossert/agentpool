# SP14a — Neural Agent Tree Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the horizontal crew-card OrgChart with a full-width vertical neural spine layout where every agent in every crew is always visible with live animated status indicators and a high-tech glow aesthetic.

**Architecture:** Two files change — `OrgChart.tsx` is fully rewritten with PAM bar, neural spine, always-on agent rows, and log strip; `Dashboard.tsx` drops its two-column grid and passes new props. Tailwind gets 7 new keyframe animations. No backend changes.

**Tech Stack:** React 18 + TypeScript, Tailwind CSS v3 (arbitrary values + `extend.keyframes`), existing `@tanstack/react-query` data, WebSocket logs hook.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `ui/tailwind.config.js` | Modify | Add `keyframes` + `animation` tokens |
| `ui/src/components/OrgChart.tsx` | Full rewrite | PAM bar, spine, crew nodes, agent rows, log strip |
| `ui/src/pages/Dashboard.tsx` | Modify | Remove two-col grid + InfoCard, pass new props to OrgChart |

`ui/src/components/InfoCard.tsx` — left in place, just not rendered. Do not delete.

---

## Task 1: Tailwind keyframes + OrgChart rewrite

**Files:**
- Modify: `ui/tailwind.config.js`
- Rewrite: `ui/src/components/OrgChart.tsx`

---

- [ ] **Step 1: Add animation keyframes to tailwind.config.js**

Replace the entire file with:

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
      keyframes: {
        ekg: {
          '0%, 100%': { opacity: '0.25' },
          '50%': { opacity: '1' },
        },
        crewGlow: {
          '0%, 100%': { boxShadow: '0 0 16px #19d4e840, 0 0 40px #19d4e815' },
          '50%': { boxShadow: '0 0 28px #19d4e870, 0 0 60px #19d4e830' },
        },
        agentPulse: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.35' },
        },
        particleFlow: {
          '0%':   { top: '-4px', opacity: '0' },
          '10%':  { opacity: '1' },
          '90%':  { opacity: '1' },
          '100%': { top: 'calc(100% - 4px)', opacity: '0' },
        },
        scanline: {
          '0%':   { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(100%)' },
        },
        pamPulse: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.55' },
        },
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0' },
        },
      },
      animation: {
        ekg:          'ekg 1.6s ease-in-out infinite',
        crewGlow:     'crewGlow 3s ease-in-out infinite',
        agentPulse:   'agentPulse 0.8s ease-in-out infinite',
        particleFlow: 'particleFlow 3s linear infinite',
        scanline:     'scanline 2s linear infinite',
        pamPulse:     'pamPulse 2s ease-in-out infinite',
        blink:        'blink 1.2s step-end infinite',
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 2: Verify Tailwind picks up the new tokens**

Run: `cd ui && npx tailwindcss --input src/index.css --output /tmp/tw-check.css 2>&1 | tail -5`

Expected: no errors, exits 0.

- [ ] **Step 3: Rewrite OrgChart.tsx**

Replace the entire file `ui/src/components/OrgChart.tsx` with:

```tsx
// ui/src/components/OrgChart.tsx
import type { CrewRun } from '../types'

// ── Constants ─────────────────────────────────────────────────────────────────

export const CREW_ORDER = [
  'discovery',
  'value_design',
  'architecture',
  'delivery',
  'business_plan',
] as const

export type CrewName = (typeof CREW_ORDER)[number] | 'discovery_interviews'

export const CREW_LABELS: Record<string, string> = {
  discovery:             'Discovery',
  discovery_interviews:  'Discovery Interviews',
  value_design:          'Value Design',
  architecture:          'Architecture',
  delivery:              'Delivery',
  business_plan:         'Business Plan',
}

export const CREW_AGENTS: Record<string, string[]> = {
  discovery: [
    'Value Chain Mapper',
    'Requirements Capture',
    'Requirements Analyst',
    'Value Lever Analyst',
  ],
  discovery_interviews: [
    'Interview Script Designer',
    'Interview Coordinator',
    'Stakeholder Interviewer',
    'Synthesis Analyst',
  ],
  value_design:  ['Value Proposition Generator', 'Portfolio Manager'],
  architecture:  ['Enterprise Architect', 'Initiative Identifier'],
  delivery:      ['Roadmap Generator'],
  business_plan: ['Business Plan Generator'],
}

const CREW_ICONS: Record<string, string> = {
  discovery:            '🔍',
  discovery_interviews: '🎙',
  value_design:         '⭐',
  architecture:         '🏛',
  delivery:             '🚀',
  business_plan:        '📊',
}

// Heights (px) for EKG bars — 7 bars, varying heights for waveform look
const EKG_HEIGHTS = [3, 9, 5, 13, 4, 7, 3]

// ── Types ─────────────────────────────────────────────────────────────────────

type AgentStatus = 'running' | 'completed' | 'queued' | 'idle'
type CrewStatus  = 'running' | 'completed' | 'failed' | 'queued' | 'idle'

// ── Helpers ───────────────────────────────────────────────────────────────────

function inferAgentStatuses(crewKey: string, logs: string[]): AgentStatus[] {
  const agents = CREW_AGENTS[crewKey] ?? []
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

function getCrewStatus(
  crewRun: CrewRun | undefined,
  isActive: boolean,
  isPipelineActive: boolean,
): CrewStatus {
  if (isActive) return 'running'
  if (crewRun?.status === 'completed') return 'completed'
  if (crewRun?.status === 'failed') return 'failed'
  if (isPipelineActive) return 'queued'
  return 'idle'
}

// ── AgentRow ──────────────────────────────────────────────────────────────────

function AgentRow({ name, status }: { name: string; status: AgentStatus }) {
  const barClass =
    status === 'running'   ? 'bg-brand animate-agentPulse' :
    status === 'completed' ? 'bg-brand-green' :
    status === 'queued'    ? 'bg-slate-800' :
                             'bg-slate-900'

  const nameClass =
    status === 'running'   ? 'text-slate-100 font-semibold' :
    status === 'completed' ? 'text-slate-500' :
    status === 'queued'    ? 'text-slate-700' :
                             'text-slate-800'

  return (
    <div className="flex items-center gap-2">
      <div className={`w-0.5 h-3.5 rounded-sm flex-shrink-0 ${barClass}`} />
      <span className={`text-[10px] font-mono leading-none ${nameClass}`}>{name}</span>
    </div>
  )
}

// ── CrewNode ──────────────────────────────────────────────────────────────────

interface CrewNodeProps {
  crewKey: string
  crewRun: CrewRun | undefined
  isActive: boolean
  isPipelineActive: boolean
  logs: string[]
  interviewBadge?: string | null
  onClick?: () => void
}

function CrewNode({
  crewKey, crewRun, isActive, isPipelineActive, logs, interviewBadge, onClick,
}: CrewNodeProps) {
  const status = getCrewStatus(crewRun, isActive, isPipelineActive)
  const agents = CREW_AGENTS[crewKey] ?? []

  const agentStatuses: AgentStatus[] = (() => {
    if (isActive) return inferAgentStatuses(crewKey, logs)
    if (status === 'completed') return agents.map(() => 'completed' as AgentStatus)
    return agents.map(() => (isPipelineActive ? 'queued' : 'idle') as AgentStatus)
  })()

  const borderClass =
    status === 'running'   ? 'border-brand animate-crewGlow' :
    status === 'completed' ? 'border-brand-green/40' :
    status === 'failed'    ? 'border-red-500/40' :
    status === 'queued'    ? 'border-slate-700' :
                             'border-slate-800'

  const bgClass =
    status === 'running'   ? 'bg-brand/5' :
    status === 'completed' ? 'bg-brand-green/5' :
    status === 'failed'    ? 'bg-red-500/5' :
                             'bg-surface'

  const headNameClass =
    status === 'running'   ? 'text-brand' :
    status === 'completed' ? 'text-brand-green' :
    status === 'failed'    ? 'text-red-400' :
    status === 'queued'    ? 'text-slate-500' :
                             'text-slate-700'

  const statusBadge =
    status === 'running'   ? <span className="text-[9px] font-mono text-brand animate-blink ml-auto">● RUNNING</span> :
    status === 'completed' ? <span className="text-[9px] font-mono text-brand-green ml-auto">✓ DONE</span> :
    status === 'failed'    ? <span className="text-[9px] font-mono text-red-400 ml-auto">✗ FAILED</span> :
    status === 'queued'    ? <span className="text-[9px] font-mono text-slate-700 ml-auto">○ QUEUED</span> :
                             null

  return (
    <div
      className={`relative border rounded-lg overflow-hidden ${borderClass} ${bgClass} ${onClick ? 'cursor-pointer' : ''}`}
      onClick={onClick}
    >
      {/* Scanline sweep — only on running crew */}
      {status === 'running' && (
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-brand to-transparent animate-scanline pointer-events-none" />
      )}

      {/* Header */}
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 border-b border-slate-800/60">
        <span className="text-sm leading-none">{CREW_ICONS[crewKey]}</span>
        <span className={`text-[10px] font-mono font-bold tracking-wider ${headNameClass}`}>
          {(CREW_LABELS[crewKey] ?? crewKey).toUpperCase()}
        </span>
        {statusBadge}
      </div>

      {/* Agent list — always rendered */}
      <div className="flex flex-col gap-1.5 px-2.5 py-2">
        {agents.map((agent, idx) => (
          <AgentRow key={agent} name={agent} status={agentStatuses[idx]} />
        ))}
        {interviewBadge && crewKey === 'discovery' && (
          <div className="text-[9px] text-brand border border-brand/20 rounded px-1.5 py-0.5 bg-brand/5 mt-0.5 font-mono">
            {interviewBadge}
          </div>
        )}
      </div>
    </div>
  )
}

// ── OrgChart (main export) ────────────────────────────────────────────────────

interface OrgChartProps {
  crewRuns: CrewRun[]
  isPipelineActive: boolean
  logs: string[]
  interviewBadge?: string | null
  onCrewClick?: (name: CrewName) => void
  onRun: () => void
  isRunPending: boolean
  lastRun?: { started_at: string | null; completed_at: string | null } | null
  orch?: { id: number; status: string } | null
}

export default function OrgChart({
  crewRuns, isPipelineActive, logs, interviewBadge,
  onCrewClick, onRun, isRunPending, lastRun: _lastRun, orch,
}: OrgChartProps) {
  const runMap = new Map(crewRuns.map(r => [r.crew_name, r]))
  const activeCrewName = crewRuns.find(r => r.status === 'running')?.crew_name
  const hasEverRun = crewRuns.length > 0

  // PAM bar status text
  const statusText = isPipelineActive && activeCrewName
    ? `${(CREW_LABELS[activeCrewName] ?? activeCrewName).toUpperCase()} RUNNING`
    : orch?.status === 'completed' ? 'COMPLETED'
    : orch?.status === 'failed'    ? 'FAILED'
    : null

  const statusClass = isPipelineActive
    ? 'text-brand animate-blink'
    : orch?.status === 'completed' ? 'text-brand-green'
    : 'text-red-400'

  const statusPrefix = isPipelineActive ? '● ' : orch?.status === 'completed' ? '✓ ' : '✗ '

  // discovery_interviews is a sub-node shown only when a run record exists
  const showDiscoveryInterviews =
    runMap.has('discovery_interviews') || activeCrewName === 'discovery_interviews'

  function renderCrew(crewKey: string, clickable = false) {
    return (
      <CrewNode
        key={crewKey}
        crewKey={crewKey}
        crewRun={runMap.get(crewKey)}
        isActive={activeCrewName === crewKey}
        isPipelineActive={isPipelineActive}
        logs={logs}
        interviewBadge={interviewBadge}
        onClick={clickable ? () => onCrewClick?.(crewKey as CrewName) : undefined}
      />
    )
  }

  return (
    <div className="bg-surface-card border border-slate-700 rounded-xl overflow-hidden">

      {/* ── PAM bar ──────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-2.5 bg-surface-raised border-b border-slate-700">
        <span className="text-brand animate-pamPulse text-sm font-mono leading-none">◈</span>
        <span className="text-[11px] font-mono font-bold tracking-[0.18em] text-brand">
          PAM · ORCHESTRATOR
        </span>

        {/* EKG waveform — always animating */}
        <div className="flex items-end gap-px ml-3">
          {EKG_HEIGHTS.map((h, i) => (
            <div
              key={i}
              className="w-0.5 bg-brand rounded-sm animate-ekg"
              style={{ height: `${h}px`, animationDelay: `${i * 0.1}s` }}
            />
          ))}
        </div>

        {statusText && (
          <span className={`text-[10px] font-mono ml-2 ${statusClass}`}>
            {statusPrefix}{statusText}
          </span>
        )}

        <div className="ml-auto">
          {!isPipelineActive && (
            <button
              onClick={onRun}
              disabled={isRunPending}
              className="text-[11px] font-mono font-semibold px-3 py-1.5 rounded-md bg-brand text-surface disabled:opacity-50 transition-all"
              style={{ boxShadow: isRunPending ? 'none' : '0 0 12px rgba(25,212,232,0.35)' }}
            >
              {isRunPending ? 'Starting…' : '▶ Run Pipeline'}
            </button>
          )}
        </div>
      </div>

      {/* ── Spine + crew columns ─────────────────────────────────── */}
      <div className="flex gap-0 p-4">

        {/* Left column: Discovery · Architecture · Business Plan */}
        <div className="flex-1 flex flex-col gap-3">
          {renderCrew('discovery', true)}
          {showDiscoveryInterviews && (
            <div className="ml-4 border-l-2 border-brand/20 pl-3">
              {renderCrew('discovery_interviews')}
            </div>
          )}
          {renderCrew('architecture')}
          {renderCrew('business_plan')}
        </div>

        {/* Neural spine */}
        <div className="relative w-px mx-5 bg-gradient-to-b from-brand to-brand/10 self-stretch">
          {hasEverRun && [0, 1, 2].map(i => (
            <div
              key={i}
              className="absolute -left-[3px] w-2 h-2 rounded-full bg-brand animate-particleFlow"
              style={{
                animationDelay: `${i}s`,
                boxShadow: '0 0 8px #19d4e8, 0 0 16px #19d4e840',
              }}
            />
          ))}
        </div>

        {/* Right column: Value Design · Delivery — offset to interleave */}
        <div className="flex-1 flex flex-col gap-3 pt-28">
          {renderCrew('value_design', true)}
          {renderCrew('delivery')}
        </div>

      </div>

      {/* ── Log strip ────────────────────────────────────────────── */}
      {logs.length > 0 && (
        <div className="mx-4 mb-4 rounded-lg bg-black/40 border border-slate-800 px-3 py-2">
          {logs.slice(-3).map((line, i, arr) => (
            <p
              key={i}
              className={`text-[10px] font-mono leading-relaxed truncate ${
                i === arr.length - 1 ? 'text-brand/70' : 'text-slate-700'
              }`}
            >
              {line}
            </p>
          ))}
        </div>
      )}

    </div>
  )
}
```

- [ ] **Step 4: Check TypeScript compiles**

Run: `cd ui && npx tsc --noEmit 2>&1 | head -30`

Expected: no errors. If `lastRun` unused warning appears, the `_lastRun` rename in the destructure handles it. Fix any type errors before continuing.

- [ ] **Step 5: Commit**

```bash
git add ui/tailwind.config.js ui/src/components/OrgChart.tsx
git commit -m "feat(sp14a): neural spine agent tree — keyframes + OrgChart rewrite"
```

---

## Task 2: Dashboard.tsx wiring + smoke test

**Files:**
- Modify: `ui/src/pages/Dashboard.tsx`

---

- [ ] **Step 1: Update Dashboard.tsx**

Replace the entire file with:

```tsx
// ui/src/pages/Dashboard.tsx
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { campaignsApi } from '../api/campaigns'
import ReviewQueue from '../components/ReviewQueue'
import OrgChart, { type CrewName } from '../components/OrgChart'
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

      {/* Neural agent tree — full width */}
      <section>
        <OrgChart
          crewRuns={crewRuns}
          isPipelineActive={isPipelineActive}
          logs={logs}
          interviewBadge={interviewBadge}
          onCrewClick={handleCrewClick}
          onRun={() => runMutation.mutate()}
          isRunPending={runMutation.isPending}
          lastRun={lastRun}
          orch={orch}
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

- [ ] **Step 2: Check TypeScript compiles**

Run: `cd ui && npx tsc --noEmit 2>&1 | head -30`

Expected: no errors.

- [ ] **Step 3: Start the dev server and open the dashboard**

Run (in a separate terminal, keep running): `cd ui && npm run dev`

Navigate to `http://localhost:5173` and open any project's dashboard (e.g. `http://localhost:5173/smoke-test`).

**Check the following:**

1. **PAM bar** — visible across the full top of the card. Shows `◈ PAM · ORCHESTRATOR`, 7 EKG bars animating continuously. "▶ Run Pipeline" button visible on the right.

2. **Left column** — three crew nodes visible: Discovery (4 agents), Architecture (2 agents), Business Plan (1 agent).

3. **Right column** — two crew nodes visible offset downward: Value Design (2 agents), Delivery (1 agent).

4. **Spine** — vertical teal line between columns visible. No particles yet (no runs in `crewRuns`).

5. **Idle agent state** — all agent bars are near-black (`bg-slate-900`), names are very dark. Nodes have dark borders. The tree feels dormant but present.

6. **No InfoCard visible** — the old right-panel card should be gone.

7. **Review Queue** — still visible below the OrgChart.

- [ ] **Step 4: Verify animations with a simulated active state**

In the browser console, the app relies on `status.crew_runs` from the API. To visually verify active state without running a real pipeline, temporarily open the Network tab, find the `/api/projects/smoke-test/status` request, and confirm it returns `crew_runs`. If there is a previously completed run, all agents should show green bars + `✓ DONE` badge. Spine particles should animate.

If no completed runs exist, the dormant state (dark agents, no particles) is the correct visual for a fresh project.

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/Dashboard.tsx
git commit -m "feat(sp14a): wire Dashboard to full-width neural OrgChart"
```

---

## Self-review

**Spec coverage:**
- ✅ Section 1 (Layout): Task 2 removes grid, makes OrgChart full-width
- ✅ Section 2 (PAM bar): Task 1 OrgChart — EKG, status text, run button
- ✅ Section 3 (Spine + particles): Task 1 — `w-px` spine, 3 orbs with `animate-particleFlow`
- ✅ Section 4 (Crew nodes, all states, correct agents): Task 1 — full state matrix, corrected CREW_AGENTS
- ✅ Section 4 (`discovery_interviews` conditional): Task 1 — `showDiscoveryInterviews` flag
- ✅ Section 5 (Log strip): Task 1 — bottom strip, last 3 lines, newest in teal
- ✅ Section 6 (Tailwind keyframes): Task 1 — all 7 keyframes added

**Placeholder scan:** None found.

**Type consistency:**
- `CrewName` is `(typeof CREW_ORDER)[number] | 'discovery_interviews'` — used consistently in `onCrewClick` prop and `handleCrewClick`
- `OrgChartProps.orch` typed `{ id: number; status: string } | null | undefined` — matches what Dashboard passes (`status?.latest_orchestration_run`)
- `AgentStatus` and `CrewStatus` defined in Task 1 and used only within `OrgChart.tsx` — no cross-task type drift
