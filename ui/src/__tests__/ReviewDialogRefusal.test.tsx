// ui/src/__tests__/ReviewDialogRefusal.test.tsx
// What a reviewer is told when the review door refuses them.
//
// Both of this dialog's handlers were `try`/`finally` with no `catch`, so a rejected request
// reset the spinner and did nothing else. An owner on a live client engagement clicked Approve,
// `PATCH /projects/{slug}/reviews/{id}` answered 403 "Only a reviewer or approver may resolve a
// review", and the dialog sat there unchanged - no error, no close, no clue. The crew stayed
// paused on the gate.
//
// Every assertion here is about the **sentence in front of the reviewer**, not about a `catch`
// existing. CLAUDE.md's recurring failure mode is a test that verifies a property one layer
// away from where it holds, and the specific trap this file avoids is named in the brief: a
// test that mocks a rejection and asserts the dialog closed would pass the defect perfectly,
// because the defect *does* leave the dialog open. So two things are asserted together on every
// path - the door's own words are rendered, **and** `onClose` was not called - and the two are
// only satisfiable by a handler that catches, reports, and stays put.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import ReviewDialog from '../components/ReviewDialog'

// A **fresh** mock per test, rather than one shared mock cleared in `beforeEach`. That is not
// a style choice, and it cost an hour: under vitest 2.1.9, `mockClear()` or `mockReset()` on a
// mock whose implementation returns a rejected promise discards the internal bookkeeping that
// was going to consume that rejection, so Node reports it as an *unhandled* rejection and
// vitest attributes it to the running test. Every test in this file failed with the refusal it
// had deliberately arranged, while the component was catching it correctly all along - proven
// by reducing it to two bare `vi.fn()`s, where `beforeEach(() => f.mockClear())` fails and no
// clear at all passes. The sibling `ReviewIntent.test.tsx` clears a shared mock and is fine
// because its mock *resolves*; only a rejecting one meets this.
//
// The holder is reassigned rather than cleared, which also gives each test genuine isolation:
// nothing carries over, so no test's green can depend on a call another test made.
let resolveReview: ReturnType<typeof vi.fn>

vi.mock('../api/endpoints', () => ({
  projectsApi: { resolveReview: (...a: unknown[]) => resolveReview(...a) },
}))

/** A refusal shaped the way axios delivers one, so `describeError` reads it for real rather
 *  than falling through its `isAxiosError` guard to the fallback - which would make every
 *  assertion below pass against a component that showed the fallback for everything. */
function axiosError(status: number, detail?: string) {
  return new AxiosError(
    'Request failed',
    String(status),
    { headers: new AxiosHeaders() },
    {},
    {
      status,
      statusText: '',
      headers: {},
      config: { headers: new AxiosHeaders() },
      data: detail ? { detail } : {},
    },
  )
}

// The sentence api/routers/reviews.py:resolve_hitl_review actually refuses with. Written out
// verbatim rather than matched loosely, because the whole argument for `describeError` over a
// fixed string is that *this* wording - naming the two content roles - is the only thing that
// tells a consultant why administering the engagement did not buy them an approval.
const REFUSAL = 'Only a reviewer or approver may resolve a review'

const review = {
  id: 7, crew_name: 'discovery_mapping', prompt: 'Please review the value chain.',
  decision: 'pending',
}

function renderDialog(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ReviewDialog slug="helia-digital-tau" review={review as never} outputs={[]} onClose={onClose} />
    </QueryClientProvider>,
  )
  return onClose
}

describe('a refused review reaches the reviewer', () => {
  beforeEach(() => { resolveReview = vi.fn() })

  it('shows the door\'s own refusal when Approve is refused, and keeps the dialog open', async () => {
    resolveReview.mockRejectedValue(axiosError(403, REFUSAL))
    const onClose = renderDialog()

    await userEvent.click(screen.getByRole('button', { name: /approve/i }))

    // The server's sentence, verbatim. A fixed string here ("Could not approve") would tell the
    // reviewer that something went wrong and nothing about what to do.
    expect(await screen.findByRole('alert')).toHaveTextContent(REFUSAL)
    // The half the brief warns about: the defect leaves the dialog open too, so "open" alone
    // proves nothing. It is asserted *with* the sentence, and only together do they exclude it.
    expect(onClose).not.toHaveBeenCalled()
  })

  it('re-enables Approve after a refusal, so the reviewer can act on what they were told', async () => {
    resolveReview.mockRejectedValue(axiosError(403, REFUSAL))
    renderDialog()

    await userEvent.click(screen.getByRole('button', { name: /approve/i }))
    await screen.findByRole('alert')

    // `finally` already did this before the fix; it is asserted because a `catch` written to
    // replace the `finally` rather than to join it would leave the button spinning for ever,
    // which is a worse failure than the silent one.
    expect(screen.getByRole('button', { name: /approve/i })).toBeEnabled()
  })

  it('shows the refusal when a revision request is refused, and keeps the notes', async () => {
    resolveReview.mockRejectedValue(axiosError(403, REFUSAL))
    const onClose = renderDialog()

    await userEvent.click(screen.getByRole('button', { name: /request revision/i }))
    await userEvent.type(screen.getByRole('textbox'), 'Tighten the summary')
    await userEvent.click(screen.getByRole('button', { name: /submit revision request/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(REFUSAL)
    expect(onClose).not.toHaveBeenCalled()
    // Closing on a refusal would discard what the reviewer wrote. Asserted rather than assumed,
    // because "stay open" and "keep the notes" come apart the moment anybody calls `cancel()`
    // on the error path to tidy up.
    expect(screen.getByRole('textbox')).toHaveValue('Tighten the summary')
  })

  it('shows the refusal when a rejection is refused', async () => {
    resolveReview.mockRejectedValue(axiosError(403, REFUSAL))
    const onClose = renderDialog()

    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))
    await userEvent.type(screen.getByRole('textbox'), 'Wrong organisation')
    await userEvent.click(screen.getByRole('button', { name: /confirm rejection/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(REFUSAL)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('falls back to its own words only when the refusal carries no sentence', async () => {
    // The two arms of `describeError` driven in both directions. Without this the whole file
    // would pass against a component that ignored the response and always printed a fixed
    // string, which is the defect one step removed rather than the fix.
    resolveReview.mockRejectedValue(axiosError(500))
    renderDialog()

    await userEvent.click(screen.getByRole('button', { name: /approve/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/could not approve this output/i)
    expect(alert).not.toHaveTextContent(REFUSAL)
  })

  it('clears a stale refusal when the reviewer tries again and succeeds', async () => {
    // A refusal that outlives the condition it described is its own defect: a consultant who
    // is granted the approver role in another tab, comes back and approves successfully would
    // otherwise still be looking at "Only a reviewer or approver may resolve a review" beside
    // a dialog that has just closed.
    resolveReview.mockRejectedValueOnce(axiosError(403, REFUSAL)).mockResolvedValueOnce({})
    const onClose = renderDialog()

    await userEvent.click(screen.getByRole('button', { name: /approve/i }))
    await screen.findByRole('alert')

    await userEvent.click(screen.getByRole('button', { name: /approve/i }))

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
