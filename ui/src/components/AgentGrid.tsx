// ui/src/components/AgentGrid.tsx
import { useMemo } from 'react'
import type { CrewRun } from '../types'
import {
  CREW_ORDER, CREW_LABELS, CREW_AGENTS, CREW_ICONS, AGENT_AVATAR,
  inferAgentStatuses, getCrewStatus,
  type AgentStatus, type CrewStatus,
} from './agentStatus'

// ── Status dot ─────────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: AgentStatus }) {
  const dot =
    status === 'running'   ? 'bg-teal-500 animate-pulse' :
    status === 'completed' ? 'bg-green-500' :
    status === 'queued'    ? 'bg-gray-300' :
                             'bg-gray-200'
  const label =
    status === 'running'   ? 'running' :
    status === 'completed' ? 'done' :
    status === 'queued'    ? 'queued' :
                             'idle'
  return (
    <span className="flex items-center gap-1">
      <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${dot}`} />
      <span className="text-[10px] text-gray-400 leading-none">{label}</span>
    </span>
  )
}

// ── AgentCard ──────────────────────────────────────────────────────────────────

function AgentCard({ name, status, onClick }: {
  name: string
  status: AgentStatus
  onClick: () => void
}) {
  const avatar = AGENT_AVATAR[name] ?? { emoji: '🤖', gradient: 'from-gray-400 to-gray-600' }
  return (
    <button
      onClick={onClick}
      className="group bg-white border border-gray-100 rounded-xl p-4 flex flex-col items-center gap-2 shadow-sm hover:shadow-md hover:border-teal-200 transition-all w-full"
    >
      <div
        className={`w-14 h-14 rounded-full bg-gradient-to-br ${avatar.gradient} flex items-center justify-center text-2xl shadow-sm flex-shrink-0`}
      >
        {avatar.emoji}
      </div>
      <p className="text-xs font-semibold text-gray-700 text-center leading-tight line-clamp-2 w-full">
        {name}
      </p>
      <StatusDot status={status} />
      <span className="text-[10px] text-teal-600 opacity-0 group-hover:opacity-100 transition-opacity font-medium">
        Chat ↗
      </span>
    </button>
  )
}

// ── Crew status badge ──────────────────────────────────────────────────────────

function CrewStatusBadge({ status }: { status: CrewStatus }) {
  if (status === 'idle') return null
  const cls =
    status === 'running'   ? 'bg-teal-50 text-teal-700 border-teal-200' :
    status === 'completed' ? 'bg-green-50 text-green-700 border-green-200' :
    status === 'failed'    ? 'bg-red-50 text-red-700 border-red-200' :
                             'bg-gray-50 text-gray-500 border-gray-200'
  const label =
    status === 'running'   ? '● Running' :
    status === 'completed' ? '✓ Done' :
    status === 'failed'    ? '✗ Failed' :
                             '○ Queued'
  return (
    <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${cls}`}>
      {label}
    </span>
  )
}

// ── AgentGrid ──────────────────────────────────────────────────────────────────

export interface AgentGridProps {
  crewRuns: CrewRun[]
  isPipelineActive: boolean
  logs: string[]
  onAgentChat: (agentName: string) => void
  onRunCrew?: (crewName: string) => void
  runningCrew?: string | null
}

const ALL_CREWS = [...CREW_ORDER, 'discovery_interviews' as const]

// crews that can be dispatched standalone (discovery_interviews requires PAM context)
const STANDALONE_CREWS = new Set(CREW_ORDER)

export default function AgentGrid({ crewRuns, isPipelineActive, logs, onAgentChat, onRunCrew, runningCrew }: AgentGridProps) {
  const runMap = useMemo(() => new Map(crewRuns.map(r => [r.crew_name, r])), [crewRuns])
  const activeCrewName = useMemo(() => crewRuns.find(r => r.status === 'running')?.crew_name, [crewRuns])
  const showDiscoveryInterviews = runMap.has('discovery_interviews') || activeCrewName === 'discovery_interviews'

  const crewsToShow = ALL_CREWS.filter(c => c !== 'discovery_interviews' || showDiscoveryInterviews)

  return (
    <div className="space-y-8">
      {crewsToShow.map(crewKey => {
        const crewRun = runMap.get(crewKey)
        const isActive = activeCrewName === crewKey
        const crewStatus = getCrewStatus(crewRun, isActive, isPipelineActive)
        const agents = CREW_AGENTS[crewKey] ?? []
        const agentStatuses: AgentStatus[] = isActive
          ? inferAgentStatuses(crewKey, logs)
          : crewStatus === 'completed'
            ? agents.map(() => 'completed' as AgentStatus)
            : agents.map(() => (isPipelineActive ? 'queued' : 'idle') as AgentStatus)

        const canRun = STANDALONE_CREWS.has(crewKey as typeof CREW_ORDER[number])
        const isDispatchingThis = runningCrew === crewKey
        const runDisabled = isPipelineActive || crewStatus === 'running' || !!runningCrew

        return (
          <div key={crewKey}>
            <div className="flex items-center gap-2 mb-4">
              <span className="text-base leading-none">{CREW_ICONS[crewKey]}</span>
              <h3 className="text-xs font-bold text-gray-500 uppercase tracking-widest">
                {CREW_LABELS[crewKey]}
              </h3>
              <CrewStatusBadge status={crewStatus} />
              {canRun && onRunCrew && (
                <button
                  onClick={() => onRunCrew(crewKey)}
                  disabled={runDisabled}
                  className="ml-auto text-[10px] font-semibold px-2 py-0.5 rounded bg-teal-50 hover:bg-teal-100 text-teal-700 border border-teal-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {isDispatchingThis ? '…' : '▶ Run'}
                </button>
              )}
            </div>
            <div
              className="grid gap-3"
              style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))' }}
            >
              {agents.map((agent, idx) => (
                <AgentCard
                  key={agent}
                  name={agent}
                  status={agentStatuses[idx]}
                  onClick={() => onAgentChat(agent)}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
