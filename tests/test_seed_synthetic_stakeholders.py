"""The synthetic stakeholder seeder, asserted on the database it writes.

Every assertion here reads the rows back out. "The function was called" and "the roster
literal has 60 entries" are both one layer away from the property that matters, which is
what is in `stakeholders` and `stakeholder_assignments` afterwards - and, for the
constraint this task exists to satisfy, what is *still* in them after `--remove`.
"""
import json

import pytest
import pytest_asyncio

from api.database import get_connection, insert_project
from scripts.seed_synthetic_stakeholders import (
    ROSTER,
    SeedRefused,
    _run,
    synthetic_email,
)

SLUG = "seed-test"
TODAY = __import__("datetime").date(2026, 8, 18)

# The two real people on sp-gs-am, in the shape that matters here: already present, holding
# roles beyond participant, and never marked synthetic.
REAL_PEOPLE = [
    ("Patrick Bossert", "patrick@futureedge.consulting"),
    ("Dougie McCrone", "patrick@eemee.com"),
]


def _registry(node_ids, *, retired=()):
    return {
        "activities": [
            {"id": n, "label": f"Node {n}", "level": "L2", "active": n not in retired}
            for n in node_ids
        ]
    }


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    """A project database at the current schema, with a registry holding every node the
    roster cites and two real stakeholders already on the roster."""
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))

    outputs = tmp_path / "projects" / SLUG / "outputs"
    outputs.mkdir(parents=True)
    cited = sorted({n for row in ROSTER for n in row[5]})
    (outputs / "value_chain_registry_v1.json").write_text(
        json.dumps(_registry(cited)), encoding="utf-8"
    )

    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
        for name, email in REAL_PEOPLE:
            await conn.execute(
                "INSERT INTO stakeholders (project_id, name, email, is_participant,"
                " is_reviewer, is_approver) VALUES (1,?,?,1,1,1)",
                (name, email),
            )
        await conn.commit()
    yield tmp_path
    get_settings.cache_clear()


async def _snapshot(table="stakeholders"):
    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(f"SELECT * FROM {table} ORDER BY id")
    return [tuple(r) for r in rows]


async def _synthetic_rows():
    async with get_connection(SLUG) as conn:
        return [
            dict(r)
            for r in await conn.execute_fetchall(
                "SELECT * FROM stakeholders WHERE is_synthetic=1 ORDER BY id"
            )
        ]


async def _assignments():
    async with get_connection(SLUG) as conn:
        return [
            (r["stakeholder_id"], r["node_id"])
            for r in await conn.execute_fetchall(
                "SELECT stakeholder_id, node_id FROM stakeholder_assignments ORDER BY id"
            )
        ]


async def _seed(**kw):
    return await _run(SLUG, apply=True, remove=False, today=TODAY, **kw)


# ── Seeding ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_it_writes_one_row_per_roster_entry_and_marks_every_one(project):
    result = await _seed()
    rows = await _synthetic_rows()

    assert result["stakeholders_inserted"] == len(ROSTER) == 60
    assert len(rows) == 60
    assert {r["name"] for r in rows} == {entry[0] for entry in ROSTER}


@pytest.mark.asyncio
async def test_it_files_every_roster_assignment_against_the_node_id(project):
    result = await _seed()
    pairs = await _assignments()
    rows = {r["name"]: r["id"] for r in await _synthetic_rows()}

    expected = {
        (rows[name], node_id)
        for name, _t, _e, _o, _l, nodes in ROSTER
        for node_id in nodes
    }
    assert set(pairs) == expected
    assert result["assignments_inserted"] == len(expected) == 83


@pytest.mark.asyncio
async def test_the_roster_spreads_across_levels_and_leaves_gaps(project):
    """A roster anchored entirely at L3, or covering every node, tests nothing downstream:
    the first bakes in the L3 efficiency skew CLAUDE.md warns about, and the second hands
    the coverage report nothing to report."""
    await _seed()
    rows = await _synthetic_rows()

    levels = {r["level"] for r in rows}
    assert levels == {"L0", "L1", "L2", "L3"}

    covered = {node_id for _sid, node_id in await _assignments()}
    cited = {n for row in ROSTER for n in row[5]}
    assert covered == cited
    # 76 of the project's 86 active nodes - short of complete, by design.
    assert len(covered) == 76


