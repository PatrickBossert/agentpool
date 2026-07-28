import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import HeartbeatDot from '../components/HeartbeatDot'
import { STARTING, type Diagnosis } from '../context/heartbeatDiagnosis'
import {
  useSchedulerHeartbeat,
  type HeartbeatValue,
} from '../context/SchedulerHeartbeatContext'

vi.mock('../context/SchedulerHeartbeatContext', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../context/SchedulerHeartbeatContext')>()),
  useSchedulerHeartbeat: vi.fn(),
}))

const mockedHeartbeat = vi.mocked(useSchedulerHeartbeat)

const ENDPOINT_MISSING: Diagnosis = {
  code: 'endpoint-missing',
  title: 'The API does not have a heartbeat endpoint.',
  action: 'Restart the API - it is running a build from before this feature.',
  httpStatus: 404,
}

function heartbeat(overrides: Partial<HeartbeatValue> = {}): HeartbeatValue {
  return {
    status: 'alive',
    lastTickAt: '2026-07-28T17:00:00',
    rotation: 0,
    diagnosis: STARTING,
    secondsSince: 3,
    refresh: vi.fn(async () => {}),
    ...overrides,
  }
}

beforeEach(() => mockedHeartbeat.mockReset())

describe('HeartbeatDot appearance', () => {
  it('uses the brand colour only when the scheduler is alive', () => {
    mockedHeartbeat.mockReturnValue(heartbeat({ status: 'alive' }))
    render(<HeartbeatDot />)
    expect(screen.getByTestId('heartbeat-dot').className).toContain('bg-brand')
  })

  it('goes grey when the scheduler is stale', () => {
    mockedHeartbeat.mockReturnValue(heartbeat({ status: 'stale' }))
    render(<HeartbeatDot />)
    const dot = screen.getByTestId('heartbeat-dot')
    expect(dot.className).toContain('bg-gray-300')
    expect(dot.className).not.toContain('bg-brand')
  })

  it('renders unknown the same as stale so a slow load raises no alarm', () => {
    mockedHeartbeat.mockReturnValue(heartbeat({ status: 'unknown' }))
    render(<HeartbeatDot />)
    expect(screen.getByTestId('heartbeat-dot').className).toContain('bg-gray-300')
  })
})

describe('HeartbeatDot panel', () => {
  it('is closed until the dot is clicked', () => {
    mockedHeartbeat.mockReturnValue(heartbeat())
    render(<HeartbeatDot />)
    expect(screen.queryByTestId('heartbeat-panel')).not.toBeInTheDocument()
    expect(screen.getByTestId('heartbeat-dot-button')).toHaveAttribute('aria-expanded', 'false')
  })

  it('names the diagnosis and what to do about it', async () => {
    mockedHeartbeat.mockReturnValue(
      heartbeat({ status: 'stale', diagnosis: ENDPOINT_MISSING }),
    )
    render(<HeartbeatDot />)
    await userEvent.click(screen.getByTestId('heartbeat-dot-button'))

    expect(screen.getByText(ENDPOINT_MISSING.title)).toBeInTheDocument()
    expect(screen.getByText(ENDPOINT_MISSING.action)).toBeInTheDocument()
    expect(screen.getByTestId('heartbeat-dot-button')).toHaveAttribute('aria-expanded', 'true')
  })

  it('shows the HTTP status when the server answered', async () => {
    mockedHeartbeat.mockReturnValue(
      heartbeat({ status: 'stale', diagnosis: ENDPOINT_MISSING, secondsSince: null }),
    )
    render(<HeartbeatDot />)
    await userEvent.click(screen.getByTestId('heartbeat-dot-button'))
    expect(screen.getByTestId('heartbeat-panel').textContent).toContain('404')
  })

  it('closes on Escape', async () => {
    mockedHeartbeat.mockReturnValue(heartbeat())
    render(<HeartbeatDot />)
    await userEvent.click(screen.getByTestId('heartbeat-dot-button'))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByTestId('heartbeat-panel')).not.toBeInTheDocument()
  })

  it('closes on a click outside it', async () => {
    mockedHeartbeat.mockReturnValue(heartbeat())
    render(
      <div>
        <HeartbeatDot />
        <button>somewhere else</button>
      </div>,
    )
    await userEvent.click(screen.getByTestId('heartbeat-dot-button'))
    await userEvent.click(screen.getByRole('button', { name: 'somewhere else' }))
    expect(screen.queryByTestId('heartbeat-panel')).not.toBeInTheDocument()
  })

  it('re-checks on demand rather than waiting for the next poll', async () => {
    const refresh = vi.fn(async () => {})
    mockedHeartbeat.mockReturnValue(heartbeat({ status: 'stale', refresh }))
    render(<HeartbeatDot />)
    await userEvent.click(screen.getByTestId('heartbeat-dot-button'))
    await userEvent.click(screen.getByRole('button', { name: /check again/i }))
    expect(refresh).toHaveBeenCalledTimes(1)
  })
})
