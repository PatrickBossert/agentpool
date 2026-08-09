# Per-Agent Model Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each agent run on a model suited to its work - fast for coordination, deep for reasoning across a corpus - in both standard and secure mode, instead of one model per crew.

**Architecture:** One registry maps each agent to a tier; a resolver binds that tier to a concrete model using the project's own `llm_mode` and settings. Crew factories stop choosing models entirely and ask the registry, exactly as they already ask `agents/tools/registry.py` for tools. A factory that cannot choose a model cannot forget to consult `llm_mode`, which is the defect that shipped past sixteen reviews last sprint.

**Tech Stack:** Python 3.13, CrewAI, FastAPI, Pydantic v2, aiosqlite, React 18 + TypeScript + Vitest, Ollama (local models).

**Spec:** `docs/superpowers/specs/2026-08-09-per-agent-model-selection-design.md`

## Global Constraints

- **British English throughout** - `-ise` not `-ize`, `-our` not `-or`. Applies to comments, docstrings, error messages, and UI copy.
- **Short en dash ` - ` with spaces in prose, never an em dash.**
- **Oxford comma** in lists of three or more.
- **No emoji in UI**; Lucide React icons only. Tailwind `brand`/`surface`/`text-*` tokens, **never `sky-*` or `blue-*`**.
- **Python 3.13 only.** Use `./venv/bin/pytest` and `./venv/bin/python`, never system Python.
- **Async fixtures must use `@pytest_asyncio.fixture`** - the project runs `asyncio_mode = strict`.
- **`projects` has no `name` column.** Insert with `(slug, sector)` or `(slug, llm_mode, sector, config_json)`.
- **`agent_outputs` has no `run_id` column**; `interview_sessions.stakeholder_id` has an enforced foreign key.
- **Run the backend suite twice before believing it is green.** `tests/conftest.py` points `DATABASE_DIR` at a fixed `/tmp/agentpool_test` that persists between runs.
- **Adding a `_migrate_*` function requires bumping `_SCHEMA_VERSION`** in `api/database.py`. Forgetting fails unsafe.
- **Every new project setting must be declared on `ProjectSettings`** in `api/models.py`. A field absent from that model is dropped inbound by `extra='ignore'`, deleted from `config_json` by `update_project_settings`'s wholesale `model_dump()`, and stripped outbound by `response_model`.
- **Integration tests are opt-in** (`pytest -m integration`) and cost real credit. Nothing here needs them.
- **Do not restart the API server**, and run uvicorn without `--reload`.

**Exact model identifiers, taken from the codebase - do not retype from memory:**

| Constant | Value | Source |
|---|---|---|
| PAM / deep | `anthropic/claude-opus-4-6` | `agents/pam/__init__.py:5` |
| Sonnet | `anthropic/claude-sonnet-4-6` | `agents/llm.py:38` |
| Haiku / fast | `anthropic/claude-haiku-4-5-20251001` | `agents/llm.py:59` |

---

## File Structure

**New files**

| File | Responsibility |
|---|---|
| `agents/model_registry.py` | `AGENT_TIER`, tier binding, and `get_llm_for_agent`. Nothing else. |
| `tests/test_model_registry.py` | Tier coverage, per-mode binding, fail-closed, and the source guard. |
| `docs/runbook-local-models.md` | Ollama deployment settings and their reasoning. |

**Modified files**

| File | Change |
|---|---|
| `api/models.py` | Six new `ProjectSettings` fields |
| `ui/src/pages/Settings.tsx`, `ui/src/types.ts` | Model selection fields |
| `agents/llm.py` | `max_tokens` on the local path; wrappers delegate to the registry |
| `agents/crews/*.py` (11 files) | Stop choosing models; call the registry per agent |
| `api/services/run_service.py` | Registry for standalone dispatch; Casey guard |
| `CLAUDE.md` | PAM exemption removed; tier table recorded |

---

## Task 1: The six model settings, declared where they survive

Before anything can resolve a model from project settings, the settings must exist and survive a round trip. This task is first because a field absent from `ProjectSettings` is silently discarded - which is exactly how `elaboration_press_timeout_seconds` shipped inert last sprint with two passing tests.

**Files:**
- Modify: `api/models.py` (`ProjectSettings`), `ui/src/types.ts`, `ui/src/pages/Settings.tsx`
- Test: `tests/test_project_settings_models.py` (create), `ui/src/__tests__/Settings.test.tsx`

**Interfaces:**
- Produces: six `ProjectSettings` fields consumed by Task 2's resolver -
  `anthropic_fast_model: str = "anthropic/claude-haiku-4-5-20251001"`,
  `anthropic_deep_model: str = "anthropic/claude-opus-4-6"`,
  `local_fast_model: str = "gemma4:fast"`,
  `local_fast_url: str = "http://localhost:11434/v1"`,
  `local_deep_model: str = "qwen27b:reasoning"`,
  `local_deep_url: str = "http://localhost:11434/v1"`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project_settings_models.py
"""A setting absent from ProjectSettings is discarded in both directions.

Pydantic v2 defaults to extra='ignore', so an undeclared field is dropped inbound;
update_project_settings writes model_dump() as the whole config_json, deleting anything
previously stored; and response_model=ProjectSettings strips it outbound. The press budget
shipped dead this way with a passing UI test that mocked the API client.
"""
import pytest

_MODEL_FIELDS = (
    "anthropic_fast_model",
    "anthropic_deep_model",
    "local_fast_model",
    "local_fast_url",
    "local_deep_model",
    "local_deep_url",
)


