# api/routers/pam_report.py
"""
PAM status report endpoint.

Exposes Pamela's project health report over HTTP. The derivation itself lives in
api.services.pam_report_service, so the scheduled daily job and this endpoint
build the same report from the same code.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from api.auth import require_any_auth
from api.services.pam_report_service import build_pam_report

router = APIRouter(prefix="/projects/{slug}/pam-report", tags=["pam-report"])


@router.get("")
async def get_pam_report(slug: str, payload: dict = Depends(require_any_auth)):
    return await build_pam_report(slug)
