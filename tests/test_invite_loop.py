# tests/test_invite_loop.py
"""One live invite per (person, project), and the same machinery does resets.

The trigger is a role, not a person: adding a stakeholder does nothing, and setting any
flag other than is_participant on somebody with no login issues an invite. A participant
never gets one - they are reached by interview URL and token, as they always were.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from api.auth import decode_token
from api.config import get_settings
from api.database import get_connection, insert_project, insert_stakeholder, fetch_project
from api.services.invite_service import (
    issue_invite, reissue_invite, accept_token, issue_reset,
)

_JWT_SECRET = "test-secret"  # conftest.py's os.environ.setdefault - never overridden here


@pytest_asyncio.fixture
async def seeded_person(tmp_path, monkeypatch):
    """A project, a stakeholder with an email, and no login.

    Isolated from the shared /tmp/agentpool_test database per CLAUDE.md's persistent-database
    trap: the projects row goes in before the stakeholder row that references it, matching
    the PRAGMA foreign_keys = ON that get_connection sets.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    slug = "invite-project"
    email = "nadia@example.com"

    async with get_connection(slug) as conn:
        await insert_project(conn, slug=slug, llm_mode="standard", sector="", config_json="{}")
        project = await fetch_project(conn, slug=slug)
        stakeholder_id = await insert_stakeholder(
            conn, project_id=project["id"], name="Nadia", email=email, is_reviewer=True,
        )

    yield slug, stakeholder_id, email
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_accepting_an_invite_creates_the_login_and_the_link(seeded_person):
    slug, stakeholder_id, email = seeded_person
    raw = await issue_invite(email=email, project_slug=slug, stakeholder_id=stakeholder_id)
    user = await accept_token(raw, "correct horse battery staple")
    assert user is not None and user["username"] == email
    # role is load-bearing: check_project_access's membership branch only fires for
    # role=="reviewer" - any other value would deny every project-scoped request outright,
    # and nothing else in this file would notice.
    assert user["role"] == "reviewer"

    from api.database import get_system_connection
    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT project_slug, stakeholder_id FROM project_memberships"
            " WHERE user_id=?", (user["id"],))
        assert [tuple(r) for r in await cur.fetchall()] == [(slug, stakeholder_id)]


@pytest.mark.asyncio
async def test_a_token_cannot_be_used_twice(seeded_person):
    slug, stakeholder_id, email = seeded_person
    raw = await issue_invite(email=email, project_slug=slug, stakeholder_id=stakeholder_id)
    assert await accept_token(raw, "first password") is not None
    assert await accept_token(raw, "second password") is None


@pytest.mark.asyncio
async def test_reissuing_replaces_the_live_invite_rather_than_adding_a_second(seeded_person):
    """One live invite per person, and re-issuing mints a new token onto the same row.

    Tokens are stored hashed, so the original raw value cannot be recovered to resend -
    re-issue necessarily refreshes the hash and the expiry, which stops the old link
    working. That is the only implementable reading of "resend the invite", and it is
    arguably the safer one: a lost email stays dead.

    Two live invites would be the real defect - two people could each set a password while
    only one membership exists.
    """
    slug, stakeholder_id, email = seeded_person
    first = await issue_invite(email=email, project_slug=slug, stakeholder_id=stakeholder_id)
    second = await reissue_invite(email=email)
    assert second is not None and second != first

    from api.database import get_system_connection
    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM auth_tokens WHERE email=? AND used_at IS NULL", (email,))
        assert (await cur.fetchone())[0] == 1, "re-issue must replace, not add"

    # The superseded link is dead, and the fresh one works.
    assert await accept_token(first, "pw") is None
    assert await accept_token(second, "pw") is not None


@pytest.mark.asyncio
async def test_a_reset_sets_a_new_password_on_an_existing_login(seeded_person):
    slug, stakeholder_id, email = seeded_person
    raw = await issue_invite(email=email, project_slug=slug, stakeholder_id=stakeholder_id)
    await accept_token(raw, "old password")
    reset = await issue_reset(email=email)
    assert reset is not None
    user = await accept_token(reset, "new password")
    assert user is not None

    from api.auth import verify_password
    from api.database import get_system_connection, fetch_user
    async with get_system_connection() as conn:
        row = await fetch_user(conn, username=email)
    assert verify_password("new password", row["hashed_pw"])
    assert not verify_password("old password", row["hashed_pw"])


@pytest.mark.asyncio
async def test_a_reset_for_an_unknown_address_reveals_nothing(seeded_person):
    """Returning None rather than raising keeps the endpoint from confirming which
    addresses have accounts."""
    assert await issue_reset(email="nobody@example.com") is None


@pytest.mark.asyncio
async def test_purpose_is_enforced_on_redemption(seeded_person):
    """An invite token cannot be redeemed as a reset, or vice versa, once a caller names the
    purpose it expects - the two endpoints pass this, even though accept_token itself accepts
    either purpose when the caller (this file's other tests) omits it."""
    slug, stakeholder_id, email = seeded_person
    raw = await issue_invite(email=email, project_slug=slug, stakeholder_id=stakeholder_id)
    assert await accept_token(raw, "pw", purpose="reset") is None
    assert await accept_token(raw, "pw", purpose="invite") is not None


