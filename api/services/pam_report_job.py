"""Pamela's daily status report.

Computes the report from live state using the same derivation the endpoint uses,
compares it with the previous stored report, records it as a versioned artefact
for the audit trail, and emails a link to the people who review it.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

import httpx

from api.config import get_settings
from api.database import (
    fetch_project,
    fetch_stakeholders,
    get_connection,
    insert_agent_output,
)
from api.services.pam_report_service import build_pam_report
from api.services.report_diff_service import diff_reports
from api.services.scheduler_service import JOB_REGISTRY

logger = logging.getLogger(__name__)

JOB_NAME = "pam_daily_report"
OUTPUT_TYPE = "pam_report"
DEV_MODE_ADDRESS = "Patrick@FutureEdge.consulting"
# The multi-valued engagement-role columns, not project_role: one person can be
# both a reviewer and an approver, which a single-select role cannot express.
REVIEW_FLAGS = ("is_reviewer", "is_approver")


def resolve_recipients(
    stakeholders: list[dict], dev_mode: bool, flags: tuple[str, ...] = REVIEW_FLAGS
) -> tuple[list[str], list[str]]:
    """Return (actual, intended) email lists for stakeholders carrying any of `flags`.

    In dev mode everything is redirected to one address, but the intended list is
    still computed so the message can say who would have received it. An empty
    intended list stays empty - redirecting nothing must not invent a recipient.

    Defaulting to both review flags keeps the daily report's audience unchanged: it
    goes to everyone with a governance role, which is what it is for. The crew
    notifications pass a narrower tuple, because a completed crew concerns reviewers
    and a submission concerns approvers.
    """
    intended = [
        s["email"] for s in stakeholders
        if any(s.get(flag) for flag in flags) and (s.get("email") or "").strip()
    ]
    if not intended:
        return [], []
    return ([DEV_MODE_ADDRESS] if dev_mode else list(intended)), intended


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


async def _send_email(to: list[str], subject: str, body: str) -> None:
    """Send a plain-text message through Resend. Raises on failure."""
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


def _compose_body(slug: str, report: dict, change: dict, intended: list[str], dev_mode: bool) -> str:
    settings = get_settings()
    link = f"{settings.public_url.rstrip('/')}/dashboard/{slug}/pam-report"
    lines = [
        f"Status report for {slug} - {datetime.now().strftime('%d %B %Y')}",
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
    lines += ["", f"Read the full report: {link}"]
    if dev_mode:
        lines += [
            "",
            "-- dev mode --",
            "This project has dev_mode enabled, so this message was sent only to you.",
            "Intended recipients: " + (", ".join(intended) or "none"),
        ]
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
        config = json.loads(project.get("config_json") or "{}")
        dev_mode = bool(config.get("dev_mode", True))

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

    actual, intended = resolve_recipients(stakeholders, dev_mode)
    if not actual:
        logger.info("pam report job: %s has no reviewer or approver stakeholders - stored, not sent", slug)
        return

    subject = f"{slug} status report - {datetime.now().strftime('%d %b %Y')}"
    body = _compose_body(slug, report, change, intended, dev_mode)
    try:
        await _send_email(actual, subject, body)
    except Exception as exc:
        # The report is already stored. A notification failure must not lose it.
        logger.warning("pam report job: email failed for %s: %s", slug, exc)


JOB_REGISTRY[JOB_NAME] = run_pam_daily_report
