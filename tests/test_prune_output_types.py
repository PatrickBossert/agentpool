# tests/test_prune_output_types.py
"""Pruning an output type takes its dependent rows with it.

agent_outputs is referenced by seven foreign key columns and enforcement is on, so a bare
DELETE raises IntegrityError. Two delete paths shipped with exactly that defect before.
"""
import pytest
import pytest_asyncio

from api.database import get_connection, insert_project, prune_output_types

SLUG = "prune-test"


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield
    get_settings.cache_clear()


async def _output(conn, output_type, version, agent="value_chain_mapper"):
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
        " version, is_current, review_status) VALUES (1,?,?,?,?,1,'pending')",
        (agent, output_type, f"{output_type}_v{version}.json", version),
    )
    await conn.commit()
    return cur.lastrowid


@pytest.mark.asyncio
async def test_it_deletes_the_named_types_and_leaves_the_rest(project):
    async with get_connection(SLUG) as conn:
        await _output(conn, "interview_scripts_batch1", 1)
        await _output(conn, "state", 1)
        await _output(conn, "interview_scripts", 1)

        result = await prune_output_types(
            conn, project_id=1, output_types=["interview_scripts_batch1", "state"]
        )
        rows = await conn.execute_fetchall("SELECT output_type FROM agent_outputs")

    assert result["deleted"] == 2
    assert [r[0] for r in rows] == ["interview_scripts"]


@pytest.mark.asyncio
async def test_it_returns_the_file_paths_before_deleting_them(project):
    """The caller archives these. After the delete there is nothing left to ask."""
    async with get_connection(SLUG) as conn:
        await _output(conn, "state", 1)
        await _output(conn, "state", 2)
        result = await prune_output_types(conn, project_id=1, output_types=["state"])

    assert sorted(result["file_paths"]) == ["state_v1.json", "state_v2.json"]


@pytest.mark.asyncio
async def test_it_clears_dependents_so_the_delete_does_not_raise(project):
    """The whole reason this helper exists. Enforcement is on, so a bare DELETE raises."""
    async with get_connection(SLUG) as conn:
        doomed = await _output(conn, "state", 1)
        keeper = await _output(conn, "interview_scripts", 1)
        await conn.execute(
            "INSERT INTO human_reviews (output_id, decision) VALUES (?, 'pending')",
            (doomed,),
        )
        await conn.execute(
            "INSERT INTO run_inputs (run_id, agent_name, output_id) VALUES (5,'a',?)",
            (doomed,),
        )
        await conn.execute(
            "INSERT INTO output_lineage (output_id, input_output_id) VALUES (?,?)",
            (keeper, doomed),
        )
        await conn.commit()

        result = await prune_output_types(conn, project_id=1, output_types=["state"])
        left = await conn.execute_fetchall(
            "SELECT COUNT(*) FROM output_lineage WHERE input_output_id=?", (doomed,)
        )

    assert result["deleted"] == 1
    # The edge pointed AT the doomed row, not from it - both directions must be cleared.
    assert left[0][0] == 0