def test_every_model_setting_is_declared():
    from api.models import ProjectSettings
    missing = [f for f in _MODEL_FIELDS if f not in ProjectSettings.model_fields]
    assert not missing, f"undeclared settings are silently discarded: {missing}"


@pytest.mark.asyncio
async def test_the_model_settings_survive_a_round_trip(client):
    """Driven through the real endpoints, not a mocked client."""
    await client.post("/projects", json={
        "client_slug": "modelsettings", "llm_mode": "standard", "sector": "test",
        "stakeholder_groups": [], "value_stream_labels": [], "crews_enabled": [],
        "review_gates": True, "slack_channel": "",
    })
    r = await client.get("/projects/modelsettings/settings")
    body = r.json()
    body["local_deep_model"] = "qwen27b:reasoning"
    body["local_deep_url"] = "http://localhost:11500/v1"
    assert (await client.patch("/projects/modelsettings/settings", json=body)).status_code == 200

    back = (await client.get("/projects/modelsettings/settings")).json()
    assert back["local_deep_model"] == "qwen27b:reasoning"
    assert back["local_deep_url"] == "http://localhost:11500/v1"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/bin/pytest tests/test_project_settings_models.py -v`
Expected: FAIL listing all six as undeclared.

- [ ] **Step 3: Declare the fields**

In `api/models.py`, add to `ProjectSettings` beside `elaboration_press_timeout_seconds`:

```python
    # Model selection. Defaults here rather than in the registry so a project created before
    # this feature resolves exactly as it did before, and so the UI has something to show.
    anthropic_fast_model: str = "anthropic/claude-haiku-4-5-20251001"
    anthropic_deep_model: str = "anthropic/claude-opus-4-6"
    local_fast_model: str = "gemma4:fast"
    local_fast_url: str = "http://localhost:11434/v1"
    local_deep_model: str = "qwen27b:reasoning"
    local_deep_url: str = "http://localhost:11434/v1"
```

- [ ] **Step 4: Run the backend test to verify it passes**

Run: `./venv/bin/pytest tests/test_project_settings_models.py -v`
Expected: PASS

- [ ] **Step 5: Add the UI fields**

In `ui/src/types.ts` add the six fields to `ProjectSettings` with the same names and types. In `ui/src/pages/Settings.tsx`, add the same six to the `DEFAULTS` object, then a section after the Interview Method block:

```tsx
<div className="mt-6">
  <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest">Models</h3>
  <p className="text-xs text-muted mt-1 mb-3">
    Fast models handle coordination and live follow-ups. Deep models handle analysis across a
    whole campaign. Sensitive projects use the local pair and never the hosted ones.
  </p>
  {([
    ['anthropic_fast_model', 'Hosted fast model'],
    ['anthropic_deep_model', 'Hosted deep model'],
    ['local_fast_model', 'Local fast model'],
    ['local_fast_url', 'Local fast URL'],
    ['local_deep_model', 'Local deep model'],
    ['local_deep_url', 'Local deep URL'],
  ] as [keyof ProjectSettings, string][]).map(([key, label]) => (
    <div key={key} className="mb-3">
      <label htmlFor={key} className="text-xs text-gray-600 block mb-1">{label}</label>
      <input
        id={key}
        type="text"
        value={String(form[key] ?? '')}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-brand"
      />
    </div>
  ))}
</div>
```

- [ ] **Step 6: Add the UI sent-not-rendered test**

```tsx
// ui/src/__tests__/Settings.test.tsx  (append)
it('sends the local deep model when the form is saved', async () => {
  const saved = vi.fn().mockResolvedValue({})
  vi.mocked(projectsApi.updateSettings).mockImplementation(saved)
  render(<Settings />)
  const input = await screen.findByLabelText(/local deep model/i)
  fireEvent.change(input, { target: { value: 'qwen27b:reasoning' } })
  fireEvent.click(screen.getByRole('button', { name: /save/i }))
  await waitFor(() =>
    expect(saved).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ local_deep_model: 'qwen27b:reasoning' }),
    ))
})
```

- [ ] **Step 7: Run both suites**

Run: `./venv/bin/pytest tests/test_project_settings_models.py -q` then `cd ui && npx vitest run && npx tsc --noEmit`
Expected: PASS, `tsc` clean

- [ ] **Step 8: Commit**

```bash
git add api/models.py ui/src/types.ts ui/src/pages/Settings.tsx tests/test_project_settings_models.py ui/src/__tests__/Settings.test.tsx
git commit -m "feat(settings): per-project model selection fields

Six fields covering the hosted and local model for each tier, plus a URL per local tier so a
deployment may run one server per model or a single Ollama endpoint serving both by name.

