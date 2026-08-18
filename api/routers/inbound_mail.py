# api/routers/inbound_mail.py
"""The public door a reply arrives at, and the private one a human reads it through.

Two routers, because they are two entirely different kinds of endpoint that happen to be
about the same rows, and putting them in one prefix would blur that:

- `POST /api/inbound-mail/resend` is **unauthenticated and public**. It carries no session,
  it is reached by a mail provider, and it writes. Everything it is allowed to believe comes
  from `verify_signature`; see `api/services/inbound_mail.py` for the whole argument.
- `GET|POST /projects/{slug}/inbound-replies*` is ordinary project-scoped surface, gated by
  `check_project_access` like every other read of a client's material.

Neither mounts a new top-level prefix. `/api` and `/projects` are both already forwarded by
the Caddyfile and the Vite dev proxy, which `tests/test_proxy_prefix_coverage.py` enumerates
`app.routes` to check - a new prefix would have made that test fail rather than making the
endpoint quietly unreachable behind Caddy, which is the failure it exists for.

**The webhook's response body is a module constant.** It is returned for a reply that was
stored, one whose token resolved to nobody, one that named a deleted project, and one that
was a redelivery of a message already held. A body assembled per branch is a body that grows
a branch, and the branch it would grow is the one that tells an unauthenticated caller which
reply tokens exist.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from api.auth import check_project_access, require_any_auth
from api.services.inbound_mail import (
    ACCEPTED_CONTENT_TYPE,
    MAX_BODY_BYTES,
    InboundRefused,
    store_inbound_reply,
    verify_signature,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inbound-mail", tags=["inbound-mail"])
replies_router = APIRouter(prefix="/projects", tags=["inbound-mail"])

# The one answer a verified request ever gets. See the module docstring.
ACCEPTED: dict[str, str] = {"status": "accepted"}


async def _bounded_body(request: Request) -> bytes:
    """The request body, refused with 413 if it is over the limit.

    Checked twice on purpose. `Content-Length` is checked first so an oversized body is
    refused without being read at all, and the read result is checked again because a
    chunked request carries no `Content-Length` to have checked - a limit that trusted the
    header would be a limit any caller could opt out of by omitting it.
    """
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_BODY_BYTES:
                raise InboundRefused(413, "payload too large")
        except ValueError:
            raise InboundRefused(400, "malformed content-length") from None
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise InboundRefused(413, "payload too large")
    return body


@router.post("/resend")
async def receive_resend_webhook(request: Request) -> dict[str, str]:
    """Accept one signed inbound message from Resend.

    The order is the security property, and it is the module docstring's first section:
    bound the body, verify the signature over exactly those bytes, and only then parse. A
    request that fails any of the first two is refused having touched no database.
    """
    try:
        body = await _bounded_body(request)
        provider_event_id = verify_signature(headers=request.headers, body=body)
    except InboundRefused as refused:
        raise HTTPException(status_code=refused.status_code, detail=refused.detail) from None

    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != ACCEPTED_CONTENT_TYPE:
        # After the signature, so an unsigned caller learns nothing from the difference.
        raise HTTPException(status_code=415, detail="unsupported media type")

    try:
        payload = json.loads(body)
    except Exception:
        # Signed by the provider and still unreadable: that is the provider's fault or ours,
        # not a routing decision, so it is said plainly rather than swallowed as "accepted".
        log.warning("inbound mail: %s carried a body that is not JSON", provider_event_id)
        raise HTTPException(status_code=400, detail="malformed payload") from None
    if not isinstance(payload, dict):
        log.warning("inbound mail: %s carried JSON that is not an object", provider_event_id)
        raise HTTPException(status_code=400, detail="malformed payload")

    await store_inbound_reply(provider_event_id=provider_event_id, payload=payload)
    return ACCEPTED


@replies_router.get("/{slug}/inbound-replies")
async def list_inbound_replies(slug: str, payload: dict = Depends(require_any_auth)) -> dict:
    """Every reply this engagement has received, newest first, with an unread count.

    The count is the reason this is one call rather than two: a reply nobody sees is a reply
    lost, and the surface needs something to put a number on without fetching the bodies.
    """
    await check_project_access(slug, payload)
    from api.database import fetch_inbound_replies, fetch_project, get_connection, get_db_path

    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        rows = await fetch_inbound_replies(conn, project_id=project["id"])
    return {
        "replies": [
            {
                "id": row["id"],
                "stakeholder_id": row["stakeholder_id"],
                "stakeholder_name": row["stakeholder_name"] or "",
                "stakeholder_email": row["stakeholder_email"] or "",
                "subject": row["subject"],
                "body": row["body"],
                "truncated": bool(row["truncated"]),
                "attachment_count": row["attachment_count"],
                "received_at": row["received_at"],
                "read_at": row["read_at"],
            }
            for row in rows
        ],
        "unread": sum(1 for row in rows if row["read_at"] is None),
    }


@replies_router.post("/{slug}/inbound-replies/{reply_id}/read")
async def mark_reply_read(
    slug: str, reply_id: int, payload: dict = Depends(require_any_auth)
) -> dict:
    """Record that a human has read this reply. Idempotent - reading twice is not an error."""
    await check_project_access(slug, payload)
    from api.database import (
        fetch_project, get_connection, get_db_path, mark_inbound_reply_read,
    )

    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        changed = await mark_inbound_reply_read(
            conn, project_id=project["id"], reply_id=reply_id, by=str(payload.get("sub") or "")
        )
    return {"ok": True, "changed": changed}
