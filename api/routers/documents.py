# api/routers/documents.py
import asyncio
import uuid
from pathlib import Path
from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile,
)
from api.auth import require_any_auth, require_org_admin_or_above, check_project_access
from api.services.authority_service import require_writable_tier
from api.services.ingest_service import (
    chunk_filter_for,
    ingest_document,
    resolve_ingest_collection,
)
from api.services.knowledge_tiers import DEFAULT_UPLOAD_TIER
from api.config import get_settings
from api.database import get_connection, get_db_path, fetch_project, insert_document, fetch_documents, fetch_document, delete_document

router = APIRouter(prefix="/projects", tags=["documents"])


def _coerce_doc(doc: dict) -> dict:
    doc = dict(doc)
    doc["ingested"] = bool(doc["ingested"])
    return doc


def _tier_of(doc: dict) -> str:
    """The knowledge tier a document was filed at.

    `project` for a row that predates the column, and that is a fact rather than a fallback:
    until this branch there was no other store anything could be written into, so every
    document without the column is in `{slug}_docs` by construction.
    """
    return doc.get("knowledge_tier") or DEFAULT_UPLOAD_TIER


@router.get("/{slug}/documents")
async def list_documents(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return [_coerce_doc(d) for d in await fetch_documents(conn, project_id=project["id"])]


@router.post("/{slug}/documents/upload", status_code=201)
async def upload_document(
    slug: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    tier: str = Form(DEFAULT_UPLOAD_TIER),
    payload: dict = Depends(require_org_admin_or_above),
):
    """Add a document to this project, at a declared knowledge tier.

    The tier defaults to `project` - the narrowest - so an upload that says nothing about
    tiers is readable by this project alone. Anything broader is a deliberate act needing
    authority for the destination, which `require_writable_tier` decides; this door only
    turns its refusal into a status code.

    The slug is passed because the destination is a store, not a tier name: an org_admin may
    write *their own* organisation's, and which one that is depends on the project. See the
    rule's own commentary in authority_service.
    """
    await check_project_access(slug, payload)
    await require_writable_tier(slug, tier, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

        settings = get_settings()
        docs_dir = Path(settings.projects_dir) / slug / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        # Unique filename to prevent collisions
        suffix = Path(file.filename or "").suffix
        unique_name = f"{uuid.uuid4().hex}{suffix}"
        dest = docs_dir / unique_name

        content = await file.read()
        dest.write_bytes(content)

        try:
            doc_id = await insert_document(
                conn,
                project_id=project["id"],
                filename=unique_name,
                original_name=file.filename,
                file_path=str(dest),
                content_type=file.content_type or "application/octet-stream",
                size_bytes=len(content),
                knowledge_tier=tier,
            )
        except Exception:
            dest.unlink(missing_ok=True)
            raise

        docs = await fetch_documents(conn, project_id=project["id"])
        background_tasks.add_task(ingest_document, slug, doc_id, str(dest), tier=tier)
        return _coerce_doc(next(d for d in docs if d["id"] == doc_id))


@router.post("/{slug}/documents/{doc_id}/reingest", status_code=202)
async def reingest_document(
    slug: str,
    doc_id: int,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(require_org_admin_or_above),
):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        doc = await fetch_document(conn, doc_id=doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    # The tier comes off the row, not from the caller and not from a default: a reingest is a
    # retry of a write that already declared where it belongs, and re-deciding it here would
    # let a retry quietly move an organisation document into the project store - the one-way
    # rule broken by a button labelled "retry".
    background_tasks.add_task(
        ingest_document, slug, doc_id, doc["file_path"], tier=_tier_of(doc)
    )
    return {"queued": True}


@router.delete("/{slug}/documents/{doc_id}", status_code=204)
async def delete_document_endpoint(
    slug: str,
    doc_id: int,
    payload: dict = Depends(require_org_admin_or_above),
):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    async with get_connection(slug) as conn:
        doc = await fetch_document(conn, doc_id=doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # The chunks go first, and a failure refuses the delete rather than reporting one.
    #
    # This block used to be `except Exception: pass` around a hand-built `f"{slug}_docs"`, so
    # a wrong collection name deleted **nothing and said nothing** - the row and the file went
    # and every chunk stayed retrievable, which is the worst possible outcome for the one
    # operation an operator performs precisely because material should no longer be findable.
    # Two changes, and both are needed: the name now comes from the same resolver the write
    # used, so the delete cannot address a different store from the ingest; and the failure is
    # a 502 the caller sees.
    #
    # Ordered ahead of the row and the file because the row is the only handle a retry has. A
    # 502 raised after the row was gone would leave chunks nobody can name, let alone remove -
    # trading a silent failure for an unrecoverable one.
    if doc["ingested"]:
        collection_name = await resolve_ingest_collection(slug, _tier_of(doc))

        def _purge() -> None:
            from api.services.chroma_client import get_chroma_client
            # Resolved per project, exactly as the upload path does: a raw CloudClient here
            # would delete from the cloud for a project whose chunks were indexed locally.
            client = get_chroma_client(slug)
            collection = client.get_or_create_collection(name=collection_name)
            collection.delete(where=chunk_filter_for(slug, doc_id, _tier_of(doc)))

        try:
            await asyncio.to_thread(_purge)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Document {doc_id} could not be removed from the search index "
                    f"('{collection_name}': {exc}), so it has NOT been deleted - its text "
                    f"would otherwise stay retrievable by every agent on this project. "
                    f"Retry the delete once ChromaDB is reachable."
                ),
            )

    async with get_connection(slug) as conn:
        deleted = await delete_document(conn, doc_id=doc_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove file from disk
    Path(doc["file_path"]).unlink(missing_ok=True)

    return Response(status_code=204)
