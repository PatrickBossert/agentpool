"""`access_state` on the stakeholder read model: can this person actually get in?

Every state here is computed from real rows and read back over HTTP from
`GET /projects/{slug}/stakeholders`, not from the pure function that decides it. The
recurring failure on this project is a test that verifies a property one layer from where
it holds, and for a read model the property is what the endpoint serves - a unit test on
`access_state()` would pass identically if `list_stakeholders` never called it.

The rows are made the way each state really arises:

  has_login       a users row plus a project_memberships row, as `accept_token` writes them.
  invited         created through the API with a role, so the invite is issued by
                  `_issue_invite_if_newly_privileged` rather than planted.
  unreachable     inserted directly, because the API refuses to *create* this state (422) -
                  it exists only on rows that predate the guard or were repaired around it,
                  which is exactly the live row that motivated the feature.
  not_invited     inserted directly, for the same reason: a role granted before sp41 wired
                  the invite trigger.
  no_login_needed a participant, through the API.

system.db at /tmp/agentpool_test persists between runs (see CLAUDE.md), so every login and
token this file creates is purged on both sides of each test. A leftover users row would
make the has_login test pass on its first run and poison every other test's state
afterwards.
"""
from pathlib import Path

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import (
    fetch_project,
    get_connection,
    get_system_connection,
    insert_stakeholder,
    insert_user,
    link_membership,
)

SLUG = "stakeholder-access-state-test"
OTHER_SLUG = "stakeholder-access-state-other"

# Every address this file touches, purged from system.db before and after each test.
EMAILS = (
    "logged-in@example.com",
    "invited@example.com",
    "legacy@example.com",
    "participant@example.com",
    "elsewhere@example.com",
)


async def _purge_system_rows() -> None:
    async with get_system_connection() as conn:
        for email in EMAILS:
            cur = await conn.execute("SELECT id FROM users WHERE username=?", (email,))
            row = await cur.fetchone()
            if row is not None:
                await conn.execute("DELETE FROM project_memberships WHERE user_id=?", (row[0],))
                await conn.execute("DELETE FROM users WHERE id=?", (row[0],))
            await conn.execute("DELETE FROM auth_tokens WHERE email=?", (email,))
        await conn.commit()


@pytest_asyncio.fixture
async def project():
    settings = get_settings()
    paths = [Path(settings.database_dir) / f"{s}.db" for s in (SLUG, OTHER_SLUG)]
    for path in paths:
        path.unlink(missing_ok=True)
    await _purge_system_rows()

    for slug in (SLUG, OTHER_SLUG):
        async with get_connection(slug) as conn:
            await conn.execute("INSERT INTO projects (slug) VALUES (?)", (slug,))
            await conn.commit()

    yield SLUG

    for path in paths:
        path.unlink(missing_ok=True)
    await _purge_system_rows()
    get_settings.cache_clear()


async def _insert_row(slug: str, **columns) -> int:
    """A stakeholder written straight to the table, bypassing the router's guards.

    Only for the two states the API will not create: a role with no address (422 on
    create), and a role with an address but no invite (the shape of every grant made
    before the invite trigger existed).
    """
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        return await insert_stakeholder(conn, project_id=project["id"], **columns)


async def _states(client, slug: str) -> dict[str, str]:
    """{stakeholder name: access_state} as the endpoint serves it."""
    r = await client.get(f"/projects/{slug}/stakeholders")
    assert r.status_code == 200, r.text
    return {row["name"]: row["access_state"] for row in r.json()}


@pytest.mark.asyncio
async def test_a_login_linked_to_this_project_reads_as_has_login(client, project):
    """The state that outranks every other: the person is in."""
    sid = await _insert_row(
        project, name="Logged In", email="logged-in@example.com", is_reviewer=True
    )
    async with get_system_connection() as conn:
        await insert_user(
            conn, username="logged-in@example.com", email="logged-in@example.com",
            role="reviewer", hashed_pw="x",
        )
        user = await conn.execute(
            "SELECT id FROM users WHERE username=?", ("logged-in@example.com",)
        )
        user_id = (await user.fetchone())[0]
        await link_membership(
            conn, user_id=user_id, project_slug=project, stakeholder_id=sid
        )

    assert (await _states(client, project))["Logged In"] == "has_login"


@pytest.mark.asyncio
async def test_an_unredeemed_invite_reads_as_invited(client, project):
    """Granted through the API, so the invite is the one the write path really issued."""
    created = await client.post(
        f"/projects/{project}/stakeholders",
        json={"name": "Invited", "email": "invited@example.com", "is_reviewer": True},
    )
    assert created.status_code in (200, 201), created.text

    assert (await _states(client, project))["Invited"] == "invited"


