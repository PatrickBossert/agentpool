"""A send-back reaches the right agent, and only that agent.

`discovery_mapping` holds two agents. Alex owns `value_chain_ledger` and Morgan owns
`value_lever_ledger`, and the crew-scoped injection `_fetch_regeneration_requests` uses for
Maya cannot tell them apart - `assessment_design` holds one agent, so scoping on the crew and
scoping on the agent are the same thing there and are not the same thing here.

**Both halves are asserted, and the second is the one that fails silently.** That a node sent
back reaches Alex is visible the moment anybody looks at the prompt. That it *also* reached
Morgan is invisible: her task is longer by one block she was never meant to see, she answers
it or ignores it, and nothing anywhere records that it happened. Every wiring test below
therefore asserts the presence on one task and the absence on the other, keyed by the task's
own agent - not on the crew, and not on a join of the two descriptions, which any one task
holding the block would satisfy.
"""
import asyncio

import pytest
import pytest_asyncio
import yaml
from unittest.mock import MagicMock, patch

from api.database import get_connection, insert_project

SLUG = "discovery-revision-test"

NODE_HEADER = "VALUE CHAIN NODES SENT BACK FOR REVISION"
LEVER_HEADER = "VALUE LEVERS SENT BACK FOR REVISION"

ALEX = "Value Chain Mapper"
MORGAN = "Value Lever Analyst"


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    """An isolated project with a config file, so build_and_run_crew can read it.

    DATABASE_DIR, PROJECTS_DIR and the settings cache are all reset on both sides: the shared
    /tmp/agentpool_test that conftest points at persists between runs, and a test writing a
    hardcoded row id into it passes once and fails on every run afterwards.
    """
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    projects_dir = tmp_path / "projects"
    monkeypatch.setenv("PROJECTS_DIR", str(projects_dir))
    (projects_dir / SLUG).mkdir(parents=True)
    (projects_dir / SLUG / "config.yaml").write_text(
        yaml.dump({"llm_mode": "standard", "sector": "utilities"})
    )
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield SLUG
    get_settings.cache_clear()


async def _project_id(conn) -> int:
    cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (SLUG,))
    return (await cur.fetchone())[0]


async def _node(
    conn, node_id="3.3.3", *, label="Mains renewal planning", level="L3", active=1,
    review_status="changes_requested", return_to="agent", reviewed_at_version=3,
    last_version=3, project_id=None,
):
    """One value_chain_ledger row, defaulting to the state a send-back leaves behind.

    reviewed_at_version and last_version both default to the same number, which is what a
    recorder stamping the row it read produces: the reviewer read version 3 and the agent has
    not written since.
    """
    await conn.execute(
        "INSERT INTO value_chain_ledger"
        " (node_id, project_id, label, level, active, review_status, review_return_to,"
        "  reviewed_at_version, last_version)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (node_id, project_id or await _project_id(conn), label, level, active,
         review_status, return_to, reviewed_at_version, last_version),
    )
    await conn.commit()


async def _lever(
    conn, lever_id="LV-001", *, title="Risk-based capital prioritisation", status="untested",
    review_status="changes_requested", return_to="agent", reviewed_at_version=3,
    last_version=3, project_id=None,
):
    await conn.execute(
        "INSERT INTO value_lever_ledger"
        " (lever_id, project_id, title, status, review_status, review_return_to,"
        "  reviewed_at_version, last_version)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (lever_id, project_id or await _project_id(conn), title, status,
         review_status, return_to, reviewed_at_version, last_version),
    )
    await conn.commit()


# ══════════════════════════════════════════════════════════════════════════════════════
# The block, per agent
# ══════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_alex_is_not_handed_morgans_lever_notes(project):
    """The plan's own test. One node and one lever both awaiting the agent, and Alex's block
    names the node alone."""
    from api.services.run_service import _pending_discovery_revisions

    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3")
        await _lever(conn, "LV-001")

    block = await _pending_discovery_revisions(SLUG, "value_chain_mapper")

    assert "3.3.3" in block
    assert "LV-001" not in block
    assert LEVER_HEADER not in block


@pytest.mark.asyncio
async def test_morgan_is_not_handed_alexs_node_notes(project):
    """The mirror, and it is not redundant with the test above.

    One assembler serving both agents is exactly the shape that lets one direction's test
    stand in for the other's - so each direction is driven, and a mutation that leaks in one
    direction only has a test of its own to fail.
    """
    from api.services.run_service import _pending_discovery_revisions

    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3")
        await _lever(conn, "LV-001")

    block = await _pending_discovery_revisions(SLUG, "value_lever_analyst")

    assert "LV-001" in block
    assert "3.3.3" not in block
    assert NODE_HEADER not in block


