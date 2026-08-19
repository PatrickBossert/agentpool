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
    """
    from api.services import chroma_client

    chroma_client._MODE_CACHE["alpha"] = "sensitive"
    chroma_client._MODE_CACHE["beta"] = "standard"
    chroma_client.forget_project_mode("alpha")
    assert chroma_client._MODE_CACHE == {"beta": "standard"}


def test_registering_the_same_clearer_twice_leaves_one_entry():
    """Import is the registration trigger, and a module can be imported more than once under
    `importlib.reload` - so a second registration of the same callable must not grow the list
    without bound. A bound method of the same object compares equal to itself, which is what
    makes `_MODE_CACHE.clear` catchable and not only a plain function."""
    from api.services import process_cache

    before = len(process_cache._CLEARERS)
    probe = {}
    process_cache.register_cache(probe.clear)
    process_cache.register_cache(probe.clear)
    try:
        assert len(process_cache._CLEARERS) == before + 1
    finally:
        process_cache._CLEARERS.remove(probe.clear)


def test_register_cache_hands_back_what_it_was_given():
    """So `forget_x = register_cache(forget_x)` is available where that reads better than a
    bare statement, and so a registrant that mistypes the name fails at import."""
    from api.services.process_cache import register_cache, _CLEARERS

    probe = {}
    try:
        assert register_cache(probe.clear) == probe.clear
    finally:
        _CLEARERS.remove(probe.clear)


# ── The inventory: a new cache is isolated by being registered, not by being remembered ──


# path::name -> how this piece of module-level state is isolated between tests, or why it
# needs no isolation. Every entry is a decision somebody made; an unlisted one fails the test
# below, which is the point - a cache that forgets to register is invisible to
# forget_all_process_caches() and reproduces the defect at the top of this file exactly.
_MODULE_LEVEL_STATE = {
    "api/services/chroma_client.py::_MODE_CACHE": (
        "registered - api.services.process_cache, cleared by conftest.reset_process_caches"
    ),
    "api/services/platform_settings.py::_CACHED_URL": (
        "registered - api.services.process_cache, cleared by conftest.reset_process_caches"
    ),
    "api/config.py::get_settings": (
        "conftest.reset_settings_cache, which predates the registry and clears it on both "
        "sides already. Not registered as well: api/config.py is the lowest module in the "
        "import order and importing api.services from it inverts that for no gain"
    ),
    "agents/graph.py::_tools_by_agent": (
        "nothing, and nothing is right - it caches an ast.parse of "
        "agents/tools/registry.py's own source, which cannot change within a process. No "
        "test can make it stale because no test can make that file different"
    ),
    "api/services/process_cache.py::_CLEARERS": (
        "the registry itself. Cleared by nothing, deliberately: emptying it would "
        "unregister every cache and turn forget_all_process_caches() into a no-op"
    ),
    "api/database.py::_MIGRATED": (
        "not a cache - it is written and never read. get_connection decides whether to "
        "migrate from PRAGMA user_version on the file, so a stale slug in this set changes "
        "no behaviour. If it ever becomes a read, it becomes a cache and moves rows"
    ),
    "api/routers/ws.py::_viewers": (
        "not a cache - live asyncio queues for open WebSocket connections. Clearing it "
        "between tests would drop subscribers rather than drop a stale value"
    ),
    "api/services/scheduler_service.py::JOB_REGISTRY": (
        "not a cache - a registration table the job modules populate at import, the same "
        "shape as _CLEARERS. It holds handlers, never a resolved value"
    ),
}


def _module_level_state_sites() -> set[str]:
    """Module-level state under `api/` and `agents/` that has the shape of a process cache.

    Three detectors, because one alone misses the obvious neighbour of what it catches:

    - a module-level name containing "cache" in any casing - `_MODE_CACHE`, `_CACHED_URL`;
    - a module-level name assigned an **empty** mutable container - `{}`, `[]`, `set()` and
      the no-argument constructor forms. A cache starts empty and is filled at run time,
      which is exactly what distinguishes it from the declared tables all over `agents/`
      that are written with their contents and never grow;
    - a function decorated with anything mentioning "cache" - `functools.lru_cache`,
      `functools.cache`. These carry no assignment to see.

    **What this cannot see**, so the next reader knows the edge rather than trusting the
    silence:

    - A cache pre-seeded with contents, or built by a call this walk does not recognise -
      `_MODES = dict(DEFAULTS)`, `_seen = _load()`. Nothing about the assignment says
      "empty", and the name need not say "cache".
    - State on a class or inside a function - a class attribute, a closure, a mutable
      default argument. Only module scope is walked.
    - Anything outside `api/` and `agents/` - `scripts/`, and the frontend, which is a
      different language.
    - Caching inside a library this code calls. `chromadb`, `httpx` and LiteLLM each hold
      state of their own and none of it is registered here.

    The inventory is therefore a floor, not a proof. It catches the shape the two real
    caches have, which is the shape a third is most likely to be written in.
    """
    found: set[str] = set()

    def empty_container(value: ast.expr | None) -> bool:
        if isinstance(value, ast.Dict) and not value.keys:
            return True
        if isinstance(value, (ast.List, ast.Set)) and not value.elts:
            return True
        return (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in ("dict", "list", "set", "defaultdict", "OrderedDict")
            and not value.args
            and not value.keywords
        )

    for pattern in ("api/**/*.py", "agents/**/*.py"):
        for path in sorted(_REPO_ROOT.glob(pattern)):
            key = path.relative_to(_REPO_ROOT).as_posix()
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in tree.body:
                name = value = None
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(
                    node.targets[0], ast.Name
                ):
                    name, value = node.targets[0].id, node.value
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    name, value = node.target.id, node.value
                if name and ("cache" in name.lower() or empty_container(value)):
                    found.add(f"{key}::{name}")
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                    "cache" in ast.unparse(d).lower() for d in node.decorator_list
                ):
                    found.add(f"{key}::{node.name}")
    return found


def test_every_module_level_cache_is_registered_or_declared_not_to_need_it():
    """A cache that never registers is invisible to `forget_all_process_caches()`.

    That is not a hypothetical: it is precisely how `_MODE_CACHE` came to be the one
    consequential value in this codebase with no suite-wide isolation, worked around one
    file at a time by whoever happened to be bitten. Nobody decided that; it was simply
    never anybody's turn to notice.

    So the next one is caught here rather than in three months by run order. Adding a
    module-level cache under `api/` or `agents/` fails this test until its author writes a
    row above saying how it is isolated - `register_cache(...)` beside it, or a reason it
    does not need to be. The reason is the deliverable: the failure is not "add yourself to
    a list", it is "say which of these two this is".

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
        "it between tests; a project's llm_mode was the last thing to go unregistered, and "
        "a stale one sends a sensitive project's documents to Chroma Cloud. If it is not a "
        "cache, add it to _MODULE_LEVEL_STATE with the reason."
    )

    gone = sorted(declared - found)
    assert not gone, (
        f"_MODULE_LEVEL_STATE names state that no longer exists: {gone}. Remove the rows - "
        "a stale exemption is how the next cache inherits a decision nobody made about it."
    )
