# tests/test_stakeholder_synthetic_migration.py
"""`stakeholders.is_synthetic` has to reach databases that already exist.

Every project database on this deployment already has a `stakeholders` table, so
`CREATE TABLE IF NOT EXISTS` in `_migrate_stakeholders` does nothing for any of them - the
column arrives only through the ALTER branch below it, and only if `get_connection` runs the
migration block at all. That second condition is a fact about `_SCHEMA_VERSION`: the block
is gated on `user_version < _SCHEMA_VERSION`, so adding a column to a migration that has
already run is exactly as invisible as adding a whole new migration and forgetting the bump.

A test built on a fresh database cannot see either failure, because a fresh database gets the
column from the CREATE TABLE statement. So this reproduces the shape a live database actually
has - the table without the column, already stamped at the previous schema version - which is
precisely `data/sp-gs-am.db`'s shape at the time this shipped.
"""
import sqlite3
from pathlib import Path

import pytest
import pytest_asyncio

from api.database import get_connection

SLUG = "synthetic-column-migration-test"


def _write_pre_column_db(db_path: Path, *, stamped_version: int) -> None:
    """A project database holding a stakeholders table with no is_synthetic column, stamped
    as already migrated to `stamped_version`."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL,"
        " llm_mode TEXT, sector TEXT, config_json TEXT, status TEXT,"
        " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE stakeholders (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " project_id INTEGER NOT NULL REFERENCES projects(id), name TEXT NOT NULL,"
        " job_title TEXT NOT NULL DEFAULT '', organisation TEXT NOT NULL DEFAULT '',"
        " email TEXT NOT NULL DEFAULT '', slack_handle TEXT NOT NULL DEFAULT '',"
        " stakeholder_groups TEXT NOT NULL DEFAULT '[]',"
        " project_role TEXT NOT NULL DEFAULT 'recipient',"
        " value_streams TEXT NOT NULL DEFAULT '[]',"
        " value_chain_stage TEXT NOT NULL DEFAULT '', activity TEXT NOT NULL DEFAULT '',"
        " disposition TEXT NOT NULL DEFAULT 'neutral', location TEXT NOT NULL DEFAULT '',"
        " country_code TEXT NOT NULL DEFAULT '', timezone TEXT NOT NULL DEFAULT '',"
        " preferred_language TEXT NOT NULL DEFAULT '', currency TEXT NOT NULL DEFAULT '',"
        " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("INSERT INTO projects (slug) VALUES (?)", (SLUG,))
    conn.execute(
        "INSERT INTO stakeholders (project_id, name, email) VALUES (1,?,?)",
        ("Patrick Bossert", "patrick@futureedge.consulting"),
    )
    conn.execute(f"PRAGMA user_version = {stamped_version}")
    conn.commit()
    conn.close()


@pytest_asyncio.fixture
async def settings_dir(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    yield tmp_path
    get_settings.cache_clear()


async def _columns(slug):
    async with get_connection(slug) as conn:
        rows = await conn.execute_fetchall("PRAGMA table_info(stakeholders)")
    return {r["name"] for r in rows}


@pytest.mark.asyncio
async def test_an_existing_database_gains_the_column(settings_dir):
    _write_pre_column_db(settings_dir / f"{SLUG}.db", stamped_version=0)
    assert "is_synthetic" in await _columns(SLUG)


@pytest.mark.asyncio
async def test_a_database_stamped_at_the_previous_version_gains_it_too(settings_dir):
    """The bump is what makes this pass. `_SCHEMA_VERSION` went 8 -> 9 with this column; a
    database stamped 8 is every project database opened since the assignment re-key, and
    without the bump the migration block never runs on one again."""
    _write_pre_column_db(settings_dir / f"{SLUG}.db", stamped_version=8)
    assert "is_synthetic" in await _columns(SLUG)


@pytest.mark.asyncio
async def test_the_people_already_there_are_not_marked_by_the_migration(settings_dir):
    """The column defaults to 0, so every row that predates it is a real person - which is
    the assumption `--remove` relies on when it deletes on `is_synthetic = 1`."""
    _write_pre_column_db(settings_dir / f"{SLUG}.db", stamped_version=8)
    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT name, email, is_synthetic FROM stakeholders ORDER BY id"
        )
    assert [dict(r) for r in rows] == [
        {
            "name": "Patrick Bossert",
            "email": "patrick@futureedge.consulting",
            "is_synthetic": 0,
        }
    ]
