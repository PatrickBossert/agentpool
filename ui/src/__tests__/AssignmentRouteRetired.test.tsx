// ui/src/__tests__/AssignmentRouteRetired.test.tsx
//
// /:slug/assignment was not orphaned - Runs.tsx links to it from any run sitting in
// `awaiting_assignment` - so retiring the page it rendered leaves live links pointing at it,
// in the runs list and in anyone's bookmarks. It redirects to where the mapping lives now.
//
// Asserted on the shipped `routes` export and driven to the destination, not stopped at the
// Navigate: a redirect that lands somewhere with no assignment surface on it would satisfy a
// pathname check and still leave the person with nothing to do.
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, beforeEach, beforeAll, afterAll, vi } from 'vitest'
import { routes } from '../router'

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

describe('the retired /:slug/assignment route', () => {
  it('sends a bookmark to Jordan, on his Setup tab', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const router = createMemoryRouter(routes, { initialEntries: ['/acme/assignment'] })
    render(
      <QueryClientProvider client={qc}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(router.state.location.pathname).toBe('/acme'))
    expect(router.state.location.search).toBe('?crew=stakeholder_management&tab=setup')

    // And the destination really holds the surface: Jordan's crew is selected, his section
    // is mounted under his own name, and it is the assignment mapping that is on it.
    expect(await screen.findByTestId('selected-crew-stakeholder_management')).toBeInTheDocument()
    expect(await screen.findByTestId('setup-section-Stakeholder Manager')).toBeInTheDocument()
    expect(await screen.findByLabelText('Filter activities')).toBeInTheDocument()
  })
})
