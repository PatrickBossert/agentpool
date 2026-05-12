# SP10d — Discovery Interviews Crew + Value Canvas Schema Corrections

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an agent-conducted discovery interviews crew (`interview_method='agent'`) as an optional alternative to ListenLabs campaigns, and correct the value canvas schema so that value propositions are anchored to process activities with typed beneficiaries, and initiatives carry structured capability uplift dimensions, dependency lists, and cost estimates.

**Architecture:** Three new CrewAI agents (Interview Coordinator → Stakeholder Interviewer → Synthesis Analyst) run sequentially inside a new `discovery_interviews` crew. The crew is conditionally prepended to PAM Phase 2 when `interview_method='agent'` in project settings. Schema corrections to `value_proposition_generator` and `initiative_identifier` apply to all projects regardless of interview method.

**Tech Stack:** Python / CrewAI, FastAPI, SQLite (aiosqlite), React / TypeScript

**Spec:** `docs/superpowers/specs/2026-05-12-sp10d-discovery-interviews-schema-corrections.md`

---

## Codebase orientation

Before starting, read these files:
- `agents/crews/discovery_mapping_crew.py` — pattern for single-agent crew factories
- `agents/tools/registry.py` — how agent→tool lists are defined (add entries at the bottom of `tool_map`)
- `agents/pam/pam_agent.py` — existing task factory pattern (copy for new task)
- `agents/crews/pam_crew.py` — `create_pam_resume_crew` (add `interview_method` param)
- `api/services/orchestration_service.py` — `run_pam_phase2` (pass `interview_method`)
- `api/services/run_service.py` — existing `discovery_mapping` branch (copy structure)
- `api/database.py` lines 887–918 — `fetch_stakeholder_assignments`, `replace_stakeholder_assignments`
- `api/models.py` — `ProjectSettings` (add `interview_method` field)
- `ui/src/types.ts` — `ProjectSettings`, `Initiative` interfaces (update both)
- `ui/src/pages/Settings.tsx` — DEFAULTS + rendered sections (add Discovery section)
- `agents/value_design/value_proposition_generator.py` — full task description (rewrite schema)
- `agents/architecture/initiative_identifier.py` — full task description (rewrite schema)
- `tests/test_pam_crew.py` — existing crew test patterns
- `tests/test_orchestration_service.py` — existing orchestration service test patterns
- `tests/test_discovery_crew.py` — existing crew assembly test patterns

---

## Task 1: `interview_method` in ProjectSettings + Settings UI

**Files:**
- Modify: `api/models.py`
- Modify: `ui/src/types.ts`
- Modify: `ui/src/pages/Settings.tsx`

### Background
`ProjectSettings` is a Pydantic model in `api/models.py`. The settings PATCH endpoint at `api/routers/projects.py` accepts and persists this model as JSON in the project config file. The frontend mirrors it in `ui/src/types.ts`. `Settings.tsx` reads/writes via `projectsApi.getSettings` / `projectsApi.updateSettings`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interview_method_setting.py
"""Tests for interview_method ProjectSettings field."""
import pytest
from pydantic import ValidationError


def test_interview_method_default_is_none():
    from api.models import ProjectSettings
    s = ProjectSettings(sector="rail")
    assert s.interview_method == "none"


def test_interview_method_accepts_agent():
    from api.models import ProjectSettings
    s = ProjectSettings(sector="rail", interview_method="agent")
    assert s.interview_method == "agent"


def test_interview_method_accepts_listenlabs():
    from api.models import ProjectSettings
    s = ProjectSettings(sector="rail", interview_method="listenlabs")
    assert s.interview_method == "listenlabs"


def test_interview_method_rejects_invalid():
    from api.models import ProjectSettings
    with pytest.raises(ValidationError):
        ProjectSettings(sector="rail", interview_method="magic")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/pboagents/Documents/agentpool1
python -m pytest tests/test_interview_method_setting.py -v
```

Expected: FAIL with `AttributeError` or `ValidationError` on `interview_method` not existing.

- [ ] **Step 3: Add `interview_method` to `api/models.py`**

In `api/models.py`, add to `ProjectSettings` after `discovery_document_ids`:

```python
interview_method: Literal["agent", "listenlabs", "none"] = "none"
```

The `Literal` import is already at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_interview_method_setting.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Update `ui/src/types.ts`**

In `ui/src/types.ts`, find `interface ProjectSettings` and add after `discovery_document_ids`:

```typescript
  interview_method: 'agent' | 'listenlabs' | 'none'
```

- [ ] **Step 6: Update `ui/src/pages/Settings.tsx`**

In `Settings.tsx`, add `interview_method: 'none'` to `DEFAULTS`:

```typescript
const DEFAULTS: ProjectSettings = {
  llm_mode: 'standard',
  sector: '',
  stakeholder_groups: [],
  value_stream_labels: [],
  roadmap_time_axis: 'quarters',
  crews_enabled: [...KNOWN_CREWS],
  review_gates: true,
  slack_channel: '',
  discovery_brief: '',
  discovery_links: [],
  discovery_document_ids: [],
  interview_method: 'none',
}
```

Add a Discovery section to the JSX, just before the `{/* Footer */}` comment block:

```tsx
{/* Discovery */}
<section className="space-y-3">
  <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest">Discovery</h3>
  <div>
    <label className="text-xs text-slate-400 block mb-2">Interview Method</label>
    <div className="flex flex-col gap-2">
      {(
        [
          ['none', 'None — skip interview phase'],
          ['agent', 'Agent interviews — platform conducts text-based interviews'],
          ['listenlabs', 'ListenLabs — external campaign via ListenLabs API'],
        ] as [ProjectSettings['interview_method'], string][]
      ).map(([value, label]) => (
        <label key={value} className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
          <input
            type="radio"
            name="interview_method"
            value={value}
            checked={form.interview_method === value}
            onChange={() => setForm({ ...form, interview_method: value })}
          />
          {label}
        </label>
      ))}
    </div>
  </div>
