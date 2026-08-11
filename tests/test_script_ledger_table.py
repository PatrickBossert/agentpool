import sqlite3
import pytest
from api.database import get_connection, fetch_project


@pytest.mark.asyncio
async def test_the_ledger_table_exists_with_script_id_as_primary_key(tmp_path, monkeypatch):
    """script_id as a PRIMARY KEY is the whole point: one id, one node, enforced by the
    database rather than by an instruction an agent has to remember."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        async with get_connection("ledger-test") as conn:
            cur = await conn.execute("PRAGMA table_info(interview_script_ledger)")
            cols = {r[1]: r for r in await cur.fetchall()}
            assert "script_id" in cols, "table missing"
            assert cols["script_id"][5] == 1, "script_id must be the primary key"
            for name in ("node_id", "active", "review_status", "reviewed_at_version",
                         "review_return_to", "last_version", "last_author"):
                assert name in cols, f"missing column {name}"

            # project_id carries a foreign key to projects(id), and get_connection turns
            # PRAGMA foreign_keys on for every connection - insert the parent row first or
            # the very first ledger insert fails on the FK, never reaching the PK check
            # this test exists to prove.
            await conn.execute("INSERT INTO projects (slug) VALUES ('ledger-test')")
            await conn.commit()
            await conn.execute(
                "INSERT INTO interview_script_ledger (script_id, project_id, node_id)"
                " VALUES ('SC-001', 1, '1.2')")
            await conn.commit()
            # sqlite3.IntegrityError specifically, not Exception: a bare Exception would
            # pass on a typo in the SQL above and prove nothing about the primary key.
            with pytest.raises(sqlite3.IntegrityError):
                await conn.execute(
                    "INSERT INTO interview_script_ledger (script_id, project_id, node_id)"
                    " VALUES ('SC-001', 1, '9.9')")
                await conn.commit()
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_backfill_loads_the_existing_json_ledger(tmp_path, monkeypatch):
    """The live project has 86 reconciled entries in interview_script_registry_v4.json.
    The table starts from those, not from zero, or every id already issued falls outside
    the guarantee the moment the artefact retires."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.services.script_ledger_backfill import backfill_script_ledger
        registry = {"scripts": [
            {"id": "SC-001", "node_id": "0", "node_label": "Organisation", "active": True},
            {"id": "SC-002", "node_id": "1", "node_label": "Property", "active": False},
        ]}
        async with get_connection("backfill-test") as conn:
            await conn.execute("INSERT INTO projects (slug) VALUES ('backfill-test')")
            await conn.commit()
            n = await backfill_script_ledger(conn, project_id=1, registry=registry)
            assert n == 2
            cur = await conn.execute(
                "SELECT script_id, node_id, active FROM interview_script_ledger ORDER BY script_id")
            rows = await cur.fetchall()
        assert [tuple(r) for r in rows] == [("SC-001", "0", 1), ("SC-002", "1", 0)]
    finally:
        get_settings.cache_clear()
