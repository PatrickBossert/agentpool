# SP10b — Discovery Inputs Page + WebFetchTool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a structured Discovery Inputs page (`/:slug/discovery`) where users save a research brief, research links, and document priority selections; wire those inputs into the Value Chain Mapper task description; and add a WebFetchTool that fetches and strips link content before the crew runs.

**Architecture:** Three new fields (`discovery_brief`, `discovery_links`, `discovery_document_ids`) are added to `ProjectSettings` and persisted via the existing PATCH `/projects/{slug}/settings` endpoint. `WebFetchTool` is a new `BaseTool` that performs an HTTP GET and strips HTML. The discovery crew factory reads the saved inputs from config.yaml, resolves document IDs to filenames via the async DB, and injects a context preamble into the Value Chain Mapper task description.

**Tech Stack:** Python (aiohttp for HTTP fetching inside WebFetchTool), FastAPI, React + TanStack Query v5, TypeScript.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `api/models.py` |
| Modify | `tests/test_projects_settings.py` |
| Create | `agents/tools/web_fetch_tool.py` |
| Create | `tests/test_web_fetch_tool.py` |
| Modify | `agents/tools/registry.py` |
| Modify | `agents/discovery/value_chain_mapper.py` |
| Modify | `agents/crews/discovery_crew.py` |
| Modify | `api/services/run_service.py` |
| Modify | `ui/src/types.ts` |
| Modify | `ui/src/pages/Settings.tsx` |
| Modify | `ui/src/components/AppLayout.tsx` |
| Modify | `ui/src/router.tsx` |
| Create | `ui/src/pages/Discovery.tsx` |

---

## Task 1: ProjectSettings — 3 new fields + backend settings test

**Files:**
- Modify: `api/models.py`
- Modify: `tests/test_projects_settings.py`

- [ ] **Step 1: Write the failing test**

Add this test at the bottom of `tests/test_projects_settings.py`:

```python
@pytest.mark.asyncio
async def test_patch_settings_discovery_fields(client):
    await client.post("/projects", json=PROJECT)
    patch_body = {
        "llm_mode": "standard",
        "sector": "rail",
        "stakeholder_groups": [],
        "value_stream_labels": [],
        "roadmap_time_axis": "quarters",
        "crews_enabled": ["discovery"],
        "review_gates": True,
        "slack_channel": "",
        "discovery_brief": "Focus on freight operations.",
        "discovery_links": [{"url": "https://example.com", "label": "Example"}],
        "discovery_document_ids": [1, 2],
    }
    resp = await client.patch("/projects/settings-test/settings", json=patch_body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["discovery_brief"] == "Focus on freight operations."
    assert data["discovery_links"] == [{"url": "https://example.com", "label": "Example"}]
    assert data["discovery_document_ids"] == [1, 2]
    # Verify persisted via GET
    get_resp = await client.get("/projects/settings-test/settings")
    assert get_resp.json()["discovery_brief"] == "Focus on freight operations."
    assert get_resp.json()["discovery_links"] == [{"url": "https://example.com", "label": "Example"}]
    assert get_resp.json()["discovery_document_ids"] == [1, 2]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest tests/test_projects_settings.py::test_patch_settings_discovery_fields -v
```

Expected: FAIL — validation error because `discovery_brief` is not a valid field on `ProjectSettings`.

- [ ] **Step 3: Add the 3 new fields to `ProjectSettings` and `ProjectCreate`**

In `api/models.py`, replace the `ProjectSettings` class:

```python
class ProjectSettings(BaseModel):
    llm_mode: Literal["standard", "sensitive", "fallback"] = "standard"
    sector: str
    stakeholder_groups: list[str] = []
    value_stream_labels: list[str] = []
    roadmap_time_axis: Literal["quarters", "years", "horizons"] = "quarters"
    crews_enabled: list[str] = [
        "discovery", "value_design", "architecture", "delivery", "business_plan"
    ]
    review_gates: bool = True
    slack_channel: str = ""
    discovery_brief: str = ""
    discovery_links: list[dict] = []
    discovery_document_ids: list[int] = []
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_projects_settings.py -v
```

Expected: All settings tests PASS (previously passing tests still pass, new test now passes).

- [ ] **Step 5: Commit**

