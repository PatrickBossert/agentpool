# tests/test_process_cache.py
"""One mechanism for the process-local caches, and an inventory so the next one joins it.

Two module-level caches are resolved once per process and invalidated by hand:
`chroma_client._MODE_CACHE` (keyed by slug, answers "is this project sensitive") and
`platform_settings._CACHED_URL` (a singleton). Only the second had suite-wide test
isolation, and the first is the one on the egress path - a stale entry there sends a
sensitive project's documents to Chroma Cloud and its prompts to hosted Anthropic, with
nothing in the logs to say so.

The first two tests below are the defect itself, demonstrated rather than described: they
share one slug, and the second one's project is sensitive. Without
`conftest.reset_process_caches` the second reads the first's answer and builds a
CloudClient. They are written in file order deliberately - run either alone and it passes,
which is the shape CLAUDE.md records as the one to distrust.

The inventory at the end of this file accounts for every piece of module-level state under
`api/` and `agents/` that has the shape of a cache - twelve sites, three of them registered
(the third is `interviews._transcript_email_log`, a rate-limit ledger that accumulates
rather than resolves, found by the detector added for the singleton shape `_CACHED_URL`
has). Every row claiming registration is *driven*: populate, clear, assert empty. An
earlier version of the inventory only checked that somebody had written the row down, and
it passed under a mutation that unregistered `_MODE_CACHE` while a sensitive project's
vectors went to Chroma Cloud.

The after-`yield` half of the fixture is asserted in `test_process_cache_teardown.py`,
which needs a module of its own to be able to see it at all.
"""
from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import chromadb

from api.config import get_settings

_REPO_ROOT = Path(__file__).parent.parent

# One slug, both tests. Sharing it is the point: the cache is keyed by slug, so two tests
# using different slugs could never collide and would prove nothing.
SLUG = "process-cache-egress"


def _project_db(directory: Path, slug: str, mode: str) -> None:
    """The minimal `projects` row `project_llm_mode` reads."""
    conn = sqlite3.connect(directory / f"{slug}.db")
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, llm_mode TEXT)")
    conn.execute("INSERT INTO projects (slug, llm_mode) VALUES (?,?)", (slug, mode))
    conn.commit()
    conn.close()


def _clients_built(monkeypatch) -> list[str]:
    """Record which Chroma client class `get_chroma_client` constructs.

    Asserted on the class built rather than on the mode returned, because the class is the
    egress: a test that checked `project_llm_mode(SLUG) == "sensitive"` would be testing the
    property one layer away from where it holds, and `get_chroma_client` could still send the
    project to the cloud.
    """
    built: list[str] = []
    monkeypatch.setattr(chromadb, "CloudClient", lambda **kw: built.append("cloud"))
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: built.append("local"))
    return built


# ── The defect, in run order ──────────────────────────────────────────────────


def test_a_standard_project_reaches_the_cloud_and_leaves_its_mode_cached(tmp_path, monkeypatch):
    """An ordinary, correct test - which happens to leave `SLUG` resolved to "standard".

    Nothing here is wrong. That is what makes it the right first half: the damage is done by
    a test that has no interest in caching at all, and the file it poisons need not know this
    one exists.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("CHROMA_API_KEY", "cloud-key-is-set")
    get_settings.cache_clear()
    _project_db(tmp_path, SLUG, "standard")

    built = _clients_built(monkeypatch)
    from api.services.chroma_client import get_chroma_client

    get_chroma_client(SLUG)
    assert built == ["cloud"], (
        "the standard half must genuinely reach CloudClient, or the sensitive half below "
        "proves nothing - it would be asserting 'local' against a branch that can no longer "
        "build anything else"
    )


def test_the_same_slug_sensitive_does_not_inherit_the_previous_test_s_answer(
    tmp_path, monkeypatch
):
    """The egress property, asserted across a test boundary.

    A different database, a different mode, the same slug. `project_llm_mode` consults
    `_MODE_CACHE` before it consults anything on disk, so without a fixture clearing it
    between tests this call answers "standard" for a project whose row says "sensitive" and
    hands its vectors to Chroma Cloud.

    This is not hypothetical staleness: `test_deployment_modes.py`, `test_secure_mode_
    routing.py` and seven other files each clear the cache by hand precisely because they hit
    it, and each covers only itself.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("CHROMA_API_KEY", "cloud-key-is-set")
    get_settings.cache_clear()
    _project_db(tmp_path, SLUG, "sensitive")

    built = _clients_built(monkeypatch)
    from api.services.chroma_client import get_chroma_client

    get_chroma_client(SLUG)
    assert built == ["local"], (
        f"a sensitive project's vectors went to Chroma Cloud: get_chroma_client({SLUG!r}) "
        f"built {built} because _MODE_CACHE still held the previous test's 'standard'"
    )


