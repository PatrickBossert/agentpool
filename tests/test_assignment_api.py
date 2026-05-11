# tests/test_assignment_api.py
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import (
    get_connection,
    insert_project,
    fetch_project,
    insert_orchestration_run,
    insert_stakeholder,
    fetch_stakeholder_assignments,
    replace_stakeholder_assignments,
    update_orchestration_run_status,
)
from unittest.mock import patch, AsyncMock

SLUG = "assignment-test"
PROJECT = {"client_slug": SLUG, "llm_mode": "standard", "sector": "rail"}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_migration_creates_stakeholder_assignments_table(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stakeholder_assignments'"
        ) as cur:
            row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_replace_and_fetch_stakeholder_assignments():
    """replace saves rows; fetch returns them in id order."""
    async with get_connection(SLUG) as conn:
        await insert_project(conn, slug=SLUG, llm_mode="standard", sector="rail", config_json="{}")
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        sh_id = await insert_stakeholder(
            conn,
            project_id=project["id"],
            name="Jane",
            job_title="CFO",
            organisation="Acme",
            email="",
            slack_handle="",
            stakeholder_groups=[],
            project_role="recipient",
            value_streams=[],
            value_chain_stage="",
            activity="",
            disposition="neutral",
            location="",
            country_code="",
            timezone="",
            preferred_language="",
            currency="",
        )
        count = await replace_stakeholder_assignments(
            conn,
            orchestration_run_id=run_id,
            assignments=[{"stakeholder_id": sh_id, "level": "L2", "node_label": "Billing"}],
        )
    assert count == 1
    async with get_connection(SLUG) as conn:
        rows = await fetch_stakeholder_assignments(conn, orchestration_run_id=run_id)
    assert len(rows) == 1
    assert rows[0]["level"] == "L2"
    assert rows[0]["node_label"] == "Billing"
    assert rows[0]["stakeholder_id"] == sh_id


@pytest.mark.asyncio
async def test_replace_stakeholder_assignments_replaces_not_appends():
    """Calling replace twice keeps only the second set."""
    async with get_connection(SLUG) as conn:
        await insert_project(conn, slug=SLUG, llm_mode="standard", sector="rail", config_json="{}")
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        sh_id = await insert_stakeholder(
            conn,
            project_id=project["id"],
            name="Bob",
            job_title="PM",
            organisation="Acme",
            email="",
            slack_handle="",
            stakeholder_groups=[],
            project_role="recipient",
            value_streams=[],
            value_chain_stage="",
            activity="",
            disposition="neutral",
            location="",
            country_code="",
            timezone="",
            preferred_language="",
            currency="",
        )
        await replace_stakeholder_assignments(
            conn,
            orchestration_run_id=run_id,
            assignments=[{"stakeholder_id": sh_id, "level": "L1", "node_label": "Operations"}],
        )
        count = await replace_stakeholder_assignments(
            conn,
            orchestration_run_id=run_id,
            assignments=[{"stakeholder_id": sh_id, "level": "L2", "node_label": "Billing"}],
        )
    assert count == 1
    async with get_connection(SLUG) as conn:
        rows = await fetch_stakeholder_assignments(conn, orchestration_run_id=run_id)
    assert len(rows) == 1
    assert rows[0]["node_label"] == "Billing"


@pytest.mark.asyncio
async def test_fetch_stakeholder_assignments_empty_for_unknown_run():
    """Returns [] when no assignments exist for a run."""
    async with get_connection(SLUG) as conn:
        await insert_project(conn, slug=SLUG, llm_mode="standard", sector="rail", config_json="{}")
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        rows = await fetch_stakeholder_assignments(conn, orchestration_run_id=run_id)
    assert rows == []


STAKEHOLDER = {
    "name": "Jane Smith",
    "job_title": "CFO",
    "organisation": "Acme",
    "email": "jane@acme.com",
    "slack_handle": "@jane",
    "stakeholder_groups": ["Finance"],
    "project_role": "governing",
    "value_streams": ["Billing"],
    "value_chain_stage": "Billing",
    "activity": "Invoicing",
    "disposition": "champion",
    "location": "UK",
    "country_code": "GB",
    "timezone": "Europe/London",
    "preferred_language": "English",
    "currency": "GBP",
}


@pytest.mark.asyncio
async def test_get_assignment_returns_empty_tree_when_no_file(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])

    resp = await client.get(f"/projects/{SLUG}/assignment/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["value_chain_tree"] == []
    assert data["assignments"] == []


@pytest.mark.asyncio
async def test_get_assignment_returns_404_for_unknown_project(client):
    resp = await client.get("/projects/unknown-proj/assignment/1")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_assignment_saves_and_returns_count(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        sh_id = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)

    payload = [{"stakeholder_id": sh_id, "level": "L2", "node_label": "Billing"}]
    resp = await client.post(f"/projects/{SLUG}/assignment/{run_id}", json=payload)
    assert resp.status_code == 200
    assert resp.json()["saved"] == 1


@pytest.mark.asyncio
async def test_post_assignment_replaces_existing(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        sh_id = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)

    # First save
    await client.post(
        f"/projects/{SLUG}/assignment/{run_id}",
        json=[{"stakeholder_id": sh_id, "level": "L1", "node_label": "Operations"}],
    )
    # Replace with different assignment
    resp = await client.post(
        f"/projects/{SLUG}/assignment/{run_id}",
        json=[{"stakeholder_id": sh_id, "level": "L2", "node_label": "Billing"}],
    )
    assert resp.json()["saved"] == 1

    # Verify only 1 row remains
    resp2 = await client.get(f"/projects/{SLUG}/assignment/{run_id}")
    assert len(resp2.json()["assignments"]) == 1
    assert resp2.json()["assignments"][0]["node_label"] == "Billing"


@pytest.mark.asyncio
async def test_post_assignment_422_for_empty_body(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])

    resp = await client.post(f"/projects/{SLUG}/assignment/{run_id}", json=[])
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_advance_orchestration_succeeds_from_awaiting_assignment(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        await update_orchestration_run_status(conn, run_id=run_id, status="awaiting_assignment")

    with patch("api.routers.assignment.resume_orchestration", new_callable=AsyncMock):
        resp = await client.patch(f"/projects/{SLUG}/orchestration-runs/{run_id}/advance")

    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


@pytest.mark.asyncio
async def test_advance_orchestration_400_if_not_awaiting(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        # status is 'running' by default

    with patch("api.routers.assignment.resume_orchestration", new_callable=AsyncMock):
        resp = await client.patch(f"/projects/{SLUG}/orchestration-runs/{run_id}/advance")

    assert resp.status_code == 400
