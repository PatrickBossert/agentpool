# api/main.py
import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.config import get_settings
from api.services.scheduler_service import scheduler_loop
import api.services.pam_report_job  # noqa: F401 - registers JOB_REGISTRY["pam_daily_report"]
from api.routers import projects, run, outputs, ws
from api.routers import validations as validations_router
from api.routers import auth as auth_router
from api.routers import documents as documents_router
from api.routers import reviews as reviews_router
from api.routers import orchestrate as orchestrate_router
from api.routers import runs as runs_router
from api.routers import stakeholders as stakeholders_router
from api.routers import campaigns as campaigns_router
from api.routers import assignment as assignment_router
from api.routers import interviews as interviews_router
from api.routers import templates as templates_router
from api.routers import admin as admin_router
from api.routers import agent_chat as agent_chat_router
from api.routers import skill_notes as skill_notes_router
from api.routers import skills as skills_router
from api.routers import milestones as milestones_router
from api.routers import pam_report as pam_report_router
from api.routers import nonworking as nonworking_router
from api.routers import system as system_router
from api.routers import commits as commits_router
from api.routers import value_chain as value_chain_router
from api.routers import script_reviews as script_reviews_router


async def _mark_stale_runs_failed(database_dir: str) -> None:
    """On startup, mark any crew_runs still in 'running' state as failed.

    Runs left in 'running' are orphaned by a previous server restart — no async
    task exists for them and they will never complete on their own.
    """
    import aiosqlite
    import logging
    log = logging.getLogger(__name__)
    for db_path in Path(database_dir).glob("*.db"):
        if db_path.name == "system.db":
            continue
        try:
            async with aiosqlite.connect(str(db_path)) as conn:
                cur = await conn.execute(
                    "UPDATE crew_runs SET status='failed', result_json=? WHERE status='running'",
                    ('{"error": "Server restart interrupted run"}',),
                )
                await conn.commit()
                if cur.rowcount:
                    log.warning(
                        "Marked %d orphaned crew run(s) as failed in %s",
                        cur.rowcount, db_path.name,
                    )
        except Exception:
            log.exception("Could not clean up stale runs in %s", db_path.name)


async def _reset_stale_scheduled_jobs() -> None:
    """On startup, reset any scheduled_jobs rows orphaned by a previous
    process death (power cut, SIGKILL, operator restart) - see
    reset_stale_running_jobs. This is a 24x7 unattended process, so it must
    self-heal on boot rather than leaving that project's daily report stuck
    forever. Never raises: a scheduling problem must not stop the API from
    starting.
    """
    import logging

    from api.database import get_system_connection, reset_stale_running_jobs

    log = logging.getLogger(__name__)
    try:
        async with get_system_connection() as conn:
            n = await reset_stale_running_jobs(conn)
        if n:
            log.warning("scheduler: reset %d job(s) stuck in 'running' after a restart", n)
    except Exception:
        log.exception("scheduler: could not reset stale jobs - continuing")


async def _register_scheduled_jobs() -> None:
    """Ensure every project has a daily report job registered.

    Uses an upsert that leaves an existing schedule alone, so restarting does not
    postpone a job that is already due. Never raises: a scheduling problem must
    not stop the API from starting.
    """
    import logging
    from datetime import datetime

    from api.database import get_system_connection, upsert_scheduled_job
    from api.services.pam_report_job import JOB_NAME
    from api.services.scheduler_service import next_due_at

    log = logging.getLogger(__name__)
    try:
        settings = get_settings()
        due = next_due_at(datetime.now())
        slugs = [p.stem for p in Path(settings.database_dir).glob("*.db")
                 if p.name != "system.db"]
        async with get_system_connection() as conn:
            for slug in slugs:
                await upsert_scheduled_job(conn, job_name=JOB_NAME, slug=slug, next_due_at=due)
        log.info("scheduler: registered the daily report job for %d project(s)", len(slugs))
    except Exception:
        log.exception("scheduler: could not register jobs - continuing without them")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path(settings.database_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.projects_dir).mkdir(parents=True, exist_ok=True)
    await _mark_stale_runs_failed(settings.database_dir)
    await _reset_stale_scheduled_jobs()

    await _register_scheduled_jobs()
    stop_event = asyncio.Event()
    scheduler_task = asyncio.create_task(scheduler_loop(stop_event))

    yield

    stop_event.set()
    scheduler_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await scheduler_task

    from api.services.http_clients import close_http_clients
    await close_http_clients()


app = FastAPI(title="AgentPool API", version="0.1.0", lifespan=lifespan, favicon_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(run.router)
app.include_router(outputs.router)
app.include_router(ws.router)
app.include_router(auth_router.router)
app.include_router(documents_router.router)
app.include_router(reviews_router.router)
app.include_router(orchestrate_router.router)
app.include_router(runs_router.router)
app.include_router(stakeholders_router.router)
app.include_router(campaigns_router.router)
app.include_router(assignment_router.router)
app.include_router(interviews_router.router)
app.include_router(templates_router.router)
app.include_router(admin_router.router)
app.include_router(agent_chat_router.router)
app.include_router(skill_notes_router.router)
app.include_router(skills_router.router)
app.include_router(milestones_router.router)
app.include_router(pam_report_router.router)
app.include_router(nonworking_router.router)
app.include_router(system_router.router)
app.include_router(commits_router.router)
app.include_router(value_chain_router.router)
app.include_router(script_reviews_router.router)
app.include_router(validations_router.router)
