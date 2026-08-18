# api/services/platform_settings.py
"""The platform_settings singleton: currently just public_url.

public_url is the address this deployment answers on. It used to be settable only by
editing PUBLIC_URL in .env and restarting the API; this is the storage and read path for
making it a setting a sysadmin changes in the browser instead (a later change adds the
door and moves the readers - see interview_service.interview_url for the reader this was
built to satisfy).
"""
import contextlib
import logging
import sqlite3
from pathlib import Path

from api.config import get_settings

_log = logging.getLogger(__name__)

# A singleton value, not keyed by anything - unlike chroma_client._MODE_CACHE, there is
# only ever one platform. _UNSET is its own sentinel so a resolved-but-blank stored value
# (impossible today, since a blank stored value falls back to the environment before
# caching, but kept explicit rather than relying on falsiness) is never confused with
# "nothing cached yet".
_UNSET = object()
_CACHED_URL = _UNSET


def forget_platform_settings() -> None:
    """Drop the cached public_url so the next call re-reads system.db.

    Call this on every write to platform_settings. Without it, a public_url changed
    through the settings door keeps resolving to whichever value this process last
    cached, for as long as the process runs - the same silent-staleness trap
    chroma_client.forget_project_mode exists to close on the mode cache.
    """
    global _CACHED_URL
    _CACHED_URL = _UNSET


def platform_public_url() -> str:
    """The platform's public_url, read synchronously: the stored setting if one is set,
    else the PUBLIC_URL environment variable.

    Sync because interview_service.interview_url - the function that builds the link a
    participant actually clicks - is a plain `def`, and an async accessor could not be
    called from it without restructuring every caller. Opens its own sqlite3 connection
    per call, read-only (file:...?mode=ro, uri=True): a caller must never be able to
    materialise system.db by asking a question, the rule caller_roles and
    _stakeholder_matches_invite already follow.

    Two failure shapes, mirroring project_llm_mode in chroma_client.py directly above
    this shape - and here both fall back to the same place, because neither says
    anything true about what the operator configured:

    - **The file does not exist.** A deployment that has not started yet. Falls back to
      the environment and does NOT cache: the database will appear, and caching "no
      database" here would freeze the environment value even after an operator later
      sets one.
    - **The read raises** (locked, no such table on a database predating this change,
      corrupt). Says nothing about what is actually stored. Falls back to the
      environment, logs a warning, and does NOT cache - caching a guess born of a
      failed read is what turns one bad read into a permanent wrong answer.

    Only a successful read is cached. A blank stored value (the column's own default,
    meaning nothing has been set yet) does not shadow the environment - "stored or env"
    is evaluated on every successful read, not "stored if a row exists".
    """
    global _CACHED_URL
    if _CACHED_URL is not _UNSET:
        return _CACHED_URL

    env_url = get_settings().public_url
    db_path = Path(get_settings().database_dir) / "system.db"
    if not db_path.exists():
        return env_url

    try:
        uri = f"file:{db_path}?mode=ro"
        with contextlib.closing(sqlite3.connect(uri, uri=True)) as conn:
            row = conn.execute(
                "SELECT public_url FROM platform_settings WHERE id=1"
            ).fetchone()
    except (sqlite3.Error, OSError) as exc:
        _log.warning(
            "platform_public_url(): system.db exists but could not be read (%s) - "
            "falling back to the environment and not caching the result", exc,
        )
        return env_url

    stored = row[0] if row else ""
    resolved = stored or env_url
    _CACHED_URL = resolved
    return resolved
