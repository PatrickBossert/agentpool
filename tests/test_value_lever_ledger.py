"""The value lever ledger: one row per lever id, append-only on the anchor.

The third ledger of this shape, and the first for a set that had no identity at all. A
script is SC-014 and a node is 3.3.3; a lever was a full sentence in position 4. Across the
five live versions of `value_levers` on sp-gs-am, v3 -> v4 reordered the same ten titles and
v4 -> v5 reworded every one of them, so review state hung on either the title or the
position would have stopped matching anything the first time Morgan ran again.

Every write test that is about the door drives the real door - SQLiteStateTool - rather than
calling the upsert, because a registration path the write does not reach is the exact defect
this line of work exists to remove.
"""
import asyncio
import contextlib
import json
import sqlite3

import pytest

from agents.tools._db import (
    current_lever_ledger_sync,
    levers_without_ids,
    register_levers_sync,
)
from agents.tools.sqlite_state import SQLiteStateTool


@pytest.fixture
def lever_project(tmp_path, monkeypatch):
    """An isolated project with a projects row and an outputs directory, and nothing else."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from api.config import get_settings
    get_settings.cache_clear()
    slug = "lever-ledger-test"
    (tmp_path / "db").mkdir(parents=True, exist_ok=True)
    (tmp_path / "projects" / slug / "outputs").mkdir(parents=True, exist_ok=True)

    from api.database import get_connection

    async def _init():
        async with get_connection(slug) as conn:
            await conn.execute("INSERT INTO projects (slug) VALUES (?)", (slug,))
            await conn.commit()
    asyncio.run(_init())
    yield slug
    get_settings.cache_clear()


def _lever(lever_id, title, **extra):
    return {"lever_id": lever_id, "lever": title, **extra}


def _outputs(slug):
    from pathlib import Path
    from api.config import get_settings
    return Path(get_settings().projects_dir) / slug / "outputs"


def _write(slug, levers, run_id=1):
    """One real write through Morgan's own door."""
    tool = SQLiteStateTool(slug=slug, agent_name="value_lever_analyst", run_id=run_id)
    return tool._run(
        operation="write", key="value_levers", agent_name="value_lever_analyst",
        value=json.dumps(levers),
    )


