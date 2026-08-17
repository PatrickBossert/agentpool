# tests/test_revert_to_version.py
"""Reverting to an earlier output version must succeed even when the newer version has
lineage, citation, or run-input rows referencing it - foreign_keys=ON means those rows
must be cleared before agent_outputs can be hard-deleted."""
import pytest
import pytest_asyncio

from api.database import get_connection, insert_project, revert_to_version

SLUG = "revert-lineage-test"


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
    yield tmp_path
    get_settings.cache_clear()


async def _output(conn, agent, output_type, version, is_current=1):
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
        " version, is_current, review_status) VALUES (1,?,?,?,?,?,'pending')",
        (agent, output_type, f"{output_type}_v{version}.json", version, is_current),
    )
    await conn.commit()
    return cur.lastrowid


@pytest.mark.asyncio
async def test_revert_succeeds_when_the_discarded_version_has_lineage_rows(project):
    async with get_connection(SLUG) as conn:
        # v1 is the target we will revert back to.
        v1 = await _output(conn, "value_chain_mapper", "value_chain_model", 1, is_current=0)
        # v2 is the doomed version - current now, deleted by the revert.
        v2 = await _output(conn, "value_chain_mapper", "value_chain_model", 2, is_current=1)
        # An unrelated output that v2 was built from, and one built from v2 - covers
        # output_lineage in both directions.
        upstream = await _output(conn, "value_lever_analyst", "value_levers", 1, is_current=1)
        downstream = await _output(conn, "interaction_designer", "interview_scripts", 1, is_current=1)

        # v2 was built from `upstream` (v2 is the output_id, upstream is the input).
        await conn.execute(
            "INSERT INTO output_lineage (output_id, input_output_id) VALUES (?,?)",
            (v2, upstream),
        )
        # `downstream` was built from v2 (downstream is the output_id, v2 is the input).
        await conn.execute(
            "INSERT INTO output_lineage (output_id, input_output_id) VALUES (?,?)",
            (downstream, v2),
        )

        await conn.execute(
            "INSERT INTO client_documents (id, project_id, filename, original_name,"
            " file_path, content_type, size_bytes) VALUES (9,1,'a.pdf','Annual.pdf','x','p',1)"
        )
        await conn.execute(
            "INSERT INTO output_citations (output_id, doc_id) VALUES (?,9)", (v2,)
        )

        await conn.execute(
            "INSERT INTO run_inputs (run_id, output_id) VALUES (50,?)", (v2,)
        )
        await conn.commit()

    async with get_connection(SLUG) as conn:
        row, deleted_paths = await revert_to_version(conn, project_id=1, output_id=v1)

    assert row is not None
    assert row["id"] == v1
    assert row["is_current"] == 1
    assert deleted_paths == ["value_chain_model_v2.json"]

    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT id, is_current FROM agent_outputs WHERE output_type='value_chain_model'"
        ) as cur:
            remaining = await cur.fetchall()
    assert [dict(r) for r in remaining] == [{"id": v1, "is_current": 1}]


@pytest.mark.asyncio
async def test_revert_supersedes_by_output_type_not_by_agent(project):
    """Version numbering and is_current supersession are scoped by (project, output_type),
    not by agent - the filename that anchors a version carries no agent (Task 3). Two agents
    can both write the 'state' output type; reverting alex's output to an earlier version
    must leave exactly one is_current row for the output type, superseding maya's row too -
    not leave two current rows standing side by side."""
    async with get_connection(SLUG) as conn:
        alex_v1 = await _output(conn, "alex", "state", 1, is_current=0)
        alex_v2 = await _output(conn, "alex", "state", 2, is_current=0)
        maya_v3 = await _output(conn, "maya", "state", 3, is_current=1)

    async with get_connection(SLUG) as conn:
        row, deleted_paths = await revert_to_version(conn, project_id=1, output_id=alex_v1)

    assert row is not None
    assert row["id"] == alex_v1
    assert row["is_current"] == 1
    assert deleted_paths == ["state_v2.json", "state_v3.json"]

    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT id, is_current FROM agent_outputs WHERE output_type='state' ORDER BY id"
        ) as cur:
            remaining = await cur.fetchall()
    remaining = [dict(r) for r in remaining]
    assert remaining == [{"id": alex_v1, "is_current": 1}]
    assert sum(r["is_current"] for r in remaining) == 1