</section>
```

- [ ] **Step 7: Run full test suite to confirm no regressions**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all existing tests pass plus 4 new ones.

- [ ] **Step 8: Commit**

```bash
git add api/models.py ui/src/types.ts ui/src/pages/Settings.tsx tests/test_interview_method_setting.py
git commit -m "feat: add interview_method to ProjectSettings and Settings UI radio group"
```

---

## Task 2: Three discovery interview agent modules

**Files:**
- Create: `agents/discovery/interview_coordinator.py`
- Create: `agents/discovery/stakeholder_interviewer.py`
- Create: `agents/discovery/synthesis_analyst.py`

### Background
Each agent module follows the same pattern as `agents/discovery/value_chain_mapper.py`:
- A `create_<agent>` factory returning a `crewai.Agent`
- A `create_<agent>_task` factory returning a `crewai.Task`

The Interview Coordinator reads `value_chain_tree` and receives stakeholder assignments injected into its task description at crew-creation time (same pattern as `discovery_brief` in `value_chain_mapper`).

The Stakeholder Interviewer reads `interview_plan` and uses HumanInputTool to conduct Q&A, writing all responses to `interview_transcripts`.

The Synthesis Analyst reads `interview_transcripts` and produces three outputs:
- `activity_insights` — enriched activity-level data (actors, needs, frustrations per L3 node)
- `requirements` — requirements register (same key as `requirements_analyst`; downstream `value_proposition_generator` reads this key regardless of interview method)
- `value_levers` — value lever register (same key as `value_lever_analyst`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_discovery_interviews_agents.py
"""Unit tests for the three discovery interview agent modules."""
from unittest.mock import MagicMock, patch
import pytest


def _mock_agent():
    return MagicMock()


# ── Interview Coordinator ─────────────────────────────────────────────────────

def test_interview_coordinator_task_includes_assignments():
    """Task description includes the stakeholder assignments block when provided."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(
            agent=agent,
            stakeholder_assignments="- Alice Chen (Head of Ops) → L2: Order Fulfilment",
        )
    _, kwargs = MockTask.call_args
    assert "Alice Chen" in kwargs["description"]
    assert "interview_plan" in kwargs["description"]


def test_interview_coordinator_task_reads_value_chain_tree():
    """Task description instructs agent to read value_chain_tree."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=agent, stakeholder_assignments="")
    _, kwargs = MockTask.call_args
    assert "value_chain_tree" in kwargs["description"]


# ── Stakeholder Interviewer ───────────────────────────────────────────────────

def test_stakeholder_interviewer_task_reads_interview_plan():
    """Task description instructs agent to read interview_plan."""
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task
    agent = _mock_agent()
    with patch("agents.discovery.stakeholder_interviewer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_stakeholder_interviewer_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "interview_plan" in kwargs["description"]
    assert "interview_transcripts" in kwargs["description"]


# ── Synthesis Analyst ─────────────────────────────────────────────────────────

def test_synthesis_analyst_task_writes_all_three_keys():
    """Task description instructs agent to write activity_insights, requirements, value_levers."""
    from agents.discovery.synthesis_analyst import create_synthesis_analyst_task
    agent = _mock_agent()
    with patch("agents.discovery.synthesis_analyst.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_synthesis_analyst_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    for key in ("activity_insights", "requirements", "value_levers"):
        assert key in kwargs["description"], f"Key '{key}' missing from task description"


def test_synthesis_analyst_task_reads_transcripts():
    """Task description instructs agent to read interview_transcripts."""
    from agents.discovery.synthesis_analyst import create_synthesis_analyst_task
    agent = _mock_agent()
    with patch("agents.discovery.synthesis_analyst.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_synthesis_analyst_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "interview_transcripts" in kwargs["description"]
```

- [ ] **Step 2: Run to verify all fail**

```bash
python -m pytest tests/test_discovery_interviews_agents.py -v
```

Expected: 5 FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `agents/discovery/interview_coordinator.py`**

```python
# agents/discovery/interview_coordinator.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_interview_coordinator(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Interview Coordinator",
        goal=(
            "Plan the stakeholder interview programme by designing tailored questions "
            "for each assigned stakeholder based on their value chain node and role."
        ),
        backstory=(
            "You are a senior discovery consultant who designs interview programmes "
            "for digital transformation engagements. You craft questions that surface "
            "process pain points, actors, needs, and capability gaps at each node of "
            "the value chain."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_interview_coordinator_task(
    agent: Agent,
    stakeholder_assignments: str = "",
) -> Task:
    assignments_block = (
        f"Stakeholder assignments:\n{stakeholder_assignments}\n\n"
        if stakeholder_assignments
        else ""
    )
    return Task(
        description=(
            f"{assignments_block}"
            "Design the stakeholder interview programme for this project.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='value_chain_tree', "
            "agent_name='interview_coordinator' to retrieve the approved value chain structure.\n"
            "2. For each stakeholder listed in the assignments above, design 5–8 tailored "
            "interview questions. Base the questions on:\n"
            "   - The value chain node(s) they are assigned to (their operational domain)\n"
            "   - Their job title and inferred responsibilities\n"
            "   - What actors, needs, and frustrations are likely at that node\n"
            "3. Structure your output as a JSON array where each element is:\n"
            "   {\n"
            "     \"stakeholder_id\": 1,\n"
            "     \"name\": \"Alice Chen\",\n"
            "     \"job_title\": \"Head of Ops\",\n"
            "     \"node_labels\": [\"Order Fulfilment\"],\n"
            "     \"questions\": [\n"
            "       \"Walk me through how an order is received and processed today.\",\n"
            "       \"What are the most common causes of delay in this process?\"\n"
            "     ]\n"
            "   }\n"
            "4. Use SQLiteStateTool with operation='write', key='interview_plan', "
            "agent_name='interview_coordinator' to save the JSON array.\n"
            "5. Use HumanInputTool with prompt: 'Please review the interview plan saved at "
            "outputs/interview_plan.json. Reply \"approved\" to proceed, or provide revision notes.'\n"
            "6. If revision notes are received, revise the plan and call HumanInputTool again. "
            "Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "A JSON interview plan saved to outputs/interview_plan.json containing one entry "
            "per assigned stakeholder with tailored questions. Confirmed approved by a human reviewer."
        ),
        agent=agent,
    )
```

- [ ] **Step 4: Create `agents/discovery/stakeholder_interviewer.py`**

```python
# agents/discovery/stakeholder_interviewer.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_stakeholder_interviewer(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Stakeholder Interviewer",
        goal=(
            "Conduct text-based interviews with each assigned stakeholder, "
            "capturing their responses verbatim to build a rich discovery transcript."
        ),
        backstory=(
            "You are an experienced discovery interviewer who builds rapport quickly "
            "and asks probing follow-up questions. You faithfully record responses "
            "without interpretation, preserving the stakeholder's own language."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_stakeholder_interviewer_task(
    agent: Agent,
    context_tasks: list[Task],
) -> Task:
    return Task(
        description=(
            "Conduct text-based interviews with each stakeholder listed in the interview plan.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='interview_plan', "
            "agent_name='stakeholder_interviewer' to retrieve the interview plan.\n"
            "2. For each stakeholder in the plan, conduct their interview:\n"
            "   a. Use HumanInputTool with a prompt that introduces yourself and the purpose "
            "of the interview, then asks the first question. Example:\n"
            "      'Hi [Name], I'm conducting a discovery interview for this engagement. "
            "I'd like to ask you about [node_labels]. "
            "First question: [questions[0]]'\n"
            "   b. Record the response, then ask each subsequent question in turn using "
            "HumanInputTool. Adapt follow-up phrasing naturally based on prior answers.\n"
            "   c. Once all questions are asked, thank the stakeholder and move to the next.\n"
            "3. Compile all Q&A pairs into a JSON array where each element is:\n"
            "   {\n"
            "     \"stakeholder_id\": 1,\n"
            "     \"name\": \"Alice Chen\",\n"
            "     \"node_labels\": [\"Order Fulfilment\"],\n"
            "     \"qa_pairs\": [\n"
            "       {\"question\": \"Walk me through how an order is processed.\", "
            "\"answer\": \"We receive orders via email...\"}\n"
            "     ]\n"
            "   }\n"
            "4. Use SQLiteStateTool with operation='write', key='interview_transcripts', "
            "agent_name='stakeholder_interviewer' to save the JSON array.\n"
        ),
        expected_output=(
            "A JSON transcript file saved to outputs/interview_transcripts.json containing "
            "all Q&A pairs for every interviewed stakeholder."
        ),
        agent=agent,
        context=context_tasks,
    )
```

