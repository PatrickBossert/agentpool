# Naming an engagement's first approver - scope

**Date:** 2026-09-26
**Status:** scoped, not approved. Three decisions below change the shape of the work.

## The problem, measured

A newly created engagement has **nobody who can approve anything**. `caller_roles` walks
`JWT → users → project_memberships → stakeholders` and returns `set()` unless all three rows
exist; a fresh project has zero stakeholders, so the walk reaches nothing for anybody. The first
`HumanInputTool` gate is therefore unopenable, and it times out after 24 hours.

`is_sys_admin` bootstraps the **administration** axis for exactly this reason and deliberately
implies nothing about **content** - both halves correct, and together they leave the hole.
`helia-digital-tau` met it on its first day: Alex's value chain sat waiting, Morgan could not
start, and the Approve button answered 403 into a handler with no `catch`.

**The seeding fix that looks obvious does not work**, and this is the measurement that shapes
everything below. `POST /auth/login` matches `ADMIN_USERNAME` from the environment *before* it
reads `users`, so the built-in administrator has **no `users` row at all** and `caller_roles`
returns at step **one**. A seeded stakeholder is the walk's **last** step. Creating one for the
creator moves their authority not at all - driven over HTTP, 201 with the flags confirmed set,
and `can_approve` still `false`.

Naming a **person** works because the invite loop builds all three rows: `issue_invite` →
`/auth/accept` creates the `users` row (or grants membership to an existing login, minting no
session) and the `project_memberships` row naming the stakeholder. That is the path the owner
was unblocked by, by hand.

## What changes

| File | Change |
|---|---|
| `api/models.py` | `ProjectCreate` gains the approver field(s) |
| `api/services/project_service.py` | `create_project` writes the stakeholder and issues the invite |
| `ui/src/api/endpoints.ts:66-71` | the payload type declares three fields; gains the new ones |
| `ui/src/components/NewProjectModal.tsx:39` | sends them; new form field(s) |
| `tests/test_project_service.py`, `tests/test_secure_mode_routing.py` | two files construct `ProjectCreate` |

**The blast radius is small, and smaller than it looks.** `ProjectCreate` has eight fields of
which the modal sends three; the rest default. This is **not** the `ProjectSettings` hazard
CLAUDE.md records - that type has 38 fields, 22 declared required, and five call sites spreading
a fetched row. `ProjectCreate` has one UI caller and one API door.

**No backfill is needed on this deployment.** Both registered projects now carry an approver with
a membership (`sp-gs-am` 2, `helia-digital-tau` 1). A general deployment might; that is a
`scripts/` script rather than a migration, following `backfill_project_registry.py`'s precedent -
`get_connection(slug)` would materialise a database for every probe slug.

## Decisions that change the work

### 1. Creation, or first run? (the one worth arguing)

The ask is a required field at creation. The alternative is to leave creation alone and refuse
**the first crew run** until an approver exists.

- **At creation**: the hole cannot be reached. Cost: a consultant spinning up a project to try
  something must name an approver before they have one, on every project for ever - and a
  required field people resent is a field they fill with `a@b.c`.
- **At first run**: the field is needed exactly when it matters, creation stays a three-field
  form, and the refusal can name the remedy. Cost: the dead end still exists until somebody
  runs a crew, and a run refused after a consultant has uploaded documents is a worse moment to
  be told than a form field.

**Recommendation: at creation.** The first run is where the *consequence* lands, but the
approver is a fact about the engagement rather than about the run, and this session has spent a
day on failures that were only visible late. A project with no named approver is not a
configured engagement.

### 2. Email only, or name and email?

A stakeholder row wants a name, and every roster, notification and invite reads it. Email alone
yields a nameless approver in the client's own correspondence.

**Recommendation: both, both required.** One extra input against a row that is read by people.

### 3. What fails the creation?

CLAUDE.md's standing rule is that *a side effect must not veto the thing it is a side effect of*.
The approver is **not** a side effect here - it is the reason for the change - so the rule points
the other way, and the two halves separate:

- **The stakeholder write failing must fail the creation.** Succeeding without it creates exactly
  the dead end this closes, and answers 201.
- **Delivery failing must not.** The token is recoverable through `resend-invite`, which is how
  the owner was unblocked, and a transient mail failure should not cost an engagement.

**Recommendation: as above**, and the response should carry the invite state so a consultant
knows whether to chase it.

## Smaller things that still need deciding

- **Validation.** There is **no email validator anywhere in this codebase** - the stakeholder door
  refuses a privileged role with *no* email (`"email is required to invite a stakeholder holding a
  role beyond participant"`) and does not check the shape. A typo'd approver address is a dead end
  that *looks* closed, which is worse than the field's absence. Minimal shape validation belongs
  here, and it is the first such check in the product.
- **Idempotency.** `create_project_endpoint` answers **200** to a re-POST of an existing slug. It
  must not create a second approver stakeholder or re-issue an invite on that path.
- **The approver may be the creator.** Naming yourself is legitimate and common on a consultancy
  deployment. It works: an email that already has a login gets a membership grant and no session.
- **`dev_mode` defaults to `True`**, so project mail is held and redirected to the operator. An
  invite issued at creation on a dev-mode deployment reaches the consultant rather than the
  approver - correct, and worth saying in the response rather than leaving to be discovered.

## Not in scope

Widening any content gate; changing `caller_roles`; a UI for managing approvers beyond the
existing Stakeholders tab; notifying anybody that a gate is waiting (that is the SP50-era gap and
is its own task, and the health registry is now the natural home for it).

## Size

Roughly a half-day: one model field pair, one service write, one modal field pair, two test
constructors, and the tests that matter - **a project created from nothing whose first HITL gate
is resolvable by the person named at creation, driven over HTTP.** A unit test of the predicate
would not have caught the defect that started this.
