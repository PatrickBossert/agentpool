# tests/test_projects_api.py
import shutil
from pathlib import Path

import pytest

from api.config import get_settings


@pytest.fixture(autouse=True)
def clean_test_state():
    """Remove any leftover test-rail state before each test."""
    get_settings.cache_clear()
    db_dir = Path("/tmp/agentpool_test")
    proj_dir = Path("/tmp/agentpool_test_projects")
    for d in (db_dir, proj_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    yield


PROJECT_PAYLOAD = {
    "client_slug": "test-rail",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations", "Customer"],
    "value_stream_labels": ["Asset Mgmt"],
    "roadmap_time_axis": "quarters",
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "#test",
}


@pytest.mark.asyncio
async def test_create_project_returns_201(client):
    resp = await client.post("/projects", json=PROJECT_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "test-rail"
    assert data["status"] == "created"


@pytest.mark.asyncio
async def test_create_project_idempotent(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.post("/projects", json=PROJECT_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert data["slug"] == "test-rail"


@pytest.mark.asyncio
async def test_get_project_status(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.get("/projects/test-rail/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_slug"] == "test-rail"
    assert "crew_runs" in data


@pytest.mark.asyncio
async def test_get_status_unknown_project_returns_404(client):
    resp = await client.get("/projects/does-not-exist/status")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_project_minimal_payload(client):
    """POST /projects with only client_slug + sector uses model defaults."""
    resp = await client.post("/projects", json={"client_slug": "minimal-co", "sector": "retail"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "minimal-co"
    assert data["status"] == "created"


@pytest.mark.asyncio
async def test_get_project_status_includes_orchestration_run_field(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.get("/projects/test-rail/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "latest_orchestration_run" in data
    assert data["latest_orchestration_run"] is None
