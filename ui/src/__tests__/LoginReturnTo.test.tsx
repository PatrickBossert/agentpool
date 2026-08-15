// ui/src/__tests__/LoginReturnTo.test.tsx
//
// The brief for this test named the guard `RequireAuth`, imported from AuthContext.tsx.
// Neither is true on this branch: the guard is `ProtectedRoute`, and until this task it lived
// in router.tsx, not AuthContext.tsx, and was not exported at all - see router.tsx's git
// history. It has been moved into AuthContext.tsx and exported as part of this task so it can
// carry the returnTo write and be tested directly. It also depends on useAuth(), so - unlike
// the brief's version - this render needs an AuthProvider ancestor, matching every other test
// in this suite that renders it (ValueChainRoute.test.tsx).
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider, ProtectedRoute } from '../context/AuthContext'

describe('an unauthenticated visit to a guarded route', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('remembers where an unauthenticated visitor was heading', () => {
    // PAM emails a link to one script. A reviewer opens it three weeks later on their phone,
    // logs in, and must land on that script - not on the dashboard, with no idea which of
    // eighty-six they were sent to.
    render(
      <MemoryRouter initialEntries={['/dashboard/projects/sp-gs-am/agents/interaction_designer']}>
        <AuthProvider>
          <ProtectedRoute><div>protected</div></ProtectedRoute>
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(screen.queryByText('protected')).not.toBeInTheDocument()
    expect(sessionStorage.getItem('returnTo'))
      .toBe('/dashboard/projects/sp-gs-am/agents/interaction_designer')
  })

  it('does not touch returnTo when a session is already live', () => {
    localStorage.setItem('ap_token', 'test-token')
    render(
      <MemoryRouter initialEntries={['/dashboard/projects/sp-gs-am/agents/interaction_designer']}>
        <AuthProvider>
          <ProtectedRoute><div>protected</div></ProtectedRoute>
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(screen.getByText('protected')).toBeInTheDocument()
    expect(sessionStorage.getItem('returnTo')).toBeNull()
  })
})