# ── The registry does what the fixture needs ──────────────────────────────────


def test_forgetting_everything_makes_the_mode_cache_re_read_the_database(tmp_path, monkeypatch):
    """The registry's effect on `_MODE_CACHE`, asserted as egress rather than as bookkeeping.

    A test that asserted `_MODE_CACHE == {}` after the call would pass while
    `get_chroma_client` went on building a CloudClient from some other stale thing - the
    "one layer away" shape CLAUDE.md records. So the whole cycle is driven through the
    client: cloud while the row says standard, still cloud after the row is changed behind
    the cache's back, local once the registry has been emptied.

    The row is rewritten with a bare sqlite3 UPDATE deliberately. Going through
    `update_project_config` would call `forget_project_mode` itself, and the test would then
    prove that function works rather than this one.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("CHROMA_API_KEY", "cloud-key-is-set")
    get_settings.cache_clear()
    _project_db(tmp_path, SLUG, "standard")

    from api.services.chroma_client import get_chroma_client
    from api.services.process_cache import forget_all_process_caches

    built = _clients_built(monkeypatch)
    get_chroma_client(SLUG)

    conn = sqlite3.connect(tmp_path / f"{SLUG}.db")
    conn.execute("UPDATE projects SET llm_mode='sensitive' WHERE slug=?", (SLUG,))
    conn.commit()
    conn.close()

    get_chroma_client(SLUG)
    assert built == ["cloud", "cloud"], (
        "the cache must still be holding 'standard' here, or the call below proves nothing "
        f"- got {built}"
    )

    forget_all_process_caches()
    get_chroma_client(SLUG)
    assert built == ["cloud", "cloud", "local"], (
        f"forget_all_process_caches() did not reach _MODE_CACHE: {built}"
    )


def test_forgetting_everything_makes_the_platform_url_re_read_system_db(tmp_path, monkeypatch):
    """The same cycle on the other registered cache, and driven the same way.

    `platform_public_url()` is the value itself rather than a client class, so there is no
    layer between the cache and the assertion to get wrong - the returned string *is* what
    every link builder pastes into a participant's email.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_URL", "https://from-the-environment.example")
    get_settings.cache_clear()
    conn = sqlite3.connect(tmp_path / "system.db")
    conn.execute("CREATE TABLE platform_settings (id INTEGER PRIMARY KEY CHECK (id = 1), "
                 "public_url TEXT NOT NULL DEFAULT '')")
    conn.execute("INSERT INTO platform_settings (id, public_url) VALUES (1, ?)",
                 ("https://first.example",))
    conn.commit()
    conn.close()

    from api.services.platform_settings import platform_public_url
    from api.services.process_cache import forget_all_process_caches

    assert platform_public_url() == "https://first.example"

    conn = sqlite3.connect(tmp_path / "system.db")
    conn.execute("UPDATE platform_settings SET public_url=? WHERE id=1",
                 ("https://second.example",))
    conn.commit()
    conn.close()

    assert platform_public_url() == "https://first.example", (
        "the cache must still be holding the first value here, or the call below is "
        "asserting against a cache that was never populated"
    )

    forget_all_process_caches()
    assert platform_public_url() == "https://second.example"


