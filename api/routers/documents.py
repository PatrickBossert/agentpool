# api/routers/documents.py
import uuid
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from api.services.ingest_service import ingest_document
from api.config import get_settings
from api.database import get_connection, get_db_path, fetch_project, insert_document, fetch_documents

router = APIRouter(prefix="/projects", tags=["documents"])


def _coerce_doc(doc: dict) -> dict:
    doc = dict(doc)
    doc["ingested"] = bool(doc["ingested"])
    return doc


@router.get("/{slug}/documents")
async def list_documents(slug: str):
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
):
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
        suffix = Path(file.filename).suffix
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
            )
        except Exception:
            dest.unlink(missing_ok=True)
            raise

        docs = await fetch_documents(conn, project_id=project["id"])
        background_tasks.add_task(ingest_document, slug, doc_id, str(dest))
        return _coerce_doc(next(d for d in docs if d["id"] == doc_id))
