# api/routers/agent_chat.py
"""POST /projects/{slug}/agent-chat — interactive agent chat endpoint."""
import asyncio
import ipaddress
import json
import re
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from api.auth import check_project_access, require_any_auth
from api.config import get_settings
from api.database import (
    fetch_project,
    get_connection,
    get_db_path,
    insert_document,
    update_project_config,
)
from api.services.agent_chat_service import AGENT_PERSONAS, run_agent_chat
from api.services.ingest_service import SUPPORTED_SUFFIXES, _extract_text, ingest_document

router = APIRouter(prefix="/projects", tags=["agent-chat"])

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_UPLOAD_SUFFIXES = SUPPORTED_SUFFIXES | _IMAGE_SUFFIXES
_PREVIEW_CHARS = 3_000


# ── Request / response models ──────────────────────────────────────────────────

class InjectedDoc(BaseModel):
    doc_id: int
    original_name: str
    preview_text: str
    is_image: bool = False


class InjectedLink(BaseModel):
    url: str
    label: str
    content_preview: str


class ChatRequest(BaseModel):
    agent_name: str
    message: str
    history: list[dict] = []
    injected_docs: list[InjectedDoc] = []
    injected_links: list[InjectedLink] = []


class LinkRequest(BaseModel):
    agent_name: str
    url: str
    label: str = ""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def _assert_public_url(url: str) -> None:
    """Raise ValueError for any URL that could reach a private/internal host (SSRF guard)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"URL scheme must be http or https, got {parsed.scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    def _resolve() -> list:
        return socket.getaddrinfo(hostname, None)

    try:
        results = await asyncio.to_thread(_resolve)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname '{hostname}': {exc}") from exc

    for _fam, _type, _proto, _canon, sockaddr in results:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError("URL resolves to a disallowed (private/internal) address")


async def _patch_config(conn, project: dict, key: str, value) -> None:
    """Merge a single key into the project's config_json and persist."""
    config = json.loads(project.get("config_json") or "{}")
    config[key] = value
    await update_project_config(
        conn,
        project_id=project["id"],
        llm_mode=project["llm_mode"],
        sector=project.get("sector") or "",
        config_json=json.dumps(config),
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/{slug}/agent-chat")
async def agent_chat(
    slug: str,
    body: ChatRequest,
    payload: dict = Depends(require_any_auth),
):
    await check_project_access(slug, payload)

    if body.agent_name not in AGENT_PERSONAS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {body.agent_name!r}")

    result = await run_agent_chat(
        slug,
        body.agent_name,
        body.message,
        body.history,
        injected_docs=[d.model_dump() for d in body.injected_docs],
        injected_links=[lnk.model_dump() for lnk in body.injected_links],
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    return {"response": result}


@router.post("/{slug}/agent-chat/upload", status_code=201)
async def chat_upload(
    slug: str,
    background_tasks: BackgroundTasks,
    agent_name: str = Form(...),
    file: UploadFile = File(...),
    payload: dict = Depends(require_any_auth),
):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{suffix}'. Supported: {', '.join(sorted(_UPLOAD_SUFFIXES))}",
        )

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

        settings = get_settings()
        docs_dir = Path(settings.projects_dir) / slug / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        unique_name = f"{uuid.uuid4().hex}{suffix}"
        dest = docs_dir / unique_name

        content = await file.read()
        dest.write_bytes(content)

        try:
            doc_id = await insert_document(
                conn,
                project_id=project["id"],
                filename=unique_name,
                original_name=file.filename or unique_name,
                file_path=str(dest),
                content_type=file.content_type or "application/octet-stream",
                size_bytes=len(content),
            )
        except Exception:
            dest.unlink(missing_ok=True)
            raise

        # Auto-enable in discovery_document_ids
        config = json.loads(project.get("config_json") or "{}")
        doc_ids: list[int] = config.get("discovery_document_ids", [])
        if doc_id not in doc_ids:
            doc_ids.append(doc_id)
            await _patch_config(conn, project, "discovery_document_ids", doc_ids)

    is_image = suffix in _IMAGE_SUFFIXES
    preview_text = ""

    if not is_image and suffix in SUPPORTED_SUFFIXES:
        try:
            text = await asyncio.to_thread(_extract_text, dest)
            preview_text = text[:_PREVIEW_CHARS]
        except Exception:
            preview_text = ""
        background_tasks.add_task(ingest_document, slug, doc_id, str(dest))
    else:
        preview_text = f"[Image file: {file.filename}]"

    return {
        "doc_id": doc_id,
        "filename": unique_name,
        "original_name": file.filename or unique_name,
        "preview_text": preview_text,
        "is_image": is_image,
    }


@router.post("/{slug}/agent-chat/link")
async def chat_add_link(
    slug: str,
    body: LinkRequest,
    payload: dict = Depends(require_any_auth),
):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    label = body.label.strip() or body.url

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

        config = json.loads(project.get("config_json") or "{}")
        links: list[dict] = config.get("discovery_links", [])
        existing_urls = {lnk.get("url") for lnk in links}
        if body.url not in existing_urls:
            links.append({"url": body.url, "label": label})
            await _patch_config(conn, project, "discovery_links", links)

    content_preview = ""
    try:
        await _assert_public_url(body.url)
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            resp = await client.get(body.url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            content_preview = _strip_html(resp.text)[:_PREVIEW_CHARS]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        content_preview = f"[Could not fetch content from {body.url}]"

    return {"url": body.url, "label": label, "content_preview": content_preview}
