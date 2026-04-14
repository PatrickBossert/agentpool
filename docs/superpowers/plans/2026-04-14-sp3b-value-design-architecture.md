# SP3b: Value Design + Architecture Crews Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Crew 2 (Value Design) and Crew 3 (Architecture) to the AgentPool — four agents that synthesise Discovery outputs into prioritised value propositions, score them into a portfolio register, extract the current-state architecture, and identify capability-gap initiatives.

**Architecture:** All four agents follow the SP3a pattern exactly: sync `BaseTool` subclasses, `HumanInputTool` SQLite polling for HITL, `crew.kickoff_async()` via `asyncio.create_task`. Each crew is triggered by `POST /projects/{slug}/run {"crew": "value_design"|"architecture"}`. Value Proposition Generator reads Discovery outputs directly from `projects/{slug}/outputs/*.json` via `SQLiteStateTool`. Portfolio Manager is the only agent to write an XLSX artefact, via the new `ExcelOutputTool`. The Value Design crew uses per-agent LLM assignment (Opus for VPG, Haiku for PM); the Architecture crew uses Sonnet for both agents.

**Tech Stack:** Python 3.14, CrewAI ≥1.14, openpyxl (new), SQLite (sync via sqlite3), ChromaDB 0.6.3, FastAPI, pytest + pytest-asyncio

---

## File Map

**Create:**
- `agents/value_design/__init__.py`
- `agents/value_design/value_proposition_generator.py`
- `agents/value_design/portfolio_manager.py`
- `agents/architecture/__init__.py`
- `agents/architecture/enterprise_architect.py`
- `agents/architecture/initiative_identifier.py`
- `agents/crews/value_design_crew.py`
- `agents/crews/architecture_crew.py`
- `agents/tools/excel_output.py`
- `tests/test_excel_output.py`
- `tests/test_value_design_crew.py`
- `tests/test_architecture_crew.py`
- `tests/integration/test_value_design_crew.py`
- `tests/integration/test_architecture_crew.py`

**Modify:**
- `requirements.txt` — add `openpyxl`
- `agents/llm.py` — add `get_haiku_llm()`
- `agents/tools/registry.py` — add `ExcelOutputTool` entries for new agents
- `api/services/run_service.py` — add `value_design` and `architecture` crew dispatch
- `tests/integration/conftest.py` — add seed fixtures for Discovery and Value Design outputs

---

## Task 1: Branch Setup and Dependencies

**Files:**
- Modify: `requirements.txt`
- Modify: `agents/llm.py`

- [ ] **Step 1: Create the SP3b worktree from the SP3a branch**

```bash
git worktree add .worktrees/sp3b-value-design-architecture -b feature/sp3b-value-design-architecture feature/sp3a-discovery-crew
cd .worktrees/sp3b-value-design-architecture
source .venv/bin/activate
```

All subsequent steps in this plan run from `.worktrees/sp3b-value-design-architecture/`.

- [ ] **Step 2: Add openpyxl to requirements.txt**

Open `requirements.txt`. After the `tavily-python==0.7.23` line, add:

```
openpyxl==3.1.5
```

- [ ] **Step 3: Install the new dependency**

```bash
pip install openpyxl==3.1.5
```

Expected: `Successfully installed openpyxl-3.1.5`

- [ ] **Step 4: Add get_haiku_llm() to agents/llm.py**

Open `agents/llm.py`. After the `get_test_llm()` function, add:

```python
def get_haiku_llm() -> LLM:
    """For agents spec'd to use claude-haiku-4-5 in production (e.g. Portfolio Manager)."""
    settings = get_settings()
    return LLM(
        model="anthropic/claude-haiku-4-5-20251001",
        api_key=settings.anthropic_api_key,
    )
```

- [ ] **Step 5: Verify existing tests still pass**

```bash
.venv/bin/pytest tests/ -q --ignore=tests/integration
```

Expected: All existing tests pass (same count as before branching).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt agents/llm.py
git commit -m "feat(sp3b): add openpyxl dependency and get_haiku_llm helper"
```

---

## Task 2: ExcelOutputTool (TDD)

**Files:**
- Create: `tests/test_excel_output.py`
- Create: `agents/tools/excel_output.py`
- Modify: `agents/tools/registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_excel_output.py`:

```python
# tests/test_excel_output.py
import json
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture(autouse=True)
def isolated_projects_dir(tmp_path, monkeypatch):
    """Redirect PROJECTS_DIR to a temp directory for each test."""
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def slug(isolated_projects_dir):
    slug = "excel-test-project"
    project_dir = isolated_projects_dir / slug
    outputs_dir = project_dir / "outputs"
    outputs_dir.mkdir(parents=True)
    # ExcelOutputTool needs a project row in SQLite — patch insert_agent_output_sync
    return slug


def test_excel_output_tool_writes_file(slug, isolated_projects_dir):
    """ExcelOutputTool writes an xlsx file with correct headers and rows."""
    from agents.tools.excel_output import ExcelOutputTool
    import openpyxl

    with patch("agents.tools.excel_output.insert_agent_output_sync"):
        tool = ExcelOutputTool(slug=slug)
        rows = [
            {"rank": 1, "title": "Alpha", "score": 90.0},
            {"rank": 2, "title": "Beta", "score": 75.0},
        ]
        result = tool._run(
            rows=rows,
            columns=["rank", "title", "score"],
            filename="portfolio_register.xlsx",
            agent_name="portfolio_manager",
        )

    file_path = Path(result)
    assert file_path.exists(), "XLSX file was not created"
    assert file_path.suffix == ".xlsx"

    wb = openpyxl.load_workbook(file_path)
    ws = wb.active

    # Headers in row 1
    headers = [ws.cell(row=1, column=i).value for i in range(1, 4)]
    assert headers == ["rank", "title", "score"]

    # Data rows
    assert ws.cell(row=2, column=1).value == 1
    assert ws.cell(row=2, column=2).value == "Alpha"
    assert ws.cell(row=3, column=2).value == "Beta"


def test_excel_output_tool_returns_absolute_path(slug):
    """Return value is the absolute path to the written file."""
    from agents.tools.excel_output import ExcelOutputTool

    with patch("agents.tools.excel_output.insert_agent_output_sync"):
        tool = ExcelOutputTool(slug=slug)
        result = tool._run(
            rows=[{"col": "val"}],
            columns=["col"],
            filename="test.xlsx",
            agent_name="test_agent",
        )

    assert Path(result).is_absolute()
    assert result.endswith(".xlsx")


def test_excel_output_tool_appends_xlsx_extension(slug):
    """filename without .xlsx extension gets it added automatically."""
    from agents.tools.excel_output import ExcelOutputTool

    with patch("agents.tools.excel_output.insert_agent_output_sync"):
        tool = ExcelOutputTool(slug=slug)
        result = tool._run(
            rows=[{"x": 1}],
            columns=["x"],
            filename="no_extension",
            agent_name="test_agent",
        )

    assert result.endswith(".xlsx")
    assert Path(result).exists()


def test_excel_output_tool_header_is_bold(slug):
    """Header row cells have bold font."""
    from agents.tools.excel_output import ExcelOutputTool
    import openpyxl

    with patch("agents.tools.excel_output.insert_agent_output_sync"):
        tool = ExcelOutputTool(slug=slug)
        result = tool._run(
            rows=[{"name": "X"}],
            columns=["name"],
            filename="bold_test.xlsx",
            agent_name="test_agent",
        )

    wb = openpyxl.load_workbook(result)
    ws = wb.active
    assert ws.cell(row=1, column=1).font.bold is True


