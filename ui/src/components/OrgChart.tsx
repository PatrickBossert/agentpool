// ui/src/components/OrgChart.tsx
import { useMemo, useCallback } from 'react'
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

// Heights (px) for EKG bars - 7 bars, varying heights for waveform look
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

  const agentStatuses = useMemo<AgentStatus[]>(() => {
    if (isActive) return inferAgentStatuses(crewKey, logs)
    if (status === 'completed') return agents.map(() => 'completed' as AgentStatus)
    return agents.map(() => (isPipelineActive ? 'queued' : 'idle') as AgentStatus)
  }, [isActive, crewKey, logs, status, agents, isPipelineActive])

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
      {/* Scanline sweep - only on running crew */}
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

      {/* Agent list - always rendered */}
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

  const renderCrew = useCallback((crewKey: string, clickable = false) => (
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
  ), [runMap, activeCrewName, isPipelineActive, logs, interviewBadge, onCrewClick])

  return (
    <div className="bg-surface-card border border-slate-700 rounded-xl overflow-hidden">

      {/* ── PAM bar ──────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-2.5 bg-surface-raised border-b border-slate-700">
        <span className="text-brand animate-pamPulse text-sm font-mono leading-none">◈</span>
        <span className="text-[11px] font-mono font-bold tracking-[0.18em] text-brand">
          PMO · ORCHESTRATOR
        </span>

        {/* EKG waveform - always animating */}
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
              {isRunPending ? 'Running…' : '▶ Run Pipeline'}
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
        <div className="relative w-px mx-5 bg-gradient-to-b from-brand to-brand/20 self-stretch">
          {(isPipelineActive || hasEverRun) && [0, 1, 2].map(i => (
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

        {/* Right column: Value Design · Delivery - offset to interleave */}
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
              key={logs.length - arr.length + i}
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
