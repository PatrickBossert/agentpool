# SP3c: Delivery Planning Crew Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Crew 4 (Delivery Planning — Roadmap Generator only) to AgentPool, producing a time-phased HTML roadmap that shows value propositions by stakeholder group, capability builds, and named benefits per value stream.

**Architecture:** One new agent (Roadmap Generator, Sonnet 4.6), one new tool (HtmlRoadmapTool — pure Python HTML string generation), one new crew (delivery_crew.py). The crew signature differs from prior crews: it accepts `value_stream_labels`, `stakeholder_groups`, and `roadmap_time_axis` from config, which are embedded into the task description string at assembly time. HITL via SQLite polling, identical to SP3a/SP3b.

**Tech Stack:** Python 3.14, CrewAI ≥1.14, FastAPI, SQLite (sync via sqlite3), pytest + pytest-asyncio. No new Python packages required.

---

## File Map

**Create:**
- `agents/delivery/__init__.py` — empty package marker
- `agents/delivery/roadmap_generator.py` — agent factory + task factory (with config params embedded in task description)
- `agents/crews/delivery_crew.py` — crew assembler; passes value_stream_labels, stakeholder_groups, roadmap_time_axis to task factory
- `agents/tools/html_roadmap.py` — HtmlRoadmapTool; renders roadmap_data dict to self-contained HTML file
- `tests/test_delivery_crew.py` — 12 unit tests for agent + crew wiring
- `tests/test_html_roadmap.py` — 8 unit tests for HtmlRoadmapTool
- `tests/integration/test_delivery_crew.py` — end-to-end integration test

**Modify:**
- `agents/tools/registry.py` — add `roadmap_generator` entry (SQLiteStateTool + HumanInputTool + HtmlRoadmapTool)
- `api/services/run_service.py` — add `"delivery"` branch + `_run_delivery_crew()` helper (reads 3 extra config fields)
- `tests/test_run_api.py` — append `test_run_delivery_crew_queues_run`
- `tests/integration/conftest.py` — append `seed_architecture_outputs` fixture

---

## Task 1: Branch Setup

**Files:** worktree + branch only

- [ ] **Step 1: Create the worktree and branch**

```bash
git worktree add .worktrees/sp3c-delivery-planning -b feature/sp3c-delivery-planning
cd .worktrees/sp3c-delivery-planning
```

- [ ] **Step 2: Verify baseline tests pass**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/ -q --ignore=tests/integration
```

Expected: 75 passed (or similar — all green).

- [ ] **Step 3: Confirm .env is present**

```bash
ls .env
```

If missing: `cp ../sp3a-discovery-crew/.env .env` (or copy from master worktree root).

---

## Task 2: HtmlRoadmapTool (TDD)

**Files:**
- Create: `agents/tools/html_roadmap.py`
- Create: `tests/test_html_roadmap.py`

- [ ] **Step 1: Create `tests/test_html_roadmap.py`**

```python
# tests/test_html_roadmap.py
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
    slug = "html-roadmap-test"
    project_dir = isolated_projects_dir / slug
    outputs_dir = project_dir / "outputs"
    outputs_dir.mkdir(parents=True)
    return slug


@pytest.fixture
def sample_roadmap_data():
    return {
        "time_axis": "quarters",
        "periods": ["Q1 2026", "Q2 2026", "Q3 2026"],
        "value_streams": ["Operations", "IT"],
        "stakeholder_groups": ["Investor", "Customer", "Operations"],
        "initiatives": [
            {
                "id": "INIT-001",
                "title": "Automate Order Entry",
                "category": "enabling",
                "complexity_score": 2,
                "period": "Q1 2026",
                "value_streams": ["Operations"],
                "proposition_ids": ["VP-001"],
            },
            {
                "id": "INIT-002",
                "title": "Integrate WMS",
                "category": "operating_model",
                "complexity_score": 3,
                "period": "Q2 2026",
                "value_streams": ["IT"],
                "proposition_ids": ["VP-002"],
            },
        ],
        "propositions": [
            {
                "id": "VP-001",
                "title": "Automated Order Management",
                "value_estimate": "High",
                "change_articulation": "Replace manual order entry.",
                "realisation_period": "Q2 2026",
                "value_streams": ["Operations"],
                "impacted_stakeholder_groups": ["Investor", "Customer", "Operations"],
                "value_levers": ["Process Automation", "OpEx Reduction"],
            },
        ],
    }


def test_html_roadmap_writes_file(slug, sample_roadmap_data):
    """HtmlRoadmapTool creates an .html file at the expected path."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    assert Path(result).exists()


def test_html_roadmap_returns_absolute_path(slug, sample_roadmap_data):
    """Return value is an absolute path ending in .html."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    assert Path(result).is_absolute()
    assert result.endswith(".html")


