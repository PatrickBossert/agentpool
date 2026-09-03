"""The value chain node ledger: one row per node id, append-only on the anchor.

The script ledger already does this for interview scripts, and the reason transfers whole -
a reviewer sends SC-014 back and the next run regenerates that one script, leaving the other
85 byte-identical, because a script is a row with its own review state. Alex's value chain is
one artefact holding 89 activities, so there was no way to send back node 3.3.3 alone.

Every write test here drives a real door - SQLiteStateTool or DeriveRegistryTool - rather
than calling the upsert directly, wherever the property is about the door. A registration
path the write does not reach is the exact defect this line of work exists to remove: run 32
wrote 41 scripts, hit CrewAI's iteration ceiling before its ledger write, and reported
completed with 41 ids outside the guarantee.
"""
import asyncio
import contextlib
import json
import sqlite3

import pytest

from agents.tools._db import current_node_ledger_sync, register_nodes_sync
from agents.tools.derive_registry import DeriveRegistryTool
from agents.tools.sqlite_state import SQLiteStateTool


@pytest.fixture
def node_project(tmp_path, monkeypatch):
    """An isolated project with a projects row and an outputs directory, and nothing else."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from api.config import get_settings
    get_settings.cache_clear()
    slug = "node-ledger-test"
    (tmp_path / "db").mkdir(parents=True, exist_ok=True)
    (tmp_path / "projects" / slug / "outputs").mkdir(parents=True, exist_ok=True)

    from api.database import get_connection

    async def _init():
        async with get_connection(slug) as conn:
            await conn.execute("INSERT INTO projects (slug) VALUES (?)", (slug,))
            await conn.commit()
    asyncio.run(_init())
    yield slug
    get_settings.cache_clear()


def _node(node_id, label, level="L3", active=True):
    return {"id": node_id, "label": label, "level": level, "active": active}


def _outputs(slug):
    from pathlib import Path
    from api.config import get_settings
    return Path(get_settings().projects_dir) / slug / "outputs"


# --------------------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_ledger_table_exists_with_node_id_as_primary_key(tmp_path, monkeypatch):
    """node_id as a PRIMARY KEY is the point: one id means one activity for the life of the
    project, enforced by the database rather than by an instruction an agent must remember."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.database import get_connection
        async with get_connection("vc-ledger-shape") as conn:
            cur = await conn.execute("PRAGMA table_info(value_chain_ledger)")
            cols = {r[1]: r for r in await cur.fetchall()}
            assert "node_id" in cols, "table missing"
            assert cols["node_id"][5] == 1, "node_id must be the primary key"
            for name in ("project_id", "label", "level", "active", "review_status",
                         "review_return_to", "last_version", "last_author",
                         "created_at", "updated_at"):
                assert name in cols, f"missing column {name}"
            # label carries NOT NULL with no default. That is what turns a null label into
            # a raise rather than a silently stored empty string - see
            # test_a_null_label_raises_rather_than_being_dropped_from_the_batch.
            assert cols["label"][3] == 1, "label must be NOT NULL"

            # project_id carries a foreign key to projects(id), and get_connection turns
            # PRAGMA foreign_keys on for every connection - insert the parent row first or
            # the first ledger insert fails on the FK, never reaching the PK check this
            # test exists to prove.
            await conn.execute("INSERT INTO projects (slug) VALUES ('vc-ledger-shape')")
            await conn.commit()
            await conn.execute(
                "INSERT INTO value_chain_ledger (node_id, project_id, label)"
                " VALUES ('3.3.3', 1, 'Original')")
            await conn.commit()
            # sqlite3.IntegrityError specifically, not Exception: a bare Exception would
            # pass on a typo in the SQL above and prove nothing about the primary key.
            with pytest.raises(sqlite3.IntegrityError):
                await conn.execute(
                    "INSERT INTO value_chain_ledger (node_id, project_id, label)"
                    " VALUES ('3.3.3', 1, 'Rewritten')")
                await conn.commit()
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_database_at_the_previous_version_gains_the_value_chain_ledger(
    tmp_path, monkeypatch
):
    """The migration must reach databases that already exist, which is what the
    _SCHEMA_VERSION bump buys. Without the bump this passes on a fresh file and the table
    never appears on any deployment that has been opened once - no error, no warning.

    Fails on _SCHEMA_VERSION = 14 and passes on 15.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        import aiosqlite
        from api.database import get_connection, get_db_path, _MIGRATED

        slug = "vc-ledger-upgrade"
        async with get_connection(slug) as conn:
            await conn.execute("DROP TABLE IF EXISTS value_chain_ledger")
            await conn.commit()
        # Stamp the file back to the previous version and drop the process-local record,
        # standing in for the real case: a database migrated before this branch existed.
        _MIGRATED.discard(slug)
        async with aiosqlite.connect(get_db_path(slug)) as raw:
            await raw.execute("PRAGMA user_version = 14")
            await raw.commit()

        async with get_connection(slug) as conn:
            cur = await conn.execute("PRAGMA table_info(value_chain_ledger)")
            cols = {r[1] for r in await cur.fetchall()}
        assert "node_id" in cols, "the migration did not reach an existing database"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_migration_leaves_a_table_it_already_finds_alone(tmp_path, monkeypatch):
    """PRAGMA table_info first, and an early return: the migration skips itself rather than
    half-altering a table that is already there in some other shape. A migration that raises
    takes every later migration in the block down with it."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        import aiosqlite
        from api.database import _migrate_value_chain_ledger

        async with aiosqlite.connect(tmp_path / "hand-built.db") as conn:
            conn.row_factory = aiosqlite.Row
            # No projects table at all, and a value_chain_ledger of the wrong shape - the
            # hand-built fixture case the block has to survive.
            await conn.execute(
                "CREATE TABLE value_chain_ledger (node_id TEXT PRIMARY KEY, whatever TEXT)")
            await conn.commit()
            await _migrate_value_chain_ledger(conn)   # must not raise
            cur = await conn.execute("PRAGMA table_info(value_chain_ledger)")
            cols = {r["name"] for r in await cur.fetchall()}
        assert cols == {"node_id", "whatever"}, "the migration touched a table it found"
    finally:
        get_settings.cache_clear()


