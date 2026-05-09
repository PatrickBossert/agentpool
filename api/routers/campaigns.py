# api/routers/campaigns.py
"""Campaign management, interview import/export, and reminder email endpoints."""
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from api.services.campaign_service import (
    list_campaigns,
    create_campaign_svc,
    update_campaign_svc,
    delete_campaign_svc,
    export_targets_csv,
    mark_invited_svc,
    import_progress_svc,
    import_results_svc,
    import_summary_svc,
    generate_reminders_svc,
    get_interview_summary,
    list_reminder_emails_svc,
    update_reminder_email_svc,
)

router = APIRouter(prefix="/projects", tags=["campaigns"])


def _404(detail: str = "Not found"):
    raise HTTPException(status_code=404, detail=detail)


class CampaignIn(BaseModel):
    value_stream_name: str = ""
    listenlabs_campaign_id: str = ""
    campaign_name: str = ""
    interview_start: str | None = None
    interview_close: str | None = None


class CampaignPatch(BaseModel):
    value_stream_name: str | None = None
    listenlabs_campaign_id: str | None = None
    campaign_name: str | None = None
    interview_start: str | None = None
    interview_close: str | None = None
    findings_summary: str | None = None


class ReminderEmailPatch(BaseModel):
    status: str  # 'approved' | 'dismissed'
    subject: str | None = None
    body: str | None = None


# ── Campaign CRUD ──────────────────────────────────────────────────────────────

@router.get("/{slug}/campaigns")
async def list_campaigns_endpoint(slug: str):
    result = await list_campaigns(slug)
    if result is None:
        _404(f"Project '{slug}' not found")
    return result


@router.post("/{slug}/campaigns", status_code=201)
async def create_campaign_endpoint(slug: str, body: CampaignIn):
    result = await create_campaign_svc(slug, body.model_dump(exclude_none=True))
    if result is None:
        _404(f"Project '{slug}' not found")
    return result


@router.patch("/{slug}/campaigns/{campaign_id}")
async def update_campaign_endpoint(slug: str, campaign_id: int, body: CampaignPatch):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    result = await update_campaign_svc(slug, campaign_id, data)
    if result is None:
        _404("Campaign not found")
    return result


@router.delete("/{slug}/campaigns/{campaign_id}", status_code=204)
async def delete_campaign_endpoint(slug: str, campaign_id: int):
    result = await delete_campaign_svc(slug, campaign_id)
    if result is None:
        _404(f"Project '{slug}' not found")
    if result is False:
        _404("Campaign not found")


# ── Import / Export ─────────────────────────────────────────────────────────────

@router.get("/{slug}/campaigns/{campaign_id}/export-targets")
async def export_targets_endpoint(slug: str, campaign_id: int):
    csv_content = await export_targets_csv(slug, campaign_id)
    if csv_content is None:
        _404("Project or campaign not found")
    filename = f"interview-targets-campaign-{campaign_id}.csv"

    def iter_csv():
        yield csv_content

    return StreamingResponse(
        iter_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{slug}/campaigns/{campaign_id}/mark-invited")
async def mark_invited_endpoint(slug: str, campaign_id: int):
    result = await mark_invited_svc(slug, campaign_id)
    if result is None:
        _404("Project or campaign not found")
    return result


@router.post("/{slug}/campaigns/{campaign_id}/import-progress")
async def import_progress_endpoint(slug: str, campaign_id: int, file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="replace")
    result = await import_progress_svc(slug, campaign_id, content)
    if result is None:
        _404("Project or campaign not found")
    return result


@router.post("/{slug}/campaigns/{campaign_id}/import-results")
async def import_results_endpoint(slug: str, campaign_id: int, file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="replace")
    result = await import_results_svc(slug, campaign_id, content)
    if result is None:
        _404("Project or campaign not found")
    return result


@router.post("/{slug}/campaigns/{campaign_id}/import-summary")
async def import_summary_endpoint(slug: str, campaign_id: int, file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="replace")
    result = await import_summary_svc(slug, campaign_id, content)
    if result is None:
        _404("Project or campaign not found")
    return result


# ── Reminder generation ─────────────────────────────────────────────────────────

@router.post("/{slug}/campaigns/{campaign_id}/generate-reminders")
async def generate_reminders_endpoint(slug: str, campaign_id: int):
    result = await generate_reminders_svc(slug, campaign_id)
    if result is None:
        _404("Project or campaign not found")
    return result


# ── Interview summary (for dashboard badge) ─────────────────────────────────────

@router.get("/{slug}/interview-summary")
async def interview_summary_endpoint(slug: str):
    result = await get_interview_summary(slug)
    if result is None:
        _404(f"Project '{slug}' not found")
    return result


# ── Reminder emails ─────────────────────────────────────────────────────────────

@router.get("/{slug}/reminder-emails")
async def list_reminder_emails_endpoint(slug: str):
    result = await list_reminder_emails_svc(slug)
    if result is None:
        _404(f"Project '{slug}' not found")
    return result


@router.patch("/{slug}/reminder-emails/{email_id}")
async def update_reminder_email_endpoint(slug: str, email_id: int, body: ReminderEmailPatch):
    result = await update_reminder_email_svc(
        slug, email_id, body.status, subject=body.subject, body=body.body
    )
    if result is None:
        _404(f"Project '{slug}' not found")
    if result is False:
        _404("Reminder email not found")
    return {"ok": True}
