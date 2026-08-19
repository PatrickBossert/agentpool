# api/routers/platform_settings.py
"""The platform_settings door: read and change the address this deployment answers on.

A router of its own rather than a home in `skills.py`, which is the other holder of
`/admin/*` paths. The prefix is shared; nothing else is. `skills.py` is the agent skills
library - CRUD, a review queue, and LLM extraction - and platform configuration filed under
it would be findable only by whoever already knew. `admin.py` was the other candidate and is
further off: despite its name it mounts under `/auth`, so a route added there would answer on
`/auth/platform-settings` and lose the `/admin` prefix this belongs under.

No proxy change accompanies this. `/admin` is already forwarded by both the `Caddyfile`
(`handle /admin*`) and `ui/vite.config.ts` (`'/admin': 'http://localhost:8000'`), and
`tests/test_proxy_prefix_coverage.py` re-derives that from the mounted routes rather than
from a list, so it would fail here if either config had stopped covering the prefix.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_sysadmin
from api.database import get_system_db
from api.services.platform_settings import (
    PublicUrlRefused,
    read_platform_settings,
    revert_platform_public_url,
    save_platform_public_url,
)

router = APIRouter(prefix="/admin", tags=["platform-settings"])


class PlatformSettingsPatch(BaseModel):
    public_url: str


@router.get("/platform-settings", dependencies=[Depends(require_sysadmin)])
async def get_platform_settings(conn=Depends(get_system_db)):
    """The public URL in force, and whether it is stored or inherited from the environment.

    Sysadmin for the same reason the write is - see `patch_platform_settings` below. There
    is nothing secret in the answer (it is in the footer of every email the deployment
    sends), but it is the read half of a sysadmin-only page and a door that opens wider than
    the one beside it invites a UI that offers an edit it cannot perform.
    """
    return await read_platform_settings(conn)


@router.patch("/platform-settings", dependencies=[Depends(require_sysadmin)])
async def patch_platform_settings(
    req: PlatformSettingsPatch, conn=Depends(get_system_db)
):
    """Change the address this deployment answers on.

    **`require_sysadmin`, a tier tighter than the platform-tier settings in `projects.py`.**
    Whoever sets this decides where every interview invitation and every welcome email
    points, and a participant clicks that link and signs in - so a wrong value here is a
    credential-phishing vector rather than a misconfiguration. `_PLATFORM_TIER_SETTINGS`
    keeps an org_admin out of the eight per-project fields that decide where one
    engagement's data is sent; this is the whole deployment, every project on it, and every
    person who has ever been invited to one.

    The rules about what a public URL may be are in
    `api.services.platform_settings.normalise_public_url`, not here. This handler's only job
    on a refusal is to choose a status code and pass the service's own sentence through: 400
    rather than 422, because the body's *shape* was fine - Pydantic already accepted it - and
    what was refused is the value.
    """
    try:
        await save_platform_public_url(conn, req.public_url)
    except PublicUrlRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await read_platform_settings(conn)


@router.delete("/platform-settings", dependencies=[Depends(require_sysadmin)])
async def delete_platform_settings(conn=Depends(get_system_db)):
    """Revert to inheriting the `PUBLIC_URL` environment variable.

    A `DELETE` rather than a `PATCH` carrying `null` or `""`: this door's `PATCH` accepts
    only a `public_url: str`, and `""` is refused by `normalise_public_url`'s scheme rule on
    purpose (see that function's docstring) - admitting it as a special case would make the
    validator's blank-string hole the mechanism for a completely different action. `DELETE`
    names what is actually happening - removing the stored override - and matches the verb
    this codebase already uses for "give this back to whatever it would otherwise be"
    (`DELETE /auth/orgs/{id}`, `DELETE /auth/projects/{slug}`).

    `require_sysadmin` for the same reason the write is: reverting to the environment
    changes where every interview invitation and every welcome email points, exactly as
    setting one does - see `patch_platform_settings` above.

    `revert_platform_public_url` does both halves - clears the stored row and drops the
    module cache - so this door does not restate either.
    """
    return await revert_platform_public_url(conn)
