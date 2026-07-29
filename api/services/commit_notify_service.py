# api/services/commit_notify_service.py
"""Tell the people who can act that a crew's output is waiting.

Pamela's remit is project governance - reviewers and approvers. Jordan speaks to the
actors in the organisation, and not from here.

A completed crew concerns reviewers, who can correct it before it is committed.
A submission concerns approvers, who must decide whether to accept it. Each
notification narrows to its own audience via resolve_recipients' flags parameter -
someone who is both reviewer and approver hears at both moments.

notify_crew_awaiting_commit is called from dispatch_crew and dispatch_agent in
api/services/run_service.py, immediately after a crew run completes.
notify_crew_ready_for_approval is called from POST /projects/{slug}/submissions.
"""
from __future__ import annotations

import json
import logging

import httpx

from api.config import get_settings
from api.database import fetch_project, fetch_stakeholders, get_connection
from api.services.pam_report_job import resolve_recipients

log = logging.getLogger(__name__)


async def _send_email(*, to: list[str], subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.resend_api_key:
        raise RuntimeError("RESEND_API_KEY is not configured")
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(
            "https://api.resend.com/emails",
            json={"from": settings.from_email, "to": to, "subject": subject, "text": body},
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Resend returned {resp.status_code}: {resp.text[:200]}")


async def _notify(
    slug: str, crew_name: str, *, flags: tuple[str, ...], subject: str, body_lines: list[str],
    audience_label: str,
) -> None:
    """Shared body for both crew notifications - only the audience, subject and
    message differ. Never raises - a failed notification must not fail a run or a
    submission that has already been recorded."""
    try:
        async with get_connection(slug) as conn:
            project = await fetch_project(conn, slug=slug)
            if not project:
                return
            stakeholders = await fetch_stakeholders(conn, project_id=project["id"])
            # dev_mode lives inside config_json, not as a column - the same read
            # pam_report_job.py:129 performs.
            config = json.loads(project.get("config_json") or "{}")
            dev_mode = bool(config.get("dev_mode", True))

        actual, intended = resolve_recipients(stakeholders, dev_mode, flags=flags)
        if not actual:
            return

        lines = list(body_lines)
        if dev_mode:
            lines += [
                "",
                f"Development mode - this would have gone to: {', '.join(intended) or 'nobody'}",
            ]

        await _send_email(to=actual, subject=subject, body="\n".join(lines))
    except Exception:
        log.exception("could not notify %s about %s", audience_label, crew_name)


async def notify_crew_ready_for_approval(slug: str, crew_name: str) -> None:
    """Tell approvers that a crew has been submitted for approval.

    Called from POST /projects/{slug}/submissions. Never raises - a failed
    notification must not fail a submission that has already been recorded.
    """
    settings = get_settings()
    link = f"{settings.public_url.rstrip('/')}/dashboard/{slug}/reviews"
    await _notify(
        slug, crew_name,
        flags=("is_approver",),
        subject=f"{slug}: {crew_name} is ready for approval",
        body_lines=[
            f"{crew_name} has been submitted and is waiting for approval.",
            "",
            f"Review it here: {link}",
        ],
        audience_label="approvers",
    )


async def notify_crew_awaiting_commit(slug: str, crew_name: str) -> None:
    """Tell reviewers that a crew has finished and is waiting to be committed.

    Called from dispatch_crew and dispatch_agent once a run completes. Never
    raises - a failed notification must not fail a completed run.
    """
    settings = get_settings()
    link = f"{settings.public_url.rstrip('/')}/dashboard/{slug}/reviews"
    await _notify(
        slug, crew_name,
        flags=("is_reviewer",),
        subject=f"{slug}: {crew_name} is ready for review",
        body_lines=[
            f"{crew_name} has finished and its output is waiting to be committed.",
            "",
            f"Review it here: {link}",
        ],
        audience_label="reviewers",
    )
