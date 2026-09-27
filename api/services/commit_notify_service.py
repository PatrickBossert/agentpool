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

# The crew whose Output tab renders each per-item review ledger.
#
# **This is what the emailed link must name, and it is not the item.** `_notify`'s second
# positional argument goes into `?crew=` and `Dashboard.tsx` seeds the selected crew from it,
# so both send-back notifiers used to mail `?crew=SC-014` and `?crew=3.3.3` - a reviewer told
# a script had been sent back landed on a crew that does not exist, one click away from the
# ledger they were notified about and with no way to tell they were on the wrong page. It
# survived because both tests of the notifier patched the notifier out, so the line that
# builds the link had never run. A mock is the right tool for "did we notify?" and it is
# exactly why nobody had run it.
#
# Declared here and held against `OUTPUT_OWNERS` and `_CREW_AGENT_NAMES` by
# tests/test_send_back_notifications.py, which derives the expected value rather than
# restating it - so a ledger whose agent moves to another crew fails there instead of
# quietly mailing a dead link. Keyed on the ledger, not on the agent: `discovery_mapping`
# holds two agents and both of its ledgers render on the one tab.
LEDGER_CREW: dict[str, str] = {
    "script": "assessment_design",
    "node": "discovery_mapping",
    "lever": "discovery_mapping",
}


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
        # The subject is logged as well as the crew, because since the send-back notifiers
        # started passing a crew rather than an item id - which is the fix that stopped the
        # link pointing at `?crew=SC-014` - the crew alone no longer says which thing failed
        # to be announced. The subject names it.
        log.exception(
            "could not notify %s about %s (%s)", audience_label, crew_name, subject
        )


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

    The crew is `LEDGER_CREW["script"]` and not `script_id`. The script id belongs in the
    subject and the intro, which is where it is; putting it where the link's `?crew=` is
    built sent every one of these notifications to a crew that does not exist.
    """
    await _notify(
        slug, LEDGER_CREW["script"],
        flags=("is_reviewer",),
        fallback_flags=("is_approver",),
        subject=f"{slug}: interview script {script_id} was sent back",
        intro=(f"{script_id} has been sent back to the {return_to}. "
               f"Note: {notes}" if notes else f"{script_id} has been sent back to the {return_to}."),
        audience_label="reviewers",
    )


async def notify_scripts_sent_back(
    slug: str, script_ids: list[str], return_to: str, notes: str
) -> None:
    """Tell the right audience that a batch of scripts has been sent back. Never raises.

    **One notification for the batch, and that is the whole reason the bulk door exists.**
    Correcting the eighty-five scripts still carrying the old closing through the singular
    door means eighty-five calls, each firing `notify_script_sent_back` - eighty-five emails
    about one decision. A notifier called inside the door's loop would have removed the
    eighty-five calls and kept the eighty-five emails, which is the defect arriving by a
    different route.

    The same audience and the same fallback as `notify_script_sent_back`, and written beside
    it rather than folded into it: the subject names a count and the intro names a list, and a
    shared function would have had to say "one or more scripts" to both of them.

    Every id is named in the body. The list is the record of what was done, and a reviewer
    opening the ledger needs to know which rows moved - eighty-five ids is roughly six hundred
    characters, which is a smaller cost than an email that says only "some scripts".

    The crew is `LEDGER_CREW["script"]`, for the reason its sibling records: `_notify`'s second
    positional argument becomes `?crew=`, and passing anything item-shaped there builds a link
    to a crew that does not exist.
    """
    count = len(script_ids)
    noun = "script" if count == 1 else "scripts"
    sent = (f"{count} interview {noun} sent back to the {return_to}: "
            f"{', '.join(script_ids)}.")
    await _notify(
        slug, LEDGER_CREW["script"],
        flags=("is_reviewer",),
        fallback_flags=("is_approver",),
        subject=f"{slug}: {count} interview {noun} were sent back",
        intro=f"{sent} Note: {notes}" if notes else sent,
        audience_label="reviewers",
    )


async def notify_item_sent_back(
    slug: str, kind: str, item_id: str, return_to: str, notes: str
) -> None:
    """Tell the right audience that one value chain node or one value lever was sent back.

    The same audience and the same reasoning as `notify_script_sent_back` above, and written
    beside it rather than inside it because the subject line names what the item is: "value
    chain node 3.3.3" and "value lever LV-001" are what a reviewer recognises, and a shared
    function would have had to say "item" to both of them.

    A send-back to the agent notifies reviewers, because the agent will regenerate it and
    they will need to read it again; a send-back to reviewers notifies reviewers because they
    are the people it was sent to. The audience is the same either way.

    Never raises - `_notify` swallows its own body, and the caller defends locally as well.

    The crew comes from `LEDGER_CREW`, so the link lands on the tab that renders the ledger.
    An unrecognised kind falls back to `discovery_mapping` rather than to `item_id`: both are
    wrong, and one of them is wrong in the way that produced `?crew=3.3.3`. The kind is
    refused long before this by `record_item_review`, so the fallback is defence and not a
    live path.
    """
    label = {"node": "value chain node", "lever": "value lever"}.get(kind, kind)
    sent = f"{item_id} has been sent back to the {return_to}."
    await _notify(
        slug, LEDGER_CREW.get(kind, "discovery_mapping"),
        flags=("is_reviewer",),
        fallback_flags=("is_approver",),
        subject=f"{slug}: {label} {item_id} was sent back",
        intro=f"{sent} Note: {notes}" if notes else sent,
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
