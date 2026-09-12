# tests/test_item_reviews.py
"""Recording a review of one value chain node or one value lever, and what the record does.

The two ledgers and the injection that reads them landed first; `discovery_review_service`
said of itself that it read "a state only a hand-written row or a backfill can reach". This
is the recorder that reaches it, and the properties below are the ones the ledgers were built
expecting.

**The stamp is the load-bearing one.** A send-back clears when the agent writes past the
version the reviewer read, and nothing else clears it - so a recorder that sets
`review_status` and omits `reviewed_at_version` produces a send-back injected into every
subsequent run for ever. Task 3 chose that failure direction deliberately, over the silent
inverse, and said the recorder owes the stamp on **both** doors. It is asserted here on both,
and asserted structurally as well: `record_item_review` takes no version argument, so there
is no parameter for a door to forget.

Every test is scoped to the slug its fixture created and to rows that fixture inserted -
never a global count and never a hardcoded id in a shared database, per CLAUDE.md's rerun
trap. The db file is removed on both sides because conftest points DATABASE_DIR at a
persistent /tmp path.
"""
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import get_connection
from api.services.discovery_review_service import (
    levers_awaiting_regeneration,
    nodes_awaiting_regeneration,
)
from api.services.item_review_service import (
    AlreadyApprovedError,
    NotYetReviewedError,
    item_ledger_rows,
    item_review_count,
    record_item_review,
)

SLUG = "item-review-test"


@pytest_asyncio.fixture
async def seeded():
    """One project, one node (3.3.3) and one lever (LV-001), both at version 3.

    Both rows start `pending` with no reviews, which is what registration leaves behind -
    `register_nodes_sync` and `register_levers_sync` write the item's own fields and never
    touch review state.
    """
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)

    async with get_connection(SLUG) as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES (?)", (SLUG,))
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (SLUG,))
        project_id = (await cur.fetchone())["id"]
        await conn.execute(
            "INSERT INTO value_chain_ledger"
            " (node_id, project_id, label, level, last_version, last_author)"
            " VALUES ('3.3.3', ?, 'Mains renewal planning', 'L3', 3, 'alex')",
            (project_id,),
        )
        await conn.execute(
            "INSERT INTO value_lever_ledger"
            " (lever_id, project_id, title, status, last_version, last_author)"
            " VALUES ('LV-001', ?, 'Risk-based capital prioritisation', 'untested', 3,"
            "         'morgan')",
            (project_id,),
        )
        await conn.commit()

    yield SLUG, project_id

    db_path.unlink(missing_ok=True)
    get_settings.cache_clear()


def _may_review():
    """Grant the content gate for the duration of a `with` block.

    Patched where the names are looked up - `api.routers.item_reviews` - and not where they
    are defined, because the router binds its own references with `from ... import`.
    CLAUDE.md records four crew tests that patched the definition site and passed for the
    wrong reason.
    """
    return patch.multiple(
        "api.routers.item_reviews",
        caller_may_contribute=AsyncMock(return_value=True),
        caller_may_approve=AsyncMock(return_value=True),
    )


# ══════════════════════════════════════════════════════════════════════════════════════
# The migration
# ══════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_database_at_version_20_gains_the_item_reviews_table(tmp_path, monkeypatch):
    """A database pinned at the version immediately below the constant gains the table.

    The literal 20, not `_SCHEMA_VERSION - 1`. The expression is always "the version below the
    constant" and therefore passes under any constant at all, including one that never moved -
    which is the whole failure this shape exists to catch. A database stamped at any older
    number is re-migrated by `get_connection` regardless, so such a test proves the migration
    *function* works and never proves the **bump** covers it. That is the exact defect this
    branch nearly shipped when master moved from 15 to 17 underneath it: one digit between a
    test of the bump and a test of nothing.

    The stamp is written on a raw connection, after the `get_connection` that created the file
    has closed: `get_connection` writes `PRAGMA user_version = _SCHEMA_VERSION` on its way out
    when it migrates, so setting it inside that block would be overwritten.
    """
    import aiosqlite

    from api.database import _MIGRATED, get_db_path

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    slug = "version-20-item-reviews"
    async with get_connection(slug) as conn:
        await conn.execute("DROP TABLE IF EXISTS item_reviews")
        await conn.commit()
    _MIGRATED.discard(slug)
    async with aiosqlite.connect(get_db_path(slug)) as raw:
        await raw.execute("PRAGMA user_version = 20")
        await raw.commit()

    async with get_connection(slug) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='item_reviews'"
        )
        assert await cur.fetchone() is not None
    get_settings.cache_clear()


