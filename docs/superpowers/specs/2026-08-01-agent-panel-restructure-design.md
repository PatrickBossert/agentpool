# The Agent Panel Restructure - Design

**Date:** 2026-08-01
**Status:** Approved for planning

Not a numbered roadmap project. This reshapes where an agent's work lives, which every
remaining roadmap project then builds on: Jordan's coverage role, interview delivery,
Casey's synthesis, and differentials.

## Problem

An agent's work has no single home.

The value chain's editor lives on its own page at `/dashboard/{slug}/value-chain`. Its
outputs are listed in the agent panel on the Dashboard. Its run history is in a third place,
the panel's Status tab. A reviewer told a crew has finished is emailed a link to
`/dashboard/{slug}/reviews`, which is none of those.

The Output tab compounds it by listing **every version of every output type** the crew has
ever produced, each with its own revision, revert and reject controls. Alex's tab is a list
of twelve `value_chain` versions plus a tree, a registry and a summary. Maya's is worse: her
task instructs one key, `interview_scripts`, and she has improvised about twenty suffixed
variants - `_a`, `_c`, `_caf`, `_part2` - each of which `SQLiteStateTool` turns into its own
output type, because it records `output_type=key`. The panel copes today by hiding the whole
`interview_scripts` prefix from that crew's list.

So the tab meant to show what an agent produced shows a filing cabinet, and the agent's
actual editor is on another page.

## Approach

**The Output tab is where you change the artefact. The Status tab is where you see what has
happened to it.**

That sentence decides every placement below, including the ones that could go either way.

### One primary output per agent

Two new per-crew maps, beside the ones the panel already has - `CREW_OUTPUT_EXTRA`,
`CREW_SETUP_OVERRIDE`, `CREW_HIDDEN_OUTPUT_PREFIXES`:

| Map | Purpose |
|---|---|
| `CREW_PRIMARY_OUTPUT` | The one `output_type` this agent's Output tab is for |
| `CREW_OUTPUT_EDITOR` | The bespoke editor component for it |

The Output tab renders the **current version of the primary output**, through its editor. No
version list, no counts, no revert, no thumbnails.

An agent with no declared editor gets a read-only render of the same artefact. That is what
makes this a default rather than a special case: every agent has the structure from the
first day, and editors arrive one at a time.

Declaring a primary states positively what belongs on the tab, where
`CREW_HIDDEN_OUTPUT_PREFIXES` states negatively what does not. The hiding list survives only
for what Status chooses to list.

**Maya's twenty output types are not modelled around.** They are an instruction-following
defect - her task names one key and she invents more - and the fix belongs at source, in the
interview generation work, not in the UI. Her primary is `interview_scripts`; the siblings
land in Status, visible rather than hidden, which is more honest than today's rug. She gets
the **read-only** render in this project, not an editor - Alex's grid is the only editor
built here, and Maya's is the first case that proves the read-only default works.

**PAM is exempt.** Its Output tab is labelled Overview and renders `PamReportView`, not an
artefact with versions - there is no primary output to declare and no editor to give it. It
keeps its existing special case in the tab strip and its own Status branch. Every rule below
is about crews that produce versioned outputs.

**The Chat, Setup and Skills tabs are untouched**, except that Alex's Setup gains a
`CREW_SETUP_OVERRIDE` and Maya's gains the interview instruments.

### What moves to Status

Run history and timestamps, the error detail, the activity event log (all already there),
plus everything leaving the Output tab: the change log, the output summary card - thumbnail
and summary line, "3 segments, 17 activities, 17 contributions" - every non-primary output
type, and **revert to this version**.

Revert belongs in Status because reverting is a fact about history, not an edit.

**Reject and revision requests go with it.** All four - revert, reject, revise, and the
version list itself - act on *a version*. Grouping them keeps the rule stateable in one
sentence. A revision request asks the agent to change something, which is closer to what
Chat does than to what an editor does.

### The value chain page dissolves

Nothing on it is genuinely cross-agent once the interview model is applied:

| Tab today | New home |
|---|---|
| Structure | Alex's `CREW_OUTPUT_EDITOR` - `StructureTab.tsx` moves as-is |
| Setup - brief, standards, documents, questionnaire preferences | Alex's `CREW_SETUP_OVERRIDE` |
| Templates - interview instruments per level | Maya's Setup tab |

Templates settles as Maya's because the instruments are **per-level configuration**: an
interview script is generated for every node by applying its level's instrument, so the
instrument is chosen three times rather than assigned seventy-nine times. Configuration
belongs in Setup; the generated interviews are output and belong in her Output tab. See the
cardinalities recorded in the interview coverage model: activity to script is 1:1, activity
to stakeholders is 1:many with a party.

