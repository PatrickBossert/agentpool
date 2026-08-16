# tests/test_password_reset_surface.py
"""The reset surface, driven at its doors rather than at its helpers.

tests/test_invite_loop.py already covers `issue_reset` and `accept_token` directly - that a
reset token sets a hash, that an unknown address answers None and persists no row, that a
reset token is refused at /auth/accept. All of that is one layer away from the properties
this file is about, which is the failure mode CLAUDE.md documents: a reset that "sets a new
hashed_pw" is not the same claim as a reset that changes *which password gets you in*, and
`issue_reset` returning None for an unknown address is not the same claim as the endpoint
being indistinguishable between the two.

So everything here goes over HTTP, and the reset assertion is made through /auth/login.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from api.auth import create_access_token, hash_password
from api.config import get_settings
from api.database import (
    get_connection, get_system_connection, fetch_project, fetch_user,
    insert_organisation, insert_org_membership, insert_project, insert_project_registry,
    insert_stakeholder, insert_user, link_membership,
)

_JWT_SECRET = "test-secret"  # conftest.py's os.environ.setdefault - never overridden here


async def _client():
    from api.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _make_login(username: str, password: str, role: str = "reviewer",
                      email: str | None = None) -> int:
    async with get_system_connection() as conn:
        await insert_user(
            conn, username=username, email=email or username, role=role,
            hashed_pw=hash_password(password),
        )
        user = await fetch_user(conn, username=username)
    return user["id"]


async def _still_signs_in(ac, username: str, password: str) -> bool:
    resp = await ac.post("/auth/login", data={"username": username, "password": password})
    return resp.status_code == 200


@pytest_asyncio.fixture
async def isolated_db(tmp_path, monkeypatch):
    """Its own DATABASE_DIR, per CLAUDE.md's persistent-database trap.

    Every test here writes users and auth_tokens rows keyed by address, and the shared
    /tmp/agentpool_test survives between runs - a second run would find the login it was
    about to create already there.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


# ── The reset itself: which password authenticates ────────────────────────────

@pytest.mark.asyncio
async def test_a_reset_makes_the_new_password_work_and_the_old_one_stop(isolated_db):
    """The property, stated the way a person experiences it.

    Asserting a changed hash - which is what a helper-level test can see - passes just as
    happily if login still accepts the old password, or if the new one does not work at all.
    Both directions are checked, through the same door somebody signs in at.
    """
    await _make_login("rae@example.com", "the-old-password")

    async with await _client() as ac:
        before_old = await ac.post(
            "/auth/login",
            data={"username": "rae@example.com", "password": "the-old-password"},
        )
        assert before_old.status_code == 200, "the account must work before it is reset"

        from api.services.invite_service import deliver_reset
        raw = await deliver_reset(email="rae@example.com")
        assert raw is not None

        redeemed = await ac.post(
            "/auth/reset", json={"token": raw, "password": "the-brand-new-password"}
        )
        assert redeemed.status_code == 200
        assert redeemed.json()["access_token"]

        after_new = await ac.post(
            "/auth/login",
            data={"username": "rae@example.com", "password": "the-brand-new-password"},
        )
        assert after_new.status_code == 200, "the new password must authenticate"

        after_old = await ac.post(
            "/auth/login",
            data={"username": "rae@example.com", "password": "the-old-password"},
        )
        assert after_old.status_code == 401, "the old password must stop working"


