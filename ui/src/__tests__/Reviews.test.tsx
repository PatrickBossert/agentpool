// ui/src/__tests__/Reviews.test.tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Reviews from '../pages/Reviews'

const statusMock = vi.fn()
const statesMock = vi.fn()
const activateMock = vi.fn()

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    status: (...args: unknown[]) => statusMock(...args),
    listReviews: vi.fn().mockResolvedValue([]),
  },
  commitsApi: {
    states: (...args: unknown[]) => statesMock(...args),
    changeCount: vi.fn().mockResolvedValue(0),
    create: vi.fn(),
    submit: vi.fn(),
    activate: (...args: unknown[]) => activateMock(...args),
  },
}))

vi.mock('../api/campaigns', () => ({
  campaignsApi: {
    listReminderEmails: vi.fn().mockResolvedValue([]),
    updateReminderEmail: vi.fn(),
  },
}))

function baseStatus(overrides: Partial<{ project_status: string; crew_runs: unknown[] }> = {}) {
  return {
    project_slug: 'acme-rail',
    project_status: 'created',
    crew_runs: [],
    latest_orchestration_run: null,
    ...overrides,
  }
}

function crewRun(crewName: string, status: string) {
  return {
    id: 1,
    project_id: 1,
    crew_name: crewName,
    status,
    result_json: null,
    started_at: null,
    finished_at: null,
    created_at: '2026-04-13T10:00:00',
  }
}

function renderReviews() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/acme-rail']}>
        <Routes>
          <Route path="/:slug" element={<Reviews />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  statusMock.mockReset()
  statesMock.mockReset()
  activateMock.mockReset()
  statesMock.mockResolvedValue({})
})

describe('Reviews - activate project control', () => {
  it('offers to activate a project that is not active', async () => {
    statusMock.mockResolvedValue(baseStatus({ project_status: 'created' }))
    renderReviews()
    expect(await screen.findByRole('button', { name: /activate project/i })).toBeInTheDocument()
  })

  it('does not offer to activate a project that is already active', async () => {
    statusMock.mockResolvedValue(baseStatus({ project_status: 'active' }))
    renderReviews()
    // Wait for a marker that only appears once its own (independent) query has
    // resolved, so we know a render past initial mount has happened before
    // asserting absence - otherwise the assertion could pass only because the
    // status query has not settled yet, which would pass just as well on a
    // broken component that never checked project_status at all.
    await screen.findByText(/no pending reviews/i)
    expect(screen.queryByRole('button', { name: /activate project/i })).not.toBeInTheDocument()
  })
})

describe('Reviews - failed and in-progress runs are not offered for approval', () => {
  it('omits a crew whose only run failed', async () => {
    statusMock.mockResolvedValue(
      baseStatus({ crew_runs: [crewRun('discovery', 'failed')] }),
    )
    statesMock.mockResolvedValue({ discovery: 'ready' })
    renderReviews()
    // Same reasoning as the activate-control absence test above: wait for a
    // sibling query's marker before asserting this one never rendered.
    await screen.findByText(/no pending reviews/i)
    expect(screen.queryByText('Ready for approval')).not.toBeInTheDocument()
  })

  it('shows a crew whose run completed', async () => {
    statusMock.mockResolvedValue(
      baseStatus({ crew_runs: [crewRun('discovery', 'completed')] }),
    )
    statesMock.mockResolvedValue({ discovery: 'ready' })
    renderReviews()
    expect(await screen.findByText('Ready for approval')).toBeInTheDocument()
  })
})