@pytest.mark.asyncio
async def test_inviting_the_same_person_to_a_second_project_keeps_both_live(tmp_path, monkeypatch):
    """One live invite per (person, project), not per person - a second engagement must not
    silently overwrite the first one's project_slug and stakeholder_id."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    slug_a, slug_b = "proj-a", "proj-b"
    email = "dual@example.com"
    try:
        async with get_connection(slug_a) as conn:
            await insert_project(conn, slug=slug_a, llm_mode="standard", sector="", config_json="{}")
            project_a = await fetch_project(conn, slug=slug_a)
            sid_a = await insert_stakeholder(
                conn, project_id=project_a["id"], name="Dual", email=email, is_reviewer=True)
        async with get_connection(slug_b) as conn:
            await insert_project(conn, slug=slug_b, llm_mode="standard", sector="", config_json="{}")
            project_b = await fetch_project(conn, slug=slug_b)
            sid_b = await insert_stakeholder(
                conn, project_id=project_b["id"], name="Dual", email=email, is_approver=True)

        raw_a = await issue_invite(email=email, project_slug=slug_a, stakeholder_id=sid_a)
        raw_b = await issue_invite(email=email, project_slug=slug_b, stakeholder_id=sid_b)
        assert raw_a != raw_b

        from api.database import get_system_connection
        async with get_system_connection() as conn:
            cur = await conn.execute(
                "SELECT project_slug FROM auth_tokens WHERE email=? AND used_at IS NULL"
                " ORDER BY project_slug", (email,))
            assert [r[0] for r in await cur.fetchall()] == [slug_a, slug_b]

        # A bare reissue is ambiguous now that two live invites exist - it must refuse to
        # guess rather than silently pick one.
        assert await reissue_invite(email=email) is None
        refreshed_a = await reissue_invite(email=email, project_slug=slug_a)
        assert refreshed_a is not None and refreshed_a != raw_a

        # Both invites still redeem correctly, to their own project.
        user = await accept_token(refreshed_a, "pw")
        assert user is not None
        async with get_system_connection() as conn:
            cur = await conn.execute(
                "SELECT project_slug, stakeholder_id FROM project_memberships WHERE user_id=?"
                " ORDER BY project_slug", (user["id"],))
            assert [tuple(r) for r in await cur.fetchall()] == [(slug_a, sid_a)]
        user2 = await accept_token(raw_b, "pw")
        assert user2 is not None and user2["id"] == user["id"]
        async with get_system_connection() as conn:
            cur = await conn.execute(
                "SELECT project_slug, stakeholder_id FROM project_memberships WHERE user_id=?"
                " ORDER BY project_slug", (user["id"],))
            assert [tuple(r) for r in await cur.fetchall()] == [(slug_a, sid_a), (slug_b, sid_b)]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_stakeholder_id_with_no_row_on_the_project_is_not_linked(tmp_path, monkeypatch):
    """A token whose stakeholder_id does not name any row on its own project must refuse the
    whole acceptance - not create a rightless login, and not spend the token.

    project_memberships.stakeholder_id lives in system.db while the stakeholder lives in the
    project database, so no foreign key can catch a mismatch. accept_token is the main caller
    of link_membership, so it must refuse rather than trust the id blindly - and refusing
    means refusing the acceptance outright, leaving the token live so a corrected invite can
    still be redeemed.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    slug = "orphan-project"
    email = "ghost@example.com"

    async with get_connection(slug) as conn:
        await insert_project(conn, slug=slug, llm_mode="standard", sector="", config_json="{}")
        # No stakeholder inserted - id 1 names nobody on this project's own database.

    try:
        raw = await issue_invite(email=email, project_slug=slug, stakeholder_id=1)
        user = await accept_token(raw, "pw")
        assert user is None, "an unverifiable stakeholder id must refuse the whole acceptance"

        from api.database import get_system_connection, fetch_user
        async with get_system_connection() as conn:
            assert await fetch_user(conn, username=email) is None, "no login must be created"
            cur = await conn.execute(
                "SELECT used_at FROM auth_tokens WHERE email=?", (email,))
            row = await cur.fetchone()
            assert row is not None and row[0] is None, "the token must stay live for a fix"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_an_invite_naming_someone_elses_stakeholder_id_is_not_linked(tmp_path, monkeypatch):
    """Existence alone is not identity. Stakeholder ids restart at 1 in every project file, so
    project 'beta' having *a* stakeholder at id 1 is the ordinary case, not the exceptional
    one - and it is not Alice merely because her invite happens to name that id.

    Reproduces the shape a reviewer drove on an earlier task: alpha's id 1 is Alice (governor,
    project_admin); beta's id 1 is Bob (participant only). An invite issued to Alice's email
    but naming project beta with stakeholder_id=1 must not link her login to Bob's row - it
    must refuse the whole acceptance, the same as an id that resolves to nobody at all.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    slug_a, slug_b = "alpha", "beta"
    try:
        async with get_connection(slug_a) as conn:
            await insert_project(conn, slug=slug_a, llm_mode="standard", sector="", config_json="{}")
            project_a = await fetch_project(conn, slug=slug_a)
            await insert_stakeholder(
                conn, project_id=project_a["id"], name="Alice", email="alice@example.com",
                is_governor=True, is_project_admin=True,
            )

        async with get_connection(slug_b) as conn:
            await insert_project(conn, slug=slug_b, llm_mode="standard", sector="", config_json="{}")
            project_b = await fetch_project(conn, slug=slug_b)
            await insert_stakeholder(
                conn, project_id=project_b["id"], name="Bob", email="bob@example.com",
                is_participant=True,
            )

        # Both projects' first stakeholder is id 1 - separate database files, separate
        # autoincrement sequences.
        raw = await issue_invite(email="alice@example.com", project_slug=slug_b, stakeholder_id=1)
        user = await accept_token(raw, "pw")
        assert user is None, "id 1 on beta is Bob, not Alice - must not link, must not log in"

        from api.database import get_system_connection, fetch_user
        async with get_system_connection() as conn:
            assert await fetch_user(conn, username="alice@example.com") is None
    finally:
        get_settings.cache_clear()


# ── Router-level tests ──────────────────────────────────────────────────────────
#
# accept_token's own return value was tested above, but the router wraps it: it mints the
# session token (which must carry org_id the same way /auth/login does) and it pins which
# purpose each endpoint will redeem. Neither of those wrappings had ever been exercised over
# HTTP - a reviewer confirmed by dropping org_id= from _login_response and dropping both
# purpose= arguments, then running the full suite: 1439 passed, unchanged. That is "the guard
# tested, the caller that uses it not," which is the exact failure shape CLAUDE.md records
# this project shipping five times already.


@pytest.mark.asyncio
async def test_accept_over_http_omits_org_id_for_a_reviewer(seeded_person):
    slug, stakeholder_id, email = seeded_person
    raw = await issue_invite(email=email, project_slug=slug, stakeholder_id=stakeholder_id)

    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/auth/accept", json={"token": raw, "password": "correct horse"})
    assert resp.status_code == 200
    payload = decode_token(resp.json()["access_token"], _JWT_SECRET)
    assert payload.get("org_id") is None


@pytest.mark.asyncio
async def test_reset_over_http_embeds_org_id_for_an_org_admin(tmp_path, monkeypatch):
    """The router's session must match /auth/login's own issuance: an org_admin whose session
    lacks org_id reads as "no org" in check_project_access and 403s on every project until
    they log out and back in. Goes via reset rather than accept, because accept_token always
    creates new logins with role="reviewer" - an org_admin login has to already exist."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        from api.database import (
            get_system_connection, insert_organisation, insert_org_membership, insert_user,
        )
        async with get_system_connection() as conn:
            org_id = await insert_organisation(conn, slug="acme", name="Acme")
            await insert_user(conn, username="boss@example.com", email="boss@example.com",
                               role="org_admin", hashed_pw="x")
            cur = await conn.execute(
                "SELECT id FROM users WHERE username=?", ("boss@example.com",))
            uid = (await cur.fetchone())[0]
            await insert_org_membership(conn, user_id=uid, org_id=org_id, role="org_admin")

        reset_raw = await issue_reset(email="boss@example.com")
        assert reset_raw is not None

        from api.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/auth/reset", json={"token": reset_raw, "password": "new-pw"})
        assert resp.status_code == 200
        payload = decode_token(resp.json()["access_token"], _JWT_SECRET)
        assert payload.get("org_id") == org_id
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_reset_token_is_refused_at_accept_and_still_redeemable_at_reset(seeded_person):
    """purpose is enforced by the router, not just supported by accept_token - this exercises
    the caller that actually supplies purpose=, which is the half nothing tested before."""
    slug, stakeholder_id, email = seeded_person
    raw = await issue_invite(email=email, project_slug=slug, stakeholder_id=stakeholder_id)
    assert await accept_token(raw, "first password") is not None  # create the login
    reset_raw = await issue_reset(email=email)
    assert reset_raw is not None

    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        refused = await ac.post("/auth/accept", json={"token": reset_raw, "password": "x"})
        assert refused.status_code == 400

        redeemed = await ac.post("/auth/reset", json={"token": reset_raw, "password": "y"})
        assert redeemed.status_code == 200


@pytest.mark.asyncio
async def test_a_reset_for_an_unknown_address_persists_no_row(seeded_person):
    """issue_reset does the same DB work for a known and an unknown address to keep the
    timing flat, but only a known address may persist a row - otherwise an unauthenticated
    caller could spray addresses and grow auth_tokens forever for free."""
    assert await issue_reset(email="sprayed@example.com") is None

    from api.database import get_system_connection
    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM auth_tokens WHERE email=?", ("sprayed@example.com",))
        assert (await cur.fetchone())[0] == 0
