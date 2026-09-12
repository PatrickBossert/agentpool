# One mechanism, and it has a scope

**Date:** 2026-09-08
**Status:** approved in conversation, ready to plan

## Why

There are two ways a reviewer's correction reaches an agent, and only one of them was designed.

| | What it is | Gate | Where it applies |
|---|---|---|---|
| **Skill** | a general rule | proposed, deduplicated, held pending, approved by a human | every project |
| **Note** | the reviewer's sentence, distilled by a model | none | every project |

**The notes mechanism was never intended.** Patrick's account, 8 September: feedback was always
meant to improve the output in hand, and then be *evaluated* as a potential project-level or
global skill for that agent through the skills review. What exists instead is a second path that
skips the queue, skips the approval, and applies everywhere.

**And the project/global choice was designed and never built.** Nothing in the system is
project-scoped today. `skills.source_project` and `agent_skill_notes.source_project` both record
where a rule *came from*; nothing filters injection on either. The reviewer's decision has no
column to be stored in and no filter to be read by.

That is the real diagnosis behind four Critical findings on the sp61 branch. They were not four
leaks; they were one absence - **material with no scope defaulting to the widest scope** - seen
from four directions.

## What this builds

**1. The correction becomes a proposal.** `ReviewDialog` already asks the reviewer to choose an
intent, `change_request` or `skill`. `intent='skill'` currently sets `kind='skill'` on
`output_changes` and **nothing reads it** - CLAUDE.md records it as captured-not-routed. It now
routes into the proposal queue sp61 built.

**2. `agent_skill_notes` retires**, along with `create_skill_note` and `_fetch_skill_notes`'
notes half. One live row exists and it is this branch's own test data.

**Nothing is lost by retiring it.** The immediate half already works without it:
`run_service.py:671` says so in as many words - *"A reviewer's note reaches the agent through
`_fetch_change_requests`"*. The note contributed only the global stickiness, which is what a
skill does with a human in the loop.

**3. Skills gain a scope.** `scope` is `project` or `global`, beside the `source_project` that
already exists. Injection filters on it: a project-scoped skill reaches its own engagement, a
global one reaches all. `_fetch_skill_notes` already takes the slug, so the filter has its
argument.

**4. The reviewer chooses the scope when they approve**, beside Approve in the queue: *applies to
this engagement* or *applies everywhere*. **Project is the default**, because widening should be
the deliberate act and the narrow answer is the safe one when a reviewer clicks without reading.

## The example, which is the whole design in one case

Patrick's, and it belongs in the product's own copy rather than only here. A correction on one
engagement:

> *"$350m CapEx allocation"* → *"renewals CapEx allocation"*

yields a rule for Maya:

> **Do not include specific investment figures** - the number may change, and some interviewees
> may not be aware of the full amount. Refer to investments by their purpose.

That is **global**: it is about how to write an instrument, and it is true of every client.

The same box on the same day might instead produce *"this client calls it the renewals
programme, not the CapEx allocation"* - which is **project**, and would be wrong somewhere else.
Same reviewer, same control, different answers. The scope is the reviewer's judgement and cannot
be derived from the text.

## The existing 53

**They become `global`**, by Patrick's decision, 8 September.

They were written when global was the only thing a skill could be, so global is the honest
reading of what their authors intended. Recorded here rather than inferred later, and worth
saying plainly: **this affirms 53 rules as universal without anybody re-reading them.** A
reviewer who finds one that was really about a single engagement demotes it; the migration does
not make that judgement for them.

## What survives from the sp61 fixes, and why they were not wasted

- `source_project` on both tables is the column a scope decision is stored against. The plumbing
  arrived while we thought we were patching a leak.
- The queue, the deduplication, `occurrences` and the proposal tool are unchanged.
- **The egress narrowing keeps exactly one job.** A *global* proposal genuinely travels, so a
  sensitive engagement's contribution to the shared library still needs
  `_candidates_that_may_travel`. A *project*-scoped one no longer needs a guard: nothing asks
  for it.

## The decision this raises, taken here

**A project-scoped skill is not offered as a deduplication candidate to another project.** The
recurrence signal is worth less than the separation: two engagements independently proposing the
same rule is exactly the evidence that it is global, and that evidence survives, because a
*pending* proposal is not yet scoped. Only an approved project-scoped rule is withheld, and by
then a human has said it belongs to one engagement.

## Testing

- A project-scoped skill reaches its own project's prompt and **not** another's. Both halves;
  the absence is what fails silently.
- A global skill reaches both. The control - without it, a filter that dropped everything passes.
- The scope defaults to `project` when a reviewer approves without choosing, asserted on what is
  **written**, not on what the control renders.
- `intent='skill'` produces a row in the queue. It has never produced anything; assert the row,
  not the request's acceptance.
- The 53 existing rows are `global` after migration, and a proposal created afterwards is not.
- Nothing reads `agent_skill_notes` once it is retired - asserted by its absence from the source,
  not by the table being empty.
