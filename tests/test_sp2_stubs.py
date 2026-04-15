# tests/test_sp2_stubs.py
import pytest
from api.config import get_settings

PROJECT = {
    "client_slug": "stub-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean():
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_value_chain_empty_for_new_project(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get("/projects/stub-test/value-chain")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_roadmap_empty_for_new_project(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get("/projects/stub-test/roadmap")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_value_chain_unknown_project_returns_404(client):
    resp = await client.get("/projects/ghost/value-chain")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_roadmap_unknown_project_returns_404(client):
    resp = await client.get("/projects/ghost/roadmap")
    assert resp.status_code == 404