- [ ] **Step 5: Create `agents/discovery/synthesis_analyst.py`**

```python
# agents/discovery/synthesis_analyst.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_synthesis_analyst(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Synthesis Analyst",
        goal=(
            "Synthesise stakeholder interview transcripts into structured discovery outputs: "
            "activity-level insights, a requirements register, and a value lever register."
        ),
        backstory=(
            "You are a senior strategy analyst who transforms raw interview data into "
            "structured consulting deliverables. You identify patterns across stakeholders, "
            "surface actors, needs, and frustrations at each process activity, and articulate "
            "the value levers that unlock transformation."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_synthesis_analyst_task(
    agent: Agent,
    context_tasks: list[Task],
) -> Task:
    return Task(
        description=(
            "Synthesise interview transcripts into three structured outputs.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='interview_transcripts', "
            "agent_name='synthesis_analyst' to retrieve all interview transcripts.\n"
            "2. Use SQLiteStateTool with operation='read', key='value_chain_tree', "
            "agent_name='synthesis_analyst' to retrieve the value chain node labels.\n"
            "3. Produce activity insights: for each L3 value chain node referenced in the "
            "transcripts, extract a JSON object:\n"
            "   {\n"
            "     \"label\": \"Goods-in Inspection\",\n"
            "     \"level\": \"L3\",\n"
            "     \"actors\": [\"Warehouse Operative\", \"Quality Inspector\"],\n"
            "     \"needs\": [\"Real-time visibility of delivery schedule\"],\n"
            "     \"frustrations\": [\"Manual paper-based receipt process causes delays\"]\n"
            "   }\n"
            "   Build an array covering every L3 node mentioned by at least one interviewee.\n"
            "4. Use SQLiteStateTool with operation='write', key='activity_insights', "
            "agent_name='synthesis_analyst' to save the activity insights array.\n"
            "5. Produce a requirements register: identify 5–15 discrete requirements surfaced "
            "across all transcripts. Each requirement:\n"
            "   {\"id\": \"REQ-001\", \"description\": \"...\", "
            "\"source_stakeholder_ids\": [1, 2], \"priority\": \"High|Medium|Low\"}\n"
            "6. Use SQLiteStateTool with operation='write', key='requirements', "
            "agent_name='synthesis_analyst' to save the requirements array.\n"
            "7. Produce a value lever register: identify 3–8 distinct value levers (themes "
            "of value creation). Each lever:\n"
            "   {\"lever\": \"Process Automation\", \"description\": \"...\", "
            "\"supporting_requirement_ids\": [\"REQ-001\"]}\n"
            "8. Use SQLiteStateTool with operation='write', key='value_levers', "
            "agent_name='synthesis_analyst' to save the value levers array.\n"
            "9. Use HumanInputTool with prompt: 'Please review the synthesis outputs: "
            "outputs/activity_insights.json, outputs/requirements.json, "
            "outputs/value_levers.json. Reply \"approved\" to proceed to Value Design, "
            "or provide revision notes.'\n"
            "10. If revision notes are received, revise the relevant outputs and call "
            "HumanInputTool again. Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "Three JSON files saved via SQLiteStateTool: "
            "activity_insights (per-node actors/needs/frustrations), "
            "requirements (requirements register), "
            "value_levers (value lever register). "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
        context=context_tasks,
    )
```

- [ ] **Step 6: Run the agent tests**

```bash
python -m pytest tests/test_discovery_interviews_agents.py -v
```

Expected: 5 PASS.

- [ ] **Step 7: Commit**

```bash
git add agents/discovery/interview_coordinator.py \
        agents/discovery/stakeholder_interviewer.py \
        agents/discovery/synthesis_analyst.py \
        tests/test_discovery_interviews_agents.py
git commit -m "feat: add Interview Coordinator, Stakeholder Interviewer, Synthesis Analyst agents"
```

---

## Task 3: Discovery interviews crew factory + registry

**Files:**
- Create: `agents/crews/discovery_interviews_crew.py`
- Modify: `agents/tools/registry.py`

