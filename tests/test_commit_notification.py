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


async def _add_stakeholder(slug: str, name: str, email: str, *, approver: bool) -> None:
    """Set the review flags directly.

    `StakeholderIn` (`api/routers/stakeholders.py:23`) has no is_reviewer or is_approver
    fields, so posting them to the endpoint would silently drop them and every
    stakeholder would arrive with the column default of 0 - making the assertion below
    pass for the wrong reason.
    """
    from api.database import get_connection, fetch_project
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        await conn.execute(
            "INSERT INTO stakeholders (project_id, name, email, project_role, "
            "is_reviewer, is_approver) VALUES (?,?,?,?,?,?)",
            (project["id"], name, email, "governing" if approver else "actor",
             int(approver), int(approver)),
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
    """The outputs are the durable record; the email is a notification."""
    await client.post("/projects", json=PROJECT)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch(
        "api.services.commit_notify_service._send_email",
        AsyncMock(side_effect=RuntimeError("resend is down")),
    ):
        await notify_crew_awaiting_commit("notify-test", "discovery_mapping")


@pytest.mark.asyncio
async def test_no_recipients_sends_nothing(client):
    await client.post("/projects", json=PROJECT)

    from api.services.commit_notify_service import notify_crew_awaiting_commit

    with patch(
        "api.services.commit_notify_service._send_email", AsyncMock()
    ) as send:
        await notify_crew_awaiting_commit("notify-test", "discovery_mapping")

    assert send.await_count == 0
