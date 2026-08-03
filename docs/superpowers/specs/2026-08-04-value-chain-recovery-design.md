# Value Chain Recovery - Design

**Date:** 2026-08-04
**Status:** Approved for planning

Recovers the three-chain structure lost in Alex's run 14, corrects the party model, and makes
the rules that were broken enforceable rather than merely instructed.

## Problem

Run 14 rebuilt the value chain from scratch and re-conceived L1 from **which value chain** to
**which process stage**. One decision, five consequences, all confirmed against the files:

| | v1 (migrated) | v2 (run 14) |
|---|---|---|
| L1 | Property, Fleet, Support - three chains | Five process stages |
| Activities | 17, columns 10-60, no collisions | 24, one 5-way collision |
| Fleet | 6 activities, 20 tasks | 2 activities, 5 tasks |
| Multi-party activities | 0 of 17 | 12 of 24, **5 split across columns** |

**Every stable ID that appears in both was reused for a different activity - 14 of 14.**
`2.1` is *Fleet Strategy & Policy Setting* in v1 and *Multi-Year Work Packaging* in v2. The
registry was rewritten as a fresh ledger of 77 entries, all `active: true`, nothing retired -
`DeriveRegistryTool` diffs against the latest *versioned* registry, and this was `_v1`, so
there was nothing to diff against.

### The party model is wrong in both versions

`value_chain_summary_v12.json`, an earlier surviving output, records it correctly:

```
"property_maintainer": "ISS (FM subcontractor)",
"fleet_maintainer":    "DXI (Fleet maintenance subcontractor)",
```

v1 then labels its fleet chain *"Custodian: GS UK · Maintainer: ISS"* while attributing
`2.5 Fleet Maintenance Delivery (ISS)` to the party `partnerDXI` - the label and the party
disagree inside one activity. v2 attributes fleet maintenance to ISS outright. **ISS does not
maintain fleet.** The fact was captured once and lost twice.

### Why alignment failed

`column` lives on the **contribution**, not the activity, so nothing requires two parties
doing one activity to share a position. Alex used the offset to express "GS UK specifies, then
ISS executes" *within* one activity, which is why `2.4` staggers at GS UK 40 / ISS 30.

---

## Decisions taken

Settled before this design and not revisited here:

- **No alpha prefix.** L1 is a number denoting the value chain. `n.n.n` throughout, as
  originally planned.
- **Process stages get no numbering and no headings.** Plan → Programme → Deliver → Monitor
  describes a work-oriented chain and not the others, so nothing shared is imposed across
  chains.
- **Chains stack vertically**, each starting at the left.
- **A chain shows lanes only for the parties that contribute in it.** The view is for
  understanding flow and who does what in what order; an empty lane does not serve that.
- Recover v1 and have Alex enrich it, rather than repair v2 or start again.

---

## Approach

### Recovery is a discard, and says so

`POST /{slug}/outputs/{output_id}/revert` already exists and is reachable from the Status tab,
so making v1 current is an action, not new code.

**There is no merge available.** The same ID string denotes different activities in each
version, so choosing v1's meaning voids v2's registry entirely. v2's prose remains useful as
source material for Alex's enrichment; none of its IDs survive. Saying this plainly matters -
a later reader finding two registries will otherwise try to reconcile them.

The registry is rebuilt from v1's IDs. v2's entries are **not** marked retired, because
retiring `2.1` would be a claim about *Fleet Strategy & Policy Setting*, which is not retired
at all - it is the very activity being restored. They are discarded as never-legitimate.

### The party model is corrected at recovery, not left to Alex

| Party | Role | Chains |
|---|---|---|
| GS UK | Custodian of all non-power assets | Property, Fleet, Support |
| ISS | FM subcontractor - property maintenance | Property |
| DXI | Fleet maintenance subcontractor | Fleet |
| Fleet Alliance | Vehicle leasing and procurement partner | Fleet |

