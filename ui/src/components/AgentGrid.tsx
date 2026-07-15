// ui/src/components/AgentGrid.tsx
import { useMemo } from 'react'
import type { CrewRun, HumanReview } from '../types'
import {
  CREW_ORDER, CREW_LABELS, CREW_AGENTS, CREW_ICONS, AGENT_AVATAR, AGENT_RUN_KEYS,
  inferAgentStatuses, getCrewStatus,
  type AgentStatus, type CrewStatus,
} from './agentStatus'

// ── Status dot ──────────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: AgentStatus }) {
  const cls =
    status === 'running'   ? 'bg-teal-500 animate-pulse' :
    status === 'waiting'   ? 'bg-amber-400 animate-pulse' :
    status === 'completed' ? 'bg-green-500' :
    status === 'queued'    ? 'bg-gray-300' :
                             'bg-gray-200'
  return <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${cls}`} />
}

// ── Compact agent chip ──────────────────────────────────────────────────────────

function AgentChip({ name, status, disabled, onClick, onRun }: {
  name: string
  status: AgentStatus
  disabled: boolean
  onClick: () => void
  onRun?: () => void
}) {
  const avatar = AGENT_AVATAR[name] ?? { emoji: '🤖', gradient: 'from-gray-400 to-gray-600' }
  return (
    <div className="group relative flex items-center gap-1.5 bg-white border border-gray-100 rounded-lg pl-1.5 pr-2.5 py-1 hover:border-teal-200 hover:shadow-sm transition-all">
      {/* Avatar */}
      <div className={`w-5 h-5 rounded-full bg-gradient-to-br ${avatar.gradient} flex items-center justify-center text-[10px] flex-shrink-0`}>
        {avatar.emoji}
      </div>

      {/* Name + dot */}
      <span className="text-xs text-gray-700 font-medium whitespace-nowrap leading-none">{name}</span>
      <StatusDot status={status} />

      {/* Hover overlay with actions */}
      <div className="absolute inset-0 hidden group-hover:flex items-center justify-center gap-2 bg-white/95 rounded-lg border border-teal-200">
        <button
          onClick={onClick}
          className="text-[10px] font-semibold text-teal-700 hover:text-teal-900"
        >
          Chat ↗
        </button>
        {onRun && (
          <>
            <span className="text-gray-200 text-[10px]">|</span>
            <button
              onClick={e => { e.stopPropagation(); onRun() }}
              disabled={disabled}
              className="text-[10px] font-semibold text-teal-700 hover:text-teal-900 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              ▶ Run
            </button>
          </>
        )}
      </div>
    </div>
  )
}

// ── Crew status badge ───────────────────────────────────────────────────────────

function CrewStatusBadge({ status }: { status: CrewStatus }) {
  if (status === 'idle') return null
  const cls =
    status === 'running'   ? 'bg-teal-50 text-teal-700 border-teal-200' :
    status === 'waiting'   ? 'bg-amber-50 text-amber-700 border-amber-200' :
    status === 'completed' ? 'bg-green-50 text-green-700 border-green-200' :
    status === 'failed'    ? 'bg-red-50 text-red-700 border-red-200' :
                             'bg-gray-50 text-gray-500 border-gray-200'
  const label =
    status === 'running'   ? '● Running' :
    status === 'waiting'   ? '⏸ Waiting' :
    status === 'completed' ? '✓ Done' :
    status === 'failed'    ? '✗ Failed' :
                             '○ Queued'
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full border ${cls}`}>
      {label}
    </span>
  )
}

// ── AgentGrid ───────────────────────────────────────────────────────────────────

export interface AgentGridProps {
  crewRuns: CrewRun[]
  isPipelineActive: boolean
  logs: string[]
  hitlReviews?: HumanReview[]
  onAgentChat: (agentName: string) => void
  onRunCrew?: (crewName: string) => void
  onRunAgent?: (agentKey: string) => void
  runningCrew?: string | null
  runningAgent?: string | null
}

const ALL_CREWS = CREW_ORDER
const STANDALONE_CREWS = new Set(CREW_ORDER)

export default function AgentGrid({
  crewRuns, isPipelineActive, logs, hitlReviews = [], onAgentChat, onRunCrew, onRunAgent, runningCrew, runningAgent,
}: AgentGridProps) {
  // crewRuns is DESC (newest first); keep first occurrence so newest run wins
  const runMap = useMemo(() => {
    const map = new Map<string, CrewRun>()
    for (const r of crewRuns) if (!map.has(r.crew_name)) map.set(r.crew_name, r)
    return map
  }, [crewRuns])
  const activeCrewName = useMemo(() => crewRuns.find(r => r.status === 'running')?.crew_name, [crewRuns])
  const waitingCrews = useMemo(() => new Set(hitlReviews.map(r => r.crew_name).filter(Boolean) as string[]), [hitlReviews])
  const showDiscoveryInterviews = runMap.has('discovery_interviews') || activeCrewName === 'discovery_interviews'
  const crewsToShow = ALL_CREWS.filter(c => c !== 'discovery_interviews' || showDiscoveryInterviews)

  return (
    <div className="space-y-1">
      {crewsToShow.map(crewKey => {
        const crewRun = runMap.get(crewKey)
        const isActive = activeCrewName === crewKey
        const isWaiting = waitingCrews.has(crewKey)
        const crewStatus = getCrewStatus(crewRun, isActive, isPipelineActive, isWaiting)
        const agents = CREW_AGENTS[crewKey] ?? []

        const agentStatuses: AgentStatus[] = isWaiting
          ? agents.map(() => 'waiting' as AgentStatus)
          : isActive
            ? inferAgentStatuses(crewKey, logs)
            : crewStatus === 'completed'
              ? agents.map(() => 'completed' as AgentStatus)
              : agents.map(() => (isPipelineActive ? 'queued' : 'idle') as AgentStatus)

        const canRunCrew = STANDALONE_CREWS.has(crewKey as typeof CREW_ORDER[number])
        const isDispatchingCrew = runningCrew === crewKey
        const anyBusy = isPipelineActive || crewStatus === 'running' || !!runningCrew || !!runningAgent

        return (
          <div key={crewKey} className="rounded-xl border border-gray-100 bg-gray-50/60 px-3 py-2.5">
            {/* Crew header */}
            <div className="flex items-center gap-1.5 mb-2">
              <span className="text-sm leading-none">{CREW_ICONS[crewKey]}</span>
              <span className="text-[11px] font-bold text-gray-500 uppercase tracking-widest">
                {CREW_LABELS[crewKey]}
              </span>
              <CrewStatusBadge status={crewStatus} />
              {canRunCrew && onRunCrew && (
                <button
                  onClick={() => onRunCrew(crewKey)}
                  disabled={anyBusy}
                  className="ml-auto text-[10px] font-semibold px-2 py-0.5 rounded bg-white hover:bg-teal-50 text-teal-700 border border-teal-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {isDispatchingCrew ? '…' : '▶ Run all'}
                </button>
              )}
            </div>

            {/* Agent chips */}
            <div className="flex flex-wrap gap-1.5">
              {agents.map((agent, idx) => {
                const agentKey = AGENT_RUN_KEYS[agent]
                const isDispatchingAgent = runningAgent === agentKey
                return (
                  <AgentChip
                    key={agent}
                    name={agent}
                    status={isDispatchingAgent ? 'running' : agentStatuses[idx]}
                    disabled={anyBusy}
                    onClick={() => onAgentChat(agent)}
                    onRun={agentKey && onRunAgent ? () => onRunAgent(agentKey) : undefined}
                  />
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
