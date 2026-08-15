# User administration: one person, one record, rights carried directly - design

**Date:** 2026-08-15
**Status:** agreed, ready for planning
**Scope:** sub-project A of four. B, C, and D are sequenced at the end.

## Why

Authority in this application is currently inferred by matching text. `_caller_matches_stakeholder_flag`
takes the calling account's email, lowercases it, and looks for a stakeholder row carrying the
same address. Nothing enforces that join, and it is the same fragility the script ledger work
spent a branch removing from the interview path.

It is also unreachable in practice. `users` holds **zero rows**, so no login can match anything,
and the function opens with:

```python
if payload.get("role") == "sysadmin":
    return True
```

That branch is doing all the work, and it grants the wrong thing. `sysadmin` is the platform tier
- it administers projects and accounts - while `is_reviewer` and `is_approver` are content rights
on one engagement. Conflating them means whoever can create a user can approve an interview
script.

Two people already hold full rights on `sp-gs-am`:

| | Rights | Reachable |
|---|---|---|
| Patrick Bossert, `patrick.bossert@arup.com` | reviewer, approver | yes |
| Dougie McCrone, no email | reviewer, approver | **no** |

Dougie cannot be notified and cannot be matched, and nothing reports either fact. Notifications
resolve recipients from the stakeholder email, so today a review notice reaches one of two
people and looks like it worked.

## The model

**One authenticated role axis, and it is administrative:**

- **`sys_admin`** - creates projects. A global flag on `users`.
- **`project_admin`** - configures the project and its people. A per-project role.
- **`project_team`** - holds one or more per-project roles: `governor`, `approver`, `reviewer`,
  `participant`.

**`sys_admin` implies `project_admin` on every project, and nothing else.** Without it a newly
created project has no stakeholders and no way to add one - the project would be dead on arrival.
The distinction that matters is not global versus per-project, it is **administration versus
content**: a system administrator may set a project up and appoint its team, and still may not
approve an interview script, because every content right is an explicit flag someone must be
given. That is precisely what the old bypass got wrong.

There is no organisation tier. This is a project-based application that happens to hold
organisation entities within it.

## Three tables, each with one job

**The person is `stakeholders`**, per project. It already holds name, job title, organisation,
email, Slack handle, mobile, timezone, entity, and comms channel - the exact field set a project
user is created with. It gains role flags beside the three it already has:

`is_project_admin`, `is_governor`, `is_approver`, `is_reviewer`, `is_participant`

Boolean columns rather than a JSON list or a join table: the pattern already exists, two rows
already carry data in it, `_notify` already filters on exactly these columns, and the role set is
fixed and small. Migration is additive - the existing flags become role entries with nothing to
rewrite.

**Authentication is `users`**, in the system database, reduced to identity, credentials, and
`is_sys_admin` - the one right that cannot be per-project, because creating a project happens
before there is a project to be a member of.

**The link is `project_memberships`**, which already exists as `user_id` x `project_slug` and
gains `stakeholder_id`. One login, many engagements: one `users` row with a membership per
project, each pointing at that project's own record of the same person.

Authority becomes a walk rather than a match - JWT, user, membership for this slug, stakeholder
row, read the flag. No text comparison anywhere.

**A participant needs no `users` row and no membership.** They exist only as a stakeholder,
reached by interview URL and token exactly as today. That is what makes "everyone except
participant-only authenticates" a structural fact rather than a rule to enforce.

**A `sys_admin` may relate to a project two ways.** Implicitly, by virtue of the global flag -
enough to administer it, but with no stakeholder row, so no address and nothing for PAM to
notify. Or explicitly, as a stakeholder carrying `is_project_admin` - a real member of that
project's life, reachable and countable as a recipient. This matters for test mode, which routes
mail to project admins and therefore needs addresses. The implicit right exists so the first row
can be created at all; the explicit row is how somebody joins the project.

## Invite and authentication

**The trigger is setting a role, not creating a person.** Adding a stakeholder does nothing. The
moment any flag other than `is_participant` is set on a person with no linked login, an invite is
issued. Clearing every non-participant flag revokes access. The rule is a consequence of the data
rather than a step to remember, and it holds whether the person was typed in or bulk-uploaded.

**The invite is a single-use, expiring token**, stored hashed, emailed as a link to a page where
the person sets a password. Accepting it creates the `users` row and the `project_memberships`
link. Until accepted the person is fully usable as a stakeholder and simply cannot log in.

**One live invite per person.** Role changes before acceptance issue no second email - roles are
read at use, not baked into the token. A project admin can **re-issue** the existing invite when
the original is lost, which resends the link and refreshes its expiry rather than creating a
parallel one.

