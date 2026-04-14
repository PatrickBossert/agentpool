# tests/test_run_api.py
import pytest
from unittest.mock import patch, AsyncMock
from api.config import get_settings

PROJECT_PAYLOAD = {
    "client_slug": "run-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean_run_test_state():
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_run_unknown_project_returns_404(client):
    resp = await client.post("/projects/ghost/run", json={})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_known_project_queues_run(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    with patch("api.services.run_service.dispatch_crew", new_callable=AsyncMock):
        resp = await client.post("/projects/run-test/run", json={"crew": "discovery"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["project_slug"] == "run-test"
    assert data["crew"] == "discovery"
    assert data["status"] == "running"
    assert isinstance(data["run_id"], int)


@pytest.mark.asyncio
async def test_run_value_design_crew_queues_run(client):
    payload = {**PROJECT_PAYLOAD, "client_slug": "vd-test", "crews_enabled": ["value_design"]}
    await client.post("/projects", json=payload)
    with patch("api.services.run_service.dispatch_crew", new_callable=AsyncMock):
        resp = await client.post("/projects/vd-test/run", json={"crew": "value_design"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["crew"] == "value_design"
    assert data["status"] == "running"
