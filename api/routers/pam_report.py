# api/routers/pam_report.py
"""
PAM status report endpoint.

Derives a structured project health report from live DB state — no LLM call.
All risk and issue judgements are computed from milestones, crew runs, reviews,
interview sessions, and uploaded documents.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from api.auth import require_any_auth
from api.services.pam_report_service import build_pam_report

router = APIRouter(prefix="/projects/{slug}/pam-report", tags=["pam-report"])


@router.get("")
async def get_pam_report(slug: str, payload: dict = Depends(require_any_auth)):
    return await build_pam_report(slug)
