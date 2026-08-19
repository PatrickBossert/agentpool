# tests/test_local_inference_override.py
"""A project may be told to use local models while its vector store stays where it is.

`sp-gs-am` runs against Chroma Cloud so the engagement is portable between clients. Measuring
local model performance used to mean switching it to `sensitive`, which also repoints Chroma at
the local instance and takes every document and interview embedding out of reach. The two things
moved together and only one of them was wanted.

`projects.force_local_inference` **removes** `HOSTED_INFERENCE` from whatever the project's mode
grants, and there is no table of capabilities an override adds - so the guarantee that no flag
can force a sensitive project hosted holds by construction. This project asserts such guarantees
rather than trusting them, so it is a test here and not only a sentence in a docstring.

**Each site is driven on its own**, following `tests/test_deployment_modes.py`. Three sites route
on `HOSTED_INFERENCE` - the crew LLM, the non-crew completion, and (for `CLOUD_VECTOR_STORE`) the
Chroma client - and a shared resolver is exactly what lets one site's test cover another's, which
CLAUDE.md records biting this project twice. So every site is asserted on what it *builds*: the
Chroma client class, the `LLM` object's `base_url`, and the URL a real local server would receive.
"""
import ast
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from anthropic import AsyncAnthropic

from api.config import get_settings
from api.services.deployment_modes import (
    EGRESS_GRANTS,
    Capability,
    granted_to,
    project_grants,
    project_permits,
)

# The shape `init_db` creates, written out here because these tests need to set the flag before
# any door for setting it exists (that door is Task 2's). Held in step with api/database.py by
# test_the_hand_built_projects_fixture_matches_the_table_init_db_creates below, which builds
# both and compares them - the earlier claim pointed at a test that opened a database through
# `get_connection` and so could not have seen the two disagree at all.
_PROJECTS_TABLE = (
    "CREATE TABLE projects ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " slug TEXT UNIQUE NOT NULL,"
    " llm_mode TEXT NOT NULL DEFAULT 'standard',"
    " force_local_inference INTEGER NOT NULL DEFAULT 0,"
    " sector TEXT,"
    " config_json TEXT,"
    " status TEXT NOT NULL DEFAULT 'created',"
    " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
)

# A local model for both tiers, so the sites below are refused a hosted model for the *flag* and
# not merely for want of configuration. The refusal is asserted separately, with these removed.
_LOCAL_MODELS = {
    "local_fast_model": "gemma4:fast",
    "local_fast_url": "http://localhost:11999/v1",
    "local_deep_model": "gemma4:deep",
    "local_deep_url": "http://localhost:11999/v1",
}