# --------------------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_ledger_table_exists_with_lever_id_as_primary_key(tmp_path, monkeypatch):
    """lever_id as a PRIMARY KEY is the point: one id means one lever for the life of the
    project, enforced by the database rather than by an instruction Morgan must remember."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.database import get_connection
        async with get_connection("lv-ledger-shape") as conn:
            cur = await conn.execute("PRAGMA table_info(value_lever_ledger)")
            cols = {r[1]: r for r in await cur.fetchall()}
            assert "lever_id" in cols, "table missing"
            assert cols["lever_id"][5] == 1, "lever_id must be the primary key"
            for name in ("project_id", "title", "status", "review_status",
                         "review_return_to", "last_version", "last_author",
                         "created_at", "updated_at"):
                assert name in cols, f"missing column {name}"
            # title carries NOT NULL with no default, which is what turns a null title into
            # a raise rather than a silently stored empty string.
            assert cols["title"][3] == 1, "title must be NOT NULL"
            # status and review_status are two different questions - the interviews answer
            # the first and a human answers the second - so one column cannot serve both.
            assert cols["status"][4] == "'untested'", "status must default to untested"
            assert cols["review_status"][4] == "'pending'", \
                "review_status must default to pending"

            # get_connection turns PRAGMA foreign_keys on for every connection, so the
            # parent row has to exist or the first insert fails on the FK and never reaches
            # the primary key check this test is about.
            await conn.execute("INSERT INTO projects (slug) VALUES ('lv-ledger-shape')")
            await conn.commit()
            await conn.execute(
                "INSERT INTO value_lever_ledger (lever_id, project_id, title)"
                " VALUES ('LV-001', 1, 'Original')")
            await conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                await conn.execute(
                    "INSERT INTO value_lever_ledger (lever_id, project_id, title)"
                    " VALUES ('LV-001', 1, 'A different lever entirely')")
                await conn.commit()
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_database_at_version_18_gains_the_value_lever_ledger(tmp_path, monkeypatch):
    """The migration must reach databases that already exist, which is what the
    _SCHEMA_VERSION bump buys. Without it this passes on a fresh file and the table never
    appears on any deployment opened once - no error, no warning.

    Fails on _SCHEMA_VERSION = 18 and passes on 19.

    **The pinned version is the one immediately below the constant, and that is what makes
    this a test of the bump rather than of the migration.** A test stamping any lower number
    passes under every constant above it, because `get_connection` re-runs the whole block
    whenever `user_version` is lower - so it would go on passing while the migration sat in
    the block with no bump covering it. This branch has already been bitten by exactly that:
    the node ledger's twin was pinned at 14 and went green against a merge that killed its
    own migration. Renumber this line with the constant, never leave it behind.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        import aiosqlite
        from api.database import get_connection, get_db_path, _MIGRATED

        slug = "lv-ledger-upgrade"
        async with get_connection(slug) as conn:
            await conn.execute("DROP TABLE IF EXISTS value_lever_ledger")
            await conn.commit()
        _MIGRATED.discard(slug)
        async with aiosqlite.connect(get_db_path(slug)) as raw:
            await raw.execute("PRAGMA user_version = 18")
            await raw.commit()

        async with get_connection(slug) as conn:
            cur = await conn.execute("PRAGMA table_info(value_lever_ledger)")
            cols = {r[1] for r in await cur.fetchall()}
        assert "lever_id" in cols, "the migration did not reach an existing database"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_lever_migration_leaves_a_table_it_already_finds_alone(
    tmp_path, monkeypatch
):
    """PRAGMA table_info first, and an early return: the migration skips itself rather than
    half-altering a table already there in some other shape. A migration that raises takes
    every later migration in the block down with it, and several fixtures build their tables
    by hand."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        import aiosqlite
        from api.database import _migrate_value_lever_ledger

        async with aiosqlite.connect(tmp_path / "hand-built.db") as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute(
                "CREATE TABLE value_lever_ledger (lever_id TEXT PRIMARY KEY, whatever TEXT)")
            await conn.commit()
            await _migrate_value_lever_ledger(conn)   # must not raise
            cur = await conn.execute("PRAGMA table_info(value_lever_ledger)")
            cols = {r["name"] for r in await cur.fetchall()}
        assert cols == {"lever_id", "whatever"}, "the migration touched a table it found"
    finally:
        get_settings.cache_clear()


# --------------------------------------------------------------------------------------
# register_levers_sync
# --------------------------------------------------------------------------------------

def test_a_levers_id_survives_its_title_being_rewritten(lever_project):
    """The plan's own test, and the whole reason levers needed ids.

    Morgan rewrote all ten titles between live versions 4 and 5 while writing about the same
    ten levers. If the second write here produced a second row, or moved the first, a
    reviewer's send-back on LV-001 would be attached to a lever that no longer exists.
    """
    slug = lever_project
    register_levers_sync(slug, [_lever("LV-001", "Original title")], 1, "morgan")
    register_levers_sync(slug, [_lever("LV-001", "Completely different wording")], 2, "morgan")
    assert list(current_lever_ledger_sync(slug)) == ["LV-001"]
    assert current_lever_ledger_sync(slug)["LV-001"]["title"] == "Original title"


def test_a_lever_that_moves_position_keeps_its_id(lever_project):
    """v3 -> v4 on the live project reordered the same ten titles and changed nothing else.

    Position is not identity, and this is the direction a test keyed on order would pass
    while the product was broken: the ledger must see one lever moved, not two levers
    swapped.
    """
    slug = lever_project
    register_levers_sync(
        slug, [_lever("LV-001", "First"), _lever("LV-002", "Second")], 1, "morgan")
    register_levers_sync(
        slug, [_lever("LV-002", "Second"), _lever("LV-001", "First")], 2, "morgan")
    ledger = current_lever_ledger_sync(slug)
    assert {k: v["title"] for k, v in ledger.items()} == {
        "LV-001": "First", "LV-002": "Second",
    }


def test_registering_returns_how_many_ids_were_added(lever_project):
    """The count is the added ones, never the named ones - it is what the backfill reports."""
    slug = lever_project
    assert register_levers_sync(
        slug, [_lever("LV-001", "One"), _lever("LV-002", "Two")], 1, "morgan") == 2
    assert register_levers_sync(
        slug, [_lever("LV-002", "Two"), _lever("LV-003", "Three")], 2, "morgan") == 1
    assert set(current_lever_ledger_sync(slug)) == {"LV-001", "LV-002", "LV-003"}


def test_a_null_title_raises_rather_than_being_dropped_from_the_batch(lever_project):
    """ON CONFLICT(lever_id) DO NOTHING, never INSERT OR IGNORE.

    INSERT OR IGNORE swallows every constraint violation on the row, not only the key
    conflict it is reached for. With it, the null title below would vanish with no error, no
    row and no signal - and the next write would find LV-009 unregistered and free to hand
    to a different lever. The batchmate assertion is the other half of the same clause: one
    commit for the whole call, so a batch that raises registers none of its members and the
    caller has to say so rather than assume a partial success.
    """
    slug = lever_project
    with pytest.raises(sqlite3.IntegrityError):
        register_levers_sync(
            slug,
            [_lever("LV-008", "Fine"), {"lever_id": "LV-009", "lever": None}],
            1, "morgan",
        )
    ledger = current_lever_ledger_sync(slug)
    assert "LV-009" not in ledger, "a null title was stored - the NOT NULL is not working"
    assert "LV-008" not in ledger, "the batch committed partially"


def test_an_entry_with_no_usable_id_is_skipped_not_raised_on(lever_project):
    """A ledger write is not the place to re-adjudicate the artefact's shape, and raising
    would cost the whole batch over an entry nothing can register anyway. It is not silent
    either - the door reports it, which is the test two sections down."""
    slug = lever_project
    added = register_levers_sync(
        slug,
        [{"lever": "no id at all"}, {"lever_id": "", "lever": "blank"},
         {"lever_id": "   ", "lever": "whitespace"}, {"lever_id": 7, "lever": "an int"},
         "not a dict", _lever("LV-004", "Real")],
        1, "morgan",
    )
    assert added == 1
    assert set(current_lever_ledger_sync(slug)) == {"LV-004"}


def test_an_id_is_stripped_before_it_becomes_a_key(lever_project):
    """' LV-001' and 'LV-001' are the same lever to every human who reads them and two
    different primary keys to SQLite - the one remaining way this table could hold one lever
    twice."""
    slug = lever_project
    register_levers_sync(slug, [_lever("LV-001", "Original")], 1, "morgan")
    register_levers_sync(slug, [_lever(" LV-001 ", "Reworded")], 2, "morgan")
    assert list(current_lever_ledger_sync(slug)) == ["LV-001"]


def test_an_empty_title_is_filled_but_a_real_one_is_never_overwritten(lever_project):
    """A title is display text; the anchor is the contract. A row that arrived with no title
    can acquire one - which is what lets a registration precede a real write - and a row that
    has one keeps it, so a regeneration cannot rewrite the ledger as a side effect."""
    slug = lever_project
    register_levers_sync(
        slug, [{"lever_id": "LV-005", "lever": ""}, _lever("LV-006", "Held")], 1, "morgan")
    register_levers_sync(
        slug, [_lever("LV-005", "Filled in"), _lever("LV-006", "Rewritten")], 2, "morgan")
    ledger = current_lever_ledger_sync(slug)
    assert ledger["LV-005"]["title"] == "Filled in"
    assert ledger["LV-006"]["title"] == "Held"


def test_status_is_the_one_field_a_later_write_may_move(lever_project):
    """The interviews decide a hypothesis; deciding it neither redefines the lever's id nor
    drops it, so status is the carve-out `active` is on the node ledger."""
    slug = lever_project
    register_levers_sync(slug, [_lever("LV-007", "Hypothesis", status="untested")], 1, "morgan")
    assert current_lever_ledger_sync(slug)["LV-007"]["status"] == "untested"

    register_levers_sync(
        slug, [_lever("LV-007", "Hypothesis", status="contradicted")], 2, "morgan")
    assert current_lever_ledger_sync(slug)["LV-007"]["status"] == "contradicted"

    register_levers_sync(
        slug, [_lever("LV-007", "Hypothesis", status="confirmed_unprompted")], 3, "morgan")
    assert current_lever_ledger_sync(slug)["LV-007"]["status"] == "confirmed_unprompted"


def test_an_entry_that_does_not_name_status_leaves_it_alone(lever_project):
    """Not naming status is a different thing from naming it, and the difference is only
    visible on a row whose held value is not the one a blanket write would set.

    Driven in both directions deliberately. The node ledger's twin was written asserting one
    direction only, and a mutation that wrote the field unconditionally passed it, because
    the row already held the value being asserted - an assertion whose subject already holds
    the expected answer cannot fail whatever the code does.
    """
    slug = lever_project
    register_levers_sync(slug, [_lever("LV-010", "A", status="contradicted")], 1, "morgan")
    register_levers_sync(slug, [{"lever_id": "LV-010", "lever": "A"}], 2, "morgan")
    assert current_lever_ledger_sync(slug)["LV-010"]["status"] == "contradicted", \
        "an entry that does not name status reset the row to the default"

    register_levers_sync(slug, [_lever("LV-011", "B", status="untested")], 1, "morgan")
    register_levers_sync(slug, [{"lever_id": "LV-011", "lever": "B"}], 2, "morgan")
    assert current_lever_ledger_sync(slug)["LV-011"]["status"] == "untested", \
        "an entry that does not name status moved the row away from untested"


def test_the_version_and_author_of_the_last_write_are_recorded(lever_project):
    """last_version and last_author are stamped on every id the call names, held or fresh -
    the staleness signal a per-lever review loop reads to tell "the reviewer has seen this
    version" from "the agent has written since"."""
    slug = lever_project
    register_levers_sync(slug, [_lever("LV-001", "One")], 3, "morgan")
    register_levers_sync(
        slug, [_lever("LV-001", "One"), _lever("LV-002", "Two")], 4, "backfill")
    ledger = current_lever_ledger_sync(slug)
    assert (ledger["LV-001"]["last_version"], ledger["LV-001"]["last_author"]) == (4, "backfill")
    assert (ledger["LV-002"]["last_version"], ledger["LV-002"]["last_author"]) == (4, "backfill")


