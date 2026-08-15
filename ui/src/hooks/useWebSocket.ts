// ui/src/hooks/useWebSocket.ts
import { useEffect, useRef, useState } from 'react'

// The same key api/client.ts writes and reads. Repeated as a literal rather than imported
// because client.ts's own interceptor does the same; there is one string to change, not two
// conventions.
const TOKEN_KEY = 'ap_token'

export function useWebSocket(slug: string | undefined, maxLines = 100) {
  const [logs, setLogs] = useState<string[]>([])
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!slug) return

    const token = localStorage.getItem(TOKEN_KEY)
    // No session, no stream. The server refuses an unauthenticated handshake outright, so
    // opening one would buy a failed connection per mount and nothing else.
    if (!token) return

    // Derived from the page origin, not named. This used to be the literal
    // ws://localhost:8000, which is wrong behind Caddy and cloudflared in production and, on
    // an https page, blocked before it leaves the browser as mixed content - an https origin
    // refuses a ws:// socket, so the log panel just stayed empty. Both proxies forward /ws to
    // the API (see vite.config.ts and the Caddyfile).
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // ['bearer', token] travels as Sec-WebSocket-Protocol - a header, and that is the point.
    // A browser cannot set Authorization on a handshake, and a query string would write a
    // thirty-day credential into proxy logs, browser history, and referrers.
    const ws = new WebSocket(`${scheme}//${window.location.host}/ws/${slug}`, ['bearer', token])
    wsRef.current = ws

    ws.onmessage = (e) => {
      if (e.data === 'ping') return  // keepalive - ignore
      setLogs((prev) => [...prev.slice(-(maxLines - 1)), e.data])
    }

    return () => {
      ws.close()
    }
  }, [slug, maxLines])

  return logs
}
