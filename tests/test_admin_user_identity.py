"""Who an account belongs to, read through the lens of one project.

`users` holds no name. The name lives on `stakeholders`, per project, reached through
`project_memberships.stakeholder_id` - and per project is the model rather than an
inconvenience: sp37 says a stakeholder is a person *on an engagement*. So "what is this
account called" has no answer and "what is this account called on this project" has exactly
one, and `GET /auth/users?project=<slug>` asks only the second.

Everything here asserts what the endpoint *sends*. The lens, the subset rule, and the scoping
are all server-side; a rendered test of any of them would sit a layer away from all three.
"""
import pathlib

import pytest
from httpx import ASGITransport, AsyncClient

from api.auth import create_access_token
from api.database import (
    get_connection,
    get_system_connection,
    insert_org_membership,
    insert_organisation,
    insert_project,
    insert_project_membership,
    insert_project_registry,
    insert_stakeholder,
    insert_user,
    link_membership,
)
from api.main import app

SECRET = "test-secret"


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def sysadmin() -> str:
    return create_access_token("admin", "sysadmin", SECRET)


def org_admin(org_id: int) -> str:
    return create_access_token("orgadmin", "org_admin", SECRET, org_id=org_id)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """A DATABASE_DIR of this test's own, cleared on both sides.

    CLAUDE.md's standing trap: the shared /tmp/agentpool_test persists between runs, so a
    test that writes fixed rows into it passes once and fails for ever after. Everything here
    writes fixed usernames and slugs, so it gets its own directory.
    """
    from api.config import get_settings

    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


async def _make_project(slug: str) -> None:
    async with get_connection(slug) as conn:
        await insert_project(conn, slug=slug, llm_mode="standard", sector="", config_json="{}")


async def _add_person(slug: str, *, name: str, entity: str = "") -> int:
    async with get_connection(slug) as conn:
        cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (slug,))
        project_id = (await cur.fetchone())[0]
        return await insert_stakeholder(conn, project_id=project_id, name=name, entity=entity)


async def _add_login(username: str, *, role: str = "reviewer", org_id: int | None = None) -> int:
    async with get_system_connection() as conn:
        await insert_user(conn, username=username, email=username, role=role, hashed_pw="x")
        cur = await conn.execute("SELECT id FROM users WHERE username=?", (username,))
        user_id = (await cur.fetchone())[0]
        if org_id:
            await insert_org_membership(conn, user_id=user_id, org_id=org_id, role="member")
    return user_id


async def _link(user_id: int, slug: str, stakeholder_id: int) -> None:
    async with get_system_connection() as conn:
        await link_membership(
            conn, user_id=user_id, project_slug=slug, stakeholder_id=stakeholder_id
        )


async def _register_org(org_slug: str, *project_slugs: str) -> int:
    async with get_system_connection() as conn:
        org_id = await insert_organisation(conn, slug=org_slug, name=org_slug.title())
        for slug in project_slugs:
            await insert_project_registry(conn, slug=slug, org_id=org_id, display_name=slug)
    return org_id


async def _get_users(token: str, project: str | None = None):
    # `if project is not None`, not `if project`. The truthiness form silently drops
    # `project=""` and the empty-string test below would then assert nothing at all - it
    # passed identically with the normalisation removed until this was fixed.
    params = {"project": project} if project is not None else None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/auth/users", headers=auth(token), params=params)


async def _list(token: str, project: str | None = None) -> list[dict]:
    resp = await _get_users(token, project)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _row(users: list[dict], username: str) -> dict:
    matches = [u for u in users if u["username"] == username]
    assert len(matches) == 1, f"{username} appears {len(matches)} times in {users}"
    return matches[0]


def _usernames(users: list[dict]) -> set[str]:
    return {u["username"] for u in users}


# ── The lens ──────────────────────────────────────────────────────────────────

