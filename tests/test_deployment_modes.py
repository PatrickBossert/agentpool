# tests/test_deployment_modes.py
"""Egress is granted, never assumed - asserted at each of the four sites that decide it.

The whole file turns on one project whose `llm_mode` is a value the grants table does not
declare. Before the inversion, every one of the four sites read such a mode as "not sensitive,
therefore hosted": documents to Chroma Cloud, prompts to Anthropic, and an auditor's page saying
so was fine. After it, the mode holds nothing and every site keeps the material on the premises.

`"sovereign"` is the value used, because it is the real one - a fourth mode with hosted models
and a local vector store is designed and deferred - but nothing here depends on that. It is
simply a mode the table does not declare, which is the only property under test. It is written
straight into the `projects` row: the column is plain `TEXT`, so this is reachable by a hand
edit today and by a forgotten table row the day the enum grows, which is the accident this
change exists to survive.

**Each site is driven on its own.** A shared table lets one site's test cover another's, and
CLAUDE.md records that masking biting this project twice. So there is no test here that calls
two sites and asserts once, and each site is asserted on what it *produces* - the Chroma client
that comes back, the `LLM` object that is built, the HTTP request that actually goes out, the
`Destination` the page renders - never on a helper having returned a string.
"""
import ast
import json
import re
import sqlite3
from pathlib import Path
from typing import get_args

import httpx
import pytest

from api.config import get_settings
from api.services.deployment_modes import EGRESS_GRANTS, Capability, granted_to, permits

_REPO_ROOT = Path(__file__).parent.parent

# Not in EGRESS_GRANTS. Asserted rather than assumed, because the day somebody declares it this
# file must fail loudly rather than quietly stop testing anything.
UNDECLARED_MODE = "sovereign"


@pytest.fixture
def undeclared_and_standard(tmp_path, monkeypatch):
    """One project in an undeclared mode, one standard, in the same process.

    Two projects because a site that has simply stopped reaching the cloud at all would pass
    every single-project assertion here. The standard project is the control that says the
    off-premises branch still exists and is still reachable.

    `CHROMA_API_KEY` is set deliberately: it is exactly the condition that forces `CloudClient`,
    so a site that ignores the mode has somewhere wrong to go.
    """
    assert UNDECLARED_MODE not in EGRESS_GRANTS, (
        f"{UNDECLARED_MODE!r} is now a declared mode - this file needs a different undeclared "
        f"value, or it is asserting nothing"
    )
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("CHROMA_API_KEY", "cloud-key-is-set")
    get_settings.cache_clear()
    for slug, mode in (("undeclared-proj", UNDECLARED_MODE), ("open-proj", "standard")):
        conn = sqlite3.connect(tmp_path / f"{slug}.db")
        conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, "
                     "llm_mode TEXT, sector TEXT, config_json TEXT)")
        conn.execute("INSERT INTO projects (slug, llm_mode, sector, config_json) VALUES (?,?,?,?)",
                     (slug, mode, "test", json.dumps({})))
        conn.commit()
        conn.close()
    yield tmp_path
    get_settings.cache_clear()


def _set_config(tmp_path, slug: str, config: dict) -> None:
    """Write config_json the way PATCH /projects/{slug}/settings would."""
    conn = sqlite3.connect(tmp_path / f"{slug}.db")
    conn.execute("UPDATE projects SET config_json=? WHERE slug=?", (json.dumps(config), slug))
    conn.commit()
    conn.close()


# --- The table itself -------------------------------------------------------------------------


def test_an_undeclared_mode_is_granted_nothing():
    """The default falls towards containment. The one property the whole change rests on."""
    assert granted_to(UNDECLARED_MODE) == frozenset()
    for capability in Capability:
        assert not permits(UNDECLARED_MODE, capability)


def test_an_undeclared_mode_warns_rather_than_raising(caplog):
    """Consistent with `project_llm_mode`'s own fail-closed-and-warn directly above site 1.

    Raising would take a whole project down over one hand-edited column; denying keeps the data
    local and lets the hosted path refuse in its own words. The warning is the operator's only
    signal that a mode was not understood, so its absence is a defect and it is asserted.
    """
    with caplog.at_level("WARNING", logger="api.services.deployment_modes"):
        assert granted_to("not-a-mode-anybody-declared") == frozenset()
    assert any(
        record.levelname == "WARNING"
        and "not-a-mode-anybody-declared" in record.getMessage()
        for record in caplog.records
    ), "an undeclared mode was denied silently - nothing tells an operator the value was wrong"


