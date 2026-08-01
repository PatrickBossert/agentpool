// ui/src/__tests__/ValueChainRoute.test.tsx
//
// The value chain page is retired - notification emails already sent and bookmarks made
// before the retirement still point at /:slug/value-chain. A 404 would strand them, so the
// route redirects to the Dashboard instead, with Alex (discovery_mapping) and the Output tab
// named in the query string for the Dashboard to read (a later task wires up the reading).
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, beforeEach } from 'vitest'
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