def test_excel_output_tool_freeze_panes(slug):
    """Freeze panes set to A2 (header row frozen)."""
    from agents.tools.excel_output import ExcelOutputTool
    import openpyxl

    with patch("agents.tools.excel_output.insert_agent_output_sync"):
        tool = ExcelOutputTool(slug=slug)
        result = tool._run(
            rows=[{"a": 1}],
            columns=["a"],
            filename="freeze_test.xlsx",
            agent_name="test_agent",
        )

    wb = openpyxl.load_workbook(result)
    ws = wb.active
    assert ws.freeze_panes == "A2"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/bin/pytest tests/test_excel_output.py -v
```

Expected: `ImportError: cannot import name 'ExcelOutputTool'` (module does not exist yet).

- [ ] **Step 3: Create agents/tools/excel_output.py**

```python
# agents/tools/excel_output.py
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import insert_agent_output_sync


class ExcelOutputToolInput(BaseModel):
    rows: list[dict[str, Any]] = Field(
        description="List of dicts representing rows. All dicts must share the same keys."
    )
    columns: list[str] = Field(
        description="Ordered list of column names to include in the output."
    )
    filename: str = Field(
        description="Output filename (e.g. 'portfolio_register.xlsx'). "
        ".xlsx extension added automatically if missing."
    )
    agent_name: str = Field(
        description="Name of the agent producing this output (used for output tracking)."
    )


class ExcelOutputTool(BaseTool):
    name: str = "ExcelOutputTool"
    description: str = (
        "Write a list of records to an Excel (.xlsx) file in the project outputs directory. "
        "Pass rows as a list of dicts with uniform keys, an ordered column list, and a filename. "
        "Returns the absolute file path to the saved file."
    )
    args_schema: type[BaseModel] = ExcelOutputToolInput
    slug: str

    def _run(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        filename: str,
        agent_name: str,
    ) -> str:
        try:
            import openpyxl
            from openpyxl.styles import Font
        except ImportError:
            return "Error: openpyxl not installed — run: pip install openpyxl"

        settings = get_settings()
        outputs_dir = Path(settings.projects_dir) / self.slug / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        if not filename.endswith(".xlsx"):
            filename = f"{filename}.xlsx"
        file_path = outputs_dir / filename

        try:
            wb = openpyxl.Workbook()
            ws = wb.active

            # Header row — bold
            for col_idx, col_name in enumerate(columns, start=1):
                cell = ws.cell(row=1, column=col_idx, value=col_name)
                cell.font = Font(bold=True)

            # Data rows
            for row_idx, row in enumerate(rows, start=2):
                for col_idx, col_name in enumerate(columns, start=1):
                    ws.cell(row=row_idx, column=col_idx, value=row.get(col_name, ""))

            # Auto-width columns (capped at 60 to avoid absurdly wide columns)
            for col in ws.columns:
                max_len = max((len(str(cell.value or "")) for cell in col), default=0)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

            # Freeze header row
            ws.freeze_panes = "A2"

            wb.save(file_path)
            insert_agent_output_sync(
                slug=self.slug,
                agent_name=agent_name,
                output_type="excel",
                file_path=str(file_path),
            )
        except (OSError, ValueError) as e:
            return f"Error: write failed — {e}"

        return str(file_path)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/test_excel_output.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Register ExcelOutputTool in agents/tools/registry.py**

In `agents/tools/registry.py`, add the import at the top of `get_tools_for_agent()` alongside the existing imports:

```python
from agents.tools.excel_output import ExcelOutputTool
```

Then add these entries to `tool_map` inside `get_tools_for_agent()`:

```python
        "value_proposition_generator": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
        "portfolio_manager": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
            ExcelOutputTool(slug=slug),
        ],
        "enterprise_architect": [
            ChromaQueryTool(slug=slug, sector=sector),
            MermaidRenderTool(slug=slug),
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
        "initiative_identifier": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
```

- [ ] **Step 6: Run all unit tests to confirm nothing is broken**

```bash
.venv/bin/pytest tests/ -q --ignore=tests/integration
```

Expected: All existing tests still pass, 5 new excel tests pass.

- [ ] **Step 7: Commit**

```bash
git add agents/tools/excel_output.py agents/tools/registry.py tests/test_excel_output.py
git commit -m "feat(sp3b): add ExcelOutputTool and register new agent tool sets"
```

---

## Task 3: Value Proposition Generator Agent

**Files:**
- Create: `agents/value_design/__init__.py`
- Create: `agents/value_design/value_proposition_generator.py`

- [ ] **Step 1: Create the value_design package**

```bash
touch agents/value_design/__init__.py
```

`agents/value_design/__init__.py` should be an empty file.

- [ ] **Step 2: Create agents/value_design/value_proposition_generator.py**

```python
# agents/value_design/value_proposition_generator.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_value_proposition_generator(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Value Proposition Generator",
        goal=(
            "Synthesise the Discovery crew outputs into a clear, evidence-backed set of value "
            "propositions that articulate the business case for digital modernisation."
        ),
        backstory=(
            "You are a senior strategy consultant who specialises in translating analytical "
            "findings into compelling value propositions. You connect the dots between "
            "pain points, capability gaps, and quantifiable business outcomes to build "
            "a prioritised case for change."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


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
            "5. Identify 3–7 distinct value propositions by grouping related requirements, "
            "levers, pain points, and journey opportunities. Each proposition should represent "
            "a coherent area of change with a clear business outcome.\n"
            "6. Produce a JSON array where each item follows this schema exactly:\n"
            "   {\n"
            "     \"id\": \"VP-001\",\n"
            "     \"title\": \"Short label (max 6 words)\",\n"
            "     \"change_articulation\": \"2–3 sentences describing what changes and why it matters\",\n"
            "     \"impacted_stakeholder_groups\": [\"...\"],\n"
            "     \"value_estimate\": \"High|Medium|Low\",\n"
            "     \"value_estimate_rationale\": \"1–2 sentences justifying the estimate\",\n"
            "     \"supporting_evidence\": [\n"
            "       {\"type\": \"requirement|lever|pain_point|journey\", \"ref\": \"...\", \"summary\": \"...\"}\n"
            "     ]\n"
            "   }\n"
            "   IDs must be sequential: VP-001, VP-002, etc.\n"
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
            "each with id, title, change_articulation, impacted_stakeholder_groups, "
            "value_estimate, value_estimate_rationale, and supporting_evidence. "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
    )
```

- [ ] **Step 3: Write unit tests for the Value Proposition Generator**

Create `tests/test_value_design_crew.py`:

```python
# tests/test_value_design_crew.py
"""Unit tests for Value Design crew agents and crew assembly."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


# ── Value Proposition Generator ───────────────────────────────────────────────

def test_vpg_agent_role(mock_llm):
    from agents.value_design.value_proposition_generator import create_value_proposition_generator
    agent = create_value_proposition_generator(slug="test", llm=mock_llm, tools=[])
    assert agent.role == "Value Proposition Generator"


def test_vpg_task_reads_discovery_outputs(mock_llm):
    """Task description instructs the agent to read all four Discovery output keys."""
    from agents.value_design.value_proposition_generator import (
        create_value_proposition_generator,
        create_value_proposition_generator_task,
    )
    agent = create_value_proposition_generator(slug="test", llm=mock_llm, tools=[])
    task = create_value_proposition_generator_task(agent=agent)
    desc = task.description
    assert "key='requirements'" in desc
    assert "key='value_levers'" in desc
    assert "key='value_chain_summary'" in desc
    assert "key='user_journeys'" in desc


def test_vpg_task_writes_propositions(mock_llm):
    from agents.value_design.value_proposition_generator import (
        create_value_proposition_generator,
        create_value_proposition_generator_task,
    )
    agent = create_value_proposition_generator(slug="test", llm=mock_llm, tools=[])
    task = create_value_proposition_generator_task(agent=agent)
    assert "key='propositions'" in task.description
    assert "operation='write'" in task.description


def test_vpg_task_has_hitl(mock_llm):
    from agents.value_design.value_proposition_generator import (
        create_value_proposition_generator,
        create_value_proposition_generator_task,
    )
    agent = create_value_proposition_generator(slug="test", llm=mock_llm, tools=[])
    task = create_value_proposition_generator_task(agent=agent)
    assert "HumanInputTool" in task.description
    assert "approved" in task.description
```

