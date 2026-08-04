# tests/test_milestone_completion.py
"""When a milestone was actually reached, as distinct from when it was due.

Slippage cannot be seen without both dates. The plan holds due_date; ticking a milestone
records completed_at, and the difference is what the schedule and PAM's report report.
"""
import shutil
from datetime import date
from pathlib import Path

import pytest

from api.config import get_settings

SLUG = "ms-completion-test"
PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "utilities",
    "stakeholder_groups": [],
    "value_stream_labels": [],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean():
    def wipe():
        settings = get_settings()
        Path(settings.database_dir, f"{SLUG}.db").unlink(missing_ok=True)
        proj = Path(settings.projects_dir, SLUG)
        if proj.exists():
            shutil.rmtree(proj)
    wipe()
    yield
    get_settings.cache_clear()
    wipe()


async def _milestone(client, **overrides) -> dict:
    await client.post("/projects", json=PROJECT)
    body = {"title": "Value chain approved", "due_date": "2026-08-15", **overrides}
    r = await client.post(f"/projects/{SLUG}/milestones", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.mark.asyncio
async def test_a_new_milestone_has_no_actual_date(client):
    m = await _milestone(client)
    assert m["completed_at"] is None


@pytest.mark.asyncio
async def test_ticking_a_milestone_stamps_today(client):
    m = await _milestone(client)
    r = await client.patch(f"/projects/{SLUG}/milestones/{m['id']}", json={"status": "complete"})
    assert r.status_code == 200
    assert r.json()["completed_at"] == date.today().isoformat()


@pytest.mark.asyncio
async def test_unticking_clears_the_actual_date(client):
    """An incomplete milestone has no actual date. Leaving the old one behind would show
    a completion date against something still outstanding."""
    m = await _milestone(client)
    await client.patch(f"/projects/{SLUG}/milestones/{m['id']}", json={"status": "complete"})
    r = await client.patch(f"/projects/{SLUG}/milestones/{m['id']}", json={"status": "pending"})
    assert r.json()["completed_at"] is None


@pytest.mark.asyncio
async def test_an_explicit_date_wins_over_today(client):
    """Milestones are ticked off retrospectively far more often than on the day, so the
    caller must be able to say when it actually happened."""
    m = await _milestone(client)
    r = await client.patch(
        f"/projects/{SLUG}/milestones/{m['id']}",
        json={"status": "complete", "completed_at": "2026-08-11"},
    )
    assert r.json()["completed_at"] == "2026-08-11"


@pytest.mark.asyncio
async def test_the_actual_date_can_be_corrected_without_touching_status(client):
    m = await _milestone(client)
    await client.patch(f"/projects/{SLUG}/milestones/{m['id']}", json={"status": "complete"})
    r = await client.patch(
        f"/projects/{SLUG}/milestones/{m['id']}", json={"completed_at": "2026-08-20"}
    )
    assert r.json()["completed_at"] == "2026-08-20"
    assert r.json()["status"] == "complete"


@pytest.mark.asyncio
async def test_editing_something_else_leaves_the_actual_date_alone(client):
    # completed_at is absent from most payloads, and absent must mean "unchanged" rather
    # than "clear it" - otherwise renaming a milestone would silently lose its actual date.
    m = await _milestone(client)
    await client.patch(
        f"/projects/{SLUG}/milestones/{m['id']}",
        json={"status": "complete", "completed_at": "2026-08-11"},
    )
    r = await client.patch(f"/projects/{SLUG}/milestones/{m['id']}", json={"title": "Renamed"})
    assert r.json()["title"] == "Renamed"
    assert r.json()["completed_at"] == "2026-08-11"
