# tests/test_review_intent_proposes.py
"""A reviewer who says "make this a standing rule" files a proposal, and the notes path is gone.

**There were two ways a correction reached an agent and only one of them was designed.** A
skill is proposed, deduplicated, held `pending`, approved by a human and scoped; a note was
the reviewer's sentence distilled by a model and injected into every engagement's prompts with
no gate at all. Patrick's account, 8 September: there was never any intent for a notes
mechanism - feedback was always meant to improve the output in hand and then be *evaluated* as
a project-level or global skill through the skills review.

So `intent='skill'` - a radio `ReviewDialog` has offered all along, which set `kind='skill'` on
`output_changes` where nothing read the value - routes into the queue sp61 built, and
`agent_skill_notes` retires.

**Three properties, and the second is the one a careless routing change breaks in silence.**

1. `intent='skill'` produces a **row**. It has never produced anything, so a 200 says nothing
   whatever about it: every assertion here is on what is in `skills`, and on the two columns
   that decide where an approved rule would reach - `source_project` and `scope`.
2. `intent='change_request'` still reaches the agent's next run through
   `fetch_open_change_requests`. Get this wrong and a reviewer who asked for a revision gets a
   proposal instead - no error, and they find out when the artefact comes back unchanged.
3. Nothing in the source names the retired table. Asserted over the source rather than by the
   table being empty, because an empty table passes against a reader that would fill it on the
   next review.

Nothing here reaches a provider: `project_completion` - the seam `find_duplicate_skill` routes
the deduplication through - is substituted for every test in this module, autouse, whether or
not the test expects it to be called.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping
from unittest.mock import AsyncMock, patch

import pytest

from api.config import get_settings

SLUG = "review-proposes-test"
ELSEWHERE = "review-proposes-other"
PROJECT = {
    "client_slug": SLUG, "llm_mode": "standard", "sector": "utilities",
    "stakeholder_groups": [], "value_stream_labels": [], "review_gates": True,
    "slack_channel": "",
    "approver_name": "Approver Fixture", "approver_email": "approver@fixture.test",}

# The reviewer's own sentence, in the shape Patrick's worked example takes: a rule about how to
# write an instrument, drawn from a correction made on one engagement.
RULE = "Refer to investments by their purpose rather than by their headline figure."
REVISION = "The second paragraph still names the wrong programme - please correct it."

AGENT = "value_chain_mapper"
ROLE = "Value Chain Mapper"


@pytest.fixture(autouse=True)
def _isolated_databases(tmp_path, monkeypatch):
    """A system database and a project database of this test's own.

    `tests/conftest.py` points both at a fixed path that persists between runs, and this module
    asserts on `skills` - a **system** table, which no per-module project `.db` unlink reaches.
    Left shared, the first run would file a proposal and every run afterwards would find it as a
    deduplication candidate and increment it instead, so `action` would be `created` once and
    `incremented` for ever: the trap CLAUDE.md records, arriving through the queue.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_provider_call():
    """Substitute the seam, never a provider client.

    `propose_skill` -> `find_duplicate_skill` -> `llm_client.project_completion`, routed on the
    proposing project's own mode. With an empty library there are no candidates and the call is
    never made, so this is belt-and-braces - and it is autouse for exactly that reason: two real
    outbound calls have already happened on this branch, both from a test whose stub was not yet
    in place on a path the author had reasoned could not reach one.
    """
    with patch(
        "api.services.llm_client.project_completion",
        new=AsyncMock(return_value='{"match_id": null, "reason": "nothing held"}'),
    ) as stub:
        yield stub


@pytest.fixture(autouse=True)
def _granted_authority():
    """This module is about where an intent goes, not about who may record one.

    The `client` fixture's sysadmin token names no real user, so `caller_may_contribute`
    correctly answers False for it and the door would 403 first. Patched on the router module,
    where the name is looked up. tests/test_write_door_authority.py drives the gate itself.
    """
    with patch("api.routers.reviews.caller_may_contribute", new=AsyncMock(return_value=True)):
        yield


