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
    "crews_enabled": ["requirements"],
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


# ---------------------------------------------------------------------------
# Re-baselining. A change request that moves the plan is a legitimate event, so it exists -
# but as its own deliberate, approver-gated action, and never as a side effect of editing a
# date. A baseline that can be quietly overwritten is not a baseline.
# ---------------------------------------------------------------------------


async def _rebaseline(client, milestone_id: int, **body):
    return await client.post(
        f"/projects/{SLUG}/milestones/{milestone_id}/rebaseline", json=body
    )


@pytest.mark.asyncio
async def test_rebaselining_records_the_superseded_baseline(client):
    """Asserting only that the new baseline took effect proves nothing about whether the
    original survived, which is the entire reason for keeping a history."""
    await _project(client)
    m = await _milestone(client)
    await client.post(f"/projects/{SLUG}/activate")

    r = await _rebaseline(client, m["id"], baseline_date="2026-08-24", reason="CR-014 approved")
    assert r.status_code in (200, 201), r.text
    assert (await _get(client, m["id"]))["baseline_date"] == "2026-08-24"

    history = (await client.get(f"/projects/{SLUG}/milestones/{m['id']}/baselines")).json()
    assert [h["baseline_date"] for h in history] == ["2026-08-10"]
    assert history[0]["reason"] == "CR-014 approved"


@pytest.mark.asyncio
async def test_rebaselining_without_a_reason_is_refused(client):
    # A re-baseline nobody explained is indistinguishable from a mistake six months later.
    await _project(client)
    m = await _milestone(client)
    await client.post(f"/projects/{SLUG}/activate")
    r = await _rebaseline(client, m["id"], baseline_date="2026-08-24", reason="   ")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_two_rebaselines_keep_both_originals_in_order(client):
    # One entry cannot distinguish "records the superseded baseline" from "records the
    # first baseline only", and a plan that moves twice is the normal case.
    await _project(client)
    m = await _milestone(client)
    await client.post(f"/projects/{SLUG}/activate")

    await _rebaseline(client, m["id"], baseline_date="2026-08-24", reason="CR-014")
    await _rebaseline(client, m["id"], baseline_date="2026-08-31", reason="CR-021")

    history = (await client.get(f"/projects/{SLUG}/milestones/{m['id']}/baselines")).json()
    assert [h["baseline_date"] for h in history] == ["2026-08-10", "2026-08-24"]
    assert [h["reason"] for h in history] == ["CR-014", "CR-021"]
    assert (await _get(client, m["id"]))["baseline_date"] == "2026-08-31"


@pytest.mark.asyncio
async def test_rebaselining_something_never_baselined_is_refused(client):
    """There is nothing to supersede. Allowing it would let added scope acquire a promise
    retrospectively, which is how a project makes its own scope growth disappear."""
    await _project(client)
    await client.post(f"/projects/{SLUG}/activate")
    m = await _milestone(client, title="New scope", due_date="2026-09-01")
    r = await _rebaseline(client, m["id"], baseline_date="2026-09-15", reason="CR-030")
    assert r.status_code == 404
