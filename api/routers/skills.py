# api/routers/skills.py
"""Agent skills library — CRUD, review queue, export/import, and LLM extraction."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.auth import require_any_auth, require_sysadmin
from api.database import (
    get_system_db,
    insert_skill,
    fetch_skills,
    update_skill,
    delete_skill,
)
from api.services.skills_service import check_specificity, extract_skill, extract_skills_many, BASELINE_SKILLS

router = APIRouter(tags=["skills"])


# ── Request models ─────────────────────────────────────────────────────────────

class SkillCreate(BaseModel):
    agents: list[str]
    name: str
    description: str
    source: str = "manual"
    source_project: str | None = None


class SkillUpdate(BaseModel):
    status: str | None = None
    name: str | None = None
    description: str | None = None
    agents: list[str] | None = None


class SkillExtractRequest(BaseModel):
    raw_input: str


class SkillImportItem(BaseModel):
    agents: list[str]
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
    return await extract_skill(body.raw_input)


@router.post("/admin/skills/extract-many")
async def extract_skills_many_endpoint(
    body: SkillExtractRequest,
    _payload: dict = Depends(require_any_auth),
):
    """Extract one or more skills from free-form input text (no DB write)."""
    return await extract_skills_many(body.raw_input)


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

    skill_id = await insert_skill(
        conn,
        agents=body.agents,
        name=body.name,
        description=body.description,
        source=body.source,
        source_project=body.source_project,
        flag_reason=flag_reason,
        flag_suggestion=flag_suggestion,
    )
    rows = await fetch_skills(conn)
    skill = next((s for s in rows if s["id"] == skill_id), None)
    return skill


@router.get("/admin/skills")
async def list_skills(
    status: str | None = None,
    agent_name: str | None = None,
    payload: dict = Depends(require_any_auth),
    conn=Depends(get_system_db),
):
    """List skills. Non-sysadmins may see approved and pending; rejected is sysadmin-only."""
    if payload.get("role") != "sysadmin" and status not in ("approved", "pending"):
        status = "approved"
    return await fetch_skills(conn, agent_name=agent_name, status=status)


@router.patch("/admin/skills/{skill_id}")
async def update_skill_endpoint(
    skill_id: int,
    body: SkillUpdate,
    payload: dict = Depends(require_sysadmin),
    conn=Depends(get_system_db),
):
    """Approve, reject, edit a skill, or update agent assignments (sysadmin only)."""
    if body.status and body.status not in ("pending", "approved", "rejected"):
        raise HTTPException(status_code=422, detail="status must be pending, approved, or rejected")
    updated = await update_skill(
        conn,
        skill_id=skill_id,
        status=body.status,
        name=body.name,
        description=body.description,
        reviewed_by=payload.get("sub"),
        agents=body.agents,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    rows = await fetch_skills(conn)
    skill = next((s for s in rows if s["id"] == skill_id), None)
    return skill


@router.delete("/admin/skills/{skill_id}", status_code=204)
async def remove_skill(
    skill_id: int,
    _payload: dict = Depends(require_sysadmin),
    conn=Depends(get_system_db),
):
    """Delete a skill and all its agent assignments (sysadmin only)."""
    deleted = await delete_skill(conn, skill_id=skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Skill not found")


@router.get("/admin/skills/export")
async def export_skills(
    _payload: dict = Depends(require_sysadmin),
    conn=Depends(get_system_db),
):
    """Export all approved skills as a JSON bundle."""
    skills = await fetch_skills(conn, status="approved")
    export = [
        {"agents": s["agents"], "name": s["name"], "description": s["description"], "source": "import"}
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
    """Import a JSON bundle of skills (idempotent — deduplicates by name)."""
    existing = await fetch_skills(conn)
    existing_names = {s["name"].lower(): s for s in existing}
    imported = 0
    skipped = 0
    for item in items:
        key = item.name.lower()
        if key in existing_names:
            # Merge any new agents into the existing skill's assignments
            existing_skill = existing_names[key]
            new_agents = [a for a in item.agents if a not in existing_skill["agents"]]
            if new_agents:
                merged = existing_skill["agents"] + new_agents
                await update_skill(conn, skill_id=existing_skill["id"], agents=merged)
            skipped += 1
            continue
        specificity = await check_specificity(item.description)
        flag_reason = specificity.get("reason") if specificity.get("is_specific") else None
        flag_suggestion = specificity.get("suggestion") if specificity.get("is_specific") else None
        await insert_skill(
            conn,
            agents=item.agents,
            name=item.name,
            description=item.description,
            source=item.source or "import",
            source_project=item.source_project,
            flag_reason=flag_reason,
            flag_suggestion=flag_suggestion,
        )
        existing_names[key] = {"id": -1, "agents": item.agents}  # prevent re-import in same batch
        imported += 1
    return {"imported": imported, "skipped": skipped}


@router.post("/admin/skills/seed")
async def seed_baseline(
    force: bool = False,
    _payload: dict = Depends(require_sysadmin),
    conn=Depends(get_system_db),
):
    """Seed the skills library from the factory baseline.

    force=True wipes all existing baseline skills before re-seeding so
    updated descriptions and agent assignments are applied cleanly.
    """
    if force:
        # Remove all baseline skills (and their assignments via cascade logic)
        async with conn.execute(
            "SELECT id FROM skills WHERE source = 'baseline'"
        ) as cur:
            baseline_ids = [r[0] for r in await cur.fetchall()]
        for bid in baseline_ids:
            await delete_skill(conn, skill_id=bid)
        await conn.commit()

    existing = await fetch_skills(conn)
    existing_names = {s["name"].lower(): s for s in existing}
    seeded = 0
    for item in BASELINE_SKILLS:
        key = item["name"].lower()
        if key in existing_names:
            existing_skill = existing_names[key]
            new_agents = [a for a in item["agents"] if a not in existing_skill["agents"]]
            if new_agents:
                merged = existing_skill["agents"] + new_agents
                await update_skill(conn, skill_id=existing_skill["id"], agents=merged)
            continue
        skill_id = await insert_skill(
            conn,
            agents=item["agents"],
            name=item["name"],
            description=item["description"],
            source="baseline",
        )
        await update_skill(conn, skill_id=skill_id, status="approved", reviewed_by="system")
        existing_names[key] = {"id": skill_id, "agents": item["agents"]}
        seeded += 1
    return {"seeded": seeded}