def test_the_targeted_invalidator_still_drops_one_slug_and_not_the_others():
    """`forget_project_mode(slug)` is not replaced by the registry, and must not become it.

    Its two production callers - `insert_project` and `update_project_config` in
    api/database.py - drop exactly the project whose `llm_mode` was written. A version that
    cleared everything would work, silently cost every other project on the deployment a
    re-read, and hide the difference between the two operations this branch exists to keep
    apart.

    Scoped to the two slugs this test put there rather than asserting the whole dict equals
    `{"beta": "standard"}`. The whole-dict form was here first and it failed under an
    unrelated mutation, on residue from the tests above it - a failure that said nothing
    about `forget_project_mode`. CLAUDE.md's rule, arrived at the same way.
    """
    from api.services import chroma_client

    cache = chroma_client._MODE_CACHE
    cache["alpha"] = "sensitive"
    cache["beta"] = "standard"
    chroma_client.forget_project_mode("alpha")
    assert "alpha" not in cache
    assert cache["beta"] == "standard"


def test_registering_the_same_clearer_twice_leaves_one_entry():
    """Import is the registration trigger, and a module can be imported more than once under
    `importlib.reload` - so a second registration of the same callable must not grow the list
    without bound. A bound method of the same object compares equal to itself, which is what
    makes `_MODE_CACHE.clear` catchable and not only a plain function."""
    from api.services import process_cache

    before = len(process_cache._CLEARERS)
    probe = {}
    # Registered before the `try`, so the cleanup below cannot raise ValueError over an
    # exception from register_cache itself and hide it.
    process_cache.register_cache(probe.clear)
    try:
        process_cache.register_cache(probe.clear)
        assert len(process_cache._CLEARERS) == before + 1
    finally:
        process_cache._CLEARERS.remove(probe.clear)


def test_register_cache_hands_back_what_it_was_given():
    """So `forget_x = register_cache(forget_x)` is available where that reads better than a
    bare statement, and so a registrant that mistypes the name fails at import."""
    from api.services.process_cache import register_cache, _CLEARERS

    probe = {}
    returned = register_cache(probe.clear)
    try:
        assert returned == probe.clear
    finally:
        _CLEARERS.remove(probe.clear)


# ── The inventory: a new cache is isolated by being registered, not by being remembered ──

# The three verdicts a row may carry. REGISTERED is the only one that makes a claim about a
# mechanism, so it is the only one that must be *proved* - every REGISTERED row needs a probe
# in _REGISTERED_PROBES below, and the probe drives populate -> clear -> assert-empty. The
# first version of this table had no probes, and under a mutation that unregistered
# _MODE_CACHE the inventory passed while a sensitive project's vectors went to Chroma Cloud:
# it checked that somebody had written a row, never that the row was true. A guard that
# verifies a declaration rather than a behaviour is decoration.
REGISTERED = "registered"
ISOLATED_ELSEWHERE = "isolated by something other than the registry"
NOT_A_CACHE = "no isolation needed"