Declared on ProjectSettings and asserted through a real round trip rather than a mocked
client: a field absent from that model is dropped inbound by extra='ignore', deleted from
config_json by the wholesale model_dump(), and stripped outbound by response_model. That is
how the press budget shipped inert with two passing tests."
```

---

## Task 2: The model registry

The core of the design: agents declare a tier, the mode binds it, and the resolver reads the project's own `llm_mode` rather than trusting a caller.

**Files:**
- Create: `agents/model_registry.py`, `tests/test_model_registry.py`
- Modify: `agents/llm.py`

**Interfaces:**
- Consumes: the six settings from Task 1; `project_llm_mode(slug) -> str` from `api/services/chroma_client.py`
- Produces:
  - `AGENT_TIER: dict[str, str]` mapping every agent name to `"fast"` or `"deep"`
  - `get_llm_for_agent(agent_name: str, slug: str) -> LLM`
  - `LocalModelUnavailable(RuntimeError)` raised when a sensitive project's tier has no model configured

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_model_registry.py
"""The registry is the single place an agent's model is decided.

Crew factories previously chose models themselves, which is how discovery_interviews_crew came
to declare llm_mode and never read it - putting the Synthesis Analyst on a hosted model while it
held ChromaQueryTool over the project's own interview answers.
"""
import re
import sqlite3
from pathlib import Path

import pytest

from api.config import get_settings


@pytest.fixture
def two_projects(tmp_path, monkeypatch):
    """One sensitive, one standard, in the same process.

    A per-deployment implementation passes every single-project test and fails only this shape.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    import json
    for slug, mode in (("sec-proj", "sensitive"), ("std-proj", "standard")):
        conn = sqlite3.connect(tmp_path / f"{slug}.db")
        conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, "
                     "llm_mode TEXT, sector TEXT, config_json TEXT)")
        conn.execute("INSERT INTO projects (slug, llm_mode, sector, config_json) VALUES (?,?,?,?)",
                     (slug, mode, "test", json.dumps({})))
        conn.commit(); conn.close()
    from api.services import chroma_client
    chroma_client._MODE_CACHE.clear()
    yield
    get_settings.cache_clear()


def test_every_dispatched_agent_has_a_tier():
    """Set equality, not a subset. A subset passes forever while an agent has no tier, and
    passes again if one is removed. This is the shape that caught visual_illustrator missing
    from the tool registry, where the crew raised before its first task."""
    from agents.model_registry import AGENT_TIER
    src = Path("agents/tools/registry.py").read_text()
    body = src.split("tool_map: dict[str, list[BaseTool]] = {")[1]
    registered = set(re.findall(r'^\s{8}"([a-z_]+)":', body, re.M))
    assert set(AGENT_TIER) == registered, (
        f"only in tool registry: {registered - set(AGENT_TIER)}; "
        f"only in AGENT_TIER: {set(AGENT_TIER) - registered}"
    )


def test_tiers_are_only_fast_or_deep():
    from agents.model_registry import AGENT_TIER
    assert set(AGENT_TIER.values()) <= {"fast", "deep"}


def test_a_sensitive_project_gets_local_models_for_both_tiers(two_projects):
    from agents.model_registry import get_llm_for_agent
    fast = get_llm_for_agent("stakeholder_interviewer", "sec-proj")
    deep = get_llm_for_agent("synthesis_analyst", "sec-proj")
    assert fast.base_url == "http://localhost:11434/v1"
    assert deep.base_url == "http://localhost:11434/v1"
    assert "claude" not in f"{fast.model}{deep.model}"


def test_both_modes_are_honoured_in_one_process(two_projects):
    """The test a per-deployment switch cannot pass."""
    from agents.model_registry import get_llm_for_agent
    assert get_llm_for_agent("synthesis_analyst", "sec-proj").base_url is not None
    assert get_llm_for_agent("synthesis_analyst", "std-proj").base_url is None


def test_two_agents_in_one_crew_get_different_models(two_projects):
    """The collapse being fixed: value_design_crew gave both agents one model in sensitive mode."""
    from agents.model_registry import get_llm_for_agent
    fast = get_llm_for_agent("portfolio_manager", "std-proj")
    deep = get_llm_for_agent("value_proposition_generator", "std-proj")
    assert fast.model != deep.model


def test_an_unconfigured_local_tier_refuses_rather_than_falling_back(two_projects, monkeypatch):
    """Never a hosted fallback, and never borrowing the other tier."""
    from agents import model_registry
    from agents.model_registry import get_llm_for_agent, LocalModelUnavailable
    monkeypatch.setattr(model_registry, "_project_setting",
                        lambda slug, key, default: "" if key == "local_deep_model" else default)
    with pytest.raises(LocalModelUnavailable, match="local_deep_model"):
        get_llm_for_agent("synthesis_analyst", "sec-proj")


def test_both_llm_paths_set_max_tokens(two_projects):
    """The hosted path set max_tokens=16384 because the 4096 default clips large tool-call JSON.
    The sensitive branch set nothing, so secure mode clipped exactly those outputs."""
    from agents.model_registry import get_llm_for_agent
    for slug in ("sec-proj", "std-proj"):
        llm = get_llm_for_agent("value_chain_mapper", slug)
        assert getattr(llm, "max_tokens", None) == 16384, f"{slug} has no max_tokens"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `./venv/bin/pytest tests/test_model_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.model_registry'`

- [ ] **Step 3: Create the registry**