# ══════════════════════════════════════════════════════════════════════════════════════
# The stamp - what makes a send-back clear
# ══════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_recorder_takes_no_version_argument(seeded):
    """The stamp is read off the row, so no door can pass the wrong one or omit it.

    `record_script_review` takes `at_version` and its single door fills it correctly; there
    are two doors here, and Task 3's handoff asked for the stamp on both. A parameter is the
    thing that gets forgotten - CLAUDE.md's `update_project_config` entry is six carry-through
    lines of exactly this shape, five of which could be mutated with a green suite. Asserted
    on the signature rather than trusted to the docstring, so reintroducing the parameter
    fails here rather than silently reopening the hole.
    """
    params = inspect.signature(record_item_review).parameters
    assert "at_version" not in params
    assert "reviewed_at_version" not in params


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,item_id,id_column,table",
    [("node", "3.3.3", "node_id", "value_chain_ledger"),
     ("lever", "LV-001", "lever_id", "value_lever_ledger")],
)
async def test_a_send_back_stamps_the_version_the_reviewer_read(
    seeded, kind, item_id, id_column, table
):
    """reviewed_at_version comes out equal to last_version, in the same write.

    Both kinds, separately parametrised rather than asserted through one shared helper on one
    of them: the recorder is written once over `ITEM_LEDGERS`, which is precisely the shape
    where one kind's test covers the other's bug.
    """
    slug, project_id = seeded
    async with get_connection(slug) as conn:
        row = await record_item_review(
            conn, project_id=project_id, kind=kind, item_id=item_id, reviewer="sam",
            decision="changes_requested", notes="This is the wrong altitude.",
            return_to="agent",
        )
    assert row["review_status"] == "changes_requested"
    assert row["review_return_to"] == "agent"
    assert row["reviewed_at_version"] == 3
    assert row["last_version"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,item_id",
    [("node-ledger", "3.3.3"), ("lever-ledger", "LV-001")],
)
async def test_neither_review_door_forgets_the_stamp(client, seeded, path, item_id):
    """Both doors, over HTTP, because "both review doors must reach it" is about the doors.

    A test of the service alone cannot see a door that assembles its own UPDATE, and this
    codebase has shipped that exact shape - a property tested one layer away from where it
    holds, five times by CLAUDE.md's count.
    """
    slug, _ = seeded
    with _may_review():
        r = await client.post(
            f"/projects/{slug}/{path}/{item_id}/review",
            json={"decision": "changes_requested", "return_to": "agent",
                  "notes": "Reads as an L3 task, not an L2 decision."},
        )
    assert r.status_code == 200, r.text
    assert r.json()["reviewed_at_version"] == 3


