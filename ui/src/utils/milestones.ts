// ui/src/utils/milestones.ts
// How a milestone stands against what it was promised.
//
// Three dates. baseline_date is what was promised, set at activation and moved only by an
// explicit re-baseline. due_date is what is currently expected, and is editable.
// completed_at is what happened.
//
// Measuring against due_date alone - which is what this file did before baselines existed
// - reports a project that slips as often as it re-plans as perfectly on track, because
// every milestone met the date it was most recently given.
import { workingDaysBetween } from './holidays'

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
 * While outstanding the forecast is the **later of the plan and today**: a promised date
 * that has already passed can no longer be met, whatever the plan still says. Without
 * that, a milestone nobody re-planned and nobody delivered reported as on plan, and the
 * delivery headline read "on the promised date" over work already overdue - the exact
 * false reassurance a baseline exists to remove.
 *
 * `today` is a parameter, not read from the clock, so every caller is deterministic and
 * the tests do not drift into passing or failing with the calendar.
 *
 * Both measures return null rather than zero when nothing moved, so a caller renders a
 * badge on truth rather than on a number.
 */
export function milestoneVariance(
  m: MilestoneVarianceInput,
  excluded?: Set<string>,
  today: string = new Date().toISOString().slice(0, 10),
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
  // Delivered: what happened. Outstanding: the plan, or today if the plan is already
  // behind us - a date that has passed is no longer a forecast.
  const against = complete
    ? m.completed_at
    : (m.due_date && m.due_date > today ? m.due_date : (m.due_date ? today : null))
  const slip = gap(m.baseline_date, against)
  const replan = gap(m.baseline_date, m.due_date)

  if (slip === null) {
    // Delivered on or before the promise. If the plan had moved out and it was still met,
    // that is a recovery rather than business as usual, and worth saying so.
    return { state: replan !== null && complete ? 'recovered' : 'on_plan', slip, replan }
  }
  return { state: complete ? 'late' : 'at_risk', slip, replan }
}
