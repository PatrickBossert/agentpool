# tests/test_auto_assign_anchor.py
"""Assignments follow the script's own anchor.

auto_assign keyed on node_label - the script's title - and took activity_id from whatever
assignment already existed, so the node link was whatever a human last set and a retitled
script orphaned its assignment. The script now states its anchor, so it is the authority.
"""
import json
from pathlib import Path

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import fetch_node_template_assignments, fetch_project, get_connection
from api.services.auto_assign_service import auto_assign_interview_scripts

SLUG = "anchor-test"
PROJECT = {
    "client_slug": SLUG, "llm_mode": "standard", "sector": "utilities",
    "stakeholder_groups": [], "value_stream_labels": [], "crews_enabled": ["requirements"],
    "review_gates": True, "slack_channel": "",
}
SCRIPTS = {
    "SC-001": {
        "script_id": "SC-001", "node_id": "1.2", "level": "L2", "relationship": "internal",
        "node_label": "Planned Maintenance L2 Interview", "research_brief": "b",
        "sections": [{"section_id": "S1", "title": "Opening", "questions": []}],
    },
    "SC-010": {
        "script_id": "SC-010", "node_id": "0", "level": "A", "relationship": "regulator",
        "node_label": "Internal Audit Interview", "research_brief": "b",
        "sections": [{"section_id": "S1", "title": "Governance", "questions": []}],
    },
}


@pytest_asyncio.fixture
async def project(client):
    await client.post("/projects", json=PROJECT)
    outputs = Path(get_settings().projects_dir) / SLUG / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "interview_scripts.json").write_text(json.dumps(SCRIPTS))
    return SLUG


async def _assignments() -> list[dict]:
    async with get_connection(SLUG) as conn:
        proj = await fetch_project(conn, slug=SLUG)
        return await fetch_node_template_assignments(conn, proj["id"])


@pytest.mark.asyncio
async def test_the_assignment_takes_the_node_from_the_script(project):
    await auto_assign_interview_scripts(SLUG)
    by_script = {r["script_id"]: r for r in await _assignments()}
    assert by_script["SC-001"]["activity_id"] == "1.2"


@pytest.mark.asyncio
async def test_an_external_script_is_assigned_to_the_entity(project):
    """The case that had no answer before: an auditor's script named itself and anchored to
    nothing, so it appeared in no coverage figure at all."""
    await auto_assign_interview_scripts(SLUG)
    audit = next(r for r in await _assignments() if r["script_id"] == "SC-010")
    assert audit["activity_id"] == "0"


@pytest.mark.asyncio
async def test_retitling_a_script_keeps_its_assignment(project):
    """The defect keying on node_label caused: a retitled script looked like a new node, so
    it gained a second assignment and the first was orphaned."""
    await auto_assign_interview_scripts(SLUG)

    retitled = json.loads(json.dumps(SCRIPTS))
    retitled["SC-001"]["node_label"] = "Planned Maintenance - revised title"
    outputs = Path(get_settings().projects_dir) / SLUG / "outputs"
    (outputs / "interview_scripts.json").write_text(json.dumps(retitled))
    await auto_assign_interview_scripts(SLUG)

    rows = await _assignments()
    assert len([r for r in rows if r["script_id"] == "SC-001"]) == 1
    assert next(r for r in rows if r["script_id"] == "SC-001")["node_label"] == (
        "Planned Maintenance - revised title"
    )


@pytest.mark.asyncio
async def test_retitling_a_script_reuses_its_template(project):
    """The half of the retitle defect the assignment row cannot show.

    The database upsert matches on script_id, so the assignment stays single whatever the
    in-memory cache is keyed on. The cache decides something else: whether the existing
    template is found. Keyed on the label, a retitled script misses its own template and
    publishes a second one to the shared library, leaving an orphan nobody will delete.
    """
    await auto_assign_interview_scripts(SLUG)
    before = next(r for r in await _assignments() if r["script_id"] == "SC-001")

    retitled = json.loads(json.dumps(SCRIPTS))
    retitled["SC-001"]["node_label"] = "Planned Maintenance - revised title"
    outputs = Path(get_settings().projects_dir) / SLUG / "outputs"
    (outputs / "interview_scripts.json").write_text(json.dumps(retitled))
    await auto_assign_interview_scripts(SLUG)

    after = next(r for r in await _assignments() if r["script_id"] == "SC-001")
    assert after["interview_template_id"] == before["interview_template_id"]


@pytest.mark.asyncio
async def test_a_moved_anchor_overwrites_rather_than_being_kept(project):
    """activity_id was COALESCEd, so a script that moved node kept its old anchor forever -
    the update looked as though it had applied and silently had not."""
    await auto_assign_interview_scripts(SLUG)

    moved = json.loads(json.dumps(SCRIPTS))
    moved["SC-001"]["node_id"] = "2"
    outputs = Path(get_settings().projects_dir) / SLUG / "outputs"
    (outputs / "interview_scripts.json").write_text(json.dumps(moved))
    await auto_assign_interview_scripts(SLUG)

    row = next(r for r in await _assignments() if r["script_id"] == "SC-001")
    assert row["activity_id"] == "2"


VERSIONED_SLUG = "anchor-test-versioned"
VERSIONED_PROJECT = {**PROJECT, "client_slug": VERSIONED_SLUG}


@pytest_asyncio.fixture
async def versioned_scripts_project(client):
    """A project whose only interview_scripts artefact is versioned - which is what every
    real project has, since insert_agent_output_sync renames every output it records to a
    _vN suffix and nothing is ever left at the bare interview_scripts.json path again."""
    await client.post("/projects", json=VERSIONED_PROJECT)
    from agents.tools._db import insert_agent_output_sync

    outputs = Path(get_settings().projects_dir) / VERSIONED_SLUG / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    draft = outputs / "interview_scripts.json"
    draft.write_text(json.dumps(SCRIPTS))
    insert_agent_output_sync(VERSIONED_SLUG, "interview_coordinator", "interview_scripts", str(draft))
    # Sanity: insert_agent_output_sync must actually have moved it away, or this fixture
    # would not be testing what it claims to.
    assert not draft.exists()
    return VERSIONED_SLUG


@pytest.mark.asyncio
async def test_auto_assign_finds_the_current_scripts(versioned_scripts_project):
    """It read a bare interview_scripts.json and returned 0 when absent, so assignment has
    silently done nothing since writes became versioned. A count alone would pass against a
    function that counts without writing, so this also checks the assignment landed in the
    database with the template it claims to have created."""
    slug = versioned_scripts_project
    count = await auto_assign_interview_scripts(slug)
    assert count > 0

    async with get_connection(slug) as conn:
        proj = await fetch_project(conn, slug=slug)
        rows = await fetch_node_template_assignments(conn, proj["id"])
    by_script = {r["script_id"]: r for r in rows}
    assert by_script["SC-001"]["activity_id"] == "1.2"
    assert by_script["SC-001"]["interview_template_id"] is not None