@pytest.mark.asyncio
async def test_an_invite_token_cannot_be_redeemed_as_a_reset(isolated_db, tmp_path):
    """`purpose="reset"` on `/auth/reset`'s accept_token call, which nothing witnessed.

    Removing that one argument leaves the whole suite green, and the consequence is the
    takeover sp37 closed, reached through a different door: an invite for an email that
    already has a login grants a membership and refuses a session at `/auth/accept`
    (deliberately - the redeemer is not the account owner), but `/auth/reset` *always* mints
    one. Unpinned, the same token POSTed here returns a live JWT whose `sub` is the victim,
    while the victim's password still works and nothing looks wrong to them.

    tests/test_invite_loop.py:132 asserts the filter on `accept_token`, the helper. The
    endpoint is what supplies the argument, and it is the endpoint that mints the session -
    so this is asserted here, over HTTP, and the password is checked afterwards because a
    refusal that still redeemed would satisfy a status assertion.
    """
    from api.database import get_connection, insert_project, insert_stakeholder
    from api.services.invite_service import issue_invite

    slug = "invite-vs-reset"
    async with get_connection(slug) as conn:
        await insert_project(conn, slug=slug, llm_mode="standard", sector="", config_json="{}")
        project = await fetch_project(conn, slug=slug)
        stakeholder_id = await insert_stakeholder(
            conn, project_id=project["id"], name="Rae", email="rae@example.com",
            is_reviewer=True,
        )

    await _make_login("rae@example.com", "the-victims-own-password")
    raw = await issue_invite(
        email="rae@example.com", project_slug=slug, stakeholder_id=stakeholder_id
    )

    async with await _client() as ac:
        refused = await ac.post("/auth/reset", json={"token": raw, "password": "seized"})
        assert refused.status_code == 400, (
            "an invite token must not be redeemable at the reset door - it mints a session, "
            f"and this one would be the victim's: {refused.text}"
        )
        assert not refused.json().get("access_token")

        assert await _still_signs_in(ac, "rae@example.com", "the-victims-own-password")
        assert not await _still_signs_in(ac, "rae@example.com", "seized")


@pytest.mark.asyncio
async def test_a_reset_token_is_single_use_at_the_endpoint(isolated_db):
    """Redeeming twice is refused - so a link that has been forwarded, quoted in a ticket, or
    left in an inbox cannot be replayed to seize the account after the owner has used it."""
    await _make_login("rae@example.com", "old")
    from api.services.invite_service import deliver_reset
    raw = await deliver_reset(email="rae@example.com")

    async with await _client() as ac:
        first = await ac.post("/auth/reset", json={"token": raw, "password": "first-choice"})
        assert first.status_code == 200
        second = await ac.post("/auth/reset", json={"token": raw, "password": "second-choice"})
        assert second.status_code == 400

        # And the first redemption's password is the one that stands.
        ok = await ac.post(
            "/auth/login", data={"username": "rae@example.com", "password": "first-choice"}
        )
        assert ok.status_code == 200
        no = await ac.post(
            "/auth/login", data={"username": "rae@example.com", "password": "second-choice"}
        )
        assert no.status_code == 401


# ── The 204-always contract ───────────────────────────────────────────────────

_VOLATILE_HEADERS = {"date", "server"}


def _comparable(resp):
    return (
        resp.status_code,
        resp.content,
        {k.lower(): v for k, v in resp.headers.items() if k.lower() not in _VOLATILE_HEADERS},
    )


@pytest.mark.asyncio
async def test_reset_request_answers_a_known_and_an_unknown_address_identically(isolated_db):
    """The security property this door exists to hold: it must not reveal whether an address
    has an account.

    Compared as whole responses rather than status alone - status, body bytes, and every
    header that is not a clock or a build constant. A `detail` explaining that no account was
    found, an added `Content-Length` difference, or a 200-vs-204 split are all the same
    defect: an unauthenticated caller learns which addresses are real. `Date` and `Server` are
    excluded because they vary between two calls regardless of the address.
    """
    await _make_login("known@example.com", "whatever")

    async with await _client() as ac:
        known = await ac.post("/auth/reset-request", json={"email": "known@example.com"})
        unknown = await ac.post("/auth/reset-request", json={"email": "nobody@example.com"})

    assert known.status_code == 204
    assert _comparable(known) == _comparable(unknown), (
        "a caller must not be able to tell a known address from an unknown one:\n"
        f"  known:   {_comparable(known)}\n  unknown: {_comparable(unknown)}"
    )

    # The half a response comparison cannot see: only the known address may leave a row, or
    # an unauthenticated caller can spray addresses and grow auth_tokens for free.
    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT email FROM auth_tokens WHERE purpose='reset' ORDER BY email")
        assert [r[0] for r in await cur.fetchall()] == ["known@example.com"]


