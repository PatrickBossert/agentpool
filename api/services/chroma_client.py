# api/services/chroma_client.py
"""Single source of ChromaDB client construction.

Secure mode is a property of a project, not of a deployment: one server runs sensitive and
standard projects side by side, so the choice cannot come from an environment variable
alone. A sensitive project uses a local Chroma even when CHROMA_API_KEY is set.

This is why the slug is required. The previous signature took no arguments and read one
global key, which made the per-project guarantee inexpressible rather than merely unwritten.
"""
import contextlib
import logging
import sqlite3
from pathlib import Path

import chromadb

from api.config import get_settings
from api.services.deployment_modes import Capability, project_permits
from api.services.process_cache import register_cache

_log = logging.getLogger(__name__)

# Resolved once per slug per process, and invalidated by forget_project_mode whenever
# llm_mode is written (see api.database.update_project_config). Caching survives a mode
# switch only between the write and the next resolution - it is not stale by design, it is
# stale until someone tells it otherwise.
_MODE_CACHE: dict[str, str] = {}

# The clear-*everything* half, declared to api.services.process_cache so the suite has one
# fixture rather than nine files' worth of hand-rolled `_MODE_CACHE.clear()`. Deliberately
# `_MODE_CACHE.clear` and not `forget_project_mode`: the registry has no slug to give, and
# the targeted invalidator below answers a different question - it stays, because its two
# production callers in api/database.py must drop exactly one project.
register_cache(_MODE_CACHE.clear)

# The other half of a project's egress inputs: `projects.force_local_inference`, which removes
# HOSTED_INFERENCE from whatever the mode grants. Cached and registered on exactly the same
# terms as the mode, and for the same reason - a stale entry here decides where prompts go.
#
# **Read separately from llm_mode, deliberately.** The obvious alternative is one query
# returning both, since every caller wanting one wants the other, and it was rejected on two
# counts. `project_llm_mode`'s three-shape contract below is argued in detail and its
# unreadable-database branch falls to "sensitive"; a joined `SELECT llm_mode,
# force_local_inference` turns a `projects` table that has not yet been migrated - or one a
# test builds by hand, and twenty-one test files do - into exactly that branch, silently
# reporting every such project as sensitive on the strength of a missing column. And what the
# join would have bought is not the read at all but the invalidation, which
# `forget_project_mode` below buys instead by dropping both in one place. The cost avoided is
# one sqlite open per slug per process, on a path that is cached after the first call.
_FORCE_LOCAL_CACHE: dict[str, bool] = {}
register_cache(_FORCE_LOCAL_CACHE.clear)


def forget_project_mode(slug: str) -> None:
    """Drop a project's cached egress inputs so the next resolution re-reads the database.

    Call this from wherever llm_mode is written. Without it, a project switched
    standard -> sensitive keeps routing to whichever client its mode last resolved to,
    for as long as the process runs - a silent confidentiality breach with no
    operator-visible signal, not merely a stale read.

    It drops `force_local_inference` too, and that is the whole reason the two caches may be
    read by separate queries: there is one invalidator, so a write path cannot clear one input
    and leave the other stale. Keep it that way - a second targeted invalidator beside this one
    is the defect, not the fix.
    """
    _MODE_CACHE.pop(slug, None)
    _FORCE_LOCAL_CACHE.pop(slug, None)


def project_llm_mode(slug: str) -> str:
    """The project's llm_mode, read synchronously.

    Sync because every caller is: index_answers, the ingest service and ChromaQueryTool all
    run outside the event loop or in a thread. Note for a future reader: this opens its own
    sqlite3 connection per call and, unlike the async pool in api.database.get_connection,
    sets no busy_timeout - so it can raise "database is locked" under contention rather than
    waiting, which is exactly the read error the fail-closed branch below exists to handle.

    Three shapes, deliberately treated differently:

    - **No slug at all.** Refused, and this is the only one that raises. Every caller of this
      seam is about to decide where a *particular* project's material goes, so a blank slug is
      a caller that lost one rather than a project that does not exist yet - and the two are
      indistinguishable from the branch below, which is why the empty string is treated here
      rather than by changing what a missing database answers. Answering "standard" for it sent
      the test interview dialog's answers to Anthropic while it held the slug in its props and
      discarded them (CLAUDE.md records that incident on the LLM seam); the shared tiers make it
      sharper, because `sector_` and `org_` are the collections whose names carry no slug, so a
      caller assembling a shared-tier operation is the likeliest to think it has no project to
      name. `elaboration_press` already made exactly this repair one seam over.
    - The database file does not exist at all: the project has never been created, so it
      has no secrets to protect. This is a stable fact, safe to default to "standard" and
      cache. Kept as it is on purpose - `create_project` resolves a mode inside the window
      between `get_connection` making the file and `insert_project` writing the row, and a
      genuinely absent project is not a mistake.
    - The database file exists but the read fails (locked, corrupt, permission denied,
      whatever): this says nothing about the project's real mode, and defaulting to
      "standard" here would silently route a possibly-sensitive project's data to Chroma
      Cloud on a transient fault. Fails closed to "sensitive" instead, and the result is
      NOT cached - caching a guess born of a failed read is what would turn one bad read
      into a permanent, silent breach.
    """
    if not (slug or "").strip():
        raise ValueError(
            "project_llm_mode needs the slug of the project whose material is about to move. "
            "It was given none, and a blank slug is a caller that lost one rather than a "
            "project that does not exist yet - answering for it would route that project's "
            "documents to Chroma Cloud and its prompts to a hosted model, silently. Pass the "
            "slug through rather than defaulting it."
        )

    if slug in _MODE_CACHE:
        return _MODE_CACHE[slug]

    db_path = Path(get_settings().database_dir) / f"{slug}.db"
    if not db_path.exists():
        _MODE_CACHE[slug] = "standard"
        return "standard"

    try:
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            row = conn.execute(
                "SELECT llm_mode FROM projects WHERE slug=?", (slug,)
            ).fetchone()
    except (sqlite3.Error, OSError):
        _log.warning(
            "project_llm_mode(%s): database exists but could not be read - "
            "defaulting to sensitive and not caching the result", slug,
        )
        return "sensitive"

    mode = row[0] if row and row[0] else "standard"
    _MODE_CACHE[slug] = mode
    return mode