@pytest.mark.asyncio
async def test_a_send_back_reaches_the_agent_until_the_agent_writes_and_then_stops(seeded):
    """The whole point of the stamp, driven end to end against the real registration path.

    Before: the node is awaiting Alex. After `register_nodes_sync` names it again - which is
    what any run of his does - `last_version` has moved past `reviewed_at_version` and the row
    drops out. Nothing calls a close-out; the evidence *is* the write.

    **What clears it is any run, not an addressed note.** Alex rebuilds the whole chain every
    time and `register_nodes_sync` stamps `last_version` on every id the call names, so this
    passes whether or not he changed 3.3.3 at all. That is the ledger's honest reach today and
    the surface says so rather than implying otherwise - see NodeReviewPanel's own note.
    """
    from agents.tools._db import register_nodes_sync

    slug, project_id = seeded
    async with get_connection(slug) as conn:
        await record_item_review(
            conn, project_id=project_id, kind="node", item_id="3.3.3", reviewer="sam",
            decision="changes_requested", notes="Wrong altitude.", return_to="agent",
        )
        awaiting = await nodes_awaiting_regeneration(conn, project_id=project_id)
    assert [r["node_id"] for r in awaiting] == ["3.3.3"]

    register_nodes_sync(
        slug,
        [{"id": "3.3.3", "label": "Mains renewal planning", "level": "L3", "active": True}],
        4, "alex",
    )

    async with get_connection(slug) as conn:
        awaiting = await nodes_awaiting_regeneration(conn, project_id=project_id)
    assert awaiting == []


@pytest.mark.asyncio
async def test_a_lever_send_back_clears_the_same_way(seeded):
    """The mirror, against `register_levers_sync`, for the reason the parametrised test above
    gives: one recorder over two ledgers is where one kind's test covers the other's bug."""
    from agents.tools._db import register_levers_sync

    slug, project_id = seeded
    async with get_connection(slug) as conn:
        await record_item_review(
            conn, project_id=project_id, kind="lever", item_id="LV-001", reviewer="sam",
            decision="changes_requested", notes="Not a lever, an outcome.", return_to="agent",
        )
        awaiting = await levers_awaiting_regeneration(conn, project_id=project_id)
    assert [r["lever_id"] for r in awaiting] == ["LV-001"]

    register_levers_sync(
        slug, [{"lever_id": "LV-001", "lever": "Reworded entirely"}], 4, "morgan"
    )

    async with get_connection(slug) as conn:
        awaiting = await levers_awaiting_regeneration(conn, project_id=project_id)
    assert awaiting == []


@pytest.mark.asyncio
async def test_a_plain_review_also_records_the_version_it_was_read_at(seeded):
    """Stamped on every decision, not only on a send-back.

    The staleness indicator a reviewer reads - "changed since v3 -> v7" - is this same number,
    and a missing stamp on a plain `reviewed` renders a tick against content nobody has read.
    """
    slug, project_id = seeded
    async with get_connection(slug) as conn:
        row = await record_item_review(
            conn, project_id=project_id, kind="node", item_id="3.3.3", reviewer="sam",
            decision="reviewed",
        )
    assert row["review_status"] == "reviewed"
    assert row["reviewed_at_version"] == 3
    assert row["review_return_to"] is None


@pytest.mark.asyncio
async def test_a_row_the_agent_has_never_written_stamps_zero_rather_than_null(seeded):
    """last_version is nullable, and NULL is the one value the awaiting query reads as
    "no recorder has ever touched this row". Writing 0 says "read at the beginning of time",
    which clears correctly the moment the agent first writes; leaving NULL would leave the
    row indistinguishable from one no recorder had reached.
    """
    slug, project_id = seeded
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO value_chain_ledger (node_id, project_id, label) "
            "VALUES ('9.9.9', ?, 'Backfilled, never written')", (project_id,)
        )
        await conn.commit()
        row = await record_item_review(
            conn, project_id=project_id, kind="node", item_id="9.9.9", reviewer="sam",
            decision="changes_requested", notes="Still wrong.", return_to="agent",
        )
    assert row["last_version"] is None
    assert row["reviewed_at_version"] == 0


# ══════════════════════════════════════════════════════════════════════════════════════
# The note, and where it goes
# ══════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_reviewers_words_reach_the_agents_block(seeded):
    """The note joins the awaiting-the-agent SELECT and reaches the injected prompt.

    Before `item_reviews` existed the block named the id and nothing else, and the reviewer's
    sentence reached the same prompt only through `_fetch_change_requests`. This is the
    addition Task 3 predicted, asserted where it lands - in the block an agent is actually
    handed, not only in the dict the query returns.
    """
    from api.services.run_service import _pending_discovery_revisions

    slug, project_id = seeded
    async with get_connection(slug) as conn:
        await record_item_review(
            conn, project_id=project_id, kind="node", item_id="3.3.3", reviewer="sam",
            decision="changes_requested", return_to="agent",
            notes="This belongs at L2 - it is a decision, not a task.",
        )
    block = await _pending_discovery_revisions(slug, "value_chain_mapper")
    assert "3.3.3" in block
    assert "This belongs at L2 - it is a decision, not a task." in block