def _make_project(
    directory: Path, slug: str, mode: str, forced: bool, config: dict | None = None
) -> None:
    conn = sqlite3.connect(directory / f"{slug}.db")
    conn.execute(_PROJECTS_TABLE)
    conn.execute(
        "INSERT INTO projects (slug, llm_mode, force_local_inference, sector, config_json) "
        "VALUES (?,?,?,?,?)",
        (slug, mode, 1 if forced else 0, "test", json.dumps(config or {})),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def projects(tmp_path, monkeypatch):
    """Four projects covering the cell this exists for and the controls that give it meaning.

    `CHROMA_API_KEY` is set deliberately: it is the condition that forces `CloudClient`, so a
    site that wrongly narrowed the vector store has somewhere visibly wrong to go. Without it
    every project would get an `HttpClient` and the whole point - Chroma Cloud untouched - would
    be unassertable.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("CHROMA_API_KEY", "cloud-key-is-set")
    get_settings.cache_clear()
    _make_project(tmp_path, "forced-standard", "standard", True, _LOCAL_MODELS)
    _make_project(tmp_path, "plain-standard", "standard", False, _LOCAL_MODELS)
    _make_project(tmp_path, "forced-sensitive", "sensitive", True, _LOCAL_MODELS)
    _make_project(tmp_path, "plain-sensitive", "sensitive", False, _LOCAL_MODELS)
    yield tmp_path
    get_settings.cache_clear()


# --- The resolved grant ------------------------------------------------------------------------


def test_a_standard_project_forced_local_keeps_cloud_vectors(projects):
    """The whole point, in one assertion pair: local models, Chroma Cloud untouched.

    Both halves matter and they are independent. Asserting only that hosted inference is gone
    would pass for a change that simply made the project sensitive, which is the very outcome
    this exists to avoid.
    """
    grants = project_grants("forced-standard")
    assert Capability.CLOUD_VECTOR_STORE in grants
    assert Capability.HOSTED_INFERENCE not in grants


def test_an_unforced_standard_project_is_unchanged(projects):
    """The control. Without it the test above would pass for a resolver that narrowed everything."""
    assert project_grants("plain-standard") == granted_to("standard")
    assert Capability.HOSTED_INFERENCE in project_grants("plain-standard")


def test_the_flag_can_never_grant_a_sensitive_project_hosted_inference(projects):
    """Narrowing only, asserted rather than trusted.

    A sensitive project is granted nothing, and no state of the flag reaches past that. This is
    the property the whole set-difference shape exists to deliver, and it is the one that would
    fail silently if somebody ever wrote a union into `project_grants`.
    """
    for slug in ("forced-sensitive", "plain-sensitive"):
        assert project_grants(slug) == frozenset(), slug
        assert not project_permits(slug, Capability.HOSTED_INFERENCE), slug
        assert not project_permits(slug, Capability.CLOUD_VECTOR_STORE), slug


def test_no_project_ever_resolves_to_more_than_its_mode_declares(projects, tmp_path):
    """The general form, over every declared mode and both states of the flag.

    The two tests above name the two cells that matter today. This one says the *rule*: whatever
    the override, a project is a subset of what its mode grants. It is the assertion that would
    catch an override added later whose author reached for a union - which no test naming
    `sensitive` and `standard` could see.
    """
    for mode in EGRESS_GRANTS:
        for forced in (False, True):
            slug = f"subset-{mode}-{int(forced)}"
            _make_project(tmp_path, slug, mode, forced)
            assert project_grants(slug) <= granted_to(mode), (
                f"{slug} resolved to more than mode {mode!r} declares - an override added a "
                f"capability, which nothing in this path may ever do"
            )


# --- Site 1: the Chroma client -------------------------------------------------------------------


def test_a_forced_project_still_gets_the_cloud_chroma_client(projects, monkeypatch):
    """Asserted on which client class was constructed, because that is this site's whole output.

    **This was never red.** Before the change `get_chroma_client` asked
    `permits(project_llm_mode(slug), CLOUD_VECTOR_STORE)`, which answers `CloudClient` for a
    `standard` project whatever the flag says - and reverting the site to that today fails
    nothing. Site 1's move to `project_permits` is uniformity, not a live guarantee, exactly as
    `get_chroma_client`'s own docstring says.

    What the test guards is the *property*, which is worth guarding whether or not any current
    line implements it: the flag must not reach `CLOUD_VECTOR_STORE`. Make an override that
    removes it and this fails - which is the next override's mistake, not this one's. A
    resolver that narrowed both capabilities would leave an operator's documents unreachable
    with nothing said.
    """
    import chromadb
    built = []
    monkeypatch.setattr(chromadb, "CloudClient", lambda **kw: built.append("cloud"))
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: built.append("local"))
    from api.services.chroma_client import get_chroma_client

    get_chroma_client("forced-standard")
    assert built == ["cloud"], (
        "forcing local inference moved the project's vector store, which is exactly the "
        "coupling this change exists to break"
    )


def test_the_local_chroma_branch_is_still_reachable_in_the_same_process(projects, monkeypatch):
    """Guard the guard: if nothing could reach `HttpClient` any more, the test above would pass
    for the wrong reason and would keep passing with the grant check deleted entirely."""
    import chromadb
    built = []
    monkeypatch.setattr(chromadb, "CloudClient", lambda **kw: built.append("cloud"))
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: built.append("local"))
    from api.services.chroma_client import get_chroma_client

    get_chroma_client("forced-standard")
    get_chroma_client("forced-sensitive")
    assert built == ["cloud", "local"]


# --- Site 2: the LLM a crew agent runs on --------------------------------------------------------


def test_a_forced_project_builds_a_local_llm_for_a_crew_agent(projects):
    """Asserted on the `LLM` object, not on the resolver that fed it.

    A local model is reached by `base_url`; a hosted one has none, so `base_url` is precisely
    "which provider this agent's prompts go to". A test asserting `project_permits` returned
    False would pass while this site went on reading `permits(mode, ...)`.
    """
    from agents.model_registry import get_llm_for_agent

    llm = get_llm_for_agent("synthesis_analyst", "forced-standard")
    assert llm.base_url == "http://localhost:11999/v1", (
        f"a project forced to local inference sent a crew agent's prompts to a hosted "
        f"provider: {llm.model!r}"
    )
    assert llm.model == "openai/gemma4:deep"

    hosted = get_llm_for_agent("synthesis_analyst", "plain-standard")
    assert hosted.base_url is None, (
        "the hosted branch is unreachable in this process - the assertion above proves nothing"
    )


def test_a_forced_project_with_no_local_model_is_refused_rather_than_sent_hosted(
    projects, tmp_path
):
    """The loud failure the design asks for. A silent hosted fallback would benchmark Anthropic
    and report it as local, which is worse than not running at all."""
    from agents.model_registry import LocalModelUnavailable, get_llm_for_agent

    _make_project(tmp_path, "forced-bare", "standard", True, {"local_deep_url": ""})
    with pytest.raises(LocalModelUnavailable) as excinfo:
        get_llm_for_agent("synthesis_analyst", "forced-bare")
    message = str(excinfo.value)

    # The sentence's own distinguishing clauses, not the absence of the old one: `not in` is
    # satisfied by any rewording at all, including a wrong one, so it asserts nothing about
    # what an operator is actually told.
    assert "is not permitted to send prompts to a hosted model" in message, message
    assert "no local model for the 'deep' tier" in message, message
    assert "a project may also be set to force local inference" in message, (
        f"the refusal names only the mode, which for this project is 'standard' and grants "
        f"hosted inference outright - so an operator is left with no cause that fits: {message}"
    )
    assert "Its mode is 'standard'" in message, message


# --- Site 3: the non-crew completion --------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_forced_project_sends_a_non_crew_completion_to_the_local_model(
    projects, monkeypatch
):
    """The third routing site, driven on the request that actually went out.

    `resolve_model`'s own comment says it asks "the same grant the crew path asks, so the two
    cannot answer differently for one project". Left on `permits(mode, ...)` while the crew path
    moved, a forced project would run its crews on Ollama and its elaboration press and Agent
    Chat on Anthropic - both a false measurement and the two answering differently.

    A fake transport rather than a fake client class, for the reason CLAUDE.md gives: swapping
    the client cannot see that the Anthropic SDK POSTs `/v1/messages` while every local server
    here serves `/chat/completions`.

    **Both** clients get a transport, and the hosted one is not decoration. With only the local
    client faked, a regression here does not fail an assertion - it makes a real request to
    `api.anthropic.com` (401 on the suite's `"test-key"`, with the body transmitted), so a red
    suite talks to a provider and the failure says "AuthenticationError" rather than naming
    where the prompt went. One recording handler serves both, so the assertion below fails
    with the wrong URL in its message.
    """
    from api.services import http_clients
    from api.services.llm_client import project_completion

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                200, json={"choices": [{"message": {"role": "assistant", "content": "local"}}]}
            )
        return httpx.Response(200, json={
            "id": "msg_probe", "type": "message", "role": "assistant",
            "model": "claude-haiku-4-5-20251001",
            "content": [{"type": "text", "text": "hosted"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        http_clients, "_local_llm_client", httpx.AsyncClient(transport=transport),
    )
    monkeypatch.setattr(
        http_clients, "_anthropic_client",
        AsyncAnthropic(api_key="not-a-real-key", http_client=httpx.AsyncClient(transport=transport)),
    )

    reply = await project_completion(
        "forced-standard", "fast", [{"role": "user", "content": "who sees this?"}]
    )

    assert len(requests) == 1, "the completion never reached a model at all"
    assert str(requests[0].url) == "http://localhost:11999/v1/chat/completions", (
        f"a forced project's non-crew completion went to {requests[0].url}"
    )
    assert reply == "local"
    assert json.loads(requests[0].content)["model"] == "gemma4:fast"


def test_the_hosted_completion_branch_is_still_reachable(projects):
    """Guard the guard, for site 3: the assertion above would survive this site losing its
    hosted branch entirely."""
    from api.services.llm_client import resolve_model

    assert resolve_model("plain-standard", "fast")[1] is None
    assert resolve_model("forced-standard", "fast")[1] is not None


# --- The column, and the migration that adds it ---------------------------------------------------


async def _projects_columns_from_init_db(path) -> dict:
    """The `projects` table `init_db` alone builds, with no migration having run.

    `init_db` takes a bare connection and is called that way by `tests/test_database.py`, so
    this is the code's own path and not a shape invented for the test.
    """
    import aiosqlite
    from api.database import init_db

    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await init_db(conn)
        async with conn.execute("PRAGMA table_info(projects)") as cur:
            return {row["name"]: dict(row) async for row in cur}


@pytest.mark.asyncio
async def test_init_db_alone_creates_the_column_with_the_override_off(tmp_path):
    """`CREATE TABLE` must carry the column, asserted **with the migration block never run**.

    CLAUDE.md's step 2 for adding a column - "add the column to the `CREATE TABLE` statement so
    fresh DBs include it" - has no assertion anywhere if it is checked through
    `get_connection`, because `init_db` runs at index 0 of that block and the migration at
    index 1: the migration supplies the column on a fresh database too, so deleting it from
    `CREATE TABLE` leaves the whole suite green. This test's predecessor did exactly that and
    claimed in its docstring to be checking the opposite. `init_db` is therefore driven on its
    own, which is the only shape in which the two can disagree.

    They must not, and the reason is not tidiness: `CREATE TABLE` is what a database created
    *after* a future squash of the migration block would carry, and it is the shape
    `_PROJECTS_TABLE` above is written against.
    """
    columns = await _projects_columns_from_init_db(tmp_path / "init-db-only.db")
    assert "force_local_inference" in columns, (
        "init_db's CREATE TABLE has lost the column. Nothing else would notice - the migration "
        "supplies it on every database opened through get_connection - so this is the only "
        "place the two can be held to agreeing"
    )
    assert columns["force_local_inference"]["dflt_value"] == "0"
    assert columns["force_local_inference"]["notnull"] == 1


@pytest.mark.asyncio
async def test_the_hand_built_projects_fixture_matches_the_table_init_db_creates(tmp_path):
    """`_PROJECTS_TABLE` claims to be the shape `init_db` creates - held to it, not trusted.

    These tests set the flag by direct SQL because its door is Task 2's, so the fixture is a
    second declaration of a table that already has one. A second declaration free to drift is
    the defect `tests/test_deployment_modes.py` guards against across the language boundary and
    that `agents/identity.py` is held to against its TypeScript copy; the same rule applies to
    a copy one file away in the same language.

    Column *names* rather than full definitions, deliberately: a differing default or collation
    on `created_at` would fail this for no reason a reader could act on, while a missing or
    extra column is exactly the drift that would make a fixture stop resembling production.
    """
    real = await _projects_columns_from_init_db(tmp_path / "init-db-only.db")

    conn = sqlite3.connect(tmp_path / "fixture-shape.db")
    conn.execute(_PROJECTS_TABLE)
    fixture = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    conn.close()

    assert fixture == set(real), (
        f"_PROJECTS_TABLE and api/database.py's projects table disagree: {fixture ^ set(real)}"
    )


@pytest.mark.asyncio
async def test_a_fresh_database_carries_the_column_with_the_override_off(tmp_path, monkeypatch):
    """The end-to-end fresh path, which is what a new deployment actually gets.

    It cannot distinguish `CREATE TABLE` from the migration - the test above is what does that -
    but it is still worth its line: it says the two together produce the column, which is the
    fact `create_project` depends on.
    """
    import api.database as db

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    async with db.get_connection("fresh-flag-db") as conn:
        async with conn.execute("PRAGMA table_info(projects)") as cur:
            columns = {row["name"]: row async for row in cur}
    assert "force_local_inference" in columns
    assert columns["force_local_inference"]["dflt_value"] == "0"
    assert columns["force_local_inference"]["notnull"] == 1
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_database_at_the_previous_version_gains_the_force_local_inference_column(
    tmp_path, monkeypatch
):
    """Fails on _SCHEMA_VERSION 13 and passes on 14.

    A migration added without the bump silently never runs on any database already opened at the
    current version - no error, no warning, just a column that never arrives. Every read of the
    flag then falls to "not forced", which is the *wider* answer, so the miss would look like the
    feature simply not working on exactly the deployments that already exist.
    """
    import api.database as db

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    slug = "legacy-flag-db"

    async with db.get_connection(slug):
        pass
    con = sqlite3.connect(str(tmp_path / f"{slug}.db"))
    con.execute("ALTER TABLE projects DROP COLUMN force_local_inference")
    con.execute("PRAGMA user_version = 13")
    con.commit()
    con.close()
    db._MIGRATED.discard(slug)

    async with db.get_connection(slug) as conn:
        async with conn.execute("PRAGMA table_info(projects)") as cur:
            cols = {row["name"] async for row in cur}
    assert "force_local_inference" in cols
    get_settings.cache_clear()


# --- How the reader behaves when it cannot answer -------------------------------------------------


def test_a_projects_table_without_the_column_resolves_as_not_forced(tmp_path, monkeypatch):
    """The reason the flag is read by its own query rather than joined onto `llm_mode`.

    A `projects` table with no `force_local_inference` column - a database that predates the
    migration, or one of the twenty-one test files that build the table by hand - must resolve to
    "nobody asked for the override", because a column that does not exist cannot have been set.
    A joined `SELECT llm_mode, force_local_inference` would instead take `project_llm_mode`'s
    unreadable-database branch and report every such project as **sensitive**, on the strength of
    a missing column.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    conn = sqlite3.connect(tmp_path / "old-shape.db")
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, llm_mode TEXT, "
                 "sector TEXT, config_json TEXT)")
    conn.execute("INSERT INTO projects (slug, llm_mode, sector, config_json) VALUES (?,?,?,?)",
                 ("old-shape", "standard", "test", "{}"))
    conn.commit()
    conn.close()

    assert project_grants("old-shape") == granted_to("standard")
    get_settings.cache_clear()


def test_an_unreadable_database_falls_closed_to_forcing_local_inference(tmp_path, monkeypatch):
    """The failure direction, asserted where it is visible.

    A read that fails says nothing about the project, so the flag falls to its *narrowing*
    answer. It is only observable in isolation because the mode read fails closed too and grants
    nothing either way - so this drives the reader directly, which is legitimate here because
    this file is the resolver's own test.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "not-a-database.db").write_text("this is not an sqlite file")
    from api.services.chroma_client import project_forces_local_inference

    assert project_forces_local_inference("not-a-database") is True
    get_settings.cache_clear()


def test_the_reader_refuses_a_blank_slug():
    """The same refusal `project_llm_mode` makes one function up, and for the same reason: a
    blank slug is a caller that lost one, and answering for it decides egress for a project
    nobody named."""
    from api.services.chroma_client import project_forces_local_inference

    with pytest.raises(ValueError):
        project_forces_local_inference("  ")


# --- Invalidation ----------------------------------------------------------------------------------


def test_forgetting_a_project_drops_the_flag_as_well_as_the_mode(projects, tmp_path):
    """One invalidator for both egress inputs, asserted as what gets built rather than as
    bookkeeping.

    The flag and the mode are read by separate queries, which is safe only because
    `forget_project_mode` drops both. A second targeted invalidator, or this one clearing only
    the mode, would leave a project routing on a flag it no longer holds - and a test asserting
    `_FORCE_LOCAL_CACHE == {}` would pass while `get_llm_for_agent` went on building the old one.
    """
    from api.services.chroma_client import forget_project_mode
    from agents.model_registry import get_llm_for_agent

    assert get_llm_for_agent("synthesis_analyst", "plain-standard").base_url is None

    conn = sqlite3.connect(tmp_path / "plain-standard.db")
    conn.execute("UPDATE projects SET force_local_inference=1 WHERE slug='plain-standard'")
    conn.commit()
    conn.close()

    assert get_llm_for_agent("synthesis_analyst", "plain-standard").base_url is None, (
        "the flag was not cached at all - the invalidation below then proves nothing"
    )

    forget_project_mode("plain-standard")
    assert get_llm_for_agent("synthesis_analyst", "plain-standard").base_url == (
        "http://localhost:11999/v1"
    ), "forget_project_mode dropped the mode and left the flag stale"


# --- Nothing reads the flag behind the resolver's back -----------------------------------------
#
# Every test above pins one site, and every one of them would go on passing while a new site
# read the flag straight - deciding egress from a boolean rather than from a grant, and missing
# the cache on the way. The two walks below are the mechanism; `project_forces_local_inference`'s
# own docstring promises them by name.
#
# Same technique and same form as `tests/test_process_cache.py` and
# `tests/test_platform_public_url_readers.py`, including the rule those learned the hard way:
# **the exemption names what is allowed, not what is not.**

_REPO_ROOT = Path(__file__).parent.parent
_PRODUCTION = ("api/**/*.py", "agents/**/*.py", "scripts/**/*.py")

# Defines the reader. It owns both the query and the cache.
_READER = "api/services/chroma_client.py"

# Owns the column: the CREATE TABLE, the migration, and the single UPDATE that writes it.
_COLUMN_OWNER = "api/database.py"

# Holds the one legitimate caller of the reader - not as a file, but as one function inside it.
_RESOLVER_MODULE = "api/services/deployment_modes.py"
_RESOLVER = "project_grants"

_FLAG = "force_local_inference"
_READER_NAME = "project_forces_local_inference"


def _named_nodes(tree: ast.Module, name: str) -> list[ast.AST]:
    """Every node naming `name`, however it is spelled - an import, a bare call, an attribute
    on a module object, or a **string constant equal to it**.

    Matched over the AST rather than the text so a docstring or a comment may discuss the
    reader while code may not - except that a docstring saying the name *exactly*, and nothing
    else, is not a thing anybody writes, so the constant arm costs no prose.

    The constant arm is what closes `getattr(chroma_client, "project_forces_local_inference")`
    in its plain-literal form, which is the more plausible copy-paste of the two `getattr`
    spellings and which the other walk cannot see either: the reader's name contains
    `forces_`, so `"force_local_inference"` is not a substring of it. Concatenated and
    run-time-assembled forms remain invisible, and the test's docstring says so.
    """
    found = []
    for node in ast.walk(tree):
        named = (
            node.attr if isinstance(node, ast.Attribute)
            else node.id if isinstance(node, ast.Name)
            else node.name if isinstance(node, ast.alias)
            else node.value if isinstance(node, ast.Constant) and isinstance(node.value, str)
            else None
        )
        if named == name:
            found.append(node)
    return found


def test_nothing_calls_the_flag_reader_outside_the_resolver():
    """`project_forces_local_inference` is an input to `project_grants`, not a question a
    routing site may ask.

    A site calling it directly would decide egress from the flag alone - hosted or local
    without ever consulting the mode - which is precisely the shape `deployment_modes` exists
    to end, and it is the direction that fails *open*: a `sensitive` project whose flag is off
    reads as "not forced" and would be routed hosted. The resolver's set difference is what
    makes "no override can widen a mode" true by construction, and it is bypassed by any
    caller that does not go through it.

    **What the walk sees:** the name `project_forces_local_inference` used anywhere under
    `api/`, `agents/` or `scripts/` - as an import, a call, an attribute on a module, an
    aliased import, or a **plain string literal equal to it** - in any file except the module
    that defines it, and in `deployment_modes.py` anywhere outside the body of
    `project_grants`.

    The literal arm exists for `getattr(chroma_client, "project_forces_local_inference")`,
    which walked through both walks before it was added: this one saw no `Name`, `Attribute`
    or `alias`, and the SQL walk below could not see it either, because the reader's name
    contains `forces_` and so does not contain `force_local_inference` as a substring. It is
    the more plausible of the two `getattr` spellings, being a straight copy of the name.

    **What it cannot see**, which matters more than the list above. A call assembled at run
    time - `getattr(chroma_client, "project_forces_" + suffix)`, or a name held in a variable
    - is invisible to it, and adding the literal arm narrowed that gap without closing it. So
    is a second implementation: nothing here stops a new site opening its own `sqlite3`
    connection and issuing `SELECT force_local_inference` - that is the *other* walk below,
    and neither catches a query built by string concatenation. And it says nothing about
    `tests/`, which drive the reader directly on purpose. It catches the copy-paste, which is
    how a second caller would actually arrive.

    The exemption inside `deployment_modes.py` is one function rather than the whole file,
    deliberately: a second resolver added beside `project_grants` - one that read the flag
    without subtracting - is exactly the defect, and a file-level exemption would welcome it.
    """
    offenders: list[str] = []
    for pattern in _PRODUCTION:
        for path in sorted(_REPO_ROOT.glob(pattern)):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if rel == _READER:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            allowed: set[int] = set()
            if rel == _RESOLVER_MODULE:
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                            node.name == _RESOLVER:
                        allowed |= {id(n) for n in _named_nodes(node, _READER_NAME)}
            for node in _named_nodes(tree, _READER_NAME):
                if id(node) not in allowed:
                    offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, (
        f"{_READER_NAME} is named outside {_RESOLVER_MODULE}::{_RESOLVER} at {offenders}. A "
        "site deciding where material goes asks "
        "api.services.deployment_modes.project_permits(slug, capability), which resolves the "
        "project's mode and this override together. Reading the flag on its own decides egress "
        "from a boolean: a sensitive project with the flag off reads as 'not forced' and goes "
        "hosted."
    )


def _docstring_constants(tree: ast.Module) -> set[int]:
    """Node ids of every docstring in this module - module, class and function.

    Derived rather than pattern-matched, so the walk below may forbid the column name in code
    while this file, `deployment_modes.py` and `llm_client.py` go on explaining it in prose.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            ids.add(id(body[0].value))
    return ids


def test_nothing_writes_sql_naming_the_column_outside_the_two_modules_that_own_it():
    """The second way round the resolver, and the one the first walk cannot see: a site that
    never calls the reader at all and simply selects the column itself.

    That misses the cache as well as the narrowing - `project_forces_local_inference` is the
    only thing `forget_project_mode` can invalidate, so a second query would read a value
    nothing drops and a second *write* would leave the cached one pinned for the life of the
    process. `api/database.py` owns the column (`CREATE TABLE`, the migration, and the single
    `UPDATE` in `update_project_config`); `api/services/chroma_client.py` owns the read.

    **What the walk sees:** a string constant, anywhere under `api/`, `agents/` or `scripts/`,
    that contains `force_local_inference` alongside anything else - which every SQL statement
    naming it does. The bare literal on its own is *allowed*, because that is the field name
    as a dict key or a member of `_PLATFORM_TIER_SETTINGS`, and those read the row somebody
    already fetched rather than issuing a query. Naming what is allowed rather than guessing
    at what is not is the correction sp58's public_url walk needed: its first draft matched
    substrings of rendered source and let `cfg = get_settings(); cfg.public_url` through.

    **It caught a refusal sentence on the way in, and that was the right answer.** The 403
    from `_refuse_platform_tier_setting_changes` names its fields by joining
    `_PLATFORM_TIER_SETTINGS` - bare literals, allowed - so an operator still reads the column
    name; what the sentence around it may not do is embed the name in prose, where nothing
    distinguishes it from a hand-written query. Rewording cost one clause. Exempting the
    router would have cost the walk its only view of the file that reads project rows.

    **What it cannot see.** A statement assembled from parts - an f-string, a `" ".join`, a
    name held in a constant - is invisible, and so is `getattr`/`row[3]` positional access to
    a row selected with `SELECT *`. It also cannot see a *write* through a legitimately-shaped
    call: `update_project_config` is the only writer by argument, not by mechanism, and the
    thing that makes a second writer safe is the `forget_project_mode` call inside it rather
    than anything asserted here. Docstrings are excluded structurally, so prose about the
    column stays free.
    """
    offenders: list[str] = []
    for pattern in _PRODUCTION:
        for path in sorted(_REPO_ROOT.glob(pattern)):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if rel in (_READER, _COLUMN_OWNER):
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            docstrings = _docstring_constants(tree)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                if id(node) in docstrings or node.value == _FLAG:
                    continue
                if _FLAG in node.value:
                    offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, (
        f"{_FLAG} appears inside a longer string - almost certainly SQL - at {offenders}, "
        f"outside {_COLUMN_OWNER} and {_READER}. Read it through "
        "api.services.deployment_modes.project_permits(slug, capability) and write it through "
        "api.database.update_project_config, which is the only writer that drops the cached "
        "value. A second query reads a value forget_project_mode cannot invalidate; a second "
        "write leaves the cached one pinned for the life of the process."
    )
