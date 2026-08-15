// ui/src/__tests__/client.test.ts
//
// The read half of the rolling-session round trip. tests/test_rolling_session.py proves the
// server writes X-Refreshed-Token; nothing before this proved the browser actually reads it.
// A middleware bug that set the header to a truthy-but-useless value (see review: "x") would
// satisfy a bare truthiness check on the server side and then log everyone out on the very
// next request once client.ts stored "x" as the session token - the two halves have to be
// proven together, per CLAUDE.md's recurring failure mode.
import type { AxiosResponse } from 'axios'
import { storeRefreshedToken } from '../api/client'

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
