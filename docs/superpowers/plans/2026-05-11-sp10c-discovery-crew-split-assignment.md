# SP10c — Discovery Crew Split + Stakeholder Assignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the monolithic `discovery` crew into a mapping-only `discovery_mapping` crew with a PAM-level `awaiting_assignment` gate, and add a stakeholder assignment UI so consultants can assign registry stakeholders to value chain nodes before interviews begin.

**Architecture:** Two PAM phases share an `orchestration_run_id` — Phase 1 runs `discovery_mapping` and sets status to `awaiting_assignment`; Phase 2 is triggered by the consultant confirming assignments via a new Assignment page and runs the rest of the pipeline. Three new API endpoints (GET/POST assignment data, PATCH advance) back the Assignment page. The value chain tree JSON is saved by the mapper agent directly to `outputs/value_chain_tree.json` via `SQLiteStateTool`.

**Tech Stack:** Python/FastAPI, aiosqlite, CrewAI, React/TypeScript, TanStack Query, React Router, Tailwind CSS

---

## File Map

**New files:**
- `agents/crews/discovery_mapping_crew.py` — single-agent crew (Value Chain Mapper only)
- `api/routers/assignment.py` — GET/POST/PATCH assignment endpoints
- `tests/test_assignment_api.py` — API tests for assignment endpoints
- `ui/src/pages/Assignment.tsx` — two-panel assignment UI

**Modified files:**
- `agents/discovery/value_chain_mapper.py` — add `value_chain_tree` JSON save step to task
- `agents/pam/pam_agent.py` — add `create_run_discovery_mapping_task`
- `agents/crews/pam_crew.py` — replace `create_pam_crew` with `create_pam_mapping_crew` + `create_pam_resume_crew`
- `api/services/orchestration_service.py` — split into `run_pam_phase1` / `run_pam_phase2` / `resume_orchestration`
- `api/services/project_service.py` — add `get_value_chain_tree`
- `api/database.py` — add `stakeholder_assignments` migration + 2 helpers
- `api/services/run_service.py` — add `discovery_mapping` branch
- `api/main.py` — register assignment router
- `tests/test_pam_crew.py` — update for new crew factories
- `tests/test_orchestration_service.py` — update for new service functions
- `ui/src/types.ts` — add `ValueChainNode`, `StakeholderAssignment`, `AssignmentData`
- `ui/src/api/endpoints.ts` — add 3 assignment API methods
- `ui/src/components/StatusBadge.tsx` — add `awaiting_assignment` colour
- `ui/src/pages/Runs.tsx` — add assignment link for `awaiting_assignment` runs
- `ui/src/router.tsx` — add `/:slug/assignment` route

---

## Task 1: DB migration — `stakeholder_assignments` + helpers

**Files:**
- Modify: `api/database.py`

### Background

`database.py` uses a pattern of `_migrate_*` async functions that are called from `get_connection`. Each one uses `CREATE TABLE IF NOT EXISTS` or `ALTER TABLE` so they are safe to run on existing DBs.

The `_json` alias for the `json` module is already imported at the top of `database.py`. `get_settings()` and `Path` are already imported.

- [ ] **Step 1: Add `_migrate_stakeholder_assignments` after `_migrate_campaigns`**

In `api/database.py`, add this function after `_migrate_campaigns` (around line 213):

```python
async def _migrate_stakeholder_assignments(conn: aiosqlite.Connection) -> None:
    """Create stakeholder_assignments table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS stakeholder_assignments (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            orchestration_run_id  INTEGER NOT NULL REFERENCES orchestration_runs(id),
            stakeholder_id        INTEGER NOT NULL REFERENCES stakeholders(id),
            level                 TEXT NOT NULL,
            node_label            TEXT NOT NULL,
            created_at            DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()
```

- [ ] **Step 2: Call `_migrate_stakeholder_assignments` in `get_connection`**

In `api/database.py`, find the `get_connection` context manager (around line 215). Add the call after `await _migrate_campaigns(conn)`:

```python
        await _migrate_campaigns(conn)
        await _migrate_stakeholder_assignments(conn)
        yield conn
```

- [ ] **Step 3: Add `fetch_stakeholder_assignments` and `replace_stakeholder_assignments` helpers**

Add these two functions at the end of `api/database.py` (after the last existing function):

```python
async def fetch_stakeholder_assignments(
    conn: aiosqlite.Connection, *, orchestration_run_id: int
) -> list[dict]:
    """Return all assignments for an orchestration run, ordered by id."""
    async with conn.execute(
        "SELECT * FROM stakeholder_assignments WHERE orchestration_run_id=? ORDER BY id",
        (orchestration_run_id,),
    ) as cur:
        return [dict(r) async for r in cur]


async def replace_stakeholder_assignments(
    conn: aiosqlite.Connection,
    *,
    orchestration_run_id: int,
    assignments: list[dict],
) -> int:
    """Replace all assignments for this run. Returns count saved."""
    await conn.execute(
        "DELETE FROM stakeholder_assignments WHERE orchestration_run_id=?",
        (orchestration_run_id,),
    )
    for a in assignments:
        await conn.execute(
            "INSERT INTO stakeholder_assignments "
            "(orchestration_run_id, stakeholder_id, level, node_label) VALUES (?,?,?,?)",
            (orchestration_run_id, a["stakeholder_id"], a["level"], a["node_label"]),
        )
    await conn.commit()
    return len(assignments)
```

- [ ] **Step 4: Write a failing test**

In `tests/test_stakeholders_api.py`, add at the bottom (or in a separate test file — use `tests/test_stakeholders_api.py` since it already has the same DB/project setup):

Actually, add to a new file `tests/test_assignment_api.py` — Step 4 is just the migration test. Add:

```python
# tests/test_assignment_api.py
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, insert_project, fetch_project, insert_orchestration_run

SLUG = "assignment-test"
PROJECT = {"client_slug": SLUG, "llm_mode": "standard", "sector": "rail"}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_migration_creates_stakeholder_assignments_table(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stakeholder_assignments'"
        ) as cur:
            row = await cur.fetchone()
    assert row is not None
```

