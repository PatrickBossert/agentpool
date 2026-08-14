import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
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

// InterviewTemplateEditor talks to apiClient directly rather than through projectsApi, and it
// is mounted from this panel now, so its two calls need stubbing here too.
const editorGetMock = vi.fn()
const editorPatchMock = vi.fn()
vi.mock('../api/client', () => ({
  apiClient: {
    get: (...a: unknown[]) => editorGetMock(...a),
    patch: (...a: unknown[]) => editorPatchMock(...a),
  },
}))

const FULL_SCRIPT = {
  script_id: 'SC-042', node_id: '1.4.2', node_label: 'Work Order Dispatch', level: 'L3',
  welcome_message: 'Welcome', closing_message: 'Thanks',
  sections: [{ section_id: 'S1', title: 'Opening', discipline: 'governance',
               question_intent: 'evidence', elicitation: 'unprompted',
               questions: [{ id: 'Q1', text: 'How is a job dispatched?', follow_up_count: 2,
                             probing_instructions: '', follow_up_branches: [],
                             evasion_signals: [] }] }],
}

beforeEach(() => {
  patchMock.mockClear()
  reviewMock.mockClear()
  editorGetMock.mockReset().mockResolvedValue({ data: FULL_SCRIPT })
  editorPatchMock.mockReset().mockResolvedValue({ data: { ok: true } })
})

// The panel mounts InterviewTemplateEditor, which uses useQueryClient - so anything that
// opens it needs a provider. The exits that do not open it are rendered bare, as before.
function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

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
    isAxiosError: true,
    response: { data: { detail: 'SC-042 was changed by ana since you opened it' } },
  })
  render(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.change(screen.getByLabelText(/script title/i), { target: { value: 'Mine' } })
  fireEvent.click(screen.getByRole('button', { name: /save changes/i }))
  expect(await screen.findByText(/changed by ana/i)).toBeInTheDocument()
  expect(reviewMock).not.toHaveBeenCalled()
})

// ── The full editor ────────────────────────────────────────────────────────────
//
// The spec asked for "the existing ScriptCard rendering plus the existing editor, which
// already versions and validates". The branch delivered ScriptCard plus a single title input,
// and MayaSetupTab's mount of InterviewTemplateEditor went with the template-assignment layer
// it sat in - so for the length of this branch no sections, questions, or probes were editable
// anywhere in the application. These prove the editor is reachable, that it saves against the
// version this panel opened, and that the review is recorded for it.

it('opens the full editor, so questions and probes are editable again', async () => {
  renderWithClient(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /edit questions/i }))
  // A question's text as a form value, not a heading: the read-only ScriptCard behind the
  // editor renders question text too, and a text match would pass without the editor.
  expect(await screen.findByDisplayValue('How is a job dispatched?')).toBeInTheDocument()
})

it('saves the full script against the version the panel opened', async () => {
  renderWithClient(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /edit questions/i }))
  await screen.findByDisplayValue('How is a job dispatched?')
  fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

  await waitFor(() => expect(editorPatchMock).toHaveBeenCalled())
  expect(editorPatchMock.mock.calls[0][0]).toBe('/projects/p/interview-scripts/SC-042')
  expect(editorPatchMock.mock.calls[0][1]).toMatchObject({ base_version: 3 })
})

it('records an edited review after the full editor saves, and closes', async () => {
  const onClose = vi.fn()
  renderWithClient(<ScriptReviewPanel slug="p" script={script} row={row} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: /edit questions/i }))
  await screen.findByDisplayValue('How is a job dispatched?')
  fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

  await waitFor(() => expect(reviewMock).toHaveBeenCalled())
  expect(reviewMock.mock.calls[0][2]).toMatchObject({ decision: 'edited' })
  await waitFor(() => expect(onClose).toHaveBeenCalled())
})

it('records nothing when the full editor save is refused', async () => {
  editorPatchMock.mockRejectedValueOnce({
    isAxiosError: true,
    response: { data: { detail: 'SC-042 was changed by ana since you opened it' } },
  })
  renderWithClient(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /edit questions/i }))
  await screen.findByDisplayValue('How is a job dispatched?')
  fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

  // findAllBy, not findBy: InterviewTemplateEditor deliberately shows the server's detail in
  // both its body and its footer, so a single-element query fails on the success case.
  expect((await screen.findAllByText(/changed by ana/i)).length).toBeGreaterThan(0)
  expect(reviewMock).not.toHaveBeenCalled()
})

// ── can_review ─────────────────────────────────────────────────────────────────

it('offers no exits at all to a reader who may not review', () => {
  render(<ScriptReviewPanel slug="p" script={script} row={row} canReview={false}
                            onClose={() => {}} />)
  expect(screen.queryByRole('button', { name: /save changes/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /reviewed, no changes/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /send back/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /edit questions/i })).not.toBeInTheDocument()
  // Read-only, not broken - the script itself is still there to read.
  expect(screen.getByText(/but not review it/i)).toBeInTheDocument()
})

it('offers the exits to a reader who may review', () => {
  render(<ScriptReviewPanel slug="p" script={script} row={row} canReview
                            onClose={() => {}} />)
  expect(screen.getByRole('button', { name: /reviewed, no changes/i })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /edit questions/i })).toBeInTheDocument()
})
