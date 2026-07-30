# Auto-start on Approval - Design

**Date:** 2026-07-31
**Status:** Approved for planning

**Project 2 of the roadmap.** Projects 1 (the approval loop) and 3 (the value chain editor,
both halves) are built. The remaining projects are unchanged: Jordan's coverage role,
interview delivery, Casey's synthesis, and differentials.

## Problem

The approval loop ends in silence.

An approver commits a crew's output and nothing happens. No crew starts, and by deliberate
design no notification is sent - project 1's spec chose not to notify on approval on the
grounds that "the next crew starting is the signal, and the contributor hears from *that*
crew when it finishes". That reasoning was sound and the signal was never built, so today a
commit produces no observable effect at all beyond a database row.

Everything needed to close it already exists:

- `api/services/crew_graph.py` holds `CREW_DEPENDENCIES`, the authoritative upstream graph,
  with `downstream_of()` by inversion and `is_crew_ready()` computed from it.
- `commit_crew` already computes `released` and the endpoint already returns it.
- Starting a crew is two steps: `insert_crew_run(...)` then
  `asyncio.create_task(dispatch_crew(...))`.

`released` is consumed by nothing - not by the frontend, which types it and discards it, and
not by anything else. This project makes the commit act.

## Approach

A commit starts every crew directly downstream of it that is **ready**.

### Ready, not newly ready

`released` reports crews this commit made ready *for the first time*:

```python
released = [c for c in candidates if not was_ready[c] and await is_crew_ready(conn, crew_name=c)]
```

Auto-starting on that would start each crew at most once, ever. A second commit upstream
returns an empty list, because the crew was already ready. The first pass through the
pipeline would run itself and every subsequent revision would be manual - which is the
common case once a project is under way.

The trigger is therefore readiness itself, not the transition into it. Revise the value
chain, approve, and Maya re-runs. This is the premise project 7 rests on: differentials
exist to make precisely this re-run cheap, designing an interview for the one changed
process step rather than all thirty.

A crew whose other upstreams are still uncommitted does not start. `discovery_interviews`
needs both `assessment_design` and `stakeholder_management`; committing one of them starts
nothing.

### Cascade safety is structural

A crew completing does not commit anything. Every hop between crews requires a human
approval, so a single commit can start at most the crews directly below it and can never
chain further on its own. This is a property of the design rather than a limit imposed on
it, and it is asserted as a test rather than left as an argument.

### An already-running crew is skipped

Two reviewers commit within a minute, or someone commits while a downstream crew is
mid-run. Two concurrent runs of one crew both writing versioned outputs is the failure to
avoid.

The in-flight run is already working from committed upstream state, so a second run would
duplicate it. The start is suppressed and reported; **the commit itself still lands.** This
matches the existing precedent, where `commit_crew` raises `CrewRunInProgress` rather than
proceeding when the crew *being committed* is running.

The accepted cost: if the in-flight run had already read its inputs, the later commit's
changes are not picked up by it. The response names the skipped crew, so a reviewer can
re-run once it finishes.

Queueing the start was rejected: it needs a pending-start store, a drain step, a rule for
collapsing two queued starts, and recovery if the process dies mid-run - real machinery for
a case a skip handles. Cancelling the running crew was rejected too: no cancellation
mechanism exists, `dispatch_crew` has no cooperative stop point inside a CrewAI run, and
three commits in a row would burn two full runs for nothing.

### The response describes what happened

`released` is **replaced**, not supplemented. It describes a hypothetical and has no
consumer; two overlapping fields where one is unused is a trap for the next reader. Every
downstream crew appears in exactly one of:

| Field | Meaning |
|---|---|
| `started` | Dispatched, with the run id |
| `skipped` | Ready, but already running |
| `waiting` | Not ready, with the upstream crews it still needs |

`waiting` is what makes a commit that starts nothing legible: it says which approval is
needed next rather than leaving the reviewer to guess.

### Only an inactive project suppresses a start

`projects.status` is set by `POST /projects/{slug}/activate` and **read by nothing** -
project 1's spec said the daily report would skip inactive projects, and no such check was
built. This gives the column the job it was created for: an inactive project's commits land
and start nothing, and activating it is what makes the pipeline flow. It makes "the
approver activates it and it starts to breathe" literally true.

There is no per-commit opt-out. It would put a decision on the common path for a case
already constrained by something else - committing crew A starts crew B, and B running then
blocks committing B.

