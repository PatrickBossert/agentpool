# Scheduler Heartbeat and Idle Activity Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Idle agents rotate their wellbeing activity every 30 seconds with a breathing fade, but only while the scheduler's heartbeat is fresh - so a living board means a living clock.

**Architecture:** The scheduler stamps a single-row heartbeat table on every pass. An authenticated endpoint reports whether that stamp is recent, deciding staleness server-side so client clock skew cannot lie. One React context polls that endpoint and holds a rotation counter that advances only while the heartbeat is fresh; idle text is derived from the existing `getIdleStatus` hash with the counter added to its seed, so no state has to be stored or synchronised between the components that render it.

**Tech Stack:** FastAPI, aiosqlite, pytest / pytest-asyncio; React 18, TypeScript, Tailwind CSS v3, vitest, @testing-library/react.

## Global Constraints

- **British English** throughout - `-ise` (organise, prioritise), `-our` (behaviour, colour), `-re` (centre).
- **Spaced hyphen ` - `** in all prose, comments, and copy. Never an em dash (`—`).
- **No emoji** in rendered web content. Lucide React icons only.
- **Oxford comma** in lists of three or more.
- Backend: async `aiosqlite` throughout; all raw SQL lives in `api/database.py`; no ORM.
- Frontend: brand tokens only - `bg-brand`, `text-brand`. Never `sky-*` or `blue-*`.
- Tests use in-memory or `/tmp` SQLite via `tests/conftest.py`; no running services required.
- Backend tests run with `./venv/bin/pytest` - **not** bare `pytest`.
- Baseline before this plan: **537 backend tests passing**.
- The heartbeat means "the scheduler loop is cycling". It deliberately does **not** report whether individual jobs succeed - do not add job-outcome reporting to it.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `api/database.py` (modify) | `scheduler_heartbeat` table plus its two helpers, beside the existing `scheduled_jobs` helpers |
| `api/services/scheduler_service.py` (modify) | Stamp the heartbeat each pass; tick every 60s |
| `api/routers/system.py` (create) | `GET /system/heartbeat` - the liveness judgement |
| `api/main.py` (modify) | Register the new router |
| `tests/test_scheduler_heartbeat.py` (create) | Backend coverage for all of the above |
| `ui/src/api/endpoints.ts` (modify) | `systemApi.heartbeat()` client call |
| `ui/src/context/SchedulerHeartbeatContext.tsx` (create) | Polls liveness, owns the rotation counter - all timing for this feature lives here |
| `ui/src/components/FadingText.tsx` (create) | The breathing fade, isolated from anything that knows about agents |
| `ui/src/components/agentStatus.ts` (modify) | `getRotatedIdleStatus` - seed advancement with repeat avoidance |
| `ui/src/components/AppLayout.tsx` (modify) | Mount the provider; render the header dot |
| `ui/src/components/CrewCarousel.tsx` (modify) | Two idle call sites |
| `ui/src/components/AgentChatDrawer.tsx` (modify) | One idle call site |
| `ui/src/__tests__/SchedulerHeartbeatContext.test.tsx` (create) | Polling and rotation gating |
| `ui/src/__tests__/FadingText.test.tsx` (create) | Fade behaviour and reduced motion |
| `ui/src/__tests__/agentStatusRotation.test.ts` (create) | Seed advancement and repeat avoidance |

---

## Task 1: Heartbeat storage

**Files:**
- Modify: `api/database.py` - add the table to `init_system_db` (the `executescript` block ending at line 1527), add two helpers after `fetch_due_jobs` (line 2248)
- Test: `tests/test_scheduler_heartbeat.py`

**Interfaces:**
- Consumes: `get_system_connection()` - existing async context manager yielding an `aiosqlite.Connection` with `row_factory = aiosqlite.Row`
- Produces:
  - `async def record_scheduler_heartbeat(conn: aiosqlite.Connection, *, now_iso: str) -> None`
  - `async def fetch_scheduler_heartbeat(conn: aiosqlite.Connection) -> str | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scheduler_heartbeat.py`:

```python
# tests/test_scheduler_heartbeat.py
"""The scheduler's liveness stamp.

One row, always id=1: "there is exactly one heartbeat" is a property of the schema
rather than of the code that writes it.
"""
import pytest

from api.database import (
    fetch_scheduler_heartbeat,
    get_system_connection,
    record_scheduler_heartbeat,
)


@pytest.fixture(autouse=True)
async def clear_heartbeat():
    """Each test starts from no heartbeat, whatever ran before it."""
    async with get_system_connection() as conn:
        await conn.execute("DELETE FROM scheduler_heartbeat")
        await conn.commit()
    yield


@pytest.mark.asyncio
async def test_fetch_returns_none_before_any_tick():
    async with get_system_connection() as conn:
        assert await fetch_scheduler_heartbeat(conn) is None


@pytest.mark.asyncio
async def test_recording_then_fetching_round_trips():
    async with get_system_connection() as conn:
        await record_scheduler_heartbeat(conn, now_iso="2026-07-28T10:00:00")
        assert await fetch_scheduler_heartbeat(conn) == "2026-07-28T10:00:00"


@pytest.mark.asyncio
async def test_recording_twice_updates_rather_than_accumulating():
    """A per-minute stamp must not grow a row per minute."""
    async with get_system_connection() as conn:
        await record_scheduler_heartbeat(conn, now_iso="2026-07-28T10:00:00")
        await record_scheduler_heartbeat(conn, now_iso="2026-07-28T10:01:00")
        assert await fetch_scheduler_heartbeat(conn) == "2026-07-28T10:01:00"
        async with conn.execute("SELECT COUNT(*) AS n FROM scheduler_heartbeat") as cur:
            assert (await cur.fetchone())["n"] == 1
```

