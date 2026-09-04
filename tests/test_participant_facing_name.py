# tests/test_participant_facing_name.py
"""A participant reads the name they know us by; the slug is the operator's alone.

`sp-gs-am` is a filename, a database name and a URL segment. A stakeholder at GS Asset
Management has no reason to meet it, and "GS Asset Management - Your interview transcript"
is what should land in their inbox. Governance is the other way round: a governor tracking
four engagements files by the slug, so their subject keeps it and the report body carries
the mapping between the two names instead.

**Every assertion here reads the subject out of the real HTTP request `_post_to_resend`
builds**, through an `httpx.MockTransport`, for the reason the seam's own tests do: a
helper that returns the right string while the send path builds its own would satisfy a
test of the helper and none of these. `compose_subject` is asserted directly exactly once,
and only for the case that has no send path to drive it through.

**Each participant path is driven on its own.** The two of them share one seam, and a
shared seam is the shape that lets one path's test cover another's - which has bitten this
project twice. There is also a seam-level test, because the guarantee is meant to hold for
the participant path that has not been written yet.

**The empty case is the common case.** `client_name` ships empty, so every project that
exists today takes that path; it is tested as the default rather than as an edge.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from api.config import get_settings
from api.services import outbound_mail

# A slug shaped like a real one, so "the slug did not leak" is a claim about a string that
# could plausibly have leaked rather than about a placeholder.
SLUG = "pfn-gs-am"
CLIENT_NAME = "GS Asset Management"

_SLUGS = (SLUG, "pfn-unnamed", "pfn-governance")


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
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_pfn_test")
    return captured


def payload(request: httpx.Request) -> dict:
    assert str(request.url) == "https://api.resend.com/emails", str(request.url)
    return json.loads(request.content)


def subject(request: httpx.Request) -> str:
    return payload(request)["subject"]


def text(request: httpx.Request) -> str:
    return payload(request)["text"]


# ── Fixture data ─────────────────────────────────────────────────────────────

async def _make_project(client, slug: str, **config_keys) -> None:
    """A project, registered exactly as `POST /projects` registers one.

    Going through the door rather than writing the row matters here: the door registers the
    slug with `display_name=req.client_slug`, so the registry's display name **is** the slug.
    A fallback to it would look like a friendly name and read as `pfn-gs-am` to a
    participant, and only a project made this way can catch that.
    """
    await client.post("/projects", json={
        "client_slug": slug, "llm_mode": "standard", "sector": "rail",
    })
    await _set_config(slug, dev_mode=False, **config_keys)


async def _set_config(slug: str, **keys) -> None:
    """Merge keys into `config_json`, which is where the seam reads its settings."""
    from api.database import fetch_project, get_connection
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        config = json.loads(project.get("config_json") or "{}")
        config.update(keys)
        await conn.execute(
            "UPDATE projects SET config_json=? WHERE slug=?", (json.dumps(config), slug)
        )
        await conn.commit()


async def _add_stakeholder(slug: str, name: str, email: str, **flags) -> int:
    from api.database import fetch_project, get_connection
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        cur = await conn.execute(
            "INSERT INTO stakeholders (project_id, name, email, project_role, "
            "is_reviewer, is_approver, is_governor) VALUES (?,?,?,?,?,?,?)",
            (project["id"], name, email, "governing",
             int(flags.get("reviewer", False)), int(flags.get("approver", False)),
             int(flags.get("governor", False))),
        )
        await conn.commit()
        return cur.lastrowid


REMINDER_SUBJECT = "A quick reminder"
PARTICIPANT = "participant@example.test"


async def _approved_reminder(slug: str) -> None:
    from api.database import fetch_project, get_connection, insert_reminder_email
    stakeholder_id = await _add_stakeholder(slug, "Participant", PARTICIPANT)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        campaign_cur = await conn.execute(
            "INSERT INTO campaigns (project_id, campaign_name) VALUES (?,?)",
            (project["id"], "Discovery"),
        )
        await conn.commit()
        email_id = await insert_reminder_email(
            conn, project_id=project["id"], campaign_id=campaign_cur.lastrowid,
            stakeholder_id=stakeholder_id, subject=REMINDER_SUBJECT,
            body="Please complete your interview.", escalation_level="gentle",
        )
        await conn.execute(
            "UPDATE reminder_emails SET status='approved' WHERE id=?", (email_id,)
        )
        await conn.commit()


async def _send_reminder(slug: str) -> None:
    from api.services.campaign_service import send_reminder_emails_svc
    await send_reminder_emails_svc(slug)


TRANSCRIPT_SUBJECT = "Your interview transcript"
INTERVIEWEE = "interviewee@example.test"


async def _completed_session(slug: str, token: str) -> None:
    from api.database import fetch_project, get_connection
    from tests.support_interview_sessions import insert_interview_session
    stakeholder_id = await _add_stakeholder(slug, "Interviewee", INTERVIEWEE)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
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


async def _activate(slug: str) -> None:
    from api.database import get_connection, set_project_status
    async with get_connection(slug) as conn:
        await set_project_status(conn, slug=slug, status="active")


# ── The two participant-facing paths, each driven on its own ─────────────────

@pytest.mark.asyncio
async def test_a_reminder_is_headed_with_the_name_the_participant_knows_us_by(client, sent):
    await _make_project(client, SLUG, client_name=CLIENT_NAME)
    await _approved_reminder(SLUG)

    await _send_reminder(SLUG)

    assert subject(sent[0]) == f"{CLIENT_NAME} - {REMINDER_SUBJECT}"


@pytest.mark.asyncio
async def test_a_transcript_is_headed_with_the_name_the_participant_knows_us_by(
    client, sent,
):
    await _make_project(client, SLUG, client_name=CLIENT_NAME)
    await _completed_session(SLUG, "pfn-transcript-named")

    await _send_transcript(client, "pfn-transcript-named")

    assert subject(sent[0]) == f"{CLIENT_NAME} - {TRANSCRIPT_SUBJECT}"


@pytest.mark.asyncio
async def test_the_name_is_applied_by_the_seam_and_not_by_the_two_paths_that_exist(
    client, sent,
):
    """The guarantee has to hold for the participant path nobody has written yet.

    There is no interview-invitation sender today - a link reaches a participant through the
    reminder path or by hand - so the third participant-facing sender is a matter of when.
    Applied at the seam it is already headed correctly; applied at the two call sites it is
    not, and the two tests above would pass either way.
    """
    await _make_project(client, SLUG, client_name=CLIENT_NAME)

    await outbound_mail.send_project_mail(
        slug=SLUG, audience=outbound_mail.STAKEHOLDERS, to=[PARTICIPANT],
        subject="Your interview", body="An invitation nobody has written yet.",
    )

    assert subject(sent[0]) == f"{CLIENT_NAME} - Your interview"


@pytest.mark.asyncio
async def test_a_held_message_is_still_headed_with_the_participants_name(client, sent):
    """Two independent decisions taken from one read of the project.

    A redirected message is still the participant's message; the operator reading it in the
    dev-mode mailbox should see the subject that would have gone out. Collapsing the two
    decisions - heading the subject only when the mail is actually delivered, say - would
    make every held message misrepresent what was composed.
    """
    await _make_project(client, SLUG, client_name=CLIENT_NAME)
    await _set_config(SLUG, dev_mode=True)
    await _approved_reminder(SLUG)

    await _send_reminder(SLUG)

    assert payload(sent[0])["to"] == [get_settings().dev_mode_address]
    assert subject(sent[0]) == f"{CLIENT_NAME} - {REMINDER_SUBJECT}"


# ── The empty case, which is every project's default today ───────────────────

@pytest.mark.asyncio
async def test_an_unnamed_project_sends_the_reminder_subject_exactly_as_composed(
    client, sent,
):
    """`client_name` ships empty, so this is the common path rather than the edge.

    The two things it must not be are stated separately because they fail separately: an
    unconditional prefix produces `"- A quick reminder"`, and a fallback to the registry's
    display name produces `"pfn-unnamed - A quick reminder"`, since `POST /projects`
    registers a new slug with its display name set to the slug.
    """
    await _make_project(client, "pfn-unnamed")
    await _approved_reminder("pfn-unnamed")

    await _send_reminder("pfn-unnamed")

    assert subject(sent[0]) == REMINDER_SUBJECT
    assert not subject(sent[0]).startswith("-")
    assert "pfn-unnamed" not in subject(sent[0])


@pytest.mark.asyncio
async def test_an_unnamed_project_sends_the_transcript_subject_exactly_as_composed(
    client, sent,
):
    await _make_project(client, "pfn-unnamed")
    await _completed_session("pfn-unnamed", "pfn-transcript-unnamed")

    await _send_transcript(client, "pfn-transcript-unnamed")

    assert subject(sent[0]) == TRANSCRIPT_SUBJECT
    assert not subject(sent[0]).startswith("-")
    assert "pfn-unnamed" not in subject(sent[0])


@pytest.mark.asyncio
async def test_a_name_that_is_only_whitespace_is_no_name(client, sent):
    """It is free text on a settings form, and a space is what a half-finished edit leaves.

    `" " - A quick reminder` is the unconditional prefix's failure wearing a different
    coat, so emptiness is decided after stripping rather than by truthiness.
    """
    await _make_project(client, SLUG, client_name="   ")
    await _approved_reminder(SLUG)

    await _send_reminder(SLUG)

    assert subject(sent[0]) == REMINDER_SUBJECT


@pytest.mark.asyncio
async def test_a_project_with_no_database_still_leaks_no_slug(sent):
    """Fails safe on the same read that fails closed for `dev_mode`.

    An unreadable project has no name, so the subject goes out as composed. The slug is the
    one thing to hand at that moment, which is exactly why it must not be reachable from
    here - `compose_subject` is not given it.
    """
    await outbound_mail.send_project_mail(
        slug="no-such-project-anywhere", audience=outbound_mail.STAKEHOLDERS,
        to=[PARTICIPANT], subject=TRANSCRIPT_SUBJECT, body="b",
    )

    assert subject(sent[0]) == TRANSCRIPT_SUBJECT
    assert "no-such-project-anywhere" not in subject(sent[0])


# ── The property, stated once over every participant-facing path ─────────────

@pytest.mark.asyncio
async def test_the_slug_reaches_no_participant_in_a_subject_or_a_body(client, sent):
    """Both paths, named and unnamed, subject and body: the slug appears in none of them.

    Driven over the unnamed project as well as the named one because the unnamed project is
    where a slug would be reached for - there is nothing else to head a subject with.
    """
    for slug, config in ((SLUG, {"client_name": CLIENT_NAME}), ("pfn-unnamed", {})):
        await _make_project(client, slug, **config)
        await _approved_reminder(slug)
        await _send_reminder(slug)
        await _completed_session(slug, f"pfn-slug-check-{slug}")
        await _send_transcript(client, f"pfn-slug-check-{slug}")

    assert len(sent) == 4
    for request in sent:
        assert SLUG not in subject(request), subject(request)
        assert SLUG not in text(request), text(request)
        assert "pfn-unnamed" not in subject(request), subject(request)
        assert "pfn-unnamed" not in text(request), text(request)


def test_the_seam_can_head_a_subject_with_no_name_it_was_not_given():
    """The empty case as a unit, which is the one case with no send path of its own.

    `compose_subject` takes no slug, so there is no fallback for a future edit to reach for.
    Asserted here rather than only in the transport tests because a signature is the thing
    being fixed - the transport tests would still pass if a slug parameter were added and
    left unused.
    """
    import inspect
    assert "slug" not in inspect.signature(outbound_mail.compose_subject).parameters
    assert outbound_mail.compose_subject(
        outbound_mail.STAKEHOLDERS, TRANSCRIPT_SUBJECT, ""
    ) == TRANSCRIPT_SUBJECT


# ── Governance keeps the slug, and gets the mapping in the report header ─────

@pytest.mark.asyncio
async def test_the_status_report_subject_keeps_the_slug_governance_files_by(client, sent):
    """Not an oversight and not a leak. A governor tracking four engagements names this one
    `pfn-gs-am` in a status meeting and sorts their inbox by it, so the subject is left
    exactly as Pamela composed it."""
    await _make_project(client, SLUG, client_name=CLIENT_NAME)
    await _activate(SLUG)
    await _add_stakeholder(SLUG, "Gov", "governor@example.test", governor=True)

    from api.services.pam_report_job import run_pam_daily_report
    await run_pam_daily_report(SLUG)

    assert subject(sent[0]).startswith(f"{SLUG} status report")
    assert not subject(sent[0]).startswith(CLIENT_NAME)


@pytest.mark.asyncio
async def test_the_status_report_header_carries_both_names(client, sent):
    """The mapping between the two names, in the one place a governor will look for it.

    The subject is addressed and filed by slug; the header is where the reader learns which
    engagement that slug is. Read off the wire because the header is what reaches them - a
    test of `_report_header` alone would pass with the report body still composed the old
    way.
    """
    await _make_project(client, SLUG, client_name=CLIENT_NAME)
    await _activate(SLUG)
    await _add_stakeholder(SLUG, "Gov", "governor@example.test", governor=True)

    from api.services.pam_report_job import run_pam_daily_report
    await run_pam_daily_report(SLUG)

    header = text(sent[0]).splitlines()[0]
    assert CLIENT_NAME in header, header
    assert SLUG in header, header


@pytest.mark.asyncio
async def test_an_unnamed_status_report_header_carries_the_slug_alone(client, sent):
    """No empty bracket. `Status report for pfn-unnamed ()` is what an unconditional
    `f"{name} ({slug})"` produces on every project that exists today."""
    await _make_project(client, "pfn-unnamed")
    await _activate("pfn-unnamed")
    await _add_stakeholder("pfn-unnamed", "Gov", "governor@example.test", governor=True)

    from api.services.pam_report_job import run_pam_daily_report
    await run_pam_daily_report("pfn-unnamed")

    header = text(sent[0]).splitlines()[0]
    assert header.startswith("Status report for pfn-unnamed - "), header
    assert "(" not in header, header


@pytest.mark.asyncio
async def test_a_crew_notice_subject_is_not_headed_with_the_client_name(client, sent):
    """The second governance path, driven separately from the first.

    Both audiences resolve through one `SUBJECT_PREFIXED_AUDIENCES`, so this could be
    covered by the report test - which is precisely the shape that has let one path's test
    stand in for another's here before.
    """
    await _make_project(client, "pfn-governance", client_name=CLIENT_NAME)
    await _add_stakeholder("pfn-governance", "Rev", "reviewer@example.test", reviewer=True)

    from api.services.commit_notify_service import notify_crew_awaiting_commit
    await notify_crew_awaiting_commit("pfn-governance", "discovery_mapping")

    assert not subject(sent[0]).startswith(CLIENT_NAME)
    assert CLIENT_NAME not in subject(sent[0])


# ── Platform correspondence has no project, so it takes neither name ─────────

@pytest.mark.asyncio
async def test_the_welcome_email_carries_neither_a_client_name_nor_a_slug(sent):
    """It announces a login, not an engagement. There is no project whose name it could
    honestly carry, which is the same reason no correspondent signs it."""
    from api.services.admin_service import _send_welcome_email
    await _send_welcome_email("newcomer@example.test", "newcomer", "temp-password")

    assert subject(sent[0]) == "Your TaskReimagination.ai account has been created"
    assert CLIENT_NAME not in subject(sent[0])
    assert SLUG not in subject(sent[0])


def test_only_the_participant_audience_is_prefixed():
    """The decision, written where it is taken. A new audience is opted in deliberately or
    not at all, because the alternative is a governance-shaped audience inheriting a
    participant-shaped subject from whichever rule happened to be uniform."""
    assert outbound_mail.SUBJECT_PREFIXED_AUDIENCES == frozenset(
        {outbound_mail.STAKEHOLDERS}
    )
