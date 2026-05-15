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


# --- New RBAC dependency tests ---

import pytest
from fastapi import HTTPException
from api.auth import (
    create_access_token, decode_token,
    require_sysadmin, require_org_admin_or_above, require_any_auth,
)


def make_payload(role: str, org_id: int | None = None) -> dict:
    token = create_access_token("alice", role, "test-secret", org_id=org_id)
    return decode_token(token, "test-secret")


def test_require_sysadmin_passes():
    payload = make_payload("sysadmin")
    assert require_sysadmin(payload) == payload


def test_require_sysadmin_rejects_org_admin():
    with pytest.raises(HTTPException) as exc:
        require_sysadmin(make_payload("org_admin"))
    assert exc.value.status_code == 403


def test_require_org_admin_or_above_passes_sysadmin():
    payload = make_payload("sysadmin")
    assert require_org_admin_or_above(payload) == payload


def test_require_org_admin_or_above_passes_org_admin():
    payload = make_payload("org_admin", org_id=1)
    assert require_org_admin_or_above(payload) == payload


def test_require_org_admin_or_above_rejects_reviewer():
    with pytest.raises(HTTPException):
        require_org_admin_or_above(make_payload("reviewer"))


def test_require_any_auth_passes_all():
    for role in ("sysadmin", "org_admin", "reviewer"):
        payload = make_payload(role)
        assert require_any_auth(payload) == payload


def test_org_id_in_token():
    payload = make_payload("org_admin", org_id=7)
    assert payload["org_id"] == 7


def test_sysadmin_no_org_id():
    payload = make_payload("sysadmin")
    assert "org_id" not in payload