Note: the `clear_heartbeat` fixture is an async generator fixture. `pytest.ini` sets `asyncio_mode = strict`, so decorate it with `@pytest_asyncio.fixture` instead of `@pytest.fixture` and add `import pytest_asyncio` - copy the style used by the async fixtures in `tests/conftest.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_scheduler_heartbeat.py -v`
Expected: FAIL - `ImportError: cannot import name 'fetch_scheduler_heartbeat' from 'api.database'`

- [ ] **Step 3: Add the table**

In `api/database.py`, inside `init_system_db`'s `executescript` block, immediately after the `scheduled_jobs` table (which ends at line 1526 with `PRIMARY KEY (job_name, slug)` and `);`), add:

```sql
        CREATE TABLE IF NOT EXISTS scheduler_heartbeat (
            id           INTEGER PRIMARY KEY CHECK (id = 1),
            last_tick_at TEXT NOT NULL
        );
```

- [ ] **Step 4: Add the helpers**

In `api/database.py`, after `fetch_due_jobs` (ends line 2248), add:

```python
async def record_scheduler_heartbeat(conn: aiosqlite.Connection, *, now_iso: str) -> None:
    """Stamp the scheduler's liveness.

    The heartbeat means "the loop is cycling", not "the last job succeeded" - the
    caller stamps it even on a pass where a job raised.
    """
    await conn.execute(
        "INSERT INTO scheduler_heartbeat (id, last_tick_at) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET last_tick_at=excluded.last_tick_at",
        (now_iso,),
    )
    await conn.commit()


async def fetch_scheduler_heartbeat(conn: aiosqlite.Connection) -> str | None:
    """The last tick timestamp, or None when the scheduler has never ticked."""
    async with conn.execute(
        "SELECT last_tick_at FROM scheduler_heartbeat WHERE id = 1"
    ) as cur:
        row = await cur.fetchone()
    return row["last_tick_at"] if row else None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_scheduler_heartbeat.py -v`
Expected: 3 passed

- [ ] **Step 6: Run the file twice in succession**

Run: `./venv/bin/pytest tests/test_scheduler_heartbeat.py -q && ./venv/bin/pytest tests/test_scheduler_heartbeat.py -q`
Expected: both runs pass. These tests share the real `system.db` in `DATABASE_DIR`, so a run that only passes once is a bug in the fixture.

- [ ] **Step 7: Commit**

```bash
git add api/database.py tests/test_scheduler_heartbeat.py
git commit -m "feat: add the scheduler heartbeat table and its helpers"
```

---

## Task 2: The scheduler stamps its heartbeat

**Files:**
- Modify: `api/services/scheduler_service.py` - `TICK_SECONDS` (line 22), `scheduler_loop` (lines 79-93)
- Test: `tests/test_scheduler_heartbeat.py` (append)

**Interfaces:**
- Consumes: `record_scheduler_heartbeat(conn, *, now_iso)`, `get_system_connection()`
- Produces: no new symbols. `TICK_SECONDS` changes value from `900` to `60`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler_heartbeat.py`:

```python
import asyncio
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_tick_is_one_minute():
    """The heartbeat is only as good as its resolution."""
    from api.services import scheduler_service
    assert scheduler_service.TICK_SECONDS == 60


@pytest.mark.asyncio
async def test_loop_stamps_the_heartbeat_even_when_a_job_raises():
    """The heartbeat reports that the loop is cycling, not that jobs succeeded.

    A job failing every night must not make the board look dead - that is a
    different fault, and conflating them would hide both.
    """
    from api.services.scheduler_service import scheduler_loop

    stop = asyncio.Event()
    with patch(
        "api.services.scheduler_service.run_due_jobs",
        AsyncMock(side_effect=RuntimeError("boom")),
    ), patch("api.services.scheduler_service.TICK_SECONDS", 0.01):
        task = asyncio.create_task(scheduler_loop(stop))
        await asyncio.sleep(0.1)
        stop.set()
        await task

    async with get_system_connection() as conn:
        assert await fetch_scheduler_heartbeat(conn) is not None


