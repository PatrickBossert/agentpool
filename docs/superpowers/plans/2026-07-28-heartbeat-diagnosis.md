# Diagnosable Scheduler Heartbeat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The header dot stops collapsing every failure into the same grey - it keeps the reason, and one click says which of eight situations you are in and what to do about it.

**Architecture:** A pure classifier turns a heartbeat response or an axios error into a `Diagnosis` - a code, a sentence, and an action. The context stores it alongside the existing `status`, which is left untouched so the rotation gating and its tests carry over unchanged. The dot moves into its own file and becomes a button opening a plain-text panel.

**Tech Stack:** React 18, TypeScript, Tailwind CSS v3, axios 1.7, vitest, @testing-library/react and @testing-library/user-event.

## Global Constraints

- **British English** - `-ise` (organise, recognise), `-our` (behaviour, colour), `-re` (centre).
- **Spaced hyphen ` - `** in all prose, comments, and user-facing copy. Never an em dash (`—`). This applies to prose, not to hyphenated compound adjectives ("per-minute" keeps its tight hyphen).
- **No emoji** in rendered web content. Lucide React icons only.
- **Oxford comma** in lists of three or more.
- Tailwind **brand tokens only** - `bg-brand`, `text-brand`, `brand-dark`. Never `sky-*` or `blue-*`.
- `status` keeps its exact current type and semantics - `'unknown' | 'alive' | 'stale'`. Diagnosis rides alongside it. Do not fold one into the other.
- The dot's appearance does not change: `bg-brand opacity-60` when alive, `bg-gray-300` otherwise, and `unknown` renders identically to `stale`.
- Frontend tests: `cd ui && npx vitest run <path>`. Whole suite: `cd ui && npx vitest run`. Typecheck: `cd ui && npx tsc --noEmit`.
- **Baseline: 40 frontend tests passing, 12 files, no failures.** Any failure you see is yours.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `ui/src/context/heartbeatDiagnosis.ts` (create) | Pure classification - response or error in, `Diagnosis` out. Knows nothing about React |
| `ui/src/context/SchedulerHeartbeatContext.tsx` (modify) | Stores the diagnosis, exposes `refresh()` |
| `ui/src/components/HeartbeatDot.tsx` (create) | The dot, the panel, and their open/close behaviour |
| `ui/src/components/AppLayout.tsx` (modify) | Loses the inline `HeartbeatDot`, imports it instead |
| `ui/src/__tests__/heartbeatDiagnosis.test.ts` (create) | Every diagnosis case, no rendering |
| `ui/src/__tests__/SchedulerHeartbeatContext.test.tsx` (modify) | Diagnosis plumbing and `refresh()` |
| `ui/src/__tests__/HeartbeatDot.test.tsx` (rewrite) | Colour, panel open/close, the action, Check again |

---

## Task 1: The diagnosis classifier

**Files:**
- Create: `ui/src/context/heartbeatDiagnosis.ts`
- Test: `ui/src/__tests__/heartbeatDiagnosis.test.ts`

**Interfaces:**
- Consumes: `SchedulerHeartbeat` from `ui/src/api/endpoints.ts` - `{ last_tick_at: string | null; seconds_since: number | null; alive: boolean }`
- Produces:
  - `type DiagnosisCode = 'starting' | 'ticking' | 'stopped' | 'never-ticked' | 'endpoint-missing' | 'unreachable' | 'server-error' | 'forbidden' | 'unexpected'`
  - `interface Diagnosis { code: DiagnosisCode; title: string; action: string; httpStatus: number | null }`
  - `const STARTING: Diagnosis`
  - `function diagnoseResponse(beat: SchedulerHeartbeat): Diagnosis`
  - `function diagnoseError(error: unknown): Diagnosis`

- [ ] **Step 1: Write the failing tests**

Create `ui/src/__tests__/heartbeatDiagnosis.test.ts`:

```ts
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/heartbeatDiagnosis.test.ts`
Expected: FAIL - cannot resolve `../context/heartbeatDiagnosis`

- [ ] **Step 3: Implement**

Create `ui/src/context/heartbeatDiagnosis.ts`:

```ts
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
  const status = axios.isAxiosError(error) ? (error.response?.status ?? null) : null

  if (axios.isAxiosError(error)) {
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
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && npx vitest run src/__tests__/heartbeatDiagnosis.test.ts`
Expected: 10 passed

- [ ] **Step 5: Typecheck**

Run: `cd ui && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add ui/src/context/heartbeatDiagnosis.ts ui/src/__tests__/heartbeatDiagnosis.test.ts
git commit -m "feat: classify why the scheduler heartbeat is in the state it is in"
```

---

## Task 2: The context keeps the diagnosis and can be asked to re-check

