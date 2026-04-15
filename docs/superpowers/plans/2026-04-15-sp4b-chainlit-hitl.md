# SP4b Chainlit HITL Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Chainlit as a live HITL interface for all five crews so consultants can run any crew and respond to agent review gates directly in chat.

**Architecture:** A new `ChainlitHumanInputTool` subclasses `HumanInputTool` and replaces `_arun()` with `cl.AskUserMessage` — when the crew is running inside a Chainlit session, each HITL gate surfaces as a native text-input widget. The tool is injected via an optional `hitl_tool` param added to `get_tools_for_agent()` and all five crew factories. The Chainlit `app.py` is rewritten to route project/crew selection, create the tool, and call `crew.kickoff_async()`. The REST API path (`run_service.py`) is unchanged — it never passes `hitl_tool`, so `HumanInputTool` (SQLite polling) stays active for n8n/programmatic triggers.

**Tech Stack:** Python 3.13, CrewAI 1.14, Chainlit 2.6, aiosqlite, pytest-asyncio (strict mode)

---

## File Map

| File | Action |
|---|---|
| `agents/tools/chainlit_human_input.py` | Create |
| `agents/tools/registry.py` | Modify — add `hitl_tool` param |
| `agents/crews/discovery_crew.py` | Modify — add `hitl_tool` param |
| `agents/crews/value_design_crew.py` | Modify — add `hitl_tool` param |
| `agents/crews/architecture_crew.py` | Modify — add `hitl_tool` param |
| `agents/crews/delivery_crew.py` | Modify — add `hitl_tool` param |
| `agents/crews/business_plan_crew.py` | Modify — add `hitl_tool` param |
| `chainlit_app/app.py` | Full rewrite |
| `tests/test_chainlit_human_input.py` | Create |
| `tests/test_registry.py` | Create |
| `tests/test_discovery_crew.py` | Modify — add hitl_tool test |
| `tests/test_value_design_crew.py` | Modify — add hitl_tool test |
| `tests/test_architecture_crew.py` | Modify — add hitl_tool test |
| `tests/test_delivery_crew.py` | Modify — add hitl_tool test |
| `tests/test_business_plan_crew.py` | Modify — add hitl_tool test |

---

## Task 1: ChainlitHumanInputTool

**Files:**
- Create: `agents/tools/chainlit_human_input.py`
- Create: `tests/test_chainlit_human_input.py`

### Background

`HumanInputTool._run()` polls SQLite every 5 seconds waiting for a human to submit a decision via the REST API. `ChainlitHumanInputTool` replaces this with `cl.AskUserMessage` — Chainlit's native "pause and wait for user input" primitive. It keeps the same `name = "HumanInputTool"` so all existing agent task descriptions work unchanged.

`insert_hitl_review` and `complete_hitl_review` are synchronous (`sqlite3`) — fine to call from `async def`. They do fast point writes.