@pytest.mark.asyncio
async def test_a_node_returned_to_the_reviewer_never_reaches_alex(project):
    """A return to `reviewer` is a human-to-human loop. Regenerating the node the reviewer was
    about to re-read rewrites the thing under discussion."""
    from api.services.run_service import _pending_discovery_revisions

    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3", return_to="reviewer")

    assert await _pending_discovery_revisions(SLUG, "value_chain_mapper") == ""


@pytest.mark.asyncio
async def test_a_lever_returned_to_the_reviewer_never_reaches_morgan(project):
    from api.services.run_service import _pending_discovery_revisions

    async with get_connection(SLUG) as conn:
        await _lever(conn, "LV-001", return_to="reviewer")

    assert await _pending_discovery_revisions(SLUG, "value_lever_analyst") == ""


@pytest.mark.asyncio
async def test_a_node_a_reviewer_merely_read_never_reaches_alex(project):
    """`changes_requested` is the only decision that asks for a regeneration. A node that was
    read, edited or approved has had its say and is not owed a rewrite."""
    from api.services.run_service import _pending_discovery_revisions

    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.1", review_status="reviewed", return_to=None)
        await _node(conn, "3.3.2", review_status="approved", return_to=None)
        await _node(conn, "3.3.4", review_status="pending", return_to=None)

    assert await _pending_discovery_revisions(SLUG, "value_chain_mapper") == ""


@pytest.mark.asyncio
async def test_a_retired_node_does_not_reach_alex(project):
    """A node dropped from the chain is not one he can be asked to revise. The ledger never
    deletes a row, so without the active filter a send-back recorded before a retirement would
    outlive the node itself."""
    from api.services.run_service import _pending_discovery_revisions

    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3", active=0)

    assert await _pending_discovery_revisions(SLUG, "value_chain_mapper") == ""


@pytest.mark.asyncio
async def test_a_send_back_clears_once_the_agent_has_written_past_the_version_read(project):
    """The row clears on evidence the work was done, not on the assumption that a run meant it
    was. `register_nodes_sync` stamps `last_version` on every id a batch names, so a batch
    that named this node moves it past the version the reviewer read."""
    from api.services.run_service import _pending_discovery_revisions

    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3", reviewed_at_version=3, last_version=4)
        await _lever(conn, "LV-001", reviewed_at_version=3, last_version=4)

    assert await _pending_discovery_revisions(SLUG, "value_chain_mapper") == ""
    assert await _pending_discovery_revisions(SLUG, "value_lever_analyst") == ""


@pytest.mark.asyncio
async def test_a_send_back_with_no_stamped_version_still_reaches_the_agent(project):
    """The one place this read is deliberately not spelled the way `scripts_awaiting_
    regeneration` spells it, and the reason is in `discovery_review_service`.

    Nothing writes `reviewed_at_version` yet - the recorder arrives with the review surface.
    Compared the script ledger's way, a NULL would read as 0, every row whose agent has ever
    written would be excluded, and a recorder that set `review_status` without the stamp would
    produce a send-back that reached the agent **never**, on every run, silently. This way it
    reaches the agent until something clears it: still a defect, but one that announces itself
    in the prompt rather than one nobody can see.
    """
    from api.services.run_service import _pending_discovery_revisions

    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3", reviewed_at_version=None, last_version=7)
        await _lever(conn, "LV-001", reviewed_at_version=None, last_version=7)

    assert "3.3.3" in await _pending_discovery_revisions(SLUG, "value_chain_mapper")
    assert "LV-001" in await _pending_discovery_revisions(SLUG, "value_lever_analyst")


@pytest.mark.asyncio
async def test_a_send_back_on_a_row_that_was_never_registered_still_reaches_the_agent(project):
    """`last_version` is nullable, and both backfills leave it so on rows they register from an
    artefact that predates per-batch versioning. NULL <= 0 evaluates to NULL in SQL, which is
    not true - the trap that silently cost `scripts_awaiting_regeneration` a fix round."""
    from api.services.run_service import _pending_discovery_revisions

    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3", reviewed_at_version=None, last_version=None)
        await _lever(conn, "LV-001", reviewed_at_version=None, last_version=None)

    assert "3.3.3" in await _pending_discovery_revisions(SLUG, "value_chain_mapper")
    assert "LV-001" in await _pending_discovery_revisions(SLUG, "value_lever_analyst")