@pytest.mark.asyncio
async def test_several_stakeholders_share_a_node(project):
    """Several people on one activity is the normal case, and the pair uniqueness
    constraint must not be mistaken for a per-node one."""
    await _seed()
    pairs = await _assignments()
    per_node = {}
    for _sid, node_id in pairs:
        per_node[node_id] = per_node.get(node_id, 0) + 1
    assert max(per_node.values()) > 1


@pytest.mark.asyncio
async def test_no_seeded_row_holds_a_role_beyond_participant(project):
    """A role beyond participant is what mints an invite, and an invite is a redeemable
    credential. Sixty of those is the failure this asserts against."""
    await _seed()
    rows = await _synthetic_rows()

    assert all(r["is_participant"] == 1 for r in rows)
    for flag in ("is_reviewer", "is_approver", "is_project_admin", "is_governor"):
        assert {r[flag] for r in rows} == {0}, flag


@pytest.mark.asyncio
async def test_every_seeded_address_is_undeliverable_by_reservation(project):
    """.invalid is reserved by RFC 2606. dev_mode does NOT cover the campaign or transcript
    senders, so the address on the row is the address Resend would be handed."""
    await _seed()
    rows = await _synthetic_rows()

    assert all(r["email"].endswith("@synthetic.invalid") for r in rows)
    assert len({r["email"] for r in rows}) == 60


@pytest.mark.asyncio
async def test_it_fills_value_streams_so_a_campaign_can_find_them(project):
    """campaign_service selects on `value_streams LIKE`, so an empty one is invisible to
    every campaign - which is the one thing the roster is being seeded for."""
    await _seed()
    rows = await _synthetic_rows()

    streams = {s for r in rows for s in json.loads(r["value_streams"])}
    assert streams == {"Organisation", "Property", "Fleet", "Support Services"}
    assert all(json.loads(r["value_streams"]) for r in rows)


# ── The real people ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_it_leaves_the_real_stakeholders_exactly_as_they_were(project):
    before = await _snapshot()
    await _seed()
    async with get_connection(SLUG) as conn:
        after = [
            tuple(r)
            for r in await conn.execute_fetchall(
                "SELECT * FROM stakeholders WHERE is_synthetic=0 ORDER BY id"
            )
        ]
    assert after == before


@pytest.mark.asyncio
async def test_a_real_stakeholder_is_never_marked_synthetic(project):
    await _seed()
    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT name FROM stakeholders WHERE is_synthetic=0 ORDER BY id"
        )
    assert [r["name"] for r in rows] == [name for name, _ in REAL_PEOPLE]


@pytest.mark.asyncio
async def test_the_api_cannot_set_or_clear_the_marker(project):
    """The reason it is a column rather than a convention. If an ordinary edit could flip
    it, `--remove` would delete a real person or leave a synthetic one behind."""
    from api.database import update_stakeholder, _STAKEHOLDER_UPDATABLE_FIELDS
    from api.database import insert_stakeholder
    import inspect

    assert "is_synthetic" not in _STAKEHOLDER_UPDATABLE_FIELDS
    assert "is_synthetic" not in inspect.signature(insert_stakeholder).parameters

    await _seed()
    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT id FROM stakeholders WHERE is_synthetic=1 LIMIT 1"
        )
        with pytest.raises(ValueError):
            await update_stakeholder(
                conn, stakeholder_id=rows[0]["id"], is_synthetic=0
            )
        still = await conn.execute_fetchall(
            "SELECT is_synthetic FROM stakeholders WHERE id=?", (rows[0]["id"],)
        )
    assert still[0]["is_synthetic"] == 1


