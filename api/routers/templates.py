# api/routers/templates.py
"""Template library CRUD — interview and questionnaire templates stored in system.db."""
import json
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from api.auth import get_token_payload
from api.database import (
    get_system_db,
    fetch_all_templates,
    fetch_template,
    insert_template,
    update_template,
    delete_template,
)

router = APIRouter(prefix="/api/templates", tags=["templates"])


class TemplateCreate(BaseModel):
    model_config = {"populate_by_name": True}
    name: str
    description: str = ""
    type: str
    schema_json: Any = {}


class TemplatePatch(BaseModel):
    model_config = {"populate_by_name": True}
    name: str | None = None
    description: str | None = None
    schema_json: Any = None


@router.get("")
async def list_templates(
    type: str | None = None,
    _user: dict = Depends(get_token_payload),
    conn=Depends(get_system_db),
):
    return await fetch_all_templates(conn, type_filter=type)


@router.post("", status_code=201)
async def create_template(
    body: TemplateCreate,
    _user: dict = Depends(get_token_payload),
    conn=Depends(get_system_db),
):
    if isinstance(body.schema_json, str):
        schema_str = body.schema_json
    else:
        schema_str = json.dumps(body.schema_json)
    tid = await insert_template(conn, body.name, body.description, body.type, schema_str)
    row = await fetch_template(conn, tid)
    result = dict(row)
    result.pop("schema_json", None)
    return result


@router.get("/{template_id}")
async def get_template(
    template_id: int,
    _user: dict = Depends(get_token_payload),
    conn=Depends(get_system_db),
):
    row = await fetch_template(conn, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    result = dict(row)
    raw = result.get("schema_json", "{}")
    try:
        result["schema_json"] = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        result["schema_json"] = {}
    return result


@router.patch("/{template_id}")
async def patch_template(
    template_id: int,
    body: TemplatePatch,
    _user: dict = Depends(get_token_payload),
    conn=Depends(get_system_db),
):
    existing = await fetch_template(conn, template_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Template not found")
    existing = dict(existing)

    name = body.name if body.name is not None else existing["name"]
    description = body.description if body.description is not None else existing["description"]

    if body.schema_json is not None:
        if isinstance(body.schema_json, str):
            schema_str = body.schema_json
        else:
            schema_str = json.dumps(body.schema_json)
    else:
        schema_str = existing["schema_json"]

    await update_template(conn, template_id, name, description, schema_str)
    row = await fetch_template(conn, template_id)
    result = dict(row)
    raw = result.get("schema_json", "{}")
    try:
        result["schema_json"] = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        result["schema_json"] = {}
    return result


@router.delete("/{template_id}", status_code=204)
async def delete_template_endpoint(
    template_id: int,
    _user: dict = Depends(get_token_payload),
    conn=Depends(get_system_db),
):
    existing = await fetch_template(conn, template_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Template not found")
    await delete_template(conn, template_id)
    return Response(status_code=204)
