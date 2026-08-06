# Reviewer Feedback Loop - Design

**Status:** agreed 2026-08-06

**Goal:** Close the loop between human feedback and agent behaviour, routing each piece of
feedback to the destination its lifetime demands - a transient change request, a standing project
fact, or a durable agent skill.

## Why

Feedback is recorded and never reaches the agent. The paths were traced directly:

- `output_changes` is written by `api/routers/commits.py:182` (a reviewer requesting a change) and
  `api/services/value_chain_store.py:91` (a manual edit). It is read by exactly one consumer,
  `api/services/commit_service.py:146`, which displays it at commit time. **No agent, crew factory,
  `run_service` or `orchestration_service` reads it.**
- `human_reviews.notes` carries the reviewer's words from `PATCH /{slug}/reviews/{id}`.

**Correction, established during stage 1:** this section originally claimed `human_reviews.notes` was
display-only. **That was wrong.** `fetch_agent_outputs` computes a `reviewer_notes` alias as a
subquery over it (`api/database.py`), `_fetch_revision_notes` read that alias, and `run_service`
injected it as a `REVISION INSTRUCTIONS` block - so the review flow always reached the agent. The
error came from grepping for readers of the *table* when the reader used a computed *alias*.

Two consequences, both settled in stage 1. The same note was briefly injected twice, once through
each carrier; the old path has been retired and `output_changes` is now the single carrier. And
there are **two review doors**, not one: `PATCH /reviews/{id}` serves `ReviewDialog.tsx`, while
`POST /review` serves `RerunDialog.tsx`'s "Suggest a revision" and `AgentStatusTab.tsx`'s inline
"Revise". Both now write to the queue. Anything planned against this spec must account for both.

So a reviewer's correction reached the agent only through the review flow's `REVISION INSTRUCTIONS`
block, and only while the output's `review_status` remained `changes_requested` - with no lifecycle,
no record of whether it had been acted upon, and nothing carrying it beyond that one window. A
manual edit had no path at all, which is worse, because the editor believes they have fixed it -
`value_chain_store` records the edit with `source="edit"` and no rationale, and the next run
silently reverts it.

**The underlying asymmetry:** everything project-scoped is unread, and everything read is global.

| Channel | Scope | Written by | Read by agent |
|---|---|---|---|
| `skills` where `status='approved'` | Global | Baseline seed only | yes, via `_fetch_skill_notes` |
| `agent_skill_notes` | **Global** - no `project_id` | A separate manual endpoint | yes, via `_fetch_skill_notes` |
| `human_reviews.notes` | Project | The review flow | **yes** - via the `reviewer_notes` alias, see correction above |
| `output_changes` | Project | Reviewers and manual edits | no |

This fell between two features. The review feature records decisions; the skills feature builds
capability. Neither owned "a correction to this agent, on this project", and each looks complete
from its own vantage.

The durable half already works end to end. `run_service.py:93` gathers approved skills and skill
notes; `run_service.py:395` prepends them to every task description. All 54 skills are
`source='baseline'` with `source_project=NULL` - the promotion columns exist and have never been
used. This spec is their first use.

## Three destinations, one discriminator

The **rationale** decides the destination, never the action. "Remove that number" is all three
depending on why:

| Same action, different reason | Kind | Destination | Lifetime |
|---|---|---|---|
| "it is wrong, the budget is 8m" | Correction | Project RAG | Until a human retires it |
| "numbers change; refer to the budget generally" | Skill | Skills library | Until a curator rejects it |
| "it clutters this section" | Change request | The agent's next run | One run |

No classifier can separate those from the edit alone. Only the reviewer holds the why, which is
why intent is captured at entry.

**Project facts do not become skills.** A skill is a general capability applicable to any
engagement; a fact is true of one client and will change. Putting a fact in the prompt bloats every
task with detail most of them do not need, and the fact silently rots. Putting a rule in RAG means
it applies only when semantically retrieved - precisely when the agent is already thinking about
the subject and least needs telling.

## Capture

The reviewer chooses intent in their own language, not our taxonomy:

