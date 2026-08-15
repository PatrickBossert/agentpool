# tests/test_invite_loop.py
"""One live invite per person, and the same machinery does resets.

The trigger is a role, not a person: adding a stakeholder does nothing, and setting any
flag other than is_participant on somebody with no login issues an invite. A participant
never gets one - they are reached by interview URL and token, as they always were.
"""
import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import get_connection, insert_project, insert_stakeholder, fetch_project
from api.services.invite_service import (
    issue_invite, reissue_invite, accept_token, issue_reset,
)


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
async def test_a_mismatched_stakeholder_id_is_not_linked(tmp_path, monkeypatch):
    """A token whose stakeholder_id does not name a real row on its own project must not
    be linked - not to nothing, and not to whichever row happens to sit at that id on a
    different project.

    project_memberships.stakeholder_id lives in system.db while the stakeholder lives in the
    project database, so no foreign key can catch a mismatch, and stakeholder ids restart at
    1 in every project file. A reviewer drove this on an earlier task: linking a user on
    project B with project A's stakeholder id returned B's *other* stakeholder's roles.
    accept_token is the main caller of link_membership, so it must refuse to link rather than
    trust the id blindly. The login itself is still created - the person proved they hold the
    invite - only the membership is withheld.
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
        assert user is not None, "the login is still created"

        from api.database import get_system_connection
        async with get_system_connection() as conn:
            cur = await conn.execute(
                "SELECT project_slug, stakeholder_id FROM project_memberships WHERE user_id=?",
                (user["id"],))
            assert await cur.fetchall() == [], "an unverifiable stakeholder id must not be linked"
    finally:
        get_settings.cache_clear()
