// ui/src/__tests__/useWebSocket.test.tsx
//
// The browser half of the log stream. tests/test_websocket_log_stream.py proves the server
// refuses a handshake that carries no credential in Sec-WebSocket-Protocol; this proves the
// hook actually puts one there. Both halves have to be proven together - a server that
// demands a header and a client that never sends it is a log panel that is permanently empty,
// and each half on its own passes.
//
// Asserted against what the hook hands to `new WebSocket`, not against a helper that computes
// a URL. The URL and the protocol list only matter as arguments to that constructor, and a
// pure function tested beside the hook would keep passing while the hook called it with the
// wrong things - or stopped calling it at all.
import { act, renderHook } from '@testing-library/react'
import { useWebSocket } from '../hooks/useWebSocket'

class FakeWebSocket {
  static opened: FakeWebSocket[] = []
  url: string
  protocols: string | string[] | undefined
  onmessage: ((e: { data: string }) => void) | null = null
  close = vi.fn()

  constructor(url: string, protocols?: string | string[]) {
    this.url = url
    this.protocols = protocols
    FakeWebSocket.opened.push(this)
  }
}

function setOrigin(protocol: string, host: string) {
  // jsdom pins window.location, so it is replaced outright rather than assigned to. The
  // production-shaped case is an https page behind Caddy; the dev case is plain http.
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { protocol, host, pathname: '/dashboard/runs/1', search: '' },
  })
}

describe('useWebSocket', () => {
  const realLocation = window.location

  beforeEach(() => {
    FakeWebSocket.opened = []
    localStorage.clear()
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    Object.defineProperty(window, 'location', { configurable: true, value: realLocation })
  })

  it('sends the stored session token as a subprotocol, not in the URL', () => {
    // The whole reason a subprotocol was chosen over ?token=: sessions here roll for thirty
    // days, and a URL lands in proxy logs, browser history, and referrers. If the credential
    // ever moves back into the URL, the second assertion is what notices.
    setOrigin('http:', 'localhost:5173')
    localStorage.setItem('ap_token', 'header.payload.signature')

    renderHook(() => useWebSocket('acme-transport'))

    expect(FakeWebSocket.opened).toHaveLength(1)
    expect(FakeWebSocket.opened[0].protocols).toEqual(['bearer', 'header.payload.signature'])
    expect(FakeWebSocket.opened[0].url).not.toContain('header.payload.signature')
  })

  it('derives the URL from the page origin in development', () => {
    setOrigin('http:', 'localhost:5173')
    localStorage.setItem('ap_token', 'a.b.c')

    renderHook(() => useWebSocket('acme-transport'))

    expect(FakeWebSocket.opened[0].url).toBe('ws://localhost:5173/ws/acme-transport')
  })

  it('uses wss on an https page, so the socket is not blocked as mixed content', () => {
    // The production case, behind Caddy and cloudflared. A ws:// socket opened from an https
    // origin is refused by the browser before it leaves the page, which is what the hardcoded
    // ws://localhost:8000 did on every deployed run view.
    setOrigin('https:', 'agentpool.example.com')
    localStorage.setItem('ap_token', 'a.b.c')

    renderHook(() => useWebSocket('acme-transport'))

    expect(FakeWebSocket.opened[0].url).toBe('wss://agentpool.example.com/ws/acme-transport')
  })

  it('opens nothing when there is no session to authenticate with', () => {
    setOrigin('https:', 'agentpool.example.com')

    renderHook(() => useWebSocket('acme-transport'))

    expect(FakeWebSocket.opened).toEqual([])
  })

  it('opens nothing without a slug', () => {
    setOrigin('https:', 'agentpool.example.com')
    localStorage.setItem('ap_token', 'a.b.c')

    renderHook(() => useWebSocket(undefined))

    expect(FakeWebSocket.opened).toEqual([])
  })

  it('collects the lines it is sent and drops the keepalive', () => {
    // The control. Without it every assertion above would be satisfied by a hook that opened
    // a correctly-authenticated socket and then ignored everything that arrived on it.
    setOrigin('http:', 'localhost:5173')
    localStorage.setItem('ap_token', 'a.b.c')

    const { result } = renderHook(() => useWebSocket('acme-transport'))
    const socket = FakeWebSocket.opened[0]
    act(() => {
      socket.onmessage?.({ data: 'alex: started' })
      socket.onmessage?.({ data: 'ping' })
    })

    expect(result.current).toEqual(['alex: started'])
  })
})
