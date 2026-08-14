import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ScriptReviewPanel } from '../components/tabs/ScriptReviewPanel'

const row = {
  script_id: 'SC-042', node_id: '1.4.2', node_label: 'Work Order Dispatch',
  review_status: 'pending' as const, reviewed_at_version: null,
  review_return_to: null, last_version: 3, last_author: 'interaction_designer',
  review_count: 0,
}
const script = { script_id: 'SC-042', node_id: '1.4.2', node_label: 'Work Order Dispatch',
                 level: 'L3', sections: [] }

const patchMock = vi.fn().mockResolvedValue({})
const reviewMock = vi.fn().mockResolvedValue({})
vi.mock('../api/endpoints', () => ({
  projectsApi: {
    patchInterviewScript: (...a: unknown[]) => patchMock(...a),
    reviewScript: (...a: unknown[]) => reviewMock(...a),
  },
}))

beforeEach(() => { patchMock.mockClear(); reviewMock.mockClear() })

it('records a review when the reader signs off without changing anything', async () => {
  render(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /reviewed, no changes/i }))
  await waitFor(() => expect(reviewMock).toHaveBeenCalled())
  expect(reviewMock.mock.calls[0][2]).toMatchObject({ decision: 'reviewed' })
  expect(patchMock).not.toHaveBeenCalled()
})

it('sends the version it opened, so a stale save can be refused', async () => {
  render(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.change(screen.getByLabelText(/script title/i), { target: { value: 'Retitled' } })
  fireEvent.click(screen.getByRole('button', { name: /save changes/i }))
  await waitFor(() => expect(patchMock).toHaveBeenCalled())
  expect(patchMock.mock.calls[0][2]).toMatchObject({ base_version: 3 })
})

it('records an edited review after a successful save', async () => {
  render(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.change(screen.getByLabelText(/script title/i), { target: { value: 'Retitled' } })
  fireEvent.click(screen.getByRole('button', { name: /save changes/i }))
  await waitFor(() => expect(reviewMock).toHaveBeenCalled())
  expect(reviewMock.mock.calls[0][2]).toMatchObject({ decision: 'edited' })
})

it('sends back with the note and the target the reader chose', async () => {
  render(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /send back/i }))
  fireEvent.change(screen.getByLabelText(/feedback/i), { target: { value: 'anchors are wrong' } })
  fireEvent.click(screen.getByRole('button', { name: /to maya/i }))
  await waitFor(() => expect(reviewMock).toHaveBeenCalled())
  expect(reviewMock.mock.calls[0][2]).toMatchObject({
    decision: 'changes_requested', return_to: 'agent', notes: 'anchors are wrong',
  })
})

// Added beyond the brief's verbatim set: the power-check for send-back (hardcode
// `return_to: 'agent'`) does not fail the brief's own test above, because that test only
// ever clicks "To Maya" - already 'agent'. Without this test, "To reviewers" sending the
// wrong target would ship silently. Same failure class CLAUDE.md's review-history section
// warns about repeatedly: a guard tested for one of its two conditions.
it('sends back to reviewers, not Maya, when that is the target the reader chose', async () => {
  render(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /send back/i }))
  fireEvent.change(screen.getByLabelText(/feedback/i), { target: { value: 'check with sponsor' } })
  fireEvent.click(screen.getByRole('button', { name: /to reviewers/i }))
  await waitFor(() => expect(reviewMock).toHaveBeenCalled())
  expect(reviewMock.mock.calls[0][2]).toMatchObject({
    decision: 'changes_requested', return_to: 'reviewer', notes: 'check with sponsor',
  })
})

it('surfaces a stale-save refusal rather than failing silently', async () => {
  patchMock.mockRejectedValueOnce({
    response: { data: { detail: 'SC-042 was changed by ana since you opened it' } },
  })
  render(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.change(screen.getByLabelText(/script title/i), { target: { value: 'Mine' } })
  fireEvent.click(screen.getByRole('button', { name: /save changes/i }))
  expect(await screen.findByText(/changed by ana/i)).toBeInTheDocument()
  expect(reviewMock).not.toHaveBeenCalled()
})
