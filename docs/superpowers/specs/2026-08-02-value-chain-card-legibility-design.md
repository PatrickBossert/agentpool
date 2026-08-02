# Value Chain Card Legibility - Design

**Date:** 2026-08-02
**Status:** Approved for planning

Follows SP23c, which made the grid continuous, saveable and repairable. This makes what it
renders readable. Not a numbered roadmap project.

## Problem

The grid works and cannot be read.

**A card has no edge.** `ContributionCard.tsx:66` sets `border-transparent` unless the card is
selected. Every unselected card therefore has an invisible border and reads as a floating
patch of surface rather than a bounded object, so one card does not separate from the next.

**A description shows about six words of a paragraph.** The description sits in a single-line
`<input>`. Alex's contribution descriptions run 196 to 486 characters, median 305. Everything
past the first line is invisible, and there is no indication anything was cut.

**The `n.n.n` activities are a number, not a list.** A card shows a `ListTree` icon and a
count. Reaching the activities themselves means selecting the card and reading the dialog, so
the question the grid exists to answer - what work sits under this stage, for this party -
cannot be answered from the grid.

**Two levels render with no number at all.** The segment band shows only its label
(`ValueChainGrid.tsx:192`) and the dialog heading shows the activity's label without its
`n.n` (`ContributionPanel.tsx:57,69`). A reader deep in a 24-column chain has nothing telling
them where they are.

### What the data allows

The shape of `value_chain_model_v2.json` decides most of the design:

| Fact | Consequence |
|---|---|
| Every contribution has 1-3 tasks (28 have one, seven have two, two have three) | Listing tasks inside a card adds one to three lines, not a wall |
| No task has a `label` field - only a `description`, median 199 characters | A task line in a card can only be its number plus the opening of its description |
| Contribution descriptions: median 305 characters | Three lines shows roughly a third; the rest must be one click away |
| 37 contributions across 24 activities and 4 parties | Card count is unchanged by this work |

### What already exists

`ContributionPanel` is **already the dialog this design needs**. It is a modal - `role="dialog"`,
`aria-modal="true"`, focus moved in on open and returned to the opener on close, Escape and
backdrop both closing - and it already renders the contribution's full description, every one
of its tasks with the task's full description, and the propositions on its activity. It opens
today by clicking a card header.

Nothing new is built for the dialog. It gains a second way in and a highlight.

---

## Approach

### The card gains an edge

`border-transparent` becomes a visible resting border; selection changes the border's
**colour** rather than making a border appear. A card that only grows an outline when selected
teaches the reader that borders mean selection, which is exactly the confusion to avoid when
the border's job is separating one card from its neighbour.

### Three lines of description

The single-line `<input>` becomes a `<textarea>` three rows high.

**It stays strictly controlled - `value`, never `defaultValue`.** That is not a style
preference. A `defaultValue` on a column-keyed input silently corrupted saved data on SP22a,
and the controlled value plus a card key on the contribution's identity are the two defences
against it. Changing the element must not weaken either.

Three rows shows roughly a third of a median description. The remainder is in the dialog,
which the card header already opens.

### The `n.n.n` activities are listed

The task count becomes a list of that contribution's tasks. Each line is the task's `n.n.n`
number in mono, then the opening of its description clamped to a single line.

**Propositions keep their count and are not listed.** A proposition attaches to the activity
as a whole, not to one party's contribution, so listing them per card would repeat the same
proposition on every party's card in that column - stating a shared thing several times as
though there were several of them.

### Clicking a task opens the existing dialog, on that task

A task line is a button. It opens `ContributionPanel` with that task highlighted and scrolled
into view.

Reusing the panel rather than building a task dialog keeps one dialog with one set of focus,
Escape and backdrop behaviour already covered by tests. It also gives the reader the context
around the task they clicked - the contribution's other tasks and the activity's propositions -
which is usually what is wanted when reading one of them.

The card header keeps opening the same dialog with nothing highlighted. Two entry points, one
dialog, one mounted-or-not decision in the grid.

### Numbering leads, everywhere

| Where | Today | After |
|---|---|---|
| Segment band | `Strategic Planning & Standards` | `1 Strategic Planning & Standards` |
| Card header | `1.1` then the activity label | unchanged |
| Task line in a card | not rendered | `1.1.1` then the description's opening |
| Dialog heading | `Asset Hierarchy - GS UK` | `1.1 Asset Hierarchy - GS UK` |
| Dialog task | `task.label ?? task.id` | `1.1.1` always, then the label when there is one |

`ContributionPanel.tsx:94` renders `task.label ?? task.id`, so a task that *did* carry a label
would display the label and lose its number. The number is always shown; the label follows it
when present. The current data has no labels, so this is invisible today and wrong the moment
one is written.

The dialog's `aria-label` keeps leading with the activity's label rather than its number - the
comment at `ContributionPanel.tsx:54` records that "1.1 detail" told a screen reader nothing,
and that reasoning still holds for the accessible name even though the visible heading now
carries the number.

### Taller cards, and the one thing they break

Three description rows plus up to three task lines makes every card taller. Cells in a CSS
grid row share a row height, so a party's row still reads straight across - the row is simply
taller, which costs vertical space and nothing else.

The collision stacking at `ValueChainGrid.tsx:319` pulls each occupant up by a hard-coded
`-mt-16`, a magic number coupled to the old card height and flagged as such in SP23c's final
review. With taller cards that offset no longer lands where it was drawn for. It must be
derived from the card rather than restated, or a 3-deep collision will overlap in a way that
hides the drag handles the stacking exists to expose.

---

## What this does not change

The model, the API, and column semantics. Drag, keyboard movement, zoom, the cross-segment
guard, and the collision stacking mechanism itself. The dialog stays **read-only**: tasks are
not editable from it, exactly as now.

## Testing

**The card:**
- An unselected card has a visible border; a selected one differs by colour, not by the
  presence of a border. Asserting only that a selected card has `border-brand` passes on
  today's broken behaviour, so the unselected case is the one that must be asserted.
- The description element accepts multi-line rendering and remains controlled: typing into it
  calls `onChange`, and the rendered value follows the model rather than local state. A test
  that only checks the element is a `textarea` would pass on an uncontrolled one.
- A contribution with three tasks renders three task lines. A contribution with one renders
  one. Asserting "a task line renders" is true of a broken implementation that renders only
  the first, so assert the count.

**The task lines and the dialog:**
- Clicking a task line opens the dialog with **that** task highlighted. A fixture whose
  contribution has one task cannot distinguish "highlights the clicked task" from "highlights
  the first task" - this needs a contribution with at least **three** tasks, and the middle
  one clicked.
- Opening from the card header highlights nothing.
- Closing returns focus to whatever opened it, from both entry points. The existing focus
  test covers the header path only.

**Numbering:**
- The segment band renders the segment's number before its label.
- The dialog heading renders the activity's `n.n` before its label.
- A task **with** a label renders its number and then the label - the case the current
  `label ?? id` fallback silently fails, and which no current fixture contains, so the fixture
  must add one.

**Height:**
- A 3-deep collision keeps every card's header reachable at the new card height. Asserting the
  offset's numeric value would lock in the same coupling this change exists to remove, so
  assert what the offset is for.

## Out of scope

Editing tasks from the dialog. Writing short `label` values for tasks, which belongs to the
crew instructions rather than the UI - the display handles their absence and their presence.
Connector arrows, still dropped. Any change to what a column means. Listing propositions per
card. Auto-repairing stored models.
