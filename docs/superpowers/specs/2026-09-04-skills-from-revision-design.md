# An agent proposes a skill from the revision it just made

**Date:** 2026-09-04
**Status:** draft for review

## Why

A reviewer sent SC-014 back on 3 September: the welcome and framing repeated each other, and
the framing should carry the interview's purpose rather than a second set of reassurances. Maya
revised it, well. **Then the lesson evaporated.**

The note fixed one script. The rule behind it - *the welcome carries privacy and tone; the
framing carries purpose* - applies to every interview script Maya will ever write, on every
engagement. Nothing captured it, so the next project starts with a Maya who will make the same
mistake and a reviewer who has to write the same note.

**The machinery to prevent that already exists and has never been connected.** 54 skills are
assigned to agents and injected into every crew run. Every one is `baseline` or `manual`; **not
one has come from a review.** `skills_service.extract_skills_many` turns free text into
structured proposals and `check_specificity` judges whether a description is actionable - both
reachable only from the admin skills page. The generic review door declares an `intent` of
`skill`, which sets `kind='skill'` on `output_changes` and stops there: nothing reads those
rows. `kind` has only ever held `change_request` and `unclassified`.

## The decision, and the one it was weighed against

**The agent proposes, having made the change.** Decided 2026-09-04. It has context nobody else
has: it knows what it actually changed, not merely what was asked.

The alternative was a periodic sweep over review history, proposing where feedback recurs. It
was rejected on a single argument: **a sweep can only learn from mistakes that have already been
repeated.** Recurrence is its evidence, so by construction the failure must happen twice before
it proposes anything - and preventing the second occurrence is the entire point. On a new
deployment it is worth nothing until history accumulates.

What the sweep had over per-revision proposal is *evidence of generality*. A proposal made from
one note is the agent guessing that the note generalises, and skills reach every future run, so
a bad skill is worse than no skill.

## Duplicate detection is recurrence detection

**This is the part that gets both mechanisms from one design.** Before proposing, the agent
checks its draft against the approved skills for its own name **and** the pending suggestions.

A match is **not** noise to discard. It is the second occurrence - exactly the signal the sweep
existed to find, arriving without waiting for a sweep. So a duplicate **increments a count** on
the existing suggestion and records the new provenance, rather than creating a row or being
dropped.

The queue sorts by occurrences. A suggestion seen once is a guess and sits at the bottom; one
seen three times, across different scripts or projects, is evidence and rises to the top with
its occurrences attached. **Approve from evidence, not from prose.**

## What must not happen

**A proposed skill is not injected.** `_fetch_skill_notes` reads `status='approved'`; a
proposal is `pending` and reaches no run until a human approves it. This is the whole safety
argument for letting the agent propose freely, and it is one line - assert it, because if a
pending skill ever reached a prompt the agent would be teaching itself.

**The proposal must not change the revision.** The agent revises first and proposes second. A
tool call that fails, refuses, or times out must not fail the run or alter the artefact - the
reviewer asked for a revision, not a skill.

## Applies to every agent, not to Maya

The requirement, stated so a new agent is measured against it: **an agent that can be sent work
back should propose the general rule behind the correction it just made.** The mechanism is a
tool available to every agent, not a step in Maya's task - `SkillProposalTool`, registered for
any agent that produces a reviewable output.

That deliberately covers the loops sp60 is building for Alex and Morgan, and the ones the
unbuilt register-shaped outputs will need.

## Where it lands

`skills` lives in `system.db`, so new columns go in `init_system_db` as `CREATE TABLE IF NOT
EXISTS` plus `ALTER`, and **`_SCHEMA_VERSION` must not be bumped** - that constant gates project
databases, and bumping it would re-run every project migration for a table it does not govern.

Columns the design needs and the table lacks: `occurrences` (default 1), and `proposed_by_agent`.
`source_project` already exists and is NULL on all 54 rows - the proposal path should populate
it, since a skill's provenance is the first thing a reviewer will want.

**Scope is inherited, not decided here.** An approved skill applies to its agent on every
engagement, which is how the existing 54 work. `source_project` makes a later project-scoped
tier possible without a migration; that is a separate decision and out of scope.

## Testing

- A proposal reaches the queue as `pending` and is **absent from what `_fetch_skill_notes`
  injects**. This is the safety property; assert what reaches the prompt, not what the table
  holds.
- A near-duplicate of an approved skill increments occurrences and creates no row.
- A near-duplicate of a *pending* suggestion does the same - the pending set is checked, not
  only the approved one.
- A genuinely new proposal creates a row with occurrences 1.
- A failing proposal does not fail the run, and does not alter the artefact the agent just
  revised.
- The queue orders by occurrences, so evidence sorts above guesswork.
- **The duplicate test must use a differently-worded near-duplicate**, not the same string. An
  exact-match test would pass against a comparison that only ever catches identical text, which
  is not what "duplicate" means here.

## Out of scope

Project-scoped skills. Retiring or superseding an approved skill. Measuring whether an approved
skill changed the agent's output - worth doing, and it needs a baseline this design does not
create. The `intent='skill'` path on the generic review door, which stays captured-not-routed
until this loop is proven.
