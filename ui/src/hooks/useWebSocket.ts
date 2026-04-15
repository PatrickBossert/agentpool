// ui/src/hooks/useWebSocket.ts
import { useEffect, useRef, useState } from 'react'

export function useWebSocket(slug: string | undefined, maxLines = 100) {
  const [logs, setLogs] = useState<string[]>([])
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!slug) return
    const ws = new WebSocket(`ws://localhost:8000/ws/${slug}`)
    wsRef.current = ws

    ws.onmessage = (e) => {
      if (e.data === 'ping') return  // keepalive — ignore
      setLogs((prev) => [...prev.slice(-(maxLines - 1)), e.data])
    }

    return () => {
      ws.close()
    }
  }, [slug, maxLines])

  return logs
}