@pytest.mark.asyncio
async def test_a_levers_note_reaches_morgan_and_not_alex(seeded):
    """The note is scoped by `item_kind`, so Alex's block never carries Morgan's sentence.

    The half that fails silently is the second one: a block reaching the agent it should is
    visible; a block also reaching the agent it should not is a task one paragraph longer that
    nothing records.
    """
    from api.services.run_service import _pending_discovery_revisions

    slug, project_id = seeded
    async with get_connection(slug) as conn:
        await record_item_review(
            conn, project_id=project_id, kind="lever", item_id="LV-001", reviewer="sam",
            decision="changes_requested", return_to="agent",
            notes="Monetised risk scoring is the mechanism, not the lever.",
        )
    morgan = await _pending_discovery_revisions(slug, "value_lever_analyst")
    alex = await _pending_discovery_revisions(slug, "value_chain_mapper")
    assert "Monetised risk scoring is the mechanism, not the lever." in morgan
    assert alex == ""


@pytest.mark.asyncio
async def test_only_the_most_recent_note_is_carried_and_the_row_is_not_duplicated(seeded):
    """Two reviews on one node produce one line carrying the later note.

    A join rather than a correlated subquery would have returned the node once per review
    event, so the agent would be told twice about one node - the fan-out defect
    `_fetch_change_requests` deduplicates against, arriving by a different route.
    """
    slug, project_id = seeded
    async with get_connection(slug) as conn:
        await record_item_review(
            conn, project_id=project_id, kind="node", item_id="3.3.3", reviewer="sam",
            decision="changes_requested", return_to="agent", notes="First thought.",
        )
        await record_item_review(
            conn, project_id=project_id, kind="node", item_id="3.3.3", reviewer="alexis",
            decision="changes_requested", return_to="agent", notes="Second thought.",
        )
        awaiting = await nodes_awaiting_regeneration(conn, project_id=project_id)
    assert len(awaiting) == 1
    assert awaiting[0]["notes"] == "Second thought."


@pytest.mark.asyncio
async def test_a_row_with_no_review_event_still_appears_with_no_note(seeded):
    """A hand-written or backfilled row joins NULL and must not drop out of the result.

    The send-back is the state that matters; the note is what came with it, and a row that
    reached this state by some other route is still owed a regeneration.
    """
    slug, project_id = seeded
    async with get_connection(slug) as conn:
        await conn.execute(
            "UPDATE value_chain_ledger SET review_status='changes_requested',"
            " review_return_to='agent' WHERE node_id='3.3.3'"
        )
        await conn.commit()
        awaiting = await nodes_awaiting_regeneration(conn, project_id=project_id)
    assert [r["node_id"] for r in awaiting] == ["3.3.3"]
    assert awaiting[0]["notes"] is None


# ══════════════════════════════════════════════════════════════════════════════════════
# The vocabulary, and the approval gate
# ══════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_an_approval_does_not_satisfy_its_own_gate(seeded):
    """An item nobody has read cannot be approved, and an approval is not a reading of it.

    Both halves: the refusal, and - after one approval has been forced through - that the
    count still reads zero, so a second item could not be approved on the strength of it.
    """
    slug, project_id = seeded
    async with get_connection(slug) as conn:
        with pytest.raises(NotYetReviewedError):
            await record_item_review(
                conn, project_id=project_id, kind="node", item_id="3.3.3",
                reviewer="sam", decision="approved",
            )
        await record_item_review(
            conn, project_id=project_id, kind="node", item_id="3.3.3", reviewer="sam",
            decision="approved", forced=True,
        )
        assert await item_review_count(
            conn, project_id=project_id, kind="node", item_id="3.3.3"
        ) == 0


