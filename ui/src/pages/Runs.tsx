import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import StatusBadge from '../components/StatusBadge'
import { bcp47 } from '../utils/holidays'
import type { OrchestrationRunHistory } from '../types'

function formatDuration(started: string | null, completed: string | null): string {
  if (!started || !completed) return '-'
  const ms = new Date(completed).getTime() - new Date(started).getTime()
  const mins = Math.floor(ms / 60000)
  const secs = Math.floor((ms % 60000) / 1000)
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`
}

function RunRow({ run, slug, locale = 'GB' }: { run: OrchestrationRunHistory; slug: string; locale?: string }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="bg-surface-card rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-gray-900">Run #{run.id}</span>
          <StatusBadge status={run.status} />
          {run.status === 'awaiting_assignment' && (
            <Link
              to={`/${slug}/assignment`}
              onClick={(e) => e.stopPropagation()}
              className="text-xs text-teal-400 hover:text-teal-300 underline underline-offset-2"
            >
              Go to Assignment →
            </Link>
          )}
          {run.crew_runs.length > 0 && (
            <span className="text-xs text-gray-400">
              {run.crew_runs.length} crew{run.crew_runs.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          <span className="text-xs text-gray-400">
            {run.started_at ? new Date(run.started_at).toLocaleString(bcp47(locale)) : '-'}
          </span>
          <span className="text-xs text-gray-400">
            {formatDuration(run.started_at, run.completed_at)}
          </span>
          <span className="text-gray-400 text-xs">{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div className="border-t border-gray-200 px-4 py-3 space-y-1.5">
          {run.crew_runs.length === 0 ? (
            <p className="text-xs text-gray-400">No crew runs linked to this orchestration run.</p>
          ) : (
            run.crew_runs.map((cr) => (
              <div key={cr.crew_name} className="flex items-center justify-between py-1">
                <span className="text-xs text-gray-600">{cr.crew_name}</span>
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
      const hasActive = query.state.data?.some(
        (r) => r.status === 'running' || r.status === 'awaiting_assignment',
      )
      return hasActive ? 5000 : false
    },
  })

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug!),
    enabled: !!slug,
  })

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-gray-900">Run History</h2>
      {isLoading && <p className="text-sm text-gray-400">Loading…</p>}
      {!isLoading && runs.length === 0 && (
        <p className="text-sm text-gray-400">No pipeline runs yet.</p>
      )}
      <div className="space-y-3">
        {runs.map((run) => (
          <RunRow key={run.id} run={run} slug={slug!} locale={settings?.locale} />
        ))}
      </div>
    </div>
  )
}
