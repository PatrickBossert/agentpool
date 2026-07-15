// ui/src/components/GanttReadOnly.tsx
// Read-only version of the Schedule page Gantt chart.
// Same visual as GanttChart but no drag interaction.

import { formatDate, formatDateShort, workingDaysBetween, buildExcludedDateSet } from '../utils/holidays'
import type { PublicHoliday } from '../utils/holidays'
import type { NonWorkingRange } from '../types'

// ── Shared helpers (duplicated from Schedule.tsx to avoid a circular import) ──

export function todayStr(): string {
  return new Date().toISOString().slice(0, 10)
}

export function addDays(dateStr: string, days: number): string {
  const d = new Date(dateStr + 'T00:00:00')
  d.setDate(d.getDate() + Math.round(days))
  return d.toISOString().slice(0, 10)
}

export function daysBetween(a: string, b: string): number {
  return Math.round(
    (new Date(b + 'T00:00:00').getTime() - new Date(a + 'T00:00:00').getTime()) / 86_400_000,
  )
}

export function inferSchedule(dueDates: string[]): { schedStart: string; durationWeeks: number } {
  if (dueDates.length < 2) {
    return { schedStart: todayStr(), durationWeeks: 8 }
  }
  const earliest = dueDates.reduce((a, b) => a < b ? a : b)
  const latest   = dueDates.reduce((a, b) => a > b ? a : b)
  const days     = daysBetween(earliest, latest)
  const inferred = Math.max(4, Math.ceil(days / 7) + 1)
  const snapped  = ([4, 6, 8, 10, 12, 14, 16, 20] as number[]).find(w => w >= inferred) ?? 20
  return { schedStart: earliest, durationWeeks: snapped }
}

// ── Styling ───────────────────────────────────────────────────────────────────

type MilestoneRAG = 'complete' | 'overdue' | 'due_soon' | 'on_track' | 'unscheduled'

function milestoneState(status: 'pending' | 'complete', due_date: string | null): MilestoneRAG {
  if (status === 'complete') return 'complete'
  if (!due_date) return 'unscheduled'
  const diff = daysBetween(todayStr(), due_date)
  if (diff < 0) return 'overdue'
  if (diff <= 3) return 'due_soon'
  return 'on_track'
}

const GANTT_STYLE: Record<MilestoneRAG, { border: string; bg: string; text: string }> = {
  complete:    { border: 'border-teal-500',  bg: 'bg-teal-500',  text: 'text-white' },
  overdue:     { border: 'border-red-500',   bg: 'bg-red-500',   text: 'text-white' },
  due_soon:    { border: 'border-amber-400', bg: 'bg-amber-400', text: 'text-white' },
  on_track:    { border: 'border-green-400', bg: 'bg-white',     text: 'text-green-600' },
  unscheduled: { border: 'border-gray-300',  bg: 'bg-gray-100',  text: 'text-gray-400' },
}

// ── Component ─────────────────────────────────────────────────────────────────

const GANTT_H = 220
const LABEL_H = 50

export interface GanttMilestone {
  id: number
  milestone_key: string
  title: string
  due_date: string | null
  status: 'pending' | 'complete'
  sort_order: number
  rag?: MilestoneRAG
}

interface Props {
  milestones: GanttMilestone[]
  startDate: string
  durationWeeks: number
  holidays: PublicHoliday[]
  nonWorkingRanges: NonWorkingRange[]
  locale: string
}

export default function GanttReadOnly({
  milestones, startDate, durationWeeks, holidays, nonWorkingRanges, locale,
}: Props) {
  const totalDays = durationWeeks * 7
  const endDate   = addDays(startDate, totalDays)
  const today     = todayStr()

  const sorted = [...milestones].sort((a, b) =>
    a.sort_order !== b.sort_order ? a.sort_order - b.sort_order : a.id - b.id,
  )

  function toPct(date: string): number {
    const raw = daysBetween(startDate, date) / totalDays
    return Math.max(2, Math.min(98, raw * 100))
  }

  const launchM    = sorted.find(m => m.milestone_key === 'interviews_launched')
  const completeM  = sorted.find(m => m.milestone_key === 'interviews_complete')
  const lDate      = launchM?.due_date ?? null
  const cDate      = completeM?.due_date ?? null

  const todayPct     = toPct(today)
  const todayInRange = today >= startDate && today <= endDate

  const visibleHolidays = holidays.filter(h => h.date >= startDate && h.date <= endDate)

  return (
    <div className="mb-2 select-none">
      <div
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

        {/* Holiday bands — same style as non-working periods */}
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
          if (!m.due_date) return null
          const xPct    = toPct(m.due_date)
          const state   = m.rag ?? milestoneState(m.status, m.due_date)
          const { border, bg, text } = GANTT_STYLE[state]
          const isAbove = idx % 2 === 0
          const shortDate = formatDateShort(m.due_date, locale)

          return (
            <div
              key={m.id}
              className="absolute"
              style={{
                left: `${xPct}%`,
                top: 0, bottom: 0, width: 80,
                transform: 'translateX(-50%)',
                pointerEvents: 'none',
                zIndex: 10,
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

              <div style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)' }}>
                <div className={`w-7 h-7 rounded-full border-2 flex items-center justify-center text-[9px] font-bold ${border} ${bg} ${text}`}>
                  {idx + 1}
                </div>
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
          {lDate && cDate && (() => {
            const excluded = buildExcludedDateSet(visibleHolidays, nonWorkingRanges.filter(r => r.end_date >= startDate && r.start_date <= endDate))
            const wd = workingDaysBetween(lDate, cDate, excluded)
            return (
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded bg-teal-50 border border-teal-300 inline-block" />
                {`Interview window (${wd} working day${wd !== 1 ? 's' : ''})`}
              </span>
            )
          })()}
          {(nonWorkingRanges.some(r => r.end_date >= startDate && r.start_date <= endDate) || visibleHolidays.length > 0) && (() => {
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
        </div>
        <span>{formatDate(endDate, locale)}</span>
      </div>
    </div>
  )
}
