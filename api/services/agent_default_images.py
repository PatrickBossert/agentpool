# api/services/agent_default_images.py
"""The deployment's default portrait for an agent, promoted from the first project to upload one.

Patrick's instruction, 7 September: portraits stay per project, but *"if no default image
exists, then use the first uploaded image as the default for all future projects."* An agent
with **no portrait at all** should not need the same photograph uploaded onto every engagement
in turn.

## Four levels, and the precedence is stated once

| | Where it lives | Set by |
|---|---|---|
| 1. Project override | `projects/<slug>/assets/agents/<agent_id>.<ext>` | uploading on that project |
| 2. Promoted default | `<DATA_DIR>/agent_defaults/`, recorded in `system.db` | the first upload for an agent with no default |
| 3. Built-in asset | `ui/public/agents/<name>.jpg`, shipped in the repository | whoever added the agent |
| 4. Initials | nothing on disk | `AgentAvatar` |

First match wins. Level 1 is `agent_config_service._merge`, which was already the one place an
override beats a default. **Level 2 is inserted in exactly one place** - `agent_defaults`, which
is where level 3 was already read - so the interview page and the Setup section cannot come to
disagree about an agent's face. `interview_service` reads the *resolved* value of that same
merge, so both doors inherit level 2 without either of them being told about it.

**The promotion only ever fills level 2** - it never overwrites a built-in asset and never
overwrites itself. "First" means first, not latest: once a default exists, later uploads stay
project overrides. That is what makes the rule predictable rather than a race in which the most
recent engagement silently re-faces every other one.

The *read* order and the *write* rule are two different statements and must not be collapsed.
Reading, a promoted default beats a built-in asset, because the table above says so and because
an agent given a shipped portrait *after* one was promoted for them is a repository decision
that should not silently outrank an operator's. Writing, an agent with a built-in asset is
never promoted over at all, so today - with all eighteen agents carrying one - the two orders
cannot be told apart by any real agent. `promote_if_unclaimed` refuses on `has_no_face`, which
is the write rule; `promoted_default_url` answers unconditionally, which is the read rule.

## Nothing here is inferred from the filesystem

`agent_default_images` in `system.db` holds the agent, the stored extension, the slug it came
from, and when. Provenance matters more here than for an ordinary asset: this is the one write
in the product where **one engagement's upload changes what a different client's engagement
displays**, and "which project did this face come from" must be answerable without reading file
timestamps.

## It is served from its own door

`GET /api/agents/{agent_id}/image` (`api/routers/agent_assets.py`), unauthenticated. Never from
the project it came from: that would tie every project's rendering to the continued existence
of whichever engagement uploaded first, and would leak that slug into an unrelated client's
markup.

## Read synchronously, read-only, and cached only on success

`agent_defaults` is a plain `def` called eighteen times per bulk configuration read, so the
accessor is synchronous and holds the table in a process-local dict - the shape
`platform_settings.platform_public_url` already has, with the same three rules and for the same
reasons. It opens `system.db` with `mode=ro`, so asking the question can never materialise the
database (`caller_roles` and `_stakeholder_matches_invite` follow the same rule). A missing file
and a failing read both answer "no promoted defaults" and **do not cache**, because caching a
guess born of a failed read is what turns one bad read into a permanent wrong answer.

Falling back to "no promoted default" is the safe direction here in a way it would not be for
`llm_mode`: the worst outcome is that an agent renders their built-in portrait or their
initials for the life of a process, which is what they did before this existed.

**Every write must call `forget_agent_default_images()`**, or the process serves the old answer
until it restarts. `promote_if_unclaimed` does, after the file is on disk - never before, or a
concurrent read could repopulate the cache from a row whose bytes have not been written yet and
serve a 404 for a portrait that is about to exist.
"""
from __future__ import annotations

import contextlib
import logging
import sqlite3
from pathlib import Path

from api.config import get_settings
from api.database import claim_agent_default_image, get_system_connection
from api.services.image_intake import PORTRAIT_CONTENT_TYPES
from api.services.process_cache import register_cache

_log = logging.getLogger(__name__)

# Extension -> the content type it is served as. Inverted from `PORTRAIT_CONTENT_TYPES` rather
# than restated, so a fourth accepted type cannot be storable and unservable at the same time.
_CONTENT_TYPE_BY_EXTENSION: dict[str, str] = {
    extension: content_type
    for content_type, (extension, _format) in PORTRAIT_CONTENT_TYPES.items()
}

# `None` is "nothing read yet", distinct from `{}` - "read successfully, and no agent has a
# promoted default". The second is the ordinary state on every deployment today and must be
# cached; the first must not be confused with it or the read is repeated on every call.
_CACHED: dict[str, str] | None = None


