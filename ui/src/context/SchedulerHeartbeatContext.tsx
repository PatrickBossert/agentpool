// ui/src/context/SchedulerHeartbeatContext.tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

import { systemApi } from '../api/endpoints'

export type HeartbeatStatus = 'unknown' | 'alive' | 'stale'

export const POLL_MS = 60_000      // matches the scheduler's tick
export const ROTATION_MS = 30_000  // how often an idle agent changes activity

export interface HeartbeatValue {
  status: HeartbeatStatus
  lastTickAt: string | null
  rotation: number
}

// Consumers rendered outside the provider degrade to a still board rather than
// throwing - the rotation is decoration, never a reason to fail a render.
const SchedulerHeartbeatContext = createContext<HeartbeatValue>({
  status: 'unknown',
  lastTickAt: null,
  rotation: 0,
})

export function useSchedulerHeartbeat(): HeartbeatValue {
  return useContext(SchedulerHeartbeatContext)
}

export function SchedulerHeartbeatProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<HeartbeatStatus>('unknown')
  const [lastTickAt, setLastTickAt] = useState<string | null>(null)
  const [rotation, setRotation] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const beat = await systemApi.heartbeat()
        if (cancelled) return
        setStatus(beat.alive ? 'alive' : 'stale')
        setLastTickAt(beat.last_tick_at)
      } catch {
        // An unreachable API is indistinguishable from a stopped clock, and both
        // mean the same thing to a viewer: stop breathing.
        if (cancelled) return
        setStatus('stale')
      }
    }

    void poll()
    const id = setInterval(() => void poll(), POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  useEffect(() => {
    if (status !== 'alive') return
    const id = setInterval(() => setRotation((r) => r + 1), ROTATION_MS)
    return () => clearInterval(id)
  }, [status])

  return (
    <SchedulerHeartbeatContext.Provider value={{ status, lastTickAt, rotation }}>
      {children}
    </SchedulerHeartbeatContext.Provider>
  )
}