```python
# agents/model_registry.py
"""Which model each agent runs on.

Agents declare a capability tier; the project's llm_mode binds that tier to a concrete model.
This mirrors agents/tools/registry.py, which maps an agent to its tools, and exists for the same
reason: knowledge that lives in eleven crew factories drifts. discovery_interviews_crew declared
llm_mode as a parameter and never read it, putting the Synthesis Analyst on a hosted model while
it held ChromaQueryTool over the project's own interview answers. Sixteen task-scoped reviews
passed it.

The mode is read here from the project's own row rather than accepted from the caller. A caller
that can pass the wrong mode is a caller that can leak.
"""
import json
import logging

from crewai import LLM

from api.config import get_settings
from api.services.chroma_client import project_llm_mode
from agents.anthropic_compat import ensure_conversation_ends_with_user

ensure_conversation_ends_with_user()

_log = logging.getLogger(__name__)

# See agents/llm.py for why streaming and an explicit timeout are required: CrewAI's Anthropic
# provider defaults to stream=False with timeout=None, which killed runs 22 and 23.
_LONG_CALL_TRANSPORT = {"stream": True, "timeout": 600.0}

# max_tokens=16384: the 4096 default clips large tool-call JSON outputs - questionnaire scripts
# run to ~8K tokens and the value chain tree to ~2.5K. Applied to both paths, because the local
# branch previously set nothing and clipped exactly those outputs.
_MAX_TOKENS = 16384


class LocalModelUnavailable(RuntimeError):
    """A sensitive project has no model configured for a tier.

    Raised rather than falling back. A hosted fallback would send client content to a third
    party, and borrowing the other tier's model would silently change what ran.
    """


# Fast is coordination and mechanical assembly. Deep is reasoning across a corpus, or producing a
# structure others inherit and cannot easily correct.
AGENT_TIER: dict[str, str] = {
    "interview_coordinator":       "fast",   # Taylor - builds the plan, creates sessions
    "stakeholder_interviewer":     "fast",   # Avery - creates sessions, waits, collects
    "stakeholder_manager":         "fast",   # Jordan - drafts outreach
    "portfolio_manager":           "fast",   # already deliberately on Haiku today
    "roadmap_generator":           "fast",   # sequences an existing register
    "visual_illustrator":          "deep",   # writes briefs grounded in real project data
    "interaction_designer":        "deep",   # Maya - the instruments the campaign runs on
    "synthesis_analyst":           "deep",   # Casey - reasons across every answer in a campaign
    "value_chain_mapper":          "deep",   # Alex - the spine everything downstream inherits
    "value_lever_analyst":         "deep",   # Morgan
    "value_proposition_generator": "deep",
    "enterprise_architect":        "deep",
    "initiative_identifier":       "deep",
    "requirements_capture":        "deep",
    "requirements_analyst":        "deep",
    "business_plan_generator":     "deep",
    "pam":                         "deep",   # no exemption - PAM can read project outputs
}

_TIER_SETTINGS = {
    ("fast", "standard"):  ("anthropic_fast_model", None),
    ("deep", "standard"):  ("anthropic_deep_model", None),
    ("fast", "sensitive"): ("local_fast_model", "local_fast_url"),
    ("deep", "sensitive"): ("local_deep_model", "local_deep_url"),
}


def _project_setting(slug: str, key: str, default: str) -> str:
    """One value from the project's config_json, falling back to the model default.

    Synchronous, because every caller is: crew factories are built inside a running crew and the
    standalone dispatch is a plain function.
    """
    import contextlib
    import sqlite3
    path = f"{get_settings().database_dir}/{slug}.db"
    with contextlib.suppress(sqlite3.Error, OSError, json.JSONDecodeError):
        with contextlib.closing(sqlite3.connect(path)) as conn:
            row = conn.execute(
                "SELECT config_json FROM projects WHERE slug=?", (slug,)
            ).fetchone()
            if row and row[0]:
                value = json.loads(row[0]).get(key)
                if value:
                    return str(value)
    return default


def get_llm_for_agent(agent_name: str, slug: str) -> LLM:
    """The LLM this agent runs on for this project.

    Raises KeyError for an unregistered agent rather than guessing a tier - an unknown agent is a
    registry gap, and guessing would hide it the way a default tool list would have hidden
    visual_illustrator's missing entry.
    """
    tier = AGENT_TIER[agent_name]
    mode = project_llm_mode(slug)
    settings = get_settings()

    if mode == "sensitive":
        model_key, url_key = _TIER_SETTINGS[(tier, "sensitive")]
        model = _project_setting(slug, model_key, "")
        base_url = _project_setting(slug, url_key, "")
        if not model or not base_url:
            raise LocalModelUnavailable(
                f"Project '{slug}' is sensitive and has no local model for the '{tier}' tier. "
                f"Set {model_key} and {url_key} in the project's settings. "
                f"A hosted model is never substituted for a sensitive project."
            )
        return LLM(
            model=f"openai/{model}",
            base_url=base_url,
            api_key="not-needed",
            max_tokens=_MAX_TOKENS,
        )

    model_key, _ = _TIER_SETTINGS[(tier, "standard")]
    default = ("anthropic/claude-haiku-4-5-20251001" if tier == "fast"
               else "anthropic/claude-opus-4-6")
    return LLM(
        model=_project_setting(slug, model_key, default),
        api_key=settings.anthropic_api_key,
        max_tokens=_MAX_TOKENS,
        **_LONG_CALL_TRANSPORT,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_model_registry.py -v`
Expected: PASS

- [ ] **Step 5: Verify the tier test has power**

Delete one entry from `AGENT_TIER`, confirm `test_every_dispatched_agent_has_a_tier` fails and names it, restore it, confirm it passes. Report both.

- [ ] **Step 6: Commit**

```bash
git add agents/model_registry.py tests/test_model_registry.py
git commit -m "feat(agents): agents declare a tier, the project's mode binds it

AGENT_TIER maps each of the seventeen registered agents to fast or deep; get_llm_for_agent
resolves that against the project's own llm_mode and settings.

The mode is read from the project row rather than accepted from the caller, because a caller
that can pass the wrong mode is a caller that can leak - and build_and_run_agent currently
reads it from config.yaml, which fails open when that file drifts.

A sensitive project with no local model for a tier raises rather than falling back. A hosted
fallback would send client content to a third party and borrowing the other tier's model would
silently change what ran."
```

---

## Task 3: Crew factories consume the registry

Eleven factories currently choose models. After this task none of them contains a model name or a mode branch, which is what makes the class of defect structurally unreachable.