```bash
git add api/models.py tests/test_projects_settings.py
git commit -m "feat: add discovery_brief, discovery_links, discovery_document_ids to ProjectSettings"
```

---

## Task 2: WebFetchTool

**Files:**
- Create: `agents/tools/web_fetch_tool.py`
- Create: `tests/test_web_fetch_tool.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_web_fetch_tool.py`:

```python
# tests/test_web_fetch_tool.py
from unittest.mock import patch, MagicMock
import pytest
from agents.tools.web_fetch_tool import WebFetchTool


@pytest.fixture
def tool():
    return WebFetchTool()


def test_returns_stripped_text_on_success(tool):
    html = "<html><body><p>Hello world</p></body></html>"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html

    with patch("agents.tools.web_fetch_tool.requests.get", return_value=mock_response):
        result = tool._run(url="https://example.com")

    assert "Hello world" in result
    assert "<p>" not in result


def test_truncates_long_content(tool):
    html = "<html><body>" + ("x" * 20_000) + "</body></html>"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html

    with patch("agents.tools.web_fetch_tool.requests.get", return_value=mock_response):
        result = tool._run(url="https://example.com")

    assert len(result) <= 8_100  # 8000 chars + small overhead for truncation message


def test_returns_error_on_non_200(tool):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"

    with patch("agents.tools.web_fetch_tool.requests.get", return_value=mock_response):
        result = tool._run(url="https://example.com/missing")

    assert "Error" in result
    assert "404" in result


def test_returns_error_on_connection_failure(tool):
    import requests as req_lib
    with patch("agents.tools.web_fetch_tool.requests.get", side_effect=req_lib.RequestException("timeout")):
        result = tool._run(url="https://unreachable.example.com")

    assert "Error" in result
    assert "unreachable" not in result or "timeout" in result.lower() or "Error" in result


def test_strips_script_and_style_tags(tool):
    html = "<html><head><style>body{color:red}</style></head><body><script>alert(1)</script><p>Content</p></body></html>"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html

    with patch("agents.tools.web_fetch_tool.requests.get", return_value=mock_response):
        result = tool._run(url="https://example.com")

    assert "Content" in result
    assert "alert" not in result
    assert "color:red" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_web_fetch_tool.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'agents.tools.web_fetch_tool'`.

- [ ] **Step 3: Implement WebFetchTool**

Create `agents/tools/web_fetch_tool.py`:

```python
# agents/tools/web_fetch_tool.py
import re
import requests
from pydantic import BaseModel, Field
from crewai.tools import BaseTool

_CHAR_LIMIT = 8_000
_TIMEOUT = 10  # seconds

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


class WebFetchToolInput(BaseModel):
    url: str = Field(description="The URL to fetch and read.")


def _strip_html(html: str) -> str:
    """Remove script/style blocks and HTML tags; collapse whitespace."""
    # Remove <script>...</script> and <style>...</style> blocks
    html = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


class WebFetchTool(BaseTool):
    name: str = "WebFetchTool"
    description: str = (
        "Fetch the text content of a web page given its URL. "
        "Returns the page's readable text, stripped of HTML. "
        "Use for reading research links provided for this project."
    )
    args_schema: type[BaseModel] = WebFetchToolInput

    def _run(self, url: str) -> str:
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            return f"Error fetching {url}: {exc}"

        if resp.status_code != 200:
            return f"Error fetching {url}: HTTP {resp.status_code}"

        text = _strip_html(resp.text)
        if len(text) > _CHAR_LIMIT:
            text = text[:_CHAR_LIMIT] + f"\n\n[Content truncated at {_CHAR_LIMIT} characters]"
        return text
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_web_fetch_tool.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/tools/web_fetch_tool.py tests/test_web_fetch_tool.py
git commit -m "feat: add WebFetchTool — HTTP GET with HTML stripping and 8k char truncation"
```

---

## Task 3: Registry + Discovery crew — inject discovery inputs into Value Chain Mapper task

**Files:**
- Modify: `agents/tools/registry.py`
- Modify: `agents/discovery/value_chain_mapper.py`
- Modify: `agents/crews/discovery_crew.py`
- Modify: `api/services/run_service.py`

- [ ] **Step 1: Write a failing integration-style test for task description injection**

Add this test to `tests/test_discovery_crew.py` (check the file first to understand the existing test pattern, then add to it):

