// ui/src/pages/ValuePropositions.tsx
import { Fragment, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import type { PortfolioItem } from '../types'

export default function ValuePropositions() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: items = [], isLoading } = useQuery<PortfolioItem[]>({
    queryKey: ['portfolio-register', slug],
    queryFn: () => projectsApi.portfolioRegister(slug!),
    enabled: !!slug,
  })

  function toggleRow(id: string) {
    setExpandedId((prev) => (prev === id ? null : id))
  }

  function valueEstimateColour(v: string) {
    if (v === 'High') return 'text-brand-green'
    if (v === 'Medium') return 'text-amber-400'
    return 'text-slate-400'
  }

  if (isLoading) {
    return (
      <div className="p-6">
        <p className="text-sm text-slate-500">Loading…</p>
      </div>
    )
  }

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold text-slate-100 mb-1">Value Propositions</h2>
      <p className="text-slate-400 text-sm mb-6">Scored and ranked by the Portfolio Manager agent.</p>

      {items.length === 0 ? (
        <div className="bg-surface-card rounded-xl p-8 text-center max-w-lg">
          <p className="text-slate-300 text-sm font-medium mb-2">No value propositions yet</p>
          <p className="text-slate-500 text-xs leading-relaxed mb-4">
            The Portfolio Manager agent scores and ranks propositions after the Value Design crew
            completes. Run the pipeline from the Dashboard.
          </p>
          <button
            onClick={() => navigate(`/${slug}`)}
            className="px-4 py-2 bg-brand hover:bg-brand-dark text-white text-sm rounded"
          >
            Run Pipeline →
          </button>
        </div>
      ) : (
        <>
          <div className="mb-4 rounded-lg border border-amber-800/40 bg-amber-900/10 px-4 py-3 text-xs text-amber-400 leading-relaxed">
            Scoring dimensions: value impact, feasibility, strategic fit. Six Capitals scoring
            (IIRC framework + safety + performance) coming in a future sprint.
          </div>

          <div className="bg-surface-card rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-xs text-slate-500 uppercase tracking-wide">
                  <th className="text-left px-4 py-3 w-10">#</th>
                  <th className="text-left px-4 py-3 w-16">ID</th>
                  <th className="text-left px-4 py-3">Title</th>
                  <th className="text-left px-4 py-3 w-20">Est.</th>
                  <th className="text-right px-4 py-3 w-16">Value</th>
                  <th className="text-right px-4 py-3 w-16">Feas.</th>
                  <th className="text-right px-4 py-3 w-20">Strat. Fit</th>
                  <th className="text-right px-4 py-3 w-16">Total</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <Fragment key={item.id}>
                    <tr
                      onClick={() => toggleRow(item.id)}
                      className="border-b border-slate-800 hover:bg-slate-800/40 cursor-pointer transition-colors"
                    >
                      <td className="px-4 py-3 text-slate-500">{item.rank}</td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400">{item.id}</td>
                      <td className="px-4 py-3 text-slate-200 font-medium">{item.title}</td>
                      <td className={`px-4 py-3 text-xs font-semibold ${valueEstimateColour(item.value_estimate)}`}>
                        {item.value_estimate}
                      </td>
                      <td className="px-4 py-3 text-right text-slate-300">{item.score_value.toFixed(1)}</td>
                      <td className="px-4 py-3 text-right text-slate-300">{item.score_feasibility.toFixed(1)}</td>
                      <td className="px-4 py-3 text-right text-slate-300">{item.score_strategic_fit.toFixed(1)}</td>
                      <td className="px-4 py-3 text-right font-semibold text-brand">{item.total_score.toFixed(1)}</td>
                    </tr>
                    {expandedId === item.id && (
                      <tr key={`${item.id}-detail`} className="border-b border-slate-800 bg-slate-900/40">
                        <td colSpan={8} className="px-6 py-4 space-y-3">
                          <p className="text-sm text-slate-300 leading-relaxed">{item.change_articulation}</p>
                          <p className="text-xs text-slate-500">
                            <span className="font-semibold text-slate-400">Stakeholders: </span>
                            {item.impacted_stakeholder_groups.join(', ')}
                          </p>
                          <div className="grid grid-cols-3 gap-4 text-xs text-slate-500">
                            <div>
                              <span className="font-semibold text-slate-400">Value: </span>
                              {item.score_value_rationale}
                            </div>
                            <div>
                              <span className="font-semibold text-slate-400">Feasibility: </span>
                              {item.score_feasibility_rationale}
                            </div>
                            <div>
                              <span className="font-semibold text-slate-400">Strategic fit: </span>
                              {item.score_strategic_fit_rationale}
                            </div>
                          </div>
                          <p className="text-xs text-slate-600">
                            Weights — Value ×{item.weights_used.value}, Feasibility ×{item.weights_used.feasibility}, Strategic Fit ×{item.weights_used.strategic_fit}
                          </p>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
