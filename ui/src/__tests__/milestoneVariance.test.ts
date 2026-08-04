// ui/src/__tests__/milestoneVariance.test.ts
//
// One calculation, three consumers: the milestone list, Progress Against Plan, and the
// exported pack. Three implementations of the same arithmetic disagree the first time one
// changes, which has already happened once on the export path.
//
// Every interval is in working days with the project's excluded dates, matching the rest
// of the schedule. Two units in one view invite the reader to compare numbers that are not
// comparable.
import { describe, it, expect } from 'vitest'

import { milestoneVariance } from '../utils/milestones'

// Fri 14 Aug 2026 is the promise and the plan. Nothing has moved.
const base = {
  status: 'pending',
  baseline_date: '2026-08-14',
  due_date: '2026-08-14',
  completed_at: null as string | null,
}

describe('milestoneVariance', () => {
  it('reports work with no baseline as added scope, never as on plan', () => {
    // A project that adds five milestones and delivers them against no baseline has not
    // delivered its plan. Treating an absent baseline as no variance reports scope growth
    // as success.
    const v = milestoneVariance({ ...base, baseline_date: null })
    expect(v.state).toBe('added_scope')
    expect(v.slip).toBeNull()
    expect(v.replan).toBeNull()
  })

  it('reports an outstanding milestone already past its baseline as at risk', () => {
    // The state the previous view could not express: not yet due, so it rendered green,
    // while its current plan had already moved past what was promised.
    const v = milestoneVariance({ ...base, due_date: '2026-08-21' })
    expect(v.state).toBe('at_risk')
    expect(v.slip).toBe(5)
  })

  it('measures slip against the actual date once complete', () => {
    const v = milestoneVariance({ ...base, status: 'complete', completed_at: '2026-08-19' })
    expect(v.state).toBe('late')
    expect(v.slip).toBe(3)
  })

  it('measures slip against the current plan while outstanding', () => {
    // A fixture of only completed milestones cannot tell the two apart, and the
    // outstanding case is the one that gives warning while there is still time.
    expect(milestoneVariance({ ...base, due_date: '2026-08-19' }).slip).toBe(3)
  })

  it('separates re-planning from delivery', () => {
    // Delivered exactly on a revised plan: nothing late against that plan, three days
    // against what was promised. One number cannot carry both answers.
    const v = milestoneVariance({
      ...base, due_date: '2026-08-19', status: 'complete', completed_at: '2026-08-19',
    })
    expect(v.replan).toBe(3)
    expect(v.slip).toBe(3)
  })

  it('reports a milestone re-planned late but delivered on the promise as recovered', () => {
    const v = milestoneVariance({
      ...base, due_date: '2026-08-21', status: 'complete', completed_at: '2026-08-14',
    })
    expect(v.state).toBe('recovered')
    expect(v.slip).toBeNull()
    expect(v.replan).toBe(5)
  })

  it('is on plan when nothing moved', () => {
    const v = milestoneVariance({ ...base, status: 'complete', completed_at: '2026-08-14' })
    expect(v.state).toBe('on_plan')
    expect(v.slip).toBeNull()
    expect(v.replan).toBeNull()
  })

  it('is on plan when delivered early', () => {
    const v = milestoneVariance({ ...base, status: 'complete', completed_at: '2026-08-11' })
    expect(v.state).toBe('on_plan')
    expect(v.slip).toBeNull()
  })

  it("honours the project's excluded dates", () => {
    // Mon 17 Aug excluded: Fri 14 to Tue 18 is one working day, not two.
    const v = milestoneVariance({ ...base, due_date: '2026-08-18' }, new Set(['2026-08-17']))
    expect(v.slip).toBe(1)
  })

  it('is on plan when it has no dates at all to compare', () => {
    // A baselined milestone whose plan was later cleared. Nothing can be said, and
    // saying "late" would be an invention.
    const v = milestoneVariance({ ...base, due_date: null })
    expect(v.slip).toBeNull()
    expect(v.state).toBe('on_plan')
  })
})

describe('a promised date that has passed', () => {
  // `today` is a parameter rather than read from the clock, so these are deterministic.
  // Fri 14 Aug 2026 is the promise and the plan throughout.
  const TUE_18 = '2026-08-18'

  it('reports an overdue milestone as at risk, though nothing was re-planned', () => {
    // The gap this closes. Slip measured baseline -> due_date is zero when nothing moved,
    // so an overdue milestone read as on plan while the delivery headline said "on the
    // promised date" - the exact false reassurance baselines exist to remove.
    const v = milestoneVariance({ ...base }, undefined, TUE_18)
    expect(v.state).toBe('at_risk')
    expect(v.slip).toBe(2)
  })

  it('leaves a milestone that is not yet due on plan', () => {
    // Nothing has gone wrong yet. Reporting a slip here would cry wolf on every project.
    expect(milestoneVariance({ ...base }, undefined, '2026-08-12').state).toBe('on_plan')
  })

  it('takes the later of the plan and today when both have passed', () => {
    // Re-planned to Tue 18 and still not delivered on Thu 20: the forecast is now, not the
    // plan it has already missed.
    const v = milestoneVariance({ ...base, due_date: TUE_18 }, undefined, '2026-08-20')
    expect(v.slip).toBe(4)
    expect(v.replan).toBe(2)
  })

  it('leaves a completed milestone untouched by today', () => {
    // Delivered on the promise a fortnight ago is still delivered on the promise.
    const v = milestoneVariance(
      { ...base, status: 'complete', completed_at: '2026-08-14' }, undefined, '2026-08-28',
    )
    expect(v.state).toBe('on_plan')
    expect(v.slip).toBeNull()
  })

  it("honours excluded dates when measuring against today", () => {
    const v = milestoneVariance({ ...base }, new Set(['2026-08-17']), TUE_18)
    expect(v.slip).toBe(1)
  })
})
