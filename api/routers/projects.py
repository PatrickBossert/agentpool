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
from api.services.auto_assign_service import (
    auto_assign_interview_scripts,
    auto_assign_questionnaire_scripts,
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


import re as _re

# SVG excluded: same-origin SVG can execute embedded scripts (XSS)
SAFE_OUTPUT_EXTENSIONS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
_SLUG_RE = _re.compile(r'^[a-z0-9][a-z0-9_-]*$')


@router.get("/{slug}/output-files/{filename}")
async def serve_output_file(slug: str, filename: str, payload: dict = Depends(require_any_auth)):
    """Serve a static image file from the project outputs directory."""
    # Validate slug to prevent path traversal via URL segment
    if not _SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="Invalid project slug.")
    suffix = Path(filename).suffix.lower()
    if suffix not in SAFE_OUTPUT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only raster image files (.png, .jpg, .webp) can be served here.")
    # Reject any path separators or traversal sequences in the bare filename
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    outputs_root = Path(get_settings().projects_dir).resolve() / slug / "outputs"
    candidate = (outputs_root / filename).resolve()
    # Containment check: resolved candidate must remain inside outputs_root
    if not str(candidate).startswith(str(outputs_root) + "/"):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"Output file '{filename}' not found.")
    return FileResponse(
        path=candidate,
        media_type=SAFE_OUTPUT_EXTENSIONS[suffix],
        headers={"X-Content-Type-Options": "nosniff"},
    )


# ── Node Template Assignment endpoints ────────────────────────────────────────

class NodeTemplateAssignmentBody(BaseModel):
    interview_template_id: int | None = None
    questionnaire_template_id: int | None = None


class PublishNodeTemplateBody(BaseModel):
    name: str
    description: str = ""


def _load_tree_nodes(slug: str) -> list[dict]:
    """Return ordered L1+L2 nodes with id+label from registry (preferred) or tree fallback.

    L1 nodes are included so senior leaders can be assigned a strategic questionnaire.
    L3 activity nodes are excluded — they are traceable via IDs but have no own templates yet.
    """
    outputs_dir = Path(get_settings().projects_dir) / slug / "outputs"

    # Prefer the registry — it is the source of truth for stable IDs.
    registry_path = outputs_dir / "value_chain_registry.json"
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            return [
                {"activity_id": a["id"], "label": a["label"], "level": a.get("level", "L2")}
                for a in registry.get("activities", [])
                if a.get("level") in ("L1", "L2") and a.get("active", True)
            ]
        except Exception:
            pass

    # Fall back to tree file (pre-registry projects have no activity_id).
    tree_path = outputs_dir / "value_chain_tree.json"
    if not tree_path.exists():
        return []
    try:
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
        nodes: list[dict] = []
        for chain in tree:
            nodes.append({"activity_id": chain.get("id"), "label": chain["label"], "level": "L1"})
            for node in chain.get("children", []):
                nodes.append({"activity_id": node.get("id"), "label": node["label"], "level": "L2"})
        return nodes
    except Exception:
        return []


@router.get("/{slug}/node-templates")
async def list_node_templates(slug: str, payload: dict = Depends(require_any_auth)):
    """Return all node→template assignments for a project.

    If no assignments exist yet but value_chain_tree.json is present, auto-seeds
    rows for each L2 node so the Templates tab shows all nodes immediately.
    """
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        assignments = await fetch_node_template_assignments(conn, project["id"])
        if not assignments:
            for node in _load_tree_nodes(slug):
                await upsert_node_template_assignment(
                    conn, project["id"],
                    node["label"], None, None,
                    activity_id=node.get("activity_id"),
                    level=node.get("level", "L2"),
                )
            assignments = await fetch_node_template_assignments(conn, project["id"])
        else:
            # Backfill activity_id / level for rows that predate these columns.
            needs_backfill = any(
                a.get("activity_id") is None or a.get("level") is None
                for a in assignments
            )
            if needs_backfill:
                for node in _load_tree_nodes(slug):
                    if node.get("activity_id") or node.get("level"):
                        await conn.execute(
                            "UPDATE node_template_assignments "
                            "SET activity_id=COALESCE(activity_id, ?), level=COALESCE(level, ?) "
                            "WHERE project_id=? AND node_label=?",
                            (node.get("activity_id"), node.get("level", "L2"),
                             project["id"], node["label"]),
                        )
                await conn.commit()
                assignments = await fetch_node_template_assignments(conn, project["id"])
        return assignments


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


@router.get("/{slug}/value-chain-registry")
async def get_value_chain_registry(slug: str, payload: dict = Depends(require_any_auth)):
    """Return the stable activity ID registry for this project."""
    await check_project_access(slug, payload)
    registry_path = Path(get_settings().projects_dir) / slug / "outputs" / "value_chain_registry.json"
    if not registry_path.exists():
        raise HTTPException(status_code=404, detail="No activity registry found for this project")
    return json.loads(registry_path.read_text(encoding="utf-8"))


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


# ── Interview & Questionnaire Scripts ─────────────────────────────────────────

class InterviewScriptPatch(BaseModel):
    script: dict


def _scripts_path(slug: str, kind: str) -> Path:
    return Path(get_settings().projects_dir) / slug / "outputs" / f"{kind}_scripts.json"


@router.get("/{slug}/interview-scripts")
async def list_interview_scripts(slug: str, payload: dict = Depends(require_any_auth)):
    """Return all interview scripts keyed by node_label."""
    await check_project_access(slug, payload)
    p = _scripts_path(slug, "interview")
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


@router.get("/{slug}/interview-scripts/{node_label}")
async def get_interview_script(slug: str, node_label: str, payload: dict = Depends(require_any_auth)):
    """Return the interview script for a single node."""
    await check_project_access(slug, payload)
    p = _scripts_path(slug, "interview")
    if not p.exists():
        raise HTTPException(status_code=404, detail="No interview scripts found")
    scripts = json.loads(p.read_text(encoding="utf-8"))
    if node_label not in scripts:
        raise HTTPException(status_code=404, detail=f"No script for node '{node_label}'")
    return scripts[node_label]


@router.patch("/{slug}/interview-scripts/{node_label}")
async def patch_interview_script(
    slug: str, node_label: str, body: InterviewScriptPatch,
    payload: dict = Depends(require_org_admin_or_above),
):
    """Update the interview script for a node and sync to the system template."""
    await check_project_access(slug, payload)
    p = _scripts_path(slug, "interview")
    scripts = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    scripts[node_label] = {**body.script, "node_label": node_label}
    p.write_text(json.dumps(scripts, ensure_ascii=False, indent=2), encoding="utf-8")
    updated = await auto_assign_interview_scripts(slug)
    return {"ok": True, "templates_updated": updated}


@router.get("/{slug}/questionnaire-scripts")
async def list_questionnaire_scripts(slug: str, payload: dict = Depends(require_any_auth)):
    """Return all questionnaire scripts keyed by node_label."""
    await check_project_access(slug, payload)
    p = _scripts_path(slug, "questionnaire")
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))
