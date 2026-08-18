"""Pamela's daily status report.

Computes the report from live state using the same derivation the endpoint uses,
compares it with the previous stored report, records it as a versioned artefact
for the audit trail, and emails a link to the people who review it.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from api.config import get_settings
from api.database import (
    fetch_project,
    fetch_stakeholders,
    get_connection,
    insert_agent_output,
)
from api.services.outbound_mail import GOVERNANCE, config_client_name, send_project_mail
from api.services.pam_report_service import build_pam_report
from api.services.report_diff_service import diff_reports
from api.services.scheduler_service import JOB_REGISTRY

logger = logging.getLogger(__name__)

JOB_NAME = "pam_daily_report"
OUTPUT_TYPE = "pam_report"
# The multi-valued engagement-role columns, not project_role: one person can be
# a reviewer, an approver and a governor at once, which a single-select role cannot
# express.
#
# `is_governor` joined the tuple in sp44. The design has always said governors receive
# PAM's reports, and this is the one place that sentence is expressible - but until the
# flag was grantable it selected nobody, so adding it would have been decoration. It is
# also the *only* thing the governor role does: nothing gates on it, and milestone
# completion (the design's other half) has no distinct action in the code to gate.
REVIEW_FLAGS = ("is_reviewer", "is_approver", "is_governor")


def resolve_recipients(
    stakeholders: list[dict], flags: tuple[str, ...] = REVIEW_FLAGS
) -> list[str]:
    """The addresses this message is *for* - stakeholders carrying any of `flags`.

    Audience selection only. It used to return `(actual, intended)` and apply the
    `dev_mode` redirect itself, which meant the delivery decision lived in two modules
    and was absent from three others; `outbound_mail.send_project_mail` owns it now, and
    this function answers the question it is actually qualified to answer.

    Defaulting to all three review flags keeps the daily report's audience unchanged: it
    goes to everyone with a governance role, which is what it is for. The crew
    notifications pass a narrower tuple, because a completed crew concerns reviewers
    and a submission concerns approvers.
    """
    return [
        s["email"] for s in stakeholders
        if any(s.get(flag) for flag in flags) and (s.get("email") or "").strip()
    ]


async def _previous_report(conn, project_id: int) -> dict | None:
    """The most recent stored report, or None when this is the first."""
    async with conn.execute(
        "SELECT file_path FROM agent_outputs WHERE project_id=? AND agent_name='PAM' "
        "AND output_type=? ORDER BY version DESC LIMIT 1",
        (project_id, OUTPUT_TYPE),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    try:
        return json.loads(Path(row["file_path"]).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("pam report job: previous report unreadable (%s) - treating as first", exc)
        return None


async def _next_version(conn, project_id: int) -> int:
    async with conn.execute(
        "SELECT MAX(version) FROM agent_outputs WHERE project_id=? AND agent_name='PAM' "
        "AND output_type=?",
        (project_id, OUTPUT_TYPE),
    ) as cur:
        return ((await cur.fetchone())[0] or 0) + 1


def _report_header(slug: str, client_name: str) -> str:
    """Who this report is about, named both ways.

    Governance mail is addressed and filed by slug - that is how a governor tracking four
    engagements at once names this one in a status meeting, so the subject line keeps it and
    `outbound_mail` deliberately does not prefix governance subjects with the friendly name.
    The header is where the two names are reconciled: `GS Asset Management (sp-gs-am)` gives
    the reader the mapping in the one place they will look for it, without changing how the
    message is addressed.

    Composed here rather than in the seam, and that is not an oversight. The seam owns the
    envelope - who the message is from, who it reaches, and the subject that heads it - while
    the report remains the author of its own content. Pushing a body header through
    `send_project_mail` would make the seam a composer of governance prose, and the next
    caller with a different body shape would have to be composed for too.

    Falls back to the slug alone when there is no `client_name` - which is every project
    today - rather than emitting an empty bracket.
    """
    named = f"{client_name} ({slug})" if client_name else slug
    return f"Status report for {named} - {datetime.now().strftime('%d %B %Y')}"


def _compose_body(slug: str, report: dict, change: dict, client_name: str = "") -> str:
    settings = get_settings()
    link = f"{settings.public_url.rstrip('/')}/dashboard/{slug}/pam-report"
    lines = [
        _report_header(slug, client_name),
        "",
        f"Overall health: {report.get('overall_health', 'unknown')}",
        report.get("health_summary", ""),
        "",
        f"Changes since the last report: {change['summary']}",
    ]
    for label, key in [("New risks", "new_risks"), ("New issues", "new_issues")]:
        if change.get(key):
            lines.append("")
            lines.append(f"{label}:")
            lines.extend(f"  - {t}" for t in change[key])
    # No dev-mode footer here any more: send_project_mail appends it, because it is the
    # thing that decides whether the message was redirected at all.
    lines += ["", f"Read the full report: {link}"]
    return "\n".join(lines)


async def run_pam_daily_report(slug: str) -> None:
    """Generate, store and send Pamela's report for one project."""
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
    if not project:
        logger.warning("pam report job: project %s not found - skipping", slug)
        return
    if project.get("status") != "active":
        # A project still in setup (e.g. 'created', awaiting approval) has
        # nothing worth reporting on yet - and checking this before
        # build_pam_report avoids doing that work for every skipped project.
        logger.info(
            "pam report job: project %s is not active - skipping", slug
        )
        return

    report = await build_pam_report(slug)

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            logger.warning("pam report job: project %s not found - skipping", slug)
            return
        project_id = project["id"]

        previous = await _previous_report(conn, project_id)
        change = diff_reports(previous, report)
        report["change_summary"] = change

        version = await _next_version(conn, project_id)
        outputs_dir = Path(get_settings().projects_dir) / slug / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        path = outputs_dir / f"{OUTPUT_TYPE}_v{version}.json"
        path.write_text(json.dumps(report, indent=2))

        # insert_agent_output does not manage is_current, unlike the sync helper
        # the crew tools use. Supersede explicitly or every report looks stale.
        await conn.execute(
            "UPDATE agent_outputs SET is_current=0 WHERE project_id=? AND agent_name='PAM' "
            "AND output_type=?",
            (project_id, OUTPUT_TYPE),
        )
        output_id = await insert_agent_output(
            conn, project_id=project_id, agent_name="PAM",
            output_type=OUTPUT_TYPE, file_path=str(path), version=version,
        )
        await conn.execute("UPDATE agent_outputs SET is_current=1 WHERE id=?", (output_id,))
        await conn.commit()

        stakeholders = await fetch_stakeholders(conn, project_id=project_id)

    intended = resolve_recipients(stakeholders)
    if not intended:
        logger.info(
            "pam report job: %s has no reviewer, approver or governor stakeholders "
            "- stored, not sent", slug,
        )
        return

    # The subject stays keyed on the slug: this audience files by it. The friendly name is
    # carried in the header of the body instead - see `_report_header`.
    subject = f"{slug} status report - {datetime.now().strftime('%d %b %Y')}"
    body = _compose_body(
        slug, report, change,
        client_name=config_client_name(json.loads(project.get("config_json") or "{}")),
    )
    try:
        # Governance: this is the report Pamela's own remit produces, and it goes to
        # reviewers, approvers and governors.
        await send_project_mail(
            slug=slug, audience=GOVERNANCE, to=intended, subject=subject, body=body,
        )
    except Exception as exc:
        # The report is already stored. A notification failure must not lose it.
        logger.warning("pam report job: email failed for %s: %s", slug, exc)


JOB_REGISTRY[JOB_NAME] = run_pam_daily_report