- [ ] **Step 4: Run the unit tests**

```bash
.venv/bin/pytest tests/test_value_design_crew.py::test_vpg_agent_role tests/test_value_design_crew.py::test_vpg_task_reads_discovery_outputs tests/test_value_design_crew.py::test_vpg_task_writes_propositions tests/test_value_design_crew.py::test_vpg_task_has_hitl -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/value_design/__init__.py agents/value_design/value_proposition_generator.py tests/test_value_design_crew.py
git commit -m "feat(sp3b): add Value Proposition Generator agent"
```

---

## Task 4: Portfolio Manager Agent

**Files:**
- Create: `agents/value_design/portfolio_manager.py`

- [ ] **Step 1: Create agents/value_design/portfolio_manager.py**

```python
# agents/value_design/portfolio_manager.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_portfolio_manager(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Portfolio Manager",
        goal=(
            "Score and rank the approved value propositions into a prioritised portfolio "
            "using human-defined weighting criteria."
        ),
        backstory=(
            "You are a portfolio management specialist who helps organisations make "
            "evidence-based investment decisions. You apply structured scoring frameworks "
            "to rank initiatives objectively, then present the results in a clear register "
            "that senior stakeholders can act on."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_portfolio_manager_task(agent: Agent, context_tasks: list[Task]) -> Task:
    return Task(
        description=(
            "Score and rank the value propositions into a prioritised portfolio register.\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='propositions', "
            "agent_name='portfolio_manager' to retrieve the approved value propositions.\n"
            "2. Use HumanInputTool with prompt: 'Please provide ranking weights for portfolio "
            "scoring as a JSON object. Weights are integers 1–10. Example: "
            "{\"value\": 5, \"feasibility\": 3, \"strategic_fit\": 2}. "
            "These will be normalised to sum to 100%.'\n"
            "3. Parse the human's JSON response to extract value, feasibility, and "
            "strategic_fit weights. If the response cannot be parsed as JSON, use default "
            "weights: {\"value\": 5, \"feasibility\": 3, \"strategic_fit\": 2}.\n"
            "4. Normalise weights so they sum to 1.0: "
            "w_value = value / total, w_feasibility = feasibility / total, "
            "w_strategic_fit = strategic_fit / total.\n"
            "5. Score each proposition on a 0–10 scale for each dimension "
            "(value impact, feasibility of delivery, strategic fit to company direction). "
            "Justify each score with one sentence.\n"
            "6. Compute total_score = (score_value * w_value + score_feasibility * w_feasibility "
            "+ score_strategic_fit * w_strategic_fit) * 10, rounded to 1 decimal place.\n"
            "7. Rank propositions by total_score descending (rank 1 = highest). "
            "Break ties alphabetically by title.\n"
            "8. Build a JSON array where each item follows this schema exactly:\n"
            "   {\n"
            "     \"rank\": 1,\n"
            "     \"id\": \"VP-001\",\n"
            "     \"title\": \"...\",\n"
            "     \"change_articulation\": \"...\",\n"
            "     \"impacted_stakeholder_groups\": [...],\n"
            "     \"value_estimate\": \"High|Medium|Low\",\n"
            "     \"score_value\": 8.5,\n"
            "     \"score_feasibility\": 6.0,\n"
            "     \"score_strategic_fit\": 9.0,\n"
            "     \"score_value_rationale\": \"...\",\n"
            "     \"score_feasibility_rationale\": \"...\",\n"
            "     \"score_strategic_fit_rationale\": \"...\",\n"
            "     \"total_score\": 82.5,\n"
            "     \"weights_used\": {\"value\": 5, \"feasibility\": 3, \"strategic_fit\": 2}\n"
            "   }\n"
            "9. Use SQLiteStateTool with operation='write', key='portfolio_register', "
            "agent_name='portfolio_manager' to save the JSON array.\n"
            "10. Use ExcelOutputTool with:\n"
            "    - rows: the portfolio register list\n"
            "    - columns: [\"rank\", \"id\", \"title\", \"value_estimate\", \"score_value\", "
            "\"score_feasibility\", \"score_strategic_fit\", \"total_score\"]\n"
            "    - filename: 'portfolio_register.xlsx'\n"
            "    - agent_name: 'portfolio_manager'\n"
            "11. Use HumanInputTool with prompt: 'Portfolio register scored and saved to "
            "outputs/portfolio_register.xlsx. Please review the rankings. "
            "Reply \"approved\" to proceed, or provide notes.'\n"
            "12. If revision notes are received, revise scores or ranking and repeat "
            "steps 9–11. Maximum 3 revision cycles.\n"
        ),
        expected_output=(
            "A JSON portfolio register saved to outputs/portfolio_register.json "
            "and an Excel file at outputs/portfolio_register.xlsx, "
            "each containing all value propositions ranked by weighted score. "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
        context=context_tasks,
    )
```

- [ ] **Step 2: Add Portfolio Manager unit tests to tests/test_value_design_crew.py**

Append to the end of `tests/test_value_design_crew.py`:

```python
# ── Portfolio Manager ─────────────────────────────────────────────────────────

def test_pm_agent_role(mock_llm):
    from agents.value_design.portfolio_manager import create_portfolio_manager
    agent = create_portfolio_manager(slug="test", llm=mock_llm, tools=[])
    assert agent.role == "Portfolio Manager"


def test_pm_task_reads_propositions(mock_llm):
    from agents.value_design.portfolio_manager import (
        create_portfolio_manager,
        create_portfolio_manager_task,
    )
    agent = create_portfolio_manager(slug="test", llm=mock_llm, tools=[])
    task = create_portfolio_manager_task(agent=agent, context_tasks=[])
    assert "key='propositions'" in task.description
    assert "operation='read'" in task.description


def test_pm_task_requests_weights_via_hitl(mock_llm):
    from agents.value_design.portfolio_manager import (
        create_portfolio_manager,
        create_portfolio_manager_task,
    )
    agent = create_portfolio_manager(slug="test", llm=mock_llm, tools=[])
    task = create_portfolio_manager_task(agent=agent, context_tasks=[])
    assert "HumanInputTool" in task.description
    assert "weights" in task.description.lower()


def test_pm_task_uses_excel_output_tool(mock_llm):
    from agents.value_design.portfolio_manager import (
        create_portfolio_manager,
        create_portfolio_manager_task,
    )
    agent = create_portfolio_manager(slug="test", llm=mock_llm, tools=[])
    task = create_portfolio_manager_task(agent=agent, context_tasks=[])
    assert "ExcelOutputTool" in task.description
    assert "portfolio_register.xlsx" in task.description


def test_pm_task_writes_portfolio_register(mock_llm):
    from agents.value_design.portfolio_manager import (
        create_portfolio_manager,
        create_portfolio_manager_task,
    )
    agent = create_portfolio_manager(slug="test", llm=mock_llm, tools=[])
    task = create_portfolio_manager_task(agent=agent, context_tasks=[])
    assert "key='portfolio_register'" in task.description
    assert "operation='write'" in task.description
```

- [ ] **Step 3: Run the Portfolio Manager unit tests**

```bash
.venv/bin/pytest tests/test_value_design_crew.py -v
```

Expected: All 9 tests PASS (4 VPG + 5 PM).

- [ ] **Step 4: Commit**

```bash
git add agents/value_design/portfolio_manager.py tests/test_value_design_crew.py
git commit -m "feat(sp3b): add Portfolio Manager agent"
```

---

