# tests/test_skill_notes_travel.py
"""A lesson learned on one engagement is not injected into another engagement's hosted prompt.

`agent_skill_notes` is the other end of the table family sp61 has been narrowing, and it was
the more exposed end. `_fetch_skill_notes` took **no slug at all**, read the global table with
no project filter and no approval gate, and prepended the result to every task of every crew
on every project - so a note went into prompts routed by engagements that had nothing to do
with it. A note is a model's distillation of a reviewer's verbatim sentence about one named
engagement, and until this change the extraction was never even told to keep client detail
out. It is strictly worse than the deduplication candidates the previous commit narrowed:
injected as *instruction* rather than offered for comparison, and with no approval step where
the skills half has one.

**Two properties, and the second is what makes the first mean anything.** Every "the note did
not travel" assertion in this file is paired with an assertion that a permitted note *did* -
in the same block, from the same call. That is the trap this branch has already fallen into
once, when a leak test asserted the absence of a request that could not have existed. A fix
that injected nothing at all would pass every negative here and fail every positive.

Nothing in this file reaches a provider: the injection path reads the database only, and the
write door's model call is substituted at `project_completion`, the seam it now goes through.
"""
import ast
import json
from pathlib import Path

import pytest
import pytest_asyncio

from api.config import get_settings
from api.services.run_service import _fetch_skill_notes, _note_may_travel

AGENT = "interaction_designer"
CREW = "assessment_design"

_SECRET = "Never repeat the Q3 outage at Iberdrola in an interview welcome."
_SHAREABLE = "State the units on every figure you carry forward."
_UNATTRIBUTED = "A lesson recorded before anybody wrote down which engagement it came from."


@pytest.fixture(autouse=True)
def _isolated_system_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _project(slug: str, mode: str) -> None:
    from api.database import get_connection, insert_project

    async with get_connection(slug) as conn:
        await insert_project(
            conn, slug=slug, llm_mode=mode, sector="rail",
            config_json=json.dumps({
                "local_fast_model": "gemma4:fast",
                "local_fast_url": "http://localhost:11999/v1",
            }),
        )


async def _note(note: str, source_project: str | None) -> int:
    from api.database import get_system_connection, insert_skill_note

    async with get_system_connection() as conn:
        return await insert_skill_note(
            conn, agent_name=AGENT, note=note,
            raw_input="the reviewer's own sentence", source_project=source_project,
        )


# ── the injection ──────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_sensitive_engagements_note_is_not_injected_into_a_hosted_run():
    """The leak, driven as the review drove it - and with a control in the same block.

    `_SHAREABLE` belongs to the running project itself, so the block is never empty and this
    asserts *which* note was withheld rather than that nothing was injected.
    """
    await _project("notes-sensitive-a", "sensitive")
    await _project("notes-standard-b", "standard")
    await _note(_SECRET, "notes-sensitive-a")
    await _note(_SHAREABLE, "notes-standard-b")

    block = await _fetch_skill_notes(CREW, "notes-standard-b")

    assert _SECRET not in block, (
        "a sensitive engagement's note was prepended to a task routed to a hosted model"
    )
    assert _SHAREABLE in block, "the withholding took the running project's own note with it"


@pytest.mark.asyncio
async def test_a_note_from_another_permitted_engagement_still_travels():
    """The control on the rule itself.

    A note is meant to be a general lesson applied wherever that agent works. Withholding
    every note that came from somewhere else would end the feature while passing the test
    above, so the rule has to be about egress and not about provenance alone.
    """
    await _project("notes-standard-one", "standard")
    await _project("notes-standard-two", "standard")
    await _note(_SHAREABLE, "notes-standard-one")

    block = await _fetch_skill_notes(CREW, "notes-standard-two")

    assert _SHAREABLE in block


@pytest.mark.asyncio
async def test_a_run_that_keeps_its_inference_local_is_shown_every_note():
    """Nothing leaves, so nothing is withheld - the same first question as the candidates.

    The note from the *sensitive* engagement is the one that matters here: a standard one
    would travel under any version of the rule and would prove nothing about this branch.
    """
    await _project("notes-sensitive-runner", "sensitive")
    await _project("notes-sensitive-other", "sensitive")
    await _project("notes-standard-other", "standard")
    await _note(_SECRET, "notes-sensitive-other")
    await _note(_SHAREABLE, "notes-standard-other")
    await _note(_UNATTRIBUTED, None)

    block = await _fetch_skill_notes(CREW, "notes-sensitive-runner")

    assert _SECRET in block
    assert _SHAREABLE in block
    assert _UNATTRIBUTED in block


