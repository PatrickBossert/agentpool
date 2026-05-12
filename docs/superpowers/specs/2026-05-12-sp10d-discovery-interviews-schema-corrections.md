# SP10d — Discovery Interviews Crew + Value Canvas Schema Corrections

## Overview

SP10d delivers two things in one sprint:

1. **Discovery Interviews Crew** — a three-agent CrewAI crew that conducts text-based stakeholder interviews inside the platform, producing the same `requirements.json` and `value_levers.json` outputs as the existing ListenLabs path, plus a new `activity_insights.json` enriching each value chain activity with actors, needs, and frustrations surfaced from interviews.

2. **Value Canvas Schema Corrections** — updated agent task schemas for `value_proposition_generator` and `initiative_identifier` to align with the intended value canvas model: propositions anchored to process activities with typed beneficiaries; initiatives typed as enabler or change_activity with structured capability uplift dimensions, explicit dependency lists, and cost estimates.

Projects choose their interview method via a new `interview_method` ProjectSettings field (`'agent' | 'listenlabs' | 'none'`). Default is `'none'` for backwards compatibility.

---

## Context

### Value canvas intended schema

```
Project
└── Value Stream (L1 — corporate entity or shared service)
    └── Value Chain Stage (L2)
        └── Process Activity (L3)
            ├── Actors (who performs it)
            ├── Needs (what they require)
            ├── Frustrations (what impedes them)
            └── Value Proposition (change to how the activity is carried out)
                ├── Activity ref (L3 node it addresses)
                ├── Beneficiaries → Benefit types
                └── Capability Uplifts ("to do this we need to be able to...")
                    └── Initiative (one uplift = one initiative)
                        ├── Dimension: people | data | systems | organisation |
                        │             partnership | architectural | operating_model
                        ├── Type: enabler | change_activity
                        ├── Dependencies (inbound/outbound)
                        └── Cost estimate
```

### What SP10c shipped

- `value_chain_tree` saved as L1/L2/L3 JSON by the Value Chain Mapper after diagram approval
- Stakeholder Assignment page: consultants assign registry stakeholders to L1/L2/L3 nodes before interviews
- PAM two-phase split: Phase 1 = discovery_mapping (ends at `awaiting_assignment`); Phase 2 = resume pipeline after assignment confirmation

### Gaps addressed in SP10d

| Gap | Fix |
|---|---|
| No actors/needs/frustrations per activity | Synthesis Analyst writes `activity_insights` from interview transcripts |
| Propositions not anchored to activities | `value_proposition_generator` schema gains `activity_refs` + `beneficiaries` |
| `capability_gaps` free text | Replaced with `capability_uplifts` array with typed dimensions |
| Initiative typed by category not role | Replace `category` with `initiative_type: enabler/change_activity` + dependency lists |
| No cost estimates on initiatives | Add `cost_estimate: {low, high, currency, rationale}` |

---

## Section 1 — `interview_method` ProjectSettings field

### Backend

Add `interview_method: str = 'none'` to `ProjectSettings` in `api/models.py`.

Valid values: `'agent'`, `'listenlabs'`, `'none'`.

No DB migration needed — stored in `project.json` config file via the existing settings PATCH endpoint.

### Frontend

Add a radio group to `ui/src/pages/Settings.tsx` in the Discovery section, below the existing discovery brief/links fields:

```
Interview method
○ None (skip interview phase)
○ Agent interviews (platform conducts text-based interviews)
○ ListenLabs (external campaign via ListenLabs API)
```

Label and value mapping: `none`, `agent`, `listenlabs`.

Update `ui/src/types.ts`: add `interview_method: 'agent' | 'listenlabs' | 'none'` to `ProjectSettings`.

---

## Section 2 — Discovery Interviews Crew (three agents)

### Agent 1: Interview Coordinator

**File:** `agents/discovery/interview_coordinator.py`

**Role:** Plans and coordinates the stakeholder interview programme based on the value chain assignments.

**Task steps:**
1. Read `key='value_chain_tree'` (approved value chain with L1/L2/L3 nodes)
2. Receive formatted stakeholder assignments string injected into task description at crew creation time
3. Produce an interview plan: for each assigned stakeholder, 5–8 tailored questions based on their assigned node(s) and inferred role/domain
4. Write `key='interview_plan'` — JSON array: `[{stakeholder_id, name, job_title, node_labels: [...], questions: [...]}]`
5. HITL: present plan for approval; accept revision notes up to 3 cycles

### Agent 2: Stakeholder Interviewer