### Background
The crew factory follows the pattern in `agents/crews/discovery_mapping_crew.py`. It calls `get_tools_for_agent` once per agent role. `hitl_tool` override is supported for Chainlit integration. Stakeholder assignments arrive as a pre-formatted string (injected at crew creation time) and are passed directly into `create_interview_coordinator_task`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_discovery_interviews_crew.py
"""Unit tests for the discovery interviews crew factory."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM, Process


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


def _build_crew(mock_llm, stakeholder_assignments=None):
    with patch("agents.crews.discovery_interviews_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.discovery_interviews_crew import create_discovery_interviews_crew
        return create_discovery_interviews_crew(
            slug="test",
            run_id=1,
            llm_mode="standard",
            sector="logistics",
            stakeholder_assignments=stakeholder_assignments or [],
            llm=mock_llm,
        )


def test_discovery_interviews_crew_has_three_agents(mock_llm):
    crew = _build_crew(mock_llm)
    assert len(crew.agents) == 3


def test_discovery_interviews_crew_has_three_tasks(mock_llm):
    crew = _build_crew(mock_llm)
    assert len(crew.tasks) == 3


def test_discovery_interviews_crew_sequential(mock_llm):
    crew = _build_crew(mock_llm)
    assert crew.process == Process.sequential


def test_discovery_interviews_crew_injects_assignments(mock_llm):
    """Coordinator task description includes the formatted stakeholder string."""
    assignments = [
        {"name": "Alice Chen", "job_title": "Head of Ops", "level": "L2", "node_label": "Order Fulfilment"},
    ]
    crew = _build_crew(mock_llm, stakeholder_assignments=assignments)
    coordinator_task = crew.tasks[0]
    assert "Alice Chen" in coordinator_task.description


def test_discovery_interviews_crew_uses_registry(mock_llm):
    """get_tools_for_agent is called for all three agent roles."""
    with patch(
        "agents.crews.discovery_interviews_crew.get_tools_for_agent", return_value=[]
    ) as mock_reg:
        from agents.crews.discovery_interviews_crew import create_discovery_interviews_crew
        create_discovery_interviews_crew(
            slug="myslug", run_id=5, llm_mode="standard", sector="rail",
            stakeholder_assignments=[], llm=mock_llm,
        )
    called_agents = {c.args[0] for c in mock_reg.call_args_list}
    assert "interview_coordinator" in called_agents
    assert "stakeholder_interviewer" in called_agents
    assert "synthesis_analyst" in called_agents


def test_registry_has_interview_coordinator_entry():
    with patch("agents.tools.registry.get_settings") as ms, \
         patch("agents.tools.registry.load_project_config", return_value={"sector": "rail"}):
        ms.return_value.projects_dir = "/tmp"
        from agents.tools.registry import get_tools_for_agent
        tools = get_tools_for_agent("interview_coordinator", slug="t", run_id=1, sector="rail")
    assert len(tools) > 0


def test_registry_has_stakeholder_interviewer_entry():
    with patch("agents.tools.registry.get_settings") as ms, \
         patch("agents.tools.registry.load_project_config", return_value={"sector": "rail"}):
        ms.return_value.projects_dir = "/tmp"
        from agents.tools.registry import get_tools_for_agent
        tools = get_tools_for_agent("stakeholder_interviewer", slug="t", run_id=1, sector="rail")
    assert len(tools) > 0


def test_registry_has_synthesis_analyst_entry():
    with patch("agents.tools.registry.get_settings") as ms, \
         patch("agents.tools.registry.load_project_config", return_value={"sector": "rail"}):
        ms.return_value.projects_dir = "/tmp"
        from agents.tools.registry import get_tools_for_agent
        tools = get_tools_for_agent("synthesis_analyst", slug="t", run_id=1, sector="rail")
    assert len(tools) > 0
```

- [ ] **Step 2: Run to verify all fail**

```bash
python -m pytest tests/test_discovery_interviews_crew.py -v
```

Expected: 8 FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `agents/crews/discovery_interviews_crew.py`**

```python
# agents/crews/discovery_interviews_crew.py
"""Discovery Interviews crew — Interview Coordinator → Stakeholder Interviewer → Synthesis Analyst."""
from crewai import Crew, Process, LLM
from agents.llm import get_pam_llm
from agents.tools.registry import get_tools_for_agent
from agents.discovery.interview_coordinator import (
    create_interview_coordinator,
    create_interview_coordinator_task,
)
from agents.discovery.stakeholder_interviewer import (
    create_stakeholder_interviewer,
    create_stakeholder_interviewer_task,
)
from agents.discovery.synthesis_analyst import (
    create_synthesis_analyst,
    create_synthesis_analyst_task,
)


def _format_assignments(stakeholder_assignments: list[dict]) -> str:
    """Format a list of assignment dicts into a human-readable block."""
    if not stakeholder_assignments:
        return "(No stakeholder assignments provided)"
    lines = []
    for a in stakeholder_assignments:
        name = a.get("name", "Unknown")
        job_title = a.get("job_title", "")
        level = a.get("level", "")
        node_label = a.get("node_label", "")
        line = f"- {name}"
        if job_title:
            line += f" ({job_title})"
        if level and node_label:
            line += f" → {level}: {node_label}"
        lines.append(line)
    return "\n".join(lines)


def create_discovery_interviews_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    stakeholder_assignments: list[dict],
    llm: LLM | None = None,
    hitl_tool=None,
) -> Crew:
    """Create a sequential crew that conducts and synthesises stakeholder interviews.

    stakeholder_assignments: list of dicts with keys: name, job_title, level, node_label.
    """
    if llm is None:
        llm = get_pam_llm()

    assignments_str = _format_assignments(stakeholder_assignments)

    coordinator = create_interview_coordinator(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("interview_coordinator", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )
    interviewer = create_stakeholder_interviewer(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("stakeholder_interviewer", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )
    analyst = create_synthesis_analyst(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("synthesis_analyst", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )

    t1 = create_interview_coordinator_task(agent=coordinator, stakeholder_assignments=assignments_str)
    t2 = create_stakeholder_interviewer_task(agent=interviewer, context_tasks=[t1])
    t3 = create_synthesis_analyst_task(agent=analyst, context_tasks=[t2])

    return Crew(
        agents=[coordinator, interviewer, analyst],
        tasks=[t1, t2, t3],
        process=Process.sequential,
        verbose=True,
    )
```

- [ ] **Step 4: Add registry entries to `agents/tools/registry.py`**

In `agents/tools/registry.py`, find the `tool_map` dict and add these three entries after `"business_plan_generator"`:

```python
        "interview_coordinator": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
        "stakeholder_interviewer": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
        "synthesis_analyst": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
```

- [ ] **Step 5: Run crew and registry tests**

```bash
python -m pytest tests/test_discovery_interviews_crew.py -v
```

Expected: 8 PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/crews/discovery_interviews_crew.py agents/tools/registry.py \
        tests/test_discovery_interviews_crew.py
git commit -m "feat: add discovery interviews crew factory and registry entries"
```

---

## Task 4: `run_service.py` — `discovery_interviews` branch

**Files:**
- Modify: `api/services/run_service.py`

### Background
`build_and_run_crew(slug, crew_name, run_id)` is called by `RunCrewTool._arun` (via PAM) and `dispatch_crew` (direct trigger). `run_id` is the crew_run row's ID. To get the `orchestration_run_id`, query `crew_runs WHERE id=run_id`. Then fetch stakeholder assignments and enrich them with stakeholder name/job_title from the `stakeholders` table.

New imports needed at module top: `fetch_stakeholder_assignments`, `fetch_stakeholders` from `api.database`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_service_interviews.py
"""Tests for the discovery_interviews branch in build_and_run_crew."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_build_and_run_crew_raises_for_non_agent_interview_method():
    """If interview_method != 'agent', discovery_interviews raises ValueError."""
    from api.database import get_connection, insert_project, insert_crew_run, fetch_project
    async with get_connection("rsi-test") as conn:
        await insert_project(
            conn, slug="rsi-test", llm_mode="standard", sector="rail",
            config_json='{"interview_method": "none"}'
        )
        project = await fetch_project(conn, slug="rsi-test")
        crew_run_id = await insert_crew_run(
            conn, project_id=project["id"], crew_name="discovery_interviews", status="running"
        )

    with patch("api.services.run_service.load_project_config",
               return_value={"llm_mode": "standard", "sector": "rail", "interview_method": "none"}):
        from api.services.run_service import build_and_run_crew
        with pytest.raises(ValueError, match="interview_method"):
            await build_and_run_crew("rsi-test", "discovery_interviews", crew_run_id)