def test_html_roadmap_contains_value_streams(slug, sample_roadmap_data):
    """HTML contains value stream labels as section headers."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    content = Path(result).read_text()
    assert "Operations" in content
    assert "IT" in content


def test_html_roadmap_contains_period_headers(slug, sample_roadmap_data):
    """HTML contains all period names as column headers."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    content = Path(result).read_text()
    assert "Q1 2026" in content
    assert "Q2 2026" in content
    assert "Q3 2026" in content


def test_html_roadmap_contains_stakeholder_rows(slug, sample_roadmap_data):
    """HTML contains stakeholder group names as row labels."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    content = Path(result).read_text()
    assert "Investor" in content
    assert "Customer" in content


def test_html_roadmap_contains_initiative_titles(slug, sample_roadmap_data):
    """HTML contains initiative titles in the Capability Builds rows."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    content = Path(result).read_text()
    assert "Automate Order Entry" in content
    assert "Integrate WMS" in content


def test_html_roadmap_contains_value_levers(slug, sample_roadmap_data):
    """HTML contains value lever names in the Benefits rows."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    content = Path(result).read_text()
    assert "Process Automation" in content
    assert "OpEx Reduction" in content


def test_html_roadmap_appends_html_extension(slug, sample_roadmap_data):
    """filename without .html extension gets it added automatically."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap_no_ext",
            agent_name="roadmap_generator",
        )
    assert result.endswith(".html")
    assert Path(result).exists()


def test_html_roadmap_error_on_write_failure(slug, sample_roadmap_data):
    """Returns error string when the file cannot be saved."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"), \
         patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="fail.html",
            agent_name="roadmap_generator",
        )
    assert result.startswith("Error: render failed")
```

- [ ] **Step 2: Run tests — verify they all FAIL with ImportError**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_html_roadmap.py -v 2>&1 | head -20
```

Expected: 8 errors — `ModuleNotFoundError: No module named 'agents.tools.html_roadmap'`

- [ ] **Step 3: Create `agents/tools/html_roadmap.py`**

```python
# agents/tools/html_roadmap.py
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import insert_agent_output_sync

_CATEGORY_COLOURS: dict[str, str] = {
    "enabling": "#3b82f6",
    "operating_model": "#f59e0b",
    "business_change": "#22c55e",
}

_HTML_HEADER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Delivery Roadmap</title>
<style>
  body { font-family: Arial, sans-serif; margin: 24px; color: #1f2937; }
  h1 { font-size: 1.5rem; margin-bottom: 24px; }
  .value-stream { margin-bottom: 40px; }
  .vs-header { font-size: 1.1rem; font-weight: 700; background: #1e3a5f; color: white;
               padding: 8px 12px; margin: 0; border-radius: 4px 4px 0 0; }
  table.roadmap-grid { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #d1d5db; padding: 6px 8px; vertical-align: top;
           min-width: 120px; }
  th.row-label, td.row-label { font-weight: 600; background: #f9fafb; min-width: 140px;
                                white-space: nowrap; font-size: 0.85rem; }
  th.period-header { background: #f3f4f6; font-weight: 700; text-align: center;
                     font-size: 0.85rem; }
  .vp-chip { display: inline-block; background: #eff6ff; border: 1px solid #bfdbfe;
             border-radius: 4px; padding: 2px 6px; font-size: 0.78rem; margin: 2px; }
  .init-chip { display: inline-block; color: white; border-radius: 4px;
               padding: 3px 7px; font-size: 0.78rem; margin: 2px; }
  .complexity-badge { background: rgba(0,0,0,0.25); border-radius: 3px;
                      padding: 0 3px; font-size: 0.72rem; }
  .capability-label { background: #f0fdf4; color: #166534; }
  .benefits-label { background: #fefce8; color: #713f12; }
  .benefit-block { margin-bottom: 4px; }
  .lever-names { font-size: 0.78rem; display: block; color: #374151; }
  .estimate-badge { display: inline-block; border-radius: 4px; padding: 1px 6px;
                    font-size: 0.75rem; font-weight: 700; margin-top: 2px; }
  .badge-high { background: #dcfce7; color: #166534; }
  .badge-medium { background: #fef9c3; color: #713f12; }
  .badge-low { background: #fee2e2; color: #991b1b; }
</style>
</head>
<body>
<h1>Delivery Roadmap</h1>
"""

_HTML_FOOTER = "</body></html>"


class HtmlRoadmapToolInput(BaseModel):
    roadmap_data: dict[str, Any] = Field(
        description=(
            "Roadmap JSON object with keys: periods (list), value_streams (list), "
            "stakeholder_groups (list), initiatives (list), propositions (list)."
        )
    )
    filename: str = Field(
        default="roadmap.html",
        description="Output filename. .html extension added automatically if missing.",
    )
    agent_name: str = Field(
        description="Name of the agent producing this output (used for output tracking)."
    )


