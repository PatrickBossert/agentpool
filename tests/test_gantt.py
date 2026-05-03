import json
import shutil
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, insert_agent_output, fetch_project

SLUG = "gantt-test"
PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "rail",
}

MINIMAL_ROADMAP = {
    "periods": ["Q1 2025", "Q2 2025"],
    "value_streams": ["Customer Portal"],
    "stakeholder_groups": [],
    "initiatives": [
        {
            "title": "Digital Onboarding",
            "value_streams": ["Customer Portal"],
            "period": "Q1 2025",
            "category": "enabling",
            "complexity_score": 7,
        }
    ],
    "propositions": [],
}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    proj_dir = Path(settings.projects_dir) / SLUG
    db_path.unlink(missing_ok=True)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)


async def _insert_roadmap_data(file_path: str) -> int:
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        return await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name="test_agent",
            output_type="roadmap_data",
            file_path=file_path,
            version=1,
        )


@pytest.mark.asyncio
async def test_get_roadmap_data_returns_json(client):
    """Create project + write JSON + insert row → GET returns 200 with correct keys."""
    await client.post("/projects", json=PROJECT)
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / SLUG / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    json_file = outputs_dir / "roadmap_data.json"
    json_file.write_text(json.dumps(MINIMAL_ROADMAP), encoding="utf-8")
    await _insert_roadmap_data(str(json_file))

    resp = await client.get(f"/projects/{SLUG}/roadmap-data")
    assert resp.status_code == 200
    data = resp.json()
    assert "periods" in data
    assert "initiatives" in data
    assert data["periods"] == ["Q1 2025", "Q2 2025"]
    assert data["initiatives"][0]["title"] == "Digital Onboarding"


@pytest.mark.asyncio
async def test_get_roadmap_data_unknown_project_404(client):
    resp = await client.get("/projects/ghost-project/roadmap-data")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_roadmap_data_no_output_404(client):
    """Valid project with no roadmap_data output row → 404."""
    await client.post("/projects", json=PROJECT)
    resp = await client.get(f"/projects/{SLUG}/roadmap-data")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_roadmap_data_file_missing_on_disk_404(client):
    """Row exists but JSON file deleted → 404."""
    await client.post("/projects", json=PROJECT)
    await _insert_roadmap_data("/tmp/does-not-exist-sp8b-abc.json")

    resp = await client.get(f"/projects/{SLUG}/roadmap-data")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_html_roadmap_tool_writes_json(client):
    """HtmlRoadmapTool._run() writes roadmap_data.json alongside roadmap.html."""
    await client.post("/projects", json=PROJECT)
    settings = get_settings()

    from agents.tools.html_roadmap import HtmlRoadmapTool
    tool = HtmlRoadmapTool(slug=SLUG)
    tool._run(
        roadmap_data=MINIMAL_ROADMAP,
        filename="roadmap.html",
        agent_name="test_roadmap_agent",
    )

    outputs_dir = Path(settings.projects_dir) / SLUG / "outputs"
    json_file = outputs_dir / "roadmap_data.json"
    assert json_file.exists(), "roadmap_data.json was not written"
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert "periods" in data
    assert "initiatives" in data
    assert "value_streams" in data
