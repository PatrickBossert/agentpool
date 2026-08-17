// ui/src/__tests__/adminUsersApi.test.ts
//
// What the browser actually puts on the wire when the user list is read through a project.
//
// Driven through the real exported apiClient with a stand-in adapter - axios's own extension
// point for swapping the transport, the pattern client.test.ts established and
// inviteLinkApi.test.ts follows - so this reads the URL and query string as they are really
// sent. UserListPerson.test.tsx mocks `adminApi` wholesale, so it can prove the page *calls*
// listUsers('alpha') and can say nothing at all about whether the slug reaches the request:
// deleting the params from the client leaves that test entirely green. This is the assertion
// that lands on the property rather than beside it.
import type { AxiosRequestConfig, AxiosResponse } from 'axios'
import { apiClient } from '../api/client'
import { adminApi } from '../api/admin'

type Seen = { url?: string; params?: unknown }

const realAdapter = apiClient.defaults.adapter
let seen: Seen[] = []

function respondWith(data: unknown) {
  apiClient.defaults.adapter = (config: AxiosRequestConfig) => {
    seen.push({ url: config.url, params: config.params })
    return Promise.resolve({
      data, status: 200, statusText: 'OK', headers: {}, config,
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

test('a project-scoped read sends the slug as ?project=', async () => {
  respondWith([])
  await adminApi.listUsers('alpha')
  expect(seen).toHaveLength(1)
  expect(seen[0].url).toBe('/auth/users')
  expect(seen[0].params).toEqual({ project: 'alpha' })
})

test('an unscoped read sends no project at all', async () => {
  // Not `?project=` empty, and not `?project=undefined`: the server treats "absent" as the
  // unscoped list and would take any string as a slug to authorise, so an empty one would be
  // a 403 on the default view.
  respondWith([])
  await adminApi.listUsers()
  expect(seen[0].params).toBeUndefined()
  await adminApi.listUsers('')
  expect(seen[1].params).toBeUndefined()
})
