# tests/test_reminder_email_copy.py
"""The reminder templates read as British English and sign off as a named correspondent.

Two defects, both in `REMINDER_TEMPLATES` (`api/services/campaign_service.py`): an em dash
where the style guide requires a spaced en dash, and a sign-off reading "Best regards, The
Project Team" when the envelope now names a real person - `"Jordan Williams"
<stakeholder-manager@taskreimagination.ai>`, per sp54/sp55.

Every assertion here reads the request `_post_to_resend` actually builds, through an
`httpx.MockTransport`, the same way `tests/test_participant_facing_name.py` does - a
template-constant assertion would pass even if the send path re-rendered the body from
something else, or if a future edit reintroduced an em dash between the template and the
wire.

The sign-off is resolved through `agents.identity.AGENT_IDENTITY`, not hard-coded, so a
rename of the stakeholder manager changes every reminder generated afterwards without a code
change. `test_the_signoff_follows_a_rename_in_agent_identity` is the test a hard-coded
"Jordan Williams" would fail: it mutates `AGENT_IDENTITY` before generating, and the sent
body must carry the new name.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from agents.identity import AGENT_IDENTITY, Identity
from api.config import get_settings
from api.services import outbound_mail

SLUG = "rec-gs-am"
_SLUGS = (SLUG,)

REMINDER_SUBJECT_FRAGMENT = "reminder"
PARTICIPANT = "participant@example.test"


@pytest.fixture(autouse=True)
def clean():
    """Remove this file's databases and project directories either side of each test."""
    settings = get_settings()

    def _wipe():
        import shutil
        for slug in _SLUGS:
            (Path(settings.database_dir) / f"{slug}.db").unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                (Path(settings.database_dir) / f"{slug}.db{suffix}").unlink(missing_ok=True)
            proj = Path(settings.projects_dir) / slug
            if proj.exists():
                shutil.rmtree(proj)

    _wipe()
    yield
    _wipe()


