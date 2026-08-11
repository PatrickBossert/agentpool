# The script ledger becomes a table, and review comes down to the script - design

**Date:** 2026-08-11
**Status:** agreed, ready for planning

## Why

Maya reached full coverage on 2026-08-11 across runs 31, 32, and 33: 86 scripts for 86 active
nodes, 1,711 questions, ledger reconciled. Run 32 is the reason this document exists.

That run wrote 41 scripts and lost the entire ledger. It stopped on CrewAI's default `max_iter`
of 25, and because writing the cumulative ledger is Maya's **last** step, the ceiling cut exactly
the step that keeps script ids inside the succession guard. It ended with 77 scripts on disk and
a registry still holding 36 - `SC-037` through `SC-077` existing outside the one guarantee the
whole design rests on.

Nothing errored. The run reported `completed`.

The exposure was concrete rather than theoretical. Maya allocates the next script id, the
ledger's highest was `SC-036`, and `_merge_with_current` keys on `script_id`. The next run would
have emitted `SC-037` for node `3.3.2`, and merge-on-write would have silently overwritten node
`1.4.2`'s script - with the cross-check unable to object, because `SC-037` was not registered.
That is precisely the scrambling the two-doors work was built to prevent, reachable because the
ledger lagged.

The ledger was rebuilt by hand and `max_iter` raised to 60, which is why run 33 completed the
last nine scripts *and* wrote the ledger. Both are patches on a shape that is wrong: **a
correctness record whose maintenance depends on an agent remembering to write it at the end of a
long run.**

## The design

### The ledger becomes a table

`interview_script_ledger`, one row per script, in the project database:

| Column | Purpose |
|---|---|
| `script_id` **PRIMARY KEY** | one id, one row |
| `node_id`, `node_label` | the permanent anchor |
| `active` | retirement, never deletion |
| `review_status` | `pending`, `reviewed`, `approved`, `changes_requested` |
| `reviewed_at_version` | the `interview_scripts` version that was actually read |
| `review_return_to` | `agent` or `reviewer`, set with `changes_requested` |
| `last_version`, `last_author` | which version last changed this script, and who wrote it |
| `created_at`, `updated_at` | |

`script_id` as a primary key is the point. "One id means one node for the life of the project"
stops being a rule an agent must honour and becomes a constraint it cannot violate.

`_SCHEMA_VERSION` is 2 in `api/database.py:1258`. Adding a `_migrate_*` function without bumping
it fails silently on every database already opened at the current version - no error, just rows
that stay unmigrated forever. Bump it in the same change.

### Registration is a side effect of the write

After a successful `interview_scripts` write, the write path upserts ledger rows: **insert new
ids, never change an existing `node_id`.**

The obvious objection is circularity. The ledger exists to be the independent record the scripts
write is *checked against*, so auto-updating it sounds like letting the subject mark its own
homework - a batch moving `SC-005` to a new node would rewrite the ledger to agree and the guard
would never fire.

That objection dissolves because the succession rule forbids exactly two things: redefining an
id, and dropping one. Append-only does neither. A new id is registered at the node its script
names; an existing id appearing at a different node is still refused. The guarantee is untouched
and the lag disappears.

This is the pattern the codebase already trusts. `insert_agent_output_sync` maintains
`is_current` on every write rather than asking anyone to remember; the script ledger should be
maintained the same way, for the same reason.

### The JSON registry retires

`interview_script_registry` has exactly one consumer: the guards. `_current_script_registry`
(`agents/tools/sqlite_state.py:82`) reads it for the cross-check, and
`_validate_interview_script_registry` guards writes to it. Nothing in the API or the UI reads it.

Retiring it pays three times:

- **It deletes run 32's failure mode.** If the ledger maintains itself there is no last step to
  lose.
- **It removes the cumulative-ledger instruction**, its regression test
  (`tests/test_interaction_designer_prompt.py:62`), and the whole class of "she sent a partial
  ledger and was refused".
- **It gives back iterations.** Re-sending an 86-entry ledger is part of what exhausted run 32.

`validate_scripts_against_script_registry` stays a pure function over a mapping; only its caller
changes, loading from the table instead of a file. `agents/tools/ownership.py:21` loses its
`interview_script_registry` entry, because a system-maintained table is not Maya's artefact to
own. Maya's prompt loses step 3's registry read, the ledger write, and the ledger clause in
`expected_output`.

Migration backfills from `interview_script_registry_v4.json`, verified reconciled at 86 entries.
Earlier versions stay on disk as history.

### Review comes down to the script

The review loop already exists and is not missing anything conceptually - it is at the wrong
granularity. `agent_outputs.review_status` and `human_reviews.decision` carry `approved`,
`changes_requested`, `dismissed`, and `rejected`, but review is per **artefact version**. For
Maya one artefact version is all 86 scripts, so the existing loop can only accept or reject the
entire set at once. Nobody reviews 1,711 questions in one decision.

**Authority comes from the stakeholder assignment, not from the login.**
`stakeholders.is_reviewer` and `is_approver` (`api/database.py:281-282`) already drive this:
`caller_may_commit` requires `is_approver`, `caller_may_submit` accepts either, both through
`_caller_matches_stakeholder_flag` (`api/services/commit_service.py:45`). Per-script review uses
the same check and the same flags. No new role concept.

Two properties of that machinery must be inherited rather than reinvented:

- **The fallback is asymmetric on purpose.** Review notifications fall back to approvers when a
  project has no reviewers, or nobody hears and the loop never starts. Approval notifications do
  not fall back to reviewers, because with no approvers there is genuinely nobody who can
  approve (`api/services/commit_notify_service.py:145`).
- **The gate is currently permissive.** `_caller_matches_stakeholder_flag` returns true for
  `sysadmin`, and today every login is sysadmin against an empty users table, so the first branch
  always fires. The restriction becomes real when accounts exist, with no code change. Per-script
  review inherits that, and will not actually restrict anyone on this deployment yet.

**Reviewed many times, approved once**, so state and history separate. `script_reviews` holds one
row per review event - `script_id`, `reviewer`, `decision`, `notes`, `at_version`, `created_at` -
and nothing is ever overwritten. The ledger row carries the derived current state. A second
approval is refused while a row is already approved; it must be sent back first.

**A send-back carries a target, and this is the load-bearing detail.** An approver may return a
script to Maya or to the reviewers, so `changes_requested` sets `review_return_to`.

Only `agent` enters Maya's differential. A return to reviewers is a human-to-human loop and must
never trigger regeneration - otherwise "please look at this again" quietly rewrites the
instrument the reviewer was about to re-read, and they review something else. A boolean cannot
express that, which is why the field exists.

### Regeneration and editing, and the record of which

**Maya's differential grows one clause.** Today it is "generate for nodes with no script". It
becomes "generate for nodes with no script, **and** regenerate any script whose ledger row asks
for revision with `review_return_to = 'agent'`, using its note."

Without that clause the feature is already broken. Change requests reach her scoped by
`output_type`, as free text against `interview_scripts` as a whole, and land beside an
instruction to skip every node that already has a script. She ignores them. This is a regression
the full-coverage work introduced, and it is invisible until someone asks for a revision and
nothing happens.

Per-script notes also close a hazard CLAUDE.md records: `RerunDialog` fans out, posting one
review per crew output, so anything assembling feedback must deduplicate or repeat the same
instruction N times. One row, one note, no fan-out.

**The human edit path is rebuilt, not patched.** It is currently broken in a way that loses work
silently. `InterviewTemplateEditor.tsx` GETs and PATCHes `/interview-scripts/{node_label}`
(`api/routers/projects.py:518,533`). That PATCH writes `outputs/interview_scripts.json` - a bare,
unversioned file that does not exist on this project - and keys by `node_label`, while the real
artefact is keyed by `script_id` and resolved through `current_output_path`. So the editor reads
one thing and writes another, produces no `agent_outputs` row, no version, no validation, and no
ledger entry, and then calls `auto_assign_interview_scripts` so Jordan's assignments sync from
the phantom.

Replaced by `GET`/`PATCH /interview-scripts/{script_id}`, resolving through
`current_output_path` and writing through `SQLiteStateTool` - a real version, the validators, and
a ledger row recording `last_author` as the person. Editing content resets `review_status` to
`pending`, because the tick described content that no longer exists.

### The minimal UI

A backend nobody can drive is the same as no backend, so this spec includes enough to use the
model and no more: a per-script list showing node, status, and reviewer; a tick to mark reviewed;
a send-back taking a note and a target; and a staleness indicator wherever
`reviewed_at_version < last_version`, reading "reviewed at v3, changed since".

It goes in Maya's Output tab beside the existing script list, which is where a reviewer is
already looking. A richer reviewing experience - filtering, bulk actions, diffing versions,
reading an instrument end to end - is worth designing on its own once someone has actually
reviewed a few dozen and knows what they need.

## Deferred, deliberately

**Revert becomes soft, and is not wired into the approve loop here.** `revert_to_version`
(`api/database.py:1705`) hard-deletes every version newer than its target. The agreed semantic is
the opposite: keep the version and mark it `active = 0`, so nothing is destroyed and the history
stays readable. That change touches every artefact type rather than Maya's, so it is recorded
here and built separately. Until then, a revert can strand ledger rows whose scripts existed only
in deleted versions - those rows must be marked `active = 0`, never deleted, because deleting
them reopens the id-reuse hole this design exists to close.

**The review workbench**, as above.

**Evidence-level coverage** stays where the previous spec left it: questions carry no node
reference, so evidence is filed at the script's own anchor, and the retro-fit route is Casey
mapping evidence to additional nodes where alignment is clear.

## Testing

- **The ledger is written by the scripts write, asserted through `SQLiteStateTool`'s real write**
  rather than by calling the upsert. A registration path the write does not reach is the defect
  this whole document is about.
- **A batch moving a registered id to another node is still refused after auto-registration.**
  This is the property most likely to be quietly destroyed by making registration automatic, and
  the one whose loss would be invisible - the write would succeed and the ledger would agree.
- **A run that dies mid-batch leaves every written script registered.** Simulated by writing two
  batches and asserting after the first, since that is exactly what run 32 could not do.
- **`review_return_to = 'reviewer'` does not put the script in Maya's differential**, and
  `'agent'` does. Asserted on the differential the task actually receives, not on the ledger row -
  the row is the mechanism, the prompt is the property.
- **A human edit produces a new version, a ledger row naming the person, and a reset review
  status**, driven through the endpoint rather than the service.
- **Approval is refused on an already-approved script**, and permitted after a send-back.
- **The staleness indicator renders** when `reviewed_at_version < last_version`, with a script
  that has been reviewed and then changed.

## Out of scope

Coverage validation, the level and perspective split, and the anchoring model are unchanged. The
illustration pipeline remains sequenced behind the business case writer. Nothing here alters
which model runs which agent.