`/dashboard/{slug}/value-chain` **redirects** to the Dashboard with Alex selected rather
than 404ing, so existing bookmarks and links in already-sent email still land somewhere
sensible.

### The Dashboard preview

`ReviewDialog.tsx`'s `CREW_OUTPUT_TYPE` maps `discovery_mapping` to `value_chain`, the
legacy Mermaid type. `AgentDetailPanel.tsx`'s `MERMAID_OUTPUT_TYPES` includes the same. So
Alex's inline preview still renders a diagram, and once he is re-run - producing no
`value_chain` output at all - it would show nothing.

Both point at `value_chain_model`, and the summary card described above replaces the
thumbnail for it. A structured model has no diagram to draw; a summary line is the honest
equivalent.

The line is **computed client-side from the model already fetched** - counting segments,
activities, contributions and tasks - not a new field on the output row. Nothing needs to
store it, and a count that derives from the artefact cannot go stale against it.

### Links land where the work is

`commit_notify_service.py` builds `{public_url}/dashboard/{slug}/reviews` for all three
notices. They become a link to the agent's Output tab, so an approver arrives at the thing
they were asked to look at rather than a list containing it. `_notify` already has
`crew_name` in scope at the point the link is built.

**The gotcha:** the panel restores its last tab from `localStorage`. An approver whose last
visit ended on Chat would land on Chat no matter what the email said. **The URL wins when
present**, and the saved tab is consulted only when it says nothing:
`/dashboard/{slug}?crew=<crew>&tab=output`.

The Reviews page stays as the cross-crew "what needs me" list, and keeps the activate
control. Only the links change.

---

## Decomposition

`ui/src/components/AgentDetailPanel.tsx` is 1745 lines and this makes Status substantially
bigger. It splits the way `StructureTab` was extracted from `ValueChain.tsx` on the previous
branch:

| File | Responsibility |
|---|---|
| `ui/src/components/AgentOutputTab.tsx` | **Create.** Current primary output, through its editor. |
| `ui/src/components/AgentStatusTab.tsx` | **Create.** Runs, changes, summary card, other outputs, version actions. |
| `ui/src/components/AgentDetailPanel.tsx` | **Modify.** Keeps the tab strip, the shared queries, and the per-crew maps. |
| `ui/src/components/StructureTab.tsx` | **Modify.** Becomes Alex's output editor. |
| `ui/src/components/ReviewDialog.tsx` | **Modify.** `CREW_OUTPUT_TYPE` for `discovery_mapping`. |
| `ui/src/pages/ValueChain.tsx` | **Delete.** Its three tabs redistributed. |
| `ui/src/router.tsx` | **Modify.** The old route redirects. |
| `ui/src/pages/Dashboard.tsx` | **Modify.** Accepts `crew` and `tab` from the URL. |
| `api/services/commit_notify_service.py` | **Modify.** The link carries the crew. |

Without the split the file lands past 2000 lines, and the next change to it is worse than
this one.

`OutputItem` splits along the same seam: version list, thumbnail, revert, reject and revise
go to Status; the editor path does not need it at all.

## Testing

**The split must be lossless.** Every control that exists today exists somewhere afterwards
and still works. Named individually rather than counted, so a control silently dropped is a
failure rather than a gap in a total: revert, reject, revise, the version list, the
thumbnail, the lazy content load.

**Placement:**
- Alex's Output tab renders the grid, not a version list.
- An agent with **no** declared editor renders its primary output read-only - the case that
  proves this is a default and not a special case for one agent.
- The Status tab shows non-primary output types; the Output tab does not.

**Links and routing:**
- A URL naming a crew and tab **beats** the saved tab. A test that only checks the URL works
  would pass while the `localStorage` value silently won, which is the whole defect.
- `/dashboard/{slug}/value-chain` redirects rather than 404s.
- The three notification links carry the crew that the notice is about - asserted per notice,
  because they are built at three call sites.

**Fixture sizing**, carried from the previous two branches: an agent with exactly one output
type cannot distinguish "shows the primary" from "shows everything it has". Any test of the
primary-output rule needs a crew fixture with **at least two** output types, one primary and
one not.

## Prerequisite

`sp-gs-am` has no migrated value chain model, so Alex's Output tab will correctly show the
migrate prompt rather than a grid until `POST /projects/sp-gs-am/value-chain-model/migrate`
has run. Do that first, or the first thing seen after this work will look like a failure.

## Out of scope

Building editors for agents other than Alex - the structure arrives for all, the editors
arrive one at a time. Fixing Maya's output-key sprawl at source, which belongs with the
interview generation work. The capability model - mapping systems and data onto
contributions - which is banked separately. Any change to what the Reviews page shows, as
opposed to what links to it. Roadmap project 4, Jordan's coverage role, which this makes
easier but does not begin.