def test_the_grants_table_cannot_be_written_by_an_importer():
    """The module's docstring says nothing here may acquire a default that grants something.

    A writable table reaches the same place by a different door: any importer could add a row,
    at run time, from anywhere, and grant a mode an egress the declaration does not carry. The
    values were always `frozenset`; this is the mapping itself. Asserted rather than left to the
    type annotation, which is not enforcement.
    """
    with pytest.raises(TypeError):
        EGRESS_GRANTS["invented-at-run-time"] = frozenset(Capability)


def test_the_grants_table_and_the_project_model_declare_the_same_modes():
    """Held equal by set, in both directions, against both models that declare the enum.

    A mode in the enum and missing from the table should fail here rather than at a client: it
    would be routed by the default, which is safe but is not what whoever added it intended, and
    they would find out from a project that refuses to run rather than from a test. A mode in the
    table and missing from the enum is the reverse mistake and equally worth catching - it is a
    grant nothing can ever be set to.

    The same shape `agents/identity.py` is held to against `ui/src/components/agentStatus.ts`.
    """
    from api.models import ProjectCreate, ProjectSettings

    declared = set(EGRESS_GRANTS)
    for model in (ProjectCreate, ProjectSettings):
        annotation = model.model_fields["llm_mode"].annotation
        assert get_args(annotation), f"{model.__name__}.llm_mode is no longer a Literal"
        assert set(get_args(annotation)) == declared, (
            f"{model.__name__}.llm_mode and EGRESS_GRANTS disagree: "
            f"{set(get_args(annotation)) ^ declared}"
        )


# Every place in `api/`, `agents/` and `scripts/` that is allowed to write a mode name as a
# literal, and how many times. Held equal - not as a subset - by the test below.
#
# This is an inventory, not an exemption list. Nothing here is excused from the rule; each entry
# *is* the rule, written down with its reason, and the count is part of it. Adding a mode-name
# literal anywhere - a new file, or a second one inside a function already listed - fails the
# test and has to be justified here in one line before it can pass.
_MODE_LITERALS: dict[str, tuple[int, str]] = {
    "api/models.py::ProjectCreate": (4, "the Literal, and its default"),
    "api/models.py::ProjectSettings": (4, "the Literal, and its default"),
    "api/services/deployment_modes.py::<module>": (3, "the grants table - the declaration itself"),
    "api/services/chroma_client.py::project_llm_mode": (
        4, "reads the column and fails closed to 'sensitive'; decides no egress"
    ),
    "agents/model_registry.py::<module>": (
        4, "_TIER_SETTINGS' second key, which means local/hosted rather than a mode - see M2"
    ),
    "agents/model_registry.py::get_llm_for_agent": (2, "indexes _TIER_SETTINGS, having asked permits()"),
    "api/services/llm_client.py::resolve_model": (2, "indexes _TIER_SETTINGS, having asked permits()"),
    "agents/egress.py::is_gated_by_mode": (
        2, "asks the resolver the same question in two modes - a question, not a rule"
    ),
    "api/services/data_architecture_service.py::data_architecture": (
        2, "the same two-mode question, for the page's 'gated_by_mode' badge"
    ),
    "agents/graph.py::build_graph": (1, "a default argument, documented in place"),
}


def _mode_literal_sites() -> dict[str, int]:
    """Every mode-name string literal under `api/`, `agents/` and `scripts/`, by enclosing scope.

    Keyed `path::qualname` and counted, because a location alone is too coarse: a fifth egress
    decision added inside `resolve_model`, which legitimately holds two already, would not
    create a new key. The count makes it visible.
    """
    found: dict[str, int] = {}

    def visit(node: ast.AST, path: Path, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, path, scope + [child.name])
                continue
            if isinstance(child, ast.Constant) and child.value in EGRESS_GRANTS:
                key = f"{path.relative_to(_REPO_ROOT)}::{'.'.join(scope) or '<module>'}"
                found[key] = found.get(key, 0) + 1
            visit(child, path, scope)

    for pattern in ("api/**/*.py", "agents/**/*.py", "scripts/**/*.py"):
        for path in sorted(_REPO_ROOT.glob(pattern)):
            visit(ast.parse(path.read_text(), filename=str(path)), path, [])
    return found


