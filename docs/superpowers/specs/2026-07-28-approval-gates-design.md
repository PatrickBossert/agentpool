# Committing Output, and Releasing It Downstream - Design

**Date:** 2026-07-28
**Status:** Approved for planning

**Project 1 of 4.** Project 2 makes agent chat an editing surface; project 3 computes the
differential between commits and enables auto-start; project 4 gives Jordan his coverage
role. All three are out of scope here.

Chat comes before the differential deliberately. A differential is only worth computing
once outputs change in small increments, and today the only way to change an output at
all is to re-run its whole crew. Chat editing is what makes incremental change happen;
the differential is what makes it cheap downstream.

## Problem

A crew that finishes has no way to hand off, and a human who wants something changed has
no way to say so that takes effect.

- **Nothing chains crews.** `CREW_DOWNSTREAM` exists only in
  `ui/src/components/agentStatus.ts:353` as a display hint. The backend has no dependency
  graph, and no code path starts a crew because another one finished.
- **The wait is a blocking sleep.** `agents/tools/human_input.py:73` polls
  `time.sleep(5)` against a 24-hour deadline, inside a CrewAI tool, inside an in-process
  asyncio task. An engagement runs for months; a restart kills the run; and at 24 hours
  the tool returns the string `"timeout"` and the crew proceeds as though it had an
  answer.
- **`review_status = 'pending'` means nothing.** It is the column default. In
  `sp-gs-am`, 24 of 25 current outputs sit at `pending` while only 20 reviews have ever
  been raised, none of them pending.
- **Asking for a change does not change anything.** A change request is a note somebody
  must act on later, while the same instruction typed into agent chat would be acted on
  at once. Same intent, two mechanisms, different latency.

## Approach

There is one verb and one commit.

**Changing** an output is a single concept with several doors: agent chat, an inline edit
in the output tab, a reviewer's note. Each records who asked, what they asked for, and
what the agent changed. All of them mutate the **working** version.

**Committing** is the one act that is not a change. It does not mutate; it fixes a
version, attributes it, and releases it to the crews downstream. It is restricted to
governing roles, and it is the only event project 2's differential can key on.

Nothing is held open, so restarts stop mattering - there is no in-flight state to
survive. Approval latency becomes irrelevant, because waiting is a row in a table rather
than a sleeping thread.

**The invariant that makes this safe:** an edit never touches a committed version. Editing
after a commit starts a new working version. Without this, the differential engine
computes deltas against a version that has moved underneath it - and the downstream crew
either redoes work already done or misses changes that were edited away.

**Readiness, not auto-start.** Committing arms the downstream crew; a human commits the
spend. Auto-start waits for project 2, because firing a downstream crew across an entire
value chain on every commit is the cost blow-up this work exists to prevent.

---

## Data model

Three new tables in the per-project database (`data/<slug>.db`), created in `init_db`.

