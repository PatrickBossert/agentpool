import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
  render(<ScriptReviewRow row={base} onReview={() => {}} />)
  expect(screen.getByText(/changed since/i)).toBeInTheDocument()
})

it('does not mark a review stale when it was read at the current version', () => {
  render(<ScriptReviewRow row={{ ...base, reviewed_at_version: 5 }} onReview={() => {}} />)
  expect(screen.queryByText(/changed since/i)).not.toBeInTheDocument()
})

it('shows an unreviewed script as awaiting review, not as stale', () => {
  render(<ScriptReviewRow
    row={{ ...base, review_status: 'pending', reviewed_at_version: null }}
    onReview={() => {}} />)
  expect(screen.queryByText(/changed since/i)).not.toBeInTheDocument()
  expect(screen.getByText(/awaiting review/i)).toBeInTheDocument()
})

// NULL is a real input, not an edge case: last_version has no default, and
// backfill_script_ledger leaves it NULL on every row it creates. The staleness comparison
// must not treat a NULL as "less than" or "greater than" anything - a naive `<=` reading of
// `NULL <= 0` already dropped a row from a query once on this branch.
it('renders a backfilled row (last_version null) without crashing, and does not mark it stale', () => {
  render(<ScriptReviewRow row={{ ...base, last_version: null }} onReview={() => {}} />)
  expect(screen.getByText('SC-001')).toBeInTheDocument()
  expect(screen.queryByText(/changed since/i)).not.toBeInTheDocument()
})

it('renders a reviewed row with no recorded review version without crashing, and does not mark it stale', () => {
  // reviewed_at_version null on a *non-pending* row - distinct from the 'awaiting review'
  // case above, which is the only NULL shape the original test covered.
  render(<ScriptReviewRow row={{ ...base, reviewed_at_version: null }} onReview={() => {}} />)
  expect(screen.getByText('SC-001')).toBeInTheDocument()
  expect(screen.queryByText(/changed since/i)).not.toBeInTheDocument()
})

it('sends a plain "reviewed" decision with no target or note when marked reviewed', async () => {
  const onReview = vi.fn()
  render(<ScriptReviewRow row={base} onReview={onReview} />)

  await userEvent.click(screen.getByRole('button', { name: /mark reviewed/i }))

  expect(onReview).toHaveBeenCalledTimes(1)
  expect(onReview).toHaveBeenCalledWith('SC-001', 'reviewed')
})

it('sends the note and an "agent" target when sent back to the agent', async () => {
  // The target is the load-bearing distinction in the whole feature: 'agent' makes Maya
  // regenerate the script, 'reviewer' is a human-to-human loop that must never trigger
  // regeneration. A test that only checks the row re-renders after a click cannot tell
  // these apart - only the call arguments can.
  const onReview = vi.fn()
  render(<ScriptReviewRow row={base} onReview={onReview} />)

  await userEvent.click(screen.getByRole('button', { name: /^send back$/i }))
  await userEvent.type(screen.getByLabelText(/send-back note/i), 'Q3 is leading the witness')
  await userEvent.click(screen.getByRole('button', { name: /to agent/i }))

  expect(onReview).toHaveBeenCalledTimes(1)
  expect(onReview).toHaveBeenCalledWith(
    'SC-001', 'changes_requested', 'agent', 'Q3 is leading the witness',
  )
})

it('sends the note and a "reviewer" target when sent back to another reviewer', async () => {
  const onReview = vi.fn()
  render(<ScriptReviewRow row={base} onReview={onReview} />)

  await userEvent.click(screen.getByRole('button', { name: /^send back$/i }))
  await userEvent.type(screen.getByLabelText(/send-back note/i), 'check with the client sponsor first')
  await userEvent.click(screen.getByRole('button', { name: /to reviewer/i }))

  expect(onReview).toHaveBeenCalledTimes(1)
  expect(onReview).toHaveBeenCalledWith(
    'SC-001', 'changes_requested', 'reviewer', 'check with the client sponsor first',
  )
})