@pytest.mark.asyncio
async def test_reset_request_still_mints_a_usable_token_for_a_known_address(isolated_db):
    """The other side of the 204: silence must not have been implemented by doing nothing.

    A handler that never called the service at all would satisfy the indistinguishability
    test above perfectly. Nothing can read the token from this door - that is the point -
    so the account's own live token is redeemed instead, proving the request minted one.
    """
    await _make_login("rae@example.com", "the-old-password")

    async with await _client() as ac:
        resp = await ac.post("/auth/reset-request", json={"email": "rae@example.com"})
        assert resp.status_code == 204

        async with get_system_connection() as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM auth_tokens"
                " WHERE email=? AND purpose='reset' AND used_at IS NULL",
                ("rae@example.com",),
            )
            assert (await cur.fetchone())[0] == 1, "the self-service door must mint a token"


# ── The administrator door ────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org_with_people(isolated_db):
    """An organisation, a project in it, and four logins: a sysadmin, an org_admin, a plain
    reviewer, and a reviewer who is an approver on the project."""
    slug = "reset-project"
    async with get_system_connection() as conn:
        org_id = await insert_organisation(conn, slug="acme", name="Acme")
        await insert_project_registry(conn, slug=slug, org_id=org_id, display_name="Acme")

    async with get_connection(slug) as conn:
        await insert_project(conn, slug=slug, llm_mode="standard", sector="", config_json="{}")
        project = await fetch_project(conn, slug=slug)
        approver_sid = await insert_stakeholder(
            conn, project_id=project["id"], name="Ada", email="ada@example.com",
            is_reviewer=True, is_approver=True,
        )

    subject_id = await _make_login("subject@example.com", "subjects-own-password")
    admin_id = await _make_login("boss@example.com", "x", role="org_admin")
    await _make_login("plain@example.com", "x")
    approver_id = await _make_login("ada@example.com", "x")

    async with get_system_connection() as conn:
        await insert_org_membership(conn, user_id=admin_id, org_id=org_id, role="org_admin")
        await insert_org_membership(conn, user_id=subject_id, org_id=org_id, role="member")
        await link_membership(
            conn, user_id=approver_id, project_slug=slug, stakeholder_id=approver_sid
        )

    return {
        "slug": slug,
        "org_id": org_id,
        "subject_id": subject_id,
        "sysadmin": create_access_token("root", "sysadmin", _JWT_SECRET),
        "org_admin": create_access_token("boss@example.com", "org_admin", _JWT_SECRET,
                                          org_id=org_id),
        "reviewer": create_access_token("plain@example.com", "reviewer", _JWT_SECRET),
        "approver": create_access_token("ada@example.com", "reviewer", _JWT_SECRET),
    }


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["reviewer", "approver"])
async def test_the_administrator_door_refuses_below_the_platform_tier(org_with_people, who):
    """Driven over HTTP as each caller, because the gate is a dependency - a service-level
    test would never touch it.

    The approver is the case worth naming: they hold a project role that lets them approve
    an engagement's outputs, and `caller_roles` would say so. Resetting a login is account
    administration, not project content, and the reset it mints is global - so the project
    role buys nothing here, and this endpoint must not have been gated on it.
    """
    async with await _client() as ac:
        resp = await ac.post(
            f"/auth/users/{org_with_people['subject_id']}/reset-link",
            headers=_auth(org_with_people[who]),
        )
    assert resp.status_code == 403, f"{who} must not be able to mint a reset link"

    # And no token was minted on the way to the refusal.
    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM auth_tokens WHERE email=? AND purpose='reset'",
            ("subject@example.com",),
        )
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["sysadmin", "org_admin"])
async def test_the_platform_tier_gets_a_link_that_actually_resets_the_account(
    org_with_people, tier
):
    """Success, proven by redeeming what came back rather than by its shape.

    A handler that returned a well-formed but unminted string would pass any assertion about
    the response alone. The token is carried to /auth/reset and then to /auth/login, which is
    the whole point of the link: the account owner chooses a password the administrator never
    sees.
    """
    async with await _client() as ac:
        resp = await ac.post(
            f"/auth/users/{org_with_people['subject_id']}/reset-link",
            headers=_auth(org_with_people[tier]),
        )
        assert resp.status_code == 200, resp.text
        raw = resp.json()["reset_token"]
        assert raw

        # An administrator-minted token is a reset, not an invite - the routers pin purpose,
        # and this is the new door's own token going through that check. (The equivalent for
        # self-service tokens is already covered in tests/test_invite_loop.py.)
        assert (await ac.post("/auth/accept", json={"token": raw, "password": "x"})).status_code == 400

        redeemed = await ac.post(
            "/auth/reset", json={"token": raw, "password": "chosen-by-the-owner"}
        )
        assert redeemed.status_code == 200

        signed_in = await ac.post(
            "/auth/login",
            data={"username": "subject@example.com", "password": "chosen-by-the-owner"},
        )
        assert signed_in.status_code == 200
        old = await ac.post(
            "/auth/login",
            data={"username": "subject@example.com", "password": "subjects-own-password"},
        )
        assert old.status_code == 401


