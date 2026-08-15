# tests/test_rolling_session.py
"""Thirty days, refreshed on use, so an active reviewer never logs in twice.

PAM's links are ordinary application URLs: they work while a session is live and bounce to
login when it is not. A reviewer who reads three scripts a week should never see the login
page again after the first time.

seeded_project_slug follows tests/test_my_permissions.py's fixture of the same name: the
client fixture in conftest.py is an async httpx client against the real app, so every call
here is awaited, and the db file is removed before and after rather than trusting a fresh
tmp_path - DATABASE_DIR is the process-wide /tmp/agentpool_test set in conftest.py, which
persists between runs.

Round 1 review found the roll itself trustworthy but three ways it could be trusted too much:
a refused (403/404) response still got another thirty days, a ghost or demoted account's old
token still got re-issued because the middleware copied its claims rather than checking them,
and the roll had no ceiling of its own - a token used once a month would refresh forever. All
three are covered below, alongside decoding the header rather than only checking it is truthy.
"""
from pathlib import Path

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from jose import jwt
from httpx import AsyncClient, ASGITransport

from api.auth import ABSOLUTE_SESSION_EXPIRE_DAYS, ACCESS_TOKEN_EXPIRE_HOURS, create_access_token
from api.config import get_settings
from api.database import fetch_user, get_connection, get_system_connection, insert_user, link_membership
from api.main import app

SLUG = "rolling-session-test"
_SECRET = "test-secret"  # conftest.py's os.environ.setdefault - never overridden here


@pytest_asyncio.fixture
async def seeded_project_slug():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)

    async with get_connection(SLUG) as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES (?)", (SLUG,))
        await conn.commit()

    yield SLUG

    db_path.unlink(missing_ok=True)
    get_settings.cache_clear()


async def _purge_system_login(email: str) -> None:
    """Remove any system-db login (and its memberships) for this email.

    system.db at /tmp/agentpool_test is shared and persistent, unlike seeded_project_slug's
    own per-project database - per CLAUDE.md's persistent-database trap, a test that seeds a
    users row here and does not clean it up poisons every run after the first: insert_user
    returns False on the second run because the row already exists, and a role written by a
    previous run would leak into this one silently.
    """
    async with get_system_connection() as conn:
        cur = await conn.execute("SELECT id FROM users WHERE username=?", (email,))
        row = await cur.fetchone()
        if row is None:
            return
        await conn.execute("DELETE FROM project_memberships WHERE user_id=?", (row[0],))
        await conn.execute("DELETE FROM users WHERE id=?", (row[0],))
        await conn.commit()


def test_a_token_lasts_thirty_days():
    assert ACCESS_TOKEN_EXPIRE_HOURS == 24 * 30
    secret = get_settings().jwt_secret
    payload = jwt.decode(create_access_token("ana", "reviewer", secret), secret,
                         algorithms=["HS256"])
    remaining = datetime.fromtimestamp(payload["exp"], tz=timezone.utc) - datetime.now(timezone.utc)
    assert 29 <= remaining.days <= 30


@pytest.mark.asyncio
async def test_an_authenticated_request_returns_a_refreshed_token(client, seeded_project_slug):
    """Rolling means re-issued on use, with a token that actually decodes and carries a
    materially later expiry - not merely a truthy header value. A middleware that set
    `X-Refreshed-Token: x` would satisfy a bare truthiness check while logging out the very
    next request that tried to use it (client.ts's storeRefreshedToken would store "x"
    verbatim), so this mints the request's own bearer token with a short, deliberately stale
    exp - far short of the full thirty days - and asserts the header decodes to a fresh
    thirty-day token for the same caller."""
    secret = get_settings().jwt_secret
    stale_exp = datetime.now(timezone.utc) + timedelta(hours=1)
    original_token = jwt.encode(
        {"sub": "admin", "role": "sysadmin", "iat": datetime.now(timezone.utc), "exp": stale_exp},
        secret, algorithm="HS256",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": f"Bearer {original_token}"},
    ) as ac:
        r = await ac.get(f"/projects/{seeded_project_slug}/my-permissions")
    assert r.status_code == 200
    refreshed = r.headers.get("X-Refreshed-Token")
    assert refreshed, "an authenticated response must roll the session"

    refreshed_payload = jwt.decode(refreshed, secret, algorithms=["HS256"])
    assert refreshed_payload["sub"] == "admin"
    assert refreshed_payload["role"] == "sysadmin"
    assert refreshed_payload["exp"] > stale_exp.timestamp()


