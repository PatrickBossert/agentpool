# api/services/ingest_service.py
import asyncio
import logging
from pathlib import Path

from api.services.chroma_client import get_chroma_client
from api.database import get_connection, update_document_ingested

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}

# Chroma caps records per Upsert ACTION, not per collection. A 1.5MB PDF chunked to 848
# records was sent in one call against a limit of 300, and the whole call was rejected
# atomically - so any document over roughly 300KB of extracted text could never ingest, on
# any plan, and sat on "pending" for ever because there is no failed state to show.
#
# 250 rather than 300 is deliberate headroom: the limit is a tenant setting rather than a
# constant of the product, and a batch sized exactly at the cap has nothing left if it moves.
UPSERT_BATCH = 250


class IngestError(Exception):
    """Raised when ingestion fails and the caller asked to be told."""


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    return path.read_text(errors="replace")


def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be less than chunk_size ({chunk_size})")
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start : start + chunk_size])
        start += chunk_size - overlap
    return [c for c in chunks if c.strip()]


async def ingest_document(
    slug: str, doc_id: int, file_path: str, *, raise_on_error: bool = False
) -> None:
    """Extract text, chunk, upsert to ChromaDB, then mark ingested=1 in SQLite.

    raise_on_error=True makes every failure raise IngestError. Callers that await
    this in a request path need that: if indexing is the only route to a document
    being usable, a silent failure leaves a document that looks uploaded and is
    permanently invisible. Background callers keep the default and only log.
    """
    path = Path(file_path)

    def _fail(message: str, exc: Exception | None = None) -> None:
        logger.warning("ingest_document: %s", message)
        if raise_on_error:
            raise IngestError(message) from exc

    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        logger.info("ingest_document: unsupported type %s, skipping", path.suffix)
        return

    try:
        text = await asyncio.to_thread(_extract_text, path)
    except Exception as exc:
        return _fail(f"text extraction failed for {path.name}: {exc}", exc)

    chunks = _chunk_text(text)
    if not chunks:
        logger.info("ingest_document: no text extracted from %s", path.name)
        return

    def _upsert() -> None:
        client = get_chroma_client()
        collection = client.get_or_create_collection(f"{slug}_docs")
        ids = [f"{path.name}::{i}" for i in range(len(chunks))]
        metadatas = [
            {"filename": path.name, "chunk": i, "doc_id": doc_id} for i in range(len(chunks))
        ]
        # Sliced rather than sent whole. A failing batch raises out of here and the caller
        # leaves the document unmarked, so a partial index is retried rather than recorded
        # as done - a document that looks ingested and is mostly absent is worse than one
        # that plainly failed.
        for start in range(0, len(chunks), UPSERT_BATCH):
            end = start + UPSERT_BATCH
            collection.upsert(
                documents=chunks[start:end],
                ids=ids[start:end],
                metadatas=metadatas[start:end],
            )

    try:
        await asyncio.to_thread(_upsert)
    except Exception as exc:
        return _fail(f"ChromaDB upsert failed for {path.name}: {exc}", exc)

    try:
        async with get_connection(slug) as conn:
            await update_document_ingested(conn, doc_id=doc_id)
    except Exception as exc:
        return _fail(f"DB update failed for doc_id={doc_id}: {exc}", exc)