async def _seed_review(client, slug: str = SLUG) -> tuple[int, int]:
    """A project with one of Alex's outputs and one pending review. Returns (review_id, output_id)."""
    body = dict(PROJECT, client_slug=slug)
    await client.post("/projects", json=body)
    from api.database import get_connection

    async with get_connection(slug) as conn:
        cur = await conn.execute(
            "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
            " version, is_current, review_status)"
            f" VALUES (1,'{AGENT}','value_chain_model','m_v1.json',1,1,'pending')"
        )
        output_id = cur.lastrowid
        cur = await conn.execute(
            "INSERT INTO human_reviews (output_id, decision) VALUES (?, 'pending')",
            (output_id,),
        )
        review_id = cur.lastrowid
        await conn.commit()
    return review_id, output_id


async def _skills_for(role: str = ROLE) -> list[dict]:
    from api.database import fetch_skills, get_system_connection

    async with get_system_connection() as conn:
        return await fetch_skills(conn, agent_name=role)


# ── the correction becomes a proposal ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_reviewers_rule_is_filed_as_a_pending_proposal(client):
    """The row, not the response.

    `intent='skill'` has answered 200 since the day the radio was added and produced nothing at
    all, so a status code proves precisely nothing here. Four assertions, and each is a separate
    fact: the rule is stored, it is `pending` so no prompt sees it until a human approves, it
    carries the engagement it was written on, and it is scoped to that engagement rather than to
    all of them.
    """
    review_id, _ = await _seed_review(client)

    res = await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": RULE, "intent": "skill"},
    )
    assert res.status_code == 200

    proposals = [s for s in await _skills_for() if s["description"] == RULE]
    assert len(proposals) == 1, (
        "the reviewer's rule reached the skills queue exactly once, or not at all"
    )
    proposal = proposals[0]
    assert proposal["status"] == "pending", (
        "a proposal that is not pending is injected into every future run of this agent with "
        "nobody having approved it - the gate is the whole safety argument"
    )
    assert proposal["source_project"] == SLUG
    assert proposal["scope"] == "project", (
        "the reviewer decides at approval whether a rule widens; filing one already global "
        "would make the widening automatic, which is what sp65 exists to stop"
    )


@pytest.mark.asyncio
async def test_the_proposal_is_filed_against_the_agent_whose_output_was_reviewed(client):
    """Filed under the name the injection looks skills up by, or it can never reach a prompt.

    `agent_outputs.agent_name` holds the snake id the crews dispatch by; `agent_skill_assignments`
    is keyed by the role name. A proposal filed under the snake id is approvable, looks exactly
    like a working one, and is injected into nothing for ever - CLAUDE.md records that arriving
    once already, through `visual_illustrator`.
    """
    review_id, _ = await _seed_review(client)

    await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": RULE, "intent": "skill"},
    )

    assert [s["description"] for s in await _skills_for(ROLE)] == [RULE]
    assert await _skills_for(AGENT) == [], (
        "the proposal was filed under the snake id, which no approval can ever inject"
    )


@pytest.mark.asyncio
async def test_the_proposal_carries_the_engagement_the_correction_was_made_on(client):
    """The slug is the path's, never a default - and it is what makes the row reachable.

    A `project`-scoped row with no `source_project` matches no engagement and reaches nothing.
    `propose_skill` raises on a blank slug rather than filing one, and the route must not get
    round that by inventing a value: the proposal filed from a review on `SLUG` is offered to a
    run on `SLUG` and to no other.
    """
    from api.services.run_service import _skill_applies_here

    review_id, _ = await _seed_review(client)

    await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": RULE, "intent": "skill"},
    )

    proposal = next(s for s in await _skills_for() if s["description"] == RULE)
    approved = dict(proposal, status="approved")
    assert _skill_applies_here(SLUG, approved) is True
    assert _skill_applies_here(ELSEWHERE, approved) is False


@pytest.mark.asyncio
async def test_an_approval_proposes_nothing(client):
    """An approval is not feedback, on this path as on the change-request one.

    The guard has to key on the decision rather than on the notes being non-empty: with empty
    notes the two are indistinguishable, and an approval carrying a comment would otherwise file
    the reviewer's compliment as a standing rule for the agent.
    """
    review_id, _ = await _seed_review(client)

    await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "approved", "notes": "Good - exactly right.", "intent": "skill"},
    )

    assert await _skills_for() == []


