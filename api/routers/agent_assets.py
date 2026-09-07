# api/routers/agent_assets.py
"""The deployment's own assets for an agent, belonging to no project.

One door: `GET /api/agents/{agent_id}/image`, the promoted default portrait. See
`api/services/agent_default_images.py` for the promotion rule and its four-level precedence
table; this file is only the serving half.

## Why it is not served from the project it came from

`GET /projects/{slug}/agents/{agent_id}/image` already exists and already serves a portrait
without authentication. Reusing it for a promoted default would mean every project's rendering
of that agent pointed at whichever engagement happened to upload first - so the face would
vanish the day that engagement was cleaned up, and until then an unrelated client's markup
would carry another client's slug. A deployment-level asset needs a deployment-level address.

## Why it is unauthenticated

The interview page renders it for a participant holding a session token and no login, which is
the same reason `GET /{slug}/branding/image` and the per-project portrait door have no floor
either. It discloses a portrait of a persona, which is what the door is for, and it carries no
slug at all - so unlike the per-project door it cannot be used to learn whether an engagement
exists.

## The prefix

`/api/agents`, and **`/api*` is already forwarded by both proxies** - the `Caddyfile` block and
the `'/api'` entry in `ui/vite.config.ts` - so this route needs no new entry in either. That is
worth stating rather than leaving to be noticed: a prefix missing from those two configurations
does not 404, it falls through to the static file server and answers the landing page with a
**200**. `tests/test_proxy_prefix_coverage.py` enumerates `app.routes` and would fail if this
route reached neither, which is what makes the sentence above a check rather than a claim.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from agents.identity import AGENT_IDENTITY
from api.services.agent_default_images import promoted_default_file

router = APIRouter(prefix="/api/agents", tags=["agent-assets"])

NO_DEFAULT_PORTRAIT = "No default portrait for this agent."


@router.get("/{agent_id}/image")
async def get_agent_default_image(agent_id: str) -> FileResponse:
    """Serve the deployment's default portrait for one agent. **No authentication, by design.**

    Two 404s and they are deliberately different sentences, following the per-project door:
    an unknown **agent** is named, because the roll is a global constant already returned by
    `GET /projects/{slug}/agents/config` and naming it discloses nothing; an agent with no
    promoted default gets the neutral sentence.

    A recorded row whose file is missing answers the same 404 as no row at all. The row is the
    authority on the address (`promoted_default_file` reads the stored extension rather than
    trying each accepted one in turn), and a missing file behind a live row is a defect in the
    write path rather than something to paper over by guessing at another extension.
    """
    if agent_id not in AGENT_IDENTITY:
        raise HTTPException(status_code=404, detail=f"Unknown agent '{agent_id}'")

    found = promoted_default_file(agent_id)
    if found is None:
        raise HTTPException(status_code=404, detail=NO_DEFAULT_PORTRAIT)

    path, content_type = found
    if not path.exists():
        raise HTTPException(status_code=404, detail=NO_DEFAULT_PORTRAIT)

    return FileResponse(
        path=path,
        media_type=content_type,
        # The bytes were chosen by an administrator and are served from the deployment's own
        # origin, so a browser must not be free to decide they are something else.
        headers={"X-Content-Type-Options": "nosniff"},
    )