async def _two_engagements() -> int:
    """One login, on two projects, under a different name and entity on each."""
    await _make_project("alpha")
    await _make_project("beta")
    alpha = await _add_person("alpha", name="Jane Smith", entity="Group Finance")
    beta = await _add_person("beta", name="J. Smith", entity="Retail Bank")
    user_id = await _add_login("jane@example.com")
    await _link(user_id, "alpha", alpha)
    await _link(user_id, "beta", beta)
    return user_id


@pytest.mark.asyncio
async def test_the_same_account_is_named_differently_under_each_project(isolated_db):
    """The whole point of the lens. There is no "which of these two is authoritative" here
    because the question was never asked: each request names the project it is asking about,
    and each answer is that project's own stakeholder row."""
    await _two_engagements()

    on_alpha = _row(await _list(sysadmin(), project="alpha"), "jane@example.com")
    on_beta = _row(await _list(sysadmin(), project="beta"), "jane@example.com")

    assert on_alpha["person"] == {"name": "Jane Smith", "entity": "Group Finance"}
    assert on_beta["person"] == {"name": "J. Smith", "entity": "Retail Bank"}


@pytest.mark.asyncio
async def test_selecting_a_project_lists_that_projects_members_and_no_one_else(isolated_db):
    await _make_project("alpha")
    await _make_project("beta")
    alpha = await _add_person("alpha", name="Jane Smith")
    beta = await _add_person("beta", name="Ruth Kelly")
    jane = await _add_login("jane@example.com")
    ruth = await _add_login("ruth@example.com")
    await _add_login("neither@example.com")
    await _link(jane, "alpha", alpha)
    await _link(ruth, "beta", beta)

    on_alpha = _usernames(await _list(sysadmin(), project="alpha"))

    assert "jane@example.com" in on_alpha
    assert "ruth@example.com" not in on_alpha
    assert "neither@example.com" not in on_alpha


@pytest.mark.asyncio
async def test_an_entity_recorded_without_a_name_still_travels(isolated_db):
    await _make_project("alpha")
    stakeholder = await _add_person("alpha", name="Jane Smith", entity="")
    jane = await _add_login("jane@example.com")
    await _link(jane, "alpha", stakeholder)

    person = _row(await _list(sysadmin(), project="alpha"), "jane@example.com")["person"]

    assert person == {"name": "Jane Smith", "entity": None}


@pytest.mark.asyncio
async def test_an_access_grant_with_no_person_record_is_listed_with_no_name(isolated_db):
    """`insert_project_membership` - the /admin access grant - writes a NULL stakeholder_id.
    The account is genuinely on the project, so it belongs in the list; it simply has no
    person behind it, and `person: null` is the truthful answer rather than a blank name or a
    dropped row."""
    await _make_project("alpha")
    granted = await _add_login("granted@example.com")
    async with get_system_connection() as conn:
        await insert_project_membership(conn, user_id=granted, project_slug="alpha")

    row = _row(await _list(sysadmin(), project="alpha"), "granted@example.com")

    assert row["person"] is None


@pytest.mark.asyncio
async def test_a_membership_pointing_at_a_deleted_stakeholder_row_reads_as_absent(isolated_db):
    await _make_project("alpha")
    stakeholder = await _add_person("alpha", name="Jane Smith")
    jane = await _add_login("jane@example.com")
    await _link(jane, "alpha", stakeholder)
    async with get_connection("alpha") as conn:
        await conn.execute("DELETE FROM stakeholders WHERE id=?", (stakeholder,))
        await conn.commit()

    assert _row(await _list(sysadmin(), project="alpha"), "jane@example.com")["person"] is None


@pytest.mark.asyncio
async def test_selecting_a_project_whose_database_has_gone_creates_no_file(isolated_db):
    """`get_connection` creates the file it is handed. A slug with no database must not leave
    an empty one behind on every load of the user list."""
    jane = await _add_login("jane@example.com")
    await _link(jane, "vanished", 3)

    row = _row(await _list(sysadmin(), project="vanished"), "jane@example.com")

    assert row["person"] is None
    assert not (pathlib.Path(isolated_db) / "vanished.db").exists()


