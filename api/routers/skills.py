# api/routers/skills.py
"""Agent skills library — CRUD, review queue, export/import, and LLM extraction."""
from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.auth import require_any_auth, require_sysadmin
from api.database import (
    get_system_db,
    insert_agent_skill,
    fetch_agent_skills,
    update_agent_skill,
    delete_agent_skill,
)
from api.services.skills_service import check_specificity, extract_skill, BASELINE_SKILLS

router = APIRouter(tags=["skills"])


# ── Request models ─────────────────────────────────────────────────────────────

class SkillCreate(BaseModel):
    agent_name: str
    name: str
    description: str
    source: str = "manual"
    source_project: str | None = None


class SkillUpdate(BaseModel):
    status: str | None = None
    name: str | None = None
    description: str | None = None


class SkillExtractRequest(BaseModel):
    raw_input: str


class SkillImportItem(BaseModel):
    agent_name: str
    name: str
    description: str
    source: str = "import"
    source_project: str | None = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/admin/skills/extract")
async def extract_skill_endpoint(
    body: SkillExtractRequest,
    _payload: dict = Depends(require_any_auth),
):
    """Extract a skill name + description from raw feedback text (no DB write)."""
    result = await extract_skill(body.raw_input)
    return result


@router.post("/admin/skills", status_code=201)
async def create_skill(
    body: SkillCreate,
    payload: dict = Depends(require_any_auth),
    conn=Depends(get_system_db),
):
    """Submit a skill for review. Runs specificity check; saves as pending."""
    specificity = await check_specificity(body.description)
    flag_reason = specificity.get("reason") if specificity.get("is_specific") else None
    flag_suggestion = specificity.get("suggestion") if specificity.get("is_specific") else None

    skill_id = await insert_agent_skill(
        conn,
        agent_name=body.agent_name,
        name=body.name,
        description=body.description,
        source=body.source,
        source_project=body.source_project,
        flag_reason=flag_reason,
        flag_suggestion=flag_suggestion,
    )
    rows = await fetch_agent_skills(conn)
    skill = next((s for s in rows if s["id"] == skill_id), None)
    return skill


@router.get("/admin/skills")
async def list_skills(
    status: str | None = None,
    agent_name: str | None = None,
    payload: dict = Depends(require_any_auth),
    conn=Depends(get_system_db),
):
    """List skills. Non-sysadmins are restricted to approved skills only."""
    if payload.get("role") != "sysadmin" and status != "approved":
        status = "approved"
    return await fetch_agent_skills(conn, agent_name=agent_name, status=status)


@router.patch("/admin/skills/{skill_id}")
async def update_skill(
    skill_id: int,
    body: SkillUpdate,
    payload: dict = Depends(require_sysadmin),
    conn=Depends(get_system_db),
):
    """Approve, reject, or edit a skill (sysadmin only)."""
    if body.status and body.status not in ("pending", "approved", "rejected"):
        raise HTTPException(status_code=422, detail="status must be pending, approved, or rejected")
    updated = await update_agent_skill(
        conn,
        skill_id=skill_id,
        status=body.status,
        name=body.name,
        description=body.description,
        reviewed_by=payload.get("sub"),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    rows = await fetch_agent_skills(conn)
    skill = next((s for s in rows if s["id"] == skill_id), None)
    return skill


@router.delete("/admin/skills/{skill_id}", status_code=204)
async def remove_skill(
    skill_id: int,
    _payload: dict = Depends(require_sysadmin),
    conn=Depends(get_system_db),
):
    """Delete a skill (sysadmin only)."""
    deleted = await delete_agent_skill(conn, skill_id=skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Skill not found")


@router.get("/admin/skills/export")
async def export_skills(
    _payload: dict = Depends(require_sysadmin),
    conn=Depends(get_system_db),
):
    """Export all approved skills as a JSON bundle."""
    skills = await fetch_agent_skills(conn, status="approved")
    export = [
        {
            "agent_name": s["agent_name"],
            "name": s["name"],
            "description": s["description"],
            "source": "import",
        }
        for s in skills
    ]
    return JSONResponse(
        content=export,
        headers={"Content-Disposition": 'attachment; filename="agent_skills_export.json"'},
    )


@router.post("/admin/skills/import")
async def import_skills(
    items: list[SkillImportItem],
    _payload: dict = Depends(require_sysadmin),
    conn=Depends(get_system_db),
):
    """Import a JSON bundle of skills (idempotent — skips existing agent_name+name combos)."""
    existing = await fetch_agent_skills(conn)
    existing_keys = {(s["agent_name"].lower(), s["name"].lower()) for s in existing}
    imported = 0
    skipped = 0
    for item in items:
        key = (item.agent_name.lower(), item.name.lower())
        if key in existing_keys:
            skipped += 1
            continue
        specificity = await check_specificity(item.description)
        flag_reason = specificity.get("reason") if specificity.get("is_specific") else None
        flag_suggestion = specificity.get("suggestion") if specificity.get("is_specific") else None
        await insert_agent_skill(
            conn,
            agent_name=item.agent_name,
            name=item.name,
            description=item.description,
            source=item.source or "import",
            source_project=item.source_project,
            flag_reason=flag_reason,
            flag_suggestion=flag_suggestion,
        )
        existing_keys.add(key)
        imported += 1
    return {"imported": imported, "skipped": skipped}


@router.post("/admin/skills/seed")
async def seed_baseline(
    _payload: dict = Depends(require_sysadmin),
    conn=Depends(get_system_db),
):
    """Seed the skills library from the factory baseline (idempotent)."""
    existing = await fetch_agent_skills(conn)
    existing_keys = {(s["agent_name"].lower(), s["name"].lower()) for s in existing}
    seeded = 0
    for item in BASELINE_SKILLS:
        key = (item["agent_name"].lower(), item["name"].lower())
        if key in existing_keys:
            continue
        skill_id = await insert_agent_skill(
            conn,
            agent_name=item["agent_name"],
            name=item["name"],
            description=item["description"],
            source="baseline",
        )
        # Auto-approve baseline skills
        await update_agent_skill(conn, skill_id=skill_id, status="approved", reviewed_by="system")
        existing_keys.add(key)
        seeded += 1
    return {"seeded": seeded}
