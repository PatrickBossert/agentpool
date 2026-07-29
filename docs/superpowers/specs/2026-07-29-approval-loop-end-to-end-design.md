# Making the Approval Loop Work End to End - Design

**Date:** 2026-07-29
**Status:** Approved for planning

**Project 1 of 7.** The remaining six, in order: auto-start on approval; the value chain
editor with its sequence attribute; Jordan's coverage role and clock-triggered re-runs;
interview delivery with tokenised links and transcripts into the RAG store; Casey's daily
synthesis; and differentials, which are needed only when a crew is re-approved.

## Problem

The commit machinery merged in SP20a does nothing. Three defects, each independently
fatal, plus one modelling error found by walking the process through end to end.

- **Crews still block.** Twelve agent modules instruct the agent, as numbered task steps,
  to call `HumanInputTool` and wait for the string "approved" - for example
  `agents/value_design/value_proposition_generator.py:76-80`. That tool polls
  `time.sleep(5)` against a 24-hour deadline (`agents/tools/human_input.py:69-90`). The
  two skill descriptions rewritten in SP20a are injected *above* those task descriptions
  and do not override them.
- **The two rewritten skills never load.** Baseline seeding merges an existing skill's
  agent list but never updates its description (`api/routers/skills.py:226-240`), so an
  existing `system.db` keeps the old text.
- **Nobody can commit.** `ui/src/components/ReviewQueue.tsx`, which holds the commit
  control, is imported by nothing but its own test. The live page is
  `ui/src/pages/Reviews.tsx`, which has no commit control.
- **The state model is wrong.** SP20a modelled two states - produced, then approved. The
  process has three, because the contributor edits the artefact before the approver ever
  sees it.

### The modelling error, stated plainly

`notify_crew_awaiting_commit` fires when a crew run completes, and `resolve_recipients`
sends to everyone flagged `is_reviewer` **or** `is_approver`. So the approver is summoned
the moment the agent finishes - before the contributor has uploaded the follow-up
document, corrected the labels, or changed the sequencing. The approver arrives at a
half-finished artefact and has nothing useful to decide.

The old blocking mechanism made the same assumption more deeply: it presumed the human
**never touches the artefact**, only replying "approved" or handing revision notes back to
the agent. That is why it could live inside a tool call - there was nothing to do between
question and answer. In the real process the contributor edits titles, labels, and
ordering directly, with no agent involved. Removing the block is therefore not a
performance fix; it is a correction to what the system believed was happening.

## Approach

Three states, two acts, two audiences.

The agent produces. The contributor shapes it and says when it is ready. The approver
approves. Each act notifies exactly the group that must act next, and nobody else.

---

## The three-state model

| State | Meaning | Who acts next |
|---|---|---|
| `working` | The agent produced it; the contributor is still shaping it | Contributor |
| `ready` | The contributor has marked it ready for approval | Approver |
| `committed` | The approver approved it | Nobody - the next crew's turn |

One new table in the per-project database, created in `init_db`, parallel to
`approval_commits`:

```sql
CREATE TABLE IF NOT EXISTS crew_submissions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    crew_name     TEXT NOT NULL,
    submitted_by  TEXT NOT NULL,
    submitted_at  TEXT NOT NULL DEFAULT (datetime('now')),
    notes         TEXT NOT NULL DEFAULT ''
);
```

**State is computed, never stored** - the same rule readiness already follows. Compare the
crew's latest `crew_submissions.submitted_at` against its latest
`approval_commits.committed_at`:

- neither exists → `working`
- a submission with no commit, or a submission later than the commit → `ready`
- a commit with no submission, or a commit later than the submission → `committed`

Re-submission falls out of this for nothing: the contributor edits again after approval,
submits again, and the crew returns to `ready`. That is the ordinary case once a crew has
been through the loop once, not an edge case.

**Timestamp comparison.** Both columns default to `datetime('now')` and are compared as
text in the same `'YYYY-MM-DD HH:MM:SS'` format. A submission and a commit landing in the
same second resolves to `committed` - the approver's act wins a tie, which is the safe
direction: it cannot leave a crew stuck in `ready` after it has been approved.

`POST /projects/{slug}/submissions` takes `{ crew_name, notes }` and is permitted on the
same rule the commit endpoint uses, but admitting reviewers as well as approvers:
`sysadmin` passes; otherwise the caller's `users.email` must match a stakeholder in this
project with `is_reviewer` **or** `is_approver` set. As with commits, the first branch
always fires today because the `users` table is empty, and the rule tightens by itself
once accounts exist.

---

## Who hears what, and when

| Event | Audience | Message |
|---|---|---|
| A crew run completes | `is_reviewer` | The crew has finished; its output is ready to review |
| A submission is created | `is_approver` | This crew is ready for your approval |
| A commit is created | nobody | The next crew starting is the signal, and the contributor hears from *that* crew when it finishes |

