import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { HeartbeatDot } from '../components/AppLayout'
import { useSchedulerHeartbeat } from '../context/SchedulerHeartbeatContext'
import { STARTING } from '../context/heartbeatDiagnosis'

vi.mock('../context/SchedulerHeartbeatContext', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../context/SchedulerHeartbeatContext')>()),
  useSchedulerHeartbeat: vi.fn(),
}))

const mockedHeartbeat = vi.mocked(useSchedulerHeartbeat)

beforeEach(() => mockedHeartbeat.mockReset())

describe('HeartbeatDot', () => {
  it('uses the brand colour only when the scheduler is alive', () => {
    mockedHeartbeat.mockReturnValue({
      status: 'alive', lastTickAt: '2026-07-28T17:00:00', rotation: 0,
      diagnosis: STARTING, secondsSince: null, refresh: async () => {},
    })
    render(<HeartbeatDot />)
    expect(screen.getByTestId('heartbeat-dot').className).toContain('bg-brand')
  })

  it('goes grey when the scheduler is stale', () => {
    mockedHeartbeat.mockReturnValue({
      status: 'stale', lastTickAt: '2026-07-28T09:00:00', rotation: 0,
      diagnosis: STARTING, secondsSince: null, refresh: async () => {},
    })
    render(<HeartbeatDot />)
    const dot = screen.getByTestId('heartbeat-dot')
    expect(dot.className).toContain('bg-gray-300')
    expect(dot.className).not.toContain('bg-brand')
  })

  it('renders unknown the same as stale so a slow load raises no alarm', () => {
    mockedHeartbeat.mockReturnValue({
      status: 'unknown', lastTickAt: null, rotation: 0,
      diagnosis: STARTING, secondsSince: null, refresh: async () => {},
    })
    render(<HeartbeatDot />)
    expect(screen.getByTestId('heartbeat-dot').className).toContain('bg-gray-300')
  })

  it('names the last tick in its tooltip', () => {
    mockedHeartbeat.mockReturnValue({
      status: 'unknown', lastTickAt: null, rotation: 0,
      diagnosis: STARTING, secondsSince: null, refresh: async () => {},
    })
    render(<HeartbeatDot />)
    expect(screen.getByTestId('heartbeat-dot').getAttribute('title'))
      .toBe('The scheduler has not ticked yet')
  })
})
