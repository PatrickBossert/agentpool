# tests/test_admin.py
import pytest
import pathlib
from httpx import AsyncClient, ASGITransport
from api.main import app
from api.auth import create_access_token, decode_token

SECRET = "test-secret"


def sysadmin_token():
    return create_access_token("admin", "sysadmin", SECRET)


def org_admin_token(org_id: int):
    return create_access_token("orgadmin", "org_admin", SECRET, org_id=org_id)


def reviewer_token():
    return create_access_token("reviewer", "reviewer", SECRET)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "pass")
    monkeypatch.setenv("DATABASE_DIR", "/tmp/test_admin_db")
    from api.config import get_settings
    get_settings.cache_clear()
    pathlib.Path("/tmp/test_admin_db").mkdir(exist_ok=True)
    # Remove stale system.db between tests so each test starts fresh
    db = pathlib.Path("/tmp/test_admin_db/system.db")
    if db.exists():
        db.unlink()


@pytest.mark.asyncio
async def test_login_admin_gets_sysadmin_role():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/auth/login", data={"username": "admin", "password": "pass"})
    assert resp.status_code == 200
    payload = decode_token(resp.json()["access_token"], SECRET)
    assert payload["role"] == "sysadmin"


@pytest.mark.asyncio
async def test_create_and_list_org():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/auth/orgs",
            json={"slug": "acme", "name": "Acme Corp"},
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 201
        org_id = resp.json()["id"]

        resp = await client.get("/auth/orgs", headers=auth(sysadmin_token()))
        assert resp.status_code == 200
        assert any(o["slug"] == "acme" for o in resp.json())

        resp = await client.patch(
            f"/auth/orgs/{org_id}",
            json={"name": "Acme Ltd"},
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Acme Ltd"


@pytest.mark.asyncio
async def test_reviewer_cannot_create_org():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/auth/orgs",
            json={"slug": "x", "name": "X"},
            headers=auth(reviewer_token()),
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_user_and_list():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create org first
        resp = await client.post(
            "/auth/orgs", json={"slug": "org1", "name": "Org 1"},
            headers=auth(sysadmin_token()),
        )
        org_id = resp.json()["id"]

        # Create user
        resp = await client.post(
            "/auth/users",
            json={
                "username": "alice",
                "email": "alice@test.com",
                "password": "secret123",
                "role": "reviewer",
                "org_id": org_id,
            },
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 201
        assert resp.json()["username"] == "alice"
        assert "hashed_pw" not in resp.json()

        # List users
        resp = await client.get("/auth/users", headers=auth(sysadmin_token()))
        assert any(u["username"] == "alice" for u in resp.json())


@pytest.mark.asyncio
async def test_duplicate_username_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {"username": "bob", "email": "b@t.com", "password": "p", "role": "reviewer"}
        await client.post("/auth/users", json=payload, headers=auth(sysadmin_token()))
        resp = await client.post("/auth/users", json=payload, headers=auth(sysadmin_token()))
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_project_membership_grant_revoke():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/auth/users",
            json={"username": "carol", "email": "c@t.com", "password": "p", "role": "reviewer"},
            headers=auth(sysadmin_token()),
        )
        user_id = resp.json()["id"]

        resp = await client.post(
            f"/auth/users/{user_id}/projects/my-proj",
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 201

        resp = await client.get(
            f"/auth/users/{user_id}/projects",
            headers=auth(sysadmin_token()),
        )
        assert any(m["project_slug"] == "my-proj" for m in resp.json())

        resp = await client.delete(
            f"/auth/users/{user_id}/projects/my-proj",
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 204


@pytest.mark.asyncio
async def test_org_admin_cannot_create_sysadmin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create org first
        resp = await client.post(
            "/auth/orgs", json={"slug": "org2", "name": "Org 2"},
            headers=auth(sysadmin_token()),
        )
        org_id = resp.json()["id"]

        resp = await client.post(
            "/auth/users",
            json={"username": "hacker", "email": "h@t.com", "password": "p", "role": "sysadmin"},
            headers=auth(org_admin_token(org_id)),
        )
        assert resp.status_code == 409  # svc_create_user returns None for forbidden role


@pytest.mark.asyncio
async def test_register_project():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/auth/orgs", json={"slug": "org3", "name": "Org 3"},
            headers=auth(sysadmin_token()),
        )
        org_id = resp.json()["id"]

        resp = await client.post(
            "/auth/projects",
            json={"slug": "proj-a", "org_id": org_id, "display_name": "Project A"},
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 201

        resp = await client.get("/auth/projects", headers=auth(sysadmin_token()))
        assert any(r["slug"] == "proj-a" for r in resp.json())


@pytest.mark.asyncio
async def test_a_created_sysadmin_carries_the_flag_caller_roles_reads():
    """is_sys_admin had no writer. Every account made through this endpoint got
    role='sysadmin' and is_sys_admin=0, and authority_service.caller_roles reads only the
    column - so a sysadmin created here silently held no project_admin anywhere, while
    one whose row had been flagged by hand did. Two accounts, the same role string,
    different authority, and nothing on either row to say which was which.

    Asserted through caller_roles rather than by reading the column, because the column is
    only interesting for what the walk makes of it - a test on the column alone would pass
    against an implementation that stored it under a name nothing reads.
    """
    from api.services.authority_service import caller_roles

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/auth/users",
            json={
                "username": "newsys", "email": "newsys@test.com",
                "password": "secret123", "role": "sysadmin",
            },
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 201

    roles = await caller_roles("any-project", {"sub": "newsys", "role": "sysadmin"})
    assert "sys_admin" in roles
    assert "project_admin" in roles


@pytest.mark.asyncio
async def test_a_created_reviewer_does_not_carry_it():
    """The other side of "derived from the role" - without this, setting the column to 1
    unconditionally would pass the test above and hand every invited reviewer
    project_admin on every project in the system."""
    from api.services.authority_service import caller_roles

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/auth/users",
            json={
                "username": "newrev", "email": "newrev@test.com",
                "password": "secret123", "role": "reviewer",
            },
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 201

    assert await caller_roles("any-project", {"sub": "newrev", "role": "reviewer"}) == set()


@pytest.mark.asyncio
async def test_promoting_an_account_to_sysadmin_moves_the_flag_with_it():
    """The one edit that can introduce the divergence after creation. Setting the column
    only on insert would leave PATCH /auth/users/{id} minting the same mismatched pair the
    creation path used to."""
    from api.services.authority_service import caller_roles

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/auth/users",
            json={
                "username": "promoted", "email": "promoted@test.com",
                "password": "secret123", "role": "reviewer",
            },
            headers=auth(sysadmin_token()),
        )
        user_id = created.json()["id"]

        resp = await client.patch(
            f"/auth/users/{user_id}",
            json={"email": "promoted@test.com", "role": "sysadmin"},
            headers=auth(sysadmin_token()),
        )
        assert resp.status_code == 200

    assert "sys_admin" in await caller_roles(
        "any-project", {"sub": "promoted", "role": "sysadmin"}
    )
