// ui/src/components/tabs/PamSetupTab.tsx
// PAM's Setup tab: full project schedule (milestones, Gantt, non-working periods)
import { useState, useRef, useCallback, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2, Circle, AlertTriangle, Clock, Plus, Trash2,
  ChevronDown, ChevronUp, RefreshCw, CalendarDays, Wand2, Ban, Pencil,
} from 'lucide-react'
import { milestonesApi, nonworkingApi, projectsApi } from '../../api/endpoints'
import type { Milestone, NonWorkingRange } from '../../types'
import {
  getPublicHolidays, formatDate, formatDateShort,
  buildExcludedDateSet, workingDaysBetween as libWorkingDaysBetween,
} from '../../utils/holidays'
import type { PublicHoliday } from '../../utils/holidays'

// ── Date helpers ──────────────────────────────────────────────────────────────

function todayStr(): string {
  return new Date().toISOString().slice(0, 10)
}

function addDays(dateStr: string, days: number): string {
  const d = new Date(dateStr + 'T00:00:00')
  d.setDate(d.getDate() + Math.round(days))
  return d.toISOString().slice(0, 10)
}

function daysBetween(a: string, b: string): number {
  return Math.round(
    (new Date(b + 'T00:00:00').getTime() - new Date(a + 'T00:00:00').getTime()) / 86_400_000,
  )
}

type MilestoneRAG = 'complete' | 'overdue' | 'due_soon' | 'on_track' | 'unscheduled'

function milestoneState(m: Pick<Milestone, 'status' | 'due_date'>): MilestoneRAG {
  if (m.status === 'complete') return 'complete'
  if (!m.due_date) return 'unscheduled'
  const diff = daysBetween(todayStr(), m.due_date)
  if (diff < 0) return 'overdue'
  if (diff <= 3) return 'due_soon'
  return 'on_track'
}

function countdownLabel(m: Milestone, excludedDates?: Set<string>): string {
  if (!m.due_date) return ''
  const calDiff = daysBetween(todayStr(), m.due_date)
  if (calDiff === 0) return 'Due today'
  if (calDiff > 0) {
    const wd = excludedDates ? libWorkingDaysBetween(todayStr(), m.due_date, excludedDates) : calDiff
    return `${wd} working day${wd !== 1 ? 's' : ''} remaining`
  }
  const wd = excludedDates ? libWorkingDaysBetween(m.due_date, todayStr(), excludedDates) : Math.abs(calDiff)
  return wd <= 1 ? '1 working day overdue' : `${wd} working days overdue`
}

const STATE_BADGE: Record<MilestoneRAG, string> = {
  complete:    'bg-teal-50 text-teal-700 border-teal-200',
  overdue:     'bg-red-50 text-red-700 border-red-200',
  due_soon:    'bg-amber-50 text-amber-700 border-amber-200',
  on_track:    'bg-gray-50 text-gray-600 border-gray-200',
  unscheduled: 'bg-gray-50 text-gray-400 border-gray-100',
}

const GANTT_STYLE: Record<MilestoneRAG, { border: string; bg: string; text: string }> = {
  complete:    { border: 'border-teal-500',  bg: 'bg-teal-500',  text: 'text-white' },
  overdue:     { border: 'border-red-500',   bg: 'bg-red-500',   text: 'text-white' },
  due_soon:    { border: 'border-amber-400', bg: 'bg-amber-400', text: 'text-white' },
  on_track:    { border: 'border-green-400', bg: 'bg-white',     text: 'text-green-600' },
  unscheduled: { border: 'border-gray-300',  bg: 'bg-gray-100',  text: 'text-gray-400' },
}

// ── Auto-date scheduling ──────────────────────────────────────────────────────

const DEFAULT_KEY_ORDER = [
  'project_initiation',
  'discovery_docs', 'value_chain_approved', 'stakeholders_assigned', 'scripts_approved',
  'interviews_launched', 'interviews_complete',
  'propositions_approved', 'portfolio_approved', 'roadmap_approved',
  'business_case_draft', 'business_plan_delivered', 'project_closeout',
]

function interviewWindowDays(durationWeeks: number): number {
  if (durationWeeks >= 12) return 28
  if (durationWeeks >= 7)  return 21
  return 14
}

function autoOffsets(durationWeeks: number): number[] {
  const totalDays    = durationWeeks * 7
  const iwDays       = interviewWindowDays(durationWeeks)
  const launchFrac   = 0.35
  const completeFrac = launchFrac + iwDays / totalDays

  const postDays     = totalDays * (1 - completeFrac)
  const reviewDays   = Math.max(7, Math.floor(postDays * 0.20))
  const closeoutDays = 2
  const analysisDays = Math.max(3, postDays - reviewDays - closeoutDays)

  const A = completeFrac
  const B = A + analysisDays / totalDays
  const C = B + reviewDays   / totalDays

  return [
    0.0,
    0.05, 0.13, 0.21, 0.29,
    launchFrac, completeFrac,
    A + (analysisDays / totalDays) * 0.30,
    A + (analysisDays / totalDays) * 0.57,
    A + (analysisDays / totalDays) * 0.83,
    B, C, 1.0,
  ]
}

