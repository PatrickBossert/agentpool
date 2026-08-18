# api/services/ingest_service.py
import asyncio
import logging
from pathlib import Path

from api.services.chroma_client import get_chroma_client
from api.services.knowledge_tiers import (
    DEFAULT_UPLOAD_TIER,
    UPLOADABLE_TIERS,
    collection_for,
    org_slug_for_project,
)
from api.database import (
    fetch_project,
    get_connection,
    update_document_ingest_failed,
    update_document_ingested,
)

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


def ingest_collection(slug: str, tier: str, *, sector: str = "") -> str:
    """The one store an ingestion at `tier` writes into. Raises rather than widening.

    **A project ingestion cannot write `org_` or `sector_`, whatever it is asked for.** That
    is structural rather than checked: the project branch passes neither a sector nor an
    org_slug to `collection_for`, so there is nothing for either to resolve to, and the only
    lever any caller has on this function is a closed vocabulary of three tiers that defaults
    to the narrowest. No caller anywhere hands the ingest path a collection *name*.

    Broadening is therefore never a side effect of an ingestion - it takes a caller who
    declared a broader tier at a door that checked their authority for that destination
    (`knowledge_tiers.assert_may_write_tier`). `interviews` is refused here as everywhere: a
    document filed into the interview store would be retrieved with an answer's provenance.

    Shared with the delete door, which resolves the collection to purge through this same
    function. A delete that addressed a different store from the write is the exact shape of
    the defect Task 1 found at `documents.py:127` - and two resolutions could not stay in
    agreement.
    """
    if tier not in UPLOADABLE_TIERS:
        raise ValueError(
            f"Cannot ingest a document at the {tier!r} tier. Valid tiers are: "
            f"{', '.join(UPLOADABLE_TIERS)}."
        )
    if tier == "project":
        return collection_for("project", slug=slug)
    if tier == "organisation":
        return collection_for("organisation", slug=slug, org_slug=org_slug_for_project(slug))
    return collection_for("sector", slug=slug, sector=sector)


def chunk_filter_for(slug: str, doc_id: int, tier: str) -> dict:
    """The Chroma `where` that selects exactly this document's chunks in `tier`'s store.

    At the project tier the collection is already this project and nothing else, and legacy
    chunks - everything ingested before this branch - carry no `slug` metadata at all, so a
    filter naming it would match none of them and a delete would remove nothing. At the
    broader tiers the store is shared between projects, `doc_id` is a per-project SQLite id,
    and nothing was ever written there before this branch, so the pair is both necessary and
    always present.
    """
    if tier == "project":
        return {"doc_id": doc_id}
    return {"$and": [{"doc_id": doc_id}, {"slug": slug}]}


async def resolve_ingest_collection(slug: str, tier: str) -> str:
    """`ingest_collection` with the project's own sector fetched for the sector tier.

    Async because the sector lives in the project database; the synchronous half is kept
    separate so the rule itself can be asserted without one.
    """
    sector = ""
    if tier == "sector":
        async with get_connection(slug) as conn:
            project = await fetch_project(conn, slug=slug)
        sector = (project or {}).get("sector") or ""
    return await asyncio.to_thread(ingest_collection, slug, tier, sector=sector)


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
    slug: str,
    doc_id: int,
    file_path: str,
    *,
    raise_on_error: bool = False,
    tier: str = DEFAULT_UPLOAD_TIER,
) -> None:
    """Extract text, chunk, upsert to ChromaDB, then mark ingested=1 in SQLite.

    raise_on_error=True makes every failure raise IngestError. Callers that await
    this in a request path need that: if indexing is the only route to a document
    being usable, a silent failure leaves a document that looks uploaded and is
    permanently invisible. Background callers keep the default and only log.

    `tier` names the knowledge store the chunks land in and defaults to `project`, the
    narrowest - see `ingest_collection` for why that default is the whole rule. A caller
    passing a broader tier has already been checked for authority over that destination at
    its door; a caller passing nothing writes this project's own store and can write nothing
    else.
    """
    path = Path(file_path)

    async def _fail(
        message: str, exc: Exception | None = None, *, raising: bool = True
    ) -> None:
        """Log it, record it on the document, and raise if the caller asked.

        Recording is what makes the failure visible. A background task cannot return an
        error to a request that has already responded, so the log was the only trace - and
        the row went on saying "pending", indistinguishable from not yet started, through
        three permanent failures.

        `raising=False` records the state without raising, for outcomes that are terminal
        for the document but not errors of the upload. Recording and raising are separate
        decisions, and conflating them either hides a dead document or fails a request that
        genuinely succeeded.
        """
        logger.warning("ingest_document: %s", message)
        try:
            async with get_connection(slug) as conn:
                await update_document_ingest_failed(conn, doc_id=doc_id, error=message)
        except Exception:
            # Never mask the original failure with a bookkeeping one - the message above is
            # the thing worth having, and it is already logged.
            logger.exception("ingest_document: could not record failure for doc_id=%s", doc_id)
        if raise_on_error and raising:
            raise IngestError(message) from exc

    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        logger.info("ingest_document: unsupported type %s, skipping", path.suffix)
        return

    # Resolved before a byte is read, so a tier that cannot be honoured - an unknown one, or
    # the organisation tier on a project belonging to no organisation - costs a recorded
    # failure and reaches no store at all, rather than being discovered halfway through an
    # upsert into somewhere.
    try:
        collection_name = await resolve_ingest_collection(slug, tier)
    except ValueError as exc:
        return await _fail(
            f"cannot ingest {path.name} at the {tier!r} tier: {exc}", exc
        )

    try:
        text = await asyncio.to_thread(_extract_text, path)
    except Exception as exc:
        return await _fail(f"text extraction failed for {path.name}: {exc}", exc)

    chunks = _chunk_text(text)
    if not chunks:
        # Recorded, not raised. An image-only PDF is a real upload that yields nothing to
        # index: failing the request would make every scan an unexplained 502, which an
        # earlier decision deliberately ruled out. But an early return left the row saying
        # "pending" for ever, with nothing to retry and nothing to read, so the state is
        # written even though the upload stands.
        return await _fail(
            f"no text could be extracted from {path.name} - if it is a scan, it needs OCR "
            "before it can be indexed",
            raising=False,
        )

    def _upsert() -> None:
        client = get_chroma_client(slug)
        collection = client.get_or_create_collection(collection_name)
        ids = [f"{path.name}::{i}" for i in range(len(chunks))]
        # `slug` is carried on every chunk because `doc_id` is a per-project SQLite id and
        # the organisation and sector stores are shared: two projects will hold a document 7
        # apiece, and a delete filtering on doc_id alone would take both. See
        # `chunk_filter_for` - the delete door filters on the pair everywhere the collection
        # is not already project-scoped.
        metadatas = [
            {"filename": path.name, "chunk": i, "doc_id": doc_id, "slug": slug}
            for i in range(len(chunks))
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
        return await _fail(f"ChromaDB upsert failed for {path.name}: {exc}", exc)

    try:
        async with get_connection(slug) as conn:
            await update_document_ingested(conn, doc_id=doc_id)
    except Exception as exc:
        return await _fail(f"DB update failed for doc_id={doc_id}: {exc}", exc)
