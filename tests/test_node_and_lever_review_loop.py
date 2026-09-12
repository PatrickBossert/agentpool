# tests/test_node_and_lever_review_loop.py
"""The whole loop, at the size the live project is: a reviewer sends one node back, the next
run of Alex's is told about that node and no other, and the other eighty-eight ledger rows are
byte-identical.

Every part of this is asserted somewhere else, one row at a time and one layer at a time -
`test_item_reviews.py` for the recorder, `test_discovery_revision_injection.py` for the
routing, `test_value_chain_ledger.py` for the registration. This file drives the arc those
tests each hold one link of, over the real doors, against eighty-nine nodes and ten levers.
The point of the size is the property: **"it leaves everything else alone" is not a claim a
fixture holding one row can make**, and it is the claim the whole design rests on. Maya's loop
is trusted because run 37 regenerated SC-014 and left eighty-five scripts byte-identical; this
is the same evidence for Alex and Morgan, taken before their first real run rather than after.

**What is expected to move, said here so a correct run is not read as a leak.** The byte
comparison below is *within the ledger*. Alex writes `value_chain_model`,
`value_chain_registry`, `value_chain_summary` and `value_chain_tree`, and the last two are
derived from the first - a single-node change legitimately rewrites both of them end to end.
The ledger is where "only this node moved" is a question with an answer, which is the reason
the registry became a table.

The database directory is a `tmp_path` of this module's own, with `get_settings.cache_clear()`
on both sides: `conftest` points `DATABASE_DIR` at a `/tmp` path that persists between runs,
and these tests hold ids (`3.3.3`, `LV-003`) that would poison it.
"""
import hashlib

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from api.config import get_settings
from api.database import get_connection
from api.services.run_service import _pending_discovery_revisions

SLUG = "node-lever-loop"

NODE_HEADER = "VALUE CHAIN NODES SENT BACK FOR REVISION"
LEVER_HEADER = "VALUE LEVERS SENT BACK FOR REVISION"


def _chain() -> list[dict]:
    """Eighty-nine activities in the shape CLAUDE.md's anchoring section describes.

    `0` is the organisation, `0.A` and `0.S` its organisation-level role nodes, each L1 entity
    carries `<L1>.C` and `<L1>.F`, and L2 and L3 belong to exactly one L1. The count is the
    live number on `sp-gs-am` and is asserted rather than trusted, because "the other 88" is
    arithmetic over it: a generator quietly producing 87 would leave every assertion below
    true and the headline claim unproven.
    """
    activities = [
        {"id": "0", "label": "Water and wastewater services", "level": "L0", "active": True},
        {"id": "0.A", "label": "Audit and assurance", "level": "L0", "active": True},
        {"id": "0.S", "label": "Corporate services frontline", "level": "L0", "active": True},
    ]
    for l1 in range(1, 5):
        activities.append(
            {"id": f"{l1}", "label": f"Entity {l1}", "level": "L1", "active": True}
        )
        for role in ("C", "F"):
            activities.append(
                {"id": f"{l1}.{role}", "label": f"Entity {l1} {role}", "level": "L1",
                 "active": True}
            )
        for l2 in range(1, 4):
            activities.append(
                {"id": f"{l1}.{l2}", "label": f"Capability {l1}.{l2}", "level": "L2",
                 "active": True}
            )
            for l3 in range(1, 6):
                activities.append(
                    {"id": f"{l1}.{l2}.{l3}", "label": f"Activity {l1}.{l2}.{l3}",
                     "level": "L3", "active": True}
                )
    # Two L3s beyond the uniform shape, because a real chain is not uniform and eighty-nine
    # is not divisible into one. They make the count the live one.
    activities.append(
        {"id": "1.1.6", "label": "Activity 1.1.6", "level": "L3", "active": True}
    )
    activities.append(
        {"id": "2.1.6", "label": "Activity 2.1.6", "level": "L3", "active": True}
    )
    return activities


def _levers() -> list[dict]:
    """Ten levers, the number `sp-gs-am` holds, each with the permanent id Task 2 gave them."""
    return [
        {"lever_id": f"LV-{n:03d}", "lever": f"Lever number {n}", "status": "untested"}
        for n in range(1, 11)
    ]


@pytest_asyncio.fixture
async def chain(tmp_path, monkeypatch):
    """A project whose two ledgers were filled by the **real registration path** at version 1.

    `register_nodes_sync` and `register_levers_sync` rather than hand-written INSERTs: this
    file is about what happens between a reviewer and the agent's next write, and both ends of
    that are those two functions. A fixture that inserted rows itself could agree with a
    registration path that had stopped stamping `last_version` at all.
    """
    from agents.tools._db import register_levers_sync, register_nodes_sync

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    async with get_connection(SLUG) as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES (?)", (SLUG,))
        await conn.commit()
    assert register_nodes_sync(SLUG, _chain(), 1, "alex") == 89
    assert register_levers_sync(SLUG, _levers(), 1, "morgan") == 10
    yield SLUG
    get_settings.cache_clear()