def test_a_fresh_row_starts_pending_with_no_return_to(lever_project):
    """A lever nobody has looked at is pending, not approved - the default must not be the
    permissive one."""
    slug = lever_project
    register_levers_sync(slug, [_lever("LV-001", "One")], 1, "morgan")
    row = current_lever_ledger_sync(slug)["LV-001"]
    assert row["review_status"] == "pending"
    assert row["review_return_to"] is None


def test_registering_against_an_unknown_slug_refuses_without_creating_a_database(
    lever_project
):
    """sqlite3.connect creates the file it is pointed at, so a projects-row check alone
    answers "Project not found" having just materialised an empty database for the slug it is
    denying - one file per guess for anybody probing slugs."""
    from pathlib import Path
    from api.config import get_settings
    created = Path(get_settings().database_dir) / "no-such-project.db"
    with pytest.raises(ValueError, match="Project not found"):
        register_levers_sync("no-such-project", [_lever("LV-001", "One")], 1, "morgan")
    assert not created.exists(), "the refusal materialised a database"


def test_levers_without_ids_reports_positions_not_titles(lever_project):
    """The whole point of the task is that a title does not identify a lever, so the message
    saying "this has no identity" must not use one. Positions are 1-based, matching what an
    agent counting entries in its own array would say."""
    assert levers_without_ids([
        _lever("LV-001", "Has one"), {"lever": "Does not"},
        {"lever_id": "  ", "lever": "Blank"}, _lever("LV-002", "Has one"),
    ]) == [2, 3]
    assert levers_without_ids([]) == []
    assert levers_without_ids(None) == []


