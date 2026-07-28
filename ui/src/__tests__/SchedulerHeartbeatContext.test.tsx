import { render, screen, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import {
  SchedulerHeartbeatProvider,
  useSchedulerHeartbeat,
  ROTATION_MS,
} from '../context/SchedulerHeartbeatContext'
import { systemApi } from '../api/endpoints'

vi.mock('../api/endpoints', () => ({
  systemApi: { heartbeat: vi.fn() },
}))

function Probe() {
  const { status, rotation } = useSchedulerHeartbeat()
  return <span data-testid="probe">{`${status}:${rotation}`}</span>
}

function renderProbe() {
  return render(
    <SchedulerHeartbeatProvider>
      <Probe />
    </SchedulerHeartbeatProvider>,
  )
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.mocked(systemApi.heartbeat).mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('SchedulerHeartbeatContext', () => {
  it('starts unknown so a slow first load cannot flash a false alarm', () => {
    vi.mocked(systemApi.heartbeat).mockReturnValue(new Promise(() => {}))
    renderProbe()
    expect(screen.getByTestId('probe')).toHaveTextContent('unknown:0')
  })

  it('reports alive once the heartbeat is fresh', async () => {
    vi.mocked(systemApi.heartbeat).mockResolvedValue({
      last_tick_at: '2026-07-28T17:00:00', seconds_since: 3, alive: true,
    })
    renderProbe()
    await act(async () => { await Promise.resolve() })
    expect(screen.getByTestId('probe')).toHaveTextContent('alive:0')
  })

  it('treats a failed fetch as stale', async () => {
    vi.mocked(systemApi.heartbeat).mockRejectedValue(new Error('network'))
    renderProbe()
    await act(async () => { await Promise.resolve() })
    expect(screen.getByTestId('probe')).toHaveTextContent('stale:0')
  })

  it('advances rotation on the 30-second boundary while alive', async () => {
    vi.mocked(systemApi.heartbeat).mockResolvedValue({
      last_tick_at: '2026-07-28T17:00:00', seconds_since: 3, alive: true,
    })
    renderProbe()
    await act(async () => { await Promise.resolve() })
    await act(async () => { vi.advanceTimersByTime(ROTATION_MS) })
    expect(screen.getByTestId('probe')).toHaveTextContent('alive:1')
  })

  it('does not advance rotation while stale - a frozen board is the signal', async () => {
    vi.mocked(systemApi.heartbeat).mockResolvedValue({
      last_tick_at: '2026-07-28T09:00:00', seconds_since: 9000, alive: false,
    })
    renderProbe()
    await act(async () => { await Promise.resolve() })
    await act(async () => { vi.advanceTimersByTime(ROTATION_MS * 4) })
    expect(screen.getByTestId('probe')).toHaveTextContent('stale:0')
  })
})
