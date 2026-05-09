# SP10e — Dashboard Retheme, Org Chart, and Interview Tracking Design

## Overview

Three related improvements shipped as one sprint:

1. **Style makeover** — swap brand accent tokens from purple to Future Edge teal/green across the entire app
2. **Dashboard redesign** — replace crew progress cards with a vertical org chart + live info card (upper half) and review queue (lower half)
3. **Interview tracking** — campaign-linked stakeholder interview management with import/export workflow, reminder generation, and agent synthesis

---

## 1. Colour System

### Approach

Option B: keep existing dark charcoal surfaces, swap only brand accent tokens.

**Unchanged surface tokens (`ui/tailwind.config.js`):**

| Token | Value | Role |
|---|---|---|
| `surface` | `#1a1825` | App background |
| `surface-raised` | `#221f33` | Header / Sidebar |
| `surface-card` | `#2a2640` | Cards / panels |

**Changed brand tokens:**

| Token | Old | New | Role |
|---|---|---|---|
| `brand` (DEFAULT) | `#7c6af7` | `#19d4e8` | Primary accent — Future Edge teal |
| `brand-light` | `#c4b8ff` | `#7eedf6` | Logo, headings |
| `brand-dark` | `#5b4ed6` | `#0fa8b8` | Hover / pressed states |
| `brand-green` | *(new)* | `#47c247` | Secondary accent — Future Edge green |

### Scope of changes

Every file using `text-brand*`, `bg-brand*`, `border-brand*`, or `text-sky-*` / `border-sky-*` (used in AppLayout for active nav state) must be updated. A grep-first task will identify all affected files before touching any of them.

`text-sky-300 border-sky-300` in `AppLayout.tsx` (active nav link) maps to the new brand teal.

---

## 2. Dashboard Redesign

The Dashboard page (`ui/src/pages/Dashboard.tsx`) is replaced entirely. Layout:

```
┌─────────────────────────────────────────────────────┐
│  Org Chart (left, ~55%)   │  Info Card (right, ~45%) │
│                           │                           │
│  [PAM]                    │  Current agent / task     │
│    │                      │  Progress bar             │
│  [D][VD][Arch][Del][BP]   │  Live log stream          │
│                           │                           │
├───────────────────────────┴───────────────────────────┤
│  Review Queue                                         │
└───────────────────────────────────────────────────────┘
```

### 2.1 Org Chart

**PAM node** — always at top.
- Active run: teal border (`border-brand`), pulsing dot indicator
- Idle: 55% opacity, no border, "Pipeline idle" label

**Five crew nodes** (horizontal row below PAM, connected by lines):
- `discovery`, `value_design`, `architecture`, `delivery`, `business_plan`

**Crew node states:**

| State | Visual |
|---|---|
| `completed` | Green left-border, faint green background tint, ✓ icon |
| `running` | Teal border, pulse dot; expands below to show agent sub-nodes |
| `queued` | 55% opacity, no border |
| `idle` (no run) | 55% opacity, all crews |

**Agent sub-nodes** (shown only for the active crew):
- Each crew has a hardcoded ordered list of its agents (3–4 per crew)
- Status derived from crew status + WebSocket log parsing: completed agents show ✓, in-progress shows ▶, pending shows ○
- Agent names stored as a constant map in the component: `CREW_AGENTS: Record<string, string[]>`

**Discovery crew badge:**
When a campaign is active (interview window open), the Discovery node shows a small completion badge: `"47 / 120 ✓"` derived from stakeholder interview_status counts.

### 2.2 Info Card

Shown alongside the org chart on the right.

**Active run state:**
- Crew name (h3), active agent name (body), current task description (2-line truncated)
- Progress bar: `completed_agents / total_agents` for the active crew
- Live log stream: last 10 lines from `useWebSocket(slug)`, auto-scrolling, monospace, muted text, timestamp prefix
- If interviews active: inline row "Stakeholder interviews: 47 / 120 complete"

**Idle state:**
- "No pipeline running" heading
- Last run: date + total duration (from run history API)
- "Run Pipeline →" button with teal glow (`box-shadow: 0 0 12px rgba(25,212,232,0.4)`)

### 2.3 Data sources

| Data | Source |
|---|---|
| Crew run status | `GET /projects/{slug}/status` → `status.crew_runs[]` |
| Live log lines | `useWebSocket(slug)` (existing hook) |
| Review queue items | `GET /projects/{slug}/reviews` (existing) |
| Last run summary | `GET /projects/{slug}/runs` → first item |
| Interview completion | New: `GET /projects/{slug}/interview-summary` |