# --------------------------------------------------------------------------------------
# The door
# --------------------------------------------------------------------------------------

def test_a_levers_write_through_the_state_tool_registers_them(lever_project):
    """Registration is a side effect of the write, exactly as insert_agent_output_sync
    maintains is_current, and for the same reason: a correctness record an agent has to
    remember to maintain is one that goes missing when a run stops early. Run 32 wrote 41
    scripts, hit the iteration ceiling before its ledger write, and reported completed."""
    slug = lever_project
    out = _write(slug, [
        _lever("LV-001", "Risk-based capital prioritisation", status="untested"),
        _lever("LV-002", "Outcome-based contracting", status="untested"),
    ])
    assert out.startswith("Written to"), out
    assert "WARNING" not in out, out
    ledger = current_lever_ledger_sync(slug)
    assert {k: v["title"] for k, v in ledger.items()} == {
        "LV-001": "Risk-based capital prioritisation",
        "LV-002": "Outcome-based contracting",
    }
    assert ledger["LV-001"]["last_version"] == 1
    assert ledger["LV-001"]["last_author"] == "value_lever_analyst"


def test_a_second_write_registers_the_new_ids_and_keeps_the_old_titles(lever_project):
    """The regeneration case, end to end through the real door: Morgan rewords what she
    already wrote and adds one. The ledger gains the new id and loses nothing - and a lever
    she has dropped is retained rather than forgotten, because every theme, script and
    proposition citing LV-002 resolves through that row."""
    slug = lever_project
    _write(slug, [_lever("LV-001", "First wording"), _lever("LV-002", "Dropped later")])
    out = _write(slug, [
        _lever("LV-001", "Completely different wording"),
        _lever("LV-003", "A genuinely new lever"),
    ])
    assert "WARNING" not in out, out
    ledger = current_lever_ledger_sync(slug)
    assert {k: v["title"] for k, v in ledger.items()} == {
        "LV-001": "First wording",
        "LV-002": "Dropped later",
        "LV-003": "A genuinely new lever",
    }