@pytest.mark.asyncio
async def test_build_and_run_crew_calls_interviews_crew_when_agent():
    """If interview_method='agent', discovery_interviews crew is created and kicked off."""
    from api.database import get_connection, insert_project, insert_crew_run, fetch_project, insert_orchestration_run
    async with get_connection("rsi-agent-test") as conn:
        await insert_project(
            conn, slug="rsi-agent-test", llm_mode="standard", sector="rail",
            config_json='{"interview_method": "agent"}'
        )
        project = await fetch_project(conn, slug="rsi-agent-test")
        orch_run_id = await insert_orchestration_run(conn, project_id=project["id"])
        crew_run_id = await insert_crew_run(
            conn, project_id=project["id"], crew_name="discovery_interviews",
            status="running", orchestration_run_id=orch_run_id
        )

    mock_crew = AsyncMock()
    mock_crew.kickoff_async = AsyncMock(return_value="done")

    with patch("api.services.run_service.load_project_config",
               return_value={"llm_mode": "standard", "sector": "rail", "interview_method": "agent"}), \
         patch("agents.crews.discovery_interviews_crew.create_discovery_interviews_crew",
               return_value=mock_crew) as mock_factory:
        from api.services.run_service import build_and_run_crew
        await build_and_run_crew("rsi-agent-test", "discovery_interviews", crew_run_id)

    mock_crew.kickoff_async.assert_awaited_once()
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_run_service_interviews.py -v
```

Expected: 2 FAIL.

- [ ] **Step 3: Add `discovery_interviews` branch to `api/services/run_service.py`**

First, update the import at the top of the file to add `fetch_stakeholder_assignments` and `fetch_stakeholders`:

```python
from api.database import (
    get_connection,
    update_crew_run_status,
    fetch_project,
    fetch_documents,
    fetch_stakeholder_assignments,
    fetch_stakeholders,
)
```

Then add the `discovery_interviews` branch in `build_and_run_crew`, **before** the `elif crew_name == "discovery_mapping":` block:

```python
    if crew_name == "discovery_interviews":
        interview_method = config.get("interview_method", "none")
        if interview_method != "agent":
            raise ValueError(
                f"Cannot dispatch discovery_interviews crew: "
                f"interview_method is '{interview_method}', expected 'agent'"
            )

        # Recover orchestration_run_id from the crew_run row
        async with get_connection(slug) as conn:
            async with conn.execute(
                "SELECT orchestration_run_id FROM crew_runs WHERE id=?", (run_id,)
            ) as cur:
                cr_row = await cur.fetchone()
            orchestration_run_id = cr_row["orchestration_run_id"] if cr_row else None
            if not orchestration_run_id:
                raise ValueError(
                    f"crew_run {run_id} has no orchestration_run_id — "
                    "discovery_interviews must be dispatched via PAM"
                )

            # Fetch assignments and enrich with stakeholder details
            raw_assignments = await fetch_stakeholder_assignments(
                conn, orchestration_run_id=orchestration_run_id
            )
            project_row = await fetch_project(conn, slug=slug)
            all_stakeholders = await fetch_stakeholders(conn, project_id=project_row["id"])
            stakeholder_map = {s["id"]: s for s in all_stakeholders}

            stakeholder_assignments = [
                {
                    "name": stakeholder_map.get(a["stakeholder_id"], {}).get("name", "Unknown"),
                    "job_title": stakeholder_map.get(a["stakeholder_id"], {}).get("job_title", ""),
                    "level": a["level"],
                    "node_label": a["node_label"],
                }
                for a in raw_assignments
                if a["stakeholder_id"] in stakeholder_map
            ]

        from agents.crews.discovery_interviews_crew import create_discovery_interviews_crew
        crew = create_discovery_interviews_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            stakeholder_assignments=stakeholder_assignments,
        )

    elif crew_name == "discovery_mapping":
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_run_service_interviews.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add api/services/run_service.py tests/test_run_service_interviews.py
git commit -m "feat: add discovery_interviews branch to run_service with assignment enrichment"
```

---

## Task 5: PAM wiring — `pam_agent`, `pam_crew`, `orchestration_service`

**Files:**
- Modify: `agents/pam/pam_agent.py`
- Modify: `agents/crews/pam_crew.py`
- Modify: `api/services/orchestration_service.py`

### Background
PAM Phase 2 (`create_pam_resume_crew`) needs a new optional first task when `interview_method='agent'`. The `orchestration_service.run_pam_phase2` reads `interview_method` from project config and passes it through.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pam_crew.py` — these new tests go after the existing ones:

```python
# Add to tests/test_pam_crew.py

def _build_resume_crew_with_interviews(mock_llm):
    with patch("agents.crews.pam_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.pam_crew import create_pam_resume_crew
        return create_pam_resume_crew(
            slug="test",
            orchestration_run_id=1,
            llm_mode="standard",
            interview_method="agent",
            llm=mock_llm,
        )


def test_pam_resume_crew_agent_method_has_five_tasks(mock_llm):
    """When interview_method='agent', the resume crew has 5 tasks (interviews + 4 crews)."""
    crew = _build_resume_crew_with_interviews(mock_llm)
    assert len(crew.tasks) == 5


def test_pam_resume_crew_agent_method_first_task_references_discovery_interviews(mock_llm):
    crew = _build_resume_crew_with_interviews(mock_llm)
    assert "discovery_interviews" in crew.tasks[0].description


def test_pam_resume_crew_none_method_has_four_tasks(mock_llm):
    """When interview_method='none', the resume crew still has 4 tasks (no interviews prepended)."""
    crew = _build_resume_crew(mock_llm)
    assert len(crew.tasks) == 4
```

Add to `tests/test_orchestration_service.py`:

```python
# Add to tests/test_orchestration_service.py

@pytest.mark.asyncio
async def test_run_pam_phase2_passes_interview_method_to_crew():
    """run_pam_phase2 reads interview_method from config and passes it to create_pam_resume_crew."""
    from api.database import get_connection, insert_project, insert_orchestration_run, fetch_project

    async with get_connection("orch-imethod-test") as conn:
        await insert_project(
            conn, slug="orch-imethod-test",
            llm_mode="standard", sector="rail", config_json="{}"
        )
        project = await fetch_project(conn, slug="orch-imethod-test")
        run_id = await insert_orchestration_run(conn, project_id=project["id"])

    mock_crew = AsyncMock()
    mock_crew.kickoff_async = AsyncMock(return_value=None)

    with patch(
        "api.services.orchestration_service.load_project_config",
        return_value={"llm_mode": "standard", "interview_method": "agent"},
    ), patch(
        "agents.crews.pam_crew.create_pam_resume_crew", return_value=mock_crew
    ) as mock_factory:
        from api.services.orchestration_service import run_pam_phase2
        await run_pam_phase2("orch-imethod-test", run_id)

    mock_factory.assert_called_once()
    call_kwargs = mock_factory.call_args.kwargs
    assert call_kwargs.get("interview_method") == "agent"
```

- [ ] **Step 2: Run to verify failures**

```bash
python -m pytest tests/test_pam_crew.py tests/test_orchestration_service.py -v 2>&1 | grep FAILED
```

