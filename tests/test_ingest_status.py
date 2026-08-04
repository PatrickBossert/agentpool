# tests/test_ingest_status.py
"""A failed ingest says so, and says why.

client_documents held only `ingested` (0 or 1), so the UI could say "pending" and nothing
else - whether ingestion had not run, was running, or had failed permanently. A 1.5MB PDF
failed three times against Chroma's per-action record limit, each failure logging a warning
nobody would see, and the document read as merely waiting for a day.
"""
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from api.database import (
    fetch_document,
    get_connection,
    insert_document,
    insert_project,
    update_document_ingest_failed,
    update_document_ingested,
)
from api.services.ingest_service import ingest_document

SLUG = "ingest-status-test"
QUOTA_ERROR = (
    "Quota exceeded: 'Number of records' exceeded quota limit for action 'Upsert': "
    "current usage of 848 exceeds limit of 300"
)


@pytest_asyncio.fixture
async def doc(tmp_path, monkeypatch):
    """A project and one uploaded document, in this test's own database."""
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))

    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
        rows = await conn.execute_fetchall("SELECT id FROM projects WHERE slug=?", (SLUG,))
        project_id = rows[0][0]
        doc_id = await insert_document(
            conn, project_id=project_id, filename="a.pdf", original_name="Annual.pdf",
            file_path=str(tmp_path / "a.pdf"), content_type="application/pdf",
            size_bytes=1505860,
        )
    yield doc_id
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_new_document_starts_pending(doc):
    async with get_connection(SLUG) as conn:
        row = await fetch_document(conn, doc_id=doc)
    assert row["ingest_status"] == "pending"
    assert row["ingest_error"] is None


@pytest.mark.asyncio
async def test_success_records_ingested_with_no_error(doc):
    async with get_connection(SLUG) as conn:
        await update_document_ingested(conn, doc_id=doc)
        row = await fetch_document(conn, doc_id=doc)
    assert row["ingest_status"] == "ingested"
    assert row["ingest_error"] is None
    assert row["ingested"] == 1


@pytest.mark.asyncio
async def test_failure_records_the_reason(doc):
    """The whole point. "Pending" told a reader nothing; the quota message tells them the
    document is too large for one call, which is the thing they need to know."""
    async with get_connection(SLUG) as conn:
        await update_document_ingest_failed(conn, doc_id=doc, error=QUOTA_ERROR)
        row = await fetch_document(conn, doc_id=doc)
    assert row["ingest_status"] == "failed"
    assert "Quota exceeded" in row["ingest_error"]
    assert row["ingested"] == 0


@pytest.mark.asyncio
async def test_a_retry_after_failure_clears_the_reason(doc):
    """A stale error beside a green status is worse than no error - a reader trusts the
    older, louder signal."""
    async with get_connection(SLUG) as conn:
        await update_document_ingest_failed(conn, doc_id=doc, error=QUOTA_ERROR)
        await update_document_ingested(conn, doc_id=doc)
        row = await fetch_document(conn, doc_id=doc)
    assert row["ingest_status"] == "ingested"
    assert row["ingest_error"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("apply,expected_flag", [
    (update_document_ingested, 1),
    (lambda conn, *, doc_id: update_document_ingest_failed(conn, doc_id=doc_id, error="x"), 0),
])
async def test_status_and_the_ingested_flag_never_disagree(doc, apply, expected_flag):
    """Two columns describing one fact drift the moment either has its own writer. Both go
    through one function, and this is what holds that."""
    async with get_connection(SLUG) as conn:
        await apply(conn, doc_id=doc)
        row = await fetch_document(conn, doc_id=doc)
    assert row["ingested"] == expected_flag
    assert (row["ingest_status"] == "ingested") == bool(row["ingested"])


@pytest.mark.asyncio
async def test_a_chroma_failure_reaches_the_document_row(doc, tmp_path):
    """End to end through ingest_document, not just the helper: the helper existing and the
    service calling it are different facts, and only the second one shows a user anything."""
    # .txt, not .pdf: writing plain text to a .pdf fails at extraction, so the upsert this
    # test exists to exercise would never be reached and it would pass for the wrong reason.
    source = tmp_path / "a.txt"
    source.write_text("Asset condition data is recorded inconsistently. " * 400)

    client = MagicMock()
    collection = MagicMock()
    client.get_or_create_collection.return_value = collection
    collection.upsert.side_effect = RuntimeError(QUOTA_ERROR)

    with patch("api.services.ingest_service.get_chroma_client", return_value=client):
        await ingest_document(SLUG, doc, str(source))

    async with get_connection(SLUG) as conn:
        row = await fetch_document(conn, doc_id=doc)
    assert row["ingest_status"] == "failed"
    assert "Quota exceeded" in row["ingest_error"]


@pytest.mark.asyncio
async def test_an_unreadable_file_also_reports_why(doc, tmp_path):
    """Extraction failure is the other way a document dies silently - a corrupt PDF looked
    exactly like a quota rejection, which is to say like nothing at all."""
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"not a pdf")

    await ingest_document(SLUG, doc, str(source))

    async with get_connection(SLUG) as conn:
        row = await fetch_document(conn, doc_id=doc)
    assert row["ingest_status"] == "failed"
    assert row["ingest_error"]


@pytest.mark.asyncio
async def test_a_document_with_no_extractable_text_is_not_left_pending(doc, tmp_path):
    """An empty scan produced no chunks and returned early, so the row stayed pending for
    ever with nothing to retry and nothing to read."""
    source = tmp_path / "empty.txt"
    source.write_text("   \n  \n")

    await ingest_document(SLUG, doc, str(source))

    async with get_connection(SLUG) as conn:
        row = await fetch_document(conn, doc_id=doc)
    assert row["ingest_status"] == "failed"
    assert "no text" in row["ingest_error"].lower()


@pytest.mark.asyncio
async def test_no_extractable_text_is_recorded_but_does_not_raise(doc, tmp_path):
    """Recording and raising are separate decisions.

    An image-only PDF is a real upload that yields nothing to index. An earlier decision
    ruled that it must not fail the request - every scan would become an unexplained 502 -
    and that still holds. What changed is that the document no longer reads as pending
    afterwards, because the outcome is terminal even though the upload succeeded.
    """
    source = tmp_path / "scan.txt"
    source.write_text("   \n ")

    # raise_on_error=True is the chat upload path, which awaits this inside the request.
    await ingest_document(SLUG, doc, str(source), raise_on_error=True)

    async with get_connection(SLUG) as conn:
        row = await fetch_document(conn, doc_id=doc)
    assert row["ingest_status"] == "failed"
    assert "OCR" in row["ingest_error"]


@pytest.mark.asyncio
async def test_a_genuine_failure_still_raises_for_the_request_path(doc, tmp_path):
    """The other half: quota rejection is not "nothing to index", and a caller awaiting it
    in a request must still be told."""
    source = tmp_path / "a.txt"
    source.write_text("Asset condition data. " * 400)

    client = MagicMock()
    collection = MagicMock()
    client.get_or_create_collection.return_value = collection
    collection.upsert.side_effect = RuntimeError(QUOTA_ERROR)

    from api.services.ingest_service import IngestError

    with patch("api.services.ingest_service.get_chroma_client", return_value=client):
        with pytest.raises(IngestError):
            await ingest_document(SLUG, doc, str(source), raise_on_error=True)
