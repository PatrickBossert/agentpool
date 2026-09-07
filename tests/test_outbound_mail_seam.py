# tests/test_outbound_mail_seam.py
"""dev_mode holds outbound mail on every path, and each path is asked separately.

`dev_mode` reads as "hold all outbound mail for this project" and covered two of the
five send paths. The three it missed - the interview reminder sender, the transcript
sender, and the welcome email - are the ones that email stakeholders rather than the
operator. A test that drove only the two that already worked would have passed on the
day the defect was live, so every path is driven here, and each is driven on its own.

**The assertion is who receives the message, not that a function was called.** Every
test below reads the recipients out of the real HTTP request `_post_to_resend` builds,
through an `httpx.MockTransport` that also carries the URL - so a send that reached the
wrong host, or reached Resend with the participant's own address in `to`, fails here.

**Every path is asserted with the mode off as well as on.** A seam that redirected
unconditionally would hold mail for ever and satisfy every "is it redirected" test in
the file; the "not held" half is what stops that passing.

**Each path is powered separately.** These five paths now share one function, and a
shared seam is exactly the shape that lets one path's test cover another's - which has
bitten this project twice. Each pair below drives one caller end to end, so breaking the
transcript path fails the transcript tests and nothing else.
"""
import json
from email.utils import parseaddr
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from api.config import get_settings
from api.services import outbound_mail

_SLUGS = (
    "seam-governance-held", "seam-governance-open",
    "seam-notice-held", "seam-notice-open",
    "seam-reminder-held", "seam-reminder-open",
    "seam-transcript-held", "seam-transcript-open",
    "seam-face", "seam-footer",
)

# The shipped default, named only where the assertion is *about* that literal - the guard
# below that no service module hardcodes it. Everywhere else the redirect is read from
# settings, because DEV_MODE_ADDRESS is configurable and .env.example tells operators to
# change it: a test asserting the literal would go red for anybody who did.
_SHIPPED_DEFAULT = "Patrick@FutureEdge.consulting"


def redirect() -> str:
    """Where a held project's mail actually goes, per configuration."""
    return get_settings().dev_mode_address


@pytest.fixture(autouse=True)
def clean():
    """Remove this file's databases and project directories either side of each test.

    Without this a project created by one run leaks into the next, and a test that
    asserts "held" would pass against a leftover row rather than the one it wrote.
    """
    settings = get_settings()
    def _wipe():
        for slug in _SLUGS:
            (Path(settings.database_dir) / f"{slug}.db").unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                (Path(settings.database_dir) / f"{slug}.db{suffix}").unlink(missing_ok=True)
            proj = Path(settings.projects_dir) / slug
            if proj.exists():
                import shutil
                shutil.rmtree(proj)
    _wipe()
    yield
    _wipe()


@pytest.fixture
def sent(monkeypatch):
    """Capture the real outbound requests, and return the list they land in.

    `httpx.MockTransport` rather than a swapped client class, so what is asserted is the
    request that would actually have gone on the wire - method, URL and JSON body. A
    mock standing in for `AsyncClient` cannot see a wrong URL, and this project has been
    caught by exactly that before (`local_fast_url` producing `/v1/v1/messages`).

    `httpx` is replaced on the module rather than globally, so the ASGI transport the
    `client` fixture runs on is untouched.
    """
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": "mock-message-id"})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return httpx.AsyncClient(*args, **kwargs)

    monkeypatch.setattr(outbound_mail, "httpx", SimpleNamespace(AsyncClient=factory))
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_seam_test")
    return captured


def recipients(request: httpx.Request) -> list[str]:
    """The addresses this request would actually deliver to."""
    assert str(request.url) == "https://api.resend.com/emails", str(request.url)
    return json.loads(request.content)["to"]


def payload(request: httpx.Request) -> dict:
    return json.loads(request.content)


def sender(request: httpx.Request) -> str:
    """The whole `From` header this request would have carried."""
    return payload(request)["from"]


def sender_address(request: httpx.Request) -> str:
    """Just the address half of `From` - the role, with the person's name stripped off."""
    return parseaddr(sender(request))[1]


