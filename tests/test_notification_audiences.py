# tests/test_notification_audiences.py
"""A completed crew concerns reviewers; a submission concerns approvers.

resolve_recipients gained a flags parameter so the two crew notifications can each
narrow to their own audience, while Pamela's daily report keeps going to everyone
with a governance role (its default stays both flags).
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.config import get_settings

PROJECT = {
    "client_slug": "audience-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}

SLUG = "audience-test"


@pytest.fixture(autouse=True)
def clean():
    """Unlink this test's project database before and after each test - a leftover
    DB from a previous run leaves stale stakeholders behind and lets the next run
    pass for the wrong reason."""
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _set_dev_mode(slug: str, value: bool) -> None:
    """dev_mode lives inside config_json, not as a column on projects. Dev mode
    redirects every address to one, which would hide the filtering under test."""
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
    slug: str, name: str, email: str, *, reviewer: bool, approver: bool
) -> None:
    """Set the review flags directly in the database - a unit test of the
    notification, not of the stakeholders endpoint's auth and validation."""
    from api.database import get_connection, fetch_project
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        await conn.execute(
            "INSERT INTO stakeholders (project_id, name, email, project_role, "
            "is_reviewer, is_approver) VALUES (?,?,?,?,?,?)",
            (project["id"], name, email, "governing",
             int(reviewer), int(approver)),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_a_completed_crew_notifies_reviewers_and_not_approvers(client):
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Rev", "rev@example.com", reviewer=True, approver=False)
    await _add_stakeholder(SLUG, "App", "app@example.com", reviewer=False, approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_awaiting_commit
    with patch("api.services.commit_notify_service._send_email", AsyncMock()) as send:
        await notify_crew_awaiting_commit(SLUG, "discovery_mapping")

    assert send.await_count == 1
    to = send.await_args.kwargs["to"]
    assert "rev@example.com" in to
    assert "app@example.com" not in to


@pytest.mark.asyncio
async def test_a_submission_notifies_approvers_and_not_reviewers(client):
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Rev", "rev@example.com", reviewer=True, approver=False)
    await _add_stakeholder(SLUG, "App", "app@example.com", reviewer=False, approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_ready_for_approval
    with patch("api.services.commit_notify_service._send_email", AsyncMock()) as send:
        await notify_crew_ready_for_approval(SLUG, "discovery_mapping")

    assert send.await_count == 1
    to = send.await_args.kwargs["to"]
    assert "app@example.com" in to
    assert "rev@example.com" not in to


@pytest.mark.asyncio
async def test_somebody_who_is_both_hears_at_both_moments(client):
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "Both", "both@example.com", reviewer=True, approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import (
        notify_crew_awaiting_commit, notify_crew_ready_for_approval,
    )
    with patch("api.services.commit_notify_service._send_email", AsyncMock()) as send:
        await notify_crew_awaiting_commit(SLUG, "discovery_mapping")
        await notify_crew_ready_for_approval(SLUG, "discovery_mapping")

    assert send.await_count == 2
    assert all("both@example.com" in c.kwargs["to"] for c in send.await_args_list)


@pytest.mark.asyncio
async def test_a_submission_notification_failure_does_not_raise(client):
    await client.post("/projects", json=PROJECT)
    await _add_stakeholder(SLUG, "App", "app@example.com", reviewer=False, approver=True)
    await _set_dev_mode(SLUG, False)

    from api.services.commit_notify_service import notify_crew_ready_for_approval
    with patch(
        "api.services.commit_notify_service._send_email",
        AsyncMock(side_effect=RuntimeError("resend is down")),
    ):
        await notify_crew_ready_for_approval(SLUG, "discovery_mapping")