- [ ] **Step 5: Run the test to verify it fails**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest tests/test_assignment_api.py::test_migration_creates_stakeholder_assignments_table -v
```

Expected: FAIL (table doesn't exist yet)

- [ ] **Step 6: Run the test again after implementing — it should pass**

```bash
pytest tests/test_assignment_api.py::test_migration_creates_stakeholder_assignments_table -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add api/database.py tests/test_assignment_api.py
git commit -m "feat: add stakeholder_assignments table migration and DB helpers"
```

---

## Task 2: Discovery mapping crew + value chain tree step

**Files:**
- Create: `agents/crews/discovery_mapping_crew.py`
- Modify: `agents/discovery/value_chain_mapper.py`
- Modify: `api/services/run_service.py`
- Modify: `api/services/project_service.py`

### Background

`SQLiteStateTool._run` writes `value` (a JSON string) to `{projects_dir}/{slug}/outputs/{key}.json`. So writing `key='value_chain_tree'` creates `outputs/value_chain_tree.json`. The project_service pattern for reading output files is: check if project exists, then check if file exists, return `[]` if not.

- [ ] **Step 1: Create `agents/crews/discovery_mapping_crew.py`**

```python
# agents/crews/discovery_mapping_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_crew_llm
from agents.tools.registry import get_tools_for_agent
from agents.discovery.value_chain_mapper import (
    create_value_chain_mapper,
    create_value_chain_mapper_task,
)


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
) -> Crew:
    """Single-agent crew: runs Value Chain Mapper only.

    Args:
        slug: Project slug.
        run_id: crew_runs.id for this execution.
        llm_mode: LLM routing mode.
        sector: Client sector for ChromaDB sector queries.
        llm: Optional LLM override (used in tests).
        hitl_tool: Optional HumanInputTool override (used in tests).
        discovery_brief: Free-text research brief from project settings.
        discovery_links: List of {"url": str, "label": str} dicts.
        priority_doc_names: Original filenames of prioritised documents.
    """
    if llm is None:
        llm = get_crew_llm(llm_mode)

    vcm = create_value_chain_mapper(
        slug=slug,
        llm=llm,
        tools=get_tools_for_agent(
            "value_chain_mapper",
            slug=slug,
            run_id=run_id,
            sector=sector,
            hitl_tool=hitl_tool,
        ),
    )
    vcm_task = create_value_chain_mapper_task(
        agent=vcm,
        discovery_brief=discovery_brief,
        discovery_links=discovery_links,
        priority_doc_names=priority_doc_names,
    )

    return Crew(
        agents=[vcm],
        tasks=[vcm_task],
        process=Process.sequential,
        verbose=True,
    )
```

- [ ] **Step 2: Add `value_chain_tree` save step to the mapper task**

In `agents/discovery/value_chain_mapper.py`, find `create_value_chain_mapper_task`. The task description currently ends with step 9 (revision loop). Add step 10 after step 9:

The full updated task description string (replace the `description=` argument):

```python
    return Task(
        description=(
            f"{context_preamble}"
            "Analyse the client documents and sector context to map the organisation's value chain.\n\n"
            "Steps:\n"
            "1. Use DocumentIngestionTool with filename=None to ingest all client documents.\n"
            "2. Use ChromaQueryTool with collection='project' to understand the client's operations.\n"
            "3. Use TavilySearchTool to research the sector's typical value chain structure.\n"
            "4. Use ChromaQueryTool with collection='sector' for additional sector benchmarks.\n"
            "5. Produce a Mermaid diagram showing primary activities (left to right: Inbound Logistics, "
            "Operations, Outbound Logistics, Marketing & Sales, Service) and support activities, "
            "labelled with client-specific process names where known.\n"
            "6. Use MermaidRenderTool to save the diagram with filename='value_chain'.\n"
            "7. Use SQLiteStateTool with operation='write', key='value_chain_summary', "
            "agent_name='value_chain_mapper' to save a brief JSON summary: "
            "{\"activities\": [list of key activities identified], \"sector\": \"...\"}.\n"
            "8. Use HumanInputTool with prompt: 'Please review the value chain diagram saved at "
            "outputs/value_chain.md. Reply \"approved\" to proceed, or provide revision notes.'\n"
            "9. If revision notes are received (response is not 'approved'), revise the diagram "
            "and call HumanInputTool again. Repeat at most 3 times total.\n"
            "10. Once the diagram is approved, use SQLiteStateTool with operation='write', "
            "key='value_chain_tree', agent_name='value_chain_mapper' to save the value chain as a "
            "structured JSON tree. The format must be a JSON array where each element is an L1 node:\n"
            "[\n"
            "  {\n"
            "    \"label\": \"Inbound Logistics\",\n"
            "    \"level\": \"L1\",\n"
            "    \"children\": [\n"
            "      {\n"
            "        \"label\": \"Materials Receipt\",\n"
            "        \"level\": \"L2\",\n"
            "        \"children\": [\n"
            "          {\"label\": \"Goods-in Inspection\", \"level\": \"L3\"}\n"
            "        ]\n"
            "      }\n"
            "    ]\n"
            "  }\n"
            "]\n"
            "Use client-specific labels. L1 = primary activity/value stream, "
            "L2 = stage within that stream, L3 = specific activity. "
            "Children arrays are optional — include them only where sub-stages are known.\n"
        ),
        expected_output=(
            "A Mermaid value chain diagram saved to outputs/value_chain.md, "
            "a JSON summary saved via SQLiteStateTool, "
            "a structured JSON tree saved to key='value_chain_tree', "
            "and confirmation that the diagram has been approved by a human reviewer."
        ),
        agent=agent,
    )