def domain() -> str:
    """The sending domain, per configuration.

    Read rather than written literally, for the reason `redirect()` is: FROM_EMAIL is
    configurable and a deployment on another domain must not go red. The *local* parts
    below are written literally, because those are what these tests are about.
    """
    return parseaddr(get_settings().from_email)[1].rpartition("@")[2]


async def _make_project(client, slug: str, *, holds_mail: bool) -> None:
    await client.post("/projects", json={
        "client_slug": slug, "llm_mode": "standard", "sector": "rail",
    })
    await _set_dev_mode(slug, holds_mail)


async def _set_dev_mode(slug: str, value: bool) -> None:
    """dev_mode lives inside config_json, not as a column on projects."""
    from api.database import fetch_project, get_connection
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        config = json.loads(project.get("config_json") or "{}")
        config["dev_mode"] = value
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


async def _activate(slug: str) -> None:
    from api.database import get_connection, set_project_status
    async with get_connection(slug) as conn:
        await set_project_status(conn, slug=slug, status="active")


# ── Path 1: Pamela's daily status report (already honoured dev_mode) ──────────

@pytest.mark.asyncio
async def test_the_status_report_reaches_governance_when_mail_is_not_held(client, sent):
    slug = "seam-governance-open"
    await _make_project(client, slug, holds_mail=False)
    await _activate(slug)
    await _add_stakeholder(slug, "Gov", "governor@example.test", governor=True)

    from api.services.pam_report_job import run_pam_daily_report
    await run_pam_daily_report(slug)

    assert len(sent) == 1
    assert recipients(sent[0]) == ["governor@example.test"]


@pytest.mark.asyncio
async def test_the_status_report_is_held_when_the_project_holds_mail(client, sent):
    slug = "seam-governance-held"
    await _make_project(client, slug, holds_mail=True)
    await _activate(slug)
    await _add_stakeholder(slug, "Gov", "governor@example.test", governor=True)

    from api.services.pam_report_job import run_pam_daily_report
    await run_pam_daily_report(slug)

    assert len(sent) == 1
    assert recipients(sent[0]) == [redirect()]
    assert "governor@example.test" not in recipients(sent[0])


# ── Path 2: the crew notices (already honoured dev_mode) ─────────────────────

@pytest.mark.asyncio
async def test_a_crew_notice_reaches_reviewers_when_mail_is_not_held(client, sent):
    slug = "seam-notice-open"
    await _make_project(client, slug, holds_mail=False)
    await _add_stakeholder(slug, "Rev", "reviewer@example.test", reviewer=True)

    from api.services.commit_notify_service import notify_crew_awaiting_commit
    await notify_crew_awaiting_commit(slug, "discovery_mapping")

    assert len(sent) == 1
    assert recipients(sent[0]) == ["reviewer@example.test"]


@pytest.mark.asyncio
async def test_a_crew_notice_is_held_when_the_project_holds_mail(client, sent):
    slug = "seam-notice-held"
    await _make_project(client, slug, holds_mail=True)
    await _add_stakeholder(slug, "Rev", "reviewer@example.test", reviewer=True)

    from api.services.commit_notify_service import notify_crew_awaiting_commit
    await notify_crew_awaiting_commit(slug, "discovery_mapping")

    assert len(sent) == 1
    assert recipients(sent[0]) == [redirect()]
    assert "reviewer@example.test" not in recipients(sent[0])


# ── Path 3: interview reminders - one of the three that ignored dev_mode ─────

