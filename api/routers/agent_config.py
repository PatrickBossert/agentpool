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

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import check_project_access, require_any_auth
from api.database import (
    AGENT_CONFIG_COLUMNS,
    fetch_agent_config,
    fetch_project,
    get_connection,
    get_db_path,
    is_contained_slug,
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


# A URI scheme at the front of the string: `scheme:` where scheme starts with a letter. RFC
# 3986's production, so `/agents/x.jpg`, `agents/x.jpg` and `//host/x.jpg` all correctly have
# none - a relative reference cannot contain a colon before its first slash.
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_BROWSER_SCHEMES = {"http", "https"}

# The two things the WHATWG URL parser does to a string **before** it reads the scheme, and the
# only two this function reproduces. Nothing else of that algorithm is copied: the rest decides
# hosts, ports and paths, none of which this check has an opinion about.
_TAB_OR_NEWLINE = re.compile(r"[\t\n\r]")
# C0 control or space - U+0000 to U+0020 inclusive. `str.strip()` is **not** this set: it strips
# some Unicode spaces this does not, and misses `\x00`-`\x08`, `\x0e`-`\x1f`, which this does.
_C0_OR_SPACE = "".join(chr(code) for code in range(0x21))


def _as_the_browser_reads_it(value: str) -> str:
    """The candidate, normalised the way the URL parser normalises it before parsing a scheme.

    **A smaller normalisation is a bypass, and this one was.** The first version of this check
    called `str.strip()`, which cannot see a character in the *middle* of a string - so
    `ja\\tvascript:alert(1)` matched no scheme, was accepted with 200, was stored verbatim, and
    came back out of `resolve_agent_config_with` for the browser to reassemble into
    `javascript:alert(1)`. Eight inputs got through that way, including `\\x00javascript:` and
    the `data:` equivalents. It is the textbook scheme-filter bypass and it defeated the check
    completely: any refused scheme could be spelled with a tab in it.

    Two steps, in the parser's own order:

    1. Remove leading and trailing **C0 control or space**. Strictly larger than `str.strip()`
       at the ends, which is the half that let a leading `\\x00` through.
    2. Remove **every** tab, line feed and carriage return, from anywhere. This is the half a
       `strip()` can never do, and the half that matters - the colon has to end up adjacent to
       the letters before any scheme test can see it.

    Both orders happen to agree here, since tab, LF and CR are themselves C0 controls, but the
    parser's order is kept so the correspondence is checkable rather than argued.

    Deliberately **not** the whole algorithm. Percent-encoding, full-width colons and zero-width
    spaces are all left alone, and they are safe to leave: a browser resolves each of them to a
    same-origin *relative path*, which is the permitted case, rather than reconstituting a
    scheme. Reproducing more would be a second URL parser in this repository, which is a worse
    thing to own than this five-line correspondence.
    """
    return _TAB_OR_NEWLINE.sub("", value.strip(_C0_OR_SPACE))


def _assert_renderable_image(image_url: str | None) -> None:
    """Refuse an `image_url` a browser would not fetch over http or https.

    **This value is not read by this server.** It is written into the interview page's branding
    payload and lands in an `<img src>` on `VoiceInterview.tsx`, and that page is rendered for a
    participant holding a session token and no login - `GET /projects/{slug}/branding/image` is
    one of the two doors CLAUDE.md documents as deliberately having no floor at all, for exactly
    that reason. So what is stored here is a string this deployment hands to somebody else's
    browser, and the question is what that browser will do with it.

    **What this guard is actually for, stated at its real strength.** `<img src>` is the only
    sink, and in that sink a `javascript:` URL does **not** execute - the load simply fails - and
    a `data:image/svg+xml` renders in the restricted image mode, with no script and no external
    fetch. An earlier version of this docstring said `javascript:` "executes on the interview
    origin", which is untrue here, and it said so in the same paragraph as a check that any tab
    could walk through. Overstating the threat while understating the porousness is the pairing
    most likely to stop the next reader looking, and CLAUDE.md's rule is that a guard's reach is
    established rather than described.

    The honest reason is narrower and still worth having: it holds the field to the two schemes
    that **fetch a resource over the network**, so the reach stays inside the class
    `brand_header_image_url` already permits and does not quietly grow a new one. That matters
    most for a change nobody has made yet - move this value into an `href`, a CSS `url()` or an
    `<object>` and the sink stops being forgiving, while a guard that reads as working would be
    inherited unexamined.

    **An off-site `http`/`https` URL is still allowed, and that is a decision rather than an
    oversight.** It makes every participant's browser fetch from a third party, disclosing their
    IP, their user agent and the timing of an interview in progress - on a `sensitive`
    engagement whose documents and inference this project keeps on the premises. It is permitted
    because `brand_header_image_url` on `ProjectSettings` has always done the same thing on the
    same page through `PATCH /{slug}/settings`, so refusing it here would close half a class and
    leave the operator unable to tell which half. The reach is **declared** instead, in
    `agents/egress.py`, naming both fields; the real fix is a same-origin upload path serving
    both, and it is its own task.

    `//host/x.png` is permitted for the same reason - the browser resolves it to `https://host/`,
    which is a shape this door already accepts spelled out in full. It is the one permitted value
    that reads to an operator like a local path, so an operator-facing "this points off-site"
    warning, whenever the upload task adds one, has to resolve rather than string-match.

    A relative path is the intended shape and passes untouched. `''` passes too: it is a
    deliberate clear, not an address.

    The refusal names the scheme **as the browser would reconstitute it**, not as it was typed.
    An administrator who pasted something with a stray tab in it is told what it actually is, and
    a test asserting that name cannot pass against a check that skipped the normalisation.
    """
    if not image_url:
        return
    match = _SCHEME.match(_as_the_browser_reads_it(image_url))
    if match is None:
        return
    # Lower-cased, because the parser lower-cases a scheme too: the sentence reports what the
    # browser would end up with rather than how it was typed, which is the whole point of
    # normalising before matching. `JavaScript:` and `ja<tab>vascript:` are both reported as
    # `javascript:`, and a test asserting that name cannot pass against a check that matched the
    # raw string.
    scheme = match.group(0)[:-1].lower()
    if scheme not in _BROWSER_SCHEMES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"image_url must be a path or an http/https address - "
                f"'{scheme}:' is not one a browser fetches over the network on the interview "
                "page"
            ),
        )


def _assert_project_exists(slug: str) -> None:
    """404 for a slug with no database, **before** `get_connection` is asked for one.

    `get_connection` runs the migration block against whatever file it is handed and creates
    the file if it is missing, so a caller probing slugs would otherwise materialise one
    database per guess. `caller_roles` and `_stakeholder_matches_invite` already carry this
    guard for the same reason, and CLAUDE.md names the hazard twice.

    Only a `sysadmin` could ever reach it here - everyone else is refused by
    `check_project_access` first - so this is the file-per-guess hazard rather than an
    escalation. `is_contained_slug` is asked as well as existence because a slug that escapes
    `DATABASE_DIR` would have this door running schema into somebody else's database, and the
    two questions are answered together everywhere else this pattern appears.
    """
    if not is_contained_slug(slug) or not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")


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
    _assert_project_exists(slug)
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
    _assert_project_exists(slug)
    _assert_renderable_image(body.image_url)
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
