# api/routers/agent_config.py
"""What this project calls an agent, shows for it, and gives it to speak with.

`project_agent_config` has existed since Task 1 and `resolve_agent_config` has read it since,
but nothing could **write** it except a test - so every project on the deployment ran on the
defaults and the wrong-voice defect's first broken link ("the choice is not persisted anywhere
a server can see") was only half repaired. This is the door the Setup section saves through.

## Two verbs, and the second is a PUT on purpose

`GET` answers three things at once - the defaults, the project's overrides, and the resolution
of one over the other - because a Setup tab has to show a value **and** say whether it is a
choice or an inheritance. Serving only the resolved answer would make those indistinguishable,
which is the thing sp58's platform-URL panel exists to avoid saying wrongly.

`PUT` replaces the row. `upsert_agent_config` writes all six columns on every call, so a field
absent from the body is **cleared** rather than left alone - and a `PATCH` on that writer would
be a lie about its semantics. The section posts its whole state, which is the shape this suits.

## Authority: administration, per project

Naming an agent and choosing its voice is configuring the engagement, so this is the
administration axis - `require_project_administration` over the `check_project_access` floor,
exactly like `PATCH /{slug}/settings` and the milestone schedule beside it.

**Not platform tier, and not `_PLATFORM_TIER_SETTINGS`.** Nothing here decides where an
engagement's material is sent. `model_id` is the field that looks as though it might, and it is
not: it is the **ElevenLabs synthesis model** (`agents.identity.DEFAULT_TTS_MODEL_ID`, threaded
through `synthesise(text, voice_id, model_id)`), which exists so a French voice is not spoken
through an English model. The six LLM model ids that *do* decide where prompts go live on
`ProjectSettings` and are refused to a `project_admin`. Two different things in this product are
called a model id and only one of them is a security control; this is the other one.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import check_project_access, require_any_auth
from api.database import (
    AGENT_CONFIG_COLUMNS,
    fetch_agent_config,
    fetch_project,
    get_connection,
    upsert_agent_config,
)
from api.services.agent_config_service import (
    UnknownAgent,
    agent_defaults,
    resolve_agent_config_with,
)
from api.services.authority_service import require_project_administration

router = APIRouter(prefix="/projects/{slug}/agents", tags=["agent-config"])


class AgentConfigBody(BaseModel):
    """The overrides this project records for one agent. Every field is optional and nullable.

    `None` means "no override, use the agent's default" - the same thing a NULL column means,
    and the reason the six are declared here rather than being required: a section that has
    only ever had a voice chosen must be able to say so without inventing a display name.

    An **empty string is not None.** The table draws that distinction deliberately (a project
    that has cleared a name has said something; a project that never opened the settings has
    not), so it is preserved on the wire rather than normalised away here.
    """

    display_name: str | None = None
    image_url: str | None = None
    voice_id: str | None = None
    language: str | None = None
    country_code: str | None = None
    model_id: str | None = None


def _defaults_or_404(agent_id: str) -> dict[str, Any]:
    """The agent's defaults, or a 404 naming the id.

    `UnknownAgent` rather than an empty resolution is `agent_config_service`'s rule and this
    door keeps it: an `agent_id` outside `AGENT_IDENTITY` is a typo or a retired key, and
    answering a shrug would let a misspelled id be configured into a row nothing ever reads.
    """
    try:
        return agent_defaults(agent_id)
    except UnknownAgent:
        raise HTTPException(status_code=404, detail=f"Unknown agent '{agent_id}'")


async def _answer(conn: Any, *, slug: str, agent_id: str, defaults: dict[str, Any]) -> dict:
    """Defaults, overrides and the resolution of one over the other, in one shape.

    The resolution is `resolve_agent_config_with` rather than a merge written here. The rule -
    NULL means the default, `''` does not - lives in `agent_config_service._merge` and a second
    expression of it in a router is precisely the drift that module exists to end.
    """
    project = await fetch_project(conn, slug=slug)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    row = await fetch_agent_config(conn, project_id=project["id"], agent_id=agent_id)
    return {
        "agent_id": agent_id,
        # Whether this project has ever recorded anything for this agent. Distinct from "every
        # override is None", which a row of NULLs also satisfies - `fetch_agent_config` keeps
        # the two apart for this reader.
        "configured": row is not None,
        "defaults": defaults,
        "overrides": {field: (row[field] if row else None) for field in AGENT_CONFIG_COLUMNS},
        "resolved": await resolve_agent_config_with(conn, slug=slug, agent_id=agent_id),
    }


@router.get("/{agent_id}/config")
async def get_agent_config(
    slug: str, agent_id: str, payload: dict = Depends(require_any_auth)
) -> dict:
    """This project's configuration for one agent, defaults and overrides shown apart.

    A read, so the membership floor and nothing else - the same authority as
    `GET /{slug}/settings`, which this sits beside. An administrator sees the same answer they
    are about to change; a reviewer sees who is going to interview their stakeholders.
    """
    await check_project_access(slug, payload)
    defaults = _defaults_or_404(agent_id)
    async with get_connection(slug) as conn:
        return await _answer(conn, slug=slug, agent_id=agent_id, defaults=defaults)


@router.put("/{agent_id}/config")
async def put_agent_config(
    slug: str,
    agent_id: str,
    body: AgentConfigBody,
    payload: dict = Depends(require_any_auth),
) -> dict:
    """Replace this project's overrides for one agent, and answer the new resolution.

    The floor first, then the administration gate - never the gate alone, which would let a
    platform role act on an engagement it is not on.

    Answers the same shape `GET` does rather than an acknowledgement, because the resolved
    value after a save is the thing the section renders and re-deriving it in TypeScript is how
    a page comes to disagree with the server about what it just stored.
    """
    await check_project_access(slug, payload)
    await require_project_administration(slug, payload)
    defaults = _defaults_or_404(agent_id)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        await upsert_agent_config(
            conn,
            project_id=project["id"],
            agent_id=agent_id,
            display_name=body.display_name,
            image_url=body.image_url,
            voice_id=body.voice_id,
            language=body.language,
            country_code=body.country_code,
            model_id=body.model_id,
        )
        return await _answer(conn, slug=slug, agent_id=agent_id, defaults=defaults)