# --------------------------------------------------------------------------------------
# register_nodes_sync
# --------------------------------------------------------------------------------------

def test_registering_an_existing_node_never_moves_its_label(node_project):
    """The plan's own test, and the whole succession rule in one assertion.

    Alex rebuilds the entire chain and re-emits every label on every run - one run produced
    59 label changes, not one of them a redefinition - so a rebuild must not be able to
    rewrite the ledger as a side effect of running.
    """
    slug = node_project
    register_nodes_sync(slug, [_node("3.3.3", "Original")], 1, "alex")
    register_nodes_sync(slug, [_node("3.3.3", "Rewritten")], 2, "alex")
    assert current_node_ledger_sync(slug)["3.3.3"]["label"] == "Original"


def test_registering_returns_how_many_ids_were_added(node_project):
    """The count is the added ones, never the named ones - it is what a caller reports and
    what the backfill's own report is built from."""
    slug = node_project
    assert register_nodes_sync(slug, [_node("1", "One"), _node("2", "Two")], 1, "alex") == 2
    assert register_nodes_sync(slug, [_node("2", "Two"), _node("3", "Three")], 2, "alex") == 1
    assert set(current_node_ledger_sync(slug)) == {"1", "2", "3"}


def test_a_null_label_raises_rather_than_being_dropped_from_the_batch(node_project):
    """ON CONFLICT(node_id) DO NOTHING, never INSERT OR IGNORE.

    INSERT OR IGNORE swallows every constraint violation on the row, not only the key
    conflict it is reached for. This is the difference asserted directly: with it, the null
    label below would vanish with no error, no row, and no signal - and the next write would
    find '9.9' unregistered and free to re-anchor. The batchmate assertion is the other half
    of the same clause: one commit for the whole call, so a batch that raises registers none
    of its members and the caller has to say so rather than assume a partial success.
    """
    slug = node_project
    with pytest.raises(sqlite3.IntegrityError):
        register_nodes_sync(
            slug, [_node("9.8", "Fine"), {"id": "9.9", "label": None}], 1, "alex"
        )
    ledger = current_node_ledger_sync(slug)
    assert "9.9" not in ledger, "a null label was stored - the NOT NULL is not doing its job"
    assert "9.8" not in ledger, "the batch committed partially"


