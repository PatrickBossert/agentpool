import { AxiosError } from 'axios'
import { describe, it, expect } from 'vitest'

import {
  STARTING,
  diagnoseError,
  diagnoseResponse,
} from '../context/heartbeatDiagnosis'

/** A real AxiosError, so the tests exercise the same shape axios throws. */
function axiosErrorWithStatus(status: number): AxiosError {
  const error = new AxiosError('Request failed')
  error.response = { status } as AxiosError['response']
  return error
}

describe('diagnoseResponse', () => {
  it('reports a live scheduler as ticking, with nothing to do', () => {
    const d = diagnoseResponse({
      last_tick_at: '2026-07-28T17:00:00', seconds_since: 12, alive: true,
    })
    expect(d.code).toBe('ticking')
    expect(d.action).toBe('')
  })

  it('distinguishes a scheduler that stopped from one that never started', () => {
    const stopped = diagnoseResponse({
      last_tick_at: '2026-07-28T09:00:00', seconds_since: 9000, alive: false,
    })
    const never = diagnoseResponse({
      last_tick_at: null, seconds_since: null, alive: false,
    })
    expect(stopped.code).toBe('stopped')
    expect(never.code).toBe('never-ticked')
    // They imply different actions - that distinction is the point of the feature.
    expect(stopped.action).not.toBe(never.action)
  })
})

describe('diagnoseError', () => {
  it('reads a 404 as an API predating the endpoint, and says to restart it', () => {
    const d = diagnoseError(axiosErrorWithStatus(404))
    expect(d.code).toBe('endpoint-missing')
    expect(d.httpStatus).toBe(404)
    expect(d.action).toMatch(/restart the api/i)
  })

  it('reads an error with no response as unreachable', () => {
    const d = diagnoseError(new AxiosError('Network Error'))
    expect(d.code).toBe('unreachable')
    expect(d.httpStatus).toBeNull()
  })

  it('reads a 403 as a permissions problem', () => {
    expect(diagnoseError(axiosErrorWithStatus(403)).code).toBe('forbidden')
  })

  it('reads any 5xx as a server error', () => {
    expect(diagnoseError(axiosErrorWithStatus(500)).code).toBe('server-error')
    expect(diagnoseError(axiosErrorWithStatus(503)).code).toBe('server-error')
  })

  it('falls back to unexpected rather than mislabelling an unrecognised status', () => {
    const d = diagnoseError(axiosErrorWithStatus(418))
    expect(d.code).toBe('unexpected')
    expect(d.httpStatus).toBe(418)
  })

  it('survives a non-axios throw and carries its message', () => {
    const d = diagnoseError(new Error('boom'))
    expect(d.code).toBe('unexpected')
    expect(d.action).toContain('boom')
    expect(d.httpStatus).toBeNull()
  })

  it('survives a thrown non-Error without throwing itself', () => {
    expect(() => diagnoseError('just a string')).not.toThrow()
    expect(diagnoseError('just a string').code).toBe('unexpected')
  })
})

describe('STARTING', () => {
  it('has no action, so a slow first load suggests nothing is wrong', () => {
    expect(STARTING.code).toBe('starting')
    expect(STARTING.action).toBe('')
  })
})
