# api/services/agent_config_service.py
"""What an agent is called, shown as, and sounds like on one project.

One function, `resolve_agent_config(slug, agent_id)`, and everything downstream of it - the
Setup tab, the session stamp, the interview portal - reads a resolved answer rather than
deciding for itself. That is the correction the wrong-voice defect asks for: the fallback used
to be `DEFAULT_VOICE_CONFIG`, a constant inside `ui/src/pages/VoiceInterview.tsx`, which no
server could read, no project could override, and no review ever looked at.

**Override where present, default otherwise, per field.** Each of the five is resolved on its
own, so a project may choose a voice for Avery without also having to restate the name it was
already happy with. A resolver that took the row wholesale the moment one existed would make
choosing a voice silently erase a name.

**"Present" means "not NULL", never "truthy".** NULL is the column saying nothing; an empty
string is the project saying "nothing". A project that has deliberately cleared a display name
is not a project that never set one, and testing truthiness would collapse the two and quietly
reinstate the default over a decision somebody made. `_override` is the single place that rule
is expressed, so the five fields cannot drift apart on it.

The defaults live in `agents/identity.py`, beside the permanent `agent_id` this keys on. Nothing
here is keyed on a display name, which is what makes renaming an agent - or running an
engagement where it is called something else - free.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.identity import AGENT_IDENTITY
from api.database import fetch_agent_config, get_connection, get_db_path

# The keys `resolve_agent_config` answers, in the order the design names them. Stated once so
# the resolver, the defaults and the tests cannot disagree about what a resolved config holds.
CONFIG_FIELDS = ("display_name", "image_url", "voice_id", "language", "country_code")


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
    }


def _override(row: dict[str, Any] | None, field: str) -> Any | None:
    """The project's value for one field, or None if it has not set one.

    `row.get(field)` would be wrong twice over: it cannot tell a stored `''` from an absent
    column, and it is the truthiness test the module docstring rules out.
    """
    if row is None or field not in row:
        return None
    return row[field]


async def resolve_agent_config(slug: str, agent_id: str) -> dict[str, Any]:
    """Resolve one agent's name, image, and voice for one project.

    Returns `display_name`, `image_url`, `voice_id`, `language`, and `country_code`, each the
    project's override where it has recorded one and the default from `agents/identity.py`
    otherwise.

    A slug with no database on disk resolves every default and **does not create one**. That is
    the rule `caller_roles` and `_stakeholder_matches_invite` already follow, and it matters
    here for the same reason: this is reached from a public interview path, so a slug that can
    be guessed must not be a slug that can be materialised one file per guess.
    """
    defaults = agent_defaults(agent_id)
    row = await _fetch_overrides(slug, agent_id)
    resolved: dict[str, Any] = {}
    for field in CONFIG_FIELDS:
        override = _override(row, field)
        resolved[field] = defaults[field] if override is None else override
    return resolved


async def _fetch_overrides(slug: str, agent_id: str) -> dict[str, Any] | None:
    """The stored row for this agent, or None - including when there is no project at all."""
    if not slug or not slug.strip():
        return None
    if not Path(get_db_path(slug)).exists():
        return None
    async with get_connection(slug) as conn:
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project = await cur.fetchone()
        if project is None:
            return None
        return await fetch_agent_config(conn, project_id=project["id"], agent_id=agent_id)
