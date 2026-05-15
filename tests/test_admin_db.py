# tests/test_admin_db.py
import pytest
import pytest_asyncio
import aiosqlite
from api.database import (
    init_system_db,
    insert_organisation, fetch_all_organisations, fetch_organisation,
    update_organisation, delete_organisation,
    insert_org_membership, fetch_org_members, update_org_membership_role,
    delete_org_membership, fetch_user_org,
    insert_project_registry, fetch_project_registry, fetch_org_projects,
    fetch_all_registry, delete_project_registry,
    insert_project_membership, delete_project_membership,
    fetch_user_project_memberships, has_project_membership,
    insert_user, fetch_user_by_id, fetch_all_users, fetch_users_by_org,
    update_user, delete_user,
)


@pytest_asyncio.fixture
async def sys_conn():
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        await init_system_db(conn)
        yield conn


@pytest.mark.asyncio
async def test_org_crud(sys_conn):
    org_id = await insert_organisation(sys_conn, slug="acme", name="Acme Corp")
    assert org_id > 0
    org = await fetch_organisation(sys_conn, org_id=org_id)
    assert org["name"] == "Acme Corp"
    await update_organisation(sys_conn, org_id=org_id, name="Acme Ltd")
    org = await fetch_organisation(sys_conn, org_id=org_id)
    assert org["name"] == "Acme Ltd"
    orgs = await fetch_all_organisations(sys_conn)
    assert len(orgs) == 1
    await delete_organisation(sys_conn, org_id=org_id)
    assert await fetch_organisation(sys_conn, org_id=org_id) is None


@pytest.mark.asyncio
async def test_org_membership(sys_conn):
    org_id = await insert_organisation(sys_conn, slug="acme", name="Acme")
    ok = await insert_user(sys_conn, username="bob", email="bob@test.com", role="org_admin",
                           hashed_pw="hashed", project_slug=None)
    assert ok
    user = await fetch_user_by_id(sys_conn, user_id=1)
    await insert_org_membership(sys_conn, user_id=user["id"], org_id=org_id, role="org_admin")
    members = await fetch_org_members(sys_conn, org_id=org_id)
    assert len(members) == 1
    assert members[0]["username"] == "bob"
    user_org = await fetch_user_org(sys_conn, user_id=user["id"])
    assert user_org["org_id"] == org_id
    await update_org_membership_role(sys_conn, user_id=user["id"], org_id=org_id, role="member")
    members = await fetch_org_members(sys_conn, org_id=org_id)
    assert members[0]["role"] == "member"
    await delete_org_membership(sys_conn, user_id=user["id"], org_id=org_id)
    assert await fetch_org_members(sys_conn, org_id=org_id) == []


@pytest.mark.asyncio
async def test_project_registry(sys_conn):
    org_id = await insert_organisation(sys_conn, slug="acme", name="Acme")
    await insert_project_registry(sys_conn, slug="proj-a", org_id=org_id, display_name="Project A")
    row = await fetch_project_registry(sys_conn, slug="proj-a")
    assert row["org_id"] == org_id
    org_projs = await fetch_org_projects(sys_conn, org_id=org_id)
    assert len(org_projs) == 1
    all_reg = await fetch_all_registry(sys_conn)
    assert len(all_reg) == 1
    await delete_project_registry(sys_conn, slug="proj-a")
    assert await fetch_project_registry(sys_conn, slug="proj-a") is None


@pytest.mark.asyncio
async def test_project_membership(sys_conn):
    await insert_user(sys_conn, username="carol", email="carol@test.com", role="reviewer",
                      hashed_pw="hashed", project_slug=None)
    user = await fetch_user_by_id(sys_conn, user_id=1)
    ok = await insert_project_membership(sys_conn, user_id=user["id"], project_slug="proj-x")
    assert ok
    memberships = await fetch_user_project_memberships(sys_conn, user_id=user["id"])
    assert len(memberships) == 1
    assert await has_project_membership(sys_conn, user_id=user["id"], project_slug="proj-x")
    assert not await has_project_membership(sys_conn, user_id=user["id"], project_slug="other")
    await delete_project_membership(sys_conn, user_id=user["id"], project_slug="proj-x")
    assert not await has_project_membership(sys_conn, user_id=user["id"], project_slug="proj-x")


@pytest.mark.asyncio
async def test_user_helpers(sys_conn):
    await insert_user(sys_conn, username="alice", email="alice@test.com", role="sysadmin",
                      hashed_pw="hashed", project_slug=None)
    org_id = await insert_organisation(sys_conn, slug="acme", name="Acme")
    await insert_user(sys_conn, username="bob", email="bob@test.com", role="org_admin",
                      hashed_pw="hashed", project_slug=None)
    bob = await fetch_user_by_id(sys_conn, user_id=2)
    await insert_org_membership(sys_conn, user_id=bob["id"], org_id=org_id, role="org_admin")
    all_users = await fetch_all_users(sys_conn)
    assert len(all_users) == 2
    org_users = await fetch_users_by_org(sys_conn, org_id=org_id)
    assert len(org_users) == 1
    assert org_users[0]["username"] == "bob"
    await update_user(sys_conn, user_id=bob["id"], email="bob2@test.com", role="member")
    updated = await fetch_user_by_id(sys_conn, user_id=bob["id"])
    assert updated["email"] == "bob2@test.com"
    await delete_user(sys_conn, user_id=bob["id"])
    assert await fetch_user_by_id(sys_conn, user_id=bob["id"]) is None