def _may_review():
    """Grant the content gate, patched where the router looks the names up.

    `api.routers.item_reviews` binds its own references with `from ... import`, so patching
    `authority_service` would miss it - the four crew tests CLAUDE.md records patched the
    definition site and passed for the wrong reason.
    """
    return patch.multiple(
        "api.routers.item_reviews",
        caller_may_contribute=AsyncMock(return_value=True),
        caller_may_approve=AsyncMock(return_value=True),
    )


async def _ledger_hashes(table: str, id_column: str) -> dict[str, str]:
    """Every row of a ledger, each hashed whole, keyed by its id.

    `SELECT *`, deliberately: a comparison naming its columns cannot see a column added later
    moving under it, and "nothing else changed" is a claim about the row rather than about the
    fields this test happened to think of.
    """
    async with get_connection(SLUG) as conn:
        cur = await conn.execute(f"SELECT * FROM {table} ORDER BY {id_column}")
        rows = await cur.fetchall()
        columns = [d[0] for d in cur.description]
    key = columns.index(id_column)
    return {
        row[key]: hashlib.sha256(repr(tuple(row)).encode()).hexdigest() for row in rows
    }


def _ids_named_in(block: str) -> set[str]:
    """The item ids a prompt block actually names, read off the head of each bullet.

    A substring test cannot answer this at ninety-nine items: `3.3.3` contains `3.3`, every
    label in this fixture ends in its own id, and `1.1.6 not in block` would fail on a block
    naming `11.1.6`. The block's lines are `- {id} ({level}): {label}`, so the id is the
    second token of a bullet and nothing else is.
    """
    return {
        line.split()[1]
        for line in block.splitlines()
        if line.startswith("- ") and len(line.split()) > 1
    }


async def _send_back(client, path: str, item_id: str, notes: str) -> None:
    """One send-back through the real door, asserted to have been accepted."""
    with _may_review():
        r = await client.post(
            f"/projects/{SLUG}/{path}/{item_id}/review",
            json={"decision": "changes_requested", "return_to": "agent", "notes": notes},
        )
    assert r.status_code == 200, r.text


# ══════════════════════════════════════════════════════════════════════════════════════
# The loop
# ══════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_one_node_goes_back_reaches_alex_alone_and_clears_when_he_writes(client, chain):
    """Door to prompt to write, in one test, with eighty-eight other nodes present.

    The three links each have a test of their own. What none of them can see is the join: a
    recorder writing a state the query does not read, or a query returning rows the block does
    not render, would leave all three green and the loop dead. Driven over HTTP because the
    door is where a reviewer stands.

    The clearing at the end is the loop closing on **evidence**, not on a close-out call:
    nothing marks the send-back resolved, and what removes it is `register_nodes_sync` stamping
    `last_version` past the version the reviewer read.
    """
    await _send_back(client, "node-ledger", "3.3.3", "This belongs at L2 - it is a decision.")

    block = await _pending_discovery_revisions(SLUG, "value_chain_mapper")
    assert NODE_HEADER in block
    assert _ids_named_in(block) == {"3.3.3"}
    assert "This belongs at L2 - it is a decision." in block

    from agents.tools._db import register_nodes_sync
    register_nodes_sync(SLUG, _chain(), 2, "alex")

    assert await _pending_discovery_revisions(SLUG, "value_chain_mapper") == ""


@pytest.mark.asyncio
async def test_a_single_node_send_back_leaves_the_other_88_rows_byte_identical(client, chain):
    """The property the design rests on, asserted by hash over the whole ledger.

    **Within the registry.** `value_chain_tree` and `value_chain_summary` are derived from the
    model and will legitimately move end to end when one node changes - saying so is the
    spec's own instruction, because the first reviewer to diff a run otherwise reads a correct
    regeneration as a leak. The ledger is the artefact where "only 3.3.3 moved" is answerable,
    and this is the answer.

    Hashed rather than compared field by field, so a column added to the ledger later is
    inside the claim rather than outside it.
    """
    before = await _ledger_hashes("value_chain_ledger", "node_id")
    assert len(before) == 89

    await _send_back(client, "node-ledger", "3.3.3", "Wrong altitude.")

    after = await _ledger_hashes("value_chain_ledger", "node_id")
    assert set(after) == set(before), "the send-back added or removed a ledger row"
    moved = {node_id for node_id, digest in after.items() if digest != before[node_id]}
    assert moved == {"3.3.3"}


