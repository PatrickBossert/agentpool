import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { downloadOutput } from '../utils/download'
import type { FinancialSummary, AgentOutput } from '../types'

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtCurrency(v: number | null): string {
  if (v === null || v === undefined) return '-'
  const abs = Math.abs(v)
  if (abs >= 1_000_000) return `£${(v / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `£${(v / 1_000).toFixed(0)}k`
  return `£${v.toFixed(0)}`
}

function fmtPercent(v: number | null): string {
  if (v === null || v === undefined) return '-'
  return `${(v * 100).toFixed(1)}%`
}

// ── Sub-components ────────────────────────────────────────────────────────────

function MetricCard({ label, value, colour }: { label: string; value: string; colour: string }) {
  return (
    <div className="bg-surface rounded-lg p-3">
      <p className="text-xs text-gray-400 uppercase tracking-widest mb-1">{label}</p>
      <p className="text-xl font-bold" style={{ color: colour }}>
        {value}
      </p>
    </div>
  )
}

const OUTPUT_META: Record<string, { label: string; colour: string }> = {
  docx: { label: 'Business Plan', colour: '#3b82f6' },
  pptx: { label: 'Executive Presentation', colour: '#f59e0b' },
  excel: { label: 'Cost/Benefit Model', colour: '#22c55e' },
}

function OutputCard({ output, slug, token }: { output: AgentOutput; slug: string; token: string }) {
  const meta = OUTPUT_META[output.output_type] ?? { label: output.output_type, colour: '#6366f1' }
  const ext = output.output_type.toUpperCase()
  const filename = output.file_path.split('/').pop() ?? output.output_type
  return (
    <div className="bg-surface-card rounded-xl px-4 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span
          className="rounded px-2 py-0.5 text-xs font-bold tracking-wide"
          style={{ background: `${meta.colour}20`, color: meta.colour }}
        >
          {ext}
        </span>
        <div>
          <p className="text-sm text-gray-900 font-medium">{meta.label}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            {output.agent_name} · v{output.version} · {output.review_status}
          </p>
        </div>
      </div>
      <button
        onClick={() => downloadOutput(slug, output.id, filename, token).catch(console.error)}
        className="text-xs text-brand hover:text-brand-dark border border-brand/20 rounded px-2.5 py-1.5 transition-colors"
      >
        <span className="flex items-center gap-1"><Download size={12} />Download</span>
      </button>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function BusinessPlan() {
  const { slug } = useParams<{ slug: string }>()
  const { token } = useAuth()

  const { data: summary } = useQuery<FinancialSummary>({
    queryKey: ['financial-summary', slug],
    queryFn: () => projectsApi.financialSummary(slug!),
    enabled: !!slug,
    retry: false,
  })

  const { data: outputs = [] } = useQuery<AgentOutput[]>({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.outputs(slug!),
    enabled: !!slug,
  })

  const docxOutput = outputs.find((o) => o.output_type === 'docx') ?? null
  const pptxOutput = outputs.find((o) => o.output_type === 'pptx') ?? null
  const excelOutput = outputs.find((o) => o.output_type === 'excel') ?? null
  const hasOutputs = !!(docxOutput || pptxOutput || excelOutput)

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-gray-900">Business Plan</h2>

      {summary && (
        <section>
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">
            Financial Summary
          </h3>
          <div className="grid grid-cols-3 gap-3">
            <MetricCard label="NPV" value={fmtCurrency(summary.npv)} colour="#22c55e" />
            <MetricCard label="IRR" value={fmtPercent(summary.irr)} colour="#22c55e" />
            <MetricCard
              label="Payback Period"
              value={summary.payback_period ?? '-'}
              colour="#f1f5f9"
            />
            <MetricCard
              label="Total Investment"
              value={fmtCurrency(summary.total_investment)}
              colour="#f59e0b"
            />
            <MetricCard
              label="Total Benefits"
              value={fmtCurrency(summary.total_benefits)}
              colour="#22c55e"
            />
            <MetricCard
              label="Max Borrowing"
              value={fmtCurrency(summary.max_borrowing)}
              colour="#f87171"
            />
          </div>
        </section>
      )}

      <section>
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">
          Outputs
        </h3>
        {!hasOutputs && (
          <p className="text-sm text-gray-400">
            Business plan outputs will appear here once the Business Plan Generator has run.
          </p>
        )}
        <div className="space-y-2">
          {docxOutput && <OutputCard output={docxOutput} slug={slug!} token={token!} />}
          {pptxOutput && <OutputCard output={pptxOutput} slug={slug!} token={token!} />}
          {excelOutput && <OutputCard output={excelOutput} slug={slug!} token={token!} />}
        </div>
      </section>
    </div>
  )
}
