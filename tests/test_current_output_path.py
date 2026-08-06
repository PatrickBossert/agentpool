"""The ledger decides which version is current, not the highest number on disk.

value_chain_summary v5 was written on 6 August and marked current. v9, v11 and v12 from
mid-July sat beside it, so every agent read the 15 July file - which names DXI as fleet
maintainer, three weeks after a human corrected that to Fraikin. The database was right the
whole time; nothing asked it.
"""
import json
import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, fetch_validation_warnings
from agents.tools._db import current_output_path, latest_output_path


@pytest_asyncio.fixture
async def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "ledger-test"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            pid = (await cur.fetchone())[0]

    async def add(output_type, version, current, write_file=True):
        p = outputs / f"{output_type}_v{version}.json"
        if write_file:
            p.write_text(json.dumps({"v": version}))
        async with get_connection(slug) as conn:
            await conn.execute(
                "INSERT INTO agent_outputs"
                " (project_id, agent_name, output_type, file_path, version, is_current)"
                " VALUES (?,?,?,?,?,?)",
                (pid, "value_chain_mapper", output_type, str(p), version,
                 1 if current else 0))
            await conn.commit()
        return p

    yield slug, outputs, pid, add
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_ledger_wins_over_a_higher_number_on_disk(ledger):
    """The value_chain_summary incident, as a test."""
    slug, outputs, _, add = ledger
    await add("value_chain_summary", 5, current=True)
    (outputs / "value_chain_summary_v12.json").write_text(json.dumps({"v": 12}))

    assert latest_output_path(outputs / "value_chain_summary.json").name \
        == "value_chain_summary_v12.json", "precondition: the glob prefers v12"
    resolved = current_output_path(slug, "value_chain_summary")
    assert resolved is not None and resolved.name == "value_chain_summary_v5.json"


@pytest.mark.asyncio
async def test_a_revert_is_honoured(ledger):
    """Newer files stay on disk; the ledger points at the reverted version. This is the
    case a filename-ordering scheme cannot express at all."""
    slug, outputs, _, add = ledger
    await add("value_chain_tree", 12, current=False)
    await add("value_chain_tree", 4, current=True)

    assert (outputs / "value_chain_tree_v12.json").exists()
    assert current_output_path(slug, "value_chain_tree").name == "value_chain_tree_v4.json"


@pytest.mark.asyncio
async def test_no_row_falls_back_to_the_disk_glob(ledger):
    """A first write writes and renames the file before its row exists, so this branch is
    not a nicety - without it every first write breaks."""
    slug, outputs, _, _ = ledger
    (outputs / "hand_written_v2.json").write_text("{}")
    assert current_output_path(slug, "hand_written").name == "hand_written_v2.json"


@pytest.mark.asyncio
async def test_no_row_and_no_file_is_none(ledger):
    slug, _, _, _ = ledger
    assert current_output_path(slug, "never_written") is None


@pytest.mark.asyncio
async def test_a_dangling_row_returns_none_rather_than_a_stale_file(ledger):
    """Falling through to the glob is what turns a broken pointer into a wrong answer."""
    slug, outputs, _, add = ledger
    await add("value_chain_model", 9, current=True, write_file=False)
    (outputs / "value_chain_model_v2.json").write_text(json.dumps({"v": 2}))

    assert current_output_path(slug, "value_chain_model") is None, \
        "a lost current version must not silently resolve to an older one"


@pytest.mark.asyncio
async def test_a_dangling_row_records_the_way_out(ledger):
    """A warning that says only 'file missing' leaves the reader to do the investigation
    the warning existed to save."""
    slug, outputs, pid, add = ledger
    await add("value_chain_model", 9, current=True, write_file=False)
    (outputs / "value_chain_model_v2.json").write_text("{}")
    (outputs / "value_chain_model_v7.json").write_text("{}")

    current_output_path(slug, "value_chain_model", run_id=42)

    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=pid, sources=["output_resolution"])
    assert len(rows) == 1
    w = rows[0]
    assert w["code"] == "current_file_missing"
    assert w["subject"] == "value_chain_model"
    assert w["run_id"] == 42
    assert "value_chain_model_v9.json" in w["detail"], "names the missing file"
    assert "v2" in w["detail"] and "v7" in w["detail"], \
        "names the versions still on disk, so reverting is a decision not an investigation"


@pytest.mark.asyncio
async def test_a_dangling_row_with_nothing_left_says_so(ledger):
    slug, _, pid, add = ledger
    await add("value_levers", 3, current=True, write_file=False)
    current_output_path(slug, "value_levers")
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=pid, sources=["output_resolution"])
    assert "none" in rows[0]["detail"], rows[0]["detail"]


@pytest.mark.asyncio
async def test_resolving_twice_does_not_duplicate_the_warning(ledger):
    slug, _, pid, add = ledger
    await add("value_chain_model", 9, current=True, write_file=False)
    current_output_path(slug, "value_chain_model")
    current_output_path(slug, "value_chain_model")
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(
            conn, project_id=pid, sources=["output_resolution"])
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_an_unversioned_file_is_still_found(ledger):
    """latest_output_path prefers the un-suffixed path; the fallback must keep that."""
    slug, outputs, _, _ = ledger
    (outputs / "legacy_thing.json").write_text("{}")
    assert current_output_path(slug, "legacy_thing").name == "legacy_thing.json"


@pytest.mark.asyncio
async def test_a_superseded_row_never_wins(ledger):
    """Only is_current is consulted, not the highest version in the ledger."""
    slug, outputs, _, add = ledger
    await add("value_chain_summary", 9, current=False)
    await add("value_chain_summary", 3, current=True)
    assert current_output_path(slug, "value_chain_summary").name \
        == "value_chain_summary_v3.json"
