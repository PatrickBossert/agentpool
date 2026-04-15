import pytest
from pathlib import Path
from api.config import get_settings

PROJECT_A = {
    "client_slug": "list-proj-a",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}
PROJECT_B = {**PROJECT_A, "client_slug": "list-proj-b"}


@pytest.fixture(autouse=True)
def clean():
    # Remove any leftover DB files before each test so list tests start fresh
    db_dir = Path(get_settings().database_dir)
    for db_file in db_dir.glob("*.db"):
        db_file.unlink(missing_ok=True)
    yield
    for db_file in db_dir.glob("*.db"):
        db_file.unlink(missing_ok=True)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_list_projects_empty(client):
    resp = await client.get("/projects")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_projects_returns_all(client):
    await client.post("/projects", json=PROJECT_A)
    await client.post("/projects", json=PROJECT_B)
    resp = await client.get("/projects")
    assert resp.status_code == 200
    slugs = [p["slug"] for p in resp.json()]
    assert "list-proj-a" in slugs
    assert "list-proj-b" in slugs
    assert len(slugs) == 2
