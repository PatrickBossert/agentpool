// ui/src/components/PamReportView.tsx
import { useQuery } from '@tanstack/react-query'
import {
  CheckCircle2, XCircle, Clock, Loader2,
  Shield, AlertOctagon, CalendarDays, Users, FileText,
  Download, RefreshCw, ArrowRight, Circle, CheckCheck,
} from 'lucide-react'
import { pamReportApi, projectsApi, nonworkingApi } from '../api/endpoints'
import type { PamReport, PamReportMilestone, PamReportRisk, PamReportIssue, PamReportCrewStatus } from '../types'
import GanttReadOnly, { inferSchedule, daysBetween, todayStr } from './GanttReadOnly'
import { getPublicHolidays, buildExcludedDateSet, workingDaysBetween } from '../utils/holidays'

// ── RAG / status helpers ──────────────────────────────────────────────────────

const RAG_COLOURS = {
  red:   { bg: 'bg-red-500',   border: 'border-red-200',   text: 'text-red-700',   badge: 'bg-red-50 border-red-200 text-red-700' },
  amber: { bg: 'bg-amber-400', border: 'border-amber-200', text: 'text-amber-700', badge: 'bg-amber-50 border-amber-200 text-amber-700' },
  green: { bg: 'bg-green-500', border: 'border-green-200', text: 'text-green-700', badge: 'bg-green-50 border-green-200 text-green-700' },
}

const SEVERITY_COLOURS = {
  critical: 'bg-red-50 border-red-200 text-red-800',
  high:     'bg-amber-50 border-amber-200 text-amber-800',
  medium:   'bg-yellow-50 border-yellow-200 text-yellow-800',
  low:      'bg-gray-50 border-gray-200 text-gray-700',
}

const SEVERITY_DOT = {
  critical: 'bg-red-500',
  high:     'bg-amber-400',
  medium:   'bg-yellow-400',
  low:      'bg-gray-300',
}

const MS_RAG = {
  complete:    { label: 'Complete',    cls: 'bg-teal-50 border-teal-200 text-teal-700' },
  overdue:     { label: 'Overdue',     cls: 'bg-red-50 border-red-200 text-red-700' },
  due_soon:    { label: 'Due soon',    cls: 'bg-amber-50 border-amber-200 text-amber-700' },
  on_track:    { label: 'On track',    cls: 'bg-green-50 border-green-200 text-green-700' },
  unscheduled: { label: 'Unscheduled', cls: 'bg-gray-50 border-gray-200 text-gray-500' },
}

const MS_RAG_CIRCLE = {
  complete:    'bg-teal-500  border-teal-500  text-white',
  overdue:     'bg-red-500   border-red-500   text-white',
  due_soon:    'bg-amber-400 border-amber-400 text-white',
  on_track:    'bg-white     border-green-400 text-green-600',
  unscheduled: 'bg-white     border-gray-200  text-gray-400',
}

const MS_DELTA_CLS = {
  complete:    '',
  overdue:     'text-red-500',
  due_soon:    'text-amber-500',
  on_track:    'text-gray-400',
  unscheduled: 'text-gray-300',
}

const CREW_STATUS_COLOUR: Record<string, string> = {
  completed:   'text-teal-600',
  failed:      'text-red-500',
  running:     'text-blue-500',
  not_started: 'text-gray-300',
}

const CREW_STATUS_LABEL: Record<string, string> = {
  completed:   'Complete',
  failed:      'Failed',
  running:     'Running',
  not_started: 'Not started',
}

function fmt(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso.includes('T') ? iso : iso + 'T00:00:00').toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

// ── Print helper ──────────────────────────────────────────────────────────────

