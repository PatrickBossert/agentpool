# tests/test_send_back_notifications.py
"""The email a reviewer gets when something is sent back, driven rather than mocked.

**Every existing test of these two functions patches them out**, so the body - the audience
resolution, the subject, and the line that builds the link - had never executed. That is the
right tool for "did the door notify?" and it is exactly why nobody had run the line that
builds the link, which was wrong: `_notify`'s second positional argument becomes `?crew=` and
both notifiers passed the *item id*, so a reviewer told that SC-014 or 3.3.3 had been sent
back landed on a crew that does not exist.

So everything here executes the real function with only the mail seam stubbed. The stub is
`send_project_mail`, patched where `commit_notify_service` looks it up, and the assertions are
made on the body it was handed - which is what an inbox would show.

`notify_script_sent_back` carried the same defect and predates this branch; it is fixed and
asserted here beside its sibling, because one of the two passing and the other not is how the
second instance arrived in the first place.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import get_connection
from api.services.commit_notify_service import (
    LEDGER_CREW,
    notify_item_sent_back,
    notify_script_sent_back,
)

SLUG = "send-back-notification-test"


@pytest_asyncio.fixture
async def project_with_a_reviewer():
    """One project with one reviewer stakeholder, so the audience resolves to somebody.

    `_notify` returns early when nobody is resolved, which would make every assertion below
    pass vacuously against an empty mailbox - the failure mode of a test that stubs the send
    and never checks it happened. `assert_awaited_once` on the stub is what rules that out.

    The db file is removed on both sides: conftest points DATABASE_DIR at a persistent /tmp
    path, so leftover rows from a previous run must not be able to change what resolves.
    """
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)

    async with get_connection(SLUG) as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES (?)", (SLUG,))
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (SLUG,))
        project_id = (await cur.fetchone())["id"]
        await conn.execute(
            "INSERT INTO stakeholders (project_id, name, email, is_reviewer)"
            " VALUES (?, 'Priya Raman', 'priya.raman@example.test', 1)",
            (project_id,),
        )
        await conn.commit()

    yield SLUG

    db_path.unlink(missing_ok=True)
    get_settings.cache_clear()


def _sent_mail():
    """Stub the one seam that reaches Resend, and nothing else.

    Patched on `api.services.commit_notify_service.send_project_mail` - where the name is
    looked up, because that module binds its own reference with `from ... import`. Patching
    the definition site in `outbound_mail` would leave this call reaching the real one.
    """
    return patch(
        "api.services.commit_notify_service.send_project_mail", new=AsyncMock()
    )


def _link_in(body: str) -> str:
    for line in body.splitlines():
        if "http" in line:
            return line.split("Review it here: ", 1)[-1].strip()
    raise AssertionError(f"no link in the notification body:\n{body}")


# ══════════════════════════════════════════════════════════════════════════════════════
# The link
# ══════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,item_id", [("node", "3.3.3"), ("lever", "LV-001")],
)
async def test_the_item_link_names_the_crew_whose_tab_renders_the_ledger(
    project_with_a_reviewer, kind, item_id
):
    """`?crew=discovery_mapping`, which is where the node and lever ledgers are rendered.

    Asserted on the parsed query string rather than on a substring of the URL: `?crew=3.3.3`
    and `?crew=discovery_mapping` both contain "crew=", and a substring test that happened to
    match the tab would have passed against the defect.
    """
    with _sent_mail() as send:
        await notify_item_sent_back(
            project_with_a_reviewer, kind, item_id, "agent", "Wrong altitude."
        )
    send.assert_awaited_once()
    query = parse_qs(urlparse(_link_in(send.await_args.kwargs["body"])).query)
    assert query["crew"] == ["discovery_mapping"]
    assert query["tab"] == ["output"]


@pytest.mark.asyncio
async def test_the_script_link_names_assessment_design_and_not_the_script_id(
    project_with_a_reviewer,
):
    """The pre-existing half of the same defect. Every send-back notification this deployment
    has sent carried `?crew=SC-014`; one argument fixed both, and both are asserted."""
    with _sent_mail() as send:
        await notify_script_sent_back(
            project_with_a_reviewer, "SC-014", "agent", "The framing repeats the welcome."
        )
    send.assert_awaited_once()
    query = parse_qs(urlparse(_link_in(send.await_args.kwargs["body"])).query)
    assert query["crew"] == ["assessment_design"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "notify,item_id",
    [
        (lambda slug: notify_item_sent_back(slug, "node", "3.3.3", "agent", "n"), "3.3.3"),
        (lambda slug: notify_item_sent_back(slug, "lever", "LV-001", "agent", "n"), "LV-001"),
        (lambda slug: notify_script_sent_back(slug, "SC-014", "agent", "n"), "SC-014"),
    ],
)
async def test_the_item_id_never_reaches_the_query_string(
    project_with_a_reviewer, notify, item_id
):
    """The defect stated as its own property, in the place it appeared.

    The two tests above say what the crew *is*; this says what it must never be. They are not
    the same assertion - a third ledger wired to some other wrong constant would pass both of
    those and fail this one.
    """
    with _sent_mail() as send:
        await notify(project_with_a_reviewer)
    send.assert_awaited_once()
    link = _link_in(send.await_args.kwargs["body"])
    assert item_id not in urlparse(link).query
    # It is still in the mail, where it belongs - the reviewer has to know which one.
    assert item_id in send.await_args.kwargs["subject"]


@pytest.mark.asyncio
async def test_the_link_is_built_on_this_deployments_public_url(project_with_a_reviewer):
    """Read through `platform_public_url`, so a deployment that stored one mails that one.

    Driven rather than read: this line lives inside `_notify`'s blanket `try`, so a link
    builder that raised would have produced no mail at all and no error anybody sees.
    """
    with _sent_mail() as send, patch(
        "api.services.commit_notify_service.platform_public_url",
        return_value="https://engagements.example.test",
    ):
        await notify_item_sent_back(project_with_a_reviewer, "node", "3.3.3", "agent", "n")
    link = _link_in(send.await_args.kwargs["body"])
    assert link.startswith(
        f"https://engagements.example.test/dashboard/{project_with_a_reviewer}?"
    )


# ══════════════════════════════════════════════════════════════════════════════════════
# The declaration the link is built from
# ══════════════════════════════════════════════════════════════════════════════════════

def test_every_ledger_link_names_the_crew_that_actually_runs_its_agent():
    """`LEDGER_CREW` held against the maps it must agree with, by derivation.

    Each ledger tracks an output type; `OUTPUT_OWNERS` says which agent writes that type, and
    `_CREW_AGENT_NAMES` says which crew dispatches that agent. The expected value is computed
    from those two rather than restated, so moving an agent between crews fails here instead
    of quietly mailing a link to the crew it used to be in.

    Set equality over the keys as well, so a ledger added without a crew fails as loudly as a
    crew named for a ledger that no longer exists - the shape CLAUDE.md's sole-caller guard
    uses, and for the same reason.
    """
    from agents.tools.ownership import OUTPUT_OWNERS
    from api.services.item_review_service import ITEM_LEDGERS
    from api.services.run_service import _CREW_AGENT_NAMES

    crew_of_agent = {
        agent: crew for crew, agents in _CREW_AGENT_NAMES.items() for agent in agents
    }
    expected = {
        kind: crew_of_agent[OUTPUT_OWNERS[spec.output_type]]
        for kind, spec in ITEM_LEDGERS.items()
    }
    # The script ledger is not in ITEM_LEDGERS - it predates it and has its own service - so
    # its own derivation is spelled out rather than left as the one unchecked entry.
    expected["script"] = crew_of_agent[OUTPUT_OWNERS["interview_scripts"]]

    assert LEDGER_CREW == expected


def test_the_derivation_this_file_uses_is_not_vacuous():
    """The guard above compares two computed dicts, and two empty dicts are equal.

    A renamed `OUTPUT_OWNERS` key or an `ITEM_LEDGERS` that lost its `output_type` field would
    raise rather than pass - but a future refactor that made either lookup total-with-a-default
    would leave the assertion true and meaningless.
    """
    assert set(LEDGER_CREW) == {"script", "node", "lever"}
    assert LEDGER_CREW["node"] == "discovery_mapping"
    assert LEDGER_CREW["script"] == "assessment_design"


# ══════════════════════════════════════════════════════════════════════════════════════
# The audience and the words
# ══════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_notification_reaches_the_projects_reviewers(project_with_a_reviewer):
    """Resolved from the stakeholder flags for real, not asserted at the call boundary."""
    with _sent_mail() as send:
        await notify_item_sent_back(
            project_with_a_reviewer, "node", "3.3.3", "agent", "Wrong altitude."
        )
    assert send.await_args.kwargs["to"] == ["priya.raman@example.test"]


@pytest.mark.asyncio
async def test_a_project_whose_governors_are_all_approvers_still_hears(tmp_path, monkeypatch):
    """The fallback, driven. A project with approvers and no reviewers would otherwise be
    notified of nothing at all - which is the reason `notify_crew_awaiting_commit` has this
    fallback and the reason this inherited it."""
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    slug = "approvers-only-send-back"
    async with get_connection(slug) as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES (?)", (slug,))
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (slug,))
        await conn.execute(
            "INSERT INTO stakeholders (project_id, name, email, is_approver)"
            " VALUES (?, 'Sam Okafor', 'sam.okafor@example.test', 1)",
            ((await cur.fetchone())["id"],),
        )
        await conn.commit()

    with _sent_mail() as send:
        await notify_item_sent_back(slug, "lever", "LV-001", "agent", "Not a lever.")
    assert send.await_args.kwargs["to"] == ["sam.okafor@example.test"]
    get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,described", [("node", "value chain node"), ("lever", "value lever")],
)
async def test_the_subject_says_which_kind_of_thing_was_sent_back(
    project_with_a_reviewer, kind, described
):
    """"value chain node 3.3.3" and "value lever LV-001" are what a reviewer recognises. A
    subject saying "item" would be true of both and useful for neither."""
    item_id = "3.3.3" if kind == "node" else "LV-001"
    with _sent_mail() as send:
        await notify_item_sent_back(project_with_a_reviewer, kind, item_id, "agent", "n")
    assert f"{described} {item_id}" in send.await_args.kwargs["subject"]


@pytest.mark.asyncio
async def test_the_reviewers_note_travels_with_the_notification(project_with_a_reviewer):
    """The note is the whole content of the message - "3.3.3 was sent back" without it tells
    a reviewer nothing they can act on."""
    with _sent_mail() as send:
        await notify_item_sent_back(
            project_with_a_reviewer, "node", "3.3.3", "agent",
            "This belongs at L2 - it is a decision, not a task.",
        )
    assert "This belongs at L2 - it is a decision, not a task." in (
        send.await_args.kwargs["body"]
    )


@pytest.mark.asyncio
async def test_a_send_back_with_no_note_does_not_mail_the_word_none(
    project_with_a_reviewer,
):
    """A return to reviewers carries no note, and "Note: " with nothing after it reads as a
    broken template rather than as an absent note."""
    with _sent_mail() as send:
        await notify_item_sent_back(project_with_a_reviewer, "node", "3.3.3", "reviewer", "")
    body = send.await_args.kwargs["body"]
    assert "Note:" not in body
    assert "3.3.3 has been sent back to the reviewer." in body


@pytest.mark.asyncio
async def test_a_project_with_nobody_to_tell_sends_nothing(tmp_path, monkeypatch):
    """Rather than mailing an empty recipient list, which Resend refuses as a whole request."""
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    slug = "nobody-to-tell"
    async with get_connection(slug) as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES (?)", (slug,))
        await conn.commit()

    with _sent_mail() as send:
        await notify_item_sent_back(slug, "node", "3.3.3", "agent", "n")
    send.assert_not_awaited()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_notifier_never_raises_into_its_caller(project_with_a_reviewer, caplog):
    """The review is already committed by the time this runs, so a mail failure must not turn
    a recorded send-back into a failed request - and must not be silent either."""
    with patch(
        "api.services.commit_notify_service.send_project_mail",
        new=AsyncMock(side_effect=RuntimeError("resend is down")),
    ):
        await notify_item_sent_back(project_with_a_reviewer, "node", "3.3.3", "agent", "n")
    assert "could not notify" in caplog.text
    # The crew alone no longer says which thing failed to be announced, now that the crew is
    # the crew; the subject is logged so an operator can tell which send-back went unheard.
    assert "3.3.3" in caplog.text
