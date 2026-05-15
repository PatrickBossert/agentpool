// ui/src/pages/Report.tsx
import React, { useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
  ResponsiveContainer,
} from 'recharts'
import { projectsApi } from '../api/endpoints'
import type { PortfolioItem, Initiative, CostEstimate, AgentOutput } from '../types'
import './Report.css'

// ── Constants ─────────────────────────────────────────────────────────────────

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

const DELIVERABLE_TYPES: Record<string, string> = {
  docx: 'Business Plan',
  pptx: 'Executive Presentation',
  excel: 'Cost/Benefit Financial Model',
}

// ── Formatters ────────────────────────────────────────────────────────────────

function fmtCurrency(v: number | null): string {
  if (v === null || v === undefined) return '—'
  const abs = Math.abs(v)
  if (abs >= 1_000_000) return `£${(v / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `£${(v / 1_000).toFixed(0)}k`
  return `£${v.toFixed(0)}`
}

function fmtPercent(v: number | null): string {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function fmtCostRange(c: CostEstimate): string {
  return `${fmtCurrency(c.low)} – ${fmtCurrency(c.high)}`
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
}

function slugToTitle(slug: string): string {
  return slug.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

// ── Radar helpers ─────────────────────────────────────────────────────────────

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

function radarData(item: PortfolioItem) {
  return DIMENSIONS.map(({ key, label }) => ({
    dimension: label,
    score: getScore(item, key),
    neutral: 5,
  }))
}

// ── Sub-sections ──────────────────────────────────────────────────────────────

function CoverPage({ slug, sector }: { slug: string; sector: string }) {
  return (
    <div className="report-cover">
      <p className="text-sm font-mono uppercase tracking-widest mb-4" style={{ color: '#19d4e8' }}>
        Digital Modernisation Strategy
      </p>
      <h1 className="text-5xl font-bold mb-3 print:text-4xl print:text-black">
        {slugToTitle(slug)}
      </h1>
      <p className="text-xs font-mono text-slate-600 mb-1 print:text-slate-400">{slug}</p>
      <p className="text-xl mb-2 text-slate-400 print:text-slate-600">{sector}</p>
      <p className="text-sm text-slate-500 mt-8 print:text-slate-500">
        Generated {new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}
      </p>
      <p className="text-xs text-slate-600 mt-2 print:text-slate-400">Prepared by FutureMomentum</p>
    </div>
  )
}

function ValuePropositionsSection({ items }: { items: PortfolioItem[] }) {
  if (items.length === 0) {
    return (
      <div className="report-section">
        <h2 className="report-section-title">Value Propositions</h2>
        <p className="text-slate-500 text-sm">No value propositions generated yet.</p>
      </div>
    )
  }
  return (
    <div className="report-section">
      <h2 className="report-section-title">Value Propositions</h2>
      <div className="space-y-8">
        {items.map((item) => (
          <div key={item.id} className="border border-slate-700 rounded-xl p-4 print:border-slate-200">
            <div className="flex items-start justify-between mb-2">
              <h3 className="text-base font-semibold text-slate-100 print:text-black">
                {item.rank}. {item.title}
              </h3>
              <span className="text-xs font-mono text-slate-400 print:text-slate-500">
                Score {item.total_score.toFixed(1)}
              </span>
            </div>
            <p className="text-sm text-slate-400 mb-4 print:text-slate-600">{item.change_articulation}</p>
            <ResponsiveContainer width="100%" height={180}>
              <RadarChart data={radarData(item)}>
                <PolarGrid stroke="#334155" />
                <PolarAngleAxis dataKey="dimension" tick={{ fill: '#94a3b8', fontSize: 9 }} />
                <Radar name="neutral" dataKey="neutral" stroke="#475569" strokeDasharray="3 3" fill="none" dot={false} />
                <Radar name="score" dataKey="score" stroke="#19d4e8" fill="#19d4e8" fillOpacity={0.25} dot={false} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        ))}
      </div>
    </div>
  )
}

function InitiativeRegisterSection({ initiatives }: { initiatives: Initiative[] }) {
  if (initiatives.length === 0) {
    return (
      <div className="report-section">
        <h2 className="report-section-title">Initiative Register</h2>
        <p className="text-slate-500 text-sm">No initiatives generated yet.</p>
      </div>
    )
  }

  // Group by first value stream (or 'Unassigned')
  const groups: Record<string, Initiative[]> = {}
  for (const init of initiatives) {
    const key = init.value_streams && init.value_streams.length > 0 ? init.value_streams[0] : 'Unassigned'
    groups[key] = groups[key] ?? []
    groups[key].push(init)
  }

  return (
    <div className="report-section">
      <h2 className="report-section-title">Initiative Register</h2>
      <table className="report-table">
        <thead>
          <tr>
            <th>Initiative</th>
            <th>Type</th>
            <th>Cost Estimate</th>
            <th>Period</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(groups).map(([vs, inits]) => (
            <React.Fragment key={`group-${vs}`}>
              <tr className="group-header">
                <td colSpan={4}>{vs}</td>
              </tr>
              {inits.map((init) => (
                <tr key={init.id}>
                  <td>
                    <p className="font-medium text-slate-100 print:text-black">{init.title}</p>
                    <p className="text-slate-500 text-xs mt-0.5 print:text-slate-500 line-clamp-2">
                      {init.description}
                    </p>
                  </td>
                  <td>
                    <span className="capitalize">{init.initiative_type.replace('_', ' ')}</span>
                  </td>
                  <td>{fmtCostRange(init.cost_estimate)}</td>
                  <td>{init.period ?? '—'}</td>
                </tr>
              ))}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function FinancialSummarySection({ summary }: { summary: { npv: number | null; irr: number | null; payback_period: string | null; max_borrowing: number | null; total_investment: number | null; total_benefits: number | null } | null }) {
  const metrics = [
    { label: 'NPV', value: fmtCurrency(summary?.npv ?? null), colour: '#19d4e8' },
    { label: 'IRR', value: fmtPercent(summary?.irr ?? null), colour: '#19d4e8' },
    { label: 'Payback Period', value: summary?.payback_period ?? '—', colour: '#94a3b8' },
    { label: 'Total Investment', value: fmtCurrency(summary?.total_investment ?? null), colour: '#f87171' },
    { label: 'Total Benefits', value: fmtCurrency(summary?.total_benefits ?? null), colour: '#47c247' },
    { label: 'Max Borrowing', value: fmtCurrency(summary?.max_borrowing ?? null), colour: '#f59e0b' },
  ]

  return (
    <div className="report-section">
      <h2 className="report-section-title">Financial Summary</h2>
      <div className="report-metrics-grid">
        {metrics.map(({ label, value, colour }) => (
          <div key={label} className="report-metric-card">
            <p className="text-xs uppercase tracking-widest text-slate-500 mb-1 print:text-slate-400">{label}</p>
            <p className="text-2xl font-bold print:text-xl" style={{ color: colour }}>{value}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function DeliverablesSection({ outputs }: { outputs: AgentOutput[] }) {
  const deliverables = outputs.filter((o) => DELIVERABLE_TYPES[o.output_type])

  return (
    <div className="report-section">
      <h2 className="report-section-title">Deliverables</h2>
      {deliverables.length === 0 ? (
        <p className="text-slate-500 text-sm">No deliverable files generated yet.</p>
      ) : (
        <table className="report-table">
          <thead>
            <tr>
              <th>Document</th>
              <th>Format</th>
              <th>Version</th>
              <th>Generated</th>
            </tr>
          </thead>
          <tbody>
            {deliverables.map((o) => (
              <tr key={o.id}>
                <td className="text-slate-100 print:text-black">{DELIVERABLE_TYPES[o.output_type]}</td>
                <td className="uppercase font-mono text-xs text-slate-400">{o.output_type}</td>
                <td>v{o.version}</td>
                <td className="text-slate-400 print:text-slate-600">{fmtDate(o.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="text-xs text-slate-600 mt-4 print:text-slate-400">
        Full documents available in the FutureMomentum Documents tab for this project.
      </p>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Report() {
  const { slug } = useParams<{ slug: string }>()

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug!),
    enabled: !!slug,
  })

  const { data: financialSummary } = useQuery({
    queryKey: ['financial-summary', slug],
    queryFn: () => projectsApi.financialSummary(slug!),
    enabled: !!slug,
  })

  const { data: propositions = [] } = useQuery({
    queryKey: ['portfolio-register', slug],
    queryFn: () => projectsApi.portfolioRegister(slug!),
    enabled: !!slug,
  })

  const { data: roadmapData } = useQuery({
    queryKey: ['roadmap-data', slug],
    queryFn: () => projectsApi.roadmapData(slug!),
    enabled: !!slug,
  })

  const { data: outputs = [] } = useQuery({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.outputs(slug!),
    enabled: !!slug,
  })

  const allLoaded = settings !== undefined && financialSummary !== undefined && roadmapData !== undefined

  // Auto-trigger print dialog once all data has loaded
  useEffect(() => {
    if (!allLoaded) return
    const timer = setTimeout(() => window.print(), 300)
    return () => clearTimeout(timer)
  }, [allLoaded])

  const initiatives: Initiative[] = roadmapData?.initiatives ?? []

  return (
    <div className="report-root">
      <button className="report-print-btn" onClick={() => window.print()}>
        Print / Save as PDF
      </button>

      <CoverPage slug={slug ?? ''} sector={settings?.sector ?? ''} />
      <ValuePropositionsSection items={propositions} />
      <InitiativeRegisterSection initiatives={initiatives} />
      <FinancialSummarySection summary={financialSummary ?? null} />
      <DeliverablesSection outputs={outputs} />
    </div>
  )
}
