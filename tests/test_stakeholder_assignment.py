# tests/test_stakeholder_assignment.py
"""The stakeholder-to-value-chain mapping is a durable project fact.

It used to be an event inside an orchestration run: keyed on `orchestration_run_id`, so it
could not be made before the first run, did not survive between runs, and could be read by
nothing that was not a run. Every assertion here is aimed at that - and at the layer the
property actually has to hold, which for the crew is what `build_and_run_crew` feeds the
Interview Coordinator, not what a helper returns.
"""
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import (
    fetch_project,
    fetch_stakeholder_assignments,
    get_connection,
    insert_crew_run,
    insert_orchestration_run,
    insert_project,
    insert_stakeholder,
    replace_stakeholder_assignments,
)

SLUG = "assign-durable"

# Two activities the registry knows about, so a node id has a label to be shown under.
REGISTRY = {
    "schema_version": 2,
    "activities": [
        {"id": "1.2", "label": "Portfolio", "level": "L2", "active": True},
        {"id": "2.7", "label": "Elsewhere", "level": "L2", "active": True},
    ],
}


def _write_registry(projects_dir: Path, activities: list[dict]) -> None:
    outputs = projects_dir / SLUG / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "value_chain_registry.json").write_text(
        json.dumps({"schema_version": 2, "activities": activities}), encoding="utf-8"
    )


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    """A project of its own, with two stakeholders and a value chain registry.

    Its own DATABASE_DIR and PROJECTS_DIR, because the shared /tmp/agentpool_test survives
    between runs and a test that leans on it passes once and fails ever after.
    """
    db_dir = tmp_path / "data"
    projects_dir = tmp_path / "projects"
    db_dir.mkdir(parents=True, exist_ok=True)
    projects_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATABASE_DIR", str(db_dir))
    monkeypatch.setenv("PROJECTS_DIR", str(projects_dir))
    get_settings.cache_clear()

    _write_registry(projects_dir, REGISTRY["activities"])

    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="rail",
            config_json='{"interview_method": "agent"}',
        )
        row = await fetch_project(conn, slug=SLUG)
        alice = await insert_stakeholder(
            conn, project_id=row["id"], name="Alice Chen", job_title="Head of Ops"
        )
        bob = await insert_stakeholder(
            conn, project_id=row["id"], name="Bob Smith", job_title="Packer"
        )

    yield {
        "id": row["id"],
        "alice": alice,
        "bob": bob,
        "db_dir": db_dir,
        "projects_dir": projects_dir,
    }
    get_settings.cache_clear()


async def _dispatch_interviews(project_id: int) -> list[dict]:
    """Run the discovery_interviews dispatch and return what it fed the crew.

    Deliberately not a call to `fetch_stakeholder_assignments`. The property under test is
    that the mapping reaches the Interview Coordinator, and this project has shipped five
    tests that verified a property one layer away from where it holds.
    """
    async with get_connection(SLUG) as conn:
        orch_run_id = await insert_orchestration_run(conn, project_id=project_id)
        crew_run_id = await insert_crew_run(
            conn, project_id=project_id, crew_name="discovery_interviews",
            status="running", orchestration_run_id=orch_run_id,
        )

    crew = MagicMock()
    crew.kickoff_async = AsyncMock(return_value="done")

    with patch(
        "api.services.run_service.load_project_config",
        return_value={"llm_mode": "standard", "sector": "rail", "interview_method": "agent"},
    ), patch(
        "agents.crews.discovery_interviews_crew.create_discovery_interviews_crew",
        return_value=crew,
    ) as factory:
        from api.services.run_service import build_and_run_crew
        await build_and_run_crew(SLUG, "discovery_interviews", crew_run_id)

    return factory.call_args.kwargs["stakeholder_assignments"]