function buildDateMap(
  milestones: Milestone[], start: string, durationWeeks: number,
): Record<number, string> {
  const offsets   = autoOffsets(durationWeeks)
  const totalDays = durationWeeks * 7
  const result: Record<number, string> = {}

  const keyed = DEFAULT_KEY_ORDER
    .map(k => milestones.find(m => m.milestone_key === k))
    .filter(Boolean) as Milestone[]

  const custom = milestones
    .filter(m => !DEFAULT_KEY_ORDER.includes(m.milestone_key))
    .sort((a, b) => a.sort_order - b.sort_order)

  keyed.forEach((m, i) => {
    result[m.id] = addDays(start, (offsets[i] ?? 1) * totalDays)
  })
  custom.forEach((m, i) => {
    result[m.id] = addDays(start, (0.90 + 0.10 * (i + 1) / (custom.length + 1)) * totalDays)
  })
  return result
}

// ── Interview completion tracker ──────────────────────────────────────────────

interface SessionRow { session_token: string; stakeholder_name: string; status: string }

function InterviewCompletionPanel({ slug }: { slug: string }) {
  const { data: sessions = [] } = useQuery({
    queryKey: ['interview-sessions', slug],
    queryFn: () =>
      fetch(`/api/interviews/sessions/${slug}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
      }).then(r => r.ok ? r.json() as Promise<SessionRow[]> : Promise.resolve([])),
    refetchInterval: 60_000,
  })
  if (!sessions.length) return null
  const complete    = sessions.filter(s => s.status === 'completed')
  const outstanding = sessions.filter(s => s.status !== 'completed')
  return (
    <div className="mt-3 rounded-lg border border-gray-100 bg-gray-50 p-3">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs font-semibold text-gray-600">Interview completion</p>
        <span className="text-xs text-gray-500">{complete.length} / {sessions.length} complete</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-1.5 mb-3">
        <div className="h-1.5 rounded-full bg-teal-500 transition-all"
          style={{ width: `${Math.round((complete.length / sessions.length) * 100)}%` }} />
      </div>
      {outstanding.length > 0 && (
        <ul className="space-y-1">
          {outstanding.map(s => (
            <li key={s.session_token} className="flex items-center justify-between text-xs">
              <span className="text-gray-700">{s.stakeholder_name}</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                s.status === 'active'
                  ? 'bg-brand/10 text-brand border-brand/20'
                  : 'bg-gray-100 text-gray-500 border-gray-200'
              }`}>{s.status === 'active' ? 'In progress' : 'Not started'}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── Gantt chart ───────────────────────────────────────────────────────────────

const GANTT_H = 220
const LABEL_H = 50

function dateToPct(date: string, startDate: string, totalDays: number): number {
  const raw = daysBetween(startDate, date) / totalDays
  return Math.max(2, Math.min(98, raw * 100))
}

interface GanttPreview { fromIdx: number; offsetDays: number }

function GanttChart({
  milestones, startDate, durationWeeks, onUpdateDates,
  holidays, nonWorkingRanges, locale,
}: {
  milestones: Milestone[]
  startDate: string
  durationWeeks: number
  onUpdateDates: (updates: { id: number; date: string }[]) => void
  holidays: PublicHoliday[]
  nonWorkingRanges: NonWorkingRange[]
  locale: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const dragRef      = useRef<{
    fromIdx: number; startX: number; totalPx: number
    snapshots: { id: number; date: string }[]
  } | null>(null)
  const sortedRef = useRef<Milestone[]>([])
  const [preview, setPreview] = useState<GanttPreview | null>(null)

  const totalDays = durationWeeks * 7
  const endDate   = addDays(startDate, totalDays)
  const today     = todayStr()

  const sorted = [...milestones].sort((a, b) =>
    a.sort_order !== b.sort_order ? a.sort_order - b.sort_order : a.id - b.id,
  )
  sortedRef.current = sorted

  function effDate(m: Milestone, idx: number): string | null {
    if (preview && idx >= preview.fromIdx && m.due_date) {
      const raw = addDays(m.due_date, preview.offsetDays)
      return raw < startDate ? startDate : raw > endDate ? endDate : raw
    }
    return m.due_date
  }

  function toPct(date: string): number {
    return dateToPct(date, startDate, totalDays)
  }

  const handleMouseDown = useCallback((e: React.MouseEvent, fromIdx: number) => {
    const ms = sortedRef.current
    if (!containerRef.current) return
    const m = ms[fromIdx]
    if (!m?.due_date) return
    e.preventDefault()

    dragRef.current = {
      fromIdx,
      startX:    e.clientX,
      totalPx:   containerRef.current.getBoundingClientRect().width,
      snapshots: ms.slice(fromIdx).filter(sm => sm.due_date).map(sm => ({ id: sm.id, date: sm.due_date! })),
    }

    const onMove = (ev: MouseEvent) => {
      const ds = dragRef.current
      if (!ds) return
      const dayDelta = Math.round(((ev.clientX - ds.startX) / ds.totalPx) * totalDays)
      setPreview({ fromIdx: ds.fromIdx, offsetDays: dayDelta })
    }

    const onUp = (ev: MouseEvent) => {
      const ds = dragRef.current
      if (ds) {
        const dayDelta = Math.round(((ev.clientX - ds.startX) / ds.totalPx) * totalDays)
        const updates  = ds.snapshots.map(({ id, date }) => {
          const raw = addDays(date, dayDelta)
          return { id, date: raw < startDate ? startDate : raw > endDate ? endDate : raw }
        })
        onUpdateDates(updates)
      }
      dragRef.current = null
      setPreview(null)
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [totalDays, startDate, endDate, onUpdateDates])

  const launchM    = sorted.find(m => m.milestone_key === 'interviews_launched')
  const completeM  = sorted.find(m => m.milestone_key === 'interviews_complete')
  const launchIdx  = launchM   ? sorted.indexOf(launchM)   : -1
  const completeIdx = completeM ? sorted.indexOf(completeM) : -1
  const lDate      = launchM   ? effDate(launchM,   launchIdx)   : null
  const cDate      = completeM ? effDate(completeM, completeIdx) : null

  const chartExcluded = buildExcludedDateSet(holidays, nonWorkingRanges)
  const iwWorkingDays = lDate && cDate && cDate > lDate
    ? libWorkingDaysBetween(lDate, cDate, chartExcluded)
    : null

  const todayPct     = toPct(today)
  const todayInRange = today >= startDate && today <= endDate

  const visibleHolidays = holidays.filter(h => h.date >= startDate && h.date <= endDate)

  return (
    <div className="mb-4 select-none">
      <div
        ref={containerRef}
        className="relative bg-white border border-gray-100 rounded-2xl"
        style={{ height: GANTT_H }}
      >
        {/* Week grid */}
        {Array.from({ length: durationWeeks + 1 }, (_, i) => (
          <div
            key={i}
            className="absolute top-0 bottom-0 border-l border-gray-100 pointer-events-none"
            style={{ left: `${(i / durationWeeks) * 100}%` }}
          >
            {i > 0 && i < durationWeeks && (
              <span className="absolute text-[9px] text-gray-300" style={{ bottom: LABEL_H - 10, left: 3 }}>
                W{i}
              </span>
            )}
          </div>
        ))}

        {/* Non-working range bands */}
        {nonWorkingRanges.map(r => {
          if (r.end_date < startDate || r.start_date > endDate) return null
          const effStart = r.start_date < startDate ? startDate : r.start_date
          const effEnd   = r.end_date   > endDate   ? endDate   : r.end_date
          const l  = daysBetween(startDate, effStart) / totalDays * 100
          const ri = Math.max(0, 100 - (daysBetween(startDate, effEnd) + 1) / totalDays * 100)
          return (
            <div
              key={r.id}
              className="absolute bg-orange-50/60 border-x border-orange-200/40 pointer-events-none"
              style={{ top: 0, bottom: 0, left: `${l}%`, right: `${ri}%` }}
              title={`Non-working: ${r.label}`}
            />
          )
        })}

        {/* Interview window band */}
        {lDate && cDate && (
          <>
            <div
              className="absolute bg-teal-50/70 border-x border-teal-200/50 pointer-events-none"
              style={{ top: LABEL_H + 4, bottom: LABEL_H + 4, left: `${toPct(lDate)}%`, right: `${100 - toPct(cDate)}%` }}
            />
            <div
              className="absolute pointer-events-none flex items-center justify-center"
              style={{ top: '50%', transform: 'translateY(-50%)', left: `${toPct(lDate)}%`, right: `${100 - toPct(cDate)}%`, zIndex: 8 }}
            >
              <span className="text-[8px] text-teal-500 font-bold tracking-widest uppercase whitespace-nowrap bg-white px-1.5 rounded-sm">
                INTERVIEWS
              </span>
            </div>
          </>
        )}

        {/* Today line */}
        {todayInRange && (
          <div className="absolute top-0 bottom-0 pointer-events-none" style={{ left: `${todayPct}%` }}>
            <div className="h-full border-l-2 border-dashed border-rose-300/70" />
            <span className="absolute text-[9px] text-rose-400 font-semibold whitespace-nowrap"
              style={{ bottom: LABEL_H - 10, left: 4 }}>Today</span>
          </div>
        )}

        {/* Holiday bands */}
        {visibleHolidays.map(h => {
          const l  = daysBetween(startDate, h.date) / totalDays * 100
          const ri = 100 - (daysBetween(startDate, h.date) + 1) / totalDays * 100
          return (
            <div
              key={'hol-' + h.date}
              className="absolute bg-orange-50/60 border-x border-orange-200/40 pointer-events-none"
              style={{ top: 0, bottom: 0, left: `${l}%`, right: `${Math.max(0, ri)}%` }}
              title={h.name}
            />
          )
        })}

        {/* Spine */}
        <div className="absolute left-0 right-0 border-t border-gray-200 pointer-events-none" style={{ top: '50%' }} />

        {/* Milestone markers */}
        {sorted.map((m, idx) => {
          const date = effDate(m, idx)
          if (!date) return null

          const xPct       = toPct(date)
          const state      = milestoneState({ status: m.status, due_date: date })
          const { border, bg, text } = GANTT_STYLE[state]
          const isAbove    = idx % 2 === 0
          const isCascaded = !!(preview && idx > preview.fromIdx && m.due_date)
          const isDragging = !!(preview && idx === preview.fromIdx)
          const canDrag    = !!m.due_date

          const shortDate = formatDateShort(date, locale)

          return (
            <div
              key={m.id}
              className="absolute"
              style={{
                left: `${xPct}%`,
                top: 0, bottom: 0, width: 80,
                transform: 'translateX(-50%)',
                pointerEvents: 'none',
                zIndex: isDragging ? 30 : isCascaded ? 20 : 10,
              }}
            >
              {isAbove && (
                <div className="absolute text-center" style={{ top: 8, left: 0, right: 0 }}>
                  <p className="text-[9px] font-semibold text-gray-600 leading-tight">
                    {m.title.length > 20 ? m.title.slice(0, 19) + '…' : m.title}
                  </p>
                  <p className="text-[8px] text-gray-400 mt-0.5">{shortDate}</p>
                </div>
              )}

              {isAbove && (
                <div className="absolute bg-gray-200"
                  style={{ width: 1, left: '50%', top: LABEL_H - 2, bottom: 'calc(50% + 14px)' }} />
              )}

              <div style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', pointerEvents: 'auto', zIndex: 2 }}>
                <button
                  onMouseDown={e => handleMouseDown(e, idx)}
                  className={`w-7 h-7 rounded-full border-2 flex items-center justify-center text-[9px] font-bold transition-transform
                    ${border} ${bg} ${text}
                    ${canDrag ? 'cursor-grab hover:scale-110 active:cursor-grabbing' : 'cursor-default opacity-50'}
                    ${isDragging ? 'scale-125 shadow-lg shadow-teal-100' : isCascaded ? 'scale-110 opacity-70' : ''}`}
                  title={canDrag ? `Drag to shift this and all later milestones — ${date}` : m.title}
                >
                  {idx + 1}
                </button>
              </div>

              {!isAbove && (
                <div className="absolute bg-gray-200"
                  style={{ width: 1, left: '50%', top: 'calc(50% + 14px)', bottom: LABEL_H - 2 }} />
              )}

              {!isAbove && (
                <div className="absolute text-center" style={{ bottom: 8, left: 0, right: 0 }}>
                  <p className="text-[9px] font-semibold text-gray-600 leading-tight">
                    {m.title.length > 20 ? m.title.slice(0, 19) + '…' : m.title}
                  </p>
                  <p className="text-[8px] text-gray-400 mt-0.5">{shortDate}</p>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between mt-1.5 px-1 text-[10px] text-gray-400">
        <span>{formatDate(startDate, locale)}</span>
        <div className="flex items-center gap-5">
          {lDate && cDate && (
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded bg-teal-50 border border-teal-300 inline-block" />
              {iwWorkingDays != null
                ? `Interview window (${iwWorkingDays} working day${iwWorkingDays !== 1 ? 's' : ''})`
                : `Interview window (${interviewWindowDays(durationWeeks) / 7} wks)`}
            </span>
          )}
          {(nonWorkingRanges.filter(r => r.end_date >= startDate && r.start_date <= endDate).length > 0 || visibleHolidays.length > 0) && (() => {
            const nwrDays = nonWorkingRanges.reduce((sum, r) => {
              const s = r.start_date < startDate ? startDate : r.start_date
              const e = r.end_date   > endDate   ? endDate   : r.end_date
              return s <= e ? sum + daysBetween(s, e) + 1 : sum
            }, 0)
            const total = nwrDays + visibleHolidays.length
            return (
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded-sm bg-orange-100 border border-orange-300 inline-block" />
                Non-working ({total} day{total !== 1 ? 's' : ''})
              </span>
            )
          })()}
          <span className="flex items-center gap-1.5">
            <span className="w-4 border-t-2 border-dashed border-rose-300 inline-block" />
            Today
          </span>
          <span className="text-gray-300">Drag to shift milestone and all following</span>
        </div>
        <span>{formatDate(endDate, locale)}</span>
      </div>
    </div>
  )
}

// ── Non-working ranges panel ──────────────────────────────────────────────────

interface NWREdit { label: string; start_date: string; end_date: string }

function NonWorkingPanel({ slug, locale }: { slug: string; locale: string }) {
  const qc = useQueryClient()
  const [open, setOpen]       = useState(false)
  const [adding, setAdding]   = useState(false)
  const [editId, setEditId]   = useState<number | null>(null)
  const [form, setForm]       = useState<NWREdit>({ label: '', start_date: '', end_date: '' })

  const { data: ranges = [] } = useQuery({
    queryKey: ['nonworking', slug],
    queryFn:  () => nonworkingApi.list(slug),
    enabled:  !!slug,
  })

  const create = useMutation({
    mutationFn: () => nonworkingApi.create(slug, form),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['nonworking', slug] }); setAdding(false); setForm({ label: '', start_date: '', end_date: '' }) },
  })
  const update = useMutation({
    mutationFn: () => nonworkingApi.update(slug, editId!, form),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['nonworking', slug] }); setEditId(null) },
  })
  const remove = useMutation({
    mutationFn: (id: number) => nonworkingApi.remove(slug, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['nonworking', slug] }),
  })

  function startEdit(r: NonWorkingRange) {
    setEditId(r.id)
    setForm({ label: r.label, start_date: r.start_date, end_date: r.end_date })
    setAdding(false)
  }

  function startAdd() {
    setAdding(true)
    setEditId(null)
    setForm({ label: '', start_date: '', end_date: '' })
  }

  return (
    <div className="mb-4 border border-gray-100 rounded-2xl overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-5 py-3 bg-gray-50 hover:bg-gray-100 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Ban size={14} className="text-orange-400" />
          <span className="text-xs font-bold text-gray-600 uppercase tracking-widest">
            Non-working periods
          </span>
          {ranges.length > 0 && (
            <span className="text-[10px] bg-orange-100 text-orange-600 px-1.5 py-0.5 rounded-full font-semibold">
              {ranges.length}
            </span>
          )}
        </div>
        {open ? <ChevronUp size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
      </button>

      {open && (
        <div className="px-5 py-4 space-y-3 bg-white">
          {ranges.length === 0 && !adding && (
            <p className="text-xs text-gray-400">No non-working periods defined.</p>
          )}

          {ranges.map(r => (
            editId === r.id ? (
              <div key={r.id} className="border border-orange-200 rounded-lg bg-orange-50/30 p-3 space-y-2">
                <input
                  value={form.label}
                  onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
                  placeholder="Label (e.g. Christmas)"
                  className="w-full text-xs border border-gray-200 rounded px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-orange-400 bg-white"
                />
                <div className="flex gap-2 items-center">
                  <input type="date" value={form.start_date}
                    onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))}
                    className="text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-orange-400 bg-white flex-1"
                    style={{ colorScheme: 'light' }} />
                  <span className="text-xs text-gray-400">to</span>
                  <input type="date" value={form.end_date}
                    onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))}
                    className="text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-orange-400 bg-white flex-1"
                    style={{ colorScheme: 'light' }} />
                </div>
                <div className="flex gap-2">
                  <button onClick={() => update.mutate()} disabled={!form.label || !form.start_date || !form.end_date || update.isPending}
                    className="text-xs bg-orange-500 text-white rounded px-3 py-1.5 hover:bg-orange-600 disabled:opacity-40 transition-colors">
                    Save
                  </button>
                  <button onClick={() => setEditId(null)} className="text-xs text-gray-400 hover:text-gray-600 px-2 transition-colors">
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div key={r.id} className="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2">
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-gray-700">{r.label}</p>
                  <p className="text-[10px] text-gray-400 mt-0.5">
                    {formatDate(r.start_date, locale)} – {formatDate(r.end_date, locale)}
                  </p>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                  <button onClick={() => startEdit(r)} className="text-gray-300 hover:text-gray-500 transition-colors" aria-label="Edit">
                    <Pencil size={13} />
                  </button>
                  <button onClick={() => remove.mutate(r.id)} className="text-gray-300 hover:text-red-400 transition-colors" aria-label="Delete">
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            )
          ))}

          {adding && (
            <div className="border border-orange-200 rounded-lg bg-orange-50/30 p-3 space-y-2">
              <input
                autoFocus
                value={form.label}
                onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
                placeholder="Label (e.g. Christmas)"
                className="w-full text-xs border border-gray-200 rounded px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-orange-400 bg-white"
              />
              <div className="flex gap-2 items-center">
                <input type="date" value={form.start_date}
                  onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))}
                  className="text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-orange-400 bg-white flex-1"
                  style={{ colorScheme: 'light' }} />
                <span className="text-xs text-gray-400">to</span>
                <input type="date" value={form.end_date}
                  onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))}
                  className="text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-orange-400 bg-white flex-1"
                  style={{ colorScheme: 'light' }} />
              </div>
              <div className="flex gap-2">
                <button onClick={() => create.mutate()} disabled={!form.label || !form.start_date || !form.end_date || create.isPending}
                  className="text-xs bg-orange-500 text-white rounded px-3 py-1.5 hover:bg-orange-600 disabled:opacity-40 transition-colors">
                  Add
                </button>
                <button onClick={() => setAdding(false)} className="text-xs text-gray-400 hover:text-gray-600 px-2 transition-colors">
                  Cancel
                </button>
              </div>
            </div>
          )}

          {!adding && editId === null && (
            <button onClick={startAdd}
              className="flex items-center gap-1.5 text-xs text-orange-500 hover:text-orange-600 transition-colors">
              <Plus size={12} />
              Add non-working period
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ── Date controls ─────────────────────────────────────────────────────────────

function DateControls({
  startDate, durationWeeks, onStart, onDuration, onAssign, busy,
}: {
  startDate: string; durationWeeks: number
  onStart: (d: string) => void; onDuration: (w: number) => void
  onAssign: () => void; busy: boolean
}) {
  const iw = interviewWindowDays(durationWeeks)
  return (
    <div className="flex items-end gap-4 flex-wrap bg-gray-50 border border-gray-100 rounded-2xl px-4 py-3 mb-4">
      <div>
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">Project start</p>
        <input type="date" value={startDate}
          onChange={e => onStart(e.target.value)}
          className="text-sm text-gray-900 border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-teal-400"
          style={{ colorScheme: 'light' }} />
      </div>
      <div>
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">Duration</p>
        <select value={durationWeeks} onChange={e => onDuration(Number(e.target.value))}
          className="text-sm text-gray-900 border border-gray-200 rounded-lg px-3 py-2 pr-8 bg-white focus:outline-none focus:ring-2 focus:ring-teal-400">
          {[4, 6, 8, 10, 12, 14, 16, 20].map(w => (
            <option key={w} value={w}>{w} weeks</option>
          ))}
        </select>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-gray-500 mb-2">
          Interview window:{' '}
          <span className="font-semibold text-teal-600">{iw / 7} weeks ({iw} days)</span>
          <span className="text-gray-400 ml-1">
            {durationWeeks < 7 ? '— minimum' : durationWeeks >= 12 ? '— extended' : '— recommended'}
          </span>
        </p>
        <button onClick={onAssign} disabled={busy}
          className="flex items-center gap-2 text-xs px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-40 transition-colors">
          <Wand2 size={12} className={busy ? 'animate-pulse' : ''} />
          Auto-assign milestone dates
        </button>
      </div>
    </div>
  )
}

// ── Milestone row ─────────────────────────────────────────────────────────────

function MilestoneRow({
  m, idx, slug, showInterviews, prevDueDate, locale, excludedDates,
}: {
  m: Milestone; idx: number; slug: string; showInterviews: boolean
  prevDueDate: string | null; locale: string; excludedDates: Set<string>
}) {
  const [expanded, setExpanded] = useState(false)
  const qc = useQueryClient()

  const patch = useMutation({
    mutationFn: (data: Parameters<typeof milestonesApi.update>[2]) =>
      milestonesApi.update(slug, m.id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['milestones', slug] }),
  })
  const remove = useMutation({
    mutationFn: () => milestonesApi.remove(slug, m.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['milestones', slug] }),
  })

  const state      = milestoneState(m)
  const badgeCls   = STATE_BADGE[state]
  const isComplete = m.status === 'complete'

  const phaseLabel = (() => {
    if (state === 'complete') return 'Complete'
    if (!m.due_date || !prevDueDate) return countdownLabel(m, excludedDates)
    const wd = libWorkingDaysBetween(prevDueDate, m.due_date, excludedDates)
    if (wd <= 0) return 'Same day'
    return `${wd} working day${wd !== 1 ? 's' : ''}`
  })()

  return (
    <div className={`border rounded-xl transition-all ${isComplete ? 'border-teal-100 bg-teal-50/30' : 'border-gray-100 bg-white'}`}>
      <div className="flex items-start gap-3 p-4">
        <span className="flex-shrink-0 w-6 h-6 rounded-full bg-gray-100 border border-gray-200 text-gray-500 text-[9px] font-bold flex items-center justify-center mt-0.5">
          {idx + 1}
        </span>
        <button
          onClick={() => patch.mutate({ status: isComplete ? 'pending' : 'complete' })}
          className="mt-0.5 flex-shrink-0 transition-colors"
          aria-label={isComplete ? 'Mark pending' : 'Mark complete'}
        >
          {isComplete
            ? <CheckCircle2 size={20} className="text-teal-500" />
            : <Circle size={20} className="text-gray-300" />}
        </button>

        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2 flex-wrap">
            <p className={`text-sm font-semibold leading-snug ${isComplete ? 'line-through text-gray-400' : 'text-gray-800'}`}>
              {m.title}
            </p>
            {phaseLabel && (
              <span className={`flex-shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${badgeCls}`}>
                {phaseLabel}
              </span>
            )}
          </div>

          {m.description && (
            <p className="text-xs text-gray-500 mt-1 leading-relaxed">{m.description}</p>
          )}

          <div className="flex items-center gap-3 mt-2 flex-wrap">
            <div className="flex items-center gap-1.5">
              <CalendarDays size={12} className="text-gray-400" />
              <input
                type="date" value={m.due_date ?? ''}
                onChange={e => patch.mutate({ due_date: e.target.value || null })}
                className="text-xs text-gray-600 border-0 bg-transparent focus:outline-none focus:ring-0 cursor-pointer p-0"
                style={{ colorScheme: 'light' }}
              />
              {m.due_date && (
                <span className="text-[10px] text-gray-400">
                  {formatDate(m.due_date, locale)}
                </span>
              )}
            </div>
            {showInterviews && (
              <button
                onClick={() => setExpanded(v => !v)}
                className="text-xs text-teal-600 hover:text-teal-700 flex items-center gap-0.5 transition-colors"
              >
                {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                {expanded ? 'Hide tracker' : 'View completion tracker'}
              </button>
            )}
          </div>
          {expanded && showInterviews && <InterviewCompletionPanel slug={slug} />}
        </div>

        <button
          onClick={() => remove.mutate()}
          className="text-gray-300 hover:text-red-400 transition-colors flex-shrink-0 mt-0.5"
          aria-label="Delete milestone"
        >
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  )
}

// ── Add milestone form ────────────────────────────────────────────────────────

function AddMilestoneForm({ slug, onDone }: { slug: string; onDone: () => void }) {
  const [title, setTitle]      = useState('')
  const [description, setDesc] = useState('')
  const [dueDate, setDueDate]  = useState('')
  const qc = useQueryClient()
  const create = useMutation({
    mutationFn: () => milestonesApi.create(slug, { title, description, due_date: dueDate || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['milestones', slug] }); onDone() },
  })
  return (
    <div className="border border-teal-200 rounded-xl bg-teal-50/40 p-4 space-y-3">
      <p className="text-xs font-bold text-teal-700 uppercase tracking-widest">New milestone</p>
      <input autoFocus value={title} onChange={e => setTitle(e.target.value)}
        placeholder="Milestone title"
        className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal-400 bg-white" />
      <input value={description} onChange={e => setDesc(e.target.value)}
        placeholder="Description (optional)"
        className="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal-400 bg-white" />
      <div className="flex items-center gap-2">
        <input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)}
          className="text-xs border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal-400 bg-white"
          style={{ colorScheme: 'light' }} />
        <button onClick={() => create.mutate()} disabled={!title.trim() || create.isPending}
          className="text-xs bg-teal-600 text-white rounded-lg px-4 py-2 hover:bg-teal-700 disabled:opacity-40 transition-colors">
          Add
        </button>
        <button onClick={onDone} className="text-xs text-gray-400 hover:text-gray-600 px-3 py-2 transition-colors">
          Cancel
        </button>
      </div>
    </div>
  )
}

