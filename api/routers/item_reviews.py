# api/routers/item_reviews.py
"""Per-node and per-lever review endpoints - the `discovery_mapping` half of what
`script_reviews.py` does for Maya.

Four doors, two reads and two writes, and the two writes are the pair Task 3 meant when it
said the recorder owes `reviewed_at_version` and **both review doors must reach it**. Neither
door passes that stamp: `record_item_review` reads `last_version` off the row it is already
holding and stamps from that, so there is no parameter for a door to forget. See that
function for why the signature differs from `record_script_review`'s.

**Authority is the two named content gates, not a fifth copy of them.** CLAUDE.md records
that four older call sites - `script_reviews.py` among them - restate the role sets inline and
are not uniform with each other. `caller_may_contribute` is `{reviewer, approver}` and
`caller_may_approve` is `{approver}`; both live in `authority_service.py` and are asked here
by name. Recording an opinion about what the project currently says is the *content* axis, so
these are content gates on top of the membership floor and never
`require_project_administration` - a consultant configures the engagement, and judging Alex's
value chain is not configuration.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import check_project_access, require_any_auth
from api.database import fetch_project, get_connection
from api.services.authority_service import caller_may_approve, caller_may_contribute
from api.services.item_review_service import (
    AlreadyApprovedError,
    NotYetReviewedError,
    item_ledger_rows,
    record_item_review,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["item-reviews"])


class ItemReviewRequest(BaseModel):
    decision: str
    notes: str = ""
    return_to: str | None = None
    forced: bool = False


async def _ledger(slug: str, kind: str, payload: dict) -> list[dict]:
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return await item_ledger_rows(conn, project_id=project["id"], kind=kind)


async def _review(
    slug: str, kind: str, item_id: str, body: ItemReviewRequest, payload: dict
) -> dict:
    """Both write doors, in one body, because the two differ only in which ledger they name.

    The refusal sentence names the kind, so "a reviewer was refused on a node" and "a reviewer
    was refused on a lever" are told apart in a log and in a test rather than being one
    sentence that could have come from either.
    """
    await check_project_access(slug, payload)
    permitted = (
        await caller_may_approve(slug, payload)
        if body.decision == "approved"
        else await caller_may_contribute(slug, payload)
    )
    if not permitted:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Not permitted to approve this {kind}"
                if body.decision == "approved"
                else f"Not permitted to review this {kind}"
            ),
        )

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        try:
            updated = await record_item_review(
                conn, project_id=project["id"], kind=kind, item_id=item_id,
                reviewer=payload.get("sub", ""), decision=body.decision,
                notes=body.notes, return_to=body.return_to, forced=body.forced,
            )
        except (AlreadyApprovedError, NotYetReviewedError) as e:
            # A conflict with stored state, not a malformed request - branching on the
            # exception's type rather than on its wording, so a reworded message cannot
            # silently reclassify a conflict as a 422.
            raise HTTPException(status_code=409, detail=str(e))
        except ValueError as e:
            # An unknown decision, a send-back with no target, or an id with no ledger row.
            # The last is arguably a 404; it is a 422 here because it is the same class of
            # answer the other two are - the body named something the ledger does not hold -
            # and script_reviews.py's 404 for it required a second query this door does not
            # make.
            raise HTTPException(status_code=422, detail=str(e))

    if body.decision == "changes_requested":
        from api.services.commit_notify_service import notify_item_sent_back
        # The review is already committed above; a failed notification must not turn a
        # recorded review into a failed request. notify_item_sent_back already wraps its own
        # body, so this is redundant today - but that guarantee lives two modules away, and a
        # bare call here would silently start depending on it staying that way.
        try:
            await notify_item_sent_back(
                slug, kind, item_id, body.return_to or "", body.notes
            )
        except Exception:
            log.exception(
                "could not notify about %s %s sent back on %s", kind, item_id, slug
            )
    return updated


@router.get("/{slug}/node-ledger")
async def get_node_ledger(slug: str, payload: dict = Depends(require_any_auth)):
    return await _ledger(slug, "node", payload)


@router.get("/{slug}/lever-ledger")
async def get_lever_ledger(slug: str, payload: dict = Depends(require_any_auth)):
    return await _ledger(slug, "lever", payload)


@router.post("/{slug}/node-ledger/{node_id}/review")
async def review_node(
    slug: str, node_id: str, body: ItemReviewRequest,
    payload: dict = Depends(require_any_auth),
):
    return await _review(slug, "node", node_id, body, payload)


@router.post("/{slug}/lever-ledger/{lever_id}/review")
async def review_lever(
    slug: str, lever_id: str, body: ItemReviewRequest,
    payload: dict = Depends(require_any_auth),
):
    return await _review(slug, "lever", lever_id, body, payload)