**Files:**
- Modify: all eleven `agents/crews/*_crew.py`, `agents/llm.py`, `api/services/run_service.py:597-640`
- Test: `tests/test_model_registry.py` (append the source guard)

**Interfaces:**
- Consumes: `get_llm_for_agent(agent_name, slug)` from Task 2

- [ ] **Step 1: Write the failing source guard**

```python
# tests/test_model_registry.py  (append)
def test_no_crew_factory_chooses_a_model():
    """Factories ask the registry. A factory that cannot choose a model cannot forget to
    consult llm_mode, which is the defect that shipped past sixteen reviews.

    Guards the class rather than the instance: bare-filename reads recurred across six sites and
    raw database connections across seven before each got a guard.
    """
    offenders = []
    for path in sorted(Path("agents/crews").glob("*_crew.py")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "anthropic/claude" in stripped or "get_pam_llm" in stripped \
                    or "get_haiku_llm" in stripped or "get_crew_llm" in stripped:
                offenders.append(f"{path}:{number}  {stripped[:70]}")
    assert not offenders, (
        "these choose a model instead of asking get_llm_for_agent:\n  " + "\n  ".join(offenders)
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/bin/pytest tests/test_model_registry.py::test_no_crew_factory_chooses_a_model -v`
Expected: FAIL, listing every factory that names a model or calls a mode helper.

- [ ] **Step 3: Convert each factory**

For every `agents/crews/*_crew.py`, replace its model-selection block with a per-agent registry call. Using `value_design_crew.py` as the worked example - its current block is the clearest instance of the defect:

```python
# before
    if llm is not None:
        vpg_llm = pm_llm = llm
    elif llm_mode == "sensitive":
        _local = get_crew_llm("sensitive")
        vpg_llm = pm_llm = _local
    else:
        vpg_llm = get_pam_llm()
        pm_llm = get_haiku_llm()

# after
    from agents.model_registry import get_llm_for_agent
    vpg_llm = llm or get_llm_for_agent("value_proposition_generator", slug)
    pm_llm = llm or get_llm_for_agent("portfolio_manager", slug)
```

Keep the `llm=` override - integration tests inject a cheap model through it and it is the only
consumer of `get_test_llm`. Keep each factory's `llm_mode` parameter for signature compatibility
even though it is now unused; removing it would touch every call site in `run_service.py` for no
behavioural gain. Add `# noqa` only if a linter objects.

- [ ] **Step 4: Convert the standalone dispatch**

`api/services/run_service.py:597` builds one `llm = get_crew_llm(llm_mode)` for whichever agent is
dispatched, reading `llm_mode` from `config.yaml`. Replace with:

```python
    from agents.model_registry import get_llm_for_agent
    llm = get_llm_for_agent(agent_key, slug)
```

and delete the now-unused `llm_mode` local if nothing else in the function uses it.

- [ ] **Step 5: Reduce the old helpers to wrappers**

In `agents/llm.py`, leave `get_test_llm` alone. `get_crew_llm`, `get_pam_llm`, and `get_haiku_llm`
have no callers left in `agents/crews/` after Step 3 - check for others with
`grep -rn "get_crew_llm\|get_pam_llm\|get_haiku_llm" api agents | grep -v test` and convert any
remaining caller to the registry. If none remain, delete the three functions and say so.

- [ ] **Step 6: Run the guard and the crew suites**

Run: `./venv/bin/pytest tests/test_model_registry.py tests/test_value_design_crew.py tests/test_discovery_interviews_crew.py tests/test_business_plan_crew.py tests/test_delivery_crew.py -q`
Expected: PASS. Crew tests that patch `get_crew_llm` will need repointing at
`agents.model_registry.get_llm_for_agent` - **patch where the name is looked up**, in the crew
module, not where it is defined. That distinction cost this project four tests and hid a live bug.

- [ ] **Step 7: Full suite twice**

Run: `./venv/bin/pytest -q` twice. Identical counts both times.

- [ ] **Step 8: Commit**

```bash
git add agents/crews/ agents/llm.py api/services/run_service.py tests/test_model_registry.py
git commit -m "refactor(crews): factories ask the registry instead of choosing models

No crew factory now contains a model name or a mode branch, enforced by a source guard. That
is the structural point rather than a tidiness one: a factory that cannot choose a model cannot
forget to consult llm_mode, and forgetting is exactly what discovery_interviews_crew did.

The standalone dispatch also stops reading llm_mode from config.yaml, which is the authority
that fails open when that file drifts from the projects column."
```

---

## Task 4: PAM loses its exemption

**Files:**
- Modify: `CLAUDE.md` (line ~208), `agents/crews/pam_crew.py`
- Test: `tests/test_model_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_registry.py  (append)
def test_pam_routes_locally_for_a_sensitive_project(two_projects):
    """PAM holds SQLiteStateTool and can read project outputs, so an always-hosted exemption
    was a hole in the secure-mode guarantee rather than a quality decision."""
    from agents.model_registry import get_llm_for_agent
    pam = get_llm_for_agent("pam", "sec-proj")
    assert pam.base_url == "http://localhost:11434/v1"
    assert "claude" not in pam.model
```

- [ ] **Step 2: Run it**

Run: `./venv/bin/pytest tests/test_model_registry.py::test_pam_routes_locally_for_a_sensitive_project -v`
Expected: PASS if Task 2 and 3 are complete - `AGENT_TIER["pam"] = "deep"` already routes it. If
`pam_crew.py` still calls `get_pam_llm`, it fails; convert it as in Task 3.