def test_an_entry_with_no_usable_id_is_skipped_not_raised_on(node_project):
    """The artefact's own validators refuse a malformed id at the door; a ledger write is not
    the place to re-adjudicate the artefact's shape, and raising here would cost the whole
    batch over an entry nothing can register anyway."""
    slug = node_project
    added = register_nodes_sync(
        slug,
        [{"label": "no id"}, {"id": "", "label": "blank"}, {"id": 3, "label": "int"},
         "not a dict", _node("4.1", "Real")],
        1, "alex",
    )
    assert added == 1
    assert set(current_node_ledger_sync(slug)) == {"4.1"}


def test_an_empty_label_is_filled_but_a_real_one_is_never_overwritten(node_project):
    """A label is display text; the anchor is the contract. The same asymmetry the script
    ledger's node_label CASE carries, and for the same reason - a row that arrived with no
    label (the backfill's case) can acquire one, and a row that has one keeps it."""
    slug = node_project
    register_nodes_sync(slug, [{"id": "5.1", "label": ""}, _node("5.2", "Held")], 1, "alex")
    register_nodes_sync(slug, [_node("5.1", "Filled in"), _node("5.2", "Rewritten")], 2, "alex")
    ledger = current_node_ledger_sync(slug)
    assert ledger["5.1"]["label"] == "Filled in"
    assert ledger["5.2"]["label"] == "Held"


def test_active_is_the_one_field_a_later_write_may_move(node_project):
    """Retiring an id and un-retiring it are neither redefining it nor dropping it - the one
    exception the succession rule carves out. An entry that does not name active leaves the
    held value alone, which is a different thing from naming it false."""
    slug = node_project
    register_nodes_sync(slug, [_node("6.1", "Retire me")], 1, "alex")
    register_nodes_sync(slug, [_node("6.1", "Retire me", active=False)], 2, "alex")
    assert current_node_ledger_sync(slug)["6.1"]["active"] is False

    register_nodes_sync(slug, [{"id": "6.1", "label": "Retire me"}], 3, "alex")
    assert current_node_ledger_sync(slug)["6.1"]["active"] is False, \
        "an entry that does not name active moved it"

    register_nodes_sync(slug, [_node("6.1", "Retire me", active=True)], 4, "alex")
    assert current_node_ledger_sync(slug)["6.1"]["active"] is True


def test_the_version_and_author_of_the_last_write_are_recorded(node_project):
    """last_version and last_author are stamped on every id the call names, held or fresh -
    the staleness signal a per-node review loop reads to tell "the reviewer has seen this
    version" from "the agent has written since"."""
    slug = node_project
    register_nodes_sync(slug, [_node("7.1", "One")], 3, "alex")
    register_nodes_sync(slug, [_node("7.1", "One"), _node("7.2", "Two")], 4, "morgan")
    ledger = current_node_ledger_sync(slug)
    assert (ledger["7.1"]["last_version"], ledger["7.1"]["last_author"]) == (4, "morgan")
    assert (ledger["7.2"]["last_version"], ledger["7.2"]["last_author"]) == (4, "morgan")


def test_a_fresh_row_starts_pending_with_no_return_to(node_project):
    """The review state Tasks 3 and 4 build on. A node nobody has looked at is pending, not
    approved - the default must not be the permissive one."""
    slug = node_project
    register_nodes_sync(slug, [_node("8.1", "One")], 1, "alex")
    row = current_node_ledger_sync(slug)["8.1"]
    assert row["review_status"] == "pending"
    assert row["review_return_to"] is None


