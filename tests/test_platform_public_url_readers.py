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

**The five tests are worth nothing as a guarantee about the seam**, which is what the
source walk at the foot of this file is for: every one of them keeps passing while a sixth
builder reads `get_settings().public_url` straight.
"""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from api.config import get_settings
from api.services import platform_settings as ps

STORED_URL = "https://reader-test.example"
_REPO_ROOT = Path(__file__).parent.parent


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


# ── The sixth reader, which the five tests above cannot see ──────────────────

# The accessor owns the only two legitimate reads (`_resolve`'s environment argument, once
# for the accessor and once for the door's report). Exempt as a file rather than as two
# line numbers, which would rot on the next edit to it.
_ACCESSOR = "api/services/platform_settings.py"

# The settings door, where `req.public_url` is the PATCH body's own field and not the
# settings singleton at all. Narrowed rather than exempted - see the test's docstring.
_DOOR = "api/routers/platform_settings.py"


def _request_body_params(tree: ast.Module) -> set[str]:
    """Parameter names in this module annotated with one of its own Pydantic models.

    Derived rather than listed, so the exemption survives a rename of `req` or of
    `PlatformSettingsPatch` and still refuses to widen: an *unannotated* base, or one
    annotated with anything else, is not a request body and is not excused. A first draft
    asked instead whether the base "looked like settings" by rendering it and matching
    substrings, and `cfg = get_settings()` walked straight through it - the exemption has to
    name what is allowed, not guess at what is not.
    """
    models = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(ast.unparse(base) == "BaseModel" for base in node.bases)
    }
    params: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args
        for arg in args.posonlyargs + args.args + args.kwonlyargs:
            if arg.annotation is not None and ast.unparse(arg.annotation) in models:
                params.add(arg.arg)
    return params


def test_nothing_reads_public_url_off_settings_outside_the_accessor():
    """A sixth link builder must not be able to reach `get_settings().public_url` directly.

    The five readers above are pinned one by one, and every one of them would go on passing
    while a new sixth read the environment variable straight past the whole feature. Worse
    than a missed opportunity, because a direct reader now collects two defects rather than
    one: Task 3 *deleted* the four original readers' own `.rstrip('/')` calls, on the correct
    reasoning that the accessor owns normalisation, so a fresh `get_settings().public_url`
    both ignores the stored setting and re-opens the trailing-slash bug that put
    `https://host//dashboard/login` in the welcome email - the bug the last test above pins.

    Same technique as `tests/test_process_cache.py`'s two source walks and
    `test_only_the_seam_posts_to_resend`, and for the same reason: a docstring saying "use
    the accessor" is prose, not a mechanism.

    **What the walk sees:** an attribute named `public_url` on any base, anywhere under
    `api/`, `agents/` and `scripts/` - so `get_settings().public_url`, `settings.public_url`
    and `s = get_settings(); s.public_url` are all caught wherever a link is built.

    **What it cannot see**, and this matters more than the list of what it can. A read
    spelled some other way - `getattr(get_settings(), "public_url")`, or a lookup into
    `get_settings().model_dump()` - is invisible to it, as is a host hard-coded into an
    f-string or assembled from parts, and as is anything added inside the two modules
    exempted below. It is the same class of limit `outbound_mail.py`'s `api.resend.com`
    guard carries and documents: it catches the copy-paste, which is how all five original
    readers came to exist, and not a determined rewrite.

    The door is narrowed rather than exempted. Skipping the file wholesale would leave the
    one router whose subject *is* this setting as the single place a direct read could be
    added unseen, so exactly one base is excused there - a parameter annotated with one of
    the module's own Pydantic models, which `req.public_url` is and
    `get_settings().public_url` is not.
    """
    offenders: list[str] = []
    for pattern in ("api/**/*.py", "agents/**/*.py", "scripts/**/*.py"):
        for path in sorted(_REPO_ROOT.glob(pattern)):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if rel == _ACCESSOR:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            bodies = _request_body_params(tree) if rel == _DOOR else set()
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Attribute) and node.attr == "public_url"):
                    continue
                if isinstance(node.value, ast.Name) and node.value.id in bodies:
                    continue
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"public_url is read off settings outside the accessor at {offenders}. Call "
        "api.services.platform_settings.platform_public_url() instead: reading the setting "
        "directly ignores whatever a sysadmin stored through /admin/platform-settings, and "
        "the accessor is also the only place the trailing slash is stripped, so a direct "
        "read puts a double slash back into every link this deployment sends."
    )
