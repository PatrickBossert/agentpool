// ui/src/pages/RunDetail.tsx
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import StatusBadge from '../components/StatusBadge'
import { useWebSocket } from '../hooks/useWebSocket'

export default function RunDetail() {
  const { slug, runId: _runId } = useParams<{ slug: string; runId: string }>()
  const navigate = useNavigate()
  const logs = useWebSocket(slug)

  const { data: status } = useQuery({
    queryKey: ['status', slug],
    queryFn: () => projectsApi.status(slug!),
    enabled: !!slug,
    refetchInterval: (query) => {
      const s = query.state.data?.latest_orchestration_run?.status
      return s === 'running' ? 3_000 : false
    },
  })

  const orch = status?.latest_orchestration_run

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate(`/${slug}`)}
          className="text-sm text-slate-400 hover:text-slate-200"
        >
          ← Back to Dashboard
        </button>
        <h2 className="text-lg font-semibold text-slate-100">Pipeline Run</h2>
        {orch && <StatusBadge status={orch.status} />}
      </div>

      {/* Crew progress */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Crew Progress
        </h3>
        {!status?.crew_runs.length && (
          <p className="text-sm text-slate-500">Waiting for crews to start…</p>
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

      {/* Live agent log */}
      {logs.length > 0 && (
        <section>
          <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
            Agent Log
          </h3>
          <div className="bg-black/40 rounded-lg p-4 font-mono text-xs text-emerald-400 space-y-0.5 max-h-64 overflow-y-auto">
            {logs.map((line, i) => (
              <p key={i}>{line}</p>
            ))}
          </div>
        </section>
      )}

      {/* Completion notice */}
      {orch && orch.status !== 'running' && (
        <div
          className={`rounded-lg px-4 py-3 text-sm ${
            orch.status === 'completed'
              ? 'bg-emerald-900/30 text-emerald-300'
              : 'bg-red-900/30 text-red-300'
          }`}
        >
          {orch.status === 'completed'
            ? 'Pipeline completed successfully. All outputs are available in the Documents tab.'
            : 'Pipeline failed. Check the agent log above for details.'}
        </div>
      )}
    </div>
  )
}