The test file uses `@pytest.mark.asyncio` (required — `asyncio_mode = strict` in `pytest.ini`). Patching `chainlit.AskUserMessage` at the module level works because `import chainlit as cl` in the implementation file is just an alias — `cl.AskUserMessage` resolves to the same object as `chainlit.AskUserMessage`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chainlit_human_input.py`:

```python
# tests/test_chainlit_human_input.py
"""Unit tests for ChainlitHumanInputTool."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def tool():
    from agents.tools.chainlit_human_input import ChainlitHumanInputTool
    return ChainlitHumanInputTool(slug="test-proj", run_id=42)


@pytest.mark.asyncio
async def test_arun_returns_user_response(tool):
    with patch("chainlit.AskUserMessage") as mock_ask, \
         patch("agents.tools.chainlit_human_input.insert_hitl_review", return_value=1), \
         patch("agents.tools.chainlit_human_input.complete_hitl_review"):
        mock_ask.return_value.send = AsyncMock(return_value={"output": "approved"})
        result = await tool._arun("Please approve the value chain.")
    assert result == "approved"


@pytest.mark.asyncio
async def test_arun_writes_audit_record(tool):
    with patch("chainlit.AskUserMessage") as mock_ask, \
         patch("agents.tools.chainlit_human_input.insert_hitl_review", return_value=1) as mock_insert, \
         patch("agents.tools.chainlit_human_input.complete_hitl_review"):
        mock_ask.return_value.send = AsyncMock(return_value={"output": "ok"})
        await tool._arun("Review this output.")
    mock_insert.assert_called_once_with(slug="test-proj", run_id=42, prompt="Review this output.")


@pytest.mark.asyncio
async def test_arun_completes_audit_record(tool):
    with patch("chainlit.AskUserMessage") as mock_ask, \
         patch("agents.tools.chainlit_human_input.insert_hitl_review", return_value=7), \
         patch("agents.tools.chainlit_human_input.complete_hitl_review") as mock_complete:
        mock_ask.return_value.send = AsyncMock(return_value={"output": "approved"})
        await tool._arun("Approve?")
    mock_complete.assert_called_once_with(slug="test-proj", review_id=7, decision="approved")


@pytest.mark.asyncio
async def test_arun_on_timeout_returns_timeout_string(tool):
    with patch("chainlit.AskUserMessage") as mock_ask, \
         patch("agents.tools.chainlit_human_input.insert_hitl_review", return_value=1), \
         patch("agents.tools.chainlit_human_input.complete_hitl_review"):
        mock_ask.return_value.send = AsyncMock(return_value=None)
        result = await tool._arun("Approve?")
    assert result.startswith("timeout:")


@pytest.mark.asyncio
async def test_arun_db_error_returns_error_string(tool):
    with patch("agents.tools.chainlit_human_input.insert_hitl_review",
               side_effect=RuntimeError("db down")):
        result = await tool._arun("Approve?")
    assert result.startswith("Error:")


def test_tool_name_is_HumanInputTool(tool):
    assert tool.name == "HumanInputTool"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_chainlit_human_input.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'agents.tools.chainlit_human_input'`

- [ ] **Step 3: Create the implementation**

Create `agents/tools/chainlit_human_input.py`:

```python
# agents/tools/chainlit_human_input.py
"""
ChainlitHumanInputTool — HumanInputTool variant for Chainlit sessions.

