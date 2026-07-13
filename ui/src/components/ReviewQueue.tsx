// ui/src/components/ReviewQueue.tsx
import type { AgentOutput } from '../types'
import { projectsApi } from '../api/endpoints'
import { useQueryClient } from '@tanstack/react-query'

interface Props {
  slug: string
  outputs: AgentOutput[]
}

export default function ReviewQueue({ slug, outputs }: Props) {
  const qc = useQueryClient()
  const pending = outputs.filter((o) => o.review_status === 'pending')

  if (pending.length === 0) {
    return <p className="text-sm text-gray-400">No items pending review.</p>
  }

  async function decide(outputId: number, decision: string) {
    await projectsApi.review(slug, outputId, decision)
    qc.invalidateQueries({ queryKey: ['outputs', slug] })
  }

  return (
    <div className="space-y-2">
      {pending.map((o) => (
        <div
          key={o.id}
          className="flex items-center justify-between bg-surface-card rounded-lg px-4 py-3"
        >
          <div>
            <p className="text-sm font-medium text-gray-900">{o.agent_name}</p>
            <p className="text-xs text-gray-400">{o.output_type} · v{o.version}</p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => decide(o.id, 'approved')}
              className="text-xs bg-emerald-800 hover:bg-emerald-700 text-emerald-200 px-3 py-1 rounded transition-colors"
            >
              Approve
            </button>
            <button
              onClick={() => decide(o.id, 'changes_requested')}
              className="text-xs bg-red-900 hover:bg-red-800 text-red-200 px-3 py-1 rounded transition-colors"
            >
              Request changes
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