def project_forces_local_inference(slug: str) -> bool:
    """Whether this project is set to force local inference, read synchronously.

    Sync for the reason `project_llm_mode` is: both egress routers that consult it are, and an
    `async` resolver on this path would block a task rather than answer a question.

    **Not a router, and not a public question.** The only legitimate caller is
    `api.services.deployment_modes.project_grants`, which turns it into a set difference; a
    site reading this directly would be deciding egress from a flag rather than from a grant,
    which is the shape `deployment_modes` exists to end. Task 2 adds the source walk that says
    so.

    Four shapes, mirroring `project_llm_mode` above so the two inputs cannot answer a failure
    in opposite directions:

    - **No slug at all.** Refused, and the only one that raises - for the reason given one
      function up, which applies with equal force here: a blank slug is a caller that lost one.
    - The database file does not exist: nothing can have asked for the override, so `False` is
      the fact rather than a guess. Cached, as the mode's equivalent branch is.
    - The `projects` table has no `force_local_inference` column - a database that predates the
      migration, or one a test builds by hand. Again `False` is the fact and not a fallback: a
      column that does not exist cannot have been set to 1. Asked with `PRAGMA table_info`
      rather than by matching sqlite's "no such column" message, so the test is structural.
    - The read fails for any other reason (locked, corrupt, permission denied): this says
      nothing about the project, so it falls closed to `True` - the *narrowing* answer, which
      keeps prompts on the premises - and the result is not cached, because caching a guess
      born of a failed read is what turns one bad read into a permanent silent decision.
    """
    if not (slug or "").strip():
        raise ValueError(
            "project_forces_local_inference needs the slug of the project whose prompts are "
            "about to move. It was given none, and a blank slug is a caller that lost one "
            "rather than a project that does not exist yet. Pass the slug through rather than "
            "defaulting it."
        )

    if slug in _FORCE_LOCAL_CACHE:
        return _FORCE_LOCAL_CACHE[slug]

    db_path = Path(get_settings().database_dir) / f"{slug}.db"
    if not db_path.exists():
        _FORCE_LOCAL_CACHE[slug] = False
        return False

    try:
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
            if "force_local_inference" not in columns:
                _FORCE_LOCAL_CACHE[slug] = False
                return False
            row = conn.execute(
                "SELECT force_local_inference FROM projects WHERE slug=?", (slug,)
            ).fetchone()
    except (sqlite3.Error, OSError):
        _log.warning(
            "project_forces_local_inference(%s): database exists but could not be read - "
            "forcing local inference and not caching the result", slug,
        )
        return True

    forced = bool(row[0]) if row and row[0] is not None else False
    _FORCE_LOCAL_CACHE[slug] = forced
    return forced


def get_chroma_client(slug: str):
    """A Chroma client for this project.

    A project not granted `CLOUD_VECTOR_STORE` always gets a local HttpClient. One that is
    granted it gets CloudClient when an API key is set, else the same local client.

    Asked as a grant rather than as `mode == "sensitive"`: this is the site where forgetting a
    mode is silent, because a CloudClient built for a project that should never have had one
    raises nothing and warns nobody - it just works, off the premises. An undeclared mode is
    refused the cloud here, so the failure it causes is a project that stays local.

    Asked of the *project* rather than of its mode, because the two can differ: nothing that
    narrows a project may remove `CLOUD_VECTOR_STORE`, so today the answers agree here - and
    that is a fact about today's overrides, not a licence to ask the shorter question.
    """
    settings = get_settings()
    if not project_permits(slug, Capability.CLOUD_VECTOR_STORE):
        return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    if settings.chroma_api_key:
        return chromadb.CloudClient(
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
            api_key=settings.chroma_api_key,
        )
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