def test_a_write_whose_levers_carry_no_id_tells_the_agent_so(lever_project):
    """An agent that omits the id must hear about it in the run that omitted it - the tool's
    return string is handed straight back to it, so it can correct itself before the run ends.

    The levers that do carry ids are still registered: the note names what was left out
    rather than refusing the write, because refusing would cost the work the run just did.
    """
    slug = lever_project
    out = _write(slug, [
        _lever("LV-001", "Identified"),
        {"lever": "No id", "status": "untested"},
        {"lever": "Also no id", "status": "untested"},
    ])
    assert out.startswith("Written to"), out
    assert "WARNING" in out, out
    assert "lever_id" in out and "position 2, 3" in out, out
    assert set(current_lever_ledger_sync(slug)) == {"LV-001"}


def test_an_ordinary_write_with_every_id_present_carries_no_warning(lever_project):
    """The negative control for the test above: a message that appeared on every write would
    train the agent to ignore it."""
    slug = lever_project
    out = _write(slug, [_lever("LV-001", "Identified"), _lever("LV-002", "Also identified")])
    assert "WARNING" not in out, out


def test_a_write_that_is_not_an_array_registers_nothing_and_says_so(lever_project):
    """The silent loss path on this key, made loud.

    `value_levers` is a JSON array. An object - `{"value_levers": [...]}`, which is the shape
    every *other* key on this tool takes, and therefore the mistake to expect - was accepted,
    written durably, answered a plain "Written to ...", and left the ledger empty. Every other
    loss path here announces itself in the string CrewAI hands back to the agent: a failed
    registration says so, a lever with no id says so. A guard that is silent where its two
    neighbours are loud is the one an agent learns nothing from, and the run ends with ten
    levers outside the succession guarantee and nothing said.

    The write still lands, deliberately. Refusing it would cost the work the run just did over
    a container, and an outright refusal belongs in `_VALIDATORS` - which has no entry for this
    key precisely because it refuses anything that is *not* a dict.
    """
    slug = lever_project
    out = _write(slug, {"value_levers": [_lever("LV-001", "Wrapped in an object")]})
    assert out.startswith("Written to"), out
    assert "WARNING" in out, out
    assert "must be a JSON array" in out and "dict" in out, out
    assert current_lever_ledger_sync(slug) == {}


def test_the_not_an_array_warning_names_what_was_actually_sent(lever_project):
    """A string is a different mistake from an object and the message says which.

    `type(parsed).__name__` rather than a fixed "not an array": an agent that sent a JSON
    string of an array needs to be told it sent a string, and the two are indistinguishable in
    a message that only says the expected shape.
    """
    slug = lever_project
    out = _write(slug, "LV-001, LV-002")
    assert "WARNING" in out and "str" in out, out
    assert current_lever_ledger_sync(slug) == {}


