# tests/test_projects_api.py
import json
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


@pytest.mark.asyncio
async def test_portfolio_register_empty(client):
    """Returns [] when project exists but portfolio_register.json does not."""
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.get("/projects/test-rail/portfolio-register")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_portfolio_register_returns_data(client):
    """Returns parsed JSON array when portfolio_register.json exists on disk."""
    await client.post("/projects", json=PROJECT_PAYLOAD)

    register = [
        {
            "rank": 1,
            "id": "VP-001",
            "title": "Modernise Asset Management",
            "change_articulation": "Replaces manual inspection logs with IoT-driven data.",
            "impacted_stakeholder_groups": ["Operations", "Safety"],
            "value_estimate": "High",
            "score_value": 8.0,
            "score_feasibility": 7.0,
            "score_strategic_fit": 9.0,
            "score_value_rationale": "Direct cost reduction.",
            "score_feasibility_rationale": "APIs exist.",
            "score_strategic_fit_rationale": "Core strategy.",
            "total_score": 80.0,
            "weights_used": {"value": 5, "feasibility": 3, "strategic_fit": 2},
        }
    ]
    outputs_dir = Path("/tmp/agentpool_test_projects/test-rail/outputs")
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "portfolio_register.json").write_text(
        json.dumps(register), encoding="utf-8"
    )

    resp = await client.get("/projects/test-rail/portfolio-register")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "VP-001"
    assert data[0]["total_score"] == 80.0
