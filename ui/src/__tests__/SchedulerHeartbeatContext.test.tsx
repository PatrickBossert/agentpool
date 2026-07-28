import { render, screen, act } from '@testing-library/react'
import { AxiosError } from 'axios'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import {
  SchedulerHeartbeatProvider,
  useSchedulerHeartbeat,
  ROTATION_MS,
  POLL_MS,
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

  it('stops advancing rotation once a later poll reports the scheduler died - proves the interval is torn down, not just paused', async () => {
    const heartbeatMock = vi.mocked(systemApi.heartbeat)
    heartbeatMock
      .mockResolvedValueOnce({ last_tick_at: '2026-07-28T17:00:00', seconds_since: 3, alive: true })
      .mockResolvedValue({ last_tick_at: '2026-07-28T17:00:00', seconds_since: 9000, alive: false })

    renderProbe()
    await act(async () => { await Promise.resolve() })
    expect(screen.getByTestId('probe')).toHaveTextContent('alive:0')

    // One rotation tick while alive - the interval genuinely exists.
    await act(async () => { vi.advanceTimersByTime(ROTATION_MS) })
    expect(screen.getByTestId('probe')).toHaveTextContent('alive:1')

    // Advance to the next POLL_MS boundary, where the mocked heartbeat now
    // reports the scheduler has died, and flush the resulting microtasks so
    // the second poll's result lands.
    await act(async () => {
      vi.advanceTimersByTime(POLL_MS - ROTATION_MS)
      await Promise.resolve()
      await Promise.resolve()
    })
    const probe = screen.getByTestId('probe')
    expect(probe.textContent).toMatch(/^stale:/)
    const rotationAtTransition = probe.textContent

    // Further time must not move the rotation counter. If the cleanup that
    // clears the rotation interval were ever dropped, the leaked interval
    // would keep incrementing here regardless of status.
    await act(async () => { vi.advanceTimersByTime(ROTATION_MS * 4) })
    expect(screen.getByTestId('probe')).toHaveTextContent(rotationAtTransition!)
  })
})

function DiagnosisProbe() {
  const { diagnosis, refresh } = useSchedulerHeartbeat()
  return (
    <div>
      <span data-testid="code">{diagnosis.code}</span>
      <button onClick={() => void refresh()}>refresh</button>
    </div>
  )
}

function renderDiagnosisProbe() {
  return render(
    <SchedulerHeartbeatProvider>
      <DiagnosisProbe />
    </SchedulerHeartbeatProvider>,
  )
}

describe('SchedulerHeartbeatContext diagnosis', () => {
  it('starts as starting, so a slow first load names no fault', () => {
    vi.mocked(systemApi.heartbeat).mockReturnValue(new Promise(() => {}))
    renderDiagnosisProbe()
    expect(screen.getByTestId('code')).toHaveTextContent('starting')
  })

  it('keeps the reason a poll failed instead of discarding it', async () => {
    const error = new AxiosError('Request failed')
    error.response = { status: 404 } as AxiosError['response']
    vi.mocked(systemApi.heartbeat).mockRejectedValue(error)

    renderDiagnosisProbe()
    await act(async () => { await Promise.resolve() })

    expect(screen.getByTestId('code')).toHaveTextContent('endpoint-missing')
  })

  it('recovers to ticking once a poll succeeds again', async () => {
    const error = new AxiosError('Network Error')
    vi.mocked(systemApi.heartbeat)
      .mockRejectedValueOnce(error)
      .mockResolvedValue({
        last_tick_at: '2026-07-28T17:00:00', seconds_since: 3, alive: true,
      })

    renderDiagnosisProbe()
    await act(async () => { await Promise.resolve() })
    expect(screen.getByTestId('code')).toHaveTextContent('unreachable')

    await act(async () => { vi.advanceTimersByTime(POLL_MS) })
    await act(async () => { await Promise.resolve() })
    expect(screen.getByTestId('code')).toHaveTextContent('ticking')
  })

  it('refresh polls straight away rather than waiting for the interval', async () => {
    vi.mocked(systemApi.heartbeat).mockResolvedValue({
      last_tick_at: '2026-07-28T17:00:00', seconds_since: 3, alive: true,
    })
    renderDiagnosisProbe()
    await act(async () => { await Promise.resolve() })
    const afterFirstPoll = vi.mocked(systemApi.heartbeat).mock.calls.length

    await act(async () => {
      screen.getByRole('button', { name: 'refresh' }).click()
      await Promise.resolve()
    })

    expect(vi.mocked(systemApi.heartbeat).mock.calls.length).toBe(afterFirstPoll + 1)
  })
})
