// ui/src/__tests__/PamReportExport.test.ts
//
// The exported pack is what reaches a client, so it has to agree with the screen it came
// from. It did not: the excluded-date set was built inside the Progress Against Plan
// render callback, reachable from the timeline and not from the print path, so the export
// counted weekends only and reported a slip spanning a holiday as a day longer than the
// app showed it.
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest'

import { buildPrintHtml } from '../components/PamReportView'
import type { PamReport, PamReportMilestone } from '../types'

// `milestoneVariance` defaults `today` to the real clock, and these tests exercise components
// that legitimately read it - PamReportView and PamSetupTab render a live view, so threading a
// date through them would be wrong. The clock is faked instead.
//
// Fixed once already in milestoneVariance.test.ts on 19 Aug 2026, where every call was given an
// explicit `today`. That fix was applied to the file that failed and not to the *callers* of the
// same function, so the same defect detonated here a fortnight later. Pin the clock in any test
// that reaches milestoneVariance, however indirectly.
const FIXED_TODAY = new Date('2026-08-14T09:00:00Z')

beforeAll(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); vi.setSystemTime(FIXED_TODAY) })
afterAll(() => { vi.useRealTimers() })


function milestone(over: Partial<PamReportMilestone> = {}): PamReportMilestone {
  return {
    id: 1, milestone_key: 'value_chain_approved', title: 'Value chain approved',
    due_date: '2026-08-14', status: 'complete', completed_at: '2026-08-19',
    baseline_date: '2026-08-14',
    rag: 'complete', days_delta: null, sort_order: 1, ...over,
  }
}

function report(milestones: PamReportMilestone[]): PamReport {
  return {
    generated_at: '2026-08-04T00:00:00Z', project_slug: 'acme', client_name: 'Acme',
    sector: 'utilities', overall_health: 'green', health_summary: '',
    milestones, milestones_complete: 1, milestones_total: 1,
    crews: [], risks: [], issues: [], interview_tracker: null,
    pending_reviews: 0, stakeholder_count: 0, doc_count: 0, change_summary: '',
  } as unknown as PamReport
}

describe('the exported Progress Against Plan table', () => {
  it('shows the planned date and the actual date, not the planned date alone', () => {
    const html = buildPrintHtml(report([milestone()]))
    expect(html).toContain('2026-08-14')
    expect(html).toContain('2026-08-19')
    expect(html).toContain('<th>Planned</th>')
    expect(html).toContain('<th>Actual</th>')
  })

  it('counts the slip in working days, not calendar days', () => {
    // Fri 14 Aug to Wed 19 Aug: five calendar days, three working days.
    expect(buildPrintHtml(report([milestone()]))).toContain('3wd late')
  })

  it("honours the project's excluded dates, as the on-screen timeline does", () => {
    // Mon 17 Aug excluded: the same slip is two working days, not three. Before the
    // excluded set was threaded into the export, this said 3 while the screen said 2.
    const html = buildPrintHtml(report([milestone()]), new Set(['2026-08-17']))
    expect(html).toContain('2wd late')
    expect(html).not.toContain('3wd late')
  })

  it('shows a dash rather than a lateness for a milestone still outstanding', () => {
    const html = buildPrintHtml(report([
      milestone({ status: 'pending', completed_at: null, rag: 'on_track' }),
    ]))
    expect(html).not.toContain('wd late')
  })

  it('shows no lateness for one delivered to plan', () => {
    const html = buildPrintHtml(report([milestone({ completed_at: '2026-08-14' })]))
    expect(html).toContain('2026-08-14')
    expect(html).not.toContain('wd late')
  })
})


describe('the delivery movement headline', () => {
  it('states how far delivery has moved, in working days', () => {
    const html = buildPrintHtml(report([
      milestone({ id: 1, baseline_date: '2026-08-14', due_date: '2026-08-14',
                  completed_at: '2026-08-14', status: 'complete' }),
      milestone({ id: 2, baseline_date: '2026-08-21', due_date: '2026-08-28',
                  completed_at: null, status: 'pending', sort_order: 2 }),
    ]))
    expect(html).toContain('5 working days')
  })

  it('reads the movement from the last baselined milestone, not the last one', () => {
    // A single piece of added scope on the end would otherwise silently become the
    // project's delivery date - a number put in front of a client measuring work nobody
    // committed to.
    const html = buildPrintHtml(report([
      milestone({ id: 1, baseline_date: '2026-08-14', due_date: '2026-08-21',
                  completed_at: null, status: 'pending' }),
      milestone({ id: 2, baseline_date: null, due_date: '2026-12-01',
                  completed_at: null, status: 'pending', sort_order: 2 }),
    ]))
    // The added-scope milestone still appears in the table - it is real work - so its
    // date being present proves nothing. What discriminates is the headline: reading the
    // movement from it would find no baseline, report zero, and say "on the promised
    // date" while the project is a week behind.
    expect(html).toContain('5 working days')
    expect(html).not.toContain('on the promised date')
  })

  it('says delivery is on the promised date when nothing has moved', () => {
    const html = buildPrintHtml(report([
      milestone({ id: 1, baseline_date: '2026-08-14', due_date: '2026-08-14',
                  completed_at: '2026-08-14', status: 'complete' }),
    ]))
    expect(html).toContain('on the promised date')
    expect(html).not.toContain('working days')
  })

  it('says nothing about movement when nothing has a baseline', () => {
    // Before activation there is no promise, so there is no movement to report - and a
    // zero would read as "on plan" against a plan that was never agreed.
    const html = buildPrintHtml(report([
      milestone({ id: 1, baseline_date: null, due_date: '2026-08-14',
                  completed_at: null, status: 'pending' }),
    ]))
    expect(html).not.toContain('working days')
    expect(html).not.toContain('on the promised date')
  })
})

describe('the exported table carries the promise', () => {
  it('shows the promised date in its own column', () => {
    const html = buildPrintHtml(report([
      milestone({ baseline_date: '2026-08-10', due_date: '2026-08-14',
                  completed_at: '2026-08-14', status: 'complete' }),
    ]))
    expect(html).toContain('<th>Promised</th>')
    expect(html).toContain('2026-08-10')
  })

  it('reports a milestone delivered on a revised plan as late against the promise', () => {
    // daysLate measured against due_date and reported this as on time, which is the
    // defect the baseline exists to expose.
    const html = buildPrintHtml(report([
      milestone({ baseline_date: '2026-08-10', due_date: '2026-08-14',
                  completed_at: '2026-08-14', status: 'complete' }),
    ]))
    expect(html).toContain('4wd late')
  })
})