@pytest.mark.asyncio
async def test_a_blank_rule_proposes_nothing(client):
    """Whitespace is not a rule. `_derive_skill_name` would name it "Proposed Agent Skill"."""
    review_id, _ = await _seed_review(client)

    await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": "   ", "intent": "skill"},
    )

    assert await _skills_for() == []


@pytest.mark.asyncio
async def test_a_proposal_that_cannot_be_filed_does_not_fail_the_review(client, monkeypatch):
    """The review door releases a paused crew, and a nice-to-have must never hold that shut.

    `HumanInputTool` polls `human_reviews` for up to twenty-four hours; this PATCH is what ends
    that wait. Refusing it because the queue was unreachable - a locked system database, a model
    that would not answer, an agent id `_SNAKE_TO_DISPLAY` has no entry for - would leave the
    crew blocked to protect a suggestion. The same contract `SkillProposalTool` states for
    itself, one door over: it cannot fail the thing it is attached to.
    """
    from api.services import skills_service

    async def _explode(*_a, **_k):
        raise RuntimeError("the queue is unreachable")

    monkeypatch.setattr(skills_service, "propose_skill", _explode)
    review_id, output_id = await _seed_review(client)

    res = await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": RULE, "intent": "skill"},
    )

    assert res.status_code == 200
    from api.database import get_connection

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT decision FROM human_reviews WHERE id=?", (review_id,)
        )
        changes = await conn.execute_fetchall(
            "SELECT COUNT(*) FROM output_changes WHERE output_id=?", (output_id,)
        )
    assert rows[0][0] == "changes_requested", "the reviewer's decision was lost with the proposal"
    assert changes[0][0] == 1


# ── and the other intent still reaches the agent ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_change_request_still_reaches_the_agents_next_run(client):
    """The half a careless routing change breaks in silence.

    Asserted where it holds - on `fetch_open_change_requests`, which is what
    `_fetch_change_requests` in `run_service.py` reads to build the block prepended to the
    crew's next task - rather than on the `output_changes` row existing. A row with the wrong
    `kind` exists, is visible in the change log, and is skipped by the injection: exactly the
    state `intent='skill'` was in before this change, and the state a reviewer asking for a
    revision must never be put into.
    """
    from api.database import fetch_open_change_requests, get_connection

    review_id, output_id = await _seed_review(client)

    await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": REVISION, "intent": "change_request"},
    )

    async with get_connection(SLUG) as conn:
        open_requests = await fetch_open_change_requests(conn, output_ids=[output_id])
    assert [r["request"] for r in open_requests] == [REVISION]
    assert await _skills_for() == [], (
        "a revision request was filed as a skill proposal - the reviewer asked for one thing "
        "and got the other, and nothing anywhere says so"
    )


@pytest.mark.asyncio
async def test_the_default_intent_still_reaches_the_agents_next_run(client):
    """The same property through the body a reviewer who touched no radio sends.

    An omitted `intent` and `intent='change_request'` are different requests and must reach the
    same row, which is why both are driven rather than one standing for the other.
    """
    from api.database import fetch_open_change_requests, get_connection

    review_id, output_id = await _seed_review(client)

    await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": REVISION},
    )

    async with get_connection(SLUG) as conn:
        open_requests = await fetch_open_change_requests(conn, output_ids=[output_id])
    assert [r["request"] for r in open_requests] == [REVISION]
    assert await _skills_for() == []


@pytest.mark.asyncio
async def test_a_correction_is_unchanged_and_proposes_nothing(client):
    """The third intent, which reaches the agent through RAG rather than through either of these.

    Its `output_changes` row is still written with `kind='correction'`, and it is deliberately
    absent from `fetch_open_change_requests` - injecting it there too would say the same thing
    twice. Driven here so that a routing change cannot quietly collapse the three intents into
    two.
    """
    from api.database import fetch_open_change_requests, get_connection

    review_id, output_id = await _seed_review(client)

    await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": "ISS only maintains property",
              "intent": "correction"},
    )

    async with get_connection(SLUG) as conn:
        kinds = await conn.execute_fetchall(
            "SELECT kind FROM output_changes WHERE output_id=?", (output_id,)
        )
        open_requests = await fetch_open_change_requests(conn, output_ids=[output_id])
    assert [k[0] for k in kinds] == ["correction"]
    assert open_requests == []
    assert await _skills_for() == []