**Files:**
- Modify: `ui/src/context/SchedulerHeartbeatContext.tsx`
- Modify: `ui/src/__tests__/SchedulerHeartbeatContext.test.tsx` (append tests, and update the existing `Probe` if needed)
- Modify: `ui/src/__tests__/HeartbeatDot.test.tsx` (its four mock return values must gain the new fields or the typecheck fails - see Step 5)

**Interfaces:**
- Consumes: `STARTING`, `Diagnosis`, `diagnoseResponse`, `diagnoseError` from `../context/heartbeatDiagnosis`
- Produces: `HeartbeatValue` gains three members, consumed by Task 3:
  ```ts
  diagnosis: Diagnosis
  secondsSince: number | null
  refresh: () => Promise<void>
  ```
  `status`, `lastTickAt`, `rotation`, `POLL_MS`, and `ROTATION_MS` are unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `ui/src/__tests__/SchedulerHeartbeatContext.test.tsx`. Note the existing file already mocks `../api/endpoints` and has a `renderProbe` helper - reuse them; do not add a second mock.

```tsx
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
```

Add `import { AxiosError } from 'axios'` and `POLL_MS` to the file's existing imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/SchedulerHeartbeatContext.test.tsx`
Expected: FAIL - `diagnosis` is undefined, so reading `.code` throws

- [ ] **Step 3: Implement the context changes**

In `ui/src/context/SchedulerHeartbeatContext.tsx`:

Add to the imports:

```tsx
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

import { STARTING, diagnoseError, diagnoseResponse, type Diagnosis } from './heartbeatDiagnosis'
```

Extend the interface and the default value:

```tsx
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
```

Replace the provider's state and polling effect:

```tsx
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
```

`cancelledRef.current` is reset to `false` at the top of the effect, not only set to `true` in its cleanup: React 18's StrictMode mounts, unmounts, and remounts in development, and without the reset the second mount would start with the flag already raised and silently discard every poll.

- [ ] **Step 4: Run the context tests to verify they pass**

Run: `cd ui && npx vitest run src/__tests__/SchedulerHeartbeatContext.test.tsx`
Expected: 10 passed (6 existing plus 4 new)

- [ ] **Step 5: Repair the HeartbeatDot test's mocks**

`HeartbeatValue` has gained three required members, so the four `mockReturnValue` calls in `ui/src/__tests__/HeartbeatDot.test.tsx` no longer satisfy the type and `tsc` will fail. Task 3 rewrites this file completely, but the tree must typecheck at the end of every task, so add the missing fields now.

Add to the file's imports:

```tsx
import { STARTING } from '../context/heartbeatDiagnosis'
```

and add these three properties to each of the four objects passed to `mockReturnValue`:

```tsx
      diagnosis: STARTING, secondsSince: null, refresh: async () => {},
```

Change nothing else in that file - in particular leave its assertions alone.

- [ ] **Step 6: Run the whole frontend suite and typecheck**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: 54 passed (40 baseline, plus 10 from Task 1, plus 4 here), no type errors

- [ ] **Step 7: Commit**

```bash
git add ui/src/context/SchedulerHeartbeatContext.tsx ui/src/__tests__/SchedulerHeartbeatContext.test.tsx ui/src/__tests__/HeartbeatDot.test.tsx
git commit -m "feat: keep the reason a heartbeat poll failed, and allow an immediate re-check"
```

---

## Task 3: The dot becomes a button with a diagnosis panel

**Files:**
- Create: `ui/src/components/HeartbeatDot.tsx`
- Modify: `ui/src/components/AppLayout.tsx` - remove the inline `HeartbeatDot` (lines 14-41, the JSDoc block and the exported function) and its now-unused `useSchedulerHeartbeat` import; import the component instead. The render site at line 138 is unchanged.
- Rewrite: `ui/src/__tests__/HeartbeatDot.test.tsx`

**Interfaces:**
- Consumes: `useSchedulerHeartbeat()` returning `{ status, lastTickAt, rotation, diagnosis, secondsSince, refresh }`; `Diagnosis` from `../context/heartbeatDiagnosis`
- Produces: default export `HeartbeatDot`. Nothing later depends on it.

**Structure note:** the visual dot is a `<span>` **inside** the `<button>`, not the button itself. A 6px button is an unreasonably small target; the button carries padding so the hit area is roughly 20px while the dot stays 6px. `data-testid="heartbeat-dot"` therefore stays on the span that carries the colour classes, and the button gets `data-testid="heartbeat-dot-button"`.

- [ ] **Step 1: Write the failing tests**

Replace the whole contents of `ui/src/__tests__/HeartbeatDot.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/HeartbeatDot.test.tsx`
Expected: FAIL - cannot resolve `../components/HeartbeatDot`

- [ ] **Step 3: Create the component**

Create `ui/src/components/HeartbeatDot.tsx`:

```tsx
// ui/src/components/HeartbeatDot.tsx
import { useEffect, useRef, useState } from 'react'

import { useSchedulerHeartbeat } from '../context/SchedulerHeartbeatContext'

/**
 * Ambient scheduler liveness, and the diagnosis behind it.
 *
 * The dot itself stays deliberately quiet - two colours, no wording, meaningless
 * to anyone who does not know the convention. The panel exists because the colour
 * alone cannot say whether the clock stopped or the API never answered, and those
 * want different actions from whoever is looking.
 */
export default function HeartbeatDot() {
  const { status, lastTickAt, secondsSince, diagnosis, refresh } = useSchedulerHeartbeat()
  const [open, setOpen] = useState(false)
  const [checking, setChecking] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    function onPointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }

    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('mousedown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('mousedown', onPointerDown)
    }
  }, [open])

  async function checkAgain() {
    setChecking(true)
    try {
      await refresh()
    } finally {
      setChecking(false)
    }
  }

  const detail = [
    lastTickAt ? `Last tick ${lastTickAt}` : 'No tick recorded',
    secondsSince === null ? null : `${secondsSince}s ago`,
    diagnosis.httpStatus === null ? null : `HTTP ${diagnosis.httpStatus}`,
  ]
    .filter(Boolean)
    .join(' - ')

  return (
    <div ref={containerRef} className="relative flex items-center">
      <button
        type="button"
        data-testid="heartbeat-dot-button"
        title={diagnosis.title}
        aria-label={diagnosis.title}
        aria-expanded={open}
        onClick={() => setOpen((wasOpen) => !wasOpen)}
        // Padding rather than a bigger dot: the target is comfortable to hit while
        // the mark itself stays as small and quiet as it was.
        className="p-2 -m-2 flex items-center"
      >
        <span
          data-testid="heartbeat-dot"
          className={`block w-1.5 h-1.5 rounded-full ${
            status === 'alive' ? 'bg-brand opacity-60' : 'bg-gray-300'
          }`}
        />
      </button>

      {open && (
        <div
          data-testid="heartbeat-panel"
          role="dialog"
          aria-label="Scheduler status"
          className="absolute top-6 left-0 z-50 w-72 rounded-lg border border-gray-200 bg-white p-3 shadow-lg"
        >
          <p className="text-xs font-semibold text-gray-900">{diagnosis.title}</p>
          <p className="text-[11px] text-gray-500 mt-1">{detail}</p>
          {diagnosis.action !== '' && (
            <p className="text-[11px] text-gray-700 mt-2">{diagnosis.action}</p>
          )}
          <button
            type="button"
            onClick={() => void checkAgain()}
            disabled={checking}
            className="mt-3 text-[11px] font-semibold text-brand hover:text-brand-dark disabled:opacity-50"
          >
            {checking ? 'Checking…' : 'Check again'}
          </button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && npx vitest run src/__tests__/HeartbeatDot.test.tsx`
Expected: 9 passed

- [ ] **Step 5: Wire it into AppLayout**

In `ui/src/components/AppLayout.tsx`:

Delete the JSDoc comment block and the whole exported `HeartbeatDot` function (lines 14-41 - it begins with `/**` above `export function HeartbeatDot()` and ends with that function's closing brace).

Change the context import so it no longer pulls in `useSchedulerHeartbeat`, which nothing in this file uses any more:

```tsx
import { SchedulerHeartbeatProvider } from '../context/SchedulerHeartbeatContext'
```

Add the component import beside the other component imports:

```tsx
import HeartbeatDot from './HeartbeatDot'
```

The render site (`<HeartbeatDot />`, currently line 138, immediately before the `{user?.sub}` span) does not change.

- [ ] **Step 6: Run the whole frontend suite and typecheck**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: 59 passed - 54 after Task 2, plus the 9 tests in the rewritten dot file, less the 4 it replaced. No type errors.

If `tsc` reports `HeartbeatDot` is still exported from `AppLayout` and imported nowhere, the deletion in Step 5 was incomplete.

- [ ] **Step 7: Commit**

```bash
git add ui/src/components/HeartbeatDot.tsx ui/src/components/AppLayout.tsx ui/src/__tests__/HeartbeatDot.test.tsx
git commit -m "feat: make the heartbeat dot say what is wrong and what to do"
```

---

## Manual verification

Automated tests cannot judge whether the panel is legible or well placed. After Task 3, with the UI running:

1. With the API stopped entirely, the dot is grey. Click it: the panel should say the API cannot be reached, and suggest checking it is running.
2. Start the API. Click **Check again** - the panel should resolve to "The scheduler is running normally." within a second or so, without waiting for the 60-second poll, and the dot should turn teal.
3. Confirm the panel sits below the dot, does not overflow the window, and does not push the header's other items around when it opens.
4. Press Escape, and separately click elsewhere in the header - both should close it.
5. Tab to the dot from the keyboard: it should take focus visibly, and Enter or Space should open the panel.
