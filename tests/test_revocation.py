"""Clearing every non-participant flag revokes access - and so does deleting the person.

The design says exactly that. Nothing implemented it: caller_roles was right (no flags,
no roles) while check_project_access, which asks project_memberships and applies no role
test whatever, kept answering yes. The person kept full read of the engagement, and
deleting the stakeholder row outright left a membership pointing at an id that no longer
existed - a dangling stakeholder_id with a live login attached.

Every assertion below is a request driven as that person, not a look at the tables. A
table-level test ("the row is gone") passes against an implementation that deletes the
wrong row, or the right row on the wrong project, or that deletes it while some other
door still lets the caller in. The question is whether they can still get at the
engagement, so the test asks the engagement.
"""
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.auth import create_access_token
from api.config import get_settings
from api.database import (
    fetch_project,
    fetch_user,
    get_connection,
    get_system_connection,
    insert_project_membership,
    insert_stakeholder,
    insert_user,
    link_membership,
)

SLUG = "revocation-test"
OTHER_SLUG = "revocation-test-other"

PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["requirements"],
    "review_gates": True,
    "slack_channel": "",
}
OTHER_PROJECT = {**PROJECT, "client_slug": OTHER_SLUG}

USERNAME = "revocation-reviewer@example.com"


async def _as_them() -> AsyncClient:
    """A client carrying the session this person would hold after accepting their invite -
    role="reviewer", which is what invite_service mints, and the only login role
    check_project_access will even attempt a membership lookup for."""
    from api.main import app

    token = create_access_token(USERNAME, "reviewer", "test-secret")
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest_asyncio.fixture
async def invited(client):
    """One project, one person holding is_reviewer, one login linked to their row.

    Built through insert_user + link_membership rather than through the invite flow: the
    accepted-invite end state is what is under test, and reaching it through /auth/accept
    would put the invite loop's own correctness between the fixture and the assertion.
    """
    settings = get_settings()
    for slug in (SLUG, OTHER_SLUG):
        (Path(settings.database_dir) / f"{slug}.db").unlink(missing_ok=True)

    await client.post("/projects", json=PROJECT)

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        stakeholder_id = await insert_stakeholder(
            conn, project_id=project["id"], name="Rae", email=USERNAME,
            is_reviewer=True, is_participant=True,
        )

    async with get_system_connection() as sys_conn:
        await insert_user(
            sys_conn, username=USERNAME, email=USERNAME, role="reviewer", hashed_pw="x"
        )
        user = await fetch_user(sys_conn, username=USERNAME)
        await link_membership(
            sys_conn, user_id=user["id"], project_slug=SLUG, stakeholder_id=stakeholder_id
        )

    async with await _as_them() as them:
        yield {"them": them, "stakeholder_id": stakeholder_id, "user_id": user["id"]}

    get_settings.cache_clear()
    for slug in (SLUG, OTHER_SLUG):
        (Path(settings.database_dir) / f"{slug}.db").unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_they_can_read_the_engagement_before_anything_is_revoked(invited):
    """The control every test below leans on. Without it a revocation test passes just as
    well against a fixture that never granted access in the first place."""
    assert (await invited["them"].get(f"/projects/{SLUG}/outputs")).status_code == 200


@pytest.mark.asyncio
async def test_clearing_the_last_role_shuts_them_out(client, invited):
    """The design's sentence, driven end to end: an administrator clears is_reviewer
    through the ordinary PATCH, and the next request that person makes is refused."""
    resp = await client.patch(
        f"/projects/{SLUG}/stakeholders/{invited['stakeholder_id']}",
        json={"is_reviewer": False},
    )
    assert resp.status_code == 200

    after = await invited["them"].get(f"/projects/{SLUG}/outputs")
    assert after.status_code == 403


