# The review surface moves to the output, and the template layer goes - design

**Date:** 2026-08-14
**Status:** agreed, ready for planning

## Why

Per-script review shipped with its actions in the wrong place. `ScriptReviewRow` offers "Mark
reviewed" and "Send back" as list actions, next to a script it never shows. Both are conclusions
a person reaches *after* reading an instrument, so the list invites a judgement it gives no
means of forming.

The editor that would let them read it exists - `InterviewTemplateEditor`, already writing
through the versioned door - but it is reached from Maya's **Setup** tab, off a
template-assignment row, rather than from the output it edits.

And `approved` has been a valid decision on the endpoint since the review work landed, with
approver-only authority already enforced. The UI has simply never offered it.

Meanwhile the Setup tab is actively misinforming. Its coverage mapping reports **L2 Decision
Architecture for every node regardless of level**, which reads as though most of Maya's 86
instruments are pitched at the wrong altitude.

They are not. Measured against the live registry:

| | |
|---|---|
| Scripts whose level disagrees with their node | **0** |
| By level | 1 × L0, 3 × L1, 17 × L2, 59 × L3 |
| By role | 2 × C, 1 × A, 2 × F, 1 × S |

That is enforced, not lucky: `validate_anchor_levels` refuses any batch where a script's level
disagrees with its node's, on every write, added after run 26 filed the Board and C-Suite script
against node `1`.

The wrong number comes from `node_template_assignments`, a separate table of 103 rows in which
**every row carries `level = 'L2'`** - a default never populated from the real node. Only 86 of
the 103 hold a `script_id`; the rest are stale rows seeded from the value chain tree.

So the layer duplicates a mapping the scripts already carry correctly and 1:1, and the copy is
wrong. It also has a `publish` action that 404s on every real project, because it looks up by
`node_label` in an artefact keyed by `script_id`. It has been broken and unnoticed.

## Part B: the template-assignment layer is removed

Sequenced first, because it is what makes the Output tab the single honest home for an artefact.
Building the good surface beside the misleading one is the more expensive order.

**Removed:** the `node_template_assignments` table, `api/services/auto_assign_service.py`,
`publish_node_template` and the `/node-templates` routes, `ui/src/api/nodeTemplates.ts`, the
Setup-tab section that renders the coverage mapping, and the mention in `Architecture.tsx`.

**One consumer matters, and it is not the mapping UI.**
`api/services/interview_answer_service.py:151` resolves a stored answer's `script_id` by matching
`node_template_assignments` on `node_label`. That is the citation path - how an answer records
which instrument produced it. Removing the table without replacing it would silently orphan every
answer.

**The replacement is better than what it replaces: `interview_sessions` gains `script_id`, set
when the session is created.** A session is *for* a script, so the session should carry it.
Today it carries `node_label` and the service re-derives the script by matching label text - the
same brittle label-matching that makes `publish` 404, and that `auto_assign_service` itself calls
"the original defect".

**The second consumer is already dead.** `interview_service.py:147` reads an assignment only to
find a `questionnaire_template_id`. Exactly **1 of 103** rows has one, and questionnaires moved
inline into the interview when `questionnaire_builder` was removed. That branch goes with the
table.

**Timing is the strongest argument for doing this now.** The project has **0 interview sessions
and 0 answers**. The citation path being re-pointed has never carried a row. Once invitations go
out this becomes a data migration against live evidence instead of a schema change on an empty
table.

Nothing is lost that the scripts do not already hold better: `activity_id` duplicates the
script's `node_id`, `script_id` duplicates the ledger's primary key, `level` is wrong on every
row, and `node_label` is the label-matching that keeps breaking.

## Part A: reviewing happens in the document, approving happens in the list

### The list is the approver's view

One row per script, showing the **node id** as its identity - `1.4.2`, not `SC-042` - with the
script's title, its review status, **how many reviews it has had**, and the staleness flag.

`script_id` remains the identity underneath: stakeholder assignments and stored answers cite it,
so it can never change. Only the display changes. `SC-042` means nothing to a reviewer, while the
value chain id is the reference used consistently everywhere else in the application.

Two actions: **Open**, and **Approve**.

Approve belongs here deliberately. It is the one judgement made *across* scripts rather than
inside one. It is disabled until the script has at least one review, and offered only to a
stakeholder flagged `is_approver`. The count is what makes the gate legible - "3 reviews" tells an
approver why the button is live.

### Reviewing happens inside the document

Opening a row renders the script - sections, questions, probes - in an editable view: the existing
`ScriptCard` rendering plus the existing editor, which already versions and validates.

Three ways out, and **all three record a review event**, because each means a human read it:

| Exit | Records | Effect on the artefact |
|---|---|---|
| Save changes | `edited` | New version, `last_author` is the person |
| Send back | `changes_requested` with a note and a target | None; the note reaches Maya or the reviewers |
| Reviewed, no changes | `reviewed` | None |

`approved` is excluded from the count: an approval must not satisfy its own gate.

### One person may review and then approve

Any review satisfies the gate, including the approver's own. A smaller engagement may have one
person holding both roles, and someone who opens a script, reads it, and marks it reviewed has
genuinely read it. The gate asks "has this been read", not "by somebody other than you".

## What changes underneath

**Three schema changes.** `script_reviews.decision` gains `edited`. `interview_sessions` gains
`script_id`. `node_template_assignments` goes.

**The review count is derived, never stored** -
`COUNT(*) FROM script_reviews WHERE script_id = ? AND decision != 'approved'`, returned on the
ledger endpoint beside each row. Storing it would create a second source of truth for something
one query answers, and the previous branch already spent a fix round on a derived field going
stale.

**Version conflict is the one new failure path.** The PATCH carries the artefact version the
reviewer opened, and is refused with a 409 naming who superseded it and when. With several
reviewers this is not hypothetical, and the reviewer whose work vanishes has no way to know it
happened. This project has already lost a human edit to a silent write once.

**The approve gate is enforced server-side.** A disabled button is a hint; the endpoint must
refuse an approval on a script with no reviews, or the gate is decoration.
`AlreadyApprovedError` already establishes the pattern for a stateful refusal returning 409.

## Testing

This project has a long record of tests verifying a property one layer from where it holds, so
each of these is specified at the layer that matters:

- **The approve endpoint refuses a zero-review script**, driven through HTTP rather than by
  reading the count, and permits it after one review.
- **Each of the three exits records the event it claims**, and the count moves accordingly -
  asserted on the count the endpoint returns, not on the row the service wrote.
- **A stale PATCH is refused**, driven as two sequential edits from the same base version, with
  the second rejected.
- **The citation path survives Part B**: a session created after the change carries its
  `script_id`, driven through session creation rather than by inserting a row.
- **The list renders the node id**, and a script with no reviews renders Approve disabled -
  asserted on what is rendered and on what the button would send.
- **Removing the layer breaks no interview path**: a session opens and an answer records with the
  table gone.

## Out of scope

The coverage validator, the level and perspective split, and the anchoring model are unchanged -
this alters where review happens, not what Maya owes. Soft revert stays deferred. Retirement
(`active: false`) stays unreachable and is recorded in CLAUDE.md's known issues; giving it a door
is a separate decision. The richer reviewing experience - filtering, bulk actions, diffing
versions side by side - remains worth designing once somebody has reviewed a few dozen
instruments and knows what they need.
