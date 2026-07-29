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

// A single crew whose readiness qualifies it for a commit row. Its outstanding-change
// count is its own query so that one crew's fetch does not block the others from
// rendering.
//
// A crew that has never been committed always shows a row - it is waiting on its first
// release. A crew that has already been committed only shows again once it has
// accumulated new changes since that commit: repeat commits are allowed (the backend
// inserts a fresh approval_commits row on every call, with no uniqueness constraint),
// but there is nothing to commit a second time until something has changed.
export function CommitRow({
  slug,
  crew,
  committed,
  onCommit,
}: {
  slug: string
  crew: string
  committed: boolean
  onCommit: (crewName: string) => Promise<void>
}) {
  const { data: changeCount = 0 } = useQuery({
    queryKey: ['crew-changes', slug, crew],
    queryFn: () => commitsApi.changeCount(slug, crew),
  })

  if (committed && changeCount === 0) {
    return null
  }

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

  // Crews whose upstream is ready - candidates for a commit row. Whether a given crew
  // actually needs one (never committed, or committed but with new changes since) is
  // decided inside CommitRow itself, which is the only place that knows the change count.
  const readyCrews = Object.entries(readiness)
    .filter(([, r]) => r.ready)
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

  if (pending.length === 0 && readyCrews.length === 0) {
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
      {readyCrews.length > 0 && (
        <div className="space-y-2">
          {readyCrews.map((crew) => (
            <CommitRow
              key={crew}
              slug={slug}
              crew={crew}
              committed={committed.includes(crew)}
              onCommit={commit}
            />
          ))}
        </div>
      )}
    </div>
  )
}