def test_every_mode_name_written_into_the_code_is_one_somebody_declared():
    """Egress is decided by a grant, never by a mode's name - guarded against a *fifth* site.

    **This test exists only for a site that does not exist yet.** The four that do are each
    covered by a behavioural test above, which fails on what the site builds whatever the
    condition is spelled like. So this one earns its place only if it detects the *coupling* -
    a module deciding something from a mode name instead of from the grants table - rather than
    one syntax for it. The first version did not, and review proved it: it matched only an
    `ast.Compare` against a constant, so `== "standard"` was caught while
    `in ("standard", "fallback")`, `!= _SENSITIVE` via a named constant, and `_TIER_SETTINGS[
    (tier, "sensitive")]` all walked past. Worse, the report's own power-check technique used
    the membership form precisely *because* it evaded the guard - which was evidence about the
    guard that should have closed it.

    So the rule is not about syntax at all: **every literal mode name in the source is
    inventoried.** A comparison, a tuple membership, a `match` case, a dict subscript, a module
    constant assigned for later use, a default argument - all of them are an `ast.Constant`
    holding a mode name, and all of them land here. `scripts/` is swept as well as `api/` and
    `agents/`, so a fifth site cannot hide by being somewhere the earlier glob did not look.

    Docstrings and comments are structurally invisible: a docstring is one `Constant` holding
    the whole docstring, never a bare `"sensitive"`, which is why three files may discuss the
    old shape in prose without tripping this. That was the one thing the first version got
    right, and it is kept.

    **What remains out of reach, so the next reader knows the edge rather than trusting the
    silence:**

    - A name assembled at run time - `"sensi" + "tive"`, `"".join(...)`, a value read from
      configuration or from another table. Nothing in the AST is the mode name.
    - A comparison against a mode that is **not yet declared**: `mode == "sovereign"` written
      before `sovereign` is in the table is invisible, because the inventory is keyed on the
      table's own values. Declaring the mode arms the guard retroactively, which is the right
      order, but it does mean the guard is weakest during exactly the change it protects. When
      sovereign lands, add it to the table *first*.
    - The frontend, which is a different language and is guarded separately below.
    """
    found = _mode_literal_sites()
    expected = {key: count for key, (count, _) in _MODE_LITERALS.items()}

    new = {k: v for k, v in found.items() if k not in expected}
    assert not new, (
        "a mode name is written into code that has not declared why: "
        f"{new}. Egress is decided by asking api.services.deployment_modes.permits() for a "
        "capability, never by testing a mode's name. If this literal genuinely decides no "
        "egress, add it to _MODE_LITERALS with its reason."
    )
    gone = {k: v for k, v in expected.items() if k not in found}
    assert not gone, (
        f"_MODE_LITERALS lists places that no longer hold a mode name: {gone}. Remove them - a "
        "stale inventory entry is a place a real one could hide."
    )
    assert found == expected, (
        "the number of mode-name literals changed in a place that already had some: "
        f"{ {k: (expected[k], found[k]) for k in expected if expected[k] != found[k]} }. "
        "A second literal inside a scope that legitimately holds one is exactly how a fifth "
        "egress decision would arrive unnoticed."
    )


# --- The vocabulary across the language boundary ------------------------------------------------

_FRONTEND_MODE_LISTS = {
    "ui/src/types.ts": 1,
    "ui/src/components/NewProjectModal.tsx": 3,
    "ui/src/pages/Settings.tsx": 1,
}


def _frontend_mode_lists() -> dict[str, list[set[str]]]:
    """Every list of modes the front end declares, extracted structurally.

    Structurally, and not by searching for the three known names: a search keyed on the modes
    would catch one going *missing* from a dropdown and would be blind to an extra one nobody
    declared, which is the more dangerous direction - a mode a user can select and the grants
    table has never heard of.

    Two shapes, because the front end holds two kinds of list. A union type is read off any line
    naming `llm_mode` or `llmMode`; the selectable options are read out of the `<select>` that
    follows an `LLM Mode` label, which is the anchor both pages already share.
    """
    lists: dict[str, list[set[str]]] = {}
    for relative in _FRONTEND_MODE_LISTS:
        source = (_REPO_ROOT / relative).read_text()
        found: list[set[str]] = []
        for line in source.splitlines():
            # Case-insensitive: the state hook is `llmMode` and its setter `setLlmMode`, so a
            # case-sensitive anchor silently covered one of the modal's two unions and not the
            # other - which is why the count above is asserted rather than assumed.
            if not re.search(r"llm_?mode", line, re.IGNORECASE):
                continue
            for union in re.findall(r"'[a-z_]+'(?:\s*\|\s*'[a-z_]+')+", line):
                found.append(set(re.findall(r"'([a-z_]+)'", union)))
        for block in re.findall(r"LLM Mode</label>(.*?)</select>", source, re.S):
            options = set(re.findall(r"<option value=\"([a-z_]+)\"", block))
            if options:
                found.append(options)
        lists[relative] = found
    return lists


