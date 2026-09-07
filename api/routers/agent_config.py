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

It also answers one fact **about** the resolution - `is_interviewer`, from
`interviewer_agent_ids()` - so the section can offer a rehearsal to the agents that can conduct
an interview. Derived server-side, not stored, and not to be restated in TypeScript.

**The sex of the resolved voice is answered by `GET /projects/{slug}/voices`, not here**, and
the reason is what this door costs. It is read once per agent panel on every render, so a
third-party lookup on its happy path is paid by every consultant opening the section, to serve
a value used only by whoever clicks "Change voice" - and because failed lookups are not cached,
an ElevenLabs outage is re-paid on every read rather than once per process. The picker's own
door already takes the voice id and already opens on a user action where a wait is expected.

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

## The portrait is uploaded, not typed

`image_url` has always been free text, so the only way to give an agent a face was to name a
path that somebody had already put in the repository - or an address on somebody else's server.
`POST .../image` takes the photograph itself, hands it to `prepare_portrait`, and answers a
**same-origin** URL under this door's own `GET` sibling.

`GET .../image` has **no authentication at all**, exactly like `GET /{slug}/branding/image` and
for the same reason: the interview page renders it for a participant who has no login. CLAUDE.md
names those two as the deliberate exceptions to the membership floor, and this is the second
shape of the first one rather than a third exception - the same page, the same participant, the
same absence of a credential to check.

