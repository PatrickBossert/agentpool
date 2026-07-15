// ui/src/pages/ValuePropositions.tsx
import { Fragment, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
  ResponsiveContainer,
} from 'recharts'
import { projectsApi } from '../api/endpoints'
import type { PortfolioItem } from '../types'

const DIMENSIONS = [
  { key: 'financial' as const,           label: 'Financial' },
  { key: 'manufactured' as const,        label: 'Manufactured' },
  { key: 'intellectual' as const,        label: 'Intellectual' },
  { key: 'human' as const,               label: 'Human' },
  { key: 'social_relationship' as const, label: 'Social' },
  { key: 'natural' as const,             label: 'Natural' },
  { key: 'safety' as const,              label: 'Safety' },
  { key: 'performance' as const,         label: 'Performance' },
]

type DimKey = typeof DIMENSIONS[number]['key']

function getScore(item: PortfolioItem, key: DimKey): number {
  const map: Record<DimKey, number> = {
    financial: item.score_financial,
    manufactured: item.score_manufactured,
    intellectual: item.score_intellectual,
    human: item.score_human,
    social_relationship: item.score_social_relationship,
    natural: item.score_natural,
    safety: item.score_safety,
    performance: item.score_performance,
  }
  return map[key]
}

function getUnit(item: PortfolioItem, key: DimKey): string {
  const map: Record<DimKey, string> = {
    financial: item.score_financial_unit,
    manufactured: item.score_manufactured_unit,
    intellectual: item.score_intellectual_unit,
    human: item.score_human_unit,
    social_relationship: item.score_social_relationship_unit,
    natural: item.score_natural_unit,
    safety: item.score_safety_unit,
    performance: item.score_performance_unit,
  }
  return map[key]
}

function getRationale(item: PortfolioItem, key: DimKey): string {
  const map: Record<DimKey, string> = {
    financial: item.score_financial_rationale,
    manufactured: item.score_manufactured_rationale,
    intellectual: item.score_intellectual_rationale,
    human: item.score_human_rationale,
    social_relationship: item.score_social_relationship_rationale,
    natural: item.score_natural_rationale,
    safety: item.score_safety_rationale,
    performance: item.score_performance_rationale,
  }
  return map[key]
}

function radarData(item: PortfolioItem) {
  return DIMENSIONS.map(({ key, label }) => ({
    dimension: label,
    score: getScore(item, key),
    neutral: 5,
  }))
}

function valueEstimateColour(v: string) {
  if (v === 'High') return 'text-brand-green'
  if (v === 'Medium') return 'text-amber-400'
  return 'text-gray-400'
}

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

  if (isLoading) {
    return (
      <div className="p-6">
        <p className="text-sm text-gray-400">Loading…</p>
      </div>
    )
  }

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-1">Value Propositions</h2>
      <p className="text-gray-500 text-sm mb-6">Scored and ranked by the Portfolio Manager agent.</p>

      {items.length === 0 ? (
        <div className="bg-surface-card rounded-xl p-8 text-center max-w-lg">
          <p className="text-gray-700 text-sm font-medium mb-2">No value propositions yet</p>
          <p className="text-gray-400 text-xs leading-relaxed mb-4">
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
        <div className="bg-surface-card rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-xs text-gray-500 uppercase tracking-wide">
                <th className="text-left px-4 py-3 w-10">#</th>
                <th className="text-left px-4 py-3 w-16">ID</th>
                <th className="text-left px-4 py-3">Title</th>
                <th className="text-left px-4 py-3 w-20">Est.</th>
                <th className="text-right px-4 py-3 w-16">Total</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <Fragment key={item.id}>
                  <tr
                    onClick={() => toggleRow(item.id)}
                    className="border-b border-gray-200 hover:bg-gray-50 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-3 text-gray-400">{item.rank}</td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-500">{item.id}</td>
                    <td className="px-4 py-3 text-gray-900 font-medium">{item.title}</td>
                    <td className={`px-4 py-3 text-xs font-semibold ${valueEstimateColour(item.value_estimate)}`}>
                      {item.value_estimate}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold text-brand">
                      {item.total_score.toFixed(1)}
                    </td>
                  </tr>
                  {expandedId === item.id && (
                    <tr key={`${item.id}-detail`} className="border-b border-gray-200 bg-gray-50">
                      <td colSpan={5} className="px-6 py-4">
                        <p className="text-sm text-gray-700 leading-relaxed mb-4">
                          {item.change_articulation}
                        </p>
                        <p className="text-xs text-gray-500 mb-4">
                          <span className="font-semibold text-gray-600">Stakeholders: </span>
                          {item.impacted_stakeholder_groups.join(', ')}
                        </p>
                        <div className="flex gap-6">
                          <div className="w-56 shrink-0">
                            <ResponsiveContainer width="100%" height={220}>
                              <RadarChart data={radarData(item)}>
                                <PolarGrid stroke="#334155" />
                                <PolarAngleAxis
                                  dataKey="dimension"
                                  tick={{ fill: '#94a3b8', fontSize: 10 }}
                                />
                                <Radar
                                  name="neutral"
                                  dataKey="neutral"
                                  stroke="#475569"
                                  strokeDasharray="3 3"
                                  fill="none"
                                  dot={false}
                                />
                                <Radar
                                  name="score"
                                  dataKey="score"
                                  stroke="#14b8a6"
                                  fill="#14b8a6"
                                  fillOpacity={0.3}
                                  dot={false}
                                />
                              </RadarChart>
                            </ResponsiveContainer>
                          </div>
                          <div className="flex-1 space-y-2">
                            {DIMENSIONS.map(({ key, label }) => (
                              <div key={key} className="flex gap-2 text-xs">
                                <span className="w-24 shrink-0 font-semibold text-gray-600">
                                  {label}
                                </span>
                                <span className="w-8 shrink-0 text-center font-mono text-brand">
                                  {getScore(item, key).toFixed(1)}
                                </span>
                                <span className="text-gray-500 leading-relaxed">
                                  ({getUnit(item, key)}) - {getRationale(item, key)}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                        <p className="text-xs text-gray-400 mt-4">
                          Weights - Financial ×{item.weights_used.financial}, Natural ×{item.weights_used.natural}, Safety ×{item.weights_used.safety}, Performance ×{item.weights_used.performance}, Manufactured ×{item.weights_used.manufactured}, Intellectual ×{item.weights_used.intellectual}, Human ×{item.weights_used.human}, Social ×{item.weights_used.social_relationship}
                        </p>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
