# tests/test_skill_candidates_travel.py
"""A deduplication candidate travels only where its own engagement's material may travel.

**This file was `test_skill_notes_travel.py` and most of it has gone with the mechanism it
tested.** `agent_skill_notes` was the other end of the table family sp61 narrowed: a model's
distillation of a reviewer's verbatim sentence about one named engagement, prepended to every
task of every crew on every project, with no approval step where the skills half has one. sp61
gave it a `source_project` and an egress rule; sp65 retired it altogether, because it was never
intended - feedback was always meant to improve the output in hand and then be *evaluated* as
a project-level or global skill through the skills review, which `intent='skill'` on the review
door now does (tests/test_review_intent_proposes.py).

What survives is what was never about notes: the egress narrowing on the **candidates** a
proposal is compared against, and the two source guards that keep it where it belongs. Both
halves of every rule are still asserted here - a narrowing that withheld everything would pass
each negative and fail each positive.

Nothing in this file reaches a provider: what is left reads the database and the source tree.
"""
import ast
import json
from pathlib import Path

import pytest

from api.config import get_settings
from api.services.run_service import _fetch_skill_notes

AGENT = "interaction_designer"
CREW = "assessment_design"

_SHAREABLE = "State the units on every figure you carry forward."


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


# ── the injection ──────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_approved_library_skill_is_unaffected_by_any_of_this():
    """The egress narrowing is about candidates, and it must not reach the injection.

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


def test_the_injection_cannot_be_called_without_the_engagement_it_is_for():
    """The slug is positional and has no default, so a caller cannot forget it silently.

    That is the whole of the defect: the old signature was `(crew_name)`, which made the
    routing question unaskable rather than unasked.
    """
    import inspect

    params = inspect.signature(_fetch_skill_notes).parameters
    assert list(params) == ["crew_name", "slug"]
    assert params["slug"].default is inspect.Parameter.empty


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
