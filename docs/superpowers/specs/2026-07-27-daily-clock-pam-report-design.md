# Daily Clock + Pamela's Status Report - Design Spec

**Date:** 2026-07-27
**Sprint:** SP19a (proposed)

---

## Goal

Give the platform a clock, with Pamela's daily status report as its first and only consumer. The report is generated from live project state at 17:00 each day, stored as a versioned artefact so there is an audit trail, summarises what changed since the previous day, and is emailed as a link to the people who need to review it.

This is the first of two specs. The second covers event-driven approval triggers, which is what lets an approved report go out to a wider audience and what lets one crew start when another's output is approved.

---

## Problem

**Nothing in the platform runs on a schedule.** There is no scheduler, no cron, and no recurring job anywhere in the Python codebase. The two n8n workflows are a webhook receiver and a Slack trigger - both inbound, neither a clock. So the parts of the engagement that are inherently time-driven cannot happen at all: a daily management report, or checking which interview reminders are due.

**Pamela's report is ephemeral.** `GET /projects/{slug}/pam-report` computes everything live from milestones, crew runs, agent outputs, human reviews and interview sessions. Risks and issues are derived on each request - there are no `risks` or `issues` tables. That means the report is always current, and also that it has no history: there is no record of what the position was last Tuesday, and no way to say what has changed since.

**"Flag any new risks" is impossible without memory.** Identifying what is *new* requires knowing what existed before. Nothing is stored, so nothing can be compared.

---

## Why the clock is built in-app, not in n8n

n8n is already running in the stack and has a schedule trigger, so it is the obvious candidate. It is the wrong one:

- **n8n's role here is a Slack relay.** `slack_notify.py` and `human_input.py` POST to `N8N_WEBHOOK_URL` to reach Slack. Neither of the two workflows schedules anything.
- **An external clock cannot catch up.** If the machine is asleep or the app is down when the trigger fires, the tick is lost and nothing knows. A scheduler that records its own last-run state in the database sees on the next boot that a job is overdue and runs it.
- **It would be untestable.** A JSON workflow blob sits outside the test suite; the equivalent Python is a small module with unit tests.
- **Docker is not currently installed on the development machine**, so n8n cannot run there at all.

n8n keeps its Slack job. The clock is ours.

---

## Architecture

Three pieces, each small.

### 1. `scheduled_jobs` table in `system.db`

One row per job per project: `(job_name, slug, last_run_at, next_due_at, status, last_error)`. Living in `system.db` rather than each project database means all scheduling is visible in one place, and the scheduler can find due work without opening every project.

### 2. A scheduler in the FastAPI lifespan

Wakes on a short interval, selects rows whose `next_due_at` has passed, and runs them. It also runs **once on boot**, so a restart or a closed laptop lid self-heals: anything overdue runs immediately.

Overdue work is **not backfilled**. If the machine was off for a week, Pamela produces one report, not seven. A backlog of seven identical-looking reports would be noise, and the report describes the position *now*, not a reconstruction of last Wednesday.

### 3. `pam_daily_report` - the only job

Reuses the existing report derivation, compares against the previous stored snapshot, records today's, and notifies. Described in full below.

---

## The job

**Compute.** Call the same code path that serves `GET /{slug}/pam-report`, so the stored artefact and the live view can never disagree.

**Diff.** Compare today's risks and issues against the most recent stored snapshot, keyed on `title` - the field that identifies a risk in the existing derivation (each carries `severity` and `title`). The change summary records:

- risks and issues that appeared since the last report
- risks and issues that have cleared
- milestone RAG changes
- crew runs that completed or failed since the last report

The first ever report for a project has nothing to compare against and says so, rather than reporting every current risk as new.

**Store.** Write the report JSON to `projects/<slug>/outputs/` and record it as a versioned `agent_outputs` row with `agent_name='PAM'` and `output_type='pam_report'`. This gives the audit trail, puts it in Pamela's Outputs tab beside her other artefacts, and gets version history for free.

Note that the async `insert_agent_output` helper does not set `is_current`, unlike the synchronous `insert_agent_output_sync` used by crew tools. The job must set it explicitly so the newest report is the current one.

**Notify.** Email the `governing` and `reviewer` stakeholders a link to the report. Plain text, since that is all the Resend integration currently sends and a link needs nothing more.

---

## What the report contains

The existing derivation already returns overall health, a health summary, milestones with RAG status, crew status, derived risks, derived issues, and an interview tracker. To that this spec adds the **change summary** described above.