def test_a_failed_lever_registration_is_reported_to_the_agent_not_swallowed(
    lever_project, monkeypatch
):
    """Never fail a durable write over the ledger - the file and its row are committed by
    then, and telling the agent it failed makes it write again and version a duplicate. But
    the loss must not be silent either: silence is the shape of the defect this whole line of
    work exists to close.
    """
    slug = lever_project

    def _boom(*args, **kwargs):
        raise sqlite3.IntegrityError("NOT NULL constraint failed: value_lever_ledger.title")

    monkeypatch.setattr("agents.tools.sqlite_state.register_levers_sync", _boom)
    out = _write(slug, [_lever("LV-001", "One")])
    assert out.startswith("Written to"), "the write was failed over the ledger"
    assert "WARNING" in out and "lever ledger was not updated" in out, out
    assert current_lever_ledger_sync(slug) == {}


def test_the_write_itself_still_lands_when_the_ledger_does_not(lever_project):
    """The artefact and its agent_outputs row are what the pipeline runs on. A ledger failure
    must cost the row and nothing else."""
    slug = lever_project
    _write(slug, [_lever("LV-001", "One")])
    from agents.tools._db import current_output_path
    path = current_output_path(slug, "value_levers")
    assert path is not None and path.exists()
    assert json.loads(path.read_text())[0]["lever_id"] == "LV-001"


# --------------------------------------------------------------------------------------
# Morgan's instructions
# --------------------------------------------------------------------------------------

def test_morgans_task_tells_her_to_keep_the_id_a_lever_already_has():
    """The ledger can only hold what the artefact names, and the artefact only carries ids
    because Morgan is told to write them. Asserted against the real task text rather than
    described here: a ledger keyed on an id no agent emits is a table of one row.
    """
    from unittest.mock import MagicMock
    from crewai import LLM
    from agents.discovery.value_lever_analyst import (
        create_value_lever_analyst,
        create_value_lever_analyst_task,
    )

    agent = create_value_lever_analyst(slug="test", llm=MagicMock(spec=LLM), tools=[])
    task = create_value_lever_analyst_task(agent=agent, context_tasks=[])
    description = task.description
    assert '"lever_id"' in description, "the schema does not name lever_id"
    assert "key='value_levers'" in description and "operation='read'" in description, \
        "she is never told to read the ids already on record"
    assert "LV-" in description, "the id format is not stated"
    assert "lever_id" in task.expected_output, \
        "the expected output does not require the id"


def test_morgan_declares_reading_her_own_levers():
    """`agents/reads.py` is where what an agent draws on is a fact rather than an
    instruction. She now reads her own output to preserve its ids, and a declaration that
    did not say so would leave the graph reporting an artefact read by nobody."""
    from agents.reads import AGENT_READS
    sources = {read.source for read in AGENT_READS["value_lever_analyst"]}
    assert "value_levers" in sources


# --------------------------------------------------------------------------------------
# The backfill
# --------------------------------------------------------------------------------------

def _seed_levers(slug, levers):
    from agents.tools._db import insert_agent_output_sync
    path = _outputs(slug) / "value_levers.json"
    path.write_text(json.dumps(levers))
    insert_agent_output_sync(slug=slug, agent_name="value_lever_analyst",
                             output_type="value_levers", file_path=str(path))


def test_assigning_ids_never_touches_a_lever_that_already_has_one():
    """The assignment rule, driven directly, because it is the half of the backfill that
    decides whether a re-run can renumber. Pure on purpose: no database, no artefact, no
    filesystem, so the property can be asked of it in every arrangement that matters."""
    from scripts.backfill_value_lever_ledger import assign_lever_ids

    out, assigned = assign_lever_ids(
        [{"lever_id": "LV-004", "lever": "Held"}, {"lever": "New"}], held=set())
    assert [lever["lever_id"] for lever in out] == ["LV-004", "LV-005"]
    assert [a["lever_id"] for a in assigned] == ["LV-005"]

    # Second pass over its own output: nothing left to assign.
    again, assigned_again = assign_lever_ids(out, held={"LV-004", "LV-005"})
    assert [lever["lever_id"] for lever in again] == ["LV-004", "LV-005"]
    assert assigned_again == []