Expected: 4 new tests fail.

- [ ] **Step 3: Add `create_run_discovery_interviews_task` to `agents/pam/pam_agent.py`**

Add after `create_run_discovery_mapping_task`:

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

- [ ] **Step 4: Update `create_pam_resume_crew` in `agents/crews/pam_crew.py`**

Update the import at the top of the file:

```python
from agents.pam.pam_agent import (
    create_pam_agent,
    create_run_discovery_mapping_task,
    create_run_discovery_interviews_task,
    create_run_value_design_task,
    create_run_architecture_task,
    create_run_delivery_task,
    create_run_business_plan_task,
)
```

Replace `create_pam_resume_crew` with:

```python
def create_pam_resume_crew(
    slug: str,
    orchestration_run_id: int,
    llm_mode: str,
    interview_method: str = "none",
    llm: LLM | None = None,
) -> Crew:
    """Phase 2 PAM crew: optionally discovery_interviews, then value_design → business_plan."""
    if llm is None:
        llm = get_pam_llm()

    tools = get_tools_for_agent("pam", slug=slug, run_id=orchestration_run_id)
    pam = create_pam_agent(slug=slug, llm=llm, tools=tools)

    tasks = []
    if interview_method == "agent":
        t_interviews = create_run_discovery_interviews_task(pam, slug=slug, context_tasks=[])
        tasks.append(t_interviews)
        context_for_value_design = [t_interviews]
    else:
        context_for_value_design = []

    t1 = create_run_value_design_task(pam, slug=slug, context_tasks=context_for_value_design)
    t2 = create_run_architecture_task(pam, slug=slug, context_tasks=[t1])
    t3 = create_run_delivery_task(pam, slug=slug, context_tasks=[t2])
    t4 = create_run_business_plan_task(pam, slug=slug, context_tasks=[t3])
    tasks += [t1, t2, t3, t4]

    return Crew(
        agents=[pam],
        tasks=tasks,
        process=Process.sequential,
        verbose=True,
    )
```

- [ ] **Step 5: Update `run_pam_phase2` in `api/services/orchestration_service.py`**

Replace the `crew = create_pam_resume_crew(...)` call in `run_pam_phase2`:

```python
async def run_pam_phase2(slug: str, orchestration_run_id: int) -> None:
    """Run the resume phase (optionally interviews, then value_design → business_plan)."""
    try:
        settings = get_settings()
        config = load_project_config(Path(settings.projects_dir) / slug)
        from agents.crews.pam_crew import create_pam_resume_crew
        crew = create_pam_resume_crew(
            slug=slug,
            orchestration_run_id=orchestration_run_id,
            llm_mode=config.get("llm_mode", "standard"),
            interview_method=config.get("interview_method", "none"),
        )
        await crew.kickoff_async()
        async with get_connection(slug) as conn:
            await update_orchestration_run_status(
                conn, run_id=orchestration_run_id, status="completed"
            )
    except Exception:
        _log.exception(
            "PAM phase2 failed for slug=%s orchestration_run_id=%d",
            slug,
            orchestration_run_id,
        )
        async with get_connection(slug) as conn:
            await update_orchestration_run_status(
                conn, run_id=orchestration_run_id, status="failed"
            )
```

- [ ] **Step 6: Run PAM and orchestration tests**

```bash
python -m pytest tests/test_pam_crew.py tests/test_orchestration_service.py -v
```

Expected: all pass (3 new pam_crew tests + 1 new orchestration test).

- [ ] **Step 7: Commit**

```bash
git add agents/pam/pam_agent.py agents/crews/pam_crew.py \
        api/services/orchestration_service.py
git commit -m "feat: wire discovery_interviews into PAM Phase 2 with interview_method gate"
```

---

## Task 6: Schema correction — `value_proposition_generator`

**Files:**
- Modify: `agents/value_design/value_proposition_generator.py`

### Background
The existing proposition schema has: `id, title, change_articulation, impacted_stakeholder_groups, value_estimate, value_estimate_rationale, supporting_evidence`. We add:
- `activity_refs: ["L3:Goods-in Inspection"]` — which L3 node(s) this proposition addresses
- `beneficiaries: [{group: "...", benefit_types: [...]}]` — who benefits and how

The agent also gains an optional step 4b: read `activity_insights` and use it to populate `activity_refs` and `beneficiaries`. If `activity_insights` is absent (non-agent-interview projects), infer from available data.

Valid `benefit_types`: `time_saving`, `cost_reduction`, `quality_improvement`, `risk_reduction`, `experience`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_value_proposition_generator.py
"""Tests for the updated value_proposition_generator task schema."""
from unittest.mock import MagicMock, patch


