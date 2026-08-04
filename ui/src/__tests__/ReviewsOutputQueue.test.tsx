// ui/src/__tests__/ReviewsOutputQueue.test.tsx
//
// An output is created review_status='pending' and, until now, nothing in the application
// could ever move it off pending: POST /projects/{slug}/review existed on the server and
// no frontend code called it. 79 outputs had accumulated in one project.
//
// They were also invisible. The reviews endpoint lists human_reviews joined through
// crew_runs, and its own docstring notes that output reviews - which have no crew_run_id -
// are excluded by that join.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import Reviews from '../pages/Reviews'

const { OUTPUTS, submitOutputReview } = vi.hoisted(() => ({
  submitOutputReview: vi.fn().mockResolvedValue(undefined),
  OUTPUTS: [
    // Alex's deliverable - his crew's primary output.
    { id: 91, agent_name: 'value_chain_mapper', output_type: 'value_chain_model', version: 6,
      review_status: 'pending', is_current: true, file_path: '', created_at: '' },
    // Same crew, not its deliverable. The registry, tree and summary are how the model is
    // reached, not the thing being approved.
    { id: 90, agent_name: 'value_chain_mapper', output_type: 'value_chain_registry', version: 3,
      review_status: 'pending', is_current: true, file_path: '', created_at: '' },
    // PAM's report. She is deliberately absent from CREW_OUTPUT_TYPE, so a strict
    // primaries-only filter would drop the one output most often waiting on someone.
    { id: 76, agent_name: 'PAM', output_type: 'pam_report', version: 3,
      review_status: 'pending', is_current: true, file_path: '', created_at: '' },
    // Superseded: a previous version is history, not work awaiting a decision.
    { id: 85, agent_name: 'value_chain_mapper', output_type: 'value_chain_model', version: 5,
      review_status: 'pending', is_current: false, file_path: '', created_at: '' },
    // Already decided.
    { id: 74, agent_name: 'PAM', output_type: 'pam_report', version: 1,
      review_status: 'approved', is_current: false, file_path: '', created_at: '' },
  ],
}))

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    listReviews: vi.fn().mockResolvedValue([]),
    outputs: vi.fn().mockResolvedValue(OUTPUTS),
    submitOutputReview,
    resolveReview: vi.fn(),
    deleteReview: vi.fn(),
    getSettings: vi.fn().mockResolvedValue({}),
  },
  campaignsApi: { listReminderEmails: vi.fn().mockResolvedValue([]) },
  commitsApi: { states: vi.fn().mockResolvedValue({}), submit: vi.fn(), approve: vi.fn() },
}))

function renderReviews() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/acme/reviews']}>
        <Routes><Route path="/:slug/reviews" element={<Reviews />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('outputs awaiting review', () => {
  it("lists a crew's deliverable and PAM's report, and nothing else", async () => {
    renderReviews()
    await waitFor(() => expect(screen.getByTestId('output-review-91')).toBeInTheDocument())
    expect(screen.getByTestId('output-review-76')).toBeInTheDocument()
    // Assert the count, not just presence: "the model is listed" is equally true of a
    // filter that lists all five and floods the queue.
    expect(screen.getAllByTestId(/^output-review-/)).toHaveLength(2)
  })

  it('omits a superseded version and one already decided', async () => {
    renderReviews()
    await waitFor(() => expect(screen.getByTestId('output-review-91')).toBeInTheDocument())
    expect(screen.queryByTestId('output-review-85')).toBeNull()
    expect(screen.queryByTestId('output-review-74')).toBeNull()
  })

  it('approves an output through the endpoint that already existed', async () => {
    renderReviews()
    await waitFor(() => expect(screen.getByTestId('approve-output-91')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('approve-output-91'))

    await waitFor(() =>
      expect(submitOutputReview).toHaveBeenCalledWith('acme', 91, 'approved', ''))
  })

  it('requests changes with the note the reviewer wrote', async () => {
    renderReviews()
    await waitFor(() => expect(screen.getByTestId('output-notes-91')).toBeInTheDocument())

    await userEvent.type(screen.getByTestId('output-notes-91'), 'Fleet party is wrong')
    await userEvent.click(screen.getByTestId('request-changes-output-91'))

    await waitFor(() =>
      expect(submitOutputReview).toHaveBeenCalledWith(
        'acme', 91, 'changes_requested', 'Fleet party is wrong'))
  })
})

describe('naming the agent on a review card', () => {
  it("shows the agent's name, not the stored snake_case key", async () => {
    renderReviews()
    await waitFor(() => expect(screen.getByTestId('output-review-91')).toBeInTheDocument())
    // agent_outputs stores 'value_chain_mapper'; the reader knows him as Alex.
    expect(screen.getByTestId('output-review-91')).toHaveTextContent('Alex Chen')
    expect(screen.getByTestId('output-review-91')).not.toHaveTextContent('value_chain_mapper')
  })

  it('handles an agent whose stored name is already its key', async () => {
    // PAM is stored as 'PAM', not snake_case, so a converter that only title-cases
    // underscores would leave her as "PAM" while every other agent gained a name.
    renderReviews()
    await waitFor(() => expect(screen.getByTestId('output-review-76')).toBeInTheDocument())
    expect(screen.getByTestId('output-review-76')).toHaveTextContent('Pamela Reid')
  })
})