# ── Durability ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assignment_can_be_made_before_any_orchestration_run(project):
    """The old shape could not express this at all - the key was a run id, NOT NULL."""
    async with get_connection(SLUG) as conn:
        async with conn.execute("SELECT COUNT(*) FROM orchestration_runs") as cur:
            assert (await cur.fetchone())[0] == 0, "fixture must start with no runs"

        saved = await replace_stakeholder_assignments(
            conn,
            project_id=project["id"],
            assignments=[{"stakeholder_id": project["alice"], "node_id": "1.2"}],
        )
        assert saved == 1

    async with get_connection(SLUG) as conn:
        rows = await fetch_stakeholder_assignments(conn, project_id=project["id"])
    assert [r["node_id"] for r in rows] == ["1.2"]


@pytest.mark.asyncio
async def test_assignment_made_before_any_run_reaches_the_second_run(project):
    """Made once, by hand, with no run in existence - and still delivered on run two.

    Under the old shape both runs would have seen nothing: run one because the assignment
    was filed against no run at all, run two because it was filed against run one.
    """
    async with get_connection(SLUG) as conn:
        await replace_stakeholder_assignments(
            conn,
            project_id=project["id"],
            assignments=[{"stakeholder_id": project["alice"], "node_id": "1.2"}],
        )

    first = await _dispatch_interviews(project["id"])
    second = await _dispatch_interviews(project["id"])

    for delivered in (first, second):
        assert [a["stakeholder_id"] for a in delivered] == [project["alice"]]
        assert delivered[0]["node_id"] == "1.2"
        assert delivered[0]["name"] == "Alice Chen"
        assert delivered[0]["node_label"] == "Portfolio"
        assert delivered[0]["level"] == "L2"


# ── The node id is the contract, not the label ────────────────────────────────


@pytest.mark.asyncio
async def test_a_relabelled_node_keeps_its_assignment(project):
    """Alex re-emits every label on every run - one run produced 59 label changes.

    Storing the id and reading the label back means a relabelled node carries its people
    with it. Storing the label, as the old column did, would have detached them.
    """
    async with get_connection(SLUG) as conn:
        await replace_stakeholder_assignments(
            conn,
            project_id=project["id"],
            assignments=[{"stakeholder_id": project["alice"], "node_id": "1.2"}],
        )

    before = await _dispatch_interviews(project["id"])
    assert before[0]["node_label"] == "Portfolio"

    _write_registry(project["projects_dir"], [
        {"id": "1.2", "label": "Portfolio Management", "level": "L2", "active": True},
        {"id": "2.7", "label": "Elsewhere", "level": "L2", "active": True},
    ])

    after = await _dispatch_interviews(project["id"])
    assert after[0]["node_label"] == "Portfolio Management"
    assert after[0]["stakeholder_id"] == project["alice"]

    async with get_connection(SLUG) as conn:
        rows = await fetch_stakeholder_assignments(conn, project_id=project["id"])
    assert [r["node_id"] for r in rows] == ["1.2"], "the stored row must not have moved"


