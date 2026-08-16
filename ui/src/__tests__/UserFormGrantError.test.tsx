// ui/src/__tests__/UserFormGrantError.test.tsx
//
// grantMut and revokeMut had no onError at all, so a refused grant was silent: sp38 scoped
// `POST /auth/users/{id}/projects/{slug}` to the caller's own organisation, and an org_admin
// typing another organisation's slug got a 403 that produced no message, no change to the
// list, and no reason to think anything had happened. Shipping a second grantable role while
// leaving that in place would have made two silent refusals rather than one.
//
// Asserted on the server's own sentence, not on a fixed string: "Access denied to this
// project" tells the operator the slug is not theirs, which a generic failure message cannot.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AxiosError, AxiosHeaders } from 'axios'

import UserForm from '../pages/UserForm'
import { adminApi } from '../api/admin'

vi.mock('../api/admin', () => ({
  adminApi: {
    listOrgs: vi.fn().mockResolvedValue([]),
    listUsers: vi.fn(),
    listUserProjects: vi.fn(),
    grantProjectAccess: vi.fn(),
    revokeProjectAccess: vi.fn(),
    createUser: vi.fn(),
    updateUser: vi.fn(),
  },
}))

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'ana', role: 'org_admin' } }),
}))

const ACCESS_DENIED = 'Access denied to this project'

// A genuine AxiosError: describeError narrows through axios.isAxiosError, which reads
// isAxiosError off the instance. A stand-in of the right shape would pass against a
// describeError that read `.response` directly and fail against the real one.
function axios403(detail: string): AxiosError {
  const headers = new AxiosHeaders()
  const config = { headers }
  return new AxiosError(
    'Request failed with status code 403',
    'ERR_BAD_REQUEST',
    config as never,
    {},
    {
      status: 403,
      statusText: 'Forbidden',
      data: { detail },
      headers: {},
      config: config as never,
    },
  )
}

function renderForm() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/admin/users/3']}>
        <Routes>
          <Route path="/admin/users/:userId" element={<UserForm />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('UserForm project access', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(adminApi.listOrgs).mockResolvedValue([] as never)
    vi.mocked(adminApi.listUsers).mockResolvedValue(
      [{ id: 3, username: 'rae', email: 'rae@example.com', role: 'reviewer' }] as never,
    )
    vi.mocked(adminApi.listUserProjects).mockResolvedValue(
      [{ id: 1, project_slug: 'acme' }] as never,
    )
  })

  it('shows the server’s reason when a grant is refused', async () => {
    vi.mocked(adminApi.grantProjectAccess).mockRejectedValue(axios403(ACCESS_DENIED))
    renderForm()

    const slugInput = await screen.findByPlaceholderText('project-slug')
    await userEvent.type(slugInput, 'someone-elses-project')
    await userEvent.click(screen.getByRole('button', { name: 'Grant' }))

    expect(await screen.findByText(ACCESS_DENIED)).toBeInTheDocument()
  })

  it('shows the server’s reason when a revoke is refused', async () => {
    vi.mocked(adminApi.revokeProjectAccess).mockRejectedValue(axios403(ACCESS_DENIED))
    renderForm()

    await userEvent.click(await screen.findByRole('button', { name: 'Revoke' }))

    expect(await screen.findByText(ACCESS_DENIED)).toBeInTheDocument()
  })

  it('says nothing when the grant succeeds', async () => {
    // The control. Without it a component that rendered the message unconditionally would
    // satisfy both tests above.
    vi.mocked(adminApi.grantProjectAccess).mockResolvedValue({ ok: true } as never)
    renderForm()

    const slugInput = await screen.findByPlaceholderText('project-slug')
    await userEvent.type(slugInput, 'acme')
    await userEvent.click(screen.getByRole('button', { name: 'Grant' }))

    await waitFor(() => expect(adminApi.grantProjectAccess).toHaveBeenCalled())
    expect(screen.queryByText(ACCESS_DENIED)).not.toBeInTheDocument()
  })
})
