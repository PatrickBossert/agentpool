// ui/src/__tests__/ReviewQueueDrawer.test.tsx
//
// The review queue was a fixed 240px column, present on every dashboard at every moment, and
// saying "No pending reviews" for almost all of them. It is a drawer now: shut by default,
// overlaying the content rather than displacing it, with a handle that keeps the count
// readable without opening anything.
//
// **Overlay rather than push is the property that reclaims the space.** A drawer that pushed
// would give the 240px back only while it was shut, which is the arrangement it replaced. The
// assertion for that is on the content column's width being unchanged between the two states -
// jsdom reports 0 for every box, so it is asserted structurally instead: the drawer is
// positioned `absolute`, so it is out of the row's flow and cannot displace a sibling.
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { AuthProvider } from '../context/AuthContext'
import Dashboard from '../pages/Dashboard'
import { projectsApi } from '../api/endpoints'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    list: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({ project_slug: 'acme-rail', project_status: 'created', crew_runs: [] }),
    outputs: vi.fn().mockResolvedValue([]),
    listReviews: vi.fn().mockResolvedValue([]),
    getSettings: vi.fn().mockResolvedValue({}),
    deleteReview: vi.fn().mockResolvedValue({}),
  },
  milestonesApi: { list: vi.fn().mockResolvedValue([]) },
  commitsApi: { readiness: vi.fn().mockResolvedValue({}) },
}))

function review(id: number) {
  return { id, prompt: 'Please check the value chain', crew_run_id: id,
           crew_name: 'discovery_mapping', decision: 'pending', reviewed_at: '' }
}

function renderDashboard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/acme-rail']}>
          <Routes><Route path="/:slug" element={<Dashboard />} /></Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

const drawer = () => screen.getByTestId('review-queue-drawer')
const handle = () => screen.getByRole('button', { name: /review queue/i })

beforeEach(() => {
  vi.mocked(projectsApi.listReviews).mockResolvedValue([])
})

describe('the review queue drawer', () => {
  it('is shut when the dashboard opens', async () => {
    renderDashboard()
    await waitFor(() => expect(drawer()).toHaveAttribute('aria-hidden', 'true'))
    // No scrim while shut, or every click on the dashboard beneath would be swallowed.
    expect(screen.queryByTestId('review-queue-scrim')).toBeNull()
  })

  it('does not displace the content, whether shut or open', async () => {
    // The whole point of the change. `absolute` takes the drawer out of the row's flow, so
    // the column beside it is the same width in both states - which is what "reclaims 240px"
    // means. Asserted on the positioning rather than on a measurement, because jsdom performs
    // no layout and would report zero either way.
    renderDashboard()
    await waitFor(() => expect(drawer()).toBeInTheDocument())
    expect(drawer().className).toContain('absolute')

    fireEvent.click(handle())
    await waitFor(() => expect(drawer()).toHaveAttribute('aria-hidden', 'false'))
    expect(drawer().className).toContain('absolute')
  })

  it('shows the pending count on the handle without being opened', async () => {
    // The one thing the always-open panel was reliably read for. If this needed a click, the
    // drawer would have taken something away rather than only given space back.
    vi.mocked(projectsApi.listReviews).mockResolvedValue([review(1), review(2)] as never)
    renderDashboard()

    await waitFor(() => expect(within(handle()).getByText('2')).toBeInTheDocument())
    expect(drawer()).toHaveAttribute('aria-hidden', 'true')
  })

  it('opens on the handle and closes again on it', async () => {
    renderDashboard()
    await waitFor(() => expect(drawer()).toBeInTheDocument())

    fireEvent.click(handle())
    await waitFor(() => expect(drawer()).toHaveAttribute('aria-hidden', 'false'))
    expect(handle()).toHaveAttribute('aria-expanded', 'true')

    fireEvent.click(handle())
    await waitFor(() => expect(drawer()).toHaveAttribute('aria-hidden', 'true'))
  })

  it('closes on Escape, and on a click outside', async () => {
    // Two exits besides the handle. A drawer that covers content and can only be dismissed by
    // finding its button again is a modal wearing a drawer's clothes.
    renderDashboard()
    await waitFor(() => expect(drawer()).toBeInTheDocument())

    fireEvent.click(handle())
    await waitFor(() => expect(drawer()).toHaveAttribute('aria-hidden', 'false'))
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(drawer()).toHaveAttribute('aria-hidden', 'true'))

    fireEvent.click(handle())
    await waitFor(() => expect(drawer()).toHaveAttribute('aria-hidden', 'false'))
    fireEvent.click(screen.getByTestId('review-queue-scrim'))
    await waitFor(() => expect(drawer()).toHaveAttribute('aria-hidden', 'true'))
  })

  it('still lists the reviews once it is open', async () => {
    // The control on all of the above: a drawer that never rendered its contents would satisfy
    // every "is it shut" assertion perfectly.
    vi.mocked(projectsApi.listReviews).mockResolvedValue([review(1)] as never)
    renderDashboard()

    fireEvent.click(await screen.findByRole('button', { name: /review queue/i }))
    expect(await within(drawer()).findByText(/Please check the value chain/)).toBeInTheDocument()
  })
})
