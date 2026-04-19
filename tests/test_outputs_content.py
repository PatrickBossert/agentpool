import shutil
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, insert_agent_output, fetch_project

SLUG = "content-test"
PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "rail",
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


async def _insert_output(file_path: str, output_type: str = "value_chain") -> int:
    """Helper: insert an agent_output row for SLUG and return its ID."""
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        return await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name="test_agent",
            output_type=output_type,
            file_path=file_path,
            version=1,
        )


@pytest.mark.asyncio
async def test_get_content_returns_mermaid_source(client):
    """Create a project + real file + output row → GET returns file content."""
    await client.post("/projects", json=PROJECT)
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / SLUG / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    md_file = outputs_dir / "value_chain.md"
    md_file.write_text("graph LR\n  A --> B", encoding="utf-8")
    output_id = await _insert_output(str(md_file), output_type="value_chain")

    resp = await client.get(f"/projects/{SLUG}/outputs/{output_id}/content")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "graph LR\n  A --> B"
    assert data["output_type"] == "value_chain"


@pytest.mark.asyncio
async def test_get_content_unknown_project_404(client):
    resp = await client.get("/projects/ghost-project/outputs/1/content")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_content_unknown_output_404(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get(f"/projects/{SLUG}/outputs/99999/content")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_content_output_wrong_project_404(client):
    """Output row belongs to SLUG — cannot be fetched via other_slug."""
    other_slug = "other-content-test"
    settings = get_settings()
    other_db = Path(settings.database_dir) / f"{other_slug}.db"
    other_dir = Path(settings.projects_dir) / other_slug
    try:
        await client.post("/projects", json={**PROJECT, "client_slug": other_slug})
        await client.post("/projects", json=PROJECT)

        outputs_dir = Path(settings.projects_dir) / SLUG / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        md_file = outputs_dir / "vc.md"
        md_file.write_text("graph LR\n  A-->B", encoding="utf-8")
        output_id = await _insert_output(str(md_file), output_type="value_chain")

        # Try to read SLUG's output via other_slug — should be 404
        resp = await client.get(f"/projects/{other_slug}/outputs/{output_id}/content")
        assert resp.status_code == 404
    finally:
        other_db.unlink(missing_ok=True)
        if other_dir.exists():
            shutil.rmtree(other_dir)


@pytest.mark.asyncio
async def test_get_content_file_missing_on_disk_404(client):
    """Row exists in DB but file was deleted from disk → 404."""
    await client.post("/projects", json=PROJECT)
    output_id = await _insert_output("/tmp/does-not-exist-sp7c-abc.md")

    resp = await client.get(f"/projects/{SLUG}/outputs/{output_id}/content")
    assert resp.status_code == 404
    assert "not found on disk" in resp.json()["detail"]
