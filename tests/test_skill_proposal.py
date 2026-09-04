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

The duplicate half of the file stands on `_fake_haiku` below. Read its docstring before
trusting anything here: the comparison is a model judgement, so the stub has to stand in for
one, and a stub that answered a constant would make half these tests vacuous.
"""
import json
import types

import pytest

from api.config import get_settings
from api.services.run_service import _fetch_skill_notes, _SNAKE_TO_DISPLAY
from api.services.skills_service import propose_skill

# The crew Maya runs in, and the agent it dispatches. Read from the map rather than written
# out, so this test follows a rename instead of quietly testing nothing.
AGENT = "interaction_designer"
OTHER_AGENT = "value_chain_mapper"
CREW = "assessment_design"
RULE = "The welcome carries privacy and tone; the framing carries the interview's purpose"

# The same rule as RULE, said twice more with almost none of its vocabulary. This is the
# requirement the duplicate detection exists for: an exact-match test would pass against a
# string comparison, which can never fire on real proposals and would leave the recurrence
# signal permanently silent.
RULE_REWORDED_A = "Keep confidentiality in the welcome and purpose in the framing"
RULE_REWORDED_B = (
    "The opening should state privacy; the framing should state what the interview covers"
)
# About the same subject, and a different rule. A comparison loose enough to merge this with
# the three above would pass every duplicate test in this file and quietly lose a rule, which
# is worse than the duplicate row it avoided.
DIFFERENT_RULE = "The welcome should name the interviewer and the team they belong to"

# What the stub knows and a string comparison cannot: which of these say the same thing.
_MEANINGS = {
    RULE: "welcome-privacy-framing-purpose",
    RULE_REWORDED_A: "welcome-privacy-framing-purpose",
    RULE_REWORDED_B: "welcome-privacy-framing-purpose",
    DIFFERENT_RULE: "welcome-names-interviewer",
}


def _meaning(text: str) -> str:
    """Anything not in the table is its own meaning, so an unlisted rule matches only itself."""
    return _MEANINGS.get(text, f"literal:{text}")


@pytest.fixture(autouse=True)
def _isolated_system_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fake_haiku(monkeypatch):
    """Stand in for the comparator's model call, and answer by meaning rather than by text.

    Autouse, so no test in this file can reach the real API - `propose_skill` now asks Haiku
    whether a proposal restates a rule already held.

    The stub answers from `_MEANINGS`, not from the wording, which is the only way an offline
    test can exercise the property the feature rests on: it returns a match for two strings
    that share almost no words, and no match for two strings that share most of theirs. It is
    therefore **not a constant** - the same stub is what makes the duplicate tests and the
    control below disagree, so neither can be passing because the stub decided the answer.

    It reads the ids and descriptions out of the request the production code actually built,
    so a comparison that stopped sending the candidates would stop matching here too.

    Yields the list of requests made, for the test that asserts what was asked.
    """
    calls: list[dict] = []

    async def _create(**kwargs):
        calls.append(kwargs)
        payload = json.loads(kwargs["messages"][0]["content"])
        wanted = _meaning(payload["proposed"])
        match = next(
            (h["id"] for h in payload["held"] if _meaning(h["description"]) == wanted), None
        )
        body = json.dumps({"match_id": match, "reason": "stub"})
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=body)])

    monkeypatch.setattr(
        "api.services.skills_service.AsyncAnthropic",
        lambda **_: types.SimpleNamespace(messages=types.SimpleNamespace(create=_create)),
    )
    return calls


async def _count_skills(agent: str) -> int:
    from api.database import fetch_skills, get_system_connection

    async with get_system_connection() as conn:
        return len(await fetch_skills(conn, agent_name=_SNAKE_TO_DISPLAY[agent]))


async def _occurrences_of(skill_id: int) -> int:
    return (await _stored(skill_id))["occurrences"]


async def _provenance_of(skill_id: int) -> list[tuple]:
    from api.database import fetch_skill_occurrences, get_system_connection

    async with get_system_connection() as conn:
        rows = await fetch_skill_occurrences(conn, skill_id=skill_id)
    return [(r["source_project"], r["source_ref"], r["description"]) for r in rows]


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


async def _reject(skill_id: int) -> None:
    from api.database import get_system_connection, update_skill

    async with get_system_connection() as conn:
        assert await update_skill(conn, skill_id=skill_id, status="rejected", reviewed_by="tester")


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


# ── a duplicate is evidence, not noise ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_first_proposal_asks_no_model(_fake_haiku):
    """Nothing to compare against, so nothing is asked - and the write stays deterministic.

    It also fixes the meaning of the call counts asserted below: a request in `_fake_haiku`
    is a comparison against real candidates, never an empty one.
    """
    result = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")
    assert _fake_haiku == []
    assert result["action"] == "created"
    assert result["occurrences"] == 1


@pytest.mark.asyncio
async def test_a_differently_worded_duplicate_increments_rather_than_inserts():
    """The property the task exists for, against a pending suggestion.

    The first proposal is never approved, so this is the recurrence case that matters most:
    the second sighting of a rule nobody has ruled on yet is exactly the evidence the queue
    needs in order to sort it above a guess. The two strings share almost no vocabulary, so a
    comparison by text cannot pass this.
    """
    first = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")
    before = await _count_skills(AGENT)

    second = await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")

    assert await _count_skills(AGENT) == before
    assert second["action"] == "incremented"
    assert second["skill_id"] == first["skill_id"]
    assert second["occurrences"] == 2
    assert await _occurrences_of(first["skill_id"]) == 2


@pytest.mark.asyncio
async def test_a_differently_worded_duplicate_of_an_approved_skill_increments_it():
    """The approved arm. Both sets are candidates, and a rule already in force still counts:
    the recurrence says the agent needed telling again, which is worth recording even though
    no reviewer has anything left to approve.
    """
    first = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")
    await _approve(first["skill_id"])
    before = await _count_skills(AGENT)

    second = await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")

    assert await _count_skills(AGENT) == before
    assert second["action"] == "incremented"
    assert second["skill_id"] == first["skill_id"]
    assert second["status"] == "approved"
    assert await _occurrences_of(first["skill_id"]) == 2


@pytest.mark.asyncio
async def test_a_genuinely_new_proposal_creates_a_row_with_one_occurrence():
    """The control, and the thing that makes every assertion above mean something.

    Without it a comparison that called everything a duplicate would pass them all. Both rules
    here are about the welcome and share most of their words - the pair a loose comparison
    merges - and merging them would lose a rule, which is worse than the duplicate row it
    avoided.
    """
    first = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")
    before = await _count_skills(AGENT)

    second = await propose_skill(AGENT, DIFFERENT_RULE, "p2", "SC-031")

    assert await _count_skills(AGENT) == before + 1
    assert second["action"] == "created"
    assert second["skill_id"] != first["skill_id"]
    assert second["occurrences"] == 1
    assert await _occurrences_of(first["skill_id"]) == 1


@pytest.mark.asyncio
async def test_the_comparison_is_put_to_the_model_with_both_texts(_fake_haiku):
    """What is *sent*, not what is decided.

    A comparison that answered from the strings alone would never call the model, and one that
    called it without the candidates could never match. Asserted against the request the
    production code built.
    """
    first = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")
    await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")

    assert len(_fake_haiku) == 1
    payload = json.loads(_fake_haiku[0]["messages"][0]["content"])
    assert payload["proposed"] == RULE_REWORDED_B
    assert [h["id"] for h in payload["held"]] == [first["skill_id"]]
    assert payload["held"][0]["description"] == RULE_REWORDED_A


@pytest.mark.asyncio
async def test_provenance_accumulates_and_the_origin_is_not_overwritten():
    """How many, and where - the question a reviewer asks at the queue.

    A rule seen three times on one project is weaker evidence than one seen once each on
    three, so every occurrence keeps its own project and reference. The `skills` row's own
    `source_project` stays the first occurrence's, because that is the row's origin, and the
    count stays equal to the number of occurrences recorded.
    """
    first = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")
    await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")

    row = await _stored(first["skill_id"])
    assert (row["source_project"], row["source_ref"]) == ("p1", "SC-014")
    assert await _provenance_of(first["skill_id"]) == [
        ("p1", "SC-014", RULE_REWORDED_A),
        ("p2", "SC-031", RULE_REWORDED_B),
    ]
    assert row["occurrences"] == len(await _provenance_of(first["skill_id"]))


@pytest.mark.asyncio
async def test_a_duplicate_proposed_for_another_agent_creates_its_own_row(_fake_haiku):
    """Candidates are the proposing agent's own rules. Two agents may need the same rule, and
    each holds it separately - `_fetch_skill_notes` injects per agent, so a count pooled
    across agents would say a rule recurs when it was proposed once for each of two.
    """
    first = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")

    second = await propose_skill(OTHER_AGENT, RULE_REWORDED_B, "p2", "SC-031")

    assert second["action"] == "created"
    assert second["agent"] == _SNAKE_TO_DISPLAY[OTHER_AGENT]
    assert await _occurrences_of(first["skill_id"]) == 1
    # Nothing was even compared: the other agent held no rules to compare against.
    assert _fake_haiku == []


@pytest.mark.asyncio
async def test_a_rejected_rule_is_not_a_candidate_and_a_re_proposal_returns_to_the_queue():
    """A human refused this rule. Incrementing the refused row would file the recurrence where
    the queue does not look - counted, and invisible - so the re-proposal is a fresh pending
    row a reviewer sees again.
    """
    first = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")
    await _reject(first["skill_id"])

    second = await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")

    assert second["action"] == "created"
    assert second["skill_id"] != first["skill_id"]
    assert second["status"] == "pending"
    assert await _occurrences_of(first["skill_id"]) == 1


@pytest.mark.asyncio
async def test_a_comparison_the_model_cannot_answer_creates_a_row_rather_than_failing(monkeypatch):
    """The proposal is attached to a revision a reviewer asked for, and must not fail with it.

    An unreachable or incoherent model degrades to "not a duplicate": a duplicate row is
    visible in the queue and a reviewer can reject it, where a raised exception would take
    down the run that produced the artefact.
    """
    await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")

    async def _explode(**_):
        raise RuntimeError("no route to the model")

    monkeypatch.setattr(
        "api.services.skills_service.AsyncAnthropic",
        lambda **_: types.SimpleNamespace(messages=types.SimpleNamespace(create=_explode)),
    )
    second = await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")

    assert second["action"] == "created"
    assert second["occurrences"] == 1


@pytest.mark.asyncio
async def test_an_id_the_model_was_never_offered_is_refused(monkeypatch):
    """The one failure of this comparison that is silent at every later layer: an id that is
    not a candidate would increment an unrelated skill, and nothing downstream could tell.
    """
    first = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")
    stranger = first["skill_id"] + 4321

    async def _hallucinate(**_):
        body = json.dumps({"match_id": stranger, "reason": "stub"})
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=body)])

    monkeypatch.setattr(
        "api.services.skills_service.AsyncAnthropic",
        lambda **_: types.SimpleNamespace(messages=types.SimpleNamespace(create=_hallucinate)),
    )
    second = await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")

    assert second["action"] == "created"
    assert await _occurrences_of(first["skill_id"]) == 1
