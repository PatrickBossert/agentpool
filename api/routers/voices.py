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
    DEFAULT_LIBRARY_LANGUAGE,
    VoiceCatalogueUnavailable,
    accents_present,
    add_library_voice,
    fetch_account_voices,
    fetch_library_voices,
    filter_account_voices,
    languages_present,
    library_axes,
)
from api.services.voice_metadata import resolved_voice_sex

router = APIRouter(prefix="/projects/{slug}/voices", tags=["voices"])


@router.get("")
async def list_voices(
    slug: str,
    accent: str = Query(
        default="",
        description=(
            "ElevenLabs' own accent vocabulary, forwarded unmodified. An **opt-in narrowing**: "
            "the default is every accent, because the accents are all of one language and "
            "narrowing by one of them hides the rest."
        ),
    ),
    gender: str | None = Query(default=None),
    language: str | None = Query(
        default=None,
        description=(
            "ElevenLabs' own language codes, forwarded unmodified to the library query. "
            f"Omit for the default, `{DEFAULT_LIBRARY_LANGUAGE}`; pass an empty string to ask "
            "for every language. The account listing is never narrowed by it."
        ),
    ),
    search: str | None = Query(default=None),
    current_voice_id: str | None = Query(
        default=None,
        description=(
            "The voice this agent is already configured with. Not a filter - it is answered "
            "back as `voice_sex`, so the picker can open on voices of the same sex without "
            "deriving that from the listing."
        ),
    ),
    payload: dict = Depends(require_any_auth),
) -> dict[str, Any]:
    """Both voice listings for this project: English by default, every accent by default.

    `check_project_access` is the **first** line. The door takes a slug in its path, and the
    route sweep counts exactly that - but the floor is here because the caller has to be on
    the engagement, not because the sweep would notice if it were not.

    **Two axes, and only one of them is a narrowing.** `en` is the language; `british`,
    `irish`, `american` and `new zealand` are accents of it, and ElevenLabs keeps them as
    separate query parameters. This door used to apply the project's `interview_accent` -
    `british` by default - as the filter a picker opened on, which showed **6 of 41** account
    voices measured on 7 September. So the default moved onto the axis that broadens: the
    library is asked for `DEFAULT_LIBRARY_LANGUAGE`, and the accent narrows nothing until
    somebody asks it to.

    `interview_accent` is retired rather than merely unread. It had this one production reader
    and reached no interview - the accent an interview is conducted in is a property of the
    voice each interviewer is given, chosen per agent and stamped on the session - so a
    setting named "Interview accent" decided nothing about interviews while hiding 85% of the
    voices in a picker.

    **Omitted and empty are different for `language`, and that distinction moved with the
    default.** Omitted means "you decide" and is answered `en`; empty means the consultant
    wants every language. `accent` needs no such distinction any more, because it no longer
    has a default to be cleared of - both spellings of "say nothing" mean every accent, and a
    parameter with two ways to say one thing invites a caller to depend on the difference.

    **The account listing is never narrowed by language.** These are the deployment's own
    voices, all 41 deliberately added by somebody, and `filter_account_voices` is not offered
    a language to filter on - structural rather than remembered. The default exists to stop a
    consultant scrolling past the library's other languages, and the account has no such
    problem to solve.

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

    **`voice_sex` answers the sex of the voice the caller already has**, and it is here rather
    than on the agent configuration door because this is the request the picker makes when it
    *opens*: a user-initiated action where a wait is expected, on a surface that already has a
    spinner and already tolerates a failed listing. Resolving it on the configuration read
    instead put a third-party round trip on the happy path of a read every agent panel makes,
    for a value only the picker consumes - and since failed lookups are not cached, an outage
    was re-paid on every render.

    **It is asked of `ask_voice_sex`, never derived from the listing.** The obvious shortcut is
    to look the voice up in `account` and read its `gender`, and it fails silently for exactly
    the callers that narrowed by accent: the listing is narrowed by `applied_accent`, so a
    voice of a different accent is simply not in it, and "not found" is indistinguishable from
    "no label". Asking keeps this door and the crew's `always_male`/`always_female` selection
    reading one source, which is the constraint this whole line of work turns on.

    **`accent_options` is what a picker renders, and it is the union of both listings.** The
    first version of this door derived the options from the account alone, which made **Irish
    unreachable** - irish exists only in the library, and Irish is one of the four planned
    engagements. That left the picker two bad choices: hardcoding a list of accents, or
    offering no way to reach one of the four. Retiring the accent default disturbs none of
    that - the union is what it always was, and the probe is still asked unfiltered.

    **`language_options` is the same rule on the new axis**, and it is not decoration. A
    control that applies `en` must be able to show `en` and to offer what else exists, or the
    default becomes a filter with no way out - which is the defect this change exists to
    repair, reintroduced one axis over. Derived from `verified_languages` on the account
    listing and the library probe, never from a list in this codebase, and `applied_language`
    joins it so a picker never applies a filter its own control cannot show.
    """
    await check_project_access(slug, payload)

    applied_accent = accent
    applied_language = DEFAULT_LIBRARY_LANGUAGE if language is None else language

    account: list[dict[str, Any]] = []
    account_accents: list[str] = []
    account_languages: list[str] = []
    account_error: str | None = None
    library: list[dict[str, Any]] = []
    library_has_more = False
    lib_accents: list[str] = []
    lib_languages: list[str] = []
    # True when the probe was truncated *or* failed. Either way the option lists are not the
    # library's whole vocabulary - of either axis, since one truncated page truncates both -
    # and a picker must not present them as one.
    options_partial = False
    library_error: str | None = None

    try:
        all_account = await fetch_account_voices()
        # Both derived from the **unfiltered** listing, so the picker's dropdowns offer what
        # this account actually holds rather than only the value already selected.
        account_accents = accents_present(all_account)
        account_languages = languages_present(all_account)
        # **No `language=` here, and that absence is the design.** These are the deployment's
        # own voices, every one deliberately added, and narrowing them by the language default
        # would reintroduce on the account listing exactly the hidden-voices defect this
        # change removed from the accent. Structural: the parameter is not passed, so there is
        # nothing to get wrong rather than a rule to remember.
        account = filter_account_voices(all_account, accent=applied_accent, gender=gender)
        account_ids = frozenset(
            v["voice_id"] for v in all_account if isinstance(v.get("voice_id"), str)
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except VoiceCatalogueUnavailable as exc:
        account_error = str(exc)
        account_ids = frozenset()

    # Asked **before** the narrowed call and deliberately unfiltered - see `library_axes`.
    # Both are needed: the narrowed one is the result set, and asked with `accent=british` it
    # reports british, so a dropdown derived from it would offer exactly the option already
    # selected. That argument now has a second instance the default makes unavoidable: the
    # narrowed call carries `language=en` on a bare request, so a language dropdown derived
    # from it would offer `en` alone. Cached per process, so this is one extra request per
    # process rather than per keystroke.
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
        lib_accents, lib_languages, options_partial = await library_axes()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except VoiceCatalogueUnavailable:
        # Not reported in `library_error`, which names a failure of the *result set*: a
        # picker with a short accent list and a full result set has something to show, and
        # setting it here would make an account failure plus a probe failure a 502 while a
        # perfectly good library listing sat in hand.
        options_partial = True

    try:
        library, library_has_more = await fetch_library_voices(
            accent=applied_accent,
            gender=gender,
            language=applied_language,
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
    # `applied_accent` joins them even when neither listing reported it, so a caller whose
    # chosen accent is beyond the library page, or whose library call failed, still sees the
    # value in the control rather than a dropdown that silently disagrees with the filter it
    # is applying.
    accent_options = sorted(
        {a for a in account_accents + lib_accents + [applied_accent] if a}
    )
    # The same union and the same rule on the language axis. `applied_language` matters more
    # here than `applied_accent` does above, because there is a **default**: a bare request
    # applies `en`, and a control that could not show `en` would leave a filter nobody chose
    # with no way out - which is precisely the defect on the accent axis that this change
    # exists to repair.
    language_options = sorted(
        {lang for lang in account_languages + lib_languages + [applied_language] if lang}
    )

    return {
        "accent": applied_accent,
        # What the library was actually asked for, which is the default when the request named
        # no language and `""` when it asked for every one.
        "language": applied_language,
        "filters": {"gender": gender, "search": search},
        # The sex of the voice the caller arrived with, or None where it cannot be established
        # or acted on. `None` means **open unfiltered**, never "no voices" and never an error:
        # `resolved_voice_sex` collapses four routes onto it and the picker must treat them
        # alike.
        #
        # It is one more provider round trip on a door that already makes up to three, and it
        # does add to the wait rather than overlapping it. That is the trade this move accepts:
        # the cost belongs on the request a consultant made by opening the picker, not on the
        # configuration read that renders behind it. Omitting `current_voice_id` costs nothing
        # at all - `ask_voice_sex` returns without a request for an absent voice.
        "voice_sex": await resolved_voice_sex(current_voice_id),
        "accent_options": accent_options,
        # The vocabulary walk stopped at its bound with the provider still saying there was
        # more, or a page of it failed. Either way the list is not the library's whole accent
        # vocabulary, and a control that renders it as exhaustive is presenting part of the
        # library as all of it - which is how Irish went missing on 7 September.
        "accent_options_partial": options_partial,
        "language_options": language_options,
        # The same flag under the name of the axis it qualifies. One value, deliberately
        # served twice: both lists are read off the same walk, so whatever it did not reach
        # was unread for both - and a consumer of `language_options` that had to know it
        # should read a field named for the *accent* would eventually not.
        "language_options_partial": options_partial,
        "account_accents": account_accents,
        "library_accents": lib_accents,
        "account_languages": account_languages,
        "library_languages": lib_languages,
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
