# api/services/ingest_service.py
import logging
from pathlib import Path

import chromadb

from api.config import get_settings
from api.database import get_connection, update_document_ingested

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}


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


async def ingest_document(slug: str, doc_id: int, file_path: str) -> None:
    """
    Background task: extract text from file, chunk, upsert to ChromaDB,
    then mark ingested=1 in SQLite. Logs and returns on any error.
    """
    path = Path(file_path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        logger.info("ingest_document: unsupported type %s, skipping", path.suffix)
        return

    settings = get_settings()
    try:
        text = _extract_text(path)
    except Exception as exc:
        logger.warning("ingest_document: text extraction failed for %s: %s", path.name, exc)
        return

    chunks = _chunk_text(text)
    if not chunks:
        logger.info("ingest_document: no text extracted from %s", path.name)
        return

    try:
        if settings.chroma_api_key:
            client = chromadb.CloudClient(
                tenant=settings.chroma_tenant,
                database=settings.chroma_database,
                api_key=settings.chroma_api_key,
            )
        else:
            client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        collection = client.get_or_create_collection(f"{slug}_docs")
        ids = [f"{path.name}::{i}" for i in range(len(chunks))]
        metadatas = [{"filename": path.name, "chunk": i} for i in range(len(chunks))]
        collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)
    except Exception as exc:
        logger.warning("ingest_document: ChromaDB upsert failed for %s: %s", path.name, exc)
        return

    try:
        async with get_connection(slug) as conn:
            await update_document_ingested(conn, doc_id=doc_id)
    except Exception as exc:
        logger.warning("ingest_document: DB update failed for doc_id=%s: %s", doc_id, exc)
