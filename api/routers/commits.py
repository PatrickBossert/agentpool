# api/routers/commits.py
"""Committing crew output, and reading what that released."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import check_project_access, require_any_auth
from api.database import (
    fetch_approval_commits,
    get_connection,
    get_db_path,
    insert_output_change,
    output_exists,
)
from api.services.commit_service import caller_may_commit, changes_for_crew, commit_crew
from api.services.crew_graph import CREW_DEPENDENCIES, readiness_report

router = APIRouter(prefix="/projects", tags=["commits"])


class CommitRequest(BaseModel):
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

    return await commit_crew(
        slug,
        crew_name=req.crew_name,
        committed_by=payload.get("sub", ""),
        notes=req.notes,
    )


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