The gantt chart needs no new work. The email links to the existing report view, which renders the chart client-side in React, so there is nothing to render server-side and no image pipeline to build. This was the single largest cost in the alternative designs and it disappears entirely by linking rather than embedding.

---

## Email

**Recipients:** stakeholders whose `project_role` is `governing` or `reviewer`.

**Content:** a plain-text message naming the project, the report date, a one-line health summary, the count of new risks and issues, and a link to the report.

**`dev_mode`:** a boolean in the project's `config_json`, exposed through the existing `GET`/`PATCH /{slug}/settings` endpoints. When true, every recipient is replaced by `Patrick@FutureEdge.consulting`. The real recipient list is still computed and included in the message body, so a dev-mode email shows who *would* have received it.

`dev_mode` defaults to **true** for existing and new projects. A scheduler that emails real stakeholders the first time it runs correctly is a worse failure than one that emails nobody.

---

## Roles

Review and approval routing uses the **existing multi-valued engagement-role
columns**, not `project_role`:

| Column | Meaning |
|--------|---------|
| `is_participant` | Attends workshops, surveys or discovery interviews |
| `is_reviewer` | Reviews deliverables and provides sign-off comments before a gate closes |
| `is_approver` | Has authority to formally approve milestone completion |

Pamela's report goes to stakeholders flagged `is_reviewer` or `is_approver`.

An earlier draft of this spec added a fourth value to `project_role`. That was
wrong: `project_role` is single-select, so it cannot express someone who is both a
recipient and a reviewer, and the boolean columns already existed for exactly this
purpose - the stakeholder form even says "A stakeholder may hold all three roles
simultaneously. The PMO uses these to route review requests and approval gates."
Nothing read them until now; this gives them their first consumer.

`project_role` keeps its three values and its own meaning: the stakeholder's
relationship to the engagement.

---

## Parameters

| Setting | Value | Reasoning |
|---------|-------|-----------|
| Schedule | 17:00 daily | As specified |
| Timezone | The server's local time | The platform runs on one dedicated Mac mini. A per-project timezone is a real requirement for international clients, but not for this build - noted as a limitation rather than silently assumed away |
| Tick interval | 15 minutes | Fine enough that a 17:00 job runs by 17:15, coarse enough to be invisible |
| Catch-up | Run once on boot if overdue | No backfill |
| Diff key | Risk/issue `title` | The field that identifies a risk in the existing derivation |

---

## Error handling

| Failure | Behaviour | Reasoning |
|---------|-----------|-----------|
| The job throws | Record `status='failed'` and the error on the row, schedule the next run normally | One bad day must not stop the schedule |
| Email send fails | The report is still generated and stored; the failure is recorded | The audit trail matters more than the notification, and a stored report can be re-sent |
| A project has no `governing` or `reviewer` stakeholders | Generate and store, skip the email, record why | Silence here should be explainable, not mysterious |
| The scheduler itself throws | Log and continue to the next tick | The scheduler must not be able to kill the app |

Because the platform runs as a single process, an in-flight guard - marking the row `running` with a start stamp, and updating status conditionally so a completion cannot overwrite a terminal state - is enough to prevent overlapping runs. This is the same conditional-update discipline that the crew-run status work needs.

---

## Testing

Unit tests, with the clock and email boundaries mocked - no waiting on real time and no real sends.

**Scheduler**
- Selects only rows whose `next_due_at` has passed
- Runs an overdue job exactly once on boot and does not backfill
- A failing job records the error and does not block the next tick
- A job already marked `running` is not started again

**Change detection**
- A risk present in both snapshots is not reported as new
- A risk present only today is reported as new
- A risk that has cleared is reported as resolved
- The first report for a project reports no changes rather than everything

**Tokenised access**
- `require_any_auth`, `require_org_admin_or_above` and `require_sysadmin` each reject a token carrying a `scope` claim
- `require_report_access` accepts a normal session
- `require_report_access` accepts a `report:read` token whose slug matches, and rejects one whose slug does not
- Exchange rejects an expired token, a revoked token, and an unknown token
- A successful exchange records `last_used_at`

**Report job**
- The stored artefact is recorded as a versioned `agent_outputs` row with `is_current` set
- Email recipients resolve to `governing` and `reviewer` stakeholders only
- With `dev_mode` true, the send goes only to the dev address and the body still names the real recipients
- With no eligible stakeholders, the report is stored and no send is attempted

---

## Tokenised report access

Recipients must be able to open the report without an account. The link therefore
carries a scoped, expiring access token.

### The hard boundary

