# api/services/voice_settings.py
"""Where a project's regional accent comes from, and why it is not the locale it already has.

`ProjectSettings.interview_accent` is the answer, and it holds **ElevenLabs' own accent word**
- `british`, `scottish`, `irish`, `australian`, `new zealand` - which goes on the wire to
`GET /v1/shared-voices?accent=...` unmodified. Nothing in this codebase translates it, which
is the point: a translation is a table, and a table of voice facts is what this branch exists
to end.

## Why a new field, when `ProjectSettings.locale` exists

`locale` is already there, already `GB` by default, already set in the UI, and already means
the country - `getPublicHolidays` and `Intl.DateTimeFormat` consume it. Deriving the accent
from it was the first candidate and it is wrong, for a reason that shows up in the very first
of the four planned engagements: **a Scottish engagement's country code is `GB`.** So is a
British one's. `locale` cannot tell them apart, and no widening of it can - `GB-SCT` is not an
ISO 3166-1 alpha-2 code and would break the two consumers above.

The deeper objection is that deriving would *assert that country determines accent*, and it
does not. A London engagement may deliberately want a Scottish interviewer, and an Irish
engagement run out of a British office is still Irish. One field cannot carry both facts
without one of them being wrong somewhere, and the wrongness is silent.

So there are two fields because there are two questions, and the docstring above says which is
which. What is refused is a *third* thing: an accent-to-voice map. The accent narrows the
listing; the provider says which voices have it.

## Why the vocabulary is open

`interview_accent` is a plain `str`, not a `Literal`. A closed set would be this repository
restating ElevenLabs' accent vocabulary, stale the first time they add one - the sixth
declaration of voice facts on a branch built to end the first five. An unrecognised value
reaches the provider and comes back with nothing, and the door names the accent it applied in
its response, so a typo reads as "no voices for accent 'scotish'" rather than as an outage.

`british` is the default because British English is the default for a new project (Patrick,
4 September). An **empty string** means no accent filter at all, which is a different thing
from the default and is how a consultant clears the picker.
"""
from __future__ import annotations

from api.models import ProjectSettings
from api.services.project_service import read_project_config

# Read off the model rather than typed again, so the default exists once. Restating `british`
# here would be a second declaration that a later change to the model could not reach - the
# same failure mode, at the smallest possible scale.
DEFAULT_INTERVIEW_ACCENT: str = ProjectSettings.model_fields["interview_accent"].default


async def project_interview_accent(slug: str) -> str:
    """This project's accent, or the default where it has recorded none.

    Returns `""` when the project has deliberately cleared the filter, which is why the
    absent-key test is `is None` rather than truthiness: `''` is the project saying "every
    accent" and a missing key is the project having said nothing. `_override` in
    `agent_config_service` draws the same line for the same reason.

    A non-string stored value falls back to the default rather than reaching the provider as
    a number - `config_json` is written through `ProjectSettings`, so it cannot happen through
    the door, and this is about a config hand-edited on disk.
    """
    stored = (await read_project_config(slug)).get("interview_accent")
    return stored if isinstance(stored, str) else DEFAULT_INTERVIEW_ACCENT