_MODULE_LEVEL_STATE = {
    "api/services/chroma_client.py::_MODE_CACHE": (
        REGISTERED, "the egress cache - proved by probe below and by the two tests at the "
        "top of this file, which drive it through get_chroma_client"
    ),
    "api/services/chroma_client.py::_FORCE_LOCAL_CACHE": (
        REGISTERED, "the other half of a project's egress inputs - proved by probe below. "
        "Registered separately from _MODE_CACHE because it is a separate dict; both are "
        "dropped together by forget_project_mode, which is the production invalidator and "
        "is asserted in tests/test_local_inference_override.py"
    ),
    "api/services/platform_settings.py::_CACHED_URL": (
        REGISTERED, "the platform public_url singleton - proved by probe below"
    ),
    "api/routers/interviews.py::_transcript_email_log": (
        REGISTERED, "a per-process rate-limit ledger, not a resolved value, but the same "
        "trap: it accumulates, so one test's three sends leave a later test on the same "
        "session token answering 429"
    ),
    "api/services/voice_metadata.py::_GENDER_CACHE": (
        REGISTERED, "a voice's sex as ElevenLabs reports it, held because it does not change "
        "- proved by probe below. Stale entries are the ordinary test-order trap and one that "
        "would be hard to read: a test establishing a voice as female makes the next test's "
        "differently-labelled voice pass because of the first, and the interviewer selection "
        "is exactly what reads it"
    ),
    "api/services/voice_catalogue.py::_LIBRARY_ACCENTS": (
        REGISTERED, "the accents the ElevenLabs Voice Library holds, asked unfiltered so the "
        "voice picker can offer an accent the account does not have - irish, which is one of "
        "the four planned engagements - proved by probe below. Held because it is a fact "
        "about the provider rather than about a request, and a picker that narrows as a "
        "consultant types would otherwise make one call per keystroke. The test-order trap is "
        "the ordinary one and reads badly: a test that warmed it from one stubbed library "
        "answers for the next test's differently-stocked one, so the second passes because of "
        "the first"
    ),
    "api/config.py::get_settings": (
        ISOLATED_ELSEWHERE, "conftest.reset_settings_cache, which predates the registry and "
        "clears it on both sides. Deliberately not also registered: api/config.py is the "
        "lowest module in the import order and importing api.services from it inverts that. "
        "That is a layering preference, not a constraint - process_cache imports nothing, so "
        "the import would work. Asserted by the two-test pair below"
    ),
    "agents/graph.py::_tools_by_agent": (
        NOT_A_CACHE, "caches an ast.parse of agents/tools/registry.py's own source, which "
        "cannot change within a process. No test can make it stale because no test can make "
        "that file different"
    ),
    "api/services/process_cache.py::_CLEARERS": (
        NOT_A_CACHE, "the registry itself. Emptying it would unregister every cache and turn "
        "forget_all_process_caches() into a no-op"
    ),
    "api/database.py::_MIGRATED": (
        NOT_A_CACHE, "written and never read - get_connection decides whether to migrate "
        "from PRAGMA user_version on the file, so a stale slug here changes no behaviour. "
        "The write-only half is asserted below, because the day it becomes a read it "
        "becomes a slug-keyed cache and this row would otherwise stay green"
    ),
    "api/routers/ws.py::_viewers": (
        NOT_A_CACHE, "live asyncio queues for open WebSocket connections. Clearing it "
        "between tests would drop subscribers rather than drop a stale value"
    ),
    "api/services/scheduler_service.py::JOB_REGISTRY": (
        NOT_A_CACHE, "a registration table the job modules populate at import, the same "
        "shape as _CLEARERS. It holds handlers, never a resolved value"
    ),
    "api/services/http_clients.py::_tts_client": (
        NOT_A_CACHE, "a pooled httpx client, held to avoid a TLS handshake per utterance. "
        "See the note on _anthropic_client below"
    ),
    "api/services/http_clients.py::_local_llm_client": (
        NOT_A_CACHE, "the same, for the local model server"
    ),
    "api/services/http_clients.py::_anthropic_client": (
        NOT_A_CACHE, "the same, and the one with a resolved value inside it - the API key "
        "is read from settings once and baked in. Not registered because emptying these "
        "means an *async* close, which this registry's sync contract cannot express, and "
        "dropping the reference without closing leaks the socket. Safe today because every "
        "test substitutes the getter or monkeypatches the global, both of which pytest "
        "restores. A test that called the real getter after changing the key would pin that "
        "client for the session, and nothing would catch it"
    ),
}

# Every REGISTERED row needs one, and the test below refuses a claim without a proof.
# (fill, is_populated) - fill puts something in, is_populated reports whether it is still
# there. is_populated is asserted true *before* the clear as well as false after, so a probe
# that quietly fails to populate cannot pass by clearing nothing.
def _mode_cache_probe():
    from api.services import chroma_client
    key = "process-cache-probe"
    return (
        lambda: chroma_client._MODE_CACHE.__setitem__(key, "sensitive"),
        lambda: key in chroma_client._MODE_CACHE,
    )


def _force_local_cache_probe():
    from api.services import chroma_client
    key = "process-cache-probe"
    return (
        lambda: chroma_client._FORCE_LOCAL_CACHE.__setitem__(key, True),
        lambda: key in chroma_client._FORCE_LOCAL_CACHE,
    )


def _platform_url_probe():
    from api.services import platform_settings as ps
    def fill():
        ps._CACHED_URL = "https://probe.example"
    return fill, lambda: ps._CACHED_URL is not ps._UNSET


