# Milestone Baselines and Slippage - Design

**Date:** 2026-08-04
**Status:** Approved for planning

Makes Progress Against Plan answer the question it is named after. Not a numbered roadmap
project.

## Problem

`project_milestones` holds `due_date`, `status` and `completed_at`. `due_date` is **editable**.

So the moment anyone re-plans after a slip, the original commitment is overwritten, and every
comparison afterwards measures actual against the *revised* plan. **A project that slips four
times and is re-planned four times shows as perfectly on track** - each milestone met the date
it was most recently given. The one number a client asks for is the one the model cannot
produce.

Two further gaps follow from the same root:

- **Slippage is only visible on completed milestones.** Those are the ones that no longer
  matter. The dangerous slip is on work not yet done, whose dates are already wrong and still
  render green because the due date has not arrived.
- **Per-milestone lateness does not answer the reader's question.** "3 days late" on milestone
  3 is a fact about the past. What matters is what it did to milestone 13.

## Approach

### Three dates, two different failures

| Field | Meaning | Editable |
|---|---|---|
| `baseline_date` | What was promised | Set once at activation; changed only by an explicit re-baseline |
| `due_date` | What we currently expect | Yes |
| `completed_at` | What actually happened | Yes |

From them, two measures that are routinely conflated and should not be:

- **Delivery slip** - `baseline_date` → `completed_at` when complete, or → `due_date` while
  outstanding. This is the forecast, and it is what makes drift visible **before** a date
  arrives rather than after.
- **Re-plan** - `baseline_date` → `due_date`. How far the plan itself has moved, regardless of
  delivery.

A milestone can be delivered exactly on its current plan and be three weeks late against what
was promised. A client will ask about both, and one number cannot carry both answers.

### The baseline is set at activation

`POST /{slug}/activate` already exists, is approver-gated, and marks the moment the engagement
formally starts. It copies each milestone's `due_date` into `baseline_date`.

Activation rather than seeding: seeded dates are placeholders that get moved around during
setup, and baselining those would baseline noise. Activation rather than a separate "commit
the schedule" button: an extra deliberate action is one more thing to forget, and a project
with no baseline silently loses the whole feature.

**A milestone with no `due_date` at activation gets no baseline.** It was never promised a
date, and inventing one would manufacture a commitment nobody made.

### Re-baselining is explicit, and never destroys the original

A change request that moves the plan is a legitimate PMO event, so re-baselining exists - but
as its own approver-gated action with a stated reason, not as a side effect of editing a date.

The superseded baseline is written to `milestone_baselines` (`milestone_id`, `baseline_date`,
`superseded_at`, `reason`, `set_by`) before `baseline_date` is overwritten. **The first
commitment is therefore never lost**, which is the whole point of having a baseline at all.

### Work added after activation is not "on time"

A milestone created after activation has `baseline_date` null. It renders as **added scope**,
never as on-plan.

This distinction is load-bearing. A project that adds five milestones and delivers them all
against no baseline has not delivered its plan; it has delivered a different plan. Treating an
absent baseline as "no variance" would report scope growth as success.

### One derivation, three consumers

`milestoneVariance(m, excluded)` returns the state and both measures, computed in working days
with the project's excluded dates - matching every other interval in this schedule. Its
consumers are the milestone list, the on-screen Progress Against Plan, and the exported pack.
Three implementations of the same arithmetic would disagree the first time one changed, which
has already happened once on the export path.

`daysLate` folds into it as the delivery-slip case.

| State | Condition |
|---|---|
| `added_scope` | No baseline |
| `on_plan` | Delivered, or forecast, on or before baseline |
| `late` | Delivered after baseline |
| `at_risk` | Outstanding, current plan already past baseline |
| `recovered` | Re-planned later than baseline, delivered on or before baseline |

`at_risk` is the state the current view cannot express, and the reason for the whole change.

### What Progress Against Plan shows

**A headline figure.** How far the delivery date has moved: the last baselined milestone's
baseline against its actual or current plan. One sentence - *"delivery has moved 7 working
days"* - which is the status report.

**Slip as a length, not a number.** On the Gantt each milestone carries a hollow baseline
marker and a solid actual-or-planned marker on the same axis, with the gap shaded. Five
milestones each slipping two days reads instantly as a staircase drifting right; five badges
reading "2 days late" do not.

**The per-row badge stays**, for the detail beneath. Right granularity for *which one hurt
us*, wrong for *are we in trouble*.

---

## What this does not change

`due_date` stays editable and keeps its meaning - the current plan. `completed_at` keeps
today's stamping behaviour. Nothing about crews, outputs, or reviews.

## Testing

**Setting the baseline:**
- Activation baselines every milestone that has a due date, and no others. A fixture where all
  milestones have dates cannot distinguish "baselines those with a date" from "baselines
  everything", so it needs one without.
- Activating twice does not re-baseline. The second activation of an in-flight project would
  otherwise silently adopt the slipped plan as the promise - the exact failure this exists to
  prevent.
- Editing `due_date` afterwards leaves `baseline_date` untouched. Assert the baseline
  explicitly; a test that only checks the new due date passes while the baseline moves with it.

**Re-baselining:**
- The superseded baseline is readable from `milestone_baselines` afterwards. Asserting only
  that the new baseline took effect proves nothing about whether the original survived.
- A re-baseline without a reason is refused.

**Variance:**
- An outstanding milestone whose current plan is already past its baseline is `at_risk`, not
  `on_plan`. This is the state today's view cannot express, so it is the one test that must
  exist.
- A milestone with no baseline is `added_scope`, not `on_plan`.
- Delivery slip uses `completed_at` when complete and `due_date` when not - a fixture with
  only completed milestones cannot tell the two apart.
- Re-plan and delivery slip differ for a milestone delivered on a revised date: one is zero
  and the other is not.
- Working days honour the excluded set, as `daysLate` already does.

**The headline:**
- End-date movement reads from the last **baselined** milestone, not the last milestone - or a
  single added-scope milestone at the end silently becomes the project's delivery date.

## Out of scope

Automatic re-planning of downstream dates when one slips - the cascade is a judgement, and
guessing it would put dates in front of a client that nobody agreed. Cost or resource
variance. A full baseline-version history in the UI beyond the audit record. Earned value.
