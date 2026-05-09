import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import StatusBadge from '../components/StatusBadge'
import type { OrchestrationRunHistory } from '../types'

function formatDuration(started: string | null, completed: string | null): string {
  if (!started || !completed) return '—'
  const ms = new Date(completed).getTime() - new Date(started).getTime()
  const mins = Math.floor(ms / 60000)
  const secs = Math.floor((ms % 60000) / 1000)
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`
}

function RunRow({ run }: { run: OrchestrationRunHistory }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="bg-surface-card rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-slate-200">Run #{run.id}</span>
          <StatusBadge status={run.status} />
          {run.crew_runs.length > 0 && (
            <span className="text-xs text-slate-500">
              {run.crew_runs.length} crew{run.crew_runs.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-500">
            {run.started_at ? new Date(run.started_at).toLocaleString() : '—'}
          </span>
          <span className="text-xs text-slate-500">
            {formatDuration(run.started_at, run.completed_at)}
          </span>
          <span className="text-slate-500 text-xs">{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div className="border-t border-slate-800 px-4 py-3 space-y-1.5">
          {run.crew_runs.length === 0 ? (
            <p className="text-xs text-slate-500">No crew runs linked to this orchestration run.</p>
          ) : (
            run.crew_runs.map((cr) => (
              <div key={cr.crew_name} className="flex items-center justify-between py-1">
                <span className="text-xs text-slate-300">{cr.crew_name}</span>
                <StatusBadge status={cr.status} />
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}

export default function Runs() {
  const { slug } = useParams<{ slug: string }>()

  const { data: runs = [], isLoading } = useQuery({
    queryKey: ['runs', slug],
    queryFn: () => projectsApi.listRuns(slug!),
    enabled: !!slug,
    refetchInterval: (query) => {
      const hasRunning = query.state.data?.some((r) => r.status === 'running')
      return hasRunning ? 5000 : false
    },
  })

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-slate-100">Run History</h2>
      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {!isLoading && runs.length === 0 && (
        <p className="text-sm text-slate-500">No pipeline runs yet.</p>
      )}
      <div className="space-y-3">
        {runs.map((run) => (
          <RunRow key={run.id} run={run} />
        ))}
      </div>
    </div>
  )
}