**File:** `agents/discovery/stakeholder_interviewer.py`

**Role:** Conducts individual text-based interviews using HumanInputTool, one stakeholder at a time.

**Task steps:**
1. Read `key='interview_plan'`
2. For each stakeholder in the plan:
   a. Use HumanInputTool to introduce the interview and ask each question in sequence
   b. Capture responses verbatim
3. Write `key='interview_transcripts'` — JSON array: `[{stakeholder_id, name, node_labels: [...], qa_pairs: [{question, answer}]}]`

### Agent 3: Synthesis Analyst

**File:** `agents/discovery/synthesis_analyst.py`

**Role:** Synthesises interview transcripts into structured discovery outputs that downstream agents consume.

**Task steps:**
1. Read `key='interview_transcripts'`
2. Read `key='value_chain_tree'` (for node labels)
3. Produce `key='activity_insights'` — for each L3 node referenced in transcripts:
   ```json
   {
     "label": "Goods-in Inspection",
     "level": "L3",
     "actors": ["Warehouse Operative", "Quality Inspector"],
     "needs": ["Real-time visibility of delivery schedule"],
     "frustrations": ["Manual paper-based receipt process causes delays"]
   }
   ```
4. Produce `key='requirements'` — requirements register (same format as legacy `requirements_analyst`)
5. Produce `key='value_levers'` — value lever register (same format as legacy `value_lever_analyst`)
6. HITL: present synthesis for approval; accept revision notes up to 3 cycles

**Downstream compatibility:** `value_proposition_generator` reads `requirements`, `value_levers`, and (opportunistically) `activity_insights`. Writing all three here means the downstream pipeline is identical regardless of interview method.

---

## Section 3 — Crew factory and data flow

### `agents/crews/discovery_interviews_crew.py` (new)

```python
def create_discovery_interviews_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    stakeholder_assignments: list[dict],  # [{stakeholder_id, name, job_title, level, node_label}]
    llm: LLM | None = None,
    hitl_tool=None,
) -> Crew
```

Stakeholder assignments are injected into the Interview Coordinator task description as a formatted block:

```
Stakeholder assignments:
- Alice Chen (Head of Ops) → L2: Order Fulfilment
- Bob Smith (CTO) → L1: Technology
```

No new tool required. Same pattern as `discovery_brief` injection in `value_chain_mapper`.

### `api/services/run_service.py` — `discovery_interviews` branch

```python
elif crew_name == "discovery_interviews":
    interview_method = config.get("interview_method", "none")
    if interview_method != "agent":
        raise ValueError(
            f"Cannot dispatch discovery_interviews crew: interview_method is '{interview_method}', expected 'agent'"
        )
    # Fetch active orchestration run for this slug
    # Fetch stakeholder_assignments joined with stakeholders table
    # Pass enriched list to create_discovery_interviews_crew(...)
```

Also reachable via `dispatch_crew` directly for standalone testing outside PAM.

---

## Section 4 — PAM wiring

### `agents/pam/pam_agent.py`

Add:

```python
def create_run_discovery_interviews_task(agent: Agent, slug: str, context_tasks: list) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='discovery_interviews' to run the "
            f"Discovery Interviews crew for project '{slug}'. Wait for it to complete. "
            f"Then use SlackNotifyTool to send: "
            f"'✓ Discovery interviews complete for {slug}. Starting Value Design.'"
        ),
        expected_output="Confirmation that discovery_interviews crew completed and Slack notified.",
        agent=agent,
        context=context_tasks,
    )
```

### `agents/crews/pam_crew.py`

`create_pam_resume_crew` gains `interview_method: str = 'none'` parameter:

```python
def create_pam_resume_crew(
    slug, orchestration_run_id, llm_mode, interview_method="none", llm=None
) -> Crew:
    ...
    tasks = []
    if interview_method == "agent":
        t_interviews = create_run_discovery_interviews_task(pam, slug, context_tasks=[])
        tasks.append(t_interviews)
        context_for_value_design = [t_interviews]
    else:
        context_for_value_design = []

    t1 = create_run_value_design_task(pam, slug, context_tasks=context_for_value_design)
    t2 = create_run_architecture_task(pam, slug, context_tasks=[t1])
    t3 = create_run_delivery_task(pam, slug, context_tasks=[t2])
    t4 = create_run_business_plan_task(pam, slug, context_tasks=[t3])
    tasks += [t1, t2, t3, t4]
    return Crew(agents=[pam], tasks=tasks, process=Process.sequential, verbose=True)
```

