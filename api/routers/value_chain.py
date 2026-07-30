# api/routers/value_chain.py
"""Reading and saving the value chain model."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import check_project_access, require_any_auth
from api.database import get_db_path
from api.services.value_chain_model import validate_model
from api.services.value_chain_store import load_model, migrate_project, save_model

router = APIRouter(prefix="/projects", tags=["value-chain"])


class ModelSave(BaseModel):
    model: dict
    summary: str = ""


def _require_project(slug: str) -> None:
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")


@router.get("/{slug}/value-chain-model")
async def get_value_chain_model(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    _require_project(slug)
    model = await load_model(slug)
    if model is None:
        raise HTTPException(status_code=404, detail="No value chain model yet")
    return {"model": model}


@router.put("/{slug}/value-chain-model")
async def put_value_chain_model(
    slug: str, body: ModelSave, payload: dict = Depends(require_any_auth)
):
    """Save a new working version. Reports every problem at once rather than the first."""
    await check_project_access(slug, payload)
    _require_project(slug)

    problems = validate_model(body.model)
    if problems:
        raise HTTPException(status_code=422, detail={"problems": problems})

    output_id = await save_model(
        slug, body.model, saved_by=payload.get("sub", ""), summary=body.summary
    )
    return {"output_id": output_id}


@router.post("/{slug}/value-chain-model/migrate")
async def migrate_value_chain_model(
    slug: str, payload: dict = Depends(require_any_auth)
):
    await check_project_access(slug, payload)
    _require_project(slug)
    try:
        return await migrate_project(slug, saved_by=payload.get("sub", ""))
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
