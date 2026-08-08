"""A filename family belongs to exactly one output type.

DeriveRegistryTool wrote value_chain_registry_vN.json as output_type='state' while
SQLiteStateTool wrote the same family as 'value_chain_registry'. Two writers, one family,
two types - which is why the clean-baseline prune demoted value_chain_summary v12 to v4
and value_chain_tree v13 to v9, and why 'state' could never be pruned.

This is the invariant a type-keyed resolver depends on: without it, looking up
'value_chain_registry' finds only half the rows and returns a confident wrong answer.
"""
import json
import re
import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings
from api.database import get_connection

_VERSIONED = re.compile(r"^(?P<stem>.+?)_v\d+$")


def _family(file_path: str) -> str:
    """The filename family a path belongs to: 'value_chain_registry_v5.json' -> the stem."""
    stem = Path(file_path).stem
    m = _VERSIONED.match(stem)
    return m.group("stem") if m else stem


@pytest_asyncio.fixture
async def derive_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "family-test"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
    (outputs / "value_chain_tree.json").write_text(json.dumps(
        [{"id": "0", "label": "Org", "level": "L0", "children": [
            {"id": "1", "label": "Chain", "level": "L1"}]}]))
    yield slug, outputs, tmp_path
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_derived_registry_is_recorded_as_a_registry(derive_db):
    slug, outputs, _ = derive_db
    from agents.tools.derive_registry import DeriveRegistryTool

    assert not DeriveRegistryTool(slug=slug)._run().startswith("Error")

    async with get_connection(slug) as conn:
        async with conn.execute(
            "SELECT output_type, file_path FROM agent_outputs WHERE is_current=1"
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    reg = [r for r in rows if "value_chain_registry" in r["file_path"]]
    assert reg, "no row was written for the derived registry"
    assert reg[0]["output_type"] == "value_chain_registry", \
        f"derived registry recorded as {reg[0]['output_type']!r}"


@pytest.mark.asyncio
async def test_no_filename_family_has_two_current_rows(derive_db):
    """The invariant a type-keyed resolver actually depends on.

    Scoped to is_current rows on purpose. Superseded rows legitimately carry the type they
    were written under - sp-gs-am has fifteen 'state' rows from before per-key output types
    existed, naming summary, tree and registry files - and rewriting them would be
    rewriting history to satisfy a rule none of them can break. A superseded row is never
    resolved. Two *current* rows over one family is what makes resolution ambiguous.
    """
    slug, outputs, _ = derive_db
    from agents.tools.derive_registry import DeriveRegistryTool

    DeriveRegistryTool(slug=slug)._run()

    async with get_connection(slug) as conn:
        async with conn.execute(
                "SELECT output_type, file_path FROM agent_outputs WHERE is_current=1") as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    families: dict[str, set] = {}
    for r in rows:
        families.setdefault(_family(r["file_path"]), set()).add(r["output_type"])
    split = {f: sorted(t) for f, t in families.items() if len(t) > 1}
    assert not split, f"filename families with more than one current row: {split}"


@pytest.mark.asyncio
async def test_no_output_type_has_two_current_rows(derive_db):
    """insert_agent_output_sync sweeps is_current before each insert, so this holds by
    construction. Asserted because sp-gs-am carried two current 'state' rows for months -
    the resolver picks one with ORDER BY version DESC, and picking is not resolving."""
    slug, _, _ = derive_db
    from agents.tools.derive_registry import DeriveRegistryTool

    DeriveRegistryTool(slug=slug)._run()
    DeriveRegistryTool(slug=slug)._run()

    async with get_connection(slug) as conn:
        async with conn.execute(
            "SELECT output_type, COUNT(*) n FROM agent_outputs"
            " WHERE is_current=1 GROUP BY output_type HAVING n > 1") as cur:
            dupes = [dict(r) for r in await cur.fetchall()]
    assert not dupes, f"output types with more than one current row: {dupes}"


@pytest.mark.asyncio
async def test_the_migration_retypes_existing_state_rows(derive_db):
    """A project migrated from before this change must end up with the same invariant."""
    slug, outputs, _ = derive_db
    reg_file = outputs / "value_chain_registry_v3.json"
    reg_file.write_text(json.dumps({"activities": []}))
    other = outputs / "some_other_state_v1.json"
    other.write_text("{}")

    async with get_connection(slug) as conn:
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            pid = (await cur.fetchone())[0]
        for path in (reg_file, other):
            await conn.execute(
                "INSERT INTO agent_outputs"
                " (project_id, agent_name, output_type, file_path, version, is_current)"
                " VALUES (?,?,?,?,?,1)",
                (pid, "value_chain_mapper", "state", str(path), 3))
        await conn.commit()

    # get_connection now memoises migrations per (slug, inode) for the life of the
    # process, so a reopen of the same file no longer re-runs them by itself. Forgetting
    # slug here stands in for the real scenario this migration exists for - a project
    # database from before this change, opened for the first time - since the app itself
    # never writes a 'state' row for this family into an already-migrated file.
    from api.database import _forget_migrations
    _forget_migrations(slug)

    # Reopening runs the migrations.
    async with get_connection(slug) as conn:
        async with conn.execute(
            "SELECT output_type, file_path FROM agent_outputs"
            " WHERE file_path LIKE '%value_chain_registry%'") as cur:
            retyped = [dict(r) for r in await cur.fetchall()]
        async with conn.execute(
            "SELECT output_type FROM agent_outputs"
            " WHERE file_path LIKE '%some_other_state%'") as cur:
            untouched = [dict(r) for r in await cur.fetchall()]

    assert retyped, "fixture wrote no registry row"
    assert all(r["output_type"] == "value_chain_registry" for r in retyped), retyped
    assert all(r["output_type"] == "state" for r in untouched), \
        "a state row naming something else must be left alone"
