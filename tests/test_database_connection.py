# tests/test_database_connection.py
import asyncio

import pytest
from api.config import get_settings


@pytest.mark.asyncio
async def test_connections_are_wal(tmp_path, monkeypatch):
    """journal_mode=delete makes writers block readers on one project file, and
    completions - the heavy writes - cluster at the end of a break."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    from api.database import get_connection
    async with get_connection("waltest") as conn:
        cur = await conn.execute("PRAGMA journal_mode")
        assert (await cur.fetchone())[0].lower() == "wal"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_connections_have_a_busy_timeout(tmp_path, monkeypatch):
    """busy_timeout is per-connection, unlike WAL, so it must be asserted on the
    connection itself rather than inferred from the pragma having been issued once.
    Without it, a connection that meets a lock fails immediately with 'database is
    locked' instead of waiting for the writer to finish."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    from api.database import get_connection
    async with get_connection("busytimeouttest") as conn:
        cur = await conn.execute("PRAGMA busy_timeout")
        assert (await cur.fetchone())[0] == 10000
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_migrations_run_once_per_slug(tmp_path, monkeypatch):
    """28 migration functions on every open, ~4.2ms, and one request opens several."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    import api.database as db
    calls = []
    original = db._migrate_interview_answers

    async def counting(conn):
        calls.append(1)
        await original(conn)

    monkeypatch.setattr(db, "_migrate_interview_answers", counting)
    db._MIGRATED.clear()
    async with db.get_connection("oncetest") as conn:
        await conn.execute("SELECT 1")
    async with db.get_connection("oncetest") as conn:
        await conn.execute("SELECT 1")
    assert len(calls) == 1, f"migrations ran {len(calls)} times for one slug"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_migrations_rerun_after_the_file_is_deleted_and_recreated(tmp_path, monkeypatch):
    """The property the (slug, inode) design existed to protect and PRAGMA user_version
    protects now: a slug alone is not proof a given file has been migrated. Delete the
    file underneath a memoised slug and reopen it - the new, schema-less file must be
    migrated again, not skipped because its slug looks familiar. This is also what a test
    fixture that unlinks a fixed-slug .db file between tests relies on, and there are
    dozens of those in this suite."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    import api.database as db
    calls = []
    original = db._migrate_interview_answers

    async def counting(conn):
        calls.append(1)
        await original(conn)

    monkeypatch.setattr(db, "_migrate_interview_answers", counting)
    db._MIGRATED.clear()

    async with db.get_connection("deletetest") as conn:
        await conn.execute("SELECT 1")
    assert len(calls) == 1

    db.get_db_path("deletetest").unlink()

    async with db.get_connection("deletetest") as conn:
        await conn.execute("SELECT 1")
    assert len(calls) == 2, (
        f"migrations ran {len(calls)} times across a delete and recreate under the same "
        "slug - the new file was wrongly treated as already migrated"
    )
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_writer_does_not_block_concurrent_reader(tmp_path, monkeypatch):
    """The property that actually matters: a reader on its own connection can
    proceed while another connection holds an open write transaction on the
    same project file. Under journal_mode=delete this deadlocks (or times out
    on busy_timeout) because the writer's exclusive lock blocks the reader
    until commit. Under WAL, readers see the pre-write snapshot and return
    immediately - this test would fail (hang, or raise 'database is locked')
    against the original journal_mode=delete configuration.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    import api.database as db

    async with db.get_connection("concurrenttest") as writer:
        await writer.execute(
            "CREATE TABLE IF NOT EXISTS wal_probe (id INTEGER PRIMARY KEY, val TEXT)"
        )
        await writer.commit()

        # Open a write transaction and leave it uncommitted.
        await writer.execute("BEGIN IMMEDIATE")
        await writer.execute("INSERT INTO wal_probe (val) VALUES ('pending')")

        # A concurrent reader on a separate connection must not block on the
        # writer's uncommitted transaction.
        async def read():
            async with db.get_connection("concurrenttest") as reader:
                cur = await reader.execute("SELECT COUNT(*) FROM wal_probe")
                return (await cur.fetchone())[0]

        result = await asyncio.wait_for(read(), timeout=3.0)
        assert result == 0  # reader sees pre-write snapshot, not the uncommitted row

        await writer.commit()

    get_settings.cache_clear()
