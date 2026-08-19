// ui/src/__tests__/AdminDashboardPlatformSettings.test.tsx
//
// The platform public URL panel on AdminDashboard - Task 4 of the platform-public-url plan.
// Driven through the real exported apiClient with a stand-in adapter (the pattern
// client.test.ts established, adminUsersApi.test.ts and inviteLinkApi.test.ts follow),
// rather than mocking adminApi wholesale. CLAUDE.md names the shape being avoided here: "a
// radio tested as *rendered*, not as *sent*" - a test that finds the input and the button in
// the DOM proves nothing about the request body that leaves the browser, and this branch has
// already produced four tests that passed without testing what they were named for. Every
// test below reads what actually reached the adapter's config, not what a mocked function
// was merely called with.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { AxiosRequestConfig, AxiosResponse } from 'axios'
import { apiClient } from '../api/client'
import AdminDashboard from '../pages/AdminDashboard'

type Role = 'sysadmin' | 'org_admin' | 'reviewer'

let mockRole: Role = 'sysadmin'
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: { sub: 'ana', role: mockRole } }),
}))

type Seen = { method?: string; url?: string; body: unknown }

const realAdapter = apiClient.defaults.adapter
let seen: Seen[] = []

function jsonBody(data: unknown): unknown {
  return typeof data === 'string' ? JSON.parse(data) : data
}

const PLATFORM_SETTINGS_URL = '/admin/platform-settings'

/** Stubs /auth/orgs and /auth/users (AdminDashboard's other two queries, unconditional on
 * role) with empty lists, and routes /admin/platform-settings through the handlers passed
 * in - each keyed by HTTP method, each free to resolve or reject. Any other request throws,
 * so an unstubbed call fails loudly rather than hanging the test. */
function stubAdapter(platformHandlers: {
  get?: () => Promise<AxiosResponse> | AxiosResponse
  patch?: () => Promise<AxiosResponse> | AxiosResponse
  delete?: () => Promise<AxiosResponse> | AxiosResponse
}) {
  apiClient.defaults.adapter = async (config: AxiosRequestConfig) => {
    const method = (config.method ?? 'get').toLowerCase()
    seen.push({ method, url: config.url, body: jsonBody(config.data) })

    if (config.url === '/auth/orgs') {
      return { data: [], status: 200, statusText: 'OK', headers: {}, config } as AxiosResponse
    }
    if (config.url === '/auth/users') {
      return { data: [], status: 200, statusText: 'OK', headers: {}, config } as AxiosResponse
    }
    if (config.url === PLATFORM_SETTINGS_URL) {
      const handler = (platformHandlers as Record<string, (() => Promise<AxiosResponse> | AxiosResponse) | undefined>)[method]
      if (handler) return handler()
    }
    throw new Error(`unstubbed request: ${method.toUpperCase()} ${config.url}`)
  }
}

function okResponse(data: unknown, config: AxiosRequestConfig = {}): AxiosResponse {
  return { data, status: 200, statusText: 'OK', headers: {}, config } as AxiosResponse
}

function refused(status: number, detail: string) {
  return () =>
    Promise.reject(
      Object.assign(new Error(`Request failed with status code ${status}`), {
        isAxiosError: true,
        response: { status, data: { detail }, headers: {} },
      }),
    )
}

function renderDashboard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminDashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  seen = []
  mockRole = 'sysadmin'
  localStorage.clear()
})

afterEach(() => {
  apiClient.defaults.adapter = realAdapter
})

