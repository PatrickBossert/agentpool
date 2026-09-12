// ui/src/__tests__/ItemReviewPanel.test.tsx
//
// **What is sent.** Every assertion here reads the arguments the panel actually handed the
// client, not the text on a button - CLAUDE.md records twelve assertions on this project that
// passed without testing what they were named for, and one of them was a radio that rendered
// correctly and was never sent.
//
// Both kinds are driven separately throughout. The panel picks its client function out of a
// map keyed on `kind`, which is exactly the shape where one kind's test covers the other's
// wiring: a map whose two entries both pointed at `reviewNode` would pass every node test in
// this file.
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ItemReviewPanel } from '../components/tabs/ItemReviewPanel'
import type { ReviewableItem } from '../components/tabs/ItemReviewRow'

const nodeMock = vi.fn().mockResolvedValue({})
const leverMock = vi.fn().mockResolvedValue({})
vi.mock('../api/endpoints', () => ({
  projectsApi: {
    reviewNode: (...a: unknown[]) => nodeMock(...a),
    reviewLever: (...a: unknown[]) => leverMock(...a),
  },
}))

const node: ReviewableItem = {
  item_id: '3.3.3', label: 'Mains renewal planning', meta: 'L3',
  review_status: 'pending', reviewed_at_version: null, last_version: 3, review_count: 0,
}

const lever: ReviewableItem = {
  item_id: 'LV-001', label: 'Risk-based capital prioritisation', meta: 'untested',
  review_status: 'pending', reviewed_at_version: null, last_version: 3, review_count: 0,
}

beforeEach(() => {
  nodeMock.mockClear()
  leverMock.mockClear()
})

function renderNode(props: Partial<React.ComponentProps<typeof ItemReviewPanel>> = {}) {
  return render(
    <ItemReviewPanel slug="p" kind="node" item={node} agentName="Alex"
                     onClose={() => {}} {...props} />,
  )
}

function renderLever(props: Partial<React.ComponentProps<typeof ItemReviewPanel>> = {}) {
  return render(
    <ItemReviewPanel slug="p" kind="lever" item={lever} agentName="Morgan"
                     onClose={() => {}} {...props} />,
  )
}

it('records a review when the reader signs off on a node without changes', async () => {
  renderNode()
  fireEvent.click(screen.getByRole('button', { name: /reviewed, no changes/i }))
  await waitFor(() => expect(nodeMock).toHaveBeenCalled())
  expect(nodeMock.mock.calls[0][1]).toBe('3.3.3')
  expect(nodeMock.mock.calls[0][2]).toMatchObject({ decision: 'reviewed' })
  expect(leverMock).not.toHaveBeenCalled()
})

it('records a review when the reader signs off on a lever without changes', async () => {
  renderLever()
  fireEvent.click(screen.getByRole('button', { name: /reviewed, no changes/i }))
  await waitFor(() => expect(leverMock).toHaveBeenCalled())
  expect(leverMock.mock.calls[0][1]).toBe('LV-001')
  expect(leverMock.mock.calls[0][2]).toMatchObject({ decision: 'reviewed' })
  expect(nodeMock).not.toHaveBeenCalled()
})

it('sends a node back to the agent with the note and the target it was sent under', async () => {
  renderNode()
  fireEvent.click(screen.getByRole('button', { name: /send back/i }))
  fireEvent.change(screen.getByLabelText(/feedback/i),
                   { target: { value: 'This belongs at L2.' } })
  fireEvent.click(screen.getByRole('button', { name: /to alex/i }))
  await waitFor(() => expect(nodeMock).toHaveBeenCalled())
  expect(nodeMock.mock.calls[0][2]).toEqual({
    decision: 'changes_requested', return_to: 'agent', notes: 'This belongs at L2.',
  })
})