- [ ] **Step 3: Rewrite the CLAUDE.md rule**

Replace the line reading *"PAM always uses `claude-opus-4-6` regardless of sensitive mode. Other
agents use `LOCAL_LLM_MODEL` when sensitive mode is enabled"* with:

```markdown
Each agent declares a capability tier in `agents/model_registry.py` - `fast` or `deep` - and the
project's `llm_mode` binds that tier to a model. Crew factories never choose a model; they call
`get_llm_for_agent(agent_name, slug)`, and a source guard fails if one names a model.

PAM has no exemption. It is `deep` and routes to the local model for a sensitive project like
every other agent, because it holds `SQLiteStateTool` and can read project outputs - an
always-hosted orchestrator was a hole in the secure-mode guarantee rather than a quality choice.

A sensitive project with no local model configured for a tier raises `LocalModelUnavailable`
rather than falling back. There is no hosted fallback and no borrowing of the other tier.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md agents/crews/pam_crew.py tests/test_model_registry.py
git commit -m "feat(secure): PAM routes locally like every other agent

CLAUDE.md stated PAM always uses claude-opus-4-6 regardless of sensitive mode. PAM holds
SQLiteStateTool and can read project outputs, so that was a hole in the guarantee rather than a
quality decision. Secure mode now means what it says."
```

---

## Task 5: Casey refuses to run while interviews are live

Running the Synthesis Analyst saturates the reasoning model while the fast model serves live follow-ups. Inside the crew this is already impossible - `Process.sequential`, `context_tasks=[t2]`, and Avery blocking on `HumanInputTool` until a consultant replies "ready". The standalone dispatch bypasses it with `context_tasks=[]`, and is the only reachable path.

**Files:**
- Modify: `api/services/run_service.py` (`build_and_run_agent`, around line 597)
- Test: `tests/test_run_service_interviews.py`

**Interfaces:**
- Consumes: `fetch_interview_sessions_status(conn, project_id=...)` from `api/database.py:2983` - read its real signature before use

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_service_interviews.py  (append)
@pytest.mark.asyncio
async def test_standalone_casey_refuses_while_interviews_are_live(live_campaign):
    """Driven through build_and_run_agent, not by calling a guard helper.

    A guard the dispatch does not consult is worthless, which this codebase has recorded seven
    times. The crew path already expresses "wait for interviews" correctly via Avery's HITL gate;
    this is the only path that bypasses it.
    """
    from api.services.run_service import build_and_run_agent
    with pytest.raises(ValueError, match="interview"):
        await build_and_run_agent(live_campaign, "synthesis_analyst", run_id=1)


@pytest.mark.asyncio
async def test_standalone_casey_runs_once_interviews_are_done(completed_campaign, monkeypatch):
    """The guard must not block the normal case."""
    from api.services import run_service
    called = {}
    async def fake_kickoff(self):
        called["ran"] = True
    monkeypatch.setattr("crewai.Crew.kickoff_async", fake_kickoff)
    await run_service.build_and_run_agent(completed_campaign, "synthesis_analyst", run_id=1)
    assert called.get("ran")
```

Build `live_campaign` and `completed_campaign` as `@pytest_asyncio.fixture`s seeding one project
each with sessions in `active`/`pending` and `completed` status respectively, using
`monkeypatch.setenv("DATABASE_DIR", str(tmp_path))` with `get_settings.cache_clear()` on both sides.
`interview_sessions.stakeholder_id` has an enforced foreign key, so seed stakeholders too.

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_run_service_interviews.py -v`
Expected: FAIL - no exception is raised.

- [ ] **Step 3: Add the guard**

In `build_and_run_agent`, after the `AGENT_CREW_NAME` membership check:

```python
    if agent_key == "synthesis_analyst":
        # Casey saturates the reasoning model, and during a campaign the fast model is answering
        # live follow-ups on the same machine. Inside the crew this cannot happen: the process is
        # sequential and Avery blocks on HumanInputTool until a consultant confirms interviews are
        # complete. Only this path bypasses that, so the refusal belongs here rather than in a
        # second general mechanism.
        async with get_connection(slug) as conn:
            project = await fetch_project(conn, slug=slug)
            counts = await fetch_interview_sessions_status(conn, project_id=project["id"])
        live = (counts.get("pending", 0) or 0) + (counts.get("active", 0) or 0)
        if live:
            raise ValueError(
                f"{live} interview session(s) are still pending or active. Casey reads the whole "
                f"corpus and would compete with the model answering live follow-ups. Wait for the "
                f"interviews to finish, or mark the outstanding sessions abandoned."
            )
```

Read `fetch_interview_sessions_status`'s real return shape at `api/database.py:2983` first and
adapt - the brief assumes a dict of status to count.

- [ ] **Step 4: Run to verify both pass**

Run: `./venv/bin/pytest tests/test_run_service_interviews.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/run_service.py tests/test_run_service_interviews.py
git commit -m "fix(runs): standalone Casey refuses while interviews are live

Casey saturates the reasoning model while the fast model answers live follow-ups on the same
machine. Inside the crew this is already impossible - sequential process, context_tasks=[t2],
and Avery blocking on HumanInputTool until a consultant confirms interviews are complete.

The standalone dispatch builds Casey's task with context_tasks=[] and runs immediately, so it
is the only reachable path. Asserted through build_and_run_agent rather than by calling a guard
helper: a guard the dispatch does not consult is worthless."
```

---

## Task 6: The local-model runbook

Deployment settings, not application configuration, and they belong somewhere an operator will find them.

