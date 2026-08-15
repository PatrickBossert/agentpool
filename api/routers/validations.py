# api/routers/validations.py
"""List and dispose of structural validation warnings.

A warning nobody can see cannot inform a review decision, and a disposition nobody can
record cannot tell "we considered this and it is fine" from "nobody looked".
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_any_auth, check_project_access
from api.database import (
    get_connection, get_db_path, fetch_project,
    fetch_validation_warnings, dispose_validation_warning,
)
from api.services.authority_service import caller_may_contribute

router = APIRouter(prefix="/projects", tags=["validations"])

_DISPOSITIONS = ("open", "acknowledged", "dismissed")


class DispositionRequest(BaseModel):
    disposition: str
    note: str = ""


@router.get("/{slug}/validation-warnings")
async def list_validation_warnings(
    slug: str,
    source: str | None = None,
    disposition: str | None = None,
    payload: dict = Depends(require_any_auth),
):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return await fetch_validation_warnings(
            conn,
            project_id=project["id"],
            sources=[source] if source else None,
            dispositions=[disposition] if disposition else None,
        )


@router.patch("/{slug}/validation-warnings/{warning_id}")
async def dispose_warning(
    slug: str,
    warning_id: int,
    req: DispositionRequest,
    payload: dict = Depends(require_any_auth),
):
    """Record what was decided about a warning.

    Gated as feedback, not as an approval: a disposition says "we looked at this", which
    is the same authority as leaving a review. Reading the warnings stays open to every
    member - a warning nobody can see cannot inform anything.
    """
    await check_project_access(slug, payload)
    if not await caller_may_contribute(slug, payload):
        raise HTTPException(
            status_code=403,
            detail="Only a reviewer or approver may dispose of a validation warning",
        )
    if req.disposition not in _DISPOSITIONS:
        raise HTTPException(
            status_code=422,
            detail=f"disposition must be one of {', '.join(_DISPOSITIONS)}",
        )
    # A dismissal without a reason is indistinguishable from nobody looking, which is the
    # exact ambiguity the disposition exists to remove. Acknowledging needs no reason -
    # it says the warning is right, and there is nothing extra to explain.
    if req.disposition == "dismissed" and not req.note.strip():
        raise HTTPException(
            status_code=422, detail="a dismissal must record why it is a false positive"
        )
    async with get_connection(slug) as conn:
        updated = await dispose_validation_warning(
            conn, warning_id=warning_id, disposition=req.disposition,
            note=req.note.strip(), by=payload.get("sub", "unknown"),
        )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Warning {warning_id} not found")
    return {"id": warning_id, "disposition": req.disposition, "note": req.note.strip()}
