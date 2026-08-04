# tests/test_milestone_baseline.py
"""What a milestone was promised, as distinct from what is currently planned.

due_date is editable, so re-planning after a slip overwrites the original commitment and
every comparison afterwards measures actual against the revised plan. A project that slips
four times and is re-planned four times shows as perfectly on track - each milestone met
the date it was most recently given.
"""
import shutil
from pathlib import Path

import pytest

from api.config import get_settings

SLUG = "ms-baseline-test"
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


async def _project(client) -> None:
    r = await client.post("/projects", json=PROJECT)
    assert r.status_code in (200, 201), r.text


async def _milestone(client, **overrides) -> dict:
    body = {"title": "Kickoff", "due_date": "2026-08-10", **overrides}
    r = await client.post(f"/projects/{SLUG}/milestones", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _get(client, milestone_id: int) -> dict:
    r = await client.get(f"/projects/{SLUG}/milestones")
    assert r.status_code == 200, r.text
    return next(m for m in r.json() if m["id"] == milestone_id)


@pytest.mark.asyncio
async def test_activation_baselines_a_milestone_that_has_a_due_date(client):
    await _project(client)
    m = await _milestone(client)
    await client.post(f"/projects/{SLUG}/activate")
    assert (await _get(client, m["id"]))["baseline_date"] == "2026-08-10"


@pytest.mark.asyncio
async def test_activation_leaves_an_undated_milestone_unbaselined(client):
    # A fixture where every milestone has a date cannot tell "baselines those with a date"
    # from "baselines everything". An undated milestone was never promised anything, and
    # inventing a baseline would manufacture a commitment nobody made.
    await _project(client)
    m = await _milestone(client, title="Unscheduled", due_date=None)
    await client.post(f"/projects/{SLUG}/activate")
    assert (await _get(client, m["id"]))["baseline_date"] is None


@pytest.mark.asyncio
async def test_activating_again_does_not_move_a_baseline(client):
    """Re-activating an in-flight project would otherwise adopt the slipped plan as the
    promise - the exact failure the baseline exists to prevent, arriving through the
    mechanism meant to prevent it."""
    await _project(client)
    m = await _milestone(client)
    await client.post(f"/projects/{SLUG}/activate")
    await client.patch(
        f"/projects/{SLUG}/milestones/{m['id']}", json={"due_date": "2026-08-20"}
    )
    await client.post(f"/projects/{SLUG}/activate")
    assert (await _get(client, m["id"]))["baseline_date"] == "2026-08-10"


@pytest.mark.asyncio
async def test_editing_the_plan_leaves_the_baseline_alone(client):
    # Assert the baseline explicitly. A test that only checks the new due date passes
    # while the baseline moves along with it, which is the whole defect.
    await _project(client)
    m = await _milestone(client)
    await client.post(f"/projects/{SLUG}/activate")
    r = await client.patch(
        f"/projects/{SLUG}/milestones/{m['id']}", json={"due_date": "2026-08-20"}
    )
    assert r.json()["due_date"] == "2026-08-20"
    assert r.json()["baseline_date"] == "2026-08-10"


@pytest.mark.asyncio
async def test_a_milestone_added_after_activation_has_no_baseline(client):
    """Added scope is not on-plan delivery. Treating an absent baseline as no variance
    would report scope growth as success."""
    await _project(client)
    await client.post(f"/projects/{SLUG}/activate")
    m = await _milestone(client, title="New scope", due_date="2026-09-01")
    assert (await _get(client, m["id"]))["baseline_date"] is None


@pytest.mark.asyncio
async def test_activation_reports_how_many_it_baselined(client):
    await _project(client)
    await _milestone(client)
    await _milestone(client, title="Second", due_date="2026-08-20")
    await _milestone(client, title="Undated", due_date=None)
    r = await client.post(f"/projects/{SLUG}/activate")
    assert r.json()["milestones_baselined"] == 2