# ── Idempotency ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_running_it_twice_leaves_the_same_database(project):
    await _seed()
    first_people = await _snapshot()
    first_pairs = await _assignments()

    second = await _seed()

    assert second["stakeholders_inserted"] == 0
    assert second["assignments_inserted"] == 0
    assert await _snapshot() == first_people
    assert await _assignments() == first_pairs


@pytest.mark.asyncio
async def test_a_second_run_restores_an_assignment_a_human_removed(project):
    """Additive, not replacing: the second run puts back what belongs to the roster and
    leaves an unrelated assignment made by hand alone."""
    await _seed()
    async with get_connection(SLUG) as conn:
        await conn.execute(
            "DELETE FROM stakeholder_assignments WHERE node_id='1.1.1'"
        )
        await conn.execute(
            "INSERT INTO stakeholder_assignments (project_id, stakeholder_id, node_id)"
            " VALUES (1,1,'9.9.9')"
        )
        await conn.commit()

    result = await _seed()

    pairs = await _assignments()
    assert result["assignments_inserted"] == 1
    assert any(node == "1.1.1" for _sid, node in pairs)
    assert (1, "9.9.9") in pairs


# ── Dry run ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_dry_run_writes_nothing_and_makes_no_backup(project):
    before = await _snapshot()
    result = await _run(SLUG, apply=False, remove=False, today=TODAY)

    assert result["applied"] is False
    assert result["roster_size"] == 60
    assert await _snapshot() == before
    assert await _synthetic_rows() == []
    assert not (project / f"{SLUG}.pre-synthetic-2026-08-18.db").exists()


# ── Backup ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_first_apply_copies_the_database_aside(project):
    backup = project / f"{SLUG}.pre-synthetic-2026-08-18.db"
    assert not backup.exists()

    await _seed()

    assert backup.exists()
    import sqlite3

    conn = sqlite3.connect(backup)
    try:
        count = conn.execute("SELECT COUNT(*) FROM stakeholders").fetchone()[0]
    finally:
        conn.close()
    # The copy is the state BEFORE the seed - two real people, nobody else.
    assert count == len(REAL_PEOPLE)


@pytest.mark.asyncio
async def test_a_second_apply_does_not_overwrite_the_backup(project):
    """The point of the copy is the pre-seed state. A second run overwriting it with the
    post-seed state would destroy the only thing it is for."""
    await _seed()
    backup = project / f"{SLUG}.pre-synthetic-2026-08-18.db"
    stamp = backup.stat().st_mtime_ns

    await _seed()

    assert backup.stat().st_mtime_ns == stamp


# ── Removal ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remove_takes_out_every_synthetic_row_and_leaves_the_rest(project):
    before = await _snapshot()
    await _seed()

    result = await _run(SLUG, apply=True, remove=True, today=TODAY)

    assert result["stakeholders_deleted"] == 60
    assert result["assignments_deleted"] == 83
    assert await _snapshot() == before
    assert await _assignments() == []


@pytest.mark.asyncio
async def test_remove_still_finds_a_row_whose_every_editable_field_has_changed(project):
    """The constraint this whole design serves. A convention keyed on the name or the
    address would lose this row; the column does not."""
    await _seed()
    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT id FROM stakeholders WHERE is_synthetic=1 ORDER BY id LIMIT 1"
        )
        victim = rows[0]["id"]
        await conn.execute(
            "UPDATE stakeholders SET name='Patrick Bossert',"
            " email='patrick@futureedge.consulting', entity='Advisor',"
            " organisation='ARUP', level='L1' WHERE id=?",
            (victim,),
        )
        await conn.commit()

    await _run(SLUG, apply=True, remove=True, today=TODAY)

    async with get_connection(SLUG) as conn:
        left = await conn.execute_fetchall("SELECT id FROM stakeholders ORDER BY id")
    assert victim not in [r["id"] for r in left]
    assert len(left) == len(REAL_PEOPLE)


