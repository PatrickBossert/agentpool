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
    "crews_enabled": ["discovery"],
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
        "api.services.commit_notify_service._send_email", AsyncMock()
    ) as send:
        await notify_crew_awaiting_commit("notify-test", "discovery_mapping")

    assert send.await_count == 1
    recipients = send.await_args.kwargs["to"]
    assert "actor@example.com" not in recipients


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
        "api.services.commit_notify_service._send_email",
        AsyncMock(side_effect=RuntimeError("resend is down")),
    ) as send:
        await notify_crew_awaiting_commit("notify-test", "discovery_mapping")

    assert send.await_count == 1


@pytest.mark.asyncio
async def test_no_recipients_sends_nothing(client):
    await client.post("/projects", json=PROJECT)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch(
        "api.services.commit_notify_service._send_email", AsyncMock()
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

    with patch("api.services.commit_notify_service._send_email", AsyncMock()) as send:
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

    with patch("api.services.commit_notify_service._send_email", AsyncMock()) as send:
        await notify_crew_failed(SLUG, "assessment_design", triggered_by=None)

    recipients = send.await_args.kwargs["to"]
    assert "actor@example.com" in recipients
    assert "gov@example.com" not in recipients


@pytest.mark.asyncio
async def test_a_failing_send_does_not_mask_the_run_failure(client):
    """dispatch_crew re-raises the original exception after calling this. If notification
    raised, a mail error would replace the real run error."""
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=False)

    from api.services.commit_notify_service import notify_crew_failed

    with patch(
        "api.services.commit_notify_service._send_email",
        AsyncMock(side_effect=RuntimeError("resend down")),
    ):
        await notify_crew_failed(SLUG, "assessment_design", triggered_by="gov@example.com")
    # No exception escaping is the assertion.


@pytest.mark.asyncio
async def test_a_successful_run_still_sends_the_completion_notice_not_a_failure_one(client):
    await client.post("/projects", json=PROJECT)
    # A reviewer, so the completion notice actually has a recipient to inspect.
    await _add_stakeholder(SLUG, "Actor", "actor@example.com", approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch("api.services.commit_notify_service._send_email", AsyncMock()) as send:
        await notify_crew_awaiting_commit(SLUG, "assessment_design")

    assert "failed" not in send.await_args.kwargs["subject"].lower()
    assert "ready for review" in send.await_args.kwargs["subject"].lower()
