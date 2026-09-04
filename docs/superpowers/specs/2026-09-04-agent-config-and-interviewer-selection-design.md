# Per-project agent configuration, and choosing an interviewer

**Date:** 2026-09-04
**Status:** draft for review

## Why - and the diagnosis of finding 1

The first completed interview used the wrong voice and showed no interviewer image. The chain
is broken in three places, each independently:

1. **Avery's voice choice is not persisted anywhere a server can see.** `AverySetupTab` writes
   to `localStorage` under `agentpool-avery-voice-config`. It is per browser, not per project,
   and never leaves the machine that set it.
2. **Nothing writes `voice_config` at session creation.** `InterviewSessionTool` accepts one on
   the session dict and stores it, but no caller supplies it, so the column is `NULL`.
3. **The fallback is hardcoded in a component.** `VoiceInterview.tsx` holds
   `DEFAULT_VOICE_CONFIG = { elevenlabs_voice_id: '21m00Tcm4TlvDq8ikWAM', ... }`. That id is
   ElevenLabs' stock **Rachel - a female voice** - used for an interviewer the setup screen
   describes as male.

So the voice heard was not a fallback for Avery's; it was a hardcoded stranger.

`interviewer_image_url` is empty for the same class of reason: the branding payload carries the
field, and nothing populates it.

## What this builds

**An agent configuration section on every agent's Setup tab.** Name, image, and voice - each
overriding a default rather than replacing it. The defaults are what runs today: the display
names in `agents/identity.py`, and the voice currently used for Avery.

**Voices are chosen from the available ElevenLabs voices**, filtered by regional accent -
Scottish and Irish among them - showing each voice's rate and availability, with a **preview**
played from the API's own `preview_url` rather than synthesised.

**Only interviewer voices are used for now.** Every agent gets the settings because the shape is
the same and the alternative is a special case; nothing but the interviewers reads the voice yet.

**Laura Nelson joins the discovery interviews team** as a second, female interviewer.

**Taylor chooses who interviews each stakeholder** - always male, always female, or random -
from a project setting.

## Why this is cheap, structurally

`agents/identity.py` already separates a **permanent `agent_id`** from a **mutable display
name**, and that decision was made for exactly this. The configuration keys on `agent_id`; the
name, image and voice are data. Renaming Avery, or running a project where he is called
something else, moves no identity and breaks no history.

The same decision is why the mail seam already resolves a correspondent by role rather than by
name, and why an agent can be re-imaged without touching what it produced.

## Where the configuration lives

**A project table, `project_agent_config`**, keyed on `(project_id, agent_id)`, holding
`display_name`, `image_url`, `voice_id`, `language`, `country_code`. Absent row, or absent
column, means the default.

**Not `localStorage`.** The current arrangement is a defect, not a pattern to extend: settings
that never reach the server cannot reach an interview, which is finding 1's first link.

**Not `config_json`.** This is per agent, not per project-wide setting, and it wants a row per
agent rather than a nested blob.

## The session records the voice it used

`interview_sessions.voice_config` is **stamped at session creation** from the resolved
configuration, and the interview reads the session's copy, never the project's current one.

This is the rule sp57 learned the expensive way with
`client_documents.knowledge_collection`: **an address that is re-derived is an address that can
move underneath the thing it points at.** A project's interviewer voice may change between a
session being issued and the interview being taken; the transcript should say which voice
actually conducted it, and a re-derivation cannot.

It also gives Taylor's male/female choice somewhere to be recorded, since that choice is made
per stakeholder at invite time.

## Choosing the interviewer

A project setting - **always male, always female, or random** - read by Taylor when he issues an
invite. The chosen interviewer is resolved to a voice and stamped on the session.

**Random must be recorded, not re-rolled.** If the assignment lives only in a setting, a session
re-read later gets a different interviewer, and a participant who returns to a link hears a
different person. Stamping it at creation is what makes the choice stable - the same argument as
the voice itself.

Out of scope: matching interviewer to stakeholder on any attribute other than this setting.

## Laura Nelson

A new entry in `AGENT_IDENTITY` with her own permanent `agent_id`, registered as a second
interviewer on `discovery_interviews`. She needs a tier in `agents/model_registry.py` -
**`fast`, matching Avery**, since it is the same job.

Her default voice is a female ElevenLabs voice; Avery's default should be corrected to a male
one at the same time, because it currently is not.

## The voices list - two endpoints, not one

Established by calling the API on 4 September rather than assumed. **There are two listings and
they answer different questions.**

| | `GET /v1/voices` | `GET /v1/shared-voices` |
|---|---|---|
| What it holds | the 32 voices **in this account** | the whole Voice Library |
| Accents present | british, american, australian, new zealand, scottish | those plus **irish** and the rest |
| Rate | `available_for_tiers`, **empty on every voice** | **`rate`** and `fiat_rate` |
| Filtering | none | `accent`, `gender`, `language`, `use_case` |
| Preview | `preview_url` | `preview_url` |

**The premium-rate information is only on `shared-voices`.** The account listing carries
`available_for_tiers`, and it is `[]` on all 32, so a picker built on `/v1/voices` alone can
show availability and accent but cannot show what a voice costs.

So the door proxies **both**: the account list for what is ready to use, and the library for
finding something new. They are not interchangeable, and a picker offering only one of them is
either missing Irish or missing the rate.

**Adding a library voice copies it into the account.** That is a write, not a read, and it
belongs behind the same authority as any other project configuration change - not on the
preview path.

### Three things this makes free

**`labels.gender` is `male`/`female`/`neutral` on the API's own metadata.** Taylor's
always-male/always-female selection is therefore a filter, **not a hand-maintained list of which
voice is which sex.** A curated list would be a fifth declaration of voice facts, which is
exactly what this branch exists to stop.

**`accent` is a first-class filter**, so Scottish and Irish are a query parameter rather than
curation.

**`preview_url` is a static audio URL on both endpoints**, so preview needs no synthesis call.
The earlier plan to speak a sample line through `synthesise` was more expensive, slower, and
spent characters for something the API already hosts.

### Egress

This is a new outbound path. CLAUDE.md lists ElevenLabs as an ungated reach; this widens what is
sent there from interview text to a voice listing request, which carries **no client material**.
The row must say so rather than leaving the table stale.

*Verified on the live account, 4 September:* it already holds a professional Scottish voice -
"Alba Mac - Animated Scottish", female, conversational - so the picker has something real to
show without touching the library.

## Testing

- A project with no configuration resolves every default, and the interview runs exactly as it
  does today. This is the control; without it, a change that broke resolution entirely would
  pass the tests below.
- A configured voice reaches `voice_config` on the session, and the interview speaks with it.
  **Assert the voice id that reaches the synthesis call**, not the value in the table.
- Changing the project's configuration after a session is created does **not** change that
  session's voice.
- `random` is stamped once: reading the session twice returns the same interviewer.
- `always_female` never yields Avery, and `always_male` never yields Laura.
- A voice preview plays the API's `preview_url` and **makes no synthesis call at all** - assert
  that nothing reaches text-to-speech, since the cheap implementation and the expensive one look
  identical to a participant.
- The picker's male/female filter is applied to the API's `labels.gender`, not to a list in this
  codebase. A curated list would be a fifth declaration of voice facts.
- Adding a library voice to the account is a write and takes the configuration door's authority,
  not the preview path's.

## Out of scope

Per-agent behaviour settings beyond name, image and voice - Avery's existing interviewing
preferences stay where they are for now, though they have the same localStorage defect and
should follow. Voice cloning. Matching interviewer to stakeholder by any attribute other than
the male/female/random setting.
