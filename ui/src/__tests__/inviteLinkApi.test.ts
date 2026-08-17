// ui/src/__tests__/inviteLinkApi.test.ts
//
// What the browser actually puts on the wire when an administrator asks for an invite link.
//
// Driven through the real exported apiClient with a stand-in adapter - axios's own extension
// point for swapping the transport, the pattern client.test.ts established and
// passwordResetApi.test.ts follows - so this reads the URL, method and body as they are
// really sent. A test that rendered the page and found a button would say nothing about any
// of it: the recurring failure on this project is an assertion landing one layer from the
// property, and for an API client the property is the request.
//
// The path is worth asserting character by character. `/{slug}/stakeholders/{id}/import` is
// registered before `/{stakeholder_id}` on the server precisely because these paths collide
// in ways nothing type-checks, and a resend posted to the wrong one would 404, 405, or -
// worst - reach a different handler.
import type { AxiosRequestConfig, AxiosResponse } from 'axios'
import { apiClient } from '../api/client'
import { stakeholdersApi } from '../api/endpoints'

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

describe('stakeholdersApi.resendInvite', () => {
  it('posts to the resend door for that project and that stakeholder, with no body', async () => {
    respondWith({ invite_token: 'tok-abc' })

    await stakeholdersApi.resendInvite('acme', 42)

    expect(seen).toEqual([
      {
        url: '/projects/acme/stakeholders/42/resend-invite',
        method: 'post',
        // The door takes nothing: it reads the stakeholder from the path and the caller
        // from the token. A body here would be a second, unread source of truth about
        // whose invite is being reissued.
        body: undefined,
      },
    ])
  })

  it('returns the raw token, which is the only copy that will ever exist', async () => {
    // The server stores a digest, so a token dropped on the floor here cannot be recovered -
    // asking again mints a different one and kills this link. A client that discarded the
    // body would leave the page with nothing to render.
    respondWith({ invite_token: 'tok-abc' })

    await expect(stakeholdersApi.resendInvite('acme', 42)).resolves.toEqual({
      invite_token: 'tok-abc',
    })
  })

  it('rejects rather than resolving when the door refuses', async () => {
    // 403 for a project_admin, 404 with nothing live to resend, 409 once the person has a
    // login. All three have to reach the caller: swallowing them would leave an
    // administrator looking at a page that says nothing happened and nothing failed.
    apiClient.defaults.adapter = () =>
      Promise.reject(Object.assign(new Error('Request failed'), {
        isAxiosError: true,
        response: { status: 403, data: { detail: 'Org admin or above required' } },
      }))

    await expect(stakeholdersApi.resendInvite('acme', 42)).rejects.toBeTruthy()
  })
})