def _transcript_log_probe():
    from api.routers import interviews
    key = "process-cache-probe-token"
    return (
        lambda: interviews._transcript_email_log[key].append(1.0),
        lambda: key in interviews._transcript_email_log,
    )


def _voice_gender_probe():
    from api.services import voice_metadata
    key = "process-cache-probe-voice"
    return (
        lambda: voice_metadata._GENDER_CACHE.__setitem__(key, "female"),
        lambda: key in voice_metadata._GENDER_CACHE,
    )


def _library_accents_probe():
    """A singleton rather than a dict, so the probe reassigns the module attribute.

    Same shape as `_platform_url_probe`: there is no key to insert, and "warm" is simply
    "not None".
    """
    from api.services import voice_catalogue
    return (
        lambda: setattr(
            voice_catalogue,
            "_LIBRARY_ACCENTS",
            voice_catalogue.AccentProbe(["probe-accent"], False),
        ),
        lambda: voice_catalogue._LIBRARY_ACCENTS is not None,
    )


_REGISTERED_PROBES = {
    "api/services/voice_metadata.py::_GENDER_CACHE": _voice_gender_probe,
    "api/services/voice_catalogue.py::_LIBRARY_ACCENTS": _library_accents_probe,
    "api/services/chroma_client.py::_MODE_CACHE": _mode_cache_probe,
    "api/services/chroma_client.py::_FORCE_LOCAL_CACHE": _force_local_cache_probe,
    "api/services/platform_settings.py::_CACHED_URL": _platform_url_probe,
    "api/routers/interviews.py::_transcript_email_log": _transcript_log_probe,
}


def _module_level_state_sites() -> set[str]:
    """Module-level state under `api/` and `agents/` that has the shape of a process cache.

    Four detectors, because each alone misses the obvious neighbour of what it catches:

    1. a module-level name containing "cache" in any casing - `_MODE_CACHE`, `_CACHED_URL`;
    2. a module-level name assigned an **empty** mutable container - `{}`, `[]`, `set()`,
       the no-argument constructor forms, and `defaultdict(...)`, which is empty despite
       always carrying a factory argument and is the most idiomatic slug-keyed cache shape
       in Python after `{}`. Emptiness is what separates a cache from the declared tables
       all over `agents/`, which are written with their contents and never grow;
    3. a module-level name that some function reassigns through `global`. This is the shape
       of a lazily-resolved singleton, and it is the shape `platform_settings._CACHED_URL`
       has - detector 1 catches that one only because of its name, so without this a future
       `_resolved_url = None` would be invisible. It found the three pooled clients in
       `api/services/http_clients.py`, which nobody had accounted for;
    4. a function decorated with anything mentioning "cache" - `functools.lru_cache`,
       `functools.cache`. These carry no assignment to see.

    Assignments are walked recursively through `if`, `try` and `with` at module level, and
    across chained and tuple targets, rather than only over `tree.body` with a single Name
    target.

    **What this still cannot see**, so the next reader knows the edge rather than trusting
    the silence:

    - a cache **pre-seeded** with contents and not named "cache" - `_seen = dict(a=1)`,
      `_modes = _load()`, or unpacked from a call whose shape cannot be read
      (`_a, _b = _make_pair()`). Nothing about the assignment says "empty" and the name
      says nothing either. This is the largest remaining gap, and all three spellings were
      measured rather than assumed;
    - memoisation behind a **custom** decorator - `@_memoise`, `@cached_property` under an
      alias - since detector 4 matches the decorator's source text;
    - state on a class, in a closure, or in a mutable default argument. Only module scope is
      walked;
    - anything outside `api/` and `agents/` - `scripts/`, and the frontend;
    - caching inside a library this code calls. `chromadb`, `httpx` and LiteLLM each hold
      state of their own and none of it is registered here.

    A floor, not a proof. It catches the shape the registered caches have, which is the
    shape a fourth is most likely to be written in.
    """
    mutable_constructors = {"dict", "list", "set", "defaultdict", "OrderedDict", "deque"}

    def empty_container(value: ast.expr | None) -> bool:
        if isinstance(value, ast.Dict) and not value.keys:
            return True
        if isinstance(value, (ast.List, ast.Set)) and not value.elts:
            return True
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id not in mutable_constructors:
                return False
            # A defaultdict is empty however it was constructed; its argument is a factory,
            # not contents. Every other constructor here is empty only with no arguments.
            return value.func.id == "defaultdict" or not (value.args or value.keywords)
        return False

    found: set[str] = set()
    for pattern in ("api/**/*.py", "agents/**/*.py"):
        for path in sorted(_REPO_ROOT.glob(pattern)):
            key = path.relative_to(_REPO_ROOT).as_posix()
            tree = ast.parse(path.read_text(), filename=str(path))

            rebound_globally = {
                name for node in ast.walk(tree) if isinstance(node, ast.Global)
                for name in node.names
            }

            def visit(node: ast.AST) -> None:
                for child in ast.iter_child_nodes(node):
                    # A new scope: its assignments are locals, not module state.
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        continue
                    # (name, the expression bound to *that* name). Unpacking is paired up
                    # element-wise, so `_a, _b = {}, {}` is two empty containers rather
                    # than one tuple that is not an empty container - which is how it
                    # slipped past the first version of this walk.
                    bound: list[tuple[str, ast.expr | None]] = []
                    if isinstance(child, ast.Assign):
                        for target in child.targets:
                            if isinstance(target, ast.Name):
                                bound.append((target.id, child.value))
                            elif isinstance(target, (ast.Tuple, ast.List)):
                                elts = (
                                    child.value.elts
                                    if isinstance(child.value, (ast.Tuple, ast.List))
                                    and len(child.value.elts) == len(target.elts)
                                    else [None] * len(target.elts)
                                )
                                bound += [
                                    (e.id, v) for e, v in zip(target.elts, elts)
                                    if isinstance(e, ast.Name)
                                ]
                    elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                        bound = [(child.target.id, child.value)]
                    for name, value in bound:
                        if (
                            "cache" in name.lower()
                            or empty_container(value)
                            or name in rebound_globally
                        ):
                            found.add(f"{key}::{name}")
                    visit(child)

            visit(tree)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                    "cache" in ast.unparse(d).lower() for d in node.decorator_list
                ):
                    found.add(f"{key}::{node.name}")
    return found


