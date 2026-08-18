# tests/test_platform_settings.py
"""platform_public_url()'s precedence chain: stored value, environment, and the two read
failures that must fall back without caching.

Three tests for stored-vs-environment precedence are written separately on purpose - a
resolver that answered the environment unconditionally would pass
test_the_environment_wins_when_nothing_is_stored and
test_a_blank_stored_value_does_not_shadow_the_environment together while failing the first.
"""
import sqlite3

import pytest

from api.config import get_settings
from api.services import platform_settings as ps


@pytest.fixture(autouse=True)
def _isolated_platform_settings(tmp_path, monkeypatch):
    """Point DATABASE_DIR at this test's own tmp_path and drop the module cache on both
    sides, so no test can see another test's system.db or another test's cached result.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    ps.forget_platform_settings()
    yield
    ps.forget_platform_settings()
    get_settings.cache_clear()


def _write_system_db(tmp_path, public_url=None, *, with_table=True):
    """Create system.db. public_url=None leaves the table with no row at all - the
    "nothing stored yet" shape - rather than a row holding a blank string.
    """
    db_path = tmp_path / "system.db"
    conn = sqlite3.connect(db_path)
    try:
        if with_table:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS platform_settings ("
                " id INTEGER PRIMARY KEY CHECK (id = 1),"
                " public_url TEXT NOT NULL DEFAULT '',"
                " updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
            if public_url is not None:
                conn.execute(
                    "INSERT INTO platform_settings (id, public_url) VALUES (1, ?) "
                    "ON CONFLICT(id) DO UPDATE SET public_url=excluded.public_url",
                    (public_url,),
                )
            conn.commit()
    finally:
        conn.close()
    return db_path


def test_the_stored_value_wins_over_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://env.example")
    get_settings.cache_clear()
    _write_system_db(tmp_path, "https://stored.example")

    assert ps.platform_public_url() == "https://stored.example"


def test_the_environment_wins_when_nothing_is_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://env.example")
    get_settings.cache_clear()
    # platform_settings exists but holds no row - nothing has been saved through the
    # settings door yet, distinct from the "database does not exist" shape below.
    _write_system_db(tmp_path, public_url=None)

    assert ps.platform_public_url() == "https://env.example"


def test_a_blank_stored_value_does_not_shadow_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://env.example")
    get_settings.cache_clear()
    _write_system_db(tmp_path, "")

    assert ps.platform_public_url() == "https://env.example"


def test_a_missing_database_is_not_cached(tmp_path, monkeypatch):
    """The database appearing after a first call must be visible on the next one."""
    monkeypatch.setenv("PUBLIC_URL", "https://env.example")
    get_settings.cache_clear()

    assert ps.platform_public_url() == "https://env.example"

    _write_system_db(tmp_path, "https://stored.example")

    assert ps.platform_public_url() == "https://stored.example"


def test_a_read_failure_is_not_cached(tmp_path, monkeypatch):
    """system.db exists but predates this change (no platform_settings table): the read
    raises, falls back to the environment, and does not poison the cache - a stored value
    written afterwards must still be seen.
    """
    monkeypatch.setenv("PUBLIC_URL", "https://env.example")
    get_settings.cache_clear()
    _write_system_db(tmp_path, "unused", with_table=False)

    assert ps.platform_public_url() == "https://env.example"

    _write_system_db(tmp_path, "https://stored.example")

    assert ps.platform_public_url() == "https://stored.example"


def test_a_successful_read_is_cached(tmp_path, monkeypatch):
    """Once a stored value has been read successfully, a later change to the database is
    not seen until forget_platform_settings() is called.
    """
    monkeypatch.setenv("PUBLIC_URL", "https://env.example")
    get_settings.cache_clear()
    _write_system_db(tmp_path, "https://stored.example")

    assert ps.platform_public_url() == "https://stored.example"

    _write_system_db(tmp_path, "https://changed.example")

    assert ps.platform_public_url() == "https://stored.example"

    ps.forget_platform_settings()

    assert ps.platform_public_url() == "https://changed.example"


def test_forget_platform_settings_clears_the_cache(tmp_path, monkeypatch):
    """forget() must actually invalidate a populated cache - not merely be called while
    there is nothing cached to invalidate.

    An earlier version of this test called platform_public_url() once against a database
    that did not exist yet (the uncached "file absent" branch), so its own forget() call
    cleared a cache that was already empty - a no-op forget_platform_settings() still
    passed it when run alone. Reachable only because CLAUDE.md's "one layer away from
    where it holds" failure mode has a mirror image on a module-level cache: the test
    read as complete but never put anything in the cache for forget() to remove.

    This version establishes the state it claims to invalidate before ever calling
    forget(): populate the cache from a real stored value, change what is stored
    underneath, and confirm the stale cached value is still served - proving the cache is
    actually holding something - before forget() and the fresh read that follows. It
    differs from test_a_successful_read_is_cached in what shows up after the
    invalidation: here the row underneath is cleared to blank, so the fresh read after
    forget() falls all the way through the stored value to the environment, rather than
    to a second stored value.
    """
    monkeypatch.setenv("PUBLIC_URL", "https://env.example")
    get_settings.cache_clear()
    _write_system_db(tmp_path, "https://stored.example")

    assert ps.platform_public_url() == "https://stored.example"  # populates the cache

    _write_system_db(tmp_path, "")  # blank the row underneath, without forgetting yet

    assert ps.platform_public_url() == "https://stored.example"  # still the stale cache

    ps.forget_platform_settings()

    assert ps.platform_public_url() == "https://env.example"  # blank row falls to env
