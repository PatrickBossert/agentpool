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
            "score_financial": 7.0,
            "score_financial_rationale": "Reduces OpEx by automating inspections.",
            "score_financial_unit": "NPV £M",
            "score_manufactured": 6.5,
            "score_manufactured_rationale": "Extends asset life through predictive maintenance.",
            "score_manufactured_unit": "Asset replacement value £M",
            "score_intellectual": 5.5,
            "score_intellectual_rationale": "Generates proprietary sensor datasets.",
            "score_intellectual_unit": "R&D £M / IP count",
            "score_human": 6.0,
            "score_human_rationale": "Upskills maintenance staff in data analysis.",
            "score_human_unit": "FTE-days / skills uplift",
            "score_social_relationship": 5.5,
            "score_social_relationship_rationale": "Improves regulator confidence through transparency.",
            "score_social_relationship_unit": "NPS / beneficiary count",
            "score_natural": 6.0,
            "score_natural_rationale": "Reduces unnecessary site visits and emissions.",
            "score_natural_unit": "CO₂e t / water ML / land ha",
            "score_safety": 8.0,
            "score_safety_rationale": "Early fault detection reduces RIDDOR-reportable incidents.",
            "score_safety_unit": "RIDDOR rate / safety risk score",
            "score_performance": 7.5,
            "score_performance_rationale": "Increases asset availability by reducing unplanned outages.",
            "score_performance_unit": "Throughput % / availability %",
            "total_score": 68.5,
            "weights_used": {
                "financial": 20,
                "manufactured": 10,
                "intellectual": 5,
                "human": 5,
                "social_relationship": 5,
                "natural": 20,
                "safety": 20,
                "performance": 15,
            },
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
    assert data[0]["score_financial"] == 7.0
    assert data[0]["weights_used"]["safety"] == 20


@pytest.mark.asyncio
async def test_portfolio_register_unknown_project(client):
    """Returns 404 when the project does not exist."""
    resp = await client.get("/projects/nonexistent/portfolio-register")
    assert resp.status_code == 404
