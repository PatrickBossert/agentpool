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

## The first upload becomes the default, when there is no default

**Decided by Patrick, 7 September.** Portraits are per project. But an agent with **no default
portrait at all** - Laura today, and every future agent before somebody draws one - should not
need the same photograph uploaded onto every engagement in turn. So **the first portrait
uploaded for such an agent is promoted to the deployment's default**, and every later project
inherits it.

### Four levels, and the precedence is stated once

| | Where it lives | Set by |
|---|---|---|
| 1. Project override | `projects/<slug>/assets/agents/<agent_id>.<ext>` | uploading on that project |
| 2. Promoted default | deployment assets, recorded in `system.db` | the first upload for an agent with no default |
| 3. Built-in asset | `ui/public/agents/<name>.jpg`, shipped in the repository | whoever added the agent |
| 4. Initials | nothing on disk | `AgentAvatar` |

First match wins, and **the promotion only ever fills level 2** - it never overwrites a built-in
asset and never overwrites itself. "First" means first, not latest: once a default exists, later
uploads stay project overrides. That is what makes the rule predictable rather than a race in
which the most recent engagement silently re-faces every other one.

### It is claimed atomically, not checked and then written

Two projects uploading at once for a faceless agent must not both promote. The claim is an
`INSERT OR IGNORE` keyed on `agent_id`, which is the pattern
`register_project_if_unregistered` already uses for exactly this shape - check-then-write has a
window, and the window here is two clients' portraits racing.

### It is recorded, not inferred from the filesystem

`agent_default_images` in `system.db` holds `agent_id` (primary key), the stored extension, the
slug it was promoted from, and when. Provenance matters more here than for an ordinary asset:
this is the one write in the product where **one engagement's upload changes what a different
client's engagement displays**, and "which project did this face come from" must be answerable
without reading file timestamps.

`system.db` takes **no `_SCHEMA_VERSION` bump** - `init_system_db` is idempotent, has no version
gate, and runs on every system connection. CLAUDE.md states this rule and states that it is
inverted from the project-database rule; this is a system table.

### It is served from its own door, not from the project it came from

`GET /api/agents/{agent_id}/image`, **unauthenticated**, like the branding image and for the
same reason: the interview page has no login. Serving a promoted default from
`/api/projects/<origin-slug>/agents/...` would tie every project's rendering to the continued
existence of whichever engagement happened to upload first, and would leak that slug into the
markup of unrelated clients.

### What this deliberately accepts

**Whoever uploads first decides that agent's face for the deployment.** That is the instruction,
and it is safe for a persona portrait in a way it would not be for client material - but it is
the only place in this product where an upload on one engagement is visible on another, so it is
written down rather than left to be discovered. There is no promotion for any other asset, and
none for an agent that already has a face.

A consequence to expect rather than diagnose: replacing a promoted default is not an upload, it
is a deletion of the recorded row. No door does that yet, deliberately - `DELETE
/api/agents/{agent_id}/image` is the obvious shape when somebody wants it, and it is
sysadmin-tier work because it changes every engagement at once.

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

---

# Separating agent setup from crew setup

**Decided by Patrick, 7 September**, after the Setup pane was measured at 86px holding 3364px
of content. The height was a layout bug and is fixed; the 3364px is not a bug, it is four full
agent configurations stacked under a heading that also holds the crew's own settings.

## The distinction, and why it is real

| | Keyed on | Answers | Changed |
|---|---|---|---|
| **Agent** | `(project_id, agent_id)` | who this person is - name, face, voice, synthesis model, and any options peculiar to that agent | once, at the start |
| **Crew** | project and crew | what this crew should do on this engagement | repeatedly, during delivery |

Two objects, two keys, two clocks. Stacking the rarely-touched one above the frequently-touched
one means scrolling past four portraits to reach a brief.

**The code already separates them and the tab does not.** `CrewSetupSections` renders *bespoke*
agent configuration - three of eighteen agents have one - and `CrewAgentConfiguration` renders
name, image, voice and model for **all** of them. Their docstrings argue for the split; the tab
concatenates the result.

**And the current split is already inconsistent.** `CREW_SETUP_OVERRIDE` replaces the Setup tab
wholesale for three crews, with `PamSetupTab`, `AlexSetupTab` and `MayaSetupTab` - components
named after *agents*, configuring agents, occupying a crew's tab. So "Setup" today holds crew
metadata, three agent panels presented as crew settings, and every agent's universal
configuration. Three different things under one heading, which is why no arrangement of it
scrolls well: it is not one topic.

## What this builds

**A new `Agents` tab** on the detail panel, between Setup and Skills. It holds an agent selector
for the crew's agents and, for the selected one, everything agent-scoped:

- the universal configuration - display name, image, voice, synthesis model
- that agent's bespoke section, if it has one (`AGENT_SETUP_SECTION`)
- the rehearsal button, for agents that can conduct an interview

