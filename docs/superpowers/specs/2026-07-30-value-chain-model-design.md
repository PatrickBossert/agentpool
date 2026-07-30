# The Value Chain Model, and a Table Editor - Design

**Date:** 2026-07-30
**Status:** Approved for planning

**Project 3a of the roadmap.** 3b builds the grid of cards - drag-and-drop, connector
arrows, and pop-ups - on top of this model. The remaining projects are unchanged: Jordan's
coverage role, interview delivery, Casey's synthesis, and differentials.

## Problem

The value chain cannot be edited, because there is nothing to edit.

`value_chain_mapper` emits a markdown file wrapping a Mermaid `flowchart LR`, and
`ui/src/pages/ValueChain.tsx:145` extracts that fence with a regex and hands it to
`mermaid.render()`. The agent emits a **rendering**, not a model. A Mermaid node can carry
a label and a CSS class and nothing else - no description, no counts, no position, no
attribution beyond a colour.

Three consequences:

- **No descriptions exist at any level.** `value_chain_registry.json` carries only
  `{id, label, level, active, parent_id}`.
- **No sequence exists.** Order is implied by the Mermaid source and, in the assignment
  views, by numerically sorting the ID - so identity and order are the same thing, and an
  activity inserted before an existing one cannot be represented.
- **Joint delivery cannot be expressed.** An activity performed by two parties has one
  label, one colour, one position. There is no way to say that SP-GS raises the works order
  and ISS executes the repair, and therefore no way to interview each party about its own
  part.

## Approach

The model becomes the source and every rendering becomes a projection of it - the same
principle already recorded for manual edits: the versioned artefact is the truth, and a
live view is derived from it, never a second place the state lives.

The activity stays one thing. Each party's part of it becomes a **contribution**, which is
what occupies a row and a column, carries its own description, and owns its tasks.

---

## The model

```
Segment            1        "PROPERTY VALUE CHAIN"        (today's L1, unchanged)
  Party            SP-GS, ISS, DXI                        (lanes within a segment)
  Activity         1.1.2    "Reactive Maintenance"        (today's L2, one stable ID)
    Contribution   1.1.2 × SP-GS    lane, column, description
      Task         1.1.2.3  "Raise works order"           (today's L3)
    Contribution   1.1.2 × ISS      lane, column, description
      Task         1.1.2.7  "Execute repair"
  Proposition      attaches to the activity
```

**Identity.** Segments, activities, and tasks keep the existing `Ln.n.n` stable IDs,
unchanged and never reused. A contribution's identity is the composite
`(activity_id, party_id)` - deliberately not a new ID space. It needs no second
never-reuse discipline, it is self-describing, and attributing a further party to an
activity creates a contribution without touching the activity's ID or its parentage.

**Tasks belong to a contribution, not to an activity.** The existing data already says so:
each L3 carries exactly one party colour, because a task is one party's work. This also
matches the intended UI, where a card's task list is that party's tasks.

**Propositions belong to the activity.** An opportunity such as "paperless works order
management" spans both parties, which is the common case. A proposition may optionally
name a party when the opportunity is one party's alone.

**Position.** A contribution carries `(lane, column)`, where lane is the party and column
is an integer position within its segment. A gap is an unoccupied column - it needs no
representation of its own.

Two contributions of the same activity in the **same column** mean the parties act
concurrently. Offset columns mean a handoff, and the gap between them shows the sequence.
The layout is therefore a readable claim about how work is delivered rather than
decoration, which is what lets it drive generated artefacts later.

**Columns are sparse.** Assign them in steps of 10 so inserting between two neighbours
picks an intermediate value rather than renumbering the segment. Renumbering on exhaustion
is rare and cheap at this scale.

---

## What the agent emits

`value_chain_mapper` stops emitting Mermaid and emits the structured model as JSON:
segments, parties, activities with descriptions, contributions with their lane, column and
description, tasks, and **links** between contributions.

Links are stored and validated in 3a but **not rendered** - they are what 3b draws as
connector arrows. They are captured now because the agent knows the flow at the moment it
maps the chain, and asking it again later would mean re-running a crew to recover
information it already had. A link names a source and a target contribution; a link whose
endpoints are not both present is rejected rather than stored dangling.

Without this the next Alex run overwrites the model with a diagram and the editor has
nothing to edit.

### Mermaid becomes a derived view

The diagram tab keeps working by **generating** Mermaid from the model, including
regenerating the party colour classes so the chart looks as it does today.

