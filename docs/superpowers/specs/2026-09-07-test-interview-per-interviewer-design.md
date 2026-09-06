# A test interview per interviewer, and a picker that opens on the right voices

**Date:** 2026-09-07
**Status:** approved, ready to plan

## Why

sp62 added a second interviewer, Laura Nelson, and left the rehearsal button where it had
always been: on Avery's Setup tab, opening a dialog that is Avery's in six places. So the
product now has two interviewers and can only rehearse one of them.

Patrick also asked that the voice picker show **male voices for Avery and female voices for
Laura**, which is the second half of the same problem - choosing a voice for an interviewer
currently means scrolling past every voice for the other one.

## What this builds

1. **A Test interview button on each interviewer's configuration section.**
2. **A voice picker that opens filtered to that interviewer's sex**, as a pre-set default
   rather than a lock.
3. **A rehearsal dialog that is nobody's in particular** - it greets you as, and shows the
   face of, whichever interviewer it was opened for.
4. **A portrait fallback**, because Laura has no photograph and would otherwise render broken.

## The server already anticipated most of this

`POST /api/interviews/test/speak` takes `agent_id` and resolves that agent's voice and
synthesis model through `resolve_agent_config`. Its own comment says why the work stops
there: *"It defaults to the interviewer because that is whose rehearsal button exists today;
Laura's setup tab passes her own id rather than needing a second door."*

**No new door.** This is a frontend feature with two fields added to an existing response.

## Who is an interviewer - already declared, do not restate

`interviewer_agent_ids()` in `api/services/interviewer_selection.py` answers *"the agents that
can conduct an interview"*, and its rule is **an identity with a `voice_id`**. That is the one
place the question is answered, and the button's audience must come from it rather than from a
list in TypeScript - the same rule that stopped the voice-locale table being restated.

So `GET /projects/{slug}/agents/{agent_id}/config` gains **`is_interviewer: bool`**, derived
from that function. The section renders the button when it is true.

**Deliberately not a new concept.** An agent that can speak is an agent that can rehearse an
interview, and that is what the existing predicate already means. If a non-interviewing agent
is ever given a voice, this button follows it - and the fix then is to give
`interviewer_agent_ids()` a better rule, in the one place, rather than to add a second list
here.

## The sex filter, and the decision it must not reverse

Patrick's request is that Avery's picker shows male voices and Laura's female. The obvious
implementation is a table mapping agents to sexes, and **`interviewer_selection.py` refuses
that in writing:**

> Sex comes from ElevenLabs' `labels.gender` on the resolved voice, not from here, "because
> the sex is a property of the *voice* and the voice is a per-project setting - a project that
> gives Avery a female voice has said something, and a table in this repository mapping agents
> to sexes would contradict it while looking authoritative."

`agents/identity.py` says the same of Laura: her identity "names neither her voice nor her
sex, both of which are the mutable half this file exists" to separate.

**So the filter is derived from the voice the interviewer already has.** Avery's resolved voice
is Daniel, whose `labels.gender` is `male`; Laura's is Alice, `female`. The requested behaviour
falls out, and no new authority is created.

`GET .../agents/{agent_id}/config` gains **`voice_sex: "male" | "female" | null`**, answered by
`ask_voice_sex` - the same function `always_male`/`always_female` uses, so the picker and the
crew cannot disagree about what a voice is.

### Three properties this must have

**It is a default, not a lock.** The filter is pre-set and clearable. A consultant who wants to
give Laura a male voice is making a legitimate choice - the design says a project that does so
"has said something" - and the picker must not be the thing that forbids it.

**An unanswerable lookup opens unfiltered, never empty.** `ask_voice_sex` distinguishes three
cases deliberately: a voice with a sex, a voice the provider gave no sex for, and *no voice at
all* (`answered=True, label=None` - "an agent with no voice has no sex, which is a fact rather
than an outage"). Only the first pre-sets a filter. **Showing nothing because a lookup failed
is the worst available outcome**, since it is indistinguishable from an account with no voices.

**It costs no synthesis and no extra round trip per keystroke.** The sex is resolved once,
server-side, with the rest of the configuration.

## The dialog stops being Avery's

`TestInterviewDialog.tsx` hardcodes `AVERY_HIRES` in five renders and *"Hi, I'm Avery — and
I'll be your interviewer today"* in a sixth. Opening it for Laura without touching that would
greet a consultant as Avery, in Laura's voice.

**That is finding 1 of the interview walkthrough, exactly** - a voice and a face that disagree
with the person named - which is the defect this whole line of work started from. The dialog
takes an `agentId`, and reads `display_name` and `image_url` from the resolved configuration it
already has access to.

A consequence worth naming: renaming an agent in `agents/identity.py`, or giving one a
per-project name, now changes the rehearsal too. That is the point of keying on `agent_id`.

## Laura has no photograph

`ui/public/agents/laura-nelson.jpg` does not exist, and her resolved `image_url` is `null`.

**A missing portrait renders as initials on a plain background**, derived from the display
name - not a broken image, and not Avery's face standing in for hers. The fallback is a
property of the component rather than of Laura, so it covers the fourteen other agents that
have no per-project image either.

*A real portrait for Laura is wanted and is not this task* - it needs an asset, not code, and
the fallback is what makes her usable in the meantime rather than blocked on one.

## Testing

- **The button appears for exactly the agents the server calls interviewers**, and the test
  asserts against a payload rather than a list in the test file - a hardcoded pair of ids would
  pass against a component that ignored `is_interviewer` entirely.
- **The picker opens filtered to the interviewer's sex**, and the assertion is on the request
  the picker *sends*, not on what it renders. A filter applied only to the rendered list is a
  different feature that looks identical in a screenshot.
- **Clearing the filter shows voices of both sexes** - the control. Without it, a picker that
  hardcoded a permanent filter would pass the test above.
- **A voice whose sex the provider will not give opens unfiltered**, and a *distinct* test
  covers an agent with no voice at all. `ask_voice_sex` answers those two cases differently on
  purpose, and one test cannot witness both.
- **The dialog greets you as the interviewer it was opened for**, asserted for Laura
  specifically - Avery's name is the default everywhere and a test using him would pass against
  the hardcoding this removes.
- **An agent with no image renders initials, not a broken image**, and not another agent's.

## Out of scope

A portrait asset for Laura. Changing who Taylor picks or how. Any voice-sex concept stored in
this repository. Rehearsing a crew agent that is not an interviewer.
