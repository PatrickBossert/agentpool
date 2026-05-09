import json
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import (
    get_connection,
    fetch_project,
    insert_stakeholder,
    fetch_stakeholders,
    fetch_stakeholder,
    update_stakeholder,
    delete_stakeholder,
)

SLUG = "stakeholders-test"
PROJECT = {"client_slug": SLUG, "llm_mode": "standard", "sector": "rail"}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


STAKEHOLDER = {
    "name": "Jane Smith",
    "job_title": "CFO",
    "organisation": "Acme Corp",
    "email": "jane@acme.com",
    "slack_handle": "@jane",
    "stakeholder_groups": ["Finance"],
    "project_role": "governing",
    "value_streams": ["Customer Onboarding"],
    "value_chain_stage": "Billing",
    "activity": "Invoice processing",
    "disposition": "champion",
    "location": "United Kingdom",
    "country_code": "GB",
    "timezone": "Europe/London",
    "preferred_language": "English",
    "currency": "GBP",
}


@pytest.mark.asyncio
async def test_migration_creates_stakeholders_table(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stakeholders'"
        ) as cur:
            row = await cur.fetchone()
    assert row is not None, "stakeholders table should exist after migration"


@pytest.mark.asyncio
async def test_insert_and_fetch_stakeholders(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        sid = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)
        rows = await fetch_stakeholders(conn, project_id=project["id"])
    assert len(rows) == 1
    assert rows[0]["id"] == sid
    assert rows[0]["name"] == "Jane Smith"
    assert rows[0]["stakeholder_groups"] == ["Finance"]
    assert rows[0]["value_streams"] == ["Customer Onboarding"]


@pytest.mark.asyncio
async def test_fetch_stakeholder_by_id(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        sid = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)
        row = await fetch_stakeholder(conn, stakeholder_id=sid, project_id=project["id"])
    assert row is not None
    assert row["email"] == "jane@acme.com"


@pytest.mark.asyncio
async def test_fetch_stakeholder_wrong_project_returns_none(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        sid = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)
        row = await fetch_stakeholder(conn, stakeholder_id=sid, project_id=9999)
    assert row is None


@pytest.mark.asyncio
async def test_update_stakeholder(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        sid = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)
        ok = await update_stakeholder(conn, stakeholder_id=sid, name="Jane Updated", disposition="neutral")
        row = await fetch_stakeholder(conn, stakeholder_id=sid, project_id=project["id"])
    assert ok is True
    assert row["name"] == "Jane Updated"
    assert row["disposition"] == "neutral"


@pytest.mark.asyncio
async def test_delete_stakeholder(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        sid = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)
        ok = await delete_stakeholder(conn, stakeholder_id=sid)
        rows = await fetch_stakeholders(conn, project_id=project["id"])
    assert ok is True
    assert rows == []


# ── API-level tests ──────────────────────────────────────────────────────────

STAKEHOLDER_PAYLOAD = {
    "name": "Jane Smith",
    "job_title": "CFO",
    "organisation": "Acme Corp",
    "email": "jane@acme.com",
    "slack_handle": "@jane",
    "stakeholder_groups": ["Finance"],
    "project_role": "governing",
    "value_streams": ["Customer Onboarding"],
    "value_chain_stage": "Billing",
    "activity": "Invoice processing",
    "disposition": "champion",
    "location": "United Kingdom",
    "country_code": "GB",
    "timezone": "Europe/London",
    "preferred_language": "English",
    "currency": "GBP",
}


@pytest.mark.asyncio
async def test_list_stakeholders_empty(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get(f"/projects/{SLUG}/stakeholders")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_stakeholder(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(f"/projects/{SLUG}/stakeholders", json=STAKEHOLDER_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Jane Smith"
    assert data["stakeholder_groups"] == ["Finance"]
    assert data["value_streams"] == ["Customer Onboarding"]
    assert "id" in data

    list_resp = await client.get(f"/projects/{SLUG}/stakeholders")
    assert len(list_resp.json()) == 1


@pytest.mark.asyncio
async def test_update_stakeholder_api(client):
    await client.post("/projects", json=PROJECT)
    create_resp = await client.post(f"/projects/{SLUG}/stakeholders", json=STAKEHOLDER_PAYLOAD)
    sid = create_resp.json()["id"]

    updated = {**STAKEHOLDER_PAYLOAD, "name": "Jane Updated", "disposition": "neutral"}
    resp = await client.put(f"/projects/{SLUG}/stakeholders/{sid}", json=updated)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Jane Updated"
    assert resp.json()["disposition"] == "neutral"


@pytest.mark.asyncio
async def test_delete_stakeholder_api(client):
    await client.post("/projects", json=PROJECT)
    create_resp = await client.post(f"/projects/{SLUG}/stakeholders", json=STAKEHOLDER_PAYLOAD)
    sid = create_resp.json()["id"]

    del_resp = await client.delete(f"/projects/{SLUG}/stakeholders/{sid}")
    assert del_resp.status_code == 204

    list_resp = await client.get(f"/projects/{SLUG}/stakeholders")
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_stakeholder_unknown_project_404(client):
    resp = await client.get("/projects/no-such-slug/stakeholders")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stakeholder_unknown_id_404(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.put(f"/projects/{SLUG}/stakeholders/9999", json=STAKEHOLDER_PAYLOAD)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_import_csv_creates_and_updates(client):
    await client.post("/projects", json=PROJECT)
    csv_content = (
        "name,job_title,organisation,email,stakeholder_groups,project_role,"
        "value_streams,value_chain_stage,activity,disposition,"
        "location,country_code,timezone,preferred_language,currency\n"
        "Jane Smith,CFO,Acme,jane@acme.com,Finance,governing,"
        "Customer Onboarding,Billing,Invoicing,champion,"
        "United Kingdom,GB,Europe/London,English,GBP\n"
        "Tom Jones,COO,Acme,tom@acme.com,Operations,actor,"
        "Operations,Delivery,,supporter,"
        "United States,US,America/New_York,English,USD\n"
    )
    resp = await client.post(
        f"/projects/{SLUG}/stakeholders/import",
        files={"file": ("stakeholders.csv", csv_content.encode(), "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 2
    assert data["updated"] == 0
    assert data["errors"] == []

    # Import again with same emails → both should update
    resp2 = await client.post(
        f"/projects/{SLUG}/stakeholders/import",
        files={"file": ("stakeholders.csv", csv_content.encode(), "text/csv")},
    )
    assert resp2.json()["created"] == 0
    assert resp2.json()["updated"] == 2


@pytest.mark.asyncio
async def test_import_csv_skips_bad_rows(client):
    await client.post("/projects", json=PROJECT)
    csv_content = (
        "name,email,disposition\n"
        "Valid Person,valid@acme.com,champion\n"
        "Bad Person,bad@acme.com,INVALID_DISPOSITION\n"
    )
    resp = await client.post(
        f"/projects/{SLUG}/stakeholders/import",
        files={"file": ("stakeholders.csv", csv_content.encode(), "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 1
    assert len(data["errors"]) == 1
    assert data["errors"][0]["row"] == 2