@pytest.mark.asyncio
async def test_another_projects_send_back_does_not_reach_this_run(project):
    """Both ledgers are keyed on the item id alone - node_id and lever_id are the primary keys,
    so two projects in one database file cannot hold the same id. `project_id` is still read on
    every query, because the column exists to be asked and a filter nobody drives is a filter
    that can be deleted without a test noticing."""
    from api.services.run_service import _pending_discovery_revisions

    async with get_connection(SLUG) as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES ('somebody-else')")
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE slug='somebody-else'")
        other_id = (await cur.fetchone())[0]
        await _node(conn, "3.3.3", project_id=other_id)
        await _lever(conn, "LV-001", project_id=other_id)

    assert await _pending_discovery_revisions(SLUG, "value_chain_mapper") == ""
    assert await _pending_discovery_revisions(SLUG, "value_lever_analyst") == ""


@pytest.mark.asyncio
async def test_the_block_is_absent_when_nothing_is_awaiting(project):
    """An ordinary run is unchanged. Both agents, because a shared assembler returning "" for
    the wrong reason would satisfy either one alone."""
    from api.services.run_service import _pending_discovery_revisions

    assert await _pending_discovery_revisions(SLUG, "value_chain_mapper") == ""
    assert await _pending_discovery_revisions(SLUG, "value_lever_analyst") == ""


@pytest.mark.asyncio
async def test_an_agent_that_owns_no_item_ledger_gets_no_block(project):
    """Scoping is by ownership of a ledger, not by crew - so `discovery_mapping`-only falls out
    of who owns what rather than being asserted a second time somewhere else. Maya has a
    per-item ledger of her own and reaches it through `_fetch_regeneration_requests`; she must
    not also reach this one."""
    from api.services.run_service import _pending_discovery_revisions

    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3")
        await _lever(conn, "LV-001")

    for agent_name in ("interaction_designer", "stakeholder_manager", "pam", ""):
        assert await _pending_discovery_revisions(SLUG, agent_name) == "", agent_name


@pytest.mark.asyncio
async def test_the_block_names_every_awaiting_item_and_its_label(project):
    """A reviewer cites an id; the label is what tells the agent which activity that id is."""
    from api.services.run_service import _pending_discovery_revisions

    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3", label="Mains renewal planning", level="L3")
        await _node(conn, "1.F", label="Finance business partnering", level="L1")

    block = await _pending_discovery_revisions(SLUG, "value_chain_mapper")

    assert "3.3.3" in block and "Mains renewal planning" in block
    assert "1.F" in block and "Finance business partnering" in block
    assert NODE_HEADER in block


# ══════════════════════════════════════════════════════════════════════════════════════
# The wiring: which task the block actually lands on
# ══════════════════════════════════════════════════════════════════════════════════════
#
# These build the **real** discovery_mapping crew - the real agents, with their real `role`
# strings - because the join from a task back to an agent name is a string comparison through
# `_SNAKE_TO_DISPLAY`, and a mocked crew would agree with whatever that comparison happened to
# do. Only the LLM, the tools and the kickoff are stubbed.

def _stub_crew_construction():
    from crewai import LLM
    return (
        patch("agents.crews.discovery_mapping_crew.get_tools_for_agent", return_value=[]),
        patch(
            "agents.crews.discovery_mapping_crew.get_llm_for_agent",
            return_value=MagicMock(spec=LLM),
        ),
    )


async def _descriptions_at_kickoff(crew_name="discovery_mapping", run_id=1) -> dict:
    """Run the crew with kickoff stubbed, and return {agent role: task description}.

    Captured from inside the fake kickoff rather than afterwards, so the assertion pins that
    the block was on the task *before* the crew ran and not merely at some point.
    """
    from crewai import Crew
    from api.services.run_service import build_and_run_crew

    captured: dict = {}

    async def _fake_kickoff(self):
        captured.update({t.agent.role: t.description for t in self.tasks})
        return "done"

    tools_patch, llm_patch = _stub_crew_construction()
    with tools_patch, llm_patch, patch.object(Crew, "kickoff_async", _fake_kickoff):
        await build_and_run_crew(SLUG, crew_name, run_id=run_id)
    return captured


