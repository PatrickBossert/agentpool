"""The Output tab must show the current artefact, not every run that ever wrote one.

list_interview_scripts globbed every interview_scripts*.json and merged them oldest-first.
That was right while Maya's set was spread across files. By 6 August it meant twenty files
spanning four runs produced six distinct L0 interviews - three of them predating node_id
and so undedupable by anything but their titles, which differed by an em dash and the word
"L0".
"""
import json
import pytest
from pathlib import Path
from api.config import get_settings


@pytest.fixture
def scripts_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    outputs = tmp_path / "projects" / "ep-test" / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    yield outputs
    get_settings.cache_clear()


def _script(label, level="L0", node="0"):
    return {"node_label": label, "level": level, "node_id": node,
            "sections": [{"section_id": "S1", "questions": []}]}


@pytest.mark.asyncio
async def test_only_the_current_version_is_returned(scripts_dir, client):
    (scripts_dir / "interview_scripts_v1.json").write_text(json.dumps({
        "GS UK Portfolio — L0 Board Interview":
            _script("GS UK Portfolio — L0 Board Interview")}))
    (scripts_dir / "interview_scripts_v15.json").write_text(json.dumps({
        "GS UK Portfolio L0 Interview": _script("GS UK Portfolio L0 Interview")}))
    (scripts_dir / "interview_scripts_v33.json").write_text(json.dumps({
        "SC-001": _script("Board and C-Suite Interview")}))

    r = await client.get("/projects/ep-test/interview-scripts")
    assert r.status_code == 200
    body = r.json()
    assert sorted(body) == ["SC-001"], f"history leaked into the current set: {sorted(body)}"


@pytest.mark.asyncio
async def test_an_empty_outputs_directory_returns_an_empty_map(scripts_dir, client):
    r = await client.get("/projects/ep-test/interview-scripts")
    assert r.status_code == 200
    assert r.json() == {}


@pytest.mark.asyncio
async def test_a_legacy_role_script_is_served_in_the_two_field_shape(scripts_dir, client):
    """The sixteen live scripts predate the level/perspective split and file the role
    letter in `level` with no `perspective` at all.

    normalise_scripts is what gives them a perspective on the way out, and this is the
    only path the Output tab reads. Nothing on disk is rewritten, so the endpoint is the
    only place the property can be asserted: reverting the call to `return deduped`
    leaves the file, the dedupe, and every other test in this module unchanged, and the
    UI silently files every role script in the wrong bucket.
    """
    (scripts_dir / "interview_scripts_v3.json").write_text(json.dumps({
        "SC-004": {"script_id": "SC-004", "node_id": "1.F", "level": "F",
                   "node_label": "Fleet Frontline Worker Interview",
                   "sections": [{"section_id": "S1", "questions": []}]},
        "SC-005": _script("Board and C-Suite Interview"),
    }))

    r = await client.get("/projects/ep-test/interview-scripts")
    assert r.status_code == 200
    body = r.json()

    role = body["SC-004"]
    assert role.get("perspective") == "F", (
        f"the role letter never reached perspective: {role.get('perspective')!r} - "
        "the Output tab splits on perspective, so this script lands in the wrong bucket"
    )
    assert role.get("level") is None, (
        f"'F' is still filed as a structural tier: {role.get('level')!r}"
    )
    # An ordinary script is untouched by the same pass - a normaliser that blanked every
    # level would satisfy the two assertions above and break every other script.
    assert body["SC-005"]["level"] == "L0"
    assert body["SC-005"].get("perspective") is None


@pytest.mark.asyncio
async def test_dedupe_still_runs_within_the_current_version(scripts_dir, client):
    """Two scripts in one artefact can still normalise to the same label, and values that
    are not interviews must still be dropped.

    The labels here differ only in punctuation and case, which _dedupe_key does collapse.
    It deliberately does NOT merge '&' with 'and' - that would silently collapse two
    interviews that are genuinely different - so a pair differing that way is not a
    duplicate and must not be used to test this.
    """
    (scripts_dir / "interview_scripts_v2.json").write_text(json.dumps({
        "SC-001": _script("Board — C-Suite Interview"),
        "SC-009": _script("board  c suite interview"),
        "not-a-script": {"test": True},
    }))
    r = await client.get("/projects/ep-test/interview-scripts")
    body = r.json()
    assert "not-a-script" not in body
    assert len(body) == 1, \
        f"duplicates within one artefact must still collapse: {sorted(body)}"
