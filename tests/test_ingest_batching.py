# tests/test_ingest_batching.py
"""Chroma caps records per Upsert action, so a large document must go in batches.

SPUK_2025_Annual_Accounts.pdf chunked to 848 records and was sent in one call against a
300-record-per-action limit. Chroma rejected the whole call atomically, nothing was written,
and the document sat on "pending" for ever - there is no failed state to show, only
`ingested = 0`.

The store held 48 records at the time, which is what proves this is a per-call batch limit
rather than a storage quota: total usage was nowhere near the cap and it still failed.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from api.services.ingest_service import UPSERT_BATCH, ingest_document

# Enough text to chunk well past the cap. _chunk_text steps 800 characters per chunk
# (1000 with 200 overlap), so this is roughly 500 chunks - the document that broke this made
# 848, and a fixture under the cap could not fail either way.
BIG_TEXT = "Asset condition data is recorded inconsistently across depots. " * 6500


@pytest.fixture
def big_file(tmp_path) -> Path:
    path = tmp_path / "annual_accounts.txt"
    path.write_text(BIG_TEXT)
    return path


def _collection(client: MagicMock) -> MagicMock:
    collection = MagicMock()
    client.get_or_create_collection.return_value = collection
    return collection


def test_the_batch_size_stays_under_chromas_limit():
    # Pinned: the whole defect is one number being too large.
    assert UPSERT_BATCH <= 300


@pytest.mark.asyncio
async def test_a_large_document_is_upserted_in_batches(big_file, monkeypatch):
    client = MagicMock()
    collection = _collection(client)

    async def _noop_update(*args, **kwargs):
        return None

    with patch("api.services.ingest_service.get_chroma_client", return_value=client), \
         patch("api.services.ingest_service.get_connection"), \
         patch("api.services.ingest_service.update_document_ingested", _noop_update):
        await ingest_document("acme", 3, str(big_file))

    calls = collection.upsert.call_args_list
    assert len(calls) > 1, "sent in one call - this is the defect"
    for _, kwargs in calls:
        assert len(kwargs["ids"]) <= UPSERT_BATCH


@pytest.mark.asyncio
async def test_batching_loses_no_chunk_and_duplicates_none(big_file):
    """A batch loop that drops the tail, or overlaps its slices, would still pass the size
    assertion above while silently indexing the wrong document."""
    client = MagicMock()
    collection = _collection(client)

    async def _noop_update(*args, **kwargs):
        return None

    with patch("api.services.ingest_service.get_chroma_client", return_value=client), \
         patch("api.services.ingest_service.get_connection"), \
         patch("api.services.ingest_service.update_document_ingested", _noop_update):
        await ingest_document("acme", 3, str(big_file))

    ids, documents = [], []
    for _, kwargs in collection.upsert.call_args_list:
        ids.extend(kwargs["ids"])
        documents.extend(kwargs["documents"])
        # Each batch must stay internally consistent, or a chunk lands under another's id.
        assert len(kwargs["ids"]) == len(kwargs["documents"]) == len(kwargs["metadatas"])

    from api.services.ingest_service import _chunk_text
    expected = _chunk_text(big_file.read_text())
    assert len(ids) == len(expected)
    assert len(set(ids)) == len(ids), "an id was emitted twice"
    assert documents == expected, "chunks were reordered or dropped"


@pytest.mark.asyncio
async def test_a_batch_failure_does_not_mark_the_document_ingested(big_file):
    """Marking it ingested after a partial write is worse than the original bug: the
    document then looks indexed while most of it is absent, and nothing will retry it."""
    client = MagicMock()
    collection = _collection(client)
    collection.upsert.side_effect = [None, RuntimeError("quota exceeded")]

    marked = []

    async def _record(*args, **kwargs):
        marked.append(kwargs.get("doc_id"))

    with patch("api.services.ingest_service.get_chroma_client", return_value=client), \
         patch("api.services.ingest_service.get_connection"), \
         patch("api.services.ingest_service.update_document_ingested", _record):
        await ingest_document("acme", 3, str(big_file))

    assert marked == []


def test_the_agent_tool_batches_too(tmp_path, monkeypatch):
    """Alex ingests through his own tool, which had the identical unbatched call. Fixing only
    the upload path would leave every crew run hitting the same ceiling."""
    from agents.tools.document_ingestion import DocumentIngestionTool

    docs = tmp_path / "acme" / "docs"
    docs.mkdir(parents=True)
    (docs / "annual_accounts.txt").write_text(BIG_TEXT)

    settings = MagicMock()
    settings.projects_dir = str(tmp_path)
    settings.chroma_api_key = "test-key"

    client = MagicMock()
    collection = _collection(client)

    # Patched at the factory rather than at chromadb, because the tool no longer chooses a
    # client class itself - which client a project gets is decided by get_chroma_client, and
    # tested in tests/test_secure_mode_document_paths.py. This test is about batching only.
    with patch("agents.tools.document_ingestion.get_settings", return_value=settings), \
         patch("agents.tools.document_ingestion.get_chroma_client", return_value=client):
        DocumentIngestionTool(slug="acme")._run(filename=None)

    calls = collection.upsert.call_args_list
    assert len(calls) > 1, "the agent tool still sends one call"
    for _, kwargs in calls:
        assert len(kwargs["ids"]) <= UPSERT_BATCH
