"""The job: compute, store for audit, diff against yesterday, notify."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.services.pam_report_job import JOB_NAME, resolve_recipients

SLUG = "pam-job-test"


def _sh(name, email, *, reviewer=False, approver=False):
    return {"name": name, "email": email,
            "is_reviewer": int(reviewer), "is_approver": int(approver)}


def test_recipients_are_reviewers_and_approvers_only():
    people = [
        _sh("Rev", "rev@example.test", reviewer=True),
        _sh("App", "app@example.test", approver=True),
        _sh("Both", "both@example.test", reviewer=True, approver=True),
        _sh("Neither", "none@example.test"),
    ]
    actual, intended = resolve_recipients(people, dev_mode=False)
    assert sorted(actual) == ["app@example.test", "both@example.test", "rev@example.test"]
    assert sorted(intended) == sorted(actual)


def test_someone_flagged_both_appears_once():
    """The flags are independent, so a person holding both must not be emailed twice."""
    people = [_sh("Both", "both@example.test", reviewer=True, approver=True)]
    actual, _ = resolve_recipients(people, dev_mode=False)
    assert actual == ["both@example.test"]


def test_dev_mode_redirects_but_still_reports_the_intended_list():
    people = [_sh("Rev", "rev@example.test", reviewer=True)]
    actual, intended = resolve_recipients(people, dev_mode=True)
    assert actual == ["Patrick@FutureEdge.consulting"]
    assert intended == ["rev@example.test"]


def test_stakeholders_without_an_email_are_skipped():
    people = [_sh("NoMail", "", reviewer=True), _sh("Rev", "rev@example.test", reviewer=True)]
    actual, _ = resolve_recipients(people, dev_mode=False)
    assert actual == ["rev@example.test"]


def test_dev_mode_sends_nowhere_when_there_are_no_eligible_stakeholders():
    """Redirecting an empty list must not invent a recipient."""
    actual, intended = resolve_recipients([_sh("Nobody", "a@example.test")], dev_mode=True)
    assert actual == []
    assert intended == []


@pytest.mark.asyncio
async def test_job_stores_the_report_as_a_current_versioned_output(client):
    await client.post("/projects", json={
        "client_slug": SLUG, "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_job import run_pam_daily_report

    with patch("api.services.pam_report_job._send_email", new_callable=AsyncMock):
        await run_pam_daily_report(SLUG)

    resp = await client.get(f"/projects/{SLUG}/outputs")
    reports = [o for o in resp.json()
               if o["agent_name"] == "PAM" and o["output_type"] == "pam_report"]
    assert len(reports) == 1
    assert reports[0]["is_current"] is True


@pytest.mark.asyncio
async def test_second_run_supersedes_the_first(client):
    """insert_agent_output does not manage is_current - the job must."""
    await client.post("/projects", json={
        "client_slug": "pam-job-super", "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_job import run_pam_daily_report

    with patch("api.services.pam_report_job._send_email", new_callable=AsyncMock):
        await run_pam_daily_report("pam-job-super")
        await run_pam_daily_report("pam-job-super")

    resp = await client.get("/projects/pam-job-super/outputs")
    reports = [o for o in resp.json()
               if o["agent_name"] == "PAM" and o["output_type"] == "pam_report"]
    current = [r for r in reports if r["is_current"]]
    assert len(reports) == 2
    assert len(current) == 1
    assert current[0]["version"] == 2


@pytest.mark.asyncio
async def test_first_run_reports_no_changes(client):
    await client.post("/projects", json={
        "client_slug": "pam-job-first", "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_job import run_pam_daily_report

    with patch("api.services.pam_report_job._send_email", new_callable=AsyncMock):
        await run_pam_daily_report("pam-job-first")

    from api.config import get_settings
    outputs = Path(get_settings().projects_dir) / "pam-job-first" / "outputs"
    written = sorted(outputs.glob("pam_report*.json"))
    stored = json.loads(written[-1].read_text())
    assert stored["change_summary"]["is_first_report"] is True


@pytest.mark.asyncio
async def test_email_failure_does_not_lose_the_report(client):
    """The audit trail matters more than the notification."""
    await client.post("/projects", json={
        "client_slug": "pam-job-mail", "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_job import run_pam_daily_report

    with patch("api.services.pam_report_job._send_email",
               new_callable=AsyncMock, side_effect=RuntimeError("resend down")):
        await run_pam_daily_report("pam-job-mail")

    resp = await client.get("/projects/pam-job-mail/outputs")
    assert any(o["output_type"] == "pam_report" for o in resp.json())


@pytest.mark.asyncio
async def test_job_is_registered_with_the_scheduler():
    from api.services import pam_report_job  # noqa: F401 - import registers it
    from api.services.scheduler_service import JOB_REGISTRY
    assert JOB_NAME in JOB_REGISTRY


def test_email_links_to_the_pam_report_page_not_the_client_report():
    """/report renders Report.tsx, the client engagement report - a different
    document with none of the risks, issues, or change summary the email
    describes. Pamela's status report is PamReportView, routed at
    /:slug/pam-report."""
    from api.services.pam_report_job import _compose_body

    report = {"overall_health": "green", "health_summary": "On track"}
    change = {"summary": "No change since the previous report.",
              "new_risks": [], "new_issues": []}
    body = _compose_body(SLUG, report, change, intended=[], dev_mode=False)

    assert f"/dashboard/{SLUG}/pam-report" in body
    assert f"/dashboard/{SLUG}/report" not in body
