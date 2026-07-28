# Approval-Driven Crew Triggering - Design

**Date:** 2026-07-28
**Status:** Approved for planning
**Project 1 of 3.** Project 2 adds differential downstream work and enables auto-start;
project 3 gives Jordan his coverage role. Both are out of scope here.

## Problem

A crew that finishes has no way to hand off. Three gaps compound:

- **Nothing chains crews.** `CREW_DOWNSTREAM` exists only in
  `ui/src/components/agentStatus.ts:353` as a display hint. The backend has no
  dependency graph, and no code path anywhere starts a crew because another one
  finished.
- **The wait is a blocking sleep.** `agents/tools/human_input.py:73` polls
  `time.sleep(5)` against a 24-hour deadline, inside a CrewAI tool, inside an
  in-process asyncio task. An engagement runs for months; a restart kills the run;
  and at 24 hours the tool returns the string `"timeout"` and the crew proceeds as
  though it had an answer.
- **`review_status = 'pending'` means nothing.** It is the column default. In
  `sp-gs-am`, 24 of 25 current outputs sit at `pending` while only 20 reviews have ever
  been raised, none of them pending. Any design gating on "upstream outputs approved"
  deadlocks on real data.

## Approach

A crew run completing means "open for review", not "done". The system opens a gate; a
governing approver closes it; closing it marks the downstream crews ready.

Nothing is held open, so restarts stop mattering - there is no in-flight state to
survive. Approval latency becomes irrelevant, because the waiting is a row in a table
rather than a sleeping thread.

**Readiness, not auto-start.** Approving a gate arms the downstream crew; a human
commits the spend. Auto-start is deliberately deferred to project 2, because firing a
downstream crew across an entire value chain on every approval is the cost blow-up this
work exists to prevent.

---

## The gate

A new table in the per-project database (`data/<slug>.db`), created in `init_db`:

```sql
CREATE TABLE IF NOT EXISTS approval_gates (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    crew_name    TEXT NOT NULL,
    crew_run_id  INTEGER NOT NULL REFERENCES crew_runs(id),
    status       TEXT NOT NULL DEFAULT 'open',
    opened_at    TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at    TEXT,
    closed_by    TEXT NOT NULL DEFAULT '',
    UNIQUE (crew_run_id)
);
```

`status` is one of `open`, `approved`, `changes_requested`. The `UNIQUE (crew_run_id)`
makes "one gate per run" a property of the schema rather than of the code.

**Stacked change requests need no new storage.** `human_reviews` already carries
`crew_run_id`, so each reviewer's note is another row against that run. Several
reviewers can file requests before anyone re-runs anything, which is the point: rework
happens once, addressing all of them.

### Lifecycle

| Event | Effect |
|---|---|
| A crew run reaches `completed` | A gate is opened for it |
| A reviewer files a change request | Gate status becomes `changes_requested`; the note joins the stack |
| An approver approves | Gate status becomes `approved`, `closed_at` and `closed_by` set |
| A crew run fails | No gate. There is nothing to approve |
| The crew is re-run after changes | A **new** run, so a new gate. The old one keeps its `changes_requested` status as the record of that round |

`closed_by` records the approving user's `sub` claim from their JWT - the same identity
the rest of the API authenticates with.

A gate is never re-opened. A round of review is a fact about one run, and the history of
rounds is what makes the audit trail worth having.

**The system opens the gate, not the agent.** Both completion sites -
`dispatch_crew` (`api/services/run_service.py:387`) and `dispatch_agent`
(`api/services/run_service.py:558`) - open a gate immediately after
`update_crew_run_status(..., status="completed")`. Asking an LLM to remember to raise
its own gate is a weaker guarantee than doing it where the status is already written.

Gate creation must not fail the run: it is guarded and logged, in the same spirit as the
scheduler's heartbeat.

**Every crew gets a gate, including leaf crews** such as `business_plan` whose approval
releases nothing downstream. The audit record of who signed off the final deliverable is
worth more than the saved row.

---

## The blocking poll stops gating phases

`HumanInputTool` keeps its polling implementation for genuine mid-crew questions - an
interviewer asking a clarifying question during a session is a real use.

What changes is the **instructions**: the end-of-phase review gating is removed from the
agent skills that currently mandate it, specifically the `Human Review Gate` and
`Phase Gating` entries in `api/services/skills_service.py` (lines 110 and 131). Those
tell agents to pause at the end of every phase and refuse to let downstream crews
proceed. Left in place, crews still block for 24 hours and the gate achieves nothing.

