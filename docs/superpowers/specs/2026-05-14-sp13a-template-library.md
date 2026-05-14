# SP13a — Interview & Questionnaire Template Library

## Overview

Introduces a platform-wide template library stored in `system.db`. Templates are reusable across all projects and come in two types: **interview** (qualitative question sets) and **questionnaire** (structured 0–4 maturity assessments). A new Templates UI lets consultants create, edit, and delete both types.

This sprint is a prerequisite for SP13b (node assignment + agent tailoring) and SP13c (assessment in voice interview).

---

## Section 1 — Data model

### `interview_templates` table in `system.db`

```sql
CREATE TABLE IF NOT EXISTS interview_templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    type        TEXT    NOT NULL CHECK(type IN ('interview', 'questionnaire')),
    schema_json TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

Migration runs on startup via the existing `init_system_db` function in `api/database.py`.

### Interview template schema (stored in `schema_json`)

```json
{
  "welcome_message": "Hi {name}, thank you for joining...",
  "closing_message": "Thank you for your time and candour.",
  "sections": [
    {
      "title": "Role & Context",
      "questions": [
        {
          "id": "Q1",
          "text": "Can you walk me through your role and what you're responsible for day-to-day?",
          "follow_up_count": 2,
          "probing_instructions": "Probe for decision authority, team interfaces, key outputs.",
          "follow_up_branches": [
            "What does a typical week look like for you?",
            "Who do you interact with most closely in that role?"
          ],
          "evasion_signals": ["not sure", "it varies", "it depends", "hard to say"]
        }
      ]
    }
  ]
}
```

The `{name}` placeholder in `welcome_message`/`closing_message` is substituted at session creation time with the stakeholder's name.

### Questionnaire template schema (stored in `schema_json`)

```json
{
  "scale": {
    "min": 0,
    "max": 4,
    "labels": {
      "0": "Not Accounted For",
      "1": "Initial",
      "2": "Developing",
      "3": "Managed",
      "4": "Optimized"
    }
  },
  "sections": [
    {
      "id": "S1",
      "title": "Data Governance",
      "description": "Formal structures, policies, roles, and responsibilities for managing data assets",
      "questions": [
        {
          "id": "S1Q1",
          "text": "Our organisation has formal data governance policies and procedures"
        },
        {
          "id": "S1Q2",
          "text": "Data stewardship roles and responsibilities are clearly defined"
        }
      ]
    }
  ]
}
```

---

## Section 2 — Backend API

**File:** `api/routers/templates.py` (new file)
**Prefix:** `/api/templates`
**Auth:** JWT required on all write endpoints; GET endpoints also require auth (consultant-facing only)

### Endpoints

```
GET    /api/templates                  → list all (filter by ?type=interview|questionnaire)
POST   /api/templates                  → create
GET    /api/templates/{id}             → get one
PATCH  /api/templates/{id}             → update name/description/schema_json
DELETE /api/templates/{id}             → delete
```

**Request body for POST/PATCH:**
```json
{
  "name": "Operations Interview v1",
  "description": "General operations stakeholder interview",
  "type": "interview",
  "schema_json": { ... }
}
```

`schema_json` is accepted as either a parsed object or a JSON string; stored as string.

**Response shape (list item):**
```json
{
  "id": 1,
  "name": "Operations Interview v1",
  "description": "...",
  "type": "interview",
  "created_at": "2026-05-14T10:00:00",
  "updated_at": "2026-05-14T10:00:00"
}
```

Full `schema_json` only returned on single-item GET, not in list responses (keeps list fast).

### DB helpers

**File:** `api/database.py`

```python
async def fetch_all_templates(conn, type_filter=None) -> list[Row]
async def fetch_template(conn, template_id) -> Row | None
async def insert_template(conn, name, description, type_, schema_json) -> int
async def update_template(conn, template_id, name, description, schema_json) -> None
async def delete_template(conn, template_id) -> bool
```

All operate on the `system.db` connection (passed in by the router using `get_system_db` dependency).

### `get_system_db` dependency

**File:** `api/database.py`

```python
async def get_system_db():
    async with aiosqlite.connect(settings.system_db_path) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn
