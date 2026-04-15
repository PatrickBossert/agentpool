# tests/test_reviews.py
import pytest
from api.config import get_settings

PROJECT = {
    "client_slug": "review-test",
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
async def test_submit_review_approve(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, fetch_project, insert_agent_output
    async with get_connection("review-test") as conn:
        project = await fetch_project(conn, slug="review-test")
        output_id = await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name="test_agent",
            output_type="value_chain",
            file_path="/tmp/test.json",
            version=1,
        )

    resp = await client.post(
        "/projects/review-test/review",
        json={"output_id": output_id, "decision": "approved", "notes": "Looks good"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["decision"] == "approved"
    assert data["output_id"] == output_id


@pytest.mark.asyncio
async def test_submit_review_reject(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, fetch_project, insert_agent_output
    async with get_connection("review-test") as conn:
        project = await fetch_project(conn, slug="review-test")
        output_id = await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name="test_agent",
            output_type="value_chain",
            file_path="/tmp/test2.json",
            version=1,
        )

    resp = await client.post(
        "/projects/review-test/review",
        json={"output_id": output_id, "decision": "changes_requested", "notes": "Needs work"},
    )
    assert resp.status_code == 201
    assert resp.json()["decision"] == "changes_requested"


@pytest.mark.asyncio
async def test_review_unknown_project_returns_404(client):
    resp = await client.post(
        "/projects/ghost/review",
        json={"output_id": 1, "decision": "approved", "notes": ""},
    )
    assert resp.status_code == 404