@pytest.mark.asyncio
async def test_a_role_with_no_address_reads_as_unreachable(client, project):
    """The row the whole feature exists for: reviewer and approver, empty email, weeks of
    looking exactly like a working stakeholder.

    The 422 the API now raises on create is asserted alongside it, so this test also says
    why the row had to be inserted directly - if creating it ever becomes possible, this
    fails and somebody re-reads `_validate_deliverable_role`.
    """
    refused = await client.post(
        f"/projects/{project}/stakeholders",
        json={"name": "Nowhere", "email": "", "is_reviewer": True},
    )
    assert refused.status_code == 422, refused.text

    await _insert_row(project, name="Nowhere", email="", is_reviewer=True, is_approver=True)

    assert (await _states(client, project))["Nowhere"] == "unreachable"


@pytest.mark.asyncio
async def test_a_participant_only_row_needs_no_login(client, project):
    created = await client.post(
        f"/projects/{project}/stakeholders",
        json={"name": "Taking Part", "email": "participant@example.com",
              "is_participant": True},
    )
    assert created.status_code in (200, 201), created.text

    assert (await _states(client, project))["Taking Part"] == "no_login_needed"


@pytest.mark.asyncio
async def test_a_deliverable_role_with_neither_login_nor_invite_reads_as_not_invited(
    client, project
):
    """The fifth state, and not a tidy-up: this is every role granted before the invite
    trigger was wired, and any row whose login was later deleted. Reporting it as `invited`
    would tell an administrator a link exists to resend when the door answers 404, and
    reporting it as `unreachable` would blame an address that is perfectly good.
    """
    await _insert_row(project, name="Legacy", email="legacy@example.com", is_reviewer=True)

    assert (await _states(client, project))["Legacy"] == "not_invited"


@pytest.mark.asyncio
async def test_a_login_on_another_project_is_not_reported_as_access_to_this_one(
    client, project
):
    """Per-project linkage, not global account existence.

    The distinction is the one sp37's review protected and sp42's always-204 preserves: a
    read model that answered "this address has an account" would make any project
    administrator's stakeholder list an oracle over arbitrary addresses. Here the account
    is real, logs in, and holds a membership - on a different engagement - and this project
    must still report the row as not yet invited.
    """
    await _insert_row(
        project, name="Elsewhere", email="elsewhere@example.com", is_reviewer=True
    )
    other_sid = await _insert_row(
        OTHER_SLUG, name="Elsewhere", email="elsewhere@example.com", is_reviewer=True
    )
    async with get_system_connection() as conn:
        await insert_user(
            conn, username="elsewhere@example.com", email="elsewhere@example.com",
            role="reviewer", hashed_pw="x",
        )
        cur = await conn.execute(
            "SELECT id FROM users WHERE username=?", ("elsewhere@example.com",)
        )
        user_id = (await cur.fetchone())[0]
        await link_membership(
            conn, user_id=user_id, project_slug=OTHER_SLUG, stakeholder_id=other_sid
        )

    assert (await _states(client, project))["Elsewhere"] == "not_invited"
    # The control: the same login on the project it really belongs to.
    assert (await _states(client, OTHER_SLUG))["Elsewhere"] == "has_login"


@pytest.mark.asyncio
async def test_invited_is_exactly_the_state_the_resend_door_serves(client, project):
    """The state the UI offers the action for, and the door's own answer, driven together.

    `invited` gates the "issue an invite link" button. If the two ever disagree the button
    appears where the door 404s or 409s - the shape of defect sp44 spent a round on. So
    each state is asked of the door as well as of the read model, in one test, on rows
    created the way each state really arises.
    """
    invited = await client.post(
        f"/projects/{project}/stakeholders",
        json={"name": "Invited", "email": "invited@example.com", "is_reviewer": True},
    )
    assert invited.status_code in (200, 201), invited.text
    invited_id = invited.json()["id"]

    legacy_id = await _insert_row(
        project, name="Legacy", email="legacy@example.com", is_reviewer=True
    )

    logged_in_id = await _insert_row(
        project, name="Logged In", email="logged-in@example.com", is_reviewer=True
    )
    async with get_system_connection() as conn:
        await insert_user(
            conn, username="logged-in@example.com", email="logged-in@example.com",
            role="reviewer", hashed_pw="x",
        )
        cur = await conn.execute(
            "SELECT id FROM users WHERE username=?", ("logged-in@example.com",)
        )
        user_id = (await cur.fetchone())[0]
        await link_membership(
            conn, user_id=user_id, project_slug=project, stakeholder_id=logged_in_id
        )

    states = await _states(client, project)
    assert states == {"Invited": "invited", "Legacy": "not_invited",
                      "Logged In": "has_login"}

    served = await client.post(
        f"/projects/{project}/stakeholders/{invited_id}/resend-invite"
    )
    assert served.status_code == 200, served.text
    assert served.json()["invite_token"]

    assert (
        await client.post(f"/projects/{project}/stakeholders/{legacy_id}/resend-invite")
    ).status_code == 404
    assert (
        await client.post(f"/projects/{project}/stakeholders/{logged_in_id}/resend-invite")
    ).status_code == 409