// ── Summary stats ─────────────────────────────────────────────────────────────

function ScheduleSummary({ milestones }: { milestones: Milestone[] }) {
  const overdue  = milestones.filter(m => milestoneState(m) === 'overdue')
  const dueSoon  = milestones.filter(m => milestoneState(m) === 'due_soon')
  const complete = milestones.filter(m => m.status === 'complete')
  const next     = milestones
    .filter(m => m.status === 'pending' && m.due_date && daysBetween(todayStr(), m.due_date) >= 0)
    .sort((a, b) => (a.due_date ?? '').localeCompare(b.due_date ?? ''))[0]

  return (
    <div className="grid grid-cols-4 gap-3 mb-4">
      {[
        { label: 'Complete', value: complete.length, color: 'text-teal-600', bg: 'bg-teal-50 border-teal-100' },
        { label: 'Overdue',  value: overdue.length,  color: overdue.length  ? 'text-red-600'   : 'text-gray-400', bg: overdue.length  ? 'bg-red-50 border-red-100'     : 'bg-gray-50 border-gray-100' },
        { label: 'Due soon', value: dueSoon.length,  color: dueSoon.length  ? 'text-amber-600' : 'text-gray-400', bg: dueSoon.length  ? 'bg-amber-50 border-amber-100' : 'bg-gray-50 border-gray-100' },
        { label: 'Total',    value: milestones.length, color: 'text-gray-600', bg: 'bg-gray-50 border-gray-100' },
      ].map(({ label, value, color, bg }) => (
        <div key={label} className={`rounded-xl border p-3 ${bg}`}>
          <p className={`text-xl font-bold ${color}`}>{value}</p>
          <p className="text-xs text-gray-500 mt-0.5">{label}</p>
        </div>
      ))}
      {next && (
        <div className="col-span-4 rounded-xl border border-gray-100 bg-gray-50 p-3 flex items-center gap-2">
          <Clock size={14} className="text-gray-400 flex-shrink-0" />
          <p className="text-xs text-gray-600">
            <span className="font-semibold">Next: </span>{next.title}
            {next.due_date && <span className="text-gray-400 ml-1">— {countdownLabel(next)}</span>}
          </p>
        </div>
      )}
    </div>
  )
}

