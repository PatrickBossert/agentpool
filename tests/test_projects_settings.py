import shutil
import yaml
import pytest
from pathlib import Path
from api.config import get_settings

PROJECT = {
    "client_slug": "settings-test",
    "llm_mode": "standard",
    "sector": "rail",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "roadmap_time_axis": "quarters",
    "crews_enabled": ["discovery", "value_design"],
    "review_gates": True,
    "slack_channel": "#rail",
}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / "settings-test.db"
    proj_dir = Path(settings.projects_dir) / "settings-test"
    db_path.unlink(missing_ok=True)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)


@pytest.mark.asyncio
async def test_get_settings_returns_config(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get("/projects/settings-test/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sector"] == "rail"
    assert data["llm_mode"] == "standard"
    assert data["stakeholder_groups"] == ["Operations"]
    assert data["review_gates"] is True
    assert "client_slug" not in data


@pytest.mark.asyncio
async def test_get_settings_unknown_project_404(client):
    resp = await client.get("/projects/ghost/settings")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_settings_updates_db(client):
    await client.post("/projects", json=PROJECT)
    patch_body = {
        "llm_mode": "sensitive",
        "sector": "energy",
        "stakeholder_groups": ["Finance"],
        "value_stream_labels": [],
        "roadmap_time_axis": "years",
        "crews_enabled": ["discovery"],
        "review_gates": False,
        "slack_channel": "#energy",
    }
    resp = await client.patch("/projects/settings-test/settings", json=patch_body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["sector"] == "energy"
    assert data["llm_mode"] == "sensitive"
    assert data["review_gates"] is False
    # Verify persisted via GET
    get_resp = await client.get("/projects/settings-test/settings")
    assert get_resp.json()["sector"] == "energy"
    assert get_resp.json()["llm_mode"] == "sensitive"


@pytest.mark.asyncio
async def test_patch_settings_rewrites_yaml(client):
    await client.post("/projects", json=PROJECT)
    patch_body = {
        "llm_mode": "standard",
        "sector": "energy",
        "stakeholder_groups": [],
        "value_stream_labels": [],
        "roadmap_time_axis": "quarters",
        "crews_enabled": ["discovery"],
        "review_gates": True,
        "slack_channel": "",
    }
    await client.patch("/projects/settings-test/settings", json=patch_body)
    settings = get_settings()
    yaml_path = Path(settings.projects_dir) / "settings-test" / "config.yaml"
    with yaml_path.open() as f:
        config = yaml.safe_load(f)
    assert config["sector"] == "energy"
    assert config["client_slug"] == "settings-test"


@pytest.mark.asyncio
async def test_patch_settings_unknown_project_404(client):
    patch_body = {
        "llm_mode": "standard",
        "sector": "rail",
        "stakeholder_groups": [],
        "value_stream_labels": [],
        "roadmap_time_axis": "quarters",
        "crews_enabled": ["discovery"],
        "review_gates": True,
        "slack_channel": "",
    }
    resp = await client.patch("/projects/ghost/settings", json=patch_body)
    assert resp.status_code == 404
