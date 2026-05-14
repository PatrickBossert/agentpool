# tests/test_templates_router.py
import json
from pathlib import Path

import pytest
import pytest_asyncio
import aiosqlite
from httpx import AsyncClient, ASGITransport

from api.config import get_settings
from api.database import (
    init_system_db,
    fetch_all_templates,
    fetch_template,
    insert_template,
    update_template,
    delete_template,
)


@pytest_asyncio.fixture
async def sysdb(tmp_path):
    db_path = tmp_path / "system.db"
    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        await init_system_db(conn)
        yield conn


@pytest.mark.asyncio
async def test_insert_and_fetch_template(sysdb):
    schema = json.dumps({"sections": []})
    tid = await insert_template(sysdb, "T1", "desc", "interview", schema)
    assert tid > 0
    row = await fetch_template(sysdb, tid)
    assert row["name"] == "T1"
    assert row["type"] == "interview"
    assert row["schema_json"] == schema


@pytest.mark.asyncio
async def test_fetch_all_templates_with_filter(sysdb):
    await insert_template(sysdb, "I1", "", "interview", "{}")
    await insert_template(sysdb, "Q1", "", "questionnaire", "{}")
    all_t = await fetch_all_templates(sysdb)
    assert len(all_t) == 2
    interviews = await fetch_all_templates(sysdb, type_filter="interview")
    assert len(interviews) == 1
    assert interviews[0]["name"] == "I1"


@pytest.mark.asyncio
async def test_update_and_delete_template(sysdb):
    tid = await insert_template(sysdb, "Old", "", "questionnaire", "{}")
    await update_template(sysdb, tid, "New", "d", '{"sections":[]}')
    row = await fetch_template(sysdb, tid)
    assert row["name"] == "New"
    deleted = await delete_template(sysdb, tid)
    assert deleted is True
    assert await fetch_template(sysdb, tid) is None


# ── API-level tests ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def auth_client():
    """AsyncClient with a valid Bearer token for the test admin user."""
    # Remove system.db so the admin user is freshly seeded
    system_db = Path("/tmp/agentpool_test/system.db")
    system_db.unlink(missing_ok=True)
    get_settings.cache_clear()

    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        login = await ac.post("/auth/login", data={"username": "admin", "password": "test-admin-pw"})
        token = login.json()["access_token"]
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac

    system_db.unlink(missing_ok=True)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_list_templates_empty(auth_client):
    resp = await auth_client.get("/api/templates")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_interview_template(auth_client):
    payload = {
        "name": "Standard Interview",
        "description": "A standard interview template",
        "type": "interview",
        "schema_json": {"sections": ["intro", "main"]},
    }
    resp = await auth_client.post("/api/templates", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] > 0
    assert data["name"] == "Standard Interview"
    assert data["type"] == "interview"
    assert "schema_json" not in data


@pytest.mark.asyncio
async def test_create_questionnaire_template(auth_client):
    payload = {
        "name": "Stakeholder Questionnaire",
        "description": "A questionnaire for stakeholders",
        "type": "questionnaire",
        "schema_json": {"questions": []},
    }
    resp = await auth_client.post("/api/templates", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["type"] == "questionnaire"
    assert data["name"] == "Stakeholder Questionnaire"


@pytest.mark.asyncio
async def test_get_template_by_id(auth_client):
    create_resp = await auth_client.post("/api/templates", json={
        "name": "Fetch Me",
        "type": "interview",
        "schema_json": {"key": "value"},
    })
    tid = create_resp.json()["id"]

    resp = await auth_client.get(f"/api/templates/{tid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == tid
    assert data["name"] == "Fetch Me"
    assert isinstance(data["schema_json"], dict)
    assert data["schema_json"] == {"key": "value"}


@pytest.mark.asyncio
async def test_list_templates_filter_by_type(auth_client):
    await auth_client.post("/api/templates", json={"name": "I1", "type": "interview", "schema_json": {}})
    await auth_client.post("/api/templates", json={"name": "Q1", "type": "questionnaire", "schema_json": {}})

    resp = await auth_client.get("/api/templates?type=interview")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "I1"
    assert data[0]["type"] == "interview"


@pytest.mark.asyncio
async def test_patch_template(auth_client):
    create_resp = await auth_client.post("/api/templates", json={
        "name": "Original",
        "description": "old desc",
        "type": "interview",
        "schema_json": {"v": 1},
    })
    tid = create_resp.json()["id"]

    patch_resp = await auth_client.patch(f"/api/templates/{tid}", json={
        "name": "Updated",
        "description": "new desc",
        "schema_json": {"v": 2},
    })
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["name"] == "Updated"
    assert data["description"] == "new desc"
    assert data["schema_json"] == {"v": 2}


@pytest.mark.asyncio
async def test_delete_template(auth_client):
    create_resp = await auth_client.post("/api/templates", json={
        "name": "To Delete",
        "type": "interview",
        "schema_json": {},
    })
    tid = create_resp.json()["id"]

    del_resp = await auth_client.delete(f"/api/templates/{tid}")
    assert del_resp.status_code == 204

    get_resp = await auth_client.get(f"/api/templates/{tid}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_get_template_not_found(auth_client):
    resp = await auth_client.get("/api/templates/999")
    assert resp.status_code == 404