v1's party ids (`sp`, `partnerISS`, `partnerDXI`) carry labels identical to the ids. They gain
real labels. `2.5`'s label loses its `(ISS)` suffix, which contradicted its own attribution.

This is done as part of recovery rather than delegated, because it is a correction against a
recorded fact, not a judgement - and because Alex has now got it wrong twice unprompted.

### One activity, one column

`validate_model` gains a rule: **every contribution of one activity shares one column.**

It binds Alex's write path and the editor's Save alike, so partner alignment holds by
construction rather than by care. A handoff between parties stops being an offset within one
activity and becomes what it always was - two activities, or two tasks of one.

The existing lane-uniqueness rule (no party repeats a column within a chain) is unchanged and
still needed: it governs one party across activities, this governs one activity across parties.

### Chains stack

Each chain becomes its own block of rows - its own party lanes, its own columns starting at
the left - with the blocks stacked vertically and a chain heading above each.

Today the three would sit **side by side on one horizontal line**: seeing Fleet means
scrolling past the whole of Property, and a party's lane spans all three chains at once, which
is meaningless when the chains have different parties.

**This partly reverses SP23c**, which merged per-segment grids into one continuous chain. That
was right when the segments were stages of a single chain and is wrong when they are three
separate chains. The code is the same; the meaning of a segment changed underneath it. Worth
recording so the reversal reads as a decision rather than as drift.

Lanes are per chain: Property shows GS UK and ISS; Fleet shows GS UK, DXI and Fleet Alliance;
Support shows GS UK alone. A party absent from a chain has no row there.

### No column ruler

The per-column header printing the raw position (`10  20  30`) is removed. It was added so a
gap read as a position rather than as whitespace; the cards' own `n.n` numbers carry that now,
and a number above a column reads as a stage heading whatever it actually denotes.

**Gaps remain rendered as empty cells** - the ruler goes, not the columns. An unoccupied
column between two occupied ones is still a real position and still shows as a space in the
flow.

### What Alex is asked to do

Review the recovered model and add what was never in it. v1 has 59 task labels and **zero
descriptions at any level**, zero propositions, zero links, and only two partner contributions
across seventeen activities.

- A description for each activity, each contribution and each task.
- The missing partner contributions - ISS in property delivery, DXI in fleet maintenance,
  Fleet Alliance in fleet acquisition - each aligned to its activity's column.
- Propositions where the source material supports them.

**He keeps every existing `n.n` and `n.n.n` ID and may only add by extension.** This is the
instruction that has failed twice, which is why the next section exists.

### ID enforcement at the write path

SP23c added `_VALIDATORS` in `agents/tools/sqlite_state.py`, consulted before a write, whose
failure returns the problems to the agent so it can correct itself in the same run. It
currently checks structure only.

It gains a registry check: every `segments[].id`, `activities[].id` and `tasks[].id` must
either exist in the current registry at the matching level, or be a genuine addition -
never an existing ID carrying a new label.

Without it, "review and add detail" can renumber the chain a third time. The instruction-only
discipline has now failed on IDs, on column uniqueness, and on the L1 axis, in a single run.

### Card presentation

The cards are washed out: `bg-surface-card` is `#ffffff` and the page `surface.DEFAULT` is
`#f9fafb`, a two per cent difference, and SP24a's resting border is `border-surface` - which
resolves to that same page background. **The card's edge is currently drawn in the colour of
the thing it is meant to separate from.** The palette has no border token at all and no dark
mode, so there is nothing in the scale to draw an edge with.

- A `surface.border` token is added and the card uses it, with a shadow. Selection continues
  to change the border's **colour** rather than adding an edge, which was SP24a's rule and
  remains right.
- **Cards are a fixed, uniform height** - a two-line header, three description lines, three
  activity lines and the controls row. Uniform height is what lets a party's row read
  straight across; today the tallest card in a row sets every cell's height.