it('sends a lever back to the agent with the note and the target it was sent under', async () => {
  renderLever()
  fireEvent.click(screen.getByRole('button', { name: /send back/i }))
  fireEvent.change(screen.getByLabelText(/feedback/i),
                   { target: { value: 'That is the mechanism, not the lever.' } })
  fireEvent.click(screen.getByRole('button', { name: /to morgan/i }))
  await waitFor(() => expect(leverMock).toHaveBeenCalled())
  expect(leverMock.mock.calls[0][2]).toEqual({
    decision: 'changes_requested',
    return_to: 'agent',
    notes: 'That is the mechanism, not the lever.',
  })
})

it('sends a return to reviewers under return_to reviewer, never to the agent', async () => {
  // The difference is the whole of the human-to-human loop: only `agent` enters the
  // regeneration block, because regenerating the item a reviewer was about to re-read
  // rewrites the thing under discussion. Asserted on what was sent, because both buttons
  // record a review and only the payload tells them apart.
  renderNode()
  fireEvent.click(screen.getByRole('button', { name: /send back/i }))
  fireEvent.change(screen.getByLabelText(/feedback/i), { target: { value: 'Ask Priya.' } })
  fireEvent.click(screen.getByRole('button', { name: /to reviewers/i }))
  await waitFor(() => expect(nodeMock).toHaveBeenCalled())
  expect(nodeMock.mock.calls[0][2]).toMatchObject({ return_to: 'reviewer' })
})

it('will not send an item back to the agent with no guidance', () => {
  // A regeneration request with no note tells the agent nothing, and it is the reviewer's
  // words that reach the prompt beside the id.
  renderNode()
  fireEvent.click(screen.getByRole('button', { name: /send back/i }))
  expect(screen.getByRole('button', { name: /to alex/i })).toBeDisabled()
  // The human-to-human return is not blocked: "have a look at this" is a complete message
  // between two people in a way it is not to an agent.
  expect(screen.getByRole('button', { name: /to reviewers/i })).not.toBeDisabled()
})

it('names the agent it sends to rather than writing the persona out', async () => {
  // The name arrives as a prop, resolved from this project's own agent identity. A hard-coded
  // 'Alex' would be a second registry free to drift from agents/identity.py - the rule the
  // mail seam states and this follows.
  render(<ItemReviewPanel slug="p" kind="node" item={node} agentName="Robin"
                          onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /send back/i }))
  expect(screen.getByRole('button', { name: /to robin/i })).toBeInTheDocument()
})

it('closes only after the review has landed', async () => {
  const onClose = vi.fn()
  renderNode({ onClose })
  fireEvent.click(screen.getByRole('button', { name: /reviewed, no changes/i }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
})

it('reports the server\'s own refusal rather than a fixed string, and does not close', async () => {
  // describeError is imported from utils, not copied - several of this API's refusals say
  // something a fixed string cannot, and a 409 "cannot re-approve, send it back first" is
  // precisely the sentence a reviewer needs.
  nodeMock.mockRejectedValueOnce({
    isAxiosError: true,
    response: { status: 409, data: { detail: 'node 3.3.3 cannot re-approve, send it back first' } },
  })
  const onClose = vi.fn()
  renderNode({ onClose })
  fireEvent.click(screen.getByRole('button', { name: /reviewed, no changes/i }))
  expect(await screen.findByText(/cannot re-approve/i)).toBeInTheDocument()
  expect(onClose).not.toHaveBeenCalled()
})

it('offers no exits at all to a reader who may not review', () => {
  // can_review comes from /my-permissions, the same authority the door consults - so a reader
  // who may not review is shown the item rather than buttons the server would refuse.
  renderNode({ canReview: false })
  expect(screen.queryByRole('button', { name: /reviewed, no changes/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /send back/i })).not.toBeInTheDocument()
  expect(screen.getByText(/not review it/i)).toBeInTheDocument()
})

it('shows the id, the level, and the version the judgement is being made against', () => {
  renderNode()
  expect(screen.getByText('3.3.3')).toBeInTheDocument()
  expect(screen.getByText('L3')).toBeInTheDocument()
  expect(screen.getByText('v3')).toBeInTheDocument()
})

it('shows a lever by its id and its hypothesis status', () => {
  renderLever()
  expect(screen.getByText('LV-001')).toBeInTheDocument()
  expect(screen.getByText('untested')).toBeInTheDocument()
})
