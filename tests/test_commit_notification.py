# tests/test_commit_notification.py
"""Pamela's audience is governance - reviewers and approvers. Jordan's is the actors,
and he says nothing here.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.config import get_settings

PROJECT = {
    "client_slug": "notify-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "review_gates": True,
    "slack_channel": "",
}

SLUG = "notify-test"


@pytest.fixture(autouse=True)
def clean():
    """Unlink this test's project database before and after each test, not just
    the settings cache - a leftover DB from a previous run leaves stale
    stakeholders behind and lets the next run pass for the wrong reason."""
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _set_dev_mode(slug: str, value: bool) -> None:
    """dev_mode lives inside config_json, not as a column on projects."""
    import json
    from api.database import get_connection, fetch_project
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        config = json.loads(project.get("config_json") or "{}")
        config["dev_mode"] = value
        await conn.execute(
            "UPDATE projects SET config_json=? WHERE slug=?", (json.dumps(config), slug)
        )
        await conn.commit()


async def _add_stakeholder(
    slug: str, name: str, email: str, *, approver: bool, reviewer: bool | None = None
) -> None:
    """Set the review flags directly via the database.

    `StakeholderIn` (`api/routers/stakeholders.py:45-46`) does declare is_reviewer and
    is_approver, so posting through the endpoint would work too - but going straight to
    the database keeps this a unit test of commit_notify_service, not of the
    stakeholders endpoint's auth and validation.

    `reviewer` defaults to `approver` - every pre-existing call site relies on that, since
    this file previously only ever produced stakeholders that were both flags or neither.
    notify_crew_failed's tests need one that is_approver but explicitly not is_reviewer,
    to prove a governance role alone does not admit someone to a reviewers-only broadcast -
    hence the override.
    """
    if reviewer is None:
        reviewer = approver
    from api.database import get_connection, fetch_project
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        await conn.execute(
            "INSERT INTO stakeholders (project_id, name, email, project_role, "
            "is_reviewer, is_approver) VALUES (?,?,?,?,?,?)",
            (project["id"], name, email, "governing" if approver else "actor",
             int(reviewer), int(approver)),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_notification_goes_to_reviewers_and_approvers_only(client, monkeypatch):
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder("notify-test", "Gov", "gov@example.com", approver=True)
    await _add_stakeholder("notify-test", "Actor", "actor@example.com", approver=False)
    # dev_mode defaults to on, which would redirect everything to one address and hide
    # the very filtering this test exists to check.
    await _set_dev_mode("notify-test", False)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch(
        "api.services.commit_notify_service.send_project_mail", AsyncMock()
    ) as send:
        await notify_crew_awaiting_commit("notify-test", "discovery_mapping")

    assert send.await_count == 1
    recipients = send.await_args.kwargs["to"]
    assert "actor@example.com" not in recipients


@pytest.mark.asyncio
async def test_a_run_that_wrote_nothing_is_not_announced_as_ready_to_commit(client):
    """The subject and the body must not claim output that does not exist.

    Run 36 of sp-gs-am finished in 50 seconds with coverage already complete and nothing
    sent back to the agent, wrote no `agent_outputs` row at all, and this notifier still
    said its output was "waiting to be committed". A reviewer who opens the dashboard and
    finds nothing learns to discount the notification - and it is the one that matters
    they will then ignore.
    """
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder("notify-test", "Gov", "gov@example.com", approver=True)
    await _set_dev_mode("notify-test", False)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch(
        "api.services.commit_notify_service.send_project_mail", AsyncMock()
    ) as send:
        await notify_crew_awaiting_commit("notify-test", "assessment_design", outputs_written=0)

    assert send.await_count == 1
    subject = send.await_args.kwargs["subject"]
    body = send.await_args.kwargs["body"]
    assert "nothing to commit" in subject
    assert "ready to commit" not in subject
    # The body carries the claim the subject summarises; a fix to one and not the other
    # leaves the notification contradicting itself.
    assert "wrote no new output" in body
    # The *positive* claim, not the bare phrase: the correct message says "so nothing is
    # waiting to be committed", which contains the phrase while denying it. Asserting the
    # fragment made this test fail against working code - the refusal-quotes-its-own-key
    # shape CLAUDE.md records, committed here by the author of this test.
    assert "its output is waiting to be committed" not in body


@pytest.mark.asyncio
async def test_a_run_that_wrote_something_still_says_ready_to_commit(client):
    """The control. Without it, refusing to announce anything would pass the test above."""
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder("notify-test", "Gov", "gov@example.com", approver=True)
    await _set_dev_mode("notify-test", False)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch(
        "api.services.commit_notify_service.send_project_mail", AsyncMock()
    ) as send:
        await notify_crew_awaiting_commit("notify-test", "assessment_design", outputs_written=3)

    assert "is ready to commit" in send.await_args.kwargs["subject"]
    assert "waiting to be committed" in send.await_args.kwargs["body"]


@pytest.mark.asyncio
async def test_a_caller_that_does_not_count_still_over_reports(client):
    """`None` is "I did not count", and must keep the original sentence.

    A new dispatcher that forgets the argument should over-report rather than fall silent -
    an unnecessary trip to the dashboard costs less than a completion nobody hears about.
    """
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder("notify-test", "Gov", "gov@example.com", approver=True)
    await _set_dev_mode("notify-test", False)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch(
        "api.services.commit_notify_service.send_project_mail", AsyncMock()
    ) as send:
        await notify_crew_awaiting_commit("notify-test", "assessment_design")

    assert "is ready to commit" in send.await_args.kwargs["subject"]


@pytest.mark.asyncio
async def test_the_dispatcher_counts_what_the_run_wrote_and_passes_it_on(client):
    """The wiring, not the sentence.

    The notifier tests above pass `outputs_written` by hand, so they hold with a dispatcher
    that never counts - hard-coding it to 99 left the whole suite green at 2365 when this
    test did not exist. What must be asserted is that the number reaching the notifier is
    the number of rows the run actually wrote.

    `build_and_run_crew` is stubbed rather than run: this asserts the bookkeeping around a
    run, and a real crew would spend money to prove nothing extra.
    """
    from unittest.mock import ANY

    await client.post("/projects", json=PROJECT)
    await _add_stakeholder("notify-test", "Gov", "gov@example.com", approver=True)
    await _set_dev_mode("notify-test", False)

    from api.database import get_connection, fetch_project, insert_agent_output
    from api.services import run_service

    async with get_connection("notify-test") as conn:
        project = await fetch_project(conn, slug="notify-test")
        run_id = (await (await conn.execute(
            "INSERT INTO crew_runs (project_id, crew_name, status) VALUES (?,?,?) RETURNING id",
            (project["id"], "assessment_design", "running"),
        )).fetchone())[0]
        await conn.commit()

    # A run that writes nothing.
    with patch.object(run_service, "build_and_run_crew", AsyncMock(return_value=None)), \
         patch("api.services.commit_notify_service.notify_crew_awaiting_commit",
               AsyncMock()) as notify:
        await run_service.dispatch_crew("notify-test", "assessment_design", run_id)
    assert notify.await_args.kwargs["outputs_written"] == 0

    # A run that writes two, counted from the same high-water mark.
    async def _write_two(slug, crew_name, rid):
        async with get_connection(slug) as conn:
            for n in ("a", "b"):
                await insert_agent_output(
                    conn, project_id=project["id"], agent_name="interaction_designer",
                    output_type=f"probe_{n}", file_path=f"/tmp/{n}.json", version=1,
                )

    with patch.object(run_service, "build_and_run_crew", AsyncMock(side_effect=_write_two)), \
         patch("api.services.commit_notify_service.notify_crew_awaiting_commit",
               AsyncMock()) as notify:
        await run_service.dispatch_crew("notify-test", "assessment_design", run_id)
    assert notify.await_args.kwargs["outputs_written"] == 2


@pytest.mark.asyncio
async def test_a_failing_send_does_not_raise(client):
    """The outputs are the durable record; the email is a notification.

    A reviewer/approver stakeholder is required here - with no recipients,
    resolve_recipients returns an empty actual list and notify_crew_awaiting_commit
    returns before _send_email is ever called, so the mocked failure would never be
    exercised and the test would prove nothing about the guard.
    """
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder("notify-test", "Gov", "gov@example.com", approver=True)
    await _set_dev_mode("notify-test", False)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch(
        "api.services.commit_notify_service.send_project_mail",
        AsyncMock(side_effect=RuntimeError("resend is down")),
    ) as send:
        await notify_crew_awaiting_commit("notify-test", "discovery_mapping")

    assert send.await_count == 1


@pytest.mark.asyncio
async def test_no_recipients_sends_nothing(client):
    await client.post("/projects", json=PROJECT)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch(
        "api.services.commit_notify_service.send_project_mail", AsyncMock()
    ) as send:
        await notify_crew_awaiting_commit("notify-test", "discovery_mapping")

    assert send.await_count == 0


@pytest.mark.asyncio
async def test_a_failed_run_notifies_reviewers_and_whoever_triggered_it(client):
    await client.post("/projects", json=PROJECT)
    # A reviewer, so "reviewers are notified always" has someone to prove itself against.
    # triggered_by below is a bare address, not a stakeholder - proving the addition does
    # not require project membership.
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_failed

    with patch("api.services.commit_notify_service.send_project_mail", AsyncMock()) as send:
        await notify_crew_failed(SLUG, "assessment_design", triggered_by="gov@example.com")

    recipients = send.await_args.kwargs["to"]
    assert "actor@example.com" in recipients
    assert "gov@example.com" in recipients


@pytest.mark.asyncio
async def test_a_failed_run_with_no_trigger_notifies_reviewers_only(client):
    """A manually started run has nobody who triggered it - reviewers still need to know.
    gov@example.com is deliberately added as an approver (but not a reviewer) here, so the
    assertion proves the address is absent because nothing named it and it holds no
    reviewer flag, not because nobody was in the project."""
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=True)
    await _add_stakeholder(SLUG, "Gov", "gov@example.com", approver=True, reviewer=False)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_failed

    with patch("api.services.commit_notify_service.send_project_mail", AsyncMock()) as send:
        await notify_crew_failed(SLUG, "assessment_design", triggered_by=None)

    recipients = send.await_args.kwargs["to"]
    assert "actor@example.com" in recipients
    assert "gov@example.com" not in recipients


@pytest.mark.asyncio
async def test_a_triggered_by_that_is_not_an_address_does_not_cost_reviewers_their_notice(
    client,
):
    """The only production caller passes the JWT's `sub`, which is a username.

    Resend rejects a request whose `to` list holds a malformed entry, so a username
    reaching the recipient list loses everyone their notification, not just the person
    it names. The extra recipient is dropped instead.
    """
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_failed

    with patch("api.services.commit_notify_service.send_project_mail", AsyncMock()) as send:
        await notify_crew_failed(SLUG, "assessment_design", triggered_by="admin")

    assert send.await_count == 1
    recipients = send.await_args.kwargs["to"]
    assert "actor@example.com" in recipients
    assert "admin" not in recipients


@pytest.mark.asyncio
async def test_a_failing_send_does_not_mask_the_run_failure(client):
    """dispatch_crew re-raises the original exception after calling this. If notification
    raised, a mail error would replace the real run error."""
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=False)

    from api.services.commit_notify_service import notify_crew_failed

    with patch(
        "api.services.commit_notify_service.send_project_mail",
        AsyncMock(side_effect=RuntimeError("resend down")),
    ) as send:
        await notify_crew_failed(SLUG, "assessment_design", triggered_by="gov@example.com")

    # No exception escaping is the assertion - but it holds vacuously unless the send was
    # actually attempted, as it would be if the audience resolved to nobody.
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_the_notification_links_to_the_crew_it_is_about(client):
    """Three notices are built at three call sites, so the crew is asserted per notice
    rather than once - a link carrying the wrong crew is worse than one carrying none.

    The whole path is asserted, not the query string in pieces: a regression to
    /{slug}/reviews?crew=...&tab=output carries both parameters and would satisfy a pair of
    substring checks while landing the reader on the review queue instead of the agent.

    approver=True here (not False): notify_crew_awaiting_commit's audience is
    is_reviewer, falling back to is_approver only when there is no reviewer at all. A
    stakeholder created with approver=False is neither (reviewer defaults to approver -
    see _add_stakeholder's docstring), so _send_email would never be reached and the
    assertions below would never run."""
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch("api.services.commit_notify_service.send_project_mail", AsyncMock()) as send:
        await notify_crew_awaiting_commit(SLUG, "assessment_design")

    body = send.await_args.kwargs["body"]
    assert f"/dashboard/{SLUG}?crew=assessment_design&tab=output" in body


@pytest.mark.asyncio
async def test_the_approval_notification_links_to_the_crew_it_is_about(client):
    """Same claim as above, for notify_crew_ready_for_approval's own call site - a separate
    _notify() invocation with its own link construction in scope."""
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Gov", "gov@example.com", approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_ready_for_approval

    with patch("api.services.commit_notify_service.send_project_mail", AsyncMock()) as send:
        await notify_crew_ready_for_approval(SLUG, "stakeholder_management")

    body = send.await_args.kwargs["body"]
    assert f"/dashboard/{SLUG}?crew=stakeholder_management&tab=output" in body


@pytest.mark.asyncio
async def test_the_failure_notification_links_to_the_crew_it_is_about(client):
    """Same claim again, for notify_crew_failed's call site - reviewers reading a failure
    notice need to land on the crew that failed, not a generic reviews list."""
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_failed

    with patch("api.services.commit_notify_service.send_project_mail", AsyncMock()) as send:
        await notify_crew_failed(SLUG, "discovery_interviews", triggered_by=None)

    body = send.await_args.kwargs["body"]
    assert f"/dashboard/{SLUG}?crew=discovery_interviews&tab=output" in body


@pytest.mark.asyncio
async def test_a_successful_run_still_sends_the_completion_notice_not_a_failure_one(client):
    await client.post("/projects", json=PROJECT)
    # A reviewer, so the completion notice actually has a recipient to inspect.
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch("api.services.commit_notify_service.send_project_mail", AsyncMock()) as send:
        await notify_crew_awaiting_commit(SLUG, "assessment_design")

    assert "failed" not in send.await_args.kwargs["subject"].lower()
    subject = send.await_args.kwargs["subject"].lower()
    # Names the commit queue, not the review one. "ready for review" sent people to the
    # HITL review queue, which has been empty for these crews since they stopped blocking
    # for a typed approval - the body always said "waiting to be committed" and the subject
    # contradicted it.
    assert "ready to commit" in subject
    assert "review" not in subject
