# Interview flow - findings from the first completed interview

**Date:** 2026-09-04
**Status:** observations and decisions, recorded for action

The first interview this system has ever completed ran on 4 September against `sp-gs-am`,
session 1, script SC-001, synthetic stakeholder Alistair Groves. **39 minutes, 59 answers, a
23,503-character transcript.** The path works end to end; what follows is what was wrong with
it, observed by Patrick walking it as the participant.

Numbered as reported. Decisions are his; my notes on cause or scope are marked.

---

## 1. The interviewer had no image, and the wrong voice

The voice was the **default ElevenLabs voice**, not the one previously selected for Avery, and
not a project-specific voice. No interviewer image. Name, voice and image should all be
project-specific.

*Observed in the data before the walkthrough:* `interview_sessions.voice_config` was `NULL`, and
the branding payload carried `interviewer_name: "Avery Singh"` with `interviewer_image_url: ""`.
So the name resolves and nothing else does. Whatever assigns a voice does not run at session
creation.

## 2. The introduction is far too long

Microphone check, then interview setup, then the welcome, then the framing - **burdensome**
before a single question.

**Decisions:** drop the interview intro entirely, it is covered by the welcome. The framing
should read **only its first paragraph** - the `positioning` field, shown in italics in the
script viewer - not the full `context_setting` list.

## 3. Silence did not re-prompt

Not speaking, with only background noise, **moved to the next question** instead of re-prompting
the current one. A participant who pauses to think loses the question.

## 4. The progress bar reached 100% at the last question

Misleading: several follow-ups still remained. **It should reach 100% only at closing.**

## 5. The synthesis check came from the script

It was read from `synthesis_check.synthesis_prompt` - written by Maya at design time, before
anybody had said anything.

**Decision:** a synthesis check must be a check of **what was actually said**. Maya must not
pre-suppose the output of the interview. Drop it from interview execution now, and **eventually
from the questionnaire design** - the Maya change is later, not now.

## 6. A second synthesis, generated on the fly, missed the point

After the scripted synthesis check came another, not in the script, so synthesised live. It
**missed the main theme** - poor data means risk means an unmanageable portfolio over the term
of the investment - and instead offered sequencing options, after Patrick had said the projects
must run in parallel.

**Decision: skip synthesis entirely.** Comment it out in the code as **withdrawn until further
notice**, and go straight from the questions to peer referral and closing.

*My note:* dynamic synthesis is the riskiest thing in the flow - it speaks with authority about
what a participant meant, in front of that participant, with no chance to check it first.

## 7. The edit pencils in the final review are not visible enough

**Decision:** leave **all fields open for editing** in the review and correction step, rather
than requiring a pencil to be found and clicked.

## 8. "Email this to me" did not work

**Decision:** replace it with a note - for confidentiality reasons the report will not be
emailed, but it can be copied with the **[COPY]** button.

*My note:* this is consistent with the existing arrangement rather than a retreat - `dev_mode`
holds project mail, the sender domain is unverified, and the transcript is client material.

## 9. Speech-to-text did not recognise key words

**"Iberdrola"** and **"ISS"** were not recognised, and the interviewer used both frequently. It
reads badly to a participant hearing their own organisation's name mangled back at them.

*My note:* Deepgram supports keyword boosting and custom vocabulary; the terms are available -
the client name, the parent company and the contractor all appear in the project's own value
chain registry and scripts.

---

## Grouping, for sequencing

| Group | Items | Nature |
|---|---|---|
| Identity and voice | 1 | Configuration - per project, and nothing populates it |
| Flow and pacing | 2, 3, 4 | Front-end behaviour, independently fixable |
| Synthesis | 5, 6 | **Design decision** - withdraw now, Maya's script change later |
| Review step | 7, 8 | Front-end, small |
| Recognition | 9 | Deepgram configuration, needs a term source |

**Nothing here blocks anything else.** These are all downstream of a working pipeline, so they
can be taken in any order, and none of them touches the two paused review branches.
