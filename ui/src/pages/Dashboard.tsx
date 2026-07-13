// ui/src/pages/Dashboard.tsx
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import ReviewQueue from '../components/ReviewQueue'
import AgentGrid from '../components/AgentGrid'
import AgentChatDrawer from '../components/AgentChatDrawer'
import { useWebSocket } from '../hooks/useWebSocket'
import type { CrewRun } from '../types'

export default function Dashboard() {
  const { slug } = useParams<{ slug?: string }>()
  const navigate = useNavigate()
  const logs = useWebSocket(slug)
  const [activeAgent, setActiveAgent] = useState<string | null>(null)

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

  const runMutation = useMutation({
    mutationFn: () => projectsApi.orchestrate(slug!),
    onSuccess: (data) => {
      navigate(`/${slug}/runs/${data.orchestration_run_id}`)
    },
  })

  if (!slug) {
    return (
      <div className="p-8 text-gray-400">
        <p>Select a project from the sidebar to begin.</p>
      </div>
    )
  }

  const crewRuns: CrewRun[] = status?.crew_runs ?? []
  const orch = status?.latest_orchestration_run
  const isPipelineActive = orch?.status === 'running'

  return (
    <div className="p-6 space-y-8">
      {/* Project header */}
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold text-gray-900">{slug}</h2>
        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={() => window.open(`/dashboard/${slug}/report`, '_blank')}
            className="text-xs px-3 py-1.5 rounded-lg bg-white border border-gray-200 text-gray-600 hover:text-gray-900 hover:border-gray-400 transition-colors"
          >
            Export Report
          </button>
          {(orch?.status === 'completed' || orch?.status === 'failed') && (
            <button
              onClick={() => navigate(`/${slug}/runs/${orch.id}`)}
              className="text-xs text-teal-600 hover:text-teal-700"
            >
              View Last Run →
            </button>
          )}
          {isPipelineActive ? (
            <span className="text-xs font-medium text-teal-600 animate-pulse">● Pipeline running</span>
          ) : (
            <button
              onClick={() => runMutation.mutate()}
              disabled={runMutation.isPending}
              className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-700 disabled:opacity-50 text-white transition-colors"
            >
              {runMutation.isPending ? 'Starting…' : '▶ Run Pipeline'}
            </button>
          )}
        </div>
      </div>

      {/* Agent grid */}
      <section>
        <AgentGrid
          crewRuns={crewRuns}
          isPipelineActive={isPipelineActive}
          logs={logs}
          onAgentChat={setActiveAgent}
        />
      </section>

      {/* Review queue */}
      <section>
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">
          Review Queue
        </h3>
        <ReviewQueue slug={slug} outputs={outputs} />
      </section>

      {/* Agent chat drawer */}
      <AgentChatDrawer
        slug={slug}
        agentName={activeAgent}
        onClose={() => setActiveAgent(null)}
      />
    </div>
  )
}
