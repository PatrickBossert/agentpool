# tests/test_outputs_api.py
import pytest
from api.config import get_settings

PROJECT_PAYLOAD = {
    "client_slug": "out-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean_outputs_test_state():
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_outputs_empty_for_new_project(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    resp = await client.get("/projects/out-test/outputs")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_outputs_unknown_project_returns_404(client):
    resp = await client.get("/projects/ghost/outputs")
    assert resp.status_code == 404
