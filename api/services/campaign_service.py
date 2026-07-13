# api/services/campaign_service.py
"""Campaign management — interview tracking service layer."""
import csv
import io
import json as _json
from datetime import datetime, timezone

from api.config import get_settings
import httpx

from api.database import (
    get_connection,
    get_db_path,
    fetch_project,
    insert_campaign,
    fetch_campaigns,
    fetch_campaign,
    update_campaign,
    delete_campaign,
    fetch_stakeholders_for_value_stream,
    update_stakeholder_interview_status,
    insert_interview_response,
    fetch_interview_responses,
    insert_reminder_email,
    fetch_reminder_emails,
    update_reminder_email,
    fetch_session_token_for_stakeholder,
    fetch_approved_reminder_emails,
    mark_reminder_email_sent,
)

# ── Reminder templates ─────────────────────────────────────────────────────────

REMINDER_TEMPLATES = {
    "gentle": {
        "subject": "A quick reminder — we'd love your input",
        "body": (
            "Hi {name},\n\n"
            "We noticed you haven't yet completed your stakeholder interview for the "
            "{campaign_name} initiative. Your perspective is genuinely valuable to us "
            "and will directly shape the recommendations we make.\n\n"
            "The interview takes around 10–15 minutes and can be completed at a time "
            "that suits you. Please follow the link below to get started:\n\n"
            "{interview_url}\n\n"
            "Thank you for your time.\n\n"
            "Best regards,\nThe Project Team"
        ),
    },
    "firm": {
        "subject": "Reminder — your interview is still open",
        "body": (
            "Hi {name},\n\n"
            "We're still hoping to capture your perspective as part of the "
            "{campaign_name} stakeholder engagement. We'd really appreciate "
            "you completing the short interview when you get a chance:\n\n"
            "{interview_url}\n\n"
            "Your input helps us ensure the recommendations we make reflect "
            "the full range of stakeholder views.\n\n"
            "Best regards,\nThe Project Team"
        ),
    },
    "urgent": {
        "subject": "Final reminder — interview window closing soon",
        "body": (
            "Hi {name},\n\n"
            "This is a final reminder that the stakeholder interview window for "
            "{campaign_name} is closing very soon. After this date we will not "
            "be able to include your input in the analysis.\n\n"
            "Please take 10 minutes to complete the interview — your voice matters:\n\n"
            "{interview_url}\n\n"
            "Best regards,\nThe Project Team"
        ),
    },
}


def _escalation_level(invited_at_str: str) -> str:
    """Return 'gentle', 'firm', or 'urgent' based on days since invite."""
    try:
        invited = datetime.fromisoformat(invited_at_str.replace("Z", "+00:00"))
        if invited.tzinfo is None:
            invited = invited.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - invited).days
    except Exception:
        days = 0
    if days <= 7:
        return "gentle"
    if days <= 14:
        return "firm"
    return "urgent"


# ── Service functions ──────────────────────────────────────────────────────────

async def list_campaigns(slug: str) -> list[dict] | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await fetch_campaigns(conn, project_id=project["id"])


async def create_campaign_svc(slug: str, data: dict) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        cid = await insert_campaign(conn, project_id=project["id"], **data)
        return await fetch_campaign(conn, campaign_id=cid, project_id=project["id"])


async def update_campaign_svc(slug: str, campaign_id: int, data: dict) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        ok = await update_campaign(conn, campaign_id=campaign_id, **data)
        if not ok:
            return None
        return await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])


async def delete_campaign_svc(slug: str, campaign_id: int) -> bool | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        camp = await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])
        if not camp:
            return False
        return await delete_campaign(conn, campaign_id=campaign_id)