@pytest.mark.asyncio
async def test_clearing_the_last_role_kills_the_outstanding_invite(client, project, monkeypatch):
    """Revocation withdraws the credential as well as the membership.

    Driven as the whole chain rather than as a state assertion, because the state was never
    the damage: the token is redeemable at an unauthenticated door, so "still invited" means
    "still able to get in". Every step an administrator would actually take, in order -
    grant, revoke, then the entire resend-and-accept sequence attempted against the token
    that was live a moment ago - and the assertions are on the users row and the membership,
    not on status codes, because the question is whether access comes back.

    `issue_invite` is wrapped rather than mocked so the raw token is recoverable: auth_tokens
    stores only a digest, and the resend door - the other way to obtain one - is precisely
    what must stop working here.
    """
    import api.routers.stakeholders as stakeholders_router
    from api.services.invite_service import issue_invite as _real_issue_invite

    issued: dict[str, str] = {}

    async def _capturing(*, email: str, project_slug: str, stakeholder_id: int):
        raw = await _real_issue_invite(
            email=email, project_slug=project_slug, stakeholder_id=stakeholder_id
        )
        issued[email] = raw
        return raw

    monkeypatch.setattr(stakeholders_router, "issue_invite", _capturing)

    created = await client.post(
        f"/projects/{project}/stakeholders",
        json={"name": "Invited", "email": "invited@example.com", "is_reviewer": True},
    )
    assert created.status_code in (200, 201), created.text
    sid = created.json()["id"]
    token = issued.get("invited@example.com")
    assert token, "no invite was issued - the revocation below would have nothing to cancel"
    assert (await _states(client, project))["Invited"] == "invited"

    revoked = await client.patch(
        f"/projects/{project}/stakeholders/{sid}", json={"is_reviewer": False}
    )
    assert revoked.status_code == 200, revoked.text

    # The roster no longer offers the action, because the row no longer reads as invited.
    assert (await _states(client, project))["Invited"] == "no_login_needed"

    # The door has nothing left to hand out.
    resent = await client.post(f"/projects/{project}/stakeholders/{sid}/resend-invite")
    assert resent.status_code == 404, resent.text

    # And the token that was live before the revocation is dead. Unauthenticated, as
    # /auth/accept really is.
    from httpx import ASGITransport, AsyncClient
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        redeemed = await anon.post(
            "/auth/accept", json={"token": token, "password": "handed-back"}
        )
    assert redeemed.status_code != 200, redeemed.text

    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT id FROM users WHERE username=?", ("invited@example.com",)
        )
        assert await cur.fetchone() is None, "a login was created for a revoked person"
        cur = await conn.execute(
            "SELECT 1 FROM project_memberships WHERE project_slug=?", (project,)
        )
        assert await cur.fetchone() is None, "the revoked membership came back"


@pytest.mark.asyncio
async def test_a_row_holding_no_role_never_reads_as_invited_even_with_a_token_alive(
    client, project
):
    """The guard, witnessed on its own.

    `cancel_invite` is the repair; this is what holds when the repair does not run. The
    token here is planted straight into auth_tokens - the shape a write that never reached
    the router would leave behind - so the cancellation cannot be what produces the answer.
    Without the role check preceding the invite check, this row reads `invited` and the
    roster offers to hand a revoked person their access back in one click.
    """
    await _insert_row(
        project, name="Taking Part", email="participant@example.com", is_participant=True
    )
    async with get_system_connection() as conn:
        await conn.execute(
            "INSERT INTO auth_tokens (token_hash, email, project_slug, stakeholder_id,"
            " purpose, expires_at) VALUES (?,?,?,?,'invite','2099-01-01 00:00:00')",
            ("planted-digest", "participant@example.com", project, 1),
        )
        await conn.commit()

    assert (await _states(client, project))["Taking Part"] == "no_login_needed"


@pytest.mark.asyncio
async def test_an_expired_invite_still_reads_as_invited_because_a_resend_revives_it(
    client, project
):
    """Unredeemed, not unexpired.

    `reissue_invite` selects on `used_at IS NULL` alone and rewrites the expiry, so a
    timed-out invite is precisely one a resend can revive. A read model that excluded
    expired rows would hide the action from the people who most need it - and the two
    halves are asserted together here, because the whole point of the state is what it
    predicts the door will do.
    """
    created = await client.post(
        f"/projects/{project}/stakeholders",
        json={"name": "Invited", "email": "invited@example.com", "is_reviewer": True},
    )
    assert created.status_code in (200, 201), created.text
    sid = created.json()["id"]

    async with get_system_connection() as conn:
        await conn.execute(
            "UPDATE auth_tokens SET expires_at='2020-01-01 00:00:00' WHERE email=?",
            ("invited@example.com",),
        )
        await conn.commit()

    assert (await _states(client, project))["Invited"] == "invited"
    revived = await client.post(f"/projects/{project}/stakeholders/{sid}/resend-invite")
    assert revived.status_code == 200, revived.text
