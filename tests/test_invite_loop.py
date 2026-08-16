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
    result = await accept_token(raw, "correct horse battery staple")
    assert result is not None
    user, issue_session = result
    assert user["username"] == email
    # role is load-bearing: check_project_access's membership branch only fires for
    # role=="reviewer" - any other value would deny every project-scoped request outright,
    # and nothing else in this file would notice.
    assert user["role"] == "reviewer"
    assert issue_session, "a brand-new login must be allowed to sign in immediately"

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
    result = await accept_token(reset, "new password")
    assert result is not None
    _user, issue_session = result
    assert issue_session, "a reset must always be allowed to sign in - it is how the person recovers access"

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
        result = await accept_token(refreshed_a, "pw")
        assert result is not None
        user, issue_session = result
        assert issue_session, "the first acceptance for this email is a brand-new login"
        async with get_system_connection() as conn:
            cur = await conn.execute(
                "SELECT project_slug, stakeholder_id FROM project_memberships WHERE user_id=?"
                " ORDER BY project_slug", (user["id"],))
            assert [tuple(r) for r in await cur.fetchall()] == [(slug_a, sid_a)]
        result2 = await accept_token(raw_b, "pw")
        assert result2 is not None
        user2, issue_session2 = result2
        assert user2["id"] == user["id"]
        assert not issue_session2, (
            "the second invite redeems against an email that already has a login - "
            "granting the membership must not also mint a session"
        )
        async with get_system_connection() as conn:
            cur = await conn.execute(
                "SELECT project_slug, stakeholder_id FROM project_memberships WHERE user_id=?"
                " ORDER BY project_slug", (user["id"],))
            assert [tuple(r) for r in await cur.fetchall()] == [(slug_a, sid_a), (slug_b, sid_b)]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_second_invite_does_not_overwrite_the_existing_login_password(tmp_path, monkeypatch):
    """CRITICAL: an invite must never change an existing account's password.

    _has_linked_login is scoped per project by design, so the same email can legitimately be
    invited onto a second engagement while it already holds a login from a first one - this
    file's own test_inviting_the_same_person_to_a_second_project_keeps_both_live proves that
    is intended. Before this fix, redeeming that second invite ran the same
    `UPDATE users SET hashed_pw=?` a brand new signup does. Chained with resend-invite
    returning the raw token to the API caller (api/routers/stakeholders.py), any
    project_admin on any project - not just this one - could add an existing user's email
    (including a sysadmin's) as a stakeholder here, fetch the token, and redeem it with a
    password of their own choosing: full account takeover from three individually reasonable
    pieces. Only a reset-purpose token, which the account owner triggers themselves to their
    own address, may set a password on an existing account.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    slug_a, slug_b = "proj-a-takeover", "proj-b-takeover"
    email = "victim@example.com"
    try:
        async with get_connection(slug_a) as conn:
            await insert_project(conn, slug=slug_a, llm_mode="standard", sector="", config_json="{}")
            project_a = await fetch_project(conn, slug=slug_a)
            sid_a = await insert_stakeholder(
                conn, project_id=project_a["id"], name="Victim", email=email, is_reviewer=True)
        async with get_connection(slug_b) as conn:
            await insert_project(conn, slug=slug_b, llm_mode="standard", sector="", config_json="{}")
            project_b = await fetch_project(conn, slug=slug_b)
            sid_b = await insert_stakeholder(
                conn, project_id=project_b["id"], name="Victim", email=email, is_reviewer=True)

        # The victim accepts the first invite for real, choosing their own password.
        raw_a = await issue_invite(email=email, project_slug=slug_a, stakeholder_id=sid_a)
        victim_result = await accept_token(raw_a, "victims-real-password")
        assert victim_result is not None
        _victim, victim_issue_session = victim_result
        assert victim_issue_session, "the victim's own first acceptance is a brand-new login"

        from api.auth import verify_password
        from api.database import get_system_connection, fetch_user
        async with get_system_connection() as conn:
            before = await fetch_user(conn, username=email)
        assert verify_password("victims-real-password", before["hashed_pw"])

        # An "attacker" with admin rights only on project B adds the same email there and
        # redeems the resulting invite with a password of their own choosing.
        raw_b = await issue_invite(email=email, project_slug=slug_b, stakeholder_id=sid_b)
        attacker_result = await accept_token(raw_b, "attacker-chosen-password")
        assert attacker_result is not None
        _attacker_user, attacker_issue_session = attacker_result
        assert not attacker_issue_session, (
            "redeeming an invite for an email that already has a login must not mint a "
            "session - see the HTTP-level test below for the router enforcing this"
        )

        async with get_system_connection() as conn:
            after = await fetch_user(conn, username=email)
        # The password must be exactly what it was before the second invite was redeemed -
        # not the one the second acceptance just typed in.
        assert after["hashed_pw"] == before["hashed_pw"]
        assert verify_password("victims-real-password", after["hashed_pw"])
        assert not verify_password("attacker-chosen-password", after["hashed_pw"])

        # And the point of the second invite - a membership on project B - still lands; the
        # fix must not have traded the takeover for silently dropping the membership instead.
        async with get_system_connection() as conn:
            cur = await conn.execute(
                "SELECT project_slug, stakeholder_id FROM project_memberships WHERE user_id=?"
                " ORDER BY project_slug", (after["id"],))
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
async def test_accepting_an_invite_for_an_already_registered_email_mints_no_session(
    tmp_path, monkeypatch,
):
    """CRITICAL, round 2: closing the password overwrite (test_a_second_invite_does_not_
    overwrite_the_existing_login_password, above) was not enough on its own. accept_token
    still returned the *victim's own user row*, and the router turned every successful
    return into a session minted from that row's username/role/org_id - so redeeming an
    invite for an already-registered email handed the redeemer a live JWT *as that person,
    at their real privilege level*, silently, because the password was never touched and the
    victim has no reason to notice.

    Drives the full chain over HTTP rather than calling accept_token directly - the earlier,
    direct-call version of this test could not see the escalation, because accept_token's own
    return value (a user dict) looked identical whether or not the router was about to mint a
    session from it. The property lives one layer up, in what the router does with what
    accept_token returns.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    victim_email = "sysadmin-victim@example.com"
    try:
        from api.auth import hash_password, verify_password
        from api.database import get_system_connection, insert_user, fetch_user

        # The victim already holds a privileged login, created independently of any invite.
        async with get_system_connection() as conn:
            await insert_user(
                conn, username=victim_email, email=victim_email, role="sysadmin",
                hashed_pw=hash_password("victims-real-password"),
            )
            before = await fetch_user(conn, username=victim_email)

        # An admin on some other project adds the victim's email as a stakeholder there and
        # obtains the raw invite token exactly as POST /projects/{slug}/stakeholders/{id}/
        # resend-invite would hand it back.
        slug = "attacker-project"
        async with get_connection(slug) as conn:
            await insert_project(conn, slug=slug, llm_mode="standard", sector="", config_json="{}")
            project = await fetch_project(conn, slug=slug)
            sid = await insert_stakeholder(
                conn, project_id=project["id"], name="Victim", email=victim_email,
                is_reviewer=True,
            )
        raw = await issue_invite(email=victim_email, project_slug=slug, stakeholder_id=sid)

        from api.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/auth/accept", json={"token": raw, "password": "attacker-chosen-password"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert not body.get("access_token"), (
            "an invite redeemed against an already-registered email must not mint a "
            f"session - got a response carrying one: {body!r}"
        )

        # The other half of the contract, added in sp41: the refusal has to be explainable.
        # AcceptInvite.tsx renders `detail` verbatim - it is the only place this outcome is
        # worded - so a response that omitted it would drop the browser onto a page-local
        # fallback, and one that carried an empty string would be falsy there and put the
        # password form back on screen after a membership that really was granted. No
        # assertion on the wording itself: that is the page's to render, not to restate.
        assert body.get("already_registered") is True
        assert isinstance(body.get("detail"), str) and body["detail"].strip(), (
            f"the no-session response must explain itself - got: {body!r}"
        )

        # The password must still be exactly what it was - not the attacker's redemption
        # password, and this is the second, independent proof (alongside the direct-call
        # test above) that it was never touched.
        async with get_system_connection() as conn:
            after = await fetch_user(conn, username=victim_email)
        assert after["hashed_pw"] == before["hashed_pw"]
        assert verify_password("victims-real-password", after["hashed_pw"])
        assert not verify_password("attacker-chosen-password", after["hashed_pw"])

        # The one thing this acceptance is entitled to grant - the project B membership -
        # still lands; the fix must not have traded the takeover for silently dropping the
        # invite's entire purpose.
        async with get_system_connection() as conn:
            cur = await conn.execute(
                "SELECT project_slug, stakeholder_id FROM project_memberships WHERE user_id=?",
                (after["id"],))
            assert [tuple(r) for r in await cur.fetchall()] == [(slug, sid)]
    finally:
        get_settings.cache_clear()


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
