# tests/test_platform_public_url_readers.py
"""Every reader of the platform's public_url, powered separately.

Task 3 moved five link builders off `get_settings().public_url` and onto
`platform_public_url()` - the sysadmin-set setting, falling back to `PUBLIC_URL`. A
shared accessor makes it very easy for one reader's test to cover another's (CLAUDE.md
records this masking twice already), so each reader below is driven through a different
production entry point, and each assertion looks for a link string that appears nowhere
else in this file.

**Assert the URL that reaches the transport, not the accessor's return value.** Every
test stores a distinctive URL through the real settings service, drives the reader's
actual production caller, and reads the link back out of the HTTP request that would
have gone to Resend - through an `httpx.MockTransport`, the same technique
tests/test_outbound_mail_seam.py uses and for the reason its docstring gives: a helper
returning the right string proves nothing about what a participant receives.

**DATABASE_DIR is isolated to this file's own tmp_path**, autoused below - the same
isolation tests/test_platform_settings.py's fixture applies. `system.db` is shared and
persists between test runs (CLAUDE.md's own warning about `/tmp/agentpool_test`), so a
test that stored a real value into it would poison every later test in the session and
every run after this one.
"""
import json
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from api.config import get_settings
from api.services import platform_settings as ps

STORED_URL = "https://reader-test.example"


@pytest.fixture(autouse=True)
def _isolated_platform_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    ps.forget_platform_settings()
    yield
    ps.forget_platform_settings()
    get_settings.cache_clear()


