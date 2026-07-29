# api/services/commit_notify_service.py
"""Tell the people who can act that a crew's output is waiting.

Pamela's remit is project governance - reviewers and approvers. Jordan speaks to the
actors in the organisation, and not from here.
"""
from __future__ import annotations

import json
import logging

import httpx

from api.config import get_settings
from api.database import fetch_project, fetch_stakeholders, get_connection
from api.services.pam_report_job import DEV_MODE_ADDRESS, resolve_recipients

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


async def notify_crew_awaiting_commit(slug: str, crew_name: str) -> None:
    """Never raises. A failed notification must not fail a completed run."""
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

        actual, intended = resolve_recipients(stakeholders, dev_mode)
        if not actual:
            return

        settings = get_settings()
        link = f"{settings.public_url.rstrip('/')}/dashboard/{slug}/reviews"
        lines = [
            f"{crew_name} has finished and its output is waiting to be committed.",
            "",
            f"Review it here: {link}",
        ]
        if dev_mode:
            lines += [
                "",
                f"Development mode - this would have gone to: {', '.join(intended) or 'nobody'}",
            ]

        await _send_email(
            to=actual,
            subject=f"{slug}: {crew_name} is ready for review",
            body="\n".join(lines),
        )
    except Exception:
        log.exception("could not notify reviewers that %s is awaiting commit", crew_name)