```python
def test_value_chain_mapper_task_includes_discovery_brief():
    """Task description includes the discovery brief when provided."""
    from agents.discovery.value_chain_mapper import create_value_chain_mapper_task
    from unittest.mock import MagicMock
    agent = MagicMock()
    task = create_value_chain_mapper_task(
        agent=agent,
        discovery_brief="Focus on passenger services.",
        discovery_links=[{"url": "https://rsp.com", "label": "RSP"}],
        priority_doc_names=["strategy_2025.pdf"],
    )
    assert "Focus on passenger services." in task.description
    assert "https://rsp.com" in task.description
    assert "strategy_2025.pdf" in task.description


def test_value_chain_mapper_task_unchanged_when_no_inputs():
    """Task description is unchanged (no extra section) when all inputs are empty."""
    from agents.discovery.value_chain_mapper import create_value_chain_mapper_task
    from unittest.mock import MagicMock
    agent = MagicMock()
    task = create_value_chain_mapper_task(agent=agent)
    assert "Research brief:" not in task.description
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_discovery_crew.py -v -k "discovery_brief or unchanged_when_no"
```

Expected: FAIL — `create_value_chain_mapper_task` does not accept those kwargs.

- [ ] **Step 3: Update `agents/tools/registry.py` to add WebFetchTool to value_chain_mapper**

In `agents/tools/registry.py`, add the import at the top of the function body (with the other local imports):

```python
from agents.tools.web_fetch_tool import WebFetchTool
```

Then update the `value_chain_mapper` entry in `tool_map`:

```python
"value_chain_mapper": [
    DocumentIngestionTool(slug=slug),
    TavilySearchTool(),
    WebFetchTool(),
    ChromaQueryTool(slug=slug, sector=sector),
    MermaidRenderTool(slug=slug),
    SQLiteStateTool(slug=slug),
    HumanInputTool(slug=slug, run_id=run_id),
],
```

- [ ] **Step 4: Update `agents/discovery/value_chain_mapper.py` — accept and inject discovery inputs**

Replace the entire file content:

```python
# agents/discovery/value_chain_mapper.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_value_chain_mapper(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Value Chain Mapper",
        goal=(
            "Map the client organisation's complete value chain by analysing uploaded documents "
            "and researching the sector. Produce a clear, accurate Mermaid diagram."
        ),
        backstory=(
            "You are a senior strategy consultant specialising in value chain analysis. "
            "You have deep expertise in identifying primary and support activities across "
            "industry sectors and translating them into clear visual models."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def _build_discovery_context(
    discovery_brief: str,
    discovery_links: list[dict],
    priority_doc_names: list[str],
) -> str:
    """Build a context preamble for the task description. Returns empty string if all inputs are empty."""
    parts = []
    if discovery_brief:
        parts.append(f"Research brief: {discovery_brief}")
    if discovery_links:
        links_list = "\n".join(
            f"  {i+1}. {entry.get('label', entry['url'])} — {entry['url']}"
            for i, entry in enumerate(discovery_links)
        )
        parts.append(
            "The client has provided these research links — fetch and read each "
            "using WebFetchTool before beginning your analysis:\n" + links_list
        )
    if priority_doc_names:
        docs_list = ", ".join(priority_doc_names)
        parts.append(
            f"Priority source documents (prioritise these when querying ChromaDB): {docs_list}"
        )
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n\n"


def create_value_chain_mapper_task(
    agent: Agent,
    discovery_brief: str = "",
    discovery_links: list[dict] | None = None,
    priority_doc_names: list[str] | None = None,
) -> Task:
    context_preamble = _build_discovery_context(
        discovery_brief=discovery_brief,
        discovery_links=discovery_links or [],
        priority_doc_names=priority_doc_names or [],
    )
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
        ),
        expected_output=(
            "A Mermaid value chain diagram saved to outputs/value_chain.md, "
            "a JSON summary saved via SQLiteStateTool, "
            "and confirmation that the diagram has been approved by a human reviewer."
        ),
        agent=agent,
    )
```

- [ ] **Step 5: Run the new tests to verify they pass**

```bash
pytest tests/test_discovery_crew.py -v -k "discovery_brief or unchanged_when_no"
```

Expected: Both new tests PASS.

