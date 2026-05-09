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
