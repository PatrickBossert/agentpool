// ui/src/pages/ValueChain.tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'

export default function ValueChain() {
  const { slug } = useParams<{ slug: string }>()

  const { data: outputs = [], isLoading } = useQuery({
    queryKey: ['value-chain', slug],
    queryFn: () => projectsApi.valueChain(slug!),
    enabled: !!slug,
  })

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold text-slate-100 mb-4">Value Chain</h2>

      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}

      {!isLoading && outputs.length === 0 && (
        <div className="bg-surface-card rounded-xl p-8 text-center">
          <p className="text-slate-400 text-sm">
            Awaiting Value Chain Mapper output.
          </p>
          <p className="text-slate-600 text-xs mt-2">
            Run the Discovery crew to generate the value chain analysis.
          </p>
        </div>
      )}

      {outputs.length > 0 && (
        <div className="space-y-3">
          {outputs.map((output) => (
            <div key={output.id} className="bg-surface-card rounded-lg px-4 py-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-slate-200">{output.agent_name}</span>
                <span className="text-xs text-slate-500">v{output.version} · {output.review_status}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
