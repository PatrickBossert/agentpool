// ui/src/components/ReviewQueue.tsx
import type { AgentOutput } from '../types'
import { projectsApi, commitsApi } from '../api/endpoints'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CREW_LABELS } from './agentStatus'
import CommitControl from './CommitControl'

interface Props {
  slug: string
  outputs: AgentOutput[]
}

// A single crew awaiting commit. Its outstanding-change count is its own query so that
// one crew's fetch does not block the others from rendering.
function CommitRow({
  slug,
  crew,
  onCommit,
}: {
  slug: string
  crew: string
  onCommit: (crewName: string) => Promise<void>
}) {
  const { data: changeCount = 0 } = useQuery({
    queryKey: ['crew-changes', slug, crew],
    queryFn: () => commitsApi.changeCount(slug, crew),
  })

  return (
    <div className="flex items-center justify-between bg-white border border-gray-200 rounded-lg px-4 py-3">
      <div>
        <p className="text-sm font-medium text-gray-900">{CREW_LABELS[crew] ?? crew}</p>
      </div>
      <CommitControl crewName={crew} changeCount={changeCount} onCommit={onCommit} />
    </div>
  )
}

export default function ReviewQueue({ slug, outputs }: Props) {
  const qc = useQueryClient()
  const pending = outputs.filter((o) => o.review_status === 'pending')

  const { data: readiness = {} } = useQuery({
    queryKey: ['crew-readiness', slug],
    queryFn: () => commitsApi.readiness(slug),
  })
  const { data: committed = [] } = useQuery({
    queryKey: ['committed-crews', slug],
    queryFn: () => commitsApi.committedCrews(slug),
  })

  // Crews whose upstream is ready but not yet committed - those are the ones whose
  // turn it is for an approver to release.
  const awaitingCommit = Object.entries(readiness)
    .filter(([crew, r]) => r.ready && !committed.includes(crew))
    .map(([crew]) => crew)

  async function decide(outputId: number, decision: string) {
    await projectsApi.review(slug, outputId, decision)
    qc.invalidateQueries({ queryKey: ['outputs', slug] })
  }

  async function commit(crewName: string) {
    await commitsApi.create(slug, crewName)
    // Both the board's Ready states and this list derive from these two queries.
    await qc.invalidateQueries({ queryKey: ['crew-readiness', slug] })
    await qc.invalidateQueries({ queryKey: ['committed-crews', slug] })
  }

  if (pending.length === 0 && awaitingCommit.length === 0) {
    return <p className="text-sm text-gray-400">No items pending review.</p>
  }

  return (
    <div className="space-y-4">
      {pending.length > 0 && (
        <div className="space-y-2">
          {pending.map((o) => (
            <div
              key={o.id}
              className="flex items-center justify-between bg-white border border-gray-200 rounded-lg px-4 py-3"
            >
              <div>
                <p className="text-sm font-medium text-gray-900">{o.agent_name}</p>
                <p className="text-xs text-gray-400">{o.output_type} · v{o.version}</p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => decide(o.id, 'approved')}
                  className="text-xs bg-emerald-100 hover:bg-emerald-200 text-emerald-800 border border-emerald-200 px-3 py-1 rounded transition-colors"
                >
                  Approve
                </button>
                <button
                  onClick={() => decide(o.id, 'changes_requested')}
                  className="text-xs bg-red-100 hover:bg-red-200 text-red-800 border border-red-200 px-3 py-1 rounded transition-colors"
                >
                  Request changes
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      {awaitingCommit.length > 0 && (
        <div className="space-y-2">
          {awaitingCommit.map((crew) => (
            <CommitRow key={crew} slug={slug} crew={crew} onCommit={commit} />
          ))}
        </div>
      )}
    </div>
  )
}