### `api/services/orchestration_service.py`

`run_pam_phase2` reads `interview_method` from project config and passes it to `create_pam_resume_crew`.

---

## Section 5 — Schema corrections

### 5a. `value_proposition_generator` — updated proposition schema

Add to each proposition object:

```json
{
  "activity_refs": ["L3:Goods-in Inspection", "L3:Invoice Processing"],
  "beneficiaries": [
    {
      "group": "Warehouse Operative",
      "benefit_types": ["time_saving", "experience"]
    },
    {
      "group": "Finance Team",
      "benefit_types": ["cost_reduction", "quality_improvement"]
    }
  ]
}
```

Valid `benefit_types`: `time_saving`, `cost_reduction`, `quality_improvement`, `risk_reduction`, `experience`.

Step added to task description: read `key='activity_insights'` opportunistically (skip if missing — `interview_method` may not be `'agent'`). Use insights to inform `activity_refs` and `beneficiaries`. If `activity_insights` absent, infer `activity_refs` from value chain summary and leave `beneficiaries` based on `impacted_stakeholder_groups` with `benefit_types` inferred from supporting evidence.

### 5b. `initiative_identifier` — updated initiative schema

Replace `capability_gaps: [string]` and `category: "enabling|operating_model|business_change"` with:

```json
{
  "id": "INIT-001",
  "title": "...",
  "description": "...",
  "proposition_ids": ["VP-001"],
  "capability_uplifts": [
    {
      "dimension": "systems",
      "description": "Implement warehouse management system with real-time goods-in tracking"
    },
    {
      "dimension": "people",
      "description": "Train warehouse operatives on digital receipt processes"
    }
  ],
  "initiative_type": "enabler",
  "enabler_dependencies": [],
  "change_dependencies": [],
  "complexity_score": 3,
  "complexity_rationale": "...",
  "cost_estimate": {
    "low": 50000,
    "high": 150000,
    "currency": "GBP",
    "rationale": "..."
  },
  "related_requirements": ["REQ-001"]
}
```

Valid `dimension` values: `people`, `data`, `systems`, `organisation`, `partnership`, `architectural`, `operating_model`.

`initiative_type`:
- `"enabler"` — technology/data/infrastructure change; populates `enabler_dependencies` (other INIT IDs this depends on)
- `"change_activity"` — process/org/strategic change; populates `change_dependencies` (enabler INIT IDs required before this can run)

`enabler_dependencies` is only populated for `initiative_type="enabler"`. `change_dependencies` is only populated for `initiative_type="change_activity"`. The other field is always `[]`.

---

## Section 6 — Files affected

| File | Change |
|---|---|
| `api/models.py` | Add `interview_method: str = 'none'` to `ProjectSettings` |
| `api/services/run_service.py` | Add `discovery_interviews` branch |
| `api/services/orchestration_service.py` | Pass `interview_method` to `create_pam_resume_crew` |
| `agents/crews/discovery_interviews_crew.py` | **New** — three-agent crew factory |
| `agents/discovery/interview_coordinator.py` | **New** — agent + task |
| `agents/discovery/stakeholder_interviewer.py` | **New** — agent + task |
| `agents/discovery/synthesis_analyst.py` | **New** — agent + task |
| `agents/tools/registry.py` | Add `discovery_interviews` entry |
| `agents/pam/pam_agent.py` | Add `create_run_discovery_interviews_task` |
| `agents/crews/pam_crew.py` | `create_pam_resume_crew` gains `interview_method` param |
| `agents/value_design/value_proposition_generator.py` | Add `activity_refs`, `beneficiaries`; read `activity_insights` opportunistically |
| `agents/architecture/initiative_identifier.py` | Replace schema: `capability_uplifts`, `initiative_type`, dependencies, `cost_estimate` |
| `ui/src/pages/Settings.tsx` | Add `interview_method` radio group |
| `ui/src/types.ts` | Update `ProjectSettings`, `Initiative`, `ValueProposition` types |
| `tests/test_discovery_interviews_crew.py` | **New** — crew factory + agent tests |
| `tests/test_pam_crew.py` | Update for `interview_method` param |
| `tests/test_orchestration_service.py` | Update phase2 tests for `interview_method` forwarding |
| `tests/test_value_proposition_generator.py` | **New** — tests for updated proposition schema (activity_refs, beneficiaries) |
| `tests/test_initiative_identifier.py` | **New** — tests for updated initiative schema (capability_uplifts, initiative_type, dependencies, cost_estimate) |