## Task 5: Value Design Crew Assembly and API Wiring

**Files:**
- Create: `agents/crews/value_design_crew.py`
- Modify: `api/services/run_service.py`
- Modify: `tests/test_value_design_crew.py` (append crew wiring tests)
- Modify: `tests/test_run_api.py` (append new crew API tests)

- [ ] **Step 1: Create agents/crews/value_design_crew.py**

```python
# agents/crews/value_design_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_crew_llm, get_pam_llm, get_haiku_llm
from agents.tools.registry import get_tools_for_agent
from agents.value_design.value_proposition_generator import (
    create_value_proposition_generator,
    create_value_proposition_generator_task,
)
from agents.value_design.portfolio_manager import (
    create_portfolio_manager,
    create_portfolio_manager_task,
)


def create_value_design_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
) -> Crew:
    """
    Assemble and return the Value Design Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
        sector: Client sector (unused by Value Design but kept for interface consistency).
        llm: Optional LLM override (used in tests to inject a cheap model for all agents).
    """
    if llm is not None:
        # Test override: use the same cheap model for all agents
        vpg_llm = pm_llm = llm
    elif llm_mode == "sensitive":
        # Sensitive mode: all agents use local LLM
        _local = get_crew_llm("sensitive")
        vpg_llm = pm_llm = _local
    else:
        # Production: per-spec model assignment
        vpg_llm = get_pam_llm()    # Claude Opus 4.6
        pm_llm = get_haiku_llm()   # Claude Haiku 4.5

    vpg = create_value_proposition_generator(
        slug=slug,
        llm=vpg_llm,
        tools=get_tools_for_agent("value_proposition_generator", slug=slug, run_id=run_id, sector=sector),
    )
    pm = create_portfolio_manager(
        slug=slug,
        llm=pm_llm,
        tools=get_tools_for_agent("portfolio_manager", slug=slug, run_id=run_id, sector=sector),
    )

    vpg_task = create_value_proposition_generator_task(agent=vpg)
    pm_task = create_portfolio_manager_task(agent=pm, context_tasks=[vpg_task])

    return Crew(
        agents=[vpg, pm],
        tasks=[vpg_task, pm_task],
        process=Process.sequential,
        verbose=True,
    )
```

- [ ] **Step 2: Add crew wiring tests to tests/test_value_design_crew.py**

Append to `tests/test_value_design_crew.py`:

```python
# ── Crew wiring ───────────────────────────────────────────────────────────────

def test_value_design_crew_has_two_agents(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.value_design_crew import create_value_design_crew
        crew = create_value_design_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    assert len(crew.agents) == 2


def test_value_design_crew_agent_roles(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.value_design_crew import create_value_design_crew
        crew = create_value_design_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    roles = {a.role for a in crew.agents}
    assert "Value Proposition Generator" in roles
    assert "Portfolio Manager" in roles


def test_value_design_crew_sequential_process(mock_llm):
    from crewai import Process
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.value_design_crew import create_value_design_crew
        crew = create_value_design_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    assert crew.process == Process.sequential


def test_value_design_crew_sensitive_mode_uses_local_llm(mock_llm):
    """In sensitive mode, a single local LLM is used (not the test override)."""
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]), \
         patch("agents.crews.value_design_crew.get_crew_llm") as mock_local:
        mock_local.return_value = mock_llm
        from agents.crews.value_design_crew import create_value_design_crew
        crew = create_value_design_crew(
            slug="test", run_id=1, llm_mode="sensitive", sector="logistics"
        )
    mock_local.assert_called_once_with("sensitive")
```

- [ ] **Step 3: Run the crew wiring tests**

```bash
.venv/bin/pytest tests/test_value_design_crew.py -v
```

Expected: All 13 tests PASS.

- [ ] **Step 4: Update api/services/run_service.py to dispatch the Value Design crew**

In `run_service.py`, add the `value_design` branch to `dispatch_crew()` and add the `_run_value_design_crew()` helper. The existing `dispatch_crew` looks like:

```python
if crew_name == "discovery":
    await _run_discovery_crew(slug=slug, run_id=run_id)
else:
    raise ValueError(f"Unknown crew: '{crew_name}'")
```

Replace that block with:

```python
if crew_name == "discovery":
    await _run_discovery_crew(slug=slug, run_id=run_id)
elif crew_name == "value_design":
    await _run_value_design_crew(slug=slug, run_id=run_id)
else:
    raise ValueError(f"Unknown crew: '{crew_name}'")
```

Then add the new helper function at the bottom of `run_service.py`:

```python
async def _run_value_design_crew(slug: str, run_id: int) -> None:
    """Build and run the Value Design Crew asynchronously."""
    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    llm_mode = config.get("llm_mode", "standard")
    sector = config.get("sector", "")

    from agents.crews.value_design_crew import create_value_design_crew
    crew = create_value_design_crew(
        slug=slug,
        run_id=run_id,
        llm_mode=llm_mode,
        sector=sector,
    )
    await crew.kickoff_async()
```

- [ ] **Step 5: Add Value Design run API tests to tests/test_run_api.py**

Append to `tests/test_run_api.py`:

```python
@pytest.mark.asyncio
async def test_run_value_design_crew_queues_run(client):
    payload = {**PROJECT_PAYLOAD, "client_slug": "vd-test", "crews_enabled": ["value_design"]}
    await client.post("/projects", json=payload)
    with patch("api.services.run_service.dispatch_crew", new_callable=AsyncMock):
        resp = await client.post("/projects/vd-test/run", json={"crew": "value_design"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["crew"] == "value_design"
    assert data["status"] == "running"
```

- [ ] **Step 6: Run all unit tests**

```bash
.venv/bin/pytest tests/ -q --ignore=tests/integration
```

Expected: All tests pass (new value_design tests included).

- [ ] **Step 7: Commit**

```bash
git add agents/crews/value_design_crew.py api/services/run_service.py tests/test_value_design_crew.py tests/test_run_api.py
git commit -m "feat(sp3b): add Value Design crew and API wiring"
```

---

## Task 6: Enterprise Architect Agent

**Files:**
- Create: `agents/architecture/__init__.py`
- Create: `agents/architecture/enterprise_architect.py`

- [ ] **Step 1: Create the architecture package**

```bash
touch agents/architecture/__init__.py
```

`agents/architecture/__init__.py` should be an empty file.

- [ ] **Step 2: Create agents/architecture/enterprise_architect.py**