@pytest.mark.asyncio
async def test_a_heartbeat_failure_does_not_stop_the_loop():
    """The scheduler must never be able to take the application down."""
    from api.services.scheduler_service import scheduler_loop

    stop = asyncio.Event()
    with patch(
        "api.services.scheduler_service.run_due_jobs", AsyncMock()
    ) as run, patch(
        "api.services.scheduler_service.record_scheduler_heartbeat",
        AsyncMock(side_effect=RuntimeError("disk full")),
    ), patch("api.services.scheduler_service.TICK_SECONDS", 0.01):
        task = asyncio.create_task(scheduler_loop(stop))
        await asyncio.sleep(0.1)
        stop.set()
        await task

    assert run.await_count >= 2, "the loop stopped cycling after a heartbeat failure"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_scheduler_heartbeat.py -v -k "tick_is_one_minute or stamps_the_heartbeat or heartbeat_failure"`
Expected: FAIL - `test_tick_is_one_minute` asserts `900 == 60`; the other two fail because nothing writes a heartbeat and `record_scheduler_heartbeat` is not imported into the module namespace, so the patch target does not exist.

- [ ] **Step 3: Implement**

In `api/services/scheduler_service.py`, add `record_scheduler_heartbeat` to the existing import from `api.database` (lines 13-18):

```python
from api.database import (
    fetch_due_jobs,
    get_system_connection,
    mark_job_finished,
    mark_job_running,
    record_scheduler_heartbeat,
)
```

Change `TICK_SECONDS` (line 22):

```python
TICK_SECONDS = 60           # heartbeat resolution - a 17:00 job runs by 17:01
```

Replace the body of `scheduler_loop`:

```python
async def scheduler_loop(stop_event: asyncio.Event) -> None:
    """Run due jobs on boot, then every tick until asked to stop.

    Every exception is swallowed and logged: the scheduler must never be able to
    take the application down with it. That includes the heartbeat - a stamp that
    cannot be written is a lost indicator, not a reason to stop running jobs.
    """
    while not stop_event.is_set():
        try:
            await run_due_jobs()
        except Exception:
            logger.exception("scheduler: tick failed")

        # Stamped outside the guard above, so a pass in which a job raised still
        # reports the loop as alive.
        try:
            async with get_system_connection() as conn:
                await record_scheduler_heartbeat(
                    conn, now_iso=datetime.now().isoformat(timespec="seconds")
                )
        except Exception:
            logger.exception("scheduler: could not record the heartbeat")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_SECONDS)
        except asyncio.TimeoutError:
            pass
```

`datetime` is already imported at the top of the file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_scheduler_heartbeat.py -v`
Expected: 6 passed

- [ ] **Step 5: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 543 passed (537 baseline + 6). No new warnings.

- [ ] **Step 6: Commit**

```bash
git add api/services/scheduler_service.py tests/test_scheduler_heartbeat.py
git commit -m "feat: stamp a heartbeat on every scheduler pass, tick every minute"
```

---

## Task 3: The heartbeat endpoint

**Files:**
- Create: `api/routers/system.py`
- Modify: `api/main.py` - import beside the other routers, `include_router` beside the calls at lines 139-146
- Test: `tests/test_scheduler_heartbeat.py` (append)

**Interfaces:**
- Consumes: `fetch_scheduler_heartbeat(conn)`, `get_system_connection()`, `require_any_auth` from `api.auth`
- Produces: `GET /system/heartbeat` returning `{"last_tick_at": str | None, "seconds_since": int | None, "alive": bool}`, and `api.routers.system.STALE_AFTER_SECONDS = 150`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler_heartbeat.py`:

```python
from datetime import datetime, timedelta


@pytest.mark.asyncio
async def test_heartbeat_endpoint_reports_not_alive_before_any_tick(client):
    resp = await client.get("/system/heartbeat")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"last_tick_at": None, "seconds_since": None, "alive": False}


@pytest.mark.asyncio
async def test_heartbeat_endpoint_reports_alive_for_a_recent_tick(client):
    recent = (datetime.now() - timedelta(seconds=140)).isoformat(timespec="seconds")
    async with get_system_connection() as conn:
        await record_scheduler_heartbeat(conn, now_iso=recent)

    body = (await client.get("/system/heartbeat")).json()
    assert body["alive"] is True
    assert body["last_tick_at"] == recent
    assert 135 <= body["seconds_since"] <= 145


@pytest.mark.asyncio
async def test_heartbeat_endpoint_reports_stale_for_an_old_tick(client):
    old = (datetime.now() - timedelta(seconds=200)).isoformat(timespec="seconds")
    async with get_system_connection() as conn:
        await record_scheduler_heartbeat(conn, now_iso=old)

    assert (await client.get("/system/heartbeat")).json()["alive"] is False


