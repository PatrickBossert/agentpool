// ui/src/__tests__/PasswordResetPages.test.tsx
//
// The three pages of the reset surface, asserted on what they send and what they store -
// not on what they render, except where the rendering *is* the property (the acknowledgement
// that must not vary, and the link an administrator has to be able to copy).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import ForgottenPassword from '../pages/ForgottenPassword'
import ResetPassword from '../pages/ResetPassword'
import UserList, { resetLinkUrl } from '../pages/UserList'

vi.mock('../api/endpoints', () => ({
  authApi: {
    requestReset: vi.fn(),
    resetPassword: vi.fn(),
  },
}))

vi.mock('../api/admin', () => ({
  adminApi: {
    listUsers: vi.fn(),
    deleteUser: vi.fn(),
    issueResetLink: vi.fn(),
  },
}))

// A real, decodable JWT - ResetPassword calls parseToken on whatever comes back, and a token
// whose middle segment is not base64 JSON would exercise the fallback branch instead of the
// ordinary one. Payload: {"sub":"rae@example.com","role":"reviewer","exp":9999999999}.
const REAL_JWT =
  'header.' +
  btoa(JSON.stringify({ sub: 'rae@example.com', role: 'reviewer', exp: 9999999999 })) +
  '.signature'

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
})

// ── The self-service request ─────────────────────────────────────────────────

