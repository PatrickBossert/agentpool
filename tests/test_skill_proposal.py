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

    Yields the list of requests made, for the test that asserts what was asked. Each recorded
    request carries the client's own construction arguments under `_client_kwargs`, so the
    budget the call is made under is assertable alongside its content.
    """
    calls: list[dict] = []

    def _client(**client_kwargs):
        async def _create(**kwargs):
            calls.append({**kwargs, "_client_kwargs": client_kwargs})
            payload = json.loads(kwargs["messages"][0]["content"])
            wanted = _meaning(payload["proposed"])
            match = next(
                (h["id"] for h in payload["held"] if _meaning(h["description"]) == wanted), None
            )
            body = json.dumps({"match_id": match, "reason": "stub"})
            return types.SimpleNamespace(content=[types.SimpleNamespace(text=body)])

        return types.SimpleNamespace(messages=types.SimpleNamespace(create=_create))

    monkeypatch.setattr("api.services.skills_service.AsyncAnthropic", _client)
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
    """The one failure of this comparison that is silent at every later layer: an id that was
    not a candidate increments an unrelated agent's skill, and nothing downstream can tell.

    The stranger has to be a **real** id belonging to another agent, which is the shape a
    hallucination actually takes - candidate ids are small integers and most of them exist. An
    id of nothing at all proves nothing about this guard: the write would find no row, report
    nothing counted, and the proposal would be created anyway for a reason that has nothing to
    do with refusing it. That is what the first version of this test asserted, and it passed
    with the guard deleted.
    """
    stranger = await propose_skill(OTHER_AGENT, DIFFERENT_RULE, "p0", "SC-001")
    first = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")

    async def _hallucinate(**_):
        body = json.dumps({"match_id": stranger["skill_id"], "reason": "stub"})
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=body)])

    monkeypatch.setattr(
        "api.services.skills_service.AsyncAnthropic",
        lambda **_: types.SimpleNamespace(messages=types.SimpleNamespace(create=_hallucinate)),
    )
    second = await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")

    assert second["action"] == "created"
    assert await _occurrences_of(stranger["skill_id"]) == 1
    assert await _occurrences_of(first["skill_id"]) == 1


# ── the agent id has to resolve, or nobody can ever action the proposal ────────
#
# The structural guard - every dispatched agent resolves to a skills name - lives in
# `tests/test_crew_agent_registration.py`, beside the tool-map guard asking the same question
# of the other registry an agent has to be in. This file had a second copy under the same name,
# written while that one was being written on master; two tests with one name guarding one
# property is a guard that can be deleted in either place and still look present in the other.
# The end-to-end below is what this file is for, and it is not a duplicate: it drives a
# proposal from the agent the absence was found on, all the way to the prompt.

@pytest.mark.asyncio
async def test_a_proposal_from_the_illustrator_is_filed_where_an_approval_can_reach_it():
    """The end-to-end the passthrough used to fail, driven the whole way.

    `visual_illustrator` is dispatched by the `business_plan` crew. Under the old passthrough
    its proposal was filed under the snake id, reported `created` with an id, approved by a
    human - and reached no prompt, which is the design's own description of the trap. Asserted
    at the injection, because that is the only layer where the difference shows.
    """
    result = await propose_skill(
        "visual_illustrator", "Render every chart in the client's own palette.", "p1", "VI-001"
    )
    await _approve(result["skill_id"])
    assert "client's own palette" in await _fetch_skill_notes("business_plan")


@pytest.mark.asyncio
async def test_a_proposal_naming_an_unresolvable_agent_is_refused_and_writes_nothing():
    """Refuse, never guess. An id in neither vocabulary is one whose proposal nobody could
    ever action, and a row filed under it is indistinguishable from a working one.
    """
    from api.database import fetch_skills, get_system_connection
    from api.services.skills_service import UnknownProposingAgent

    with pytest.raises(UnknownProposingAgent, match="knowledge_curator"):
        await propose_skill("knowledge_curator", RULE, "p1", "SC-014")

    async with get_system_connection() as conn:
        assert await fetch_skills(conn) == []


@pytest.mark.asyncio
async def test_a_caller_holding_the_role_name_already_is_not_mangled():
    """The admin door's vocabulary. `agent_skill_assignments` is keyed by these, so a name
    that is already one must pass through unchanged rather than be refused with the ids.
    """
    result = await propose_skill(_SNAKE_TO_DISPLAY[AGENT], RULE, "p1", "SC-014")
    assert result["agent"] == _SNAKE_TO_DISPLAY[AGENT]
    await _approve(result["skill_id"])
    assert RULE in await _fetch_skill_notes(CREW)


# ── the comparator's failures are loud, and its budget is its own ──────────────

@pytest.mark.asyncio
async def test_a_reply_wrapped_in_a_code_fence_is_still_understood(monkeypatch):
    """The sibling in this module has stripped fences since it was written, because this model
    does it. The comparator asks for bare JSON in the same way, so one fenced reply would turn
    recurrence off permanently while the queue kept filling with rows that look like new rules.
    """
    first = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")

    async def _fenced(**_):
        body = '```json\n' + json.dumps({"match_id": first["skill_id"]}) + '\n```'
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=body)])

    monkeypatch.setattr(
        "api.services.skills_service.AsyncAnthropic",
        lambda **_: types.SimpleNamespace(messages=types.SimpleNamespace(create=_fenced)),
    )
    second = await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")

    assert second["action"] == "incremented"
    assert second["occurrences"] == 2


@pytest.mark.asyncio
async def test_an_id_the_model_wrote_as_a_string_is_understood(monkeypatch):
    """JSON from a model is not typed. A quoted id is the same answer and must not be read as
    a failure, which would count as a fresh rule.
    """
    first = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")

    async def _quoted(**_):
        body = json.dumps({"match_id": str(first["skill_id"])})
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=body)])

    monkeypatch.setattr(
        "api.services.skills_service.AsyncAnthropic",
        lambda **_: types.SimpleNamespace(messages=types.SimpleNamespace(create=_quoted)),
    )
    assert (await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031"))["action"] == "incremented"


@pytest.mark.asyncio
async def test_a_comparison_that_fails_says_so_in_the_log(monkeypatch, caplog):
    """A dead comparator and a healthy queue with no duplicates in it are the same thing at
    every later layer - `occurrences` stays 1 either way. The log line is the only thing that
    tells them apart, so it is asserted rather than assumed.

    The reply here is a well-formed response object with no content block, which is a shape
    the stub normalises away everywhere else in this file.
    """
    await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")

    async def _empty(**_):
        return types.SimpleNamespace(content=[])

    monkeypatch.setattr(
        "api.services.skills_service.AsyncAnthropic",
        lambda **_: types.SimpleNamespace(messages=types.SimpleNamespace(create=_empty)),
    )
    with caplog.at_level("WARNING", logger="api.services.skills_service"):
        second = await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")

    assert second["action"] == "created"
    assert any(
        r.levelname == "WARNING" and "duplicate comparison failed" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_the_comparison_carries_its_own_time_budget(_fake_haiku):
    """The SDK's defaults are sized for an interactive caller: anthropic 0.120.0 waits 600
    seconds and retries twice, which is half an hour inside a crew run for a nice-to-have
    attached to a revision that is already finished. Asserted as *sent*, on the request and on
    the client that made it.
    """
    from api.services.skills_service import _COMPARISON_RETRIES, _COMPARISON_TIMEOUT_SECONDS

    await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")
    await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")

    assert len(_fake_haiku) == 1
    assert _fake_haiku[0]["timeout"] == _COMPARISON_TIMEOUT_SECONDS
    assert _fake_haiku[0]["_client_kwargs"]["max_retries"] == _COMPARISON_RETRIES
    # A budget, not a formality: the worst case has to be a fraction of the SDK's 600s x 3.
    assert _COMPARISON_TIMEOUT_SECONDS * (_COMPARISON_RETRIES + 1) <= 60


@pytest.mark.asyncio
async def test_no_database_connection_is_held_across_the_comparison(monkeypatch):
    """The comparison is a network call, and a connection open across it is a thread held for
    as long as the model takes.

    An earlier version held one and justified it as closing the window in which two concurrent
    proposals of the same rule each create a row. That justification was false -
    `get_system_connection` opens a fresh connection per call, so two overlapping proposals
    hold two of them and no transaction spans the read and the write either way. The window is
    accepted; paying for it was not. Asserted structurally, because the cost is invisible in
    every result the function returns.
    """
    import contextlib

    import api.database as db

    real = db.get_system_connection
    open_now = {"count": 0}
    depth_at_comparison: list[int] = []

    @contextlib.asynccontextmanager
    async def _counting():
        open_now["count"] += 1
        try:
            async with real() as conn:
                yield conn
        finally:
            open_now["count"] -= 1

    async def _watching(**_):
        depth_at_comparison.append(open_now["count"])
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(text=json.dumps({"match_id": None}))]
        )

    await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")
    monkeypatch.setattr(db, "get_system_connection", _counting)
    monkeypatch.setattr(
        "api.services.skills_service.AsyncAnthropic",
        lambda **_: types.SimpleNamespace(messages=types.SimpleNamespace(create=_watching)),
    )
    await propose_skill(AGENT, DIFFERENT_RULE, "p2", "SC-031")

    assert depth_at_comparison == [0]


@pytest.mark.asyncio
async def test_deleting_a_skill_takes_its_occurrences_with_it():
    """Nothing turns foreign keys on for this connection, so the cleanup in `delete_skill` is
    the whole mechanism - and deleting the line moved no test until this one existed.
    """
    from api.database import delete_skill, get_system_connection

    first = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")
    await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")
    assert len(await _provenance_of(first["skill_id"])) == 2

    async with get_system_connection() as conn:
        assert await delete_skill(conn, skill_id=first["skill_id"])
        async with conn.execute("SELECT COUNT(*) AS n FROM skill_occurrences") as cur:
            assert (await cur.fetchone())["n"] == 0


@pytest.mark.asyncio
async def test_recording_an_occurrence_against_a_skill_that_has_gone_counts_nothing():
    """The helper's contract, which `propose_skill` relies on to tell "counted" from "there
    was nothing to count against" and fall through to creating a row.

    Asserted here rather than through `propose_skill`, because the guard above makes a match
    on a missing skill unreachable from the service: the only way to reach it is another
    process deleting the row between the read and the write. The branch that handles it is two
    lines and this is the property it rests on.
    """
    from api.database import get_system_connection, record_skill_occurrence

    async with get_system_connection() as conn:
        counted = await record_skill_occurrence(
            conn, skill_id=987654, description="A rule for a skill that is not there."
        )
        async with conn.execute("SELECT COUNT(*) AS n FROM skill_occurrences") as cur:
            orphans = (await cur.fetchone())["n"]
    assert counted == 0
    assert orphans == 0
