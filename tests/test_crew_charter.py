# tests/test_crew_charter.py
"""Every crew declares a purpose and at least one trigger, and every trigger is real.

The declaration is `agents/charter.py`. Nothing here compares it with a list written in this
file: each trigger set is **derived from the code that implements that dispatch path** - the
`elif` ladder in `build_and_run_crew`, the approval graph plus `autostart_service`'s own
exclusion, the crew names Pamela's task descriptions contain, and the Chainlit console's
frozenset - and the declaration is held equal to the derivation. A test that asserted the
charter against a second hand-typed table would pass while both were wrong together, which is
this project's recorded failure mode.

The two declared defects are derived the same way, from the call sites and the factory
signatures. So a defect fixed in the code and left declared here fails, and a new one
introduced and not declared fails too - neither direction can go quiet.
"""
from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

from agents.charter import CREW_CHARTER, DISPATCH_PATHS, NOT_A_CREW, Trigger
from agents.graph import build_graph

GRAPH = build_graph()
CREW_IDS = frozenset(GRAPH.crews)


# ── Reading the dispatch code ─────────────────────────────────────────────────


def _module_source(relative_path: str) -> str:
    path = Path(relative_path)
    assert path.exists(), f"{relative_path} does not exist"
    return path.read_text()


def _definition(reference: str) -> str:
    """The source of the function or class a `"path/to/file.py:Name"` reference names.

    Parsed rather than imported, for the reason `agents/graph.py` and `agents/egress.py` parse
    rather than import: one of the four dispatch paths lives in `chainlit_app/app.py`, which
    pulls in Chainlit and reads settings at module scope, and a path whose module is merely
    heavy to import must not look absent.
    """
    relative_path, _, name = reference.partition(":")
    source = _module_source(relative_path)
    tree = ast.parse(source, filename=relative_path)
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{relative_path} defines nothing called {name!r}")


