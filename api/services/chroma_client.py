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
from api.services.deployment_modes import Capability, permits
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


def forget_project_mode(slug: str) -> None:
    """Drop a cached mode so the next resolution re-reads the database.

    Call this from wherever llm_mode is written. Without it, a project switched
    standard -> sensitive keeps routing to whichever client its mode last resolved to,
    for as long as the process runs - a silent confidentiality breach with no
    operator-visible signal, not merely a stale read.
    """
    _MODE_CACHE.pop(slug, None)


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


def get_chroma_client(slug: str):
    """A Chroma client for this project.

    A project whose mode is not granted `CLOUD_VECTOR_STORE` always gets a local HttpClient.
    One that is granted it gets CloudClient when an API key is set, else the same local client.

    Asked as a grant rather than as `mode == "sensitive"`: this is the site where forgetting a
    mode is silent, because a CloudClient built for a project that should never have had one
    raises nothing and warns nobody - it just works, off the premises. An undeclared mode is
    refused the cloud here, so the failure it causes is a project that stays local.
    """
    settings = get_settings()
    if not permits(project_llm_mode(slug), Capability.CLOUD_VECTOR_STORE):
        return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    if settings.chroma_api_key:
        return chromadb.CloudClient(
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
            api_key=settings.chroma_api_key,
        )
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