# ── Which crew's reviews a revert clears ──────────────────────────────────────
#
# A revert dismisses the pending HITL reviews of the crew whose output it rolled back;
# human_reviews link via crew_run_id, so they otherwise survive the output's deletion and the
# board stays stuck waiting on a review of something that no longer exists.
#
# Which crew that is came from a hand-written agent-to-crew map in api/database.py. It listed
# fifteen of the seventeen agents - visual_illustrator and pam were simply absent - and it had
# already been wrong once about Morgan, sending a revert of her output to a crew she had left.
# An agent missing from the map fails silently: the revert succeeds and the stale review stays.


async def _crew_run(conn, crew_name, run_id):
    await conn.execute(
        "INSERT INTO crew_runs (id, project_id, crew_name, status) VALUES (?,1,?,'completed')",
        (run_id, crew_name),
    )
    await conn.execute(
        "INSERT INTO human_reviews (crew_run_id, decision, prompt) VALUES (?,'pending','p')",
        (run_id,),
    )
    await conn.commit()


async def _decisions(conn) -> dict[str, str]:
    async with conn.execute(
        "SELECT cr.crew_name, hr.decision FROM human_reviews hr"
        " JOIN crew_runs cr ON cr.id = hr.crew_run_id"
    ) as cur:
        return {r["crew_name"]: r["decision"] for r in await cur.fetchall()}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "agent_name,expected_crew",
    [
        # Absent from the deleted map entirely - the Illustrator's revert dismissed nothing.
        ("visual_illustrator", "business_plan"),
        # Present and correct in the deleted map: the fix must not have moved this one.
        ("roadmap_generator", "delivery"),
    ],
)
async def test_a_revert_dismisses_the_pending_review_of_its_own_crew(
    agent_name, expected_crew, project
):
    from agents.graph import build_graph

    other = next(c for c in build_graph().crews if c != expected_crew)
    async with get_connection(SLUG) as conn:
        v1 = await _output(conn, agent_name, "brief", 1, is_current=0)
        await _output(conn, agent_name, "brief", 2, is_current=1)
        await _crew_run(conn, expected_crew, 1)
        await _crew_run(conn, other, 2)

    async with get_connection(SLUG) as conn:
        await revert_to_version(conn, project_id=1, output_id=v1)

    async with get_connection(SLUG) as conn:
        decisions = await _decisions(conn)
    assert decisions[expected_crew] == "dismissed"
    assert decisions[other] == "pending", "a revert cleared a review on a crew it does not own"


@pytest.mark.asyncio
async def test_a_revert_by_an_agent_in_no_crew_dismisses_nothing(project):
    """PAM is in no crew, so there is no crew whose reviews are hers to clear. A lookup that
    guessed - by taking the first crew, say - would pass the tests above and clear a stranger's
    review here.

    Every crew carries a pending review, not one: a single crew leaves the guess free to name
    a crew with no run row, where the dismissal matches nothing and the test passes anyway.
    """
    from agents.graph import build_graph

    crews = list(build_graph().crews)
    async with get_connection(SLUG) as conn:
        v1 = await _output(conn, "pam", "state", 1, is_current=0)
        await _output(conn, "pam", "state", 2, is_current=1)
        for run_id, crew_id in enumerate(crews, start=1):
            await _crew_run(conn, crew_id, run_id)

    async with get_connection(SLUG) as conn:
        await revert_to_version(conn, project_id=1, output_id=v1)

    async with get_connection(SLUG) as conn:
        assert await _decisions(conn) == {crew_id: "pending" for crew_id in crews}