```

`system_db_path` is already in `api/config.py` as `./data/system.db`.

### Register router

**File:** `api/main.py`

```python
from api.routers import templates
app.include_router(templates.router)
```

---

## Section 3 — Frontend

### New TypeScript types

**File:** `ui/src/types.ts`

```typescript
export interface TemplateListItem {
  id: number
  name: string
  description: string
  type: 'interview' | 'questionnaire'
  created_at: string
  updated_at: string
}

export interface InterviewTemplateSchema {
  welcome_message: string
  closing_message: string
  sections: {
    title: string
    questions: {
      id: string
      text: string
      follow_up_count: number
      probing_instructions: string
      follow_up_branches: string[]
      evasion_signals: string[]
    }[]
  }[]
}

export interface QuestionnaireScale {
  min: number
  max: number
  labels: Record<string, string>
}

export interface QuestionnaireTemplateSchema {
  scale: QuestionnaireScale
  sections: {
    id: string
    title: string
    description: string
    questions: { id: string; text: string }[]
  }[]
}

export interface TemplateDetail extends TemplateListItem {
  schema_json: InterviewTemplateSchema | QuestionnaireTemplateSchema
}
```

### API client

**File:** `ui/src/api/templates.ts` (new file)

```typescript
const BASE = '/api/templates'

export const listTemplates = (type?: string) =>
  fetch(`${BASE}${type ? `?type=${type}` : ''}`, { headers: authHeaders() }).then(r => r.json())

export const getTemplate = (id: number) =>
  fetch(`${BASE}/${id}`, { headers: authHeaders() }).then(r => r.json())

export const createTemplate = (body: Partial<TemplateDetail>) =>
  fetch(BASE, { method: 'POST', headers: authHeaders('json'), body: JSON.stringify(body) }).then(r => r.json())

export const updateTemplate = (id: number, body: Partial<TemplateDetail>) =>
  fetch(`${BASE}/${id}`, { method: 'PATCH', headers: authHeaders('json'), body: JSON.stringify(body) }).then(r => r.json())

export const deleteTemplate = (id: number) =>
  fetch(`${BASE}/${id}`, { method: 'DELETE', headers: authHeaders() })
```

### Templates page

**File:** `ui/src/pages/Templates.tsx` (new file)

Two tabs: **Interview Templates** | **Questionnaire Templates**

Each tab shows a list of cards with name, description, question count, created date, and Edit / Delete actions.

**Create/Edit modal** — single modal used for both types, toggled by the active tab:

- Name field (text)
- Description field (text)
- For **interview templates**: section builder — add/remove sections, add/remove questions per section. Each question has text, probing instructions, follow-up branches (comma-separated), evasion signals (comma-separated), and follow_up_count.
- For **questionnaire templates**: scale definition (min/max/labels read-only defaulting to 0–4 maturity scale), section builder — add/remove sections, add/remove questions (text only).

Schema is serialised to JSON on save.

### Nav + route

**File:** `ui/src/router.tsx` — add `{ path: 'templates', element: <Templates /> }` as a child of the root layout.

**File:** `ui/src/components/AppLayout.tsx` — add "Templates" nav item with a suitable icon (e.g. `BookOpen`), positioned after Stakeholders.

---

## Section 4 — Files affected

| File | Change |
|---|---|
| `api/database.py` | `init_system_db` migration + 5 DB helpers + `get_system_db` dependency |
| `api/routers/templates.py` | New router — 5 CRUD endpoints |
| `api/main.py` | Register templates router |
| `ui/src/types.ts` | 6 new types |
| `ui/src/api/templates.ts` | New API client |
| `ui/src/pages/Templates.tsx` | New Templates page with tabs + create/edit modal |
| `ui/src/router.tsx` | Add templates route |
| `ui/src/components/AppLayout.tsx` | Add Templates nav item |
| `tests/test_templates_router.py` | New test file — 8 tests |

---

## Task breakdown (4 tasks)

**Task 1 — DB migration + helpers:** `interview_templates` table in `system.db` migration + `get_system_db` dependency + 5 async helpers + tests

**Task 2 — API router:** 5 CRUD endpoints + register in `main.py` + API tests

**Task 3 — Frontend types + API client:** TypeScript types + `templates.ts` client

**Task 4 — Templates page:** Two-tab UI with list, create/edit modal, nav item, route
