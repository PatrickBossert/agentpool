"""Authority is read from the person record, never inferred from an address.

The previous implementation lowercased the caller's account email and looked for a
stakeholder carrying the same string, behind an early `if role == "sysadmin": return True`
that did all the work in practice - granting content rights to whoever could administer
accounts. Both are gone.
"""
import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import (
    get_connection,
    get_db_path,
    get_system_connection,
    insert_project,
    insert_stakeholder,
    insert_user,
    link_membership,
    fetch_project,
)
from api.services.authority_service import caller_roles


@pytest_asyncio.fixture
async def seeded_authority(tmp_path, monkeypatch):
    """One project, one stakeholder holding reviewer/approver/participant, one user linked
    to that stakeholder, and a second user carrying is_sys_admin with no stakeholder and no
    membership at all - the pair the two central tests need.

    PRAGMA foreign_keys = ON is set by get_connection, so the projects row goes in before
    the stakeholder row that references it.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    slug = "authority-project"

    async with get_connection(slug) as conn:
        await insert_project(conn, slug=slug, llm_mode="standard", sector="", config_json="{}")
        project = await fetch_project(conn, slug=slug)
        stakeholder_id = await insert_stakeholder(
            conn,
            project_id=project["id"],
            name="Rae",
            email="rae@example.com",
            is_reviewer=True,
            is_approver=True,
            is_participant=True,
        )

    async with get_system_connection() as sys_conn:
        await insert_user(
            sys_conn, username="rae@example.com", email="rae@example.com",
            role="reviewer", hashed_pw="x",
        )
        cur = await sys_conn.execute(
            "SELECT id FROM users WHERE username=?", ("rae@example.com",)
        )
        rae_id = (await cur.fetchone())[0]
        await link_membership(
            sys_conn, user_id=rae_id, project_slug=slug, stakeholder_id=stakeholder_id
        )

        await insert_user(
            sys_conn, username="admin@example.com", email="admin@example.com",
            role="sysadmin", hashed_pw="x",
        )
        await sys_conn.execute(
            "UPDATE users SET is_sys_admin=1 WHERE username=?", ("admin@example.com",)
        )

        # A third account with no membership at all, whose *account email* happens to
        # equal the linked stakeholder's email. This is the coincidence the old
        # `_caller_matches_stakeholder_flag` traded on: it never checked membership, only
        # a string match against fetch_user(...)['email']. A real user, real email, no
        # link - the case the reinstated match in the power check must be able to catch,
        # and the walk must not.
        await insert_user(
            sys_conn, username="stranger@example.com", email="rae@example.com",
            role="reviewer", hashed_pw="x",
        )
        await sys_conn.commit()

    payload = {"sub": "rae@example.com", "role": "reviewer"}
    sys_payload = {"sub": "admin@example.com", "role": "sysadmin"}
    yield slug, payload, sys_payload
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def seeded_authority_two_projects(tmp_path, monkeypatch):
    """Two projects. The caller holds an approver stakeholder on the first and no
    membership at all on the second - so a stray flag on the wrong project would be the
    only way the second lookup could ever return anything.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    slug_a = "authority-project-a"
    slug_b = "authority-project-b"

    async with get_connection(slug_a) as conn:
        await insert_project(conn, slug=slug_a, llm_mode="standard", sector="", config_json="{}")
        project_a = await fetch_project(conn, slug=slug_a)
        stakeholder_id = await insert_stakeholder(
            conn, project_id=project_a["id"], name="Nova", email="nova@example.com",
            is_approver=True,
        )

    async with get_connection(slug_b) as conn:
        await insert_project(conn, slug=slug_b, llm_mode="standard", sector="", config_json="{}")

    async with get_system_connection() as sys_conn:
        await insert_user(
            sys_conn, username="nova@example.com", email="nova@example.com",
            role="reviewer", hashed_pw="x",
        )
        cur = await sys_conn.execute(
            "SELECT id FROM users WHERE username=?", ("nova@example.com",)
        )
        nova_id = (await cur.fetchone())[0]
        await link_membership(
            sys_conn, user_id=nova_id, project_slug=slug_a, stakeholder_id=stakeholder_id
        )

    payload = {"sub": "nova@example.com", "role": "reviewer"}
    yield slug_a, slug_b, payload
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_roles_come_from_the_linked_person(seeded_authority):
    slug, payload, _ = seeded_authority
    assert await caller_roles(slug, payload) == {"reviewer", "approver", "participant"}


@pytest.mark.asyncio
async def test_a_sys_admin_administers_but_cannot_approve(seeded_authority):
    """The distinction the whole design turns on: administration is not content authority.
    sys_admin exists so a new project - which has no stakeholders and therefore no way to
    add one - can be bootstrapped at all."""
    slug, _, sys_payload = seeded_authority
    roles = await caller_roles(slug, sys_payload)
    assert "project_admin" in roles
    assert "sys_admin" in roles
    assert "approver" not in roles, "administering accounts must not confer approval"
    assert "reviewer" not in roles
    assert "governor" not in roles


@pytest.mark.asyncio
async def test_an_unlinked_caller_has_no_roles(seeded_authority):
    """No membership means nothing - not a guess by matching their email."""
    slug, _, _ = seeded_authority
    assert await caller_roles(slug, {"sub": "stranger@example.com", "role": "reviewer"}) == set()


@pytest.mark.asyncio
async def test_a_membership_on_another_project_confers_nothing_here(seeded_authority_two_projects):
    slug_a, slug_b, payload = seeded_authority_two_projects
    assert "approver" in await caller_roles(slug_a, payload)
    assert await caller_roles(slug_b, payload) == set()


@pytest.mark.asyncio
async def test_a_membership_naming_an_unbuilt_project_creates_no_database(
        tmp_path, monkeypatch):
    """get_connection(slug) creates the project's database on first touch - mkdir, connect,
    init_db, and the full migration block. Every gated endpoint now calls caller_roles, so
    a caller naming a slug that was never created must not have that side effect: a
    get_db_path(slug).exists() guard closes it before get_connection is ever reached.

    The membership row points at a stakeholder_id on a project that has no database at
    all - the state a stale or guessed slug would leave a membership in - so the only way
    this test could pass by accident is if the guard were missing and get_connection's
    own migration happened to leave the walk with the same answer, which it would not:
    fetch_project would find no project either, so the answer is identical either way and
    only the absence of the file distinguishes a correct implementation from a wasteful one.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    slug = "never-created-project"

    async with get_system_connection() as sys_conn:
        await insert_user(
            sys_conn, username="ghost@example.com", email="ghost@example.com",
            role="reviewer", hashed_pw="x",
        )
        cur = await sys_conn.execute(
            "SELECT id FROM users WHERE username=?", ("ghost@example.com",)
        )
        ghost_id = (await cur.fetchone())[0]
        await link_membership(
            sys_conn, user_id=ghost_id, project_slug=slug, stakeholder_id=1
        )
        await sys_conn.commit()

    db_path = get_db_path(slug)
    assert not db_path.exists(), "fixture setup must not itself create the database"

    roles = await caller_roles(slug, {"sub": "ghost@example.com", "role": "reviewer"})

    assert roles == set()
    assert not db_path.exists(), "an authority check must not materialise a project database"
    get_settings.cache_clear()
