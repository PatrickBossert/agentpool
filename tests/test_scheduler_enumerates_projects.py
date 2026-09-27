# tests/test_scheduler_enumerates_projects.py
"""A project is a row in `project_registry`, not a file in `data/`.

Both startup sweeps used to enumerate `Path(database_dir).glob("*.db")`, which is a list of
files rather than a list of engagements - so every backup taken into `data/` became a project
within hours of being made. Measured on the live deployment, 17 September 2026: **seventeen
scheduled daily reports against one real project**, eleven of the phantoms `sp-gs-am.*`
snapshots and four of them backups of `system.db` itself.

The noise was the harmless half. The sibling sweep **writes**: `_mark_stale_runs_failed` runs
`UPDATE crew_runs SET status='failed'` against every file it finds, and ten runs in a
six-week-old `sp-gs-am` backup had been flipped by restarts - so the backups were no longer
copies of what was backed up.

Every test here drives the property in **both** directions. "A registered project gets a job"
is satisfied by a change that registers everything; "an unregistered database gets no job" is
satisfied by one that registers nothing. Only the pair says the enumeration is the registry.
"""
from __future__ import annotations

import sqlite3

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import (
    delete_scheduled_jobs_for_unknown_slugs,
    fetch_registered_slugs,
    get_system_connection,
    init_system_db,
    upsert_scheduled_job,
)

REAL = "an-engagement"
BACKUP = "an-engagement.pre-something-2026-08-05"


@pytest_asyncio.fixture
async def system_db(tmp_path, monkeypatch):
    """A private system database, and two database *files* of which only one is a project.

    `@pytest_asyncio.fixture` rather than `@pytest.fixture`: `pytest.ini` sets
    `asyncio_mode = strict`, under which a plain fixture on an `async def` is handed over as
    an un-awaited async generator - the body never runs and nothing complains.
    """
    db_dir = tmp_path / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATABASE_DIR", str(db_dir))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()

    # Two files on disk. The glob cannot tell them apart; the registry can.
    for slug in (REAL, BACKUP):
        conn = sqlite3.connect(db_dir / f"{slug}.db")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS crew_runs (id INTEGER PRIMARY KEY, status TEXT, result_json TEXT)"
        )
        conn.execute("INSERT INTO crew_runs (status) VALUES ('running')")
        conn.commit()
        conn.close()

    async with get_system_connection() as conn:
        await init_system_db(conn)
        await conn.execute(
            "INSERT OR IGNORE INTO organisations (id, slug, name) VALUES (1, 'home', 'Home')"
        )
        await conn.execute(
            "INSERT OR IGNORE INTO project_registry (slug, org_id, display_name) VALUES (?,1,?)",
            (REAL, "An Engagement"),
        )
        await conn.commit()

    yield db_dir
    get_settings.cache_clear()


# ── The enumeration ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_registry_names_the_project_and_not_the_backup_beside_it(system_db):
    """Both halves. The first alone passes against "return every stem in the directory"."""
    async with get_system_connection() as conn:
        slugs = await fetch_registered_slugs(conn)

    assert REAL in slugs
    assert BACKUP not in slugs, (
        "a backup file in data/ is being read as a project - which is how one deployment "
        "reached seventeen scheduled reports against one engagement"
    )


@pytest.mark.asyncio
async def test_a_registry_row_cannot_outlive_its_organisation(system_db):
    """Why the narrow read is about intent rather than safety, asserted so it stays true.

    This test replaces one that asserted the opposite. The reasoning written first was that
    `fetch_all_registry`'s JOIN on `organisations` is a silent filter, so a project whose
    organisation had gone would vanish from a sweep that decides what gets written to. It
    is a plausible argument and the schema refuses it: `org_id` is `NOT NULL REFERENCES
    organisations(id) ON DELETE CASCADE`, so the orphan is unreachable in both directions -
    it cannot be inserted, and deleting the organisation takes the row with it.

    Kept rather than deleted, because the next person to reach for `fetch_all_registry`
    here deserves the real reason (it selects a column this caller does not want) instead
    of a safety claim that would not survive being checked.
    """
    async with get_system_connection() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            await conn.execute(
                "INSERT INTO project_registry (slug, org_id, display_name) "
                "VALUES ('orphaned-engagement', 9999, 'No Such Org')"
            )
        await conn.rollback()

        # And the other direction: the cascade removes the project with the organisation.
        await conn.execute(
            "INSERT OR IGNORE INTO organisations (id, slug, name) VALUES (7, 'doomed', 'Doomed')"
        )
        await conn.execute(
            "INSERT INTO project_registry (slug, org_id, display_name) VALUES (?,7,?)",
            ("goes-with-its-org", "Goes"),
        )
        await conn.commit()
        assert "goes-with-its-org" in await fetch_registered_slugs(conn)

        await conn.execute("DELETE FROM organisations WHERE id=7")
        await conn.commit()
        assert "goes-with-its-org" not in await fetch_registered_slugs(conn)


