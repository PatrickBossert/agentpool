# Diagnosable Scheduler Heartbeat - Design

**Date:** 2026-07-28
**Status:** Approved for planning

## Problem

The header dot reports scheduler liveness. It has two appearances - brand teal for
alive, grey for anything else - and `SchedulerHeartbeatContext.tsx:43` reduces every
possible failure to the same grey with a bare `catch { setStatus('stale') }`.

That collapse was deliberate and its rationale is in the code:

> An unreachable API is indistinguishable from a stopped clock, and both mean the same
> thing to a viewer: stop breathing.

True for the viewer, false for the operator. The two situations demand different
actions, and the dot destroys the evidence needed to tell them apart.

This was found in use, not in review. The API had been running since before the
heartbeat endpoint existed, so `GET /system/heartbeat` returned 404, the poll rejected,
and the dot went grey. The fix was to restart the API - but nothing on screen said so.
Worse, the existing tooltip would have said "The scheduler has not ticked yet", which
asserts the endpoint answered and the scheduler is merely idle. It was not just
uninformative but wrong.

## Approach

Keep the reason the poll failed, classify it, and let the operator read it in one click.

The dot's appearance does not change: teal when ticking, grey otherwise. What changes is
that the dot becomes a control, and behind it sits a plain-text panel naming the
diagnosis and the action it implies.

**Note on scope.** A 401 cannot produce a grey dot: `ui/src/api/client.ts:20` intercepts
401, clears the stored token, and redirects to the login page. Expired sessions are
already handled and are not among the cases below.

---

## Diagnosis model

A new pure module, `ui/src/context/heartbeatDiagnosis.ts`.

```ts
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
  /** What to do about it. Empty string when there is nothing to do. */
  action: string
  /** HTTP status where the server answered, otherwise null. */
  httpStatus: number | null
}
```

Two entry points, both total - neither may throw, whatever it is handed:

- `diagnoseResponse(beat: SchedulerHeartbeat): Diagnosis`
- `diagnoseError(error: unknown): Diagnosis`

### The cases