The check lives in `start_ready_downstream`, which reads the project's status first and
returns early. Putting it there rather than in the router means every caller gets it, and a
future second caller cannot forget it.

**An inactive project's response says so rather than lying about readiness.** It returns
`started: []`, `skipped: []`, `waiting: []` with a distinct `inactive: true`. Reporting
ready crews as `waiting` would be false - they are not waiting on an upstream, they are
waiting on the project being activated, which is a different problem with a different fix.

---

## Where it lives

A new `api/services/autostart_service.py` exposing:

```python
async def start_ready_downstream(slug: str, crew_name: str, *, committed_by: str) -> dict
```

returning `{"started": [...], "skipped": [...], "waiting": [...]}`.

`api/routers/commits.py` calls it **after** `commit_crew` returns and its connection has
closed, and merges the result into the response.

Two reasons for that boundary. `commit_service` stays about commits rather than acquiring a
dependency on `run_service.dispatch_crew`. And the ordering becomes explicit at the
endpoint: **the commit lands first, and a failure to start never unwinds it.** An approval
that was recorded stays recorded whatever happens next.

## Failure

`dispatch_crew`'s success path notifies reviewers; its failure path writes a log line and
raises. Nobody is told. Combined with a commit that notifies nobody by design, auto-start
would otherwise produce: approve, crew starts, crew fails, total silence - with the approver
holding the false belief that work is in flight.

`dispatch_crew` gains `triggered_by: str | None = None`. On failure it notifies the
`is_reviewer` group always, and additionally `triggered_by` when set. An auto-started run
therefore tells the approver who committed; a manually started one tells reviewers. This
also closes the pre-existing hole for manual runs.

The sender is `notify_crew_failed` in `api/services/commit_notify_service.py`, a sibling of
`notify_crew_awaiting_commit`, reusing its audience resolution and `dev_mode` routing and
its rule that a failed send never fails the thing that triggered it.

## Operational step - this does nothing until projects are activated

**Every project in the database is `status='created'`.** Verified: `sp-gs-am`, `smoke-test`
and `vision-debug`. On the day this ships, auto-start fires nowhere.

The activate control already exists on the Reviews page and the endpoint is approver-only,
so nothing needs building. But this codebase has twice shipped work that sat inert awaiting
a manual poke - the baseline skills seeding, and the value chain migration - and this is the
third opportunity.

Two things follow:

- Each project must be activated once, by an approver. This is called out again in the plan.
- **The Reviews page shows when a project is not active** - in scope for this project, not a
  follow-up. It sits beside the existing activate control, so the state and its remedy are
  in the same place, and it reads from the `inactive` flag the commit response now returns
  rather than from a second source of truth. The answer to "why did nothing start?" belongs
  on screen, not in a status column with no rendering.

## Testing

The trigger change carries the risk, so it is tested hardest:

- A commit starts every ready downstream crew, **including on re-commit** - the case
  `released` misses and the whole reason for the change.
- A crew with an uncommitted upstream does not start, and appears in `waiting` naming what
  it needs.
- A ready crew already running is skipped, reported in `skipped`, and the commit still
  lands.
- An inactive project starts nothing, and its commit still lands.
- A failure to start does not unwind the commit.
- Completing a crew starts nothing - cascade safety as a test, not an argument.
- A failed run notifies the committer and the reviewers; a successful run notifies only
  reviewers, unchanged.
- Both suppression paths assert on `started` / `skipped` / `waiting`, not merely that a 201
  came back. A test asserting only the status code would pass under every defect this
  project exists to prevent.

**Fixture sizing.** Several of these need a crew with **two** upstreams to discriminate:
`discovery_interviews` depends on both `assessment_design` and `stakeholder_management`. A
single-upstream crew cannot tell "ready" from "its one upstream was just committed", so any
test of partial readiness built on one proves nothing. The two preceding branches each shipped
defects hidden by fixtures too small to distinguish the correct implementation from the bug;
this is where that recurs here.

## Out of scope

Differentials - project 7, which makes the re-run this project enables cheap by scoping
downstream work to what actually changed. Until then a re-run is a full re-run. Jordan's
coverage role, interview delivery, and Casey's synthesis, all unchanged in the roadmap. Any
queue or cancellation mechanism for crew runs. Reading `projects.status` anywhere other than
auto-start - the daily report's activation gate remains unbuilt and is not addressed here.
