# api/routers/voices.py
"""The voice picker's door: both ElevenLabs listings, and the one write that adds to them.

**One door, both listings.** `GET /v1/voices` is what the account already holds; `GET
/v1/shared-voices` is the Voice Library. The rate lives only on the library and Irish exists
only on the library, so a picker offered one of them is missing either the cost or half the
accents. Proxying them separately would make that mistake available; proxying them together
makes it impossible.

**Preview is `preview_url` and makes no synthesis call.** Every voice in both listings carries
a sample ElevenLabs already hosts, so the client plays that URL. Speaking a line through
`synthesise` would spend characters on audio that exists, be slower, and sound *identical* to
a listener - which is why `tests/test_voice_catalogue.py` asserts on the wire that nothing in
this path reaches `/v1/text-to-speech`, rather than trusting the code to look right.

## The two doors and their two authorities

`GET` is a read of provider metadata carrying no client material, so it takes the membership
floor - `check_project_access` - and nothing else. CLAUDE.md: a pure read needs neither gate.

`POST /library` is **platform tier**, and that is one step tighter than the design asked for.
The design called it "the same authority as any other project configuration change", which
would be `require_project_administration`. It is not, for the reason the knowledge tiers are
decided on: **the write does not stay inside the engagement.** There is one ElevenLabs account
per deployment, shared by every client on it, so adding a voice spends the consultancy's credit
and changes what every other engagement's picker shows. That is the shape
`require_writable_tier` refuses at the sector tier - "the sector store is the only one whose
readership is other clients" - and it is why `resend-invite` is the one write in
`stakeholders.py` that stayed on the platform tier while fifteen doors around it widened.

Being too tight costs a client-side project_admin a message to their consultant. Being too
loose lets them spend somebody else's money into a store every other client reads. The slug is
still scoped first with `check_project_access`, because the door is mounted under one and a
platform role is not a membership.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth import check_project_access, require_any_auth, require_org_admin_or_above
from api.services.voice_catalogue import (
    VoiceCatalogueUnavailable,
    accents_present,
    add_library_voice,
    fetch_account_voices,
    fetch_library_voices,
    filter_account_voices,
    library_accents,
)
from api.services.voice_settings import project_interview_accent

router = APIRouter(prefix="/projects/{slug}/voices", tags=["voices"])


@router.get("")
async def list_voices(
    slug: str,
    accent: str | None = Query(
        default=None,
        description=(
            "ElevenLabs' own accent vocabulary - british, scottish, irish, australian, "
            "new zealand. Omit to use the project's `interview_accent`; pass an empty "
            "string to ask for every accent."
        ),
    ),
    gender: str | None = Query(default=None),
    language: str | None = Query(default=None),
    search: str | None = Query(default=None),
    payload: dict = Depends(require_any_auth),
) -> dict[str, Any]:
    """Both voice listings for this project, with the project's accent applied by default.

    `check_project_access` is the **first** line. The door takes a slug in its path, and the
    route sweep counts exactly that - but the floor is here because the caller has to be on
    the engagement, not because the sweep would notice if it were not.

    **Omitted and empty are different**, and the difference is the whole reason `accent`
    defaults to `None` rather than to `""`. Omitted means "you decide", and the answer is the
    project's `interview_accent`; empty means the consultant has cleared the filter and wants
    the lot. Collapsing them would make the project setting unclearable from the picker.

    **A partial answer is reported, never hidden.** If one listing fails and the other
    succeeds, the successful one is returned with the failure named in `account_error` or
    `library_error`, because a picker showing the account's five British voices is useful even
    when the library is unreachable - and a picker silently showing five when it should show
    ninety is the failure that gets diagnosed as "there are no Scottish voices". If **both**
    fail there is nothing to show and it is a 502; the sentence names both.

    **Truncation is a partial answer too, and it is reported the same way.** Both library
    calls are one bounded page with no pagination behind it, so `library_has_more` and
    `accent_options_partial` carry the provider's own `has_more` out to whatever renders
    them. A consumer that cannot tell a complete answer from a first page will present one as
    the other, and on a picker that reads as "that voice is not in the library".

    **`accent_options` is what a picker renders, and it is the union of both listings.** The
    first version of this door derived the options from the account alone, which made **Irish
    unreachable** - irish exists only in the library, and Irish is one of the four planned
    engagements. That left the picker two bad choices, hardcoding a list of accents or
    offering no way to reach one of the four, and it quietly made free-text `interview_accent`
    the only route to Irish, which is weight an open vocabulary was not chosen to carry.
    """
    await check_project_access(slug, payload)

    applied_accent = await project_interview_accent(slug) if accent is None else accent
    accent_source = "project" if accent is None else "request"

    account: list[dict[str, Any]] = []
    account_accents: list[str] = []
    account_error: str | None = None
    library: list[dict[str, Any]] = []
    library_has_more = False
    lib_accents: list[str] = []
    # True when the probe was truncated *or* failed. Either way the option list is not the
    # library's whole accent vocabulary, and a picker must not present it as one.
    accent_options_partial = False
    library_error: str | None = None

    try:
        all_account = await fetch_account_voices()
        # Derived from the **unfiltered** listing, so the picker's accent dropdown offers the
        # accents this account actually holds rather than only the one already selected.
        account_accents = accents_present(all_account)
        account = filter_account_voices(all_account, accent=applied_accent, gender=gender)
        account_ids = frozenset(
            v["voice_id"] for v in all_account if isinstance(v.get("voice_id"), str)
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except VoiceCatalogueUnavailable as exc:
        account_error = str(exc)
        account_ids = frozenset()

    # Asked **before** the narrowed call and deliberately unfiltered - see `library_accents`.
    # Both are needed: the narrowed one is the result set, and asked with `accent=british` it
    # reports british, so a dropdown derived from it would offer exactly the option already
    # selected. Cached per process, so this is one extra request per process rather than per
    # keystroke.
    #
    # **Its own `try`, and the separation is the whole point.** These two shared one for a
    # single commit and the coupling ran in both directions. Sharing it made the *auxiliary*
    # query gate the *primary* one, and the probe is the heavier of the two - the unfiltered
    # hundred-voice page against a narrowed query - so the more likely failure was the one
    # suppressing the result set entirely. And the shared `except` cleared `lib_accents`
    # unconditionally, so a failure of the **narrowed** call discarded a cached, known-good
    # probe: `accent_options` went from `['british', 'irish', 'scottish']` to
    # `['british', 'scottish']`, losing precisely the option the probe exists to add.
    try:
        lib_accents, accent_options_partial = await library_accents()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except VoiceCatalogueUnavailable:
        # Not reported in `library_error`, which names a failure of the *result set*: a
        # picker with a short accent list and a full result set has something to show, and
        # setting it here would make an account failure plus a probe failure a 502 while a
        # perfectly good library listing sat in hand.
        accent_options_partial = True

    try:
        library, library_has_more = await fetch_library_voices(
            accent=applied_accent,
            gender=gender,
            language=language,
            search=search,
            account_ids=account_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except VoiceCatalogueUnavailable as exc:
        library_error = str(exc)

    if account_error and library_error:
        raise HTTPException(status_code=502, detail=f"{account_error}; {library_error}")

    # The union, and the one thing a picker should render. `account_accents` and
    # `library_accents` are kept beside it because they answer different questions - "what can
    # I use now" against "what could I add" - but neither alone is the option list: the account
    # has no Irish voice and the library is where Irish lives.
    #
    # `applied_accent` joins them even when neither listing reported it, so a project whose
    # saved accent is beyond the library page, or whose library call failed, still sees its own
    # setting in its own picker rather than a control that silently disagrees with the filter
    # it is applying.
    accent_options = sorted(
        {a for a in account_accents + lib_accents + [applied_accent] if a}
    )

    return {
        "accent": applied_accent,
        "accent_source": accent_source,
        "filters": {"gender": gender, "language": language, "search": search},
        "accent_options": accent_options,
        # The options came off one bounded page, or off a probe that failed. Either way the
        # list is not the library's whole accent vocabulary, and a control that renders it as
        # exhaustive is presenting a first page as a complete answer.
        "accent_options_partial": accent_options_partial,
        "account_accents": account_accents,
        "library_accents": lib_accents,
        "account": account,
        "account_error": account_error,
        "library": library,
        # `LIBRARY_PAGE_SIZE` bounds the result set and there is no pagination, so this is how
        # a picker knows to say "narrow your filters" rather than "that voice is not in the
        # library".
        "library_has_more": library_has_more,
        "library_error": library_error,
    }


class AddLibraryVoiceRequest(BaseModel):
    """Which library voice to copy into the account, and what to call it there.

    All three are required with `min_length=1`. `public_owner_id` comes off the library entry
    and has no default it could be guessed from, and a blank `name` would have ElevenLabs
    name the copy for us - a silent choice on a resource shared by every engagement.
    """

    public_owner_id: str = Field(min_length=1)
    voice_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


@router.post("/library", status_code=201)
async def add_voice_to_account(
    slug: str,
    body: AddLibraryVoiceRequest,
    payload: dict = Depends(require_org_admin_or_above),
) -> dict[str, Any]:
    """Copy a Voice Library voice into this deployment's ElevenLabs account.

    Platform tier, for the reason in the module docstring: one account serves every
    engagement, so this is not a change to *this* project. `check_project_access` still runs
    first - the door is mounted under a slug, and a platform role says nothing about whether
    the caller is on this engagement.

    The response carries the **new** `voice_id` the account assigned. It is not the library id
    that was sent, and a project's configuration must hold the new one.
    """
    await check_project_access(slug, payload)
    try:
        added = await add_library_voice(
            public_owner_id=body.public_owner_id, voice_id=body.voice_id, name=body.name
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except VoiceCatalogueUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return added