@pytest.mark.asyncio
async def test_it_only_clears_dependents_of_the_doomed_rows(project):
    """The dependent-clearing test above only checks that a doomed row's dependents are
    gone - it never checks that a kept row's dependents survive. If any of the seven
    DELETEs in prune_output_types lost its `WHERE ... IN (doomed)` clause and became an
    unconditional `DELETE FROM <table>`, every test in this file would still pass, because
    none of them plant a dependent on a row that is meant to survive.

    This test attaches a dependent row to a kept output in every one of the seven
    (table, column) pairs - including approval_commit_outputs, output_changes and
    output_citations, which no other test in this file touches - and asserts the kept
    output's dependents are still there after the prune. It also gives output_lineage a
    surviving edge between two kept outputs, on top of the doomed-row edges the other test
    already covers, so a dropped WHERE clause on either of its two DELETEs is caught even
    though that edge never mentions the doomed row.
    """
    async with get_connection(SLUG) as conn:
        doomed = await _output(conn, "state", 1)
        keeper = await _output(conn, "interview_scripts", 1)
        kept2 = await _output(conn, "interview_scripts", 2)

        # Parent rows required by FK enforcement for the two dependent tables no other
        # test in this file exercises.
        commit_cur = await conn.execute(
            "INSERT INTO approval_commits (crew_name, committed_by) VALUES"
            " ('discovery_mapping', 'tester')"
        )
        commit_id = commit_cur.lastrowid
        doc_cur = await conn.execute(
            "INSERT INTO client_documents (project_id, filename, original_name, file_path)"
            " VALUES (1, 'a.pdf', 'a.pdf', '/tmp/a.pdf')"
        )
        doc_id = doc_cur.lastrowid

        for output_id in (doomed, keeper):
            await conn.execute(
                "INSERT INTO human_reviews (output_id, decision) VALUES (?, 'pending')",
                (output_id,),
            )
            await conn.execute(
                "INSERT INTO approval_commit_outputs (commit_id, output_id) VALUES (?, ?)",
                (commit_id, output_id),
            )
            await conn.execute(
                "INSERT INTO output_changes (output_id, requested_by, source, request)"
                " VALUES (?, 'tester', 'chat', 'reword it')",
                (output_id,),
            )
            await conn.execute(
                "INSERT INTO run_inputs (run_id, agent_name, output_id) VALUES (5, 'a', ?)",
                (output_id,),
            )
            await conn.execute(
                "INSERT INTO output_citations (output_id, doc_id) VALUES (?, ?)",
                (output_id, doc_id),
            )

        # Doomed-row edges on both output_lineage columns (as the other test covers),
        # plus a kept-to-kept edge that mentions the doomed row nowhere at all.
        await conn.execute(
            "INSERT INTO output_lineage (output_id, input_output_id) VALUES (?, ?)",
            (doomed, keeper),
        )
        await conn.execute(
            "INSERT INTO output_lineage (output_id, input_output_id) VALUES (?, ?)",
            (keeper, doomed),
        )
        await conn.execute(
            "INSERT INTO output_lineage (output_id, input_output_id) VALUES (?, ?)",
            (keeper, kept2),
        )
        await conn.commit()

        result = await prune_output_types(conn, project_id=1, output_types=["state"])

        counts = {}
        for table, column in (
            ("human_reviews", "output_id"),
            ("approval_commit_outputs", "output_id"),
            ("output_changes", "output_id"),
            ("run_inputs", "output_id"),
            ("output_citations", "output_id"),
        ):
            for output_id, label in ((doomed, "doomed"), (keeper, "keeper")):
                rows = await conn.execute_fetchall(
                    f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (output_id,)
                )
                counts[(table, label)] = rows[0][0]

        lineage_touching_doomed = await conn.execute_fetchall(
            "SELECT COUNT(*) FROM output_lineage WHERE output_id=? OR input_output_id=?",
            (doomed, doomed),
        )
        lineage_kept_edge = await conn.execute_fetchall(
            "SELECT COUNT(*) FROM output_lineage WHERE output_id=? AND input_output_id=?",
            (keeper, kept2),
        )

    assert result["deleted"] == 1

    for table in (
        "human_reviews",
        "approval_commit_outputs",
        "output_changes",
        "run_inputs",
        "output_citations",
    ):
        assert counts[(table, "doomed")] == 0, f"{table}: doomed output's row survived"
        assert counts[(table, "keeper")] == 1, f"{table}: kept output's row was deleted"

    assert lineage_touching_doomed[0][0] == 0
    assert lineage_kept_edge[0][0] == 1


@pytest.mark.asyncio
async def test_running_it_twice_is_safe(project):
    """This script may be run again by someone unsure whether it already ran."""
    async with get_connection(SLUG) as conn:
        await _output(conn, "state", 1)
        first = await prune_output_types(conn, project_id=1, output_types=["state"])
        second = await prune_output_types(conn, project_id=1, output_types=["state"])

    assert first["deleted"] == 1
    assert second["deleted"] == 0
    assert second["file_paths"] == []


@pytest.mark.asyncio
async def test_an_empty_type_list_deletes_nothing(project):
    """Guards the caller passing an empty list - an unguarded IN () would be a syntax
    error at best and a full table delete at worst."""
    async with get_connection(SLUG) as conn:
        await _output(conn, "state", 1)
        result = await prune_output_types(conn, project_id=1, output_types=[])
        rows = await conn.execute_fetchall("SELECT COUNT(*) FROM agent_outputs")

    assert result == {"deleted": 0, "file_paths": []}
    assert rows[0][0] == 1
