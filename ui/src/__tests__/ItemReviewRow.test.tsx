// ui/src/__tests__/ItemReviewRow.test.tsx
//
// One row of a per-item review ledger. The status maps are checked against the **producer** -
// item_review_service.VALID_DECISIONS, read out of the Python - rather than against a list
// restated here, which would agree with itself for ever. That is not hypothetical: 'edited'
// was added to the script ledger's VALID_DECISIONS and not to its component, tsc saw a total
// Record over a union that was simply too narrow, and 412 frontend tests passed while the
// list crashed on render.
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { render, screen, fireEvent } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { ICON, LABEL, ItemReviewRow, type ReviewableItem } from '../components/tabs/ItemReviewRow'
import type { ItemReviewStatus } from '../types'

const node: ReviewableItem = {
  item_id: '3.3.3', label: 'Mains renewal planning', meta: 'L3',
  review_status: 'reviewed', reviewed_at_version: 3, last_version: 5, review_count: 1,
}

const lever: ReviewableItem = {
  item_id: 'LV-001', label: 'Risk-based capital prioritisation', meta: 'untested',
  review_status: 'pending', reviewed_at_version: null, last_version: 3, review_count: 0,
}

const noop = () => {}

it('shows a node by its id, its label, and its level', () => {
  render(<ItemReviewRow item={node} onOpen={noop} onApprove={noop} canApprove={false} />)
  expect(screen.getByText('3.3.3')).toBeInTheDocument()
  expect(screen.getByText('Mains renewal planning')).toBeInTheDocument()
  expect(screen.getByText('L3')).toBeInTheDocument()
})

it('shows a lever by its id, its title, and its hypothesis status', () => {
  // The lever id is displayed because a reviewer has to cite it - unlike a script id, which
  // is deliberately hidden in favour of the node id it names. A lever has no other permanent
  // handle: its title is a full sentence that regeneration rewords.
  render(<ItemReviewRow item={lever} onOpen={noop} onApprove={noop} canApprove={false} />)
  expect(screen.getByText('LV-001')).toBeInTheDocument()
  expect(screen.getByText('Risk-based capital prioritisation')).toBeInTheDocument()
  expect(screen.getByText('untested')).toBeInTheDocument()
})

it('marks a review stale when the item changed after it was read', () => {
  render(<ItemReviewRow item={node} onOpen={noop} onApprove={noop} canApprove={false} />)
  expect(screen.getByText(/changed since/i)).toBeInTheDocument()
})

it('does not mark a review stale when it was read at the current version', () => {
  render(<ItemReviewRow item={{ ...node, reviewed_at_version: 5 }}
                        onOpen={noop} onApprove={noop} canApprove={false} />)
  expect(screen.queryByText(/changed since/i)).not.toBeInTheDocument()
})

it('shows an unreviewed item as awaiting review, not as stale', () => {
  render(<ItemReviewRow item={lever} onOpen={noop} onApprove={noop} canApprove={false} />)
  expect(screen.queryByText(/changed since/i)).not.toBeInTheDocument()
  expect(screen.getByText(/awaiting review/i)).toBeInTheDocument()
})

it('renders a row the agent has never written (last_version null) without marking it stale', () => {
  // NULL is a real input, not an edge case: last_version has no default, and a row created
  // by a backfill never had a version to record. A naive comparison reading NULL as "less
  // than" would brand every such row stale on sight.
  render(<ItemReviewRow item={{ ...node, last_version: null }}
                        onOpen={noop} onApprove={noop} canApprove={false} />)
  expect(screen.getByText('3.3.3')).toBeInTheDocument()
  expect(screen.queryByText(/changed since/i)).not.toBeInTheDocument()
})

it('disables approve until the item has been read', () => {
  render(<ItemReviewRow item={lever} onOpen={noop} onApprove={noop} canApprove />)
  expect(screen.getByRole('button', { name: /approve/i })).toBeDisabled()
})

it('enables approve once it has a review, and says how many', () => {
  render(<ItemReviewRow item={{ ...lever, review_count: 3 }}
                        onOpen={noop} onApprove={noop} canApprove />)
  expect(screen.getByRole('button', { name: /approve/i })).not.toBeDisabled()
  expect(screen.getByText(/3 reviews/i)).toBeInTheDocument()
})