@pytest.mark.asyncio
async def test_heartbeat_endpoint_requires_authentication():
    """The dashboard is authenticated; liveness should not leak to anyone who asks."""
    from httpx import ASGITransport, AsyncClient

    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as anon:
        assert (await anon.get("/system/heartbeat")).status_code in (401, 403)
```

The 140/200-second offsets sit well clear of the 150-second threshold on purpose: asserting at exactly 150 and 151 would make the test's outcome depend on how long the request took.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_scheduler_heartbeat.py -v -k "endpoint"`
Expected: FAIL - all four return 404, the route does not exist.

- [ ] **Step 3: Create the router**

Create `api/routers/system.py`:

```python
# api/routers/system.py
"""System liveness.

The dashboard polls this to decide whether the idle agents should breathe. It
reports whether the scheduler loop is cycling - not whether the jobs it runs
succeed, which is a separate signal.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from api.auth import require_any_auth
from api.database import fetch_scheduler_heartbeat, get_system_connection

router = APIRouter(prefix="/system", tags=["system"])

# Two and a half ticks - tolerant of one missed pass, and still fast enough that a
# stopped clock becomes visible within a few minutes.
STALE_AFTER_SECONDS = 150


@router.get("/heartbeat")
async def get_heartbeat(payload: dict = Depends(require_any_auth)) -> dict:
    """Whether the scheduler loop is cycling.

    `alive` is decided here rather than in the browser so that a client with a
    skewed system clock cannot report a healthy server as dead, or the reverse.
    """
    async with get_system_connection() as conn:
        last_tick_at = await fetch_scheduler_heartbeat(conn)

    if last_tick_at is None:
        return {"last_tick_at": None, "seconds_since": None, "alive": False}

    seconds_since = int(
        (datetime.now() - datetime.fromisoformat(last_tick_at)).total_seconds()
    )
    return {
        "last_tick_at": last_tick_at,
        "seconds_since": seconds_since,
        "alive": seconds_since <= STALE_AFTER_SECONDS,
    }
```

- [ ] **Step 4: Register it**

In `api/main.py`, add to the router imports (beside `from api.routers import nonworking as nonworking_router`):

```python
from api.routers import system as system_router
```

and beside the `include_router` calls at lines 139-146:

```python
app.include_router(system_router.router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_scheduler_heartbeat.py -v`
Expected: 10 passed

- [ ] **Step 6: Run the full backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 547 passed. No new warnings.

- [ ] **Step 7: Commit**

```bash
git add api/routers/system.py api/main.py tests/test_scheduler_heartbeat.py
git commit -m "feat: add the scheduler heartbeat endpoint"
```

---

## Task 4: Liveness context and rotation counter

**Files:**
- Modify: `ui/src/api/endpoints.ts` - add after the `pamReportApi` block (lines 219-222)
- Create: `ui/src/context/SchedulerHeartbeatContext.tsx`
- Test: `ui/src/__tests__/SchedulerHeartbeatContext.test.tsx`

**Interfaces:**
- Consumes: `GET /system/heartbeat` from Task 3; `apiClient` from `ui/src/api/client.ts`
- Produces:
  - `systemApi.heartbeat(): Promise<SchedulerHeartbeat>` where `SchedulerHeartbeat = { last_tick_at: string | null; seconds_since: number | null; alive: boolean }`
  - `SchedulerHeartbeatProvider({ children })`
  - `useSchedulerHeartbeat(): { status: 'unknown' | 'alive' | 'stale'; lastTickAt: string | null; rotation: number }`
  - Exported constants `POLL_MS = 60_000`, `ROTATION_MS = 30_000`

- [ ] **Step 1: Write the failing tests**

Create `ui/src/__tests__/SchedulerHeartbeatContext.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/SchedulerHeartbeatContext.test.tsx`
Expected: FAIL - cannot resolve `../context/SchedulerHeartbeatContext`

- [ ] **Step 3: Add the API client call**

In `ui/src/api/endpoints.ts`, after the `pamReportApi` block (ends line 222), add:

```ts
export interface SchedulerHeartbeat {
  last_tick_at: string | null
  seconds_since: number | null
  alive: boolean
}

export const systemApi = {
  heartbeat: (): Promise<SchedulerHeartbeat> =>
    apiClient.get<SchedulerHeartbeat>('/system/heartbeat').then((r) => r.data),
}
```

- [ ] **Step 4: Create the context**

Create `ui/src/context/SchedulerHeartbeatContext.tsx`:

```tsx
// ui/src/context/SchedulerHeartbeatContext.tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

import { systemApi } from '../api/endpoints'

export type HeartbeatStatus = 'unknown' | 'alive' | 'stale'

export const POLL_MS = 60_000      // matches the scheduler's tick
export const ROTATION_MS = 30_000  // how often an idle agent changes activity

export interface HeartbeatValue {
  status: HeartbeatStatus
  lastTickAt: string | null
  rotation: number
}

// Consumers rendered outside the provider degrade to a still board rather than
// throwing - the rotation is decoration, never a reason to fail a render.
const SchedulerHeartbeatContext = createContext<HeartbeatValue>({
  status: 'unknown',
  lastTickAt: null,
  rotation: 0,
})

export function useSchedulerHeartbeat(): HeartbeatValue {
  return useContext(SchedulerHeartbeatContext)
}

export function SchedulerHeartbeatProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<HeartbeatStatus>('unknown')
  const [lastTickAt, setLastTickAt] = useState<string | null>(null)
  const [rotation, setRotation] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const beat = await systemApi.heartbeat()
        if (cancelled) return
        setStatus(beat.alive ? 'alive' : 'stale')
        setLastTickAt(beat.last_tick_at)
      } catch {
        // An unreachable API is indistinguishable from a stopped clock, and both
        // mean the same thing to a viewer: stop breathing.
        if (cancelled) return
        setStatus('stale')
      }
    }

    void poll()
    const id = setInterval(() => void poll(), POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  useEffect(() => {
    if (status !== 'alive') return
    const id = setInterval(() => setRotation((r) => r + 1), ROTATION_MS)
    return () => clearInterval(id)
  }, [status])

  return (
    <SchedulerHeartbeatContext.Provider value={{ status, lastTickAt, rotation }}>
      {children}
    </SchedulerHeartbeatContext.Provider>
  )
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd ui && npx vitest run src/__tests__/SchedulerHeartbeatContext.test.tsx`
Expected: 5 passed

- [ ] **Step 6: Typecheck**

Run: `cd ui && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add ui/src/api/endpoints.ts ui/src/context/SchedulerHeartbeatContext.tsx ui/src/__tests__/SchedulerHeartbeatContext.test.tsx
git commit -m "feat: poll scheduler liveness and gate the rotation counter on it"
```

---

## Task 5: The breathing fade