- **At most three `n.n.n` activities are listed.** Where there are more, the remainder is
  **counted, not silently dropped** - a bare truncation reads as "this contribution has three
  activities", which is a false statement rather than a shortened one. No contribution in the
  current model has more than three, so this is a guard rather than a common case.

### The card shows, the dialog edits

Selection of an individual activity **moves off the card and into the dialog**. The card's
activity lines become plain text: number, then the opening of the label or description.

A **pencil control** on the card opens the dialog, which becomes editable - the `n.n` stage
and its `n.n.n` activities can both be changed there. It is the single way in; the card header
keeps drag and keyboard movement and no longer opens anything. *(If you want the header to
keep opening the dialog as well, say so - it is one line, and I have chosen the single entry
point because two controls opening one dialog invites the question of how they differ.)*

**The parties editor stays on the card**, where the lane it acts on is visible.

This **removes part of SP24a**, shipped two days ago: the card's activity lines were clickable
and carried a `taskId` up through `onSelect` so the dialog could open highlighted on the one
clicked. With the lines no longer interactive that plumbing has no producer, so it goes rather
than lingering as unreachable code. Recording it as a decision, not an oversight - the
mechanism worked, and the interaction model changed out from under it.

---

## What this does not change

The `n.n.n` scheme. Column semantics for one party across activities - same column is
concurrent, offset is a handoff, a gap is a real position. Drag, zoom, the stacked-card
rendering of collisions, the contribution model, or the API.

## Testing

**Recovery:**
- After recovery the current model has three chains and 17 activities, and `validate_model`
  returns no problems.
- The registry holds v1's IDs and none of v2's. Asserting only that v1's are present would
  pass on a registry holding both, which is the state that has to be impossible.

**Alignment:**
- An activity whose two contributions sit in different columns is refused, naming the
  activity and both columns. A fixture with one party per activity cannot exercise this at
  all, so it needs a joint activity.
- Alignment and lane-uniqueness are separate rules: a model violating one must not be reported
  as violating the other.

**Layout:**
- Three chains render as three stacked blocks, each with its own column set starting at the
  left - not as one horizontal run. A single-chain fixture cannot tell the two layouts apart.
- A party contributing in one chain has no lane in the others. This needs a fixture where the
  parties genuinely differ per chain, or "shows lanes for contributing parties" and "shows
  lanes for all parties" give the same answer.
- No column header renders the raw position, and an unoccupied column between two occupied
  ones still renders as an empty cell. Removing the ruler must not remove the gap.

**Card presentation:**
- The card's resting border is not the page background colour. Asserting that *some* border
  class is present is what let the current defect through - SP24a's test asserted
  `border-surface` and passed while the edge was invisible. The assertion has to be that the
  border differs from `surface.DEFAULT`.
- Two cards with different amounts of content have the same height. A fixture where both
  contributions carry one activity and a short description cannot distinguish a fixed height
  from a coincidence.
- A contribution with five activities renders three lines and states that two more exist. The
  count is the assertion - "renders three lines" alone is equally true of silent truncation.

**The card shows, the dialog edits:**
- The card's activity lines are not interactive: no button, no handler.
- The pencil opens the dialog; the card header does not.
- An activity's label edited in the dialog reaches the model, and the field is controlled -
  the same `defaultValue` defence that guards the card's description guards this one.

**ID enforcement:**
- A model reusing an existing ID for a different label is refused, and the returned string
  names the ID and both labels. Asserting only the refusal proves nothing about whether the
  agent can act on it.
- A genuinely new ID at a valid level is accepted, so the check does not freeze the chain.
- Alex's actual v2 model is a fixture: validated against v1's registry it must be refused.

## Out of scope

Interviewing to resolve what DXI's scope actually is - the party model here records what the
source states and no more. Connector arrows. Any change to what a column means. Making Maya's
level instruments editable. The capability model. Roadmap project 4, Jordan's coverage.
