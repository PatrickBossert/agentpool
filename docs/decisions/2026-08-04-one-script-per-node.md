# One interview script per node, not per person

**Date:** 2026-08-04
**Status:** Accepted, with a known limitation
**Applies to:** Maya's interview scripts, Jordan's stakeholder mapping, Taylor's invitations,
PAM's coverage reporting

## The decision

An interview script belongs to a **node** - a value chain segment, stage or activity, at its
level - and is complete in itself. It is not a component to be assembled with others.

A stakeholder is assigned to a node and is interviewed with that node's script. One person,
one node, one interview.

## Why, and what it assumes

The schema assumes that **staff in organisations map well onto nodes at different levels of
management seniority**. An L2 stage has someone accountable for it; its L3 activities have
practitioners who perform them. Interviewing a person about the node they own is therefore
the natural unit, and a complete script for that node is the natural instrument.

Where one person appears to span many nodes at one level - say eight L3 activities - the
reading is that they are accountable for the **L2 stage above them**, and they are
interviewed in that capacity with the L2 script. The apparent breadth is a signal about
seniority, not a case for stitching eight L3 scripts together.

## The limitation this accepts

**A person assigned to several nodes at the same level has no single interview.** The schema
has no way to assemble one session from several node scripts, and combining them is not
something the design supports.

In practice this is worked around by choosing *which* nodes to interview rather than
interviewing all of them. On a chain of 3 segments, 17 stages and 60 activities - 80 nodes -
a realistic programme interviews 30 to 40 people, concentrating on the activities where
challenges are already suspected. That is deliberately more than the dozen an
assembled-per-person design would need, and deliberately fewer than all 80: it buys better
coverage and sharper insight than a dozen broad conversations, without pretending every
activity warrants its own session.

**This is a known limitation, accepted for now, not an oversight.**

## What follows from it

**Coverage is measured per node, and full coverage is not the target.** A gap is a node with
nobody assigned; the count is a real measure, but 100% is not what a good programme looks
like. Roughly half the nodes on a typical chain will be deliberately left uninterviewed.

That has a direct consequence for reporting, and it is **not yet built**: there is currently
no way to distinguish *"nobody assigned yet"* from *"deliberately not interviewing this
one"*. Until there is, PAM's coverage figure will report deliberate scoping as a permanent
shortfall, and a permanent shortfall stops being read. A `coverage_intent` on the node - or
an explicit exclusion list - is the smallest thing that fixes it.

**Maya generates a script for every node regardless of assignment.** Scripts derive from the
value chain, not from the stakeholder list, so a stakeholder added late needs no new design
work - the script for their node already exists.

**An interview's rationale can still be role-shaped.** F and S roles carry a ground-truth
execution rationale whatever activities they support; that is a property of the role applied
to the node's script, not an assembly of several scripts.

## Extensibility, if this limitation is ever lifted

Nothing here forecloses per-person assembly. What it would need:

- An **interview session** as a first-class object, distinct from the script - today an
  interview is effectively the script plus a recipient.
- A **session-to-node** relation, so one session can carry several nodes, replacing today's
  implicit one-to-one.
- A rule for **ordering and de-duplicating** sections across the node scripts in a session,
  which is the substantive design problem and the reason this was not attempted now.

The node-keyed scripts written today remain valid inputs to that design. They would become
components without being rewritten, which is why keeping them complete-per-node costs
nothing in the meantime.
