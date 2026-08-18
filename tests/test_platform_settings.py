# tests/test_platform_settings.py
"""platform_public_url()'s precedence chain: stored value, environment, and the two read
failures that must fall back without caching - and the `/admin/platform-settings` door that
writes it.

Three tests for stored-vs-environment precedence are written separately on purpose - a
resolver that answered the environment unconditionally would pass
test_the_environment_wins_when_nothing_is_stored and
test_a_blank_stored_value_does_not_shadow_the_environment together while failing the first.
"""
import sqlite3

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.auth import create_access_token
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


# ── The door: /admin/platform-settings ────────────────────────────────────────
#
# Driven over HTTP rather than by calling the service, because half of what is under test is
# the door itself - the tier it is gated on, and the status code a refusal becomes. The
# autouse fixture above already points DATABASE_DIR at this test's own tmp_path, so the app's
# own system.db is created there and no door test can see, or poison, another test's stored
# value.


def _client(role: str, **claims) -> AsyncClient:
    from api.main import app

    token = create_access_token("someone", role, "test-secret", **claims)
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest_asyncio.fixture
async def sysadmin():
    async with _client("sysadmin") as ac:
        yield ac


@pytest_asyncio.fixture
async def org_admin():
    async with _client("org_admin", org_id=1) as ac:
        yield ac


@pytest.mark.asyncio
async def test_an_org_admin_may_not_change_the_platform_url(sysadmin, org_admin):
    """The caller that matters is a real administrator one tier down, not an anonymous one.

    An unauthenticated request is refused by the FastAPI dependency before this door's own
    rule is ever consulted, so a test using one would pass against a handler gated on
    nothing at all. The same note stands against tests/test_milestone_door_authority.py,
    where "a real administrator of a *different* engagement" is the caller that can tell a
    gate from its absence.

    The org_admin here is not merely refused: the value a sysadmin stored beforehand is
    still in force afterwards, so the refusal is proved to have landed before the write
    rather than after it.
    """
    await sysadmin.patch(
        "/admin/platform-settings", json={"public_url": "https://legitimate.example"}
    )

    resp = await org_admin.patch(
        "/admin/platform-settings", json={"public_url": "https://evil.example"}
    )

    assert resp.status_code == 403
    after = await sysadmin.get("/admin/platform-settings")
    assert after.json()["public_url"] == "https://legitimate.example"


@pytest.mark.asyncio
async def test_an_org_admin_may_not_read_the_platform_settings(org_admin):
    resp = await org_admin.get("/admin/platform-settings")

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_a_sysadmin_stores_a_url_and_it_becomes_the_one_in_force(sysadmin, monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://env.example")
    get_settings.cache_clear()

    resp = await sysadmin.patch(
        "/admin/platform-settings", json={"public_url": "https://stored.example"}
    )

    assert resp.status_code == 200
    assert resp.json() == {"public_url": "https://stored.example", "source": "stored"}


@pytest.mark.asyncio
async def test_nothing_stored_reads_as_the_environment(sysadmin, monkeypatch):
    """`source` is the half a populated field cannot show: an operator looking at
    https://env.example has no way to tell a saved setting from the value the deployment
    booted with, and the two behave differently the next time .env changes."""
    monkeypatch.setenv("PUBLIC_URL", "https://env.example")
    get_settings.cache_clear()

    resp = await sysadmin.get("/admin/platform-settings")

    assert resp.status_code == 200
    assert resp.json() == {"public_url": "https://env.example", "source": "environment"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sent, expected, not_expected",
    [
        (
            "ftp://files.example",
            ps.SCHEME_REFUSAL,
            (ps.NO_HOST_REFUSAL, ps.CREDENTIALS_REFUSAL),
        ),
        (
            "app.example.com",  # no scheme at all - urlparse reads the whole thing as a path
            ps.SCHEME_REFUSAL,
            (ps.NO_HOST_REFUSAL, ps.CREDENTIALS_REFUSAL),
        ),
        (
            "https:///dashboard",
            ps.NO_HOST_REFUSAL,
            (ps.SCHEME_REFUSAL, ps.CREDENTIALS_REFUSAL),
        ),
        (
            "https://someone:hunter2@app.example.com",
            ps.CREDENTIALS_REFUSAL,
            (ps.SCHEME_REFUSAL, ps.NO_HOST_REFUSAL),
        ),
    ],
)
async def test_a_refusal_names_its_own_rule(sysadmin, sent, expected, not_expected):
    """Each refusal is asserted by the sentence the *service* owns, never by a substring
    this test supplied in the URL it sent.

    CLAUDE.md records the shape being avoided: check_write refused an undeclared key and the
    refusal message quoted the key it was refusing, so `"test_state" in write_result` could
    not fail. Asserting on the URL here would be the same test. The three constants are
    module-level in api/services/platform_settings.py for exactly this - and the
    not_expected leg is what makes the assertion distinguishing rather than merely
    non-empty, since a handler that answered one fixed sentence to everything would satisfy
    the positive half four times over.
    """
    resp = await sysadmin.patch("/admin/platform-settings", json={"public_url": sent})

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert expected in detail
    for other in not_expected:
        assert other not in detail


@pytest.mark.asyncio
async def test_a_refused_url_is_not_stored(sysadmin):
    """The refusal is a refusal to *store*, not a warning issued alongside the write."""
    await sysadmin.patch(
        "/admin/platform-settings", json={"public_url": "https://good.example"}
    )

    await sysadmin.patch("/admin/platform-settings", json={"public_url": "ftp://bad.example"})

    resp = await sysadmin.get("/admin/platform-settings")
    assert resp.json()["public_url"] == "https://good.example"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sent, stored",
    [
        ("https://app.example.com/", "https://app.example.com"),
        ("https://app.example.com///", "https://app.example.com"),
        ("  https://app.example.com/dashboard/  ", "https://app.example.com/dashboard"),
        ("https://app.example.com/?utm=x#frag", "https://app.example.com"),
    ],
)
async def test_the_stored_form_carries_no_trailing_slash(sysadmin, sent, stored):
    """Four of the five link builders already call .rstrip('/') - the same rule written
    five times because nothing enforced it once. Enforced here, once, on the way in."""
    resp = await sysadmin.patch("/admin/platform-settings", json={"public_url": sent})

    assert resp.status_code == 200
    assert resp.json()["public_url"] == stored


@pytest.mark.asyncio
async def test_a_write_is_visible_to_the_next_read_in_the_same_process(sysadmin, monkeypatch):
    """The end-to-end property forget_platform_settings() exists for.

    The middle platform_public_url() call is load-bearing and not a convenience: it populates
    the module cache from a stored value, so there is something stale for the second write to
    have to invalidate. Without it the cache would be empty when that write lands, the read
    afterwards would go to the database whatever the handler did about the cache, and a
    service that never called forget_platform_settings() would pass - which is the "one layer
    away from where it holds" shape CLAUDE.md describes, in its module-cache form. It is also
    why the first PATCH is here at all: against a tmp_path with no system.db yet,
    platform_public_url() answers from the environment and deliberately does not cache, so
    there would still be nothing to invalidate.
    """
    monkeypatch.setenv("PUBLIC_URL", "https://env.example")
    get_settings.cache_clear()

    first = await sysadmin.patch(
        "/admin/platform-settings", json={"public_url": "https://first.example"}
    )
    assert first.status_code == 200

    assert ps.platform_public_url() == "https://first.example"  # populates the cache

    second = await sysadmin.patch(
        "/admin/platform-settings", json={"public_url": "https://changed.example"}
    )
    assert second.status_code == 200

    assert ps.platform_public_url() == "https://changed.example"