@pytest.mark.asyncio
async def test_approving_twice_is_refused(seeded):
    """Once per item, and it must be sent back before it can be approved again.

    Classified on the exception's type, not on the wording of its message.
    """
    slug, project_id = seeded
    async with get_connection(slug) as conn:
        await record_item_review(
            conn, project_id=project_id, kind="lever", item_id="LV-001", reviewer="sam",
            decision="reviewed",
        )
        await record_item_review(
            conn, project_id=project_id, kind="lever", item_id="LV-001", reviewer="sam",
            decision="approved",
        )
        with pytest.raises(AlreadyApprovedError):
            await record_item_review(
                conn, project_id=project_id, kind="lever", item_id="LV-001",
                reviewer="sam", decision="approved",
            )


@pytest.mark.asyncio
async def test_a_send_back_must_name_its_target(seeded):
    """Both defaults are wrong, so there is no default. To the agent it regenerates the item
    a reviewer is about to re-read; to the reviewer it silently drops a request for
    regeneration."""
    slug, project_id = seeded
    async with get_connection(slug) as conn:
        with pytest.raises(ValueError):
            await record_item_review(
                conn, project_id=project_id, kind="node", item_id="3.3.3", reviewer="sam",
                decision="changes_requested", notes="Wrong.",
            )


@pytest.mark.asyncio
async def test_edited_is_not_a_decision_this_ledger_accepts(seeded):
    """Three exits, not the script ledger's four, and refused rather than merely unoffered.

    `edited` records that a reader changed the thing in front of them. Levers are review-only
    by decision and the value chain model has its own editor and its own workflow, so there is
    nothing here to edit - and a decision no surface can produce would arrive in
    `review_status` as a state the reviewer could never explain.
    """
    slug, project_id = seeded
    async with get_connection(slug) as conn:
        with pytest.raises(ValueError):
            await record_item_review(
                conn, project_id=project_id, kind="node", item_id="3.3.3", reviewer="sam",
                decision="edited",
            )


@pytest.mark.asyncio
async def test_an_unknown_item_kind_is_refused_rather_than_keyed_blindly(seeded):
    """A ValueError, so the router answers 422 - a KeyError would reach the client as a 500."""
    slug, project_id = seeded
    async with get_connection(slug) as conn:
        with pytest.raises(ValueError):
            await record_item_review(
                conn, project_id=project_id, kind="theme", item_id="T-001",
                reviewer="sam", decision="reviewed",
            )


@pytest.mark.asyncio
async def test_a_node_and_a_lever_sharing_an_id_do_not_share_review_events(seeded):
    """item_kind is why the events live in one table safely.

    Node ids and lever ids are different namespaces, so nothing stops a project holding the
    same string in both. Without the discriminator a reviewer's note on one would be counted
    against, and carried into the prompt for, the other.
    """
    slug, project_id = seeded
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO value_chain_ledger (node_id, project_id, label, last_version)"
            " VALUES ('X-1', ?, 'A node called X-1', 2)", (project_id,))
        await conn.execute(
            "INSERT INTO value_lever_ledger (lever_id, project_id, title, last_version)"
            " VALUES ('X-1', ?, 'A lever called X-1', 2)", (project_id,))
        await conn.commit()
        await record_item_review(
            conn, project_id=project_id, kind="node", item_id="X-1", reviewer="sam",
            decision="reviewed",
        )
        assert await item_review_count(
            conn, project_id=project_id, kind="node", item_id="X-1") == 1
        assert await item_review_count(
            conn, project_id=project_id, kind="lever", item_id="X-1") == 0
        cur = await conn.execute(
            "SELECT review_status FROM value_lever_ledger WHERE lever_id='X-1'")
        assert (await cur.fetchone())[0] == "pending"


