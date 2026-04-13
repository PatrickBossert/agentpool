// ui/src/pages/Dashboard.tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import StatusBadge from '../components/StatusBadge'
import ReviewQueue from '../components/ReviewQueue'
import { useWebSocket } from '../hooks/useWebSocket'

export default function Dashboard() {
  const { slug } = useParams<{ slug?: string }>()
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

  if (!slug) {
    return (
      <div className="p-8 text-slate-400">
        <p>Select a project from the sidebar to begin.</p>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-100 mb-1">{slug}</h2>
        {status && (
          <div className="flex items-center gap-2">
            <StatusBadge status={status.project_status} />
          </div>
        )}
      </div>

      {/* Crew progress */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Crew Progress
        </h3>
        {status?.crew_runs.length === 0 && (
          <p className="text-sm text-slate-500">No crew runs yet.</p>
        )}
        <div className="space-y-2">
          {status?.crew_runs.map((run) => (
            <div
              key={run.id}
              className="flex items-center justify-between bg-surface-card rounded-lg px-4 py-3"
            >
              <span className="text-sm text-slate-200">{run.crew_name}</span>
              <StatusBadge status={run.status} />
            </div>
          ))}
        </div>
      </section>

      {/* Review queue */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Review Queue
        </h3>
        <ReviewQueue slug={slug} outputs={outputs} />
      </section>

      {/* Live log */}
      {logs.length > 0 && (
        <section>
          <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
            Agent Log
          </h3>
          <div className="bg-black/40 rounded-lg p-4 font-mono text-xs text-emerald-400 space-y-0.5 max-h-48 overflow-y-auto">
            {logs.map((line, i) => (
              <p key={i}>{line}</p>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
