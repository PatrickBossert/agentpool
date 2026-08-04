// ui/src/utils/milestones.ts
// How a milestone's actual completion compares with its plan.
//
// A milestone carries two dates: due_date, when it was planned, and completed_at, when it
// was actually reached. Slippage is the difference, and it is the only thing that makes
// tracking against plan possible - a list of completed milestones with no actual dates
// says a project finished everything, and nothing about whether it finished on time.
import { workingDaysBetween } from './holidays'

export interface MilestoneDates {
  due_date: string | null
  completed_at?: string | null
}

/**
 * Working days between a milestone's plan and its actual completion, or null when the
 * question does not arise - still outstanding, never scheduled, or reached on time or early.
 *
 * Working rather than calendar days, matching every other interval in this schedule: the
 * phase gaps between milestones use the same helper and honour the same excluded dates.
 * Two units in one view invite the reader to compare numbers that are not comparable, and
 * a calendar count reports every weekend slip as worse than it was.
 *
 * Null rather than zero for an on-time milestone, so a caller can render a badge on truth
 * rather than on a number - "0 days late" against work delivered to plan is noise.
 */
export function daysLate(m: MilestoneDates, excluded?: Set<string>): number | null {
  if (!m.due_date || !m.completed_at) return null
  if (m.completed_at <= m.due_date) return null
  const late = workingDaysBetween(m.due_date, m.completed_at, excluded)
  return late > 0 ? late : null
}
