# api/services/interviewer_selection.py
"""Which interviewer takes a stakeholder, decided once and recorded.

`interviewer_selection` on `ProjectSettings` is `always_male`, `always_female`, or `random`.
This module turns that setting into an `agent_id` per session, together with the configuration
that interviewer resolves to on this project - and it is deliberately shaped so that the
*decision* is made once, at session creation, and never again.

**Why the choice is stamped and not looked up.** The setting is per project and the choice is
per session, so the two disagree the moment anybody edits the setting - which may happen at any
point between an invite going out and the participant clicking it. Under `random` a lookup is
worse still: it would answer a different person every time the same link is opened, so a
participant who paused halfway would come back to a stranger. The row is the only thing that
can say who actually conducted an interview. Same rule, same reason, as `client_documents.
knowledge_collection` in sp57: **an address that is re-derived is an address that can move
underneath the thing it points at.**

**Where sex comes from.** Not from here. `voice_gender` asks ElevenLabs for the resolved
voice's own `labels.gender`, because the sex is a property of the *voice* and the voice is a
per-project setting - a project that gives Avery a female voice has said something, and a table
in this repository mapping agents to sexes would contradict it while looking authoritative. It
would also be the sixth declaration of voice facts on a branch that exists to end the first
five.

**Who counts as an interviewer.** Derived, not listed: the agents `AGENT_IDENTITY` gives a
`voice_id` to. `agents/identity.py` states the rule this reads - `voice_id` is None for every
agent that does not speak, and only the interviewers are synthesised - so the roster is a
consequence of an existing declaration rather than a new one beside it.
`test_the_roster_is_the_interviewers_the_crew_builds` holds that derivation against the
independent declaration in `discovery_interviews`, so an agent given a voice for some other
purpose fails a test rather than quietly joining the interviewing roster.

**A sex that cannot be established is a refusal, not a shrug.** If a project asks for a female
interviewer and no candidate voice can be shown to be female, no session is created and the
crew reads why. The alternative is stamping a man on every session in the programme and
finding out at the first interview - and because the stamp is permanent, fixing the API key
afterwards does not fix the sessions.
"""
from __future__ import annotations

import json
import random as _random
from dataclasses import dataclass, field
from typing import Any

from agents.identity import AGENT_IDENTITY
from api.database import fetch_project, get_connection, get_db_path, is_contained_slug
from api.services.agent_config_service import resolve_agent_config
from api.services.voice_metadata import voice_gender_or_unknown

# The sex each non-random mode asks for, in the vocabulary ElevenLabs answers in.
_WANTED_GENDER = {"always_male": "male", "always_female": "female"}

DEFAULT_SELECTION = "random"


class NoInterviewerAvailable(RuntimeError):
    """No interviewer on the roster can be shown to meet the project's selection.

    Raised rather than resolved to somebody, because the choice is stamped: a session created
    with the wrong interviewer stays wrong after the cause is fixed.
    """


def interviewer_agent_ids() -> list[str]:
    """The agents that can conduct an interview, in a stable order.

    Sorted so that a deterministic tie-break is available to tests and to
    `_random.Random(seed)`, and so the order does not depend on dictionary insertion.
    """
    return sorted(
        agent_id
        for agent_id, identity in AGENT_IDENTITY.items()
        if identity.voice_id
    )


@dataclass(frozen=True)
class InterviewerSelection:
    """The decision, made once for a batch of sessions and then applied to each of them.

    `configs` holds the *resolved* configuration for every eligible interviewer, fetched
    before a single row is written, so a batch of thirty sessions makes one resolution per
    interviewer rather than thirty. `pick()` is the only thing that happens per session, and
    under `random` it is the only thing that may answer differently between two of them.
    """

    mode: str
    eligible: tuple[str, ...]
    configs: dict[str, dict[str, Any]]
    rng: _random.Random = field(default_factory=_random.Random, compare=False)

    def pick(self) -> str:
        """One interviewer for one session.

        Under `always_male` and `always_female` this is a choice among the interviewers whose
        voice carries that sex, which is normally one and may be several - the setting names a
        sex, not a person, so two female voices are two acceptable answers rather than an
        error. Under `random` it is a choice among all of them.
        """
        return self.rng.choice(list(self.eligible))

    def stamp_for(self, agent_id: str) -> dict[str, Any]:
        """The `voice_config` blob written onto the session row for this interviewer.

        The three original keys keep their names because the interview portal already reads
        them; `model_id` joins them because the session `/speak` door holds a session token
        rather than a slug, so the session is the only place it can learn which synthesis
        model this project configured. Without it a project that picks a multilingual model
        still speaks its real interviews through the English one - configured, stored, and
        reaching nothing.
        """
        config = self.configs[agent_id]
        return {
            "elevenlabs_voice_id": config["voice_id"],
            "language": config["language"],
            "country_code": config["country_code"],
            "model_id": config["model_id"],
        }


async def project_interviewer_selection(slug: str) -> str:
    """This project's `interviewer_selection`, or the default where it has recorded none.

    Read from `config_json`, which is where `ProjectSettings` is stored. A project that
    predates the setting has no key, and `random` is what it has always effectively done -
    there was one interviewer.
    """
    if not slug or not slug.strip():
        raise ValueError(
            "project_interviewer_selection requires a slug; a blank one is a caller that "
            "lost it, not a project that does not exist"
        )
    if not is_contained_slug(slug) or not get_db_path(slug).exists():
        return DEFAULT_SELECTION
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
    if not project:
        return DEFAULT_SELECTION
    try:
        config = json.loads(project.get("config_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        return DEFAULT_SELECTION
    choice = config.get("interviewer_selection")
    return choice if choice in _WANTED_GENDER or choice == "random" else DEFAULT_SELECTION


async def resolve_interviewer_selection(
    slug: str, *, rng: _random.Random | None = None
) -> InterviewerSelection:
    """Decide who may take this project's sessions, before any of them is written.

    Resolves every interviewer's configuration for this project, and - only when the project
    has asked for a sex - asks ElevenLabs what sex each resolved voice is. Under `random`, the
    shipped default, nothing here reaches the network.
    """
    mode = await project_interviewer_selection(slug)
    roster = interviewer_agent_ids()
    configs = {agent_id: await resolve_agent_config(slug, agent_id) for agent_id in roster}

    wanted = _WANTED_GENDER.get(mode)
    if wanted is None:
        eligible: tuple[str, ...] = tuple(roster)
    else:
        matching = []
        for agent_id in roster:
            if await voice_gender_or_unknown(configs[agent_id]["voice_id"]) == wanted:
                matching.append(agent_id)
        eligible = tuple(matching)

    if not eligible:
        raise NoInterviewerAvailable(
            f"interviewer_selection is '{mode}' and no interviewer's configured voice is "
            f"{wanted} according to ElevenLabs. No sessions were created: the interviewer is "
            f"stamped on the session at creation, so issuing them now would record the wrong "
            f"one permanently. Configure a {wanted} voice for one of {', '.join(roster)}, or "
            f"set interviewer_selection to 'random'."
        )

    return InterviewerSelection(
        mode=mode,
        eligible=eligible,
        configs=configs,
        rng=rng if rng is not None else _random.Random(),
    )
