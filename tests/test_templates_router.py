# tests/test_templates_router.py
import json
import pytest
import pytest_asyncio
import aiosqlite
from api.database import (
    init_system_db,
    fetch_all_templates,
    fetch_template,
    insert_template,
    update_template,
    delete_template,
)


@pytest_asyncio.fixture
async def sysdb(tmp_path):
    db_path = tmp_path / "system.db"
    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        await init_system_db(conn)
        yield conn


@pytest.mark.asyncio
async def test_insert_and_fetch_template(sysdb):
    schema = json.dumps({"sections": []})
    tid = await insert_template(sysdb, "T1", "desc", "interview", schema)
    assert tid > 0
    row = await fetch_template(sysdb, tid)
    assert row["name"] == "T1"
    assert row["type"] == "interview"
    assert row["schema_json"] == schema


@pytest.mark.asyncio
async def test_fetch_all_templates_with_filter(sysdb):
    await insert_template(sysdb, "I1", "", "interview", "{}")
    await insert_template(sysdb, "Q1", "", "questionnaire", "{}")
    all_t = await fetch_all_templates(sysdb)
    assert len(all_t) == 2
    interviews = await fetch_all_templates(sysdb, type_filter="interview")
    assert len(interviews) == 1
    assert interviews[0]["name"] == "I1"


@pytest.mark.asyncio
async def test_update_and_delete_template(sysdb):
    tid = await insert_template(sysdb, "Old", "", "questionnaire", "{}")
    await update_template(sysdb, tid, "New", "d", '{"sections":[]}')
    row = await fetch_template(sysdb, tid)
    assert row["name"] == "New"
    deleted = await delete_template(sysdb, tid)
    assert deleted is True
    assert await fetch_template(sysdb, tid) is None