@pytest.mark.asyncio
async def test_alexs_task_carries_the_node_block_and_morgans_does_not(project):
    """The absence is asserted on Morgan's own task, not on the crew.

    CLAUDE.md records an assertion scoped to a container that any sibling could satisfy: the
    "why is this greyed out" note asserted per section, so any section already holding one
    satisfied every control in it. Asserting that the crew's prompts contain "3.3.3 exactly
    once", or that the concatenation of both descriptions holds the block, is the same defect -
    both pass if the block is on the wrong task.
    """
    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3")

    seen = await _descriptions_at_kickoff()

    assert NODE_HEADER in seen[ALEX] and "3.3.3" in seen[ALEX]
    assert NODE_HEADER not in seen[MORGAN]
    assert "3.3.3" not in seen[MORGAN]


@pytest.mark.asyncio
async def test_morgans_task_carries_the_lever_block_and_alexs_does_not(project):
    async with get_connection(SLUG) as conn:
        await _lever(conn, "LV-001")

    seen = await _descriptions_at_kickoff()

    assert LEVER_HEADER in seen[MORGAN] and "LV-001" in seen[MORGAN]
    assert LEVER_HEADER not in seen[ALEX]
    assert "LV-001" not in seen[ALEX]


@pytest.mark.asyncio
async def test_each_agent_gets_its_own_block_when_both_are_awaiting(project):
    """The case that distinguishes "routed" from "given to whoever asked first": both ledgers
    hold a send-back, and each task carries exactly one of the two blocks."""
    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3")
        await _lever(conn, "LV-001")

    seen = await _descriptions_at_kickoff()

    assert "3.3.3" in seen[ALEX] and "LV-001" not in seen[ALEX]
    assert "LV-001" in seen[MORGAN] and "3.3.3" not in seen[MORGAN]


@pytest.mark.asyncio
async def test_an_ordinary_run_carries_neither_block(project):
    """Nothing awaiting either agent, so an ordinary run is unchanged - asserted on the task
    text rather than on the assembler, since the assembler returning "" says nothing about
    what the loop does with it."""
    seen = await _descriptions_at_kickoff()

    for role in (ALEX, MORGAN):
        assert NODE_HEADER not in seen[role]
        assert LEVER_HEADER not in seen[role]


@pytest.mark.asyncio
async def test_a_send_back_brings_the_skill_proposal_instruction_to_that_task_alone(project):
    """A per-item send-back is a correction with a general rule possibly behind it, exactly as
    a change request is, so it earns the instruction on the same terms - and on the task it was
    delivered to, not on the crew. Morgan corrected nothing and has nothing to generalise."""
    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3")

    seen = await _descriptions_at_kickoff()

    assert "SkillProposalTool" in seen[ALEX]
    assert "SkillProposalTool" not in seen[MORGAN]


@pytest.mark.asyncio
async def test_the_skill_proposal_instruction_is_injected_once_not_twice(project):
    """Two blocks fired on one task - the change request and the node send-back - and a human
    sent one lot of work back, not two. Two copies of "propose at most one rule" is the
    fan-out defect `_fetch_change_requests` deduplicates for, arriving from a third source."""
    from api.database import insert_output_change

    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3")
        cur = await conn.execute(
            "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
            " version, is_current, review_status)"
            " VALUES (?,'value_chain_mapper','value_chain_model','m_v1.json',1,1,'pending')",
            (await _project_id(conn),),
        )
        await conn.commit()
        await insert_output_change(
            conn, output_id=cur.lastrowid, requested_by="alice", source="review",
            request="use the approved figures", summary="", kind="change_request",
        )

    seen = await _descriptions_at_kickoff()

    assert seen[ALEX].count("SkillProposalTool") == 1


@pytest.mark.asyncio
async def test_the_change_request_block_still_reaches_both_tasks(project):
    """The load-bearing regression. A reviewer who asks for a revision must still get one, and
    if that breaks there is no error - the artefact comes back unchanged and nobody knows why.

    A change request is crew-scoped by design and reaches every task in the crew; only the new
    per-item block is per-agent. Driven with a node send-back present as well, because the
    per-task branch this task added is the thing that could have narrowed it.
    """
    from api.database import insert_output_change

    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3")
        cur = await conn.execute(
            "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
            " version, is_current, review_status)"
            " VALUES (?,'value_chain_mapper','value_chain_model','m_v1.json',1,1,'pending')",
            (await _project_id(conn),),
        )
        await conn.commit()
        await insert_output_change(
            conn, output_id=cur.lastrowid, requested_by="alice", source="review",
            request="use the approved figures", summary="", kind="change_request",
        )

    seen = await _descriptions_at_kickoff()

    assert "use the approved figures" in seen[ALEX]
    assert "use the approved figures" in seen[MORGAN]