**Files:**
- Create: `ui/src/components/FadingText.tsx`
- Test: `ui/src/__tests__/FadingText.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks - this component knows nothing about agents or heartbeats
- Produces: default export `FadingText({ text, delayKey, className }: { text: string; delayKey: string; className?: string })`, plus named exports `FADE_MS = 600` and `MAX_DELAY_MS = 1200`

- [ ] **Step 1: Write the failing tests**

Create `ui/src/__tests__/FadingText.test.tsx`:

```tsx
import { render, screen, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import FadingText, { FADE_MS, MAX_DELAY_MS } from '../components/FadingText'

function mockReducedMotion(reduce: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduce && query === '(prefers-reduced-motion: reduce)',
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

beforeEach(() => {
  vi.useFakeTimers()
  mockReducedMotion(false)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('FadingText', () => {
  it('shows its initial text immediately', () => {
    render(<FadingText text="Morning yoga" delayKey="pam" />)
    expect(screen.getByText('Morning yoga')).toBeInTheDocument()
  })

  it('keeps showing the old text while fading out', () => {
    const { rerender } = render(<FadingText text="Morning yoga" delayKey="pam" />)
    rerender(<FadingText text="In the sauna" delayKey="pam" />)
    expect(screen.getByText('Morning yoga')).toBeInTheDocument()
  })

  it('shows the new text once the fade completes', () => {
    const { rerender } = render(<FadingText text="Morning yoga" delayKey="pam" />)
    rerender(<FadingText text="In the sauna" delayKey="pam" />)
    act(() => { vi.advanceTimersByTime(FADE_MS + MAX_DELAY_MS) })
    expect(screen.getByText('In the sauna')).toBeInTheDocument()
  })

  it('swaps instantly under prefers-reduced-motion', () => {
    mockReducedMotion(true)
    const { rerender } = render(<FadingText text="Morning yoga" delayKey="pam" />)
    rerender(<FadingText text="In the sauna" delayKey="pam" />)
    expect(screen.getByText('In the sauna')).toBeInTheDocument()
  })

  it('gives different keys different delays so the board ripples', () => {
    const { container: a } = render(<FadingText text="x" delayKey="pam" />)
    const { container: b } = render(<FadingText text="x" delayKey="discovery" />)
    const delayOf = (c: HTMLElement) =>
      (c.firstElementChild as HTMLElement).style.transitionDelay
    expect(delayOf(a)).not.toEqual(delayOf(b))
  })
})
```

The last test compares two hashed delays. Two keys can in principle hash to the same
delay; if `'pam'` and `'discovery'` happen to collide once the implementation exists,
substitute any two other crew keys rather than weakening the assertion.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/FadingText.test.tsx`
Expected: FAIL - cannot resolve `../components/FadingText`

- [ ] **Step 3: Implement**

Create `ui/src/components/FadingText.tsx`:

```tsx
// ui/src/components/FadingText.tsx
import { useEffect, useMemo, useRef, useState } from 'react'

export const FADE_MS = 600
export const MAX_DELAY_MS = 1200

/** Spread the change across a window so the board ripples rather than snapping in unison. */
function hashToDelay(key: string): number {
  let h = 0
  for (let i = 0; i < key.length; i++) h = (Math.imul(31, h) + key.charCodeAt(i)) | 0
  return Math.abs(h) % MAX_DELAY_MS
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

/**
 * Fades out, swaps, and fades back in when `text` changes.
 *
 * Sequential rather than an overlapping crossfade: two absolutely positioned
 * spans would need a fixed width, and these sit inline in cards that size to
 * their content.
 */
export default function FadingText({
  text,
  delayKey,
  className,
}: {
  text: string
  delayKey: string
  className?: string
}) {
  const [displayed, setDisplayed] = useState(text)
  const [visible, setVisible] = useState(true)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const delay = useMemo(() => hashToDelay(delayKey), [delayKey])

  useEffect(() => {
    if (text === displayed) return

    if (prefersReducedMotion()) {
      setDisplayed(text)
      return
    }

    setVisible(false)
    timerRef.current = setTimeout(() => {
      setDisplayed(text)
      setVisible(true)
    }, delay + FADE_MS)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [text, displayed, delay])

  const reduced = prefersReducedMotion()
  return (
    <span
      className={className}
      style={{
        opacity: visible ? 1 : 0,
        transition: reduced ? undefined : `opacity ${FADE_MS}ms ease-in-out`,
        transitionDelay: reduced ? undefined : `${delay}ms`,
      }}
    >
      {displayed}
    </span>
  )
}
```

The swap timer waits `delay + FADE_MS`, not `FADE_MS`: the CSS `transition-delay` postpones the fade, so swapping at `FADE_MS` would replace the text while it was still visible.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && npx vitest run src/__tests__/FadingText.test.tsx`
Expected: 5 passed

- [ ] **Step 5: Typecheck**

Run: `cd ui && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add ui/src/components/FadingText.tsx ui/src/__tests__/FadingText.test.tsx
git commit -m "feat: add the breathing fade for changing status text"
```

---

## Task 6: Seed advancement with repeat avoidance

**Files:**
- Modify: `ui/src/components/agentStatus.ts` - `getIdleStatus` (lines 397-402) and new code below it
- Test: `ui/src/__tests__/agentStatusRotation.test.ts`

**Interfaces:**
- Consumes: the module-private `IDLE_STATUSES` array (line 369), and `getIdleStatus(key: string, runIndex?: number): string` - whose **signature and return values must not change**. Its body is refactored to call a shared hash helper, which is behaviour-preserving; nothing else about it may change.
- Produces: `getRotatedIdleStatus(key: string, runIndex: number, rotation: number): string`

- [ ] **Step 1: Write the failing tests**

Create `ui/src/__tests__/agentStatusRotation.test.ts`:

```ts
import { describe, it, expect } from 'vitest'

import { getIdleStatus, getRotatedIdleStatus } from '../components/agentStatus'

const KEYS = ['pam', 'discovery', 'value_design', 'architecture', 'delivery']

describe('getRotatedIdleStatus', () => {
  it('matches getIdleStatus when nothing has rotated yet', () => {
    for (const key of KEYS) {
      expect(getRotatedIdleStatus(key, 3, 0)).toBe(getIdleStatus(key, 3))
    }
  })

  it('never repeats an activity back to back - a repeat reads as a missed breath', () => {
    for (const key of KEYS) {
      for (let rotation = 1; rotation < 500; rotation++) {
        expect(getRotatedIdleStatus(key, 0, rotation)).not.toBe(
          getRotatedIdleStatus(key, 0, rotation - 1),
        )
      }
    }
  })

  it('works through every activity before revisiting one', () => {
    const seen = new Set<string>()
    for (let rotation = 0; rotation < 25; rotation++) {
      seen.add(getRotatedIdleStatus('pam', 0, rotation))
    }
    expect(seen.size).toBe(25)
  })

  it('gives different agents different activities from one shared counter', () => {
    const activities = KEYS.map((k) => getRotatedIdleStatus(k, 0, 7))
    expect(new Set(activities).size).toBeGreaterThan(1)
  })

  it('stays cheap at the rotation counts a long-open dashboard reaches', () => {
    // A board left open overnight reaches ~2,880 rotations. This must be constant
    // time - an implementation that walked the history would blow the stack here.
    expect(() => getRotatedIdleStatus('pam', 0, 100_000)).not.toThrow()
  })
})
```

The "every activity before revisiting" test hard-codes 25 because `IDLE_STATUSES` has 25
entries today. If you add or remove an activity, update the number - the property being
tested is that the count equals the list length.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/__tests__/agentStatusRotation.test.ts`
Expected: FAIL - `getRotatedIdleStatus is not a function`

- [ ] **Step 3: Implement**

In `ui/src/components/agentStatus.ts`, first extract the hash that `getIdleStatus`
already computes inline, so both functions share one definition. Replace the existing
`getIdleStatus` (lines 397-402) with:

```ts
function hashSeed(seed: string): number {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (Math.imul(31, h) + seed.charCodeAt(i)) | 0
  return Math.abs(h)
}

export function getIdleStatus(key: string, runIndex = 0): string {
  return IDLE_STATUSES[hashSeed(key + runIndex) % IDLE_STATUSES.length]
}
```

This is the same arithmetic the function performs today, lifted into a helper - the
first test in this task pins that equivalence.

Then add below it:

```ts
function gcd(a: number, b: number): number {
  while (b !== 0) [a, b] = [b, a % b]
  return a
}

/**
 * The activity to show for an idle agent at a given rotation.
 *
 * A stride walk rather than seed advancement. Because the stride is coprime with the
 * list length it can never be congruent to zero, so no activity ever follows itself,
 * and the walk visits every activity before revisiting one. Checking for a repeat
 * after the fact would instead need the previously displayed value - which means
 * either storing it or walking the history, and the history grows without bound while
 * the page stays open.
 *
 * At rotation 0 this reduces to getIdleStatus, so a freshly loaded board is unchanged.
 */
export function getRotatedIdleStatus(key: string, runIndex: number, rotation: number): string {
  const n = IDLE_STATUSES.length
  if (n < 2) return IDLE_STATUSES[0]

  const base = hashSeed(key + runIndex) % n
  let stride = 1 + (hashSeed(`${key}${runIndex}:stride`) % (n - 1))
  while (gcd(stride, n) !== 1) stride = (stride % (n - 1)) + 1

  return IDLE_STATUSES[(base + rotation * stride) % n]
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && npx vitest run src/__tests__/agentStatusRotation.test.ts`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/agentStatus.ts ui/src/__tests__/agentStatusRotation.test.ts
git commit -m "feat: derive an idle agent's activity from a rotation counter"
```

---

## Task 7: Wire it into the board

**Files:**
- Modify: `ui/src/components/AppLayout.tsx` - wrap the returned tree (line 57 onwards), add the dot before `{user?.sub}` (line 106)
- Modify: `ui/src/components/CrewCarousel.tsx` - lines 93 and 227
- Modify: `ui/src/components/AgentChatDrawer.tsx` - line 298
- Test: `ui/src/__tests__/HeartbeatDot.test.tsx`

**Interfaces:**
- Consumes: `SchedulerHeartbeatProvider`, `useSchedulerHeartbeat` (Task 4); `FadingText` (Task 5); `getRotatedIdleStatus` (Task 6)
- Produces: nothing consumed by later tasks

**Note on `AgentChatDrawer.tsx`:** this component is not currently rendered anywhere in the app - grep for `AgentChatDrawer` finds only its own file. Update it anyway so the three idle call sites stay consistent, but expect no visible change from it and do not spend time trying to verify it in the browser.

- [ ] **Step 1: Write the failing test**

Create `ui/src/__tests__/HeartbeatDot.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { HeartbeatDot } from '../components/AppLayout'
import { useSchedulerHeartbeat } from '../context/SchedulerHeartbeatContext'

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
    })
    render(<HeartbeatDot />)
    expect(screen.getByTestId('heartbeat-dot').className).toContain('bg-brand')
  })

  it('goes grey when the scheduler is stale', () => {
    mockedHeartbeat.mockReturnValue({
      status: 'stale', lastTickAt: '2026-07-28T09:00:00', rotation: 0,
    })
    render(<HeartbeatDot />)
    const dot = screen.getByTestId('heartbeat-dot')
    expect(dot.className).toContain('bg-gray-300')
    expect(dot.className).not.toContain('bg-brand')
  })

  it('renders unknown the same as stale so a slow load raises no alarm', () => {
    mockedHeartbeat.mockReturnValue({ status: 'unknown', lastTickAt: null, rotation: 0 })
    render(<HeartbeatDot />)
    expect(screen.getByTestId('heartbeat-dot').className).toContain('bg-gray-300')
  })

  it('names the last tick in its tooltip', () => {
    mockedHeartbeat.mockReturnValue({ status: 'unknown', lastTickAt: null, rotation: 0 })
    render(<HeartbeatDot />)
    expect(screen.getByTestId('heartbeat-dot').getAttribute('title'))
      .toBe('The scheduler has not ticked yet')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/HeartbeatDot.test.tsx`
Expected: FAIL - `HeartbeatDot` is not exported from `../components/AppLayout`

- [ ] **Step 3: Add the dot and the provider to AppLayout**

In `ui/src/components/AppLayout.tsx`, add to the imports:

```tsx
import {
  SchedulerHeartbeatProvider,
  useSchedulerHeartbeat,
} from '../context/SchedulerHeartbeatContext'
```

Add this component above the `AppLayout` component definition:

```tsx
/**
 * Ambient scheduler liveness.
 *
 * Deliberately quiet: legible to someone who knows the convention, meaningless to a
 * client in the room. The frozen agent activities are the louder half of the signal.
 */
export function HeartbeatDot() {
  const { status, lastTickAt } = useSchedulerHeartbeat()
  const title = !lastTickAt
    ? 'The scheduler has not ticked yet'
    : status === 'alive'
      ? `The scheduler last ticked at ${lastTickAt}`
      : `The scheduler has not ticked since ${lastTickAt}`

  return (
    <span
      data-testid="heartbeat-dot"
      title={title}
      aria-label={title}
      className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
        status === 'alive' ? 'bg-brand opacity-60' : 'bg-gray-300'
      }`}
    />
  )
}
```

Render it immediately before `<span className="text-xs text-gray-400">{user?.sub}</span>` (line 106):

```tsx
          <HeartbeatDot />
          <span className="text-xs text-gray-400">{user?.sub}</span>
```

Wrap the returned tree so every page below the layout can read the context. The current return begins at line 57 with `return (` followed by `<div className="min-h-screen bg-gray-200 flex flex-col">`; wrap that `<div>` and its closing tag:

```tsx
  return (
    <SchedulerHeartbeatProvider>
      <div className="min-h-screen bg-gray-200 flex flex-col">
        {/* ...unchanged... */}
      </div>
    </SchedulerHeartbeatProvider>
  )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ui && npx vitest run src/__tests__/HeartbeatDot.test.tsx`
Expected: 4 passed

- [ ] **Step 5: Rotate PAM's idle status in CrewCarousel**

In `ui/src/components/CrewCarousel.tsx`, add to the imports:

```tsx
import FadingText from './FadingText'
import { useSchedulerHeartbeat } from '../context/SchedulerHeartbeatContext'
```

and add `getRotatedIdleStatus` to the existing import from `./agentStatus` (line 8).

In the component that renders line 93, add near its other hooks:

```tsx
  const { rotation } = useSchedulerHeartbeat()
```

Replace line 93:

```tsx
        : <FadingText
            className="text-[10px] font-medium text-gray-400"
            text={getRotatedIdleStatus('pam', runCount, rotation)}
            delayKey="pam"
          />
```

- [ ] **Step 6: Rotate each crew's idle status in CrewCarousel**

In the component that renders line 227, add near its other hooks:

```tsx
  const { rotation } = useSchedulerHeartbeat()
```

Replace line 227:

```tsx
                             <FadingText
                               className="text-[10px] font-medium text-gray-300"
                               text={getRotatedIdleStatus(crewKey, crewRun?.id ?? 0, rotation)}
                               delayKey={crewKey}
                             />
```

- [ ] **Step 7: Rotate the chat drawer's idle status**

In `ui/src/components/AgentChatDrawer.tsx`, add to the imports:

```tsx
import FadingText from './FadingText'
import { useSchedulerHeartbeat } from '../context/SchedulerHeartbeatContext'
```

and add `getRotatedIdleStatus` to the existing import from `./agentStatus` (line 8).

Add near the component's other hooks:

```tsx
  const { rotation } = useSchedulerHeartbeat()
```

Replace line 298 (keeping the surrounding pill `<span>` exactly as it is):

```tsx
                  <FadingText
                    text={getRotatedIdleStatus(agentName ?? 'agent', crewRun?.id ?? 0, rotation)}
                    delayKey={agentName ?? 'agent'}
                  />
```

- [ ] **Step 8: Run the whole frontend suite and typecheck**

Run: `cd ui && npx vitest run && npx tsc --noEmit`
Expected: all suites pass, no type errors. If an existing test renders `CrewCarousel` outside the provider, it still passes - the context default is `{ status: 'unknown', lastTickAt: null, rotation: 0 }`, which renders a still board rather than throwing.

- [ ] **Step 9: Run the backend suite**

Run: `./venv/bin/pytest -q --ignore=tests/integration`
Expected: 547 passed, unchanged by this task.

- [ ] **Step 10: Commit**

```bash
git add ui/src/components/AppLayout.tsx ui/src/components/CrewCarousel.tsx ui/src/components/AgentChatDrawer.tsx ui/src/__tests__/HeartbeatDot.test.tsx
git commit -m "feat: breathe the idle agent activities while the scheduler ticks"
```

---

## Manual verification

Automated tests cannot see a fade. After Task 7:

1. Start the API and the UI. Open the dashboard and leave it for two minutes. Idle agents should change activity roughly every 30 seconds, not all at the same instant, each one fading out and back in rather than snapping.
2. The dot beside the username should be soft teal. Hover it - the tooltip should name a tick time within the last minute.
3. Stop only the scheduler (comment out the `asyncio.create_task(scheduler_loop(...))` line in `api/main.py`'s lifespan and restart the API). Within about three minutes the dot should turn grey and the activities should stop changing while the rest of the dashboard keeps working normally.
4. Restore the line and confirm both resume.
5. Set "Reduce motion" in macOS System Settings > Accessibility > Display, reload, and confirm the activities still change but swap instantly with no fade.
