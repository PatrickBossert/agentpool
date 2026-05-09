# SP10b/c/d — Discovery Workflow Enhancement Design

## Overview

The current Discovery crew is a single monolithic run that maps the value chain and conducts requirements interviews in one pass. This design splits it into two focused crews with an explicit human assignment gate between them, adds a structured inputs page with real web research capability, and introduces a targeted per-stakeholder interview and synthesis phase.

**Sprint decomposition:**
- **SP10b** — Discovery Inputs page + WebFetchTool + settings storage
- **SP10c** — Split crews, PAM `awaiting_assignment` state, Stakeholder Assignment page, enhanced HITL review gate
- **SP10d** — discovery_interviews crew (Interview Coordinator + Stakeholder Interviewer + Synthesis Analyst)

---

## Motivation

Getting the value chain definition right is fundamental to everything downstream: stakeholder assignment, targeted interviews, value design, roadmap, and business case all inherit the value chain structure. The current workflow has three gaps:

1. **No structured input mechanism** — the crew researches the sector generically; users cannot point it at specific URLs, prioritise certain documents, or provide a research brief
2. **No revision loop** — if the value chain output is incomplete or wrong, there is no mechanism to add context and request a better result before moving on
3. **No assignment layer** — interviews are conducted generically rather than targeting specific people about their specific part of the value chain; synthesis is not structured per value chain node

---

## Full Workflow

```
[Discovery Inputs configured — brief, links, document selection]
        ↓
[PAM triggers discovery_mapping]
        ↓
[Value Chain Mapper runs — fetches links, queries docs, produces value chain]
        ↓
[HITL review gate]
   ├── Approved → proceed
   └── Revision requested:
         - User provides feedback notes
         - User can add more links (this iteration only)
         - User can add more documents (this iteration only)
         - Crew re-runs with original inputs + revision additions
         - Up to 3 revision iterations
        ↓
[Approved value chain locked — orchestration status → awaiting_assignment]
        ↓
[User opens Assignment screen]
   - Value chain tree (left) + stakeholder registry (right)
   - Assigns stakeholders to nodes at L1/L2/L3
   - Coverage warnings for unassigned nodes
   - Confirms assignments → status → queued for discovery_interviews
        ↓
[PAM triggers discovery_interviews]
        ↓
[Interview Coordinator schedules sessions per stakeholder/node]
        ↓
[Stakeholder Interviewer conducts scoped HITL sessions]
        ↓
[Synthesis Analyst produces structured findings record per value chain node]
        ↓
[Findings output visible in UI alongside value chain diagram]
```

---

## SP10b — Discovery Inputs Page + WebFetchTool

### Discovery Inputs page

**Route:** `/:slug/discovery`

**Nav placement:** Between Dashboard and Value Chain in the sidebar.

**Three sections:**

**1. Research Brief**
Free-text field (textarea). Any context the user wants the crew to know before it starts: company strategic context, what's in scope, known constraints, what the client has flagged. Passed verbatim into the Value Chain Mapper's task context.

**2. Research Links**
An add/remove list. Each entry has a URL and an optional label (e.g. `https://www.rail-delivery-group.com` → "Rail Delivery Group"). No limit on number of entries. When discovery_mapping runs, the Value Chain Mapper receives these links and calls WebFetchTool to retrieve and read the content of each one. Links added during a HITL revision request are appended for that iteration only — they do not permanently modify the saved inputs.

**3. Source Documents**
A checklist of documents already uploaded to the project (from the client_documents table). Checked documents are passed to the crew as priority sources; ChromaDB queries are filtered to prefer chunks from these files. If nothing is checked, all uploaded documents are treated equally (current behaviour preserved).

**Persistence:** All three fields are stored in `ProjectSettings` via PATCH to the existing `/projects/{slug}/settings` endpoint. Three new fields added to the `ProjectSettings` model:
- `discovery_brief: str` (default: `""`)
- `discovery_links: list[dict]` — each entry `{"url": str, "label": str}` (default: `[]`)
- `discovery_document_ids: list[int]` — IDs from client_documents (default: `[]`)

No new table or endpoint needed.

**Save behaviour:** A "Save" button at the bottom. Changes take effect on the next crew run. The page shows the last-saved state on load.

### WebFetchTool

A new tool at `crews/tools/web_fetch_tool.py`. Takes a single URL, performs an HTTP GET with a browser-like user agent, returns the page text content stripped of HTML tags, truncated to a configurable character limit (default 8,000 characters to avoid overloading context). Returns an error string if the URL is unreachable or returns a non-200 status rather than raising an exception (crew continues without blocking).

Added to the Value Chain Mapper agent's tool list alongside TavilySearchTool.

**Task context injection:** The Value Chain Mapper's task description is updated to include:
```
Research brief: {discovery_brief}

The client has provided these research links — fetch and read each before 
beginning your analysis:
{discovery_links formatted as numbered list}

Priority source documents: {selected document filenames}
```

