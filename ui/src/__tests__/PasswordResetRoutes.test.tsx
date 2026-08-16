// ui/src/__tests__/PasswordResetRoutes.test.tsx
//
// Where the two reset routes sit in the tree, asserted with no session in storage.
//
// This is the property that cannot be seen by rendering either page directly: both must sit
// outside ProtectedRoute, like /login and /accept-invite. Somebody who has forgotten their
// password has no session and cannot get one until the reset is done, so a route placed
// inside the guard would bounce them to a login they cannot complete - and would do it
// silently, since the pages themselves are perfectly correct either way.
//
// The Login link is checked here for the same reason: it is a destination, and a destination
// is only real if something is mounted at it.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import { AuthProvider } from '../context/AuthContext'
import { routes } from '../router'

vi.mock('../api/endpoints', () => ({
  authApi: {
    login: vi.fn(),
    accept: vi.fn(),
    requestReset: vi.fn(),
    resetPassword: vi.fn(),
  },
  projectsApi: {
    list: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({ crew_runs: [] }),
    outputs: vi.fn().mockResolvedValue([]),
    listReviews: vi.fn().mockResolvedValue([]),
    getSettings: vi.fn().mockResolvedValue({}),
  },
  milestonesApi: { list: vi.fn().mockResolvedValue([]) },
  commitsApi: { readiness: vi.fn().mockResolvedValue({}) },
}))

// See ValueChainRoute.test.tsx for the full account: jsdom's AbortSignal and Node's real
// Request come from different realms, and the data router builds a Request on every
// navigation. No route in this app defines a loader, so nothing here needs real Fetch
// semantics.
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

// No token, deliberately - that is the whole point of these routes.
beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})

function renderAt(initialEntry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(routes, { initialEntries: [initialEntry] })
  render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>,
  )
  return router
}

describe('the reset routes with no session', () => {
  it('serves /forgotten-password rather than bouncing to login', async () => {
    const router = renderAt('/forgotten-password')
    expect(await screen.findByRole('heading', { name: /reset your password/i })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/forgotten-password')
  })

  it('serves /reset-password/:token rather than bouncing to login', async () => {
    // The link somebody follows out of their email or their administrator's message. Behind
    // the guard this redirects to /login, which is the one page they cannot get past.
    const router = renderAt('/reset-password/raw-token-value')
    expect(
      await screen.findByRole('heading', { name: /choose a new password/i }),
    ).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/reset-password/raw-token-value')
  })
})

describe('the way in from the sign-in page', () => {
  it('reaches the request page from Login without a session', async () => {
    // Login had no secondary action at all before this. The link is only worth anything if
    // it lands somewhere that is mounted and reachable unauthenticated, so it is followed
    // here rather than merely found.
    const router = renderAt('/login')
    await userEvent.click(screen.getByRole('link', { name: /forgotten your password\?/i }))

    expect(await screen.findByRole('heading', { name: /reset your password/i })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/forgotten-password')
  })
})
