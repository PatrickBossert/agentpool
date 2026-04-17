# tests/test_ingest_service.py
"""Unit tests for api.services.ingest_service."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chroma_mock():
    """Return a mock chromadb.HttpClient whose get_or_create_collection works."""
    collection = MagicMock()
    collection.upsert = MagicMock()
    client = MagicMock()
    client.get_or_create_collection = MagicMock(return_value=collection)
    return client, collection


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_chunk_text_overlap_gte_chunk_size_raises():
    """_chunk_text must raise ValueError when overlap >= chunk_size to prevent infinite loop."""
    from api.services.ingest_service import _chunk_text

    with pytest.raises(ValueError, match="overlap"):
        _chunk_text("hello", chunk_size=10, overlap=10)


@pytest.mark.asyncio
async def test_unsupported_extension_skips(tmp_path):
    """A .zip file should be silently skipped — no ChromaDB call, ingested stays 0."""
    zip_file = tmp_path / "archive.zip"
    zip_file.write_bytes(b"PK...")

    with patch("api.services.ingest_service.chromadb") as mock_chroma, \
         patch("api.services.ingest_service.update_document_ingested", new_callable=AsyncMock) as mock_db:
        from api.services.ingest_service import ingest_document
        await ingest_document("test-slug", doc_id=1, file_path=str(zip_file))

    mock_chroma.HttpClient.assert_not_called()
    mock_db.assert_not_called()


@pytest.mark.asyncio
async def test_text_extraction_failure_leaves_ingested_false(tmp_path):
    """If _extract_text raises, function returns without touching ChromaDB or DB."""
    bad_pdf = tmp_path / "broken.pdf"
    bad_pdf.write_bytes(b"not a real pdf")

    chroma_client, _ = _make_chroma_mock()
    with patch("api.services.ingest_service.chromadb") as mock_chroma, \
         patch("api.services.ingest_service.update_document_ingested", new_callable=AsyncMock) as mock_db, \
         patch("api.services.ingest_service._extract_text", side_effect=Exception("parse error")):
        mock_chroma.HttpClient.return_value = chroma_client
        from api.services.ingest_service import ingest_document
        await ingest_document("test-slug", doc_id=2, file_path=str(bad_pdf))

    mock_db.assert_not_called()


@pytest.mark.asyncio
async def test_chroma_unavailable_leaves_ingested_false(tmp_path):
    """If ChromaDB raises on connect, function returns without updating DB."""
    txt_file = tmp_path / "report.txt"
    txt_file.write_text("Some important content here.")

    with patch("api.services.ingest_service.chromadb") as mock_chroma, \
         patch("api.services.ingest_service.update_document_ingested", new_callable=AsyncMock) as mock_db:
        mock_chroma.HttpClient.side_effect = Exception("connection refused")
        mock_chroma.CloudClient.side_effect = Exception("connection refused")
        from api.services.ingest_service import ingest_document
        await ingest_document("test-slug", doc_id=3, file_path=str(txt_file))

    mock_db.assert_not_called()


@pytest.mark.asyncio
async def test_happy_path_txt(tmp_path):
    """.txt file: chunks upserted and ingested flag set to 1."""
    txt_file = tmp_path / "brief.txt"
    txt_file.write_text("Client briefing document. " * 50)  # >200 chars to get 1+ chunks

    chroma_client, collection = _make_chroma_mock()
    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    with patch("api.services.ingest_service.chromadb") as mock_chroma, \
         patch("api.services.ingest_service.update_document_ingested", new_callable=AsyncMock) as mock_db, \
         patch("api.services.ingest_service.get_connection", return_value=mock_conn):
        mock_chroma.HttpClient.return_value = chroma_client
        from api.services.ingest_service import ingest_document
        await ingest_document("test-slug", doc_id=4, file_path=str(txt_file))

    collection.upsert.assert_called_once()
    call_kwargs = collection.upsert.call_args
    assert len(call_kwargs.kwargs["documents"]) >= 1
    assert call_kwargs.kwargs["ids"][0].startswith("brief.txt::")
    mock_db.assert_awaited_once_with(mock_conn, doc_id=4)


@pytest.mark.asyncio
async def test_happy_path_docx(tmp_path):
    """.docx file: python-docx path exercised, chunks upserted, flag set."""
    from docx import Document as DocxDocument
    docx_path = tmp_path / "proposal.docx"
    doc = DocxDocument()
    for _ in range(10):
        doc.add_paragraph("This is a paragraph about digital transformation strategy.")
    doc.save(str(docx_path))

    chroma_client, collection = _make_chroma_mock()
    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    with patch("api.services.ingest_service.chromadb") as mock_chroma, \
         patch("api.services.ingest_service.update_document_ingested", new_callable=AsyncMock) as mock_db, \
         patch("api.services.ingest_service.get_connection", return_value=mock_conn):
        mock_chroma.HttpClient.return_value = chroma_client
        from api.services.ingest_service import ingest_document
        await ingest_document("test-slug", doc_id=5, file_path=str(docx_path))

    collection.upsert.assert_called_once()
    mock_db.assert_awaited_once_with(mock_conn, doc_id=5)
