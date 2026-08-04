# tests/test_crew_rename_migration.py
"""Renaming a crew is a migration, not a rename.

`crew_runs.crew_name` holds the name a run was dispatched under, and `approval_commits` and
`crew_submissions` carry the same column. Rename the key in code alone and every historical
row belongs to a crew that no longer exists: it does not read as history, it disappears from
the board, and a commit gate keyed to it can never be satisfied.
"""
import shutil
from pathlib import Path

import pytest

from api.config import get_settings
from api.database import get_connection

SLUG = "crew-rename-test"
PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "utilities",
    "stakeholder_groups": [],
    "value_stream_labels": [],
    "crews_enabled": ["requirements"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean():
    def wipe():
        settings = get_settings()
        Path(settings.database_dir, f"{SLUG}.db").unlink(missing_ok=True)
        proj = Path(settings.projects_dir, SLUG)
        if proj.exists():
            shutil.rmtree(proj)
    wipe()
    yield
    get_settings.cache_clear()
    wipe()


async def _write_old_rows(conn) -> None:
    """Rows as they were stored before the rename, inserted directly - the point is to
    reproduce a database written by the old code."""
    project = await conn.execute_fetchall("SELECT id FROM projects LIMIT 1")
    project_id = project[0][0]
    await conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status) VALUES (?,?,?)",
        (project_id, "architecture", "completed"),
    )
    await conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status) VALUES (?,?,?)",
        (project_id, "discovery", "completed"),
    )
    await conn.execute(
        "INSERT INTO approval_commits (crew_name, committed_by, notes) VALUES (?,?,?)",
        ("architecture", "a", ""),
    )
    await conn.commit()


@pytest.mark.asyncio
async def test_a_historical_run_is_renamed_not_orphaned(client):
    """Asserting that new rows use the new name would pass while every past run vanished
    from the board - which is the whole risk of a rename."""
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        await _write_old_rows(conn)

    # No explicit call: the migration runs on connection open, so simply reopening is the
    # production path. Asserting a return count here tested a call the fixture had already
    # made, which is why it read zero.
    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall("SELECT crew_name FROM crew_runs ORDER BY id")

    # Renamed AND still present - two rows in, two rows out. A migration that deleted what
    # it could not rename would satisfy a names-only assertion.
    assert len(rows) == 2
    assert {r[0] for r in rows} == {"capabilities", "requirements"}


@pytest.mark.asyncio
async def test_commits_are_renamed_too(client):
    # approval_commits carries the same column. Migrating only crew_runs would leave a
    # commit gate keyed to a crew nothing can ever run, so the pipeline stops there.
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        await _write_old_rows(conn)

    from api.database import rename_crew_in_stored_rows

    async with get_connection(SLUG) as conn:
        await rename_crew_in_stored_rows(conn)
        rows = await conn.execute_fetchall("SELECT crew_name FROM approval_commits")

    assert [r[0] for r in rows] == ["capabilities"]


@pytest.mark.asyncio
async def test_running_the_migration_twice_changes_nothing_further(client):
    # It runs on every connection open. A second pass must be a no-op rather than, say,
    # renaming something that legitimately arrived under the new name.
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        await _write_old_rows(conn)

    from api.database import rename_crew_in_stored_rows

    async with get_connection(SLUG) as conn:
        await rename_crew_in_stored_rows(conn)
        second = await rename_crew_in_stored_rows(conn)
        rows = await conn.execute_fetchall("SELECT crew_name FROM crew_runs ORDER BY id")

    assert second == 0
    assert {r[0] for r in rows} == {"capabilities", "requirements"}


def test_no_declaration_still_names_the_old_crews():
    """A half-finished rename fails here rather than at runtime on someone's board.

    Checks the maps that decide what may run - not prose, and not `architecture` used as an
    output type in agent_chat_service, which is a different thing with the same spelling.
    """
    from api.services.crew_graph import CREW_DEPENDENCIES
    from api.services.run_service import _CREW_AGENT_NAMES

    for name in ("architecture", "discovery"):
        assert name not in CREW_DEPENDENCIES
        assert name not in _CREW_AGENT_NAMES
        for deps in CREW_DEPENDENCIES.values():
            assert name not in deps