# ── The unscoped default ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_unscoped_list_carries_no_person_field_at_all(isolated_db):
    """No project means no lens, and no lens means no name - not a name picked from whichever
    engagement happened to sort first. The field is absent rather than null so a client cannot
    render a column that has no question behind it."""
    await _two_engagements()

    row = _row(await _list(sysadmin()), "jane@example.com")

    assert "person" not in row


@pytest.mark.asyncio
async def test_an_empty_project_parameter_is_the_unscoped_list_not_a_refusal(isolated_db):
    """`?project=` is absence, not a slug. Left unnormalised it would part company by tier -
    a sysadmin scoped to a slug nothing matches, an org_admin 403'd on the default view."""
    org_id = await _register_org("acme", "ours")
    await _add_login("jane@example.com", org_id=org_id)

    resp = await _get_users(org_admin(org_id), project="")

    assert resp.status_code == 200
    assert _usernames(resp.json()) == {"jane@example.com"}
    assert "person" not in resp.json()[0]


@pytest.mark.asyncio
async def test_the_unscoped_list_still_shows_every_account(isolated_db):
    """It stays the default because it is the only view that can list an account holding no
    membership anywhere - the built-in administrator, and anything created directly through
    /admin - which is an account this screen can still delete and reset."""
    await _make_project("alpha")
    stakeholder = await _add_person("alpha", name="Jane Smith")
    jane = await _add_login("jane@example.com")
    await _link(jane, "alpha", stakeholder)
    await _add_login("nobody@example.com")

    assert _usernames(await _list(sysadmin())) == {"jane@example.com", "nobody@example.com"}


# ── Sysadmin visibility ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_sysadmin_still_sees_sysadmin_accounts_under_any_project(isolated_db):
    """A sysadmin holds no membership on most projects, so without this a platform
    administrator would select a project and watch their own account disappear."""
    await _make_project("alpha")
    stakeholder = await _add_person("alpha", name="Jane Smith")
    jane = await _add_login("jane@example.com")
    await _link(jane, "alpha", stakeholder)
    await _add_login("platform@example.com", role="sysadmin")

    listed = await _list(sysadmin(), project="alpha")

    assert _usernames(listed) == {"jane@example.com", "platform@example.com"}
    assert _row(listed, "platform@example.com")["person"] is None, (
        "kept for reachability, not claimed to be on the project - so no name is invented"
    )


@pytest.mark.asyncio
async def test_an_org_admin_is_shown_no_sysadmin_the_unscoped_list_would_not_show(isolated_db):
    """The account-existence rule, on the one clause that could have breached it.

    `fetch_users_by_org` reveals a sysadmin to an org_admin only when that sysadmin holds a
    membership of their organisation. Keeping sysadmins regardless of project membership for
    *every* caller would have started confirming the existence of platform accounts an
    org_admin has no way to learn about - so the clause is a sysadmin-caller clause.
    """
    await _make_project("ours")
    stakeholder = await _add_person("ours", name="Jane Smith")
    org_id = await _register_org("acme", "ours")
    jane = await _add_login("jane@example.com", org_id=org_id)
    await _link(jane, "ours", stakeholder)
    await _add_login("platform@example.com", role="sysadmin")

    token = org_admin(org_id)
    unscoped = _usernames(await _list(token))
    scoped = _usernames(await _list(token, project="ours"))

    assert "platform@example.com" not in unscoped, "the pre-existing answer, unchanged"
    assert "platform@example.com" not in scoped
    assert scoped == {"jane@example.com"}