async def export_targets_csv(slug: str, campaign_id: int) -> str | None:
    """Return CSV string of interview targets (non-completed stakeholders) for campaign.
    Returns None if project/campaign not found.
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        camp = await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])
        if not camp:
            return None
        stakeholders = await fetch_stakeholders_for_value_stream(
            conn,
            project_id=project["id"],
            value_stream_name=camp["value_stream_name"],
            exclude_completed=True,
        )

    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=["name", "email", "country_code", "value_stream", "campaign_id"]
    )
    writer.writeheader()
    for s in stakeholders:
        writer.writerow({
            "name": s["name"],
            "email": s["email"],
            "country_code": s.get("country_code") or "",
            "value_stream": camp["value_stream_name"],
            "campaign_id": str(camp["id"]),
        })
    return output.getvalue()


async def mark_invited_svc(slug: str, campaign_id: int) -> dict | None:
    """Set interview_invited_at = now() and interview_status = 'invited' for all
    non-completed stakeholders in the campaign's value stream.
    Returns {"marked": N} or None if not found.
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        camp = await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])
        if not camp:
            return None
        stakeholders = await fetch_stakeholders_for_value_stream(
            conn,
            project_id=project["id"],
            value_stream_name=camp["value_stream_name"],
            exclude_completed=True,
        )
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for s in stakeholders:
            if not s.get("interview_invited_at"):
                await update_stakeholder_interview_status(
                    conn,
                    stakeholder_id=s["id"],
                    status="invited",
                    invited_at=now,
                )
                count += 1
        return {"marked": count}


async def import_progress_svc(slug: str, campaign_id: int, content: str) -> dict | None:
    """Parse progress CSV (email, status) and update stakeholder interview_status.
    Returns {"updated": N, "skipped": M} or None if not found.
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        camp = await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])
        if not camp:
            return None

        reader = csv.DictReader(io.StringIO(content))
        rows = [{k.strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader]

        updated = 0
        skipped = 0
        now = datetime.now(timezone.utc).isoformat()

        for row in rows:
            email = row.get("email", "").strip()
            status_val = row.get("status", "").strip().lower()
            if not email:
                skipped += 1
                continue

            async with conn.execute(
                "SELECT id FROM stakeholders WHERE email=? AND project_id=?",
                (email, project["id"]),
            ) as cur:
                s = await cur.fetchone()

            if not s:
                skipped += 1
                continue

            if status_val == "completed":
                await update_stakeholder_interview_status(
                    conn,
                    stakeholder_id=s["id"],
                    status="completed",
                    completed_at=now,
                )
            else:
                await update_stakeholder_interview_status(
                    conn,
                    stakeholder_id=s["id"],
                    status="invited",
                )
            updated += 1

        return {"updated": updated, "skipped": skipped}


async def import_results_svc(slug: str, campaign_id: int, content: str) -> dict | None:
    """Parse results file (JSON array or CSV with email column) and store raw blobs.
    Returns {"imported": N, "unmatched": M} or None if not found.
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        camp = await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])
        if not camp:
            return None

        # Try JSON array first, fall back to CSV
        records: list[dict] = []
        try:
            parsed = _json.loads(content)
            if isinstance(parsed, list):
                records = parsed
            elif isinstance(parsed, dict):
                records = [parsed]
        except _json.JSONDecodeError:
            reader = csv.DictReader(io.StringIO(content))
            records = [{k.strip().lower(): v for k, v in r.items()} for r in reader]

        imported = 0
        unmatched = 0

        for record in records:
            email = str(record.get("email", "")).strip()
            if not email:
                unmatched += 1
                continue

            async with conn.execute(
                "SELECT id FROM stakeholders WHERE email=? AND project_id=?",
                (email, project["id"]),
            ) as cur:
                s = await cur.fetchone()

            if not s:
                unmatched += 1
                continue

            await insert_interview_response(
                conn,
                stakeholder_id=s["id"],
                campaign_id=campaign_id,
                raw_data=_json.dumps(record),
            )
            imported += 1

        return {"imported": imported, "unmatched": unmatched}


async def import_summary_svc(slug: str, campaign_id: int, content: str) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        ok = await update_campaign(
            conn, campaign_id=campaign_id, findings_summary=content
        )
        if not ok:
            return None
        return {"ok": True}