- [ ] **Step 6: Update `agents/crews/discovery_crew.py` — accept and forward discovery inputs**

Replace the `create_discovery_crew` function signature and the `vcm_task` line:

```python
def create_discovery_crew(
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
    """
    Assemble and return the Discovery Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
        sector: Client sector (used by ChromaQueryTool for sector knowledge base).
        llm: Optional LLM override (used in tests to inject a cheap model).
        hitl_tool: Optional HITL tool override (Chainlit integration).
        discovery_brief: Free-text research brief from Discovery Inputs page.
        discovery_links: List of {"url", "label"} dicts from Discovery Inputs page.
        priority_doc_names: List of document filenames selected on Discovery Inputs page.
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

    vcm_task = create_value_chain_mapper_task(
        agent=vcm,
        discovery_brief=discovery_brief,
        discovery_links=discovery_links,
        priority_doc_names=priority_doc_names,
    )
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

- [ ] **Step 7: Update `api/services/run_service.py` — load and forward discovery inputs**

In `build_and_run_crew`, replace the `if crew_name == "discovery":` block:

```python
    if crew_name == "discovery":
        from agents.crews.discovery_crew import create_discovery_crew
        from api.database import fetch_project, fetch_documents

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

        crew = create_discovery_crew(
            slug=slug,
            run_id=run_id,
            llm_mode=llm_mode,
            sector=sector,
            discovery_brief=discovery_brief,
            discovery_links=discovery_links,
            priority_doc_names=priority_doc_names,
        )
```

Also add `fetch_project, fetch_documents` to the existing import at the top of `run_service.py`:

```python
from api.database import get_connection, update_crew_run_status, fetch_project, fetch_documents
```

- [ ] **Step 8: Run the full test suite to check for regressions**

```bash
pytest tests/ -v --ignore=tests/integration -x
```

Expected: All previously passing tests still pass; the 2 new `test_discovery_crew.py` tests pass.

- [ ] **Step 9: Commit**

```bash
git add agents/tools/registry.py agents/discovery/value_chain_mapper.py \
        agents/crews/discovery_crew.py api/services/run_service.py \
        tests/test_discovery_crew.py
git commit -m "feat: wire discovery inputs into Value Chain Mapper task + add WebFetchTool to registry"
```

---

## Task 4: Frontend — types, Discovery page, nav item, route

**Files:**
- Modify: `ui/src/types.ts`
- Modify: `ui/src/pages/Settings.tsx`
- Modify: `ui/src/components/AppLayout.tsx`
- Modify: `ui/src/router.tsx`
- Create: `ui/src/pages/Discovery.tsx`

- [ ] **Step 1: Update `ui/src/types.ts` — add DiscoveryLink and 3 new fields to ProjectSettings**

In `ui/src/types.ts`, add a new `DiscoveryLink` interface before `ProjectSettings`, and add the 3 new fields to `ProjectSettings`. The `ProjectSettings` interface currently ends at `slack_channel`. Find the `ProjectSettings` interface and replace it:

```typescript
export interface DiscoveryLink {
  url: string
  label: string
}

