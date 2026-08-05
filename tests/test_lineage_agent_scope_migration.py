# tests/test_lineage_agent_scope_migration.py
"""run_inputs and run_documents used to be keyed by run_id alone, so link_output_sync
attached every read the whole crew run had made to a new output - including reads made by
an earlier agent in the same run for something else entirely. Fixing that requires
agent_name in the primary key.

CREATE TABLE IF NOT EXISTS in _migrate_lineage does nothing for a database that already has
these tables - which every live database does, since Task 4 shipped them. SQLite cannot
change a primary key via ALTER TABLE, so a live database needs the guarded rebuild in
_migrate_run_inputs_agent_scope. A test built against a fresh database cannot catch a
migration that only no-ops: this test reproduces the OLD shape explicitly, the way
test_crew_rename_migration.py reproduces a database written by pre-rename code.
"""
import shutil
import sqlite3
from pathlib import Path

import pytest

from api.config import get_settings
from api.database import get_connection

SLUG = "lineage-agent-scope-migration-test"


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


def _write_old_shape_db(db_path: Path) -> None:
    """run_inputs/run_documents as _migrate_lineage originally created them - keyed on
    (run_id, output_id) / (run_id, doc_id) alone, with no agent_name column at all. One row
    in each proves a rebuild carries data over rather than silently dropping it.

    The rebuilt tables keep their REFERENCES agent_outputs(id)/client_documents(id) clause,
    and this connection runs with foreign_keys=ON, so the row copied across must reference
    something real - a project, an agent_outputs row (id 42) and a client_documents row
    (id 9) are created first, mirroring what a live database would already have.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL,"
        " llm_mode TEXT, sector TEXT, config_json TEXT, status TEXT,"
        " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE agent_outputs (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL,"
        " agent_name TEXT NOT NULL, output_type TEXT NOT NULL, file_path TEXT NOT NULL,"
        " version INTEGER NOT NULL DEFAULT 1, review_status TEXT NOT NULL DEFAULT 'pending',"
        " revision_notes TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE client_documents (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL,"
        " filename TEXT NOT NULL, original_name TEXT NOT NULL, file_path TEXT NOT NULL,"
        " content_type TEXT, size_bytes INTEGER, ingested INTEGER NOT NULL DEFAULT 0,"
        " ingest_status TEXT NOT NULL DEFAULT 'pending', ingest_error TEXT,"
        " uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE run_inputs (run_id INTEGER NOT NULL, output_id INTEGER NOT NULL,"
        " PRIMARY KEY (run_id, output_id))"
    )
    conn.execute(
        "CREATE TABLE run_documents (run_id INTEGER NOT NULL, doc_id INTEGER NOT NULL,"
        " PRIMARY KEY (run_id, doc_id))"
    )
    conn.execute(
        "INSERT INTO projects (id, slug, llm_mode, status) VALUES (1,?,'standard','created')",
        (SLUG,),
    )
    conn.execute(
        "INSERT INTO agent_outputs (id, project_id, agent_name, output_type, file_path)"
        " VALUES (42,1,'value_chain_mapper','value_chain_model','x_v1.json')"
    )
    conn.execute(
        "INSERT INTO client_documents (id, project_id, filename, original_name, file_path)"
        " VALUES (9,1,'h.pdf','Annual.pdf','x')"
    )
    conn.execute("INSERT INTO run_inputs (run_id, output_id) VALUES (7, 42)")
    conn.execute("INSERT INTO run_documents (run_id, doc_id) VALUES (7, 9)")
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_the_old_two_column_shape_is_rebuilt_with_agent_name_in_the_key():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    _write_old_shape_db(db_path)

    # No explicit call: the migration runs on connection open, so simply opening is the
    # production path - just like reopening sp-gs-am.db does.
    async with get_connection(SLUG) as conn:
        async with conn.execute("PRAGMA table_info(run_inputs)") as cur:
            run_inputs_pk = {row["name"]: row["pk"] async for row in cur}
        async with conn.execute("PRAGMA table_info(run_documents)") as cur:
            run_documents_pk = {row["name"]: row["pk"] async for row in cur}
        run_inputs_rows = await conn.execute_fetchall(
            "SELECT run_id, agent_name, output_id FROM run_inputs"
        )
        run_documents_rows = await conn.execute_fetchall(
            "SELECT run_id, agent_name, doc_id FROM run_documents"
        )

    # agent_name exists AND is part of the primary key, not just a bystander column -
    # three columns keyed, not two.
    assert run_inputs_pk.get("agent_name", 0) > 0
    assert sum(1 for v in run_inputs_pk.values() if v > 0) == 3
    assert run_documents_pk.get("agent_name", 0) > 0
    assert sum(1 for v in run_documents_pk.values() if v > 0) == 3

    # The pre-existing row survived the rebuild, carried over with agent_name='' - a
    # destructive rebuild would have left these tables empty instead.
    assert [tuple(r) for r in run_inputs_rows] == [(7, "", 42)]
    assert [tuple(r) for r in run_documents_rows] == [(7, "", 9)]


@pytest.mark.asyncio
async def test_running_the_migration_twice_changes_nothing_further():
    """It runs on every connection open. A second pass over an already-migrated database
    must be a no-op, not a second rebuild that could re-lose the agent_name values just
    carried over."""
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    _write_old_shape_db(db_path)

    async with get_connection(SLUG) as conn:
        pass

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT run_id, agent_name, output_id FROM run_inputs"
        )

    assert [tuple(r) for r in rows] == [(7, "", 42)]