```

- [ ] **Step 3: Add `get_value_chain_tree` to `project_service.py`**

In `api/services/project_service.py`, add after `get_portfolio_register` (or at the end of the file):

```python
async def get_value_chain_tree(slug: str) -> list | None:
    """Return the value chain tree JSON for the assignment page.

    Returns:
        None  — project DB does not exist (unknown project)
        []    — project exists but value_chain_tree.json not yet on disk
        list  — parsed JSON array from outputs/value_chain_tree.json
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
    settings = get_settings()
    path = Path(settings.projects_dir) / slug / "outputs" / "value_chain_tree.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
```

- [ ] **Step 4: Add `discovery_mapping` branch to `run_service.py`**

In `api/services/run_service.py`, find the `if crew_name == "discovery":` block and add the `discovery_mapping` branch immediately before it:

```python
    if crew_name == "discovery_mapping":
        from agents.crews.discovery_mapping_crew import create_discovery_mapping_crew

        discovery_brief = config.get("discovery_brief", "")
        discovery_links = config.get("discovery_links", [])
        discovery_document_ids = config.get("discovery_document_ids", [])

        priority_doc_names: list[str] = []
        if discovery_document_ids:
            async with get_connection(slug) as conn:
                project_row = await fetch_project(conn, slug=slug)
                if project_row:
                    all_docs = await fetch_documents(conn, project_id=project_row["id"])
                    doc_map = {d["id"]: d["original_name"] for d in all_docs}
                    priority_doc_names = [
                        doc_map[doc_id]
                        for doc_id in discovery_document_ids
                        if doc_id in doc_map
                    ]

        crew = create_discovery_mapping_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            discovery_brief=discovery_brief,
            discovery_links=discovery_links,
            priority_doc_names=priority_doc_names,
        )

    elif crew_name == "discovery":
```

Note: change `if crew_name == "discovery":` → `elif crew_name == "discovery":` since we added the new block before it.

- [ ] **Step 5: Write a test for the discovery_mapping crew factory**

In `tests/test_discovery_crew.py`, add these tests at the bottom:

```python
from unittest.mock import MagicMock, patch
from crewai import LLM, Process


def test_discovery_mapping_crew_has_one_agent():
    from agents.crews.discovery_mapping_crew import create_discovery_mapping_crew
    mock_llm = MagicMock(spec=LLM)
    with patch("agents.crews.discovery_mapping_crew.get_tools_for_agent", return_value=[]):
        crew = create_discovery_mapping_crew(
            slug="test", run_id=1, llm_mode="standard", sector="rail", llm=mock_llm
        )
    assert len(crew.agents) == 1


def test_discovery_mapping_crew_has_one_task():
    from agents.crews.discovery_mapping_crew import create_discovery_mapping_crew
    mock_llm = MagicMock(spec=LLM)
    with patch("agents.crews.discovery_mapping_crew.get_tools_for_agent", return_value=[]):
        crew = create_discovery_mapping_crew(
            slug="test", run_id=1, llm_mode="standard", sector="rail", llm=mock_llm
        )
    assert len(crew.tasks) == 1


def test_discovery_mapping_crew_task_mentions_value_chain_tree():
    from agents.crews.discovery_mapping_crew import create_discovery_mapping_crew
    mock_llm = MagicMock(spec=LLM)
    with patch("agents.crews.discovery_mapping_crew.get_tools_for_agent", return_value=[]):
        crew = create_discovery_mapping_crew(
            slug="test", run_id=1, llm_mode="standard", sector="rail", llm=mock_llm
        )
    assert "value_chain_tree" in crew.tasks[0].description
```

- [ ] **Step 6: Run the tests**

```bash
pytest tests/test_discovery_crew.py -v -k "mapping"
```

Expected: 3 tests PASS

- [ ] **Step 7: Commit**

```bash
git add agents/crews/discovery_mapping_crew.py \
        agents/discovery/value_chain_mapper.py \
        api/services/run_service.py \
        api/services/project_service.py \
        tests/test_discovery_crew.py
git commit -m "feat: add discovery_mapping crew and value_chain_tree save step"
```

---

## Task 3: PAM crew split + orchestration service refactor

**Files:**
- Modify: `agents/pam/pam_agent.py`
- Modify: `agents/crews/pam_crew.py`
- Modify: `api/services/orchestration_service.py`
- Modify: `tests/test_pam_crew.py`
- Modify: `tests/test_orchestration_service.py`

### Background

`pam_crew.py` currently has `create_pam_crew` which builds a 5-task sequential crew. We replace this with two factories. `orchestration_service.py` currently has `start_orchestration` and `run_pam_crew`. We replace `run_pam_crew` with `run_pam_phase1`, `run_pam_phase2`, and `resume_orchestration`.

`test_pam_crew.py` has 5 tests all referencing `create_pam_crew` — all must be updated. `test_orchestration_service.py` patches `run_pam_crew` and `create_pam_crew` — these patches must be updated to target the new names.

- [ ] **Step 1: Add `create_run_discovery_mapping_task` to `pam_agent.py`**

In `agents/pam/pam_agent.py`, add after the imports and before `create_pam_agent`:

```python
def create_run_discovery_mapping_task(agent: Agent, slug: str) -> Task:
    return Task(
        description=(
            f"Use RunCrewTool with crew_name='discovery_mapping' to run the Discovery Mapping crew "
            f"for project '{slug}'. Wait for it to complete. "
            f"Then use SlackNotifyTool to send: "
            f"'✓ Value chain mapping complete for {slug}. Awaiting stakeholder assignment.'"
        ),
        expected_output="Confirmation that discovery_mapping crew completed and Slack notified.",
        agent=agent,
    )
```

- [ ] **Step 2: Rewrite `pam_crew.py`**

Replace the entire content of `agents/crews/pam_crew.py` with:

```python
# agents/crews/pam_crew.py
"""PAM orchestration crews — Phase 1 (mapping) and Phase 2 (resume pipeline)."""
from crewai import Crew, Process, LLM
from agents.llm import get_pam_llm
from agents.tools.registry import get_tools_for_agent
from agents.pam.pam_agent import (
    create_pam_agent,
    create_run_discovery_mapping_task,
    create_run_value_design_task,
    create_run_architecture_task,
    create_run_delivery_task,
    create_run_business_plan_task,
)


def create_pam_mapping_crew(
    slug: str,
    orchestration_run_id: int,
    llm_mode: str,
    llm: LLM | None = None,
) -> Crew:
    """Phase 1 PAM crew: runs discovery_mapping only.

    On completion the orchestration service sets status to 'awaiting_assignment'.
    """
    if llm is None:
        llm = get_pam_llm()

    tools = get_tools_for_agent("pam", slug=slug, run_id=orchestration_run_id)
    pam = create_pam_agent(slug=slug, llm=llm, tools=tools)
    t1 = create_run_discovery_mapping_task(agent=pam, slug=slug)

    return Crew(
        agents=[pam],
        tasks=[t1],
        process=Process.sequential,
        verbose=True,
    )


def create_pam_resume_crew(
    slug: str,
    orchestration_run_id: int,
    llm_mode: str,
    llm: LLM | None = None,
) -> Crew:
    """Phase 2 PAM crew: value_design → architecture → delivery → business_plan.

    SP10d will prepend a discovery_interviews task here.
    """
    if llm is None:
        llm = get_pam_llm()

    tools = get_tools_for_agent("pam", slug=slug, run_id=orchestration_run_id)
    pam = create_pam_agent(slug=slug, llm=llm, tools=tools)

    t1 = create_run_value_design_task(agent=pam, slug=slug, context_tasks=[])
    t2 = create_run_architecture_task(agent=pam, slug=slug, context_tasks=[t1])
    t3 = create_run_delivery_task(agent=pam, slug=slug, context_tasks=[t2])
    t4 = create_run_business_plan_task(agent=pam, slug=slug, context_tasks=[t3])

    return Crew(
        agents=[pam],
        tasks=[t1, t2, t3, t4],
        process=Process.sequential,
        verbose=True,
    )
```

- [ ] **Step 3: Update `test_pam_crew.py`**

Replace the entire content of `tests/test_pam_crew.py` with:

```python
# tests/test_pam_crew.py
"""Unit tests for the PAM orchestration crews."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM, Process


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