**Files:**
- Create: `docs/runbook-local-models.md`
- Modify: `CLAUDE.md` (a pointer in Known issues / tech debt)

- [ ] **Step 1: Write the runbook**

```markdown
# Running the local models

Secure mode runs two models at once - a fast model for coordination and live follow-ups, and a
reasoning model for analysis. Both must stay resident.

## Ollama settings

    OLLAMA_KEEP_ALIVE=-1          # never unload; both models stay resident
    OLLAMA_MAX_LOADED_MODELS=2    # at least 2, or they evict each other
    OLLAMA_NUM_PARALLEL=4         # concurrent requests per model

`OLLAMA_MAX_LOADED_MODELS` is the one that silently defeats the others. At its default of 1 the
two models evict each other on every alternation regardless of keep-alive and regardless of free
memory, which presents as the models being slow rather than as a configuration fault.

Keep-alive matters because interviewees arrive at lunchtimes with hours of silence between. At the
5 minute default the fast model is cold-loaded repeatedly, and a multi-gigabyte load in front of a
waiting interviewee is exactly the latency the press budget then skips - so a configuration fault
would be masked as a model limitation.

## Context sizes

Ollama's default `num_ctx` is 4096 and it truncates **silently**, oldest tokens first, which are
the instructions. Measured against a live project:

| Artefact | Approx tokens |
|---|---|
| value_chain_tree | 2,900 |
| value_chain_registry | 3,482 |
| value_chain_model | 12,230 |

An agent's system prompt plus task plus one `value_chain_model` read already exceeds 4096. Start at
`num_ctx 16384` for the reasoning model and `8192` for the fast model, then raise from `ollama ps`,
which prints each loaded model's real footprint.

At Q4_K_M a 4B fast model needs roughly 3 GB and a 27B reasoning model roughly 17 GB before KV
cache. On 24 GB that is workable but not comfortable, which is why the sizes above start
conservative.

## Do not set a stop sequence

CrewAI passes its own stop sequence and its tool-calling loop depends on it. A `PARAMETER stop` in
a Modelfile truncates the loop mid-cycle in ways that look like the model failing to use tools.
```

- [ ] **Step 2: Point at it from CLAUDE.md**

Add under Known issues / tech debt:

```markdown
- Secure mode runs two local models concurrently. `OLLAMA_MAX_LOADED_MODELS` defaults to 1, which
  makes them evict each other on every alternation regardless of free memory - see
  `docs/runbook-local-models.md` before diagnosing local models as slow.
```

- [ ] **Step 3: Commit**

```bash
git add docs/runbook-local-models.md CLAUDE.md
git commit -m "docs: runbook for running two local models concurrently

OLLAMA_MAX_LOADED_MODELS defaults to 1, so the pair evict each other on every alternation
regardless of keep-alive and regardless of free memory - which presents as slowness rather than
as configuration. Context sizes are given from measured artefact sizes rather than guessed,
because Ollama's 4096 default truncates silently and drops the instructions first."
```

---

## Task 7: Prove it end to end

- [ ] **Step 1: Verify the guards have power**

For each of the two source guards, add a scratch offender, confirm the guard names it, remove it,
confirm the guard passes. Report both directions for both guards:
- `test_no_crew_factory_chooses_a_model` - add `llm = get_pam_llm()` to any crew factory.
- `test_every_dispatched_agent_has_a_tier` - add a new key to `tool_map` in `agents/tools/registry.py`.

- [ ] **Step 2: Confirm no hosted call can happen for a sensitive project**

Run: `grep -rn "anthropic/claude\|get_pam_llm\|get_haiku_llm\|get_crew_llm" agents/ api/ | grep -v test`
Expected: hits only inside `agents/model_registry.py` and `agents/llm.py`'s `get_test_llm`.

- [ ] **Step 3: Full suites**

Run: `./venv/bin/pytest -q` twice - identical counts. Then `cd ui && npx vitest run && npx tsc --noEmit`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: per-agent model selection verified end to end

Both source guards verified in both directions. No model name or mode branch survives outside
the registry."
```

---

## Self-review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| Two tiers, agent declares, mode binds | 2 |
| Tier assignments for all 17 agents | 2 |
| Crew factories stop choosing models | 3 |
| Configuration in project settings only | 1, 2 |
| `LOCAL_LLM_MODEL` / `LLAMACPP_BASE_URL` removed | 3 (Step 5 sweep) |
| Every field declared on `ProjectSettings` | 1 |
| Secure mode fails closed | 2 |
| PAM loses its exemption, CLAUDE.md rewritten | 4 |
| `max_tokens` on both paths | 2 |
| Context sizing from measured artefacts | 6 |
| Ollama keep-alive and max-loaded-models | 6 |
| Casey refuses while interviews are live | 5 |
| Press duration logging | **gap - see below** |
| Tier coverage as set equality | 2 |
| Two agents in one crew differ | 2 |
| Two projects interleaved in one process | 2 |
| Unconfigured tier raises | 2 |
| Settings round-trip through real endpoints | 1 |
| No factory contains a model name | 3 |
| Standalone Casey guard at the dispatch | 5 |

**Gap found and closed:** the spec requires duration logging on every elaboration press, plus a
count of skips, so the hosted-override decision can be made from real numbers. Add to Task 5 as a
final step, since it touches the same interview path:

- [ ] **Task 5, Step 6: Log press durations**

In `api/services/interview_service.py`'s `elaboration_press`, wrap the `asyncio.wait_for` call to
record elapsed time on both the success and timeout paths:

```python
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(_press_call(prompt, slug), timeout=timeout_seconds)
        _log.info("elaboration_press[%s]: %.2fs, %d chars", slug,
                  time.perf_counter() - started, len(result))
        return result
    except asyncio.TimeoutError:
        _log.warning("elaboration_press[%s]: SKIPPED after %.2fs (budget %.1fs)", slug,
                     time.perf_counter() - started, timeout_seconds)
        return ""
