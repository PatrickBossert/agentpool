// ui/src/__tests__/Reviews.test.tsx
import { render, screen, waitFor } from '@testing-library/react'
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
    // Wait for the status fetch to resolve before asserting absence, otherwise the
    // assertion could pass only because the query has not settled yet.
    await waitFor(() => expect(statusMock).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /activate project/i })).not.toBeInTheDocument()
  })
})