@pytest.mark.asyncio
async def test_the_original_task_body_survives_the_injection(project):
    """Every block is prepended. A block that replaced the task rather than preceding it would
    pass every presence assertion above."""
    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3")

    seen = await _descriptions_at_kickoff()

    assert "value_chain_model" in seen[ALEX], "Alex's own task body has gone"
    assert seen[ALEX].startswith(NODE_HEADER), "the block must precede the task, not follow it"


# ══════════════════════════════════════════════════════════════════════════════════════
# The join from a task back to an agent name
# ══════════════════════════════════════════════════════════════════════════════════════

def test_every_discovery_mapping_task_resolves_to_its_agent_name():
    """`agent_name_for_task` joins a task to the snake key through the agent's `role` string,
    and a string join can fail quietly: a role reworded in an agent module and not in
    `_SNAKE_TO_DISPLAY` resolves to "", the block goes to nobody, and the run looks ordinary.

    Driven against the real crew, so the role strings are the real ones.
    """
    from crewai import LLM
    from agents.crews.discovery_mapping_crew import create_discovery_mapping_crew
    from api.services.run_service import agent_name_for_task

    with patch("agents.crews.discovery_mapping_crew.get_tools_for_agent", return_value=[]):
        crew = create_discovery_mapping_crew(
            slug="join-test", run_id=1, sector="utilities", llm=MagicMock(spec=LLM)
        )

    assert [agent_name_for_task(t) for t in crew.tasks] == [
        "value_chain_mapper", "value_lever_analyst"
    ]


def test_a_task_whose_agent_is_unknown_resolves_to_nothing_rather_than_guessing():
    """"" rather than a fallback to the first agent or to the crew: a block delivered to the
    wrong agent is the failure this whole task exists to prevent, and delivering it to nobody
    is at least the failure the warning in `build_and_run_crew` names."""
    from api.services.run_service import agent_name_for_task

    stranger = MagicMock()
    stranger.agent.role = "Some Agent Nobody Registered"
    assert agent_name_for_task(stranger) == ""

    agentless = MagicMock()
    agentless.agent = None
    assert agent_name_for_task(agentless) == ""


@pytest.mark.asyncio
async def test_a_block_that_reaches_no_task_is_logged(project, caplog):
    """A send-back assembled for an agent no task will take is a reviewer's instruction that
    reached nobody, and it is otherwise indistinguishable from an ordinary run. It cannot be
    raised on - refusing the run would discard the rest of the crew's completed work over a
    prompt block - so the names are logged, which is what tells "the join broke" apart from
    "there was nothing to send" after the fact."""
    import logging

    async with get_connection(SLUG) as conn:
        await _node(conn, "3.3.3")

    with caplog.at_level(logging.WARNING, logger="api.services.run_service"), \
         patch("api.services.run_service.agent_name_for_task", return_value="nobody"):
        await _descriptions_at_kickoff()

    assert any(
        "value_chain_mapper" in r.getMessage() and "reached nobody" in r.getMessage()
        for r in caplog.records
    ), caplog.text


def test_both_ledgers_are_declared_as_things_the_dispatch_path_reads():
    """`CREW_DISPATCH_READS` is what the privacy page shows an auditor asking "what does a crew
    run read?", and this task added two tables to that answer.

    **What this cannot see**, and it is the same limit `test_what_the_dispatch_path_names_
    tables_that_exist` states from the other end: it compares a declaration against two names
    written here. A third ledger read added to the dispatch path and declared nowhere would
    pass it, because nothing walks the dispatch path's SQL. It makes deleting a declaration
    fail, not forgetting to write one.
    """
    from agents.reads import CREW_DISPATCH_READS

    declared = {read.source for read in CREW_DISPATCH_READS}
    assert "value_chain_ledger" in declared
    assert "value_lever_ledger" in declared


