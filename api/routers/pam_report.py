# api/routers/pam_report.py
"""
PAM status report endpoint.

Exposes Pamela's project health report over HTTP. The derivation itself lives in
api.services.pam_report_service, so the scheduled daily job and this endpoint
build the same report from the same code.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from api.auth import check_project_access, require_any_auth
from api.services.pam_report_service import build_pam_report

router = APIRouter(prefix="/projects/{slug}/pam-report", tags=["pam-report"])


@router.get("")
async def get_pam_report(slug: str, payload: dict = Depends(require_any_auth)):
    """This project's health report - run status, milestone variance, output summaries.

    A read, so membership is the whole gate; there is no content axis here. It is the
    membership floor that was missing, and its absence made this a cross-project leak
    rather than a loose one: `require_any_auth` asks whether the caller has a login, never
    which engagement the login belongs to, so any valid token read any slug's report.

    This router aliased nothing, which is exactly why it survived the sweep that found
    `milestones.py` and `nonworking.py` - the hole had two disguises and an enumeration by
    name found only one of them. Go by behaviour: every handler under a `/projects/{slug}`
    prefix calls this.
    """
    await check_project_access(slug, payload)
    return await build_pam_report(slug)
