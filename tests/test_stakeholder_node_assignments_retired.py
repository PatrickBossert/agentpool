# tests/test_stakeholder_node_assignments_retired.py
"""The second assignment table has to actually leave the databases that already have it.

There were two. `stakeholder_node_assignments` was written by the assignment page and read
by nothing on the backend; `stakeholder_assignments` is what run_service hands the Interview
Coordinator and had no reachable writer. A human could therefore save the mapping into a
table no agent consults - which is the defect this branch exists to close - and leaving the
unread one in place, empty and plausibly named, is how a third writer would find it.

Every project database on this deployment already holds the table, so the drop reaches them
only if `get_connection` runs the migration block at all, and that is a fact about
`_SCHEMA_VERSION` rather than about the migration: the block is gated on
`user_version < _SCHEMA_VERSION`. A test built on a fresh database cannot see a missed bump,
because a fresh database never had the table in the first place. So this reproduces the shape
a live database actually has - the table present, the file stamped at the previous version -
which is `data/sp-gs-am.db`'s shape at the time this shipped. It fails on 9 and passes on 10.
"""
import sqlite3
from pathlib import Path

import pytest
import pytest_asyncio

from api.database import get_connection

SLUG = "node-assignments-retirement-test"


def _write_pre_drop_db(db_path: Path, *, stamped_version: int) -> None:
    """A project database still holding stakeholder_node_assignments, stamped as already
    migrated to `stamped_version`."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL,"
        " llm_mode TEXT, sector TEXT, config_json TEXT, status TEXT,"
        " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE stakeholder_node_assignments (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " project_id INTEGER NOT NULL, stakeholder_id INTEGER NOT NULL,"
        " node_key TEXT NOT NULL, UNIQUE(project_id, stakeholder_id, node_key))"
    )
    conn.execute("INSERT INTO projects (slug) VALUES (?)", (SLUG,))
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


async def _tables(slug) -> set[str]:
    async with get_connection(slug) as conn:
        rows = await conn.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    return {r["name"] for r in rows}


@pytest.mark.asyncio
async def test_an_existing_database_loses_the_table(settings_dir):
    _write_pre_drop_db(settings_dir / f"{SLUG}.db", stamped_version=0)
    tables = await _tables(SLUG)
    assert "stakeholder_node_assignments" not in tables
    # And the mapping agents actually read is still there, so this dropped the right one.
    assert "stakeholder_assignments" in tables


@pytest.mark.asyncio
async def test_a_database_stamped_at_the_previous_version_loses_it_too(settings_dir):
    """The bump is what makes this pass. `_SCHEMA_VERSION` went 9 -> 10 with this drop; a
    database stamped 9 is every project database opened since `is_synthetic` shipped, and
    without the bump the migration block never runs on one again."""
    _write_pre_drop_db(settings_dir / f"{SLUG}.db", stamped_version=9)
    assert "stakeholder_node_assignments" not in await _tables(SLUG)


@pytest.mark.asyncio
async def test_the_helpers_that_read_it_are_gone_too(settings_dir):
    """A helper outliving its table is a NameError waiting for its first caller, and worse,
    an invitation to recreate the table to make the helper work again."""
    import api.database as db

    assert not hasattr(db, "get_stakeholder_node_assignments")
    assert not hasattr(db, "upsert_stakeholder_node_assignments")


def test_the_endpoints_that_wrote_it_are_gone_too():
    """The two doors on the stakeholders router. Retiring the table while leaving a writer
    routed at it turns a save into a 500 rather than into the one door that works.

    Asserted against the app's own route table rather than by calling the paths: a 404 from
    a live handler for an unknown project and a 404 from an unrouted path are the same
    status, so a call could not tell a retired endpoint from a surviving one.
    """
    from api.main import app

    paths = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    assert ("/projects/{slug}/stakeholder-assignments", "GET") not in paths
    assert ("/projects/{slug}/stakeholder-assignments", "PUT") not in paths
    # The door that replaces them, on the same app, so this cannot pass by finding nothing.
    assert ("/projects/{slug}/assignment", "POST") in paths
