# api/services/scheduler_service.py
"""The platform's clock.

Job state lives in the database rather than in memory, so a restart can see what
is overdue and run it. An external scheduler cannot do that: if the machine is
asleep when a cron fires, the tick is simply lost and nothing knows.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from api.database import (
    fetch_due_jobs,
    get_system_connection,
    mark_job_finished,
    mark_job_running,
)

logger = logging.getLogger(__name__)

TICK_SECONDS = 900          # 15 minutes - a 17:00 job runs by 17:15
REPORT_HOUR = 17            # server local time

# job_name -> coroutine taking the project slug. Populated by the job modules.
JOB_REGISTRY: dict[str, Callable[[str], Awaitable[None]]] = {}


def next_due_at(after: datetime, hour: int = REPORT_HOUR) -> str:
    """The next occurrence of `hour`:00 strictly after `after`.

    Deliberately returns a single next occurrence rather than catching up on every
    missed day: a week of downtime should produce one report, not seven.
    """
    candidate = after.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= after:
        candidate += timedelta(days=1)
    return candidate.isoformat(timespec="seconds")


async def run_due_jobs(now: datetime | None = None) -> int:
    """Run every job whose next_due_at has passed. Returns how many ran."""
    now = now or datetime.now()
    now_iso = now.isoformat(timespec="seconds")
    ran = 0

    async with get_system_connection() as conn:
        due = await fetch_due_jobs(conn, now_iso=now_iso)

    for job in due:
        name, slug = job["job_name"], job["slug"]
        handler = JOB_REGISTRY.get(name)
        if handler is None:
            logger.warning("scheduler: no handler registered for job %r - skipping", name)
            continue

        async with get_system_connection() as conn:
            claimed = await mark_job_running(conn, job_name=name, slug=slug, now_iso=now_iso)
        if not claimed:
            continue

        status, error = "ok", ""
        try:
            await handler(slug)
            ran += 1
        except Exception as exc:
            status, error = "failed", str(exc)
            logger.exception("scheduler: job %r failed for %s", name, slug)

        async with get_system_connection() as conn:
            await mark_job_finished(
                conn, job_name=name, slug=slug, status=status,
                next_due_at=next_due_at(now), last_error=error,
            )

    return ran


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    """Run due jobs on boot, then every tick until asked to stop.

    Every exception is swallowed and logged: the scheduler must never be able to
    take the application down with it.
    """
    while not stop_event.is_set():
        try:
            await run_due_jobs()
        except Exception:
            logger.exception("scheduler: tick failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_SECONDS)
        except asyncio.TimeoutError:
            pass
