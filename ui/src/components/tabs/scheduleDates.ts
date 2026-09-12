// ui/src/components/tabs/scheduleDates.ts
//
// The date arithmetic the project schedule is read and edited by, held once because the
// schedule now renders on two tabs.
//
// `ProjectScheduleSetup` (Setup - how the engagement is configured) and `MilestoneStatusPanel`
// (Status - what the engagement is doing) are two components over the same milestone rows. A
// second copy of `milestoneState` would be a second opinion about whether a milestone is
// overdue, and the two tabs would disagree in front of the same reader.
//
// These read the wall clock deliberately: both callers render a live view of today's schedule.
// Any test that reaches them must pin the clock - see milestoneClockDiscipline.test.ts.
import type { Milestone } from '../../types'
import { workingDaysBetween as libWorkingDaysBetween } from '../../utils/holidays'

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

export type MilestoneRAG = 'complete' | 'overdue' | 'due_soon' | 'on_track' | 'unscheduled'

export function milestoneState(m: Pick<Milestone, 'status' | 'due_date'>): MilestoneRAG {
  if (m.status === 'complete') return 'complete'
  if (!m.due_date) return 'unscheduled'
  const diff = daysBetween(todayStr(), m.due_date)
  if (diff < 0) return 'overdue'
  if (diff <= 3) return 'due_soon'
  return 'on_track'
}

export function countdownLabel(m: Milestone, excludedDates?: Set<string>): string {
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
