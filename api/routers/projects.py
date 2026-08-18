# api/routers/projects.py
import json
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from api.auth import require_any_auth, require_org_admin_or_above, check_project_access
from api.config import get_settings
from api.database import (
    get_db_path, get_connection, fetch_project, fetch_outputs_by_type, update_project_config,
    get_system_connection, register_project_if_unregistered, resolve_home_org_id,
)
from api.models import ProjectCreate, ProjectSettings, OutputContent, StatusResponse, ProjectResponse
# The one authority for "may this caller act on this project's scripts", shared with
# api/routers/script_reviews.py and api/routers/permissions.py rather than restated.
from api.services.authority_service import caller_roles, require_project_administration
from api.services.data_architecture_service import data_architecture
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
    # Every project is registered, whatever the creator's role.
    #
    # This used to be gated on `payload.get("role") == "org_admin"`, and a sysadmin's token
    # carries no org_id - so on a deployment where the sysadmin creates everything, nothing
    # was ever registered, and check_project_access refuses every org_admin on every slug for
    # want of a registry row. The gate made the hole permanent: the only role that would have
    # produced rows was the one already locked out.
    #
    # The creator's own organisation wins when their token carries one, so an org_admin who
    # belongs to an organisation does not create a project they are then refused on. Everyone
    # else registers to the home organisation, which init_system_db guarantees exists: every
    # sysadmin, and also an org_admin with no org_membership row, since login only embeds
    # org_id when there is one. That second caller is still refused on what they just created -
    # unchanged from before this branch, and a question for whoever appoints an org_admin
    # without an organisation, not for this endpoint.
    #
    # The home organisation is resolved by resolve_home_org_id and must stay that way. It
    # looks up `home_org_slug`; the tempting inline "SELECT id FROM organisations ORDER BY id
    # LIMIT 1" agrees with it on a fresh database purely because the seed happens to be
    # inserted first, and disagrees the moment a system database holds an organisation created
    # ahead of the seed - at which point every sysadmin-created project is handed to the wrong
    # organisation's admins.
    #
    # register_project_if_unregistered rather than insert_project_registry: this endpoint
    # answers 200 to a re-POST of an existing slug, and the latter is an upsert. Using it here
    # would let a re-POST silently drag an engagement back out of whichever organisation an
    # operator had moved it to through POST /auth/projects.
    async with get_system_connection() as sys_conn:
        org_id = payload.get("org_id") or await resolve_home_org_id(sys_conn)
        if not org_id:
            # Loudly, because an unregistered project is exactly the invisible state this
            # branch exists to eliminate - a 201 here would hand back a project no org_admin
            # can ever reach and say nothing about it. Reachable only if the home organisation
            # has been deleted, which DELETE /auth/orgs/{id} now refuses; the project itself is
            # already created, so re-POSTing the same slug registers it once the operator has
            # restored the organisation.
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Project '{req.client_slug}' was created but could not be registered:"
                    f" no organisation with slug '{get_settings().home_org_slug}'"
                    " (HOME_ORG_SLUG). Restore it, then re-POST this project to register it."
                ),
            )
        await register_project_if_unregistered(
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


@router.get("/{slug}/data-architecture")
async def get_data_architecture(slug: str, payload: dict = Depends(require_org_admin_or_above)):
    """What this project's agents reach, read, and run - resolved for its own `llm_mode`.

    `require_org_admin_or_above` rather than `require_any_auth`, matching the route the
    dashboard now mounts the page behind. `/data-architecture` sat outside `ProtectedRoute`
    and was public by omission - nothing public ever linked to it, and its one link has always
    sat inside the guard - so closing the page without closing its door would have moved the
    omission rather than ended it.

    404 rather than an answer for a project that does not exist: `project_llm_mode` reports
    "standard" for a database it cannot find, and answering that for an unknown slug would
    describe a hosted engagement that nobody has created.
    """
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return data_architecture(slug)


@router.get("/{slug}/settings", response_model=ProjectSettings)
async def get_settings_endpoint(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_project_settings(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result


# Fields on ProjectSettings that a `project_admin` may not change, however freely they may
# change the rest of the engagement's configuration. Not a tidiness list - each one hands a
# client-side actor something the platform tier is meant to hold:
#
#   llm_mode      - the secure-mode guarantee itself. CLAUDE.md states it as absolute: every
#                   crew agent including PAM routes locally on a sensitive project, a missing
#                   local model raises LocalModelUnavailable rather than falling back, and
#                   documents stay off Chroma Cloud. Flipping a sensitive project to
#                   "standard" sends the next run's prompts, the elaboration press and Agent
#                   Chat to hosted Anthropic, and the guarantee was never a guarantee.
#   *_model, *_url - the same reach by a quieter route: point a tier at a different model or
#                   a different base URL and the traffic goes wherever that names.
#   dev_mode      - holds all outbound project email to one address. Clearing it is what
#                   makes the scheduler email real stakeholders, which is not a decision the
#                   person being emailed about should be able to take unilaterally. It now
#                   means what it says: every project send path goes through
#                   `outbound_mail.send_project_mail`, where the mode is read. It covered
#                   two of five paths when this line was written, and the three it missed
#                   were the ones reaching participants rather than the operator.
_PLATFORM_TIER_SETTINGS = (
    "llm_mode",
    "dev_mode",
    "anthropic_fast_model",
    "anthropic_deep_model",
    "local_fast_model",
    "local_fast_url",
    "local_deep_model",
    "local_deep_url",
)


async def _refuse_platform_tier_setting_changes(slug: str, incoming: ProjectSettings) -> None:
    """Refuse a write that *changes* any platform-tier field. Presence is fine; change is not.

    Compared against the stored value rather than rejected on presence, because
    `ProjectSettings` is a whole-body model and the Settings tab round-trips it: every save
    from the UI carries `llm_mode` whether or not the user touched it, so refusing the key
    outright would refuse every save a project_admin makes. Refusing the *transition* is the
    same shape `_validate_deliverable_role` uses in stakeholders.py - it asks what the write
    would change, not what it happens to mention.

    Both sides go through `ProjectSettings` before being compared, so a field absent from a
    project's stored `config_json` is compared as the model default rather than skipped. A
    `field in current` guard here would have been **fail-open**: the one project whose config
    predates a field is the one where changing it goes unrefused.

    `llm_mode` is then overridden from `projects.llm_mode`, because that column is the sole
    authority for it - `update_project_settings` says so, and deliberately keeps it out of
    config.yaml for the same reason. `config_json` carries a copy for the Settings tab to
    round-trip, and comparing a guard against a copy is how the copy's drift becomes a
    bypass.

    Loud, not silent. Dropping the field and returning 200 would leave the caller believing
    the project is in a mode it is not, which on `llm_mode` is the worst possible failure of
    this particular setting - and silently discarding a submitted value is the defect
    `_declared_fields_only` exists to prevent one router over.
    """
    stored = await get_project_settings(slug)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    current = ProjectSettings(**stored).model_dump()

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    current["llm_mode"] = project["llm_mode"]

    submitted = incoming.model_dump()
    changed = [f for f in _PLATFORM_TIER_SETTINGS if submitted.get(f) != current.get(f)]
    if changed:
        raise HTTPException(
            status_code=403,
            detail=(
                f"{', '.join(changed)} may only be changed by an org admin or above - "
                "a project_admin configures the engagement, not how it is run"
            ),
        )


@router.patch("/{slug}/settings", response_model=ProjectSettings)
async def patch_settings_endpoint(slug: str, req: ProjectSettings, payload: dict = Depends(require_any_auth)):
    """Project configuration. Administration axis, with one field group carved out.

    The door is `require_project_administration`, so a `project_admin` reaches it. The body
    is not uniformly project configuration though: it also carries `llm_mode`, `dev_mode` and
    the per-agent model ids, which decide where this engagement's data is sent. Those stay on
    the platform tier - see `_PLATFORM_TIER_SETTINGS`.
    """
    await check_project_access(slug, payload)
    await require_project_administration(slug, payload)
    if payload.get("role") not in ("sysadmin", "org_admin"):
        await _refuse_platform_tier_setting_changes(slug, req)
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
    payload: dict = Depends(require_any_auth),
):
    """Upload a header image for the project branding.

    Branding is how the engagement presents itself to its interviewees - configuration,
    like `PATCH /{slug}/settings` beside it - so it sits on the administration axis. The
    membership floor comes first, and before the existence check too: a caller from
    outside the engagement must not be able to use this door to learn which slugs exist.
    """
    await check_project_access(slug, payload)
    await require_project_administration(slug, payload)
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
            slug=slug,
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
    # Verify the authenticated user has access to this project
    await check_project_access(slug, payload)
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


@router.get("/{slug}/value-chain-registry")
async def get_value_chain_registry(slug: str, payload: dict = Depends(require_any_auth)):
    """Return the stable activity ID registry for this project."""
    await check_project_access(slug, payload)
    from agents.tools._db import current_output_path

    registry_path = current_output_path(slug, "value_chain_registry")
    if registry_path is None:
        raise HTTPException(status_code=404, detail="No activity registry found for this project")
    return json.loads(registry_path.read_text(encoding="utf-8"))


# ── Interview & Questionnaire Scripts ─────────────────────────────────────────

class InterviewScriptPatch(BaseModel):
    script: dict
    base_version: int | None = None


def _scripts_path(slug: str, kind: str) -> Path:
    return Path(get_settings().projects_dir) / slug / "outputs" / f"{kind}_scripts.json"


@router.get("/{slug}/interview-scripts")
async def list_interview_scripts(slug: str, payload: dict = Depends(require_any_auth)):
    """Return the current interview script artefact, keyed by script id.

    This used to merge every interview_scripts*.json in the directory, which was correct
    while Maya's set was spread across files. Now that a write merges into the current
    version, the current version IS the whole artefact and the glob only adds history: by
    6 August twenty files across four runs were producing six different L0 interviews,
    three of them predating node_id and so undedupable by anything but their titles.

    dedupe_script_map still runs - two scripts inside one artefact can normalise to the
    same label, and it also drops values that are not interviews.

    normalise_scripts runs last, on the way out, so a script written before the
    level/perspective split (level: "F", no perspective) is served to the UI in the shape
    every renderer built for the split expects, with no migration of the file on disk.
    """
    await check_project_access(slug, payload)
    from agents.tools._db import current_output_path
    from api.services.interview_script_model import normalise_scripts
    from api.services.interview_scripts_service import dedupe_script_map

    outputs_dir = Path(get_settings().projects_dir) / slug / "outputs"
    current = current_output_path(slug, "interview_scripts")
    if current is None:
        return {}
    try:
        deduped = dedupe_script_map(json.loads(current.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}
    return normalise_scripts(deduped)


@router.get("/{slug}/interview-scripts/{script_id}")
async def get_interview_script(
    slug: str, script_id: str, payload: dict = Depends(require_any_auth)
):
    """One script from the current artefact, resolved through the ledger.

    Keyed by script_id because that is what the artefact is keyed by, what
    _merge_with_current merges on, and what stakeholder assignments and stored answers
    cite. The previous node_label form read a bare interview_scripts.json that
    insert_agent_output_sync renames away on every write.
    """
    await check_project_access(slug, payload)
    scripts = await list_interview_scripts(slug, payload)
    if script_id not in scripts:
        raise HTTPException(status_code=404, detail=f"No script '{script_id}'")
    return scripts[script_id]


@router.patch("/{slug}/interview-scripts/{script_id}")
async def patch_interview_script(
    slug: str, script_id: str, body: InterviewScriptPatch,
    payload: dict = Depends(require_any_auth),
):
    """Edit one script, through the same door the agent writes by.

    SQLiteStateTool gives the edit a version, the validators, and a ledger row recording
    last_author as the person. Writing the file directly would skip all three, which is
    what the previous implementation did.

    node_id is taken from the stored script, never from the body: a human edit changes
    content, never the anchor, and letting the body carry node_id would reopen the
    id-moving hole this branch exists to close.

    Authority is read from caller_roles, not the login role. This used to be
    require_org_admin_or_above while POST /script-ledger/{id}/review next door used the
    stakeholder flag, and ScriptReviewPanel's "Save changes" calls both in sequence - so
    the two could disagree, in either direction, and the panel checked neither. An
    is_reviewer whose login is not org_admin was offered the button by /my-permissions
    and refused by the PATCH. Worse, an org_admin who is not a flagged stakeholder got
    the opposite: the PATCH succeeded, the follow-up review 403'd, the artefact was
    versioned with no review recorded, and the panel's own row was left stale - so
    retrying returned 409 naming someone else as the editor. It was them.

    Same roles as the review endpoint's non-approval path, which makes /my-permissions'
    can_review true for the thing it is named after: editing a script and reviewing it
    are the same authority.
    """
    await check_project_access(slug, payload)
    roles = await caller_roles(slug, payload)
    if not (roles & {"reviewer", "approver"}):
        raise HTTPException(status_code=403, detail="Not permitted to edit this script")

    from agents.tools.sqlite_state import SQLiteStateTool

    scripts = await list_interview_scripts(slug, payload)
    if script_id not in scripts:
        raise HTTPException(status_code=404, detail=f"No script '{script_id}'")

    if body.base_version is not None:
        # last_version is nullable - rows loaded by the backfill carry NULL because no
        # SQLiteStateTool write has touched them since. A NULL held[0] means "we don't
        # know this row's version", not "it is current", so `held[0] > body.base_version`
        # would be NULL under plain SQL comparison and silently drop the row from a WHERE
        # clause rather than refuse or accept the edit - the exact trap CLAUDE.md warns
        # about. We choose to accept the edit in that case: refusing a save we have no
        # evidence is stale would block every first edit after a backfill for no reason,
        # and the row gets a real last_version the moment this write completes, so the
        # gap closes itself rather than accumulating risk.
        async with get_connection(slug) as conn:
            project = await fetch_project(conn, slug=slug)
            cur = await conn.execute(
                "SELECT last_version, last_author FROM interview_script_ledger"
                " WHERE script_id=? AND project_id=?", (script_id, project["id"]))
            held = await cur.fetchone()
        if held and held[0] is not None and held[0] > body.base_version:
            raise HTTPException(
                status_code=409,
                detail=(f"{script_id} was changed by {held[1] or 'someone else'} since you "
                        f"opened it (you have v{body.base_version}, current is v{held[0]}) - "
                        f"reopen it and reapply your changes"),
            )

    merged = {script_id: {**body.script, "script_id": script_id,
                          "node_id": scripts[script_id].get("node_id")}}

    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=0)
    result = tool._run(operation="write", key="interview_scripts",
                       agent_name="interaction_designer", value=json.dumps(merged))
    if not result.startswith("Written to"):
        raise HTTPException(status_code=422, detail=result)

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        # node_label is COALESCEd, not overwritten blind: a partial body that omits it
        # must not blank the ledger's copy. When the edit does carry one,
        # script_review_service._fetch_change_requests reads l.node_label straight off
        # this row to name the script to Maya on a send-back - leaving it stale here
        # would keep naming the edit's own retitle by the text it just replaced.
        # review_return_to=NULL is brief-mandated: a human edit is not the revision an
        # outstanding changes_requested send-back was waiting for, so the edit must not
        # leave that send-back pointing at whichever agent run picks the script up next.
        await conn.execute(
            "UPDATE interview_script_ledger"
            " SET last_author=?, review_status='pending', review_return_to=NULL,"
            "     node_label=COALESCE(?, node_label), updated_at=CURRENT_TIMESTAMP"
            " WHERE script_id=? AND project_id=?",
            (payload.get("sub", "human"), merged[script_id].get("node_label") or None,
             script_id, project["id"]),
        )
        await conn.commit()
    return {"ok": True}


@router.get("/{slug}/questionnaire-scripts")
async def list_questionnaire_scripts(slug: str, payload: dict = Depends(require_any_auth)):
    """Return all questionnaire scripts keyed by node_label."""
    await check_project_access(slug, payload)
    p = _scripts_path(slug, "questionnaire")
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))
