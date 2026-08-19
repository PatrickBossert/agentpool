# api/services/process_cache.py
"""One place that knows how to empty every process-local cache.

Some values are resolved once per process and then held: a project's `llm_mode`
(`chroma_client._MODE_CACHE`) and the platform's `public_url`
(`platform_settings._CACHED_URL`). Each already owns a *targeted* invalidator for its own
production callers - `forget_project_mode(slug)` on a settings write, and
`forget_platform_settings()` on a platform write - and those stay exactly as they are.

A third registrant, `interviews._transcript_email_log`, is not a cache of a resolved value
at all - it is a rate-limit ledger that *accumulates* for the life of the process. It
belongs here for the same reason and with the same consequence: three transcript sends for
a session token in one test leave any later test using that token answering 429 for a limit
it never reached. Read "cache" throughout this module as "state resolved or accumulated once
per process", which is the property that matters; `register_cache` keeps the shorter name.

What was missing is the other operation: **forget everything**. It has one caller, the
autouse fixture in `tests/conftest.py`, and one job - stop state populated by one test from
answering a question asked by the next. That was not an abstract tidiness worry.
Task 3 hit it on `_CACHED_URL`, where `tests/test_interview_url.py` failed *by run order*;
and nine test files clear `_MODE_CACHE` by hand, each covering only itself. `_MODE_CACHE`
is the one that matters, because it answers "is this project sensitive" - a stale entry
there routes a sensitive project's documents to Chroma Cloud and its prompts to hosted
Anthropic, with nothing raised and nothing logged.

**This is a registry of invalidators, not a shared cache.** The two caches are not the same
shape and must not be made so: one is keyed by slug and opens a project database, the other
is a singleton opening `system.db`, and - the part that would actually be lost - their read
paths fail closed in deliberately *opposite* directions. `project_llm_mode` falls to
`"sensitive"` on an unreadable database, because the wrong answer sends client material to
the wrong country. `platform_public_url` falls back to the environment, because a link
builder that raised would take down every interview invitation over a transient lock. Those
are two decisions, each argued in its own docstring; a shared read path would make the
asymmetry look like an accident. The duplication worth removing is the invalidation.

**Imports nothing.** Every registrant imports this module, so anything imported here is a
cycle waiting for the right import order - and there is nothing to import: the registry is a
list of callables that each already know how to empty the one thing they own.
"""
from __future__ import annotations

from collections.abc import Callable

# Registration happens at import, so a cache that is never imported has nothing to clear and
# its absence is correct rather than a gap. Order is registration order and nothing depends
# on it: the clearers are independent by construction, since a registrant that needed another
# one emptied first would be sharing state with it and would not be two caches.
_CLEARERS: list[Callable[[], None]] = []


def register_cache(clear: Callable[[], None]) -> Callable[[], None]:
    """Declare a process-local cache and how to empty it. Returns `clear` unchanged.

    Call at module scope, next to the cache itself, passing the *clear-everything* function -
    `_MODE_CACHE.clear`, not `forget_project_mode`. The targeted invalidator takes an
    argument and answers a different question; this registry has no argument to give it.

    Registering the same callable twice is a no-op rather than a second entry, so a module
    re-imported under `importlib.reload` does not grow the list without bound. Bound methods
    of the same object compare equal, so `d.clear` registered twice is caught as well as a
    plain function.

    `clear` is returned so a registrant can write `forget_x = register_cache(forget_x)` where
    that reads better than a bare statement, and so a mis-registration is a name error at
    import rather than a cache that silently never clears.
    """
    if clear not in _CLEARERS:
        _CLEARERS.append(clear)
    return clear


def forget_all_process_caches() -> None:
    """Empty every registered cache.

    Not for production use: a request that needs one cache dropped knows which, and dropping
    the others would make an unrelated reader re-open a database for no reason. This exists so
    the suite has a single fixture instead of a per-file habit, and so the next cache added is
    isolated by being registered rather than by being remembered - which
    `tests/test_process_cache.py` checks by inventory, because a cache that forgets to
    register is invisible here and would reproduce the defect exactly.
    """
    for clear in _CLEARERS:
        clear()
