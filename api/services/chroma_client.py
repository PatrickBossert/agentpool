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

_log = logging.getLogger(__name__)

# Resolved once per slug per process. llm_mode changes only when a human edits the project.
_MODE_CACHE: dict[str, str] = {}


def project_llm_mode(slug: str) -> str:
    """The project's llm_mode, read synchronously.

    Sync because every caller is: index_answers, the ingest service and ChromaQueryTool all
    run outside the event loop or in a thread. Defaults to "standard" when the project or
    column cannot be read - a project that does not exist has no secrets to protect, and
    failing closed here would break ingest for every standard project on a bad read.
    """
    if slug in _MODE_CACHE:
        return _MODE_CACHE[slug]
    mode = "standard"
    db_path = Path(get_settings().database_dir) / f"{slug}.db"
    with contextlib.suppress(sqlite3.Error, OSError):
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            row = conn.execute(
                "SELECT llm_mode FROM projects WHERE slug=?", (slug,)
            ).fetchone()
            if row and row[0]:
                mode = row[0]
    _MODE_CACHE[slug] = mode
    return mode


def get_chroma_client(slug: str):
    """A Chroma client for this project.

    Sensitive projects always get a local HttpClient. Standard projects get CloudClient when
    an API key is set, else the same local client.
    """
    settings = get_settings()
    if project_llm_mode(slug) == "sensitive":
        return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    if settings.chroma_api_key:
        return chromadb.CloudClient(
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
            api_key=settings.chroma_api_key,
        )
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
