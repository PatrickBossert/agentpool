# The pipeline from Jordan to Blake - agent briefs

**Date:** 2026-09-04
**Status:** draft for review. Records Patrick's brief of 2026-09-04 verbatim in intent, with
implementation observations marked as such.

## Why this exists

Six agents between the value chain and the portfolio have briefs written before the pipeline had
been run end to end. Jordan's is too broad and has legacy interview-session work in it; Taylor's
produces a plan rather than running the process. This records what each is actually for, so the
next build is measured against it.

Every name below is an existing agent. Nothing here is new construction except the second
interviewer.

| Name | `agent_id` |
|---|---|
| Jordan Williams | `stakeholder_manager` |
| Taylor Brooks | `interview_coordinator` |
| Avery Singh | `stakeholder_interviewer` |
| Casey Liu | `synthesis_analyst` |
| Quinn Harper | `value_proposition_generator` |
| Blake Anderson | `portfolio_manager` |

## Jordan - the stakeholder tree and the comms conduit

**Owns:** the stakeholder tree (organisation, level, name, role) and its assignment to the value
chain. The assignment is a **manual drag-and-drop setup task** - stakeholders dropped onto
branches of the value chain tree. There is not enough information for an agent to do this work.

**Is:** the conduit for participant stakeholder communications on behalf of every other agent,
and the owner of overall programme comms at the beginning, middle and end. **Nature, timing and
triggers are deferred** - not designed here.

**Must lose:** everything to do with interview sessions. His current task reads
`interview_sessions`, identifies who is uninvited, and drafts invitations - all of it Taylor's,
all of it to be linted out. He holds `InterviewSessionTool`; after the lint he should not.

That legacy breadth already caused one live defect: his task told him to emit
`{url_base}/{session_token}` when he has no route to a session token, and it was repaired on
3 September only because the URL base was empty and falsy.

## Taylor - runs the interview process to completion

**Purpose:** get as many interviews completed as possible.

Walks the stakeholder tree and issues interview invites to stakeholders assigned to value chain
stages. Invite status and timestamps are stored **against the stakeholder record**.

**Re-running Taylor reconciles**: new assignments join the interview process, removed assignments
leave it. This is a differential, not a fresh plan.

Tracks per stakeholder: invite sent, reminder *n* sent, interview started, interview completed.
Sends the invitation, reminders with increasing urgency, and a completion thank-you.

An invite triggers an interview with Avery or the second interviewer, **using the script
associated with the stakeholder's value chain stage or attribution letter**.

## Avery, and a second interviewer

Conducts the interview using **the voice assigned for the project**. A female interviewer is to
be added; the pairing is per project.

## Casey - themes, with their evidence attached

Collates transcript findings **horizontally and vertically** to identify key themes. **Each theme
carries references back to the transcripts it came from**, so Quinn can reach the detail.

## Quinn - value propositions per theme

Builds a value proposition for each theme, using the referenced transcripts for detail.
Identifies the **potential scale of value** for each proposition using Morgan's value levers.

## Blake - the portfolio view

Takes Morgan's value levers with a **user-set importance ranking** against each, applied in his
Setup, and builds a **2x2 portfolio** and a prioritised list view of the value propositions.

Patrick's note: *"This could be programmatic i.e. agentic reasoning isn't required."*

---

## Implementation observations - mine, not the brief

**Two of these six may not need to be agents.** Blake is named as programmatic in the brief.
**Taylor's is the same shape**: walk assignments, compare against invite state, send what is
missing, chase what is stale, record what came back. That is a reconciliation loop with
templated messages. An agent doing deterministic work costs a model call and introduces
nondeterminism into a process whose value is that it does not miss anybody. The reasoning in
Taylor's brief is thin - "increasing tone of urgency" is three templates.

Worth deciding deliberately rather than by inheritance: **which of these are agents because they
reason, and which are agents because everything else here is one.**

**The schema is further along than expected.** `stakeholders` already carries `interview_status`,
`interview_invited_at` and `interview_completed_at`. Missing for Taylor's brief: reminder counts
and `interview_started_at`.

**`stakeholder_assignments` carries `node_id` and no `script_id`.** Taylor's brief needs "the
script associated with their value chain stage", and the Interview Coordinator currently matches
by `node_label`, storing NULL when a label is ambiguous - already in the tech-debt list. Since
the assignment is a *manual* action, the script id can be recorded at the moment a human makes
it, and the ambiguous match stops being needed rather than being fixed.

**Casey's theme references are the referenceability rule crossing an artefact boundary.** A theme
citing a transcript needs the transcript to have a stable id, and the citation must survive both
being regenerated. This is the same contract as a value chain node id - may grow, may retire,
never redefine or forget - applied to a reference rather than an item.

**Sessions can only be minted by an agent.** No API route creates one, and `insert_interview_
session` has no production caller. If Taylor is to issue invites, either he mints sessions or a
door is built - and if he becomes programmatic, the door is the answer.

## Out of scope, explicitly

The nature, timing and triggers of Jordan's programme comms. Everything downstream of Blake.
The second interviewer's identity and voice assignment.
