"""Clearing the interview artefacts must be reversible, and must not touch anything else.

The last bulk operation on outputs demoted two live artefacts - value_chain_summary from
v12 to v4 and value_chain_tree from v13 to v9 - because a filename family was split across
output types. This one is narrower, but it defaults to a dry run for the same reason.
"""
import json
import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings
from api.database import get_connection

TYPES = [
    "interview_scripts", "interview_script_registry",
    "l0_interview_summaries", "l1_interview_summaries", "l2_interview_summaries",
    "customer_interview_summaries", "audit_interview_summaries",
    "frontline_interview_summaries", "corp_services_interview_summaries",
]


@pytest_asyncio.fixture
async def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "reset-test"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            pid = (await cur.fetchone())[0]
        for i, t in enumerate(TYPES, start=1):
            p = outputs / f"{t}_v{i}.json"
            p.write_text(json.dumps({"seeded": t}))
            await conn.execute(
                "INSERT INTO agent_outputs"
                " (project_id, agent_name, output_type, file_path, version, is_current)"
                " VALUES (?,?,?,?,?,1)",
                (pid, "interaction_designer", t, str(p), i))
        # A value chain output that must survive untouched.
        vc = outputs / "value_chain_tree_v1.json"
        vc.write_text(json.dumps([{"id": "0", "level": "L0"}]))
        await conn.execute(
            "INSERT INTO agent_outputs"
            " (project_id, agent_name, output_type, file_path, version, is_current)"
            " VALUES (?,?,?,?,?,1)",
            (pid, "value_chain_mapper", "value_chain_tree", str(vc), 1))
        await conn.commit()
    yield slug, outputs
    get_settings.cache_clear()


async def _interview_row_count(slug):
    async with get_connection(slug) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM agent_outputs WHERE output_type LIKE '%interview%'"
        ) as cur:
            return (await cur.fetchone())[0]


@pytest.mark.asyncio
async def test_a_dry_run_changes_nothing(seeded):
    slug, outputs = seeded
    from scripts.reset_interview_artefacts import reset_interview_artefacts

    report = reset_interview_artefacts(slug)
    assert report["rows"] == len(TYPES)
    assert report["backup_db"] is None

    assert await _interview_row_count(slug) == len(TYPES), "a dry run must not delete"
    assert (outputs / "interview_scripts_v1.json").exists()


@pytest.mark.asyncio
async def test_apply_clears_every_interview_artefact(seeded):
    slug, outputs = seeded
    from scripts.reset_interview_artefacts import reset_interview_artefacts

    report = reset_interview_artefacts(slug, apply=True)
    assert report["rows"] == len(TYPES)
    assert Path(report["backup_db"]).exists(), "apply must back the database up first"

    assert await _interview_row_count(slug) == 0
    for t in TYPES:
        assert not list(outputs.glob(f"{t}_v*.json")), f"{t} files remain"


@pytest.mark.asyncio
async def test_the_value_chain_is_left_alone(seeded):
    slug, outputs = seeded
    from scripts.reset_interview_artefacts import reset_interview_artefacts

    reset_interview_artefacts(slug, apply=True)
    assert (outputs / "value_chain_tree_v1.json").exists()
    async with get_connection(slug) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM agent_outputs WHERE output_type='value_chain_tree'"
        ) as cur:
            assert (await cur.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_files_are_archived_not_deleted(seeded):
    slug, outputs = seeded
    from scripts.reset_interview_artefacts import reset_interview_artefacts

    report = reset_interview_artefacts(slug, apply=True)
    archive = Path(report["archive"])
    assert archive.is_dir()
    assert (archive / "interview_scripts_v1.json").exists()


@pytest.mark.asyncio
async def test_interview_sessions_and_answers_are_never_touched(seeded):
    """A script is reproducible - Maya writes it again in an hour. A transcript is a thing
    a person said once, and no rerun brings it back."""
    slug, _ = seeded
    import inspect
    from scripts import reset_interview_artefacts as mod
    from scripts.reset_interview_artefacts import reset_interview_artefacts

    src = inspect.getsource(mod)
    assert "DELETE FROM interview_sessions" not in src
    assert "DELETE FROM interview_answers" not in src
    reset_interview_artefacts(slug, apply=True)
