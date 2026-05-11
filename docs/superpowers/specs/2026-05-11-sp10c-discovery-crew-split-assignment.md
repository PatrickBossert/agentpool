# SP10c — Discovery Crew Split + Stakeholder Assignment Design

## Overview

Split the monolithic `discovery` crew into two focused crews separated by an explicit human assignment gate. The first crew (`discovery_mapping`) runs the Value Chain Mapper and pauses in an `awaiting_assignment` state. A consultant assigns registry stakeholders to value chain nodes via a new Assignment page. The second crew (`discovery_interviews`) runs the three interview and synthesis agents — added in SP10d.

**Sprint decomposition context:**
- SP10b — Discovery Inputs page + WebFetchTool + settings storage ✓ complete
- **SP10c — Split crews, `awaiting_assignment` gate, Stakeholder Assignment page** ← this sprint
- SP10d — `discovery_interviews` crew (Interview Coordinator + Stakeholder Interviewer + Synthesis Analyst)

---

## 1. Crew Split + Value Chain Tree JSON

### New crew: `discovery_mapping`

Create `agents/crews/discovery_mapping_crew.py`. Contains only the Value Chain Mapper agent. The crew factory signature mirrors `create_discovery_crew` for the inputs it needs:

```python
def create_discovery_mapping_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
    hitl_tool=None,
    discovery_brief: str = "",
    discovery_links: list[dict] | None = None,
    priority_doc_names: list[str] | None = None,
) -> Crew
```

`run_service.py` gains a `crew_name == "discovery_mapping"` branch that loads discovery inputs from project config (identical to the existing `discovery` branch) and calls `create_discovery_mapping_crew`.

### Existing `discovery_crew.py`

Left untouched. Its three agents (Requirements Capture, Requirements Analyst, Value Lever Analyst) remain there. SP10d will pull them into `discovery_interviews_crew.py`.

### Value chain tree JSON (Option A)

The Value Chain Mapper task description (`agents/discovery/value_chain_mapper.py`) gains a new step after the Mermaid diagram is approved:

> **Step N:** Use SQLiteStateTool with `operation='write'`, `key='value_chain_tree'`, `agent_name='value_chain_mapper'` to save the value chain as a structured JSON tree. Format:
> ```json
> [
>   {
>     "label": "Inbound Logistics",
>     "level": "L1",
>     "children": [
>       {
>         "label": "Materials Receipt",
>         "level": "L2",
>         "children": [
>           {"label": "Goods-in Inspection", "level": "L3"}
>         ]
>       }
>     ]
>   }
> ]
> ```
> Derive the tree from the value chain activities you identified. L1 = primary activity / value stream, L2 = stage within that stream, L3 = specific activity. Use client-specific labels where known.

The `value_chain_tree` key is stored in the project's SQLite state (same DB as other agent state) and is read by the Assignment API endpoint.

---

## 2. PAM Phase Split + `awaiting_assignment`

### Motivation

PAM currently runs one crew containing all five sub-crews sequentially. The `awaiting_assignment` gate requires PAM to stop after `discovery_mapping`, wait for human action, then resume. CrewAI sequential process has no built-in pause, so the pipeline is split into two PAM crews sharing the same `orchestration_run_id`.

### Phase 1 PAM crew

`agents/crews/pam_crew.py` gains `create_pam_mapping_crew`:

```python
def create_pam_mapping_crew(
    slug: str,
    orchestration_run_id: int,
    llm_mode: str,
    llm: LLM | None = None,
) -> Crew
```

Contains one task: `create_run_discovery_mapping_task(agent, slug)` — instructs PAM to run `crew_name='discovery_mapping'` via RunCrewTool, then notify Slack: `"✓ Value chain mapping complete for {slug}. Awaiting stakeholder assignment."`.

### Phase 2 PAM crew

`create_pam_resume_crew` — contains tasks for `value_design` → `architecture` → `delivery` → `business_plan` (same as current tasks 2–5). SP10d will prepend a `discovery_interviews` task here.

### Old `create_pam_crew` (5 tasks)

Removed. Both Phase 1 and Phase 2 replace it.

### `pam_agent.py`

Add `create_run_discovery_mapping_task(agent, slug)` analogous to the existing `create_run_discovery_task`.

