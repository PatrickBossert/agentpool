# Making the Value Chain Editor Usable - Design

**Date:** 2026-08-01
**Status:** Approved for planning

Prompted by the first live run of `value_chain_mapper` under the new instructions. Not a
numbered roadmap project - it unblocks the editor that projects 4, 5 and 7 all build on.

## Problem

Three things, found together when Alex ran for the first time since the model replaced the
diagram.

### The layout answers the wrong question

The grid renders **one CSS Grid per segment, stacked vertically**. So a reader sees
segment 1's party lanes, then segment 2's lanes below, then segment 3's. They can never see
all entities across the whole chain at once, which is the view the work is actually done in.

An entity absent from a segment has no row in that segment's grid at all, so "ISS does
nothing in Corporate Services" is invisible rather than obvious.

There is no zoom. `sp-gs-am` now has 5 segments and 24 activities; at the current column
width that is roughly 325rem of chain, and no way to stand back from it.

### Save silently does nothing

Verified against the live database. Alex's `value_chain_model` v2 fails validation:

```
segment 5, party GSUK, column 10 -> ['5.1', '5.2', '5.3', '5.4', '5.5']
```

All five of segment 5's activities sit at column 10. `validate_model` reports four problems,
`save_model` refuses, the endpoint returns 422 - and the reader sees nothing happen.

**SP23a added an explicit instruction for exactly this**, in the mapper's own task text:
*"Within one segment, one party MUST NOT repeat a column… a party doing three things in one
segment uses 10, 20 and 30 there."* Alex had that instruction and violated it anyway. That
is the instruction-versus-enforced-invariant gap recorded in the ID-enforcement memory,
arriving in a different field.

### An invalid model cannot be repaired through the editor

The grid finds a card by `(party, column)` and takes the first match, so four of those five
cards render **nowhere**. You cannot drag apart what you cannot see, and dragging is the only
repair the UI offers. The model is therefore unsaveable *and* unfixable.

This is the same invisible-card failure closed inside `addParty` on SP22b, arriving this time
from a crew run - a path with no defence.

### What did work, and is worth recording

Alex's run was not a failure. He wrote `output_type='value_chain_model'` correctly, and his
activity IDs match the registry he wrote **exactly** - 24 L2 entries, zero drift, which was
the assumption most at risk. He produced 7 propositions and 16 links for the first time, and
identified 5 segments and 4 parties where the migration recovered 3 and 3. Only the column
numbering failed.

---

## Approach

### One continuous grid

Rows are entities. Columns run the whole chain left to right. Segment names sit in a band
above the columns they span.

**The grid's columns become `(segment_id, column)` pairs**, ordered by segment order then by
column value. Segment 1's column 10 and segment 2's column 10 are different physical columns
because they are in different bands, so **the model needs no data change** and the existing
uniqueness rule - no two contributions of one party within one segment share a column -
keeps exactly its current meaning.

Every entity gets a row spanning the whole chain. An entity that does nothing in a segment
shows empty cells there, which is information rather than absence.

### Zoom by transform

A zoom control scales the grid with CSS `transform: scale()`. Every card stays a real DOM
element, so drag, inline editing, the party menu and the pop-up all keep working at any
zoom. No canvas, no SVG, no new library - the constraint that made React Flow the wrong
choice for this project applies equally here.

Scaling the grid rather than the page means the entity column and the segment band scale
with it, and the scroll container is unaffected.

### A cell may hold more than one contribution

A cell that resolves to several contributions renders them **stacked and offset**, with a
marker showing how many. Every card is visible and every card is draggable, so a collided
model can be repaired by dragging cards out of the stack.

This is a rendering concession, not a model change: the model still says these contributions
share a column, and the display says so too rather than hiding all but one.

### Validation at write, not only at save

`SQLiteStateTool` writes whatever an agent hands it, recording `output_type=key`, with no
validation. That is why an invalid model reached storage at all.

The tool consults a small map of key to validator. For `value_chain_model` that is
`validate_model`. When validation fails the write is refused and the tool **returns the
problems as its result**, which is how a CrewAI tool reports failure to the agent - so Alex
learns immediately and can correct it within the same run, rather than a person discovering
it days later through a Save button that appears broken.

The map is the extension point: other structured outputs can register validators later
without the tool knowing about any of them specifically.

**This does not replace `save_model`'s validation.** A person editing in the grid can still
construct an invalid model, and that path must keep refusing. Two checks on one rule is
correct here: they guard different writers.

### Save says what is wrong, in words worth reading

The 422 carries `{"problems": [...]}`, and `StructureTab.tsx:203` already renders the list
thirteen lines below the Save button. **The problems are displayed.** An earlier draft of
this section claimed they were not; that was wrong.

What fails is the wording. Five colliding contributions produce **four** identical messages -
the first occupant is never reported - and not one of them names an activity:

> two contributions occupy column 10 in party GSUK's lane

The reader's next action is to find those activities and move them, and the message tells
them neither which nor how many. Reported once per over-occupied cell, naming every activity
in it, it becomes something to act on rather than something to decode.

**One thing to confirm with the person who hit this**, because it changes nothing in this
design but would change what else needs fixing: the Save control is `disabled` when
`hasUnsavedChanges` is false. If the button was disabled rather than firing and failing, the
edit never registered as a change, which is a different defect from an unhelpful message.
The stacked-card work below makes that far less likely, since it was probably an attempt to
move a card that was not visible.

---

## What this does not change

The model, the API, and the contribution semantics are untouched. Columns still mean what
they meant - same column is concurrent delivery, offset is a handoff, a gap is a real
position. This is a rendering change, a write-path check, and an error-message improvement.

## Testing

**The layout:**
- All entities appear as rows spanning the whole chain, including an entity with no
  contribution in a given segment - which is the case the per-segment grids could not show.
- A segment's band spans exactly the columns belonging to that segment.
- Two segments each having a column 10 produce two distinct physical columns, and a card in
  one does not appear in the other. A single-segment fixture cannot distinguish a correct
  implementation from one that keys cells on column alone, so this needs at least two
  segments.
- Zoom changes the rendered scale and a card remains draggable and editable afterwards - a
  test that only asserts a style attribute would pass on a grid that scaled itself out of
  usability.

**Collided cells:**
- A cell resolving to three contributions renders three cards, not one.
- Each is individually draggable, and dragging one out leaves the other two.
- Assert on the count of rendered cards, not on the presence of any - "a card renders" is
  true of the broken behaviour too.

**Validation at write:**
- A valid `value_chain_model` writes and records an output row.
- An invalid one is refused, **no row is recorded**, and the returned string names the
  problems. The second half is what the agent acts on; asserting only the refusal proves
  nothing about whether it can recover.
- A key with no registered validator writes unchanged, so the tool stays general.
- Alex's actual v2 model, with its five-way collision, is a fixture: it must be refused.

**The message:**
- A collision message names the activity IDs involved.
- Five contributions colliding produce one message naming five, not four messages naming
  none.

## Out of scope

Any change to what a column means. Connector arrows, still dropped. Repairing stored invalid
models automatically - the editor makes them repairable, and a person decides the sequence,
because column order is a claim about how work is delivered and inventing one would attribute
a decision to Alex that nobody made. Making Maya's level instruments editable, and the
capability model, both still banked.
