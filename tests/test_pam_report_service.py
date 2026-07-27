# tests/test_pam_report_service.py
"""The report derivation must be callable outside a request.

It lived inside the route handler, so the scheduled job could not reach it.
This asserts the service exists and returns the same shape the endpoint returns.
"""
import pytest


@pytest.mark.asyncio
async def test_build_pam_report_returns_the_report_shape(client):
    await client.post("/projects", json={
        "client_slug": "pam-svc-test", "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_service import build_pam_report

    report = await build_pam_report("pam-svc-test")

    for key in ["generated_at", "project_slug", "overall_health", "health_summary",
                "milestones", "crews", "risks", "issues", "interview_tracker"]:
        assert key in report, f"missing {key}"
    assert report["project_slug"] == "pam-svc-test"


@pytest.mark.asyncio
async def test_endpoint_and_service_agree(client):
    """The endpoint must delegate, not duplicate - otherwise they can drift."""
    await client.post("/projects", json={
        "client_slug": "pam-svc-agree", "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_service import build_pam_report

    via_service = await build_pam_report("pam-svc-agree")
    resp = await client.get("/projects/pam-svc-agree/pam-report")
    via_endpoint = resp.json()

    assert resp.status_code == 200
    # generated_at is a timestamp and will differ between the two calls
    via_service.pop("generated_at", None)
    via_endpoint.pop("generated_at", None)
    assert via_service == via_endpoint