async def _approved_reminder(slug: str, email: str) -> None:
    """One approved reminder addressed to a participant, ready for the sender."""
    from api.database import fetch_project, get_connection, insert_reminder_email
    stakeholder_id = await _add_stakeholder(slug, "Participant", email)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        campaign_cur = await conn.execute(
            "INSERT INTO campaigns (project_id, campaign_name) VALUES (?,?)",
            (project["id"], "Seam campaign"),
        )
        await conn.commit()
        email_id = await insert_reminder_email(
            conn, project_id=project["id"], campaign_id=campaign_cur.lastrowid,
            stakeholder_id=stakeholder_id, subject="A quick reminder",
            body="Please complete your interview.", escalation_level="gentle",
        )
        await conn.execute(
            "UPDATE reminder_emails SET status='approved' WHERE id=?", (email_id,)
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_a_reminder_reaches_the_participant_when_mail_is_not_held(client, sent):
    slug = "seam-reminder-open"
    await _make_project(client, slug, holds_mail=False)
    await _approved_reminder(slug, "participant@example.test")

    from api.services.campaign_service import send_reminder_emails_svc
    result = await send_reminder_emails_svc(slug)

    assert result == {"sent": 1, "failed": 0, "skipped": 0}
    assert len(sent) == 1
    assert recipients(sent[0]) == ["participant@example.test"]


@pytest.mark.asyncio
async def test_a_reminder_is_held_when_the_project_holds_mail(client, sent):
    """The defect, stated directly.

    This path posted `stakeholder_email` straight to Resend with no dev_mode check.
    Sixty seeded stakeholders with plausible addresses would have been sixty live sends
    on a project whose settings said mail was held.
    """
    slug = "seam-reminder-held"
    await _make_project(client, slug, holds_mail=True)
    await _approved_reminder(slug, "participant@example.test")

    from api.services.campaign_service import send_reminder_emails_svc
    result = await send_reminder_emails_svc(slug)

    assert result == {"sent": 1, "failed": 0, "skipped": 0}
    assert len(sent) == 1
    assert recipients(sent[0]) == [redirect()]
    assert "participant@example.test" not in recipients(sent[0])


@pytest.mark.asyncio
async def test_a_held_reminder_is_still_recorded_as_sent(client, sent):
    """A redirected message was posted, so the row must not read as pending for ever."""
    slug = "seam-reminder-held"
    await _make_project(client, slug, holds_mail=True)
    await _approved_reminder(slug, "participant@example.test")

    from api.services.campaign_service import send_reminder_emails_svc
    await send_reminder_emails_svc(slug)

    from api.database import fetch_project, get_connection
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        async with conn.execute(
            "SELECT status FROM reminder_emails WHERE project_id=?", (project["id"],)
        ) as cur:
            rows = [dict(r) async for r in cur]
    assert [r["status"] for r in rows] == ["sent"]


@pytest.mark.asyncio
async def test_a_batch_that_dies_half_way_does_not_re_send_what_it_already_sent(
    client, sent, monkeypatch,
):
    """Each outcome is durable before the next message goes out.

    `POST /reminder-emails/send` is re-runnable and its recipients are real
    stakeholders, so the question that matters is what a *second* press does after the
    first press died part-way. If the statuses are accumulated and written after the
    loop, a death anywhere in a batch of sixty leaves every row at `approved` and the
    whole batch is sent again - to people who have already had it.

    Death is modelled with `asyncio.CancelledError`, which is what an interrupted
    request actually raises and which `except Exception` deliberately does not catch -
    the same event as the `--reload` restart CLAUDE.md warns about killing an in-flight
    run. A batched write fails this test; a per-row write passes it.
    """
    import asyncio

    slug = "seam-reminder-open"
    await _make_project(client, slug, holds_mail=False)
    await _approved_reminder(slug, "first@example.test")
    await _approved_reminder(slug, "second@example.test")

    real_post = outbound_mail._post_to_resend

    async def die_on_the_second(**kwargs):
        if kwargs["to"] == ["second@example.test"]:
            raise asyncio.CancelledError()
        await real_post(**kwargs)

    monkeypatch.setattr(outbound_mail, "_post_to_resend", die_on_the_second)

    from api.services.campaign_service import send_reminder_emails_svc
    with pytest.raises(asyncio.CancelledError):
        await send_reminder_emails_svc(slug)

    # The first message really did go out.
    assert [recipients(r) for r in sent] == [["first@example.test"]]

    from api.database import fetch_project, get_connection
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        async with conn.execute(
            "SELECT s.email, re.status FROM reminder_emails re "
            "JOIN stakeholders s ON s.id = re.stakeholder_id WHERE re.project_id=?",
            (project["id"],),
        ) as cur:
            rows = {r["email"]: r["status"] async for r in cur}

    assert rows["first@example.test"] == "sent", (
        "the delivered message is still approved, so pressing send again re-sends it"
    )
    assert rows["second@example.test"] == "approved", (
        "the undelivered message must stay sendable"
    )


# ── Path 4: the interview transcript - the second of the three ───────────────

_TRANSCRIPT_EMAIL = "interviewee@example.test"


async def _completed_session(client, slug: str, token: str) -> None:
    from api.database import fetch_project, get_connection
    from tests.support_interview_sessions import insert_interview_session
    stakeholder_id = await _add_stakeholder(slug, "Interviewee", _TRANSCRIPT_EMAIL)
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


@pytest.mark.asyncio
async def test_a_transcript_reaches_the_interviewee_when_mail_is_not_held(client, sent):
    slug = "seam-transcript-open"
    await _make_project(client, slug, holds_mail=False)
    await _completed_session(client, slug, "seam-transcript-token-open")

    r = await client.post(
        "/api/interviews/seam-transcript-token-open/email-transcript",
        json={"email": _TRANSCRIPT_EMAIL,
              "qa_pairs": [{"question": "Q1", "answer": "A1"}]},
    )

    assert r.status_code == 200, r.text
    assert len(sent) == 1
    assert recipients(sent[0]) == [_TRANSCRIPT_EMAIL]


@pytest.mark.asyncio
async def test_a_transcript_is_held_when_the_project_holds_mail(client, sent):
    """The second gap. This endpoint posted `body.email` straight to Resend.

    The destination check that constrains it to the session's own stakeholder still
    holds - it is a different control, guarding a leaked token rather than a held
    project - so the address the endpoint intends is unchanged and only its delivery
    moves.
    """
    slug = "seam-transcript-held"
    await _make_project(client, slug, holds_mail=True)
    await _completed_session(client, slug, "seam-transcript-token-held")

    r = await client.post(
        "/api/interviews/seam-transcript-token-held/email-transcript",
        json={"email": _TRANSCRIPT_EMAIL,
              "qa_pairs": [{"question": "Q1", "answer": "A1"}]},
    )

    assert r.status_code == 200, r.text
    assert len(sent) == 1
    assert recipients(sent[0]) == [redirect()]
    assert _TRANSCRIPT_EMAIL not in recipients(sent[0])


# ── Path 5: the welcome email - platform correspondence, and not redirected ──

@pytest.mark.asyncio
async def test_the_welcome_email_goes_to_the_new_login_and_is_not_redirected(sent):
    """The decision, asserted rather than only written down.

    This message announces a login, not an engagement. It carries no slug, so there is
    no project whose `dev_mode` could honestly be consulted, and it is not signed by a
    correspondent because the platform issued the credentials rather than an agent. It
    still leaves through the seam module, which is what keeps the single-egress property
    true - the test below proves nothing else posts to Resend.

    The consequence is real and is stated here so a reader meets it: `dev_mode` does not
    hold this message, and no setting currently does.
    """
    from api.services.admin_service import _send_welcome_email
    await _send_welcome_email("newcomer@example.test", "newcomer", "temp-password")

    assert len(sent) == 1
    assert recipients(sent[0]) == ["newcomer@example.test"]
    assert redirect() not in recipients(sent[0])


@pytest.mark.asyncio
async def test_the_welcome_email_is_not_signed_by_a_correspondent(sent):
    """No persona's name on credentials the platform issued, and no role's address.

    `FROM_EMAIL` exactly as configured, both halves. No role owns this message, so putting
    a role address on it would invite the reply to a mailbox with no reason to answer -
    `noreply@` is the honest sender for a message nobody should answer.
    """
    from agents.identity import AGENT_IDENTITY
    from api.services.admin_service import _send_welcome_email
    await _send_welcome_email("newcomer@example.test", "newcomer", "temp-password")

    assert sender(sent[0]) == get_settings().from_email
    for identity in AGENT_IDENTITY.values():
        assert identity.display_name not in sender(sent[0])
    for audience in outbound_mail.AUDIENCE_CORRESPONDENT:
        assert sender_address(sent[0]) != outbound_mail.role_address(audience)


# ── One face per audience: a mutable name, and an address keyed on the role ──
#
# Every test below reads the `From` header out of the request that would have gone on the
# wire, because that header is the artefact - a helper returning the right string while
# the send path builds its own would satisfy a test of the helper and none of these.

@pytest.mark.asyncio
async def test_stakeholder_mail_carries_the_stakeholder_managers_name(client, sent):
    from agents.identity import AGENT_IDENTITY
    slug = "seam-face"
    await _make_project(client, slug, holds_mail=False)
    await _approved_reminder(slug, "participant@example.test")

    from api.services.campaign_service import send_reminder_emails_svc
    await send_reminder_emails_svc(slug)

    assert AGENT_IDENTITY["stakeholder_manager"].display_name in sender(sent[0])


@pytest.mark.asyncio
async def test_governance_mail_carries_pams_name(client, sent):
    from agents.identity import AGENT_IDENTITY
    slug = "seam-face"
    await _make_project(client, slug, holds_mail=False)
    await _add_stakeholder(slug, "Rev", "reviewer@example.test", reviewer=True)

    from api.services.commit_notify_service import notify_crew_awaiting_commit
    await notify_crew_awaiting_commit(slug, "discovery_mapping")

    assert AGENT_IDENTITY["pam"].display_name in sender(sent[0])


@pytest.mark.asyncio
async def test_stakeholder_mail_is_sent_from_the_stakeholder_management_role(client, sent):
    """The address is the role, not `noreply@` and not the person.

    A participant replying to an interview reminder is answering whoever does stakeholder
    engagement. The local part is asserted literally because the hyphenated form of the
    `agent_id` is the decision under test; the domain is read from settings because it is
    an operator's to change.

    A reminder now also carries that participant's reply token as a `+tag` (sp56 Task 2),
    which is a third independent field and not a move of the mailbox: the part before the
    `+` is still the role, and that is exactly what is asserted here. What the tag *is* is
    `tests/test_reply_tokens.py`'s subject, not this test's.
    """
    slug = "seam-face"
    await _make_project(client, slug, holds_mail=False)
    await _approved_reminder(slug, "participant@example.test")

    from api.services.campaign_service import send_reminder_emails_svc
    await send_reminder_emails_svc(slug)

    local, _, sent_domain = sender_address(sent[0]).partition("@")
    assert local.partition("+")[0] == "stakeholder-manager", sender_address(sent[0])
    assert sent_domain == domain()


@pytest.mark.asyncio
async def test_governance_mail_is_sent_from_the_orchestrator_role(client, sent):
    """`pam` has no underscore to convert, so this is also the case that would pass if
    the rule were applied to nothing at all - which is why the stakeholder one exists."""
    slug = "seam-face"
    await _make_project(client, slug, holds_mail=False)
    await _add_stakeholder(slug, "Rev", "reviewer@example.test", reviewer=True)

    from api.services.commit_notify_service import notify_crew_awaiting_commit
    await notify_crew_awaiting_commit(slug, "discovery_mapping")

    assert sender_address(sent[0]) == f"pam@{domain()}"


@pytest.mark.asyncio
async def test_renaming_the_correspondent_renames_the_face_and_not_the_address(
    client, sent, monkeypatch,
):
    """The property the whole scheme exists for, in one test.

    The name is derived from agents/identity.py at send time, so renaming the person is a
    one-file change - a hard-coded "Jordan Williams" in the seam would pass every other
    test in this file and fail the first half of this one.

    The address is keyed on the permanent `agent_id`, so the *same* rename must not move
    it. That is what makes a mailbox outlive the person behind it, what keeps a year-old
    thread routing correctly, and what stops per-project display names - the next piece of
    work here - multiplying into per-project mailboxes. Deriving the local part from the
    display name would pass the first half and fail the second.
    """
    from agents.identity import AGENT_IDENTITY, Identity

    slug = "seam-face"
    await _make_project(client, slug, holds_mail=False)
    await _approved_reminder(slug, "participant@example.test")

    monkeypatch.setitem(
        AGENT_IDENTITY, "stakeholder_manager", Identity("Wilhelmina Testcase", None)
    )
    from api.services.campaign_service import send_reminder_emails_svc
    await send_reminder_emails_svc(slug)

    assert "Wilhelmina Testcase" in sender(sent[0])
    assert "Jordan" not in sender(sent[0])
    # The role, read past the reply-token tag a reminder now carries - see the note on
    # test_stakeholder_mail_is_sent_from_the_stakeholder_management_role.
    local, _, sent_domain = sender_address(sent[0]).partition("@")
    assert local.partition("+")[0] == "stakeholder-manager", sender_address(sent[0])
    assert sent_domain == domain()


@pytest.mark.asyncio
async def test_a_display_name_that_needs_quoting_does_not_split_the_header(
    client, sent, monkeypatch,
):
    """Display names become project-settable, and a comma in one is not exotic.

    An unquoted `Reid, Pamela <pam@...>` is two addresses to a parser, the first of them
    malformed. The header must survive a round trip through the same parsing a mail server
    would do it.
    """
    from email.utils import getaddresses

    from agents.identity import AGENT_IDENTITY, Identity

    slug = "seam-face"
    await _make_project(client, slug, holds_mail=False)
    await _add_stakeholder(slug, "Rev", "reviewer@example.test", reviewer=True)

    monkeypatch.setitem(AGENT_IDENTITY, "pam", Identity("Reid, Pamela", None))
    from api.services.commit_notify_service import notify_crew_awaiting_commit
    await notify_crew_awaiting_commit(slug, "discovery_mapping")

    parsed = getaddresses([sender(sent[0])])
    assert parsed == [("Reid, Pamela", f"pam@{domain()}")], sender(sent[0])


def test_a_role_address_is_a_rule_over_the_id_and_never_a_second_registry():
    """No id-to-address table exists, so every agent already has a usable address.

    A mapping would be a second registry mirroring agents/identity.py, free to drift from
    the ids it names. The cost of deriving instead is that a future `agent_id` could mint
    a local part no mail server accepts - so the rule is checked against every id on the
    roll rather than against the two audiences that use it today.
    """
    import re

    from agents.identity import AGENT_IDENTITY

    for agent_id in AGENT_IDENTITY:
        local = agent_id.replace("_", "-")
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", local), agent_id


@pytest.mark.asyncio
async def test_moving_from_email_moves_every_role_address_with_it(
    client, sent, monkeypatch,
):
    """One setting names the domain, and the role addresses follow it.

    A second setting for the domain - or a literal in the seam - would let a deployment
    half-move: `FROM_EMAIL` on the new domain, project mail still leaving from the old
    one. Asserted by actually moving it and reading the header off the wire, because a
    hardcoded `taskreimagination.ai` passes every other test in this file.
    """
    slug = "seam-face"
    await _make_project(client, slug, holds_mail=False)
    await _add_stakeholder(slug, "Rev", "reviewer@example.test", reviewer=True)

    monkeypatch.setattr(get_settings(), "from_email", "Elsewhere <noreply@example.org>")
    from api.services.commit_notify_service import notify_crew_awaiting_commit
    await notify_crew_awaiting_commit(slug, "discovery_mapping")

    assert sender_address(sent[0]) == "pam@example.org"


def test_a_from_email_with_no_address_is_refused_rather_than_half_built(monkeypatch):
    """Better than minting `pam@` with an empty domain and learning from a Resend 4xx."""
    monkeypatch.setattr(get_settings(), "from_email", "TaskReimagination.ai")
    with pytest.raises(RuntimeError, match="sending domain"):
        outbound_mail.role_address(outbound_mail.STAKEHOLDERS)


def test_every_audience_resolves_to_an_agent_that_exists():
    """A correspondent naming an agent the identity map does not hold would only fail
    at send time, on a path a test may not drive."""
    from agents.identity import AGENT_IDENTITY
    for audience, agent_id in outbound_mail.AUDIENCE_CORRESPONDENT.items():
        assert agent_id in AGENT_IDENTITY, audience


def test_an_unknown_audience_is_refused_rather_than_given_someones_name():
    with pytest.raises(ValueError, match="no correspondent"):
        outbound_mail.correspondent_for("finance")


# ── The redirect itself ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_held_message_names_the_people_it_would_have_reached(client, sent):
    """A message that arrives at the redirect address with no explanation is a message
    the reader cannot act on - they cannot tell whose mail they are holding."""
    slug = "seam-footer"
    await _make_project(client, slug, holds_mail=True)
    await _add_stakeholder(slug, "Rev", "reviewer@example.test", reviewer=True)
    await _add_stakeholder(slug, "Two", "second@example.test", reviewer=True)

    from api.services.commit_notify_service import notify_crew_awaiting_commit
    await notify_crew_awaiting_commit(slug, "discovery_mapping")

    text = payload(sent[0])["text"]
    assert "reviewer@example.test" in text
    assert "second@example.test" in text


@pytest.mark.asyncio
async def test_an_open_message_carries_no_development_mode_footer(client, sent):
    slug = "seam-footer"
    await _make_project(client, slug, holds_mail=False)
    await _add_stakeholder(slug, "Rev", "reviewer@example.test", reviewer=True)

    from api.services.commit_notify_service import notify_crew_awaiting_commit
    await notify_crew_awaiting_commit(slug, "discovery_mapping")

    assert "development mode" not in payload(sent[0])["text"]


@pytest.mark.asyncio
async def test_a_slug_with_no_database_holds_its_mail(sent):
    """Fails closed. `project_llm_mode("")` answering "standard" for a missing database
    is how a sensitive project's answers reached a hosted model; the same shape here
    would be a live send to a real address."""
    posted = await outbound_mail.send_project_mail(
        slug="no-such-project-anywhere", audience=outbound_mail.STAKEHOLDERS,
        to=["real.person@example.test"], subject="s", body="b",
    )
    assert posted is True
    assert recipients(sent[0]) == [redirect()]


@pytest.mark.asyncio
async def test_redirecting_nobody_does_not_invent_a_recipient(client, sent):
    slug = "seam-footer"
    await _make_project(client, slug, holds_mail=True)

    posted = await outbound_mail.send_project_mail(
        slug=slug, audience=outbound_mail.GOVERNANCE, to=[], subject="s", body="b",
    )
    assert posted is False
    assert sent == []


@pytest.mark.asyncio
async def test_a_malformed_address_does_not_cost_everyone_else_the_message(client, sent):
    """Resend rejects the whole request when one entry in `to` is malformed, so a stray
    username would take every other recipient's message down with it."""
    slug = "seam-footer"
    await _make_project(client, slug, holds_mail=False)

    await outbound_mail.send_project_mail(
        slug=slug, audience=outbound_mail.GOVERNANCE,
        to=["admin", "real@example.test"], subject="s", body="b",
    )
    assert recipients(sent[0]) == ["real@example.test"]


# ── The structural half: one place posts to Resend ───────────────────────────

def test_only_the_seam_posts_to_resend():
    """Anything posting to `api.resend.com/emails` from anywhere else is the defect
    returning: five call sites is how three of them came to have no dev_mode check.

    Asserted structurally because the alternative is noticing it in review, and this
    project's own history says that a send path added beside an existing one inherits
    whatever that one happened to do.
    """
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        parts = set(path.parts)
        if parts & {"venv", "node_modules", ".git", "tests"}:
            continue
        if "api.resend.com" in path.read_text():
            offenders.append(str(path.relative_to(root)))

    assert offenders == ["api/services/outbound_mail.py"], offenders


def test_the_redirect_address_is_not_hardcoded_in_a_service_module():
    """It was a module constant in `pam_report_job`, imported by `commit_notify_service`
    - one person's address in source, in the module that happened to need it first."""
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in (root / "api").rglob("*.py"):
        if path.name == "config.py":
            continue
        if _SHIPPED_DEFAULT in path.read_text():
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], offenders
