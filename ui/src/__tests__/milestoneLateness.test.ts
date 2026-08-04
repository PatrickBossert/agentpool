// ui/src/__tests__/milestoneLateness.test.ts
//
// How late a milestone was, in working days. Working rather than calendar because every
// other interval in this schedule is expressed that way - the phase gaps between
// milestones use the same helper and honour the same excluded dates - and two units in
// one view invite the reader to compare numbers that are not comparable.
import { describe, it, expect } from 'vitest'

import { daysLate } from '../utils/milestones'

describe('daysLate', () => {
  it('is null while a milestone has no actual date', () => {
    // Outstanding is not late. Nothing is known yet about when it will be reached.
    expect(daysLate({ due_date: '2026-08-14', completed_at: null })).toBeNull()
  })

  it('is null when it has no planned date to be late against', () => {
    expect(daysLate({ due_date: null, completed_at: '2026-08-14' })).toBeNull()
  })

  it('is null when it was reached on the day', () => {
    // Zero would render a "0 days late" badge on a milestone delivered to plan.
    expect(daysLate({ due_date: '2026-08-14', completed_at: '2026-08-14' })).toBeNull()
  })

  it('is null when it was reached early', () => {
    expect(daysLate({ due_date: '2026-08-14', completed_at: '2026-08-10' })).toBeNull()
  })

  it('counts the working days between plan and actual', () => {
    // Fri 14 Aug 2026 to Mon 17 Aug: one working day, not three calendar days. A calendar
    // count would report every weekend slip as worse than it was.
    expect(daysLate({ due_date: '2026-08-14', completed_at: '2026-08-17' })).toBe(1)
  })

  it('skips a weekend inside a longer slip', () => {
    // Fri 14 Aug to Fri 21 Aug: seven calendar days, five working days.
    expect(daysLate({ due_date: '2026-08-14', completed_at: '2026-08-21' })).toBe(5)
  })

  it("skips the project's own non-working dates", () => {
    // Mon 17 Aug excluded: Fri 14 to Tue 18 is one working day, not two.
    const excluded = new Set(['2026-08-17'])
    expect(daysLate({ due_date: '2026-08-14', completed_at: '2026-08-18' }, excluded)).toBe(1)
  })
})
