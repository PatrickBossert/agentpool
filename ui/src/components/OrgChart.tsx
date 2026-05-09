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

const CREW_ICONS: Record<CrewName, JSX.Element> = {
  discovery: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.35-4.35" />
      <path d="M8 11h6M11 8v6" />
    </svg>
  ),
  value_design: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
    </svg>
  ),
  architecture: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <rect x="2" y="14" width="8" height="7" rx="1" />
      <rect x="9" y="7" width="8" height="7" rx="1" />
      <rect x="16" y="2" width="6" height="6" rx="1" />
      <path d="M6 14V9.5M13 7V5M19 8v-2" />
    </svg>
  ),
  delivery: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <path d="M12 19V5M5 12l7-7 7 7" />
      <path d="M5 19h14" />
    </svg>
  ),
  business_plan: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M8 17v-5M12 17v-9M16 17v-3" />
    </svg>
  ),
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

  const iconColour =
    status === 'completed'
      ? 'text-brand-green'
      : isActive
        ? 'text-brand'
        : 'text-slate-500'

  return (
    <div className={`flex flex-col gap-1 ${opacityClass}`}>
      <button
        onClick={onClick}
        className={`relative border ${borderClass} ${bgClass} rounded-lg p-3 text-left transition-all w-32 h-24 flex flex-col justify-between`}
      >
        {/* Status indicator */}
        {isActive && (
          <span className="absolute top-2 right-2 w-2 h-2 rounded-full bg-brand animate-pulse" />
        )}
        {status === 'completed' && (
          <span className="absolute top-2 right-2 text-brand-green text-xs leading-none">✓</span>
        )}

        {/* Icon */}
        <span className={`${iconColour} transition-colors`}>
          {CREW_ICONS[name]}
        </span>

        {/* Label + sub-label */}
        <div>
          <p className="text-xs font-semibold text-slate-200 leading-tight pr-4">{CREW_LABELS[name]}</p>
          <p className="text-[10px] text-slate-500 leading-tight">Agent Team</p>
          {interviewBadge && name === 'discovery' && (
            <p className="text-[10px] text-brand mt-0.5">{interviewBadge}</p>
          )}
        </div>
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
