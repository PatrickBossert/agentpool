# tests/test_skill_proposal.py
"""A skill an agent proposes reaches the queue, and reaches no prompt.

The safety property is asserted against **what is injected into the task description**, not
against what the `skills` table holds. CLAUDE.md opens with seven defects of exactly the other
shape - a property verified one layer away from where it holds - and the layer that matters
here is `_fetch_skill_notes`, because that is the only thing that puts a skill in front of an
agent.

An absence assertion passes for the wrong reason as easily as the right one, so the control
below approves the same row and asserts it *does* reach the prompt. Without it, a
`propose_skill` that wrote nothing at all - or filed the assignment under a name the injection
never looks up - would pass the safety test silently.

`DATABASE_DIR` is pointed at this test's own `tmp_path` with `get_settings.cache_clear()` on
both sides: `skills` lives in the shared `system.db`, and the suite's is persistent between
runs, so a proposal left behind would poison every later run of this file.
"""
import pytest

from api.config import get_settings
from api.services.run_service import _fetch_skill_notes, _SNAKE_TO_DISPLAY
from api.services.skills_service import propose_skill

# The crew Maya runs in, and the agent it dispatches. Read from the map rather than written
# out, so this test follows a rename instead of quietly testing nothing.
AGENT = "interaction_designer"
CREW = "assessment_design"
RULE = "The welcome carries privacy and tone; the framing carries the interview's purpose"


@pytest.fixture(autouse=True)
def _isolated_system_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _stored(skill_id: int) -> dict:
    from api.database import get_system_connection

    async with get_system_connection() as conn:
        async with conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)) as cur:
            row = await cur.fetchone()
        assert row is not None, "propose_skill reported an id that is not in the table"
        return dict(row)


async def _approve(skill_id: int) -> None:
    from api.database import get_system_connection, update_skill

    async with get_system_connection() as conn:
        assert await update_skill(conn, skill_id=skill_id, status="approved", reviewed_by="tester")


@pytest.mark.asyncio
async def test_a_pending_proposal_never_reaches_a_prompt():
    """The property the whole design rests on."""
    await propose_skill(AGENT, RULE, "sp-gs-am", "SC-014")
    injected = await _fetch_skill_notes(CREW)
    assert RULE not in injected


@pytest.mark.asyncio
async def test_the_same_proposal_reaches_the_prompt_once_a_human_approves_it():
    """The control for the test above, and the only thing that makes its absence mean
    anything: the same row, same crew, same injection path, approved. It also proves the
    assignment was filed under the name `_fetch_skill_notes` looks skills up by - a proposal
    stored under the snake id would be unreachable by any approval.
    """
    result = await propose_skill(AGENT, RULE, "sp-gs-am", "SC-014")
    await _approve(result["skill_id"])
    injected = await _fetch_skill_notes(CREW)
    assert RULE in injected


@pytest.mark.asyncio
async def test_a_proposal_is_stored_pending_with_its_provenance():
    result = await propose_skill(AGENT, RULE, "sp-gs-am", "SC-014")
    assert result["action"] == "created"
    assert result["status"] == "pending"
    row = await _stored(result["skill_id"])
    assert row["status"] == "pending"
    assert row["source"] == "revision"
    assert row["source_project"] == "sp-gs-am"
    assert row["source_ref"] == "SC-014"
    assert row["proposed_by_agent"] == AGENT
    assert row["occurrences"] == 1


@pytest.mark.asyncio
async def test_the_proposal_is_assigned_to_the_agent_that_made_it():
    """Assignment is by role name, which is what the injection reads. Asserted here as well
    as through the prompt, because the failure modes differ: this one says *why* an approved
    skill would not have appeared.
    """
    from api.database import get_system_connection

    result = await propose_skill(AGENT, RULE, "sp-gs-am", "SC-014")
    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT agent_name FROM agent_skill_assignments WHERE skill_id=?",
            (result["skill_id"],),
        ) as cur:
            assigned = sorted(r["agent_name"] for r in await cur.fetchall())
    assert assigned == [_SNAKE_TO_DISPLAY[AGENT]]


@pytest.mark.asyncio
async def test_an_existing_system_database_gains_the_columns_and_keeps_its_rows():
    """The path the live deployment takes. `CREATE TABLE IF NOT EXISTS` does nothing to a
    `skills` table that already exists, so the 53 approved rows on the deployment reach the
    new columns only through the ALTER loop - and `occurrences NOT NULL DEFAULT 1` has to
    land a 1 on every one of them rather than refusing the ALTER.
    """
    import aiosqlite

    from api.database import get_system_db_path, init_system_db

    path = get_system_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        # The table exactly as it stood before this change.
        await conn.execute(
            """CREATE TABLE skills (
                   id              INTEGER PRIMARY KEY AUTOINCREMENT,
                   name            TEXT NOT NULL,
                   description     TEXT NOT NULL,
                   source          TEXT NOT NULL DEFAULT 'manual',
                   source_project  TEXT,
                   status          TEXT NOT NULL DEFAULT 'pending'
                                       CHECK(status IN ('pending', 'approved', 'rejected')),
                   flag_reason     TEXT,
                   flag_suggestion TEXT,
                   created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                   reviewed_at     DATETIME,
                   reviewed_by     TEXT
               )"""
        )
        await conn.execute(
            "INSERT INTO skills (name, description, source, status) VALUES (?,?,?,?)",
            ("Phase Gating", "An existing approved skill.", "baseline", "approved"),
        )
        await conn.commit()

        conn.row_factory = aiosqlite.Row
        await init_system_db(conn)

        async with conn.execute("PRAGMA table_info(skills)") as cur:
            columns = {r["name"] for r in await cur.fetchall()}
        assert {"source_ref", "proposed_by_agent", "occurrences"} <= columns
        async with conn.execute(
            "SELECT status, occurrences FROM skills WHERE name='Phase Gating'"
        ) as cur:
            row = await cur.fetchone()
    assert row["status"] == "approved"
    assert row["occurrences"] == 1


@pytest.mark.asyncio
async def test_a_proposal_for_one_agent_is_not_injected_into_another_crew():
    """Approved, so the status filter cannot be what is doing the work here."""
    result = await propose_skill(AGENT, RULE, "sp-gs-am", "SC-014")
    await _approve(result["skill_id"])
    assert RULE not in await _fetch_skill_notes("discovery_mapping")