@pytest.mark.asyncio
async def test_an_unauthenticated_request_gets_no_refreshed_token(seeded_project_slug):
    """No bearer token, no roll - the middleware must not manufacture a session for a caller
    who never presented one."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(f"/projects/{seeded_project_slug}/my-permissions")
    assert "X-Refreshed-Token" not in r.headers


@pytest.mark.asyncio
async def test_a_refused_request_is_not_rolled(seeded_project_slug):
    """"Authenticated" in the middleware's docstring means only "carried a decodable token" -
    a token that decodes fine but names nobody with access still gets refused by
    check_project_access, and a refusal must not be rewarded with another thirty days
    anyway. Gating on a 2xx response is what closes that.

    The account here must actually exist, with a role matching the token's - otherwise
    _current_session_claims's own existence/role check would refuse the roll on its own,
    and this test would pass identically whether or not the 2xx gate existed at all (the 404
    test above is what isolates that check; this one must isolate the gate)."""
    email = "no-membership-reviewer@example.com"
    await _purge_system_login(email)
    try:
        async with get_system_connection() as conn:
            await insert_user(
                conn, username=email, email=email, role="reviewer",
                hashed_pw="not-a-real-hash-just-a-row",
            )
        # Deliberately no link_membership call - this account exists, with the role the
        # token claims, but holds no membership on seeded_project_slug.

        secret = get_settings().jwt_secret
        token = create_access_token(email, "reviewer", secret)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as ac:
            r = await ac.get(f"/projects/{seeded_project_slug}/my-permissions")
        assert r.status_code == 403
        assert "X-Refreshed-Token" not in r.headers
    finally:
        await _purge_system_login(email)


@pytest.mark.asyncio
async def test_a_404_is_not_rolled(client):
    """Same 2xx gate, from the other common refusal shape - a decodable sysadmin token
    naming a project that does not exist."""
    r = await client.get("/projects/no-such-project-for-rolling-session-test/my-permissions")
    assert r.status_code == 404
    assert "X-Refreshed-Token" not in r.headers


@pytest.mark.asyncio
async def test_a_deleted_users_token_is_not_rolled(seeded_project_slug):
    """A user who no longer exists must not have their session extended.

    api/main.py's roll_session middleware looks the caller up fresh (_current_session_claims)
    rather than trusting the claims already on the token. Without this, a revoked account's
    token would roll forward for another thirty days on its next use, silently defeating the
    revocation - and check_project_access's sysadmin branch does not itself require the
    sub to exist, so the request below still succeeds; only the roll must be refused.
    """
    secret = get_settings().jwt_secret
    ghost_token = create_access_token("ghost-user-who-does-not-exist", "sysadmin", secret)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": f"Bearer {ghost_token}"},
    ) as ac:
        r = await ac.get(f"/projects/{seeded_project_slug}/my-permissions")
    assert r.status_code == 200
    assert "X-Refreshed-Token" not in r.headers


@pytest.mark.asyncio
async def test_a_role_change_is_not_rolled(seeded_project_slug):
    """A demoted or promoted account must re-authenticate rather than have a token minted
    under its old role quietly kept alive. The token below claims "reviewer" - which passes
    check_project_access's membership check and lets the request succeed - but the account
    now actually holds "org_admin"; _current_session_claims must catch that mismatch and
    refuse to roll even though the request itself is a 200.
    """
    email = "shifted-role@example.com"
    await _purge_system_login(email)
    try:
        async with get_system_connection() as conn:
            await insert_user(
                conn, username=email, email=email, role="org_admin",
                hashed_pw="not-a-real-hash-just-a-row",
            )
            user = await fetch_user(conn, username=email)
            await link_membership(
                conn, user_id=user["id"], project_slug=seeded_project_slug, stakeholder_id=1,
            )

        secret = get_settings().jwt_secret
        stale_token = create_access_token(email, "reviewer", secret)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            headers={"Authorization": f"Bearer {stale_token}"},
        ) as ac:
            r = await ac.get(f"/projects/{seeded_project_slug}/my-permissions")
        assert r.status_code == 200
        assert "X-Refreshed-Token" not in r.headers
    finally:
        await _purge_system_login(email)


@pytest.mark.asyncio
async def test_a_session_older_than_the_absolute_cap_is_not_rolled(seeded_project_slug):
    """The rolling exp alone has no ceiling of its own - a token used once a month would
    refresh forever. ABSOLUTE_SESSION_EXPIRE_DAYS, anchored to the token's preserved iat,
    bounds that even when the account is in good standing and the token's own exp has not
    yet passed - the belt to _current_session_claims's braces, for a token that is stolen
    rather than revoked, where there is no account state to notice."""
    secret = get_settings().jwt_secret
    now = datetime.now(timezone.utc)
    old_token = jwt.encode(
        {
            "sub": "admin",
            "role": "sysadmin",
            "iat": now - timedelta(days=ABSOLUTE_SESSION_EXPIRE_DAYS + 1),
            "exp": now + timedelta(hours=1),  # exp itself has not passed
        },
        secret, algorithm="HS256",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": f"Bearer {old_token}"},
    ) as ac:
        r = await ac.get(f"/projects/{seeded_project_slug}/my-permissions")
    assert r.status_code == 200
    assert "X-Refreshed-Token" not in r.headers


@pytest.mark.asyncio
async def test_a_roll_near_the_absolute_cap_is_clamped_to_it(seeded_project_slug):
    """The cap bounds session *lifetime*, not just how often a session may roll. A roll one
    day inside ABSOLUTE_SESSION_EXPIRE_DAYS is still a roll (the test above only covers a
    roll refused entirely, past the cap) - but api/auth.py's create_access_token must clamp
    the reissued exp to iat + ABSOLUTE_SESSION_EXPIRE_DAYS rather than handing out the full
    ordinary thirty-day window, or a roll on day eighty-nine would still mint an exp landing
    on day one-nineteen: decode_token only rejects an *expired* token, and iat is not itself
    an expiry claim, so nothing else would ever catch a session that outlived the cap by up
    to thirty days.
    """
    secret = get_settings().jwt_secret
    now = datetime.now(timezone.utc)
    old_iat = now - timedelta(days=ABSOLUTE_SESSION_EXPIRE_DAYS - 1)  # one day inside the cap
    token = jwt.encode(
        {"sub": "admin", "role": "sysadmin", "iat": old_iat, "exp": now + timedelta(hours=1)},
        secret, algorithm="HS256",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        r = await ac.get(f"/projects/{seeded_project_slug}/my-permissions")
    assert r.status_code == 200
    refreshed_payload = jwt.decode(r.headers["X-Refreshed-Token"], secret, algorithms=["HS256"])

    deadline = old_iat + timedelta(days=ABSOLUTE_SESSION_EXPIRE_DAYS)
    full_roll = now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    assert refreshed_payload["exp"] <= deadline.timestamp() + 1  # tolerate second-rounding
    assert refreshed_payload["exp"] < full_roll.timestamp(), (
        "a roll this close to the absolute cap must not still grant the full rolling window"
    )


@pytest.mark.asyncio
async def test_a_rolled_token_preserves_the_original_iat(seeded_project_slug):
    """The absolute cap above only binds if rolling does not quietly reset iat to "now" on
    every reissue - that would make the cap unreachable by construction.

    Round 1's version of this test used the shared `client` fixture's token, minted mere
    milliseconds before the request. iat is second-resolution (jose's jwt.encode truncates
    via timegm), so a freshly-recomputed iat and the preserved original one round to the
    same integer by coincidence almost every time the test runs - the assertion could not
    tell "preserved" from "silently reset to now" apart, and stayed green when the reviewer
    deleted `iat=issued_at` from api/main.py's roll_session entirely. Anchoring the original
    iat several days in the past (but still inside ABSOLUTE_SESSION_EXPIRE_DAYS, so the roll
    is not itself refused by the cap test above) removes the coincidence: a reset-to-now iat
    and the real, preserved one are then unmistakably different values.
    """
    secret = get_settings().jwt_secret
    old_iat = datetime.now(timezone.utc) - timedelta(days=5)
    token = jwt.encode(
        {
            "sub": "admin", "role": "sysadmin", "iat": old_iat,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        secret, algorithm="HS256",
    )
    original_iat = jwt.decode(token, secret, algorithms=["HS256"])["iat"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        r = await ac.get(f"/projects/{seeded_project_slug}/my-permissions")
    assert r.status_code == 200
    refreshed_payload = jwt.decode(r.headers["X-Refreshed-Token"], secret, algorithms=["HS256"])
    assert refreshed_payload["iat"] == original_iat


@pytest.mark.asyncio
async def test_a_failed_claims_lookup_does_not_break_an_already_successful_response(
    client, seeded_project_slug,
):
    """Computing the roll is a bonus on top of an already-decided, already-successful
    response - not a precondition of it. _current_session_claims does a real system-db
    lookup (and, for an org_admin, a second one inside org_id_for_session); a failure there
    must leave the response exactly as the endpoint produced it, not convert a success the
    caller already earned into a 500 purely because the extra thirty days couldn't be
    computed this time.
    """
    from unittest.mock import AsyncMock, patch
    with patch(
        "api.main._current_session_claims", new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        r = await client.get(f"/projects/{seeded_project_slug}/my-permissions")
    assert r.status_code == 200
    assert "X-Refreshed-Token" not in r.headers