```python
# agents/architecture/enterprise_architect.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_enterprise_architect(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Enterprise Architect",
        goal=(
            "Extract and structure the client's current-state enterprise architecture "
            "across data, technology, and organisation layers from uploaded documents."
        ),
        backstory=(
            "You are a principal enterprise architect who specialises in current-state "
            "assessment. You read architecture documents, org charts, system inventories, "
            "and technology registers to produce clear, structured architecture registers "
            "that reveal capability gaps and modernisation opportunities."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_enterprise_architect_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Extract the current-state enterprise architecture from uploaded client documents.\n\n"
            "Steps:\n"
            "1. Use ChromaQueryTool with collection='project', "
            "query='systems platforms technology infrastructure organisation teams roles' "
            "to retrieve architecture-related document chunks. Retrieve at least top_k=10.\n"
            "2. Use ChromaQueryTool with collection='project', "
            "query='data entities sources flows ownership master data' "
            "to retrieve data-layer content.\n"
            "3. Use ChromaQueryTool with collection='project', "
            "query='organisational structure teams capabilities reporting lines' "
            "to retrieve organisation-layer content.\n"
            "4. Extract the three architecture layers. For each layer, produce a list of "
            "named entities. If a layer has no identifiable entities from the documents, "
            "produce a list with a single placeholder: "
            "{\"name\": \"Unknown\", \"description\": \"No information found in uploaded documents.\"}.\n\n"
            "   Data layer — each entity:\n"
            "   {\"name\": \"...\", \"description\": \"...\", \"source\": \"...\", \"owner\": \"...\"}\n\n"
            "   Technology layer — each entity:\n"
            "   {\"name\": \"...\", \"description\": \"...\", "
            "\"category\": \"platform|integration|infrastructure|application\", "
            "\"status\": \"current|planned|legacy\"}\n\n"
            "   Organisation layer — each entity:\n"
            "   {\"name\": \"...\", \"type\": \"team|role|capability\", \"description\": \"...\"}\n\n"
            "5. Assemble the three layers into a single JSON object:\n"
            "   {\"data_layer\": [...], \"technology_layer\": [...], \"organisation_layer\": [...]}\n"
            "6. Use SQLiteStateTool with operation='write', key='architecture_register', "
            "agent_name='enterprise_architect' to save the JSON object.\n"
            "7. Use MermaidRenderTool to save a Mermaid diagram for each layer:\n"
            "   - Data layer: flowchart LR diagram showing entities and their relationships. "
            "filename='architecture_data_layer', agent_name='enterprise_architect'.\n"
            "   - Technology layer: flowchart TB diagram grouping systems by category. "
            "filename='architecture_technology_layer', agent_name='enterprise_architect'.\n"
            "   - Organisation layer: graph TB diagram showing hierarchy. "
            "filename='architecture_org_layer', agent_name='enterprise_architect'.\n"
            "8. Use HumanInputTool with prompt: 'Please review the architecture register saved at "
            "outputs/architecture_register.json and the three Mermaid diagrams "
            "(architecture_data_layer.md, architecture_technology_layer.md, architecture_org_layer.md). "
            "Reply \"approved\" to proceed to initiative identification, or provide notes.'\n"
            "9. If revision notes are received, revise the register and diagrams and call "
            "HumanInputTool again. Maximum 3 revision cycles.\n"
        ),
        expected_output=(
            "A JSON architecture register with data_layer, technology_layer, and organisation_layer "
            "saved to outputs/architecture_register.json. "
            "Three Mermaid diagrams saved to outputs/architecture_data_layer.md, "
            "outputs/architecture_technology_layer.md, and outputs/architecture_org_layer.md. "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
    )
```

- [ ] **Step 3: Create tests/test_architecture_crew.py with Enterprise Architect tests**

Create `tests/test_architecture_crew.py`:

```python
# tests/test_architecture_crew.py
"""Unit tests for Architecture crew agents and crew assembly."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


# ── Enterprise Architect ──────────────────────────────────────────────────────

def test_ea_agent_role(mock_llm):
    from agents.architecture.enterprise_architect import create_enterprise_architect
    agent = create_enterprise_architect(slug="test", llm=mock_llm, tools=[])
    assert agent.role == "Enterprise Architect"


def test_ea_task_queries_chroma(mock_llm):
    from agents.architecture.enterprise_architect import (
        create_enterprise_architect,
        create_enterprise_architect_task,
    )
    agent = create_enterprise_architect(slug="test", llm=mock_llm, tools=[])
    task = create_enterprise_architect_task(agent=agent)
    assert "ChromaQueryTool" in task.description
    assert "collection='project'" in task.description


def test_ea_task_writes_architecture_register(mock_llm):
    from agents.architecture.enterprise_architect import (
        create_enterprise_architect,
        create_enterprise_architect_task,
    )
    agent = create_enterprise_architect(slug="test", llm=mock_llm, tools=[])
    task = create_enterprise_architect_task(agent=agent)
    assert "key='architecture_register'" in task.description
    assert "operation='write'" in task.description


def test_ea_task_renders_three_mermaid_diagrams(mock_llm):
    from agents.architecture.enterprise_architect import (
        create_enterprise_architect,
        create_enterprise_architect_task,
    )
    agent = create_enterprise_architect(slug="test", llm=mock_llm, tools=[])
    task = create_enterprise_architect_task(agent=agent)
    assert "architecture_data_layer" in task.description
    assert "architecture_technology_layer" in task.description
    assert "architecture_org_layer" in task.description


def test_ea_task_has_hitl(mock_llm):
    from agents.architecture.enterprise_architect import (
        create_enterprise_architect,
        create_enterprise_architect_task,
    )
    agent = create_enterprise_architect(slug="test", llm=mock_llm, tools=[])
    task = create_enterprise_architect_task(agent=agent)
    assert "HumanInputTool" in task.description
    assert "approved" in task.description
```

- [ ] **Step 4: Run Enterprise Architect unit tests**

```bash
.venv/bin/pytest tests/test_architecture_crew.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/architecture/__init__.py agents/architecture/enterprise_architect.py tests/test_architecture_crew.py
git commit -m "feat(sp3b): add Enterprise Architect agent"
```

---

## Task 7: Initiative Identifier Agent

**Files:**
- Create: `agents/architecture/initiative_identifier.py`

- [ ] **Step 1: Create agents/architecture/initiative_identifier.py**

```python
# agents/architecture/initiative_identifier.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_initiative_identifier(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Initiative Identifier",
        goal=(
            "Identify the discrete initiatives required to deliver the approved value propositions "
            "by performing gap analysis between the propositions and the current-state architecture."
        ),
        backstory=(
            "You are a transformation programme architect who specialises in translating "
            "strategic intent into actionable initiatives. You analyse where value propositions "
            "demand capabilities the current architecture does not provide, and define the "
            "initiatives needed to close those gaps."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


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
            "7. Categorise each initiative:\n"
            "   - 'enabling': primarily technology or data infrastructure change\n"
            "   - 'operating_model': changes to processes, roles, or organisational structure\n"
            "   - 'business_change': strategic or customer-facing change requiring significant "
            "stakeholder engagement\n"
            "8. Produce a JSON array where each item follows this schema exactly:\n"
            "   {\n"
            "     \"id\": \"INIT-001\",\n"
            "     \"title\": \"Short initiative title (max 8 words)\",\n"
            "     \"description\": \"2–3 sentences describing what this initiative delivers\",\n"
            "     \"proposition_ids\": [\"VP-001\", \"VP-002\"],\n"
            "     \"capability_gaps\": [\"Gap description 1\", \"Gap description 2\"],\n"
            "     \"category\": \"enabling|operating_model|business_change\",\n"
            "     \"complexity_score\": 3,\n"
            "     \"complexity_rationale\": \"One sentence justifying the score\",\n"
            "     \"related_requirements\": [\"REQ-001\"]\n"
            "   }\n"
            "   IDs must be sequential: INIT-001, INIT-002, etc.\n"
            "9. Use SQLiteStateTool with operation='write', key='initiative_register', "
            "agent_name='initiative_identifier' to save the JSON array.\n"
            "10. Use HumanInputTool with prompt: 'Please review the initiative register saved at "
            "outputs/initiative_register.json. Reply \"approved\" to conclude the Architecture "
            "phase, or provide notes.'\n"
            "11. If revision notes are received, revise and call HumanInputTool again. "
            "Maximum 3 revision cycles.\n"
        ),
        expected_output=(
            "A JSON initiative register saved to outputs/initiative_register.json "
            "containing at least 1 initiative per approved value proposition, "
            "each with id, title, description, proposition_ids, capability_gaps, "
            "category, complexity_score, complexity_rationale, and related_requirements. "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
        context=context_tasks,
    )
```

- [ ] **Step 2: Add Initiative Identifier unit tests to tests/test_architecture_crew.py**

Append to `tests/test_architecture_crew.py`:

