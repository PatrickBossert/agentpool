// ui/src/__tests__/client.test.ts
//
// The read half of the rolling-session round trip. tests/test_rolling_session.py proves the
// server writes X-Refreshed-Token; nothing before this proved the browser actually reads it.
// A middleware bug that set the header to a truthy-but-useless value (see review: "x") would
// satisfy a bare truthiness check on the server side and then log everyone out on the very
// next request once client.ts stored "x" as the session token - the two halves have to be
// proven together, per CLAUDE.md's recurring failure mode.
import type { AxiosRequestConfig, AxiosResponse } from 'axios'
import { apiClient, storeRefreshedToken } from '../api/client'

// sp43: the base was the literal 'http://localhost:8000', so every call went to the viewer's
// own machine and bypassed Vite's proxy in development and Caddy in production. Nothing could
// see it: a unit suite has no proxy, and `vite dev` on the developer's own laptop is a machine
// where localhost:8000 happens to be the API.
//
// Asserted on the URL the transport is given, not on the exported API_BASE constant. Reading
// the constant back would only prove the constant: a base that never reached axios.create, or
// an interceptor putting a host back, would both sail through it. The adapter here stands in
// for the network and is handed the fully merged config the real interceptors produced;
// getUri is the same composition of baseURL and url that axios's own xhr and fetch adapters
// perform to decide where to send the request.
//
// A relative URL resolves against the page origin - that is the property, so the assertion
// resolves it the way a browser would and checks the origin it lands on. With the old base
// the transport was handed 'http://localhost:8000/auth/login', a different origin, and no
// amount of proxy configuration could have helped.
describe('every request goes to whatever origin served the page', () => {
  const realAdapter = apiClient.defaults.adapter

  afterEach(() => {
    apiClient.defaults.adapter = realAdapter
  })

  function captureSentUrls(): string[] {
    const sent: string[] = []
    apiClient.defaults.adapter = (config: AxiosRequestConfig) => {
      sent.push(apiClient.getUri(config))
      return Promise.resolve({
        data: {}, status: 200, statusText: 'OK', headers: {}, config,
      } as AxiosResponse)
    }
    return sent
  }

  it.each([
    ['/auth/login'],
    ['/projects'],
    ['/projects/acme/script-ledger'],
    ['/system/heartbeat'],
  ])('sends %s to the page origin, not to a hardcoded host', async (path) => {
    const sent = captureSentUrls()

    await apiClient.get(path)

    expect(sent).toHaveLength(1)
    const resolved = new URL(sent[0], window.location.href)
    expect(resolved.origin).toBe(window.location.origin)
    expect(resolved.pathname).toBe(path)
  })

  it('keeps query parameters on the same-origin URL', async () => {
    const sent = captureSentUrls()

    await apiClient.get('/projects/acme/outputs', { params: { output_type: 'value_chain' } })

    const resolved = new URL(sent[0], window.location.href)
    expect(resolved.origin).toBe(window.location.origin)
    expect(resolved.pathname).toBe('/projects/acme/outputs')
    expect(resolved.searchParams.get('output_type')).toBe('value_chain')
  })
})

function fakeResponse(headers: Record<string, string>): AxiosResponse {
  return {
    data: {},
    status: 200,
    statusText: 'OK',
    headers,
    config: {} as AxiosResponse['config'],
  }
}

describe('storeRefreshedToken', () => {
  beforeEach(() => localStorage.clear())

  it('stores a refreshed token when the server sends one', () => {
    const response = fakeResponse({ 'x-refreshed-token': 'a.fresh.token' })
    storeRefreshedToken(response)
    expect(localStorage.getItem('ap_token')).toBe('a.fresh.token')
  })

  it('returns the response unchanged, so callers still see their real data', () => {
    const response = fakeResponse({ 'x-refreshed-token': 'a.fresh.token' })
    expect(storeRefreshedToken(response)).toBe(response)
  })

  it('leaves any existing token alone when the response carries no refreshed one', () => {
    localStorage.setItem('ap_token', 'still-good')
    storeRefreshedToken(fakeResponse({}))
    expect(localStorage.getItem('ap_token')).toBe('still-good')
  })
})