This is deliberate on two counts. It exercises the model hard - a model that cannot produce
the existing diagram is incomplete, and that failure surfaces immediately rather than in
3b. And when the grid of cards arrives it replaces a *projection* rather than a source, so
nothing about the model has to change to accommodate it.

---

## Migration

Existing IDs survive absolutely, with their parentage. Nothing is renumbered.

### Recovering attribution

The Mermaid carries real attribution as CSS classes with a colour scheme:

| Class | Colour | Nodes | Party |
|---|---|---|---|
| `sp` | `#1a5276` | 50 | SP-GS |
| `partnerISS` | `#c0392b` | 6 | ISS |
| `partnerDXI` | `#27ae60` | 5 | DXI |

Each Mermaid node's class maps to a party. The node is then matched to a registry activity
or task **by label text**, because Mermaid's internal ids (`S1A`, `S2B`) bear no relation
to registry IDs. Matching is on the normalised label - trimmed, case-folded, and with
runs of whitespace collapsed.

Contributions are **derived from task attribution**: an activity whose tasks are all `sp`
yields one SP-GS contribution; one with mixed tasks yields a contribution per party. The
existing chart already encodes which parties contribute to each activity, indirectly,
through its children's colours.

### Unmatched nodes default to the segment's dominant party

A node whose label cannot be matched is **not** reported for remediation - it is attributed
by this cascade, so the chart is complete and correctable rather than incomplete and
blocking:

1. The party holding the most attributed contributions **in that segment**.
2. If no contribution in that segment is attributed, the party holding the most across the
   **whole project**.
3. If the project has no attributed node at all, there is nothing to migrate - a project in
   that state has no Mermaid attribution to recover, and its model comes from the agent's
   structured output instead.

Ties at step 1 or 2 are broken by party name, ascending, so the migration is deterministic
and re-runnable.

### A derived attribution is marked as such

Every contribution records `attribution` as either `stated` - recovered from a colour class
- or `derived` - produced by the cascade above.

The default is a guess, and these attributions feed stakeholder allocation and interview
design. Interviewing SP-GS's people about ISS's work is a real cost, so the guess must
never silently harden into a fact. One boolean preserves the distinction, and 3b can
highlight the derived ones without blocking anything.

### Descriptions

Descriptions have never existed and cannot be recovered. They migrate empty, at every
level.

### Idempotence

Re-running the migration on an already-migrated project changes nothing. It is keyed on the
stable IDs, so a second run finds every activity, contribution and task already present.

---

## The table editor

A new **Structure** tab on the value chain page, alongside the existing Setup, Diagram, and
Templates tabs. Diagram stays, now rendering Mermaid generated from the model; Setup and
Templates are untouched.

- One table per segment. Rows are party lanes; columns are sequence positions; a cell holds
  a contribution.
- Editing a cell edits its description. Moving a cell changes its column. An empty cell is
  a gap.
- Two side panels rather than pop-ups: a contribution's tasks, and an activity's
  propositions. Pop-ups are 3b's work, and a panel shows the same data for far less.
- A derived attribution is visibly marked, so an incorrect default is findable.

Keyboard-first. No drag library, no SVG, no canvas - those arrive with the grid in 3b, and
the point of doing the model first is that the visual layer can then be built against a
model that is already right.

---

## Testing

The migration carries the risk, so it is tested hardest:

- Every existing ID survives with its parentage, and nothing is renumbered.
- A node classed `partnerISS` yields an ISS contribution marked `stated`.
- An activity with mixed-party tasks yields one contribution per party.
- An unmatched node yields a contribution attributed by the cascade and marked `derived`.
- The cascade's second step fires when a segment has no attributed contribution, and ties
  resolve by name ascending.
- Running the migration twice leaves the model byte-identical.
- Label matching normalises whitespace and case, and a label differing only by those
  still matches.

Round-tripping proves the model is complete: the generated Mermaid renders, and its
generated `classDef` colours match the three originals.

The editor: editing a description persists it; moving a contribution changes only its
column; an empty column renders as a gap rather than collapsing; a derived attribution is
marked and a stated one is not.

## Out of scope

The grid of cards, drag-and-drop, connector arrows, and pop-ups - 3b. Migrating
`stakeholder_assignments` onto contributions, which project 4 requires. Any change to what
Maya does with the new structure, or to what Casey can now contrast between parties -
both become possible here and are built later. Editing segment or party membership.