def test_the_front_end_offers_exactly_the_modes_the_grants_table_declares():
    """A third and fourth copy of the vocabulary, one language over.

    `api/models.py`'s two `Literal`s are now held equal to the table. A TypeScript copy free to
    drift is the same defect in a different language, and there are four of them: the union in
    `types.ts`, two more in `NewProjectModal.tsx`, and the `<option>` lists in that modal and in
    `Settings.tsx` - the door that changes an *existing* project's mode, which is the one that
    matters most and which nothing previously guarded.

    Both directions are asserted, and the second is the sharp one. A mode in the table and
    missing from a dropdown merely cannot be chosen. A mode in a dropdown and missing from the
    table is selectable by a user and granted nothing by the server - which is safe, but is a
    project that silently will not run rather than a form that refuses.

    The shape `agents/identity.py` is already held to against `ui/src/components/agentStatus.ts`
    - set equality, read out of the TypeScript source, with no derivation crossing the boundary.
    """
    declared = set(EGRESS_GRANTS)
    lists = _frontend_mode_lists()

    for relative, expected_count in _FRONTEND_MODE_LISTS.items():
        assert len(lists[relative]) == expected_count, (
            f"{relative} holds {len(lists[relative])} mode lists, expected {expected_count} - "
            f"one was renamed, removed, or added, and this guard stopped covering it"
        )
        for found in lists[relative]:
            assert found == declared, (
                f"{relative} and EGRESS_GRANTS disagree about the modes: {found ^ declared}"
            )


# --- Site 1: the Chroma client ------------------------------------------------------------------


def test_an_undeclared_mode_gets_the_local_chroma_despite_a_cloud_key(
    undeclared_and_standard, monkeypatch
):
    """Asserted on which client class was constructed, because that is site 1's whole output.

    A test that checked `project_llm_mode` or a permission helper would pass while
    `get_chroma_client` ignored both. This is the failing test before the change: the mode is
    not "sensitive", `CHROMA_API_KEY` is set, and the old branch built a CloudClient.
    """
    import chromadb
    built = []
    monkeypatch.setattr(chromadb, "CloudClient", lambda **kw: built.append("cloud"))
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: built.append("local"))
    from api.services.chroma_client import get_chroma_client

    get_chroma_client("undeclared-proj")
    assert built == ["local"], (
        "a mode nothing has declared put this project's documents and vectors in Chroma Cloud"
    )


def test_the_cloud_branch_is_still_reachable_in_the_same_process(
    undeclared_and_standard, monkeypatch
):
    """Guard the guard: if nothing could reach CloudClient any more, the test above would pass
    for the wrong reason and would keep passing if the mode check were deleted entirely."""
    import chromadb
    built = []
    monkeypatch.setattr(chromadb, "CloudClient", lambda **kw: built.append("cloud"))
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: built.append("local"))
    from api.services.chroma_client import get_chroma_client

    get_chroma_client("undeclared-proj")
    get_chroma_client("open-proj")
    assert built == ["local", "cloud"]


# --- Site 2: the LLM a crew agent runs on -------------------------------------------------------


def test_an_undeclared_mode_builds_a_local_llm_for_a_crew_agent(undeclared_and_standard):
    """Asserted on the `LLM` object, not on the settings that were read.

    A local model is reached by `base_url`; a hosted one has none, so `base_url` is exactly
    "which provider this agent's prompts go to".
    """
    _set_config(undeclared_and_standard, "undeclared-proj", {
        "local_deep_model": "gemma4:deep",
        "local_deep_url": "http://localhost:11999/v1",
    })
    from agents.model_registry import get_llm_for_agent

    llm = get_llm_for_agent("synthesis_analyst", "undeclared-proj")
    assert llm.base_url == "http://localhost:11999/v1", (
        f"an undeclared mode sent a crew agent's prompts to a hosted provider: {llm.model!r}"
    )
    assert llm.model == "openai/gemma4:deep"

    hosted = get_llm_for_agent("synthesis_analyst", "open-proj")
    assert hosted.base_url is None, "the hosted branch is unreachable - the test above proves nothing"


