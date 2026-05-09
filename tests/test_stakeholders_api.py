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
