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


async def _notify(
    slug: str, crew_name: str, *, flags: tuple[str, ...], subject: str, intro: str,
    audience_label: str, fallback_flags: tuple[str, ...] | None = None,
    extra_recipient: str | None = None,
) -> None:
    """Shared body for both crew notifications - only the audience, subject and
    intro line differ. Never raises - a failed notification must not fail a run or
    a submission that has already been recorded. Link construction lives inside
    this try too: get_settings() is a call that can raise, and it must not escape
    into the caller's own error handling (dispatch_crew/dispatch_agent would
    otherwise overwrite a just-recorded status="completed" with status="failed").

    fallback_flags: if the primary flags resolve to nobody, try this audience
    instead rather than notify nobody. Only the completion notification passes
    this - see notify_crew_awaiting_commit for why.

    extra_recipient: an address to add to the flag-resolved audience, on top of
    whatever stakeholder flags produced - used by notify_crew_failed to reach
    whoever's approval triggered the run, in addition to reviewers. Subject to
    the same dev_mode routing as everyone else: in dev mode it is folded into the
    "would have gone to" list rather than sent to directly."""
    try:
        settings = get_settings()
        link = f"{settings.public_url.rstrip('/')}/dashboard/{slug}/reviews"

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
        if not actual and fallback_flags:
            actual, intended = resolve_recipients(stakeholders, dev_mode, flags=fallback_flags)

        if extra_recipient and extra_recipient not in intended:
            intended = [*intended, extra_recipient]
            if dev_mode:
                actual = [DEV_MODE_ADDRESS]
            elif extra_recipient not in actual:
                actual = [*actual, extra_recipient]

        if not actual:
            return

        lines = [intro, "", f"Review it here: {link}"]
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
    await _notify(
        slug, crew_name,
        flags=("is_approver",),
        subject=f"{slug}: {crew_name} is ready for approval",
        intro=f"{crew_name} has been submitted and is waiting for approval.",
        audience_label="approvers",
    )


async def notify_crew_awaiting_commit(slug: str, crew_name: str) -> None:
    """Tell reviewers that a crew has finished and is waiting to be committed.

    Called from dispatch_crew and dispatch_agent once a run completes. Never
    raises - a failed notification must not fail a completed run.

    Falls back to approvers when there are no reviewers: a project whose governing
    stakeholders are all flagged is_approver and none is_reviewer would otherwise
    get no completion email at all, so nobody would ever learn the crew finished
    and nothing would ever be submitted - the loop would never begin. An approver
    hearing about a completion is a smaller harm than nobody hearing at all.

    The reverse fallback is not applied to the submission notification below: if
    there are no approvers, there is genuinely nobody who can approve, and mailing
    reviewers instead would not help.
    """
    await _notify(
        slug, crew_name,
        flags=("is_reviewer",),
        fallback_flags=("is_approver",),
        subject=f"{slug}: {crew_name} is ready for review",
        intro=f"{crew_name} has finished and its output is waiting to be committed.",
        audience_label="reviewers",
    )


async def notify_crew_failed(
    slug: str, crew_name: str, *, triggered_by: str | None
) -> None:
    """Tell reviewers - and whoever's approval started it - that a run failed.

    Project 1 deliberately sends nothing when an approval lands, on the grounds that the
    next crew starting is the signal. If that crew then dies, the signal was false, and
    the person holding a wrong belief is the one who approved. They are notified in
    addition to reviewers, who would otherwise wait for output that is not coming.

    Never raises: dispatch_crew re-raises the original run failure after calling this, and
    a mail error must not replace the real one.
    """
    await _notify(
        slug, crew_name,
        flags=("is_reviewer",),
        extra_recipient=triggered_by,
        subject=f"{slug}: {crew_name} failed",
        intro=f"{crew_name} started but did not finish. Nothing is in flight for it now.",
        audience_label="reviewers",
    )
