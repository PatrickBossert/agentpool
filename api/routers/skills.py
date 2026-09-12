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
    fetch_skill_occurrences,
    update_skill,
    delete_skill,
)
from api.services.skills_service import check_specificity, extract_skill, extract_skills_many, BASELINE_SKILLS

router = APIRouter(tags=["skills"])


# Descriptions as they stood before the end-of-phase gating was removed. Seeding
# replaces a stored description only when it still matches one of these exactly - a
# description anybody has edited through the Role & Skills tab is theirs to keep.
_SUPERSEDED_DESCRIPTIONS: dict[str, str] = {
    "phase gating": (
        "Block every downstream dispatch until the project team explicitly confirms "
        "human review. If review is pending, output the review request and halt — "
        "never proceed without confirmation."
    ),
    "human review gate": (
        "At the end of every work phase, pause and request human review. Write a clear "
        "summary of what was produced and what the reviewer needs to validate. Do not "
        "allow downstream crews to proceed until review is confirmed."
    ),
}


# Agent lists as they shipped, for skills whose assignments have since been narrowed.
# Seeding merges agents into an existing skill but never removes one, so a correction that
# takes an agent off a skill would otherwise never reach an already-seeded database. The
# stored list is replaced with the baseline's only when it still matches one of these
# exactly - order-insensitively, since assignments are a set rather than a sequence. Any
# list somebody has changed through the Role & Skills tab is theirs to keep, and a second
# run is a no-op because the corrected list no longer matches.
_SUPERSEDED_AGENTS: dict[str, list[str]] = {
    # SP22a: the Value Chain Mapper emits the structured model, not a rendering, so an
    # instruction to produce a Mermaid diagram alongside it defeats the point. The
    # Enterprise Architect keeps the skill.
    "diagram rendering": ["Value Chain Mapper", "Enterprise Architect"],
}


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
    # Where the rule applies, decided by the reviewer at approval. Optional, and its absence
    # is not `project` - it is "leave the stored value alone", which for a proposal is the
    # `project` that `insert_skill` wrote. Sending `"project"` and omitting the key are
    # therefore two different requests that must reach the same row, which is the property
    # `tests/test_skill_proposal.py` asserts on the row rather than on the body.
    scope: str | None = None


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
    """List skills. A non-sysadmin sees the **global** approved library and nothing else.

    **Two tests, not one, and the second is the one sp65 added.** A row is readable by an
    ordinary login when it is `approved` *and* `scope='global'`, because those are the two
    halves of "this is the agent's published instruction rather than one client's material".
    A `pending` row is a *proposal* - since sp61 it is the agent's own sentence about the
    engagement it was corrected on, filed with that engagement's slug beside it. "When
    interviewing X's migration staff, never name the Q3 outage in the welcome" is a natural
    thing for it to write, and `_derive_skill_name` makes the *name* the first five words of
    the rule, so the name discloses as much as the description and hiding one without the
    other is not a fix.

    An approved `project`-scoped row is the same material with a human's signature on it. It
    reaches one engagement's prompt and no other (`_skill_applies_here`), it carries the
    `source_project` naming that engagement, and until sp65 this door handed it, and the slug,
    to any login that asked - including a `reviewer` on an unrelated project. **The status was
    the spelling of "global" and this branch gave `global` a column of its own**; the same
    substitution closes the sibling exemption in `_candidates_that_may_travel`, and the rule
    across both is one sentence: *what may be seen follows what may travel*.

    Until sp61 a `pending` row was something an administrator had typed into the review
    queue, which is why this door was open to every login and why nothing failed when the
    material behind it changed. That is CLAUDE.md's own rule arriving from the other side:
    *when a path starts carrying something written about one client, re-read the exemption
    it is sitting under*. It has now arrived from that side twice.

    **The status is refused and the scope is filtered, and the asymmetry is deliberate.** A
    caller who explicitly asked for the queue and was handed the library would render the
    library **as** the queue - the two renderers on this API label whatever comes back "in
    development" - so the quiet answer is a wrong answer there, not a safe one. Nobody asks
    for a scope: the library is what this door is for, and a shorter library is the library.
    A refusal would break the Team page for every non-sysadmin to say nothing they could act
    on.
    """
    if payload.get("role") != "sysadmin":
        if status is not None and status != "approved":
            raise HTTPException(
                status_code=403,
                detail=(
                    "Only a sysadmin may list skills that are not approved. A pending skill is "
                    "a proposal an agent made about one engagement, and it names that "
                    "engagement; an approved skill that applies everywhere is that agent's "
                    "published instruction, and is readable by any login."
                ),
            )
        status = "approved"
        rows = await fetch_skills(conn, agent_name=agent_name, status=status)
        return [r for r in rows if r.get("scope") == "global"]
    return await fetch_skills(conn, agent_name=agent_name, status=status)


@router.get("/admin/skills/{skill_id}/occurrences")
async def list_skill_occurrences(
    skill_id: int,
    _payload: dict = Depends(require_sysadmin),
    conn=Depends(get_system_db),
):
    """Every recorded sighting of one skill's rule, oldest first (sysadmin only).

    The evidence behind the count the queue sorts on. `skills.occurrences` says how many
    times an agent proposed the same rule; this says *where* - the engagement, the output it
    was corrected on, and the wording used that time - which is what a reviewer needs before
    approving a change to an agent's behaviour on every engagement.

    Sysadmin, matching the PATCH that acts on the queue rather than the GET that lists it:
    only a sysadmin can approve, so only a sysadmin needs the evidence, and these rows name
    client engagements and quote the agent's own words about them.

    An empty list is a legitimate answer, not a miss - the fifty-three skills that predate
    the proposal path have no occurrence rows at all. A skill that does not exist is 404, so
    the two are told apart.
    """
    rows = await fetch_skills(conn)
    if not any(s["id"] == skill_id for s in rows):
        raise HTTPException(status_code=404, detail="Skill not found")
    return await fetch_skill_occurrences(conn, skill_id=skill_id)


