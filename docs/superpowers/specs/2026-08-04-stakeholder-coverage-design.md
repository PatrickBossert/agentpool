# Stakeholder Coverage - Design

**Date:** 2026-08-04
**Status:** Approved for planning

Jordan's job, stated as a question: **do we have representatives (a) in programme governance
and (b) in the value-creating activities and their governance?** This makes that question
answerable, continuously, and makes the answer actionable in one place.

Assumes [one script per node](../../decisions/2026-08-04-one-script-per-node.md).

## Problem

Four things stand between Jordan and that question.

**A stakeholder cannot hold the role most of them need.** `LEVEL_OPTIONS` offers L0, L1, L2
and L3. Maya already writes scripts for C, A, F and S - `interview_scripts_c`, `_a`, `_f`,
`_caf` are on disk. The instruments exist for eight roles and the record can express four, so
a customer, a regulator, a frontline worker or a corporate-services respondent cannot be
recorded as such, let alone assigned.

**Assignments cannot survive Alex.** `stakeholder_assignments` joins on `node_label` - free
text - and is scoped to an `orchestration_run_id`:

```sql
orchestration_run_id  INTEGER NOT NULL REFERENCES orchestration_runs(id),
level                 TEXT NOT NULL,
node_label            TEXT NOT NULL,
```

Rename an activity and every assignment to it silently stops matching. Add one and nothing
notices. And because an assignment belongs to a *run*, it is a snapshot of what someone once
decided rather than a standing fact about the project. Every stable-ID guarantee built into
the value chain stops at this table's edge.

**Coverage has no home.** Nothing computes it. Jordan's `stakeholder_engagement_plan` is a
run artefact, so any coverage figure inside it is as old as his last run - and PAM reports
daily.

**A gap and a decision look identical.** On a chain of 80 nodes a real programme interviews
30 to 40 people. Around half the chain is deliberately not interviewed. With no way to say
so, every project reports a permanent shortfall, and a permanent shortfall stops being read.

## Approach

### One entity list, and it is already there

`model.parties` **is** the entity list. A **party** is an entity that contributes to at least
one activity; an entity that contributes to none - an industry regulator, a customer body -
is still an entity and still assignable for C and A roles.

Nothing new is stored. `validate_model` already permits a party with no contributions, and
the grid already renders lanes only for contributing parties, so a regulator appears in the
roster and draws no lane. What is missing is a way to **add** a non-contributing entity: the
grid's party menu only adds a party *to an activity*, which is the wrong gesture for an
organisation that performs none. Alex's Setup gains that, and his runs augment the same list.

Rejected: a second list in Jordan's configuration. We spent a day removing a duplicated party
model; introducing a parallel one for the entities Alex happens not to find would rebuild it.

### Roles: the eight Maya already writes for

The stakeholder's role becomes one of **L0, L1, L2, L3, C, A, F, S**. L0-L3 are seniority
against a node; C, A, F and S are role-shaped and attach to an **entity** rather than to a
position in the hierarchy.

F and S carry a **ground-truth execution rationale** - what actually happens, as against what
the process says - whatever activities the person supports. That is a property of the role
applied to a node's script, not a different kind of script.

### Assignments become facts

`stakeholder_assignments` is rebuilt on the identity the value chain actually has:

| Column | |
|---|---|
| `stakeholder_id` | who |
| `node_id` | the segment, activity or task id - a stable `n`, `n.n` or `n.n.n` |
| `node_level` | `L1`, `L2`, `L3` - which kind of node `node_id` names |
| `party_id` | the entity whose work this is |

`orchestration_run_id` and `node_label` both go. An assignment is a standing fact about the
project, not an output of a run, and it joins on an id that survives a rename.

**A node's owner constrains who may cover it.** `3.1@ISS` is ISS's work, so only an ISS
stakeholder can be assigned to it. The drag-and-drop uses this: valid targets light up,
invalid ones do not accept the drop. The entity list stops being a lookup and becomes a
guard, refusing the most likely assignment error before it is made.

### Coverage, and intent