def _build_mapping_crew(mock_llm):
    with patch("agents.crews.pam_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.pam_crew import create_pam_mapping_crew
        return create_pam_mapping_crew(
            slug="test",
            orchestration_run_id=1,
            llm_mode="standard",
            llm=mock_llm,
        )


def _build_resume_crew(mock_llm):
    with patch("agents.crews.pam_crew.get_tools_for_agent", return_value=[]):
        from agents.crews.pam_crew import create_pam_resume_crew
        return create_pam_resume_crew(
            slug="test",
            orchestration_run_id=1,
            llm_mode="standard",
            llm=mock_llm,
        )


# ── mapping crew ──────────────────────────────────────────────────────────────

def test_pam_mapping_crew_has_one_agent(mock_llm):
    crew = _build_mapping_crew(mock_llm)
    assert len(crew.agents) == 1


def test_pam_mapping_crew_has_one_task(mock_llm):
    crew = _build_mapping_crew(mock_llm)
    assert len(crew.tasks) == 1


def test_pam_mapping_crew_task_references_discovery_mapping(mock_llm):
    crew = _build_mapping_crew(mock_llm)
    assert "discovery_mapping" in crew.tasks[0].description


def test_pam_mapping_crew_sequential_process(mock_llm):
    crew = _build_mapping_crew(mock_llm)
    assert crew.process == Process.sequential


# ── resume crew ───────────────────────────────────────────────────────────────

def test_pam_resume_crew_has_one_agent(mock_llm):
    crew = _build_resume_crew(mock_llm)
    assert len(crew.agents) == 1


def test_pam_resume_crew_has_four_tasks(mock_llm):
    crew = _build_resume_crew(mock_llm)
    assert len(crew.tasks) == 4


def test_pam_resume_crew_tasks_reference_all_four_crews(mock_llm):
    crew = _build_resume_crew(mock_llm)
    all_descriptions = " ".join(t.description for t in crew.tasks)
    for name in ("value_design", "architecture", "delivery", "business_plan"):
        assert name in all_descriptions, f"'{name}' missing from task descriptions"


def test_pam_resume_crew_sequential_process(mock_llm):
    crew = _build_resume_crew(mock_llm)
    assert crew.process == Process.sequential


def test_pam_crews_use_registry(mock_llm):
    """get_tools_for_agent is called with 'pam' for both crews."""
    with patch("agents.crews.pam_crew.get_tools_for_agent", return_value=[]) as mock_reg:
        from agents.crews.pam_crew import create_pam_mapping_crew
        create_pam_mapping_crew(slug="myslug", orchestration_run_id=77, llm_mode="standard", llm=mock_llm)
    call = mock_reg.call_args_list[0]
    assert call.args[0] == "pam"
    assert call.kwargs.get("slug") == "myslug"
    assert call.kwargs.get("run_id") == 77
```

- [ ] **Step 4: Run the PAM crew tests to verify they pass**

```bash
pytest tests/test_pam_crew.py -v
```

Expected: 9 tests PASS

- [ ] **Step 5: Rewrite `orchestration_service.py`**

Replace the entire content of `api/services/orchestration_service.py` with:

```python
# api/services/orchestration_service.py
"""Start and track full-pipeline PAM orchestration runs (two-phase)."""
import asyncio
import logging
from pathlib import Path
from api.config import get_settings, load_project_config

_log = logging.getLogger(__name__)
from api.database import (
    get_connection,
    fetch_project,
    insert_orchestration_run,
    update_orchestration_run_status,
)


async def start_orchestration(slug: str) -> int:
    """Insert an orchestration_run record and fire PAM Phase 1 as a background task.

    Returns the new orchestration_run_id.
    Raises ValueError if the project does not exist.
    """
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise ValueError(f"Project '{slug}' not found")
        orchestration_run_id = await insert_orchestration_run(conn, project_id=project["id"])

    asyncio.create_task(run_pam_phase1(slug, orchestration_run_id))
    return orchestration_run_id


async def run_pam_phase1(slug: str, orchestration_run_id: int) -> None:
    """Run the mapping phase (discovery_mapping crew). On success set status to awaiting_assignment."""
    try:
        settings = get_settings()
        config = load_project_config(Path(settings.projects_dir) / slug)
        from agents.crews.pam_crew import create_pam_mapping_crew
        crew = create_pam_mapping_crew(
            slug=slug,
            orchestration_run_id=orchestration_run_id,
            llm_mode=config.get("llm_mode", "standard"),
        )
        await crew.kickoff_async()
        async with get_connection(slug) as conn:
            await update_orchestration_run_status(
                conn, run_id=orchestration_run_id, status="awaiting_assignment"
            )
    except Exception:
        _log.exception(
            "PAM phase1 failed for slug=%s orchestration_run_id=%d",
            slug,
            orchestration_run_id,
        )
        async with get_connection(slug) as conn:
            await update_orchestration_run_status(
                conn, run_id=orchestration_run_id, status="failed"
            )


async def resume_orchestration(slug: str, orchestration_run_id: int) -> None:
    """Set status to running and fire PAM Phase 2 (triggered by assignment confirmation)."""
    async with get_connection(slug) as conn:
        await update_orchestration_run_status(
            conn, run_id=orchestration_run_id, status="running"
        )
    asyncio.create_task(run_pam_phase2(slug, orchestration_run_id))


async def run_pam_phase2(slug: str, orchestration_run_id: int) -> None:
    """Run the resume phase (value_design → business_plan). On success set status to completed."""
    try:
        settings = get_settings()
        config = load_project_config(Path(settings.projects_dir) / slug)
        from agents.crews.pam_crew import create_pam_resume_crew
        crew = create_pam_resume_crew(
            slug=slug,
            orchestration_run_id=orchestration_run_id,
            llm_mode=config.get("llm_mode", "standard"),
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

- [ ] **Step 6: Update `test_orchestration_service.py`**

Replace the entire content of `tests/test_orchestration_service.py` with:

```python
# tests/test_orchestration_service.py
"""Unit tests for orchestration service and /orchestrate endpoint."""
import pytest
from unittest.mock import patch, AsyncMock


PROJECT_PAYLOAD = {
    "client_slug": "orch-api-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Ops"],
    "value_stream_labels": ["Ops"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.mark.asyncio
async def test_start_orchestration_creates_db_record():
    """start_orchestration inserts a row in orchestration_runs and returns an integer id."""
    with patch("api.services.orchestration_service.run_pam_phase1", new_callable=AsyncMock):
        with patch("asyncio.create_task"):
            from api.database import get_connection, insert_project
            async with get_connection("orch-svc-test") as conn:
                await insert_project(
                    conn, slug="orch-svc-test",
                    llm_mode="standard", sector="rail", config_json="{}"
                )
            from api.services.orchestration_service import start_orchestration
            run_id = await start_orchestration("orch-svc-test")

    assert isinstance(run_id, int)
    assert run_id > 0


@pytest.mark.asyncio
async def test_start_orchestration_returns_run_id():
    """The returned int is the primary key of the new orchestration_runs row."""
    with patch("asyncio.create_task"):
        with patch("api.services.orchestration_service.run_pam_phase1", new_callable=AsyncMock):
            from api.database import get_connection, insert_project, fetch_orchestration_run
            async with get_connection("orch-return-test") as conn:
                await insert_project(
                    conn, slug="orch-return-test",
                    llm_mode="standard", sector="rail", config_json="{}"
                )
            from api.services.orchestration_service import start_orchestration
            run_id = await start_orchestration("orch-return-test")

    async with get_connection("orch-return-test") as conn:
        row = await fetch_orchestration_run(conn, run_id=run_id)

    assert row is not None
    assert row["id"] == run_id
    assert row["status"] == "running"


@pytest.mark.asyncio
async def test_start_orchestration_fires_background_task():
    """start_orchestration calls asyncio.create_task."""
    with patch("asyncio.create_task") as mock_task, \
         patch("api.services.orchestration_service.run_pam_phase1", new_callable=AsyncMock):
        from api.database import get_connection, insert_project
        async with get_connection("orch-bg-test") as conn:
            await insert_project(
                conn, slug="orch-bg-test",
                llm_mode="standard", sector="rail", config_json="{}"
            )
        from api.services.orchestration_service import start_orchestration
        await start_orchestration("orch-bg-test")

    mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_run_pam_phase1_sets_awaiting_assignment_on_success():
    """run_pam_phase1 sets status to 'awaiting_assignment' when crew succeeds."""
    from api.database import get_connection, insert_project, fetch_orchestration_run, insert_orchestration_run, fetch_project

    async with get_connection("orch-phase1-test") as conn:
        await insert_project(
            conn, slug="orch-phase1-test",
            llm_mode="standard", sector="rail", config_json="{}"
        )
        project = await fetch_project(conn, slug="orch-phase1-test")
        run_id = await insert_orchestration_run(conn, project_id=project["id"])

    mock_crew = AsyncMock()
    mock_crew.kickoff_async = AsyncMock(return_value=None)

    import agents.crews.pam_crew
    with patch("agents.crews.pam_crew.create_pam_mapping_crew", return_value=mock_crew):
        from api.services.orchestration_service import run_pam_phase1
        await run_pam_phase1("orch-phase1-test", run_id)

    async with get_connection("orch-phase1-test") as conn:
        row = await fetch_orchestration_run(conn, run_id=run_id)

    assert row["status"] == "awaiting_assignment"


@pytest.mark.asyncio
async def test_run_pam_phase1_sets_failed_on_exception():
    """run_pam_phase1 updates status to 'failed' when the crew raises."""
    from api.database import get_connection, insert_project, fetch_orchestration_run, insert_orchestration_run, fetch_project

    async with get_connection("orch-fail-test") as conn:
        await insert_project(
            conn, slug="orch-fail-test",
            llm_mode="standard", sector="rail", config_json="{}"
        )
        project = await fetch_project(conn, slug="orch-fail-test")
        run_id = await insert_orchestration_run(conn, project_id=project["id"])

    import agents.crews.pam_crew
    with patch("agents.crews.pam_crew.create_pam_mapping_crew", side_effect=RuntimeError("boom")):
        from api.services.orchestration_service import run_pam_phase1
        await run_pam_phase1("orch-fail-test", run_id)

    async with get_connection("orch-fail-test") as conn:
        row = await fetch_orchestration_run(conn, run_id=run_id)

    assert row["status"] == "failed"


@pytest.mark.asyncio
async def test_run_pam_phase2_sets_completed_on_success():
    """run_pam_phase2 sets status to 'completed' when resume crew succeeds."""
    from api.database import get_connection, insert_project, fetch_orchestration_run, insert_orchestration_run, fetch_project

    async with get_connection("orch-phase2-test") as conn:
        await insert_project(
            conn, slug="orch-phase2-test",
            llm_mode="standard", sector="rail", config_json="{}"
        )
        project = await fetch_project(conn, slug="orch-phase2-test")
        run_id = await insert_orchestration_run(conn, project_id=project["id"])

    mock_crew = AsyncMock()
    mock_crew.kickoff_async = AsyncMock(return_value=None)

    import agents.crews.pam_crew
    with patch("agents.crews.pam_crew.create_pam_resume_crew", return_value=mock_crew):
        from api.services.orchestration_service import run_pam_phase2
        await run_pam_phase2("orch-phase2-test", run_id)

    async with get_connection("orch-phase2-test") as conn:
        row = await fetch_orchestration_run(conn, run_id=run_id)

    assert row["status"] == "completed"


# ── /orchestrate endpoint ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrate_endpoint_returns_202(client):
    await client.post("/projects", json=PROJECT_PAYLOAD)
    with patch("api.routers.orchestrate.start_orchestration", new_callable=AsyncMock, return_value=5):
        resp = await client.post("/projects/orch-api-test/orchestrate")
    assert resp.status_code == 202
    data = resp.json()
    assert data["orchestration_run_id"] == 5
    assert data["status"] == "running"


@pytest.mark.asyncio
async def test_orchestrate_endpoint_returns_404_for_unknown_project(client):
    resp = await client.post("/projects/nonexistent/orchestrate")
    assert resp.status_code == 404
```

- [ ] **Step 7: Run the orchestration tests**

```bash
pytest tests/test_orchestration_service.py tests/test_pam_crew.py -v
```

Expected: all tests PASS

- [ ] **Step 8: Commit**

```bash
git add agents/pam/pam_agent.py \
        agents/crews/pam_crew.py \
        api/services/orchestration_service.py \
        tests/test_pam_crew.py \
        tests/test_orchestration_service.py
git commit -m "feat: split PAM crew into mapping + resume phases with awaiting_assignment gate"
```

---

## Task 4: Assignment API router + tests

**Files:**
- Create: `api/routers/assignment.py`
- Modify: `api/main.py`
- Modify: `tests/test_assignment_api.py` (extend the file started in Task 1)

### Background

Three endpoints:
- `GET /projects/{slug}/assignment/{orchestration_run_id}` — returns tree + assignments + stakeholders
- `POST /projects/{slug}/assignment/{orchestration_run_id}` — saves/replaces assignments
- `PATCH /projects/{slug}/orchestration-runs/{orchestration_run_id}/advance` — triggers Phase 2

The `resume_orchestration` function calls `asyncio.create_task` internally; in tests we patch it.

- [ ] **Step 1: Create `api/routers/assignment.py`**

```python
# api/routers/assignment.py
"""Assignment endpoints: GET/POST assignment data, PATCH advance orchestration."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from api.database import (
    get_connection,
    fetch_project,
    fetch_stakeholder_assignments,
    replace_stakeholder_assignments,
    fetch_stakeholders,
    fetch_orchestration_run,
)
from api.services.project_service import get_value_chain_tree
from api.services.orchestration_service import resume_orchestration

router = APIRouter(tags=["assignment"])


class AssignmentItem(BaseModel):
    stakeholder_id: int
    level: str
    node_label: str


@router.get("/projects/{slug}/assignment/{orchestration_run_id}")
async def get_assignment(slug: str, orchestration_run_id: int):
    """Return value chain tree, current assignments, and stakeholder list."""
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        assignments = await fetch_stakeholder_assignments(
            conn, orchestration_run_id=orchestration_run_id
        )
        stakeholders = await fetch_stakeholders(conn, project_id=project["id"])

    value_chain_tree = await get_value_chain_tree(slug)

    return {
        "value_chain_tree": value_chain_tree or [],
        "assignments": [dict(a) for a in assignments],
        "stakeholders": [dict(s) for s in stakeholders],
    }


@router.post("/projects/{slug}/assignment/{orchestration_run_id}")
async def save_assignment(slug: str, orchestration_run_id: int, items: list[AssignmentItem]):
    """Replace all stakeholder assignments for an orchestration run."""
    if not items:
        raise HTTPException(status_code=422, detail="At least one assignment is required")
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        count = await replace_stakeholder_assignments(
            conn,
            orchestration_run_id=orchestration_run_id,
            assignments=[a.model_dump() for a in items],
        )
    return {"saved": count}


@router.patch("/projects/{slug}/orchestration-runs/{orchestration_run_id}/advance")
async def advance_orchestration(slug: str, orchestration_run_id: int):
    """Advance an awaiting_assignment run to Phase 2 (triggers resume_orchestration)."""
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        run = await fetch_orchestration_run(conn, run_id=orchestration_run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Orchestration run not found")
        if run["status"] != "awaiting_assignment":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot advance: run status is '{run['status']}', expected 'awaiting_assignment'",
            )
    await resume_orchestration(slug, orchestration_run_id)
    return {"status": "running"}
```

- [ ] **Step 2: Register the router in `api/main.py`**

Add the import:
```python
from api.routers import assignment as assignment_router
```

Add the include (after `campaigns_router`):
```python
app.include_router(assignment_router.router)
```

- [ ] **Step 3: Write the remaining tests in `tests/test_assignment_api.py`**

Append to `tests/test_assignment_api.py`:

```python
from api.database import (
    insert_stakeholder,
    insert_orchestration_run,
    update_orchestration_run_status,
)
from unittest.mock import patch, AsyncMock

STAKEHOLDER = {
    "name": "Jane Smith",
    "job_title": "CFO",
    "organisation": "Acme",
    "email": "jane@acme.com",
    "slack_handle": "@jane",
    "stakeholder_groups": ["Finance"],
    "project_role": "governing",
    "value_streams": ["Billing"],
    "value_chain_stage": "Billing",
    "activity": "Invoicing",
    "disposition": "champion",
    "location": "UK",
    "country_code": "GB",
    "timezone": "Europe/London",
    "preferred_language": "English",
    "currency": "GBP",
}


@pytest.mark.asyncio
async def test_get_assignment_returns_empty_tree_when_no_file(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])

    resp = await client.get(f"/projects/{SLUG}/assignment/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["value_chain_tree"] == []
    assert data["assignments"] == []


@pytest.mark.asyncio
async def test_get_assignment_returns_404_for_unknown_project(client):
    resp = await client.get("/projects/unknown-proj/assignment/1")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_assignment_saves_and_returns_count(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        sh_id = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)

    payload = [{"stakeholder_id": sh_id, "level": "L2", "node_label": "Billing"}]
    resp = await client.post(f"/projects/{SLUG}/assignment/{run_id}", json=payload)
    assert resp.status_code == 200
    assert resp.json()["saved"] == 1


@pytest.mark.asyncio
async def test_post_assignment_replaces_existing(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        sh_id = await insert_stakeholder(conn, project_id=project["id"], **STAKEHOLDER)

    # First save
    await client.post(
        f"/projects/{SLUG}/assignment/{run_id}",
        json=[{"stakeholder_id": sh_id, "level": "L1", "node_label": "Operations"}],
    )
    # Replace with different assignment
    resp = await client.post(
        f"/projects/{SLUG}/assignment/{run_id}",
        json=[{"stakeholder_id": sh_id, "level": "L2", "node_label": "Billing"}],
    )
    assert resp.json()["saved"] == 1

    # Verify only 1 row remains
    resp2 = await client.get(f"/projects/{SLUG}/assignment/{run_id}")
    assert len(resp2.json()["assignments"]) == 1
    assert resp2.json()["assignments"][0]["node_label"] == "Billing"


@pytest.mark.asyncio
async def test_post_assignment_422_for_empty_body(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])

    resp = await client.post(f"/projects/{SLUG}/assignment/{run_id}", json=[])
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_advance_orchestration_succeeds_from_awaiting_assignment(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        await update_orchestration_run_status(conn, run_id=run_id, status="awaiting_assignment")

    with patch("api.routers.assignment.resume_orchestration", new_callable=AsyncMock):
        resp = await client.patch(f"/projects/{SLUG}/orchestration-runs/{run_id}/advance")

    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


@pytest.mark.asyncio
async def test_advance_orchestration_400_if_not_awaiting(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_orchestration_run(conn, project_id=project["id"])
        # status is 'running' by default

    with patch("api.routers.assignment.resume_orchestration", new_callable=AsyncMock):
        resp = await client.patch(f"/projects/{SLUG}/orchestration-runs/{run_id}/advance")

    assert resp.status_code == 400
```

- [ ] **Step 4: Run all assignment API tests**

```bash
pytest tests/test_assignment_api.py -v
```

Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/routers/assignment.py api/main.py tests/test_assignment_api.py
git commit -m "feat: add assignment endpoints (GET/POST/PATCH advance)"
```

---

## Task 5: Frontend types + API layer

**Files:**
- Modify: `ui/src/types.ts`
- Modify: `ui/src/api/endpoints.ts`

### Background

`types.ts` already imports are fine — add the new interfaces at the end. `endpoints.ts` has `projectsApi` object — add the three new methods there.

- [ ] **Step 1: Add new types to `ui/src/types.ts`**

Append to the end of `ui/src/types.ts`:

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

- [ ] **Step 2: Add the import for `AssignmentData` in `endpoints.ts`**

In `ui/src/api/endpoints.ts`, update the import from `'../types'` to include `AssignmentData` and `StakeholderAssignment`:

```ts
import type {
  Project,
  ProjectStatus,
  AgentOutput,
  ClientDocument,
  ProjectSettings,
  OutputContent,
  TokenResponse,
  RoadmapData,
  FinancialSummary,
  HumanReview,
  OrchestrationRunHistory,
  Stakeholder,
  StakeholderImportResult,
  PortfolioItem,
  AssignmentData,
  StakeholderAssignment,
} from '../types'
```

- [ ] **Step 3: Add the 3 assignment API methods to `projectsApi`**

In `ui/src/api/endpoints.ts`, add these methods to the `projectsApi` object (after `listRuns`):

```ts
  getAssignment: (slug: string, orchestrationRunId: number): Promise<AssignmentData> =>
    apiClient
      .get<AssignmentData>(`/projects/${slug}/assignment/${orchestrationRunId}`)
      .then((r) => r.data),

  saveAssignment: (
    slug: string,
    orchestrationRunId: number,
    items: StakeholderAssignment[],
  ): Promise<{ saved: number }> =>
    apiClient
      .post<{ saved: number }>(`/projects/${slug}/assignment/${orchestrationRunId}`, items)
      .then((r) => r.data),

  advanceOrchestrationRun: (
    slug: string,
    orchestrationRunId: number,
  ): Promise<{ status: string }> =>
    apiClient
      .patch<{ status: string }>(`/projects/${slug}/orchestration-runs/${orchestrationRunId}/advance`)
      .then((r) => r.data),
```

- [ ] **Step 4: Type-check the frontend**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npx tsc --noEmit
```

Expected: 0 errors

- [ ] **Step 5: Commit**

```bash
git add ui/src/types.ts ui/src/api/endpoints.ts
git commit -m "feat: add ValueChainNode, StakeholderAssignment, AssignmentData types and API methods"
```

---

## Task 6: Assignment page + route

**Files:**
- Create: `ui/src/pages/Assignment.tsx`
- Modify: `ui/src/router.tsx`

### Background

The Assignment page is accessed from the Runs page via a link — it is not in the nav sidebar. The route follows the same `/:slug/...` pattern used by all other pages.

The page has three pieces of state:
1. `selectedNode: string | null` — the node key (`"${level}:${label}"`) the user has clicked in the tree
2. `pending: StakeholderAssignment[]` — all assignments (loaded from API, edited locally, POSTed on confirm)
3. `search: string` — stakeholder search filter

On "Confirm" click: POST pending assignments → PATCH advance → navigate to `/:slug/runs`.

- [ ] **Step 1: Create `ui/src/pages/Assignment.tsx`**

```tsx
// ui/src/pages/Assignment.tsx
import { useState, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import type { ValueChainNode, StakeholderAssignment, Stakeholder } from '../types'

type NodeKey = string

function nk(level: string, label: string): NodeKey {
  return `${level}:${label}`
}

function TreeNode({
  node,
  depth,
  selected,
  onSelect,
  assignedCounts,
}: {
  node: ValueChainNode
  depth: number
  selected: NodeKey | null
  onSelect: (k: NodeKey) => void
  assignedCounts: Record<NodeKey, number>
}) {
  const [open, setOpen] = useState(true)
  const key = nk(node.level, node.label)
  const count = assignedCounts[key] ?? 0
  const isSelected = selected === key
  const hasChildren = (node.children?.length ?? 0) > 0

  return (
    <div>
      <button
        onClick={() => { onSelect(key); if (hasChildren) setOpen((o) => !o) }}
        className={`w-full text-left px-2 py-1.5 rounded text-sm flex items-center gap-2 transition-colors ${
          isSelected ? 'bg-teal-900/50 text-teal-200' : 'hover:bg-white/5 text-slate-300'
        } ${count === 0 ? 'border-l-2 border-amber-500' : 'border-l-2 border-transparent'}`}
        style={{ paddingLeft: `${8 + depth * 16}px` }}
      >
        <span className="w-3 text-slate-500 text-xs flex-shrink-0">
          {hasChildren ? (open ? '▼' : '▶') : ''}
        </span>
        <span className="flex-1 text-left truncate">{node.label}</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded-full flex-shrink-0 ${
            count === 0
              ? 'bg-amber-900/50 text-amber-400'
              : 'bg-teal-900/50 text-teal-400'
          }`}
        >
          {count}
        </span>
      </button>
      {open &&
        node.children?.map((child) => (
          <TreeNode
            key={nk(child.level, child.label)}
            node={child}
            depth={depth + 1}
            selected={selected}
            onSelect={onSelect}
            assignedCounts={assignedCounts}
          />
        ))}
    </div>
  )
}