@pytest.mark.asyncio
async def test_stored_columns_carry_no_label_and_no_run(project):
    """The shape itself, asserted: no node_label to drift, no run to expire against."""
    async with get_connection(SLUG) as conn:
        async with conn.execute("PRAGMA table_info(stakeholder_assignments)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
    assert "node_id" in cols
    assert "project_id" in cols
    assert "node_label" not in cols
    assert "orchestration_run_id" not in cols


# ── Many-to-many is the point ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_several_stakeholders_on_one_activity_are_all_kept(project):
    """Frontline especially - two people on one activity is normal, never a duplicate."""
    async with get_connection(SLUG) as conn:
        saved = await replace_stakeholder_assignments(
            conn,
            project_id=project["id"],
            assignments=[
                {"stakeholder_id": project["alice"], "node_id": "1.2"},
                {"stakeholder_id": project["bob"], "node_id": "1.2"},
            ],
        )
    assert saved == 2

    delivered = await _dispatch_interviews(project["id"])
    assert {a["stakeholder_id"] for a in delivered} == {project["alice"], project["bob"]}
    assert {a["node_id"] for a in delivered} == {"1.2"}


@pytest.mark.asyncio
async def test_one_stakeholder_on_several_activities_is_kept(project):
    async with get_connection(SLUG) as conn:
        saved = await replace_stakeholder_assignments(
            conn,
            project_id=project["id"],
            assignments=[
                {"stakeholder_id": project["alice"], "node_id": "1.2"},
                {"stakeholder_id": project["alice"], "node_id": "2.7"},
            ],
        )
    assert saved == 2

    delivered = await _dispatch_interviews(project["id"])
    assert sorted(a["node_id"] for a in delivered) == ["1.2", "2.7"]
    assert {a["node_label"] for a in delivered} == {"Portfolio", "Elsewhere"}


@pytest.mark.asyncio
async def test_the_same_pair_twice_collapses_to_one_row(project):
    """Uniqueness is on the pair, and only on the pair."""
    async with get_connection(SLUG) as conn:
        saved = await replace_stakeholder_assignments(
            conn,
            project_id=project["id"],
            assignments=[
                {"stakeholder_id": project["alice"], "node_id": "1.2"},
                {"stakeholder_id": project["alice"], "node_id": "1.2"},
            ],
        )
    assert saved == 1

    async with get_connection(SLUG) as conn:
        rows = await fetch_stakeholder_assignments(conn, project_id=project["id"])
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_the_database_itself_refuses_a_repeated_pair(project):
    """Not only the helper - the constraint is on the table, so no writer can get past it."""
    import aiosqlite

    async with get_connection(SLUG) as conn:
        await conn.execute(
            "INSERT INTO stakeholder_assignments (project_id, stakeholder_id, node_id)"
            " VALUES (?,?,?)",
            (project["id"], project["alice"], "1.2"),
        )
        await conn.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO stakeholder_assignments (project_id, stakeholder_id, node_id)"
                " VALUES (?,?,?)",
                (project["id"], project["alice"], "1.2"),
            )


# ── The re-key itself ─────────────────────────────────────────────────────────


def _old_shaped_db(path: Path, *, rows: list[tuple] = ()) -> None:
    """A database carrying the pre-re-key table, at the schema version before the bump."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE stakeholder_assignments (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            orchestration_run_id  INTEGER NOT NULL,
            stakeholder_id        INTEGER NOT NULL,
            level                 TEXT NOT NULL,
            node_label            TEXT NOT NULL,
            created_at            DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.executemany(
        "INSERT INTO stakeholder_assignments"
        " (orchestration_run_id, stakeholder_id, level, node_label) VALUES (?,?,?,?)",
        rows,
    )
    conn.execute("PRAGMA user_version = 7")
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_an_old_run_scoped_table_is_re_keyed_on_open(tmp_path, monkeypatch):
    """The version bump is what makes this run at all - see _SCHEMA_VERSION in database.py."""
    db_dir = tmp_path / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATABASE_DIR", str(db_dir))
    get_settings.cache_clear()

    _old_shaped_db(db_dir / "legacy-shape.db")

    async with get_connection("legacy-shape") as conn:
        async with conn.execute("PRAGMA table_info(stakeholder_assignments)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
    assert "project_id" in cols and "node_id" in cols
    assert "orchestration_run_id" not in cols and "node_label" not in cols
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_an_old_table_holding_rows_is_kept_aside_not_dropped(tmp_path, monkeypatch):
    """Every project database holds zero of these, so the re-key is free - but a DROP that
    is only safe because a count came back zero should check the count."""
    db_dir = tmp_path / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATABASE_DIR", str(db_dir))
    get_settings.cache_clear()

    _old_shaped_db(db_dir / "legacy-rows.db", rows=[(1, 1, "L2", "Billing")])

    async with get_connection("legacy-rows") as conn:
        async with conn.execute("PRAGMA table_info(stakeholder_assignments)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        async with conn.execute(
            "SELECT node_label FROM stakeholder_assignments_pre_project_rekey"
        ) as cur:
            kept = [r[0] async for r in cur]
    assert "project_id" in cols
    assert kept == ["Billing"]
    get_settings.cache_clear()