Uses cl.AskUserMessage to pause crew execution and surface HITL prompts
as native Chainlit input widgets. The sync _run() inherited from
HumanInputTool (SQLite polling) is not used in this path.
"""
import chainlit as cl
from agents.tools.human_input import HumanInputTool
from agents.tools._db import insert_hitl_review, complete_hitl_review

_DEFAULT_HITL_TIMEOUT = 86400  # 24 hours — matches HumanInputTool


class ChainlitHumanInputTool(HumanInputTool):
    name: str = "HumanInputTool"  # must match — task descriptions reference this name

    async def _arun(self, prompt: str) -> str:
        try:
            review_id = insert_hitl_review(
                slug=self.slug, run_id=self.run_id, prompt=prompt
            )
        except Exception as e:
            return f"Error: could not create review record — {e}"

        res = await cl.AskUserMessage(
            content=prompt, timeout=_DEFAULT_HITL_TIMEOUT
        ).send()
        response = res["output"] if res else "timeout: no response received"

        complete_hitl_review(slug=self.slug, review_id=review_id, decision=response)
        return response
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_chainlit_human_input.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Run full suite to check for regressions**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/ --ignore=tests/integration -q
```

Expected: all tests pass (was 132 before this task; now 138)

- [ ] **Step 6: Commit**

```bash
git add agents/tools/chainlit_human_input.py tests/test_chainlit_human_input.py
git commit -m "feat: add ChainlitHumanInputTool with cl.AskUserMessage"
```

---

## Task 2: Registry hitl_tool injection

**Files:**
- Modify: `agents/tools/registry.py`
- Create: `tests/test_registry.py`

### Background

`get_tools_for_agent()` builds tool lists from a dict literal. Adding `hitl_tool=None` and a post-build list comprehension is the single change needed to cover all 10 agents. The `isinstance(t, HumanInputTool)` check works because `HumanInputTool` is already imported at the top of the function body.

For the test, `"initiative_identifier"` is the simplest agent — its tool list is `[SQLiteStateTool, HumanInputTool]` with no network-connecting tools. Pass `sector="test"` directly to skip the config-loading branch.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_registry.py`:

```python
# tests/test_registry.py
"""Unit tests for tool registry hitl_tool injection."""
from unittest.mock import MagicMock


def test_hitl_tool_injection_replaces_human_input_tool():
    """When hitl_tool is provided, all HumanInputTool instances in the list are replaced."""
    from agents.tools.human_input import HumanInputTool
    from agents.tools.registry import get_tools_for_agent

    mock_hitl = MagicMock()
    tools = get_tools_for_agent(
        "initiative_identifier", slug="test", run_id=1, sector="test",
        hitl_tool=mock_hitl,
    )

    tool_types = [type(t) for t in tools]
    assert HumanInputTool not in tool_types, "HumanInputTool should have been replaced"
    assert mock_hitl in tools, "mock_hitl should be in the tool list"


def test_hitl_tool_none_uses_default_human_input_tool():
    """When hitl_tool is None (default), HumanInputTool is used as normal."""
    from agents.tools.human_input import HumanInputTool
    from agents.tools.registry import get_tools_for_agent

    tools = get_tools_for_agent(
        "initiative_identifier", slug="test", run_id=1, sector="test",
    )

    tool_types = [type(t) for t in tools]
    assert HumanInputTool in tool_types, "HumanInputTool should be present when no override given"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_registry.py -v
```

Expected: `FAILED test_hitl_tool_injection_replaces_human_input_tool` — `get_tools_for_agent` does not yet accept `hitl_tool` keyword argument.

- [ ] **Step 3: Add the hitl_tool parameter to registry.py**

In `agents/tools/registry.py`, change the function signature and add the replacement logic at the end:

```python
def get_tools_for_agent(
    agent_name: str,
    slug: str,
    run_id: int = 0,
    sector: str = "",
    hitl_tool=None,
) -> list[BaseTool]:
    """Return instantiated tools for the given agent, scoped to the project slug."""
    from agents.tools.sqlite_state import SQLiteStateTool
    from agents.tools.human_input import HumanInputTool
    from agents.tools.document_ingestion import DocumentIngestionTool
    from agents.tools.chroma_query import ChromaQueryTool
    from agents.tools.tavily_search import TavilySearchTool
    from agents.tools.mermaid_render import MermaidRenderTool
    from agents.tools.excel_output import ExcelOutputTool
    from agents.tools.html_roadmap import HtmlRoadmapTool
    from agents.tools.word_output import WordOutputTool
    from agents.tools.powerpoint_output import PowerPointOutputTool
    from agents.tools.financial_model import FinancialModelTool

    if not sector:
        settings = get_settings()
        try:
            config = load_project_config(Path(settings.projects_dir) / slug)
            sector = config.get("sector", "")
        except Exception as e:
            _log.warning("Could not load project config for %s: %s", slug, e)
            sector = ""

    tool_map: dict[str, list[BaseTool]] = {
        "value_chain_mapper": [
            DocumentIngestionTool(slug=slug),
            TavilySearchTool(),
            ChromaQueryTool(slug=slug, sector=sector),
            MermaidRenderTool(slug=slug),
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
        "requirements_capture": [
            HumanInputTool(slug=slug, run_id=run_id),
            SQLiteStateTool(slug=slug),
        ],
        "requirements_analyst": [
            DocumentIngestionTool(slug=slug),
            ChromaQueryTool(slug=slug, sector=sector),
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
        "value_lever_analyst": [
            ChromaQueryTool(slug=slug, sector=sector),
            TavilySearchTool(),
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
        "pam": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
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
        "roadmap_generator": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
            HtmlRoadmapTool(slug=slug),
        ],
        "business_plan_generator": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
            WordOutputTool(slug=slug),
            PowerPointOutputTool(slug=slug),
            FinancialModelTool(slug=slug),
        ],
    }

    tools = tool_map.get(agent_name)
    if tools is None:
        raise ValueError(f"Unknown agent: {agent_name}")

    if hitl_tool is not None:
        tools = [hitl_tool if isinstance(t, HumanInputTool) else t for t in tools]

    return tools
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_registry.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Run full suite to check for regressions**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/ --ignore=tests/integration -q
```

Expected: all tests pass (was 138 after Task 1; now 140)

- [ ] **Step 6: Commit**

```bash
git add agents/tools/registry.py tests/test_registry.py
git commit -m "feat: add hitl_tool injection to get_tools_for_agent"
```

---

## Task 3: Crew factory propagation

**Files:**
- Modify: `agents/crews/discovery_crew.py`
- Modify: `agents/crews/value_design_crew.py`
- Modify: `agents/crews/architecture_crew.py`
- Modify: `agents/crews/delivery_crew.py`
- Modify: `agents/crews/business_plan_crew.py`
- Modify: `tests/test_architecture_crew.py` (add 1 test)
- Modify: `tests/test_value_design_crew.py` (add 1 test)
- Modify: `tests/test_delivery_crew.py` (add 1 test)
- Modify: `tests/test_business_plan_crew.py` (add 1 test)
- Modify (or create): `tests/test_discovery_crew.py` (add 1 test — file may not exist)

### Background

Each `create_*_crew()` function passes `slug`, `run_id`, `sector` directly to `get_tools_for_agent()`. Adding `hitl_tool=None` to the crew signature and threading it through all `get_tools_for_agent()` calls is uniform across all five crews. The test for each crew patches `get_tools_for_agent` (to avoid network tools) and asserts it was called with `hitl_tool=mock_hitl`.

Note: `discovery_crew.py` calls `get_tools_for_agent` 4 times (one per agent). The test asserts `hitl_tool=mock_hitl` appears in every call. The other crews call it fewer times (2, 2, 1, 1).

Note: `delivery_crew.py` has additional parameters (`value_stream_labels`, `stakeholder_groups`, `roadmap_time_axis`) that are positional after `sector`. Add `hitl_tool=None` after those existing parameters.

- [ ] **Step 1: Write the 5 failing tests (add to existing test files)**

First check whether `tests/test_discovery_crew.py` exists:

```bash
ls tests/test_discovery_crew.py 2>/dev/null || echo "MISSING"
```

If MISSING, create `tests/test_discovery_crew.py` with just the fixture and the new test:

```python
# tests/test_discovery_crew.py
"""Unit tests for Discovery crew assembly."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