---

## 3. Interview Tracking

### 3.1 Data model

**New `campaigns` table:**

```sql
CREATE TABLE campaigns (
    id          INTEGER PRIMARY KEY,
    project_slug TEXT NOT NULL,
    value_stream_name TEXT NOT NULL,   -- matches string from discovery output
    listenlabs_campaign_id TEXT,       -- manually entered
    campaign_name TEXT,
    interview_start DATE,
    interview_close DATE,
    findings_summary TEXT,             -- raw import from ListenLabs (plain text or JSON string)
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**New `interview_responses` table:**

```sql
CREATE TABLE interview_responses (
    id              INTEGER PRIMARY KEY,
    stakeholder_id  INTEGER NOT NULL REFERENCES stakeholders(id),
    campaign_id     INTEGER NOT NULL REFERENCES campaigns(id),
    raw_data        TEXT NOT NULL,     -- JSON blob, structure determined by ListenLabs export
    imported_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Additions to existing `stakeholders` table:**

`country_code` already exists in the frontend `Stakeholder` type (`ui/src/types.ts`) but is absent from `api/models.py` and the DB. It is added here to close that gap.

```sql
ALTER TABLE stakeholders ADD COLUMN country_code TEXT;      -- ISO country code (e.g. 'GB', 'US')
ALTER TABLE stakeholders ADD COLUMN interview_status TEXT   -- 'invited'|'completed'|'reminded_1'|'reminded_2'
    DEFAULT 'invited';
ALTER TABLE stakeholders ADD COLUMN interview_invited_at TIMESTAMP;
ALTER TABLE stakeholders ADD COLUMN interview_completed_at TIMESTAMP;
```

### 3.2 API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/projects/{slug}/campaigns` | List all campaigns for project |
| `POST` | `/projects/{slug}/campaigns` | Create campaign |
| `PATCH` | `/projects/{slug}/campaigns/{id}` | Update campaign (link ID, dates, name) |
| `DELETE` | `/projects/{slug}/campaigns/{id}` | Delete campaign |
| `GET` | `/projects/{slug}/campaigns/{id}/export-targets` | Download interview targets CSV |
| `POST` | `/projects/{slug}/campaigns/{id}/import-progress` | Upload progress CSV |
| `POST` | `/projects/{slug}/campaigns/{id}/import-results` | Upload individual results (CSV or JSON) |
| `POST` | `/projects/{slug}/campaigns/{id}/import-summary` | Upload findings summary (plain text or JSON) |
| `POST` | `/projects/{slug}/campaigns/{id}/generate-reminders` | Create reminder review-queue items |
| `POST` | `/projects/{slug}/campaigns/{id}/synthesise` | Trigger agent synthesis of imported results |
| `GET` | `/projects/{slug}/interview-summary` | Aggregate completion counts across all active campaigns |

### 3.3 Export — Interview Targets CSV

`GET /projects/{slug}/campaigns/{id}/export-targets` streams a CSV:

```
name,email,country_code,value_stream,campaign_id
Jane Smith,jane@corp.com,GB,Digital Transformation,camp_abc123
...
```

Rows: all stakeholders for the project where `interview_status IN ('invited','reminded_1','reminded_2')` (i.e., not yet completed). Country (`country_code`) defaults to empty string if not set on the stakeholder record.

### 3.4 Import — Progress CSV

`POST /projects/{slug}/campaigns/{id}/import-progress` — multipart file upload.

Expected columns: `email, status` (values: `completed` or `pending`/anything else).

For each row: find stakeholder by email, update `interview_status` to `completed` and set `interview_completed_at = now()` if status is `completed`. Unknown emails are silently skipped. Returns `{ updated: N, skipped: M }`.

### 3.5 Import — Individual Results

`POST /projects/{slug}/campaigns/{id}/import-results` — multipart file upload (CSV or JSON).

File is parsed to extract a list of per-respondent records. Each record requires an `email` field to match to a stakeholder. The remainder of the record is stored as a JSON blob in `interview_responses.raw_data`. No schema enforcement beyond email presence.

Returns `{ imported: N, unmatched: M }`.

### 3.6 Import — Findings Summary

`POST /projects/{slug}/campaigns/{id}/import-summary` — multipart file upload (plain text or JSON).

Raw file content stored as-is in `campaigns.findings_summary`. Displayed read-only in the UI. Returns `{ ok: true }`.

### 3.7 Agent Synthesis

`POST /projects/{slug}/campaigns/{id}/synthesise` triggers a background task:

1. Fetch all `interview_responses.raw_data` for the campaign (JSON blobs)
2. Concatenate into a structured prompt context
3. Pass to the existing discovery crew's value chain mapper with an additional `interview_findings` context block
4. Store output as a crew run result (normal run flow)

The prompt context format is intentionally loose — the agent is instructed to interpret the raw data and extract themes, not parse a specific schema.

### 3.8 Reminder Generation

`POST /projects/{slug}/campaigns/{id}/generate-reminders` evaluates each non-completed stakeholder:

- `days_since_invite = now() - interview_invited_at`
- 1–7 days: gentle template
- 8–14 days: firm template
- 15+ days: urgent template

Each creates a `review_queue` item of type `reminder_email` with:

```json
{
  "type": "reminder_email",
  "to_name": "Jane Smith",
  "to_email": "jane@corp.com",
  "subject": "<template subject>",
  "body": "<template body with name merged in>",
  "escalation_level": "gentle|firm|urgent"
}
```

Templates are server-side constants (no UI to edit templates yet).

### 3.9 Discovery page — Interviews section

New section below existing Research Brief / Links / Documents panels.

For each campaign row:
- Campaign name (editable inline) + ListenLabs Campaign ID field
- Interview window: start + close date pickers
- Completion bar: `completed / total` with percentage
- Action buttons: "Download Targets", "Import Progress", "Import Results", "Import Summary", "Generate Reminders", "Synthesise Findings"
- Findings summary: read-only textarea below the campaign row, shown if `findings_summary` is non-empty
- "+ Link Campaign" button at bottom of section to create a new campaign and link a value stream

Value stream names are populated from the discovery output (read from the existing `value_chain.json` output file if present, otherwise free-text entry).

---

## 4. Review Queue — Reminder Email Type

The existing review queue gains a new item type. No changes to the queue listing page structure — `reminder_email` items appear inline alongside existing review types.

**Reminder item display:**
- Header: "Reminder Email — {escalation_level}" badge + stakeholder name
- To: `{name} <{email}>`
- Subject: editable text input (pre-filled from template)
- Body: editable textarea (pre-filled from template, name already merged)
- Actions: "Approve & Send" / "Edit" / "Dismiss"

**"Approve & Send":** marks item approved and calls a send endpoint. Email delivery via server-side SMTP or SendGrid — implementation detail deferred to the plan (depends on environment config). For now the endpoint can log the send and mark sent without actually delivering, with a `SMTP_` env var gate.

---

## 5. Files Affected

### New files
- `api/routers/campaigns.py` — all campaign endpoints
- `api/services/campaign_service.py` — business logic (export, imports, reminder generation)
- `agents/tasks/synthesise_interviews.py` — synthesis background task
- `ui/src/pages/Discovery.tsx` — Interviews section added (file already exists, substantial additions)
- `ui/src/components/OrgChart.tsx` — new component
- `ui/src/components/InfoCard.tsx` — new component
- `ui/src/api/campaigns.ts` — API client for campaign endpoints
- `tests/test_campaigns.py`
- `tests/test_interview_imports.py`

### Modified files
- `ui/tailwind.config.js` — brand token swap
- `ui/src/pages/Dashboard.tsx` — full rewrite
- `ui/src/components/AppLayout.tsx` — active nav colour class update
- `api/models.py` — `Campaign`, `InterviewResponse` models; `Stakeholder` gains 4 new fields
- `api/database.py` — new tables + ALTER statements
- `api/main.py` — include campaigns router
- `ui/src/types.ts` — `Campaign`, `InterviewResponse` types; `Stakeholder` updated
- `ui/src/pages/Reviews.tsx` — render `reminder_email` item type
- All pages using `text-brand`/`bg-brand` purple classes (identified by grep at plan time)

---

## 6. Out of Scope

- Live ListenLabs webhook integration (deferred; polling endpoint can be added later without schema changes)
- Template editing UI (reminder copy is server-side constants for now)
- Multi-language interview copy in reminders (country is passed in export for ListenLabs to handle; our reminders are English-only for now)
- Automated email delivery without SMTP env var configuration
