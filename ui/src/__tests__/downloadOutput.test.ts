// ui/src/__tests__/downloadOutput.test.ts
//
// downloadOutput is the only consumer of API_BASE that does not go through apiClient - it calls
// fetch directly, so client.test.ts's adapter cannot see it. Same property, asserted on the URL
// this function actually fetches: an output download has to go to whatever origin served the
// page, not to a host baked into the bundle at build time.
import { downloadOutput } from '../utils/download'

describe('downloadOutput', () => {
  const realFetch = globalThis.fetch
  const realCreateObjectURL = URL.createObjectURL
  const realRevokeObjectURL = URL.revokeObjectURL
  const realAnchorClick = HTMLAnchorElement.prototype.click

  beforeEach(() => {
    URL.createObjectURL = () => 'blob:stand-in'
    URL.revokeObjectURL = () => {}
    // jsdom implements an anchor click as a navigation it then refuses to perform, which
    // prints a stack trace per test. The click is not the property under test.
    HTMLAnchorElement.prototype.click = () => {}
  })

  afterEach(() => {
    globalThis.fetch = realFetch
    URL.createObjectURL = realCreateObjectURL
    URL.revokeObjectURL = realRevokeObjectURL
    HTMLAnchorElement.prototype.click = realAnchorClick
  })

  it('fetches the download from the page origin, not from a hardcoded host', async () => {
    const sent: string[] = []
    globalThis.fetch = ((input: Request | string) => {
      sent.push(typeof input === 'string' ? input : input.url)
      return Promise.resolve(new Response('file bytes', { status: 200 }))
    }) as typeof globalThis.fetch

    await downloadOutput('acme', 42, 'value-chain.xlsx', 'a.session.token')

    expect(sent).toHaveLength(1)
    const resolved = new URL(sent[0], window.location.href)
    expect(resolved.origin).toBe(window.location.origin)
    expect(resolved.pathname).toBe('/projects/acme/outputs/42/download')
  })

  it('sends the caller-supplied bearer token', async () => {
    const seenHeaders: unknown[] = []
    globalThis.fetch = ((_input: Request | string, init?: RequestInit) => {
      seenHeaders.push(init?.headers)
      return Promise.resolve(new Response('file bytes', { status: 200 }))
    }) as typeof globalThis.fetch

    await downloadOutput('acme', 42, 'value-chain.xlsx', 'a.session.token')

    expect(seenHeaders).toEqual([{ Authorization: 'Bearer a.session.token' }])
  })
})