def test_registering_against_an_unknown_slug_refuses_without_creating_a_database(
    node_project
):
    """A project id resolved to None would write rows attributed to nothing - and the
    refusal must not itself materialise the database it is denying. sqlite3.connect creates
    the file it is pointed at, so a projects-row check alone answers "Project not found"
    having just left an empty .db behind for every slug anybody names."""
    from pathlib import Path
    from api.config import get_settings
    created = Path(get_settings().database_dir) / "no-such-project.db"
    with pytest.raises(ValueError, match="Project not found"):
        register_nodes_sync("no-such-project", [_node("1", "One")], 1, "alex")
    assert not created.exists(), "the refusal materialised a database"


# --------------------------------------------------------------------------------------
# The two doors
# --------------------------------------------------------------------------------------

def test_a_registry_write_through_the_state_tool_registers_its_nodes(node_project):
    """SQLiteStateTool is Alex's own door onto value_chain_registry, and he can write it
    without deriving. Driven through the real write, not by calling the upsert."""
    slug = node_project
    tool = SQLiteStateTool(slug=slug, agent_name="value_chain_mapper", run_id=1)
    out = tool._run(
        operation="write", key="value_chain_registry", agent_name="value_chain_mapper",
        value=json.dumps({"activities": [
            _node("0", "Organisation", level="L0"),
            _node("1", "Property", level="L1"),
        ]}),
    )
    assert out.startswith("Written to"), out
    assert "WARNING" not in out, out
    ledger = current_node_ledger_sync(slug)
    assert {k: v["label"] for k, v in ledger.items()} == {
        "0": "Organisation", "1": "Property",
    }


def test_a_second_registry_write_registers_only_the_new_ids(node_project):
    """A run can stop at any point, so every write must leave everything assigned so far
    registered - and must leave the ids it already holds exactly where they are."""
    slug = node_project
    tool = SQLiteStateTool(slug=slug, agent_name="value_chain_mapper", run_id=1)
    tool._run(operation="write", key="value_chain_registry", agent_name="value_chain_mapper",
              value=json.dumps({"activities": [_node("0", "Organisation", level="L0")]}))
    tool._run(operation="write", key="value_chain_registry", agent_name="value_chain_mapper",
              value=json.dumps({"activities": [
                  _node("0", "Renamed", level="L0"),
                  _node("1", "Property", level="L1"),
              ]}))
    ledger = current_node_ledger_sync(slug)
    assert {k: v["label"] for k, v in ledger.items()} == {
        "0": "Organisation", "1": "Property",
    }


def test_deriving_the_registry_registers_its_nodes(node_project):
    """DeriveRegistryTool is the registry's other door and writes through
    insert_agent_output_sync rather than SQLiteStateTool, so a registration wired only into
    the state tool would never see a derivation - which is how the tree is normally built."""
    slug = node_project
    outputs = _outputs(slug)
    tree = [{"id": "0", "label": "Organisation", "level": "L0", "children": [
        {"id": "1", "label": "Property", "level": "L1", "children": [
            {"id": "1.1", "label": "Works Programming", "level": "L2", "children": []},
        ]},
    ]}]
    (outputs / "value_chain_tree.json").write_text(json.dumps(tree))
    from agents.tools._db import insert_agent_output_sync
    insert_agent_output_sync(slug=slug, agent_name="value_chain_mapper",
                             output_type="value_chain_tree",
                             file_path=str(outputs / "value_chain_tree.json"))

    out = DeriveRegistryTool(slug=slug)._run(agent_name="value_chain_mapper")
    assert out.startswith("Registry derived"), out
    assert "WARNING" not in out, out
    ledger = current_node_ledger_sync(slug)
    assert {k: v["label"] for k, v in ledger.items()} == {
        "0": "Organisation", "1": "Property", "1.1": "Works Programming",
    }
    assert ledger["1.1"]["level"] == "L2"