class HtmlRoadmapTool(BaseTool):
    name: str = "HtmlRoadmapTool"
    description: str = (
        "Render a roadmap_data JSON object as a self-contained HTML roadmap file "
        "in the project outputs directory. Returns the absolute file path to the saved file."
    )
    args_schema: type[BaseModel] = HtmlRoadmapToolInput
    slug: str

    def _run(
        self,
        roadmap_data: dict[str, Any],
        filename: str = "roadmap.html",
        agent_name: str = "",
    ) -> str:
        settings = get_settings()
        outputs_dir = Path(settings.projects_dir) / self.slug / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        if not filename.endswith(".html"):
            filename = f"{filename}.html"
        file_path = outputs_dir / filename

        try:
            html = self._render_html(roadmap_data)
            file_path.write_text(html, encoding="utf-8")
            insert_agent_output_sync(
                slug=self.slug,
                agent_name=agent_name,
                output_type="html",
                file_path=str(file_path),
            )
        except (OSError, ValueError, KeyError) as e:
            return f"Error: render failed — {e}"

        return str(file_path)

    def _render_html(self, roadmap_data: dict[str, Any]) -> str:
        periods: list[str] = roadmap_data["periods"]
        value_streams: list[str] = roadmap_data["value_streams"]
        stakeholder_groups: list[str] = roadmap_data.get("stakeholder_groups", [])
        initiatives: list[dict] = roadmap_data.get("initiatives", [])
        propositions: list[dict] = roadmap_data.get("propositions", [])

        parts: list[str] = [_HTML_HEADER]

        for vs in value_streams:
            vs_initiatives = [i for i in initiatives if vs in i.get("value_streams", [])]
            vs_propositions = [p for p in propositions if vs in p.get("value_streams", [])]

            parts.append(f'<div class="value-stream">')
            parts.append(f'<h2 class="vs-header">{vs}</h2>')
            parts.append('<table class="roadmap-grid"><thead><tr>')
            parts.append('<th class="row-label"></th>')
            for period in periods:
                parts.append(f'<th class="period-header">{period}</th>')
            parts.append('</tr></thead><tbody>')

            # One row per stakeholder group — shows VP titles for matching group + period
            for sg in stakeholder_groups:
                parts.append(f'<tr><td class="row-label">{sg}</td>')
                for period in periods:
                    cell_vps = [
                        p for p in vs_propositions
                        if sg in p.get("impacted_stakeholder_groups", [])
                        and p.get("realisation_period") == period
                    ]
                    cells = "".join(
                        f'<span class="vp-chip">{p["title"]}</span>'
                        for p in cell_vps
                    )
                    parts.append(f'<td class="vp-cell">{cells}</td>')
                parts.append("</tr>")

            # Capability Builds row — initiatives coloured by category
            parts.append('<tr><td class="row-label capability-label">Capability Builds</td>')
            for period in periods:
                cell_inits = [i for i in vs_initiatives if i.get("period") == period]
                cells = "".join(
                    '<span class="init-chip" style="background:{colour}">'
                    "{title} "
                    '<span class="complexity-badge">{score}</span>'
                    "</span>".format(
                        colour=_CATEGORY_COLOURS.get(i.get("category", ""), "#9ca3af"),
                        title=i["title"],
                        score=i.get("complexity_score", ""),
                    )
                    for i in cell_inits
                )
                parts.append(f'<td class="init-cell">{cells}</td>')
            parts.append("</tr>")

            # Benefits row — value lever names + estimate badge per VP realisation period
            parts.append('<tr><td class="row-label benefits-label">Benefits</td>')
            for period in periods:
                period_vps = [p for p in vs_propositions if p.get("realisation_period") == period]
                cells = ""
                for p in period_vps:
                    levers = " · ".join(p.get("value_levers", []))
                    estimate = p.get("value_estimate", "")
                    cells += (
                        '<div class="benefit-block">'
                        f'<span class="lever-names">{levers}</span>'
                        f'<span class="estimate-badge badge-{estimate.lower()}">{estimate}</span>'
                        "</div>"
                    )
                parts.append(f'<td class="benefits-cell">{cells}</td>')
            parts.append("</tr>")

            parts.append("</tbody></table></div>")

        parts.append(_HTML_FOOTER)
        return "".join(parts)
```

- [ ] **Step 4: Run tests — verify all pass**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_html_roadmap.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add agents/tools/html_roadmap.py tests/test_html_roadmap.py
git commit -m "feat(sp3c): add HtmlRoadmapTool"
```

---

## Task 3: Roadmap Generator Agent

**Files:**
- Create: `agents/delivery/__init__.py`
- Create: `agents/delivery/roadmap_generator.py`
- Create: `tests/test_delivery_crew.py` (agent tests only — crew wiring tests added in Task 4)