it('offers no approve at all to somebody who is not an approver', () => {
  render(<ItemReviewRow item={{ ...lever, review_count: 3 }}
                        onOpen={noop} onApprove={noop} canApprove={false} />)
  expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
})

it('opens the item rather than judging it from the list, and passes its id', () => {
  const onOpen = vi.fn()
  render(<ItemReviewRow item={node} onOpen={onOpen} onApprove={noop} canApprove />)
  fireEvent.click(screen.getByRole('button', { name: /open/i }))
  expect(onOpen).toHaveBeenCalledWith('3.3.3')
  expect(screen.queryByRole('button', { name: /send back/i })).not.toBeInTheDocument()
})

it('passes the item id to approve, so the row cannot approve its neighbour', () => {
  const onApprove = vi.fn()
  render(<ItemReviewRow item={{ ...lever, review_count: 1 }}
                        onOpen={noop} onApprove={onApprove} canApprove />)
  fireEvent.click(screen.getByRole('button', { name: /approve/i }))
  expect(onApprove).toHaveBeenCalledWith('LV-001')
})

// ── Every status the backend can actually write ────────────────────────────────
//
// record_item_review sets review_status = decision, so the values this component must render
// are exactly item_review_service.VALID_DECISIONS plus 'pending' - the column default, and
// the only one no decision produces.
const VALID_DECISIONS: string[] = (() => {
  const source = readFileSync(
    path.resolve(
      path.dirname(fileURLToPath(import.meta.url)),
      '../../../api/services/item_review_service.py',
    ),
    'utf-8',
  )
  const match = source.match(/^VALID_DECISIONS\s*=\s*\(([^)]*)\)/m)
  if (!match) throw new Error('VALID_DECISIONS not found in item_review_service.py')
  return [...match[1].matchAll(/["']([^"']+)["']/g)].map((m) => m[1])
})()

const RENDERABLE_STATUSES = ['pending', ...VALID_DECISIONS]

it('reads the real VALID_DECISIONS, so this file cannot silently test nothing', () => {
  // A regex that stopped matching would leave every loop below iterating an empty list and
  // passing vacuously - the failure mode of a test derived from a foreign file.
  expect(VALID_DECISIONS).toContain('reviewed')
  expect(VALID_DECISIONS).toContain('changes_requested')
  expect(VALID_DECISIONS).toContain('approved')
})

it('has three exits and not the script ledger\'s four', () => {
  // `edited` records that a reader changed the thing in front of them, and there is nothing
  // here to change: levers are review-only by decision, and the value chain model has its own
  // editor and its own workflow. Asserted rather than left as a fact about today, so adding
  // an edit decision is a deliberate change that has to bring an editor with it.
  expect(VALID_DECISIONS).not.toContain('edited')
  expect(VALID_DECISIONS).toHaveLength(3)
})

it('has a label and an icon for every decision the backend can write', () => {
  for (const status of RENDERABLE_STATUSES) {
    expect(Object.keys(LABEL), `no label for review_status '${status}'`).toContain(status)
    expect(Object.keys(ICON), `no icon for review_status '${status}'`).toContain(status)
  }
})

it('renders a row at every status the backend can write, with a named status and an icon', () => {
  for (const status of RENDERABLE_STATUSES) {
    const item = { ...node, review_status: status as ItemReviewStatus }
    const { container, unmount } = render(
      <ItemReviewRow item={item} onOpen={noop} onApprove={noop} canApprove={false} />,
    )
    // An svg proves a component rendered rather than a bare `undefined` reaching JSX - which
    // is the actual crash: "Element type is invalid ... but got: undefined".
    expect(container.querySelector('svg'), `no icon rendered for '${status}'`).not.toBeNull()
    expect(
      screen.getByText(LABEL[status as ItemReviewStatus]),
      `'${status}' did not render its own label`,
    ).toBeInTheDocument()
    unmount()
  }
})

it('renders a status neither map knows without taking the tab down with it', () => {
  // review_status is an unconstrained TEXT column with no CHECK, so this is a reachable state
  // rather than a hypothetical one - and the Output tab has no error boundary, so an
  // unrenderable row is not a broken row, it is a blank tab.
  render(
    <ItemReviewRow item={{ ...node, review_status: 'quarantined' as ItemReviewStatus }}
                   onOpen={noop} onApprove={noop} canApprove={false} />,
  )
  expect(screen.getByText('3.3.3')).toBeInTheDocument()
  expect(screen.getByText('quarantined')).toBeInTheDocument()
})