If all three are empty, the task description is unchanged from current behaviour.

---

## SP10c — Split Crews + Assignment Step

### Crew split

The existing `discovery` crew is renamed `discovery_mapping`. Its scope narrows to one agent: **Value Chain Mapper** (with WebFetchTool added, as above).

The three remaining agents from the current discovery crew — Requirements Capture, Requirements Analyst, Value Lever Analyst — move to the new `discovery_interviews` crew (SP10d).

Both crew names are registered in the crew registry. `crews_enabled` in ProjectSettings defaults to including both. PAM's run sequence is updated to: `discovery_mapping` → `awaiting_assignment` gate → `discovery_interviews` → (remaining crews as before).

### PAM orchestration — awaiting_assignment state

A new orchestration run status value: `awaiting_assignment`. This sits between `discovery_mapping` completing and `discovery_interviews` being queued.

PAM's logic:
1. Run `discovery_mapping` — wait for completion
2. Check HITL review decision on the value chain output — if rejected, re-run (up to 3 times); if approved, set orchestration run status to `awaiting_assignment` and stop
3. Poll (or respond to webhook) for orchestration run status changing to `queued_interviews` (set by the Assignment completion endpoint)
4. Run `discovery_interviews`

The `orchestration_runs` table gains a new allowed status value: `awaiting_assignment`.

**Runs page:** The `awaiting_assignment` status is displayed with distinct styling (amber, pulsing indicator) and a "Go to Assignment →" link that takes the user directly to `/:slug/assignment`.

### Enhanced HITL review gate

The existing approve/reject gate on the Value Chain Mapper output is extended with a third option: **Request revision with additional context**.

When chosen, the UI presents:
- **Feedback notes** — free text: what is missing, what is wrong, what needs to change
- **Additional links** — same URL + label format as the inputs page; passed to this iteration only, not saved to Discovery Inputs
- **Additional documents** — multi-select from uploaded docs not already prioritised; passed to this iteration only

The crew re-runs with original Discovery Inputs plus the revision additions merged in. Iteration count is tracked; after 3 revisions the gate requires a forced approve or manual escalation. The revision additions from each iteration are stored in the human_reviews record (in the `notes` JSON field) for traceability.

### Stakeholder Assignment step

**Route:** `/:slug/assignment`

**Access:** Only active (non-404) when the current orchestration run has status `awaiting_assignment`. Otherwise redirects to the Runs page.

**Layout:** Two panels.

**Left panel — Value chain tree:** The approved value chain rendered as a collapsible tree: Value Stream (L1) → Stage (L2) → Activity (L3). Each node shows its label and a count of assigned stakeholders. Nodes with zero assignees are highlighted in amber.

**Right panel — Stakeholder registry:** The full stakeholder list as a searchable table showing name, job title, organisation, and current assignment count. A stakeholder can be selected and assigned to one or more nodes at any level (L1, L2, or L3). Assignment is additive — one stakeholder can be assigned to multiple nodes.

**Summary bar:** At the top — "X of Y nodes assigned. Z stakeholders assigned."