@pytest.mark.asyncio
async def test_the_sysadmin_clause_does_not_fire_for_an_org_admin_caller(isolated_db):
    """The previous test cannot witness the sysadmin-caller clause, and this one can.

    There, the sysadmin account holds no membership of the caller's organisation, so
    `fetch_users_by_org` never returns it and the subset rule alone keeps it out - the clause
    could be widened to every caller and nothing would change. Here the sysadmin *is* in the
    caller's organisation, so it is in the unscoped list, and whether it survives selecting a
    project it has no membership on is decided by the clause and by nothing else.

    Worth being plain about which guarantee is which: the subset rule is what makes the
    account-existence requirement hold, and it holds whatever this clause says. The clause is
    the cautious reading on top - a sysadmin is kept visible so a platform administrator does
    not lose their own account, and an org_admin's view is left exactly as it was.
    """
    await _make_project("ours")
    stakeholder = await _add_person("ours", name="Jane Smith")
    org_id = await _register_org("acme", "ours")
    jane = await _add_login("jane@example.com", org_id=org_id)
    await _link(jane, "ours", stakeholder)
    await _add_login("platform@example.com", role="sysadmin", org_id=org_id)

    token = org_admin(org_id)

    assert "platform@example.com" in _usernames(await _list(token)), (
        "in this fixture the org_admin can already see the sysadmin account unscoped, which"
        " is what leaves the clause - and nothing else - to decide the scoped answer"
    )
    assert _usernames(await _list(token, project="ours")) == {"jane@example.com"}


# ── Scoping: the lens must not widen what an org_admin can see ────────────────

@pytest.mark.asyncio
async def test_the_scoped_list_is_never_wider_than_the_unscoped_one(isolated_db):
    """The subset rule, on the population that makes it matter: a client-side login invited on
    to the caller's own project, holding no membership of the caller's organisation.

    `fetch_users_by_org` does not show that account today, and selecting the project must not
    start showing it - the scoped list is built by filtering the caller's own answer, not by
    querying `project_memberships` outwards, so an account the caller cannot see cannot arrive
    through a membership.
    """
    await _make_project("ours")
    jane_row = await _add_person("ours", name="Jane Smith")
    client_row = await _add_person("ours", name="Client Contact")
    org_id = await _register_org("acme", "ours")
    jane = await _add_login("jane@example.com", org_id=org_id)
    outsider = await _add_login("contact@client.com")
    await _link(jane, "ours", jane_row)
    await _link(outsider, "ours", client_row)

    token = org_admin(org_id)
    unscoped = _usernames(await _list(token))
    scoped = _usernames(await _list(token, project="ours"))

    assert scoped <= unscoped
    assert "contact@client.com" not in scoped
    # And the same project read by the platform tier does show them, so the assertion above
    # is not merely observing that the fixture never linked anybody.
    assert "contact@client.com" in _usernames(await _list(sysadmin(), project="ours"))


@pytest.mark.asyncio
async def test_an_org_admin_is_refused_a_project_their_organisation_does_not_own(isolated_db):
    """Refused, not silently emptied. A 403 is the same answer `check_project_access` gives
    everywhere else, which is the point - the selector's options come from `GET /auth/projects`
    and this door reads the same `project_registry`, so there is one answer to "may this
    caller see this project" rather than two that can drift apart."""
    await _make_project("theirs")
    stakeholder = await _add_person("theirs", name="Ruth Kelly")
    ours_org = await _register_org("acme", "ours")
    theirs_org = await _register_org("rival", "theirs")
    ruth = await _add_login("ruth@example.com", org_id=theirs_org)
    await _link(ruth, "theirs", stakeholder)

    resp = await _get_users(org_admin(ours_org), project="theirs")

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_the_selector_offers_an_org_admin_only_their_own_organisations_projects(isolated_db):
    """The options and the door must agree. `GET /auth/projects` is what fills the selector."""
    ours_org = await _register_org("acme", "ours")
    await _register_org("rival", "theirs")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/auth/projects", headers=auth(org_admin(ours_org)))

    assert resp.status_code == 200
    assert {p["slug"] for p in resp.json()} == {"ours"}


@pytest.mark.asyncio
async def test_a_sysadmin_may_select_any_project(isolated_db):
    await _make_project("theirs")
    stakeholder = await _add_person("theirs", name="Ruth Kelly")
    theirs_org = await _register_org("rival", "theirs")
    ruth = await _add_login("ruth@example.com", org_id=theirs_org)
    await _link(ruth, "theirs", stakeholder)

    row = _row(await _list(sysadmin(), project="theirs"), "ruth@example.com")

    assert row["person"] == {"name": "Ruth Kelly", "entity": None}
