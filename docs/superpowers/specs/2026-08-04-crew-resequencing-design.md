# Crew Re-sequencing - Design

**Date:** 2026-08-04
**Status:** Approved for planning

Re-orders everything downstream of the interviews so each crew consumes what the one before
it produced, and moves two agents to the crews whose work they actually do.

## The flow, as it should run

| # | Crew | Agents | Produces |
|---|---|---|---|
| 1 | `discovery_mapping` | Alex | the value chain |
| 2 | `assessment_design` | Maya | interview scripts, one per node |
| 3 | `stakeholder_management` | Jordan | assignments and coverage |
| 4 | `discovery_interviews` | Taylor, Avery, **Casey** | transcripts, synthesis, **themes** |
| 5 | `value_design` | **Morgan**, VP Generator, Portfolio Manager | value propositions, portfolio with ranking criteria |
| 6 | `capabilities` *(was `architecture`)* | Enterprise Architect, Initiative Identifier | as-is capabilities, uplift initiatives |
| 7 | `requirements` *(was `discovery`)* | Sam, Riley | requirements and complexity, method, cost |
| 8 | `delivery` | Roadmap Generator, Visual Illustrator | illustrated roadmap |
| 9 | `business_plan` | Business Plan Generator | the roll-up |

Positions 1-3 are unchanged. Everything from 4 onwards moves.

## What changes, and why

### Casey produces themes, not only synthesis

Two kinds, and the distinction is the point:

- **Horizontal** - across the value chain, where digital transformation could improve
  efficiency or effectiveness.
- **Vertical** - within a discipline, where maturity could be raised: governance, data, or a
  specific support service.

**Every theme cites the interview sections that evidence it.** That is what makes a value
proposition traceable back to something a named person actually said, and it is the whole
reason the downstream chain can be trusted.

### Morgan moves from Discovery to Value Design

The Value Lever Analyst identifies where value can be created. That is the input to a value
proposition, not to a requirement - and Morgan currently sits in a crew that runs **before**
the interviews have produced anything to analyse. Moving Morgan into `value_design` puts the
lever analysis next to the propositions it feeds, after the evidence exists.

### `discovery` becomes `requirements`, and runs seventh

Sam and Riley enumerate requirements against **initiatives**, which do not exist until the
Capabilities crew has produced them. A crew called *discovery* that runs after the discovery
interviews and before value design was in the wrong place under a misleading name; it now
runs where its inputs are, called what it does.

Its scope is stated: **data, people, process, decision-flow, application and technology**
requirements, plus an assessment of complexity, method and likely cost per initiative.

### `architecture` becomes `capabilities`

The crew compiles **as-is capabilities** and derives *"we need to be able to…"* uplift
initiatives from the gap between those and each value proposition. That is capability
analysis; naming it architecture invites an artefact nobody asked for.

### Renaming a crew key is a migration, not a rename

`crew_runs.crew_name` holds 13 rows for this project alone, and `approval_commits` and
`crew_submissions` carry the same column. Renaming `architecture` to `capabilities` in code
without migrating those rows orphans every historical run: it belongs to a crew that no
longer exists, so it vanishes from the board rather than reading as history.

Both renames migrate the stored names in the same change. **Display labels alone are not
enough** - a key that says `discovery` for a crew running seventh is exactly the stale name
this exercise exists to remove.

## The prerequisite nobody can skip

**Themes cannot cite sections durably today.** Three defects, all the same shape as ones
already fixed in the value chain:

1. **Scripts are keyed by `node_label`.** The top-level key is
   `"GS UK Portfolio L0 Interview"`. Rename the node and the script is orphaned.
2. **Sections carry no id** - only a `title`. A theme citing "S1: Strategic Mandate" cites a
   string that Maya may rewrite on her next run.
3. **Question ids collide across scripts.** They are `L0.S1.Q1` - level, section, question -
   with no node in them. The current file holds one L0 and one L1 script and shows 33 distinct
   ids out of 33, which is a property of the sample, not the scheme: the chain has **17 L2
   nodes**, and every one of their scripts would emit `L2.S1.Q1`.

So a citation must be `node_id → section_id → question_id`, and the first is not stored, the
second does not exist, and the third is not unique. **This is fixed before Casey cites
anything**, or the referential integrity is a claim rather than a fact - and a value
proposition traced to a question that three nodes also claim is worse than one with no
citation at all, because it looks sound.

## Cross-checking the bios

`AGENT_ROLE` and `AGENT_SKILLS` are read by the panel and describe what each agent does. Three
are now wrong:

- **Value Lever Analyst** - described as working from "discovery findings"; it now works from
  Casey's themes, which are evidence-linked rather than impressionistic.
- **Enterprise Architect / Initiative Identifier** - described in architecture terms; they now
  compile as-is capabilities and derive uplift initiatives from a value proposition gap.
- **Synthesis Analyst** - describes synthesis only, and now owns the horizontal and vertical
  themes and their citations.

**Requirements Capture and Requirements Analyst keep their bios** - their work is unchanged;
only when they run has moved. Stating that explicitly matters: a re-sequencing that quietly
rewrote every bio would lose the distinction between "this agent's job changed" and "this
agent's turn moved".

## What this does not change

The value chain, the interview instruments, stakeholder coverage, or the milestone schedule.
No agent is added or removed; two move crews and two crews are renamed.

## Testing

**Sequence and membership:**
- The frontend `CREW_ORDER`, the frontend `CREW_AGENT_NAMES` and the backend
  `_CREW_AGENT_NAMES` agree. They are three declarations of one fact and have drifted before;
  a test that reads one and asserts against a literal proves nothing about the other two.
- Morgan appears in `value_design` and in no other crew. Asserting only the first would pass
  while the agent ran twice.
- Every crew in `CREW_ORDER` has at least one agent, and every agent belongs to exactly one
  crew.

**The renames:**
- A `crew_runs` row written as `architecture` reads as `capabilities` after migration, and its
  run history still appears on the board. A test asserting only that new rows use the new name
  would pass while every historical run vanished.
- No code path still writes the old names.

**Citations:**
- Two scripts at the same level produce no colliding question ids. The current fixture cannot
  fail this, so the test needs two nodes at one level.
- A section is addressable by an id that survives Maya rewriting its title.
- A theme citing a section resolves to exactly one section, in one script, on one node.

**Bios:**
- The three changed roles no longer describe the work they have stopped doing - asserted on
  the phrase that is now wrong, not on the presence of a new one, since adding a sentence
  while leaving the stale one is the likely half-fix.

## Out of scope

The content of Casey's theme analysis, the wording of value propositions, and how complexity
or cost are estimated - all agent instructions rather than structure. Jordan's coverage work,
which is planned separately. Taylor's status view.
