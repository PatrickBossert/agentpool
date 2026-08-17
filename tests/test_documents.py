import io
import pytest
from api.config import get_settings

PROJECT = {
    "client_slug": "doc-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
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


@pytest.mark.asyncio
async def test_upload_no_filename_does_not_crash(client):
    """Upload with no filename must not raise TypeError (no 500) — guards file.filename None."""
    from unittest.mock import AsyncMock, patch

    await client.post("/projects", json=PROJECT)

    mock_ingest = AsyncMock()
    with patch("api.routers.documents.ingest_document", mock_ingest):
        # Provide a non-empty filename so FastAPI accepts the multipart field,
        # but simulate the None-guard path by checking Path("" or "").suffix == ""
        resp = await client.post(
            "/projects/doc-test/documents/upload",
            files={"file": ("noext", io.BytesIO(b"data"), "application/octet-stream")},
        )

    # File with no extension is accepted (suffix==""), uploaded, and ingest will skip it
    assert resp.status_code == 201
    assert resp.json()["original_name"] == "noext"


@pytest.mark.asyncio
async def test_upload_triggers_ingest_background_task(client, tmp_path):
    """After upload, background task runs and sets ingested=True (AsyncClient runs tasks inline)."""
    from unittest.mock import AsyncMock, patch

    await client.post("/projects", json=PROJECT)

    mock_ingest = AsyncMock()
    with patch("api.routers.documents.ingest_document", mock_ingest):
        file_content = b"Quarterly review document with strategy details."
        resp = await client.post(
            "/projects/doc-test/documents/upload",
            files={"file": ("strategy.txt", io.BytesIO(file_content), "text/plain")},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["original_name"] == "strategy.txt"
    # Background task ran (AsyncClient + ASGITransport executes tasks inline)
    mock_ingest.assert_awaited_once()
    call_args = mock_ingest.call_args
    assert call_args.args[0] == "doc-test"          # slug
    assert isinstance(call_args.args[1], int)        # doc_id
    assert call_args.args[2].endswith(".txt")        # file_path ends with .txt extension


@pytest.mark.asyncio
async def test_delete_document_with_run_documents_and_citations_succeeds(client):
    """A document a crew run has read (run_documents) or an output has cited
    (output_citations) must still be deletable - foreign_keys=ON means those rows have to
    be cleared before client_documents can be hard-deleted, or the delete raises
    IntegrityError and the endpoint 500s."""
    from api.database import get_connection

    await client.post("/projects", json=PROJECT)

    resp = await client.post(
        "/projects/doc-test/documents/upload",
        files={"file": ("report.pdf", io.BytesIO(b"content"), "application/pdf")},
    )
    doc_id = resp.json()["id"]

    async with get_connection("doc-test") as conn:
        await conn.execute(
            "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
            " version, is_current, review_status) VALUES (1,'value_lever_analyst',"
            " 'value_levers','value_levers_v1.json',1,1,'pending')"
        )
        await conn.commit()
        async with conn.execute("SELECT id FROM agent_outputs") as cur:
            output_id = (await cur.fetchone())["id"]
        await conn.execute(
            "INSERT INTO run_documents (run_id, doc_id) VALUES (30,?)", (doc_id,)
        )
        await conn.execute(
            "INSERT INTO output_citations (output_id, doc_id) VALUES (?,?)",
            (output_id, doc_id),
        )
        await conn.commit()

    resp = await client.delete(f"/projects/doc-test/documents/{doc_id}")
    assert resp.status_code == 204

    async with get_connection("doc-test") as conn:
        async with conn.execute(
            "SELECT 1 FROM client_documents WHERE id=?", (doc_id,)
        ) as cur:
            assert await cur.fetchone() is None
        async with conn.execute(
            "SELECT 1 FROM run_documents WHERE doc_id=?", (doc_id,)
        ) as cur:
            assert await cur.fetchone() is None
        async with conn.execute(
            "SELECT 1 FROM output_citations WHERE doc_id=?", (doc_id,)
        ) as cur:
            assert await cur.fetchone() is None
