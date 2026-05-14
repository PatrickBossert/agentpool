# SP13b — Node Template Assignment + Agent Tailoring

## Overview

Enables consultants to assign an interview template and a questionnaire template to each value chain node. The Interview Script Designer uses the assigned interview template as its starting point, tailors it to node context, and completes the existing HITL approval loop. The session response is extended to include the questionnaire schema so the assessment phase (SP13c) can render it. A publish-back endpoint lets consultants save a tailored script back to the template library.

**Depends on:** SP13a (template library in system.db)

---

## Section 1 — Data model

### `node_template_assignments` table in per-project DB

Migration added to `api/database.py` via `_migrate_node_template_assignments`:

```sql
CREATE TABLE IF NOT EXISTS node_template_assignments (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id                INTEGER NOT NULL REFERENCES projects(id),
    node_label                TEXT    NOT NULL,
    interview_template_id     INTEGER,
    questionnaire_template_id INTEGER,
    created_at                TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, node_label)
);
```

`interview_template_id` and `questionnaire_template_id` reference `interview_templates.id` in `system.db`. No DB-level FK (cross-DB), enforced by application logic.

### DB helpers

**File:** `api/database.py`

```python
async def fetch_node_template_assignments(conn, project_id) -> list[Row]
async def upsert_node_template_assignment(
    conn, project_id, node_label,
    interview_template_id, questionnaire_template_id
) -> None
```

---

## Section 2 — Backend API

### New endpoints in `api/routers/projects.py`

```
GET  /api/projects/{slug}/node-templates
     → list all node assignments for the project

PUT  /api/projects/{slug}/node-templates/{node_label}
     → upsert assignment for a single node

POST /api/projects/{slug}/node-templates/{node_label}/publish
     → publish the tailored interview script for this node back to the template library
```

**GET response (list item):**
```json
{
  "node_label": "Goods-in Inspection",
  "interview_template_id": 2,
  "questionnaire_template_id": 5
}
```

**PUT request body:**
```json
{
  "interview_template_id": 2,
  "questionnaire_template_id": 5
}
```
Either field may be `null` to clear the assignment.

**POST /publish request body:**
```json
{
  "name": "Operations Interview — Goods-in Tailored",
  "description": "Node-tailored script for Goods-in Inspection based on Ops Interview v1"
}
```

Publish steps:
1. Read `{projects_dir}/{slug}/outputs/interview_scripts.json`
2. Extract the entry keyed by `node_label`
3. Strip node-specific fields (`node_label`, `level`, `research_brief`, `study_objectives`) — keep only the interview template fields (`welcome_message`, `closing_message`, `sections`)
4. Call `insert_template` in `system.db` with `type='interview'`, the provided `name`/`description`, and the stripped schema
5. Return `{"template_id": <new_id>}`

Returns 404 if `interview_scripts.json` doesn't exist or the node_label key is absent.

### `get_system_db` dependency

Required by the publish endpoint (and internally by GET/PUT for cross-DB template lookups). See SP13a — same dependency defined in `api/database.py`.

---

## Section 3 — Agent updates

### Interview Script Designer — template-aware tailoring

**File:** `agents/discovery/interview_script_designer.py`

The task description is extended to accept a `node_templates` dict (keyed by node_label) injected at crew-launch time. When a node has an `interview_template_id`, its schema is fetched before the crew runs and embedded in the task description as `ASSIGNED_TEMPLATE`.

Add `node_templates_block` parameter to `create_interview_script_designer_task`:

```python
def create_interview_script_designer_task(
    agent,
    discovery_brief="",
    stakeholder_assignments_block="",
    node_templates_block="",   # NEW: JSON string of {node_label: schema | null}
) -> Task
```

In the task description, insert after assignments_block:

```
Assigned interview templates by node (use as starting point if provided):
{node_templates_block}

For nodes that have an assigned template, adapt the template questions to fit this
specific value chain node and engagement context. You may add, remove, or rephrase
questions, but preserve the overall structure and follow-up branch pattern.
For nodes without an assigned template, design from scratch as before.
```

### Crew launch — fetch templates before creating crew

**File:** `api/services/run_service.py` (discovery_interviews branch)

