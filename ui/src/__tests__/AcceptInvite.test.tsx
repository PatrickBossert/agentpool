// ui/src/__tests__/AcceptInvite.test.tsx
//
// The client half of this branch's only Critical fix, and until now the untested half.
// api/routers/invites.py refuses to mint a session when the invite named an email that
// already has a login - accepting an invite for a known address is a membership grant, not
// an authentication event, and a session minted anyway would hand the redeemer of the token
// a live JWT as the victim, sub and role and all, with nothing to notice because the
// password never changed.
//
// The server's refusal only holds if the browser respects it. Deleting the whole
// `if (!resp.access_token)` branch from AcceptInvite.tsx left all 437 frontend tests
// passing: without it, `parseToken(null)` falls through to the `?? { sub: '', role:
// 'reviewer', exp: 0 }` default and login() stores the literal string "null" as a session
// token - so the page reports a successful sign-in and navigates into the app.
//
// Both properties are asserted here, and the storage one is what makes the test
// power-checkable: a token stored is a token the request interceptor will send.
//
// sp41 added the honesty half. The refusal was correct and silent: the page took a password,
// discarded it, and said "sign in with your existing password" - which a person who had just
// chosen one twice read as the one they had just chosen. The tests for that are still
// behavioural rather than copy checks. The wording lives in exactly one place, the server's
// `detail`, so the test that matters asserts the page renders what the server sent (a string
// that appears nowhere in the page's source), not that some sentence exists.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import AcceptInvite from '../pages/AcceptInvite'

vi.mock('../api/endpoints', () => ({
  authApi: {
    accept: vi.fn(),
  },
}))

const TOKEN = 'an-invite-token'

// A real, decodable JWT for the success path - AcceptInvite calls parseToken on whatever
// comes back, and a token whose middle segment is not base64 JSON would exercise the
// fallback branch rather than the ordinary one. Payload: {"sub":"rae@example.com",
// "role":"reviewer","exp":9999999999}.
const REAL_JWT =
  'header.' +
  btoa(JSON.stringify({ sub: 'rae@example.com', role: 'reviewer', exp: 9999999999 })) +
  '.signature'

function renderPage() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[`/accept/${TOKEN}`]}>
        <Routes>
          <Route path="/accept/:token" element={<AcceptInvite />} />
          <Route path="/login" element={<div>login-page</div>} />
          <Route path="/forgotten-password" element={<div>forgotten-page</div>} />
          <Route path="/" element={<div>dashboard-home</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  )
}

async function submitPassword() {
  await userEvent.type(screen.getByLabelText(/^password$/i), 'a-long-enough-password')
  await userEvent.type(screen.getByLabelText(/confirm password/i), 'a-long-enough-password')
  await userEvent.click(screen.getByRole('button', { name: /set password and sign in/i }))
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
})

