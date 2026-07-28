# Scheduler Heartbeat and Idle Activity Rotation - Design

**Date:** 2026-07-28
**Status:** Approved for planning

## Problem

The daily clock (SP19a) runs as an asyncio task inside the API process. Nothing on
screen says whether it is cycling. If the task dies - cancelled, or wedged - the API
keeps serving, the dashboard keeps rendering, and the first evidence of failure is a
status report that never arrives.

Separately, idle agents show a fixed wellbeing activity ("On a brisk walk", "In a
float tank") that never changes, so the board looks the same whether the platform is
running or stopped.

## Approach

Make the two problems solve each other. The scheduler publishes a heartbeat; the idle
activities rotate only while that heartbeat is fresh. A living board means a living
clock. A frozen board, plus one quiet marker, means the clock has stopped.

The alternative considered and rejected was a purely client-side timer. It would
rotate happily while the backend was dead, which is worse than no indicator: it reads
as reassurance while telling you only that the browser tab is alive.

**Scope boundary.** This proves the scheduler *loop is cycling*. It deliberately does
not report whether individual jobs succeed - a job failing every night leaves the loop
healthy and the agents breathing normally. Job-outcome reporting is a separate concern
and is out of scope here.

---

## Backend

### Heartbeat storage

A single-row table in `system.db`, created in `init_system_db` alongside
`scheduled_jobs`:

```sql
CREATE TABLE IF NOT EXISTS scheduler_heartbeat (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    last_tick_at TEXT NOT NULL
);
```

The `CHECK (id = 1)` makes "there is exactly one heartbeat" a property of the schema
rather than of the code that writes it.

Two async helpers in `api/database.py`, beside the existing `scheduled_jobs` helpers:

- `record_scheduler_heartbeat(conn, *, now_iso: str) -> None` - upsert on `id=1`
  (`INSERT ... ON CONFLICT(id) DO UPDATE SET last_tick_at=excluded.last_tick_at`), so
  repeated calls update rather than accumulate.
- `fetch_scheduler_heartbeat(conn) -> str | None` - returns `last_tick_at`, or `None`
  when the scheduler has never ticked.

### Scheduler changes

In `api/services/scheduler_service.py`:

- `TICK_SECONDS` changes from `900` to `60`. The scan is one `SELECT` over a table
  holding a handful of rows, so a per-minute pass costs nothing, and it takes report
  latency at 17:00 from up to fifteen minutes down to under one.
- `scheduler_loop` records the heartbeat on every pass, placed **after** the
  `try/except` that wraps `run_due_jobs` and outside it, so a pass in which a job
  raised still stamps. The heartbeat's meaning is "the loop is alive and cycling",
  not "the last job succeeded".
- Heartbeat failure must not break the loop. It is wrapped in its own guard that logs
  and continues, consistent with the loop's existing rule that the scheduler can never
  take the application down.

### Endpoint

New router `api/routers/system.py`, registered in `api/main.py`:

```
GET /system/heartbeat        Depends(require_any_auth)
```

Response:

```json
{ "last_tick_at": "2026-07-28T17:04:00", "seconds_since": 12, "alive": true }
```

When the scheduler has never ticked: `{"last_tick_at": null, "seconds_since": null,
"alive": false}`.

**`alive` is computed on the server** as `seconds_since <= 150` - two and a half ticks,
tolerating one missed pass. Deciding this server-side keeps the judgement on a single
clock: a client machine with a skewed system time cannot report a healthy Mac mini as
dead, or the reverse.

---

## Frontend

### Liveness context

`SchedulerHeartbeatProvider` (new, `ui/src/context/SchedulerHeartbeatContext.tsx`),
mounted inside the authenticated layout, holds all timing for this feature:

- Polls `GET /system/heartbeat` every 60 seconds through a `fetchHeartbeat` helper
  added to `ui/src/api/endpoints.ts`, beside the existing PAM report call at line 218.
  (`CLAUDE.md` describes one file per resource, but the sibling call this most
  resembles lives in `endpoints.ts`; following the code keeps related calls together.)
  One provider means one request per minute regardless of how many agents are
  rendered.
- Exposes `status: 'unknown' | 'alive' | 'stale'`. A rejected or non-2xx fetch is
  `stale`. The initial value is `unknown` - rendered as neither breathing nor flagged,
  so a slow first load cannot flash a false alarm.
- Exposes `rotation: number`, incremented every 30 seconds **only while `status ===
  'alive'`**. When the heartbeat stops, the counter stops with it.

### Rotation

`getIdleStatus(key, runIndex)` in `ui/src/components/agentStatus.ts` is unchanged. It
already derives an activity by hashing `key + runIndex`, so rotation is simply seed
advancement:

```ts
getIdleStatus(key, runIndex + rotation)
```

Because each agent hashes a different key, one shared counter yields a different new
activity per agent. Where the advanced seed returns the activity already displayed, the
consumer advances once more - a repeat would read as a missed breath.

### Breathing

`FadingText` (new, `ui/src/components/FadingText.tsx`) takes the text to display and
a `delayKey` string:

- On a change of value it transitions opacity to 0 over 600ms, swaps the text, then
  transitions back to 1 over 600ms - a fade out followed by a fade in, not an
  overlapping crossfade.
- `transition-delay` is derived from hashing `delayKey` into the range 0-1200ms, so the
  board changes as a soft ripple rather than in unison.
- Under `prefers-reduced-motion: reduce` the text swaps instantly with no transition.

Applied at the three existing idle-text call sites, which keep their current styling:

| File | Line | Context |
|------|------|---------|
| `ui/src/components/CrewCarousel.tsx` | 93 | PAM's idle status |
| `ui/src/components/CrewCarousel.tsx` | 227 | Each crew's idle status |
| `ui/src/components/AgentChatDrawer.tsx` | 298 | Chat drawer header |

### The quiet cue

A small dot in the application header (`ui/src/components/AppLayout.tsx:60`):

- `alive` - filled, brand teal (`bg-brand`), at reduced opacity so it reads as ambient
  rather than as a status light demanding attention.
- `stale` - filled grey (`bg-gray-300`).
- `unknown` - grey, matching `stale`; the distinction exists to suppress the alarm, not
  to display a third appearance.

Its `title` gives the last tick time, or "The scheduler has not ticked yet" when there
is none. This is deliberately quiet: legible to someone who knows the convention,
meaningless to a client in the room. Together with the frozen board it gives two
signals, neither of them loud.

---

## Testing

**Backend (pytest, in-memory SQLite):**

- `record_scheduler_heartbeat` twice leaves exactly one row, with the later timestamp.
- `fetch_scheduler_heartbeat` returns `None` before any tick.
- The endpoint reports `alive: true` at 150 seconds and `alive: false` at 151, with
  `now` injected rather than slept for.
- The endpoint reports `alive: false` and null fields when no heartbeat exists.
- `scheduler_loop` stamps the heartbeat on a pass in which `run_due_jobs` raises.

**Frontend (vitest and `@testing-library`, both already configured):**

- `rotation` advances on the 30-second boundary while alive, and does not advance while
  stale or unknown.
- A failed heartbeat fetch moves status to `stale`.
- `FadingText` displays the new value after the fade completes, and swaps immediately
  under `prefers-reduced-motion`.
- The header dot renders the alive appearance only for `alive`.

## Known limitations

- Detection latency is up to 150 seconds by construction.
- A backgrounded browser tab has its timers throttled, so the dot can lag briefly after
  the tab regains focus. Neither is worth engineering around at this scale.