```

Add `import time`. Assert in a test that a skipped press logs at warning level with the word
`SKIPPED`, using `caplog` - the count of skips must be greppable from one campaign's logs.

**Placeholder scan:** none. Every code step carries its code. Task 5, Step 3 and Task 3, Step 6
direct the implementer to read a real signature rather than trust the plan, which is stated
explicitly rather than left implicit.

**Type consistency:** `get_llm_for_agent(agent_name: str, slug: str) -> LLM` is defined in Task 2
and called with that signature in Tasks 3, 4, and 7. `AGENT_TIER: dict[str, str]` is defined in
Task 2 and read in Tasks 2 and 7. `LocalModelUnavailable` is defined and raised in Task 2 and
asserted in Task 2's tests. The six settings names in Task 1 match `_TIER_SETTINGS` in Task 2
exactly.

---

## Task 8: The live follow-up reads the same settings as everything else

Found by Task 4's implementer. The spec states that `LOCAL_LLM_MODEL` and `LLAMACPP_BASE_URL` are
removed rather than kept as a fallback, on the grounds that a second authority for one fact is how
drift happens. They survive because `_press_call` still reads them:

```python
# api/services/interview_service.py:230
client = AsyncAnthropic(base_url=settings.llamacpp_base_url, api_key="not-needed")
model = settings.local_llm_model
```

So for a sensitive project, agents resolve `local_fast_model` and `local_fast_url` from the
project's own settings while the live follow-up resolves two process-wide environment variables.
Configure one and not the other and they disagree silently - the exact shape the spec set out to
prevent, created by this plan rather than inherited.

The press is the fast-tier workload by nature: short, latency-critical, and answering a person in
real time. It should read the fast tier's settings.

**Files:**
- Modify: `api/services/interview_service.py` (`_press_call`), `api/config.py`, `.env.example`
- Test: `tests/test_secure_mode_routing.py`

**Interfaces:**
- Consumes: the `local_fast_model` and `local_fast_url` settings from Task 1

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_the_press_uses_the_project_s_fast_local_model(two_projects, monkeypatch):
    """Agents and the live follow-up must resolve from the same place.

    Asserted on the base URL the request actually reached, not on which setting was read - the
    defect this whole plan exists to fix was a correct-looking mode helper that a code path
    never consulted.
    """
    import json
    import sqlite3
    from pathlib import Path
    from api.services import interview_service as svc

    db = Path(get_settings().database_dir) / "secure-proj.db"
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE projects SET config_json=? WHERE slug=?",
                     (json.dumps({"local_fast_model": "gemma4:fast",
                                  "local_fast_url": "http://localhost:11999/v1"}), "secure-proj"))

    seen = {}

    class FakeMessages:
        async def create(self, **kw):
            seen.update(kw)
            class R:
                content = [type("T", (), {"text": "and then?"})()]
            return R()

    class FakeClient:
        def __init__(self, **kw):
            seen["base_url"] = kw.get("base_url")
            self.messages = FakeMessages()

    monkeypatch.setattr(svc, "AsyncAnthropic", FakeClient)
    await svc.elaboration_press("Q?", "short", "press", slug="secure-proj")
    assert seen["base_url"] == "http://localhost:11999/v1"
    assert seen["model"] == "gemma4:fast"
```

Adapt the fixture name and slug to whatever `tests/test_secure_mode_routing.py` already uses -
read the file rather than trusting these names.

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/bin/pytest tests/test_secure_mode_routing.py -v`
Expected: FAIL - the base URL is the global `LLAMACPP_BASE_URL`, not the project's.

- [ ] **Step 3: Read the fast tier's settings**

In `_press_call`, replace the two `settings.*` reads with the project's fast-tier settings. Reuse
`agents.model_registry._project_setting` rather than writing a second reader - importing inside the
function avoids a cycle, which is the established pattern in this file.

Keep the failure behaviour the press already has: it is wrapped in a budget that returns no press
on expiry, so a misconfigured local model degrades to a skipped follow-up rather than an error.
Decide whether an unconfigured fast tier should raise `LocalModelUnavailable` here or be caught by
the budget, and say which you chose and why - the interviewee is waiting either way.

- [ ] **Step 4: Run the test to verify it passes**

Run: `./venv/bin/pytest tests/test_secure_mode_routing.py tests/test_interviews_router.py -q`
Expected: PASS

- [ ] **Step 5: Remove the two settings**

Run: `grep -rn "local_llm_model\|llamacpp_base_url\|LOCAL_LLM_MODEL\|LLAMACPP_BASE_URL" api agents ui .env.example`
If the only hits left are the definitions themselves, delete them from `api/config.py` and
`.env.example`. If anything still reads them, leave them and name it in your report.

- [ ] **Step 6: Commit**

```bash
git add api/services/interview_service.py api/config.py .env.example tests/test_secure_mode_routing.py
git commit -m "fix(secure): the live follow-up reads the project's fast-tier settings

Agents resolved local_fast_model and local_fast_url from the project while _press_call read the
process-wide LLAMACPP_BASE_URL and LOCAL_LLM_MODEL. Configure one and not the other and they
disagreed silently - two authorities for one fact, which is what this plan set out to remove and
had instead created."
```