@pytest.mark.asyncio
async def test_a_note_naming_no_engagement_is_withheld_from_a_hosted_run(caplog):
    """Fails closed, and this is every row written before the column existed.

    The cost is stated rather than hidden: those notes stop being injected on a hosted project
    until they are written again, and are still injected on a project that keeps inference
    local (the test above). One row on the live deployment.
    """
    await _project("notes-standard-asker", "standard")
    await _note(_UNATTRIBUTED, None)
    await _note(_SHAREABLE, "notes-standard-asker")

    with caplog.at_level("INFO", logger="api.services.run_service"):
        block = await _fetch_skill_notes(CREW, "notes-standard-asker")

    assert _UNATTRIBUTED not in block
    assert _SHAREABLE in block
    assert any("note(s) withheld" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_an_approved_library_skill_is_unaffected_by_any_of_this():
    """The two sources in that block are different kinds of thing and only one is narrowed.

    A `global` approved skill is the agent's published instruction on every engagement by
    design - the exemption `_candidates_that_may_travel` argues for and `list_skills` turns
    on. If the *egress* narrowing ever reached it, the agent would silently lose its library
    on hosted projects.

    `scope="global"` is written explicitly since sp65, and it is what keeps this test about
    egress. A skill also carries a scope now, and a project-scoped one would fail to reach
    this run for an entirely different and correct reason - the two filters would be
    indistinguishable here, and this file is not the one that tests the scope
    (tests/test_skill_scope.py is). The origin stays a *sensitive* engagement on purpose:
    that is the case the egress rule would withhold if it applied to skills, and it does not.
    """
    from api.database import get_system_connection, insert_skill
    from api.services.run_service import _SNAKE_TO_DISPLAY

    await _project("notes-standard-lib", "standard")
    async with get_system_connection() as conn:
        await insert_skill(
            conn, name="Units", description=_SHAREABLE, source="revision",
            source_project="notes-sensitive-origin", status="approved", scope="global",
            agents=[_SNAKE_TO_DISPLAY[AGENT]],
        )

    block = await _fetch_skill_notes(CREW, "notes-standard-lib")

    assert "AGENT SKILLS" in block
    assert _SHAREABLE in block


@pytest.mark.asyncio
async def test_the_rule_is_asked_of_the_grant_and_not_of_the_mode_name():
    """`force_local_inference` narrows a `standard` project below what its mode declares.

    A note from such an engagement must be withheld from a hosted run, and a check written as
    `llm_mode == "sensitive"` would send it. This is the case that tells `project_permits`
    apart from a mode comparison.
    """
    from api.database import get_connection

    await _project("notes-forced-local", "standard")
    await _project("notes-plain-standard", "standard")
    async with get_connection("notes-forced-local") as conn:
        await conn.execute(
            "UPDATE projects SET force_local_inference=1 WHERE slug=?", ("notes-forced-local",)
        )
        await conn.commit()
    await _note(_SECRET, "notes-forced-local")
    await _note(_SHAREABLE, "notes-plain-standard")

    block = await _fetch_skill_notes(CREW, "notes-plain-standard")

    assert _SECRET not in block
    assert _SHAREABLE in block


def test_the_injection_cannot_be_called_without_the_engagement_it_is_for():
    """The slug is positional and has no default, so a caller cannot forget it silently.

    That is the whole of the defect: the old signature was `(crew_name)`, which made the
    routing question unaskable rather than unasked.
    """
    import inspect

    params = inspect.signature(_fetch_skill_notes).parameters
    assert list(params) == ["crew_name", "slug"]
    assert params["slug"].default is inspect.Parameter.empty


# ── the write door ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def _fake_extraction(monkeypatch):
    """Substitute the seam, not a provider client.

    `project_completion` is what the door now calls, so stubbing a provider class would leave
    the routing untested and would be blind to the other provider entirely. Yields the calls
    so a test can assert which slug and tier the reviewer's sentence was routed on.
    """
    calls: list[dict] = []

    async def _completion(slug, tier, messages, *, system=None, max_tokens=1024):
        calls.append({"slug": slug, "tier": tier, "messages": messages, "system": system})
        return "Avoid naming an incident in a welcome."

    monkeypatch.setattr("api.services.llm_client.project_completion", _completion)
    return calls


@pytest.mark.asyncio
async def test_the_reviewers_sentence_is_routed_on_the_engagement_it_is_about(
    client, _fake_extraction
):
    """C4. The door held no slug, so the reviewer's verbatim words went to hosted Anthropic
    whatever the engagement's mode - including a sensitive one, where
    `project_permits(slug, HOSTED_INFERENCE)` would have answered False and nothing asked."""
    res = await client.post("/agent-skill-notes", json={
        "agent_name": AGENT, "raw_input": "Maya named the Q3 outage at Iberdrola.",
        "slug": "notes-write-sensitive",
    })

    assert res.status_code == 201
    assert len(_fake_extraction) == 1
    assert _fake_extraction[0]["slug"] == "notes-write-sensitive"
    assert _fake_extraction[0]["tier"] == "fast"
    assert "Iberdrola" in _fake_extraction[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_the_note_is_stored_with_the_engagement_it_came_from(client, _fake_extraction):
    """The other half, and the one the injection depends on. Routing decides where the
    reviewer's sentence goes once; the stored slug is what lets every later run decide where
    the distilled note may go."""
    from api.database import get_system_connection, fetch_skill_notes

    res = await client.post("/agent-skill-notes", json={
        "agent_name": AGENT, "raw_input": "Some feedback.", "slug": "notes-write-origin",
    })
    assert res.status_code == 201

    async with get_system_connection() as conn:
        rows = await fetch_skill_notes(conn, agent_name=AGENT)
    stored = next(r for r in rows if r["id"] == res.json()["id"])
    assert stored["source_project"] == "notes-write-origin"


@pytest.mark.asyncio
async def test_a_note_with_no_engagement_is_refused_rather_than_stored(client, _fake_extraction):
    """422, and nothing routed. A blank slug is a caller that lost one, and a note stored
    without an engagement could never be shown to a hosted run again - so accepting it would
    quietly create a dead row while looking like success."""
    for missing in ("", "   "):
        res = await client.post("/agent-skill-notes", json={
            "agent_name": AGENT, "raw_input": "Some feedback.", "slug": missing,
        })
        assert res.status_code == 422

    res = await client.post("/agent-skill-notes", json={
        "agent_name": AGENT, "raw_input": "Some feedback.",
    })
    assert res.status_code == 422
    assert _fake_extraction == [], "a slugless call still reached a model"


@pytest.mark.asyncio
async def test_a_failed_extraction_stores_nothing_rather_than_the_raw_feedback(client, monkeypatch):
    """The direction of the failure matters.

    `raw_input` is the sentence that must not travel unbounded. Falling back to storing it as
    the note would put the reviewer's verbatim words into every future prompt for that agent -
    exactly what the extraction exists to prevent - so the door refuses instead.
    """
    from api.database import get_system_connection, fetch_skill_notes

    async def _boom(*a, **k):
        raise RuntimeError("no model")

    monkeypatch.setattr("api.services.llm_client.project_completion", _boom)

    res = await client.post("/agent-skill-notes", json={
        "agent_name": AGENT, "raw_input": "Maya named the Q3 outage at Iberdrola.",
        "slug": "notes-write-broken",
    })

    assert res.status_code == 502
    async with get_system_connection() as conn:
        assert await fetch_skill_notes(conn, agent_name=AGENT) == []


@pytest.mark.asyncio
async def test_the_extraction_is_told_to_keep_the_client_out_of_the_note(client, _fake_extraction):
    """Asserted on the system prompt that is **sent**, not on the module constant.

    Second line of defence and labelled as one: a prompt asks a model to behave and a model's
    output is not a guarantee. What bounds the disclosure is `source_project` and
    `_note_may_travel`; this narrows what a correctly-behaving extraction writes down. It was
    absent here while its sibling `extract_skill` has always had it - and this is the one of
    the two whose output is injected into every crew prompt.
    """
    await client.post("/agent-skill-notes", json={
        "agent_name": AGENT, "raw_input": "Some feedback.", "slug": "notes-write-generic",
    })

    system = _fake_extraction[0]["system"]
    assert "generic" in system
    assert "never the incident" in system
    assert "client" in system


# ── the guards on the two rules ────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PRODUCTION = ("api/**/*.py", "agents/**/*.py", "scripts/**/*.py")


def _callers_of(name: str) -> dict[str, str]:
    """Every production call of `name`, attributed to the function enclosing it."""
    found: dict[str, str] = {}
    for pattern in _PRODUCTION:
        for path in sorted(_REPO_ROOT.glob(pattern)):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            tree = ast.parse(path.read_text(), filename=str(path))
            stack: dict[int, str] = {}

            def visit(node: ast.AST, prefix: list[str]) -> None:
                for child in ast.iter_child_nodes(node):
                    inner = prefix
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        inner = prefix + [child.name]
                    stack[id(child)] = ".".join(inner) or "<module>"
                    visit(child, inner)

            visit(tree, [])
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                callee = (
                    node.func.attr if isinstance(node.func, ast.Attribute)
                    else node.func.id if isinstance(node.func, ast.Name)
                    else None
                )
                if callee == name:
                    found[f"{rel}::{stack[id(node)]}"] = f"{rel}:{node.lineno}"
    return found


# The one place the unnarrowed candidate list is assembled, and the one place it is narrowed.
# Declared as a set so a vanished caller fails as loudly as a new one.
_DECLARED_UNNARROWED_READERS = {"api/services/skills_service.py::propose_skill"}
_DECLARED_NARROWERS = {"api/services/skills_service.py::find_duplicate_skill"}


def test_the_unnarrowed_candidate_read_has_exactly_one_caller():
    """I2. `_rules_already_held` reads `pending` and `approved` across every engagement.

    The narrowing sits one function later, at the send, which is the right place - the check
    belongs before the send, and filtering at the read would make the read's answer depend on
    the proposing project with no slug in its signature to make that honest. But the safety of
    that placement is entirely a property of *who calls the read*: a second consumer that sent
    the list anywhere would inherit nothing.

    CLAUDE.md's precedent for exactly this is
    `test_the_wide_project_config_writer_has_exactly_one_production_caller`, and this is the
    same shape. It cannot see a call through a variable, a `getattr`, or a name assembled at
    run time - what it catches is somebody adding a second ordinary caller.
    """
    assert set(_callers_of("_rules_already_held")) == _DECLARED_UNNARROWED_READERS, (
        "the candidate list assembled by _rules_already_held is global across engagements and "
        "is only safe because find_duplicate_skill narrows it before sending. A new caller "
        "inherits none of that. Callers found: "
        f"{sorted(_callers_of('_rules_already_held'))}"
    )


def test_the_narrowing_is_applied_wherever_candidates_are_sent():
    """The other half: the narrower must still be called, and from the send.

    Set equality, so deleting the call fails here as well as failing the behaviour tests -
    which matters because this one names *where* the rule is meant to live.
    """
    assert set(_callers_of("_candidates_that_may_travel")) == _DECLARED_NARROWERS, (
        "the candidate narrowing must be applied by the function that sends. Callers found: "
        f"{sorted(_callers_of('_candidates_that_may_travel'))}"
    )


@pytest.mark.parametrize(
    "status",
    ["pending", "rejected", "banana", "Approved", "APPROVED", "", None],
    ids=["pending", "rejected", "unknown", "title-case", "upper-case", "empty", "null"],
)
def test_only_the_exact_status_approved_is_exempt_from_the_candidate_narrowing(
    monkeypatch, status
):
    """M2. The exemption is an allow-list, and nothing asserted that until now.

    Mutating `== "approved"` to `!= "pending"` passed the entire suite, because the two are
    behaviourally identical for the two statuses `_DEDUP_STATUSES` holds today. The protection
    is forward-looking - whoever adds a third status is exactly the person a passing suite
    would fail to warn - so it is asserted against the statuses that do not exist yet.
    """
    from api.services import skills_service
    from api.services.deployment_modes import Capability

    # The proposer is granted hosted inference; the candidate's engagement is not. So the only
    # thing that can let this candidate through is the status exemption.
    def _permits(slug, capability):
        assert capability is Capability.HOSTED_INFERENCE
        return slug == "proposer"

    monkeypatch.setattr("api.services.deployment_modes.project_permits", _permits)

    candidate = {"id": 1, "source_project": "elsewhere", "name": "n", "description": "d"}
    if status is not None:
        candidate["status"] = status

    assert skills_service._candidates_that_may_travel("proposer", [candidate]) == []


def test_a_candidate_that_is_approved_is_exempt(monkeypatch):
    """The control on the parametrised test above.

    Without it, a narrowing that withheld every candidate regardless of status would pass all
    seven cases and end deduplication against the library.
    """
    from api.services import skills_service
    from api.services.deployment_modes import Capability

    def _permits(slug, capability):
        assert capability is Capability.HOSTED_INFERENCE
        return slug == "proposer"

    monkeypatch.setattr("api.services.deployment_modes.project_permits", _permits)

    candidate = {"id": 1, "source_project": "elsewhere", "status": "approved",
                 "name": "n", "description": "d"}

    assert skills_service._candidates_that_may_travel("proposer", [candidate]) == [candidate]
