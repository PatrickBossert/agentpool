// ui/src/__tests__/Reviews.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Reviews from '../pages/Reviews'

const statusMock = vi.fn()
const statesMock = vi.fn()
const activateMock = vi.fn()
const createMock = vi.fn()

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    status: (...args: unknown[]) => statusMock(...args),
    listReviews: vi.fn().mockResolvedValue([]),
  },
  commitsApi: {
    states: (...args: unknown[]) => statesMock(...args),
    changeCount: vi.fn().mockResolvedValue(0),
    create: (...args: unknown[]) => createMock(...args),
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
  createMock.mockReset()
  statesMock.mockResolvedValue({})
  createMock.mockResolvedValue({
    commit_id: 1,
    started: [],
    skipped: [],
    waiting: [],
    inactive: false,
  })
})

// An approvable crew: its run completed, and its state is ready. Both are required -
// CrewApprovalSection omits a crew whose only run failed or is still going.
function anApprovableCrew() {
  statusMock.mockResolvedValue(
    baseStatus({
      project_status: 'active',
      crew_runs: [crewRun('discovery_mapping', 'completed')],
    }),
  )
  statesMock.mockResolvedValue({ discovery_mapping: 'ready' })
}

async function approve() {
  await userEvent.click(await screen.findByRole('button', { name: /approve/i }))
}

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

  it('names both consequences of leaving a project inactive', async () => {
    // Two separate gates read projects.status, and the banner is the only place either is
    // explained: api/services/pam_report_job.py:133 skips the daily report, and
    // api/services/autostart_service.py suppresses the auto-start. Naming only one leaves
    // an approver believing the other still works.
    statusMock.mockResolvedValue(baseStatus({ project_status: 'created' }))
    renderReviews()
    const banner = await screen.findByText(/not active/i)
    expect(banner).toHaveTextContent(/next crew/i)
    expect(banner).toHaveTextContent(/daily report/i)
  })
})

describe('Reviews - what an approval did', () => {
  it('names the crew the approval started', async () => {
    anApprovableCrew()
    createMock.mockResolvedValue({
      commit_id: 1,
      started: [{ crew: 'assessment_design', run_id: 7 }],
      skipped: [],
      waiting: [],
      inactive: false,
    })
    renderReviews()
    await approve()
    expect(await screen.findByText(/started assessment design/i)).toBeInTheDocument()
  })

  it('says a skipped crew was already running and must be re-run', async () => {
    // The case a reviewer currently cannot tell from a successful start. The in-flight
    // run does not include what was just approved, so silence here loses their changes.
    anApprovableCrew()
    createMock.mockResolvedValue({
      commit_id: 1,
      started: [],
      skipped: ['assessment_design'],
      waiting: [],
      inactive: false,
    })
    renderReviews()
    await approve()
    const line = await screen.findByText(/already running/i)
    expect(line).toHaveTextContent(/assessment design/i)
    expect(line).toHaveTextContent(/re-run/i)
  })

  it('names the approval a waiting crew is still short of', async () => {
    anApprovableCrew()
    createMock.mockResolvedValue({
      commit_id: 1,
      started: [],
      skipped: [],
      waiting: [{ crew: 'discovery_interviews', waiting_on: ['stakeholder_management'] }],
      inactive: false,
    })
    renderReviews()
    await approve()
    const line = await screen.findByText(/discovery interviews/i)
    expect(line).toHaveTextContent(/stakeholder management/i)
  })

  it('gives the reason when a crew is blocked by something other than an approval', async () => {
    // Delivery cannot run without configuration the product never collects, so no
    // approval will release it - waiting_on would be empty and the reviewer none the
    // wiser. The reason is what tells them what to actually go and do.
    anApprovableCrew()
    createMock.mockResolvedValue({
      commit_id: 1,
      started: [],
      skipped: [],
      waiting: [
        {
          crew: 'delivery',
          waiting_on: [],
          reason: "It needs the project's value streams and stakeholder groups to be set first.",
        },
      ],
      inactive: false,
    })
    renderReviews()
    await approve()
    const line = await screen.findByText(/value streams/i)
    expect(line).toHaveTextContent(/delivery/i)
    expect(line).toHaveTextContent(/stakeholder groups/i)
  })

  it('says why nothing started when the project is not active', async () => {
    anApprovableCrew()
    createMock.mockResolvedValue({
      commit_id: 1,
      started: [],
      skipped: [],
      waiting: [],
      inactive: true,
    })
    renderReviews()
    await approve()
    const line = await screen.findByText(/nothing started/i)
    expect(line).toHaveTextContent(/not active/i)
  })

  it('does not claim anything about a start that failed outright', async () => {
    // The router reports only that auto-start failed - it cannot know what was started,
    // what is waiting, or whether the project is active, so it says none of those.
    anApprovableCrew()
    createMock.mockResolvedValue({ commit_id: 1, autostart_failed: true })
    renderReviews()
    await approve()
    const line = await screen.findByText(/could not be started/i)
    expect(line).toHaveTextContent(/approval is recorded/i)
    expect(screen.queryByText(/nothing follows/i)).not.toBeInTheDocument()
  })

  it('shows nothing before an approval is made', async () => {
    anApprovableCrew()
    renderReviews()
    await screen.findByText('Ready for approval')
    expect(screen.queryByText(/already running/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/nothing follows/i)).not.toBeInTheDocument()
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