# ══════════════════════════════════════════════════════════════════════════════════════
# The column
# ══════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_database_at_version_19_gains_reviewed_at_version_on_both_ledgers(
    tmp_path, monkeypatch
):
    """The bump, not the migration.

    19 is the version immediately below `_SCHEMA_VERSION`, and that is what makes this a test
    of the bump: `get_connection` re-runs the migration block whenever `user_version` is lower,
    so a test pinned at any older number passes under *any* constant above it - including one
    that never moved, leaving the ALTER in the block and unreached on every database already
    opened at the current version.

    The two tables are recreated in their pre-column shape rather than dropped, because that is
    the case the ALTER exists for: `_migrate_value_chain_ledger` early-returns on a table it
    finds, so a deployment that already has these ledgers never revisits their CREATE TABLE.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        import aiosqlite
        from api.database import get_db_path, _MIGRATED

        slug = "item-ledger-upgrade"
        async with get_connection(slug) as conn:
            await conn.execute("DROP TABLE IF EXISTS value_chain_ledger")
            await conn.execute("DROP TABLE IF EXISTS value_lever_ledger")
            await conn.execute(
                "CREATE TABLE value_chain_ledger (node_id TEXT PRIMARY KEY,"
                " project_id INTEGER NOT NULL, label TEXT NOT NULL, active INTEGER DEFAULT 1,"
                " review_status TEXT, review_return_to TEXT, last_version INTEGER)"
            )
            await conn.execute(
                "CREATE TABLE value_lever_ledger (lever_id TEXT PRIMARY KEY,"
                " project_id INTEGER NOT NULL, title TEXT NOT NULL, status TEXT,"
                " review_status TEXT, review_return_to TEXT, last_version INTEGER)"
            )
            await conn.commit()

        _MIGRATED.discard(slug)
        async with aiosqlite.connect(get_db_path(slug)) as raw:
            await raw.execute("PRAGMA user_version = 19")
            await raw.commit()

        async with get_connection(slug) as conn:
            for table in ("value_chain_ledger", "value_lever_ledger"):
                cur = await conn.execute(f"PRAGMA table_info({table})")
                cols = {r[1] for r in await cur.fetchall()}
                assert "reviewed_at_version" in cols, f"{table} did not gain the column"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_fresh_database_has_the_column_without_the_alter(tmp_path, monkeypatch):
    """The CREATE TABLE statements name it too. Both halves are needed and neither implies the
    other: without the ALTER an existing deployment never gains it, and without the column in
    the CREATE a fresh database gains it only by the ALTER it is not supposed to need."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        import aiosqlite
        from api.database import _migrate_value_chain_ledger, _migrate_value_lever_ledger

        async with aiosqlite.connect(tmp_path / "fresh.db") as conn:
            conn.row_factory = aiosqlite.Row
            await _migrate_value_chain_ledger(conn)
            await _migrate_value_lever_ledger(conn)
            for table in ("value_chain_ledger", "value_lever_ledger"):
                cur = await conn.execute(f"PRAGMA table_info({table})")
                cols = {r["name"] for r in await cur.fetchall()}
                assert "reviewed_at_version" in cols, table
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_column_migration_skips_a_database_holding_neither_table(tmp_path):
    """A migration that raises takes every later migration in the block down with it, and
    several test fixtures build `projects` and its siblings by hand with no ledgers at all.
    This one skips *itself* - per table - rather than the rest of the block, and it does not
    create what it does not find: the two functions above own creation."""
    import aiosqlite
    from api.database import _migrate_item_ledger_reviewed_at_version

    async with aiosqlite.connect(tmp_path / "hand-built.db") as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT)")
        await conn.commit()
        await _migrate_item_ledger_reviewed_at_version(conn)  # must not raise
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        names = {r["name"] for r in await cur.fetchall()}
    assert "value_chain_ledger" not in names
    assert "value_lever_ledger" not in names


@pytest.mark.asyncio
async def test_the_column_migration_adds_it_to_whichever_ledger_is_missing_it(tmp_path):
    """Each table is asked for itself. One ledger present and already carrying the column, the
    other present and not - a single shared early return would leave the second one behind."""
    import aiosqlite
    from api.database import _migrate_item_ledger_reviewed_at_version

    async with aiosqlite.connect(tmp_path / "half.db") as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute(
            "CREATE TABLE value_chain_ledger (node_id TEXT PRIMARY KEY,"
            " reviewed_at_version INTEGER)"
        )
        await conn.execute("CREATE TABLE value_lever_ledger (lever_id TEXT PRIMARY KEY)")
        await conn.commit()
        await _migrate_item_ledger_reviewed_at_version(conn)
        cur = await conn.execute("PRAGMA table_info(value_lever_ledger)")
        cols = {r["name"] for r in await cur.fetchall()}
    assert "reviewed_at_version" in cols
