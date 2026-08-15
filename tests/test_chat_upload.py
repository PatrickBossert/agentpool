# tests/test_chat_upload.py
import re

import pytest
from unittest.mock import patch, AsyncMock

SLUG = "upload-test"

@pytest.fixture(autouse=True)
def _granted_authority():
    """This module is about ingestion, file handling and the documents row, not about who
    may attach a document. The client fixture's sysadmin token names no real user, so
    caller_may_approve correctly answers False for it and every upload here would 403.

    Not a weakening of the gate: tests/test_write_door_authority.py drives every one of
    these doors over HTTP as a real member with and without the flag, so deleting the gate
    fails there. Patched on the router module, where the name is looked up - the routers
    bind their own reference via `from ... import`, so patching authority_service itself
    would miss them (CLAUDE.md's four-crew-tests entry).
    """
    with patch("api.routers.agent_chat.caller_may_approve", new=AsyncMock(return_value=True)):
        yield




async def _make_project(client):
    await client.post("/projects", json={
        "client_slug": SLUG, "llm_mode": "standard", "sector": "rail",
    })


@pytest.mark.asyncio
async def test_upload_ingests_before_responding(client):
    """Ingestion is awaited, not queued - the document is searchable on return."""
    await _make_project(client)
    with patch("api.routers.agent_chat.ingest_document", new_callable=AsyncMock) as m_ingest:
        resp = await client.post(
            f"/projects/{SLUG}/agent-chat/upload",
            data={"agent_name": "Interview Coordinator"},
            files={"file": ("notes.txt", b"warehouse runs two shifts", "text/plain")},
        )
    assert resp.status_code == 201
    m_ingest.assert_awaited_once()
    assert m_ingest.await_args.kwargs["raise_on_error"] is True


@pytest.mark.asyncio
async def test_upload_fails_loudly_when_ingestion_fails(client):
    """A Chroma outage must not produce a document that looks uploaded but is invisible."""
    await _make_project(client)
    from api.services.ingest_service import IngestError
    with patch("api.routers.agent_chat.ingest_document",
               new_callable=AsyncMock, side_effect=IngestError("chroma down")):
        resp = await client.post(
            f"/projects/{SLUG}/agent-chat/upload",
            data={"agent_name": "Interview Coordinator"},
            files={"file": ("notes.txt", b"some text", "text/plain")},
        )
    assert resp.status_code == 502
    detail = resp.json()["detail"].lower()
    assert "index" in detail
    assert "documents page" in detail
    assert re.search(r"id \d+", detail), "502 detail must name the document id so it can be located"


@pytest.mark.asyncio
async def test_response_no_longer_carries_preview_text(client):
    await _make_project(client)
    with patch("api.routers.agent_chat.ingest_document", new_callable=AsyncMock):
        resp = await client.post(
            f"/projects/{SLUG}/agent-chat/upload",
            data={"agent_name": "Interview Coordinator"},
            files={"file": ("notes.txt", b"some text", "text/plain")},
        )
    assert resp.status_code == 201
    assert "preview_text" not in resp.json()


@pytest.mark.asyncio
async def test_oversized_image_rejected(client):
    await _make_project(client)
    from api.routers.agent_chat import MAX_IMAGE_BYTES
    oversized = b"\x89PNG\r\n\x1a\n" + b"x" * MAX_IMAGE_BYTES
    resp = await client.post(
        f"/projects/{SLUG}/agent-chat/upload",
        data={"agent_name": "Interview Coordinator"},
        files={"file": ("big.png", oversized, "image/png")},
    )
    assert resp.status_code == 422
    assert "4 MB" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_image_upload_skips_ingestion(client):
    """Images cannot be embedded by a text pipeline - do not try."""
    await _make_project(client)
    with patch("api.routers.agent_chat.ingest_document", new_callable=AsyncMock) as m_ingest:
        resp = await client.post(
            f"/projects/{SLUG}/agent-chat/upload",
            data={"agent_name": "Interview Coordinator"},
            files={"file": ("chart.png", b"\x89PNG\r\n\x1a\ndata", "image/png")},
        )
    assert resp.status_code == 201
    assert resp.json()["is_image"] is True
    m_ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_document_with_no_extractable_text_still_uploads(client):
    """A scanned PDF yields no chunks. That is not an error - see the spec.

    raise_on_error=True must not turn 'nothing to index' into a failed upload,
    or every image-only PDF becomes an unexplained 502.
    """
    await _make_project(client)
    with patch("api.services.ingest_service._extract_text", return_value="   "):
        resp = await client.post(
            f"/projects/{SLUG}/agent-chat/upload",
            data={"agent_name": "Interview Coordinator"},
            files={"file": ("scanned.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_chat_upload_appears_in_project_documents(client):
    """Regression lock: chat uploads are project documents, not a separate store."""
    await _make_project(client)
    with patch("api.routers.agent_chat.ingest_document", new_callable=AsyncMock):
        upload = await client.post(
            f"/projects/{SLUG}/agent-chat/upload",
            data={"agent_name": "Interview Coordinator"},
            files={"file": ("shared.txt", b"content", "text/plain")},
        )
    doc_id = upload.json()["doc_id"]

    listing = await client.get(f"/projects/{SLUG}/documents")
    assert listing.status_code == 200
    assert doc_id in [d["id"] for d in listing.json()]


@pytest.mark.asyncio
async def test_failed_ingestion_leaves_document_recoverable(client):
    """After a 502, the row and file are deliberately kept, not rolled back.

    The human's ruling: recovery is via the reingest endpoint, not a re-upload,
    so the document must still be visible in the project library afterwards.
    """
    await _make_project(client)
    from api.services.ingest_service import IngestError
    with patch("api.routers.agent_chat.ingest_document",
               new_callable=AsyncMock, side_effect=IngestError("chroma down")):
        upload = await client.post(
            f"/projects/{SLUG}/agent-chat/upload",
            data={"agent_name": "Interview Coordinator"},
            files={"file": ("notes.txt", b"some text", "text/plain")},
        )
    assert upload.status_code == 502
    match = re.search(r"id (\d+)", upload.json()["detail"])
    assert match, "502 detail must name the document id so it can be located"
    doc_id = int(match.group(1))

    listing = await client.get(f"/projects/{SLUG}/documents")
    assert listing.status_code == 200
    docs_by_id = {d["id"]: d for d in listing.json()}
    assert doc_id in docs_by_id
    assert docs_by_id[doc_id]["ingested"] is False