`commit_notify_service.py` already exists, is tested, and is currently uncalled - SP20a
disabled its two call sites deliberately. It is re-enabled here with its audience narrowed
to reviewers, and a sibling function added for the submission event addressed to approvers.
Both keep the existing `dev_mode` routing and the rule that a failed send never fails the
thing that triggered it.

Deciding *not* to notify on approval is deliberate. In the process, what follows an
approval is the next crew starting, and the contributor is told when that crew finishes.
An email saying "this was approved" would arrive between those two and tell nobody
anything they need.

---

## Project activation

`POST /projects/{slug}/activate`, approver-only, sets `projects.status` to `'active'`.
The column exists and currently only ever holds `'created'`.

Pamela's daily report job skips any project whose status is not `'active'`, so a project
still in setup produces no reports. This makes "the approver activates it and it starts to
breathe" a real transition rather than a figure of speech, and stops report mail going out
about projects nobody has started.

---

## The twelve gates

The end-of-phase blocks come out of twelve agent modules. Each currently ends with a
numbered step of the form *"Use HumanInputTool with prompt: 'Please review X saved at
outputs/y.json. Reply "approved" to proceed…'"*. Nine of the twelve follow it with a
second step - *"If revision notes are received, revise and call HumanInputTool again.
Repeat at most 3 times."* - while `roadmap_generator` and `visual_illustrator` have the
gate alone, and `business_plan_generator`'s second occurrence is its context-gathering
step, which stays. Remove the gate and any revision-loop step that serves it; do not
remove a step by position.

`agents/discovery/value_chain_mapper.py`, `agents/discovery/requirements_analyst.py`,
`agents/discovery/value_lever_analyst.py`, `agents/discovery/interview_coordinator.py`,
`agents/discovery/interview_script_designer.py`, `agents/discovery/synthesis_analyst.py`,
`agents/value_design/value_proposition_generator.py`,
`agents/architecture/enterprise_architect.py`,
`agents/architecture/initiative_identifier.py`, `agents/delivery/roadmap_generator.py`,
`agents/delivery/visual_illustrator.py`, and
`agents/business_plan/business_plan_generator.py`.

Each loses those steps and ends by writing its output. Where the removed steps were
numbered, the remaining steps are renumbered so the instruction reads as a coherent
sequence - a task description ending at step 7 with a gap at 5 invites the model to
wonder what it missed.

`agents/tools/human_input.py` itself is **not touched**. The tool remains registered and
usable.

**Three uses stay, untouched here.** `agents/discovery/stakeholder_interviewer.py` and
`agents/discovery/requirements_capture.py` use the tool to conduct an interview - to ask
the interviewee questions and follow up - and `business_plan_generator.py:44` uses it to
gather business context rather than to seek a sign-off. None is an approval gate, so
commits do not replace them. They still block, and that is a real problem, but it belongs
with project 5, where the interview delivery path is designed and it can be settled
whether an agent polling for typed answers is a path anyone uses. Deciding it here would
be guessing.

---

## The skills correction

A general reseeding mechanism would overwrite descriptions edited through the Role &
Skills tab. Instead, a **surgical migration**: for each of the two skills, if the stored
description matches the known pre-SP20a text exactly, replace it with the new text; if it
differs by so much as a character, leave it alone.

An edited description belongs to whoever edited it. The migration is self-limiting - it
matches only text nobody has touched - and becomes a no-op once run.

---

## The reviews page

`ui/src/pages/Reviews.tsx` gains a section above its existing per-output review cards:
crews awaiting action, each showing its state, its count of changes since the last commit,
and the one control appropriate to that state - **Ready for approval** when `working`,
**Approve** when `ready`, and nothing when `committed`.

`ui/src/components/ReviewQueue.tsx` is deleted and its commit parts move into this
section. `CommitControl.tsx` survives as the approve control. Leaving two components that
half-do the same job is how the unreachable one came about.

Both controls show what they are acting over rather than blocking on it: the approve
control names the outstanding change count, as it does today.

---

## Testing

**State derivation** across every ordering of submission and commit, including neither, a
submission alone, a commit alone, submission-then-commit, commit-then-submission, and the
re-submission case where a crew returns to `ready` after having been approved.

**Notifications** are the substance of this project, so they are tested by audience rather
than by delivery: a crew completing notifies reviewers and **does not** notify approvers;
a submission notifies approvers and **does not** notify reviewers; a commit notifies
nobody. A test that only asserts an email was sent would pass under the very defect this
project exists to correct.

**Activation** gates the daily report - an inactive project produces none, an active one
does.

**The twelve modules** no longer mention `HumanInputTool`; the three that keep it still
do. Asserted per module by name, so a module silently missed is a failure rather than a
gap in a total.

**The migration** replaces a description that matches the old text and leaves an edited one
untouched.

## Out of scope

Auto-start when a commit lands - project 2. Any editor for output content, including the
value chain's sequence attribute - project 3. Jordan's coverage role - project 4. Tokenised
interview links, transcripts into the RAG store, and the fate of the three remaining
blocking uses - project 5. Casey's synthesis - project 6. Differentials - project 7.