def test_every_module_level_cache_is_registered_or_declared_not_to_need_it():
    """A cache that never registers is invisible to `forget_all_process_caches()`.

    That is not hypothetical: it is precisely how `_MODE_CACHE` came to be the one
    consequential value in this codebase with no suite-wide isolation, worked around one
    file at a time by whoever happened to be bitten. Nobody decided that; it was simply
    never anybody's turn to notice.

    So the next one is caught here rather than in three months by run order. Adding
    module-level state under `api/` or `agents/` fails this test until its author writes a
    row saying which of the three verdicts it is. The reason is the deliverable: the failure
    is not "add yourself to a list", it is "say which of these this is" - and if the answer
    is REGISTERED, the test below makes them prove it.

    Modelled on `test_deployment_modes.py`'s literal-mode-name inventory, and honest about
    its reach for the same reason - see `_module_level_state_sites` for what it cannot see.
    """
    found = _module_level_state_sites()
    declared = set(_MODULE_LEVEL_STATE)

    undeclared = sorted(found - declared)
    assert not undeclared, (
        "module-level state that looks like a process cache and is not accounted for: "
        f"{undeclared}. If it is a cache, register it with "
        "api.services.process_cache.register_cache so conftest.reset_process_caches empties "
        "it between tests, and add a probe to _REGISTERED_PROBES; a project's llm_mode was "
        "the last thing to go unregistered, and a stale one sends a sensitive project's "
        "documents to Chroma Cloud. If it is not a cache, add it with the reason."
    )

    gone = sorted(declared - found)
    assert not gone, (
        f"_MODULE_LEVEL_STATE names state that no longer exists: {gone}. Remove the rows - "
        "a stale exemption is how the next cache inherits a decision nobody made about it."
    )