@pytest.fixture
def sent(monkeypatch):
    """Capture the real outbound requests, the way test_outbound_mail_seam.py does."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": "mock-message-id"})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return httpx.AsyncClient(*args, **kwargs)

    from api.services import outbound_mail
    monkeypatch.setattr(outbound_mail, "httpx", SimpleNamespace(AsyncClient=factory))
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_reader_test")
    return captured


def body_text(request: httpx.Request) -> str:
    return json.loads(request.content)["text"]


@pytest_asyncio.fixture
async def sysadmin():
    from api.auth import create_access_token
    from api.main import app
    token = create_access_token("someone", "sysadmin", "test-secret")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        yield ac


async def _store_url(sysadmin, url: str = STORED_URL) -> None:
    resp = await sysadmin.patch("/admin/platform-settings", json={"public_url": url})
    assert resp.status_code == 200, resp.text


async def _make_project(sysadmin, slug: str) -> None:
    resp = await sysadmin.post("/projects", json={
        "client_slug": slug, "llm_mode": "standard", "sector": "rail",
    })
    assert resp.status_code in (200, 201), resp.text
    await _set_dev_mode(slug, False)


async def _set_dev_mode(slug: str, value: bool) -> None:
    from api.database import fetch_project, get_connection
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        config = json.loads(project.get("config_json") or "{}")
        config["dev_mode"] = value
        await conn.execute(
            "UPDATE projects SET config_json=? WHERE slug=?", (json.dumps(config), slug)
        )
        await conn.commit()


async def _approve_reminders(slug: str) -> None:
    """generate_reminders_svc leaves rows at their default status - send_reminder_emails_svc
    only sends 'approved' ones, the same gate tests/test_outbound_mail_seam.py's
    _approved_reminder helper crosses by hand."""
    from api.database import fetch_project, get_connection
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        await conn.execute(
            "UPDATE reminder_emails SET status='approved' WHERE project_id=?",
            (project["id"],),
        )
        await conn.commit()


async def _add_stakeholder(
    slug: str, name: str, email: str, *, value_streams: list | None = None, **flags
) -> int:
    from api.database import fetch_project, get_connection, insert_stakeholder
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        return await insert_stakeholder(
            conn, project_id=project["id"], name=name, email=email,
            project_role="governing", value_streams=value_streams,
            is_reviewer=flags.get("reviewer", False),
            is_approver=flags.get("approver", False),
            is_governor=flags.get("governor", False),
        )


# ── Reader 1: interview_service.interview_url() ──────────────────────────────
#
# Reached, in production, via campaign_service's generate_reminders_svc when a
# stakeholder already has a session token - distinct from Reader 2 below, which is the
# literal fallback f-string campaign_service.py builds for itself when there is no
# session yet. The two live one branch apart in the same function, so proving each
# needs a test that could not pass on the other: this one's link carries a session
# token suffix, and reader 2's deliberately does not.

@pytest.mark.asyncio
async def test_interview_url_reaches_a_reminder_with_a_session(sysadmin, sent):
    from api.database import (
        fetch_project, get_connection, insert_campaign, insert_interview_session,
    )

    slug = "reader-interview-url"
    await _store_url(sysadmin)
    await _make_project(sysadmin, slug)
    stakeholder_id = await _add_stakeholder(
        slug, "Interviewee", "interviewee@example.test", value_streams=["Ops"]
    )

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        campaign_id = await insert_campaign(
            conn, project_id=project["id"], value_stream_name="Ops",
            campaign_name="Reader campaign",
        )
        await insert_interview_session(
            conn, project_id=project["id"], orchestration_run_id=None,
            stakeholder_id=stakeholder_id, node_label="Goods-in Inspection",
            session_token="reader-token-1",
        )
        await conn.execute(
            "UPDATE stakeholders SET interview_invited_at=CURRENT_TIMESTAMP WHERE id=?",
            (stakeholder_id,),
        )
        await conn.commit()

    from api.services.campaign_service import (
        generate_reminders_svc, send_reminder_emails_svc,
    )
    generated = await generate_reminders_svc(slug, campaign_id)
    assert generated == {"created": 1}, generated
    await _approve_reminders(slug)

    result = await send_reminder_emails_svc(slug)
    assert result == {"sent": 1, "failed": 0, "skipped": 0}, result

    assert len(sent) == 1
    assert f"{STORED_URL}/dashboard/interview/reader-token-1" in body_text(sent[0])


# ── Reader 2: campaign_service.py's own no-session-yet fallback ──────────────

@pytest.mark.asyncio
async def test_campaign_service_no_session_fallback_reaches_a_reminder(sysadmin, sent):
    from api.database import fetch_project, get_connection, insert_campaign

    slug = "reader-campaign-fallback"
    await _store_url(sysadmin)
    await _make_project(sysadmin, slug)
    await _add_stakeholder(
        slug, "Not Yet Sessioned", "notyet@example.test", value_streams=["Ops"]
    )

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        campaign_id = await insert_campaign(
            conn, project_id=project["id"], value_stream_name="Ops",
            campaign_name="Reader campaign",
        )
        await conn.execute(
            "UPDATE stakeholders SET interview_invited_at=CURRENT_TIMESTAMP "
            "WHERE project_id=?", (project["id"],),
        )
        await conn.commit()

    from api.services.campaign_service import (
        generate_reminders_svc, send_reminder_emails_svc,
    )
    generated = await generate_reminders_svc(slug, campaign_id)
    assert generated == {"created": 1}, generated
    await _approve_reminders(slug)

    result = await send_reminder_emails_svc(slug)
    assert result == {"sent": 1, "failed": 0, "skipped": 0}, result

    assert len(sent) == 1
    text = body_text(sent[0])
    assert f"{STORED_URL}/dashboard/interview" in text
    # Distinguishing from reader 1: no session token suffix on this link.
    assert f"{STORED_URL}/dashboard/interview/" not in text


# ── Reader 3: pam_report_job._compose_body ────────────────────────────────────

@pytest.mark.asyncio
async def test_pam_report_link_reaches_governance_mail(sysadmin, sent):
    slug = "reader-pam-report"
    await _store_url(sysadmin)
    await _make_project(sysadmin, slug)
    await _add_stakeholder(slug, "Gov", "governor@example.test", governor=True)

    from api.database import get_connection, set_project_status
    async with get_connection(slug) as conn:
        await set_project_status(conn, slug=slug, status="active")

    from api.services.pam_report_job import run_pam_daily_report
    await run_pam_daily_report(slug)

    assert len(sent) == 1
    assert f"{STORED_URL}/dashboard/{slug}/pam-report" in body_text(sent[0])


# ── Reader 4: commit_notify_service._notify ───────────────────────────────────

@pytest.mark.asyncio
async def test_crew_notice_link_reaches_reviewer_mail(sysadmin, sent):
    slug = "reader-commit-notify"
    await _store_url(sysadmin)
    await _make_project(sysadmin, slug)
    await _add_stakeholder(slug, "Rev", "reviewer@example.test", reviewer=True)

    from api.services.commit_notify_service import notify_crew_awaiting_commit
    await notify_crew_awaiting_commit(slug, "discovery_mapping")

    assert len(sent) == 1
    assert f"{STORED_URL}/dashboard/{slug}?crew=discovery_mapping&tab=output" in body_text(sent[0])


# ── Reader 5: admin_service._send_welcome_email ───────────────────────────────

@pytest.mark.asyncio
async def test_welcome_email_login_link_reaches_the_new_login(sysadmin, sent):
    await _store_url(sysadmin)

    from api.services.admin_service import _send_welcome_email
    await _send_welcome_email("newcomer@example.test", "newcomer", "temp-password")

    assert len(sent) == 1
    assert f"{STORED_URL}/dashboard/login" in body_text(sent[0])


# ── The bug this task fixes: no reader had a .rstrip('/') at all ─────────────

@pytest.mark.asyncio
async def test_a_trailing_slash_from_the_environment_does_not_double_up(
    sent, monkeypatch,
):
    """admin_service.py:76 was the one reader with no `.rstrip('/')` of its own, so a
    trailing-slash PUBLIC_URL reached the welcome email as a literal double slash before
    `/dashboard/login`. Nothing is stored here - PUBLIC_URL is exercised directly, which
    is the source `_resolve` used to leave unnormalised.

    RESEND_API_KEY is set via the environment rather than by patching the `sent`
    fixture's already-built settings object, because the cache_clear() below (needed for
    the new PUBLIC_URL to take effect) would otherwise throw that object - and its
    patched attribute - away and read a fresh one straight from the environment.
    """
    monkeypatch.setenv("PUBLIC_URL", "https://env-with-slash.example/")
    monkeypatch.setenv("RESEND_API_KEY", "re_reader_test")
    get_settings.cache_clear()
    ps.forget_platform_settings()

    from api.services.admin_service import _send_welcome_email
    await _send_welcome_email("newcomer@example.test", "newcomer", "temp-password")

    assert len(sent) == 1
    text = body_text(sent[0])
    assert "https://env-with-slash.example/dashboard/login" in text
    assert "https://env-with-slash.example//dashboard/login" not in text
