// ui/src/__tests__/DashboardDeepLink.test.tsx
//
// A notification email (api/services/commit_notify_service.py) names both a crew and the
// Output tab in its link. The panel restores its *last-used* tab from localStorage under a
// key scoped per user/project/crew (AgentDetailPanel.tsx's tabKey) - a deep link must beat
// that saved value, or an approver whose last visit ended on Chat lands on Chat however the
// email was written. The URL wins when present; the saved tab is consulted only when the
// URL says nothing.
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import { routes } from '../router'

// The mocked user's `sub` - AgentDetailPanel builds its localStorage key as
// `ap_panel_tab:${user.sub}:${slug}:${crewKey}`. Without a real user here, tabKey would be
// null, the stored value would never be read, and the middle test below would pass against a
// broken implementation.
const AUTH_SUB = 'deep-link-tester'

vi.mock('../context/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  // Always a live session in this suite, so the guard is a pass-through - matching
  // ProtectedRoute's real behaviour once useAuth().token is truthy.
  ProtectedRoute: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => ({
    token: 'test-token',
    user: { sub: AUTH_SUB, role: 'reviewer', exp: 9999999999 },
    login: vi.fn(),
    logout: vi.fn(),
  }),
}))

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    list: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({ crew_runs: [] }),
    outputs: vi.fn().mockResolvedValue([]),
    listReviews: vi.fn().mockResolvedValue([]),
    getSettings: vi.fn().mockResolvedValue({}),
  },
  milestonesApi: {
    list: vi.fn().mockResolvedValue([]),
  },
  commitsApi: {
    readiness: vi.fn().mockResolvedValue({}),
  },
  valueChainApi: {
    get: vi.fn().mockResolvedValue({ model: null }),
    migrate: vi.fn(),
    save: vi.fn(),
  },
}))

// See ValueChainRoute.test.tsx for the full explanation - Node's real fetch Request rejects
// jsdom's AbortSignal, and createMemoryRouter builds one of these on every navigation.
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

beforeAll(() => {
  vi.stubGlobal('Request', PermissiveRequest)
})

afterAll(() => {
  vi.unstubAllGlobals()
})

beforeEach(() => localStorage.clear())

function renderAt(initialEntry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(routes, { initialEntries: [initialEntry] })
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('deep linking into an agent', () => {
  it('selects the crew named in the URL', async () => {
    renderAt('/acme?crew=discovery_mapping&tab=output')
    expect(await screen.findByTestId('selected-crew-discovery_mapping')).toBeInTheDocument()
  })

  it('opens the tab named in the URL even when a different one was last used', async () => {
    // The whole defect. Without the pre-set value this test passes on a broken
    // implementation, because a fresh localStorage has nothing to lose to.
    localStorage.setItem(`ap_panel_tab:${AUTH_SUB}:acme:discovery_mapping`, 'chat')
    renderAt('/acme?crew=discovery_mapping&tab=output')
    expect(await screen.findByTestId('active-tab-output')).toBeInTheDocument()
  })

  it('falls back to the saved tab when the URL names none', async () => {
    // No ?crew=, so Dashboard's default selection (PAM) is what the saved key must match.
    localStorage.setItem(`ap_panel_tab:${AUTH_SUB}:acme:PAM`, 'chat')
    renderAt('/acme')
    expect(await screen.findByTestId('active-tab-chat')).toBeInTheDocument()
  })
})
