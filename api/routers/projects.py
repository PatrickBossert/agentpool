# api/routers/projects.py
import json
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from api.auth import get_token_payload, require_any_auth, require_org_admin_or_above, check_project_access
from api.config import get_settings
from api.database import (
    get_db_path, get_connection, fetch_project, fetch_outputs_by_type, update_project_config,
    fetch_node_template_assignments, upsert_node_template_assignment,
    get_system_db_path, init_system_db, insert_template,
    get_system_connection, insert_project_registry,
)
from api.models import ProjectCreate, ProjectSettings, OutputContent, StatusResponse, ProjectResponse
import aiosqlite
from api.services.project_service import (
    create_project,
    get_project_status,
    list_all_projects,
    get_project_settings,
    update_project_settings,
    get_output_content,
    get_output_file,
    get_roadmap_data,
    get_financial_summary,
    get_portfolio_register,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
async def list_projects_endpoint(payload: dict = Depends(require_any_auth)):
    return await list_all_projects(payload)


@router.post("", status_code=201)
async def create_project_endpoint(
    req: ProjectCreate,
    response: Response,
    payload: dict = Depends(require_org_admin_or_above),
):
    if get_db_path(req.client_slug).exists():
        response.status_code = 200
    result = await create_project(req)
    # Auto-register to org for org_admin
    if payload.get("role") == "org_admin":
        org_id = payload.get("org_id")
        if org_id:
            async with get_system_connection() as sys_conn:
                await insert_project_registry(
                    sys_conn,
                    slug=req.client_slug,
                    org_id=org_id,
                    display_name=req.client_slug,
                )
    return result


@router.get("/{slug}/status", response_model=StatusResponse)
async def get_status(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_project_status(slug)
    if not result:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.get("/{slug}/value-chain")
async def get_value_chain(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return await fetch_outputs_by_type(conn, project_id=project["id"], output_type="value_chain")


@router.get("/{slug}/roadmap")
async def get_roadmap(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return await fetch_outputs_by_type(conn, project_id=project["id"], output_type="roadmap")


@router.get("/{slug}/settings", response_model=ProjectSettings)
async def get_settings_endpoint(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_project_settings(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.patch("/{slug}/settings", response_model=ProjectSettings)
async def patch_settings_endpoint(slug: str, req: ProjectSettings, payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    result = await update_project_settings(slug, req)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.get("/{slug}/outputs/{output_id}/content", response_model=OutputContent)
async def get_output_content_endpoint(slug: str, output_id: int, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_output_content(slug, output_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Output {output_id} not found for project '{slug}'")
    if result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Output file not found on disk")
    return result


_CONTENT_TYPES = {
    ".md":   "text/markdown",
    ".html": "text/html",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


@router.get("/{slug}/outputs/{output_id}/download")
async def download_output_endpoint(slug: str, output_id: int, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_output_file(slug, output_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Output {output_id} not found for project '{slug}'")
    if result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Output file not found on disk")
    file_path: Path = result["file_path"]
    filename: str = result["filename"]
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=_content_type(file_path),
        headers={"X-Filename": filename},
    )


@router.get("/{slug}/roadmap-data")
async def get_roadmap_data_endpoint(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_roadmap_data(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No roadmap data found for project '{slug}'")
    if isinstance(result, dict) and result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Roadmap data file not found on disk")
    return result


@router.get("/{slug}/financial-summary")
async def get_financial_summary_endpoint(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_financial_summary(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No financial model found for project '{slug}'")
    if isinstance(result, dict) and result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Financial model file not found on disk")
    return result


@router.get("/{slug}/portfolio-register")
async def get_portfolio_register_endpoint(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_portfolio_register(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


_IMAGE_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

_MAX_IMAGE_SIZE = 2 * 1024 * 1024  # 2 MB


@router.post("/{slug}/branding/image")
async def upload_branding_image(
    slug: str,
    file: UploadFile = File(...),
    _user: dict = Depends(get_token_payload),
):
    """Upload a header image for the project branding."""
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

        # Validate content type
        content_type = file.content_type or ""
        if content_type not in _IMAGE_CONTENT_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported image type '{content_type}'. Must be image/png, image/jpeg, or image/webp.",
            )

        # Read and validate size
        data = await file.read()
        if len(data) > _MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=422,
                detail="Image exceeds maximum allowed size of 2 MB.",
            )

        # Magic-byte content-type verification
        MAGIC_BYTES = {
            "image/png": b"\x89PNG",
            "image/jpeg": b"\xff\xd8",
            "image/webp": b"RIFF",
        }
        if not data[:4].startswith(MAGIC_BYTES.get(file.content_type, b"")):
            raise HTTPException(status_code=422, detail="File content does not match declared content type")

        # Save file
        ext = _IMAGE_CONTENT_TYPES[content_type]
        assets_dir = Path(get_settings().projects_dir) / slug / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        file_path = assets_dir / f"header{ext}"

        # Remove any previously stored header images with different extensions
        for old_ext in [".png", ".jpg", ".webp"]:
            old_path = assets_dir / f"header{old_ext}"
            if old_path != file_path and old_path.exists():
                old_path.unlink()

        file_path.write_bytes(data)

        # Update brand_header_image_url in project config
        raw = project.get("config_json") or "{}"
        config = json.loads(raw)
        image_url = f"/api/projects/{slug}/branding/image"
        config["brand_header_image_url"] = image_url
        await update_project_config(
            conn,
            project_id=project["id"],
            llm_mode=project["llm_mode"],
            sector=project["sector"],
            config_json=json.dumps(config),
        )

    return {"url": image_url}


@router.get("/{slug}/branding/image")
async def get_branding_image(slug: str):
    """Serve the project header branding image. No auth required."""
    assets_dir = Path(get_settings().projects_dir) / slug / "assets"
    # Try each supported extension
    for ext, ct in ((".png", "image/png"), (".jpg", "image/jpeg"), (".webp", "image/webp")):
        candidate = assets_dir / f"header{ext}"
        if candidate.exists():
            return FileResponse(path=candidate, media_type=ct)
    raise HTTPException(status_code=404, detail="No branding image found for this project.")


# ── Node Template Assignment endpoints ────────────────────────────────────────

class NodeTemplateAssignmentBody(BaseModel):
    interview_template_id: int | None = None
    questionnaire_template_id: int | None = None


class PublishNodeTemplateBody(BaseModel):
    name: str
    description: str = ""


@router.get("/{slug}/node-templates")
async def list_node_templates(slug: str, payload: dict = Depends(require_any_auth)):
    """Return all node→template assignments for a project."""
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return await fetch_node_template_assignments(conn, project["id"])


@router.put("/{slug}/node-templates/{node_label}")
async def upsert_node_template(slug: str, node_label: str, body: NodeTemplateAssignmentBody, payload: dict = Depends(require_org_admin_or_above)):
    """Create or update the template assignment for a node label."""
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        await upsert_node_template_assignment(
            conn,
            project["id"],
            node_label,
            body.interview_template_id,
            body.questionnaire_template_id,
        )
    return {"ok": True}


@router.post("/{slug}/node-templates/{node_label}/publish")
async def publish_node_template(slug: str, node_label: str, body: PublishNodeTemplateBody, payload: dict = Depends(require_org_admin_or_above)):
    """Publish an interview script for a node as a reusable template."""
    scripts_path = Path(get_settings().projects_dir) / slug / "outputs" / "interview_scripts.json"
    if not scripts_path.exists():
        raise HTTPException(status_code=404, detail="interview_scripts.json not found for this project")

    scripts = json.loads(scripts_path.read_text(encoding="utf-8"))
    if node_label not in scripts:
        raise HTTPException(status_code=404, detail=f"Node '{node_label}' not found in interview_scripts.json")

    entry = dict(scripts[node_label])
    # Strip non-template fields, keep only template-compatible ones
    for field in ("node_label", "level", "research_brief", "study_objectives"):
        entry.pop(field, None)

    schema_json = json.dumps(entry)

    sys_path = get_system_db_path()
    sys_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(sys_path)) as sys_conn:
        sys_conn.row_factory = aiosqlite.Row
        await init_system_db(sys_conn)
        template_id = await insert_template(sys_conn, body.name, body.description, "interview", schema_json)

    return {"template_id": template_id}
