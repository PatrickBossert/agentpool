"""Clearing every non-participant flag revokes access - and so does deleting the person,
and so does handing their seat to somebody else.

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
from unittest.mock import patch

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

# A write door and a project read. Both are asserted after every revocation below, because
# they fail for different reasons: the write door is the role gate (caller_may_contribute),
# the read is membership (check_project_access). An implementation that cut one and not the
# other would look revoked from whichever half the test happened to ask.
NONEXISTENT_OUTPUT_ID = 424242

PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "review_gates": True,
    "slack_channel": "",
}
OTHER_PROJECT = {**PROJECT, "client_slug": OTHER_SLUG}

USERNAME = "revocation-reviewer@example.com"
# The person the seat is handed to. Deliberately an address no other test uses: the tests
# below drive a real /auth/accept, which creates a real users row in the shared system.db.
NEW_HOLDER = "revocation-successor@example.com"


async def _purge_test_identities() -> None:
    """Remove every system.db row these tests create, on both sides of the fixture.

    system.db lives in DATABASE_DIR, which conftest points at a fixed /tmp path that
    persists between runs - and unlike the two project files, nothing was deleting it. That
    is survivable while a test only ever inserts the same login again (insert_user answers
    False on a duplicate and link_membership upserts), and stops being survivable the moment
    a test asserts that an invite *was issued*: accepting it leaves NEW_HOLDER holding a
    membership on this slug, `_has_linked_login` reads that back on the next run, and no
    invite is issued at all. Passes once, fails ever after - the trap CLAUDE.md documents,
    reached here by a test that creates a login rather than by one that writes a fixed id.
    """
    async with get_system_connection() as conn:
        await conn.execute(
            "DELETE FROM project_memberships WHERE project_slug IN (?,?)", (SLUG, OTHER_SLUG)
        )
        await conn.execute(
            "DELETE FROM auth_tokens WHERE project_slug IN (?,?)", (SLUG, OTHER_SLUG)
        )
        await conn.execute(
            "DELETE FROM project_memberships WHERE user_id IN"
            " (SELECT id FROM users WHERE username IN (?,?))",
            (USERNAME, NEW_HOLDER),
        )
        await conn.execute("DELETE FROM users WHERE username IN (?,?)", (USERNAME, NEW_HOLDER))
        await conn.commit()


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
    await _purge_test_identities()

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

    await _purge_test_identities()
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


# ── Handing the seat to somebody else ─────────────────────────────────────────
#
# "Dougie has left, Sam has the seat now" is the most ordinary edit an administrator makes,
# and it is not a role change: the flags stay exactly as they were, so neither the invite
# trigger nor the flag-clearing revocation sees anything happen. The membership is keyed on
# stakeholder_id - correctly, so an edited email cannot orphan it - which is precisely why
# an email edit could not dislodge it, and the departed holder kept full read of the
# engagement plus every gate caller_roles answers, indefinitely and silently.
#
# Driven as a request, never as a table read, for the reason at the top of this file.


async def _write_door(them: AsyncClient):
    """POST /{slug}/review as this caller. 403 is the authority gate refusing; 422 is the
    gate having let them through and insert_review rejecting an output_id that does not
    exist. Nothing here creates a real output, because the distinction being asserted is
    403-or-not and a real output would let a passing test hide behind a 201."""
    return await them.post(
        f"/projects/{SLUG}/review",
        json={"output_id": NONEXISTENT_OUTPUT_ID, "decision": "changes_requested", "notes": "x"},
    )


@pytest.mark.asyncio
async def test_swapping_the_email_shuts_the_previous_holder_out(client, invited):
    """The PATCH an administrator actually makes. Both doors are asserted before and after,
    so the test cannot pass by way of a gate that was refusing all along."""
    them = invited["them"]
    assert (await them.get(f"/projects/{SLUG}/outputs")).status_code == 200
    assert (await _write_door(them)).status_code == 422

    resp = await client.patch(
        f"/projects/{SLUG}/stakeholders/{invited['stakeholder_id']}",
        json={"email": NEW_HOLDER},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == NEW_HOLDER

    assert (await them.get(f"/projects/{SLUG}/outputs")).status_code == 403
    assert (await _write_door(them)).status_code == 403


@pytest.mark.asyncio
async def test_a_full_replace_that_swaps_the_email_revokes_too(client, invited):
    """PUT as well as PATCH. Both write doors reach the same handover; wiring one and not
    the other would make which verb the administrator used decide whether the departed
    holder kept their access."""
    them = invited["them"]
    assert (await them.get(f"/projects/{SLUG}/outputs")).status_code == 200

    resp = await client.put(
        f"/projects/{SLUG}/stakeholders/{invited['stakeholder_id']}",
        json={"name": "Sam", "email": NEW_HOLDER, "is_participant": True, "is_reviewer": True},
    )
    assert resp.status_code == 200

    assert (await them.get(f"/projects/{SLUG}/outputs")).status_code == 403
    assert (await _write_door(them)).status_code == 403


@pytest.mark.asyncio
async def test_the_new_holder_is_invited_and_can_reach_the_engagement(client, invited):
    """The other half of the handover. Revoking without inviting hands the seat to somebody
    who cannot reach it, so the row's roles would be describing access nobody holds.

    Driven all the way through /auth/accept to a live session and a real request, rather
    than by asserting an auth_tokens row exists: a token in the table proves an invite was
    written, not that redeeming it grants anything - and the redemption path has its own
    stakeholder-email check (_stakeholder_matches_invite) which a handover has to satisfy.
    issue_invite is wrapped rather than replaced, so the real invite is issued and only its
    raw token - which is hashed in the table and unreachable otherwise - is captured.
    """
    import api.routers.stakeholders as stakeholders_router
    from api.main import app

    real_issue_invite = stakeholders_router.issue_invite
    issued: list[tuple[dict, str]] = []

    async def spy(**kwargs):
        raw = await real_issue_invite(**kwargs)
        issued.append((kwargs, raw))
        return raw

    with patch.object(stakeholders_router, "issue_invite", new=spy):
        resp = await client.patch(
            f"/projects/{SLUG}/stakeholders/{invited['stakeholder_id']}",
            json={"email": NEW_HOLDER},
        )
    assert resp.status_code == 200

    assert [kwargs["email"] for kwargs, _ in issued] == [NEW_HOLDER]
    assert issued[0][0]["project_slug"] == SLUG
    assert issued[0][0]["stakeholder_id"] == invited["stakeholder_id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        accepted = await anon.post(
            "/auth/accept", json={"token": issued[0][1], "password": "successor-pw-123"}
        )
    assert accepted.status_code == 200
    session = accepted.json()["access_token"]
    assert session, "a brand-new login must be handed a session"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {session}"},
    ) as sam:
        assert (await sam.get(f"/projects/{SLUG}/outputs")).status_code == 200
        assert (await _write_door(sam)).status_code == 422


@pytest.mark.asyncio
async def test_correcting_the_casing_of_an_address_is_not_a_handover(client, invited):
    """The other side of the rule, and the half a too-eager implementation breaks. Nobody
    has left, so nothing is revoked and nothing is invited.

    Case and whitespace are compared the way _stakeholder_matches_invite already compares
    them, rather than by a third convention: users.username is TEXT UNIQUE under SQLite's
    binary collation, so treating a casing edit as a new person would revoke a live
    membership and then invite an address whose login already holds one.
    """
    import api.routers.stakeholders as stakeholders_router

    them = invited["them"]
    with patch.object(stakeholders_router, "issue_invite") as issue:
        resp = await client.patch(
            f"/projects/{SLUG}/stakeholders/{invited['stakeholder_id']}",
            json={"email": f"  {USERNAME.upper()}  "},
        )
    assert resp.status_code == 200
    assert issue.call_count == 0

    assert (await them.get(f"/projects/{SLUG}/outputs")).status_code == 200
    assert (await _write_door(them)).status_code == 422


@pytest.mark.asyncio
async def test_a_handover_leaves_another_engagement_alone(client, invited):
    """Same scoping rule as the flag-clearing revocation: the users row is global, the
    membership is what is project-scoped, and only the membership this row backs is cut."""
    from api.database import insert_stakeholder

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

    await client.patch(
        f"/projects/{SLUG}/stakeholders/{invited['stakeholder_id']}",
        json={"email": NEW_HOLDER},
    )

    them = invited["them"]
    assert (await them.get(f"/projects/{SLUG}/outputs")).status_code == 403
    assert (await them.get(f"/projects/{OTHER_SLUG}/outputs")).status_code == 200

    async with get_system_connection() as sys_conn:
        assert await fetch_user(sys_conn, username=USERNAME) is not None