def test_discovery_crew_accepts_hitl_tool_override(mock_llm):
    """hitl_tool is forwarded to every get_tools_for_agent call."""
    mock_hitl = MagicMock()
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.discovery_crew import create_discovery_crew
        create_discovery_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            llm=mock_llm, hitl_tool=mock_hitl,
        )
    for call in mock_reg.call_args_list:
        assert call.kwargs.get("hitl_tool") == mock_hitl, \
            f"Expected hitl_tool in call: {call}"
```

If it exists, append only the test function (no fixture — it already has one).

Add to **`tests/test_value_design_crew.py`** (at the end):

```python
def test_value_design_crew_accepts_hitl_tool_override(mock_llm):
    """hitl_tool is forwarded to every get_tools_for_agent call."""
    mock_hitl = MagicMock()
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.value_design_crew import create_value_design_crew
        create_value_design_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            llm=mock_llm, hitl_tool=mock_hitl,
        )
    for call in mock_reg.call_args_list:
        assert call.kwargs.get("hitl_tool") == mock_hitl, \
            f"Expected hitl_tool in call: {call}"
```

Add to **`tests/test_architecture_crew.py`** (at the end):

```python
def test_architecture_crew_accepts_hitl_tool_override(mock_llm):
    """hitl_tool is forwarded to every get_tools_for_agent call."""
    mock_hitl = MagicMock()
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.architecture_crew import create_architecture_crew
        create_architecture_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            llm=mock_llm, hitl_tool=mock_hitl,
        )
    for call in mock_reg.call_args_list:
        assert call.kwargs.get("hitl_tool") == mock_hitl, \
            f"Expected hitl_tool in call: {call}"
```

Add to **`tests/test_delivery_crew.py`** (at the end):

```python
def test_delivery_crew_accepts_hitl_tool_override(mock_llm):
    """hitl_tool is forwarded to get_tools_for_agent."""
    mock_hitl = MagicMock()
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.delivery_crew import create_delivery_crew
        create_delivery_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            value_stream_labels=["A", "B"], stakeholder_groups=["X"],
            roadmap_time_axis="quarters", llm=mock_llm, hitl_tool=mock_hitl,
        )
    for call in mock_reg.call_args_list:
        assert call.kwargs.get("hitl_tool") == mock_hitl, \
            f"Expected hitl_tool in call: {call}"
