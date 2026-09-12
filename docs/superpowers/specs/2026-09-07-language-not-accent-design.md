# Language is the axis; accent is a narrowing

**Date:** 2026-09-07
**Status:** approved by Patrick, ready to build

## Why

The voice picker opens filtered to the project's `interview_accent`, which defaults to
`british`. Measured against the live account on 7 September: **the picker shows 6 of 41
account voices.** Thirty-five are hidden by a default nobody chose.

Patrick's diagnosis, and it is the right one: **`en` is the language; `british`, `irish`,
`american` and `new zealand` are accents.** ElevenLabs treats them as separate axes - `language`
and `accent` are distinct query parameters, and every voice carries `verified_languages`
alongside `labels.accent`. The picker sends only the accent and never a language, so an axis
that should broaden is being used as one that narrows.

## What is actually being retired, and why it is safe

**`interview_accent` has exactly one production reader** - `api/routers/voices.py:131`, where it
becomes the picker's default filter. It reaches no interview. The accent an interview is
conducted in is a property of **the voice each interviewer is given**, chosen per agent in
`project_agent_config`, and stamped on the session at creation.

So a setting named "Interview accent" decides nothing about interviews and hides 85% of the
voices in a picker. It is removed rather than left to mislead the next reader.

**No live project stores one** - checked across every database in `data/` on 7 September - so
retiring it strands no configuration.

## What replaces it

**The picker opens on English, unfiltered by accent.** Accent stays as an opt-in narrowing with
the same dropdown, populated the same way, from the union of both listings.

`language` defaults to `en` on the library query, which is what makes the broadening honest
rather than merely removing a filter: the library holds voices in many languages, and a
consultant choosing an interviewer for an English engagement should not scroll past them.

The account listing is the deployment's own voices and stays unnarrowed by language - all 41
are ones somebody deliberately added.

**Two axes, two controls, and neither impersonates the other.** A language control appears
beside the accent one, so the multilingual future the agent configuration already carries -
`language` and `country_code` per agent, `model_id` for the synthesis model - has somewhere to
be expressed when a French engagement arrives.

## What must not regress

- **Irish stays reachable.** It is in the library listing and not the account, which is why the
  door unions both. Retiring the accent default must not disturb that union.
- **A picker never applies a filter its own control cannot show** - the rule sp62 established.
  The language control must offer what the listings actually contain, derived from the response
  rather than declared in TypeScript.
- **No voice fact is restated in TypeScript** - not the languages, not the accents, not which
  voice is which sex. The Python source guard does not walk TypeScript and will not catch it.

## Testing

- The picker's first request carries **no accent** and **`language=en`**, asserted on what is
  sent rather than on what renders.
- Choosing an accent narrows; clearing it broadens again. The control, without which a picker
  that ignored the accent entirely would pass the first test.
- A project that stored `interview_accent` before this change still loads and saves - the key
  is ignored, not an error.
- `ProjectSettings` no longer declares it, and `ui/src/types.ts` no longer declares it. Both,
  because a field removed from one and left in the other is the drift this project has now
  recorded four times.
