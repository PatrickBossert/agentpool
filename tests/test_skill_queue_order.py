# tests/test_skill_queue_order.py
"""The review queue is ordered by evidence, and the evidence is readable.

**Where the ordering is asserted, and why it is here rather than in the browser.** The queue
sorts by `occurrences` descending, so a rule an agent has proposed three times sits above one
proposed once. That decision lives in `fetch_skills`, so this file drives it over HTTP and
asserts what `GET /admin/skills?status=pending` **sends**. Its counterpart,
`ui/src/__tests__/AdminSkillsQueue.test.tsx`, asserts that the page renders the order it is
given and never re-sorts - which is only a property worth having because the order arriving is
the right one, and only this test can say that.

A frontend test alone would have been vacuous: a mocked list handed to the page already
sorted proves nothing about the sort. CLAUDE.md records eleven tests on this project that
passed while testing something one layer away from the property they were named for.

**Scoped to rows this file creates**, never counted globally or by position in the whole
table: `tests/conftest.py` points `DATABASE_DIR` at a fixed directory that persists between
runs, and `skills` is in the shared `system.db`, which already holds fifty-three rows on a
developer's machine. Every assertion here filters to the three names below, and the fixture
removes them afterwards whether the test passed or not.
"""
import pytest
import pytest_asyncio

from api.auth import create_access_token
from api.config import get_settings

# Distinctive enough that no baseline skill, and no other test's row, can collide with them.
_ONCE = "sp61-queue-order seen once"
_TWICE = "sp61-queue-order seen twice"
_THRICE = "sp61-queue-order seen three times"
_ALL = (_ONCE, _TWICE, _THRICE)

_AGENT = "Interaction Designer"


async def _insert_pending(name: str, *, occurrences: int) -> int:
    """One pending proposal with a given count, written the way `propose_skill` writes it.

    Written directly rather than through `propose_skill` on purpose: that path asks a model
    whether the rule is a duplicate, and this file is about the ordering of rows, not about
    the comparison. `tests/test_skill_proposal.py` owns the write path.
    """
    from api.database import get_system_connection, insert_skill

    async with get_system_connection() as conn:
        skill_id = await insert_skill(
            conn,
            name=name,
            description=f"The rule stated as: {name}",
            source="revision",
            source_project="sp61-origin",
            source_ref="SC-014",
            proposed_by_agent="interaction_designer",
            status="pending",
            agents=[_AGENT],
        )
        await conn.execute(
            "UPDATE skills SET occurrences = ? WHERE id = ?", (occurrences, skill_id)
        )
        await conn.commit()
    return skill_id


async def _record_sighting(skill_id: int, *, project: str, ref: str, wording: str) -> None:
    from api.database import get_system_connection, record_skill_occurrence

    async with get_system_connection() as conn:
        await record_skill_occurrence(
            conn,
            skill_id=skill_id,
            description=wording,
            source_project=project,
            source_ref=ref,
            proposed_by_agent="interaction_designer",
            bump=False,
        )


# `@pytest_asyncio.fixture`, never a plain `@pytest.fixture`. `pytest.ini` sets
# `asyncio_mode = strict`, under which a plain fixture declared `async def` is handed to the
# test as an un-awaited async generator: the setup never runs, the teardown never runs, and
# nothing fails - so the clean-up silently does not happen and the rows below survive into the
# next test in the file and the next run of the suite. That is the poisoned-database trap
# CLAUDE.md describes, arriving through the fixture that was written to prevent it. Caught
# here by the tie-break test, which saw six rows where it had written two.
@pytest_asyncio.fixture(autouse=True)
async def _remove_this_files_rows():
    yield
    from api.database import get_system_connection, delete_skill

    async with get_system_connection() as conn:
        ids: list[int] = []
        for name in _ALL:
            async with conn.execute("SELECT id FROM skills WHERE name = ?", (name,)) as cur:
                ids.extend(r["id"] for r in await cur.fetchall())
    for skill_id in ids:
        async with get_system_connection() as conn:
            # delete_skill removes the assignments and the occurrence rows too, so a later
            # run of this file starts from the same state as the first one.
            await delete_skill(conn, skill_id=skill_id)


def _ours(rows: list[dict]) -> list[str]:
    return [r["name"] for r in rows if r["name"] in _ALL]