| Code | Condition | Title | Action |
|---|---|---|---|
| `ticking` | 200, `alive: true` | The scheduler is running normally. | *(none)* |
| `stopped` | 200, `alive: false`, `last_tick_at` present | The scheduler has stopped ticking. | Check the API logs - the scheduler task has died while the API is still serving. |
| `never-ticked` | 200, `alive: false`, `last_tick_at` null | The scheduler has never ticked. | The scheduler task did not start. Check the API logs for an error during startup. |
| `endpoint-missing` | 404 | The API does not have a heartbeat endpoint. | Restart the API - it is running a build from before this feature. |
| `unreachable` | request made, no response | The API cannot be reached. | Check the API is running on the expected port. |
| `server-error` | 5xx | The API returned an error. | Check the API logs. |
| `forbidden` | 403 | This account is not permitted to read the heartbeat. | Sign out and back in. |
| `starting` | no poll has completed yet | Checking the scheduler… | *(none)* |
| `unexpected` | anything else | The heartbeat check failed. | *(the error's message, so an unrecognised failure still says something)* |

`starting` exists so a slow first load raises no alarm - it is the initial value, not a
result. `unexpected` is the total-function fallback: an unrecognised error shape yields a
diagnosis carrying the raw message rather than being mislabelled as one of the others.

Classification uses `axios.isAxiosError` to reach `error.response?.status`. An axios error
with no `response` is `unreachable`; a non-axios throw is `unexpected`.

---

## Context changes

`ui/src/context/SchedulerHeartbeatContext.tsx`.

`status` keeps its exact current type and semantics - `'unknown' | 'alive' | 'stale'`.
The rotation gating and every test written against it are untouched. Diagnosis rides
alongside rather than replacing it.

The context value gains two members:

```ts
export interface HeartbeatValue {
  status: HeartbeatStatus
  lastTickAt: string | null
  rotation: number
  diagnosis: Diagnosis      // new
  secondsSince: number | null   // new - from the endpoint, for the panel's detail line
  refresh: () => void       // new
}
```

- The poll sets `diagnosis` from `diagnoseResponse` on success and `diagnoseError` in the
  `catch`. The existing decision - `status` is `alive` when `beat.alive`, `stale`
  otherwise, and `stale` on any failure - is unchanged.
- `refresh()` runs the poll immediately, for use after restarting the API rather than
  waiting up to 60 seconds. It does not reset the interval; a refresh landing shortly
  before a scheduled poll simply produces two polls, which is harmless.
- `lastTickAt` continues to hold the last known-good value across a failed poll, as it
  does today.
- The default context value (for consumers outside the provider) gains
  `diagnosis: { code: 'starting', … }`, `secondsSince: null`, and a `refresh` that does
  nothing, preserving the existing rule that a consumer outside the provider degrades
  quietly rather than throwing.

---

## The dot

`HeartbeatDot` moves out of `ui/src/components/AppLayout.tsx` into its own
`ui/src/components/HeartbeatDot.tsx`. It is no longer a fifteen-line span, and the move
also clears a finding deferred from the previous review. `AppLayout` imports it and
renders it where it renders it today.

**Appearance is unchanged**: `w-1.5 h-1.5 rounded-full`, `bg-brand opacity-60` when
`status === 'alive'`, `bg-gray-300` otherwise. `unknown` continues to render identically
to `stale`, so a slow first load raises no alarm.

**It becomes a button.** A 6px button is an unreasonably small target, so the visual dot
becomes a `<span>` *inside* a `<button>` that carries padding - the hit area is roughly
20px while the mark itself stays 6px and as quiet as it was. `data-testid="heartbeat-dot"`
therefore stays on the span carrying the colour classes, so the existing colour assertions
hold unchanged, and the button takes `data-testid="heartbeat-dot-button"`.

The button keeps a `title` attribute so hovering still works without opening anything.
`role="img"` goes, since a button has its own role. It carries `aria-expanded`, and
`aria-label` and `title` both set to the diagnosis title, so the accessible name and the
hover tooltip say what the colour means.

Both strings therefore change wording: today the dot says "The scheduler has not ticked
yet" in all three non-alive cases. The existing assertion in
`ui/src/__tests__/HeartbeatDot.test.tsx` that pins that exact sentence must be updated to
the diagnosis title for the state it sets up. Its assertions on `data-testid` and on the
colour classes stand unchanged.

**The panel** is anchored beneath the dot. The dot and panel are wrapped in a
`relative`-positioned container so the panel can be absolutely positioned against the dot
rather than the header. It contains:

- the diagnosis title
- a detail line: the last tick time and seconds since where known, and the HTTP status
  where the server answered
- the action, when there is one
- a **Check again** button calling `refresh()`, showing "Checking…" while a poll is in
  flight

It closes on Escape, on a click outside it, and on a second click of the dot. It is
plain text with no destructive control.

**Accepted trade-off.** This adds a visible interactive control to the header during
client demos. The panel's worst-case content - "The API is running a build from before
this feature" - is dull rather than alarming, which is judged an acceptable price for
one-click diagnosis.

---

## Testing

**The classifier** is pure, so every case is a unit test with no rendering: each of the
nine codes from a representative input, plus a non-axios throw reaching `unexpected`
rather than escaping, plus an axios error with no `response` reaching `unreachable`
rather than `unexpected`.

**The context**: `diagnosis` is `starting` before the first poll resolves; a 404 poll
yields `endpoint-missing` while `status` becomes `stale`; `refresh()` triggers a poll
without waiting for the interval; a successful poll after a failed one clears the
diagnosis back to `ticking`.

**The dot**: the panel is closed initially; clicking opens it and shows the diagnosis
title and action; Escape closes it; a click outside closes it; `aria-expanded` tracks the
open state; the dot's colour classes still follow `status` alone.

## Out of scope

Persisting diagnoses, alerting, notifying anyone, or any history of past failures. This
tells you the current state and what to do about it, nothing more.