```python
# ── Initiative Identifier ─────────────────────────────────────────────────────

def test_ii_agent_role(mock_llm):
    from agents.architecture.initiative_identifier import create_initiative_identifier
    agent = create_initiative_identifier(slug="test", llm=mock_llm, tools=[])
    assert agent.role == "Initiative Identifier"


def test_ii_task_reads_three_inputs(mock_llm):
    from agents.architecture.initiative_identifier import (
        create_initiative_identifier,
        create_initiative_identifier_task,
    )
    agent = create_initiative_identifier(slug="test", llm=mock_llm, tools=[])
    task = create_initiative_identifier_task(agent=agent, context_tasks=[])
    assert "key='propositions'" in task.description
    assert "key='architecture_register'" in task.description
    assert "key='requirements'" in task.description


def test_ii_task_writes_initiative_register(mock_llm):
    from agents.architecture.initiative_identifier import (
        create_initiative_identifier,
        create_initiative_identifier_task,
    )
    agent = create_initiative_identifier(slug="test", llm=mock_llm, tools=[])
    task = create_initiative_identifier_task(agent=agent, context_tasks=[])
    assert "key='initiative_register'" in task.description
    assert "operation='write'" in task.description


def test_ii_task_has_hitl(mock_llm):
    from agents.architecture.initiative_identifier import (
        create_initiative_identifier,
        create_initiative_identifier_task,
    )
    agent = create_initiative_identifier(slug="test", llm=mock_llm, tools=[])
    task = create_initiative_identifier_task(agent=agent, context_tasks=[])
    assert "HumanInputTool" in task.description
    assert "approved" in task.description


def test_ii_task_covers_all_categories(mock_llm):
    from agents.architecture.initiative_identifier import (
        create_initiative_identifier,
        create_initiative_identifier_task,
    )
    agent = create_initiative_identifier(slug="test", llm=mock_llm, tools=[])
    task = create_initiative_identifier_task(agent=agent, context_tasks=[])
    assert "enabling" in task.description
    assert "operating_model" in task.description
    assert "business_change" in task.description
```

- [ ] **Step 3: Run all architecture unit tests**

```bash
.venv/bin/pytest tests/test_architecture_crew.py -v
```

Expected: All 10 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add agents/architecture/initiative_identifier.py tests/test_architecture_crew.py
git commit -m "feat(sp3b): add Initiative Identifier agent"
```

---

## Task 8: Architecture Crew Assembly and API Wiring

**Files:**
- Create: `agents/crews/architecture_crew.py`
- Modify: `api/services/run_service.py`
- Modify: `tests/test_architecture_crew.py` (append crew wiring tests)
- Modify: `tests/test_run_api.py` (append architecture crew API test)

- [ ] **Step 1: Create agents/crews/architecture_crew.py**

```python
# agents/crews/architecture_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_crew_llm
from agents.tools.registry import get_tools_for_agent
from agents.architecture.enterprise_architect import (
    create_enterprise_architect,
    create_enterprise_architect_task,
)
from agents.architecture.initiative_identifier import (
    create_initiative_identifier,
    create_initiative_identifier_task,
)


def create_architecture_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
) -> Crew:
    """
    Assemble and return the Architecture Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
        sector: Client sector (used by ChromaQueryTool for sector knowledge base).
        llm: Optional LLM override (used in tests to inject a cheap model).
    """
    if llm is None:
        llm = get_crew_llm(llm_mode)  # Sonnet 4.6 (standard) or local (sensitive)

    ea = create_enterprise_architect(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("enterprise_architect", slug=slug, run_id=run_id, sector=sector),
    )
    ii = create_initiative_identifier(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("initiative_identifier", slug=slug, run_id=run_id, sector=sector),
    )

    ea_task = create_enterprise_architect_task(agent=ea)
    ii_task = create_initiative_identifier_task(agent=ii, context_tasks=[ea_task])

    return Crew(
        agents=[ea, ii],
        tasks=[ea_task, ii_task],
        process=Process.sequential,
        verbose=True,
    )
```

- [ ] **Step 2: Append crew wiring tests to tests/test_architecture_crew.py**

Append to `tests/test_architecture_crew.py`:

```python
# ── Crew wiring ───────────────────────────────────────────────────────────────