@router.patch("/admin/skills/{skill_id}")
async def update_skill_endpoint(
    skill_id: int,
    body: SkillUpdate,
    payload: dict = Depends(require_sysadmin),
    conn=Depends(get_system_db),
):
    """Approve, reject, edit a skill, or update agent assignments (sysadmin only).

    **This is where a rule's reach is decided.** `scope` is the reviewer's judgement and cannot
    be derived from the text - the spec's worked example is one correction box producing either
    *do not name specific investment figures* (true of every client) or *this client calls it
    the renewals programme* (true of one). So the door accepts it, refuses a value that is
    neither, and writes nothing when the key is absent: an approval that says nothing about
    scope leaves the proposal at the narrow value it was filed with, and widening stays the
    deliberate act.

    The refusal is a 422 naming both values, matching `status` above rather than being silently
    coerced. `skills.scope` carries a CHECK constraint, so an unchecked value would raise an
    `IntegrityError` and answer 500 - a reviewer told the server broke rather than that they
    sent a word it does not have.
    """
    if body.status and body.status not in ("pending", "approved", "rejected"):
        raise HTTPException(status_code=422, detail="status must be pending, approved, or rejected")
    if body.scope is not None and body.scope not in ("project", "global"):
        raise HTTPException(status_code=422, detail="scope must be project or global")
    updated = await update_skill(
        conn,
        skill_id=skill_id,
        status=body.status,
        name=body.name,
        description=body.description,
        reviewed_by=payload.get("sub"),
        agents=body.agents,
        scope=body.scope,
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
    """Export all approved skills as a JSON bundle.

    **The bundle deliberately carries no `scope`, and `import` deliberately ignores one.** A
    re-imported bundle is re-scoped by a human, and that is the answer rather than an omission:

    - `scope='project'` means "the engagement `source_project` names", and this bundle carries
      no `source_project` either, because a slug on the exporting deployment names no
      engagement on the importing one. A scope that travels without the thing it points at is
      not a scope.
    - `scope='global'` means "every engagement **this** deployment runs", and that is a claim
      about clients the exporting reviewer has never seen. It is exactly the claim the design
      makes a human take deliberately.
    - Nothing is lost by dropping it. `import` files every row `pending`, so the bundle lands
      in the review queue, and `PATCH /admin/skills/{id}` is where the scope is chosen. The
      importing deployment's reviewer makes the same decision the exporting one did, about
      their own engagements.

    Carrying it would be worse than useless: an imported row arriving pre-set to `global` would
    let a reviewer clicking through the queue without reading widen a rule onto every
    engagement, which is the single thing the narrow default exists to prevent.

    Asserted in `tests/test_skill_proposal.py`, both halves - the bundle has no `scope` key,
    and a hand-edited bundle that carries one is stored `project` and `pending` anyway.
    """
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
    """Import a JSON bundle of skills (idempotent — deduplicates by name).

    Every new row is filed `pending` at the narrow scope `insert_skill` defaults to, whatever
    the bundle says - `SkillImportItem` declares no `scope`, so a key naming one is dropped
    rather than honoured. The reasoning is in `export_skills` above; the short form is that a
    scope is a statement about *this* deployment's engagements, and the queue is where it gets
    made.
    """
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
            superseded_agents = _SUPERSEDED_AGENTS.get(key)
            if superseded_agents is not None and sorted(existing_skill["agents"]) == sorted(
                superseded_agents
            ):
                # Still exactly the list as it shipped, so narrow it to the baseline's -
                # the one case where seeding removes an agent rather than merging.
                await update_skill(conn, skill_id=existing_skill["id"], agents=item["agents"])
            else:
                new_agents = [a for a in item["agents"] if a not in existing_skill["agents"]]
                if new_agents:
                    merged = existing_skill["agents"] + new_agents
                    await update_skill(conn, skill_id=existing_skill["id"], agents=merged)
            superseded = _SUPERSEDED_DESCRIPTIONS.get(key)
            if superseded is not None and existing_skill.get("description") == superseded:
                await update_skill(conn, skill_id=existing_skill["id"], description=item["description"])
            continue
        skill_id = await insert_skill(
            conn,
            agents=item["agents"],
            name=item["name"],
            description=item["description"],
            source="baseline",
            # The one writer that names a scope, because it is the one that approves its own
            # rows. Everything else here files `pending` and the reviewer decides the scope
            # at approval; a baseline skill has no reviewer and no `source_project`, so left
            # at the narrow default it would be a rule that reaches no engagement at all -
            # and `force=True` would silently retire the whole factory library it had just
            # deleted. The factory baseline is universal by definition, which is the same
            # judgement the migration in `init_system_db` makes about these very rows.
            scope="global",
        )
        await update_skill(conn, skill_id=skill_id, status="approved", reviewed_by="system")
        existing_names[key] = {"id": skill_id, "agents": item["agents"]}
        seeded += 1
    return {"seeded": seeded}