function esc(s: string | null | undefined): string {
  return (s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function printReport(report: PamReport) {
  const html = buildPrintHtml(report)
  const blob = new Blob([html], { type: 'text/html; charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const win = window.open(url, '_blank')
  // Revoke after the window has had time to load and print
  setTimeout(() => URL.revokeObjectURL(url), 30_000)
  if (!win) URL.revokeObjectURL(url)
}

function ragLabel(h: string) {
  return h === 'red' ? 'Red — Immediate action required'
    : h === 'amber' ? 'Amber — Monitor and action'
    : 'Green — On track'
}

function buildPrintHtml(r: PamReport): string {
  const ts = new Date(r.generated_at).toLocaleString('en-GB', { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  const ragBg = r.overall_health === 'red' ? '#ef4444' : r.overall_health === 'amber' ? '#f59e0b' : '#10b981'

  const msRows = r.milestones.map(m => {
    const rag = MS_RAG[m.rag] ?? MS_RAG.unscheduled
    const delta = m.days_delta !== null
      ? (m.days_delta < 0 ? `${Math.abs(m.days_delta)}d overdue` : m.days_delta === 0 ? 'today' : `${m.days_delta}d`)
      : '—'
    const rowStyle = m.rag === 'overdue' ? ' style="background:#fef2f2;"' : ''
    const badgeStyle = m.rag === 'overdue'
      ? ' style="background:#fee2e2;border-color:#fca5a5;color:#b91c1c;"'
      : m.rag === 'due_soon' ? ' style="background:#fffbeb;border-color:#fcd34d;color:#92400e;"'
      : m.rag === 'complete' ? ' style="background:#f0fdfa;border-color:#99f6e4;color:#0f766e;"'
      : ''
    return `<tr${rowStyle}><td>${esc(m.title)}</td><td>${esc(m.due_date)}</td><td>${esc(delta)}</td><td><span class="badge"${badgeStyle}>${esc(rag.label)}</span></td></tr>`
  }).join('')

  const crewRows = r.crews.map(c => `<tr>
    <td>${esc(c.crew_label)}</td>
    <td>${esc(CREW_STATUS_LABEL[c.status] ?? c.status)}</td>
    <td>${c.outputs_count}</td>
    <td>${c.pending_reviews || '—'}</td>
    <td>${c.last_run_at ? new Date(c.last_run_at + (c.last_run_at.includes('T') ? '' : 'T00:00:00')).toLocaleDateString('en-GB') : '—'}</td>
  </tr>`).join('')

  const issueHtml = r.issues.length
    ? r.issues.map(i => `<div class="item"><strong>${esc(i.title)}</strong><p>${esc(i.description)}</p><p><em>Recommended action:</em> ${esc(i.recommended_action)}</p></div>`).join('')
    : '<p style="color:#6b7280">No active issues.</p>'

  const riskHtml = r.risks.length
    ? r.risks.map(i => `<div class="item"><strong>[${esc(i.severity.toUpperCase())}] ${esc(i.title)}</strong><p>${esc(i.description)}</p><p><em>Mitigation:</em> ${esc(i.mitigation)}</p></div>`).join('')
    : '<p style="color:#6b7280">No risks identified.</p>'

  const highRisks = r.risks.filter(ri => ri.severity === 'high')
  const highRiskHtml = highRisks.length
    ? `<div style="margin-bottom:16px;padding:10px 14px;border-radius:6px;background:#fffbeb;border:1px solid #fcd34d;">
        <strong style="font-size:10pt;color:#92400e;">&#9888; ${highRisks.length} high-severity risk${highRisks.length !== 1 ? 's' : ''} requiring attention</strong>
        <ul style="margin:6px 0 0 16px;font-size:9.5pt;color:#92400e;">
          ${highRisks.map(ri => `<li>${esc(ri.title)}</li>`).join('')}
        </ul>
      </div>`
    : ''

  return `<!DOCTYPE html><html><head><meta charset="utf-8"><title>PMO Status Report — ${esc(r.client_name)}</title><style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 11pt; color: #111; padding: 40px; max-width: 900px; margin: 0 auto; }
    h1 { font-size: 20pt; color: #0f766e; margin-bottom: 4px; }
    h2 { font-size: 13pt; color: #0f766e; margin: 24px 0 8px; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; }
    .meta { font-size: 9pt; color: #6b7280; margin-bottom: 24px; }
    .rag { display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: 6px; background: ${ragBg}; color: white; font-weight: bold; font-size: 11pt; margin-bottom: 8px; }
    .summary { font-size: 10pt; color: #374151; margin-bottom: 16px; }
    table { width: 100%; border-collapse: collapse; margin-bottom: 12px; font-size: 9.5pt; }
    th { text-align: left; padding: 6px 8px; background: #f9fafb; border-bottom: 1px solid #e5e7eb; font-weight: 600; color: #374151; }
    td { padding: 5px 8px; border-bottom: 1px solid #f3f4f6; }
    .badge { font-size: 8pt; padding: 1px 6px; border-radius: 9999px; border: 1px solid #d1d5db; background: #f9fafb; }
    .item { margin-bottom: 12px; padding: 10px 12px; border-left: 3px solid #0f766e; background: #f9fafb; }
    .item strong { display: block; margin-bottom: 4px; }
    .item p { font-size: 9.5pt; color: #374151; margin-top: 4px; }
    @media print { body { padding: 20px; } }
  </style></head><body>
  <h1>Project Status Report</h1>
  <div class="meta">${esc(r.client_name)} · ${esc(r.sector)} · Generated ${esc(ts)}</div>
  <div class="rag">&#9679; ${esc(ragLabel(r.overall_health))}</div>
  <p class="summary">${esc(r.health_summary)}</p>
  ${highRiskHtml}
  <h2>1. Progress Against Plan</h2>
  <p style="font-size:9.5pt;color:#6b7280;margin-bottom:8px">${r.milestones_complete} of ${r.milestones_total} milestones complete</p>
  <table><thead><tr><th>Milestone</th><th>Due date</th><th>Delta</th><th>Status</th></tr></thead><tbody>${msRows}</tbody></table>
  <h2>2. Crew Status</h2>
  <table><thead><tr><th>Crew</th><th>Status</th><th>Outputs</th><th>Pending reviews</th><th>Last run</th></tr></thead><tbody>${crewRows}</tbody></table>
  <h2>3. Active Issues</h2>${issueHtml}
  <h2>4. Risks &amp; Mitigations</h2>${riskHtml}
  <p style="margin-top:32px;font-size:8pt;color:#9ca3af">Produced by Pamela Reid &#183; PMO &#183; TaskReimagination.ai</p>
  </body></html>`
}

// ── Section components ────────────────────────────────────────────────────────

function HealthBadge({ health, summary }: { health: string; summary: string }) {
  const c = RAG_COLOURS[health as 'red' | 'amber' | 'green'] ?? RAG_COLOURS.green
  return (
    <div className={`rounded-xl border p-4 ${c.border} bg-white`}>
      <div className="flex items-center gap-2.5 mb-2">
        <span className={`w-3 h-3 rounded-full flex-shrink-0 ${c.bg}`} />
        <p className={`text-sm font-bold ${c.text}`}>
          {health === 'red' ? 'Red — Immediate action required' : health === 'amber' ? 'Amber — Monitor and action' : 'Green — On track'}
        </p>
      </div>
      <p className="text-xs text-gray-600 leading-relaxed">{summary}</p>
    </div>
  )
}


function MilestoneTimeline({ milestones, complete, total, excludedDates }: {
  milestones: PamReportMilestone[]
  complete: number
  total: number
  excludedDates?: Set<string>
}) {
  const pct = total ? Math.round((complete / total) * 100) : 0
  const today = todayStr()
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
          <CalendarDays size={11} />Project timeline
        </p>
        <span className="text-[10px] text-gray-500">{complete}/{total} · {pct}%</span>
      </div>
      <div className="w-full bg-gray-100 rounded-full h-1 mb-3">
        <div className="h-1 rounded-full bg-teal-500 transition-all" style={{ width: `${pct}%` }} />
      </div>

      <div className="relative">
        {/* Vertical spine */}
        <div className="absolute left-[8px] top-1 bottom-1 w-px bg-gray-100 z-0" />

        {milestones.map((m, idx) => {
          const rag       = m.rag in MS_RAG ? m.rag : 'unscheduled'
          const circleCls = MS_RAG_CIRCLE[rag as keyof typeof MS_RAG_CIRCLE]
          const { label, cls } = MS_RAG[rag as keyof typeof MS_RAG]
          const deltaCls  = MS_DELTA_CLS[rag as keyof typeof MS_DELTA_CLS]
          const isComplete = m.status === 'complete'

          // Working-day delta, computed client-side so NWR and holidays are factored in
          const calDiff = m.due_date ? daysBetween(today, m.due_date) : null
          const delta = calDiff === null ? null
            : calDiff === 0 ? 'today'
            : calDiff > 0
              ? `${workingDaysBetween(today, m.due_date!, excludedDates)}wd`
              : `${workingDaysBetween(m.due_date!, today, excludedDates)}wd overdue`

          const shortDate = m.due_date
            ? new Date(m.due_date + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
            : null

          return (
            <div key={m.id} className="flex items-center gap-2 py-[3px] relative">
              {/* Numbered circle */}
              <div className={`w-[18px] h-[18px] rounded-full border-2 flex-shrink-0 flex items-center justify-center text-[8px] font-bold z-10 ${circleCls}`}>
                {isComplete ? '✓' : idx + 1}
              </div>

              {/* Title */}
              <span className={`text-[11px] flex-1 leading-tight min-w-0 truncate ${isComplete ? 'line-through text-gray-300' : 'text-gray-700'}`}>
                {m.title}
              </span>

              {/* Date */}
              {shortDate && (
                <span className="text-[9px] text-gray-400 flex-shrink-0 tabular-nums">{shortDate}</span>
              )}

              {/* Delta — hidden when complete */}
              {delta && !isComplete && (
                <span className={`text-[9px] font-medium flex-shrink-0 tabular-nums ${deltaCls}`}>{delta}</span>
              )}

              {/* RAG badge */}
              <span className={`text-[8px] font-semibold px-1.5 py-0.5 rounded-full border flex-shrink-0 ${cls}`}>
                {label}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function IssueSection({ issues }: { issues: PamReportIssue[] }) {
  if (!issues.length) return (
    <div className="flex items-center gap-2 text-xs text-gray-400 py-2">
      <CheckCheck size={14} className="text-teal-400" />No active issues.
    </div>
  )
  return (
    <div className="space-y-2">
      {issues.map((issue, i) => (
        <div key={i} className={`rounded-lg border p-3 ${SEVERITY_COLOURS[issue.severity]}`}>
          <div className="flex items-start gap-2 mb-1.5">
            <span className={`w-2 h-2 rounded-full flex-shrink-0 mt-1 ${SEVERITY_DOT[issue.severity]}`} />
            <p className="text-xs font-bold leading-snug flex-1">{issue.title}</p>
            <span className="text-[9px] font-bold uppercase tracking-wider opacity-60 flex-shrink-0">{issue.severity}</span>
          </div>
          <p className="text-[11px] text-gray-600 leading-relaxed ml-4 mb-2">{issue.description}</p>
          <div className="ml-4 flex items-start gap-1.5">
            <ArrowRight size={11} className="flex-shrink-0 mt-0.5 text-teal-500" />
            <p className="text-[11px] text-teal-700 leading-relaxed font-medium">{issue.recommended_action}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

function RiskSection({ risks }: { risks: PamReportRisk[] }) {
  if (!risks.length) return (
    <div className="flex items-center gap-2 text-xs text-gray-400 py-2">
      <CheckCheck size={14} className="text-teal-400" />No risks identified.
    </div>
  )
  return (
    <div className="space-y-2">
      {risks.map((risk, i) => (
        <div key={i} className={`rounded-lg border p-3 ${SEVERITY_COLOURS[risk.severity]}`}>
          <div className="flex items-start gap-2 mb-1.5">
            <span className={`w-2 h-2 rounded-full flex-shrink-0 mt-1 ${SEVERITY_DOT[risk.severity]}`} />
            <p className="text-xs font-bold leading-snug flex-1">{risk.title}</p>
            <span className="text-[9px] font-bold uppercase tracking-wider opacity-60 flex-shrink-0">{risk.severity}</span>
          </div>
          <p className="text-[11px] text-gray-600 leading-relaxed ml-4 mb-2">{risk.description}</p>
          <div className="ml-4 flex items-start gap-1.5">
            <Shield size={11} className="flex-shrink-0 mt-0.5 text-blue-400" />
            <p className="text-[11px] text-blue-700 leading-relaxed">{risk.mitigation}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

function StatsRow({ report }: { report: PamReport }) {
  const items = [
    { label: 'Stakeholders', value: report.stakeholder_count, icon: <Users size={12} />, warn: report.stakeholder_count === 0 },
    { label: 'Documents',    value: report.doc_count,          icon: <FileText size={12} />, warn: report.doc_count === 0 },
    { label: 'Pending reviews', value: report.pending_reviews, icon: <Clock size={12} />, warn: report.pending_reviews > 0 },
    { label: 'Interviews',   value: report.interview_tracker.total > 0
        ? `${report.interview_tracker.complete}/${report.interview_tracker.total}`
        : '—',
      icon: <Users size={12} />, warn: report.interview_tracker.total > 0 && report.interview_tracker.pct < 60 },
  ]
  return (
    <div className="grid grid-cols-2 gap-2">
      {items.map(({ label, value, icon, warn }) => (
        <div key={label} className={`rounded-lg border p-2.5 flex items-center gap-2 ${warn ? 'border-amber-200 bg-amber-50' : 'border-gray-100 bg-white'}`}>
          <span className={warn ? 'text-amber-500' : 'text-gray-400'}>{icon}</span>
          <div>
            <p className={`text-sm font-bold ${warn ? 'text-amber-700' : 'text-gray-700'}`}>{value}</p>
            <p className="text-[10px] text-gray-400">{label}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

export default function PamReportView({ slug }: { slug: string }) {
  const { data: report, isLoading, error, refetch, isFetching } = useQuery<PamReport>({
    queryKey: ['pam-report', slug],
    queryFn: () => pamReportApi.get(slug),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug),
    staleTime: 60_000,
  })

  const { data: nonWorkingRanges = [] } = useQuery({
    queryKey: ['nonworking', slug],
    queryFn: () => nonworkingApi.list(slug),
    staleTime: 60_000,
  })

  if (isLoading) return (
    <div className="flex-1 flex items-center justify-center text-gray-400">
      <Loader2 size={18} className="animate-spin mr-2" />Generating report…
    </div>
  )

  if (error || !report) return (
    <div className="flex-1 flex items-center justify-center text-red-400 text-sm p-4 text-center">
      Could not load report. Check the API is running.
    </div>
  )

  const ts = new Date(report.generated_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })

  return (
    <div className="flex-1 overflow-y-auto">
      {/* Report toolbar */}
      <div className="sticky top-0 z-10 bg-white border-b border-gray-100 px-4 py-2 flex items-center justify-between gap-2">
        <p className="text-[10px] text-gray-400 flex items-center gap-1">
          <Clock size={10} />Live · generated {ts}
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-1 text-[10px] text-gray-500 hover:text-gray-800 transition-colors disabled:opacity-40"
          >
            <RefreshCw size={10} className={isFetching ? 'animate-spin' : ''} />Refresh
          </button>
          <button
            onClick={() => printReport(report)}
            className="flex items-center gap-1.5 text-[10px] bg-teal-600 text-white px-2.5 py-1 rounded-lg hover:bg-teal-700 transition-colors"
          >
            <Download size={10} />Download / Print
          </button>
        </div>
      </div>

      <div className="p-4 space-y-5">
        {/* RAG health */}
        <HealthBadge health={report.overall_health} summary={report.health_summary} />

        {/* HIGH risk alert */}
        {report.risks.filter(r => r.severity === 'high').length > 0 && (() => {
          const highRisks = report.risks.filter(r => r.severity === 'high')
          return (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 flex items-start gap-2">
              <AlertOctagon size={13} className="text-amber-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-xs font-bold text-amber-700 mb-1">
                  {highRisks.length} high-severity risk{highRisks.length !== 1 ? 's' : ''} requiring attention
                </p>
                {highRisks.map((r, i) => (
                  <p key={i} className="text-[11px] text-amber-600 leading-snug">{r.title}</p>
                ))}
              </div>
            </div>
          )
        })()}

        {/* Full Gantt — uses stored schedule window, falls back to milestone-date inference */}
        {report.milestones.filter(m => m.due_date).length >= 2 && (() => {
          const locale = settings?.locale ?? 'GB'
          const stored = settings?.sched_start && settings?.sched_duration_weeks
          const { schedStart, durationWeeks } = stored
            ? { schedStart: settings!.sched_start!, durationWeeks: settings!.sched_duration_weeks! }
            : inferSchedule(report.milestones.map(m => m.due_date).filter(Boolean) as string[])
          const endDate = new Date(schedStart + 'T00:00:00')
          endDate.setDate(endDate.getDate() + durationWeeks * 7)
          const endStr = endDate.toISOString().slice(0, 10)
          const holidays = getPublicHolidays(locale, schedStart, endStr)
          return (
            <div>
              <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2 flex items-center gap-1.5">
                <CalendarDays size={11} />Schedule
              </p>
              <GanttReadOnly
                milestones={report.milestones}
                startDate={schedStart}
                durationWeeks={durationWeeks}
                holidays={holidays}
                nonWorkingRanges={nonWorkingRanges}
                locale={locale}
              />
            </div>
          )
        })()}

        {/* Timeline — instant RAG view of all milestones */}
        {report.milestones.length > 0 && (() => {
          const locale = settings?.locale ?? 'GB'
          const stored = settings?.sched_start && settings?.sched_duration_weeks
          const { schedStart, durationWeeks } = stored
            ? { schedStart: settings!.sched_start!, durationWeeks: settings!.sched_duration_weeks! }
            : inferSchedule(report.milestones.map(m => m.due_date).filter(Boolean) as string[])
          const endStr = (() => { const d = new Date(schedStart + 'T00:00:00'); d.setDate(d.getDate() + durationWeeks * 7); return d.toISOString().slice(0, 10) })()
          const holidays = getPublicHolidays(locale, schedStart, endStr)
          const excluded = buildExcludedDateSet(holidays, nonWorkingRanges)
          return (
            <MilestoneTimeline
              milestones={report.milestones}
              complete={report.milestones_complete}
              total={report.milestones_total}
              excludedDates={excluded}
            />
          )
        })()}

        {/* Stats */}
        <StatsRow report={report} />

        {/* Active issues */}
        <div>
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2 flex items-center gap-1.5">
            <AlertOctagon size={11} />Active issues ({report.issues.length})
          </p>
          <IssueSection issues={report.issues} />
        </div>

        {/* Risks */}
        <div>
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2 flex items-center gap-1.5">
            <Shield size={11} />Risks &amp; mitigations ({report.risks.length})
          </p>
          <RiskSection risks={report.risks} />
        </div>

        <p className="text-[9px] text-gray-300 text-center pt-2 pb-1">Pamela Reid · PMO · TaskReimagination.ai</p>
      </div>
    </div>
  )
}

// ── Per-crew status detail (used in Status tab) ───────────────────────────────

export function PamCrewStatusDetail({ slug }: { slug: string }) {
  const { data: report, isLoading } = useQuery<PamReport>({
    queryKey: ['pam-report', slug],
    queryFn: () => pamReportApi.get(slug),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })

  if (isLoading) return <div className="p-4 text-xs text-gray-400 flex items-center gap-2"><Loader2 size={14} className="animate-spin" />Loading crew status…</div>
  if (!report) return null

  return (
    <div className="space-y-2">
      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-3">Crew status</p>
      {report.crews.map((c: PamReportCrewStatus) => {
        const statusColour = CREW_STATUS_COLOUR[c.status] ?? 'text-gray-400'
        const statusLabel  = CREW_STATUS_LABEL[c.status] ?? c.status
        const Icon = c.status === 'completed' ? CheckCircle2
          : c.status === 'failed' ? XCircle
          : c.status === 'running' ? Loader2
          : Circle
        return (
          <div key={c.crew_key} className={`rounded-lg border p-3 bg-white transition-colors ${c.status === 'failed' ? 'border-red-100' : c.status === 'completed' ? 'border-teal-100' : 'border-gray-100'}`}>
            <div className="flex items-center gap-2 mb-1">
              <Icon size={13} className={`flex-shrink-0 ${statusColour} ${c.status === 'running' ? 'animate-spin' : ''}`} />
              <p className="text-xs font-semibold text-gray-800 flex-1">{c.crew_label}</p>
              <span className={`text-[10px] font-medium ${statusColour}`}>{statusLabel}</span>
            </div>
            <div className="pl-5 grid grid-cols-3 gap-x-4 gap-y-0.5 text-[10px] text-gray-400">
              <span>Runs: <span className="text-gray-600 font-medium">{c.run_count}</span></span>
              <span>Outputs: <span className="text-gray-600 font-medium">{c.outputs_count}</span></span>
              {c.pending_reviews > 0 && (
                <span className="text-amber-600 font-medium">{c.pending_reviews} review{c.pending_reviews !== 1 ? 's' : ''} pending</span>
              )}
              {c.last_run_at && <span className="col-span-3">Last run: {fmt(c.last_run_at)}</span>}
            </div>
            {c.error_detail && (
              <div className="mt-2 ml-5 rounded bg-red-50 border border-red-100 px-2 py-1.5">
                <p className="text-[10px] font-bold text-red-500 mb-0.5">Error</p>
                <pre className="text-[10px] text-red-700 whitespace-pre-wrap break-all font-mono leading-relaxed max-h-16 overflow-y-auto">{c.error_detail}</pre>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
