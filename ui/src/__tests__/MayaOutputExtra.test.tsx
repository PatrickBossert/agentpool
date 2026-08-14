// ui/src/__tests__/MayaOutputExtra.test.tsx
// Level carries the tier, perspective carries the role - MayaOutputExtra used to split on two
// hardcoded level sets and render nothing outside them, so a script with an unrecognised level
// vanished with no message and no count.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import MayaOutputExtra from '../components/tabs/MayaOutputExtra'
import { projectsApi } from '../api/endpoints'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getInterviewScripts: vi.fn(),
    getScriptLedger: vi.fn(),
    reviewScript: vi.fn(),
    getMyPermissions: vi.fn(),
  },
}))

const ONE_SCRIPT = {
  'SC-1': { script_id: 'SC-1', node_id: '1', level: 'L1', perspective: null, node_label: 'Property', sections: [] },
}

const LEDGER_ROW = {
  script_id: 'SC-1', node_id: '1', node_label: 'Property',
  review_status: 'pending' as const, reviewed_at_version: null,
  review_return_to: null, last_version: 2, last_author: 'interaction_designer',
  review_count: 1,
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('MayaOutputExtra', () => {
  beforeEach(() => {
    // Every render queries permissions unconditionally now (Approve is gated on it) - a
    // default resolved value keeps tests that don't care about permissions from hanging
    // on an unmocked call.
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue(
      { can_review: true, can_approve: true } as never,
    )
  })

  it('renders every script it is given, including one with an unrecognised perspective', async () => {
    // The old two buckets dropped anything outside them silently - no message, no count.
    // SC-2 is the shape the endpoint actually serves for a role script: normalise_scripts
    // moves the role letter out of `level` and into `perspective`, leaving level null. That
    // shape matched neither hardcoded level set, so every role script vanished. Fixtures
    // carrying a level inside the old VC_LEVELS set cannot see this - they render either way.
    vi.mocked(projectsApi.getInterviewScripts).mockResolvedValue({
      'SC-1': { script_id: 'SC-1', node_id: '1',   level: 'L1', perspective: null, node_label: 'Property', sections: [] },
      'SC-2': { script_id: 'SC-2', node_id: '1.F', level: null, perspective: 'F',  node_label: 'Frontline', sections: [] },
      'SC-3': { script_id: 'SC-3', node_id: '9',   level: 'L3', perspective: 'X',  node_label: 'Odd one',   sections: [] },
    } as never)
    vi.mocked(projectsApi.getScriptLedger).mockResolvedValue([])
    render(<Wrapper><MayaOutputExtra slug="p" /></Wrapper>)
    // Exact text, not a substring match: the perspective badge for SC-2 renders the title
    // "Frontline Worker", which a /Frontline/ substring match would also catch, hiding a
    // false pass if the node_label itself were never rendered.
    expect(await screen.findByText('Property')).toBeInTheDocument()
    expect(await screen.findByText('Frontline')).toBeInTheDocument()
    expect(await screen.findByText('Odd one')).toBeInTheDocument()
  })

  it('tells a failed ledger fetch apart from an empty one', async () => {
    // Before this fix, both rendered nothing - there was no way to distinguish "could not
    // load" from "nothing to review".
    vi.mocked(projectsApi.getInterviewScripts).mockResolvedValue(ONE_SCRIPT as never)
    vi.mocked(projectsApi.getScriptLedger).mockRejectedValue(new Error('network error'))
    render(<Wrapper><MayaOutputExtra slug="p" /></Wrapper>)

    expect(await screen.findByText(/could not load the script review ledger/i)).toBeInTheDocument()
  })

  it('surfaces the server detail when an approval is refused, rather than doing nothing', async () => {
    // The backend refuses a review with 403 (not a reviewer/approver), 409 (already
    // approved), or 422 (a send-back with no valid target) - all of which the person needs
    // to be told. Without a .catch, the button appeared to work and nothing happened.
    vi.mocked(projectsApi.getInterviewScripts).mockResolvedValue(ONE_SCRIPT as never)
    vi.mocked(projectsApi.getScriptLedger).mockResolvedValue([LEDGER_ROW] as never)
    vi.mocked(projectsApi.reviewScript).mockRejectedValue(
      Object.assign(new Error('Forbidden'), {
        isAxiosError: true,
        response: { status: 403, data: { detail: 'Not permitted to review this script' } },
      }),
    )
    render(<Wrapper><MayaOutputExtra slug="p" /></Wrapper>)

    await userEvent.click(await screen.findByRole('button', { name: /approve/i }))

    expect(await screen.findByText(/not permitted to review this script/i)).toBeInTheDocument()
  })

  // GET /my-permissions was added specifically because canApprove had been hardcoded true,
  // and nothing proved the replacement was consumed: beforeEach mocks can_approve: true for
  // every test in this file, so putting `canApprove={true}` back passed all 412 of them. The
  // endpoint only earns its keep if a false answer is honoured, so that is what this asserts.
  it('offers no Approve when the server says this caller may not approve', async () => {
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue(
      { can_review: true, can_approve: false } as never,
    )
    vi.mocked(projectsApi.getInterviewScripts).mockResolvedValue(ONE_SCRIPT as never)
    // review_count 3, so the row's own "has anybody read it" gate is satisfied - otherwise
    // an absent Approve would be explained by the wrong thing.
    vi.mocked(projectsApi.getScriptLedger).mockResolvedValue(
      [{ ...LEDGER_ROW, review_count: 3 }] as never,
    )
    render(<Wrapper><MayaOutputExtra slug="p" /></Wrapper>)

    // Wait for the row itself, and for the permissions answer to have arrived, before
    // concluding anything from an absence.
    expect(await screen.findByRole('button', { name: /open/i })).toBeInTheDocument()
    await waitFor(() => expect(projectsApi.getMyPermissions).toHaveBeenCalledWith('p'))
    await waitFor(() => expect(screen.getByText(/3 reviews/i)).toBeInTheDocument())

    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
  })

  it('offers Approve when the server says this caller may', async () => {
    // The positive half. Without it the test above is satisfied by a component that never
    // renders Approve at all, which is not the behaviour being protected.
    vi.mocked(projectsApi.getInterviewScripts).mockResolvedValue(ONE_SCRIPT as never)
    vi.mocked(projectsApi.getScriptLedger).mockResolvedValue(
      [{ ...LEDGER_ROW, review_count: 3 }] as never,
    )
    render(<Wrapper><MayaOutputExtra slug="p" /></Wrapper>)

    expect(await screen.findByRole('button', { name: /approve/i })).toBeInTheDocument()
  })

  it('opens the row that was clicked, not another one, and refreshes both queries on close', async () => {
    // Two scripts, not one: a lookup by the wrong key (a hardcoded id, or the first entry
    // regardless of which row was clicked) renders SC-1's content under SC-2's Open button
    // and would pass silently against a single-script fixture.
    const TWO_SCRIPTS = {
      'SC-1': { script_id: 'SC-1', node_id: '1', level: 'L1', perspective: null, node_label: 'Property', sections: [] },
      'SC-2': { script_id: 'SC-2', node_id: '2', level: 'L1', perspective: null, node_label: 'Leasing', sections: [] },
    }
    const TWO_LEDGER_ROWS = [
      { script_id: 'SC-1', node_id: '1', node_label: 'Property',
        review_status: 'pending' as const, reviewed_at_version: null,
        review_return_to: null, last_version: 2, last_author: 'interaction_designer', review_count: 1 },
      { script_id: 'SC-2', node_id: '2', node_label: 'Leasing',
        review_status: 'pending' as const, reviewed_at_version: null,
        review_return_to: null, last_version: 4, last_author: 'interaction_designer', review_count: 1 },
    ]
    vi.mocked(projectsApi.getInterviewScripts).mockResolvedValue(TWO_SCRIPTS as never)
    vi.mocked(projectsApi.getScriptLedger).mockResolvedValue(TWO_LEDGER_ROWS as never)

    // A dedicated client (not the shared Wrapper's) so invalidateQueries can be spied on
    // directly, rather than inferred from a refetch that a stale cache might skip.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')

    render(
      <QueryClientProvider client={qc}>
        <MayaOutputExtra slug="p" />
      </QueryClientProvider>,
    )

    const openButtons = await screen.findAllByRole('button', { name: /open/i })
    expect(openButtons).toHaveLength(2)
    await userEvent.click(openButtons[1]) // second row rendered is SC-2 / Leasing

    // The panel's title field is seeded from the opened script's node_label - a display
    // value, so this cannot be satisfied by the row list's own plain-text label.
    expect(await screen.findByDisplayValue('Leasing')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('Property')).not.toBeInTheDocument()

    invalidateSpy.mockClear()
    await userEvent.click(screen.getByRole('button', { name: '×' }))

    const invalidatedKeys = invalidateSpy.mock.calls.map(
      (call) => (call[0] as { queryKey: unknown[] }).queryKey,
    )
    expect(invalidatedKeys).toContainEqual(['interview-scripts', 'p'])
    expect(invalidatedKeys).toContainEqual(['script-ledger', 'p'])
  })
})