function renderForgotten() {
  return render(
    <MemoryRouter initialEntries={['/forgotten-password']}>
      <Routes>
        <Route path="/forgotten-password" element={<ForgottenPassword />} />
        <Route path="/login" element={<div>login-page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

async function askForALink(address = 'rae@example.com') {
  await userEvent.type(screen.getByLabelText(/email address/i), address)
  await userEvent.click(screen.getByRole('button', { name: /send reset link/i }))
}

describe('asking for a reset link', () => {
  it('sends the address that was typed', async () => {
    const { authApi } = await import('../api/endpoints')
    vi.mocked(authApi.requestReset).mockResolvedValue(undefined)

    renderForgotten()
    await askForALink('rae@example.com')

    await waitFor(() => expect(vi.mocked(authApi.requestReset)).toHaveBeenCalledWith('rae@example.com'))
  })

  it('says the same thing whether the request succeeded or failed', async () => {
    // The page's one security property, and the client half of the server's 204-always
    // contract. The server never distinguishes a known address from an unknown one; a page
    // that showed an acknowledgement on success and an error on rejection would hand that
    // distinction straight back the moment the endpoint ever refused anything - and would
    // do it for a network blip too, telling somebody with a perfectly good account that
    // something is wrong with their address.
    //
    // Compared as whole rendered text rather than by looking for one sentence, for the same
    // reason the backend test compares whole responses: it is the *difference* that is the
    // defect, wherever it appears.
    const { authApi } = await import('../api/endpoints')

    vi.mocked(authApi.requestReset).mockResolvedValue(undefined)
    const resolved = renderForgotten()
    await askForALink()
    await screen.findByText(/request received/i)
    const afterSuccess = resolved.container.textContent
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    resolved.unmount()

    vi.mocked(authApi.requestReset).mockRejectedValue(new Error('refused'))
    const rejected = renderForgotten()
    await askForALink()
    await screen.findByText(/request received/i)
    const afterFailure = rejected.container.textContent

    expect(afterFailure).toBe(afterSuccess)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('promises nothing about whether the address exists', async () => {
    const { authApi } = await import('../api/endpoints')
    vi.mocked(authApi.requestReset).mockResolvedValue(undefined)

    renderForgotten()
    await askForALink()

    // Conditional by construction - "if that address has an account". A page that said "a
    // link has been sent" would be a promise the server has not made, and on an address with
    // no account it would be untrue.
    expect(await screen.findByText(/if that address has an account/i)).toBeInTheDocument()
  })
})

// ── Redeeming the link ───────────────────────────────────────────────────────

function renderReset(token = 'tok-from-the-url') {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[`/reset-password/${token}`]}>
        <Routes>
          <Route path="/reset-password/:token" element={<ResetPassword />} />
          <Route path="/forgotten-password" element={<div>forgotten-page</div>} />
          <Route path="/" element={<div>dashboard-home</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  )
}

async function chooseAPassword(pw = 'a-long-enough-password', confirm = pw) {
  await userEvent.type(screen.getByLabelText(/^new password$/i), pw)
  await userEvent.type(screen.getByLabelText(/confirm new password/i), confirm)
  await userEvent.click(screen.getByRole('button', { name: /set password and sign in/i }))
}

describe('redeeming a reset link', () => {
  it('sends the token from the URL with the chosen password', async () => {
    // The token is never typed - it arrives in the path, and a page that read it from
    // anywhere else (or dropped it) would send a request the server can only refuse.
    const { authApi } = await import('../api/endpoints')
    vi.mocked(authApi.resetPassword).mockResolvedValue({
      access_token: REAL_JWT, token_type: 'bearer',
    })

    renderReset('tok-from-the-url')
    await chooseAPassword('a-long-enough-password')

    await waitFor(() =>
      expect(vi.mocked(authApi.resetPassword)).toHaveBeenCalledWith(
        'tok-from-the-url',
        'a-long-enough-password',
      ),
    )
  })

  it('signs the person in with the session the server minted', async () => {
    const { authApi } = await import('../api/endpoints')
    vi.mocked(authApi.resetPassword).mockResolvedValue({
      access_token: REAL_JWT, token_type: 'bearer',
    })

    renderReset()
    await chooseAPassword()

    expect(await screen.findByText('dashboard-home')).toBeInTheDocument()
    // Stored, not merely navigated to: this is the bearer the request interceptor sends.
    expect(localStorage.getItem('ap_token')).toBe(REAL_JWT)
  })

  it('stores nothing and offers a new link when the token is refused', async () => {
    const { authApi } = await import('../api/endpoints')
    vi.mocked(authApi.resetPassword).mockRejectedValue(new Error('400'))

    renderReset()
    await chooseAPassword()

    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid, has expired, or has already been used/i)
    expect(localStorage.getItem('ap_token')).toBeNull()
    expect(screen.queryByText('dashboard-home')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('link', { name: /ask for a new link/i }))
    expect(await screen.findByText('forgotten-page')).toBeInTheDocument()
  })

  it('does not spend the single-use token when the two passwords disagree', async () => {
    const { authApi } = await import('../api/endpoints')

    renderReset()
    await chooseAPassword('a-long-enough-password', 'something-else')

    expect(await screen.findByRole('alert')).toHaveTextContent(/passwords do not match/i)
    expect(vi.mocked(authApi.resetPassword)).not.toHaveBeenCalled()
  })
})

// ── The administrator door ───────────────────────────────────────────────────

// Usernames deliberately unlike the emails: administrator-created logins need not have the
// two equal, and the row a click resolves to has to be the row, not whichever cell happens
// to match first.
const USERS = [
  { id: 4, username: 'a.lovelace', email: 'ada@example.com', role: 'reviewer',
    created_at: '2026-01-02T00:00:00' },
  { id: 9, username: 'r.patel', email: 'rae@example.com', role: 'org_admin',
    created_at: '2026-02-03T00:00:00' },
]

function renderUserList() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <UserList />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('an administrator issuing a reset link', () => {
  it('asks for a link for the row it was clicked on', async () => {
    const { adminApi } = await import('../api/admin')
    vi.mocked(adminApi.listUsers).mockResolvedValue(USERS)
    vi.mocked(adminApi.issueResetLink).mockResolvedValue({
      reset_token: 'raw-token-value', username: 'r.patel', email: 'rae@example.com',
    })

    renderUserList()
    const row = (await screen.findByText('r.patel')).closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: /reset link/i }))

    // The id, not the index or the first row: a page that sent the wrong one would reset
    // somebody else's account and hand the administrator a link that looks perfectly right.
    await waitFor(() => expect(vi.mocked(adminApi.issueResetLink)).toHaveBeenCalledWith(9))
  })

  it('shows the whole redeemable link, and keeps showing it', async () => {
    // The token cannot be recovered once lost - the server stores only its digest, and
    // asking again mints a different one, killing the first. So it has to be on the page,
    // in full, until the administrator dismisses it: a toast that vanished would silently
    // invalidate the link they were about to send.
    const { adminApi } = await import('../api/admin')
    vi.mocked(adminApi.listUsers).mockResolvedValue(USERS)
    vi.mocked(adminApi.issueResetLink).mockResolvedValue({
      reset_token: 'raw-token-value', username: 'r.patel', email: 'rae@example.com',
    })

    renderUserList()
    const row = (await screen.findByText('r.patel')).closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: /reset link/i }))

    // The exact string an administrator will paste into a message. It has to be the route
    // ResetPassword is mounted at and it has to carry the raw token - a panel showing the
    // bare token, or a path nothing serves, sends somebody nowhere.
    const link = await screen.findByText(/\/reset-password\/raw-token-value$/)
    expect(link).toBeInTheDocument()
    expect(link.textContent).toBe(resetLinkUrl('raw-token-value'))

    // Still there after the page has had every chance to settle.
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.getByText(/\/reset-password\/raw-token-value$/)).toBeInTheDocument()

    // And it says, unmissably, that the sending is the administrator's job - the whole
    // failure mode here is assuming the system emailed it.
    expect(screen.getByText(/nothing has been emailed/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /dismiss reset link/i }))
    expect(screen.queryByText(/\/reset-password\/raw-token-value$/)).not.toBeInTheDocument()
  })

  it('says so rather than showing a link when the server refuses', async () => {
    const { adminApi } = await import('../api/admin')
    vi.mocked(adminApi.listUsers).mockResolvedValue(USERS)
    vi.mocked(adminApi.issueResetLink).mockRejectedValue(new Error('409'))

    renderUserList()
    const row = (await screen.findByText('a.lovelace')).closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: /reset link/i }))

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText(/\/reset-password\//)).not.toBeInTheDocument()
  })
})