export interface ProjectSettings {
  llm_mode: 'standard' | 'sensitive' | 'fallback'
  sector: string
  stakeholder_groups: string[]
  value_stream_labels: string[]
  roadmap_time_axis: 'quarters' | 'years' | 'horizons'
  crews_enabled: string[]
  review_gates: boolean
  slack_channel: string
  discovery_brief: string
  discovery_links: DiscoveryLink[]
  discovery_document_ids: number[]
}
```

(Read the current `ProjectSettings` block in `ui/src/types.ts` first and replace it in full.)

- [ ] **Step 2: Update `ui/src/pages/Settings.tsx` — add new fields to DEFAULTS**

The `DEFAULTS` constant in `Settings.tsx` must include all `ProjectSettings` fields or TypeScript will error. Find `const DEFAULTS: ProjectSettings = {` and add the three new fields:

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
}
```

- [ ] **Step 3: Add Discovery nav item to `ui/src/components/AppLayout.tsx`**

In `AppLayout.tsx`, find the `navItems` array (slug-scoped branch). Insert the Discovery item between Dashboard and Value Chain:

```typescript
const navItems: NavItem[] = slug
  ? [
      { to: `/${slug}`, label: 'Dashboard', end: true },
      { to: `/${slug}/discovery`, label: 'Discovery' },
      { to: `/${slug}/value-chain`, label: 'Value Chain' },
      { to: `/${slug}/roadmap`, label: 'Roadmap' },
      { to: `/${slug}/stakeholders`, label: 'Stakeholders' },
      { to: `/${slug}/business-plan`, label: 'Business Plan' },
      { to: `/${slug}/reviews`, label: 'Reviews', badge: pendingReviewCount > 0 ? pendingReviewCount : undefined },
      { to: `/${slug}/runs`, label: 'Runs' },
      { to: `/${slug}/documents`, label: 'Documents' },
    ]
  : [{ to: '/', label: 'Dashboard', end: true }]
```

- [ ] **Step 4: Add route to `ui/src/router.tsx`**

In `router.tsx`, add the import at the top:

```typescript
import Discovery from './pages/Discovery'
```

Add the route inside the children array (after the `:slug` dashboard route):

```typescript
{ path: ':slug/discovery', element: <Discovery /> },
```

- [ ] **Step 5: Create `ui/src/pages/Discovery.tsx`**

Create the full page. It fetches settings and documents, manages local form state, and PATCHes on Save:

```typescript
// ui/src/pages/Discovery.tsx
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import type { ProjectSettings, DiscoveryLink, ClientDocument } from '../types'

const SETTINGS_DEFAULTS: Pick<ProjectSettings, 'discovery_brief' | 'discovery_links' | 'discovery_document_ids'> = {
  discovery_brief: '',
  discovery_links: [],
  discovery_document_ids: [],
}

export default function Discovery() {
  const { slug } = useParams<{ slug: string }>()
  const qc = useQueryClient()

  const [brief, setBrief] = useState('')
  const [links, setLinks] = useState<DiscoveryLink[]>([])
  const [selectedDocIds, setSelectedDocIds] = useState<number[]>([])
  const [newUrl, setNewUrl] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug!),
    enabled: !!slug,
  })

  const { data: documents = [] } = useQuery<ClientDocument[]>({
    queryKey: ['documents', slug],
    queryFn: () => projectsApi.documents(slug!),
    enabled: !!slug,
  })

  useEffect(() => {
    if (settings) {
      setBrief(settings.discovery_brief ?? '')
      setLinks(settings.discovery_links ?? [])
      setSelectedDocIds(settings.discovery_document_ids ?? [])
    }
  }, [settings])

  const mutation = useMutation({
    mutationFn: (updated: ProjectSettings) => projectsApi.updateSettings(slug!, updated),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings', slug] })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
    onError: (e: Error) => setError(e.message),
  })

  function handleSave() {
    if (!settings) return
    setError(null)
    mutation.mutate({
      ...settings,
      discovery_brief: brief,
      discovery_links: links,
      discovery_document_ids: selectedDocIds,
    })
  }

  function addLink() {
    const trimmedUrl = newUrl.trim()
    if (!trimmedUrl) return
    setLinks((prev) => [...prev, { url: trimmedUrl, label: newLabel.trim() }])
    setNewUrl('')
    setNewLabel('')
  }

  function removeLink(index: number) {
    setLinks((prev) => prev.filter((_, i) => i !== index))
  }

  function toggleDoc(id: number) {
    setSelectedDocIds((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id],
    )
  }

  return (
    <div className="p-6 max-w-3xl">
      <h1 className="text-xl font-semibold text-slate-100 mb-1">Discovery Inputs</h1>
      <p className="text-slate-400 text-sm mb-8">
        Configure what the Value Chain Mapper uses before it starts. Changes take effect on the next crew run.
      </p>

      {/* Section 1: Research Brief */}
      <section className="mb-8">
        <h2 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Research Brief</h2>
        <p className="text-slate-500 text-xs mb-3">
          Any context the crew should know before it starts — strategic priorities, scope constraints, what the client has flagged.
        </p>
        <textarea
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          rows={5}
          placeholder="e.g. The client operates primarily in passenger rail in the UK. Focus on operational efficiency and safety compliance themes."
          className="w-full bg-slate-900 border border-slate-700 rounded p-3 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-sky-600 resize-y"
        />
      </section>

      {/* Section 2: Research Links */}
      <section className="mb-8">
        <h2 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Research Links</h2>
        <p className="text-slate-500 text-xs mb-3">
          URLs the crew will fetch and read before analysis. Add industry bodies, regulatory sites, company pages, or reports.
        </p>

        {links.length > 0 && (
          <ul className="mb-3 space-y-1">
            {links.map((link, i) => (
              <li key={i} className="flex items-center gap-2 bg-slate-900 border border-slate-700 rounded px-3 py-2">
                <span className="text-sky-400 text-xs font-mono flex-1 truncate">{link.url}</span>
                {link.label && <span className="text-slate-400 text-xs">{link.label}</span>}
                <button
                  type="button"
                  onClick={() => removeLink(i)}
                  className="text-slate-500 hover:text-red-400 text-xs ml-2"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex gap-2">
          <input
            value={newUrl}
            onChange={(e) => setNewUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addLink()}
            placeholder="https://..."
            className="flex-1 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-sky-600"
          />
          <input
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addLink()}
            placeholder="Label (optional)"
            className="w-40 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-sky-600"
          />
          <button
            type="button"
            onClick={addLink}
            disabled={!newUrl.trim()}
            className="px-4 py-2 bg-sky-700 hover:bg-sky-600 disabled:opacity-40 text-white text-sm rounded"
          >
            Add
          </button>
        </div>
      </section>

      {/* Section 3: Source Documents */}
      <section className="mb-8">
        <h2 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Source Documents</h2>
        <p className="text-slate-500 text-xs mb-3">
          Select documents to prioritise. The crew will focus ChromaDB queries on these files. If nothing is selected, all uploaded documents are weighted equally.
        </p>

        {documents.length === 0 ? (
          <p className="text-slate-500 text-sm italic">No documents uploaded yet. Upload documents on the Documents page.</p>
        ) : (
          <ul className="space-y-1">
            {documents.map((doc) => (
              <li key={doc.id} className="flex items-center gap-3">
                <input
                  type="checkbox"
                  id={`doc-${doc.id}`}
                  checked={selectedDocIds.includes(doc.id)}
                  onChange={() => toggleDoc(doc.id)}
                  className="accent-sky-500"
                />
                <label htmlFor={`doc-${doc.id}`} className="text-sm text-slate-300 cursor-pointer">
                  {doc.original_name}
                  <span className="text-slate-500 text-xs ml-2">
                    ({(doc.size_bytes / 1024).toFixed(0)} KB)
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Save */}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={handleSave}
          disabled={mutation.isPending}
          className="px-6 py-2 bg-brand hover:bg-brand-dark disabled:opacity-50 text-white text-sm font-medium rounded"
        >
          {mutation.isPending ? 'Saving…' : 'Save'}
        </button>
        {saved && <span className="text-emerald-400 text-sm">Saved.</span>}
      </div>
    </div>
  )
}
```

- [ ] **Step 6: Type-check the frontend**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npx tsc --noEmit
```

Expected: No type errors. If there are errors, fix them before proceeding.

- [ ] **Step 7: Run the full backend test suite**

```bash
cd /Users/pboagents/Documents/agentpool1
pytest tests/ -v --ignore=tests/integration -x
```

Expected: All tests pass (no regressions).

- [ ] **Step 8: Commit**

```bash
cd /Users/pboagents/Documents/agentpool1
git add ui/src/types.ts ui/src/pages/Settings.tsx ui/src/components/AppLayout.tsx \
        ui/src/router.tsx ui/src/pages/Discovery.tsx
git commit -m "feat: Discovery Inputs page with research brief, links, and document priority selection"
```

---

## Self-Review Checklist

Run this before declaring SP10b complete:

- [ ] `pytest tests/ --ignore=tests/integration` — all green
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors
- [ ] Discovery nav item appears between Dashboard and Value Chain
- [ ] Discovery page loads at `/:slug/discovery`, saves via PATCH, and reloads correctly
- [ ] Saving settings from the Discovery page does not wipe existing settings (full object is merged before PATCH)
- [ ] WebFetchTool is in the value_chain_mapper tool list in the registry
- [ ] Value chain mapper task description includes brief/links/docs when set, unchanged when empty
- [ ] `test_patch_settings_discovery_fields` passes
- [ ] `test_web_fetch_tool.py` — all 5 tests pass
- [ ] `test_discovery_crew.py` — new tests pass
