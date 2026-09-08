# api/routers/reviews.py
"""The two review doors, and the removal of a review.

check_project_access is membership, and membership is read access - it carries no role
test at all, so on its own it let anybody who had ever accepted an invite record a
review, resolve somebody else's, or delete one. Each write door below therefore also
asks the authority walk: recording feedback needs `caller_may_contribute`, and deleting
a review somebody else recorded needs `caller_may_approve`. See
api/services/authority_service.py for why those are the two gates.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from aiosqlite import IntegrityError as AioSQLiteIntegrityError
from api.auth import require_any_auth, check_project_access
from api.database import (
    get_connection,
    get_db_path,
    fetch_output_agent_name,
    fetch_project,
    fetch_review,
    insert_review,
    insert_output_change,
    update_review,
    delete_hitl_review,
)
from api.services.authority_service import caller_may_approve, caller_may_contribute
from api.services.project_service import get_pending_reviews

log = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["reviews"])


class ReviewRequest(BaseModel):
    output_id: int
    decision: str  # "approved" | "changes_requested"
    notes: str = ""
    # Self-declared, and left that way deliberately for now: the recorded author is
    # whatever the body says, not payload["sub"]. The gate below establishes that the
    # caller may review at all, which is the hole that mattered; who a stored review is
    # attributed to is a separate change, and one RerunDialog and AgentStatusTab both
    # depend on the current shape of.
    reviewer: str = "consultant"


@router.post("/{slug}/review", status_code=201)
async def submit_review(slug: str, req: ReviewRequest, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    if not await caller_may_contribute(slug, payload):
        raise HTTPException(
            status_code=403, detail="Only a reviewer or approver may review this project's work"
        )
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        try:
            review_id = await insert_review(
                conn,
                output_id=req.output_id,
                reviewer=req.reviewer,
                decision=req.decision,
                notes=req.notes,
            )
        except AioSQLiteIntegrityError:
            raise HTTPException(status_code=422, detail=f"output_id {req.output_id} does not exist")
        # An approval is not feedback, and neither is an empty note - mirrors the guard on
        # the PATCH door below. No intent parameter here: every caller of this endpoint
        # ("Suggest a revision" and the inline "Revise" action) means fix this output, which
        # is exactly what kind='change_request' means, so the default is correct by
        # construction rather than by omission. Don't add an intent picker to this door
        # thinking it was overlooked - it wasn't.
        if req.decision == "changes_requested" and req.notes.strip():
            await insert_output_change(
                conn,
                output_id=req.output_id,
                requested_by=payload.get("sub", "unknown"),
                source="review",
                request=req.notes.strip(),
                summary="",
                kind="change_request",
            )
        return {
            "id": review_id,
            "output_id": req.output_id,
            "decision": req.decision,
            "notes": req.notes,
        }


_INTENTS = ("change_request", "correction", "skill")

# Where each intent goes, because it is three different destinations and only one of them is
# this router's own table:
#
# | Intent           | Reaches the agent by                                                  |
# |------------------|-----------------------------------------------------------------------|
# | `change_request` | `fetch_open_change_requests`, prepended to the crew's next task        |
# | `correction`     | RAG - the row is recorded and deliberately not injected from here      |
# | `skill`          | `propose_skill`, filed `pending` for a human to approve and scope      |
#
# The third row is new. `intent='skill'` set `kind='skill'` on `output_changes` and **nothing
# read the value**: `fetch_open_change_requests` selects `kind='change_request'` alone, so the
# row was recorded, counted in the change log, and reached no agent and no library. The
# reviewer was told the rule would be used on every project and it was used nowhere.
#
# It now goes to the queue an agent's own proposal goes to, which is the mechanism the design
# always intended - proposed, deduplicated, held `pending`, approved by a human, and scoped by
# them at approval. The `output_changes` row is still written, unchanged: it is the record of
# what a reviewer asked of an output, and a rule on the queue is not that record.
_SKILL_INTENT = "skill"


async def _propose_from_review(
    slug: str, *, agent_name: str, rule: str, review_id: int
) -> dict | None:
    """File a reviewer's rule on the skills queue. Never fails the review it came with.

    **The slug is the path's, and there is no other candidate.** `propose_skill` raises on a
    blank one rather than filing a row that names no engagement, because a `project`-scoped
    skill with no `source_project` matches nothing and reaches no prompt for ever - and this
    route must not get round that refusal by inventing a value. It cannot: the slug arrives from
    the path, `check_project_access` and the database-existence check have both already passed
    on it, and it is handed over untouched.

    **The swallow is deliberate and it is not the same judgement `propose_skill` makes.** This
    PATCH is what releases a paused crew: `HumanInputTool` polls `human_reviews` for up to
    twenty-four hours and this is the write that ends the wait. Refusing it because the queue
    was unreachable - a locked system database, a model that would not answer, an agent id
    `_SNAKE_TO_DISPLAY` has no entry for - would hold a crew shut to protect a suggestion. So
    the failure is logged and the review stands, which is the contract `SkillProposalTool`
    states for itself one door over.

    Loud, because a proposal path failing on every call is indistinguishable at every later
    layer from reviewers who simply never choose that radio - the queue stays empty either way.

    Returned rather than discarded so the door can say what happened. The module is reached by
    attribute rather than by `from ... import`, so a test patching `skills_service.propose_skill`
    reaches this call - CLAUDE.md's four-crew-tests entry.
    """
    from api.services import skills_service

    try:
        return await skills_service.propose_skill(
            agent_name, rule, slug, f"review:{review_id}",
        )
    except Exception:
        log.warning(
            "skills: the rule a reviewer wrote on review %s of %r could not be filed",
            review_id, slug, exc_info=True,
        )
        return None


class HITLReviewRequest(BaseModel):
    decision: str   # "approved" | "changes_requested"
    notes: str = ""
    intent: str = "change_request"


@router.patch("/{slug}/reviews/{review_id}", status_code=200)
async def resolve_hitl_review(slug: str, review_id: int, req: HITLReviewRequest, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    if not await caller_may_contribute(slug, payload):
        raise HTTPException(
            status_code=403, detail="Only a reviewer or approver may resolve a review"
        )
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    if req.intent not in _INTENTS:
        raise HTTPException(
            status_code=422, detail=f"intent must be one of {', '.join(_INTENTS)}"
        )
    proposing_agent: str | None = None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        updated = await update_review(
            conn, review_id=review_id, decision=req.decision, notes=req.notes
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Review {review_id} not found")
        # An approval is not feedback. Recording one would inject an instruction to do nothing,
        # and - since the skill intent routes below - would file the reviewer's compliment as a
        # standing rule for the agent.
        if req.decision == "changes_requested" and req.notes.strip():
            review = await fetch_review(conn, review_id=review_id)
            if review and review.get("output_id"):
                await insert_output_change(
                    conn,
                    output_id=review["output_id"],
                    requested_by=payload.get("sub", "unknown"),
                    source="review",
                    request=req.notes.strip(),
                    summary="",
                    kind=req.intent,
                )
                if req.intent == _SKILL_INTENT:
                    # The agent whose output was reviewed is who the rule is about. Read here,
                    # where the output is already to hand, and acted on below - `propose_skill`
                    # makes a network call, and holding this connection open across it is the
                    # thing its own comment argues against.
                    proposing_agent = await fetch_output_agent_name(
                        conn, output_id=review["output_id"]
                    )
    result: dict = {"id": review_id, "decision": req.decision, "notes": req.notes}
    if proposing_agent:
        result["skill_proposal"] = await _propose_from_review(
            slug, agent_name=proposing_agent, rule=req.notes.strip(), review_id=review_id,
        )
    return result


@router.delete("/{slug}/reviews/{review_id}", status_code=204)
async def delete_review(slug: str, review_id: int, payload: dict = Depends(require_any_auth)):
    """Remove a review. Approver-gated, unlike recording one: this discards somebody
    else's recorded judgement, and there is no record left afterwards to say it happened."""
    await check_project_access(slug, payload)
    if not await caller_may_approve(slug, payload):
        raise HTTPException(
            status_code=403, detail="Only an approver may delete a review"
        )
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        deleted = await delete_hitl_review(conn, review_id=review_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Review {review_id} not found")


@router.get("/{slug}/reviews")
async def list_pending_reviews(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await get_pending_reviews(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result
