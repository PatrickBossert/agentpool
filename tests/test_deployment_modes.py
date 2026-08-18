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
import sqlite3
from pathlib import Path
from typing import Literal, get_args

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
    from api.services import chroma_client
    chroma_client._MODE_CACHE.clear()
    yield tmp_path
    # Cleared on the way out as well as in: the cache is process-global and keyed by slug, so
    # clearing only on entry leaves these slugs resolved for the rest of the session, pointing
    # at a tmp_path that no longer exists.
    chroma_client._MODE_CACHE.clear()
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


def test_no_egress_decision_is_written_as_a_comparison_against_a_mode_name():
    """The shape that was inverted, guarded against coming back in a fifth site.

    Parsed rather than grepped: this file, `chroma_client.py` and `egress.py` all discuss
    `mode == "sensitive"` in prose, and a substring search cannot tell a comment describing the
    old shape from a line implementing it. An `ast.Compare` whose operand is one of the mode
    literals is the thing itself.

    `data_architecture_service.py:299` compares `inference_destination("standard")` with
    `inference_destination("sensitive")` and is deliberately not caught: its operands are calls,
    and it is asking whether the mode moves the destination rather than deciding egress by name.
    """
    offenders = []
    for path in sorted(_REPO_ROOT.glob("api/**/*.py")) + sorted(_REPO_ROOT.glob("agents/**/*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            for operand in operands:
                if isinstance(operand, ast.Constant) and operand.value in EGRESS_GRANTS:
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno}")
    assert not offenders, (
        "egress is decided by a grant, not by a mode's name - ask "
        "api.services.deployment_modes.permits instead: " + ", ".join(offenders)
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

    monkeypatch.setitem(
        EGRESS_GRANTS, "half-granted", frozenset({Capability.CLOUD_VECTOR_STORE})
    )
    assert resolve_egress("ChromaQueryTool", "half-granted").leaves_deployment
    assert not inference_destination("half-granted").leaves_deployment
