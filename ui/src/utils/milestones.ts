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

export type MilestoneVarianceState =
  | 'added_scope' | 'on_plan' | 'late' | 'at_risk' | 'recovered'

export interface MilestoneVariance {
  /** What kind of variance this is - see the table in the design. */
  state: MilestoneVarianceState
  /** Baseline to actual once complete, or to the current plan while outstanding. */
  slip: number | null
  /** Baseline to the current plan. How far the plan itself has moved. */
  replan: number | null
}

export interface MilestoneVarianceInput {
  baseline_date?: string | null
  due_date: string | null
  completed_at?: string | null
  status: string
}

/**
 * How a milestone stands against what it was promised.
 *
 * Two measures, routinely conflated and kept apart here. **Slip** is baseline to actual
 * once delivered, and baseline to the current plan while outstanding - so drift shows
 * before a date arrives rather than after, which is the only warning worth having.
 * **Re-plan** is baseline to the current plan: how far the plan itself moved, regardless
 * of delivery. A milestone can be delivered exactly on its current plan and be three weeks
 * late against what was promised, and a client asks about both.
 *
 * Both return null rather than zero when nothing moved, matching daysLate, so a caller
 * renders a badge on truth rather than on a number.
 */
export function milestoneVariance(
  m: MilestoneVarianceInput,
  excluded?: Set<string>,
): MilestoneVariance {
  // No baseline, no promise to measure against - and this must win over every other
  // check. Work added after activation is added scope, never on-plan delivery.
  if (!m.baseline_date) return { state: 'added_scope', slip: null, replan: null }

  const gap = (from: string, to: string | null | undefined): number | null => {
    if (!to || to <= from) return null
    const days = workingDaysBetween(from, to, excluded)
    return days > 0 ? days : null
  }

  const complete = m.status === 'complete'
  const against = complete ? m.completed_at : m.due_date
  const slip = gap(m.baseline_date, against)
  const replan = gap(m.baseline_date, m.due_date)

  if (slip === null) {
    // Delivered on or before the promise. If the plan had moved out and it was still met,
    // that is a recovery rather than business as usual, and worth saying so.
    return { state: replan !== null && complete ? 'recovered' : 'on_plan', slip, replan }
  }
  return { state: complete ? 'late' : 'at_risk', slip, replan }
}