async def generate_reminders_svc(slug: str, campaign_id: int) -> dict | None:
    """Create reminder_email records for non-completed invited stakeholders.
    Returns {"created": N} or None if not found.
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        camp = await fetch_campaign(conn, campaign_id=campaign_id, project_id=project["id"])
        if not camp:
            return None

        stakeholders = await fetch_stakeholders_for_value_stream(
            conn,
            project_id=project["id"],
            value_stream_name=camp["value_stream_name"],
            exclude_completed=True,
        )

        public_url = get_settings().public_url.rstrip("/")
        count = 0
        for s in stakeholders:
            invited_at = s.get("interview_invited_at")
            if not invited_at:
                continue  # Skip un-invited stakeholders
            level = _escalation_level(invited_at)
            template = REMINDER_TEMPLATES[level]
            subject = template["subject"]
            session_token = await fetch_session_token_for_stakeholder(conn, s["id"])
            if session_token:
                interview_url = f"{public_url}/dashboard/interview/{session_token}"
            else:
                interview_url = f"{public_url}/dashboard/interview"
            body = template["body"].format(
                name=s["name"],
                campaign_name=camp["campaign_name"] or camp["value_stream_name"],
                interview_url=interview_url,
            )
            await insert_reminder_email(
                conn,
                project_id=project["id"],
                campaign_id=campaign_id,
                stakeholder_id=s["id"],
                subject=subject,
                body=body,
                escalation_level=level,
            )
            count += 1

        return {"created": count}


async def get_interview_summary(slug: str) -> dict | None:
    """Return aggregate completion counts across all campaigns with open windows."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        campaigns = await fetch_campaigns(conn, project_id=project["id"])
        today = datetime.now(timezone.utc).date().isoformat()

        total_stakeholders = 0
        total_completed = 0
        active_campaigns = []

        for camp in campaigns:
            start = camp.get("interview_start") or ""
            close = camp.get("interview_close") or ""
            window_open = bool(start and close and start <= today <= close)

            vs = camp["value_stream_name"]
            stakeholders = await fetch_stakeholders_for_value_stream(
                conn, project_id=project["id"], value_stream_name=vs
            )
            total = len(stakeholders)
            completed = sum(1 for s in stakeholders if s.get("interview_status") == "completed")

            active_campaigns.append({
                "id": camp["id"],
                "value_stream_name": vs,
                "total_stakeholders": total,
                "completed": completed,
                "window_open": window_open,
            })
            if window_open:
                total_stakeholders += total
                total_completed += completed

        return {
            "active_campaigns": active_campaigns,
            "total_stakeholders": total_stakeholders,
            "total_completed": total_completed,
        }


async def list_reminder_emails_svc(slug: str) -> list[dict] | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await fetch_reminder_emails(conn, project_id=project["id"])


async def update_reminder_email_svc(
    slug: str,
    email_id: int,
    status: str,
    subject: str | None = None,
    body: str | None = None,
) -> bool | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await update_reminder_email(
            conn,
            email_id=email_id,
            project_id=project["id"],
            status=status,
            subject=subject,
            body=body,
        )


async def send_reminder_emails_svc(slug: str) -> dict | None:
    """Send all approved reminder emails via Resend and update their status.

    Returns {"sent": N, "failed": M, "skipped": K} or None if project not found.
    Skips dispatch if RESEND_API_KEY is not configured (returns skipped count).
    """
    if not get_db_path(slug).exists():
        return None

    settings = get_settings()
    api_key = settings.resend_api_key
    from_email = settings.from_email

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None

        emails = await fetch_approved_reminder_emails(conn, project_id=project["id"])

        if not api_key:
            return {"sent": 0, "failed": 0, "skipped": len(emails), "error": "RESEND_API_KEY not configured"}

        sent = failed = 0
        async with httpx.AsyncClient(timeout=15.0) as client:
            for email in emails:
                payload = {
                    "from": from_email,
                    "to": [email["stakeholder_email"]],
                    "subject": email["subject"],
                    "text": email["body"],
                }
                try:
                    resp = await client.post(
                        "https://api.resend.com/emails",
                        json=payload,
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    if resp.status_code in (200, 201):
                        await mark_reminder_email_sent(conn, email_id=email["id"], status="sent")
                        sent += 1
                    else:
                        await mark_reminder_email_sent(conn, email_id=email["id"], status="failed")
                        failed += 1
                except Exception:
                    await mark_reminder_email_sent(conn, email_id=email["id"], status="failed")
                    failed += 1

        return {"sent": sent, "failed": failed, "skipped": 0}
