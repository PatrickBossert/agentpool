import { render, screen } from '@testing-library/react'
import { ScriptReviewRow } from '../components/tabs/ScriptReviewRow'

const base = {
  script_id: 'SC-001', node_id: '1.2', node_label: 'Works Programming',
  review_status: 'reviewed' as const, reviewed_at_version: 3,
  review_return_to: null, last_version: 5, last_author: 'interaction_designer',
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
