// ui/src/__tests__/PamSetupMilestones.test.tsx
//
// The milestone rows had no component tests - none existed for this file at all, and the
// variance work went in verified only by tsc and reading. These cover the three things a
// reader of the schedule relies on: the tickbox records a completion, the badges say what
// happened against the promise, and the promised date is not editable in place.
//
// The pure arithmetic is covered in milestoneVariance.test.ts. What is covered here is the
// wiring - that the row asks the calculation the right question and renders its answer.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import PamSetupTab from '../components/tabs/PamSetupTab'
import type { Milestone } from '../types'

const { milestones, update } = vi.hoisted(() => {
  const base = {
    slug: 'acme', description: '', notes: '', created_at: '2026-07-01',
  }
  return {
    update: vi.fn().mockResolvedValue({}),
    milestones: [
      // Delivered two working days after it was promised, on the date it was promised -
      // so measuring against the plan alone would call this on time.
      { ...base, id: 1, milestone_key: 'a', title: 'Project initiation', sort_order: 1,
        due_date: '2026-08-14', baseline_date: '2026-08-14',
        status: 'complete', completed_at: '2026-08-18' },
      // Re-planned a week out and not yet delivered: the plan has moved past the promise.
      { ...base, id: 2, milestone_key: 'b', title: 'Discovery documents', sort_order: 2,
        due_date: '2026-08-28', baseline_date: '2026-08-21',
        status: 'pending', completed_at: null },
      // Added after the plan was agreed: no promise, so no variance can be claimed.
      { ...base, id: 3, milestone_key: 'c', title: 'Extra workshop', sort_order: 3,
        due_date: '2026-09-04', baseline_date: null,
        status: 'pending', completed_at: null },
    ] as Milestone[],
  }
})

vi.mock('../api/endpoints', () => ({
  milestonesApi: {
    list: vi.fn().mockResolvedValue(milestones),
    update,
    remove: vi.fn(),
    create: vi.fn(),
    seed: vi.fn(),
  },
  projectsApi: {
    getSettings: vi.fn().mockResolvedValue({ locale: 'GB' }),
    updateSettings: vi.fn().mockResolvedValue({}),
  },
  nonworkingApi: {
    list: vi.fn().mockResolvedValue([]),
    create: vi.fn(), update: vi.fn(), remove: vi.fn(),
  },
}))

function renderTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <PamSetupTab slug="acme" />
    </QueryClientProvider>,
  )
}

describe('the milestone rows', () => {
  it('reports a milestone delivered after its promise as late', async () => {
    renderTab()
    // Fri 14 Aug to Tue 18 Aug: two working days. Its plan never moved, so a calculation
    // measuring against due_date would show nothing here at all.
    await waitFor(() =>
      expect(screen.getByTestId('milestone-variance-1')).toHaveTextContent('2 days late'))
  })

  it('reports an outstanding milestone re-planned past its promise as at risk', async () => {
    renderTab()
    // Fri 21 Aug promised, Fri 28 Aug planned: five working days, and nothing is overdue
    // yet. This is the state the schedule could not express before baselines.
    await waitFor(() =>
      expect(screen.getByTestId('milestone-variance-2')).toHaveTextContent('5 days at risk'))
  })

  it('reports work added after the plan as added scope, not as on plan', async () => {
    renderTab()
    await waitFor(() =>
      expect(screen.getByTestId('milestone-variance-3')).toHaveTextContent('Added scope'))
  })

  it('shows the promised date only where the plan has moved away from it', async () => {
    renderTab()
    // Milestone 2 was re-planned, so its promise is worth showing. Milestone 1 still sits
    // on its promise, and repeating the same date twice was the confusion this replaced.
    await waitFor(() =>
      expect(screen.getByTestId('milestone-promised-2')).toHaveTextContent('2026-08-21'))
    expect(screen.queryByTestId('milestone-promised-1')).toBeNull()
  })

  it('does not let the promised date be edited in place', async () => {
    // Moving a promise is re-baselining - approver-gated, with a stated reason. A date
    // picker here would route round that entirely.
    renderTab()
    const promised = await screen.findByTestId('milestone-promised-2')
    expect(promised.tagName).not.toBe('INPUT')
    expect(promised.closest('input')).toBeNull()
  })

  it('records the actual date when a milestone is ticked', async () => {
    renderTab()
    await userEvent.click(await screen.findByTestId('milestone-tick-2'))
    // The server stamps the date; the row's job is to say it is complete and let the
    // server decide when. Sending a date from the browser would use the reader's clock,
    // which is a different day from the project's for a good part of every day.
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith('acme', 2, { status: 'complete' }))
  })

  it('lets the actual date be corrected after the fact', async () => {
    // Milestones are ticked off retrospectively far more often than on the day, and if the
    // only way to log one is to have ticked it on the day, the actual dates become fiction.
    renderTab()
    const actual = await screen.findByTestId('milestone-actual-1')
    expect(actual.tagName).toBe('INPUT')
    expect(actual).toHaveValue('2026-08-18')
  })
})