@pytest.mark.asyncio
async def test_an_org_admin_cannot_mint_a_reset_for_a_sysadmin(org_with_people):
    """The escalation the tier check cannot see. svc_create_user and svc_update_user both
    refuse to grant sysadmin to an org_admin; a reset link on a sysadmin account reaches the
    same place from the other end, and would be quieter - the victim's password is not
    changed until the link is redeemed."""
    root_id = await _make_login("root@example.com", "x", role="sysadmin")
    async with get_system_connection() as conn:
        await insert_org_membership(
            conn, user_id=root_id, org_id=org_with_people["org_id"], role="member"
        )

    async with await _client() as ac:
        resp = await ac.post(
            f"/auth/users/{root_id}/reset-link", headers=_auth(org_with_people["org_admin"])
        )
    assert resp.status_code == 409

    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM auth_tokens WHERE email=?", ("root@example.com",))
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_an_org_admin_cannot_reach_another_organisations_account(org_with_people):
    """svc_list_users scopes an org_admin's view to their own organisation, so without this
    the id in the URL walks round a filter applied everywhere else. Refused as 409 rather
    than 404 deliberately: "not yours" must not read as "does not exist", or enumerating ids
    tells an org_admin which accounts other organisations hold."""
    async with get_system_connection() as conn:
        other_org = await insert_organisation(conn, slug="other", name="Other")
    outsider_id = await _make_login("outsider@example.com", "x")
    async with get_system_connection() as conn:
        await insert_org_membership(
            conn, user_id=outsider_id, org_id=other_org, role="member"
        )

    async with await _client() as ac:
        refused = await ac.post(
            f"/auth/users/{outsider_id}/reset-link",
            headers=_auth(org_with_people["org_admin"]),
        )
        assert refused.status_code == 409

        # A sysadmin still can - administering across organisations is a sysadmin capability
        # throughout this router, and the guard must be a scope, not a new blanket refusal.
        allowed = await ac.post(
            f"/auth/users/{outsider_id}/reset-link",
            headers=_auth(org_with_people["sysadmin"]),
        )
        assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_the_link_is_minted_for_a_login_whose_username_is_not_its_email(isolated_db):
    """Administrator-created logins have a username and an email that need not match, and
    redemption resolves the account by username. Minting against the email would produce a
    token that resolves to nobody - rolled back, answered None, and surfaced to the operator
    as "no such user" for an account plainly in front of them."""
    user_id = await _make_login(
        "r.patel", "old-password", email="rani.patel@example.com"
    )
    token = create_access_token("root", "sysadmin", _JWT_SECRET)

    async with await _client() as ac:
        resp = await ac.post(f"/auth/users/{user_id}/reset-link", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        redeemed = await ac.post(
            "/auth/reset", json={"token": resp.json()["reset_token"], "password": "new-one"}
        )
        assert redeemed.status_code == 200

        signed_in = await ac.post(
            "/auth/login", data={"username": "r.patel", "password": "new-one"}
        )
        assert signed_in.status_code == 200


@pytest.mark.asyncio
async def test_a_missing_account_is_a_404_not_a_link(isolated_db):
    token = create_access_token("root", "sysadmin", _JWT_SECRET)
    async with await _client() as ac:
        resp = await ac.post("/auth/users/98765/reset-link", headers=_auth(token))
    assert resp.status_code == 404