@pytest.mark.asyncio
async def test_remove_is_safe_to_run_twice(project):
    await _seed()
    await _run(SLUG, apply=True, remove=True, today=TODAY)
    snapshot = await _snapshot()

    result = await _run(SLUG, apply=True, remove=True, today=TODAY)

    assert result["stakeholders_deleted"] == 0
    assert await _snapshot() == snapshot


@pytest.mark.asyncio
async def test_remove_refuses_when_a_synthetic_row_holds_interview_data(project):
    """A transcript is a thing somebody said once. The seeder will not cascade through
    one, and it deletes nothing at all when it refuses."""
    await _seed()
    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT id FROM stakeholders WHERE is_synthetic=1 ORDER BY id LIMIT 1"
        )
        await conn.execute(
            "INSERT INTO interview_sessions (project_id, stakeholder_id, node_label,"
            " session_token) VALUES (1,?,'Node 1.1.1','tok-1')",
            (rows[0]["id"],),
        )
        await conn.commit()
    before = await _snapshot()

    with pytest.raises(SeedRefused, match="interview_sessions"):
        await _run(SLUG, apply=True, remove=True, today=TODAY)

    assert await _snapshot() == before
    assert len(await _assignments()) == 83


# ── Refusals ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_it_refuses_a_slug_with_no_database(project):
    with pytest.raises(SeedRefused, match="not a project here"):
        await _run("no-such-project", apply=True, remove=False, today=TODAY)


@pytest.mark.asyncio
async def test_it_refuses_a_backup_copy_that_holds_no_projects_row(project, tmp_path):
    """A dated backup beside the live file is not an engagement, and running the seeder at
    one must not migrate it, mark it, or fill it with people."""
    import shutil

    shutil.copy2(tmp_path / f"{SLUG}.db", tmp_path / "sp-copy.db")
    with pytest.raises(SeedRefused, match="holds no projects row"):
        await _run("sp-copy", apply=True, remove=False, today=TODAY)


@pytest.mark.asyncio
async def test_it_refuses_when_the_registry_does_not_hold_a_cited_node(project, tmp_path):
    outputs = tmp_path / "projects" / SLUG / "outputs"
    cited = sorted({n for row in ROSTER for n in row[5]})
    (outputs / "value_chain_registry_v1.json").write_text(
        json.dumps(_registry([n for n in cited if n != "1.1.1"])), encoding="utf-8"
    )
    before = await _snapshot()

    with pytest.raises(SeedRefused, match="not in the registry: 1.1.1"):
        await _run(SLUG, apply=True, remove=False, today=TODAY)

    assert await _snapshot() == before


@pytest.mark.asyncio
async def test_it_refuses_when_a_cited_node_has_been_retired(project, tmp_path):
    """A retired node is in the registry and must still not be assigned against: the
    assignment page filters on active, so the row would exist and be invisible."""
    outputs = tmp_path / "projects" / SLUG / "outputs"
    cited = sorted({n for row in ROSTER for n in row[5]})
    (outputs / "value_chain_registry_v1.json").write_text(
        json.dumps(_registry(cited, retired={"2.4.2"})), encoding="utf-8"
    )

    with pytest.raises(SeedRefused, match="retired in the registry: 2.4.2"):
        await _run(SLUG, apply=True, remove=False, today=TODAY)


@pytest.mark.asyncio
async def test_it_refuses_a_project_with_no_registry_at_all(project, tmp_path):
    (tmp_path / "projects" / SLUG / "outputs" / "value_chain_registry_v1.json").unlink()

    with pytest.raises(SeedRefused, match="no value_chain_registry"):
        await _run(SLUG, apply=True, remove=False, today=TODAY)


# ── The roster literal itself ─────────────────────────────────────────────────

def test_the_roster_has_no_duplicate_address():
    """Identity is (project_id, email). A duplicate would make one person two rows on the
    first run and be skipped forever afterwards."""
    emails = [synthetic_email(name) for name, *_ in ROSTER]
    assert len(set(emails)) == len(emails)