**Password reset uses the same machinery** pointed at a different starting state. Without it, a
forgotten password has no route back: invites are triggered by role changes, so there is no
natural way for an admin to re-trigger one.

**Email is the username.** Already required, already unique in practice, and what somebody will
actually type.

**The session stays a JWT bearer token, made rolling** - thirty days, re-issued on use, so an
active reviewer does not log in twice.

**The login page must carry its destination.** PAM's links are ordinary application URLs, so they
work while a session is live and bounce to login when it is not. A reviewer clicking a link to
one script three weeks later, on a different device, must return to *that script* after logging
in - not to the dashboard, with no idea which of eighty-six they were sent to.

## How roles gate behaviour

**One authority function returning a set.** `caller_roles(slug, payload) -> set[str]` performs the
walk and adds `project_admin` for a `sys_admin`. Every gate becomes a membership test instead of
each caller reimplementing the lookup. `_caller_matches_stakeholder_flag` and its email match are
removed.

**Enforced in the service, not the router.** That is the lesson `record_script_review` already
encodes: the approve gate lives there so a second caller cannot arrive later and bypass it.
Routers translate a refusal into a status code; they do not own the rule.

**Force-approve is explicit and recorded.** An approval on a script with no review stays refused
by default. An approver may override it by sending an explicit acknowledgement, and **the review
event records that it was forced**. Without that, `approved` silently means two different things
- "two people looked at this" and "one person waved it through" - and later nobody can tell which.
The warning in the UI is a courtesy; the audit trail is the point.

**Notifications resolve by role, from the record holding the address.** Reviewers get
crew-completion links, approvers get the approval-due reminder, governors get PAM's reports. The
existing asymmetry is kept deliberately: reviewer notices fall back to approvers when a project
has no reviewers, and approval notices never fall back, because with no approvers there is
genuinely nobody who can approve.

## Migration

`users` is empty, so nothing is being converted - the work is bootstrapping. The two existing
stakeholders keep their `is_reviewer` and `is_approver` flags as role entries. Dougie McCrone has
no email and therefore cannot be invited until one is set; the design surfaces that as a visible
state rather than silent non-delivery, which is what happens today.

## Testing

This codebase has a long record of verifying a property one layer from where it holds, so each of
these is specified at the layer that matters:

- **The authority walk is driven end to end** - a real JWT, a real membership, a real stakeholder
  row - not by calling `caller_roles` with a hand-built payload.
- **A `sys_admin` is refused an approval** on a project where they hold no explicit approver flag.
  This is the property the whole design turns on, and the previous implementation returned `True`
  for exactly this case.
- **Setting a non-participant role issues exactly one invite**, and setting a second role issues
  none - asserted on what was sent, not on what was stored.
- **An invite accepted creates both rows**, and the person can then authenticate; a revoked role
  removes access, driven through login rather than by inspecting the tables.
- **A forced approval is distinguishable from a reviewed one** in `script_reviews` afterwards.
- **A deep link survives a login round trip** - request a protected URL unauthenticated, log in,
  and land on the originally requested URL.
- **Test mode routes to project admins** and reaches nobody else, asserted on the recipient list
  the mailer was handed.

## Sequenced follow-ons, deliberately not in this spec

**B - project settings cleanup.** `crews_enabled` currently holds `['discovery', 'value_design',
'architecture', 'delivery', 'business_plan']`, naming two crews that do not exist and omitting
five that do: the dispatcher knows `discovery_mapping`, `assessment_design`, `requirements`,
`stakeholder_management`, `discovery_interviews`, `value_design`, `capabilities`, `delivery`, and
`business_plan`. Settings also mix project configuration with an Avery-specific follow-up timeout.
Independent of who may edit them.

**C - PAM's reminder duties.** Daily reminders to reviewers and approvers, milestone-driven
deadlines, and "reviews are complete, approval required, three days remaining". Needs A's roles
and B's milestones. Two questions to settle there: who creates the milestone schedule, given that
`project_admin` configures milestones and `governor` completes them; and what "at least one review
per output" means for Maya, where one artefact holds eighty-six separately reviewable scripts.

**D - test mode.** Replaces the hard-coded `dev_mode`, set in project settings, routing all mail
to project admins so an interview invite run can be rehearsed without reaching participants.

## Out of scope

Slack channel access is an operational step the application cannot grant; the most it should do is
record whether the invite was sent, so a project admin can see who is still missing. The mobile
number is stored and unused, reserved for future SMS. Organisation names are not validated against
value chain entities - Jordan's node-assignment tool groups both by entity so `ISS` and `ISS Ltd`
sit side by side and are dragged together.