# ══════════════════════════════════════════════════════════════════════════════════════
# The ledger reads
# ══════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_ledger_read_carries_a_count_that_excludes_approvals(seeded):
    """What the surface disables Approve on until the item has actually been read."""
    slug, project_id = seeded
    async with get_connection(slug) as conn:
        await record_item_review(
            conn, project_id=project_id, kind="node", item_id="3.3.3", reviewer="sam",
            decision="reviewed",
        )
        await record_item_review(
            conn, project_id=project_id, kind="node", item_id="3.3.3", reviewer="alexis",
            decision="approved",
        )
        rows = await item_ledger_rows(conn, project_id=project_id, kind="node")
    mine = [r for r in rows if r["node_id"] == "3.3.3"]
    assert len(mine) == 1
    assert mine[0]["review_count"] == 1
    assert mine[0]["review_status"] == "approved"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,id_key,item_id",
    [("node-ledger", "node_id", "3.3.3"), ("lever-ledger", "lever_id", "LV-001")],
)
async def test_each_ledger_door_returns_its_own_ledger(client, seeded, path, id_key, item_id):
    """Scoped to the row this fixture created, never to a count over the table."""
    slug, _ = seeded
    r = await client.get(f"/projects/{slug}/{path}")
    assert r.status_code == 200, r.text
    rows = {row[id_key]: row for row in r.json()}
    assert item_id in rows
    assert rows[item_id]["review_count"] == 0


# ══════════════════════════════════════════════════════════════════════════════════════
# Authority
# ══════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,item_id", [("node-ledger", "3.3.3"), ("lever-ledger", "LV-001")],
)
async def test_recording_a_review_needs_contribute_authority(client, seeded, path, item_id):
    """Asserted by denying the gate rather than by accepting whatever the door returns: a
    test that accepted either 200 or 403 would pass with the gate deleted.

    Both doors, because a gate copied into two handlers is a gate that holds in one of them -
    which is what CLAUDE.md means by an approval guard tested for one of its two conditions.
    """
    slug, _ = seeded
    with patch("api.routers.item_reviews.caller_may_contribute",
               new=AsyncMock(return_value=False)):
        r = await client.post(f"/projects/{slug}/{path}/{item_id}/review",
                              json={"decision": "reviewed"})
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,item_id", [("node-ledger", "3.3.3"), ("lever-ledger", "LV-001")],
)
async def test_approving_asks_for_approver_and_reviewing_asks_for_either(
    client, seeded, path, item_id
):
    """Which gate is asked is the rule; the status code is only its shadow.

    A contributor may record a reading and may not approve, and the two questions are asked of
    different predicates - so a door that asked `caller_may_contribute` for both would pass a
    test that only drove the reviewing half.
    """
    slug, _ = seeded
    contribute_only = patch.multiple(
        "api.routers.item_reviews",
        caller_may_contribute=AsyncMock(return_value=True),
        caller_may_approve=AsyncMock(return_value=False),
    )
    with contribute_only:
        r = await client.post(f"/projects/{slug}/{path}/{item_id}/review",
                              json={"decision": "reviewed"})
        assert r.status_code == 200, r.text
        r = await client.post(f"/projects/{slug}/{path}/{item_id}/review",
                              json={"decision": "approved"})
        assert r.status_code == 403, r.text
    with _may_review():
        r = await client.post(f"/projects/{slug}/{path}/{item_id}/review",
                              json={"decision": "approved"})
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_a_send_back_with_no_target_is_a_422_and_a_double_approval_is_a_409(
    client, seeded
):
    """The two refusal classes the router tells apart by exception type.

    A malformed request and a conflict with stored state owe the caller different answers, and
    branching on the wording of a message would silently reclassify one as the other the
    moment it was reworded.
    """
    slug, _ = seeded
    with _may_review():
        r = await client.post(f"/projects/{slug}/node-ledger/3.3.3/review",
                              json={"decision": "changes_requested", "notes": "Wrong."})
        assert r.status_code == 422, r.text
        await client.post(f"/projects/{slug}/node-ledger/3.3.3/review",
                          json={"decision": "reviewed"})
        await client.post(f"/projects/{slug}/node-ledger/3.3.3/review",
                          json={"decision": "approved"})
        r = await client.post(f"/projects/{slug}/node-ledger/3.3.3/review",
                              json={"decision": "approved"})
        assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_an_id_the_ledger_does_not_hold_is_refused(client, seeded):
    """A review against a node that does not exist must not create one."""
    slug, project_id = seeded
    with _may_review():
        r = await client.post(f"/projects/{slug}/node-ledger/8.8.8/review",
                              json={"decision": "reviewed"})
    assert r.status_code == 422, r.text
    async with get_connection(slug) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM value_chain_ledger WHERE node_id='8.8.8' AND project_id=?",
            (project_id,))
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,kind,item_id",
    [("node-ledger", "node", "3.3.3"), ("lever-ledger", "lever", "LV-001")],
)
async def test_a_send_back_notifies_the_reviewers(client, seeded, path, kind, item_id):
    """The same audience a script send-back reaches, for the same reason: the agent will
    regenerate the item and they will have to read it again.

    Patched on the module attribute rather than on a name bound at import, because the router
    imports it inside the handler - which is itself deliberate, so a notification module that
    fails to import cannot take the review door down with it.
    """
    slug, _ = seeded
    notify = AsyncMock()
    with _may_review(), patch(
        "api.services.commit_notify_service.notify_item_sent_back", new=notify
    ):
        r = await client.post(
            f"/projects/{slug}/{path}/{item_id}/review",
            json={"decision": "changes_requested", "return_to": "agent",
                  "notes": "Needs rework."},
        )
    assert r.status_code == 200, r.text
    notify.assert_awaited_once_with(slug, kind, item_id, "agent", "Needs rework.")


