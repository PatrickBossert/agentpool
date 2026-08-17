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
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean_run_test_state():
    yield
    get_settings.cache_clear()


async def _crew_run_count(slug: str) -> int:
    """Rows in this project's own `crew_runs` table.

    Per project, because there is one database per project and this slug belongs to one test -
    a global count would move under any other test that starts a run.
    """
    from api.database import get_connection
    async with get_connection(slug) as conn:
        async with conn.execute("SELECT COUNT(*) AS n FROM crew_runs") as cur:
            row = await cur.fetchone()
    return row["n"]


@pytest.mark.asyncio
async def test_run_with_neither_crew_nor_agent_is_refused_and_starts_nothing(client):
    """An empty body used to dispatch `requirements` - the one crew that could not be built.

    Both halves matter. The insert used to happen before the dispatch, so a refusal added late
    would answer 400 and still leave a `crew_runs` row behind: a run in the history that never
    ran and never will.
    """
    payload = {**PROJECT_PAYLOAD, "client_slug": "empty-body-test"}
    await client.post("/projects", json=payload)
    before = await _crew_run_count("empty-body-test")

    with patch("api.services.run_service.dispatch_crew", new_callable=AsyncMock) as dispatch:
        resp = await client.post("/projects/empty-body-test/run", json={})

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "crew" in detail and "agent" in detail, detail
    dispatch.assert_not_awaited()
    assert await _crew_run_count("empty-body-test") == before


@pytest.mark.asyncio
async def test_run_unknown_project_returns_404(client):
    resp = await client.post("/projects/ghost/run", json={})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_known_project_queues_run(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    with patch("api.services.run_service.dispatch_crew", new_callable=AsyncMock):
        resp = await client.post("/projects/run-test/run", json={"crew": "requirements"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["project_slug"] == "run-test"
    assert data["crew"] == "requirements"
    assert data["status"] == "running"
    assert isinstance(data["run_id"], int)


@pytest.mark.asyncio
async def test_run_value_design_crew_queues_run(client):
    payload = {**PROJECT_PAYLOAD, "client_slug": "vd-test"}
    await client.post("/projects", json=payload)
    with patch("api.services.run_service.dispatch_crew", new_callable=AsyncMock):
        resp = await client.post("/projects/vd-test/run", json={"crew": "value_design"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["crew"] == "value_design"
    assert data["status"] == "running"
    assert data["project_slug"] == "vd-test"
    assert isinstance(data["run_id"], int)


@pytest.mark.asyncio
async def test_run_capabilities_crew_queues_run(client):
    payload = {**PROJECT_PAYLOAD, "client_slug": "arch-test"}
    await client.post("/projects", json=payload)
    with patch("api.services.run_service.dispatch_crew", new_callable=AsyncMock):
        resp = await client.post("/projects/arch-test/run", json={"crew": "capabilities"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["crew"] == "capabilities"
    assert data["status"] == "running"
    assert data["project_slug"] == "arch-test"
    assert isinstance(data["run_id"], int)


@pytest.mark.asyncio
async def test_run_delivery_crew_queues_run(client):
    payload = {**PROJECT_PAYLOAD, "client_slug": "delivery-test"}
    await client.post("/projects", json=payload)
    with patch("api.services.run_service.dispatch_crew", new_callable=AsyncMock):
        resp = await client.post("/projects/delivery-test/run", json={"crew": "delivery"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["crew"] == "delivery"
    assert data["status"] == "running"
    assert data["project_slug"] == "delivery-test"
    assert isinstance(data["run_id"], int)


@pytest.mark.asyncio
async def test_run_business_plan_crew_queues_run(client):
    payload = {**PROJECT_PAYLOAD, "client_slug": "bp-test"}
    await client.post("/projects", json=payload)
    with patch("api.services.run_service.dispatch_crew", new_callable=AsyncMock):
        resp = await client.post("/projects/bp-test/run", json={"crew": "business_plan"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["crew"] == "business_plan"
    assert data["status"] == "running"
    assert data["project_slug"] == "bp-test"
    assert isinstance(data["run_id"], int)
