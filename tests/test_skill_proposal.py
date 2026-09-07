# tests/test_skill_proposal.py
"""A skill an agent proposes reaches the queue, and reaches no prompt.

The safety property is asserted against **what is injected into the task description**, not
against what the `skills` table holds. CLAUDE.md's *recurring failure mode* section lists
defects of exactly the other shape - a property verified one layer away from where it holds -
and the layer that matters
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
import asyncio
import json
import time
import types

import pytest

from api.config import get_settings
from api.services import llm_client as _llm_client
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

    Autouse, so no test in this file can reach a provider - `propose_skill` asks a model
    whether a proposal restates a rule already held.

    The stub answers from `_MEANINGS`, not from the wording, which is the only way an offline
    test can exercise the property the feature rests on: it returns a match for two strings
    that share almost no words, and no match for two strings that share most of theirs. It is
    therefore **not a constant** - the same stub is what makes the duplicate tests and the
    control below disagree, so neither can be passing because the stub decided the answer.

    It reads the ids and descriptions out of the request the production code actually built,
    so a comparison that stopped sending the candidates would stop matching here too.

    **Substituted at `project_completion`, not at a provider client.** The comparison is routed
    by the project now, so the provider is whatever that project's mode resolves to and a stub
    of one client class would be blind to the other. That leaves the *routing* unexercised by
    every test in this half of the file, deliberately: routing is asserted at the bottom of
    this file against the real `project_completion` and a fake transport, where a wrong wire
    format is visible. A stub here that stood in for the router would have hidden it.

    Yields the list of calls made - `(slug, tier, kwargs)` - so the tests below can assert what
    was asked, of which model tier, and on whose behalf.
    """
    calls: list[dict] = []

    async def _completion(slug, tier, messages, *, system=None, max_tokens=1024):
        calls.append({"slug": slug, "tier": tier, "messages": messages,
                      "system": system, "max_tokens": max_tokens})
        payload = json.loads(messages[0]["content"])
        wanted = _meaning(payload["proposed"])
        match = next(
            (h["id"] for h in payload["held"] if _meaning(h["description"]) == wanted), None
        )
        return json.dumps({"match_id": match, "reason": "stub"})

    monkeypatch.setattr(
        "api.services.llm_client.project_completion", _completion
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
async def test_the_slug_that_was_routed_on_is_the_slug_that_is_filed(_fake_haiku):
    """One spelling of one fact, all the way through.

    The slug is stripped once, and the stripped form is what `find_duplicate_skill` is routed
    by *and* what `skills` and `skill_occurrences` record. An earlier version routed on the
    stripped one and filed the caller's original, so a slug carrying whitespace would have had
    the mode read from one key and the provenance grouped under another. Not reachable through
    the only production caller, which passes the run's own slug - which is exactly why nothing
    would have failed.
    """
    from api.database import get_system_connection, fetch_skill_occurrences

    result = await propose_skill(AGENT, RULE, "  sp-gs-am  ", "SC-014")

    assert (await _stored(result["skill_id"]))["source_project"] == "sp-gs-am"
    async with get_system_connection() as conn:
        sightings = await fetch_skill_occurrences(conn, skill_id=result["skill_id"])
    assert [s["source_project"] for s in sightings] == ["sp-gs-am"]


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

    async def _explode(*_a, **_k):
        raise RuntimeError("no route to the model")

    monkeypatch.setattr("api.services.llm_client.project_completion", _explode)
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

    async def _hallucinate(*_a, **_k):
        return json.dumps({"match_id": stranger["skill_id"], "reason": "stub"})

    monkeypatch.setattr("api.services.llm_client.project_completion", _hallucinate)
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

    async def _fenced(*_a, **_k):
        return '```json\n' + json.dumps({"match_id": first["skill_id"]}) + '\n```'

    monkeypatch.setattr("api.services.llm_client.project_completion", _fenced)
    second = await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")

    assert second["action"] == "incremented"
    assert second["occurrences"] == 2


@pytest.mark.asyncio
async def test_an_id_the_model_wrote_as_a_string_is_understood(monkeypatch):
    """JSON from a model is not typed. A quoted id is the same answer and must not be read as
    a failure, which would count as a fresh rule.
    """
    first = await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")

    async def _quoted(*_a, **_k):
        return json.dumps({"match_id": str(first["skill_id"])})

    monkeypatch.setattr("api.services.llm_client.project_completion", _quoted)
    assert (await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031"))["action"] == "incremented"


@pytest.mark.asyncio
async def test_a_comparison_that_fails_says_so_in_the_log(monkeypatch, caplog):
    """A dead comparator and a healthy queue with no duplicates in it are the same thing at
    every later layer - `occurrences` stays 1 either way. The log line is the only thing that
    tells them apart, so it is asserted rather than assumed.

    The reply here is an empty string, which is what a model that answered nothing at all
    leaves this function holding. The response *shapes* a provider can produce - no content
    block, an unreadable body - now belong to `project_completion`, which raises for them; both
    arrive at the same `except` and the same line.
    """
    await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")

    async def _empty(*_a, **_k):
        return ""

    monkeypatch.setattr("api.services.llm_client.project_completion", _empty)
    with caplog.at_level("WARNING", logger="api.services.skills_service"):
        second = await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")

    assert second["action"] == "created"
    assert any(
        r.levelname == "WARNING" and "duplicate comparison failed" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_the_comparison_carries_its_own_time_budget(monkeypatch, caplog):
    """Neither client behind `project_completion` is sized for this caller, and the seam
    imposes no deadline of its own: the Anthropic SDK waits 600 seconds and retries twice, and
    the shared local client waits 120. This path runs inside a crew run, attached to a revision
    that is already finished.

    The budget used to be two keywords handed to a provider client, and it was asserted as
    *sent*. It cannot be any more - the whole point of the seam is that this code does not know
    which provider it is talking to - so it is `asyncio.wait_for` around the call, and it is
    asserted as **behaviour**: a model that never answers resolves to "not a duplicate", says
    so in the log, and does not hold the run. Shrinking the constant for the test is what makes
    the assertion about the mechanism rather than about twenty seconds elapsing.
    """
    from api.services import skills_service

    real_budget = skills_service._COMPARISON_TIMEOUT_SECONDS
    await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")

    async def _never_answers(*_a, **_k):
        await asyncio.sleep(30)
        return json.dumps({"match_id": None})

    monkeypatch.setattr(skills_service, "_COMPARISON_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr("api.services.llm_client.project_completion", _never_answers)

    started = time.monotonic()
    with caplog.at_level("WARNING", logger="api.services.skills_service"):
        second = await propose_skill(AGENT, RULE_REWORDED_B, "p2", "SC-031")
    elapsed = time.monotonic() - started

    assert second["action"] == "created", "an unanswered comparison must not lose the proposal"
    assert elapsed < 5, "the comparison was not bounded by its own budget"
    assert any("duplicate comparison failed" in r.message for r in caplog.records)
    # A budget, not a formality: the real one has to be a fraction of the SDK's 600s x 3.
    assert 0 < real_budget <= 60


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

    async def _watching(*_a, **_k):
        depth_at_comparison.append(open_now["count"])
        return json.dumps({"match_id": None})

    await propose_skill(AGENT, RULE_REWORDED_A, "p1", "SC-014")
    monkeypatch.setattr(db, "get_system_connection", _counting)
    monkeypatch.setattr("api.services.llm_client.project_completion", _watching)
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


# ── Where the comparison actually goes ────────────────────────────────────────
#
# Every test above stubs `project_completion`, which is right for asking what the comparator
# decides and blind by construction to where it sends the question. These four ask the second
# thing, and they ask it of the **request that goes out** rather than of a swapped client
# class: CLAUDE.md records that "route it locally" is two different wire formats, that a test
# swapping the client cannot see a wrong one, and that `local_fast_url` already ends in `/v1`
# so an Anthropic-shaped call becomes `/v1/v1/messages` against an Ollama that serves neither.
#
# The sensitive half is the load-bearing one. The standard half is its control: without it, a
# comparator that had simply stopped calling any model would satisfy "nothing reached
# Anthropic" perfectly.

_REAL_PROJECT_COMPLETION = _llm_client.project_completion


async def _project(slug: str, mode: str, config: dict) -> None:
    from api.database import get_connection, insert_project

    async with get_connection(slug) as conn:
        await insert_project(
            conn, slug=slug, llm_mode=mode, sector="rail", config_json=json.dumps(config)
        )


def _transports(monkeypatch):
    """Real clients over fake transports, for both providers at once.

    Both, in every test, because the assertion that matters is a *comparison*: "the local one
    was used" says nothing on its own if the hosted one was used as well, and a test that only
    installed the transport it expected would let the other call go to the real API.
    """
    import httpx
    from anthropic import AsyncAnthropic
    from api.services import http_clients

    local: list[httpx.Request] = []
    hosted: list[httpx.Request] = []

    def _local_handler(request: httpx.Request) -> httpx.Response:
        local.append(request)
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": json.dumps({"match_id": None, "reason": "local"})}}]})

    def _hosted_handler(request: httpx.Request) -> httpx.Response:
        hosted.append(request)
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-4-5",
            "content": [{"type": "text",
                         "text": json.dumps({"match_id": None, "reason": "hosted"})}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    monkeypatch.setattr(
        http_clients, "_local_llm_client",
        httpx.AsyncClient(transport=httpx.MockTransport(_local_handler)),
    )
    monkeypatch.setattr(
        http_clients, "_anthropic_client",
        AsyncAnthropic(
            api_key="test-key",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(_hosted_handler)),
        ),
    )
    monkeypatch.setattr(
        "api.services.llm_client.project_completion", _REAL_PROJECT_COMPLETION
    )
    return local, hosted


@pytest.mark.asyncio
async def test_a_sensitive_project_compares_on_its_own_model_and_reaches_no_provider(
    monkeypatch, tmp_path
):
    """The load-bearing half. Two proposals, so the second has a candidate to compare against -
    a single one short-circuits on an empty candidate list and reaches no model at all, which
    would pass this test while proving nothing.
    """
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "skills-route-sensitive"
    await _project(slug, "sensitive", {
        "local_fast_model": "gemma4:fast", "local_fast_url": "http://localhost:11999/v1",
    })

    local, hosted = _transports(monkeypatch)
    await propose_skill(AGENT, RULE_REWORDED_A, slug, "SC-014")
    second = await propose_skill(AGENT, RULE_REWORDED_B, slug, "SC-031")

    assert hosted == [], "a sensitive project's proposed rule reached Anthropic"
    assert len(local) == 1, "the comparison did not reach this project's own model"
    assert str(local[0].url) == "http://localhost:11999/v1/chat/completions"
    body = json.loads(local[0].content)
    assert body["model"] == "gemma4:fast"
    # The rule itself travels, which is the whole reason this had to move: it is the agent's
    # own generalisation about work done on this engagement.
    assert RULE_REWORDED_B in json.dumps(body)
    assert second["action"] == "created"


@pytest.mark.asyncio
async def test_a_standard_project_still_compares_on_the_hosted_model(monkeypatch, tmp_path):
    """The control. A comparator that had stopped calling any model would satisfy the test
    above perfectly, and the recurrence signal would be off with nothing to show for it.
    """
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "skills-route-standard"
    await _project(slug, "standard", {})

    local, hosted = _transports(monkeypatch)
    await propose_skill(AGENT, RULE_REWORDED_A, slug, "SC-014")
    second = await propose_skill(AGENT, RULE_REWORDED_B, slug, "SC-031")

    assert local == [], "a standard project's comparison went to a local model"
    assert len(hosted) == 1
    assert str(hosted[0].url) == "https://api.anthropic.com/v1/messages"
    assert second["action"] == "created"


@pytest.mark.asyncio
async def test_a_project_with_no_local_model_records_the_proposal_and_sends_nothing(
    monkeypatch, tmp_path, caplog
):
    """`LocalModelUnavailable` - the standing state of a sensitive project whose `deep` tier is
    configured and whose `fast` tier is not, which runs crews and cannot compare.

    Asserted as that specific failure rather than a generic one, and on all three things it
    must do: the run is not failed, nothing is sent anywhere, and the lesson is still recorded.
    Degrading to a hosted retry would be the one wrong answer available here.
    """
    from agents.model_registry import LocalModelUnavailable

    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "skills-route-unconfigured"
    await _project(slug, "sensitive", {"local_fast_model": "", "local_fast_url": ""})

    local, hosted = _transports(monkeypatch)
    with pytest.raises(LocalModelUnavailable):
        await _REAL_PROJECT_COMPLETION(slug, "fast", [{"role": "user", "content": "probe"}])

    await propose_skill(AGENT, RULE_REWORDED_A, slug, "SC-014")
    with caplog.at_level("WARNING", logger="api.services.skills_service"):
        second = await propose_skill(AGENT, RULE_REWORDED_B, slug, "SC-031")

    assert local == [] and hosted == []
    assert second["action"] == "created", "the lesson was thrown away to protect a deduplication"
    assert any("duplicate comparison failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_a_proposal_with_no_project_is_refused_rather_than_routed(monkeypatch):
    """There is no such thing as a proposal with no engagement, and a blank slug must not be
    allowed to become one.

    `project_completion` raises for a blank slug for exactly this reason, but by then the
    refusal is three layers from the caller and inside an `except` that resolves everything to
    "not a duplicate" - so a forgotten slug would have quietly created rows nobody compared.
    Refused at the door instead. `SkillProposalTool` swallows it, so the run is still safe.
    """
    local, hosted = _transports(monkeypatch)

    for missing in ("", "   ", None):
        with pytest.raises(ValueError, match="requires the project"):
            await propose_skill(AGENT, RULE, missing, "SC-014")

    assert local == [] and hosted == []
    assert await _count_skills(AGENT) == 0


# ── C2: a candidate travels only where its own project's material may travel ───────────────
#
# The routing above decides where the *proposed* rule goes. It says nothing about the
# candidate list that goes with it - so a sensitive engagement's pending rule was posted to
# hosted Haiku the moment any other engagement proposed a rule for the same agent, because the
# payload is routed by the proposing project alone.
#
# Asserted on the **request**, not on which client was constructed: `_transports` installs a
# fake transport for both providers at once, and these read the bytes that actually left. Each
# leak test is paired with a control, because a fix that simply dropped every candidate would
# pass all four of the negative ones and silently end deduplication.


async def _pending_rule_from(slug: str, description: str, *, status: str = "pending") -> int:
    """One row assigned to this file's agent, attributed to `slug`.

    Written directly rather than by proposing on `slug`, so the test does not need that
    project's model to answer before the case it is about can begin.
    """
    from api.database import get_system_connection, insert_skill

    async with get_system_connection() as conn:
        return await insert_skill(
            conn,
            name="A rule held already",
            description=description,
            source="revision",
            source_project=slug,
            source_ref="SC-014",
            proposed_by_agent=AGENT,
            status=status,
            agents=[_SNAKE_TO_DISPLAY[AGENT]],
        )


@pytest.mark.asyncio
async def test_a_sensitive_engagements_pending_rule_is_not_sent_with_another_projects_comparison(
    monkeypatch, tmp_path
):
    """The leak, driven as the review drove it.

    Engagement A is sensitive and holds a proposal naming its client. An agent then proposes an
    unrelated rule while running on engagement B, which is standard - so the comparison is
    correctly routed to hosted Anthropic, and A's sentence used to ride along inside it.
    """
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    await _project("c2-sensitive-a", "sensitive", {
        "local_fast_model": "gemma4:fast", "local_fast_url": "http://localhost:11999/v1",
    })
    await _project("c2-standard-b", "standard", {})
    secret = "When interviewing Iberdrola's SAP migration staff, never name the Q3 outage."
    await _pending_rule_from("c2-sensitive-a", secret)
    # B's own pending rule, so the comparison still happens and this asserts *which candidate*
    # was withheld rather than that the request vanished. Without it the whole list is empty,
    # `find_duplicate_skill` short-circuits, and "the secret did not travel" would be true of a
    # fix that simply stopped comparing - which is the test one file over
    # (`test_withholding_every_candidate_asks_no_model_at_all`), not this one.
    permitted = "Keep confidentiality in the welcome on every script."
    await _pending_rule_from("c2-standard-b", permitted)

    local, hosted = _transports(monkeypatch)
    await propose_skill(AGENT, DIFFERENT_RULE, "c2-standard-b", "SC-031")

    assert len(hosted) == 1, "the standard project's own comparison did not happen"
    body = hosted[0].content.decode()
    assert secret not in body, (
        "a sensitive engagement's pending rule reached Anthropic inside another project's "
        "comparison"
    )
    assert permitted in body, "the narrowing took the proposing project's own rule with it"
    assert local == []


@pytest.mark.asyncio
async def test_a_standard_engagements_pending_rule_still_travels_to_another_standard_one(
    monkeypatch, tmp_path
):
    """The control that makes the test above mean something.

    Without it, a fix that dropped every pending candidate would pass - and `occurrences` would
    stop counting the recurrence it exists to count, which is what the queue is ordered by.
    """
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    await _project("c2-standard-one", "standard", {})
    await _project("c2-standard-two", "standard", {})
    held = "Keep confidentiality in the welcome on every script."
    await _pending_rule_from("c2-standard-one", held)

    local, hosted = _transports(monkeypatch)
    await propose_skill(AGENT, DIFFERENT_RULE, "c2-standard-two", "SC-031")

    assert len(hosted) == 1
    assert held in hosted[0].content.decode(), (
        "cross-engagement recurrence stopped accumulating between projects that both permit it"
    )


@pytest.mark.asyncio
async def test_a_sensitive_project_is_still_compared_against_everything(monkeypatch, tmp_path):
    """Nothing leaves, so nothing is withheld.

    The narrowing is about where a candidate may *go*, not about who may see it - and a
    comparison on a sensitive project's own model goes nowhere. Narrowing here as well would
    cost the engagement that most needs the deduplication its best evidence, for no gain.
    """
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    await _project("c2-sensitive-here", "sensitive", {
        "local_fast_model": "gemma4:fast", "local_fast_url": "http://localhost:11999/v1",
    })
    await _project("c2-standard-elsewhere", "standard", {})
    await _project("c2-sensitive-elsewhere", "sensitive", {
        "local_fast_model": "gemma4:fast", "local_fast_url": "http://localhost:11999/v1",
    })
    held = "Keep confidentiality in the welcome on every script."
    await _pending_rule_from("c2-standard-elsewhere", held)
    # A candidate from a *second sensitive* engagement, which is the case this arm uniquely
    # protects: it is the one that would be withheld if the rule were applied per candidate
    # regardless of whether the comparison leaves the deployment. A standard candidate would
    # travel under any version of the rule and so proves nothing about this branch.
    also_held = "Name the interviewer and the team they belong to in the welcome."
    await _pending_rule_from("c2-sensitive-elsewhere", also_held)

    local, hosted = _transports(monkeypatch)
    await propose_skill(AGENT, DIFFERENT_RULE, "c2-sensitive-here", "SC-031")

    assert hosted == []
    assert len(local) == 1
    body = local[0].content.decode()
    assert held in body
    assert also_held in body


@pytest.mark.asyncio
async def test_an_approved_rule_travels_whatever_engagement_it_came_from(monkeypatch, tmp_path):
    """The exemption, and it is not a loophole.

    An approved skill is already injected into this agent's prompt on every engagement by
    `_fetch_skill_notes`, including the standard ones whose prompts go to Anthropic. It is the
    agent's published instruction rather than one client's material - the same distinction
    `list_skills` turns on - so withholding it would lose deduplication and protect nothing.
    """
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    await _project("c2-sensitive-origin", "sensitive", {
        "local_fast_model": "gemma4:fast", "local_fast_url": "http://localhost:11999/v1",
    })
    await _project("c2-standard-proposer", "standard", {})
    published = "State the units on every figure you carry forward."
    await _pending_rule_from("c2-sensitive-origin", published, status="approved")

    local, hosted = _transports(monkeypatch)
    await propose_skill(AGENT, DIFFERENT_RULE, "c2-standard-proposer", "SC-031")

    assert len(hosted) == 1
    assert published in hosted[0].content.decode()


@pytest.mark.asyncio
async def test_a_pending_rule_that_names_no_engagement_is_withheld(monkeypatch, tmp_path, caplog):
    """Fails closed, because "may this travel" has no answer without an engagement to ask about.

    Only reachable for a row an administrator typed on the global skills page - `propose_skill`
    refuses a blank slug - so the cost is that a hand-typed pending rule does not deduplicate
    against a hosted comparison, and the alternative default is a disclosure.
    """
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    await _project("c2-standard-asker", "standard", {})
    unattributed = "Some rule an administrator typed with no engagement attached."
    await _pending_rule_from(None, unattributed)
    permitted = "Keep confidentiality in the welcome on every script."
    await _pending_rule_from("c2-standard-asker", permitted)

    local, hosted = _transports(monkeypatch)
    with caplog.at_level("INFO", logger="api.services.skills_service"):
        await propose_skill(AGENT, DIFFERENT_RULE, "c2-standard-asker", "SC-031")

    assert len(hosted) == 1
    body = hosted[0].content.decode()
    assert unattributed not in body
    assert permitted in body
    # Logged, because it is the only available answer to "why did that recurrence not count".
    assert any("withheld from a comparison" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_withholding_every_candidate_asks_no_model_at_all(monkeypatch, tmp_path):
    """The narrowed list is what the short-circuit is applied to, not the original.

    A comparison whose whole candidate list is withheld has nothing to ask about, and asking
    anyway would send the proposed rule to a model to be compared against an empty list - a
    request with a cost and no possible answer.
    """
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    await _project("c2-sensitive-only", "sensitive", {
        "local_fast_model": "gemma4:fast", "local_fast_url": "http://localhost:11999/v1",
    })
    await _project("c2-standard-lonely", "standard", {})
    await _pending_rule_from("c2-sensitive-only", "The only rule anybody holds.")

    local, hosted = _transports(monkeypatch)
    result = await propose_skill(AGENT, DIFFERENT_RULE, "c2-standard-lonely", "SC-031")

    assert local == [] and hosted == []
    assert result["action"] == "created"