- [ ] **Step 1: Create empty package marker**

Create `agents/delivery/__init__.py` as an empty file.

- [ ] **Step 2: Create `agents/delivery/roadmap_generator.py`**

```python
# agents/delivery/roadmap_generator.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_roadmap_generator(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Roadmap Generator",
        goal=(
            "Sequence approved initiatives into a time-phased delivery roadmap that tells "
            "the complete story of what changes, for whom, through what capability builds, "
            "and what benefits are realised."
        ),
        backstory=(
            "You are a delivery strategy specialist who transforms initiative registers "
            "into actionable roadmaps. You sequence work intelligently — enabling "
            "infrastructure first, then operational change, then business transformation — "
            "and map each initiative to the stakeholder groups and value streams it serves."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_roadmap_generator_task(
    agent: Agent,
    value_stream_labels: list[str],
    stakeholder_groups: list[str],
    roadmap_time_axis: str,
) -> Task:
    streams_str = ", ".join(value_stream_labels)
    groups_str = ", ".join(stakeholder_groups)
    return Task(
        description=(
            "Build a time-phased delivery roadmap from the initiative register.\n\n"
            f"Project configuration:\n"
            f"- Value streams: {streams_str}\n"
            f"- Stakeholder groups: {groups_str}\n"
            f"- Time axis: {roadmap_time_axis}\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='initiative_register', "
            "agent_name='roadmap_generator' to retrieve the initiative register.\n"
            "2. Use SQLiteStateTool with operation='read', key='propositions', "
            "agent_name='roadmap_generator' to retrieve the value propositions.\n"
            "3. Use SQLiteStateTool with operation='read', key='value_levers', "
            "agent_name='roadmap_generator' to retrieve the value lever register.\n"
            "4. Sequence initiatives into named time periods:\n"
            "   - Order: enabling initiatives first (lower complexity_score first within "
            "category), then operating_model, then business_change.\n"
            "   - Name periods from the configured time axis:\n"
            f"     * 'quarters' \u2192 'Q1 2026', 'Q2 2026', 'Q3 2026', etc.\n"
            f"     * 'years' \u2192 'Year 1', 'Year 2', 'Year 3', etc.\n"
            f"     * 'horizons' \u2192 'Horizon 1', 'Horizon 2', 'Horizon 3', etc.\n"
            "   - Generate as many periods as needed; minimum 3.\n"
            "   - Distribute initiatives across periods — avoid placing all in one period.\n"
            "5. For each initiative, assign:\n"
            "   - 'period': the sequenced time period name.\n"
            f"   - 'value_streams': which of [{streams_str}] this initiative supports "
            "(based on its proposition_ids and category).\n"
            "6. For each value proposition, assign:\n"
            "   - 'realisation_period': the period when benefits are realised — the period "
            "when its last supporting initiative completes, or the period immediately after.\n"
            f"   - 'value_streams': which of [{streams_str}] this proposition belongs to.\n"
            f"   - 'impacted_stakeholder_groups': carry forward from propositions register "
            f"(choose from: {groups_str}).\n"
            "   - 'value_levers': trace each proposition's supporting_evidence for items "
            "with type='lever', then look up the 'lever' field (e.g. 'Process Automation') "
            "in the value lever register. Return a list of lever name strings.\n"
            "7. Assemble the complete roadmap JSON object with this exact structure:\n"
            "   {\n"
            f'     "time_axis": "{roadmap_time_axis}",\n'
            '     "periods": ["Q1 2026", ...],\n'
            f'     "value_streams": {value_stream_labels},\n'
            f'     "stakeholder_groups": {stakeholder_groups},\n'
            '     "initiatives": [\n'
            '       {\n'
            '         "id": "INIT-001",\n'
            '         "title": "...",\n'
            '         "category": "enabling|operating_model|business_change",\n'
            '         "complexity_score": 2,\n'
            '         "period": "Q1 2026",\n'
            '         "value_streams": ["..."],\n'
            '         "proposition_ids": ["VP-001"]\n'
            '       }\n'
            '     ],\n'
            '     "propositions": [\n'
            '       {\n'
            '         "id": "VP-001",\n'
            '         "title": "...",\n'
            '         "value_estimate": "High|Medium|Low",\n'
            '         "change_articulation": "...",\n'
            '         "realisation_period": "Q2 2026",\n'
            '         "value_streams": ["..."],\n'
            '         "impacted_stakeholder_groups": ["..."],\n'
            '         "value_levers": ["Process Automation", "..."]\n'
            '       }\n'
            '     ]\n'
            '   }\n'
            "8. Use SQLiteStateTool with operation='write', key='roadmap_data', "
            "agent_name='roadmap_generator' to save the JSON object.\n"
            "9. Use HtmlRoadmapTool with:\n"
            "   - roadmap_data: the assembled JSON object\n"
            "   - filename: 'roadmap.html'\n"
            "   - agent_name: 'roadmap_generator'\n"
            "10. Use HumanInputTool with prompt: 'Please review the roadmap at "
            "outputs/roadmap.html and the underlying data at outputs/roadmap_data.json. "
            "Reply \"approved\" to conclude Delivery Planning, or provide revision notes.'\n"
            "11. If revision notes are received, revise the roadmap data and repeat "
            "steps 8\u201310. Maximum 3 revision cycles.\n"
        ),
        expected_output=(
            "A JSON roadmap saved to outputs/roadmap_data.json and a visual roadmap "
            "saved to outputs/roadmap.html, containing all initiatives sequenced into "
            "time periods with value streams, stakeholder group rows, capability builds, "
            "and benefits (value lever names + value estimate). "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
    )
```