def _crew_dispatch_call_sites() -> dict[str, tuple[str, str, tuple[str, ...]]]:
    """Crew name to `(factory name, factory module, keyword names)`, read from the ladder.

    `build_and_run_crew` is one long `if/elif` on `crew_name`, each branch importing one crew
    factory and calling it. This walks that chain so the mapping and the arguments come from the
    dispatch code itself.
    """
    source = _module_source("api/services/run_service.py")
    tree = ast.parse(source)
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "build_and_run_crew"
    )

    call_sites: dict[str, tuple[str, str, tuple[str, ...]]] = {}

    def crew_names(test: ast.expr) -> list[str]:
        if not (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)):
            return []
        if test.left.id != "crew_name":
            return []
        operator, comparator = test.ops[0], test.comparators[0]
        if isinstance(operator, ast.Eq) and isinstance(comparator, ast.Constant):
            return [comparator.value]
        if isinstance(operator, ast.In) and isinstance(comparator, (ast.Tuple, ast.List)):
            return [element.value for element in comparator.elts]
        return []

    def walk(branches: list[ast.stmt]) -> None:
        for statement in branches:
            if not isinstance(statement, ast.If):
                continue
            body = ast.Module(body=statement.body, type_ignores=[])
            factories = [
                node for node in ast.walk(body)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id.startswith("create_") and node.func.id.endswith("_crew")
            ]
            imported = {
                alias.name: node.module
                for node in ast.walk(body) if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            for crew in crew_names(statement.test):
                if not factories:
                    continue
                call = factories[0]
                call_sites[crew] = (
                    call.func.id,
                    imported[call.func.id],
                    tuple(keyword.arg for keyword in call.keywords),
                )
            walk(statement.orelse)

    walk(function.body)
    return call_sites


def _binds(factory_name: str, module_name: str, keywords: tuple[str, ...]) -> str | None:
    """None when the call site's keywords bind to the factory, else the `TypeError` message."""
    factory = getattr(importlib.import_module(module_name), factory_name)
    try:
        inspect.signature(factory).bind(**{keyword: None for keyword in keywords})
    except TypeError as error:
        return str(error)
    return None


# ── Derived trigger sets, one per dispatch path ───────────────────────────────


def _pam_only_crews() -> frozenset[str]:
    """The crews only Pamela may dispatch, read from `autostart_service`'s own constant.

    The constant lives beside the approval path but the reason it records is a property of
    `build_and_run_crew` - the `crew_runs` row must carry an `orchestration_run_id`, which only
    an orchestration sets - so it binds the REST path exactly as much, and both derivations
    below use it. `test_a_run_row_the_rest_path_creates_cannot_start_the_pam_only_crew` proves
    that reading behaviourally rather than taking the comment's word for it.
    """
    from api.services.autostart_service import _PAM_DISPATCHED_ONLY

    return frozenset(_PAM_DISPATCHED_ONLY)


def _rest_startable() -> frozenset[str]:
    """`POST /projects/{slug}/run` takes any crew name, so every crew but the PAM-only one."""
    return CREW_IDS - _pam_only_crews()


def _approval_startable() -> frozenset[str]:
    """Only a crew directly below another can be released by that other's commit."""
    from api.services.crew_graph import CREW_DEPENDENCIES, downstream_of

    downstream = {
        crew for upstream in CREW_DEPENDENCIES for crew in downstream_of(upstream)
    }
    return frozenset(downstream) - _pam_only_crews()


def _pam_startable() -> frozenset[str]:
    """The crew names Pamela's tasks actually contain.

    Two sources, neither of them this file: `pam_crew.py` says which task builders are wired
    into her two crews, and `pam_agent.py`'s task descriptions say which crew each one tells
    her to run.
    """
    import re

    crew_source = _module_source("agents/crews/pam_crew.py")
    task_builders = {
        node.func.id
        for node in ast.walk(ast.parse(crew_source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id.startswith("create_run_") and node.func.id.endswith("_task")
    }
    assert task_builders, "no task builders found in pam_crew.py - the derivation is empty"

    named: set[str] = set()
    for builder in sorted(task_builders):
        named.update(re.findall(r"crew_name=['\"]([a-z_]+)['\"]", _definition(
            f"agents/pam/pam_agent.py:{builder}"
        )))
    return frozenset(named)


def _chainlit_offered() -> frozenset[str]:
    """The names the Chainlit console accepts, from its `_VALID_CREWS` frozenset."""
    source = _module_source("chainlit_app/app.py")
    assignment = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Assign)
        and any(getattr(target, "id", None) == "_VALID_CREWS" for target in node.targets)
    )
    return frozenset(
        node.value for node in ast.walk(assignment.value) if isinstance(node, ast.Constant)
    )


_DERIVED_STARTABLE = {
    Trigger.REST_RUN: _rest_startable,
    Trigger.APPROVAL_CASCADE: _approval_startable,
    Trigger.PAM_ORCHESTRATION: _pam_startable,
    Trigger.CHAINLIT_CONSOLE: lambda: _chainlit_offered() & CREW_IDS,
}


# ── The brief's two guards ────────────────────────────────────────────────────


@pytest.mark.parametrize("crew_id", sorted(CREW_IDS))
def test_every_crew_declares_a_purpose_and_at_least_one_trigger(crew_id):
    """Asserted on the graph node, not on `CREW_CHARTER`.

    The node is what the privacy page will render, and a declaration the node was never wired
    to is this project's recorded mistake - `AgentNode` had it once already.
    """
    crew = GRAPH.crews[crew_id]

    assert crew.purpose.strip(), f"{crew_id} has no purpose"
    assert crew.purpose.strip() != crew.display_name, (
        f"{crew_id}'s purpose is its label again, which says nothing a reader does not have"
    )
    assert len(crew.purpose.split()) >= 12, (
        f"{crew_id}'s purpose is too short to say what the crew does with the client's material"
    )
    assert crew.triggers, f"{crew_id} declares no way of being started"


@pytest.mark.parametrize("trigger", sorted(Trigger, key=lambda t: t.value))
def test_every_dispatch_path_exists_where_it_says_it_does(trigger):
    """Every declared path resolves in the code, and its entrypoint calls a crew dispatcher.

    This is the assertion that stops a trigger being decorative. The entrypoint reference is
    resolved out of its module's source and its body must name the dispatcher it claims to
    call, so renaming or moving either fails here.

    Doors are checked for existence only. The chain from an outside-facing handler to a
    dispatcher is four hops long for the orchestration path - endpoint, service, PAM crew,
    `RunCrewTool` - and grepping a chain that length would be brittle rather than strong;
    `test_the_orchestration_path_dispatches_through_pams_own_tool` covers that end instead.
    """
    path = DISPATCH_PATHS[trigger]

    body = _definition(path.entrypoint)
    assert path.dispatcher in body, (
        f"{path.entrypoint} does not call {path.dispatcher} - the declared path no longer "
        f"starts a crew"
    )
    assert path.doors, f"{trigger.value} names no door a request arrives at"
    for door in path.doors:
        _definition(door)


@pytest.mark.parametrize("crew_id", sorted(CREW_IDS))
def test_every_trigger_a_crew_names_is_a_declared_dispatch_path(crew_id):
    for trigger in GRAPH.crews[crew_id].triggers:
        assert trigger in DISPATCH_PATHS, (
            f"{crew_id} names {trigger} and no dispatch path declares it"
        )


# ── The trigger sets, held against the code that implements each path ─────────


@pytest.mark.parametrize("trigger", sorted(Trigger, key=lambda t: t.value))
def test_each_path_is_declared_on_exactly_the_crews_it_can_start(trigger):
    """The declaration equals the set derived from that path's own code.

    Both directions matter and fail differently. A crew declaring a trigger it cannot be
    started by puts a way in on the page that does not exist; a crew missing one leaves a way
    in off it, which on a page about who can set the client's material moving is the worse of
    the two.
    """
    declared = {
        crew_id for crew_id in CREW_IDS if trigger in GRAPH.crews[crew_id].triggers
    }
    derived = _DERIVED_STARTABLE[trigger]()

    assert derived, f"the derivation for {trigger.value} produced nothing - it proves nothing"
    assert declared == derived, (
        f"{trigger.value}: declared on {sorted(declared)}, but the code says "
        f"{sorted(derived)} - declared and not startable: "
        f"{sorted(declared - derived)}; startable and not declared: {sorted(derived - declared)}"
    )


def test_the_rest_endpoint_constrains_no_crew_name():
    """Why `REST_RUN` is derived as "every crew": the request model enumerates nothing.

    If a `Literal` or an enum ever lands on `RunRequest.crew`, the derivation above stops being
    "all of them" and this is what says so.
    """
    from api.models import RunRequest

    assert RunRequest(crew="a-name-no-registry-knows").crew == "a-name-no-registry-knows"
    for crew_id in sorted(CREW_IDS):
        assert RunRequest(crew=crew_id).crew == crew_id


def test_the_orchestration_path_dispatches_through_pams_own_tool():
    """The far end of the orchestration path, from the graph rather than by grep.

    Both of PAM's crews build her from `get_tools_for_agent("pam", ...)`, so her holding
    `RunCrewTool` is what makes every crew she names reachable. Take the tool away and the
    orchestration path starts nothing, whatever her task descriptions still say.
    """
    assert "RunCrewTool" in GRAPH.agents["pam"].tools


def test_the_approval_path_cannot_start_the_first_crew_in_the_pipeline():
    """A property of the shape, spelled out because it is easy to assume otherwise.

    `discovery_mapping` waits on nothing, so nothing lists it as an upstream, so no commit can
    ever release it. It is startable only by hand or by an orchestration.
    """
    assert "discovery_mapping" not in _approval_startable()
    assert Trigger.APPROVAL_CASCADE not in GRAPH.crews["discovery_mapping"].triggers


@pytest.mark.asyncio
async def test_a_run_row_the_rest_path_creates_cannot_start_the_pam_only_crew(
    tmp_path, monkeypatch
):
    """Behavioural proof of the one exclusion both derivations depend on.

    `_PAM_DISPATCHED_ONLY` is a comment's claim until something drives it. This creates the
    `crew_runs` row exactly as `api/routers/run.py` does - `insert_crew_run` with no
    `orchestration_run_id` - on a project whose `interview_method` is 'agent', so the only
    remaining precondition is the one under test, and `build_and_run_crew` refuses it.

    Its own DATABASE_DIR, per CLAUDE.md's persistent-database trap: this writes a project row
    and would poison the shared database for every later run.
    """
    from api.config import get_settings

    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        from api.database import (
            fetch_project,
            get_connection,
            insert_crew_run,
            insert_project,
        )

        slug = "charter-pam-only"
        async with get_connection(slug) as conn:
            await insert_project(
                conn, slug=slug, llm_mode="standard", sector="rail",
                config_json='{"interview_method": "agent"}',
            )
            project = await fetch_project(conn, slug=slug)
            run_id = await insert_crew_run(
                conn, project_id=project["id"],
                crew_name="discovery_interviews", status="running",
            )

        from unittest.mock import patch

        from api.services.run_service import build_and_run_crew

        with patch(
            "api.services.run_service.load_project_config",
            return_value={"sector": "rail", "interview_method": "agent"},
        ):
            with pytest.raises(ValueError, match="orchestration_run_id"):
                await build_and_run_crew(slug, "discovery_interviews", run_id)
    finally:
        get_settings.cache_clear()


# ── Defects: a path that exists and fails must be able to say so ──────────────


def test_a_crew_declares_a_defect_exactly_when_its_dispatch_call_will_not_bind():
    """The crew-level defect, derived from the call site and the factory signature.

    Every path but the Chainlit console funnels through `build_and_run_crew`, so a branch whose
    keywords do not bind to its factory is a crew that cannot be started by any of them - the
    paths exist and each one raises `TypeError` before an agent is built.

    Neither side of this is written here: the keywords come from the ladder and the parameters
    from the factory. Fix the crew and this fails until the declaration is cleared; break
    another crew the same way and it fails until that one is declared.
    """
    call_sites = _crew_dispatch_call_sites()
    assert CREW_IDS <= set(call_sites), (
        f"no dispatch branch found for {sorted(CREW_IDS - set(call_sites))}"
    )

    failures = {
        crew_id: _binds(*call_sites[crew_id])
        for crew_id in sorted(CREW_IDS)
        if _binds(*call_sites[crew_id]) is not None
    }
    declared = {
        crew_id for crew_id in CREW_IDS if GRAPH.crews[crew_id].defect is not None
    }

    assert set(failures) == declared, (
        f"crews whose dispatch call does not bind: {sorted(failures)} "
        f"({failures}); crews declaring a defect: {sorted(declared)}"
    )


def test_the_declared_crew_defect_names_the_argument_that_does_not_bind():
    """The prose is not free text: it must name what actually breaks.

    A defect sentence that had drifted off the real cause would be worse than none, because it
    reads as an investigated finding.
    """
    import re

    call_sites = _crew_dispatch_call_sites()
    for crew_id in sorted(CREW_IDS):
        defect = GRAPH.crews[crew_id].defect
        if defect is None:
            continue
        message = _binds(*call_sites[crew_id])
        assert message is not None, (
            f"{crew_id} declares a defect and its dispatch call now binds - the crew has been "
            f"fixed and the declaration has to go"
        )
        quoted = re.findall(r"'([A-Za-z_][A-Za-z_0-9]*)'", message)
        assert quoted, f"could not read a name out of {crew_id}'s TypeError: {message}"
        assert any(name in defect for name in quoted), (
            f"{crew_id}'s defect mentions none of {quoted}, which is what the call site "
            f"actually fails on: {message}"
        )


def test_every_branch_of_the_chainlit_path_fails_as_its_defect_claims():
    """The path-level defect: this dispatch ladder can start nothing.

    Two of its five names import a crew module that does not exist; the other three pass
    `llm_mode` to a factory that has not taken it since agents began resolving their own model.
    Derived per branch, so a repaired branch fails this and the declaration has to go.
    """
    source = _module_source("chainlit_app/app.py")
    builder = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_build_crew"
    )
    body = ast.Module(body=builder.body, type_ignores=[])

    shared = next(
        node for node in ast.walk(body)
        if isinstance(node, ast.Assign)
        and any(getattr(target, "id", None) == "base" for target in node.targets)
    )
    shared_keywords = tuple(keyword.arg for keyword in shared.value.keywords)
    assert shared_keywords, "the shared argument dict in _build_crew read as empty"

    offered = _chainlit_offered()
    assert offered, "the Chainlit console's crew list read as empty"

    reasons: dict[str, str] = {}
    for statement in builder.body:
        if not isinstance(statement, ast.If):
            continue
        branch = ast.Module(body=statement.body, type_ignores=[])
        crew = statement.test.comparators[0].value
        imported = {
            alias.name: node.module
            for node in ast.walk(branch) if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        call = next(
            node for node in ast.walk(branch)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id.startswith("create_")
        )
        module_name = imported[call.func.id]
        if not Path(*module_name.split(".")).with_suffix(".py").exists():
            reasons[crew] = f"no module {module_name}"
            continue
        keywords = tuple(
            keyword.arg for keyword in call.keywords if keyword.arg is not None
        )
        if any(keyword.arg is None for keyword in call.keywords):
            keywords += shared_keywords
        message = _binds(call.func.id, module_name, keywords)
        if message is not None:
            reasons[crew] = message

    assert set(reasons) == offered, (
        f"the Chainlit console offers {sorted(offered)} and only {sorted(reasons)} fail - "
        f"its declared defect says the path can start nothing"
    )
    assert DISPATCH_PATHS[Trigger.CHAINLIT_CONSOLE].defect is not None
    assert sum("no module" in reason for reason in reasons.values()) == 2, reasons
    assert sum("llm_mode" in reason for reason in reasons.values()) == 3, reasons


def test_every_dispatch_path_is_declared_on_at_least_one_crew():
    """A path no crew names describes nothing - including the broken one.

    The Chainlit console is declared on three crews and starts none of them, which is the whole
    point of a path-level defect: were it declared on no crew at all, the defect would be a
    sentence about a path the model had already forgotten.
    """
    for trigger in DISPATCH_PATHS:
        declared = {
            crew_id for crew_id in CREW_IDS if trigger in GRAPH.crews[crew_id].triggers
        }
        assert declared, f"{trigger.value} is declared on no crew"


# ── Nothing else can start a crew ─────────────────────────────────────────────


def test_no_scheduled_job_starts_a_crew():
    """Why there is no trigger for the clock.

    The scheduler runs one job - Pamela's daily report - which computes a report and emails a
    link. If a scheduled job ever gains the ability to dispatch a crew, that is a fifth trigger
    and a crew starting itself unattended, so it must be declared rather than discovered.
    `api.main` is imported because that is what registers the handlers at run time.
    """
    import api.main  # noqa: F401
    from api.services.scheduler_service import JOB_REGISTRY

    assert JOB_REGISTRY, "no scheduled jobs registered - this proves nothing"
    for job_name, handler in sorted(JOB_REGISTRY.items()):
        source = Path(inspect.getsourcefile(handler)).read_text()
        for dispatcher in ("dispatch_crew", "build_and_run_crew", "kickoff_async"):
            assert dispatcher not in source, (
                f"the scheduled job {job_name!r} reaches {dispatcher} - a crew can now be "
                f"started by the clock, which no charter declares"
            )


def test_every_crew_name_a_dispatch_path_offers_is_a_crew_or_recorded_as_not_one():
    """A name a path accepts that no registry knows is a dispatch that reports having worked.

    Both enumerable ladders are checked: `build_and_run_crew`'s branches and the Chainlit
    console's frozenset. Three such names exist and each is in `NOT_A_CREW` with what it
    actually is.
    """
    offered = set(_crew_dispatch_call_sites()) | _chainlit_offered()
    assert offered, "no offered names found - this proves nothing"

    unknown = sorted(offered - CREW_IDS - set(NOT_A_CREW))
    assert not unknown, (
        f"a dispatch path accepts {unknown}, which no registry knows as a crew. Either it is a "
        f"crew or it belongs in NOT_A_CREW with what it really is"
    )
    stale = sorted(set(NOT_A_CREW) - offered)
    assert not stale, f"NOT_A_CREW records {stale}, which no dispatch path offers any more"