@pytest.mark.asyncio
async def test_clearing_one_of_two_roles_is_not_a_revocation(client, invited):
    """The other half of the rule, and the half a too-eager implementation breaks: someone
    who is still an approver has not been revoked, whatever else was cleared."""
    await client.patch(
        f"/projects/{SLUG}/stakeholders/{invited['stakeholder_id']}",
        json={"is_approver": True},
    )
    await client.patch(
        f"/projects/{SLUG}/stakeholders/{invited['stakeholder_id']}",
        json={"is_reviewer": False},
    )
    assert (await invited["them"].get(f"/projects/{SLUG}/outputs")).status_code == 200


@pytest.mark.asyncio
async def test_deleting_the_stakeholder_shuts_them_out(client, invited):
    """A deleted person record used to leave the membership behind pointing at an id that
    no longer resolved - caller_roles found nothing, check_project_access still passed."""
    resp = await client.delete(
        f"/projects/{SLUG}/stakeholders/{invited['stakeholder_id']}"
    )
    assert resp.status_code == 204

    after = await invited["them"].get(f"/projects/{SLUG}/outputs")
    assert after.status_code == 403


@pytest.mark.asyncio
async def test_a_full_replace_that_clears_the_role_revokes_too(client, invited):
    """PUT, not PATCH. Both write doors issue the invite; both must withdraw it, or which
    one the administrator happened to use decides whether the revocation took effect."""
    resp = await client.put(
        f"/projects/{SLUG}/stakeholders/{invited['stakeholder_id']}",
        json={"name": "Rae", "email": USERNAME, "is_participant": True, "is_reviewer": False},
    )
    assert resp.status_code == 200
    assert (await invited["them"].get(f"/projects/{SLUG}/outputs")).status_code == 403


@pytest.mark.asyncio
async def test_revoking_here_leaves_another_engagement_alone(client, invited):
    """The users row is global. Revoking is scoped to the membership, so a second
    engagement - and an administrator-granted membership that no stakeholder row backs -
    must both survive being revoked from this one.
    """
    await client.post("/projects", json=OTHER_PROJECT)
    async with get_connection(OTHER_SLUG) as conn:
        other = await fetch_project(conn, slug=OTHER_SLUG)
        other_stakeholder_id = await insert_stakeholder(
            conn, project_id=other["id"], name="Rae", email=USERNAME, is_reviewer=True,
        )
    async with get_system_connection() as sys_conn:
        await link_membership(
            sys_conn, user_id=invited["user_id"], project_slug=OTHER_SLUG,
            stakeholder_id=other_stakeholder_id,
        )

    await client.delete(f"/projects/{SLUG}/stakeholders/{invited['stakeholder_id']}")

    assert (await invited["them"].get(f"/projects/{SLUG}/outputs")).status_code == 403
    assert (await invited["them"].get(f"/projects/{OTHER_SLUG}/outputs")).status_code == 200

    # And the login itself is untouched - it is a global account, not this project's.
    async with get_system_connection() as sys_conn:
        assert await fetch_user(sys_conn, username=USERNAME) is not None


@pytest.mark.asyncio
async def test_an_administrator_granted_membership_is_not_swept_up(client, invited):
    """insert_project_membership (POST /admin/users/{id}/projects) records a membership
    with no stakeholder_id at all. It was never a consequence of anybody's role flags, so
    clearing those flags must not withdraw it - which is why revocation is keyed on the
    stakeholder_id link rather than on "this email, this project".
    """
    from api.database import fetch_user_project_memberships

    async with get_system_connection() as sys_conn:
        await insert_project_membership(
            sys_conn, user_id=invited["user_id"], project_slug=OTHER_SLUG
        )

    await client.delete(f"/projects/{SLUG}/stakeholders/{invited['stakeholder_id']}")

    async with get_system_connection() as sys_conn:
        remaining = await fetch_user_project_memberships(
            sys_conn, user_id=invited["user_id"]
        )
    slugs = {m["project_slug"] for m in remaining}
    assert SLUG not in slugs
    assert OTHER_SLUG in slugs