// ── PAM Setup Tab ─────────────────────────────────────────────────────────────

export default function PamSetupTab({ slug }: { slug: string }) {
  const [adding, setAdding]               = useState(false)
  const [schedStart, setSchedStart]       = useState(todayStr())
  const [durationWeeks, setDurationWeeks] = useState(8)
  const [initialized, setInitialized]     = useState(false)
  const [assignBusy, setAssignBusy]       = useState(false)
  const qc = useQueryClient()

  const { data: milestones = [], isLoading } = useQuery({
    queryKey: ['milestones', slug],
    queryFn:  () => milestonesApi.list(slug),
    enabled:  !!slug,
  })

  const { data: settings, isError: settingsError } = useQuery({
    queryKey: ['settings', slug],
    queryFn:  () => projectsApi.getSettings(slug),
    enabled:  !!slug,
  })

  const { data: nonWorkingRanges = [] } = useQuery({
    queryKey: ['nonworking', slug],
    queryFn:  () => nonworkingApi.list(slug),
    enabled:  !!slug,
  })

  const locale = settings?.locale ?? 'GB'

  const endDate  = addDays(schedStart, durationWeeks * 7)
  const holidays: PublicHoliday[] = locale
    ? getPublicHolidays(locale, schedStart, endDate)
    : []
  const excludedDates = buildExcludedDateSet(holidays, nonWorkingRanges)

  const saveSchedule = useCallback((start: string, weeks: number) => {
    if (!slug || !settings) return
    projectsApi.updateSettings(slug, { ...settings, sched_start: start, sched_duration_weeks: weeks })
      .catch(() => {})
  }, [slug, settings])

  useEffect(() => {
    if (initialized) return
    if (settings === undefined && !settingsError) return
    if (settings?.sched_start && settings?.sched_duration_weeks) {
      setSchedStart(settings.sched_start)
      setDurationWeeks(settings.sched_duration_weeks)
      setInitialized(true)
      return
    }
    if (!milestones.length) return
    const dates = milestones.map(m => m.due_date).filter(Boolean) as string[]
    if (dates.length >= 2) {
      const earliest = dates.reduce((a, b) => a < b ? a : b)
      const latest   = dates.reduce((a, b) => a > b ? a : b)
      const days     = daysBetween(earliest, latest)
      const inferred = Math.max(4, Math.ceil(days / 7) + 1)
      const snapped  = [4, 6, 8, 10, 12, 14, 16, 20].find(w => w >= inferred) ?? 20
      setSchedStart(earliest)
      setDurationWeeks(snapped)
      saveSchedule(earliest, snapped)
    }
    setInitialized(true)
  }, [milestones, settings, settingsError, initialized, saveSchedule])

  const seed = useMutation({
    mutationFn: () => milestonesApi.seed(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['milestones', slug] }),
  })

  const assignDates = async () => {
    if (!milestones.length) return
    setAssignBusy(true)
    try {
      const map = buildDateMap(milestones, schedStart, durationWeeks)
      await Promise.all(milestones.map(m => milestonesApi.update(slug, m.id, { due_date: map[m.id] })))
      await qc.invalidateQueries({ queryKey: ['milestones', slug] })
    } finally {
      setAssignBusy(false)
    }
  }

  const updateDates = useCallback(async (updates: { id: number; date: string }[]) => {
    if (!updates.length) return
    await Promise.all(updates.map(({ id, date }) => milestonesApi.update(slug, id, { due_date: date })))
    qc.invalidateQueries({ queryKey: ['milestones', slug] })
  }, [slug, qc])

  const sorted   = [...milestones].sort((a, b) =>
    a.sort_order !== b.sort_order ? a.sort_order - b.sort_order : a.id - b.id,
  )
  const overdue  = sorted.filter(m => milestoneState(m) === 'overdue')
  const pending  = sorted.filter(m => m.status === 'pending' && milestoneState(m) !== 'overdue')
  const complete = sorted.filter(m => m.status === 'complete')

  const prevDateByIndex = sorted.map((_, i) =>
    i === 0 ? null : (sorted[i - 1].due_date ?? null),
  )

  return (
    <div className="space-y-2">
      {/* Header row */}
      <div className="flex items-center justify-between gap-4 mb-2">
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Project Schedule</p>
        <div className="flex gap-2 flex-shrink-0">
          <button
            onClick={() => seed.mutate()} disabled={seed.isPending}
            title="Add any missing default milestones"
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:border-gray-400 hover:text-gray-900 transition-colors disabled:opacity-40"
          >
            <RefreshCw size={12} className={seed.isPending ? 'animate-spin' : ''} />
            Restore defaults
          </button>
          <button
            onClick={() => setAdding(true)}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-teal-600 text-white hover:bg-teal-700 transition-colors"
          >
            <Plus size={12} />
            Add milestone
          </button>
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-gray-400">Loading schedule…</p>
      ) : (
        <>
          <ScheduleSummary milestones={milestones} />

          <DateControls
            startDate={schedStart}
            durationWeeks={durationWeeks}
            onStart={d  => { setSchedStart(d);     setInitialized(true); saveSchedule(d, durationWeeks) }}
            onDuration={w => { setDurationWeeks(w); setInitialized(true); saveSchedule(schedStart, w) }}
            onAssign={assignDates}
            busy={assignBusy}
          />

          {milestones.length > 0 && (
            <GanttChart
              milestones={milestones}
              startDate={schedStart}
              durationWeeks={durationWeeks}
              onUpdateDates={updateDates}
              holidays={holidays}
              nonWorkingRanges={nonWorkingRanges}
              locale={locale}
            />
          )}

          <NonWorkingPanel slug={slug} locale={locale} />

          {adding && (
            <div className="mb-2">
              <AddMilestoneForm slug={slug} onDone={() => setAdding(false)} />
            </div>
          )}

          {milestones.length > 0 && (
            <div className="mt-2">
              <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">
                Milestone detail
              </h2>

              {overdue.length > 0 && (
                <section className="mb-4">
                  <div className="flex items-center gap-2 mb-2">
                    <AlertTriangle size={12} className="text-red-400" />
                    <p className="text-[10px] font-bold text-red-400 uppercase tracking-widest">Overdue</p>
                  </div>
                  <div className="space-y-2">
                    {overdue.map(m => {
                      const si = sorted.indexOf(m)
                      return (
                        <MilestoneRow key={m.id} m={m} idx={si} slug={slug}
                          showInterviews={m.milestone_key === 'interviews_complete'}
                          prevDueDate={prevDateByIndex[si]}
                          locale={locale}
                          excludedDates={excludedDates} />
                      )
                    })}
                  </div>
                </section>
              )}

              {pending.length > 0 && (
                <section className="mb-4">
                  <div className="flex items-center gap-2 mb-2">
                    <Clock size={12} className="text-gray-400" />
                    <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Upcoming</p>
                  </div>
                  <div className="space-y-2">
                    {pending.map(m => {
                      const si = sorted.indexOf(m)
                      return (
                        <MilestoneRow key={m.id} m={m} idx={si} slug={slug}
                          showInterviews={m.milestone_key === 'interviews_complete'}
                          prevDueDate={prevDateByIndex[si]}
                          locale={locale}
                          excludedDates={excludedDates} />
                      )
                    })}
                  </div>
                </section>
              )}

              {complete.length > 0 && (
                <section>
                  <div className="flex items-center gap-2 mb-2">
                    <CheckCircle2 size={12} className="text-teal-400" />
                    <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Completed</p>
                  </div>
                  <div className="space-y-2">
                    {complete.map(m => {
                      const si = sorted.indexOf(m)
                      return (
                        <MilestoneRow key={m.id} m={m} idx={si} slug={slug}
                          showInterviews={false}
                          prevDueDate={prevDateByIndex[si]}
                          locale={locale}
                          excludedDates={excludedDates} />
                      )
                    })}
                  </div>
                </section>
              )}
            </div>
          )}

          {milestones.length === 0 && (
            <div className="text-center py-12">
              <p className="text-gray-400 text-sm mb-3">No milestones yet.</p>
              <button onClick={() => seed.mutate()}
                className="text-sm text-teal-600 hover:text-teal-700 underline">
                Load default schedule
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
