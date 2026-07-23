// ui/src/pages/Dashboard.tsx
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { PauseCircle, Trash2, ArrowRight, AlertTriangle, Clock, CalendarDays } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { projectsApi, milestonesApi } from '../api/endpoints'
import type { Milestone } from '../types'
import CrewCarousel from '../components/CrewCarousel'
import AgentDetailPanel from '../components/AgentDetailPanel'
import ReviewDialog from '../components/ReviewDialog'
import RerunDialog from '../components/RerunDialog'
import { useWebSocket } from '../hooks/useWebSocket'
import { CREW_ORDER, CREW_AGENTS, CREW_AGENT_NAMES, CREW_DOWNSTREAM } from '../components/agentStatus'
import type { CrewRun, HumanReview, AgentOutput } from '../types'

// ── Review queue sidebar ───────────────────────────────────────────────────────

const CREW_LABEL: Record<string, string> = {
  discovery_mapping:      'Value Chain Mapper',
  assessment_design:      'Assessment Design',
  discovery:              'Discovery',
  stakeholder_management: 'Stakeholder Management',
  discovery_interviews:   'Interview Synthesis',
  value_design:           'Value Design',
  architecture:           'Architecture',
  delivery:               'Delivery Planning',
  business_plan:          'Business Plan',
}

