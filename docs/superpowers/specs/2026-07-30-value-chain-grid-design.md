# The Value Chain Grid of Cards - Design

**Date:** 2026-07-30
**Status:** Approved for planning

**Project 3b of the roadmap.** 3a built the contribution model, the migration from the Mermaid
colour classes, versioned persistence, and a Structure table to prove the model was right. This
project replaces that table with the grid of cards. The remaining projects are unchanged:
auto-start on approval, Jordan's coverage role, interview delivery, Casey's synthesis, and
differentials.

## Problem

The Structure table proved the model but is not the view of it. It reads as a spreadsheet of
lanes and columns, when what the value chain is - and what the previous hand-built editor showed
- is a set of activity cards arranged across party swimlanes, with deliberate gaps carrying
meaning.

Three things the table cannot do:

- **A card is not a cell.** An activity's label, description, task count and proposition count
  belong together in one object you can see whole and pick up. A table row spreads them across
  columns and shows one at a time.
- **Rearranging is a click at a time.** Moving an activity four positions takes four clicks, and
  you cannot see the destination while aiming at it.
- **Joint delivery is unreachable.** No activity in the real data has more than one party, and
  the table has no way to attribute one. The reason contributions exist has never had an
  instance, so it has never been exercised, demonstrated, or corrected by hand.

## Approach

One CSS Grid per segment. Rows are party lanes, columns are the segment's sparse column
positions, and a card occupies a cell.

**The layout mechanism is the whole trick.** `grid-template-columns` comes from the segment's
column range and each card sits at an explicit `gridColumn`/`gridRow`. Snapping is not
implemented - it is the only thing that can happen, because a grid cell is the only place a card
can be. This is precisely what React Flow could not provide: a free canvas has to be *taught*
what a lane is, and teaching it is where the previous attempt spent its time.

Every cell renders a `<div>` whether occupied or not, so a gap is a real drop target rather than
an absence. For `sp-gs-am`'s first segment that is 6 columns × 2 lanes = 12 divs.

### What frames the grid

The segment - today's L1 - is named in a **left gutter**, not as a heading above the grid. That is
how the previous hand-built editor read, and it is what makes a segment scannable when several are
stacked: the eye finds the value stream on the left and follows its lanes rightwards.

Within the gutter, each lane row carries its party's label and that party's contribution count for
the segment, so an empty or thinly-populated lane is visible without counting cards.

Above the grid, a header row labels each column with its position number. Those numbers are the
model's actual column values, which is what makes a gap legible as a position rather than as
whitespace - a gap at 50 between cards at 40 and 60 is a claim, and the header is what lets a
reader see which claim.

### Connector arrows are dropped, not deferred

3a's spec listed connector arrows as 3b's work. That was a mistake, and this design removes them
rather than carrying them forward.

Position already encodes flow. Within a lane, ascending columns are the sequence. Across lanes, a
gap opposite another lane's card is a handoff - which is exactly what 3a's spec says an offset
column *means*. An arrow would restate what the layout already claims.

They are also the only part of this project needing an SVG overlay and live DOM measurement,
recomputed on scroll, resize and drag - the fragile, expensive piece. And with **zero links in
the migrated data**, nothing would render, so nothing could be verified. Building an unobservable
feature is how this codebase acquired `ReviewQueue.tsx` and nearly acquired `ContributionPanel`.

**Accepted cost:** a flow that genuinely cannot be read from position has no representation. If
one appears in real data, arrows can be added against a model that already stores the links.

---

## Decomposition

| File | Responsibility |
|---|---|
| **Create** `ui/src/utils/valueChainModel.ts` | The model types plus every pure operation on them - `columnRange`, `moveContribution`, `updateDescription`, `addParty`, `removeParty`, `confirmAttribution`, and the task and proposition counts. No React import. |
| **Create** `ui/src/components/ValueChainGrid.tsx` | One grid per segment: lane rows, column headers, cells, drop handling. |
| **Create** `ui/src/components/ContributionCard.tsx` | One card: ID, label, inline description, two counts, derived marker, party menu. |
| **Create** `ui/src/components/StructureTab.tsx` | The Structure tab lifted out of `ValueChain.tsx` - model query, pending edits, Save, the migrate affordance, and the confirmation dialog. |
| **Modify** `ui/src/components/ContributionPanel.tsx` | Same filtering, presented as a modal rather than a side panel. |
| **Delete** `ui/src/components/ValueChainTable.tsx` | Replaced by the grid. |

Two structural moves, both serving this goal rather than tidying for its own sake.

The model types currently live **inside** `ValueChainTable.tsx`, which six files import. That is
why deleting the component would ripple through unrelated files. Moving them to a module with no
React dependency fixes it permanently and makes the pure operations testable without rendering
anything.

`ui/src/pages/ValueChain.tsx` is 692 lines holding three tabs. The grid adds drag state, modal
state, party add and remove, and a confirmation dialog, which would push it past 850. Extracting
the Structure tab is cheaper now than after.

`ValueChainTable.tsx`'s tests are not deleted with it. Every behaviour they protect survives in
the grid, so the assertions transfer - identity-keyed rendering, gap rendering, move semantics,
derived marking, and the read-only case.

---

## Interaction

### Two mechanics stated precisely, because 3a hit both

**Card identity.** Cards key on `activity_id@party_id`, **not** on column. In 3a cards keyed on
column, so a move changed which contribution sat behind a given key, React reused a dirty input
against the wrong one, and the field displayed one activity's description while the next
keystroke overwrote another's - then saved it as an attributed version. Keying on identity makes
that structurally impossible rather than merely avoided. The description input is also controlled
(`value=`, never `defaultValue`). Two defences, because this defect silently corrupted saved data.

