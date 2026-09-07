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

**One fact is derived here rather than stored.** `is_interviewer` asks
`interviewer_agent_ids()`, the one place "who can conduct an interview" is answered, so the
Setup section can offer a rehearsal to the agents that can conduct one. It is derived from
local data and costs nothing.

**The interviewer's voice sex is deliberately not answered here**, though it was for one
commit. It is `resolved_voice_sex` in `api/services/voice_metadata.py`, answered by
`GET /projects/{slug}/voices` - the request the picker already makes when it opens - because
resolving it here put a third-party round trip on the happy path of the read that *every*
agent panel makes, to serve a value read only when somebody clicks "Change voice". Failed
lookups are not cached, so an ElevenLabs outage was paid on every render of this door rather
than once per process. The rule did not move: `ask_voice_sex` is still the single source, and
still the same one `interviewer_selection`'s `always_male`/`always_female` reads, so the picker
and the crew cannot disagree about what a voice is.

**Neither fact is a table.** A map of agents to sexes is refused in writing in
`interviewer_selection.py`, and it would be wrong the first time a project used the table above
to give an interviewer a different voice - which is the entire point of the table.
"""
from __future__ import annotations

from typing import Any

from agents.identity import AGENT_IDENTITY, interviewer_agent_ids
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
    return _merge(agent_defaults(agent_id), await _fetch_overrides(slug, agent_id))


def _merge(defaults: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    """Override where present, default otherwise, per field - the rule, in one place.

    Extracted when a second entry point appeared (`resolve_agent_config_with`, below). The
    fetch differs between them; the rule must not, and a second copy of "NULL means use the
    default, an empty string does not" is precisely the drift this module exists to end.
    """
    resolved: dict[str, Any] = {}
    for field in CONFIG_FIELDS:
        override = _override(row, field)
        resolved[field] = defaults[field] if override is None else override
    return resolved


async def resolve_agent_config_with(conn: Any, *, slug: str, agent_id: str) -> dict[str, Any]:
    """`resolve_agent_config`, for a caller that already holds this project's connection.

    It exists for exactly one caller and one constraint. `get_session_with_script` serves the
    **public interview path** and deliberately opens its database with `interview_db_connection`
    rather than `get_connection`, because "a public interview request is not the place to
    discover a schema change" - `get_connection` runs the migration block. Calling
    `resolve_agent_config` from there would have run migrations on a participant's request, so
    the resolution is handed the connection that is already open instead.

    Same rule, same defaults, same blank-slug refusal: only the fetch differs. Anything that
    diverges beyond the fetch belongs in `_merge`, which both call.
    """
    if not slug or not slug.strip():
        raise ValueError(
            "resolve_agent_config_with requires a slug; a blank one is a caller that lost it, "
            "not a project that does not exist"
        )
    defaults = agent_defaults(agent_id)
    async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
        project = await cur.fetchone()
    if project is None:
        return _merge(defaults, None)
    row = await fetch_agent_config(conn, project_id=project["id"], agent_id=agent_id)
    return _merge(defaults, row)


def is_interviewer(agent_id: str) -> bool:
    """Whether this agent can conduct an interview.

    Asked of `interviewer_agent_ids()`, which is where that question is answered - its rule is
    "an identity with a `voice_id`", and a second `if identity.voice_id` written here would be
    the fifth declaration of a voice fact on a branch that exists to end the first four. The
    roster is asked on every call rather than captured at import, so improving the rule in the
    one place improves this answer too.

    **Deliberately not a new concept.** An agent that can speak is an agent that can rehearse
    an interview, and the predicate already means exactly that. If a non-interviewing agent is
    ever given a voice, the rehearsal button follows it, and the repair is a better rule in
    `agents/identity.py` rather than a second list here.
    """
    return agent_id in interviewer_agent_ids()


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
