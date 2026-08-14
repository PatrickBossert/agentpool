import { render, screen, fireEvent } from '@testing-library/react'
import { vi } from 'vitest'
import { ScriptReviewRow } from '../components/tabs/ScriptReviewRow'

const base = {
  script_id: 'SC-001', node_id: '1.2', node_label: 'Works Programming',
  review_status: 'reviewed' as const, reviewed_at_version: 3,
  review_return_to: null, last_version: 5, last_author: 'interaction_designer',
  review_count: 1,
}

it('marks a review as stale when the script changed after it was read', () => {
  // reviewed_at_version 3 against last_version 5: the tick describes content nobody has
  // read. Showing it as a plain tick is the failure this indicator exists to prevent.
  render(<ScriptReviewRow row={base} onOpen={() => {}} onApprove={() => {}} canApprove={false} />)
  expect(screen.getByText(/changed since/i)).toBeInTheDocument()
})

it('does not mark a review stale when it was read at the current version', () => {
  render(<ScriptReviewRow row={{ ...base, reviewed_at_version: 5 }}
                          onOpen={() => {}} onApprove={() => {}} canApprove={false} />)
  expect(screen.queryByText(/changed since/i)).not.toBeInTheDocument()
})

it('shows an unreviewed script as awaiting review, not as stale', () => {
  render(<ScriptReviewRow
    row={{ ...base, review_status: 'pending', reviewed_at_version: null }}
    onOpen={() => {}} onApprove={() => {}} canApprove={false} />)
  expect(screen.queryByText(/changed since/i)).not.toBeInTheDocument()
  expect(screen.getByText(/awaiting review/i)).toBeInTheDocument()
})

// NULL is a real input, not an edge case: last_version has no default, and
// backfill_script_ledger leaves it NULL on every row it creates. The staleness comparison
// must not treat a NULL as "less than" or "greater than" anything - a naive `<=` reading of
// `NULL <= 0` already dropped a row from a query once on this branch.
it('renders a backfilled row (last_version null) without crashing, and does not mark it stale', () => {
  render(<ScriptReviewRow row={{ ...base, last_version: null }}
                          onOpen={() => {}} onApprove={() => {}} canApprove={false} />)
  expect(screen.getByText('1.2')).toBeInTheDocument()
  expect(screen.queryByText(/changed since/i)).not.toBeInTheDocument()
})

it('renders a reviewed row with no recorded review version without crashing, and does not mark it stale', () => {
  // reviewed_at_version null on a *non-pending* row - distinct from the 'awaiting review'
  // case above, which is the only NULL shape the original test covered.
  render(<ScriptReviewRow row={{ ...base, reviewed_at_version: null }}
                          onOpen={() => {}} onApprove={() => {}} canApprove={false} />)
  expect(screen.getByText('1.2')).toBeInTheDocument()
  expect(screen.queryByText(/changed since/i)).not.toBeInTheDocument()
})

const approveBase = {
  script_id: 'SC-042', node_id: '1.4.2', node_label: 'Work Order Dispatch',
  review_status: 'pending' as const, reviewed_at_version: null,
  review_return_to: null, last_version: 3, last_author: 'interaction_designer',
  review_count: 0,
}

it('identifies a script by its value chain id, not its internal script id', () => {
  // SC-042 is a citation token - it means nothing to a reviewer, while 1.4.2 is the
  // reference used consistently everywhere else in the application.
  render(<ScriptReviewRow row={approveBase} onOpen={() => {}} onApprove={() => {}} canApprove />)
  expect(screen.getByText('1.4.2')).toBeInTheDocument()
  expect(screen.queryByText('SC-042')).not.toBeInTheDocument()
})

it('disables approve until the script has been read', () => {
  render(<ScriptReviewRow row={approveBase} onOpen={() => {}} onApprove={() => {}} canApprove />)
  expect(screen.getByRole('button', { name: /approve/i })).toBeDisabled()
})

it('enables approve once it has a review, and shows how many', () => {
  render(<ScriptReviewRow row={{ ...approveBase, review_count: 3 }}
                          onOpen={() => {}} onApprove={() => {}} canApprove />)
  expect(screen.getByRole('button', { name: /approve/i })).not.toBeDisabled()
  expect(screen.getByText(/3 reviews/i)).toBeInTheDocument()
})

it('offers no approve at all to somebody who is not an approver', () => {
  render(<ScriptReviewRow row={{ ...approveBase, review_count: 3 }}
                          onOpen={() => {}} onApprove={() => {}} canApprove={false} />)
  expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
})

it('opens the script rather than judging it from the list', () => {
  const onOpen = vi.fn()
  render(<ScriptReviewRow row={approveBase} onOpen={onOpen} onApprove={() => {}} canApprove />)
  fireEvent.click(screen.getByRole('button', { name: /open/i }))
  expect(onOpen).toHaveBeenCalledWith('SC-042')
  expect(screen.queryByRole('button', { name: /mark reviewed/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /send back/i })).not.toBeInTheDocument()
})