Before calling `create_interview_script_designer_task`, fetch node template assignments from the per-project DB and, for each node that has an `interview_template_id`, fetch the template schema from `system.db`. Build a dict keyed by node_label and serialize to JSON for `node_templates_block`.

### Session response — questionnaire included

**File:** `api/services/interview_service.py` → `get_session_with_script`

After building `session_dict`, fetch the node template assignment for the session's `node_label` from the project DB. If `questionnaire_template_id` is set, fetch the template schema from `system.db` and append to the response:

```python
questionnaire = None
if assignment and assignment["questionnaire_template_id"]:
    # fetch from system.db
    questionnaire = template_row["schema_json"]  # parsed dict

return {
    "session": session_dict,
    "script": script,
    "branding": branding,
    "questionnaire": questionnaire,  # None if no assignment
}
```

---

## Section 4 — Frontend

### New TypeScript type

**File:** `ui/src/types.ts`

```typescript
export interface NodeTemplateAssignment {
  node_label: string
  interview_template_id: number | null
  questionnaire_template_id: number | null
}
```

### API client

**File:** `ui/src/api/nodeTemplates.ts` (new file)

```typescript
const BASE = (slug: string) => `/api/projects/${slug}/node-templates`

export const listNodeTemplates = (slug: string) =>
  fetch(BASE(slug), { headers: authHeaders() }).then(r => r.json())

export const putNodeTemplate = (slug: string, nodeLabel: string, body: Partial<NodeTemplateAssignment>) =>
  fetch(`${BASE(slug)}/${encodeURIComponent(nodeLabel)}`, {
    method: 'PUT',
    headers: authHeaders('json'),
    body: JSON.stringify(body),
  }).then(r => r.json())

export const publishNodeTemplate = (slug: string, nodeLabel: string, body: { name: string; description: string }) =>
  fetch(`${BASE(slug)}/${encodeURIComponent(nodeLabel)}/publish`, {
    method: 'POST',
    headers: authHeaders('json'),
    body: JSON.stringify(body),
  }).then(r => r.json())
```

### Value Chain Setup — Templates tab

**File:** `ui/src/pages/ValueChain.tsx`

Add a third tab to the existing Setup / Diagram tabs: **"Templates"**.

The Templates tab renders a table — one row per node in the value chain tree. Each row shows:
- Node label
- Interview template dropdown (lists all templates of `type='interview'`, plus a "— None —" option)
- Questionnaire template dropdown (lists all templates of `type='questionnaire'`, plus a "— None —" option)
- Publish button (disabled until the project has a completed interview run for that node)

On mount, fetch:
1. `listTemplates('interview')` — for interview dropdown options
2. `listTemplates('questionnaire')` — for questionnaire dropdown options
3. `listNodeTemplates(slug)` — for current assignments

On dropdown change, call `putNodeTemplate` immediately (auto-save, no explicit save button).

If the value chain tree has not been generated yet (no nodes), show an empty-state message: "Run the Value Chain crew first to generate nodes."

---

## Section 5 — Files affected

| File | Change |
|---|---|
| `api/database.py` | `_migrate_node_template_assignments` + 2 DB helpers |
| `api/routers/projects.py` | 3 new endpoints: GET/PUT node-templates + POST publish |
| `api/services/run_service.py` | Fetch node templates before creating interview script designer task |
| `agents/discovery/interview_script_designer.py` | Add `node_templates_block` param to task function |
| `api/services/interview_service.py` | Append `questionnaire` to `get_session_with_script` response |
| `ui/src/types.ts` | `NodeTemplateAssignment` type |
| `ui/src/api/nodeTemplates.ts` | New API client |
| `ui/src/pages/ValueChain.tsx` | Add Templates tab |
| `tests/test_projects_router.py` | 3 tests: list, upsert, publish |

---

## Task breakdown (3 tasks)

**Task 1 — DB + API:** `node_template_assignments` migration + 2 DB helpers + 3 endpoints + tests

**Task 2 — Agent + session service:** `node_templates_block` param in script designer task + run_service template fetch + questionnaire in `get_session_with_script`

**Task 3 — Frontend:** `NodeTemplateAssignment` type + `nodeTemplates.ts` API client + Templates tab in ValueChain.tsx