def test_architecture_crew_has_two_agents(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.architecture_crew import create_architecture_crew
        crew = create_architecture_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    assert len(crew.agents) == 2


def test_architecture_crew_agent_roles(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.architecture_crew import create_architecture_crew
        crew = create_architecture_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    roles = {a.role for a in crew.agents}
    assert "Enterprise Architect" in roles
    assert "Initiative Identifier" in roles


def test_architecture_crew_sequential_process(mock_llm):
    from crewai import Process
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.architecture_crew import create_architecture_crew
        crew = create_architecture_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    assert crew.process == Process.sequential
```

- [ ] **Step 3: Add architecture run API test to tests/test_run_api.py**

Append to `tests/test_run_api.py`:

```python
@pytest.mark.asyncio
async def test_run_architecture_crew_queues_run(client):
    payload = {**PROJECT_PAYLOAD, "client_slug": "arch-test", "crews_enabled": ["architecture"]}
    await client.post("/projects", json=payload)
    with patch("api.services.run_service.dispatch_crew", new_callable=AsyncMock):
        resp = await client.post("/projects/arch-test/run", json={"crew": "architecture"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["crew"] == "architecture"
    assert data["status"] == "running"
```

- [ ] **Step 4: Update api/services/run_service.py to dispatch the Architecture crew**

In `run_service.py`, the `dispatch_crew()` function currently ends with:

```python
elif crew_name == "value_design":
    await _run_value_design_crew(slug=slug, run_id=run_id)
else:
    raise ValueError(f"Unknown crew: '{crew_name}'")
```

Replace that block with:

```python
elif crew_name == "value_design":
    await _run_value_design_crew(slug=slug, run_id=run_id)
elif crew_name == "architecture":
    await _run_architecture_crew(slug=slug, run_id=run_id)
else:
    raise ValueError(f"Unknown crew: '{crew_name}'")
```

Then add the new helper function at the bottom of `run_service.py`:

```python
async def _run_architecture_crew(slug: str, run_id: int) -> None:
    """Build and run the Architecture Crew asynchronously."""
    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    llm_mode = config.get("llm_mode", "standard")
    sector = config.get("sector", "")

    from agents.crews.architecture_crew import create_architecture_crew
    crew = create_architecture_crew(
        slug=slug,
        run_id=run_id,
        llm_mode=llm_mode,
        sector=sector,
    )
    await crew.kickoff_async()
```

- [ ] **Step 5: Run all unit tests**

```bash
.venv/bin/pytest tests/ -q --ignore=tests/integration
```

Expected: All tests pass (new architecture crew and run API tests included).

- [ ] **Step 6: Commit**

```bash
git add agents/crews/architecture_crew.py api/services/run_service.py tests/test_architecture_crew.py tests/test_run_api.py
git commit -m "feat(sp3b): add Architecture crew and API wiring"
```

---

## Task 9: Integration Test Fixtures

**Files:**
- Modify: `tests/integration/conftest.py`

The integration conftest already creates a test project and seeds ChromaDB with a logistics fixture document. This task adds two additional session-scoped fixtures that seed the Discovery and Value Design outputs needed by the SP3b integration tests.

- [ ] **Step 1: Add seed_discovery_outputs fixture to tests/integration/conftest.py**

Open `tests/integration/conftest.py`. After the `project_id` fixture at the bottom of the file, append:

```python
@pytest.fixture(scope="session")
def seed_discovery_outputs(test_slug, setup_test_project):
    """
    Write mock Discovery crew outputs to the test project's outputs directory.
    Required by Value Design integration tests (VPG reads these via SQLiteStateTool).
    """
    from api.config import get_settings
    import json
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / test_slug / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    requirements = [
        {
            "id": "REQ-001",
            "description": "Automate manual order entry process end-to-end",
            "stakeholder_group": "Operations",
            "priority": "high",
            "source": "stakeholder_interview",
        },
        {
            "id": "REQ-002",
            "description": "Integrate warehouse management system with ERP",
            "stakeholder_group": "IT",
            "priority": "high",
            "source": "document_analysis",
        },
        {
            "id": "REQ-003",
            "description": "Implement real-time supply chain visibility dashboard",
            "stakeholder_group": "Operations",
            "priority": "medium",
            "source": "stakeholder_interview",
        },
    ]
    (outputs_dir / "requirements.json").write_text(json.dumps(requirements))

    value_levers = [
        {
            "lever": "Process Automation",
            "description": "Automate high-volume manual processes across order management",
            "value_impact": "high",
            "effort": "medium",
            "related_requirements": ["REQ-001"],
            "evidence": "Industry benchmarks show 60–80% reduction in processing time",
        },
        {
            "lever": "Systems Integration",
            "description": "Connect disparate WMS, ERP and CRM platforms",
            "value_impact": "high",
            "effort": "high",
            "related_requirements": ["REQ-002"],
            "evidence": "Eliminates manual data re-entry across 3 systems",
        },
        {
            "lever": "Real-time Visibility",
            "description": "End-to-end tracking and reporting across the supply chain",
            "value_impact": "medium",
            "effort": "medium",
            "related_requirements": ["REQ-003"],
            "evidence": "Reduces exception resolution time by ~50%",
        },
    ]
    (outputs_dir / "value_levers.json").write_text(json.dumps(value_levers))

    value_chain_summary = {
        "activities": [
            "Inbound Logistics",
            "Warehouse Operations",
            "Outbound Logistics",
            "Customer Service",
        ],
        "sector": "logistics",
    }
    (outputs_dir / "value_chain_summary.json").write_text(json.dumps(value_chain_summary))

    yield  # no teardown needed — project dir is cleaned up by setup_test_project


@pytest.fixture(scope="session")
def seed_value_design_outputs(test_slug, seed_discovery_outputs):
    """
    Write mock Value Design crew outputs to the test project's outputs directory.
    Required by Architecture integration tests (Initiative Identifier reads propositions).
    """
    from api.config import get_settings
    import json
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / test_slug / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    propositions = [
        {
            "id": "VP-001",
            "title": "Automated Order Management",
            "change_articulation": (
                "Replace manual order entry with an end-to-end automated order management platform. "
                "Eliminates data re-entry errors and reduces processing time from 4 hours to 15 minutes."
            ),
            "impacted_stakeholder_groups": ["Operations", "Finance"],
            "value_estimate": "High",
            "value_estimate_rationale": "Addresses the highest-priority requirement with clear ROI benchmark evidence.",
            "supporting_evidence": [
                {"type": "requirement", "ref": "REQ-001", "summary": "Automate manual order entry"},
                {"type": "lever", "ref": "lever_0", "summary": "Process Automation"},
            ],
        },
        {
            "id": "VP-002",
            "title": "Integrated Supply Chain Platform",
            "change_articulation": (
                "Connect WMS, ERP, and CRM into a unified integration layer. "
                "Provides a single source of truth for inventory, orders and customer data."
            ),
            "impacted_stakeholder_groups": ["IT", "Operations"],
            "value_estimate": "High",
            "value_estimate_rationale": "Resolves the root cause of data inconsistency across three systems.",
            "supporting_evidence": [
                {"type": "requirement", "ref": "REQ-002", "summary": "Integrate WMS with ERP"},
                {"type": "lever", "ref": "lever_1", "summary": "Systems Integration"},
            ],
        },
    ]
    (outputs_dir / "propositions.json").write_text(json.dumps(propositions))

    yield  # no teardown needed
```

- [ ] **Step 2: Verify the conftest parses without errors**

```bash
.venv/bin/python -c "import tests.integration.conftest; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tests/integration/conftest.py
git commit -m "test(sp3b): add seed_discovery_outputs and seed_value_design_outputs fixtures"
```

---

## Task 10: Integration Tests — Value Design Crew

**Files:**
- Create: `tests/integration/test_value_design_crew.py`

- [ ] **Step 1: Create tests/integration/test_value_design_crew.py**

```python
# tests/integration/test_value_design_crew.py
"""
End-to-end integration test for the Value Design Crew.

Requires:
- ANTHROPIC_API_KEY in .env
- Discovery outputs seeded by seed_discovery_outputs fixture

Run with: pytest -m integration -v
Takes 3–8 minutes.
"""
import contextlib
import json
import sqlite3
import pytest
from pathlib import Path
from api.config import get_settings


@pytest.mark.integration
def test_value_design_crew_end_to_end(test_slug, project_id, seed_discovery_outputs):
    """
    Run the full Value Design Crew and verify all outputs are produced.
    Uses claude-haiku for both agents (test LLM override).
    HITL pauses are auto-responded via HITL_AUTO_RESPOND='approved' set in conftest.
    """
    from agents.llm import get_test_llm
    from agents.crews.value_design_crew import create_value_design_crew

    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{test_slug}.db"

    # Create a crew_run record
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status, started_at)"
        " VALUES (?,?,?, CURRENT_TIMESTAMP)",
        (project_id, "value_design", "running"),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()

    # Build crew with cheap test LLM (both agents use Haiku in tests)
    llm = get_test_llm()
    crew = create_value_design_crew(
        slug=test_slug,
        run_id=run_id,
        llm_mode="standard",
        sector="logistics",
        llm=llm,
    )

    result = crew.kickoff()
    assert result is not None

    # Mark run completed (in production, run_service does this)
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "UPDATE crew_runs SET status='completed', finished_at=CURRENT_TIMESTAMP WHERE id=?",
            (run_id,),
        )
        conn.commit()

    outputs_dir = Path(settings.projects_dir) / test_slug / "outputs"

    # 1. propositions.json exists and is a valid JSON array
    propositions_path = outputs_dir / "propositions.json"
    assert propositions_path.exists(), "propositions.json not created"
    propositions = json.loads(propositions_path.read_text())
    assert isinstance(propositions, list), "propositions.json is not a JSON array"
    assert len(propositions) >= 1, "propositions.json contains no propositions"
    first = propositions[0]
    assert "id" in first, "Proposition missing 'id' field"
    assert "title" in first, "Proposition missing 'title' field"
    assert "change_articulation" in first, "Proposition missing 'change_articulation' field"
    assert "value_estimate" in first, "Proposition missing 'value_estimate' field"
    assert first["value_estimate"] in ("High", "Medium", "Low"), \
        f"Invalid value_estimate: {first['value_estimate']}"

    # 2. portfolio_register.json exists and is a valid JSON array
    portfolio_path = outputs_dir / "portfolio_register.json"
    assert portfolio_path.exists(), "portfolio_register.json not created"
    portfolio = json.loads(portfolio_path.read_text())
    assert isinstance(portfolio, list), "portfolio_register.json is not a JSON array"
    assert len(portfolio) >= 1, "portfolio_register.json contains no entries"
    first_item = portfolio[0]
    assert "rank" in first_item, "Portfolio entry missing 'rank' field"
    assert "total_score" in first_item, "Portfolio entry missing 'total_score' field"
    assert first_item["rank"] == 1, "First portfolio entry should have rank 1"

    # 3. portfolio_register.xlsx exists
    xlsx_path = outputs_dir / "portfolio_register.xlsx"
    assert xlsx_path.exists(), "portfolio_register.xlsx not created"

    # 4. XLSX has correct structure
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    headers = [ws.cell(row=1, column=i).value for i in range(1, ws.max_column + 1)]
    assert "rank" in headers, "portfolio_register.xlsx missing 'rank' column"
    assert "title" in headers, "portfolio_register.xlsx missing 'title' column"

    # 5. HITL records created
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM human_reviews WHERE crew_run_id=?", (run_id,)
        )
        hitl_count = cur.fetchone()[0]
    assert hitl_count >= 1, "No HITL reviews created during Value Design crew run"

    # 6. agent_outputs records created
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "SELECT DISTINCT agent_name FROM agent_outputs WHERE project_id=?",
            (project_id,),
        )
        agent_names = {row[0] for row in cur.fetchall()}
    assert "portfolio_manager" in agent_names, "Portfolio Manager produced no tracked output"
