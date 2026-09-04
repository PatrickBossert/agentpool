# api/services/agent_config_service.py
"""What an agent is called, shown as, and sounds like on one project.

One function, `resolve_agent_config(slug, agent_id)`, and everything downstream of it - the
Setup tab, the session stamp, the interview portal, the rehearsal door - reads a resolved answer
rather than deciding for itself. That is the correction the wrong-voice defect asks for: the
fallback used to be `DEFAULT_VOICE_CONFIG`, a constant inside `ui/src/pages/VoiceInterview.tsx`,
which no server could read, no project could override, and no review ever looked at. A second
constant of the same name in `TestInterviewDialog.tsx` held a *different* voice, so Avery
rehearsed as George and interviewed as somebody else again. The lesson both times is the same:
**a constant that happens to be right is not the fix.** Resolving through here is.

**Override where present, default otherwise, per field.** Each of the six is resolved on its
own, so a project may choose a voice for Avery without also having to restate the name it was
already happy with. A resolver that took the row wholesale the moment one existed would make
choosing a voice silently erase a name.

**"Present" means "not NULL", never "truthy".** NULL is the column saying nothing; an empty
string is the project saying "nothing". A project that has deliberately cleared a display name
is not a project that never set one, and testing truthiness would collapse the two and quietly
reinstate the default over a decision somebody made. `_override` is the single place that rule
is expressed, so the six fields cannot drift apart on it.

**A blank slug raises; a slug with no database resolves the defaults.** The two look alike and
are opposites, and this seam answers them exactly as `project_llm_mode` does - deliberately, and
after being caught pointing the other way. A blank slug is a caller that *lost* one, and the
same mistake in the LLM seam sent a sensitive engagement's interview answers to a hosted model
because the test dialog held the slug in its props and discarded it. A slug with no database is
a project that genuinely does not exist, which has no configuration and no secrets, and
answering the defaults for it is both correct and the only thing that avoids materialising one
database file per guessed slug.

The defaults live in `agents/identity.py`, beside the permanent `agent_id` this keys on. Nothing
here is keyed on a display name, which is what makes renaming an agent - or running an
engagement where it is called something else - free.
"""
from __future__ import annotations

from typing import Any

from agents.identity import AGENT_IDENTITY
from api.database import (
    AGENT_CONFIG_COLUMNS,
    fetch_agent_config,
    get_connection,
    get_db_path,
    is_contained_slug,
)

# The keys `resolve_agent_config` answers. Taken from the table's own column list rather than
# restated, so a column added to `project_agent_config` cannot be one the resolver ignores -
# which is how a configured field that reaches nothing gets built.
CONFIG_FIELDS = AGENT_CONFIG_COLUMNS


class UnknownAgent(KeyError):
    """Raised for an `agent_id` no identity exists for.

    Not "resolve to empty": `agent_id` is a permanent contract, the roll is `AGENT_IDENTITY`,
    and an id outside it is a typo or a retired key rather than an agent with no preferences.
    Answering a shrug would let a misspelled id reach an interview as a nameless, voiceless
    interviewer, which is the failure this whole task exists to stop happening quietly.
    """


def agent_defaults(agent_id: str) -> dict[str, Any]:
    """The unconfigured answer for one agent - what runs today, and what an override overrides."""
    identity = AGENT_IDENTITY.get(agent_id)
    if identity is None:
        raise UnknownAgent(agent_id)
    return {
        "display_name": identity.display_name,
        "image_url": identity.image,
        "voice_id": identity.voice_id,
        "language": identity.language,
        "country_code": identity.country_code,
        "model_id": identity.model_id,
    }


def _override(row: dict[str, Any] | None, field: str) -> Any | None:
    """The project's value for one field, or None if it has not set one.

    `row.get(field)` would be the truthiness test the module docstring rules out, and it would
    read `''` as absent. `row[field]` is deliberate: `fetch_agent_config` selects every column
    by name, so a missing key is a disagreement between this module and the table rather than a
    state to tolerate, and a KeyError is the right way to hear about it.
    """
    if row is None:
        return None
    return row[field]


async def resolve_agent_config(slug: str, agent_id: str) -> dict[str, Any]:
    """Resolve one agent's name, image, voice, and synthesis model for one project.

    Returns `display_name`, `image_url`, `voice_id`, `language`, `country_code`, and `model_id`,
    each the project's override where it has recorded one and the default from
    `agents/identity.py` otherwise.

    Raises `ValueError` on a blank or whitespace-only slug, and `UnknownAgent` on an `agent_id`
    outside the roll. See the module docstring for why a blank slug is refused while an
    unrecognised one is answered.
    """
    defaults = agent_defaults(agent_id)
    row = await _fetch_overrides(slug, agent_id)
    resolved: dict[str, Any] = {}
    for field in CONFIG_FIELDS:
        override = _override(row, field)
        resolved[field] = defaults[field] if override is None else override
    return resolved


async def _fetch_overrides(slug: str, agent_id: str) -> dict[str, Any] | None:
    """The stored row for this agent, or None - including when there is no project at all.

    `is_contained_slug` is asked before the path is used, not because a caller is expected to
    pass a traversal but because `get_connection` runs the migration block against whatever
    file it is handed: a slug that escapes DATABASE_DIR would have this module writing schema
    into somebody else's database. The public interview path is a declared caller, so the slug
    is not always one a router split out of a path segment.
    """
    if not slug or not slug.strip():
        raise ValueError(
            "resolve_agent_config requires a slug; a blank one is a caller that lost it, "
            "not a project that does not exist"
        )
    if not is_contained_slug(slug):
        return None
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project = await cur.fetchone()
        if project is None:
            return None
        return await fetch_agent_config(conn, project_id=project["id"], agent_id=agent_id)
