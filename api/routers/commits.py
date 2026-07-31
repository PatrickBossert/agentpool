# api/routers/commits.py
"""Committing crew output, and starting whatever it makes ready."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import check_project_access, require_any_auth
from api.database import (
    fetch_approval_commits,
    get_connection,
    get_db_path,
    insert_crew_submission,
    insert_output_change,
    output_exists,
    set_project_status,
)
from api.services.autostart_service import start_ready_downstream
from api.services.commit_service import (
    CrewRunInProgress,
    caller_may_commit,
    caller_may_submit,
    changes_for_crew,
    commit_crew,
)
from api.services.crew_graph import CREW_DEPENDENCIES, readiness_report
from api.services.crew_state_service import crew_state_report

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["commits"])


class CommitRequest(BaseModel):
    crew_name: str
    notes: str = ""


class SubmissionRequest(BaseModel):
    crew_name: str
    notes: str = ""


class ChangeRequest(BaseModel):
    output_id: int
    request: str


def _require_project(slug: str) -> None:
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")


@router.post("/{slug}/commits", status_code=201)
async def create_commit(
    slug: str, req: CommitRequest, payload: dict = Depends(require_any_auth)
):
    await check_project_access(slug, payload)
    _require_project(slug)

    if req.crew_name not in CREW_DEPENDENCIES:
        raise HTTPException(status_code=422, detail=f"Unknown crew '{req.crew_name}'")

    if not await caller_may_commit(slug, payload):
        raise HTTPException(
            status_code=403, detail="Only an approver may commit this crew's output"
        )

    try:
        result = await commit_crew(
            slug,
            crew_name=req.crew_name,
            committed_by=payload.get("sub", ""),
            notes=req.notes,
        )
    except CrewRunInProgress as e:
        raise HTTPException(status_code=409, detail=str(e))

    # After the commit, never before. The approval is recorded; a failure to start the
    # next crew must not unwind it, so this cannot raise into the response.
    try:
        started = await start_ready_downstream(
            slug, req.crew_name, committed_by=payload.get("sub", "")
        )
    except Exception:
        _log.exception("Auto-start after committing %s on %s failed", req.crew_name, slug)
        started = {"started": [], "skipped": [], "waiting": [], "inactive": False}

    return {**result, **started}


@router.post("/{slug}/submissions", status_code=201)
async def create_submission(
    slug: str, req: SubmissionRequest, payload: dict = Depends(require_any_auth)
):
    """Mark a crew's work ready for approval - and summon the approvers."""
    from api.services.commit_notify_service import notify_crew_ready_for_approval

    await check_project_access(slug, payload)
    _require_project(slug)

    if req.crew_name not in CREW_DEPENDENCIES:
        raise HTTPException(status_code=422, detail=f"Unknown crew '{req.crew_name}'")
    if not await caller_may_submit(slug, payload):
        raise HTTPException(
            status_code=403, detail="Only a reviewer or approver may submit for approval"
        )

    async with get_connection(slug) as conn:
        submission_id = await insert_crew_submission(
            conn,
            crew_name=req.crew_name,
            submitted_by=payload.get("sub", ""),
            notes=req.notes,
        )

    await notify_crew_ready_for_approval(slug, req.crew_name)
    return {"id": submission_id, "crew_name": req.crew_name, "state": "ready"}


@router.get("/{slug}/crew-states")
async def get_crew_states(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    _require_project(slug)
    async with get_connection(slug) as conn:
        return await crew_state_report(conn)


@router.post("/{slug}/activate")
async def activate_project(slug: str, payload: dict = Depends(require_any_auth)):
    """Start the project. Until this, Pamela reports nothing."""
    await check_project_access(slug, payload)
    _require_project(slug)
    if not await caller_may_commit(slug, payload):
        raise HTTPException(
            status_code=403, detail="Only an approver may activate a project"
        )
    async with get_connection(slug) as conn:
        await set_project_status(conn, slug=slug, status="active")
    return {"slug": slug, "status": "active"}


@router.get("/{slug}/commits")
async def list_commits(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    _require_project(slug)
    async with get_connection(slug) as conn:
        return await fetch_approval_commits(conn)


@router.get("/{slug}/crew-readiness")
async def get_crew_readiness(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    _require_project(slug)
    async with get_connection(slug) as conn:
        return await readiness_report(conn)


@router.post("/{slug}/changes", status_code=201)
async def create_change(
    slug: str, req: ChangeRequest, payload: dict = Depends(require_any_auth)
):
    """Record a change asked of an output. The only door in this project is a note."""
    await check_project_access(slug, payload)
    _require_project(slug)

    async with get_connection(slug) as conn:
        if not await output_exists(conn, output_id=req.output_id):
            raise HTTPException(
                status_code=422, detail=f"output_id {req.output_id} does not exist"
            )
        change_id = await insert_output_change(
            conn,
            output_id=req.output_id,
            requested_by=payload.get("sub", ""),
            source="note",
            request=req.request,
        )

    return {
        "id": change_id,
        "output_id": req.output_id,
        "requested_by": payload.get("sub", ""),
        "source": "note",
        "request": req.request,
    }


@router.get("/{slug}/changes")
async def list_changes(
    slug: str, crew_name: str, payload: dict = Depends(require_any_auth)
):
    await check_project_access(slug, payload)
    _require_project(slug)
    if crew_name not in CREW_DEPENDENCIES:
        raise HTTPException(status_code=422, detail=f"Unknown crew '{crew_name}'")
    return await changes_for_crew(slug, crew_name=crew_name)