```sql
-- One row per act of committing. What a governing role signed off, and when.
CREATE TABLE IF NOT EXISTS approval_commits (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    crew_name     TEXT NOT NULL,
    committed_by  TEXT NOT NULL,
    committed_at  TEXT NOT NULL DEFAULT (datetime('now')),
    notes         TEXT NOT NULL DEFAULT ''
);

-- Exactly which output versions that commit froze. Project 2 diffs consecutive
-- commits through this table.
CREATE TABLE IF NOT EXISTS approval_commit_outputs (
    commit_id  INTEGER NOT NULL REFERENCES approval_commits(id),
    output_id  INTEGER NOT NULL REFERENCES agent_outputs(id),
    PRIMARY KEY (commit_id, output_id)
);

-- Every change asked of an output, however it was asked.
CREATE TABLE IF NOT EXISTS output_changes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    output_id     INTEGER NOT NULL REFERENCES agent_outputs(id),
    requested_by  TEXT NOT NULL,
    source        TEXT NOT NULL,                       -- 'chat' | 'edit' | 'note'
    request       TEXT NOT NULL,                       -- what the human asked for
    summary       TEXT NOT NULL DEFAULT '',            -- what the agent changed
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**Why the commit is per crew, not per crew run.** Every output version today comes from a
run, so `crew_run_id` would work - but only until project 2, where a chat edit produces a
new version with no run attached and run-keyed commits would leave edited work
permanently uncommittable. Keying on the crew now costs nothing and avoids migrating the
commit history later. A commit covers the current working versions of that crew's outputs
-
one act, however many outputs and however many changes went into them. That matches
committing "one or more changes" rather than signing off twenty-nine interview scripts
individually.

**Committed is membership, not a flag.** An output version is committed if and only if a
row links it to a commit. `agent_outputs.review_status` is superseded and this project
stops writing it; removing the column is deferred, because `run_service.py:64` still
reads it for revision notes.

---

## Changing an output

All three doors write an `output_changes` row and produce a new working version. The
agent that owns the output makes the change - a human describes the outcome, the agent
performs it, and both halves are recorded.

| Door | How it arrives | Built in |
|---|---|---|
| Reviewer note | A note attached to an output during review | **This project**, as `source='note'` |
| Agent chat | A message in the crew's chat asking for a change | Project 2, as `source='chat'` |
| Output tab edit | Direct editing of a rendered output | Later, as `source='edit'` |

**Only notes are built here.** The table carries `source` from the start so the later
doors add rows rather than schema, and so the change log is already the single place to
look before either of them exists.

**What a note does in this project.** It is recorded, attributed, and fed to the crew's
next run - `_fetch_revision_notes` (`api/services/run_service.py:50`) already collects
revision notes for exactly this purpose. So a note in project 1 is consumed by re-running
the crew. Project 2 is what lets the agent act on a request without a full re-run, which
is the loop that makes small changes cheap.

**Only an approver can commit, whoever asked for the changes.** The blast radius is
bounded by the commit rather than by the edit - a draft with a publish step - and that
holds however many doors exist.

---

## Committing

`POST /projects/{slug}/commits` with `{ crew_name, notes }`, restricted to stakeholders
flagged `is_approver`. It writes an `approval_commits` row attributed to the caller's JWT
`sub`, links the current working version of every output belonging to that crew, and
returns the crews the commit made ready.

**Which outputs belong to a crew:** those whose `agent_outputs.agent_name` is in
`_CREW_AGENT_NAMES[crew_name]` (`api/services/run_service.py:18`) and whose `is_current`
is 1. That mapping is already the authoritative crew-to-agent relationship, and the
crew-graph test that every crew appears in both keeps the two from drifting.

A crew with no outputs can still be committed - the commit row exists with nothing linked.
Some crews legitimately produce no artefact, and readiness asks only whether a commit
exists, not how much it froze.

A commit is never undone. A later commit supersedes it, and the history of commits is the
audit trail worth having.

**Committing does not require the change log to be empty.** An approver holds the
governing authority; blocking them would let one reviewer stall an engagement. The UI
shows the count of changes since the last commit rather than hiding it.

---

## The dependency graph

`CREW_DEPENDENCIES` in a new `api/services/crew_graph.py`, mapping each crew to the crews
that must be committed before it is ready:

```python
CREW_DEPENDENCIES: dict[str, list[str]] = {
    "discovery_mapping":      [],
    "assessment_design":      ["discovery_mapping"],
    "stakeholder_management": ["assessment_design"],
    "discovery":              [],
    "discovery_interviews":   ["assessment_design", "stakeholder_management"],
    "value_design":           ["discovery", "discovery_interviews"],
    "architecture":           ["value_design"],
    "delivery":               ["architecture"],
    "business_plan":          ["delivery"],
}
```

This encodes the reordering: **Alex → Maya → Jordan**. Jordan
(`stakeholder_management`) now follows Maya (`assessment_design`), because his coming role
in project 3 is to report which process steps and roles have no interview covering them -
which he can only do once Maya's interviews exist.

Two deliberate differences from the frontend map it replaces. `discovery_interviews` no
longer names `discovery_mapping` directly - it depends on `assessment_design`, which
depends on `discovery_mapping`, so the value chain is still required transitively and
naming it twice would be redundant. And `stakeholder_management`, which had no
dependencies at all, now depends on `assessment_design`: that is the reordering.

### Readiness

`is_crew_ready(slug, crew_name) -> bool`: true when every crew in
`CREW_DEPENDENCIES[crew_name]` has at least one commit. A crew with no dependencies is
always ready.

**Later changes upstream do not un-arm a downstream crew.** Readiness is released by a
commit, and that release stands even when the upstream working version moves on. The next
upstream commit releases the next increment - which is exactly the differential project 2
consumes.

Readiness is **computed, never stored**. A stored flag would need invalidating whenever a
commit landed, and a stale one would arm a crew whose inputs had been withdrawn.

---

## The blocking poll stops gating phases

`HumanInputTool` keeps its polling implementation for genuine mid-crew questions - an
interviewer asking a clarifying question during a session is a real use.

What changes is the **instructions**: end-of-phase review gating comes out of the agent
skills that mandate it, specifically the `Phase Gating` and `Human Review Gate` entries in
`api/services/skills_service.py` (lines 110 and 131). Those tell agents to pause at the
end of every phase and refuse to let downstream crews proceed. Left in place, crews still
block for 24 hours and the commit achieves nothing.

A crew's last act becomes finishing. Its outputs are working versions awaiting a commit.

---

## Who is told

Pamela's remit is project governance - reviewers and approvers. Jordan's is the actors in
the organisation, and he says nothing here; that is project 3.

When a crew run completes, Pamela emails the stakeholders flagged `is_reviewer` or
`is_approver`, reusing `resolve_recipients` and the Resend dispatch built for her daily
report, including its `dev_mode` routing. The message names the crew, what it produced,
and links to the review queue. Email failure must not fail anything - the outputs are the
durable record.

---

## API and UI

**Endpoints**, alongside the existing reviews router and authenticated as its neighbours:

- `POST /projects/{slug}/commits` - commit a crew's working outputs. Returns the crews
  made ready.
- `GET /projects/{slug}/commits` - commit history for the project, newest first.
- `GET /projects/{slug}/changes?crew_name=` - the change log since that crew's last
  commit: who asked, what they asked, what the agent changed.
- `GET /projects/{slug}/crew-readiness` - per crew: ready, which upstream crews are
  outstanding, and how many uncommitted changes it carries.

**UI.** The crew card gains a **Ready** state, distinct from idle: the breathing activity
gives way to "Ready to run" and the button is emphasised. A crew carrying uncommitted
changes shows the count. The review queue lists crews awaiting commit, each expanding to
its change log, with a commit control for approvers.

The resting-state work just merged stands: a card that is committed with no further work
returns to breathing idle.

---

## Testing

**Backend.** A commit links exactly the current working version of each of the crew's
outputs, and none belonging to another crew. Readiness is false until every upstream crew
has a commit and true after; always true for a crew with no dependencies; and unaffected
by later uncommitted changes upstream. A note records an `output_changes` row attributed to
its author and leaves every committed version untouched - the invariant the differential
depends on, tested here on the one door that exists so the later doors inherit a rule that
is already pinned. A non-approver is refused a commit. The graph has no cycles, and every crew in `_CREW_AGENT_NAMES`
appears in it: a mismatch would strand a crew as permanently unready. Email failure does
not fail a run.

**Frontend.** The Ready state renders only when the endpoint says ready. A crew with
uncommitted changes shows the count on its commit control.

---

## Out of scope

Agent chat writing outputs - project 2. The differential between commits, and auto-start -
project 3. Jordan's coverage reporting and any communication with actors - project 4. The
output tab's inline editor, which will write to `output_changes` when built. Delegating or
escalating a commit when an approver is unavailable. Undoing a commit.