**Data model — `stakeholder_assignments` table:**
```sql
CREATE TABLE IF NOT EXISTS stakeholder_assignments (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    orchestration_run_id  INTEGER NOT NULL REFERENCES orchestration_runs(id),
    stakeholder_id        INTEGER NOT NULL REFERENCES stakeholders(id),
    level                 TEXT NOT NULL,   -- 'value_stream' | 'stage' | 'activity'
    node_label            TEXT NOT NULL,
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

A stakeholder assigned at L1 (value stream) is interviewed about the whole stream. Assigned at L3 (activity), they are interviewed about that specific activity only.

**Completing the step:** "Confirm Assignments & Begin Interviews" button. Disabled until at least one stakeholder has been assigned. On click:
- Saves all assignments to `stakeholder_assignments`
- Sets orchestration run status to `queued_interviews` via PATCH `/projects/{slug}/orchestration-runs/{id}/advance`
- PAM picks this up and triggers `discovery_interviews`
- Redirects user to the Runs page

**API endpoints (new):**
- `GET /projects/{slug}/assignment/{orchestration_run_id}` — returns current assignments and the approved value chain JSON
- `POST /projects/{slug}/assignment/{orchestration_run_id}` — saves/replaces all assignments
- `PATCH /projects/{slug}/orchestration-runs/{orchestration_run_id}/advance` — advances status from `awaiting_assignment` to `queued_interviews`

---

## SP10d — discovery_interviews Crew

### Inputs

The crew factory receives:
- `slug` — project slug
- `orchestration_run_id` — to query `stakeholder_assignments`
- `llm_mode` — LLM routing
- Approved value chain JSON (read from the value chain output file for this run)

### Agents

**1. Interview Coordinator**

Reads the `stakeholder_assignments` table for this orchestration run. Reads the approved value chain JSON. Groups stakeholders by assigned area and determines interview depth based on assignment level:
- L1 (value stream): broad strategic questions about the whole stream
- L2 (stage): operational questions about that stage
- L3 (activity): deep questions about the specific activity

Produces an **interview schedule** as JSON:
```json
[
  {
    "stakeholder_id": 3,
    "name": "Jane Smith",
    "role": "CFO",
    "assigned_nodes": [{"level": "stage", "label": "Billing"}],
    "interview_depth": "operational",
    "suggested_questions": ["..."]
  }
]
```
Saves to the agent outputs table. This schedule is the input to the Stakeholder Interviewer.

**2. Stakeholder Interviewer**

Works through the interview schedule session by session. For each session:
- Opens a HITL exchange via the existing HumanInputTool mechanism
- Identifies the session to the operator: *"Interview session: Jane Smith (CFO) — Billing stage"*
- Conducts a structured conversation scoped to the stakeholder's assigned node(s)
- Four dimensions covered in each session: what works well, pain points, unmet needs, systemic frustrations
- Questions are anchored to the value chain node: *"In your work on the Billing stage, what would you say works well today?"*
- Transcript saved per session as JSON, attributed to stakeholder ID, name, and node(s)
- Moves to next session in schedule; all sessions must complete before Synthesis runs

**3. Synthesis Analyst**

Reads all interview transcripts and the approved value chain JSON together. Produces a **structured findings record** organised by value chain node:

```json
{
  "value_chain_node": "Billing",
  "level": "stage",
  "findings": {
    "what_works_well": ["..."],
    "pain_points": ["..."],
    "unmet_needs": ["..."],
    "systemic_frustrations": ["..."]
  },
  "attributed_to": [
    {"stakeholder_id": 3, "name": "Jane Smith"}
  ]
}
```

Cross-cutting themes appearing across multiple nodes are surfaced in a separate `cross_cutting_themes` array.

Output saved as:
1. A JSON file (`discovery_findings.json`) alongside the value chain output
2. An agent output record in the outputs table (type: `discovery_findings`) — visible in the UI alongside the value chain diagram

---

## Data Flow Summary

```
ProjectSettings
  └── discovery_brief, discovery_links, discovery_document_ids
        → injected into discovery_mapping task context

discovery_mapping (Value Chain Mapper)
  ← WebFetchTool (reads research links)
  ← ChromaDB (filtered by selected documents)
  ← TavilySearch
  → value_chain.json (approved after HITL gate)

stakeholder_assignments table
  ← Assignment UI (user assigns registry stakeholders to value chain nodes)
  → interview schedule (Interview Coordinator)

discovery_interviews
  ← value_chain.json
  ← stakeholder_assignments
  → interview_schedule.json (Interview Coordinator)
  → session transcripts per stakeholder (Stakeholder Interviewer)
  → discovery_findings.json (Synthesis Analyst)
```

---

## Error Handling

- **WebFetchTool unreachable URL:** Returns error string to agent; agent logs it and continues with remaining links and other research sources. Does not block the crew.
- **All revision iterations exhausted:** HITL gate surfaces a warning; user must choose forced approve or contact support. Pipeline does not auto-proceed.
- **Assignment with zero stakeholders:** "Confirm" button is disabled; cannot advance to discovery_interviews without at least one assignment.
- **Stakeholder not available for interview:** Interviewer records a skipped session with a note; Synthesis Analyst notes the gap in the findings record for that node.

---

## Testing

**SP10b:**
- Unit tests for WebFetchTool (mock HTTP, error handling, character truncation)
- API tests for GET/PATCH settings with new discovery fields
- Frontend type-check (tsc --noEmit)

**SP10c:**
- API tests for new assignment endpoints (GET, POST, PATCH advance)
- DB migration test for `stakeholder_assignments` table
- PAM orchestration tests for `awaiting_assignment` state transition
- HITL revision gate tests (revision additions stored in notes, iteration count tracked)

**SP10d:**
- Unit tests for Interview Coordinator schedule generation
- Integration tests for full discovery_interviews crew run with mock stakeholder assignments
- Synthesis output structure validation

---

## Sprint Boundaries

| Sprint | Deliverable | Depends on |
|--------|-------------|------------|
| SP10b | Discovery Inputs page + WebFetchTool + settings fields | SP10a (done) |
| SP10c | Split crews + awaiting_assignment + Assignment UI + enhanced HITL gate | SP10b |
| SP10d | discovery_interviews crew | SP10c |

Each sprint produces working, testable software. SP10b can ship without SP10c (the inputs page improves the existing discovery crew immediately). SP10c requires SP10b (inputs are referenced by the enhanced gate). SP10d requires SP10c (needs assignment data).