function ReviewPanel({ slug, hitlReviews, outputs }: {
  slug: string
  hitlReviews: HumanReview[]
  outputs: AgentOutput[]
}) {
  const qc = useQueryClient()
  const [openReview, setOpenReview] = useState<HumanReview | null>(null)

  async function deleteReview(reviewId: number) {
    await projectsApi.deleteReview(slug, reviewId)
    qc.invalidateQueries({ queryKey: ['reviews', slug] })
  }

  return (
    <>
      <div className="w-60 flex-shrink-0 border-l border-gray-200 bg-white flex flex-col overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2 flex-shrink-0">
          <p className="text-xs font-bold text-gray-500 uppercase tracking-widest">Review Queue</p>
          {hitlReviews.length > 0 && (
            <span className="bg-amber-500 text-white text-xs font-bold rounded-full px-1.5 leading-4 min-w-[18px] text-center">
              {hitlReviews.length}
            </span>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {hitlReviews.length === 0 && (
            <p className="text-xs text-gray-400 text-center py-8">No pending reviews</p>
          )}
          {hitlReviews.map(r => {
            const label = r.crew_name ? (CREW_LABEL[r.crew_name] ?? r.crew_name) : 'Crew'
            const firstLine = r.prompt.trim().split('\n').filter(Boolean)[0] ?? ''
            const preview = firstLine.length > 60 ? firstLine.slice(0, 60) + '…' : firstLine
            return (
              <div key={r.id} className="group relative rounded-lg border border-amber-200 bg-amber-50 hover:bg-amber-100 transition-colors">
                <button
                  onClick={() => setOpenReview(r)}
                  className="w-full text-left p-3 space-y-1"
                >
                  <div className="flex items-center gap-1.5 pr-5">
                    <PauseCircle size={12} className="text-amber-500 flex-shrink-0" />
                    <p className="text-[10px] font-bold text-amber-700 uppercase tracking-wider truncate">{label}</p>
                  </div>
                  <p className="text-xs text-gray-600 leading-relaxed">{preview}</p>
                  <p className="text-[10px] text-amber-600 font-medium flex items-center gap-1">Click to review <ArrowRight size={10} /></p>
                </button>
                <button
                  onClick={() => deleteReview(r.id)}
                  title="Delete orphaned review"
                  className="absolute top-2 right-2 p-1 rounded text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            )
          })}
        </div>
      </div>

      {openReview && (
        <ReviewDialog
          slug={slug}
          review={openReview}
          outputs={outputs}
          onClose={() => setOpenReview(null)}
        />
      )}
    </>
  )
}

// ── Dashboard ──────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const { slug } = useParams<{ slug?: string }>()
  const navigate = useNavigate()
  const logs = useWebSocket(slug)

  const [selectedCrew, setSelectedCrew] = useState<string>('PAM')

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

  const { data: hitlReviews = [] } = useQuery({
    queryKey: ['reviews', slug],
    queryFn: () => projectsApi.listReviews(slug!),
    enabled: !!slug,
    refetchInterval: 5_000,
  })

  const { data: milestones = [] } = useQuery<Milestone[]>({
    queryKey: ['milestones', slug],
    queryFn: () => milestonesApi.list(slug!),
    enabled: !!slug,
    refetchInterval: 60_000,
  })

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug!),
    enabled: !!slug,
  })

  const runMutation = useMutation({
    mutationFn: () => projectsApi.orchestrate(slug!),
    onSuccess: (data) => navigate(`/${slug}/runs/${data.orchestration_run_id}`),
  })

  const [runningCrew, setRunningCrew] = useState<string | null>(null)
  async function handleRunCrew(crewName: string) {
    setRunningCrew(crewName)
    try { await projectsApi.runCrew(slug!, crewName) }
    finally { setRunningCrew(null) }
  }

  const [rerunCrew, setRerunCrew] = useState<string | null>(null)

  // Latest version of each displayable output type for the re-run crew.
  // CREW_AGENTS has display names ('Value Chain Mapper') but agent_outputs.agent_name
  // is stored as snake_case ('value_chain_mapper') — convert to match.
  const INTERNAL_TYPES = new Set(['value_chain_tree', 'value_chain_registry', 'value_chain_summary', 'state'])
  const rerunCrewOutputs: AgentOutput[] = (() => {
    if (!rerunCrew) return []
    const agentSnakeNames = new Set(
      (CREW_AGENTS[rerunCrew] ?? []).map(n => n.toLowerCase().replace(/\s+/g, '_'))
    )
    const latest = new Map<string, AgentOutput>()
    for (const o of outputs) {
      if (!agentSnakeNames.has(o.agent_name)) continue
      if (INTERNAL_TYPES.has(o.output_type) || o.output_type.includes('_tree') || o.output_type.includes('_registry')) continue
      const prev = latest.get(o.output_type)
      if (!prev || o.version > prev.version) latest.set(o.output_type, o)
    }
    return Array.from(latest.values())
  })()

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
  const pendingReviewCount = hitlReviews.length

  // Canonical run per crew (newest wins)
  const runMap = new Map<string, CrewRun>()
  for (const r of crewRuns) if (!runMap.has(r.crew_name)) runMap.set(r.crew_name, r)
  const selectedCrewRun = runMap.get(selectedCrew)

  // Crews whose current outputs were all rejected — show as idle, not completed
  const rejectedCrews = new Set<string>(
    CREW_ORDER.filter(crew => {
      const agentNames = new Set(CREW_AGENT_NAMES[crew] ?? [])
      if (!agentNames.size) return false
      const crewOutputs = outputs.filter(o => o.is_current && agentNames.has(o.agent_name))
      return crewOutputs.length > 0 && crewOutputs.every(o => o.review_status === 'rejected')
    })
  )

  return (
    <div className="flex flex-col flex-1 min-h-0">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-gray-100 bg-white flex-shrink-0 flex-wrap">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-gray-900">{slug}</h2>
          {pendingReviewCount > 0 && (
            <span className="text-[10px] font-bold bg-amber-100 text-amber-700 border border-amber-200 rounded-full px-2 py-0.5">
              {pendingReviewCount} review{pendingReviewCount !== 1 ? 's' : ''} pending
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => window.open(`/dashboard/${slug}/report`, '_blank')}
            className="text-xs px-2.5 py-1 rounded-lg bg-white border border-gray-200 text-gray-600 hover:text-gray-900 hover:border-gray-400 transition-colors"
          >
            Export Report
          </button>
          {(orch?.status === 'completed' || orch?.status === 'failed') && (
            <button
              onClick={() => navigate(`/${slug}/runs/${orch.id}`)}
              className="text-xs text-teal-600 hover:text-teal-700 flex items-center gap-1"
            >
              View Last Run <ArrowRight size={12} />
            </button>
          )}
        </div>
      </div>

      {/* ── Main area: left column + full-height review panel ──────────────── */}
      <div className="flex flex-1 min-h-0">

        {/* Left column - carousel + detail */}
        <div className="flex flex-col flex-1 min-w-0 min-h-0">

          {/* Pipeline error banner */}
          {orch?.status === 'failed' && orch.error_detail && (
            <div className="mx-5 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 flex-shrink-0">
              <p className="text-xs font-bold text-red-700 uppercase tracking-widest mb-1">Pipeline error</p>
              <pre className="text-xs text-red-800 whitespace-pre-wrap break-all font-mono leading-relaxed max-h-24 overflow-y-auto">
                {orch.error_detail}
              </pre>
            </div>
          )}

          {/* Schedule strip */}
          {milestones.length > 0 && (() => {
            const todayStr = new Date().toISOString().slice(0, 10)
            const overdue = milestones.filter(m => m.status === 'pending' && m.due_date && m.due_date < todayStr)
            const next = milestones.find(m => m.status === 'pending' && m.due_date && m.due_date >= todayStr)
            if (!overdue.length && !next) return null
            const daysTo = next?.due_date
              ? Math.ceil((new Date(next.due_date).getTime() - new Date(todayStr).getTime()) / 86_400_000)
              : null
            return (
              <button
                onClick={() => navigate(`/${slug}/schedule`)}
                className="mx-5 mt-3 flex items-center gap-3 rounded-lg border px-3 py-2 text-left transition-colors flex-shrink-0 group
                  border-gray-100 bg-white hover:border-teal-200 hover:bg-teal-50/40"
              >
                <CalendarDays size={13} className="text-gray-400 group-hover:text-teal-500 flex-shrink-0" />
                {overdue.length > 0 && (
                  <span className="flex items-center gap-1 text-xs font-semibold text-red-600">
                    <AlertTriangle size={11} />
                    {overdue.length} overdue milestone{overdue.length !== 1 ? 's' : ''}
                  </span>
                )}
                {overdue.length > 0 && next && <span className="text-gray-200">|</span>}
                {next && (
                  <span className="flex items-center gap-1 text-xs text-gray-500">
                    <Clock size={11} className="flex-shrink-0" />
                    <span className="font-medium text-gray-700">{next.title}</span>
                    {daysTo !== null && (
                      <span className={daysTo <= 3 ? 'text-amber-600' : 'text-gray-400'}>
                        — {daysTo === 0 ? 'today' : daysTo === 1 ? 'tomorrow' : `${daysTo} days`}
                      </span>
                    )}
                  </span>
                )}
                <span className="ml-auto text-[10px] text-gray-300 group-hover:text-teal-400 flex items-center gap-0.5">
                  Schedule <ArrowRight size={10} />
                </span>
              </button>
            )
          })()}

          {/* Crew carousel */}
          <div className="px-5 pt-4 pb-1 flex-shrink-0">
            <CrewCarousel
              crewRuns={crewRuns}
              isPipelineActive={isPipelineActive}
              logs={logs}
              hitlReviews={hitlReviews}
              rejectedCrews={rejectedCrews}
              selectedCrew={selectedCrew}
              onSelectCrew={setSelectedCrew}
              onRunCrew={handleRunCrew}
              onRerunCrew={setRerunCrew}
              runningCrew={runningCrew}
              onRunPipeline={() => runMutation.mutate()}
              isPipelineStarting={runMutation.isPending}
              orchestrationStatus={orch?.status ?? null}
            />
          </div>

          {/* Detail panel */}
          <div className="flex flex-1 min-h-0 px-5 pb-5 pt-3">
            <AgentDetailPanel
              slug={slug}
              crewKey={selectedCrew}
              crewRun={selectedCrewRun}
              outputs={outputs}
              logs={logs}
              isPipelineActive={isPipelineActive}
              hitlReviews={hitlReviews}
              locale={settings?.locale}
            />
          </div>
        </div>

        {/* Review panel - spans full height below the header */}
        <ReviewPanel slug={slug} hitlReviews={hitlReviews} outputs={outputs} />
      </div>

      {/* Re-run dialog */}
      {rerunCrew && (
        <RerunDialog
          slug={slug}
          crewKey={rerunCrew}
          outputs={rerunCrewOutputs}
          downstream={CREW_DOWNSTREAM[rerunCrew] ?? []}
          onFreshRun={() => handleRunCrew(rerunCrew)}
          onClose={() => setRerunCrew(null)}
        />
      )}

    </div>
  )
}