describe('saving the public URL', () => {
  it('PATCHes the typed value, as its own request body, to /admin/platform-settings', async () => {
    stubAdapter({
      get: () => okResponse({ public_url: 'https://old.example', source: 'stored' }),
      patch: () => okResponse({ public_url: 'https://new.example', source: 'stored' }),
    })
    renderDashboard()

    const input = await screen.findByDisplayValue('https://old.example')
    await userEvent.clear(input)
    await userEvent.type(input, 'https://new.example')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(seen.some((s) => s.method === 'patch' && s.url === PLATFORM_SETTINGS_URL)).toBe(true),
    )
    const patched = seen.find((s) => s.method === 'patch' && s.url === PLATFORM_SETTINGS_URL)
    // The whole body, not a substring of it - a client that sent extra keys or the wrong
    // key name would still satisfy a `toContain`-style assertion.
    expect(patched?.body).toEqual({ public_url: 'https://new.example' })
  })

  it('reflects the server’s normalised form back into the field, not the raw draft', async () => {
    // save_platform_public_url strips a trailing slash server-side; the field must show what
    // was actually stored; showing the raw typed value would silently misinform an
    // administrator about what every subsequent email link will contain.
    stubAdapter({
      get: () => okResponse({ public_url: 'https://old.example', source: 'stored' }),
      patch: () => okResponse({ public_url: 'https://new.example', source: 'stored' }),
    })
    renderDashboard()

    const input = await screen.findByDisplayValue('https://old.example')
    await userEvent.clear(input)
    await userEvent.type(input, 'https://new.example/')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await screen.findByDisplayValue('https://new.example')
  })

  it('shows the server’s own refusal sentence, not a fixed string', async () => {
    const REFUSAL = "A public URL must begin http:// or https:// - 'ftp' is neither."
    stubAdapter({
      get: () => okResponse({ public_url: 'https://old.example', source: 'stored' }),
      patch: refused(400, REFUSAL),
    })
    renderDashboard()

    const input = await screen.findByDisplayValue('https://old.example')
    await userEvent.clear(input)
    await userEvent.type(input, 'ftp://bad.example')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(REFUSAL)).toBeInTheDocument()
  })
})

describe('reverting to the environment default', () => {
  it('DELETEs /admin/platform-settings with no body', async () => {
    stubAdapter({
      get: () => okResponse({ public_url: 'https://stored.example', source: 'stored' }),
      delete: () => okResponse({ public_url: 'https://env.example', source: 'environment' }),
    })
    renderDashboard()

    await screen.findByDisplayValue('https://stored.example')
    await userEvent.click(screen.getByRole('button', { name: 'Revert to environment default' }))

    await waitFor(() =>
      expect(seen.some((s) => s.method === 'delete' && s.url === PLATFORM_SETTINGS_URL)).toBe(true),
    )
    const del = seen.find((s) => s.method === 'delete' && s.url === PLATFORM_SETTINGS_URL)
    expect(del?.body).toBeUndefined()
  })

  it('updates the field and the source badge from the server’s response', async () => {
    stubAdapter({
      get: () => okResponse({ public_url: 'https://stored.example', source: 'stored' }),
      delete: () => okResponse({ public_url: 'https://env.example', source: 'environment' }),
    })
    renderDashboard()

    await screen.findByDisplayValue('https://stored.example')
    expect(screen.getByText('a saved setting')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Revert to environment default' }))

    await screen.findByDisplayValue('https://env.example')
    expect(screen.getByText('inherited from the PUBLIC_URL environment variable')).toBeInTheDocument()
    expect(screen.queryByText('a saved setting')).not.toBeInTheDocument()
  })

  it('shows the server’s own refusal sentence on a refused revert, not a fixed string', async () => {
    const REFUSAL = 'Org admin or above required'
    stubAdapter({
      get: () => okResponse({ public_url: 'https://stored.example', source: 'stored' }),
      delete: refused(403, REFUSAL),
    })
    renderDashboard()

    await screen.findByDisplayValue('https://stored.example')
    await userEvent.click(screen.getByRole('button', { name: 'Revert to environment default' }))

    expect(await screen.findByText(REFUSAL)).toBeInTheDocument()
  })
})

describe('visibility is gated on the role the token carries', () => {
  it('renders the panel, and asks the server for the setting, for a sysadmin', async () => {
    mockRole = 'sysadmin'
    stubAdapter({
      get: () => okResponse({ public_url: 'https://stored.example', source: 'stored' }),
    })
    renderDashboard()

    expect(await screen.findByText('Platform Public URL')).toBeInTheDocument()
    await waitFor(() =>
      expect(seen.some((s) => s.method === 'get' && s.url === PLATFORM_SETTINGS_URL)).toBe(true),
    )
  })

  it('renders neither the panel nor a request to it for an org_admin', async () => {
    // The control that makes the sysadmin test above meaningful: without it, a panel that
    // always rendered would pass the test above too.
    mockRole = 'org_admin'
    stubAdapter({})
    renderDashboard()

    // Something unrelated has to resolve first, so there is a moment to have asked and not
    // have - the org list settling is that moment.
    await waitFor(() => expect(seen.some((s) => s.url === '/auth/orgs')).toBe(true))

    expect(screen.queryByText('Platform Public URL')).not.toBeInTheDocument()
    expect(seen.some((s) => s.url === PLATFORM_SETTINGS_URL)).toBe(false)
  })
})