- **Fix this output** - change request *(default)*
- **This is true of this client** - correction
- **Do this on every project** - skill candidate

The default is the option with no persistence, so a reviewer in a hurry cannot seed the global
library by accident. The choice **biases** the triage; a curator still decides at promotion.

**The queue is `output_changes` itself.** Every capture point writes a row there first, whatever
the intent, and the row remains permanently as the audit record of what was asked and by whom. The
table gains a `kind` column:

```sql
ALTER TABLE output_changes ADD COLUMN kind TEXT NOT NULL DEFAULT 'unclassified';
-- unclassified | change_request | correction | skill
```

Classification then **copies** the content onward to `project_corrections` or `skills` as
appropriate; it never moves it. An unclassified row - a manual edit saved without a rationale - sits
in the queue until a human triages it, and is injected nowhere in the meantime.

Three capture points write to that queue:

1. **The review dialog** - `changes_requested` plus notes, with the intent choice alongside.
2. **A manual edit save** - the diff shown as context and the same three-way choice. **The save is
   never blocked.** Demanding a rationale before someone can save their work is how people stop
   editing. An unexplained edit still saves and lands unclassified, surfacing in the Corrections tab
   for later triage.
3. **An acknowledged validator warning** - from the L0 anchor spec, entering as a skill candidate by
   default. Validator warnings are generic by construction: `anchor_level_mismatch` is a statement
   about how anchoring works, with no client in it.

## Corrections are project truth

A new project-scoped table, deliberately **not** hung off `output_id`:

```sql
project_corrections (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id     INTEGER NOT NULL REFERENCES projects(id),
  correction     TEXT NOT NULL,        -- the standing fact, in the reviewer's words
  rationale      TEXT,                 -- why, as given
  created_by     TEXT NOT NULL,
  noticed_on     INTEGER,              -- output_id where it surfaced: provenance, not ownership
  status         TEXT NOT NULL DEFAULT 'active',  -- active | retired
  retired_by     TEXT,
  retired_reason TEXT,
  created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

`noticed_on` is provenance and carries **no foreign key**. If a correction were owned by the output
it was raised against, the dependent-row cleanup in `prune_output_types` and `revert_to_version`
would delete it - a reviewer's standing fact silently destroyed because someone reverted an
unrelated version. Provenance can dangle harmlessly; ownership cannot.

**Immediately on classification** the correction is upserted into the project's `{slug}_docs`
collection with metadata `{"correction_id": N}`. The reviewer providing the feedback *is* the
human in the loop; no further gate is needed before it becomes project truth. The Corrections tab
is a second layer of assurance over other humans' input, not a prerequisite.

`ChromaQueryTool._citation()` gains a **third branch** rendering `[correction_id=N | reviewer
correction]`. It currently handles `answer_id` and `doc_id` and falls through to `[source unknown]`
- without the new branch, the most authoritative source in the store would be the least
attributable.

**Retrieval:** **all** active corrections for the project are returned as a distinct block ahead of
the semantic results, on every query, never subject to a similarity contest. A correction that must
out-rank a 200-page contract on cosine distance will lose exactly when it matters most.

Returning all of them is deliberate - a correction excluded by a cap is indistinguishable from one
never made, which defeats the point. The cost is therefore linear in the size of the active set, so
the Corrections tab surfaces a warning once the active count exceeds 50, prompting a human to
retire what is stale. That number is a starting value, held in one named constant.

**Corrections are locked in.** `status` moves to `retired` only by explicit human action, with a
reason recorded. Nothing automatic retires one - not a re-run, not a re-ingest, not a superseding
document. Something corrected stays corrected until a human decides otherwise.

## Skills promotion

A skill candidate becomes a `skills` row with `status='pending'`, `source='feedback'` and
`source_project=<slug>`.

`skills_service.check_specificity()` runs at capture and populates the existing `flag_reason` and
`flag_suggestion` columns, so the curator sees "mentions a supplier name; consider generalising"
rather than having to spot it. It advises; it does not gate. The curator decides.

The curator works the queue in `AdminSkills.tsx`, refining wording and assigning agents via
`agent_skill_assignments`. Only `approved` skills reach `_fetch_skill_notes()`. That gate matters:
an agent able to promote its own corrections to permanent instructions would be rewriting its own
brief with nothing watching.

## Change requests need a lifecycle

`output_changes` is already the right home - project-scoped, output-scoped, and written by both
doors. What is missing is a reader and a lifecycle.

`run_service` injects open change requests into the task description, beside the existing
skill-notes injection at `run_service.py:395`. The scope is the crew's **current** outputs - the
same scoping `commit_service.py:146` already uses, `o["agent_name"] in agents and
o.get("is_current")` - so a request against a superseded version is not replayed. Only rows with
`kind='change_request'` are injected; `correction` and `skill` rows reach the agent through their
own destinations, and `unclassified` rows reach it nowhere.

The table gains:

```sql
ALTER TABLE output_changes ADD COLUMN status         TEXT NOT NULL DEFAULT 'open';  -- open | applied
ALTER TABLE output_changes ADD COLUMN applied_run_id INTEGER;
```

A request is marked `applied` once a run has consumed it. Without that, every run carries every
change request ever made and the injected block grows without bound until it drowns the task
description. Every mechanism here competes for the same finite attention: corrections are bounded
by human curation and skills by the approval gate, but change requests arrive continuously and have
no natural ceiling. The lifecycle is what stops the design degrading precisely as it becomes
well-used.

## Surfaces

- **Corrections tab** on the Documents page, following the existing `tabCls` Inputs/Outputs pattern.
  Lists active and retired corrections with review, edit and retire.
- **Skill candidates** in the existing `AdminSkills.tsx` queue, with the specificity flags visible.
- **Change requests** shown in the review dialog against the output they concern, so a reviewer can
  see what was already asked before asking again.

## Testing

- **Classification routing** - each intent lands in its own destination and no other; the
  `output_changes` row survives classification as the audit record rather than being moved; an
  `unclassified` row is injected nowhere and appears in the Corrections tab for triage.
- **Injection scoping** - only `kind='change_request'` rows are injected; a request against a
  superseded output version is not replayed.
- **The active-set warning** - the Corrections tab warns once the active count exceeds the
  threshold, and does not warn below it.
- **Corrections** - reach Chroma on classification with `correction_id` metadata; render as
  `[correction_id=N | reviewer correction]` rather than `[source unknown]`; are returned on every
  query regardless of similarity; and survive a re-run, a re-ingest, and a `revert_to_version` on
  the output named in `noticed_on`.
- **Retirement** - only explicit human action retires one, and a retired correction stops being
  retrieved.
- **Change request lifecycle** - an open request is injected once, marked `applied`, and not
  injected again.
- **Manual edit** - saves successfully with no rationale given, and the record appears as
  unclassified.
- **`check_specificity`** - a correction naming a supplier is flagged; a generic rule is not. Tested
  against the real function, since it is the guard that stops client detail reaching the global
  library.

## Scope note

This spec is at the upper limit for a single implementation plan - it spans a capture surface, a
new table with a Chroma path, a citation change, a retrieval change, a skills wiring, a lifecycle
migration and a UI tab. It is kept as one spec because every part shares the same capture model and
splitting it would mean specifying that model three times. **The plan should stage it**, in this
order, each stage independently useful:

1. Capture and the change-request lifecycle - the smallest loop that closes, and the one that stops
   manual edits being silently reverted.
2. Corrections - table, Chroma, citation branch, retrieval block, Corrections tab.
3. Skills promotion - candidate queue, specificity flags, curator wiring.

## Sequencing

This spec is built **first**, ahead of the L0 anchor and level-anchored synthesis spec
(`2026-08-06-l0-anchor-and-level-anchored-synthesis-design.md`), which depends on it for the human
half of its feedback loop and for the triage that turns acknowledged validator warnings into
durable skills.

## Not in this spec

Tokenised review links and the Slack stub (D); making `agent_skill_notes` project-scoped - it stays
global, because project-specific material now has a proper home in RAG rather than in prompts; and
automatic detection of which document a correction supersedes, since a reviewer usually will not
know and approach 2 makes it unnecessary.