def test_the_next_number_comes_from_the_highest_id_not_from_the_count():
    """A count renumbers the moment the set is not a contiguous run from 1, which is the
    failure this file exists to make impossible.

    **The held set has gaps deliberately, and that is the whole test.** Written first
    against ten contiguous ids, `len(held) + 1` and `max(held) + 1` are the same number, so
    a mutation replacing one with the other passed - the arrangement could not tell the
    right code from the wrong code, which is not a property of the mutation but of the
    fixture. Three ids whose highest is LV-007 separate them: the answer is LV-008, and a
    count would say LV-004 and hand a new lever an id LV-004 has already meant.
    """
    from scripts.backfill_value_lever_ledger import assign_lever_ids

    held = {"LV-001", "LV-002", "LV-007"}
    out, assigned = assign_lever_ids(
        [{"lever_id": "LV-002", "lever": "Survivor"}, {"lever": "Brand new"}], held=held)
    assert [a["lever_id"] for a in assigned] == ["LV-008"]
    assert out[1]["lever_id"] == "LV-008"

    # Two new levers in one pass take consecutive numbers, so the second does not collide
    # with the first - the set the next number is drawn from includes what this call has
    # already handed out.
    _, two = assign_lever_ids([{"lever": "One"}, {"lever": "Two"}], held={"LV-004"})
    assert [a["lever_id"] for a in two] == ["LV-005", "LV-006"]


def test_the_backfill_assigns_ids_writes_them_back_and_is_a_no_op_twice(lever_project):
    """The live case: ten levers with no id at all.

    Run twice deliberately. The second run must assign nothing, register nothing, and write
    no new version of the artefact - and must leave last_version and last_author where the
    first put them, because the backfill filters to ids the ledger does not hold rather than
    relying on ON CONFLICT, and register_levers_sync stamps the version on every id it is
    handed.
    """
    slug = lever_project
    _seed_levers(slug, [
        {"lever": "Risk-based capital prioritisation", "status": "untested"},
        {"lever": "Outcome-based contracting", "status": "untested"},
    ])
    from scripts.backfill_value_lever_ledger import backfill_value_lever_ledger

    dry = backfill_value_lever_ledger(apply=False)
    mine = [p for p in dry["projects"] if p["slug"] == slug]
    assert len(mine) == 1, dry
    assert [a["lever_id"] for a in mine[0]["assigned"]] == ["LV-001", "LV-002"]
    assert mine[0]["registered"] == 0
    assert current_lever_ledger_sync(slug) == {}, "a dry run wrote to the ledger"
    from agents.tools._db import current_output_path
    assert "lever_id" not in current_output_path(slug, "value_levers").read_text(), \
        "a dry run rewrote the artefact"

    applied = backfill_value_lever_ledger(apply=True)
    entry = [p for p in applied["projects"] if p["slug"] == slug][0]
    assert entry["registered"] == 2
    assert entry["rewrote_artefact"] == 2, "the ids were not written back into the artefact"
    ledger = current_lever_ledger_sync(slug)
    assert {k: v["title"] for k, v in ledger.items()} == {
        "LV-001": "Risk-based capital prioritisation",
        "LV-002": "Outcome-based contracting",
    }

    # The live write path moves the row on; the backfill must not drag it back.
    register_levers_sync(slug, [_lever("LV-001", "Reworded")], 9, "morgan")
    again = backfill_value_lever_ledger(apply=True)
    entry = [p for p in again["projects"] if p["slug"] == slug][0]
    assert entry["assigned"] == []
    assert entry["to_register"] == []
    assert entry["registered"] == 0
    assert entry["rewrote_artefact"] is None, "a second run versioned the artefact again"
    row = current_lever_ledger_sync(slug)["LV-001"]
    assert (row["last_version"], row["last_author"]) == (9, "morgan")