- [ ] **Step 3: Create `tests/test_delivery_crew.py` (agent tests only)**

```python
# tests/test_delivery_crew.py
"""Unit tests for Delivery Planning crew agent and crew assembly."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


_VALUE_STREAMS = ["Operations", "IT"]
_STAKEHOLDER_GROUPS = ["Investor", "Customer", "Operations", "IT"]
_TIME_AXIS = "quarters"


# ── Roadmap Generator ─────────────────────────────────────────────────────────

def test_rg_agent_role(mock_llm):
    from agents.delivery.roadmap_generator import create_roadmap_generator
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    assert agent.role == "Roadmap Generator"


def test_rg_task_reads_initiative_register(mock_llm):
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=_VALUE_STREAMS,
        stakeholder_groups=_STAKEHOLDER_GROUPS,
        roadmap_time_axis=_TIME_AXIS,
    )
    assert "key='initiative_register'" in task.description


def test_rg_task_reads_propositions(mock_llm):
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=_VALUE_STREAMS,
        stakeholder_groups=_STAKEHOLDER_GROUPS,
        roadmap_time_axis=_TIME_AXIS,
    )
    assert "key='propositions'" in task.description


def test_rg_task_reads_value_levers(mock_llm):
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=_VALUE_STREAMS,
        stakeholder_groups=_STAKEHOLDER_GROUPS,
        roadmap_time_axis=_TIME_AXIS,
    )
    assert "key='value_levers'" in task.description


def test_rg_task_writes_roadmap_data(mock_llm):
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=_VALUE_STREAMS,
        stakeholder_groups=_STAKEHOLDER_GROUPS,
        roadmap_time_axis=_TIME_AXIS,
    )
    assert "key='roadmap_data'" in task.description
    assert "operation='write'" in task.description


def test_rg_task_calls_html_roadmap_tool(mock_llm):
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=_VALUE_STREAMS,
        stakeholder_groups=_STAKEHOLDER_GROUPS,
        roadmap_time_axis=_TIME_AXIS,
    )
    assert "HtmlRoadmapTool" in task.description


def test_rg_task_has_hitl(mock_llm):
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=_VALUE_STREAMS,
        stakeholder_groups=_STAKEHOLDER_GROUPS,
        roadmap_time_axis=_TIME_AXIS,
    )
    assert "HumanInputTool" in task.description
    assert "approved" in task.description


def test_rg_task_embeds_config_values(mock_llm):
    """Task description embeds value_stream_labels, stakeholder_groups, and time axis."""
    from agents.delivery.roadmap_generator import (
        create_roadmap_generator,
        create_roadmap_generator_task,
    )
    agent = create_roadmap_generator(slug="test", llm=mock_llm, tools=[])
    task = create_roadmap_generator_task(
        agent=agent,
        value_stream_labels=["Logistics", "Finance"],
        stakeholder_groups=["CEO", "CFO"],
        roadmap_time_axis="horizons",
    )
    assert "Logistics" in task.description
    assert "Finance" in task.description
    assert "CEO" in task.description
    assert "horizons" in task.description
```

- [ ] **Step 4: Run agent tests**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_delivery_crew.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add agents/delivery/__init__.py agents/delivery/roadmap_generator.py tests/test_delivery_crew.py
git commit -m "feat(sp3c): add Roadmap Generator agent"
```

---

## Task 4: Delivery Crew, Registry, and API Wiring

**Files:**
- Create: `agents/crews/delivery_crew.py`
- Modify: `agents/tools/registry.py` — add `roadmap_generator` entry
- Modify: `api/services/run_service.py` — add `"delivery"` branch + `_run_delivery_crew`
- Modify: `tests/test_delivery_crew.py` — append crew wiring tests
- Modify: `tests/test_run_api.py` — append delivery API test

- [ ] **Step 1: Create `agents/crews/delivery_crew.py`**

```python
# agents/crews/delivery_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_crew_llm
from agents.tools.registry import get_tools_for_agent
from agents.delivery.roadmap_generator import (
    create_roadmap_generator,
    create_roadmap_generator_task,
)