### `orchestration_service.py`

```
start_orchestration(slug) → orchestration_run_id
  └── asyncio.create_task(run_pam_phase1(slug, orchestration_run_id))

run_pam_phase1(slug, orchestration_run_id)
  creates create_pam_mapping_crew → kickoff_async()
  on success: update status → 'awaiting_assignment'
  on failure: update status → 'failed'

resume_orchestration(slug, orchestration_run_id)
  update status → 'running'
  asyncio.create_task(run_pam_phase2(slug, orchestration_run_id))

run_pam_phase2(slug, orchestration_run_id)
  creates create_pam_resume_crew → kickoff_async()
  on success: update status → 'completed'
  on failure: update status → 'failed'
```

### `database.py`

`update_orchestration_run_status` already accepts any TEXT value. No schema migration needed. The allowed status values are documented as: `running` | `awaiting_assignment` | `completed` | `failed`.

---

## 3. DB Migration + Assignment API

### `stakeholder_assignments` table

Added to the DB migration in `database.py` (new `_migrate_stakeholder_assignments` helper, called from `init_db`):

```sql
CREATE TABLE IF NOT EXISTS stakeholder_assignments (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    orchestration_run_id  INTEGER NOT NULL REFERENCES orchestration_runs(id),
    stakeholder_id        INTEGER NOT NULL REFERENCES stakeholders(id),
    level                 TEXT NOT NULL,   -- 'L1' | 'L2' | 'L3'
    node_label            TEXT NOT NULL,
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

### DB helpers (added to `database.py`)

```python
async def fetch_value_chain_tree(conn, *, slug: str) -> list[dict]
    # reads key='value_chain_tree' from agent_state table, returns parsed JSON or []

async def fetch_stakeholder_assignments(conn, *, orchestration_run_id: int) -> list[dict]
    # SELECT * FROM stakeholder_assignments WHERE orchestration_run_id=?

async def replace_stakeholder_assignments(
    conn,
    *,
    orchestration_run_id: int,
    assignments: list[dict],  # [{stakeholder_id, level, node_label}]
) -> int  # count saved
    # DELETE existing for run_id, then INSERT all, returns len(assignments)
```

### New router: `api/routers/assignment.py`

Registered in `main.py` after the stakeholders router.

**`GET /projects/{slug}/assignment/{orchestration_run_id}`**

Returns:
```json
{
  "value_chain_tree": [...],
  "assignments": [
    {"id": 1, "orchestration_run_id": 3, "stakeholder_id": 7, "level": "L2", "node_label": "Billing"}
  ],
  "stakeholders": [...]
}
```
404 if project not found. Returns empty `value_chain_tree: []` if the mapper hasn't saved it yet (graceful — the Assignment page renders a placeholder).

**`POST /projects/{slug}/assignment/{orchestration_run_id}`**

Body: `[{"stakeholder_id": int, "level": str, "node_label": str}]`

Calls `replace_stakeholder_assignments`. Returns `{"saved": N}`.

422 if body is empty list (must assign at least one — validation in the router, not just the UI).

**`PATCH /projects/{slug}/orchestration-runs/{orchestration_run_id}/advance`**

Validates that the orchestration run exists and has status `awaiting_assignment`. Calls `resume_orchestration(slug, orchestration_run_id)`. Returns `{"status": "running"}`.

400 if status is not `awaiting_assignment` (prevents double-advance).

---

## 4. Frontend — Assignment Page

### Types (`ui/src/types.ts`)

```ts
export interface ValueChainNode {
  label: string
  level: 'L1' | 'L2' | 'L3'
  children?: ValueChainNode[]
}

export interface StakeholderAssignment {
  stakeholder_id: number
  level: string
  node_label: string
}