@pytest.mark.asyncio
async def test_the_pending_queue_is_sent_most_evidenced_first(client):
    """A rule seen three times arrives above one seen once, whatever order they were written."""
    # Written least-evidenced first, so an endpoint that simply echoed insertion order - or
    # the created_at ordering that was there before - would answer the reverse of this.
    await _insert_pending(_ONCE, occurrences=1)
    await _insert_pending(_THRICE, occurrences=3)
    await _insert_pending(_TWICE, occurrences=2)

    res = await client.get("/admin/skills?status=pending")
    assert res.status_code == 200

    assert _ours(res.json()) == [_THRICE, _TWICE, _ONCE]


@pytest.mark.asyncio
async def test_the_count_a_reviewer_sorts_on_is_sent_with_the_row(client):
    """The control on the test above: the ordering is worth nothing if the count is invisible.

    A page cannot say "seen three times" about a body that does not carry the three.
    """
    await _insert_pending(_THRICE, occurrences=3)

    rows = (await client.get("/admin/skills?status=pending")).json()
    row = next(r for r in rows if r["name"] == _THRICE)

    assert row["occurrences"] == 3
    assert row["source_project"] == "sp61-origin"
    assert row["source_ref"] == "SC-014"
    assert row["proposed_by_agent"] == "interaction_designer"


@pytest.mark.asyncio
async def test_two_rules_with_equal_evidence_keep_the_newer_one_first(client):
    """The tie-break, asserted so a later change cannot quietly drop it.

    `created_at` is what ordered the queue before `occurrences` was put in front of it, and
    the fifty-three rows that predate the proposal path all carry `occurrences` 1 - so the
    whole existing library is decided by this arm.

    It is also the test that found `created_at` alone cannot decide it. The column is whole
    seconds, so two rows written by one test tie on it, and the order fell to whatever SQLite
    returned - which for a reviewer means a queue that reshuffles on reload. `id DESC` is the
    third key, and this assertion is what holds it there.
    """
    await _insert_pending(_ONCE, occurrences=1)
    await _insert_pending(_TWICE, occurrences=1)

    rows = (await client.get("/admin/skills?status=pending")).json()

    # _TWICE was written second, so it is the newer of two rows with identical evidence.
    assert _ours(rows) == [_TWICE, _ONCE]


@pytest.mark.asyncio
async def test_the_evidence_behind_the_count_is_readable_oldest_first(client):
    """What the count is made of - the engagement, the output, and the wording used each time.

    Oldest first, because a reviewer reads provenance as a history and the first row is the
    origin the `skills` row itself carries.
    """
    skill_id = await _insert_pending(_THRICE, occurrences=2)
    await _record_sighting(
        skill_id, project="acme-rail", ref="SC-014",
        wording="Keep confidentiality in the welcome and purpose in the framing",
    )
    await _record_sighting(
        skill_id, project="borough-water", ref="SC-031",
        wording="The opening should state privacy; the framing states what the interview covers",
    )

    res = await client.get(f"/admin/skills/{skill_id}/occurrences")
    assert res.status_code == 200
    rows = res.json()

    assert [r["source_project"] for r in rows] == ["acme-rail", "borough-water"]
    assert [r["source_ref"] for r in rows] == ["SC-014", "SC-031"]
    assert "confidentiality in the welcome" in rows[0]["description"]
    assert "framing states what the interview covers" in rows[1]["description"]


@pytest.mark.asyncio
async def test_a_skill_with_no_recorded_sightings_answers_an_empty_list(client):
    """Not a 404. The fifty-three skills that predate the proposal path have no rows at all,
    and a reviewer opening one of those must be told there is no history rather than that the
    skill is missing."""
    skill_id = await _insert_pending(_ONCE, occurrences=1)

    res = await client.get(f"/admin/skills/{skill_id}/occurrences")

    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.asyncio
async def test_a_skill_that_does_not_exist_answers_404(client):
    """The other half of the pair above - the two answers must be distinguishable."""
    res = await client.get("/admin/skills/98765432/occurrences")

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_only_a_sysadmin_may_read_the_evidence(client):
    """The same tier as the PATCH that acts on the queue.

    `GET /admin/skills` is open to any login, but these rows name client engagements and quote
    the agent's own words about them, and only a sysadmin can approve - so only a sysadmin
    needs them.
    """
    skill_id = await _insert_pending(_ONCE, occurrences=1)
    token = create_access_token("someone", "org_admin", get_settings().jwt_secret, org_id=1)

    res = await client.get(
        f"/admin/skills/{skill_id}/occurrences",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 403