def forget_agent_default_images() -> None:
    """Drop the cached table so the next read re-opens `system.db`."""
    global _CACHED
    _CACHED = None


register_cache(forget_agent_default_images)


def promoted_default_dir() -> Path:
    """Where the deployment keeps promoted portraits.

    Under `DATA_DIR` rather than `PROJECTS_DIR`: this asset belongs to the deployment, and a
    file living inside one project's directory is a file that disappears when that engagement
    is cleaned up - taking every other project's rendering of the agent with it.
    """
    return Path(get_settings().data_dir) / "agent_defaults"


def _read_table() -> dict[str, str]:
    """`agent_id -> extension` for every promoted default, or `{}` on any failure to read."""
    global _CACHED
    if _CACHED is not None:
        return _CACHED

    db_path = Path(get_settings().database_dir) / "system.db"
    if not db_path.exists():
        # A deployment that has not started yet. Not cached: the database will appear.
        return {}

    try:
        uri = f"file:{db_path}?mode=ro"
        with contextlib.closing(sqlite3.connect(uri, uri=True)) as conn:
            rows = conn.execute(
                "SELECT agent_id, extension FROM agent_default_images"
            ).fetchall()
    except (sqlite3.Error, OSError) as exc:
        _log.warning(
            "promoted agent defaults could not be read (%s) - answering none for this call "
            "and not caching the result", exc,
        )
        return {}

    _CACHED = {agent_id: extension for agent_id, extension in rows}
    return _CACHED


def promoted_default_url(agent_id: str) -> str | None:
    """The same-origin address of this agent's promoted default portrait, or None.

    Answers from the recorded row, not from the disk. A row with no file behind it answers 404
    at the door, which is the honest outcome; probing the filesystem here would make the
    resolution of an agent's face depend on a `stat` on every render.
    """
    if agent_id not in _read_table():
        return None
    return f"/api/agents/{agent_id}/image"


def promoted_default_file(agent_id: str) -> tuple[Path, str] | None:
    """The file to serve for this agent and the content type to serve it as, or None.

    The extension comes from the recorded row rather than from trying each accepted extension
    in turn, which is what `GET /projects/{slug}/agents/{agent_id}/image` has to do because
    nothing records a project override's format. Here the store is the record, so a portrait
    promoted as a PNG cannot come to be served as a JPEG by whichever file happens to be found
    first.
    """
    extension = _read_table().get(agent_id)
    if extension is None:
        return None
    content_type = _CONTENT_TYPE_BY_EXTENSION.get(extension)
    if content_type is None:
        # An extension no accepted content type maps to. Only a hand-edited row can produce
        # it, and serving bytes under a guessed type from an unauthenticated door is worse
        # than answering that there is nothing here.
        _log.warning(
            "agent_default_images row for %r names extension %r, which no accepted content "
            "type maps to - refusing to serve it", agent_id, extension,
        )
        return None
    return promoted_default_dir() / f"{agent_id}{extension}", content_type


async def promote_if_unclaimed(
    *, agent_id: str, slug: str, prepared: bytes, extension: str, has_no_face: bool
) -> bool:
    """Make this portrait the deployment's default for `agent_id`, if nobody has yet.

    Returns True when this call won the claim and wrote the file. Called from the per-project
    upload door **after** the portrait has been stored on the project, so a promotion that
    fails changes nothing about the upload the administrator asked for.

    `has_no_face` is the caller's answer to "does this agent already have a portrait shipped
    with the product", and it is passed in rather than read here so that the roll
    (`AGENT_IDENTITY`) is consulted in one place. An agent that already has a face is never
    promoted over: without that, a rule keyed only on "is the table empty for this agent"
    would give Avery a new face on every future engagement.

    The claim is the row and nothing else. `claim_agent_default_image` is `INSERT OR IGNORE`
    and its `rowcount` is what decides - a `SELECT` first would let two concurrent uploads both
    conclude they should promote, and the loser would overwrite the winner's file after losing
    the row.
    """
    if not has_no_face:
        return False

    async with get_system_connection() as conn:
        won = await claim_agent_default_image(
            conn, agent_id=agent_id, extension=extension, promoted_from_slug=slug
        )
    if not won:
        return False

    directory = promoted_default_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{agent_id}{extension}").write_bytes(prepared)
    # After the write, never before: forgetting first leaves a window in which a concurrent
    # read repopulates the cache from the row and the door answers 404 for a portrait whose
    # bytes are still being written.
    forget_agent_default_images()
    return True