# ── The startup registration ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_startup_registers_the_project_and_drops_the_phantom(system_db):
    """Driven through `_register_scheduled_jobs`, which is what actually runs at startup.

    A phantom row is seeded first, because stopping the glob creating new ones does not
    remove the old: the rows live in `system.db` and would have gone on firing daily
    against a frozen copy of a client's data.
    """
    from api.main import _register_scheduled_jobs
    from api.services.pam_report_job import JOB_NAME

    async with get_system_connection() as conn:
        await upsert_scheduled_job(
            conn, job_name=JOB_NAME, slug=BACKUP, next_due_at="2026-09-18T17:00:00"
        )
        await conn.commit()

    await _register_scheduled_jobs()

    async with get_system_connection() as conn:
        async with conn.execute("SELECT slug FROM scheduled_jobs") as cur:
            scheduled = {r["slug"] async for r in cur}

    assert REAL in scheduled, "the real engagement lost its daily report"
    assert BACKUP not in scheduled, "the phantom job survived the sweep"


@pytest.mark.asyncio
async def test_an_empty_registry_does_not_delete_every_job(system_db):
    """The refusal that stops the sweep meaning "delete everything".

    A deployment part-way through creating its first project legitimately has an empty
    registry, and a sweep keyed on it would delete the job the next statement registers.
    Asserted because the guard is one `if` and reads as defensive padding.
    """
    from api.services.pam_report_job import JOB_NAME

    async with get_system_connection() as conn:
        await upsert_scheduled_job(
            conn, job_name=JOB_NAME, slug=REAL, next_due_at="2026-09-18T17:00:00"
        )
        await conn.commit()
        dropped = await delete_scheduled_jobs_for_unknown_slugs(conn, known=[])
        async with conn.execute("SELECT COUNT(*) AS n FROM scheduled_jobs") as cur:
            remaining = (await cur.fetchone())["n"]

    assert dropped == 0
    assert remaining == 1


# ── The sweep that writes ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_stale_run_sweep_does_not_write_to_a_backup(system_db):
    """The half that made this a data-integrity defect rather than noise.

    Ten crew_runs in a real six-week-old backup had been flipped to `failed` by restarts.
    Both assertions: the project's orphaned run is still cleaned, and the backup's is left
    exactly as it was.
    """
    from api.main import _mark_stale_runs_failed

    async with get_system_connection() as conn:
        slugs = await fetch_registered_slugs(conn)

    await _mark_stale_runs_failed(str(system_db), slugs)

    def status_of(slug: str) -> str:
        conn = sqlite3.connect(system_db / f"{slug}.db")
        try:
            return conn.execute("SELECT status FROM crew_runs").fetchone()[0]
        finally:
            conn.close()

    assert status_of(REAL) == "failed", "the real project's orphaned run was not cleaned"
    assert status_of(BACKUP) == "running", (
        "the sweep wrote to a backup - a backup that changes is not a backup"
    )


@pytest.mark.asyncio
async def test_the_sweep_survives_a_registered_project_with_no_file(system_db):
    """A registry row whose database has been moved away must not take startup down.

    This is exactly the state the deployment was left in by removing two projects: the
    row goes, but the reverse - a row with no file - is reachable by restoring a
    `system.db` backup, and startup failing there would be a very confusing outage.
    """
    from api.main import _mark_stale_runs_failed

    async with get_system_connection() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO project_registry (slug, org_id, display_name) "
            "VALUES ('no-file-at-all', 1, 'Gone')"
        )
        await conn.commit()
        slugs = await fetch_registered_slugs(conn)

    await _mark_stale_runs_failed(str(system_db), slugs)  # must not raise
