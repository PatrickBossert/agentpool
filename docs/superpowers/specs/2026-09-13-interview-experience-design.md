# The last three things a participant meets

**Date:** 2026-09-13
**Status:** approved by Patrick, ready to plan

## Why

Patrick walked the participant path on 4 September - 39 minutes, 59 answers, a 23,503-character
transcript - and listed nine problems. Six are fixed. These are the three he would meet again on
the next interview, and every engagement runs through them.

## 7. Every field is open for editing

The final review and correction step hides each answer's edit behind a pencil that is
`text-gray-300` until hovered. Patrick's decision: **leave all fields open for editing** rather
than requiring a pencil to be found and clicked.

A participant correcting their own words is the last chance to fix what the recogniser heard.
An affordance nobody notices is an affordance that does not exist.

## 8. "Email this to me" is replaced by a note

The checkbox posts to `/interviews/{token}/email-transcript` and the transcript does not arrive.
Patrick's decision: **replace it with a note** - for confidentiality the report will not be
emailed, and it can be copied with the **[COPY]** button.

This is consistent with the deployment rather than a retreat. `dev_mode` holds project mail,
`FROM_EMAIL` names a domain Resend has not verified, and the transcript is client material.
**It is also the only path in the product where the recipient triggered the action and is told
it worked** - `{"sent": true}` - which is the specific defect being removed.

## 9. The recogniser is told the project's own words

**The premise of the original finding was wrong, and the correction is the substance of this
task.** The interview page uses the browser's Web Speech API - `webkitSpeechRecognition` - which
has no vocabulary or keyword support whatever. "Iberdrola" and "ISS" cannot be boosted on the
path a participant actually walks.

Deepgram was built and never connected. `GET /api/interviews/{session_token}/deepgram-token`
exists, `generate_deepgram_token` works, and **nothing in `ui/src` has ever called it** - the
only reference anywhere is a line on the Architecture page describing it as the access method.
So the documentation, the auditor-facing page and CLAUDE.md's egress material all describe a
path no participant has taken.

**Patrick's decision: finish it.** The page fetches the token from the door that exists, streams
to Deepgram, and passes **keyterms drawn from the project's own material** - the value chain
registry and the interview scripts - so the client's name, its parent and its contractors are
boosted rather than guessed.

### Where the terms come from, and where they must not

From the **project**: `value_chain_ledger` labels and the text of that project's
`interview_scripts`. Never a list in this repository. That is the rule the voice work arrived at
the hard way - five declarations of Avery's voice, two of them wrong - and a vocabulary of client
names is the same shape with a worse failure mode.

### What this makes true that is currently false

CLAUDE.md's known-issues entry says Deepgram is "used in secure mode by decision, both being
streamed with no content retention". That has been a description of an intention. It becomes a
description of the system.

### What it does not change

Deepgram remains an ungated reach - one of the five paths that send material off-premises with
no mode question asked. This connects it; it does not narrow it. The entry in `agents/egress.py`
must say what actually leaves now, which is a participant's speech rather than nothing.

## Testing

- Every answer in the review step is editable without a hover or a click to reveal, asserted by
  querying the control rather than by snapshot.
- The email checkbox is gone and nothing posts to `email-transcript`; the note names the COPY
  button. Assert the **absence of the request**, not the absence of the checkbox - the defect
  was a request that succeeded and delivered nothing.
- The keyterms sent to Deepgram come from the project's registry and scripts. Assert what is
  **sent on the socket**, not what the helper returns: a helper can be perfect and unused, which
  is precisely how this path came to exist.
- A project with no registry and no scripts connects with no keyterms rather than failing. The
  control, without which a fix that never connected would pass.
- The Web Speech fallback survives for a browser that cannot reach Deepgram, or the interview
  ends when the token door 503s on a deployment with no key.