def test_a_derivation_that_drops_a_node_retires_its_ledger_row(node_project):
    """The registry preserves a dropped id as active=false rather than forgetting it, and
    the ledger has to follow - a retired row is still the anchor every theme, requirement
    and script citing that id resolves through."""
    slug = node_project
    outputs = _outputs(slug)
    from agents.tools._db import insert_agent_output_sync

    def _derive(tree):
        (outputs / "value_chain_tree.json").write_text(json.dumps(tree))
        insert_agent_output_sync(slug=slug, agent_name="value_chain_mapper",
                                 output_type="value_chain_tree",
                                 file_path=str(outputs / "value_chain_tree.json"))
        return DeriveRegistryTool(slug=slug)._run(agent_name="value_chain_mapper")

    _derive([{"id": "0", "label": "Organisation", "level": "L0", "children": [
        {"id": "1", "label": "Property", "level": "L1", "children": []},
    ]}])
    assert current_node_ledger_sync(slug)["1"]["active"] is True

    _derive([{"id": "0", "label": "Organisation", "level": "L0", "children": []}])
    ledger = current_node_ledger_sync(slug)
    assert "1" in ledger, "a dropped node was forgotten rather than retired"
    assert ledger["1"]["active"] is False


def test_a_failed_registration_is_reported_to_the_agent_not_swallowed(node_project, monkeypatch):
    """Never fail a durable write over the ledger - the file and its row are committed by
    then, and telling the agent it failed would make it write again and version a duplicate.
    But the loss must not be silent either: silence is the shape of the defect this whole
    line of work exists to close.
    """
    slug = node_project

    def _boom(*args, **kwargs):
        raise sqlite3.IntegrityError("NOT NULL constraint failed: value_chain_ledger.label")

    monkeypatch.setattr("agents.tools.sqlite_state.register_nodes_sync", _boom)
    tool = SQLiteStateTool(slug=slug, agent_name="value_chain_mapper", run_id=1)
    out = tool._run(
        operation="write", key="value_chain_registry", agent_name="value_chain_mapper",
        value=json.dumps({"activities": [_node("0", "Organisation", level="L0")]}),
    )
    assert out.startswith("Written to"), "the write was failed over the ledger"
    assert "WARNING" in out and "node ledger was not updated" in out, out
    assert current_node_ledger_sync(slug) == {}

    monkeypatch.setattr("agents.tools.derive_registry.register_nodes_sync", _boom)
    outputs = _outputs(slug)
    (outputs / "value_chain_tree.json").write_text(
        json.dumps([{"id": "0", "label": "Organisation", "level": "L0", "children": []}]))
    from agents.tools._db import insert_agent_output_sync
    insert_agent_output_sync(slug=slug, agent_name="value_chain_mapper",
                             output_type="value_chain_tree",
                             file_path=str(outputs / "value_chain_tree.json"))
    out = DeriveRegistryTool(slug=slug)._run(agent_name="value_chain_mapper")
    assert out.startswith("Registry derived"), "the derivation was failed over the ledger"
    assert "WARNING" in out and "node ledger was not updated" in out, out


# --------------------------------------------------------------------------------------
# The backfill
# --------------------------------------------------------------------------------------

def _seed_registry(slug, activities):
    from agents.tools._db import insert_agent_output_sync
    outputs = _outputs(slug)
    path = outputs / "value_chain_registry.json"
    path.write_text(json.dumps({"schema_version": 2, "activities": activities}))
    insert_agent_output_sync(slug=slug, agent_name="value_chain_mapper",
                             output_type="value_chain_registry", file_path=str(path))


def test_the_backfill_registers_the_current_registry_and_is_a_no_op_twice(node_project):
    """The 89 ids already assigned on the live project have no row, and an id outside the
    ledger is one a later write could re-anchor unrefused.

    Run twice deliberately. The second run must register nothing AND leave last_version and
    last_author where the first put them - the backfill filters to ids the ledger does not
    hold rather than relying on ON CONFLICT, because register_nodes_sync stamps the version
    on every id it is handed and a backfill has no business moving a staleness signal.
    """
    slug = node_project
    _seed_registry(slug, [
        _node("0", "Organisation", level="L0"),
        _node("1", "Property", level="L1"),
        _node("1.1", "Works Programming", level="L2", active=False),
    ])
    from scripts.backfill_value_chain_ledger import backfill_value_chain_ledger

    dry = backfill_value_chain_ledger(apply=False)
    mine = [p for p in dry["projects"] if p["slug"] == slug]
    assert len(mine) == 1, dry
    assert mine[0]["to_register"] == ["0", "1", "1.1"]
    assert mine[0]["registered"] == 0
    assert current_node_ledger_sync(slug) == {}, "a dry run wrote to the ledger"

    applied = backfill_value_chain_ledger(apply=True)
    assert [p for p in applied["projects"] if p["slug"] == slug][0]["registered"] == 3
    ledger = current_node_ledger_sync(slug)
    assert set(ledger) == {"0", "1", "1.1"}
    assert ledger["1.1"]["active"] is False, "the registry's retired entry was registered live"

    # The live write path moves the row on; the backfill must not drag it back.
    register_nodes_sync(slug, [_node("0", "Organisation", level="L0")], 9, "alex")
    again = backfill_value_chain_ledger(apply=True)
    entry = [p for p in again["projects"] if p["slug"] == slug][0]
    assert entry["to_register"] == []
    assert entry["registered"] == 0
    row = current_node_ledger_sync(slug)["0"]
    assert (row["last_version"], row["last_author"]) == (9, "alex")