export interface AssignmentData {
  value_chain_tree: ValueChainNode[]
  assignments: StakeholderAssignment[]
  stakeholders: Stakeholder[]
}
```

### API methods (`ui/src/api.ts`)

```ts
getAssignment(slug: string, orchestrationRunId: number): Promise<AssignmentData>
saveAssignment(slug: string, orchestrationRunId: number, assignments: StakeholderAssignment[]): Promise<{saved: number}>
advanceOrchestrationRun(slug: string, orchestrationRunId: number): Promise<{status: string}>
```

### `ui/src/pages/Assignment.tsx`

**Route:** `/:slug/assignment`

**Guard:** On mount, fetch `GET /projects/{slug}/runs` to find the latest orchestration run. If its status is not `awaiting_assignment`, navigate to `/:slug/runs`. This prevents stale URL access.

**State:** Local component state tracks pending assignments (before POST). On load, initialise from `AssignmentData.assignments`.

**Layout:**

```
┌─────────────────────────────────────────────────────────┐
│  Summary bar: "X of Y nodes assigned · Z stakeholders"  │
├──────────────────────────┬──────────────────────────────┤
│  Value Chain Tree        │  Stakeholder Roster           │
│  (collapsible L1→L2→L3)  │  [search input]              │
│                          │  Name | Title | Org | Count  │
│  ▼ Inbound Logistics (2) │  Jane Smith  · CFO · ...  ✓  │
│    ▶ Materials Receipt   │  Bob Jones   · PM  · ...      │
│    ▼ Goods-in (amber)    │  ...                          │
│                          │                               │
├──────────────────────────┴──────────────────────────────┤
│  [Confirm Assignments & Begin Interviews]  (disabled     │
│   until ≥1 assignment)                                   │
└─────────────────────────────────────────────────────────┘
```

**Interactions:**
- Click a tree node → sets it as the active target; highlights it
- Click a stakeholder row → toggles assignment to the active node (teal check when assigned)
- Amber highlight on nodes with zero assignees
- Confirm button: POST assignments → PATCH advance → navigate to `/:slug/runs`

**Empty tree state:** If `value_chain_tree` is `[]` (mapper hasn't saved it yet), show a message: `"Value chain data not yet available. The mapping crew must complete before assigning stakeholders."`

### Route registration (`ui/src/App.tsx`)

```tsx
<Route path="/:slug/assignment" element={<Assignment />} />
```

No nav sidebar entry — the page is accessed from the Runs page link only.

---

## 5. Runs Page — `awaiting_assignment` Status

`ui/src/pages/Runs.tsx` — in the orchestration run status badge section, add a case for `awaiting_assignment`:

- Amber badge text: `Awaiting Assignment`
- Pulsing amber dot (same pattern as the `running` state's pulsing teal dot)
- Below the badge: `<Link to={\`/${slug}/assignment\`}>Go to Assignment →</Link>` styled as a teal text link

---

## 6. Files Affected

### New
- `agents/crews/discovery_mapping_crew.py`
- `api/routers/assignment.py`
- `ui/src/pages/Assignment.tsx`

### Modified
- `agents/discovery/value_chain_mapper.py` — add value_chain_tree save step to task description
- `agents/crews/pam_crew.py` — replace `create_pam_crew` with `create_pam_mapping_crew` + `create_pam_resume_crew`
- `agents/pam/pam_agent.py` — add `create_run_discovery_mapping_task`
- `api/services/orchestration_service.py` — split `run_pam_crew` into Phase 1 + Phase 2
- `api/database.py` — `stakeholder_assignments` migration + 3 new helpers
- `api/main.py` — register assignment router
- `api/services/run_service.py` — add `discovery_mapping` branch
- `ui/src/types.ts` — add `ValueChainNode`, `StakeholderAssignment`, `AssignmentData`
- `ui/src/api.ts` — add 3 assignment API methods
- `ui/src/App.tsx` — add `/:slug/assignment` route
- `ui/src/pages/Runs.tsx` — add `awaiting_assignment` status display

---

## 7. Tests

- `tests/test_assignment_api.py` — GET/POST/PATCH endpoints, 404, 400 on double-advance, 422 on empty POST body
- `tests/test_orchestration_service.py` — `run_pam_phase1` sets `awaiting_assignment`, `resume_orchestration` transitions to `running`, `run_pam_phase2` sets `completed`
- `tests/test_projects_api.py` — existing tests unaffected (discovery crew still exists)
- TypeScript: `tsc --noEmit` on `Assignment.tsx`

---

## 8. Out of Scope

- Enhanced HITL revision gate (3rd option with additional links/docs in the Reviews UI)
- `discovery_interviews` crew (SP10d)
- Layer Map tab content (currently stub in Discovery page)
- Any changes to the existing `discovery_crew.py` agents
