// ui/src/__tests__/passwordResetApi.test.ts
//
// What the browser actually puts on the wire for the three reset calls.
//
// Driven through the real exported apiClient with a stand-in adapter (axios's own extension
// point for swapping the transport - the pattern client.test.ts established), so these read
// the URL, method, and body as they are actually sent. A test that rendered a page and found
// a button would prove nothing about any of that: the recurring failure on this project is an
// assertion that lands one layer away from the property, and for an API client the property
// is the request.
import type { AxiosRequestConfig, AxiosResponse } from 'axios'
import { apiClient } from '../api/client'
import { authApi } from '../api/endpoints'
import { adminApi } from '../api/admin'

type Seen = { url?: string; method?: string; body: unknown }

const realAdapter = apiClient.defaults.adapter
let seen: Seen[] = []

function respondWith(data: unknown, status = 200) {
  apiClient.defaults.adapter = (config: AxiosRequestConfig) => {
    seen.push({
      url: config.url,
      method: config.method,
      body: typeof config.data === 'string' ? JSON.parse(config.data) : config.data,
    })
    return Promise.resolve({
      data, status, statusText: 'OK', headers: {}, config,
    } as AxiosResponse)
  }
}

beforeEach(() => {
  seen = []
  localStorage.clear()
})

afterEach(() => {
  apiClient.defaults.adapter = realAdapter
})

describe('authApi.requestReset', () => {
  it('posts the address to the self-service door', async () => {
    respondWith('', 204)
    await authApi.requestReset('rae@example.com')

    expect(seen).toEqual([
      { url: '/auth/reset-request', method: 'post', body: { email: 'rae@example.com' } },
    ])
  })

  it('resolves to nothing at all for the 204 the server always answers with', async () => {
    // The contract, not an oversight. The server answers 204 with an empty body whether or
    // not the address has an account, so there is no outcome to hand back - and a caller
    // given one would eventually branch on it, which is the account-existence oracle the
    // 204 exists to prevent. A client that returned `r.data` here would hand every caller
    // an empty string that is trivially mistaken for a result.
    respondWith('', 204)
    await expect(authApi.requestReset('rae@example.com')).resolves.toBeUndefined()
  })
})

describe('authApi.resetPassword', () => {
  it('posts the token and the chosen password to the redemption door', async () => {
    respondWith({ access_token: 'a.b.c', token_type: 'bearer' })
    await authApi.resetPassword('tok-abc', 'chosen-by-the-owner')

    expect(seen).toEqual([
      {
        url: '/auth/reset',
        method: 'post',
        body: { token: 'tok-abc', password: 'chosen-by-the-owner' },
      },
    ])
  })

  it('returns the session the server minted, so the caller can sign the person in', async () => {
    respondWith({ access_token: 'a.b.c', token_type: 'bearer' })
    await expect(authApi.resetPassword('tok-abc', 'pw')).resolves.toEqual({
      access_token: 'a.b.c',
      token_type: 'bearer',
    })
  })

  it('rejects rather than resolving when the token is refused', async () => {
    // A spent, expired, or invented token is a 400. Swallowing it would put somebody on the
    // dashboard route with no session rather than telling them to ask for a new link.
    apiClient.defaults.adapter = () =>
      Promise.reject(
        Object.assign(new Error('Request failed with status code 400'), {
          isAxiosError: true,
          config: { url: '/auth/reset' },
          response: { status: 400, data: { detail: 'Invalid or expired token' }, headers: {} },
        }),
      )
    await expect(authApi.resetPassword('spent', 'pw')).rejects.toThrow()
  })
})

describe('adminApi.issueResetLink', () => {
  it('posts to the named account and returns the link the administrator must deliver', async () => {
    respondWith({
      reset_token: 'raw-token-value',
      username: 'rae@example.com',
      email: 'rae@example.com',
    })
    const result = await adminApi.issueResetLink(7)

    expect(seen).toEqual([
      { url: '/auth/users/7/reset-link', method: 'post', body: undefined },
    ])
    expect(result.reset_token).toBe('raw-token-value')
  })
})