def test_every_row_claiming_registration_is_actually_emptied_by_the_registry():
    """The teeth. A row saying REGISTERED is a claim about behaviour, so it is driven.

    Populate the thing, confirm it really is populated, call `forget_all_process_caches()`,
    confirm it is empty. Both halves matter: without the first assertion a probe that
    quietly failed to fill anything would pass by clearing nothing, which is the same
    vacuous-pass shape this whole file exists to close.

    Written because the inventory above, on its own, **passed** under a mutation that
    commented out `register_cache(_MODE_CACHE.clear)` - the row still existed, so the
    bookkeeping was green while a sensitive project's vectors went to Chroma Cloud. The
    inventory says a decision was recorded; this says the decision is true.
    """
    from api.services.process_cache import forget_all_process_caches

    claimed = {k for k, (verdict, _) in _MODULE_LEVEL_STATE.items() if verdict is REGISTERED}
    assert claimed == set(_REGISTERED_PROBES), (
        "every row claiming REGISTERED must carry a probe, and every probe must belong to "
        f"such a row. Rows without a probe: {sorted(claimed - set(_REGISTERED_PROBES))}; "
        f"probes without a row: {sorted(set(_REGISTERED_PROBES) - claimed)}. A claim nobody "
        "drives is the defect this test was added to close."
    )

    for key, build_probe in sorted(_REGISTERED_PROBES.items()):
        fill, is_populated = build_probe()
        fill()
        assert is_populated(), (
            f"{key}: the probe did not populate anything, so the assertion after the clear "
            "would pass whatever the registry did. Fix the probe, not the assertion."
        )
        forget_all_process_caches()
        assert not is_populated(), (
            f"{key} is declared REGISTERED and forget_all_process_caches() left it "
            "populated. Either register_cache(...) is missing beside it, or it registers "
            "something other than its own clear-everything function."
        )


def test_the_write_only_claim_for_the_migration_set_is_still_true():
    """`_MIGRATED`'s exemption rests on a property, so the property is checked.

    Its row says "written and never read", which is what makes a stale slug harmless -
    `get_connection` decides from `PRAGMA user_version` on the file itself. The day somebody
    reads it to skip a migration it becomes a slug-keyed cache spanning tests that point
    `DATABASE_DIR` at different directories, and the inventory above would stay green
    because the row already exists. This is the row's own guard.

    A read is any load of the name that is not the receiver of a mutating method call.
    Membership (`slug in _MIGRATED`), truthiness, iteration, and passing it to a function
    all land here; `.add`, `.discard` and `.clear` do not.
    """
    mutators = {"add", "discard", "clear", "remove", "update"}
    reads: list[str] = []
    for pattern in ("api/**/*.py", "agents/**/*.py", "scripts/**/*.py"):
        for path in sorted(_REPO_ROOT.glob(pattern)):
            tree = ast.parse(path.read_text(), filename=str(path))
            safe: set[int] = set()
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in mutators
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "_MIGRATED"
                ):
                    safe.add(id(node.func.value))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Name)
                    and node.id == "_MIGRATED"
                    and isinstance(node.ctx, ast.Load)
                    and id(node) not in safe
                ):
                    reads.append(f"{path.relative_to(_REPO_ROOT).as_posix()}:{node.lineno}")

    assert not reads, (
        f"_MIGRATED is read at {reads}, so it is no longer write-only. It is now a "
        "slug-keyed process cache: register it with api.services.process_cache and move its "
        "row in _MODULE_LEVEL_STATE to REGISTERED with a probe, or explain why a stale slug "
        "is still harmless."
    )


def test_forget_all_process_caches_has_no_production_caller():
    """It is a test seam, and the docstring saying so is not a mechanism.

    A request handler that called it would work, silently cost every other project on the
    deployment a re-read, and pass every test in this file. Same technique as
    `test_only_the_seam_posts_to_resend`: walk the source rather than trust the prose.
    """
    callers: list[str] = []
    for pattern in ("api/**/*.py", "agents/**/*.py", "scripts/**/*.py"):
        for path in sorted(_REPO_ROOT.glob(pattern)):
            if path.name == "process_cache.py":
                continue
            for i, line in enumerate(path.read_text().splitlines(), 1):
                if "forget_all_process_caches" in line:
                    callers.append(f"{path.relative_to(_REPO_ROOT).as_posix()}:{i}")
    assert not callers, (
        f"forget_all_process_caches is named outside its own module at {callers}. It empties "
        "every cache on the deployment; a caller that needs one dropped knows which and "
        "should use the targeted invalidator - forget_project_mode(slug), "
        "forget_platform_settings()."
    )


