// ui/src/__tests__/DataArchitectureRoute.test.tsx
//
// Where /data-architecture sits in the route tree.
//
// It sat outside every guard - public by omission rather than by design. Nothing public has
// ever linked to it, its one link lives in the header inside ProtectedRoute, and /architecture
// beside it was already guarded, so the omission was invisible from either end. It is a
// property of the tree and of nothing else: the page renders perfectly well whatever session
// the viewer has, which is exactly why rendering the page directly cannot see this.
//
// Mounted from the real `routes` export, so it is the shipped tree that is asserted rather
// than an arrangement built for the test.
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, beforeEach, beforeAll, afterAll, vi } from 'vitest'
import { AuthProvider } from '../context/AuthContext'
import { routes } from '../router'

vi.mock('../api/dataArchitecture', () => ({
  dataArchitectureApi: {
    get: vi.fn().mockResolvedValue({
      slug: 'northern-water',
      llm_mode: 'standard',
      inference: {
        reaches: 'a language model',
        sends: 'every prompt',
        destination: 'a destination for the test',
        leaves_deployment: true,
        gated_by_mode: true,
      },
      tools: [],
      declared_not_held: [],
      agents: [],
      crews: [],
      dispatch_paths: [],
      dispatch_reads: [],
      shared_sources: [],
      scope: { crew_count: 0, agents_in_no_crew: [] },
    }),
  },
}))

vi.mock('../api/endpoints', () => ({
  authApi: { login: vi.fn(), accept: vi.fn(), requestReset: vi.fn(), resetPassword: vi.fn() },
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

// See ValueChainRoute.test.tsx: jsdom's AbortSignal and Node's real Request come from
// different realms, and the data router builds a Request on every navigation.
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

// A token AuthProvider can decode: it reads the middle segment as base64 JSON and nothing else.
function tokenFor(role: string): string {
  return `header.${btoa(JSON.stringify({ sub: 'someone', role }))}.signature`
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>,
  )
  return router
}

describe('/data-architecture is no longer public', () => {
  it('sends a visitor with no session to the sign-in page', async () => {
    const router = renderAt('/data-architecture')
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
  })

  it('sends a visitor with no session away from a named engagement too', async () => {
    // The report itself, not only the chooser. Guarding one of the two would leave the other
    // open, and the one carrying a client's slug is the one that matters.
    const router = renderAt('/data-architecture/northern-water')
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
  })

  it('turns a signed-in reviewer away', async () => {
    // Administrator-only, not merely signed-in: a reviewer has a valid session, so a guard
    // that only asked for one would let them through.
    localStorage.setItem('ap_token', tokenFor('reviewer'))
    const router = renderAt('/data-architecture/northern-water')
    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
    expect(screen.queryByText(/a destination for the test/)).toBeNull()
  })

  it('serves an administrator the engagement they asked for', async () => {
    localStorage.setItem('ap_token', tokenFor('sysadmin'))
    const router = renderAt('/data-architecture/northern-water')
    expect(await screen.findByText(/a destination for the test/)).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/data-architecture/northern-water')
  })

  it('serves an organisation administrator the chooser', async () => {
    localStorage.setItem('ap_token', tokenFor('org_admin'))
    const router = renderAt('/data-architecture')
    expect(await screen.findByText(/Which engagement\?/)).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/data-architecture')
  })
})
