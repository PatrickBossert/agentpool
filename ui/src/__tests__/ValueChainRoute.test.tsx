// ui/src/__tests__/ValueChainRoute.test.tsx
//
// The value chain page is retired - notification emails already sent and bookmarks made
// before the retirement still point at /:slug/value-chain. A 404 would strand them, so the
// route redirects to the Dashboard instead, with Alex (discovery_mapping) and the Output tab
// named in the query string for the Dashboard to read (a later task wires up the reading).
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, beforeEach, beforeAll, afterAll } from 'vitest'
import { AuthProvider } from '../context/AuthContext'
import { routes } from '../router'

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
}))

// Vitest's jsdom environment copies Node's real fetch/Request onto the test window (jsdom
// implements neither), but leaves jsdom's own AbortController/AbortSignal in place (jsdom
// does implement those, for XMLHttpRequest.abort()). The two are different classes from
// different realms, so Node's real Request constructor - which strictly checks `signal
// instanceof <its own AbortSignal>` - rejects a signal made by jsdom's AbortController with
// "Expected signal to be an instance of AbortSignal". createMemoryRouter/createBrowserRouter
// build one of these Request objects on every navigation, including the plain client-side
// <Navigate> this route issues, so this file - the only one in the suite using a data router
// - hits it. No route in this app defines a loader, so nothing here needs real fetch Request
// semantics; stubbed only for this file's globalThis, restored after, so a future test that
// does exercise real Fetch semantics through a loader fails on its own terms rather than
// inheriting a stand-in nobody expected to find here.
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

// ProtectedRoute only checks for a truthy token - AppLayout and Dashboard both read `user`
// with optional chaining throughout, so an unparsed/absent user does not crash the tree.
beforeEach(() => {
  localStorage.setItem('ap_token', 'test-token')
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

describe('the retired value chain route', () => {
  it('redirects to the Dashboard with Alex selected rather than 404ing', async () => {
    // Bookmarks and already-sent emails point here. A 404 strands them.
    renderAt('/acme/value-chain')
    expect(await screen.findByTestId('dashboard')).toBeInTheDocument()
  })

  it("preserves the slug and names Alex's crew and the Output tab in the query string", async () => {
    const router = renderAt('/acme-rail/value-chain')
    await screen.findByTestId('dashboard')

    expect(router.state.location.pathname).toBe('/acme-rail')
    expect(router.state.location.search).toBe('?crew=discovery_mapping&tab=output')
  })
})