```

Add to **`tests/test_business_plan_crew.py`** (at the end):

```python
def test_business_plan_crew_accepts_hitl_tool_override(mock_llm):
    """hitl_tool is forwarded to get_tools_for_agent."""
    mock_hitl = MagicMock()
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.business_plan_crew import create_business_plan_crew
        create_business_plan_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics",
            llm=mock_llm, hitl_tool=mock_hitl,
        )
    mock_reg.assert_called_once_with(
        "business_plan_generator", slug="test", run_id=1,
        sector="logistics", hitl_tool=mock_hitl,
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_discovery_crew.py tests/test_value_design_crew.py tests/test_architecture_crew.py tests/test_delivery_crew.py tests/test_business_plan_crew.py -v -k "hitl_tool" 2>&1 | tail -15
```

Expected: 5 failures — `create_*_crew()` does not yet accept `hitl_tool`.

- [ ] **Step 3: Update discovery_crew.py**

In `agents/crews/discovery_crew.py`, add `hitl_tool=None` to the signature and thread through all four `get_tools_for_agent` calls:

```python
def create_discovery_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
    hitl_tool=None,
) -> Crew:
    """
    Assemble and return the Discovery Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
        sector: Client sector (used by ChromaQueryTool for sector knowledge base).
        llm: Optional LLM override (used in tests to inject a cheap model).
        hitl_tool: Optional HITL tool override (used in Chainlit sessions to inject
            ChainlitHumanInputTool in place of the default SQLite-polling HumanInputTool).
    """
    if llm is None:
        llm = get_crew_llm(llm_mode)

    vcm = create_value_chain_mapper(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("value_chain_mapper", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )
    rc = create_requirements_capture(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("requirements_capture", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )
    ra = create_requirements_analyst(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("requirements_analyst", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )
    vla = create_value_lever_analyst(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("value_lever_analyst", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )

    vcm_task = create_value_chain_mapper_task(agent=vcm)
    rc_task = create_requirements_capture_task(agent=rc, context_tasks=[vcm_task], slug=slug)
    ra_task = create_requirements_analyst_task(agent=ra, context_tasks=[vcm_task, rc_task])
    vla_task = create_value_lever_analyst_task(agent=vla, context_tasks=[vcm_task, ra_task])

    return Crew(
        agents=[vcm, rc, ra, vla],
        tasks=[vcm_task, rc_task, ra_task, vla_task],
        process=Process.sequential,
        verbose=True,
    )
```

- [ ] **Step 4: Update value_design_crew.py**

Add `hitl_tool=None` to `create_value_design_crew` signature and thread through both `get_tools_for_agent` calls:

```python
def create_value_design_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
    hitl_tool=None,
) -> Crew:
    """
    Assemble and return the Value Design Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
        sector: Client sector (unused by Value Design but kept for interface consistency).
        llm: Optional LLM override (used in tests to inject a cheap model for all agents).
        hitl_tool: Optional HITL tool override (used in Chainlit sessions).
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
        tools=get_tools_for_agent("value_proposition_generator", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )
    pm = create_portfolio_manager(
        slug=slug,
        llm=pm_llm,
        tools=get_tools_for_agent("portfolio_manager", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
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

- [ ] **Step 5: Update architecture_crew.py**

Add `hitl_tool=None` to `create_architecture_crew` signature and thread through both `get_tools_for_agent` calls:

```python
def create_architecture_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
    hitl_tool=None,
) -> Crew:
    """
    Assemble and return the Architecture Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
        sector: Client sector (used by ChromaQueryTool for sector knowledge base).
        llm: Optional LLM override (used in tests to inject a cheap model).
        hitl_tool: Optional HITL tool override (used in Chainlit sessions).
    """
    if llm is None:
        llm = get_crew_llm(llm_mode)  # Sonnet 4.6 (standard) or local (sensitive)

    ea = create_enterprise_architect(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("enterprise_architect", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
    )
    ii = create_initiative_identifier(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent("initiative_identifier", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool),
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

- [ ] **Step 6: Update delivery_crew.py**

Add `hitl_tool=None` after `roadmap_time_axis` in `create_delivery_crew` signature and thread through the single `get_tools_for_agent` call:

```python
def create_delivery_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    value_stream_labels: list[str],
    stakeholder_groups: list[str],
    roadmap_time_axis: str,
    llm: LLM | None = None,
    hitl_tool=None,
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
        hitl_tool: Optional HITL tool override (used in Chainlit sessions).
    """
    if llm is None:
        llm = get_crew_llm(llm_mode)  # Sonnet 4.6 (standard) or local (sensitive)

    rg = create_roadmap_generator(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent(
            "roadmap_generator", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool
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

- [ ] **Step 7: Update business_plan_crew.py**

Add `hitl_tool=None` after `sector` in `create_business_plan_crew` signature and thread through the single `get_tools_for_agent` call:

```python
def create_business_plan_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
    hitl_tool=None,
) -> Crew:
    """
    Assemble and return the Business Plan Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
            Sensitive mode uses the local LLM. Standard and fallback both use Opus 4.6
            via get_pam_llm() — business plan quality requires Opus regardless of mode.
        sector: Client sector (passed to tool registry).
        llm: Optional LLM override (used in tests to inject a cheap model).
        hitl_tool: Optional HITL tool override (used in Chainlit sessions).
    """
    if llm is not None:
        bpg_llm = llm  # injected override
    elif llm_mode == "sensitive":
        bpg_llm = get_crew_llm("sensitive")  # local LLM for sensitive data
    else:
        bpg_llm = get_pam_llm()  # Claude Opus 4.6

    bpg = create_business_plan_generator(
        slug=slug,
        llm=bpg_llm,
        tools=get_tools_for_agent(
            "business_plan_generator", slug=slug, run_id=run_id, sector=sector,
            hitl_tool=hitl_tool,
        ),
    )

    bpg_task = create_business_plan_generator_task(agent=bpg)

    return Crew(
        agents=[bpg],
        tasks=[bpg_task],
        process=Process.sequential,
        verbose=True,
    )
```

- [ ] **Step 8: Run the 5 new tests to verify they pass**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/test_discovery_crew.py tests/test_value_design_crew.py tests/test_architecture_crew.py tests/test_delivery_crew.py tests/test_business_plan_crew.py -v -k "hitl_tool"
```

Expected: `5 passed`

- [ ] **Step 9: Run full suite to check for regressions**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/ --ignore=tests/integration -q
```

Expected: all tests pass (was 140 after Task 2; now 145)

- [ ] **Step 10: Commit**

```bash
git add agents/crews/discovery_crew.py agents/crews/value_design_crew.py \
        agents/crews/architecture_crew.py agents/crews/delivery_crew.py \
        agents/crews/business_plan_crew.py \
        tests/test_discovery_crew.py tests/test_value_design_crew.py \
        tests/test_architecture_crew.py tests/test_delivery_crew.py \
        tests/test_business_plan_crew.py
git commit -m "feat: propagate hitl_tool param through all five crew factories"
```

---

## Task 4: Chainlit app.py rewrite

**Files:**
- Rewrite: `chainlit_app/app.py`

### Background

`chainlit_app/app.py` is currently a shell with a placeholder. This task replaces it with the full session state machine described in the design spec.

Key points:
- Session state uses `cl.user_session` with keys `"slug"` and `"crew"`.
- `_run_crew()` creates the DB run record, instantiates `ChainlitHumanInputTool`, calls `crew.kickoff_async()`, then marks completion and lists outputs.
- `_build_crew()` is a sync dispatch function — all crew factories are synchronous (they just wire objects together).
- `_create_run_record()` and `_mark_run_completed()` are async wrappers around `get_connection` / `insert_crew_run` / `update_crew_run_status` from `api.database`.
- Error handling in `_run_crew()` guards `run_id` being undefined if `_create_run_record` itself fails (initialise as `None` before the try block).
- `get_settings()` is called at module level — safe because conftest.py has already set all env vars before import.
- The delivery crew needs `value_stream_labels`, `stakeholder_groups`, and `roadmap_time_axis` from the project config; these are validated before passing.

No unit tests are written for `app.py` — it is thin orchestration calling already-tested components.

- [ ] **Step 1: Rewrite chainlit_app/app.py**

Replace the entire contents of `chainlit_app/app.py` with:

```python
# chainlit_app/app.py
"""
AgentPool Chainlit HITL interface.

Session flow:
  selecting_project  →  (enter project slug)
  selecting_crew     →  (enter crew name)
  running            →  crew runs; cl.AskUserMessage handles HITL transparently

HITL gates do NOT go through on_message — Chainlit handles cl.AskUserMessage
at the protocol level. The on_message handler only needs to manage project/crew
selection, not in-flight crew communication.
"""
import chainlit as cl
import httpx
from pathlib import Path

from api.config import get_settings, load_project_config
from api.database import (
    get_connection,
    fetch_project,
    insert_crew_run,
    update_crew_run_status,
)

FASTAPI_BASE = "http://localhost:8000"
_VALID_CREWS = frozenset(
    {"discovery", "value_design", "architecture", "delivery", "business_plan"}
)
_settings = get_settings()


# ── Chainlit handlers ────────────────────────────────────────────────────────


@cl.on_chat_start
async def start() -> None:
    cl.user_session.set("slug", None)
    cl.user_session.set("crew", None)
    await cl.Message(
        content=(
            "**AgentPool** — Digital Modernisation Agent Team\n\n"
            "Enter a project slug to begin (e.g. `acme-rail`)."
        )
    ).send()


@cl.on_message
async def handle_message(msg: cl.Message) -> None:
    slug = cl.user_session.get("slug")
    crew_name = cl.user_session.get("crew")

    if slug is None:
        await _handle_project_selection(msg.content.strip().lower())
        return

    if crew_name is None:
        await _handle_crew_selection(slug, msg.content.strip().lower())
        return

    # This branch should not be reached in normal operation:
    # cl.AskUserMessage handles HITL gates transparently without going through on_message.
    await cl.Message(content="Please respond to the agent prompt above.").send()


# ── Selection helpers ────────────────────────────────────────────────────────


async def _handle_project_selection(candidate: str) -> None:
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{FASTAPI_BASE}/projects/{candidate}/status", timeout=5.0
            )
        except Exception as e:
            await cl.Message(content=f"Could not reach API: {e}").send()
            return
    if resp.status_code == 200:
        cl.user_session.set("slug", candidate)
        await cl.Message(
            content=(
                f"Project **{candidate}** loaded.\n\n"
                "Which crew would you like to run?\n"
                "```\ndiscovery | value_design | architecture | delivery | business_plan\n```"
            )
        ).send()
    else:
        await cl.Message(
            content=(
                f"Project `{candidate}` not found. "
                "Create it first via the API, then try again."
            )
        ).send()


async def _handle_crew_selection(slug: str, crew_name: str) -> None:
    if crew_name not in _VALID_CREWS:
        await cl.Message(
            content=(
                f"Unknown crew `{crew_name}`. Choose one of:\n"
                "```\ndiscovery | value_design | architecture | delivery | business_plan\n```"
            )
        ).send()
        return
    cl.user_session.set("crew", crew_name)
    await _run_crew(slug, crew_name)
    cl.user_session.set("crew", None)  # ready for another run on the same project


# ── Crew execution ───────────────────────────────────────────────────────────


async def _run_crew(slug: str, crew_name: str) -> None:
    run_id: int | None = None
    try:
        run_id = await _create_run_record(slug, crew_name)

        from agents.tools.chainlit_human_input import ChainlitHumanInputTool
        hitl_tool = ChainlitHumanInputTool(slug=slug, run_id=run_id)

        config = load_project_config(Path(_settings.projects_dir) / slug)
        llm_mode = config.get("llm_mode", "standard")
        sector = config.get("sector", "")

        crew = _build_crew(crew_name, slug, run_id, llm_mode, sector, config, hitl_tool)

        await cl.Message(content=f"⚙ Running **{crew_name}** crew…").send()
        await crew.kickoff_async()

        await _mark_run_completed(slug, run_id, "completed")
        await _send_completion_message(slug)

    except Exception as e:
        if run_id is not None:
            await _mark_run_completed(slug, run_id, "failed")
        await cl.Message(content=f"✗ Crew failed: {e}").send()


def _build_crew(
    crew_name: str,
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    config: dict,
    hitl_tool,
):
    """Dispatch to the correct crew factory based on crew_name."""
    base = dict(slug=slug, run_id=run_id, llm_mode=llm_mode, sector=sector, hitl_tool=hitl_tool)

    if crew_name == "discovery":
        from agents.crews.discovery_crew import create_discovery_crew
        return create_discovery_crew(**base)

    if crew_name == "value_design":
        from agents.crews.value_design_crew import create_value_design_crew
        return create_value_design_crew(**base)

    if crew_name == "architecture":
        from agents.crews.architecture_crew import create_architecture_crew
        return create_architecture_crew(**base)

    if crew_name == "delivery":
        from agents.crews.delivery_crew import create_delivery_crew
        value_stream_labels = config.get("value_stream_labels", [])
        stakeholder_groups = config.get("stakeholder_groups", [])
        roadmap_time_axis = config.get("roadmap_time_axis", "quarters")
        if not value_stream_labels:
            raise ValueError("Project config missing 'value_stream_labels'")
        if not stakeholder_groups:
            raise ValueError("Project config missing 'stakeholder_groups'")
        return create_delivery_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            value_stream_labels=value_stream_labels,
            stakeholder_groups=stakeholder_groups,
            roadmap_time_axis=roadmap_time_axis,
            hitl_tool=hitl_tool,
        )

    if crew_name == "business_plan":
        from agents.crews.business_plan_crew import create_business_plan_crew
        return create_business_plan_crew(**base)

    raise ValueError(f"Unknown crew: {crew_name}")  # guarded by _VALID_CREWS check upstream


# ── DB helpers ───────────────────────────────────────────────────────────────


async def _create_run_record(slug: str, crew_name: str) -> int:
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise ValueError(f"Project '{slug}' not found in database")
        run_id = await insert_crew_run(
            conn, project_id=project["id"], crew_name=crew_name, status="running"
        )
    return run_id


async def _mark_run_completed(slug: str, run_id: int, status: str) -> None:
    async with get_connection(slug) as conn:
        await update_crew_run_status(conn, run_id=run_id, status=status)


# ── Completion message ───────────────────────────────────────────────────────


async def _send_completion_message(slug: str) -> None:
    outputs_dir = Path(_settings.projects_dir) / slug / "outputs"
    lines = ["✓ Crew complete."]
    if outputs_dir.exists():
        files = sorted(f for f in outputs_dir.iterdir() if f.is_file())
        if files:
            lines.append("\nOutputs:")
            for f in files:
                size_kb = f.stat().st_size // 1024
                lines.append(f"• {f.name}  ({size_kb} KB)")
    await cl.Message(content="\n".join(lines)).send()
```

- [ ] **Step 2: Run full unit test suite to verify no regressions**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/ --ignore=tests/integration -q
```

Expected: all tests pass (still 145 — app.py has no unit tests)

- [ ] **Step 3: Verify Chainlit app imports cleanly**

```bash
cd /Users/pboagents/Documents/agentpool1 && \
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/python -c "
import sys
sys.path.insert(0, '.')
# Simulate the env vars conftest sets
import os
os.environ.setdefault('ANTHROPIC_API_KEY', 'test-key')
os.environ.setdefault('JWT_SECRET', 'test-secret')
os.environ.setdefault('DATABASE_DIR', '/tmp/agentpool_test')
os.environ.setdefault('PROJECTS_DIR', '/tmp/agentpool_test_projects')
import ast, pathlib
src = pathlib.Path('chainlit_app/app.py').read_text()
ast.parse(src)
print('Syntax OK')
"
```

Expected: `Syntax OK`

- [ ] **Step 4: Commit**

```bash
git add chainlit_app/app.py
git commit -m "feat: rewrite Chainlit app with full crew routing and ChainlitHumanInputTool"
```

---

## Final check

- [ ] **Run the complete unit test suite one last time**

```bash
/Users/pboagents/Documents/agentpool1/.worktrees/sp3a-discovery-crew/.venv/bin/pytest tests/ --ignore=tests/integration -q
```

Expected: 145 passed (132 original + 6 chainlit_human_input + 2 registry + 5 crew hitl_tool)
