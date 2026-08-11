# tests/test_coverage_validation.py
"""The contract is one interview per node, and a run that misses nodes must say so.

Maya's last run completed with sixteen scripts against eighty-nine activities and nobody
noticed for four days, because nothing stated what she owed or checked whether she delivered.
"""
import pytest

from api.services.coverage_validation import validate_node_coverage

_REGISTRY = {"activities": [
    {"id": "0",   "level": "L0", "active": True},
    {"id": "1",   "level": "L1", "active": True},
    {"id": "1.F", "level": "L1", "active": True},
    {"id": "1.2", "level": "L2", "active": True},
]}


def _script(node_id):
    return {"script_id": f"SC-{node_id}", "node_id": node_id}


def test_full_coverage_raises_nothing():
    scripts = {n: _script(n) for n in ("0", "1", "1.F", "1.2")}
    assert validate_node_coverage(scripts, _REGISTRY) == []


def test_a_missing_node_is_named():
    scripts = {n: _script(n) for n in ("0", "1", "1.F")}
    warnings = validate_node_coverage(scripts, _REGISTRY)
    assert len(warnings) == 1, "one warning, not one per missing node"
    w = warnings[0]
    assert w["code"] == "incomplete_coverage"
    assert "1.2" in w["detail"]
    assert w["measure"] == 0.75


def test_role_nodes_are_matched_on_node_id_not_level():
    """The registry files 1.F at its structural tier, L1; the script files it by perspective, F.
    Coverage matches on node_id, which is unambiguous in both artefacts, so the two level
    vocabularies cannot make a covered node read as uncovered."""
    scripts = {"SC-x": {"script_id": "SC-x", "node_id": "1.F", "level": "F"}}
    detail = validate_node_coverage(scripts, _REGISTRY)[0]["detail"]
    assert "1.F" not in detail


def test_a_retired_activity_is_not_owed_a_script():
    registry = {"activities": [
        {"id": "0", "level": "L0", "active": True},
        {"id": "9", "level": "L3", "active": False},
    ]}
    assert validate_node_coverage({"SC-1": _script("0")}, registry) == []


def test_an_empty_registry_raises_nothing():
    """A project whose value chain is not built yet owes no interviews."""
    assert validate_node_coverage({}, {"activities": []}) == []


@pytest.mark.asyncio
async def test_an_incomplete_write_records_a_warning(seeded_project):
    """Read back from validation_warnings, not from the validator's return value.

    The warning reaching the surface is the property. A warner that computes correctly and is
    never wired up looks identical from the validator's own tests.
    """
    import json
    from agents.tools.sqlite_state import SQLiteStateTool
    from api.database import get_connection, fetch_validation_warnings

    slug = seeded_project      # registry holds 1.2 and 2.7; we write a script for one
    SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=0)._run(
        operation="write", key="interview_scripts", agent_name="interaction_designer",
        value=json.dumps({"SC-001": {"script_id": "SC-001", "node_id": "1.2", "level": "L2",
                                     "relationship": "internal", "node_label": "Portfolio",
                                     "sections": []}}))

    async with get_connection(slug) as conn:
        cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (slug,))
        project_id = (await cur.fetchone())[0]
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    coverage = [r for r in rows if r["code"] == "incomplete_coverage"]
    assert len(coverage) == 1
    assert "2.7" in coverage[0]["detail"]