def test_the_backfill_skips_a_database_that_is_not_a_project(node_project):
    """get_connection migrates any slug it is handed, so a backfill that walked data/ through
    it would create databases for slugs that are not projects. Everything here is opened
    read-only, and a file that does not claim its own filename as a project is skipped."""
    from pathlib import Path
    from api.config import get_settings
    database_dir = Path(get_settings().database_dir)

    # A probe-materialised shell: no projects table at all.
    with contextlib.closing(sqlite3.connect(database_dir / "probe.db")) as conn:
        conn.execute("CREATE TABLE something (x TEXT)")
        conn.commit()
    # A dated backup copy of a real project, exactly as the other scripts leave behind.
    with contextlib.closing(sqlite3.connect(database_dir / "node-ledger-test.backup.db")) as c:
        c.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT)")
        c.execute("INSERT INTO projects (slug) VALUES ('node-ledger-test')")
        c.commit()

    from scripts.backfill_value_chain_ledger import backfill_value_chain_ledger
    report = backfill_value_chain_ledger(apply=False)
    reasons = {s["file"]: s["reason"] for s in report["skipped"]}
    assert "no projects table" in reasons["probe.db"]
    assert "a copy or backup" in reasons["node-ledger-test.backup.db"]
    assert [p["slug"] for p in report["projects"]] == []


def test_the_backfill_skips_a_project_with_no_ledger_table(node_project):
    """The table arrives through the migration block. Materialising it from a script would
    put schema creation in a place that deliberately does not migrate anything."""
    from pathlib import Path
    from api.config import get_settings
    slug = node_project
    _seed_registry(slug, [_node("0", "Organisation", level="L0")])
    db = Path(get_settings().database_dir) / f"{slug}.db"
    with contextlib.closing(sqlite3.connect(db)) as conn:
        conn.execute("DROP TABLE value_chain_ledger")
        conn.commit()

    from scripts.backfill_value_chain_ledger import backfill_value_chain_ledger
    report = backfill_value_chain_ledger(apply=True)
    reasons = {s["file"]: s["reason"] for s in report["skipped"]}
    assert "no value_chain_ledger table" in reasons[f"{slug}.db"]


def test_the_backfill_reads_the_registry_the_ledger_marks_current(node_project):
    """The ledger, never the disk. latest_output_path's glob returns the highest number on
    disk, which is a different answer after a revert - and a backfill reading the wrong
    version would register ids the project has deliberately reverted away from."""
    slug = node_project
    _seed_registry(slug, [_node("0", "Organisation", level="L0")])
    _seed_registry(slug, [_node("0", "Organisation", level="L0"), _node("9", "Mistake")])

    from api.database import get_connection

    async def _revert():
        async with get_connection(slug) as conn:
            await conn.execute(
                "UPDATE agent_outputs SET is_current=(version=1)"
                " WHERE output_type='value_chain_registry'")
            await conn.commit()
    asyncio.run(_revert())

    from scripts.backfill_value_chain_ledger import backfill_value_chain_ledger
    report = backfill_value_chain_ledger(apply=False)
    entry = [p for p in report["projects"] if p["slug"] == slug][0]
    assert entry["registry_version"] == 1
    assert entry["to_register"] == ["0"], "the backfill read a superseded registry"
