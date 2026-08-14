import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { render, screen, fireEvent } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { ICON, LABEL, ScriptReviewRow } from '../components/tabs/ScriptReviewRow'
import type { ScriptLedgerRow } from '../types'

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

// ── Every status the backend can actually write ────────────────────────────────
//
// record_script_review sets review_status = decision, so the values this component must
// render are exactly script_review_service.VALID_DECISIONS plus 'pending' (the column
// default, and what a human edit resets the row to). The list is read out of the Python
// rather than restated here on purpose: a copy would have agreed with itself when 'edited'
// was added to VALID_DECISIONS and not to this component, which is precisely how
// ICON['edited'] came to be undefined - tsc saw a total Record over a union that was
// simply too narrow, and all 412 frontend tests passed while "Save changes" crashed the
// list it returned to.
const VALID_DECISIONS: string[] = (() => {
  const source = readFileSync(
    path.resolve(
      path.dirname(fileURLToPath(import.meta.url)),
      '../../../api/services/script_review_service.py',
    ),
    'utf-8',
  )
  const match = source.match(/^VALID_DECISIONS\s*=\s*\(([^)]*)\)/m)
  if (!match) throw new Error('VALID_DECISIONS not found in script_review_service.py')
  return [...match[1].matchAll(/["']([^"']+)["']/g)].map((m) => m[1])
})()

const RENDERABLE_STATUSES = ['pending', ...VALID_DECISIONS]

it('reads the real VALID_DECISIONS, so this file cannot silently test nothing', () => {
  // A regex that stopped matching would leave every loop below iterating an empty list and
  // passing vacuously - the failure mode of a test derived from a foreign file.
  expect(VALID_DECISIONS).toContain('reviewed')
  expect(VALID_DECISIONS).toContain('edited')
  expect(VALID_DECISIONS.length).toBeGreaterThanOrEqual(4)
})

it('has a label and an icon for every decision the backend can write', () => {
  for (const status of RENDERABLE_STATUSES) {
    expect(Object.keys(LABEL), `no label for review_status '${status}'`).toContain(status)
    expect(Object.keys(ICON), `no icon for review_status '${status}'`).toContain(status)
  }
})

it('renders a row at every status the backend can write, with a named status and an icon', () => {
  for (const status of RENDERABLE_STATUSES) {
    const row = { ...base, review_status: status as ScriptLedgerRow['review_status'] }
    const { container, unmount } = render(
      <ScriptReviewRow row={row} onOpen={() => {}} onApprove={() => {}} canApprove={false} />,
    )
    // An svg proves a component rendered rather than a bare `undefined` reaching JSX -
    // which is the actual crash: "Element type is invalid ... but got: undefined".
    expect(container.querySelector('svg'), `no icon rendered for '${status}'`).not.toBeNull()
    // The mapped label, not the raw token: falling back to the wire value is survivable but
    // is not the finished surface, and asserting the token would accept the fallback.
    expect(
      screen.getByText(LABEL[status as ScriptLedgerRow['review_status']]),
      `'${status}' did not render its own label`,
    ).toBeInTheDocument()
    unmount()
  }
})

it('renders a status neither map knows without taking the tab down with it', () => {
  // review_status is an unconstrained TEXT column with no CHECK constraint, so this is a
  // reachable state rather than a hypothetical one - and the Output tab has no error
  // boundary, so an unrenderable row is not a broken row, it is a blank tab.
  render(
    <ScriptReviewRow
      row={{ ...base, review_status: 'quarantined' as ScriptLedgerRow['review_status'] }}
      onOpen={() => {}} onApprove={() => {}} canApprove={false} />,
  )
  expect(screen.getByText('1.2')).toBeInTheDocument()
  expect(screen.getByText('quarantined')).toBeInTheDocument()
})
