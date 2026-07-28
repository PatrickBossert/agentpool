// ui/src/context/SchedulerHeartbeatContext.tsx
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

import { systemApi } from '../api/endpoints'
import { STARTING, diagnoseError, diagnoseResponse, type Diagnosis } from './heartbeatDiagnosis'

export type HeartbeatStatus = 'unknown' | 'alive' | 'stale'

export const POLL_MS = 60_000      // matches the scheduler's tick
export const ROTATION_MS = 30_000  // how often an idle agent changes activity

export interface HeartbeatValue {
  status: HeartbeatStatus
  lastTickAt: string | null
  rotation: number
  diagnosis: Diagnosis
  secondsSince: number | null
  refresh: () => Promise<void>
}

// Consumers rendered outside the provider degrade to a still board rather than
// throwing - the rotation is decoration, never a reason to fail a render.
const SchedulerHeartbeatContext = createContext<HeartbeatValue>({
  status: 'unknown',
  lastTickAt: null,
  rotation: 0,
  diagnosis: STARTING,
  secondsSince: null,
  refresh: async () => {},
})

export function useSchedulerHeartbeat(): HeartbeatValue {
  return useContext(SchedulerHeartbeatContext)
}

export function SchedulerHeartbeatProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<HeartbeatStatus>('unknown')
  const [lastTickAt, setLastTickAt] = useState<string | null>(null)
  const [secondsSince, setSecondsSince] = useState<number | null>(null)
  const [diagnosis, setDiagnosis] = useState<Diagnosis>(STARTING)
  const [rotation, setRotation] = useState(0)

  // A ref rather than a local, so refresh() and the interval share one flag.
  const cancelledRef = useRef(false)

  const poll = useCallback(async () => {
    try {
      const beat = await systemApi.heartbeat()
      if (cancelledRef.current) return
      setStatus(beat.alive ? 'alive' : 'stale')
      setLastTickAt(beat.last_tick_at)
      setSecondsSince(beat.seconds_since)
      setDiagnosis(diagnoseResponse(beat))
    } catch (error) {
      if (cancelledRef.current) return
      setStatus('stale')
      setDiagnosis(diagnoseError(error))
      // lastTickAt keeps its last known-good value so the panel can still say when
      // the scheduler was last seen. secondsSince is cleared: its age was measured
      // against a server that is no longer answering, so it would be a lie.
      setSecondsSince(null)
    }
  }, [])

  useEffect(() => {
    cancelledRef.current = false
    void poll()
    const id = setInterval(() => void poll(), POLL_MS)
    return () => {
      cancelledRef.current = true
      clearInterval(id)
    }
  }, [poll])

  useEffect(() => {
    if (status !== 'alive') return
    const id = setInterval(() => setRotation((r) => r + 1), ROTATION_MS)
    return () => clearInterval(id)
  }, [status])

  return (
    <SchedulerHeartbeatContext.Provider
      value={{ status, lastTickAt, rotation, diagnosis, secondsSince, refresh: poll }}
    >
      {children}
    </SchedulerHeartbeatContext.Provider>
  )
}