@pytest.fixture
def sent(monkeypatch):
    """Capture the real outbound requests, and return the list they land in."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": "mock-message-id"})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return httpx.AsyncClient(*args, **kwargs)

    monkeypatch.setattr(outbound_mail, "httpx", SimpleNamespace(AsyncClient=factory))
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_rec_test")
    return captured


def payload(request: httpx.Request) -> dict:
    assert str(request.url) == "https://api.resend.com/emails", str(request.url)
    return json.loads(request.content)


def text(request: httpx.Request) -> str:
    return payload(request)["text"]


def subject(request: httpx.Request) -> str:
    return payload(request)["subject"]


# ── Fixture data ─────────────────────────────────────────────────────────────

async def _make_project(client, slug: str) -> None:
    await client.post("/projects", json={
        "client_slug": slug, "llm_mode": "standard", "sector": "rail",
    })
    await _set_config(slug, dev_mode=False)


async def _set_config(slug: str, **keys) -> None:
    from api.database import fetch_project, get_connection
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        config = json.loads(project.get("config_json") or "{}")
        config.update(keys)
        await conn.execute(
            "UPDATE projects SET config_json=? WHERE slug=?", (json.dumps(config), slug)
        )
        await conn.commit()


async def _generate_and_approve_reminder(client, slug: str, days_ago: int, name: str = "Alice") -> None:
    """Drive a reminder through the real generation path (not a hand-inserted row), so the
    template - including today's `AGENT_IDENTITY` read - is what actually produces the stored
    body.

    `generate_reminders_svc` has no dedup: it re-creates a reminder for every non-completed
    invited stakeholder in the value stream on every call, so calling this more than once in
    a test (one per escalation level) re-mints reminders for stakeholders added on earlier
    calls too. The row for *this* call is picked out by `name`, which is unique per call,
    rather than assumed to be the only row created.
    """
    from datetime import datetime, timedelta, timezone

    from api.database import fetch_project, get_connection, insert_stakeholder

    await client.post(
        f"/projects/{slug}/campaigns",
        json={"value_stream_name": "Digital Transformation", "campaign_name": "DT Survey"},
    )
    campaigns = (await client.get(f"/projects/{slug}/campaigns")).json()
    cid = campaigns[-1]["id"]

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        sid = await insert_stakeholder(
            conn, project_id=project["id"], name=name, email=PARTICIPANT,
            country_code="GB", value_streams=["Digital Transformation"],
        )
        invited_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        await conn.execute(
            "UPDATE stakeholders SET interview_invited_at=?, interview_status='invited' "
            "WHERE id=?",
            (invited_at, sid),
        )
        await conn.commit()

    await client.post(f"/projects/{slug}/campaigns/{cid}/generate-reminders")

    emails = (await client.get(f"/projects/{slug}/reminder-emails")).json()
    mine = [e for e in emails if name in e["body"] and e["status"] == "pending"]
    assert len(mine) == 1, emails
    await client.patch(
        f"/projects/{slug}/reminder-emails/{mine[0]['id']}", json={"status": "approved"}
    )


async def _send_reminders(slug: str) -> None:
    from api.services.campaign_service import send_reminder_emails_svc
    await send_reminder_emails_svc(slug)


TRANSCRIPT_SUBJECT = "Your interview transcript"
INTERVIEWEE = "interviewee@example.test"


async def _completed_session(slug: str, token: str) -> None:
    from api.database import fetch_project, get_connection, insert_interview_session, insert_stakeholder
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        stakeholder_id = await insert_stakeholder(
            conn, project_id=project["id"], name="Interviewee", email=INTERVIEWEE,
            country_code="GB", value_streams=["Digital Transformation"],
        )
        await insert_interview_session(
            conn, project_id=project["id"], orchestration_run_id=None,
            stakeholder_id=stakeholder_id, node_label="Goods-in Inspection",
            session_token=token,
        )
        await conn.execute(
            "UPDATE interview_sessions SET status='completed' WHERE session_token=?",
            (token,),
        )
        await conn.commit()


async def _send_transcript(client, token: str) -> None:
    r = await client.post(
        f"/api/interviews/{token}/email-transcript",
        json={"email": INTERVIEWEE, "qa_pairs": [{"question": "Q1", "answer": "A1"}]},
    )
    assert r.status_code == 200, r.text


# ── No em dash reaches a participant, over every participant-facing path ─────

@pytest.mark.asyncio
async def test_no_em_dash_reaches_a_participant(client, sent):
    """One test over all participant-facing sends, stronger than checking three templates:
    it would also catch an em dash reintroduced downstream of the template, not just one
    typed back into `REMINDER_TEMPLATES`."""
    await _make_project(client, SLUG)

    # All three escalation levels, so all three templates are exercised on the wire.
    for days_ago, level in ((3, "gentle"), (10, "firm"), (20, "urgent")):
        await _generate_and_approve_reminder(client, SLUG, days_ago, name=f"Stakeholder-{level}")
        await _send_reminders(SLUG)

    await _completed_session(SLUG, "rec-transcript")
    await _send_transcript(client, "rec-transcript")

    assert len(sent) == 4
    for request in sent:
        assert "—" not in subject(request), subject(request)
        assert "—" not in text(request), text(request)


# ── The sign-off names the correspondent, not a committee ────────────────────

@pytest.mark.asyncio
async def test_a_reminder_signs_off_as_the_stakeholder_managers_display_name(client, sent):
    await _make_project(client, SLUG)
    await _generate_and_approve_reminder(client, SLUG, days_ago=3)

    await _send_reminders(SLUG)

    display_name = AGENT_IDENTITY["stakeholder_manager"].display_name
    body = text(sent[0])
    assert f"Best regards,\n{display_name}" in body, body
    assert "The Project Team" not in body, body


@pytest.mark.asyncio
async def test_the_signoff_follows_a_rename_in_agent_identity(client, sent, monkeypatch):
    """The property that matters: not merely that today's name appears, but that it is
    *resolved*, not hard-coded. A literal "Jordan Williams" in the template would pass the
    test above and fail this one."""
    monkeypatch.setitem(AGENT_IDENTITY, "stakeholder_manager", Identity("Dana Okafor", None))
    await _make_project(client, SLUG)
    await _generate_and_approve_reminder(client, SLUG, days_ago=3)

    await _send_reminders(SLUG)

    body = text(sent[0])
    assert "Dana Okafor" in body, body
    assert "Jordan Williams" not in body, body
