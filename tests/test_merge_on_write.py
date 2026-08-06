"""A batch of interview scripts must accumulate, not clobber.

Run 26 wrote seven versions of interview_scripts in fifty minutes - v33 held SC-001, v39
held SC-008 - and the version marked current held one script of eighteen. Every write
succeeded; nothing was being refused. The artefact simply had no way to grow.
"""
import json
import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings
from api.database import get_connection
from agents.tools._db import latest_output_path


@pytest_asyncio.fixture
async def maya_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "merge-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    # A registry every anchor below resolves against, so an anchor check never masks a
    # merge failure.
    (outputs / "value_chain_registry.json").write_text(json.dumps({"activities": [
        {"id": "0", "level": "L0", "active": True},
        {"id": "1", "level": "L1", "active": True},
        {"id": "2", "level": "L1", "active": True},
    ]}))
    yield slug, outputs
    get_settings.cache_clear()


def _script(sid, node, level):
    return {sid: {
        "script_id": sid, "node_id": node, "level": level,
        "node_label": f"{sid} interview", "relationship": "internal",
        "sections": [{
            "section_id": "S1", "title": "Context", "discipline": "governance",
            "question_intent": "context", "elicitation": "unprompted",
            "questions": [{"id": "Q1.1", "text": "How does this work today?"}],
        }],
    }}


def _write(slug, payload):
    from agents.tools.sqlite_state import SQLiteStateTool
    return SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)._run(
        operation="write", key="interview_scripts",
        agent_name="interaction_designer", value=json.dumps(payload))


def _current(outputs):
    return json.loads(
        Path(latest_output_path(outputs / "interview_scripts.json")).read_text())


@pytest.mark.asyncio
async def test_a_second_batch_accumulates_rather_than_replacing(maya_project):
    slug, outputs = maya_project
    assert not _write(slug, _script("SC-001", "0", "L0")).startswith("Error")
    assert not _write(slug, _script("SC-002", "1", "L1")).startswith("Error")

    got = _current(outputs)
    assert sorted(got) == ["SC-001", "SC-002"], \
        f"the batch replaced instead of merging: {sorted(got)}"


@pytest.mark.asyncio
async def test_each_version_is_at_least_as_complete_as_the_one_before(maya_project):
    slug, outputs = maya_project
    sizes = []
    for sid, node, level in [("SC-001", "0", "L0"), ("SC-002", "1", "L1"),
                             ("SC-003", "2", "L1")]:
        _write(slug, _script(sid, node, level))
        sizes.append(len(_current(outputs)))
    assert sizes == [1, 2, 3], f"version history must only grow, got {sizes}"


@pytest.mark.asyncio
async def test_rewriting_a_script_replaces_that_script_only(maya_project):
    slug, outputs = maya_project
    _write(slug, _script("SC-001", "0", "L0"))
    _write(slug, _script("SC-002", "1", "L1"))

    corrected = _script("SC-001", "0", "L0")
    corrected["SC-001"]["node_label"] = "Corrected board interview"
    _write(slug, corrected)

    got = _current(outputs)
    assert sorted(got) == ["SC-001", "SC-002"]
    assert got["SC-001"]["node_label"] == "Corrected board interview"


@pytest.mark.asyncio
async def test_a_refused_batch_leaves_the_accumulated_set_intact(maya_project):
    """A bad batch must cost the batch, never the work already banked."""
    slug, outputs = maya_project
    _write(slug, _script("SC-001", "0", "L0"))
    _write(slug, _script("SC-002", "1", "L1"))

    result = _write(slug, _script("SC-003", "9.9.9", "L1"))   # anchor does not exist
    assert result.startswith("Error"), result

    got = _current(outputs)
    assert sorted(got) == ["SC-001", "SC-002"], \
        "a refusal must not disturb what was banked"


@pytest.mark.asyncio
async def test_a_key_absent_from_a_batch_is_not_a_deletion(maya_project):
    """Additive by design: retirement is expressed in the script registry's active flag,
    never by omission from a batch."""
    slug, outputs = maya_project
    _write(slug, _script("SC-001", "0", "L0"))
    _write(slug, _script("SC-002", "1", "L1"))
    assert sorted(_current(outputs)) == ["SC-001", "SC-002"]


@pytest.mark.asyncio
async def test_a_non_merging_key_still_replaces(maya_project):
    """Only the keys in _MERGE_ON_WRITE change behaviour."""
    from agents.tools.sqlite_state import _MERGE_ON_WRITE
    assert "value_chain_model" not in _MERGE_ON_WRITE
    assert "interview_scripts" in _MERGE_ON_WRITE


@pytest.mark.asyncio
async def test_the_tool_refuses_a_script_filed_at_the_wrong_altitude(maya_project):
    """One layer away from tests/test_anchor_levels.py: the validator is proved there,
    and here the tool that calls it must actually act on what it returns."""
    slug, outputs = maya_project
    result = _write(slug, _script("SC-001", "1", "L0"))   # L0 script on an L1 node
    assert result.startswith("Error"), result
    assert "altitude" in result
    assert latest_output_path(outputs / "interview_scripts.json") is None, \
        "a refused write must leave no file behind"
