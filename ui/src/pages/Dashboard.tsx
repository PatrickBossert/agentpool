// ui/src/pages/Dashboard.tsx
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import StatusBadge from '../components/StatusBadge'
import ReviewQueue from '../components/ReviewQueue'
import { useWebSocket } from '../hooks/useWebSocket'

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

  const { data: reviews = [] } = useQuery({
    queryKey: ['reviews', slug],
    queryFn: () => projectsApi.listReviews(slug!),
    enabled: !!slug,
    refetchInterval: 5000,
  })
  const pendingReviewCount = reviews.length

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

  const orch = status?.latest_orchestration_run

  return (
    <div className="p-6 space-y-6">
      {/* Project header + Run Pipeline control */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-100 mb-1">{slug}</h2>
          {status && (
            <div className="flex items-center gap-2">
              <StatusBadge status={status.project_status} />
            </div>
          )}
        </div>

        {/* Run Pipeline button — four states */}
        <div className="flex items-center gap-3">
          {!orch && (
            <button
              onClick={() => runMutation.mutate()}
              disabled={runMutation.isPending}
              className="px-4 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm rounded"
            >
              Run Pipeline
            </button>
          )}

          {orch?.status === 'running' && (
            <>
              <button
                disabled
                className="px-4 py-1.5 bg-slate-700 text-slate-400 text-sm rounded opacity-60 cursor-not-allowed flex items-center gap-2"
              >
                <span className="inline-block w-3 h-3 border-2 border-slate-400 border-t-transparent rounded-full animate-spin" />
                Running…
              </button>
              <button
                onClick={() => navigate(`/${slug}/runs/${orch.id}`)}
                className="text-sm text-sky-400 hover:text-sky-300"
              >
                View Run →
              </button>
            </>
          )}

          {(orch?.status === 'completed' || orch?.status === 'failed') && (
            <>
              <span
                className={`text-sm font-medium ${
                  orch.status === 'completed' ? 'text-emerald-400' : 'text-red-400'
                }`}
              >
                {orch.status === 'completed' ? 'Completed' : 'Failed'}
              </span>
              <button
                onClick={() => navigate(`/${slug}/runs/${orch.id}`)}
                className="text-sm text-sky-400 hover:text-sky-300"
              >
                View Last Run →
              </button>
              <button
                onClick={() => runMutation.mutate()}
                disabled={runMutation.isPending}
                className="px-4 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm rounded"
              >
                Run Again
              </button>
            </>
          )}
        </div>
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

      {/* Pending reviews banner */}
      {pendingReviewCount > 0 && (
        <section>
          <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-2">
            Pending Reviews
          </h3>
          <div className="bg-surface rounded-lg border-l-4 border-amber-500 px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="rounded px-2 py-0.5 text-xs font-bold tracking-wide bg-amber-500/10 text-amber-400 uppercase">
                {pendingReviewCount} pending
              </span>
              <p className="text-sm text-slate-400">
                {pendingReviewCount === 1 ? 'A crew is' : 'Crews are'} waiting for your input
              </p>
            </div>
            <Link
              to={`/${slug}/reviews`}
              className="text-xs text-sky-400 hover:text-sky-300 border border-sky-900/40 rounded px-2.5 py-1.5 transition-colors"
            >
              Go to Reviews →
            </Link>
          </div>
        </section>
      )}

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
