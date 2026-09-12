// ui/src/__tests__/ItemReviewClient.test.ts
//
// **What is sent, not what renders.** The panel tests one file over assert which client
// function was called and with what; this asserts what that function actually hands the
// transport - the method, the path, and the body. The two together are the round trip, and
// either alone is the failure mode CLAUDE.md records twelve times on this project: a test
// that passes without testing what it is named for.
//
// A wrong path here is invisible everywhere else. `reviewNode` posting to the lever door
// would satisfy every mock-based assertion in the suite, record the review against a ledger
// that has no such id, and answer 422 only at runtime. The adapter stands in for the network
// and is handed the fully merged config the real interceptors produced, so `getUri` composes
// baseURL and url exactly as axios's own adapters do.
import type { AxiosRequestConfig, AxiosResponse } from 'axios'
import { apiClient } from '../api/client'
import { projectsApi } from '../api/endpoints'

interface Sent {
  method: string
  url: string
  body: unknown
}

const realAdapter = apiClient.defaults.adapter

afterEach(() => {
  apiClient.defaults.adapter = realAdapter
})

function capture(): Sent[] {
  const sent: Sent[] = []
  apiClient.defaults.adapter = (config: AxiosRequestConfig) => {
    sent.push({
      method: (config.method ?? '').toLowerCase(),
      url: apiClient.getUri(config),
      body: typeof config.data === 'string' ? JSON.parse(config.data) : config.data,
    })
    return Promise.resolve({
      data: [], status: 200, statusText: 'OK', headers: {}, config,
    } as AxiosResponse)
  }
  return sent
}

it('reads the node ledger from the node door', async () => {
  const sent = capture()
  await projectsApi.getNodeLedger('acme')
  expect(sent).toHaveLength(1)
  expect(sent[0].method).toBe('get')
  expect(new URL(sent[0].url, window.location.href).pathname)
    .toBe('/projects/acme/node-ledger')
})

it('reads the lever ledger from the lever door', async () => {
  const sent = capture()
  await projectsApi.getLeverLedger('acme')
  expect(sent).toHaveLength(1)
  expect(sent[0].method).toBe('get')
  expect(new URL(sent[0].url, window.location.href).pathname)
    .toBe('/projects/acme/lever-ledger')
})

it('sends a node review to the node door, carrying the decision, target and note', async () => {
  const sent = capture()
  await projectsApi.reviewNode('acme', '3.3.3', {
    decision: 'changes_requested', return_to: 'agent', notes: 'Wrong altitude.',
  })
  expect(sent).toHaveLength(1)
  expect(sent[0].method).toBe('post')
  expect(new URL(sent[0].url, window.location.href).pathname)
    .toBe('/projects/acme/node-ledger/3.3.3/review')
  expect(sent[0].body).toEqual({
    decision: 'changes_requested', return_to: 'agent', notes: 'Wrong altitude.',
  })
})

it('sends a lever review to the lever door, carrying the decision, target and note', async () => {
  const sent = capture()
  await projectsApi.reviewLever('acme', 'LV-001', {
    decision: 'changes_requested', return_to: 'reviewer', notes: 'Ask Priya first.',
  })
  expect(sent).toHaveLength(1)
  expect(sent[0].method).toBe('post')
  expect(new URL(sent[0].url, window.location.href).pathname)
    .toBe('/projects/acme/lever-ledger/LV-001/review')
  expect(sent[0].body).toEqual({
    decision: 'changes_requested', return_to: 'reviewer', notes: 'Ask Priya first.',
  })
})

it('never sends a node review to the lever door, or the reverse', async () => {
  // The property the four tests above imply and none of them states. A single
  // `reviewItem(kind, ...)` collapsed onto one path would pass each of them that happened to
  // be written and fail this one.
  const sent = capture()
  await projectsApi.reviewNode('acme', 'X-1', { decision: 'reviewed' })
  await projectsApi.reviewLever('acme', 'X-1', { decision: 'reviewed' })
  const paths = sent.map((s) => new URL(s.url, window.location.href).pathname)
  expect(paths).toEqual([
    '/projects/acme/node-ledger/X-1/review',
    '/projects/acme/lever-ledger/X-1/review',
  ])
})

it('sends every one of these to the origin that served the page', async () => {
  // API_BASE is '' on purpose, so a call goes to whatever origin served the page - Vite in
  // development, Caddy in production. A new client function is where a hardcoded host gets
  // reintroduced, and sp43 records what that costs: every call to the viewer's own machine,
  // both proxies bypassed, and nothing in a unit suite able to see it.
  const sent = capture()
  await projectsApi.getNodeLedger('acme')
  await projectsApi.getLeverLedger('acme')
  await projectsApi.reviewNode('acme', '3.3.3', { decision: 'reviewed' })
  await projectsApi.reviewLever('acme', 'LV-001', { decision: 'reviewed' })
  expect(sent).toHaveLength(4)
  for (const s of sent) {
    expect(new URL(s.url, window.location.href).origin).toBe(window.location.origin)
  }
})
