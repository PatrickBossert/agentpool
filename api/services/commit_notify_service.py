# api/services/commit_notify_service.py
"""Tell the people who can act that a crew's output is waiting.

Pamela's remit is project governance - reviewers and approvers. Jordan speaks to the
actors in the organisation, and not from here.

A completed crew concerns reviewers, who can correct it before it is committed.
A submission concerns approvers, who must decide whether to accept it. Each
notification narrows to its own audience via resolve_recipients' flags parameter -
someone who is both reviewer and approver hears at both moments.

A failed run concerns reviewers too - they are waiting for output that is not coming -
and additionally whoever's approval started it, who would otherwise believe work is in
flight. That one names a specific address on top of the flag-resolved audience.

notify_crew_awaiting_commit is called from dispatch_crew and dispatch_agent in
api/services/run_service.py, immediately after a crew run completes.
notify_crew_ready_for_approval is called from POST /projects/{slug}/submissions.
notify_crew_failed is called from dispatch_crew's failure path, before it re-raises.
"""
from __future__ import annotations

import logging

from api.database import fetch_project, fetch_stakeholders, get_connection
from api.services.outbound_mail import GOVERNANCE, send_project_mail
from api.services.pam_report_job import resolve_recipients
from api.services.platform_settings import platform_public_url

log = logging.getLogger(__name__)


async def _notify(
    slug: str, crew_name: str, *, flags: tuple[str, ...], subject: str, intro: str,
    audience_label: str, fallback_flags: tuple[str, ...] | None = None,
    extra_recipient: str | None = None,
) -> None:
    """Shared body for both crew notifications - only the audience, subject and
    intro line differ. Never raises - a failed notification must not fail a run or
    a submission that has already been recorded. Link construction lives inside
    this try too: platform_public_url() is a call that can raise (it reads
    get_settings() itself), and it must not escape into the caller's own error
    handling (dispatch_crew/dispatch_agent would otherwise overwrite a
    just-recorded status="completed" with status="failed").

    fallback_flags: if the primary flags resolve to nobody, try this audience
    instead rather than notify nobody. Only the completion notification passes
    this - see notify_crew_awaiting_commit for why.

    extra_recipient: an address to add to the flag-resolved audience, on top of
    whatever stakeholder flags produced - used by notify_crew_failed to reach
    whoever's approval triggered the run, in addition to reviewers. Subject to
    the same dev_mode routing as everyone else, because send_project_mail decides
    the recipients for every entry in this list alike. Anything that is not an
    address is discarded before it reaches the recipient list: Resend rejects
    the whole request when one entry is malformed, so a stray username would take
    the reviewers' notification down with it.

    The dev_mode read and the "would have gone to" footer both used to live here.
    They are send_project_mail's now - see api/services/outbound_mail.py."""
    try:
        link = (
            f"{platform_public_url()}/dashboard/{slug}"
            f"?crew={crew_name}&tab=output"
        )

        async with get_connection(slug) as conn:
            project = await fetch_project(conn, slug=slug)
            if not project:
                return
            stakeholders = await fetch_stakeholders(conn, project_id=project["id"])

        intended = resolve_recipients(stakeholders, flags=flags)
        if not intended and fallback_flags:
            intended = resolve_recipients(stakeholders, flags=fallback_flags)

        if extra_recipient and "@" not in extra_recipient:
            log.warning(
                "discarding extra recipient %r for %s: not an address",
                extra_recipient, crew_name,
            )
            extra_recipient = None

        if extra_recipient and extra_recipient not in intended:
            intended = [*intended, extra_recipient]

        if not intended:
            return

        lines = [intro, "", f"Review it here: {link}"]

        # Governance: reviewers, approvers, and whoever's approval started the run.
        await send_project_mail(
            slug=slug, audience=GOVERNANCE, to=intended,
            subject=subject, body="\n".join(lines),
        )
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


async def notify_crew_awaiting_commit(
    slug: str, crew_name: str, *, outputs_written: int | None = None
) -> None:
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
    # `outputs_written` is what the dispatcher counted either side of the run. A run that
    # wrote nothing must not be announced as having something to commit: run 36 of sp-gs-am
    # finished in 50 seconds with full coverage and nothing sent back, wrote no output at
    # all, and this said its output "is waiting to be committed". A reviewer who opens the
    # dashboard and finds nothing learns to discount the notification, which costs more than
    # the wasted trip - it is the one that matters that they will then ignore.
    #
    # The empty message says what was observed and **not why**. A run writes nothing when it
    # is owed nothing, and also when it fails before doing anything - `result_json` is `{}`
    # either way, which is the ambiguity run 32 is on record for. Naming a cause here would
    # be inventing one.
    #
    # `None` means the caller did not count, and keeps the original sentence: a new caller
    # that forgets the argument over-reports rather than falling silent, which is the safe
    # direction for a notification.
    nothing_written = outputs_written == 0
    await _notify(
        slug, crew_name,
        flags=("is_reviewer",),
        fallback_flags=("is_approver",),
        # "ready for review" sent people to the HITL review queue, which has been empty
        # for these crews since crews stopped blocking for a typed approval - the output is
        # waiting to be committed, and the subject has to say the same thing the body does.
        subject=(
            f"{slug}: {crew_name} finished, nothing to commit" if nothing_written
            else f"{slug}: {crew_name} is ready to commit"
        ),
        intro=(
            f"{crew_name} has finished and wrote no new output, so nothing is waiting to "
            f"be committed."
            if nothing_written
            else f"{crew_name} has finished and its output is waiting to be committed."
        ),
        audience_label="reviewers",
    )


async def notify_script_sent_back(
    slug: str, script_id: str, return_to: str, notes: str
) -> None:
    """Tell the right audience that one script has been sent back. Never raises.

    A send-back to the agent notifies reviewers, because Maya will regenerate it and they
    will need to read it again. A send-back to reviewers notifies reviewers too - they are
    the audience either way, and the difference lies in what happens to the script, not in
    who hears about it.

    The reviewer fallback to approvers is inherited from notify_crew_awaiting_commit
    deliberately: a project whose governing stakeholders are all approvers and none
    reviewers would otherwise hear nothing. The reverse fallback is not applied anywhere,
    because with no approvers there is genuinely nobody who can approve.
    """
    await _notify(
        slug, script_id,
        flags=("is_reviewer",),
        fallback_flags=("is_approver",),
        subject=f"{slug}: interview script {script_id} was sent back",
        intro=(f"{script_id} has been sent back to the {return_to}. "
               f"Note: {notes}" if notes else f"{script_id} has been sent back to the {return_to}."),
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
