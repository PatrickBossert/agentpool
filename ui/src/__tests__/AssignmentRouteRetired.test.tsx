// ui/src/__tests__/AssignmentRouteRetired.test.tsx
//
// Two links point at the stakeholder-to-activity mapping: the retired `/:slug/assignment`
// route, which anyone may have bookmarked, and the "Assign stakeholders" link Runs.tsx shows
// against a run sitting in `awaiting_assignment`. Both are driven here, because both name a
// tab and the mapping has now changed tabs twice - to Agents when Setup was narrowed to what
// a crew owns, and back to Setup when the panels were re-read against the rename test.
//
// Asserted on the shipped `routes` export and driven to the destination, not stopped at the
// Navigate: a link that lands on the right crew and the wrong tab satisfies a pathname check,
// looks like working navigation, and simply does not hold what was asked for.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, beforeEach, beforeAll, afterAll, vi } from 'vitest'
import { routes } from '../router'
import { projectsApi } from '../api/endpoints'

vi.mock('../context/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  ProtectedRoute: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => ({
    token: 'test-token',
    user: { sub: 'assignment-tester', role: 'sysadmin', exp: 9999999999 },
    login: vi.fn(),
    logout: vi.fn(),
  }),
}))

// The agent configuration section mounts with the Setup tab and asks the server for each
// agent's name, image and voice. Stubbed rather than left to reach the network: an unmocked
// call resolves as a rejected promise inside react-query, which is noise in this file's
// output and a race in anybody else's.
vi.mock('../api/agentConfig', () => ({
  agentConfigApi: {
    get: vi.fn().mockResolvedValue({
      agent_id: 'stub',
      configured: false,
      defaults: {
        display_name: 'Stub', image_url: null, voice_id: null,
        language: 'en', country_code: 'GB', model_id: 'eleven_turbo_v2',
      },
      overrides: {
        display_name: null, image_url: null, voice_id: null,
        language: null, country_code: null, model_id: null,
      },
      resolved: {
        display_name: 'Stub', image_url: null, voice_id: null,
        language: 'en', country_code: 'GB', model_id: 'eleven_turbo_v2',
      },
    }),
    put: vi.fn(),
  },
}))

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    list: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({ crew_runs: [] }),
    outputs: vi.fn().mockResolvedValue([]),
    listReviews: vi.fn().mockResolvedValue([]),
    getSettings: vi.fn().mockResolvedValue({}),
    listRuns: vi.fn().mockResolvedValue([]),
    getAssignment: vi.fn().mockResolvedValue({ assignments: [], stakeholders: [] }),
    getValueChainRegistry: vi.fn().mockResolvedValue({ schema_version: 1, activities: [] }),
    saveAssignment: vi.fn().mockResolvedValue({ saved: 0 }),
    advanceOrchestrationRun: vi.fn().mockResolvedValue({ status: 'running' }),
  },
  milestonesApi: { list: vi.fn().mockResolvedValue([]) },
  commitsApi: { readiness: vi.fn().mockResolvedValue({}) },
  valueChainApi: { get: vi.fn().mockResolvedValue({ model: null }), migrate: vi.fn(), save: vi.fn() },
  agentChatApi: {
    getHistory: vi.fn().mockResolvedValue([]),
    clearHistory: vi.fn().mockResolvedValue(undefined),
    send: vi.fn(),
  },
  stakeholdersApi: { list: vi.fn().mockResolvedValue([]) },
  campaignsApi: { listReminderEmails: vi.fn().mockResolvedValue([]) },
}))

// See ValueChainRoute.test.tsx - Node's real fetch Request rejects jsdom's AbortSignal, and
// createMemoryRouter builds one on every navigation.
class PermissiveRequest {
  url: string
  method: string
  signal?: AbortSignal
  constructor(input: string | URL, init: RequestInit = {}) {
    this.url = String(input)
    this.method = init.method ?? 'GET'
    this.signal = init.signal ?? undefined
  }
}

beforeAll(() => vi.stubGlobal('Request', PermissiveRequest))
afterAll(() => vi.unstubAllGlobals())
beforeEach(() => localStorage.clear())

function renderAt(entry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(routes, { initialEntries: [entry] })
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

/**
 * The mapping is on screen, on the tab the link named - not merely somewhere in the document.
 *
 * Scoped with `within`, and that is the whole point rather than tidiness: the Setup tab is
 * rendered `hidden` rather than unmounted, so an unscoped `findByLabelText` would find the
 * filter box whether or not the tab holding it was the one that opened.
 */
async function expectTheMappingOnTheSetupTab() {
  expect(await screen.findByTestId('selected-crew-stakeholder_management')).toBeInTheDocument()
  expect(await screen.findByTestId('active-tab-setup')).toBeInTheDocument()
  const setup = await screen.findByTestId('setup-tab-panel')
  expect(setup).toBeVisible()
  expect(await within(setup).findByLabelText('Filter activities')).toBeInTheDocument()
}

describe('the retired /:slug/assignment route', () => {
  it('sends a bookmark to the Setup tab, where the mapping is made', async () => {
    const router = renderAt('/acme/assignment')

    await waitFor(() => expect(router.state.location.pathname).toBe('/acme'))
    expect(router.state.location.search).toBe('?crew=stakeholder_management&tab=setup')

    await expectTheMappingOnTheSetupTab()
  })
})

describe("Runs' \"Assign stakeholders\" link", () => {
  it('opens the same tab, driven rather than read off the href', async () => {
    // The second link, and it does not depend on the redirect above - it goes direct. Two
    // links, one destination: the mapping moved tabs twice and this is the one that would be
    // left behind, because nothing about the runs list mentions a tab.
    vi.mocked(projectsApi.listRuns).mockResolvedValue([
      { id: 4, status: 'awaiting_assignment', started_at: null, completed_at: null, crew_runs: [] },
    ] as never)
    const router = renderAt('/acme/runs')

    await userEvent.click(await screen.findByRole('link', { name: /Assign stakeholders/ }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/acme'))
    await expectTheMappingOnTheSetupTab()
  })
})
