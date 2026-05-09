// ui/src/pages/Dashboard.tsx
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { campaignsApi } from '../api/campaigns'
import ReviewQueue from '../components/ReviewQueue'
import OrgChart, { type CrewName } from '../components/OrgChart'
import InfoCard from '../components/InfoCard'
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
  const activeRun = crewRuns.find((r) => r.status === 'running')
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
        {(orch?.status === 'completed' || orch?.status === 'failed') && (
          <button
            onClick={() => navigate(`/${slug}/runs/${orch.id}`)}
            className="text-xs text-brand hover:text-brand-light"
          >
            View Last Run →
          </button>
        )}
      </div>

      {/* Org chart + info card */}
      <section className="grid grid-cols-[1fr_320px] gap-4 items-start">
        <div className="bg-surface-card border border-slate-700 rounded-xl p-4">
          <OrgChart
            crewRuns={crewRuns}
            isPipelineActive={isPipelineActive}
            logs={logs}
            interviewBadge={interviewBadge}
            onCrewClick={handleCrewClick}
          />
        </div>
        <InfoCard
          activeRun={activeRun}
          isPipelineActive={isPipelineActive}
          logs={logs}
          lastRun={lastRun}
          interviewBadge={interviewBadge}
          onRun={() => runMutation.mutate()}
          isRunPending={runMutation.isPending}
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
