"""The count an approver sees is "has a human read this", so all three reading exits count.

Editing, sending back, and signing off each mean somebody opened the instrument and formed a
judgement. Approving does not count towards its own gate.
"""
import pytest
import pytest_asyncio
from api.database import get_connection
from api.services.script_review_service import record_script_review, review_count


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    async with get_connection("count-test") as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES ('count-test')")
        await conn.execute(
            "INSERT INTO interview_script_ledger (script_id, project_id, node_id, last_version)"
            " VALUES ('SC-001', 1, '1.2', 3)")
        await conn.commit()
        yield conn
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_all_three_reading_exits_count(project):
    for decision, kwargs in (
        ("reviewed", {}),
        ("edited", {}),
        ("changes_requested", {"return_to": "agent", "notes": "fix Q3"}),
    ):
        await record_script_review(project, project_id=1, script_id="SC-001",
                                   reviewer="ana", decision=decision, at_version=3, **kwargs)
    assert await review_count(project, project_id=1, script_id="SC-001") == 3


@pytest.mark.asyncio
async def test_approving_does_not_count_towards_its_own_gate(project):
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="ana", decision="reviewed", at_version=3)
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="ana", decision="approved", at_version=3)
    assert await review_count(project, project_id=1, script_id="SC-001") == 1


@pytest.mark.asyncio
async def test_the_count_is_scoped_to_its_own_script(project):
    await project.execute(
        "INSERT INTO interview_script_ledger (script_id, project_id, node_id) "
        "VALUES ('SC-002', 1, '1.3')")
    await project.commit()
    await record_script_review(project, project_id=1, script_id="SC-002",
                               reviewer="ana", decision="reviewed", at_version=1)
    assert await review_count(project, project_id=1, script_id="SC-001") == 0