def test_the_refusal_names_the_mode_it_actually_read(undeclared_and_standard):
    """The sentence used to say "is sensitive", which the inverted branch makes false.

    An operator reading "Project 'x' is sensitive" about a project set to something else has
    been told the wrong thing about the one setting they came to check.
    """
    _set_config(undeclared_and_standard, "undeclared-proj", {"local_deep_url": ""})
    from agents.model_registry import LocalModelUnavailable, get_llm_for_agent

    with pytest.raises(LocalModelUnavailable) as excinfo:
        get_llm_for_agent("synthesis_analyst", "undeclared-proj")
    message = str(excinfo.value)
    assert UNDECLARED_MODE in message, message
    assert "is sensitive" not in message, message


# --- Site 3: the non-crew completion ------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_undeclared_mode_sends_a_completion_to_the_local_model(
    undeclared_and_standard, monkeypatch
):
    """Asserted on the request that actually went out.

    A fake transport rather than a fake client class, for the reason CLAUDE.md gives: swapping
    the client cannot see that the Anthropic SDK POSTs `/v1/messages` while every local server
    here serves `/chat/completions`. The URL below is what a real server would receive.
    """
    from api.services import http_clients
    from api.services.llm_client import project_completion

    _set_config(undeclared_and_standard, "undeclared-proj", {
        "local_fast_model": "gemma4:fast",
        "local_fast_url": "http://localhost:11999/v1",
    })
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "local"}}]}
        )

    monkeypatch.setattr(
        http_clients, "_local_llm_client",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    reply = await project_completion(
        "undeclared-proj", "fast", [{"role": "user", "content": "who sees this?"}]
    )

    assert reply == "local"
    assert len(requests) == 1, "the completion never reached the local model"
    assert str(requests[0].url) == "http://localhost:11999/v1/chat/completions"
    assert json.loads(requests[0].content)["model"] == "gemma4:fast"


@pytest.mark.asyncio
async def test_the_hosted_completion_branch_is_still_reachable(
    undeclared_and_standard, monkeypatch
):
    """Guard the guard: the assertion above would survive site 3 losing its hosted branch."""
    from api.services.llm_client import resolve_model

    assert resolve_model("open-proj", "fast")[1] is None
    assert resolve_model("undeclared-proj", "fast")[1] is not None


# --- Site 4: the auditor's view -----------------------------------------------------------------


def test_the_privacy_view_does_not_collapse_an_undeclared_mode_into_standard():
    """The site that reports rather than routes, and the one whose failure is a false statement
    to a client rather than a leak.

    `_mode_key` used to answer "standard" for anything that was not `"sensitive"`, so this page
    would have told an auditor that a mode keeping everything on the premises was sending
    prompts to Anthropic and documents to Chroma Cloud. It now reads the same grants the routing
    reads, per reach.
    """
    from agents.egress import inference_destination, resolve_egress

    assert not inference_destination(UNDECLARED_MODE).leaves_deployment
    assert not resolve_egress("ChromaQueryTool", UNDECLARED_MODE).leaves_deployment
    assert not resolve_egress("DocumentIngestionTool", UNDECLARED_MODE).leaves_deployment

    # The ungated reaches are unmoved, because no mode gates them - that is the finding the
    # module exists to state honestly, and an undeclared mode must not appear to fix it.
    assert resolve_egress("TavilySearchTool", UNDECLARED_MODE).leaves_deployment
    assert resolve_egress("WebFetchTool", UNDECLARED_MODE).leaves_deployment


def test_the_privacy_view_reads_the_grants_rather_than_a_second_copy_of_them(monkeypatch):
    """The audit view derives from the table; it does not restate it.

    Driven by moving a grant rather than by reading the source: a mode granted the cloud vector
    store but not hosted inference is precisely the shape a single "is this the strict one"
    answer cannot express, and the deferred sovereign mode is its mirror image. If the two rows
    move together here, something is still collapsing the mode to one word.
    """
    from agents.egress import inference_destination, resolve_egress
    from api.services.deployment_modes import _EGRESS_GRANTS

    # The private dict behind the public read-only view. `EGRESS_GRANTS` is a MappingProxyType
    # precisely so that nothing in `api/` or `agents/` can write a row at run time; a test
    # inventing a hypothetical mode is the one caller that needs to, and it says so by reaching
    # for the private name rather than by the table being writable to everybody.
    monkeypatch.setitem(
        _EGRESS_GRANTS, "half-granted", frozenset({Capability.CLOUD_VECTOR_STORE})
    )
    assert resolve_egress("ChromaQueryTool", "half-granted").leaves_deployment
    assert not inference_destination("half-granted").leaves_deployment