describe('accepting an invite for an email that already has a login', () => {
  it('stores no token and does not sign the redeemer in', async () => {
    const { authApi } = await import('../api/endpoints')
    vi.mocked(authApi.accept).mockResolvedValue({
      access_token: null,
      token_type: 'bearer',
      already_registered: true,
      detail:
        'An account already exists for this email address - your access has been granted. ' +
        'Sign in with your existing password.',
    })

    renderPage()
    await submitPassword()

    // The load-bearing assertion. Anything stored here is a bearer token the request
    // interceptor will attach to every subsequent call as that account.
    await waitFor(() => expect(screen.getByText(/access granted/i)).toBeInTheDocument())
    expect(localStorage.getItem('ap_token')).toBeNull()
    expect(screen.queryByText('dashboard-home')).not.toBeInTheDocument()
  })

  it("shows the server's explanation and offers the sign-in route, not an error", async () => {
    const { authApi } = await import('../api/endpoints')
    vi.mocked(authApi.accept).mockResolvedValue({
      access_token: null,
      token_type: 'bearer',
      already_registered: true,
      detail: 'An account already exists for this email address.',
    })

    renderPage()
    await submitPassword()

    expect(
      await screen.findByText('An account already exists for this email address.'),
    ).toBeInTheDocument()
    // Not styled or announced as a failure: this person's access genuinely was granted.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /go to sign in/i }))
    expect(await screen.findByText('login-page')).toBeInTheDocument()
  })

  it('offers the reset route, because it has just named a password they may not remember', async () => {
    // sp42. The server's sentence tells this person their existing password is the one to
    // sign in with, and the people who reach this panel are the ones invited to a second
    // engagement months after the first - the population least likely to remember it. Until
    // this branch there was nowhere to send them, so the honest wording was a dead end.
    // Followed rather than merely found: a link is only worth anything if it goes somewhere.
    const { authApi } = await import('../api/endpoints')
    vi.mocked(authApi.accept).mockResolvedValue({
      access_token: null,
      token_type: 'bearer',
      already_registered: true,
      detail: 'An account already exists for this email address.',
    })

    renderPage()
    await submitPassword()
    await screen.findByText(/access granted/i)

    await userEvent.click(screen.getByRole('link', { name: /forgotten your password\?/i }))
    expect(await screen.findByText('forgotten-page')).toBeInTheDocument()
    // Still no session: asking for a reset is not a redemption.
    expect(localStorage.getItem('ap_token')).toBeNull()
  })
})

describe('accepting an invite for a brand new account', () => {
  it('does sign them in - so the refusal above is about the response, not about refusing everything', async () => {
    const { authApi } = await import('../api/endpoints')
    vi.mocked(authApi.accept).mockResolvedValue({
      access_token: REAL_JWT,
      token_type: 'bearer',
    })

    renderPage()
    await submitPassword()

    expect(await screen.findByText('dashboard-home')).toBeInTheDocument()
    expect(localStorage.getItem('ap_token')).toBe(REAL_JWT)
  })
})

describe('the way out for somebody who knows they already have an account', () => {
  it('reaches /login without redeeming the invite or inventing a password', async () => {
    const { authApi } = await import('../api/endpoints')

    renderPage()
    // No password typed at all - the point of the link is that this person should not have
    // to make one up to get off this page.
    await userEvent.click(screen.getByRole('link', { name: /sign in instead/i }))

    expect(await screen.findByText('login-page')).toBeInTheDocument()
    // Outside the <form>, so clicking it must not submit: a submission here would redeem
    // the single-use token against a password nobody chose.
    expect(vi.mocked(authApi.accept)).not.toHaveBeenCalled()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('a response that carries no detail', () => {
  it('still lands on the granted state rather than falling through to a session', async () => {
    const { authApi } = await import('../api/endpoints')
    // The fallback branch: `resp.detail ?? <literal>`. Two ways this can go wrong and both
    // are behavioural, not cosmetic. A page that keyed the granted state off `detail` being
    // present rather than off the absent access_token would treat this as a successful
    // sign-in. And an empty fallback is falsy, so the panel's own condition would fail and
    // put the password form back on screen after a membership that really was granted.
    // Asserting the panel renders at all catches both; no assertion is made on its wording,
    // which belongs to the server (see the verbatim test above).
    vi.mocked(authApi.accept).mockResolvedValue({
      access_token: null,
      token_type: 'bearer',
      already_registered: true,
    })

    renderPage()
    await submitPassword()

    await waitFor(() => expect(screen.getByText(/access granted/i)).toBeInTheDocument())
    expect(localStorage.getItem('ap_token')).toBeNull()
    expect(screen.queryByText('dashboard-home')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/^password$/i)).not.toBeInTheDocument()
  })
})

describe('the invite form refuses before it ever reaches the server', () => {
  it('does not call accept when the two passwords disagree', async () => {
    const { authApi } = await import('../api/endpoints')

    renderPage()
    await userEvent.type(screen.getByLabelText(/^password$/i), 'a-long-enough-password')
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'something-else')
    await userEvent.click(screen.getByRole('button', { name: /set password and sign in/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/passwords do not match/i)
    expect(vi.mocked(authApi.accept)).not.toHaveBeenCalled()
  })
})