def test_no_other_test_file_reaches_into_a_private_cache():
    """The habit this task was meant to end, made structural.

    Thirty-two direct pokes at `chroma_client._MODE_CACHE` had grown across eight test
    files, every one of them re-implementing the isolation `conftest.reset_process_caches`
    now provides once. They are gone. Without this guard the thirty-third gets written the
    next time somebody hits the same wall, because the wall is invisible until you hit it.

    Two files are exempt, both the registry's own tests, where driving a cache directly is
    the point: this one, and `test_process_cache_teardown.py`, which leaves a slug in the
    cache on purpose so a module-scoped teardown can assert the fixture cleared it.
    Everything else has public seams - `forget_project_mode(slug)`,
    `forget_platform_settings()`, or a real project database - and the autouse fixture means
    a test usually needs none of them.

    Matched over the AST rather than the text, so a docstring may name a cache while code
    may not - `conftest.reset_process_caches` explains itself by naming both, and that is
    prose about a mechanism rather than a reach into it.
    """
    private = {"_MODE_CACHE", "_FORCE_LOCAL_CACHE", "_CACHED_URL", "_transcript_email_log"}
    exempt = {"test_process_cache.py", "test_process_cache_teardown.py"}
    offenders: list[str] = []
    for path in sorted((_REPO_ROOT / "tests").rglob("*.py")):
        if path.name in exempt:
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            named = (
                node.attr if isinstance(node, ast.Attribute)
                else node.id if isinstance(node, ast.Name)
                else node.name if isinstance(node, ast.alias)
                else None
            )
            if named in private:
                offenders.append(
                    f"{path.relative_to(_REPO_ROOT).as_posix()}:{node.lineno}"
                    if hasattr(node, "lineno") else path.name
                )
    assert not offenders, (
        f"a test reaches into a private module cache at {offenders}. Isolation between "
        "tests is conftest.reset_process_caches' job and needs nothing from the test; to "
        "drop one project mid-test use chroma_client.forget_project_mode(slug), and to "
        "control what a mode resolves to, write the projects row or stub project_llm_mode "
        "where get_chroma_client looks it up."
    )


# ── The one row isolated by something other than the registry ─────────────────

# `get_settings` is declared ISOLATED_ELSEWHERE, which is a claim about
# conftest.reset_settings_cache. It cannot be driven by a probe the way a registered cache
# can - the mechanism is a fixture, and a test cannot invoke the fixture that wraps it - so
# it is driven across a test boundary instead, the same way the egress pair at the top of
# this file is. In file order: the first populates the lru_cache, the second asserts it was
# emptied before the second test's body ran.


def test_reading_settings_populates_the_lru_cache():
    """Ordinary and correct, and it leaves `get_settings` cached - which is the setup."""
    get_settings()
    assert get_settings.cache_info().currsize == 1, (
        "get_settings did not cache, so the next test would assert an empty cache against "
        "a mechanism that was never given anything to clear"
    )


def test_the_settings_cache_is_empty_at_the_start_of_the_next_test():
    """The claim `_MODULE_LEVEL_STATE` makes about `get_settings`, asserted where it holds.

    Nothing in this test body calls `get_settings()`, so a non-zero size here means the
    previous test's entry survived - `conftest.reset_settings_cache` is the only thing that
    empties it, and it is the row's whole justification for not being registered.
    """
    assert get_settings.cache_info().currsize == 0, (
        "the previous test's Settings object survived into this one. "
        "conftest.reset_settings_cache is what clears it, and _MODULE_LEVEL_STATE cites "
        "that fixture as the reason api/config.py::get_settings need not register with "
        "api.services.process_cache."
    )