```

- [ ] **Step 2: Run the Value Design integration test**

```bash
.venv/bin/pytest tests/integration/test_value_design_crew.py -v -s
```

Expected: `PASSED` — takes 3–8 minutes. If it fails, read the full output carefully:
- `propositions.json not created` → VPG failed to write output; check HITL_AUTO_RESPOND is set (it's set in integration/conftest.py) and that the seed fixture wrote `requirements.json`, `value_levers.json`, `value_chain_summary.json`.
- `portfolio_register.xlsx not created` → PM failed; check `ExcelOutputTool` is in the PM's tool list in `registry.py`.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_value_design_crew.py
git commit -m "test(sp3b): add Value Design crew integration test"
```

---

## Task 11: Integration Tests — Architecture Crew and Final Run

**Files:**
- Create: `tests/integration/test_architecture_crew.py`

- [ ] **Step 1: Create tests/integration/test_architecture_crew.py**

```python
# tests/integration/test_architecture_crew.py
"""
End-to-end integration test for the Architecture Crew.

Requires:
- ANTHROPIC_API_KEY in .env
- ChromaDB with the project test collection (seeded by setup_test_project)
- Value Design outputs seeded by seed_value_design_outputs fixture (for Initiative Identifier)

Run with: pytest -m integration -v
Takes 3–8 minutes.
"""
import contextlib
import json
import sqlite3
import pytest
from pathlib import Path
from api.config import get_settings


@pytest.mark.integration
def test_architecture_crew_end_to_end(test_slug, project_id, seed_value_design_outputs):
    """
    Run the full Architecture Crew and verify all outputs are produced.
    seed_value_design_outputs also pulls in seed_discovery_outputs (via fixture dependency).
    Uses claude-haiku for both agents (test LLM override).
    HITL pauses are auto-responded via HITL_AUTO_RESPOND='approved' set in conftest.
    """
    from agents.llm import get_test_llm
    from agents.crews.architecture_crew import create_architecture_crew

    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{test_slug}.db"

    # Create a crew_run record
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status, started_at)"
        " VALUES (?,?,?, CURRENT_TIMESTAMP)",
        (project_id, "architecture", "running"),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()

    llm = get_test_llm()
    crew = create_architecture_crew(
        slug=test_slug,
        run_id=run_id,
        llm_mode="standard",
        sector="logistics",
        llm=llm,
    )

    result = crew.kickoff()
    assert result is not None

    # Mark run completed
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "UPDATE crew_runs SET status='completed', finished_at=CURRENT_TIMESTAMP WHERE id=?",
            (run_id,),
        )
        conn.commit()

    outputs_dir = Path(settings.projects_dir) / test_slug / "outputs"

    # 1. architecture_register.json exists and has all three layers
    arch_path = outputs_dir / "architecture_register.json"
    assert arch_path.exists(), "architecture_register.json not created"
    arch = json.loads(arch_path.read_text())
    assert "data_layer" in arch, "architecture_register.json missing 'data_layer'"
    assert "technology_layer" in arch, "architecture_register.json missing 'technology_layer'"
    assert "organisation_layer" in arch, "architecture_register.json missing 'organisation_layer'"
    assert isinstance(arch["technology_layer"], list), "technology_layer is not a list"
    assert len(arch["technology_layer"]) >= 1, "technology_layer contains no entities"

    # 2. Three Mermaid diagrams exist
    for diagram_name in [
        "architecture_data_layer.md",
        "architecture_technology_layer.md",
        "architecture_org_layer.md",
    ]:
        path = outputs_dir / diagram_name
        assert path.exists(), f"{diagram_name} not created"
        content = path.read_text()
        assert "graph" in content.lower() or "flowchart" in content.lower(), \
            f"{diagram_name} does not contain Mermaid syntax"

    # 3. initiative_register.json exists and has valid structure
    init_path = outputs_dir / "initiative_register.json"
    assert init_path.exists(), "initiative_register.json not created"
    initiatives = json.loads(init_path.read_text())
    assert isinstance(initiatives, list), "initiative_register.json is not a JSON array"
    assert len(initiatives) >= 1, "initiative_register.json contains no initiatives"
    first = initiatives[0]
    assert "id" in first, "Initiative missing 'id' field"
    assert "title" in first, "Initiative missing 'title' field"
    assert "category" in first, "Initiative missing 'category' field"
    assert first["category"] in ("enabling", "operating_model", "business_change"), \
        f"Invalid initiative category: {first['category']}"
    assert "complexity_score" in first, "Initiative missing 'complexity_score' field"
    assert 1 <= first["complexity_score"] <= 5, \
        f"complexity_score out of range: {first['complexity_score']}"

    # 4. HITL records created for both agents
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM human_reviews WHERE crew_run_id=?", (run_id,)
        )
        hitl_count = cur.fetchone()[0]
    assert hitl_count >= 2, \
        f"Expected at least 2 HITL reviews (one per agent), got {hitl_count}"

    # 5. agent_outputs records for both agents
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "SELECT DISTINCT agent_name FROM agent_outputs WHERE project_id=?",
            (project_id,),
        )
        agent_names = {row[0] for row in cur.fetchall()}
    assert "enterprise_architect" in agent_names, \
        "Enterprise Architect produced no tracked output"
    assert "initiative_identifier" in agent_names, \
        "Initiative Identifier produced no tracked output"
```

- [ ] **Step 2: Run the Architecture integration test**

```bash
.venv/bin/pytest tests/integration/test_architecture_crew.py -v -s
```

Expected: `PASSED` — takes 3–8 minutes. If Initiative Identifier fails because it can't read `propositions.json`, confirm that `seed_value_design_outputs` is listed as a fixture parameter in the test function (it seeds `propositions.json`).

- [ ] **Step 3: Run the full test suite (all unit + all integration)**

```bash
.venv/bin/pytest tests/ -q --ignore=tests/integration && .venv/bin/pytest -m integration -v
```

Expected: All unit tests pass. All integration tests pass (Value Design + Architecture + SP3a Discovery + SP3a tools).

- [ ] **Step 4: Final commit**

```bash
git add tests/integration/test_architecture_crew.py
git commit -m "test(sp3b): add Architecture crew integration test"
```

- [ ] **Step 5: Push branch**

```bash
git push -u origin feature/sp3b-value-design-architecture
```

---

## Summary

**What SP3b delivers:**

| File | Purpose |
|---|---|
| `agents/tools/excel_output.py` | New ExcelOutputTool — writes formatted XLSX |
| `agents/value_design/value_proposition_generator.py` | Synthesises Discovery outputs → value propositions |
| `agents/value_design/portfolio_manager.py` | HITL-driven weighted scoring → portfolio register |
| `agents/architecture/enterprise_architect.py` | ChromaDB extraction → architecture register + Mermaid |
| `agents/architecture/initiative_identifier.py` | Gap analysis → initiative register |
| `agents/crews/value_design_crew.py` | Value Design Crew (Opus VPG + Haiku PM) |
| `agents/crews/architecture_crew.py` | Architecture Crew (Sonnet EA + Sonnet II) |
| `api/services/run_service.py` | Dispatch for `value_design` and `architecture` crew names |

**Test counts added:** ~33 unit tests (5 excel + 13 value design + 13 architecture + 2 run API) + 2 integration tests (in addition to SP3a's 40 unit + 6 integration).

**Next sprint:** SP3c — Crew 4 Delivery Planning (Roadmap Generator + Business Plan Generator).
