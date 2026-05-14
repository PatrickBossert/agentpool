# api/routers/projects.py
import json
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from api.auth import get_token_payload
from api.config import get_settings
from api.database import get_db_path, get_connection, fetch_project, fetch_outputs_by_type, update_project_config
from api.models import ProjectCreate, ProjectSettings, OutputContent, StatusResponse, ProjectResponse
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
async def list_projects_endpoint():
    return await list_all_projects()


@router.post("", status_code=201)
async def create_project_endpoint(req: ProjectCreate, response: Response):
    if get_db_path(req.client_slug).exists():
        response.status_code = 200
    return await create_project(req)


@router.get("/{slug}/status", response_model=StatusResponse)
async def get_status(slug: str):
    result = await get_project_status(slug)
    if not result:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.get("/{slug}/value-chain")
async def get_value_chain(slug: str):
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return await fetch_outputs_by_type(conn, project_id=project["id"], output_type="value_chain")


@router.get("/{slug}/roadmap")
async def get_roadmap(slug: str):
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return await fetch_outputs_by_type(conn, project_id=project["id"], output_type="roadmap")


@router.get("/{slug}/settings", response_model=ProjectSettings)
async def get_settings_endpoint(slug: str):
    result = await get_project_settings(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.patch("/{slug}/settings", response_model=ProjectSettings)
async def patch_settings_endpoint(slug: str, req: ProjectSettings):
    result = await update_project_settings(slug, req)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


@router.get("/{slug}/outputs/{output_id}/content", response_model=OutputContent)
async def get_output_content_endpoint(slug: str, output_id: int):
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
async def download_output_endpoint(slug: str, output_id: int):
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
async def get_roadmap_data_endpoint(slug: str):
    result = await get_roadmap_data(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No roadmap data found for project '{slug}'")
    if isinstance(result, dict) and result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Roadmap data file not found on disk")
    return result


@router.get("/{slug}/financial-summary")
async def get_financial_summary_endpoint(slug: str):
    result = await get_financial_summary(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No financial model found for project '{slug}'")
    if isinstance(result, dict) and result.get("not_found_on_disk"):
        raise HTTPException(status_code=404, detail="Financial model file not found on disk")
    return result


@router.get("/{slug}/portfolio-register")
async def get_portfolio_register_endpoint(slug: str):
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

        # Save file
        ext = _IMAGE_CONTENT_TYPES[content_type]
        assets_dir = Path(get_settings().projects_dir) / slug / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        image_path = assets_dir / f"header{ext}"
        image_path.write_bytes(data)

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