@pytest.mark.asyncio
async def test_a_lever_going_back_moves_neither_ledgers_other_rows(client, chain):
    """The same property across the two ledgers, which is the half a single-ledger test cannot
    reach: one recorder serves both, keyed on `item_kind`, and the two tables sit in one
    database file.

    A recorder that keyed on the id alone would be invisible here until a node and a lever
    happened to share one - which is why `test_item_reviews` drives that collision directly.
    What this adds is that a lever review touches no node row at all.
    """
    nodes_before = await _ledger_hashes("value_chain_ledger", "node_id")
    levers_before = await _ledger_hashes("value_lever_ledger", "lever_id")
    assert len(levers_before) == 10

    await _send_back(client, "lever-ledger", "LV-003", "That is the mechanism, not the lever.")

    assert await _ledger_hashes("value_chain_ledger", "node_id") == nodes_before
    levers_after = await _ledger_hashes("value_lever_ledger", "lever_id")
    moved = {lever_id for lever_id, d in levers_after.items() if d != levers_before[lever_id]}
    assert moved == {"LV-003"}


@pytest.mark.asyncio
async def test_each_agent_is_told_about_its_own_item_and_no_other(client, chain):
    """One crew, two agents, both with something awaiting them, at the size the crew runs at.

    The absence is the half that fails silently: a block reaching the agent it should is
    visible in the prompt, and a block *also* reaching the other one is a task one paragraph
    longer that nothing records. Asserted as set equality over the ids each block names, not
    as a substring absence, so a block naming all eighty-nine nodes fails rather than passing
    on the strength of containing the right one.
    """
    await _send_back(client, "node-ledger", "3.3.3", "Wrong altitude.")
    await _send_back(client, "lever-ledger", "LV-003", "That is the mechanism, not the lever.")

    alex = await _pending_discovery_revisions(SLUG, "value_chain_mapper")
    morgan = await _pending_discovery_revisions(SLUG, "value_lever_analyst")

    assert _ids_named_in(alex) == {"3.3.3"}
    assert _ids_named_in(morgan) == {"LV-003"}
    assert LEVER_HEADER not in alex
    assert NODE_HEADER not in morgan


@pytest.mark.asyncio
async def test_alexs_run_clears_his_send_back_and_leaves_morgans_standing(client, chain):
    """Two agents in one crew, and a run in which only one of them wrote.

    The ledgers clear on their own writes and on nothing else, so Morgan's lever is still
    awaiting her after a run of Alex's - whether he ran alongside her, ahead of her, or she
    failed. A clearing keyed on the run rather than on the write would have taken the lever
    with it and the reviewer would never learn that their note went nowhere.
    """
    from agents.tools._db import register_nodes_sync

    await _send_back(client, "node-ledger", "3.3.3", "Wrong altitude.")
    await _send_back(client, "lever-ledger", "LV-003", "That is the mechanism, not the lever.")

    register_nodes_sync(SLUG, _chain(), 2, "alex")

    assert await _pending_discovery_revisions(SLUG, "value_chain_mapper") == ""
    assert _ids_named_in(
        await _pending_discovery_revisions(SLUG, "value_lever_analyst")
    ) == {"LV-003"}


@pytest.mark.asyncio
async def test_the_run_that_clears_one_send_back_restamps_all_89(client, chain):
    """Why Alex's clearing is weaker than Maya's, asserted rather than described.

    Maya regenerates the scripts she was sent back and leaves the rest alone, so her ledger's
    `last_version` moves on exactly what she rewrote. Alex rebuilds the whole chain on every
    run - one run re-emitted fifty-nine labels, and not one was a redefinition - so
    `register_nodes_sync` stamps every id the batch names and **any** run of his clears a
    send-back, addressed or not. That is the ledger's honest reach today, it is why
    `DiscoveryReviewExtra` carries a note saying so per ledger section, and the number below is
    what makes it true.

    The labels are the other half: the ledger is restamped and not rewritten. Alex re-emits
    every label on every run, and `ON CONFLICT(node_id) DO NOTHING` plus the CASE beside it
    keep the wording an id already carries, so a rebuild that reworded one cannot move the
    ledger's own record of what that id means.
    """
    from agents.tools._db import register_nodes_sync

    await _send_back(client, "node-ledger", "3.3.3", "Wrong altitude.")

    reworded = [
        dict(a, label="Mains renewal planning, reworded") if a["id"] == "3.3.3" else a
        for a in _chain()
    ]
    assert register_nodes_sync(SLUG, reworded, 2, "alex") == 0, "a rebuild registers no new id"

    async with get_connection(SLUG) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM value_chain_ledger WHERE last_version=2"
        )
        assert (await cur.fetchone())[0] == 89
        cur = await conn.execute(
            "SELECT label FROM value_chain_ledger WHERE node_id='3.3.3'"
        )
        assert (await cur.fetchone())[0] == "Activity 3.3.3"