**Coverage is per node, with no inheritance.** An executive on an L0 script is never asked
the L2 or L3 questions, so covering a chain covers nothing beneath it. Each of the 3 segments,
17 stages and 60 activities needs at least one assigned person of its own.

**Coverage intent** is what makes that number readable. Each node carries an intent:

| Intent | Meaning | Counts as a gap |
|---|---|---|
| `included` (default) | We intend to interview here | Yes, until assigned |
| `excluded` | Deliberately not interviewing, with a stated reason | **No** |

An excluded node is not a shortfall and is not reported as one. It is reported as excluded,
with its reason, so the decision stays visible instead of becoming a silence.

**The reason is required**, for the same argument as a re-baseline: an exclusion nobody
explained is indistinguishable from an oversight six months later, when the only evidence
left is that nobody was assigned.

Coverage is therefore three numbers per level, not one: **assigned**, **unassigned**, and
**excluded**. A programme covering 35 of 80 nodes with 40 deliberately excluded is in good
shape; the same 35 with nothing excluded is not, and one figure cannot tell them apart.

### One calculation, two consumers

Coverage is computed **in the backend, behind one endpoint**, and read by both Jordan's view
and PAM's report. PAM does not read Jordan's output: she reports daily and he runs rarely, so
his artefact would always be the older answer.

Jordan's view gets its immediacy from an optimistic update and a refetch, not from a second
implementation in the browser. Two implementations of one calculation disagree the first time
either changes - which happened twice in one day to the milestone lateness arithmetic.

### Jordan's tab: a view, not an artefact

The coverage map is **derived, not stored**. Alex adds an activity and it appears as a gap
immediately, with no run by anyone. That is the whole point: a stored answer to "who covers
what" is wrong the moment the chain changes, and nothing says so.

The tab shows:

- **The governance team** - who holds programme governance roles, with their responsibilities.
  This is question (a), and it is answered by role rather than by node.
- **The value chain as a tree**, each node showing its assignments, its owning party, and its
  intent.
- **The stakeholder directory**, from which people are **dragged onto nodes**.
- **Both kinds of gap highlighted** - a node with nobody on it, and a stakeholder assigned to
  nothing. The second matters as much as the first: someone in the directory covering nothing
  is either mis-recorded or was never needed.

**Jordan's run stops producing the map.** It produces what genuinely needs reasoning - who to
approach, in what order, and the comms that go with it. If he is never run, coverage still
works.

**A gap never blocks anything.** It is an issue PAM reports, and the programme proceeds.

## What this does not change

Maya's scripts stay one-per-node and complete. Taylor's invitations, the interview delivery,
and the value chain model itself are untouched. Nothing here requires a crew run to stay true.

## Testing

**Roles and entities:**
- A stakeholder can be recorded as each of the eight roles, and assigned in each.
- An entity with no contributions can be added and assigned for C and A, and draws no lane in
  the grid. A fixture where every entity contributes cannot distinguish "entities" from
  "parties" at all.

**Assignments:**
- An assignment survives a rename of its node's label. This is the defect the current schema
  has, so it is the test that must exist.
- An assignment to a node owned by another party is refused. Asserting a valid one is accepted
  proves nothing about the guard.
- Assignments are not scoped to a run: one made before a run is still there after it.

**Coverage:**
- A node with no assignment is a gap; with one, it is not.
- An **excluded** node is not a gap, and is reported separately rather than not at all. A test
  asserting only that it is absent from the gap count would pass on an implementation that
  simply hides it.
- Excluding without a reason is refused.
- Coverage does not inherit: a person on `2` leaves `2.4` uncovered. A fixture assigned at
  every level cannot tell an inheriting implementation from a correct one.
- The same calculation is what PAM reports - asserted through the endpoint both read, not by
  comparing two implementations.

**The view:**
- A node added to the model appears as a gap with no run and no re-fetch of any artefact.
- A stakeholder assigned to nothing is highlighted.

## Out of scope

Maya generating scripts incrementally when Alex changes an activity - real, and its own piece
of work. Taylor's invitation set being a query over the uninvited rather than an event.
Per-person interview assembly, which the decision record covers. Anything about how interviews
are conducted or synthesised.