**The token grants read access to one project's reports and nothing else. It must
never authorise approval.** Reading a status report and approving one are
categorically different acts: in Spec 2 an approval triggers a wider send to
`recipient` stakeholders, so a forwarded email that could approve would be a
forwarded email that could publish to the client's board.

This is not merely a policy statement, it is the single most dangerous
implementation detail in this spec. `require_any_auth` today returns any valid
token unconditionally:

```python
def require_any_auth(payload: dict = Depends(get_token_payload)) -> dict:
    """Any valid token - just verifies authentication."""
    return payload
```

A report token minted with `create_access_token` would satisfy it, and would
therefore unlock every endpoint guarded by it - documents, stakeholders, outputs,
the lot. So:

- report tokens carry a `scope` claim of `report:read` plus the `slug` they apply to
- `require_sysadmin`, `require_org_admin_or_above` and `require_any_auth` all
  **reject any token carrying a `scope` claim**
- a new `require_report_access(slug)` dependency accepts either a normal session
  or a `report:read` token whose `slug` matches the path

Failing to add the rejection turns a read-only report link into full project read
access. A test asserts each existing dependency rejects a scoped token.

### The token in the URL fragment

The emailed link is:

```
{public_url}/dashboard/report/{slug}#t=<token>
```

The token sits in the **fragment**, which browsers never transmit to a server. It
therefore cannot appear in Caddy, Cloudflare or uvicorn access logs, and cannot
leak through a `Referer` header. The SPA reads `location.hash`, exchanges it once
via `POST /projects/{slug}/report-access/exchange`, receives a short-lived
`report:read` session, and clears the hash from the URL.

This is deliberately different from the existing interview tokens, which sit in
the path (`/interview/:sessionToken`) and are consequently logged. The realistic
way tokens leak is not attackers guessing UUID4s - it is tokens sitting in log
files and analytics that nobody remembers are collecting them. Worth back-porting
to the interview links later.

### Issuance, expiry and revocation

A `report_access_tokens` table records `(token, slug, stakeholder_id, expires_at,
revoked_at, created_at, last_used_at)`.

- **Per recipient.** Each stakeholder gets their own token, so revocation is
  surgical and a leaked link identifies who forwarded it.
- **Expires after 30 days.** A stale link stops working rather than living forever.
- **Revocable** by setting `revoked_at`. Exchange rejects revoked or expired tokens.
- **`last_used_at`** records access, which doubles as a read receipt.

Tokens are generated with `secrets.token_urlsafe`, not `uuid4` - they are
credentials, and should come from a cryptographic generator.

### Security headers

The app registers only `CORSMiddleware` today. This adds `Referrer-Policy:
no-referrer` so that even the non-fragment parts of report URLs cannot leak
through outbound links.

### Why this is safer than the alternative

A PDF attachment - the format originally considered for sealing the report -
cannot be expired, cannot be revoked, tells you nothing about who opened it, and
is forwardable without limit. A scoped link is strictly more controllable on every
one of those axes. The residual risk is that a recipient forwards the email and a
colleague reads status reports until the token expires or is revoked, which is the
same exposure as forwarding a PDF, with a kill switch attached.

---

## Scope

**Included:** the `scheduled_jobs` table, the scheduler, the `pam_daily_report` job, change detection, storage as a versioned output, the plain-text email with a link, the `dev_mode` flag, the `reviewer` role, and tokenised report access with its scope rejection, fragment exchange, expiry, revocation and `Referrer-Policy` header.

**Explicitly excluded:**

- **The approval loop.** Pamela's report going to the PM for approval and then out to `recipient` stakeholders is Spec 2, because it needs the event-driven approval trigger. Until then the report goes to `governing` and `reviewer` only.
- **A second clock consumer.** Taylor Brooks's reminder-due checks and Jordan Williams's invitations wait for Spec 2's idempotency guarantees. A scheduler that re-invites stakeholders is worse than no scheduler.
- **PDF sealing.** The final approved report as an attached PDF is worth doing, but comes after the approval loop exists to define what "final" means.
- **Slack.** The n8n relay already exists; wiring Pamela's report to it is a later step.
- **Per-project timezones.**
- **Backfilling missed days.**

---

## Known consequences

**The first real send is the risky one.** Everything up to that point is reversible; an email is not. `dev_mode` defaulting to true is the guard, and turning it off should be a deliberate act with the recipient list checked first.

**A daily report on a project where nothing happens will say so, every day.** That is honest but may become noise. Whether an unchanged day should send at all is worth revisiting once there is real usage - the change summary makes it cheap to decide later.