export default function Assignment() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()

  // Find the latest awaiting_assignment run
  const { data: runs = [] } = useQuery({
    queryKey: ['runs', slug],
    queryFn: () => projectsApi.listRuns(slug!),
    enabled: !!slug,
  })

  const run = runs.find((r) => r.status === 'awaiting_assignment')
  const runId = run?.id

  const { data, isLoading } = useQuery({
    queryKey: ['assignment', slug, runId],
    queryFn: () => projectsApi.getAssignment(slug!, runId!),
    enabled: !!slug && !!runId,
  })

  const [selectedNode, setSelectedNode] = useState<NodeKey | null>(null)
  const [pending, setPending] = useState<StakeholderAssignment[]>([])
  const [search, setSearch] = useState('')

  // Initialise pending from loaded data
  const [initialised, setInitialised] = useState(false)
  if (data && !initialised) {
    setPending(data.assignments.map((a) => ({ stakeholder_id: a.stakeholder_id, level: a.level, node_label: a.node_label })))
    setInitialised(true)
  }

  const assignedCounts = useMemo(() => {
    const counts: Record<NodeKey, number> = {}
    pending.forEach((a) => {
      const key = nk(a.level, a.node_label)
      counts[key] = (counts[key] ?? 0) + 1
    })
    return counts
  }, [pending])

  const filteredStakeholders = useMemo(() => {
    if (!data) return []
    const q = search.toLowerCase()
    return data.stakeholders.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.job_title.toLowerCase().includes(q) ||
        s.organisation.toLowerCase().includes(q),
    )
  }, [data, search])

  function toggleAssignment(stakeholder: Stakeholder) {
    if (!selectedNode) return
    const [level, ...rest] = selectedNode.split(':')
    const node_label = rest.join(':')
    const exists = pending.some(
      (a) => a.stakeholder_id === stakeholder.id && a.level === level && a.node_label === node_label,
    )
    if (exists) {
      setPending((p) =>
        p.filter(
          (a) =>
            !(a.stakeholder_id === stakeholder.id && a.level === level && a.node_label === node_label),
        ),
      )
    } else {
      setPending((p) => [...p, { stakeholder_id: stakeholder.id, level, node_label }])
    }
  }

  function isAssignedToSelected(stakeholder: Stakeholder): boolean {
    if (!selectedNode) return false
    const [level, ...rest] = selectedNode.split(':')
    const node_label = rest.join(':')
    return pending.some(
      (a) => a.stakeholder_id === stakeholder.id && a.level === level && a.node_label === node_label,
    )
  }

  const saveMutation = useMutation({
    mutationFn: () => projectsApi.saveAssignment(slug!, runId!, pending),
  })
  const advanceMutation = useMutation({
    mutationFn: () => projectsApi.advanceOrchestrationRun(slug!, runId!),
  })

  async function handleConfirm() {
    await saveMutation.mutateAsync()
    await advanceMutation.mutateAsync()
    navigate(`/${slug}/runs`)
  }

  // Guard: redirect if no awaiting_assignment run
  if (!isLoading && !runId) {
    navigate(`/${slug}/runs`, { replace: true })
    return null
  }

  const totalNodes = countNodes(data?.value_chain_tree ?? [])
  const assignedNodes = Object.keys(assignedCounts).length
  const totalStakeholders = new Set(pending.map((a) => a.stakeholder_id)).size

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-100">Stakeholder Assignment</h2>
        <span className="text-sm text-slate-400">
          {assignedNodes} of {totalNodes} nodes assigned · {totalStakeholders} stakeholder
          {totalStakeholders !== 1 ? 's' : ''} assigned
        </span>
      </div>

      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}

      {!isLoading && data && (
        <>
          {data.value_chain_tree.length === 0 && (
            <p className="text-sm text-amber-400">
              Value chain data not yet available. The mapping crew must complete before assigning
              stakeholders.
            </p>
          )}

          <div className="flex gap-4 h-[calc(100vh-220px)]">
            {/* Left panel — value chain tree */}
            <div className="w-1/2 bg-surface-card rounded-xl overflow-y-auto p-3">
              <p className="text-xs text-slate-500 uppercase tracking-wide mb-2 px-2">
                Value Chain
              </p>
              {data.value_chain_tree.map((node) => (
                <TreeNode
                  key={nk(node.level, node.label)}
                  node={node}
                  depth={0}
                  selected={selectedNode}
                  onSelect={setSelectedNode}
                  assignedCounts={assignedCounts}
                />
              ))}
            </div>

            {/* Right panel — stakeholder roster */}
            <div className="w-1/2 bg-surface-card rounded-xl overflow-y-auto p-3 flex flex-col gap-3">
              <p className="text-xs text-slate-500 uppercase tracking-wide">
                Stakeholders
                {selectedNode && (
                  <span className="ml-2 text-teal-400 normal-case">
                    — assigning to: {selectedNode.split(':').slice(1).join(':')}
                  </span>
                )}
              </p>
              <input
                type="text"
                placeholder="Search name, title, org…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full bg-slate-800 text-slate-200 text-sm rounded-lg px-3 py-2 border border-slate-700 focus:outline-none focus:border-teal-500"
              />
              <div className="flex-1 overflow-y-auto space-y-1">
                {filteredStakeholders.map((s) => {
                  const assigned = isAssignedToSelected(s)
                  const totalAssignments = pending.filter((a) => a.stakeholder_id === s.id).length
                  return (
                    <button
                      key={s.id}
                      onClick={() => toggleAssignment(s)}
                      disabled={!selectedNode}
                      className={`w-full text-left px-3 py-2 rounded-lg text-sm flex items-center gap-3 transition-colors ${
                        assigned
                          ? 'bg-teal-900/40 text-teal-200'
                          : selectedNode
                          ? 'hover:bg-white/5 text-slate-300'
                          : 'text-slate-500 cursor-default'
                      }`}
                    >
                      <span className="w-4 text-teal-400">{assigned ? '✓' : ''}</span>
                      <span className="flex-1 truncate font-medium">{s.name}</span>
                      <span className="text-xs text-slate-500 truncate">
                        {s.job_title} · {s.organisation}
                      </span>
                      {totalAssignments > 0 && (
                        <span className="text-xs bg-teal-900/50 text-teal-400 px-1.5 py-0.5 rounded-full">
                          {totalAssignments}
                        </span>
                      )}
                    </button>
                  )
                })}
                {filteredStakeholders.length === 0 && (
                  <p className="text-sm text-slate-500 px-2">No stakeholders match.</p>
                )}
              </div>
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <button
              onClick={handleConfirm}
              disabled={pending.length === 0 || saveMutation.isPending || advanceMutation.isPending}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-teal-600 hover:bg-teal-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {saveMutation.isPending || advanceMutation.isPending
                ? 'Saving…'
                : 'Confirm Assignments & Begin Interviews'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function countNodes(tree: ValueChainNode[]): number {
  let count = 0
  for (const node of tree) {
    count += 1
    if (node.children) count += countNodes(node.children)
  }
  return count
}
```

- [ ] **Step 2: Add the assignment route to `router.tsx`**

In `ui/src/router.tsx`, add the import:

```tsx
import Assignment from './pages/Assignment'
```

Add the route inside the `children` array (after the `runs/:runId` route):

```tsx
{ path: ':slug/assignment', element: <Assignment /> },
```

- [ ] **Step 3: Type-check**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npx tsc --noEmit
```

Expected: 0 errors

- [ ] **Step 4: Commit**

```bash
git add ui/src/pages/Assignment.tsx ui/src/router.tsx
git commit -m "feat: add Assignment page with two-panel stakeholder assignment UI"
```

---

## Task 7: Runs page — `awaiting_assignment` status + assignment link

**Files:**
- Modify: `ui/src/components/StatusBadge.tsx`
- Modify: `ui/src/pages/Runs.tsx`

### Background

`StatusBadge` uses a `COLORS` record keyed by status string. An unknown status falls back to slate. Adding `awaiting_assignment` gives it an amber colour. `Runs.tsx` uses `<StatusBadge>` inside `<RunRow>` — we add a "Go to Assignment →" link next to the badge when the run has `awaiting_assignment` status.

- [ ] **Step 1: Add `awaiting_assignment` to `StatusBadge.tsx`**

In `ui/src/components/StatusBadge.tsx`, add to the `COLORS` record:

```ts
const COLORS: Record<string, string> = {
  pending:              'bg-slate-700 text-slate-300',
  queued:               'bg-amber-900/50 text-amber-300',
  running:              'bg-sky-900/50 text-sky-300',
  completed:            'bg-emerald-900/50 text-emerald-300',
  failed:               'bg-red-900/50 text-red-300',
  created:              'bg-slate-700 text-slate-300',
  awaiting_assignment:  'bg-amber-900/50 text-amber-300',
}
```

- [ ] **Step 2: Add the assignment link to `Runs.tsx`**

In `ui/src/pages/Runs.tsx`, update the imports to add `Link` and `useParams`:

```tsx
import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import StatusBadge from '../components/StatusBadge'
import type { OrchestrationRunHistory } from '../types'
```

Update `RunRow` to accept `slug` and show the link:

```tsx
function RunRow({ run, slug }: { run: OrchestrationRunHistory; slug: string }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="bg-surface-card rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-slate-200">Run #{run.id}</span>
          <StatusBadge status={run.status} />
          {run.status === 'awaiting_assignment' && (
            <Link
              to={`/${slug}/assignment`}
              onClick={(e) => e.stopPropagation()}
              className="text-xs text-teal-400 hover:text-teal-300 underline underline-offset-2"
            >
              Go to Assignment →
            </Link>
          )}
          {run.crew_runs.length > 0 && (
            <span className="text-xs text-slate-500">
              {run.crew_runs.length} crew{run.crew_runs.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-500">
            {run.started_at ? new Date(run.started_at).toLocaleString() : '—'}
          </span>
          <span className="text-xs text-slate-500">
            {formatDuration(run.started_at, run.completed_at)}
          </span>
          <span className="text-slate-500 text-xs">{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div className="border-t border-slate-800 px-4 py-3 space-y-1.5">
          {run.crew_runs.length === 0 ? (
            <p className="text-xs text-slate-500">No crew runs linked to this orchestration run.</p>
          ) : (
            run.crew_runs.map((cr) => (
              <div key={cr.crew_name} className="flex items-center justify-between py-1">
                <span className="text-xs text-slate-300">{cr.crew_name}</span>
                <StatusBadge status={cr.status} />
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
```

Update the `Runs` component to pass `slug` to `RunRow` and add `awaiting_assignment` to the refetch condition:

```tsx
export default function Runs() {
  const { slug } = useParams<{ slug: string }>()

  const { data: runs = [], isLoading } = useQuery({
    queryKey: ['runs', slug],
    queryFn: () => projectsApi.listRuns(slug!),
    enabled: !!slug,
    refetchInterval: (query) => {
      const hasActive = query.state.data?.some(
        (r) => r.status === 'running' || r.status === 'awaiting_assignment',
      )
      return hasActive ? 5000 : false
    },
  })

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-slate-100">Run History</h2>
      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {!isLoading && runs.length === 0 && (
        <p className="text-sm text-slate-500">No pipeline runs yet.</p>
      )}
      <div className="space-y-3">
        {runs.map((run) => (
          <RunRow key={run.id} run={run} slug={slug!} />
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Type-check**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npx tsc --noEmit
```

Expected: 0 errors

- [ ] **Step 4: Run the full test suite**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest --tb=short -q
```

Expected: all existing tests PASS + new assignment tests PASS (no regressions)

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/StatusBadge.tsx ui/src/pages/Runs.tsx
git commit -m "feat: add awaiting_assignment status badge and Go to Assignment link in Runs page"
```

---

## Self-Review

**Spec coverage:**
1. Crew split → Task 2 (discovery_mapping_crew.py) ✓
2. Value chain tree JSON → Task 2 (mapper task step 10) ✓
3. PAM phase split → Task 3 (pam_crew.py + orchestration_service.py) ✓
4. `awaiting_assignment` status → Task 3 (run_pam_phase1 sets it) ✓
5. `stakeholder_assignments` table → Task 1 ✓
6. DB helpers (fetch + replace) → Task 1 ✓
7. Assignment API (GET/POST/PATCH) → Task 4 ✓
8. `get_value_chain_tree` in project_service → Task 2 ✓
9. Frontend types → Task 5 ✓
10. API methods → Task 5 ✓
11. Assignment page → Task 6 ✓
12. Route → Task 6 ✓
13. Runs page status + link → Task 7 ✓
14. StatusBadge → Task 7 ✓

**Placeholder scan:** No TBDs. All code blocks are complete.

**Type consistency:**
- `StakeholderAssignment` defined in Task 5, used in Task 6 (`Assignment.tsx`) ✓
- `AssignmentData` defined in Task 5, used in `endpoints.ts` and `Assignment.tsx` ✓
- `fetch_stakeholder_assignments` defined in Task 1, imported in Task 4 router ✓
- `replace_stakeholder_assignments` defined in Task 1, imported in Task 4 router ✓
- `resume_orchestration` defined in Task 3, imported in Task 4 router ✓
- `create_pam_mapping_crew` / `create_pam_resume_crew` defined in Task 3, used in orchestration_service ✓
- `run_pam_phase1` in orchestration_service patched in updated test_orchestration_service ✓