@pytest.mark.asyncio
async def test_the_skill_intent_still_records_the_change_against_the_output(client):
    """The proposal is added to what the door already did, not substituted for it.

    The change log is the record of what a reviewer asked of an output, and a rule filed on the
    queue is not that record - `changes_for_crew` would show the correction vanishing from the
    output's history the moment the reviewer chose the third radio.
    """
    from api.database import get_connection

    review_id, output_id = await _seed_review(client)

    await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": RULE, "intent": "skill"},
    )

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT kind, request FROM output_changes WHERE output_id=?", (output_id,)
        )
    assert [tuple(r) for r in rows] == [("skill", RULE)]


# ── the notes mechanism is gone, asserted over the source ───────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PRODUCTION_ROOTS = ("api", "agents", "scripts", "ui/src")
_SUFFIXES = {".py", ".ts", ".tsx"}

# The names the notes mechanism was made of. `fetch_skill_notes` is deliberately **not** here:
# it is a substring of `_fetch_skill_notes`, which survives - the skills half of that function
# is what injects an approved rule - so asserting its absence would assert the absence of the
# thing that replaced it.
#
# `skillNotesApi` and `agent-skill-notes` are here because the sweep reads `ui/src` too, and
# the frontend half is where the mechanism was actually reached from: a client that still had
# a `create` on it would be one import away from a second ungated channel, whatever the
# backend did.
_RETIRED = (
    "agent_skill_notes", "insert_skill_note", "create_skill_note", "_note_may_travel",
    "skillNotesApi", "agent-skill-notes",
)


def _non_test_sources() -> dict[str, str]:
    """Every non-test source file under the production roots, by path, as text."""
    found: dict[str, str] = {}
    for root in _PRODUCTION_ROOTS:
        for path in sorted((_REPO_ROOT / root).rglob("*")):
            if not path.is_file() or path.suffix not in _SUFFIXES:
                continue
            if "__tests__" in path.parts or path.name.startswith("test_"):
                continue
            if ".test." in path.name or ".spec." in path.name:
                continue
            found[path.relative_to(_REPO_ROOT).as_posix()] = path.read_text()
    return found


def _sources_naming(name: str, sources: Mapping[str, str]) -> set[str]:
    """Which of the given sources contain `name`. A pure function over given text.

    Pure, and driven below against text this file supplies, because three guards on this
    project have been wrong about their own reach - and a walk that can only be run against the
    real tree is a walk that cannot be asked what it saw. A one-sided test passes against a
    sweep that reports everything and against one that reports nothing.
    """
    return {path for path, text in sources.items() if name in text}


@pytest.mark.parametrize("name", _RETIRED)
def test_nothing_outside_the_tests_names_the_retired_notes_mechanism(name):
    """The absence, by mechanism.

    Asserted over the source rather than by the table being empty: an empty table passes
    perfectly well against a reader that would fill it on the next review, which is the state
    the live deployment is in today with its single row of this branch's own test data.
    """
    named_by = _sources_naming(name, _non_test_sources())
    assert named_by == set(), f"{name} survives in {sorted(named_by)}"


def test_the_sweep_reports_a_name_that_is_present_and_not_one_that_is_absent():
    """The control, over text this test supplies - so it is a fact rather than an intention."""
    given = {
        "keeps.py": "rows = await fetch_skill_notes(conn)\n",
        "clean.py": "rows = await fetch_skills(conn)\n",
    }
    assert _sources_naming("fetch_skill_notes", given) == {"keeps.py"}
    assert _sources_naming("agent_skill_notes", given) == set()


def test_the_sweep_reaches_the_files_the_retirement_touched():
    """And it reads the real tree, in both languages.

    Without this, a sweep whose roots were wrong - a renamed directory, a suffix left off -
    would report the empty set for every retired name and pass while the mechanism was untouched.
    """
    sources = _non_test_sources()
    for path in (
        "api/services/run_service.py",
        "api/routers/reviews.py",
        "api/database.py",
        "ui/src/components/ReviewDialog.tsx",
        "ui/src/api/endpoints.ts",
    ):
        assert path in sources, f"the sweep does not read {path}"
    assert _sources_naming("_fetch_skill_notes", sources), (
        "the sweep found the surviving injection nowhere, so it is reading nothing useful"
    )
    assert "__tests__" not in json.dumps(sorted(sources))