A crew's last act becomes finishing.

---

## The dependency graph

`CREW_DEPENDENCIES` in a new `api/services/crew_graph.py`, mapping each crew to the
crews that must be approved before it is ready:

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
(`stakeholder_management`) now follows Maya (`assessment_design`), because his coming
role in project 3 is to report which process steps and roles have no interview covering
them - which he can only do once Maya's interviews exist.

Note the direction: this is upstream dependencies, not downstream targets. It is the
form readiness is computed from, and downstream targets are derived by inversion where
needed.

Two points where this differs from the frontend map it replaces, both deliberate.
`discovery_interviews` no longer names `discovery_mapping` directly - it depends on
`assessment_design`, which depends on `discovery_mapping`, so the value chain is still
required transitively and naming it twice would be redundant. And
`stakeholder_management`, which had no dependencies at all, now depends on
`assessment_design`: that is the reordering.

### Readiness

`is_crew_ready(slug, crew_name) -> bool`: true when every crew in
`CREW_DEPENDENCIES[crew_name]` has an approved gate. A crew with no dependencies is
always ready.

Readiness is **computed, never stored**. A stored flag would need invalidating whenever
a gate reopened or a dependency was re-run, and a stale readiness flag would arm a crew
whose inputs had been withdrawn.

The frontend's `CREW_DOWNSTREAM` becomes a derived view rather than a second source of
truth: a new `GET /projects/{slug}/crew-readiness` returns, per crew, whether it is
ready and which upstream gates it is waiting on.

---

## Who is told

Pamela's remit is project governance - reviewers and approvers. Jordan's is the actors
in the organisation, and he says nothing here; that is project 3.

When a gate opens, Pamela emails the stakeholders flagged `is_reviewer` or `is_approver`,
reusing `resolve_recipients` and the Resend dispatch built for her daily report,
including its `dev_mode` routing to a single development address. The message names the
crew, what it produced, and links to the review queue.

Email failure must not fail gate creation - the gate is the durable record; the email is
a notification.

---

## Approving over outstanding change requests

An approver may approve a gate that still has unaddressed change requests. They hold the
governing authority, and blocking them would let a single reviewer stall an engagement.

The UI shows what is being overridden rather than hiding it: the approve control names
the number of outstanding requests. This is a deliberate decision, not an oversight.

---

## API and UI

**Endpoints** (all under the existing reviews router, authenticated as its neighbours):

- `POST /projects/{slug}/gates/{gate_id}/approve` - body `{ notes }`. Sets the gate
  approved. Returns the crews this made ready, so the UI can react without refetching.
- `POST /projects/{slug}/gates/{gate_id}/request-changes` - body `{ notes }`. Adds a
  `human_reviews` row and sets the gate `changes_requested`.
- `GET /projects/{slug}/gates` - open and recently closed gates with their stacked notes.
- `GET /projects/{slug}/crew-readiness` - per crew: ready, and the upstream gates
  outstanding.

**UI.** The crew card gains a **Ready** state: distinct from idle, with the breathing
activity replaced by "Ready to run" and the button emphasised. A crew whose gate is
`changes_requested` shows that, with the stacked notes visible in the review queue. The
review queue lists open gates rather than only individual output reviews.

The resting-state work just merged stands: a card whose gate is approved and which has
no further work returns to breathing idle.

---

## Testing

**Backend.** Gate opened exactly once per completed run and not at all for a failed one;
`UNIQUE(crew_run_id)` enforced. Readiness false while any upstream gate is unapproved,
true when all are approved, and always true for a crew with no dependencies. Multiple
change requests stack against one run and leave one gate. Approval over outstanding
requests succeeds and records who closed it. Gate creation failing does not fail the run.
Email failure does not fail gate creation. The graph has no cycles and every crew in
`_CREW_AGENT_NAMES` appears in it - a mismatch between the two would strand a crew as
permanently unready.

**Frontend.** The Ready state renders only when the endpoint says ready. A gate with
outstanding change requests shows the count on the approve control.

---

## Out of scope

Auto-start on approval, and any notion of differential or incremental downstream work -
both are project 2. Jordan's coverage reporting and any communication with actors -
project 3. Delegating or escalating an approval when an approver is unavailable.
Re-opening a closed gate.
