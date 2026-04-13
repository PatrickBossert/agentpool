import io
import pytest
from api.config import get_settings

PROJECT = {
    "client_slug": "doc-test",
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
    import shutil
    from pathlib import Path
    settings = get_settings()
    db_path = Path(settings.database_dir) / "doc-test.db"
    proj_dir = Path(settings.projects_dir) / "doc-test"
    # clean before each test
    db_path.unlink(missing_ok=True)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)


@pytest.mark.asyncio
async def test_list_documents_empty(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get("/projects/doc-test/documents")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_upload_document(client):
    await client.post("/projects", json=PROJECT)
    file_content = b"Test PDF content"
    resp = await client.post(
        "/projects/doc-test/documents/upload",
        files={"file": ("test.pdf", io.BytesIO(file_content), "application/pdf")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["original_name"] == "test.pdf"
    assert data["ingested"] is False


@pytest.mark.asyncio
async def test_list_documents_after_upload(client):
    await client.post("/projects", json=PROJECT)
    await client.post(
        "/projects/doc-test/documents/upload",
        files={"file": ("report.pdf", io.BytesIO(b"content"), "application/pdf")},
    )
    resp = await client.get("/projects/doc-test/documents")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["original_name"] == "report.pdf"


@pytest.mark.asyncio
async def test_documents_unknown_project_returns_404(client):
    resp = await client.get("/projects/ghost/documents")
    assert resp.status_code == 404
