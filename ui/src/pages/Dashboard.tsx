// ui/src/pages/Dashboard.tsx
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { campaignsApi } from '../api/campaigns'
import ReviewQueue from '../components/ReviewQueue'
import OrgChart, { type CrewName } from '../components/OrgChart'
import { useWebSocket } from '../hooks/useWebSocket'
import type { CrewRun } from '../types'

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

  const { data: runs = [] } = useQuery({
    queryKey: ['runs', slug],
    queryFn: () => projectsApi.listRuns(slug!),
    enabled: !!slug,
  })

  const { data: interviewSummary } = useQuery({
    queryKey: ['interview-summary', slug],
    queryFn: () => campaignsApi.interviewSummary(slug!),
    enabled: !!slug,
    refetchInterval: 30_000,
  })

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

  const crewRuns: CrewRun[] = status?.crew_runs ?? []
  const orch = status?.latest_orchestration_run
  const isPipelineActive = orch?.status === 'running'
  const lastRun = runs[0] ?? null

  const interviewBadge: string | null = (() => {
    if (!interviewSummary || interviewSummary.total_stakeholders === 0) return null
    return `${interviewSummary.total_completed} / ${interviewSummary.total_stakeholders} ✓`
  })()

  function handleCrewClick(name: CrewName) {
    if (name === 'discovery') navigate(`/${slug}/discovery`)
  }

  return (
    <div className="p-6 space-y-6">
      {/* Project header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-100">{slug}</h2>
        <div className="flex items-center gap-3">
          <button
            onClick={() => window.open(`/dashboard/${slug}/report`, '_blank')}
            className="text-xs px-3 py-1.5 rounded bg-surface-card border border-slate-700 text-slate-300 hover:text-slate-100 hover:border-slate-500"
          >
            Export Report
          </button>
          {(orch?.status === 'completed' || orch?.status === 'failed') && (
            <button
              onClick={() => navigate(`/${slug}/runs/${orch.id}`)}
              className="text-xs text-brand hover:text-brand-light"
            >
              View Last Run →
            </button>
          )}
        </div>
      </div>

      {/* Org chart */}
      <section>
        <OrgChart
          crewRuns={crewRuns}
          isPipelineActive={isPipelineActive}
          logs={logs}
          interviewBadge={interviewBadge}
          onCrewClick={handleCrewClick}
          onRun={() => runMutation.mutate()}
          isRunPending={runMutation.isPending}
          lastRun={lastRun}
          orch={orch}
        />
      </section>

      {/* Review queue */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Review Queue
        </h3>
        <ReviewQueue slug={slug} outputs={outputs} />
      </section>
    </div>
  )
}