def create_delivery_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    value_stream_labels: list[str],
    stakeholder_groups: list[str],
    roadmap_time_axis: str,
    llm: LLM | None = None,
) -> Crew:
    """
    Assemble and return the Delivery Planning Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
        sector: Client sector (passed to tool registry for ChromaDB scoping).
        value_stream_labels: Value stream names from project config.
        stakeholder_groups: Stakeholder group names from project config.
        roadmap_time_axis: "quarters" | "years" | "horizons".
        llm: Optional LLM override (used in tests to inject a cheap model).
    """
    if llm is None:
        llm = get_crew_llm(llm_mode)  # Sonnet 4.6 (standard) or local (sensitive)

    rg = create_roadmap_generator(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent(
            "roadmap_generator", slug=slug, run_id=run_id, sector=sector
        ),
    )

    rg_task = create_roadmap_generator_task(
        agent=rg,
        value_stream_labels=value_stream_labels,
        stakeholder_groups=stakeholder_groups,
        roadmap_time_axis=roadmap_time_axis,
    )

    return Crew(
        agents=[rg],
        tasks=[rg_task],
        process=Process.sequential,
        verbose=True,
    )
```

- [ ] **Step 2: Add `roadmap_generator` entry to `agents/tools/registry.py`**

Read the current file. After the `"initiative_identifier"` entry (currently the last entry before the closing `}`), add:

```python
        "roadmap_generator": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
            HtmlRoadmapTool(slug=slug),
        ],
```

Also add the import at the top of the function body (alongside the existing imports inside `get_tools_for_agent`):

```python
    from agents.tools.html_roadmap import HtmlRoadmapTool
```

The full updated imports block inside `get_tools_for_agent` will be:

```python
    from agents.tools.sqlite_state import SQLiteStateTool
    from agents.tools.human_input import HumanInputTool
    from agents.tools.document_ingestion import DocumentIngestionTool
    from agents.tools.chroma_query import ChromaQueryTool
    from agents.tools.tavily_search import TavilySearchTool
    from agents.tools.mermaid_render import MermaidRenderTool
    from agents.tools.excel_output import ExcelOutputTool
    from agents.tools.html_roadmap import HtmlRoadmapTool
```

- [ ] **Step 3: Update `api/services/run_service.py`**

In `dispatch_crew()`, the current final branch is:

```python
        elif crew_name == "architecture":
            await _run_architecture_crew(slug=slug, run_id=run_id)
        else:
            raise ValueError(f"Unknown crew: '{crew_name}'")
```

Replace with:

```python
        elif crew_name == "architecture":
            await _run_architecture_crew(slug=slug, run_id=run_id)
        elif crew_name == "delivery":
            await _run_delivery_crew(slug=slug, run_id=run_id)
        else:
            raise ValueError(f"Unknown crew: '{crew_name}'")
```

Then append at the bottom of the file:

```python
async def _run_delivery_crew(slug: str, run_id: int) -> None:
    """Build and run the Delivery Planning Crew asynchronously."""
    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    llm_mode = config.get("llm_mode", "standard")
    sector = config.get("sector", "")
    value_stream_labels = config.get("value_stream_labels", [])
    stakeholder_groups = config.get("stakeholder_groups", [])
    roadmap_time_axis = config.get("roadmap_time_axis", "quarters")

    from agents.crews.delivery_crew import create_delivery_crew
    crew = create_delivery_crew(
        slug=slug,
        run_id=run_id,
        llm_mode=llm_mode,
        sector=sector,
        value_stream_labels=value_stream_labels,
        stakeholder_groups=stakeholder_groups,
        roadmap_time_axis=roadmap_time_axis,
    )
    # kickoff_async() runs the crew on the event loop without blocking
    await crew.kickoff_async()
```

- [ ] **Step 4: Append crew wiring tests to `tests/test_delivery_crew.py`**

Append (do NOT replace):

```python
# ── Crew wiring ───────────────────────────────────────────────────────────────

def test_delivery_crew_has_one_agent(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.delivery_crew import create_delivery_crew
        crew = create_delivery_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            value_stream_labels=_VALUE_STREAMS, stakeholder_groups=_STAKEHOLDER_GROUPS,
            roadmap_time_axis=_TIME_AXIS, llm=mock_llm,
        )
    assert len(crew.agents) == 1


def test_delivery_crew_agent_role(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.delivery_crew import create_delivery_crew
        crew = create_delivery_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            value_stream_labels=_VALUE_STREAMS, stakeholder_groups=_STAKEHOLDER_GROUPS,
            roadmap_time_axis=_TIME_AXIS, llm=mock_llm,
        )
    assert crew.agents[0].role == "Roadmap Generator"


