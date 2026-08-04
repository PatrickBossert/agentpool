// ui/src/__tests__/PamReportExport.test.ts
//
// The exported pack is what reaches a client, so it has to agree with the screen it came
// from. It did not: the excluded-date set was built inside the Progress Against Plan
// render callback, reachable from the timeline and not from the print path, so the export
// counted weekends only and reported a slip spanning a holiday as a day longer than the
// app showed it.
import { describe, it, expect } from 'vitest'

import { buildPrintHtml } from '../components/PamReportView'
import type { PamReport, PamReportMilestone } from '../types'

function milestone(over: Partial<PamReportMilestone> = {}): PamReportMilestone {
  return {
    id: 1, milestone_key: 'value_chain_approved', title: 'Value chain approved',
    due_date: '2026-08-14', status: 'complete', completed_at: '2026-08-19',
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