def test_the_backfilled_artefact_is_what_morgan_reads_next(lever_project):
    """The ids have to reach the artefact, not only the ledger. Morgan holds no tool that can
    see the ledger - she reads `value_levers` through SQLiteStateTool - so ids written only
    to the table would be invisible to the one agent that has to preserve them, and her next
    write would name none of them.
    """
    slug = lever_project
    _seed_levers(slug, [{"lever": "Risk-based capital prioritisation"}])
    from scripts.backfill_value_lever_ledger import backfill_value_lever_ledger
    backfill_value_lever_ledger(apply=True)

    tool = SQLiteStateTool(slug=slug, agent_name="value_lever_analyst", run_id=1)
    read_back = json.loads(tool._run(
        operation="read", key="value_levers", agent_name="value_lever_analyst"))
    assert read_back[0]["lever_id"] == "LV-001"
    assert read_back[0]["lever"] == "Risk-based capital prioritisation"


def test_the_backfill_reads_the_levers_the_ledger_marks_current(lever_project):
    """Through agent_outputs.is_current, never the glob. The highest number on disk is a
    different answer after a revert, and assigning ids against a version the project has
    deliberately reverted away from would attach them to levers nobody is looking at."""
    slug = lever_project
    _seed_levers(slug, [{"lever": "The reverted wording"}])
    _seed_levers(slug, [{"lever": "First"}, {"lever": "Second"}])
    # Revert to v1: the newer file stays on disk, and is no longer what the project runs on.
    from api.config import get_settings
    from pathlib import Path
    with contextlib.closing(
        sqlite3.connect(Path(get_settings().database_dir) / f"{slug}.db")
    ) as conn:
        conn.execute("UPDATE agent_outputs SET is_current=0 WHERE output_type='value_levers'")
        conn.execute(
            "UPDATE agent_outputs SET is_current=1"
            " WHERE output_type='value_levers' AND version=1")
        conn.commit()

    from scripts.backfill_value_lever_ledger import backfill_value_lever_ledger
    dry = backfill_value_lever_ledger(apply=False)
    entry = [p for p in dry["projects"] if p["slug"] == slug][0]
    assert entry["levers_version"] == 1
    assert [a["title"] for a in entry["assigned"]] == ["The reverted wording"]


def test_the_backfill_skips_a_database_that_is_not_a_project(lever_project):
    """get_connection migrates any slug it is handed, so a backfill that walked data/ through
    it would create databases for slugs that are not projects. Everything is opened read-only,
    and a file that does not claim its own filename as a project is skipped."""
    from pathlib import Path
    from api.config import get_settings
    database_dir = Path(get_settings().database_dir)

    with contextlib.closing(sqlite3.connect(database_dir / "probe.db")) as conn:
        conn.execute("CREATE TABLE something (x TEXT)")
        conn.commit()
    with contextlib.closing(
        sqlite3.connect(database_dir / "lever-ledger-test.backup.db")
    ) as conn:
        conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT)")
        conn.execute("INSERT INTO projects (slug) VALUES ('lever-ledger-test')")
        conn.commit()

    from scripts.backfill_value_lever_ledger import backfill_value_lever_ledger
    report = backfill_value_lever_ledger(apply=False)
    skipped = {s["file"]: s["reason"] for s in report["skipped"]}
    assert "probe.db" in skipped
    assert "not a project database" in skipped["probe.db"]
    assert "lever-ledger-test.backup.db" in skipped
    assert "a copy or backup" in skipped["lever-ledger-test.backup.db"]
    assert not any(p["slug"] == "probe" for p in report["projects"])


def test_the_backfill_skips_a_project_whose_database_has_no_ledger_table(lever_project):
    """The table arrives through the migration block. Materialising it here would put schema
    creation in the one file that deliberately migrates nothing - and a silent skip would
    leave an operator believing a project had been backfilled when it had not."""
    from pathlib import Path
    from api.config import get_settings
    database_dir = Path(get_settings().database_dir)
    with contextlib.closing(sqlite3.connect(database_dir / "unmigrated.db")) as conn:
        conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT)")
        conn.execute("INSERT INTO projects (slug) VALUES ('unmigrated')")
        conn.commit()

    from scripts.backfill_value_lever_ledger import backfill_value_lever_ledger
    report = backfill_value_lever_ledger(apply=False)
    skipped = {s["file"]: s["reason"] for s in report["skipped"]}
    assert "unmigrated.db" in skipped
    assert "no value_lever_ledger table" in skipped["unmigrated.db"]