def test_delivery_crew_sequential_process(mock_llm):
    from crewai import Process
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.delivery_crew import create_delivery_crew
        crew = create_delivery_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            value_stream_labels=_VALUE_STREAMS, stakeholder_groups=_STAKEHOLDER_GROUPS,
            roadmap_time_axis=_TIME_AXIS, llm=mock_llm,
        )
    assert crew.process == Process.sequential


def test_delivery_crew_sensitive_mode_uses_local_llm(mock_llm):
    """In sensitive mode, get_crew_llm is called with 'sensitive'."""
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]), \
         patch("agents.crews.delivery_crew.get_crew_llm") as mock_get_llm:
        mock_get_llm.return_value = mock_llm
        from agents.crews.delivery_crew import create_delivery_crew
        create_delivery_crew(
            slug="test", run_id=1, llm_mode="sensitive", sector="logistics",
            value_stream_labels=_VALUE_STREAMS, stakeholder_groups=_STAKEHOLDER_GROUPS,
            roadmap_time_axis=_TIME_AXIS,
        )
    mock_get_llm.assert_called_once_with("sensitive")
```

- [ ] **Step 5: Append delivery API test to `tests/test_run_api.py`**

Append (do NOT replace):

```python
@pytest.mark.asyncio
async def test_run_delivery_crew_queues_run(client):
    payload = {**PROJECT_PAYLOAD, "client_slug": "delivery-test", "crews_enabled": ["delivery"]}
    await client.post("/projects", json=payload)
    with patch("api.services.run_service.dispatch_crew", new_callable=AsyncMock):
        resp = await client.post("/projects/delivery-test/run", json={"crew": "delivery"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["crew"] == "delivery"
    assert data["status"] == "running"
    assert data["project_slug"] == "delivery-test"
    assert isinstance(data["run_id"], int)
```

- [ ] **Step 6: Run all unit tests**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/ -q --ignore=tests/integration
```

Expected: all tests pass (previous 75 + 12 new delivery + 8 html_roadmap + 1 run API = ~96 passing).

- [ ] **Step 7: Commit**

```bash
git add agents/crews/delivery_crew.py agents/tools/registry.py api/services/run_service.py tests/test_delivery_crew.py tests/test_run_api.py
git commit -m "feat(sp3c): add Delivery crew and API wiring"
```

---

## Task 5: Integration Fixture and Test

**Files:**
- Modify: `tests/integration/conftest.py` — append `seed_architecture_outputs`
- Create: `tests/integration/test_delivery_crew.py`

- [ ] **Step 1: Append `seed_architecture_outputs` to `tests/integration/conftest.py`**

Append after the `seed_value_design_outputs` fixture (current end of file):

```python
@pytest.fixture(scope="session")
def seed_architecture_outputs(test_slug, seed_value_design_outputs):
    """
    Write mock Architecture crew outputs to the test project's outputs directory.
    Required by Delivery Planning integration tests (Roadmap Generator reads initiative_register).
    seed_value_design_outputs is a dependency — it transitively seeds discovery outputs too.
    """
    from api.config import get_settings
    import json
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / test_slug / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    initiative_register = [
        {
            "id": "INIT-001",
            "title": "Automate Order Entry System",
            "description": "Implement end-to-end automated order management replacing manual entry.",
            "proposition_ids": ["VP-001"],
            "capability_gaps": ["No automated order capture system exists"],
            "category": "enabling",
            "complexity_score": 2,
            "complexity_rationale": "Well-understood technology with clear vendor options.",
            "related_requirements": ["REQ-001"],
        },
        {
            "id": "INIT-002",
            "title": "Integrate WMS and ERP Platforms",
            "description": "Build integration layer connecting WMS, ERP, and CRM systems.",
            "proposition_ids": ["VP-002"],
            "capability_gaps": [
                "No system integration layer exists",
                "Data duplicated across systems",
            ],
            "category": "operating_model",
            "complexity_score": 3,
            "complexity_rationale": "Requires significant data mapping and change management.",
            "related_requirements": ["REQ-002"],
        },
    ]
    (outputs_dir / "initiative_register.json").write_text(json.dumps(initiative_register))

    yield  # no teardown needed
```

- [ ] **Step 2: Verify conftest parses without errors**

```bash
cd /Users/pboagents/Documents/agentpool1/.worktrees/sp3c-delivery-planning && \
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/python \
  -c "import sys; sys.path.insert(0, '.'); import tests.integration.conftest; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Create `tests/integration/test_delivery_crew.py`**

```python
# tests/integration/test_delivery_crew.py
"""
End-to-end integration test for the Delivery Planning Crew (Roadmap Generator).

Requires:
- ANTHROPIC_API_KEY in .env
- Initiative register, propositions, and value_levers seeded by seed_architecture_outputs

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
def test_delivery_crew_end_to_end(test_slug, project_id, seed_architecture_outputs):
    """
    Run the full Delivery Planning Crew and verify all outputs are produced.
    Uses claude-haiku for the agent (test LLM override).
    HITL pauses are auto-responded via HITL_AUTO_RESPOND='approved' set in conftest.
    """
    from agents.llm import get_test_llm
    from agents.crews.delivery_crew import create_delivery_crew

    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{test_slug}.db"

    # Create a crew_run record
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status, started_at)"
        " VALUES (?,?,?, CURRENT_TIMESTAMP)",
        (project_id, "delivery", "running"),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()

    llm = get_test_llm()
    crew = create_delivery_crew(
        slug=test_slug,
        run_id=run_id,
        llm_mode="standard",
        sector="logistics",
        value_stream_labels=["Operations", "IT"],
        stakeholder_groups=["Investor", "Customer", "Operations", "IT"],
        roadmap_time_axis="quarters",
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

    # 1. roadmap_data.json exists with correct schema
    roadmap_path = outputs_dir / "roadmap_data.json"
    assert roadmap_path.exists(), "roadmap_data.json not created"
    roadmap = json.loads(roadmap_path.read_text())
    assert "periods" in roadmap, "roadmap_data.json missing 'periods'"
    assert "value_streams" in roadmap, "roadmap_data.json missing 'value_streams'"
    assert "initiatives" in roadmap, "roadmap_data.json missing 'initiatives'"
    assert "propositions" in roadmap, "roadmap_data.json missing 'propositions'"
    assert isinstance(roadmap["periods"], list) and len(roadmap["periods"]) >= 1
    assert isinstance(roadmap["initiatives"], list) and len(roadmap["initiatives"]) >= 1

    # 2. Each initiative has a period assigned
    for init in roadmap["initiatives"]:
        assert "period" in init, f"Initiative {init.get('id')} missing 'period'"

    # 3. Each proposition has value_levers (non-empty list)
    for prop in roadmap["propositions"]:
        assert "value_levers" in prop, f"Proposition {prop.get('id')} missing 'value_levers'"
        assert isinstance(prop["value_levers"], list), "value_levers must be a list"

    # 4. roadmap.html exists and contains value stream labels + period headers
    html_path = outputs_dir / "roadmap.html"
    assert html_path.exists(), "roadmap.html not created"
    html_content = html_path.read_text()
    assert "Operations" in html_content, "roadmap.html missing value stream label"
    for period in roadmap["periods"][:2]:
        assert period in html_content, f"roadmap.html missing period header: {period}"

    # 5. HITL record created
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM human_reviews WHERE crew_run_id=?", (run_id,)
        )
        hitl_count = cur.fetchone()[0]
    assert hitl_count >= 1, "No HITL reviews created during Delivery crew run"

    # 6. agent_outputs record for roadmap_generator
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "SELECT DISTINCT agent_name FROM agent_outputs WHERE project_id=?",
            (project_id,),
        )
        agent_names = {row[0] for row in cur.fetchall()}
    assert "roadmap_generator" in agent_names, \
        "Roadmap Generator produced no tracked output"
```

- [ ] **Step 4: Run the integration test**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/integration/test_delivery_crew.py -v -s
```

Expected: `PASSED` — takes 3–8 minutes.

**If it fails:**
- `roadmap_data.json not created` → Check HITL_AUTO_RESPOND env var is set (in conftest). Check that `seed_architecture_outputs` fixture successfully wrote `initiative_register.json`. Check that `seed_value_design_outputs` (transitive) wrote `propositions.json` and that `seed_discovery_outputs` (transitive) wrote `value_levers.json`.
- `value_levers is []` → The agent didn't trace lever evidence back to the register. Check that `value_levers.json` exists in outputs and contains `lever` fields, and that `propositions.json` has `supporting_evidence` entries with `type='lever'`.
- Any JSON parse error → LLM returned non-JSON; re-run once.

- [ ] **Step 5: Run full test suite**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/ -q --ignore=tests/integration && \
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest -m integration -v 2>&1 | tail -20
```

Expected: All unit tests pass. All integration tests pass (Discovery + Value Design + Architecture + Delivery).

- [ ] **Step 6: Commit**

```bash
git add tests/integration/conftest.py tests/integration/test_delivery_crew.py
git commit -m "test(sp3c): add Delivery crew integration test"
```

- [ ] **Step 7: Merge to master**

```bash
git checkout master
git merge --no-ff feature/sp3c-delivery-planning -m "Merge feature/sp3c-delivery-planning — Delivery Planning Crew (SP3c)"
```