**Arrow keys.** The move handler lives on the card's focusable header, never on the card
container, so arrow keys inside the description input move the cursor rather than the card. 3a
established this with cell selection: a handler on an ancestor of a text input swallows
keystrokes typed into it.

The same rule governs clicks. Opening the pop-up is a control on the card header - it is not a
click handler on the card itself, because the card contains a text input and a party menu, and a
handler above them would fire on every interaction with either. Three sibling controls inside one
card: the header (focus, move, open), the description input, and the party menu.

### Gestures

| Gesture | Effect |
|---|---|
| Drag to an empty cell **in the same lane** | The card takes that column |
| Drag to an occupied cell in the same lane | The two contributions exchange columns; nothing else on either changes |
| Drag to **another lane** | Rejected - not a valid drop target |
| Arrow keys on the card header | Identical to dragging one step |
| Open control on the card header | Pop-up: this contribution's tasks, this activity's propositions |
| Party menu, add | A new contribution at the **same column**, attribution `stated` |
| Party menu, remove | Confirmation naming the task count, then deletes the contribution and its tasks |

Both counts are always shown, a zero rendered muted rather than hidden - that an activity has no
propositions is information, and a card whose shape changes with its contents is harder to scan.

### Why cross-lane drops are refused

A contribution's identity *is* `(activity_id, party_id)`. Dropping a card into another party's
lane would not reposition it; it would replace it with a different contribution and orphan its
tasks. Re-attribution is what the party menu does, explicitly. Conflating the two produces a
gesture whose outcome nobody can predict from the movement.

### Adding a party

The menu lists parties not yet contributing to that activity. The new contribution defaults to
the **same column** as the existing one, because same column means concurrent delivery and
concurrency is the reasonable default for "these two both do this". Dragging it aside afterwards
turns it into a handoff, and that is the claim the model exists to let a person make.

A human-created contribution is always `stated`. Only migration produces `derived`.

### Removing a party

Tasks are keyed `(activity_id, party_id)`, so removing a contribution orphans its tasks -
and `validate_model` already rejects an orphaned task, so the save would fail with a 422
discovered long after the decision.

The grid therefore confirms at the moment of the action, naming what will go: *"Remove ISS from
1.1.2? Its 4 tasks will be deleted."* Nothing is orphaned and the save cannot be rejected.
Nothing is permanently lost either - the current version stays on disk untouched and Save writes
a new one, so a revert restores it. The honest cost is that those L3 IDs are then retired, never
reused, per the registry discipline.

Removal is disabled when it is an activity's last contribution, with the reason shown.

### Confirming a derived attribution

A `derived` contribution gets a **Confirm** control that sets its attribution to `stated`.

Without it every migration guess stays flagged permanently and the marker degrades into
decoration. The distinction exists so a guess never silently hardens into a fact; a person
checking the guess and saying so is the act that resolves it, and it needs somewhere to happen.

### Saving

Unchanged from 3a. Explicit and batched: a Save control commits the edits made since the last
save as a new version, superseding `is_current` and recording an attributed `output_changes` row.
A 422 lists every problem at once. Unsaved edits are visible and warn on unload.

---

## One backend change

`validate_model` currently accepts an activity with **zero** contributions. Such an activity
validates cleanly, then disappears from the grid entirely - no lane holds it - while remaining in
`activities`, with no way to recover it through the UI.

Removing a party makes that state reachable for the first time, so the rule is added here: every
activity must have at least one contribution.

No saved model violates it. All 17 of `sp-gs-am`'s L2 activities have a contribution, so the rule
cannot reject anything already on disk.

---

## Testing

**The three regressions this branch has already paid for**, carried onto the grid:

- Edit a description, move that card, and assert the **rendered** field values track the right
  activities. A model-only assertion passed while the 3a defect was live.
- A lane with columns 10, 15 and 20 renders all three. Intermediate columns are what sparse
  columns are *for*, and 3a's first implementation hid them.
- A move is asserted by comparing the whole contribution object against a pre-move clone with
  only `column` changed - not by checking `column` alone, which would pass while a move reset the
  description.

**The new gestures:**

- Dropping on an empty cell in the same lane takes that column; dropping on an occupied one
  exchanges the two and changes nothing else on either side.
- A cell in another party's lane is not a valid drop target for a card.
- Arrow keys on the card header move the card; arrow keys inside the description input move the
  cursor and leave the card where it is.
- Adding a party creates a contribution at the same column, marked `stated`.
- Removing a party that owns tasks names the count, and confirming removes the contribution and
  its tasks together while cancelling changes nothing.
- Removing an activity's only contribution is refused, with a reason.
- Confirming a derived attribution sets it to `stated`; a stated one has no such control.

**Backend:** `validate_model` reports a problem for an activity with no contributions, and
continues to accept every activity in the real migrated model.

**Fixture sizing.** This branch shipped two defects hidden by fixtures too small to discriminate
correct behaviour from incorrect - a single version file hid a lexical sort, and a two-column lane
hid a column collision. Every fixture here is sized to the case: three or more columns for move
tests, two parties for joint delivery, and a non-multiple-of-ten column for the range.

## Out of scope

Connector arrows, and the link-creation gesture that would make them demonstrable - dropped, per
the reasoning above, not deferred to a named project. Creating or deleting an **activity**, which
would mint a stable ID and therefore belongs with the registry rather than the grid. Editing
segment or party membership itself. Editing task or proposition text - the pop-up shows them
read-only, as the side panel does today. Migrating `stakeholder_assignments` onto contributions,
which project 4 requires. Code-enforced cross-run stability of the model's IDs, which project 7
requires and which remains enforced only by the agent's instruction text.