// Round 2 review: the unit tests above call storeRefreshedToken directly, so they cannot see
// whether it is actually *wired in* - a reviewer replaced the response interceptor with
// `(response) => response` and all 435 frontend tests still passed. They also do not touch
// the request interceptor at all, which reads its own 'ap_token' string literal rather than
// AuthContext's TOKEN_KEY constant. This drives the real, exported `apiClient` - both
// interceptors, as actually registered - through a fake adapter (axios's own extension point
// for swapping the transport, so no new dependency is needed to stand in for the network):
// one response carries a refreshed token, and the very next request must carry it as its
// bearer. Either interceptor being unwired, or reading the wrong storage key, fails this.
describe('apiClient session rolling, end to end', () => {
  const realAdapter = apiClient.defaults.adapter

  beforeEach(() => localStorage.clear())
  afterEach(() => {
    apiClient.defaults.adapter = realAdapter
  })

  it('stores a refreshed token from a real response, then sends it as the very next bearer', async () => {
    localStorage.setItem('ap_token', 'old-token')
    const seenAuthHeaders: unknown[] = []
    let callCount = 0

    apiClient.defaults.adapter = (config: AxiosRequestConfig) => {
      seenAuthHeaders.push((config.headers as Record<string, unknown> | undefined)?.Authorization)
      callCount += 1
      const headers = callCount === 1 ? { 'x-refreshed-token': 'brand-new-token' } : {}
      return Promise.resolve({
        data: {}, status: 200, statusText: 'OK', headers, config,
      } as AxiosResponse)
    }

    await apiClient.get('/first-call')
    expect(localStorage.getItem('ap_token')).toBe('brand-new-token')

    await apiClient.get('/second-call')
    expect(seenAuthHeaders).toEqual(['Bearer old-token', 'Bearer brand-new-token'])
  })

  it('sends no Authorization header when no token is stored', async () => {
    const seenAuthHeaders: unknown[] = []
    apiClient.defaults.adapter = (config: AxiosRequestConfig) => {
      seenAuthHeaders.push((config.headers as Record<string, unknown> | undefined)?.Authorization)
      return Promise.resolve({ data: {}, status: 200, statusText: 'OK', headers: {}, config } as AxiosResponse)
    }
    await apiClient.get('/unauthenticated-call')
    expect(seenAuthHeaders).toEqual([undefined])
  })
})

// Round 3 review: the 401 interceptor redirected to /login without recording where the
// person was. A cold click on a PAM link survives because ProtectedRoute is a route match
// and writes returnTo itself; a session expiring mid-read never reaches any React guard,
// because this handler clears the token and sets window.location, which unloads the app.
// That is the design's headline scenario - "a reviewer clicking a link to one script three
// weeks later" - failing in the one case where they had already started reading.
//
// Driven through the real registered interceptor, for the same reason the block above is:
// asserting against a hand-called function cannot see whether it is wired in.
describe('a 401 mid-session', () => {
  const realAdapter = apiClient.defaults.adapter
  const realLocation = window.location

  function standInLocation(href: string) {
    const url = new URL(href)
    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: { href: url.href, pathname: url.pathname, search: url.search },
    })
  }

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  afterEach(() => {
    apiClient.defaults.adapter = realAdapter
    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: realLocation,
    })
  })

  function refuseWith401() {
    apiClient.defaults.adapter = () =>
      Promise.reject(
        Object.assign(new Error('Request failed with status code 401'), {
          isAxiosError: true,
          config: { url: '/projects/acme/script-ledger' },
          response: { status: 401, data: {}, headers: {} },
        }),
      )
  }

  it('remembers the page the visitor was on, with the basename stripped', async () => {
    localStorage.setItem('ap_token', 'expired-token')
    standInLocation('http://localhost/dashboard/acme/agents/interaction_designer?script=1.2')
    refuseWith401()

    await expect(apiClient.get('/projects/acme/script-ledger')).rejects.toThrow()

    // The value Login reads back and hands to navigate(), which re-adds the basename - so
    // storing the raw pathname here would send them to /dashboard/dashboard/... instead.
    expect(sessionStorage.getItem('returnTo')).toBe(
      '/acme/agents/interaction_designer?script=1.2',
    )
    expect(localStorage.getItem('ap_token')).toBeNull()
    expect(window.location.href).toBe('/dashboard/login')
  })

  it('does not record the login page itself as a destination', async () => {
    standInLocation('http://localhost/dashboard/login')
    refuseWith401()

    await expect(apiClient.get('/projects/acme/script-ledger')).rejects.toThrow()

    expect(sessionStorage.getItem('returnTo')).toBeNull()
  })

  it('leaves returnTo alone when the failing call is the login attempt itself', async () => {
    standInLocation('http://localhost/dashboard/login')
    apiClient.defaults.adapter = () =>
      Promise.reject(
        Object.assign(new Error('Request failed with status code 401'), {
          isAxiosError: true,
          config: { url: '/auth/login' },
          response: { status: 401, data: {}, headers: {} },
        }),
      )

    await expect(apiClient.post('/auth/login')).rejects.toThrow()

    expect(sessionStorage.getItem('returnTo')).toBeNull()
    expect(window.location.href).toBe('http://localhost/dashboard/login')
  })
})