**This door does not write `project_agent_config`, and that is deliberate rather than
forgotten.** `upsert_agent_config` replaces the row - a field absent from the call is *cleared* -
so an upload that wrote `image_url` on its own would silently clear the agent's name, voice,
language, country and synthesis model. The upload answers the URL and the caller sends it back
through `PUT .../config` with the rest of the row, which is what the Setup section does. Two
consequences to expect rather than diagnose: a file uploaded and never saved is an orphan on
disk that nothing resolves to, and the order matters - post the file, then the configuration.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.auth import check_project_access, require_any_auth
from api.config import get_settings
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
    is_interviewer,
    resolve_agent_config_with,
)
from api.services.authority_service import require_project_administration
from api.services.image_intake import (
    PORTRAIT_CONTENT_TYPES,
    PortraitRejected,
    prepare_portrait,
)

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

    `//host/x.png` is permitted for the same reason - the browser resolves it against **the
    page's own scheme**, so it is `https://host/` on an https deployment and `http://host/` on an
    http one, and either way it is a shape this door already accepts spelled out in full. It is
    the one permitted value that reads to an operator like a local path, so an operator-facing
    "this points off-site" warning, whenever the upload task adds one, has to resolve rather than
    string-match.

    **The asymmetry this does not close, named so it is not assumed away.** The `<img src>` this
    value reaches is also fed by `brand_header_image_url`, which `interview_service` reads
    straight out of `config` and which `PATCH /{slug}/settings` writes with no validator on any
    part of the path. So the *scheme* half of this check is one door wide, exactly as the
    *off-site* half is - and the paragraph above, which reasons carefully about the second, was
    silent about the first, which is the half a reader would assume is closed. Both belong to the
    shared same-origin upload path that is the recorded follow-up; neither is widened here.

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
    """Defaults, overrides, the resolution of one over the other, and one fact about it.

    The resolution is `resolve_agent_config_with` rather than a merge written here. The rule -
    NULL means the default, `''` does not - lives in `agent_config_service._merge` and a second
    expression of it in a router is precisely the drift that module exists to end.

    `is_interviewer` is **derived, not stored beside the row**, and it is answered by
    `agent_config_service` for the same reason the merge is: the Setup section renders a Test
    interview button on it, and re-deriving the roster in TypeScript would be a fifth
    declaration of a voice fact - the exact thing this branch exists to end.

    **Nothing here reaches a third party.** Both values are read from local data, which is the
    property that had to be restored: the sex of the resolved voice was answered here for one
    commit and moved to the picker's own door, because this one is read on every render of
    every agent panel.
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
        "is_interviewer": is_interviewer(agent_id),
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


# The first four bytes each declared type must start with. **Kept in front of
# `prepare_portrait`, which performs a strictly stronger check**, because the stronger one hands
# the whole payload to a decoder before it can say anything: this refuses the obvious cases
# before Pillow is reached, exactly as `upload_branding_image` does. The two are complementary,
# not redundant, and dropping this one on the grounds that the decoder verifies the format would
# be trading a cheap refusal for an expensive one.
#
# Keyed on the same content types the allowlist declares, and
# `test_every_accepted_content_type_has_a_magic_prefix` holds the two equal. The lookup below is
# a **subscript rather than a `.get(..., b"")`** for that reason: `b""` is a prefix of every
# payload, so a default would give a fourth type added to `PORTRAIT_CONTENT_TYPES` a check that
# refuses nothing and says nothing. `upload_branding_image` has the defaulting form today; this
# one fails loudly instead, and the test above turns that from a 500 into a red suite.
_MAGIC_PREFIXES: dict[str, bytes] = {
    "image/png": b"\x89PNG",
    "image/jpeg": b"\xff\xd8",
    "image/webp": b"RIFF",
}


def _portrait_dir(slug: str) -> Path | None:
    """Where this project keeps its agent portraits, or `None` if the slug escapes.

    The slug reaches `GET .../image` with **no authentication at all**, so it is the one input
    on this door that an anonymous caller chooses freely, and it is joined onto a filesystem
    path. Containment is asserted against the resolved path rather than the string, which is the
    technique `serve_output_file` already uses on the same root: `..` lands above PROJECTS_DIR
    and an absolute slug replaces it outright, and both resolve to somewhere this refuses.

    Not `is_contained_slug`, which answers the same question about a different root
    (DATABASE_DIR) - two rules that happen to reject the same strings are not one rule, and the
    guarantee wanted here is about the directory the bytes are actually read from.
    """
    root = Path(get_settings().projects_dir).resolve()
    candidate = (root / slug / "assets" / "agents").resolve()
    if not str(candidate).startswith(str(root) + os.sep):
        return None
    return candidate


@router.post("/{agent_id}/image")
async def upload_agent_image(
    slug: str,
    agent_id: str,
    file: UploadFile = File(...),
    payload: dict = Depends(require_any_auth),
) -> dict:
    """Store a portrait for one agent on this project, and answer the URL that serves it.

    The order is `upload_branding_image`'s and is copied deliberately: the membership floor
    first, then the administration gate, and **both before the existence check** - a caller from
    outside the engagement must not be able to use this door to learn which slugs exist. The
    agent roll comes next, for the reason `_defaults_or_404` gives.

    Then the cheap refusals in the order that spends the least on a payload that is going to be
    refused anyway: the declared type, the magic-byte prefix, and only then `prepare_portrait`,
    which decodes. The ceiling is `prepare_portrait`'s and is not restated here - it names the
    limit in a sentence written to be returned verbatim, and a second copy of `10 * 1024 * 1024`
    in a router is the drift that module exists to prevent.

    Answers the stored size alongside the URL. That is not decoration: the whole point of this
    path is that a large photograph quietly becomes a small one, and an administrator who is
    never told it happened uploads the same 8 MB file again next time.
    """
    await check_project_access(slug, payload)
    await require_project_administration(slug, payload)
    _assert_project_exists(slug)
    _defaults_or_404(agent_id)

    content_type = file.content_type or ""
    if content_type not in PORTRAIT_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported image type '{content_type}'. Must be one of "
                f"{', '.join(sorted(PORTRAIT_CONTENT_TYPES))}."
            ),
        )

    data = await file.read()
    if not data[:4].startswith(_MAGIC_PREFIXES[content_type]):
        raise HTTPException(
            status_code=422, detail="File content does not match declared content type"
        )

    try:
        prepared, extension = prepare_portrait(data, content_type)
    except PortraitRejected as exc:
        # The only exception this path raises for any input, and every sentence it carries is
        # written to be returned to the caller. Anything else escaping it is a defect in
        # `image_intake` and stays a 500 rather than being dressed up as the caller's fault.
        raise HTTPException(status_code=422, detail=str(exc))

    directory = _portrait_dir(slug)
    if directory is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    directory.mkdir(parents=True, exist_ok=True)
    stored = directory / f"{agent_id}{extension}"

    # Any portrait stored under a different extension goes, and this is a correctness
    # requirement rather than tidiness: the `GET` below serves the first extension it finds, so
    # a JPEG left beside a newly uploaded PNG would go on being served and the administrator
    # would be told the upload succeeded while the old face stayed on the interview page.
    for other_extension, _ in PORTRAIT_CONTENT_TYPES.values():
        previous = directory / f"{agent_id}{other_extension}"
        if previous != stored and previous.exists():
            previous.unlink()

    stored.write_bytes(prepared)

    return {
        # No `/api` prefix. This router is mounted at `/projects`, and CLAUDE.md records that
        # only `/api/templates` and `/api/interviews` carry the prefix - so `/api/projects/...`
        # is served by nothing and 404s in the browser, while the file itself sits correctly at
        # the path below. Copied from `upload_branding_image`, which has the same defect and has
        # never shown it: no deployment has ever uploaded a header image, so its wrong URL has
        # never been fetched. Both are corrected together, because two doors returning an
        # address and only one of them resolving is how the next sweep finds the second.
        "url": f"/projects/{slug}/agents/{agent_id}/image",
        "bytes": len(prepared),
        "original_bytes": len(data),
    }


@router.get("/{agent_id}/image")
async def get_agent_image(slug: str, agent_id: str) -> FileResponse:
    """Serve this project's portrait for one agent. **No authentication, by design.**

    The interview page renders it for a participant holding a session token and no login, which
    is the same reason `GET /{slug}/branding/image` has no floor either. CLAUDE.md documents
    that door as one of exactly two deliberate exceptions on the whole surface; this is the same
    exception serving the same page, and if an agent portrait ever becomes client-confidential
    the repair is session-token scoping rather than `check_project_access`.

    It answers 404 for an unknown project, an unknown agent and a project that has uploaded
    nothing, without distinguishing them - there is nothing here worth telling an anonymous
    caller apart.
    """
    _defaults_or_404(agent_id)
    directory = _portrait_dir(slug)
    if directory is None:
        raise HTTPException(status_code=404, detail="No portrait found for this agent.")
    for content_type, (extension, _) in PORTRAIT_CONTENT_TYPES.items():
        candidate = directory / f"{agent_id}{extension}"
        if candidate.exists():
            return FileResponse(
                path=candidate,
                media_type=content_type,
                # The bytes are chosen by an administrator and served from the deployment's own
                # origin, so a browser must not be free to decide they are something else.
                headers={"X-Content-Type-Options": "nosniff"},
            )
    raise HTTPException(status_code=404, detail="No portrait found for this agent.")


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
