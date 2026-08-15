// ui/src/__tests__/LoginReturnTo.test.tsx
//
// The brief for this test named the guard `RequireAuth`, imported from AuthContext.tsx.
// Neither is true on this branch: the guard is `ProtectedRoute`, and until this task it lived
// in router.tsx, not AuthContext.tsx, and was not exported at all - see router.tsx's git
// history. It has been moved into AuthContext.tsx and exported as part of this task so it can
// carry the returnTo write and be tested directly. It also depends on useAuth(), so - unlike
// the brief's version - every render here needs an AuthProvider ancestor, matching every other
// test in this suite that renders it (ValueChainRoute.test.tsx).
//
// The brief's own test asserted a stored path of "/dashboard/projects/sp-gs-am/agents/...",
// but the guard never sees that prefix: router.tsx mounts the real router with
// `basename: '/dashboard'`, which React Router strips before location.pathname reaches any
// component. A bare MemoryRouter with no basename (as below) is the shape the guard actually
// runs under.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  MemoryRouter,
  Outlet,
  createMemoryRouter,
  RouterProvider,
  useLocation,
  useNavigate,
} from 'react-router-dom'
import { AuthProvider, ProtectedRoute, useAuth } from '../context/AuthContext'
import Login from '../pages/Login'

vi.mock('../api/endpoints', () => ({
  authApi: {
    login: vi.fn().mockResolvedValue({ access_token: 'test-token', token_type: 'bearer' }),
  },
}))

function resetStorage() {
  localStorage.clear()
  sessionStorage.clear()
}

// Same stand-in as ValueChainRoute.test.tsx, for the same reason: createMemoryRouter builds
// a real Request object on every navigation, and jsdom's AbortController/AbortSignal are a
// different realm from Node's real fetch Request that vitest's jsdom environment copies in -
// so a strict `signal instanceof AbortSignal` check rejects a jsdom-made signal. No route
// below defines a loader, so nothing here needs real fetch Request semantics.
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

describe('an unauthenticated visit to a guarded route', () => {
  beforeEach(resetStorage)

  it('remembers where an unauthenticated visitor was heading', () => {
    // PAM emails a link to one script. A reviewer opens it three weeks later on their phone,
    // logs in, and must land on that script - not on the dashboard, with no idea which of
    // eighty-six they were sent to.
    render(
      <MemoryRouter initialEntries={['/acme/agents/interaction_designer']}>
        <AuthProvider>
          <ProtectedRoute><div>protected</div></ProtectedRoute>
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(screen.queryByText('protected')).not.toBeInTheDocument()
    expect(sessionStorage.getItem('returnTo')).toBe('/acme/agents/interaction_designer')
  })

  it('does not touch returnTo when a session is already live', () => {
    localStorage.setItem('ap_token', 'test-token')
    render(
      <MemoryRouter initialEntries={['/acme/agents/interaction_designer']}>
        <AuthProvider>
          <ProtectedRoute><div>protected</div></ProtectedRoute>
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(screen.getByText('protected')).toBeInTheDocument()
    expect(sessionStorage.getItem('returnTo')).toBeNull()
  })
})

// router.tsx's real shape: a single ProtectedRoute wraps a layout element with children
// reached through an <Outlet/>, and that one instance stays mounted across every in-app
// navigation between those children (only the nested match changes, not the '/' match the
// guard itself sits on). A version of the guard that captured its destination once, on
// first mount (via useRef), froze at wherever the app was first entered and reported that
// stale path on a later sign-out instead of wherever the visitor actually was - this is the
// regression test for that: it fails against a ref-captured path and passes against a
// freshly-read one.
function Layout() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  return (
    <div>
      <div data-testid="current-path">{location.pathname}</div>
      <Outlet />
      <button onClick={() => navigate('/beta/runs')}>go to beta</button>
      {/* Deliberately calls only logout(), with no navigate() of its own - the same shape
          as a session dropping out from under a visitor mid-browse (e.g. client.ts's 401
          interceptor clearing the token on a stale request), which leaves the guard's own
          <Navigate> as the only thing that redirects. A button that also called navigate()
          itself would race that imperative call against ProtectedRoute's reactive one and
          prove nothing reliable about which location the guard captured. */}
      <button onClick={() => logout()}>session drops</button>
    </div>
  )
}

const productionShapedRoutes = [
  { path: '/login', element: <div>login-page</div> },
  {
    path: '/',
    element: <ProtectedRoute><Layout /></ProtectedRoute>,
    children: [
      { path: ':slug', element: <div>slug-page</div> },
      { path: ':slug/runs', element: <div>runs-page</div> },
      { path: ':slug/agents/:agentName', element: <div>agent-page</div> },
    ],
  },
]

function renderProductionShaped(initialEntry: string) {
  const router = createMemoryRouter(productionShapedRoutes, { initialEntries: [initialEntry] })
  render(<AuthProvider><RouterProvider router={router} /></AuthProvider>)
  return router
}

describe('the guard under its real, Outlet-nested mounting', () => {
  beforeEach(resetStorage)

  it('captures a deep-linked nested path through a real route match', async () => {
    renderProductionShaped('/acme/agents/interaction_designer')
    expect(await screen.findByText('login-page')).toBeInTheDocument()
    expect(sessionStorage.getItem('returnTo')).toBe('/acme/agents/interaction_designer')
  })

  it('reflects the last active page when the session drops mid-browse, not wherever the app was first entered', async () => {
    localStorage.setItem('ap_token', 'test-token')
    renderProductionShaped('/acme')
    expect(await screen.findByTestId('current-path')).toHaveTextContent('/acme')

    // In-app navigation to a different project's page - the single ProtectedRoute instance
    // wrapping Layout stays mounted through this, since '/' still matches both times.
    await userEvent.click(screen.getByText('go to beta'))
    expect(await screen.findByTestId('current-path')).toHaveTextContent('/beta/runs')

    await userEvent.click(screen.getByText('session drops'))
    expect(await screen.findByText('login-page')).toBeInTheDocument()
    // A frozen ref would report "/acme" here - the page the app happened to be entered on,
    // two navigations ago - rather than "/beta/runs", the page actually being read when the
    // session dropped.
    expect(sessionStorage.getItem('returnTo')).toBe('/beta/runs')
  })
})

// The other half of the round trip: LoginReturnTo's own tests above prove the guard *writes*
// returnTo. Nothing proved Login.tsx *reads* it back - the pattern CLAUDE.md names, a
// property tested one layer away from where it holds.
describe("Login consumes the guard's returnTo", () => {
  beforeEach(resetStorage)

  it('sends a returning visitor back to the page they were trying to reach, and clears the marker', async () => {
    sessionStorage.setItem('returnTo', '/acme/agents/interaction_designer')
    // productionShapedRoutes' own '/login' entry is a static placeholder with no form - swap
    // in the real Login page here, sharing the same route table so its navigate() call after
    // a successful sign-in is observable through the matched destination actually rendering.
    const router = createMemoryRouter(
      [
        { path: '/login', element: <Login /> },
        ...productionShapedRoutes.filter((r) => r.path !== '/login'),
      ],
      { initialEntries: ['/login'] },
    )
    render(<AuthProvider><RouterProvider router={router} /></AuthProvider>)

    await userEvent.type(screen.getByLabelText(/username/i), 'admin')
    await userEvent.type(screen.getByLabelText(/password/i), 'password')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findByText('agent-page')).toBeInTheDocument()
    expect(sessionStorage.getItem('returnTo')).toBeNull()
  })
})
