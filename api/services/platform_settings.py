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
from urllib.parse import urlparse

import aiosqlite

from api.config import get_settings
from api.database import fetch_platform_public_url, store_platform_public_url

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


class PublicUrlRefused(ValueError):
    """A proposed public_url broke one of the three rules below.

    Its message names the rule, in a sentence a sysadmin can act on. Routers turn it into a
    400 and pass the sentence through unchanged - the rule lives here, and a router that
    restated it would be a second opinion free to drift from this one.
    """


# The three refusals, each written once. They are module constants rather than literals
# inside normalise_public_url so that a test can assert a refusal by the sentence the
# *service* owns, instead of by a substring the test itself supplied in the URL it sent -
# the shape CLAUDE.md records under check_write, where the refusal quoted the key it was
# refusing and the assertion therefore could not fail.
SCHEME_REFUSAL = "A public URL must begin http:// or https://"
NO_HOST_REFUSAL = "A public URL must name a host"
CREDENTIALS_REFUSAL = "A public URL must not carry a username or password"


def normalise_public_url(raw: str) -> str:
    """The stored form of a public URL, or a refusal saying which rule it broke.

    Three rules, and each exists because this value is pasted into links that arrive in a
    participant's inbox and end at a sign-in page:

    - **A scheme, and one a browser follows.** Anything else produces a link that does not
      open, so every interview invitation on the deployment is dead until somebody notices.
    - **A host.** ``urlparse`` accepts ``https:///dashboard`` and similar happily; the
      result is a link that resolves against nothing.
    - **No credentials.** ``https://user:pw@host`` is the classic phishing shape, and here
      it would be *stored* and then mailed out under the deployment's own name.

    Normalisation is the fourth job, and it is why this is a function rather than a
    validator: the stored form carries no trailing slash, so the five link builders that
    each wrote ``.rstrip('/')`` for themselves stop being five places the rule can be
    forgotten. Query and fragment are dropped - a base URL every builder appends a path to
    cannot carry either and still produce a valid link.
    """
    parsed = urlparse(raw.strip())
    if parsed.scheme not in ("http", "https"):
        raise PublicUrlRefused(f"{SCHEME_REFUSAL} - {parsed.scheme or '(none)'!r} is neither.")
    if not parsed.netloc:
        raise PublicUrlRefused(f"{NO_HOST_REFUSAL} - there is nothing for a link to resolve against.")
    if parsed.username or parsed.password:
        raise PublicUrlRefused(
            f"{CREDENTIALS_REFUSAL} - it would be stored and mailed to every participant."
        )
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


async def save_platform_public_url(conn: aiosqlite.Connection, raw: str) -> str:
    """Validate, normalise, store, and drop the cache. Returns the value now stored.

    The order matters in one direction only: forgetting *after* the write. Forget first and
    a concurrent read could repopulate the cache from the old row in the window before the
    write lands, which is the stale value the forget was there to prevent - and it would
    then persist for the life of the process.
    """
    normalised = normalise_public_url(raw)
    await store_platform_public_url(conn, normalised)
    forget_platform_settings()
    return normalised


async def read_platform_settings(conn: aiosqlite.Connection) -> dict:
    """What the settings door reports: the URL in force, and where it came from.

    ``source`` is not decoration. A blank stored value resolves to the environment, so an
    operator looking at a populated field has no way to tell a saved setting from the
    PUBLIC_URL the deployment booted with - and those behave differently the next time the
    environment changes.
    """
    stored = await fetch_platform_public_url(conn)
    return {
        "public_url": platform_public_url(),
        "source": "stored" if stored else "environment",
    }
