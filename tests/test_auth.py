# tests/test_auth.py
import pytest
from pathlib import Path
from api.config import get_settings


@pytest.fixture(autouse=True)
def clean():
    # Remove system.db before each test to avoid leftover users
    system_db = Path("/tmp/agentpool_test/system.db")
    if system_db.exists():
        system_db.unlink()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_login_returns_token(client):
    resp = await client.post("/auth/login", data={"username": "admin", "password": "test-admin-pw"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    resp = await client.post("/auth/login", data={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user(client):
    resp = await client.post("/auth/login", data={"username": "ghost", "password": "any"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_user_and_login(client):
    # Log in as admin first
    login = await client.post("/auth/login", data={"username": "admin", "password": "test-admin-pw"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create a new user
    resp = await client.post(
        "/auth/users",
        json={"username": "newuser", "password": "newpass", "role": "consultant"},
        headers=headers,
    )
    assert resp.status_code == 201

    # New user can log in
    login2 = await client.post("/auth/login", data={"username": "newuser", "password": "newpass"})
    assert login2.status_code == 200