**Setup keeps crew configuration only** - the crew's note, reads and produces, and any genuinely
crew-level settings.

**The three overrides move to the Agents tab**, beside the agent they are named after. Alex's
discovery brief sits under Alex. This is what makes the split consistent: everything
agent-scoped in one place whatever its shape, rather than a rule about which shapes count.

*The consequence to accept:* a crew's Setup tab may now be metadata alone. That is honest -
those crews have no crew-level configuration, and the previous arrangement concealed it by
filling the space with agent panels.

## Three traps in adding a tab to this panel

Named because each is a silent failure, and the panel restates its tab list in three places.

**The list is written out three times** - the `Tab` union, the `isTab` guard, and the
saved-tab restore - plus the rendered tab array and the mount latch. Five sites, and a new tab
missing from the guard or the restore does not error: it falls back to `output`, so the tab
works until the user reloads and then silently forgets where they were. **Derive the guard and
the restore from one list** rather than adding a sixth restatement.

**The tab needs its own mount latch.** Setup renders `hidden` rather than unmounted, and
`setSetupOpened` exists so that opening a panel and closing it again asks the server for
nothing. An Agents tab without the same latch fetches every agent's configuration for a tab
nobody opened - which is the defect sp62 found and fixed for Setup, arriving in the tab that
holds four times as many requests.

**The selector must not re-fetch on every switch.** Selecting an agent changes which block is
shown, not which data exists; the configurations are already keyed by agent in the query cache.

## Testing

- The Agents tab survives a reload - asserted through the **saved-tab restore**, not by
  rendering it once. A tab absent from the guard renders correctly and forgets itself.
- Opening a panel on Output asks for **no** agent configuration, and opening Agents asks for it.
  The control for the latch, and the property sp62 had to fix once already.
- The tab shows the agent clicked in the carousel, not always the first.
- Setup no longer renders any agent configuration, asserted by its **absence** - a test that
  only checks the Agents tab has it would pass with both showing it.
- An agent with a bespoke section shows it under Agents, and its crew's Setup tab does not.

---

# Where a panel belongs: the rename test

**Decided by Patrick, 7 September**, after using the tabs. The Task 6 split put six panels on
the Agents tab because their components are named after agents. Reading their contents, the
naming was the only agent-ish thing about most of them.

## The test

**If this agent were renamed or replaced, would this content move with them?**

Avery's interviewing style would - it is how *he* conducts an interview. A project's milestone
schedule would not, and neither would its research brief. `PamSetupTab`, `AlexSetupTab` and
`MayaSetupTab` are named after the agent that *reads* the configuration, which made
configuration *for* an agent and configuration *of* an agent look like the same thing.

## Where each panel goes

| Panel | Content | Tab |
|---|---|---|
| Taylor | stakeholder list, counts, CSV import | **Status** |
| Taylor | Interview Invite Rules | **Setup** |
| Avery | interviewing behaviour - style, depth, persistence, timing | **Agents** (unchanged) |
| Alex | research brief, links, source documents, project context, standards | **Setup** |
| Maya | disciplines editor | **Setup** |
| Maya | interview programme overview, section structure, design features | **Status** |
| Pam | project start, duration, milestones, Gantt, non-working periods | **Setup** |
| Pam | overdue / upcoming / completed stats, interview completion tracker | **Status** |
| Jordan | stakeholder-to-value-chain-node mapping | **Setup** |

Afterwards each tab means one thing: **Agents** is who the agent is and how it behaves,
**Setup** is how the engagement is configured, **Status** is what the engagement is doing.

**The Agents tab becomes thin, and that is the correct outcome** rather than a loss. What is
left is the only content that is genuinely about the agent instead of about the engagement.

## Three traps in moving them

**The deep links move for the second time.** `router.tsx`'s `AssignmentRedirect` was corrected
from `tab=setup` to `tab=agents` during Task 6 and its comment explains why; Jordan's mapping
now returns to Setup, so the link and the comment both change again. `Runs.tsx` carries the
same link. A link that lands on the right crew and the wrong tab fails silently - it looks
like a working navigation that simply does not hold what was asked for.

**Pam's panel splits across two tabs and must not split its data.** The schedule editor and the
milestone statistics read the same milestones. Two components sharing one query key is right;
two queries is a second fetch and two answers that can disagree while one of them is stale.

**The mount latch follows the content, not the tab.** Task 6 latched the Agents tab because it
fetches configuration. Moving fetching content to Status and Setup moves the cost with it -
whichever tab now pays for a query needs the latch, or a panel opened on Output fetches a
schedule nobody asked for.

## Testing

- Each moved section is asserted **present on its new tab and absent from its old one**. Absence
  is the half that fails silently: a section rendered on both tabs satisfies every "is it there"
  assertion.
- The deep links are driven to the tab they now name, not merely checked for a string.
- One test per tab that it holds nothing belonging to another - the classification stated as a
  property rather than as a comment, so a seventh panel added later has something to fail.