@pytest.mark.asyncio
async def test_a_failed_notification_does_not_undo_a_recorded_review(client, seeded):
    """The review is committed before the notification is attempted, so a mail failure must
    not turn a recorded review into a failed request - and must not leave the reviewer
    thinking their send-back was refused when the agent will act on it.
    """
    slug, project_id = seeded
    with _may_review(), patch(
        "api.services.commit_notify_service.notify_item_sent_back",
        new=AsyncMock(side_effect=RuntimeError("no mail today")),
    ):
        r = await client.post(
            f"/projects/{slug}/node-ledger/3.3.3/review",
            json={"decision": "changes_requested", "return_to": "agent",
                  "notes": "Needs rework."},
        )
    assert r.status_code == 200, r.text
    async with get_connection(slug) as conn:
        awaiting = await nodes_awaiting_regeneration(conn, project_id=project_id)
    assert [row["node_id"] for row in awaiting] == ["3.3.3"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [("get", "node-ledger"), ("get", "lever-ledger")],
)
async def test_every_door_asks_the_membership_floor(client, seeded, method, path):
    """`check_project_access` on every door, reads included.

    The enumeration CLAUDE.md describes counts routes whose path holds `{slug}` and asks
    whether each calls the floor; these four are new members of that count, and the two reads
    are the ones an authority test is most likely to skip because they refuse nothing else.
    """
    slug, _ = seeded
    from fastapi import HTTPException

    with patch("api.routers.item_reviews.check_project_access",
               new=AsyncMock(side_effect=HTTPException(status_code=403, detail="no"))):
        r = await getattr(client, method)(f"/projects/{slug}/{path}")
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,item_id", [("node-ledger", "3.3.3"), ("lever-ledger", "LV-001")],
)
async def test_every_write_door_asks_the_membership_floor(client, seeded, path, item_id):
    """The floor is asked before the content gate, so a non-member is refused as a non-member
    rather than as somebody whose roles happened to come back empty."""
    slug, _ = seeded
    from fastapi import HTTPException

    with patch("api.routers.item_reviews.check_project_access",
               new=AsyncMock(side_effect=HTTPException(status_code=403, detail="no"))), \
            _may_review():
        r = await client.post(f"/projects/{slug}/{path}/{item_id}/review",
                              json={"decision": "reviewed"})
    assert r.status_code == 403, r.text
