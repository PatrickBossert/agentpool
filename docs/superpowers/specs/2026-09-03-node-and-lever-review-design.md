# Per-node and per-lever review for Alex and Morgan

**Date:** 2026-09-03
**Status:** draft for review

## Why

Maya's loop works. A reviewer sent SC-014 back with a note on 3 September; run 37 regenerated
that one script, addressed the note, and left the other 85 **byte-identical**. The reviewer can
see exactly what changed and nothing else moved.

Alex and Morgan have no equivalent. What they have:

| | Alex (`value_chain_mapper`) | Morgan (`value_lever_analyst`) |
|---|---|---|
| Manual edit | `StructureTab` for `value_chain_model` - used, four edits in August | none |
| Reading surface | the model editor only | **none** - "No editor registered for this output yet" |
| Send-back | generic free-text note through `RerunDialog` | same |
| Granularity | **the whole artefact** | **the whole artefact** |

The backend is not the gap. `_fetch_change_requests` injects open change requests into the next
run, scoped by output type and enforced per row on `agent_name`, and it has demonstrably worked -
two requests raised on 6 August against Alex's tree and Morgan's levers were applied in run 28.
`fetch_open_change_requests` correctly filters `kind='change_request'`, so manual edit summaries
are not fed back as instructions.

**The gap is granularity.** Maya's loop is good because a script *is* a row with its own review
state. Alex's tree is one artefact holding 89 activities; there is no way to say "3.3.3's label
is wrong" and have only that regenerate. Build a better review dialog on top of one-artefact
granularity and you get something that looks like Maya's loop and behaves like today's.

## What the reviewable unit is

**Alex: the node.** Decided 2026-09-03. Each value chain activity carries its own review state.
**Morgan: the lever**, review only - no manual editor. The reviewer directs Morgan rather than
hand-correcting his analysis.

## Alex: the registry becomes a table

`value_chain_registry` is a JSON artefact - a list of 89 objects carrying `id`, `label`, `level`,
`active`. Those are a table's columns, and the ids are already a permanent contract: the ledger
may grow and may retire, but may never redefine or forget.

**This is the same migration Maya's registry already had.** `interview_script_registry` was a
JSON artefact with a write door; it became `interview_script_ledger`, a table maintained by the
write path, and the artefact and its door were retired. The reason then applies now: run 32 wrote
41 scripts, hit `max_iter` before its ledger write, and reported `completed` with 41 ids outside
the succession guarantee. An artefact the agent must remember to write is a guarantee that holds
only when the agent finishes.

So: `value_chain_ledger`, keyed on the node id, maintained by every `value_chain_registry` write,
carrying `review_status` and `review_return_to` beside `label`, `level` and `active`.
`DeriveRegistryTool` already keeps the label an id carries, and `tree_validation` already raises
`id_redefined` - both continue to hold; the table is where their result becomes durable.

**The write path registers, never moves.** `ON CONFLICT(node_id) DO NOTHING`, matching
`register_scripts_sync`. There is no delete.

## Morgan: levers need ids before they can be reviewed

`value_levers` is a list of 10 objects whose key is `lever` - a full sentence
("Risk-Based Capital Prioritisation via Monetised Risk Scoring (Rm = Pf x Cf)"). **Review state
cannot hang off a title regeneration is free to reword.** A reviewer sends back a lever, Morgan
rephrases the title while addressing the note, and the review state no longer matches anything.

Levers therefore need a permanent id with a mutable label - `LV-001`, the same shape as
`agent_id`, `script_id`, and the value chain node ids. This is the fourth application of that
pattern on this codebase and the first for a set that already exists, so the ids must be
**assigned once to the current ten** and never re-derived from position or title.

`value_lever_ledger` then mirrors the node ledger: `lever_id` primary key, `title`, `status`,
`review_status`, `review_return_to`.

## The loop, once both ledgers exist

Identical to Maya's, and deliberately so:

1. A reviewer reads the item and takes one of three exits - `edited`, `changes_requested`,
   `reviewed`. `approved` is excluded from the review count so an approval cannot satisfy its
   own gate.
2. `changes_requested` carries `review_return_to`. Only `agent` reaches the agent; a return to
   `reviewer` is a human-to-human loop, because regenerating a script the reviewer was about to
   re-read rewrites the thing under discussion.
3. The next `discovery_mapping` run reads what is awaiting the agent and injects it, the way
   `_pending_script_revisions` does for `assessment_design`.
4. The agent regenerates **only** those items. Everything else is byte-identical, and that is
   the property to assert.

## Where this does not copy Maya

**One crew, two agents.** `discovery_mapping` holds both Alex and Morgan, so the injected block
must be per-agent: Alex must not be handed Morgan's lever notes. `_fetch_change_requests` already
enforces ownership per row on `agent_name` and is the precedent to follow.

**Alex's artefacts are coupled.** He writes `value_chain_model`, `value_chain_registry`,
`value_chain_summary` and `value_chain_tree`, and a node regeneration touches more than one. The
byte-identical assertion applies per node within the registry; the tree and summary are derived
and will legitimately move. **Say which artefacts are expected to change on a single-node
send-back before building, or the first review will look like a bug.**

**Morgan reads Alex.** `related_activity_ids` ties levers to activities, so a retired or
relabelled node can orphan a lever - which is exactly what change request 5 on 6 August was
about ("Activity id '1.5.P1.gate' cited by lever 3 ... "). Per-item review makes that check
worth running on every write rather than on a reviewer's noticing.

## Testing

- A send-back on one node regenerates that node and leaves the other 88 registry entries
  byte-identical. This is the property; assert it by hash, as run 37 was verified.
- A send-back to `reviewer` never reaches the agent.
- Alex is not handed Morgan's notes, and the reverse.
- The ledger registers a new id and never moves an existing one - drive a write that tries.
- A lever's id survives its title being rewritten.
- The injected block is absent when nothing is awaiting the agent, so an ordinary run is
  unchanged.

## Out of scope

A manual editor for Morgan's levers - decided: review only. Retiring the
`value_chain_registry` artefact itself, which can follow once the table is authoritative.
Per-node review for `value_chain_model`, which has its own editor and a different workflow.