def test_task_description_includes_activity_refs():
    """Task description requires agent to produce activity_refs on each proposition."""
    from agents.value_design.value_proposition_generator import create_value_proposition_generator_task
    agent = MagicMock()
    with patch("agents.value_design.value_proposition_generator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_value_proposition_generator_task(agent=agent)
    _, kwargs = MockTask.call_args
    assert "activity_refs" in kwargs["description"]


def test_task_description_includes_beneficiaries():
    """Task description requires agent to produce beneficiaries on each proposition."""
    from agents.value_design.value_proposition_generator import create_value_proposition_generator_task
    agent = MagicMock()
    with patch("agents.value_design.value_proposition_generator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_value_proposition_generator_task(agent=agent)
    _, kwargs = MockTask.call_args
    assert "beneficiaries" in kwargs["description"]


def test_task_description_reads_activity_insights_opportunistically():
    """Task description reads activity_insights and handles missing data gracefully."""
    from agents.value_design.value_proposition_generator import create_value_proposition_generator_task
    agent = MagicMock()
    with patch("agents.value_design.value_proposition_generator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_value_proposition_generator_task(agent=agent)
    _, kwargs = MockTask.call_args
    assert "activity_insights" in kwargs["description"]
    # Must instruct agent to skip if absent (Error: prefix)
    assert "Error:" in kwargs["description"]


def test_task_description_lists_valid_benefit_types():
    """Task description enumerates the valid benefit_types."""
    from agents.value_design.value_proposition_generator import create_value_proposition_generator_task
    agent = MagicMock()
    with patch("agents.value_design.value_proposition_generator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_value_proposition_generator_task(agent=agent)
    _, kwargs = MockTask.call_args
    for bt in ("time_saving", "cost_reduction", "quality_improvement", "risk_reduction", "experience"):
        assert bt in kwargs["description"], f"benefit_type '{bt}' missing from task description"
```

- [ ] **Step 2: Run to verify failures**

```bash
python -m pytest tests/test_value_proposition_generator.py -v
```

Expected: 4 FAIL.

- [ ] **Step 3: Rewrite the task description in `agents/value_design/value_proposition_generator.py`**

Replace the entire `create_value_proposition_generator_task` function:

```python
def create_value_proposition_generator_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Synthesise the Discovery crew outputs into a set of value propositions.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='requirements', "
            "agent_name='value_proposition_generator' to retrieve the requirements register.\n"
            "2. Use SQLiteStateTool with operation='read', key='value_levers', "
            "agent_name='value_proposition_generator' to retrieve the value levers.\n"
            "3. Use SQLiteStateTool with operation='read', key='value_chain_summary', "
            "agent_name='value_proposition_generator' to retrieve the value chain summary.\n"
            "4. Use SQLiteStateTool with operation='read', key='user_journeys', "
            "agent_name='value_proposition_generator' to check for a user journey register. "
            "If the result starts with 'Error:', the register does not exist — skip it.\n"
            "4b. Use SQLiteStateTool with operation='read', key='activity_insights', "
            "agent_name='value_proposition_generator' to check for activity-level insights "
            "(actors, needs, frustrations per process activity). "
            "If the result starts with 'Error:', activity_insights do not exist — skip it and "
            "infer activity_refs from the value_chain_summary activities list instead.\n"
            "5. Identify 3–7 distinct value propositions by grouping related requirements, "
            "levers, pain points, and journey/activity opportunities. Each proposition should "
            "represent a coherent area of change with a clear business outcome.\n"
            "6. Produce a JSON array where each item follows this schema exactly:\n"
            "   {\n"
            "     \"id\": \"VP-001\",\n"
            "     \"title\": \"Short label (max 6 words)\",\n"
            "     \"change_articulation\": \"2–3 sentences describing what changes and why it matters\",\n"
            "     \"activity_refs\": [\"L3:Goods-in Inspection\", \"L3:Invoice Processing\"],\n"
            "     \"impacted_stakeholder_groups\": [\"...\"],\n"
            "     \"beneficiaries\": [\n"
            "       {\n"
            "         \"group\": \"Warehouse Operative\",\n"
            "         \"benefit_types\": [\"time_saving\", \"experience\"]\n"
            "       }\n"
            "     ],\n"
            "     \"value_estimate\": \"High|Medium|Low\",\n"
            "     \"value_estimate_rationale\": \"1–2 sentences justifying the estimate\",\n"
            "     \"supporting_evidence\": [\n"
            "       {\"type\": \"requirement|lever|pain_point|journey|activity\", \"ref\": \"...\", \"summary\": \"...\"}\n"
            "     ]\n"
            "   }\n"
            "   IDs must be sequential: VP-001, VP-002, etc.\n"
            "   activity_refs: list of strings in the format 'L3:<node_label>' "
            "(use 'L2:<node_label>' if no L3 nodes are available for this proposition). "
            "If activity_insights were absent, infer from the value chain summary activities.\n"
            "   beneficiaries: list one entry per distinct stakeholder group that benefits. "
            "Valid benefit_types: time_saving, cost_reduction, quality_improvement, "
            "risk_reduction, experience. A beneficiary may have multiple benefit_types.\n"
            "7. Use SQLiteStateTool with operation='write', key='propositions', "
            "agent_name='value_proposition_generator' to save the JSON array.\n"
            "8. Use HumanInputTool with prompt: 'Please review the value propositions saved at "
            "outputs/propositions.json. Reply \"approved\" to proceed to portfolio scoring, "
            "or provide revision notes.'\n"
            "9. If revision notes are received (not 'approved'), revise the propositions and "
            "call HumanInputTool again. Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "A JSON array of 3–7 value propositions saved to outputs/propositions.json, "
            "each with id, title, change_articulation, activity_refs, beneficiaries, "
            "impacted_stakeholder_groups, value_estimate, value_estimate_rationale, and "
            "supporting_evidence. Confirmed approved by a human reviewer."
        ),
        agent=agent,
    )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_value_proposition_generator.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Run full suite**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add agents/value_design/value_proposition_generator.py \
        tests/test_value_proposition_generator.py
git commit -m "feat: add activity_refs and beneficiaries to value proposition schema"
```

---

## Task 7: Schema correction — `initiative_identifier`

**Files:**
- Modify: `agents/architecture/initiative_identifier.py`

### Background
Replace:
- `capability_gaps: [string]` → `capability_uplifts: [{dimension, description}]`
  - Valid dimensions: `people`, `data`, `systems`, `organisation`, `partnership`, `architectural`, `operating_model`
- `category: "enabling|operating_model|business_change"` → `initiative_type: "enabler" | "change_activity"`
- Add `enabler_dependencies: [INIT-id]` — IDs of other enablers this depends on (enabler initiatives only; `[]` for change_activity)
- Add `change_dependencies: [INIT-id]` — IDs of enabler initiatives this depends on (change_activity only; `[]` for enabler)
- Add `cost_estimate: {low, high, currency, rationale}`

The scoring/HITL flow is unchanged. The instruction to categorise initiatives (step 7) is updated.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_initiative_identifier.py
"""Tests for the updated initiative_identifier task schema."""
from unittest.mock import MagicMock, patch


def test_task_description_includes_capability_uplifts():
    from agents.architecture.initiative_identifier import create_initiative_identifier_task
    agent = MagicMock()
    with patch("agents.architecture.initiative_identifier.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_initiative_identifier_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "capability_uplifts" in kwargs["description"]


def test_task_description_lists_all_seven_dimensions():
    from agents.architecture.initiative_identifier import create_initiative_identifier_task
    agent = MagicMock()
    with patch("agents.architecture.initiative_identifier.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_initiative_identifier_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    for dim in ("people", "data", "systems", "organisation", "partnership", "architectural", "operating_model"):
        assert dim in kwargs["description"], f"Dimension '{dim}' missing from task description"


def test_task_description_includes_initiative_type():
    from agents.architecture.initiative_identifier import create_initiative_identifier_task
    agent = MagicMock()
    with patch("agents.architecture.initiative_identifier.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_initiative_identifier_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "initiative_type" in kwargs["description"]
    assert "enabler" in kwargs["description"]
    assert "change_activity" in kwargs["description"]


def test_task_description_includes_dependency_fields():
    from agents.architecture.initiative_identifier import create_initiative_identifier_task
    agent = MagicMock()
    with patch("agents.architecture.initiative_identifier.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_initiative_identifier_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "enabler_dependencies" in kwargs["description"]
    assert "change_dependencies" in kwargs["description"]


def test_task_description_includes_cost_estimate():
    from agents.architecture.initiative_identifier import create_initiative_identifier_task
    agent = MagicMock()
    with patch("agents.architecture.initiative_identifier.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_initiative_identifier_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "cost_estimate" in kwargs["description"]


def test_task_description_does_not_use_old_schema():
    """Old fields 'capability_gaps' and 'category' must not appear in the new schema."""
    from agents.architecture.initiative_identifier import create_initiative_identifier_task
    agent = MagicMock()
    with patch("agents.architecture.initiative_identifier.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_initiative_identifier_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "capability_gaps" not in kwargs["description"]
    # 'category' may appear in prose but not as a schema field key
    # Check it doesn't appear as a JSON key surrounded by quotes
    assert '"category"' not in kwargs["description"]
```

- [ ] **Step 2: Run to verify failures**

```bash
python -m pytest tests/test_initiative_identifier.py -v
```

Expected: 6 FAIL.

- [ ] **Step 3: Rewrite `create_initiative_identifier_task` in `agents/architecture/initiative_identifier.py`**

Replace the entire `create_initiative_identifier_task` function:

```python
def create_initiative_identifier_task(
    agent: Agent, context_tasks: list[Task]
) -> Task:
    return Task(
        description=(
            "Identify the initiatives required to deliver the value propositions "
            "given the current-state architecture.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='propositions', "
            "agent_name='initiative_identifier' to retrieve the value propositions.\n"
            "2. Use SQLiteStateTool with operation='read', key='architecture_register', "
            "agent_name='initiative_identifier' to retrieve the architecture register.\n"
            "3. Use SQLiteStateTool with operation='read', key='requirements', "
            "agent_name='initiative_identifier' to retrieve the requirements register.\n"
            "4. For each value proposition, analyse what capabilities it requires and compare "
            "against the technology_layer and organisation_layer in the architecture register "
            "to identify specific capability gaps.\n"
            "5. Define one or more initiatives per proposition to close identified gaps. "
            "One initiative can address gaps from multiple propositions — avoid duplicates.\n"
            "6. Score each initiative on complexity (1 = simple configuration change, "
            "5 = multi-year organisational transformation) with a rationale.\n"
            "7. Classify each initiative:\n"
            "   - initiative_type='enabler': primarily technology, data, or infrastructure "
            "change that unlocks other change. Populate enabler_dependencies with the IDs of "
            "other enabler initiatives this one depends on (empty list if none).\n"
            "   - initiative_type='change_activity': process, organisational, or "
            "strategic change that requires enablers to be in place first. Populate "
            "change_dependencies with the IDs of enabler initiatives that must complete "
            "before this one can run (empty list if none).\n"
            "8. For each initiative, identify the capability uplifts required across one or "
            "more of these dimensions: people, data, systems, organisation, partnership, "
            "architectural, operating_model. Each uplift should be a distinct, actionable "
            "statement of what the organisation needs to be able to do.\n"
            "9. Estimate the cost range for each initiative in GBP. Provide a low and high "
            "estimate with a brief rationale based on complexity_score and capability_uplifts.\n"
            "10. Produce a JSON array where each item follows this schema exactly:\n"
            "   {\n"
            "     \"id\": \"INIT-001\",\n"
            "     \"title\": \"Short initiative title (max 8 words)\",\n"
            "     \"description\": \"2–3 sentences describing what this initiative delivers\",\n"
            "     \"proposition_ids\": [\"VP-001\", \"VP-002\"],\n"
            "     \"capability_uplifts\": [\n"
            "       {\n"
            "         \"dimension\": \"systems\",\n"
            "         \"description\": \"Implement warehouse management system with real-time tracking\"\n"
            "       },\n"
            "       {\n"
            "         \"dimension\": \"people\",\n"
            "         \"description\": \"Train warehouse operatives on digital receipt processes\"\n"
            "       }\n"
            "     ],\n"
            "     \"initiative_type\": \"enabler\",\n"
            "     \"enabler_dependencies\": [],\n"
            "     \"change_dependencies\": [],\n"
            "     \"complexity_score\": 3,\n"
            "     \"complexity_rationale\": \"One sentence justifying the score\",\n"
            "     \"cost_estimate\": {\n"
            "       \"low\": 50000,\n"
            "       \"high\": 150000,\n"
            "       \"currency\": \"GBP\",\n"
            "       \"rationale\": \"Mid-complexity system integration with training uplift\"\n"
            "     },\n"
            "     \"related_requirements\": [\"REQ-001\"]\n"
            "   }\n"
            "   IDs must be sequential: INIT-001, INIT-002, etc.\n"
            "   Rules:\n"
            "   - enabler initiatives: set enabler_dependencies (other enablers required first), "
            "set change_dependencies to [].\n"
            "   - change_activity initiatives: set change_dependencies (enabler IDs required first), "
            "set enabler_dependencies to [].\n"
            "   - Valid dimensions: people, data, systems, organisation, partnership, "
            "architectural, operating_model.\n"
            "11. Use SQLiteStateTool with operation='write', key='initiative_register', "
            "agent_name='initiative_identifier' to save the JSON array.\n"
            "12. Use HumanInputTool with prompt: 'Please review the initiative register saved at "
            "outputs/initiative_register.json. Reply \"approved\" to conclude the Architecture "
            "phase, or provide notes.'\n"
            "13. If revision notes are received, revise and call HumanInputTool again. "
            "Maximum 3 revision cycles.\n"
        ),
        expected_output=(
            "A JSON initiative register saved to outputs/initiative_register.json "
            "containing at least 1 initiative per approved value proposition, "
            "each with id, title, description, proposition_ids, capability_uplifts "
            "(with dimension and description), initiative_type (enabler or change_activity), "
            "enabler_dependencies, change_dependencies, complexity_score, complexity_rationale, "
            "cost_estimate (low, high, currency, rationale), and related_requirements. "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
        context=context_tasks,
    )
```

- [ ] **Step 4: Update `ui/src/types.ts` — `Initiative` interface**

Replace the existing `Initiative` interface in `ui/src/types.ts`:

```typescript
export interface CapabilityUplift {
  dimension: 'people' | 'data' | 'systems' | 'organisation' | 'partnership' | 'architectural' | 'operating_model'
  description: string
}

export interface CostEstimate {
  low: number
  high: number
  currency: string
  rationale: string
}

export interface Initiative {
  id: string
  title: string
  description: string
  proposition_ids: string[]
  capability_uplifts: CapabilityUplift[]
  initiative_type: 'enabler' | 'change_activity'
  enabler_dependencies: string[]
  change_dependencies: string[]
  complexity_score: number
  complexity_rationale: string
  cost_estimate: CostEstimate
  related_requirements: string[]
  // Roadmap fields (added by roadmap_generator)
  value_streams?: string[]
  period?: string
}
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_initiative_identifier.py -v
```

Expected: 6 PASS.

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add agents/architecture/initiative_identifier.py \
        tests/test_initiative_identifier.py \
        ui/src/types.ts
git commit -m "feat: update initiative schema with capability_uplifts, initiative_type, dependencies, cost_estimate"
```

---

## Final: Full test suite run

- [ ] **Run all tests**

```bash
python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: all tests pass. Note the count — it should be 273 (existing) + new tests added in this sprint.

- [ ] **Check TypeScript types compile**

```bash
cd /Users/pboagents/Documents/agentpool1/ui && npx tsc --noEmit 2>&1
```

Expected: no errors.
