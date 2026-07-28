// ui/src/context/heartbeatDiagnosis.ts
import axios from 'axios'

import type { SchedulerHeartbeat } from '../api/endpoints'

/**
 * Why the heartbeat is in the state it is in.
 *
 * The dot has two appearances but many more causes, and they call for different
 * actions - restarting the API is no help if the API is down, and checking the
 * logs is no help if the running build simply predates the endpoint. Collapsing
 * them into one grey was the original defect.
 */
export type DiagnosisCode =
  | 'starting'
  | 'ticking'
  | 'stopped'
  | 'never-ticked'
  | 'endpoint-missing'
  | 'unreachable'
  | 'server-error'
  | 'forbidden'
  | 'unexpected'

export interface Diagnosis {
  code: DiagnosisCode
  /** One sentence naming what is wrong, or that nothing is. */
  title: string
  /** What to do about it. Empty when there is nothing to do. */
  action: string
  /** The status where the server answered, otherwise null. */
  httpStatus: number | null
}

/** The value before any poll has completed - a starting point, not a result. */
export const STARTING: Diagnosis = {
  code: 'starting',
  title: 'Checking the scheduler…',
  action: '',
  httpStatus: null,
}

export function diagnoseResponse(beat: SchedulerHeartbeat): Diagnosis {
  if (beat.alive) {
    return {
      code: 'ticking',
      title: 'The scheduler is running normally.',
      action: '',
      httpStatus: 200,
    }
  }
  if (beat.last_tick_at === null) {
    return {
      code: 'never-ticked',
      title: 'The scheduler has never ticked.',
      action: 'The scheduler task did not start. Check the API logs for an error during startup.',
      httpStatus: 200,
    }
  }
  return {
    code: 'stopped',
    title: 'The scheduler has stopped ticking.',
    action: 'Check the API logs - the scheduler task has died while the API is still serving.',
    httpStatus: 200,
  }
}

export function diagnoseError(error: unknown): Diagnosis {
  try {
    let status: number | null = null

    if (axios.isAxiosError(error)) {
      status = error.response?.status ?? null

      if (status === null) {
        return {
          code: 'unreachable',
          title: 'The API cannot be reached.',
          action: 'Check the API is running on the expected port.',
          httpStatus: null,
        }
      }
      if (status === 404) {
        return {
          code: 'endpoint-missing',
          title: 'The API does not have a heartbeat endpoint.',
          action: 'Restart the API - it is running a build from before this feature.',
          httpStatus: status,
        }
      }
      if (status === 403) {
        return {
          code: 'forbidden',
          title: 'This account is not permitted to read the heartbeat.',
          action: 'Sign out and back in.',
          httpStatus: status,
        }
      }
      if (status >= 500) {
        return {
          code: 'server-error',
          title: 'The API returned an error.',
          action: 'Check the API logs.',
          httpStatus: status,
        }
      }
    }

    // Total fallback. An unrecognised failure carries its own message rather than
    // being labelled as one of the cases above and sending someone the wrong way.
    return {
      code: 'unexpected',
      title: 'The heartbeat check failed.',
      action: error instanceof Error ? error.message : String(error),
      httpStatus: status,
    }
  } catch {
    // Pathological case: an error object with a throwing getter (e.g., on isAxiosError
    // or response). Must never throw, whatever is handed to us.
    return {
      code: 'unexpected',
      title: 'The heartbeat check failed.',
      action: 'An unexpected error occurred while checking the heartbeat.',
      httpStatus: null,
    }
  }
}
