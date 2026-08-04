# Output Ownership and Lineage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every output key one owning agent, record what each output was built from, and derive staleness from that record.

**Architecture:** Agent identity moves from a call argument into the tool at construction. An ownership map decides who may write which key; refusals are recorded rather than merely returned. Reads served by the state and retrieval tools are logged per run, and on write the new output is linked to everything that run read. Staleness is a query over those links against the last approved version - never a stored flag.

**Tech Stack:** Python 3.13, FastAPI, aiosqlite (raw SQL, no ORM), CrewAI, ChromaDB, React 18 + TypeScript + Vite + Tailwind v3, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-05-output-ownership-and-lineage-design.md`

**Already done, do not repeat:** the citation half of spec §6 - `ChromaQueryTool` returning `doc_id`/`original_name`/`answer_id` metadata, and the `Literal` fix - shipped as `6323c475`. This plan consumes that work; it does not redo it.

## Global Constraints

- **British English throughout** - `-ise` not `-ize`, `-our` not `-or`, `-re` not `-er`, `-ogue` not `-og`.
- **Spaced hyphen ` - ` in all content, never an em dash.** Oxford comma in lists of three or more.
- **No emoji in rendered web content.** Lucide React icons only.
- **Tailwind brand tokens only** - `text-brand`, `bg-brand`, `bg-surface`, `bg-surface-raised`, `bg-surface-card`, `text-primary`, `text-secondary`, `text-muted`. Never `sky-*` or `blue-*`.
- **All raw SQL lives in `api/database.py`.** Schema changes run on connection open and must also be added to any test fixture that creates that table by hand.
- **Never modify `agents/tools/human_input.py`.**
- **Never run `git add -A` or `git add .`** - stage the exact paths each task lists.
- **Backend tests:** `./venv/bin/pytest -q --ignore=tests/integration`.
- **Frontend tests:** `cd ui && npx vitest run` and `cd ui && npx tsc --noEmit`.
- **Both suites pass before every commit.** Baseline: 1012 backend passed, 2 skipped; 354 frontend passed.
- **Reads are never restricted.** Only writes are owned. A boundary that blocked reads would stop the pipeline.

## Not in this plan

**The tree-entity validation** - Alex's `value_chain_tree` carries no root `0`, so the registry has no L0 node and Maya's external scripts cannot anchor. That is the live blocker on the pipeline and it is a separate, smaller piece of work.

**Regenerating Maya's scripts.** Task 1 makes her next run refuse the batching rather than misfile it silently, which is better but still a refused run until the tree is fixed.

**The differential** and **automatic re-runs**, both set aside during design.

## File Structure

| File | Responsibility |
|---|---|
| `agents/tools/ownership.py` (create) | `OUTPUT_OWNERS`, and the pure check deciding whether an agent may write a key. |
| `api/services/lineage_service.py` (create) | Recording reads, linking writes, and the staleness query. Pure of tool concerns. |
| `agents/tools/sqlite_state.py` | Identity at construction; ownership enforced; reads logged. |
| `agents/tools/chroma_query.py` | Document retrievals logged. |
| `agents/tools/registry.py` | Passes `agent_name` and `run_id` into both tools. |
| `agents/tools/_db.py` | Version and `is_current` namespaces drop `agent_name`. |
| `api/database.py` | `blocked_writes`, `run_inputs`, `run_documents`, `output_lineage`, `output_citations`, and their helpers. |
| `api/routers/runs.py` | The lineage endpoint. |
| `ui/src/pages/Runs.tsx` | Tab bar and the Lineage tab. |

---

### Task 1: Ownership, and identity that is not self-asserted

**Files:**
- Create: `agents/tools/ownership.py`
- Modify: `agents/tools/sqlite_state.py`, `agents/tools/registry.py`
- Test: `tests/test_output_ownership.py` (create)

**Interfaces:**
- Produces: `OUTPUT_OWNERS: dict[str, str]`; `check_write(key: str, agent_name: str) -> str | None` returning a refusal message or `None`. Task 2 consumes `check_write`.

**Why:** `agent_name` is a call argument, so an agent asserts its own identity, and no rule says which keys it may write. Maya wrote Alex's `value_chain_registry`; nothing stopped her because nothing was watching.

This also ends the batching. `interview_scripts_batch1`…`batch9` are owned by nobody, so they cannot be written - which closes the empty Output tab, the empty review queue, and the bypassed validators in one rule.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_output_ownership.py`:

```python
# tests/test_output_ownership.py
"""One owner per output key, enforced where the write happens.

An agent's output instruction lives in its prompt, and a prompt is guidance rather than a
boundary. Maya wrote Alex's value_chain_registry honestly - she declared her own name and
wrote a key that was not hers, because nothing said she could not.
"""
import json

import pytest

from agents.tools.ownership import OUTPUT_OWNERS, check_write


def test_the_owner_may_write_its_own_key():
    assert check_write("value_chain_model", "value_chain_mapper") is None


def test_another_agent_may_not():
    refusal = check_write("value_chain_registry", "interaction_designer")
    assert refusal is not None
    # The message is what the agent reads and acts on. A bare refusal teaches it nothing.
    assert "value_chain_mapper" in refusal


def test_a_key_nobody_owns_is_refused():
    """The batching case. Asserting only the cross-agent case would let
    interview_scripts_batch1 through, which is how nine keys were written that nothing reads,
    nothing validates, and nothing shows for review."""
    refusal = check_write("interview_scripts_batch1", "interaction_designer")
    assert refusal is not None
    assert "interview_scripts_batch1" in refusal


def test_every_owner_is_a_real_agent():
    from api.services.run_service import _CREW_AGENT_NAMES

    dispatched = {a for agents in _CREW_AGENT_NAMES.values() for a in agents}
    unknown = {o for o in OUTPUT_OWNERS.values() if o not in dispatched}
    assert unknown == set(), f"keys owned by agents no crew dispatches: {unknown}"


def test_every_declared_write_is_owned_by_the_agent_told_to_make_it():
    """The map is the authority and this holds the prompts to it.

    An instruction telling an agent to write a key it does not own would be refused at run
    time, in a place nobody is watching, after the model has already done the work.
    """
    import collections
    import pathlib
    import re

    join = re.compile(r'"\s*\n\s*"')
    declared = collections.defaultdict(set)
    for path in sorted(pathlib.Path("agents").rglob("*.py")):
        if path.parts[1] in ("tools", "crews"):
            continue
        source = join.sub("", path.read_text())
        for key, agent in re.findall(
            r"operation='write', key='([a-z0-9_]+)',\s*agent_name='([a-z0-9_]+)'", source
        ):
            declared[key].add(agent)

    assert len(declared) >= 15, "the scan found too little to be asserting over"

    from api.services.run_service import _CREW_AGENT_NAMES

    dispatched = {a for agents in _CREW_AGENT_NAMES.values() for a in agents}
    for key, agents in declared.items():
        for agent in agents & dispatched:
            assert OUTPUT_OWNERS.get(key) == agent, (
                f"{agent} is told to write {key}, owned by {OUTPUT_OWNERS.get(key)}"
            )
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_output_ownership.py -q`
Expected: FAIL - `ModuleNotFoundError: agents.tools.ownership`

- [ ] **Step 3: Write the ownership map**

Create `agents/tools/ownership.py`:

```python
# agents/tools/ownership.py
"""Which agent owns which output key.

Reads are open - the pipeline depends on every agent reading upstream. Only writes are owned,
because a write is where one agent's work can destroy another's.

`value_chain_registry` is deliberately absent: it is written by DeriveRegistryTool rather than
through SQLiteStateTool, so no agent owns it here and any agent reaching for it through the
state tool is refused. That is exactly the reach that destroyed a file.
"""

OUTPUT_OWNERS: dict[str, str] = {
    "value_chain_model":           "value_chain_mapper",
    "value_chain_summary":         "value_chain_mapper",
    "value_chain_tree":            "value_chain_mapper",
    "value_levers":                "value_lever_analyst",
    "interview_scripts":           "interaction_designer",
    "interview_script_registry":   "interaction_designer",
    "stakeholder_engagement_plan": "stakeholder_manager",
    "interview_plan":              "interview_coordinator",
    "interview_transcripts":       "stakeholder_interviewer",
    "activity_insights":           "synthesis_analyst",
    "themes":                      "synthesis_analyst",
    "strategic_requirements":      "synthesis_analyst",
    "propositions":                "value_proposition_generator",
    "portfolio_register":          "portfolio_manager",
    "architecture_register":       "enterprise_architect",
    "initiative_register":         "initiative_identifier",
    "captured_requirements":       "requirements_capture",
    "requirements_analysis":       "requirements_analyst",
    "roadmap_data":                "roadmap_generator",
    "illustration_briefs":         "visual_illustrator",
}


def check_write(key: str, agent_name: str) -> str | None:
    """None when the write is allowed, otherwise the refusal the agent will read.

    The message names the owner, because an agent told only "no" will try again or improvise
    something worse - which is how nine batch keys came to exist.
    """
    owner = OUTPUT_OWNERS.get(key)
    if owner is None:
        return (
            f"Refused: '{key}' is not a declared output. Write only the key your task names - "
            f"splitting one output across several keys makes it invisible to the Output tab, "
            f"to review, and to validation."
        )
    if owner != agent_name:
        return (
            f"Refused: '{key}' belongs to {owner}. You may read it, not write it. If it is "
            f"wrong or missing something, say so in your output rather than correcting it - "
            f"the run that owns it must make the change."
        )
    return None
```

- [ ] **Step 4: Verify the map passes, then enforce it**

Run: `./venv/bin/pytest tests/test_output_ownership.py -q`
Expected: PASS, 5 tests.

In `agents/tools/sqlite_state.py`, add `agent_name: str = ""` as a field on `SQLiteStateTool` (beside `slug`), and at the top of the write branch in `_run`:

```python
        if operation == "write":
            # The identity the tool was built with, not the one the caller supplied. An
            # identity an agent asserts about itself is not an identity.
            identity = self.agent_name or agent_name
            if self.agent_name and agent_name and agent_name != self.agent_name:
                return (
                    f"Refused: this tool belongs to {self.agent_name}, and the write claims "
                    f"to be from {agent_name}."
                )
            refusal = check_write(key, identity)
            if refusal:
                return refusal
```

with `from agents.tools.ownership import check_write` at the top.

In `agents/tools/registry.py`, change every `SQLiteStateTool(slug=slug)` to
`SQLiteStateTool(slug=slug, agent_name=agent_name)`.

- [ ] **Step 5: Add the wiring tests**

Append to `tests/test_output_ownership.py`:

```python
def test_the_tool_refuses_a_write_it_does_not_own(tmp_path, monkeypatch):
    """The map existing and the tool consulting it are different facts, and only the second
    protects anything."""
    from api.config import get_settings
    from agents.tools.sqlite_state import SQLiteStateTool

    get_settings.cache_clear()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()

    tool = SQLiteStateTool(slug="acme", agent_name="interaction_designer")
    result = tool._run(
        operation="write", key="value_chain_registry",
        agent_name="interaction_designer", value=json.dumps({"activities": []}),
    )

    assert "Written to" not in result
    assert "value_chain_mapper" in result
    get_settings.cache_clear()


def test_the_tool_refuses_a_claimed_identity_that_is_not_its_own(tmp_path, monkeypatch):
    from api.config import get_settings
    from agents.tools.sqlite_state import SQLiteStateTool

    get_settings.cache_clear()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()

    tool = SQLiteStateTool(slug="acme", agent_name="interaction_designer")
    result = tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=json.dumps({}),
    )

    assert "Written to" not in result
    get_settings.cache_clear()


def test_reading_another_agents_key_still_works(tmp_path, monkeypatch):
    """Asserted rather than assumed. A boundary that blocked reads would stop the pipeline
    on its first cross-crew handover."""
    from api.config import get_settings
    from agents.tools.sqlite_state import SQLiteStateTool

    get_settings.cache_clear()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    outputs = tmp_path / "acme" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "value_chain_model.json").write_text('{"segments": []}')

    tool = SQLiteStateTool(slug="acme", agent_name="interaction_designer")
    result = tool._run(
        operation="read", key="value_chain_model", agent_name="interaction_designer",
    )

    assert "segments" in result
    get_settings.cache_clear()
```

- [ ] **Step 6: Run both suites and mutation-test**

Run: `./venv/bin/pytest -q --ignore=tests/integration` - expect 1020 passed.
Run: `cd ui && npx vitest run && npx tsc --noEmit` - expect 354 passed, tsc silent.

```bash
cp agents/tools/ownership.py /tmp/own.bak
# M1: unowned keys allowed - the batching returns
./venv/bin/python -c "
import pathlib;p=pathlib.Path('agents/tools/ownership.py');s=p.read_text()
p.write_text(s.replace('    if owner is None:','    if False:'))"
./venv/bin/pytest tests/test_output_ownership.py -q   # expect failures
cp /tmp/own.bak agents/tools/ownership.py
# M2: cross-agent writes allowed - the original defect
./venv/bin/python -c "
import pathlib;p=pathlib.Path('agents/tools/ownership.py');s=p.read_text()
p.write_text(s.replace('    if owner != agent_name:','    if False:'))"
./venv/bin/pytest tests/test_output_ownership.py -q   # expect failures
cp /tmp/own.bak agents/tools/ownership.py
./venv/bin/pytest tests/test_output_ownership.py -q   # expect 8 passed
```

- [ ] **Step 7: Commit**

```bash
git add agents/tools/ownership.py agents/tools/sqlite_state.py agents/tools/registry.py \
  tests/test_output_ownership.py
git commit -m "feat(agents): one owner per output key, enforced where the write happens"
```

---

### Task 2: Blocked writes are recorded

**Files:**
- Modify: `api/database.py`, `agents/tools/sqlite_state.py`
- Test: `tests/test_blocked_writes.py` (create)

**Interfaces:**
- Consumes: `check_write` from Task 1.
- Produces: `record_blocked_write(conn, *, project_id, run_id, agent_name, key, owner, reason) -> int`; `fetch_blocked_writes(conn, *, run_id=None) -> list[dict]`. Task 7 renders these.

**Why:** a refusal alone throws away a signal. Maya reaching for the registry was a correct diagnosis of a real upstream gap - the L0 entity was missing - and PAM reporting "Maya was blocked writing Alex's registry" states the gap rather than the misbehaviour.

- [ ] **Step 1: Write the failing test**

Create `tests/test_blocked_writes.py`:

```python
# tests/test_blocked_writes.py
"""A refused write is a finding, not just a rejection."""
import json

import pytest
import pytest_asyncio

from api.database import fetch_blocked_writes, get_connection, insert_project

SLUG = "blocked-writes-test"


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_refused_write_leaves_a_row(project):
    from agents.tools.sqlite_state import SQLiteStateTool

    tool = SQLiteStateTool(slug=SLUG, agent_name="interaction_designer", run_id=7)
    tool._run(
        operation="write", key="value_chain_registry",
        agent_name="interaction_designer", value=json.dumps({"activities": []}),
    )

    async with get_connection(SLUG) as conn:
        rows = await fetch_blocked_writes(conn)

    assert len(rows) == 1
    assert rows[0]["agent_name"] == "interaction_designer"
    assert rows[0]["key"] == "value_chain_registry"
    assert rows[0]["owner"] == "value_chain_mapper"
    assert rows[0]["run_id"] == 7


@pytest.mark.asyncio
async def test_the_agent_is_still_told(project):
    """Recording instead of telling would leave the agent looping on a write it cannot see
    failing."""
    from agents.tools.sqlite_state import SQLiteStateTool

    tool = SQLiteStateTool(slug=SLUG, agent_name="interaction_designer", run_id=7)
    result = tool._run(
        operation="write", key="value_chain_registry",
        agent_name="interaction_designer", value=json.dumps({}),
    )

    assert "value_chain_mapper" in result


@pytest.mark.asyncio
async def test_an_unowned_key_records_no_owner_rather_than_a_wrong_one(project):
    from agents.tools.sqlite_state import SQLiteStateTool

    tool = SQLiteStateTool(slug=SLUG, agent_name="interaction_designer", run_id=7)
    tool._run(
        operation="write", key="interview_scripts_batch1",
        agent_name="interaction_designer", value=json.dumps({}),
    )

    async with get_connection(SLUG) as conn:
        rows = await fetch_blocked_writes(conn)
    assert rows[0]["owner"] is None


@pytest.mark.asyncio
async def test_recording_failure_never_costs_the_refusal(project, monkeypatch):
    """The refusal is the load-bearing half. If bookkeeping fails, the write must still be
    refused rather than let through."""
    import agents.tools.sqlite_state as mod
    from agents.tools.sqlite_state import SQLiteStateTool

    def boom(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(mod, "record_blocked_write_sync", boom)

    tool = SQLiteStateTool(slug=SLUG, agent_name="interaction_designer", run_id=7)
    result = tool._run(
        operation="write", key="value_chain_registry",
        agent_name="interaction_designer", value=json.dumps({}),
    )

    assert "Written to" not in result
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_blocked_writes.py -q`
Expected: FAIL - `cannot import name 'fetch_blocked_writes'`

- [ ] **Step 3: Add the table and helpers**

In `api/database.py`, add a migration registered on connection open beside the others:

```python
async def _migrate_blocked_writes(conn: aiosqlite.Connection) -> None:
    """Writes an agent attempted and was not permitted to make.

    The attempted payload is deliberately not stored - it can be large, and the useful fact
    is that the reach happened, by whom, and for what.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS blocked_writes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id),
            run_id       INTEGER,
            agent_name   TEXT NOT NULL,
            key          TEXT NOT NULL,
            owner        TEXT,
            reason       TEXT NOT NULL,
            attempted_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()


async def fetch_blocked_writes(
    conn: aiosqlite.Connection, *, run_id: int | None = None
) -> list[dict]:
    where = " WHERE run_id = ?" if run_id is not None else ""
    params = (run_id,) if run_id is not None else ()
    async with conn.execute(
        f"SELECT * FROM blocked_writes{where} ORDER BY id DESC", params
    ) as cur:
        return [dict(row) async for row in cur]
```

- [ ] **Step 4: Record from the tool**

`SQLiteStateTool._run` is synchronous, so add a sync writer to `agents/tools/_db.py` beside the other sync helpers:

```python
def record_blocked_write_sync(
    slug: str, run_id: int, agent_name: str, key: str, owner: str | None, reason: str
) -> None:
    """Best-effort. The refusal is the load-bearing half; if this fails the write is still
    refused, and losing the record is better than letting the write through."""
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        project_id = get_project_id(slug)
        conn.execute(
            "INSERT INTO blocked_writes (project_id, run_id, agent_name, key, owner, reason)"
            " VALUES (?,?,?,?,?,?)",
            (project_id, run_id or None, agent_name, key, owner, reason),
        )
        conn.commit()
```

and in `sqlite_state.py`, add `run_id: int = 0` as a tool field and wrap the refusal:

```python
            refusal = check_write(key, identity)
            if refusal:
                try:
                    record_blocked_write_sync(
                        self.slug, self.run_id, identity, key,
                        OUTPUT_OWNERS.get(key), refusal,
                    )
                except Exception:
                    pass  # never let bookkeeping turn a refusal into a permitted write
                return refusal
```

In `registry.py`, pass `run_id=run_id` to every `SQLiteStateTool(...)`.

- [ ] **Step 5: Run, mutation-test, commit**

Run: `./venv/bin/pytest tests/test_blocked_writes.py -q` - expect 4 passed.
Run both suites - expect 1024 backend passed, 354 frontend.

```bash
# The mutation that matters: bookkeeping failure must not permit the write.
cp agents/tools/sqlite_state.py /tmp/ss.bak
./venv/bin/python -c "
import pathlib;p=pathlib.Path('agents/tools/sqlite_state.py');s=p.read_text()
p.write_text(s.replace('                except Exception:\n                    pass','                except Exception:\n                    refusal = None'))"
./venv/bin/pytest tests/test_blocked_writes.py -q   # expect 1 failed
cp /tmp/ss.bak agents/tools/sqlite_state.py
```

```bash
git add api/database.py agents/tools/_db.py agents/tools/sqlite_state.py \
  agents/tools/registry.py tests/test_blocked_writes.py
git commit -m "feat(agents): a refused write is recorded as a finding"
```

---

### Task 3: The version and filename namespaces agree

**Files:**
- Modify: `agents/tools/_db.py:84-130` (`insert_agent_output_sync`)
- Test: `tests/test_output_versioning.py` (create)

**Interfaces:**
- Produces: no new interface. Changes the scope of an existing one.

**Why:** version numbering and `is_current` supersession are scoped per `(project, agent, output_type)` while the filename is scoped per `(project, output_type)`. Maya's first registry was therefore v1, and v1 was a filename Alex had already used - the rename overwrote it, and both rows stayed current.

Task 1 makes cross-agent writes impossible, so this is belt-and-braces. It is also the difference between a refused write and a destroyed file.

- [ ] **Step 1: Write the failing test**

Create `tests/test_output_versioning.py`:

```python
# tests/test_output_versioning.py
"""Two agents writing one output type must not collide on disk.

Maya's first value_chain_registry was numbered v1 because versions were scoped per agent,
and v1 was a filename Alex had already used. The rename destroyed his file, and both rows
went on claiming to be current.
"""
import sqlite3

import pytest

from agents.tools._db import insert_agent_output_sync

SLUG = "versioning-test"


@pytest.fixture
def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()

    con = sqlite3.connect(str(tmp_path / "data" / f"{SLUG}.db"))
    con.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT)")
    con.execute(
        "CREATE TABLE agent_outputs (id INTEGER PRIMARY KEY, project_id INTEGER,"
        " agent_name TEXT, output_type TEXT, file_path TEXT, version INTEGER,"
        " review_status TEXT DEFAULT 'pending', revision_notes TEXT,"
        " is_current INTEGER NOT NULL DEFAULT 1,"
        " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    con.execute("INSERT INTO projects (id, slug) VALUES (1, ?)", (SLUG,))
    con.commit()
    con.close()

    outputs = tmp_path / SLUG / "outputs"
    outputs.mkdir(parents=True)
    yield outputs
    get_settings.cache_clear()


def _write(outputs, agent, content):
    path = outputs / "shared_type.json"
    path.write_text(content)
    insert_agent_output_sync(SLUG, agent, "shared_type", str(path))


def test_a_second_agent_does_not_overwrite_the_first(project):
    _write(project, "value_chain_mapper", '{"from": "alex"}')
    _write(project, "interaction_designer", '{"from": "maya"}')

    files = sorted(p.name for p in project.glob("shared_type_v*.json"))
    assert files == ["shared_type_v1.json", "shared_type_v2.json"]
    assert (project / "shared_type_v1.json").read_text() == '{"from": "alex"}'


def test_only_one_row_is_current(project):
    _write(project, "value_chain_mapper", '{"from": "alex"}')
    _write(project, "interaction_designer", '{"from": "maya"}')

    con = sqlite3.connect(str(project.parent.parent / "data" / f"{SLUG}.db"))
    current = con.execute(
        "SELECT agent_name FROM agent_outputs WHERE output_type='shared_type' AND is_current=1"
    ).fetchall()
    con.close()
    assert len(current) == 1
    assert current[0][0] == "interaction_designer"


def test_one_agent_writing_twice_still_versions_normally(project):
    """The ordinary case, asserted so the fix does not break it."""
    _write(project, "value_chain_mapper", '{"v": 1}')
    _write(project, "value_chain_mapper", '{"v": 2}')

    files = sorted(p.name for p in project.glob("shared_type_v*.json"))
    assert files == ["shared_type_v1.json", "shared_type_v2.json"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_output_versioning.py -q`
Expected: FAIL - both files are v1, and two rows are current.

- [ ] **Step 3: Drop `agent_name` from both scopes**

In `agents/tools/_db.py`, in `insert_agent_output_sync`:

```python
        # Scoped per (project, output_type) to match the filename, which carries no agent.
        # Scoping the version per agent while the filename ignored the agent is what let one
        # agent's v1 land on another's.
        max_ver = conn.execute(
            "SELECT MAX(version) FROM agent_outputs"
            " WHERE project_id=? AND output_type=?",
            (project_id, output_type),
        ).fetchone()[0]
        version = (max_ver or 0) + 1
```

and the supersession:

```python
        conn.execute(
            "UPDATE agent_outputs SET is_current=0"
            " WHERE project_id=? AND output_type=?",
            (project_id, output_type),
        )
```

- [ ] **Step 4: Run everything and commit**

Run: `./venv/bin/pytest -q --ignore=tests/integration` - expect 1027 passed.
Run: `cd ui && npx vitest run && npx tsc --noEmit`.

```bash
git add agents/tools/_db.py tests/test_output_versioning.py
git commit -m "fix(outputs): version and current scopes match the filename"
```

---

### Task 4: Lineage is captured from what a run actually read

**Files:**
- Modify: `api/database.py`, `agents/tools/sqlite_state.py`, `agents/tools/chroma_query.py`, `agents/tools/_db.py`
- Create: `api/services/lineage_service.py`
- Test: `tests/test_lineage_capture.py` (create)

**Interfaces:**
- Produces: `record_run_input_sync(slug, run_id, output_id)`; `record_run_document_sync(slug, run_id, doc_id)`; `link_output_sync(slug, run_id, output_id)`; and in `lineage_service`, `fetch_lineage(conn, *, project_id) -> list[dict]`. Task 5 consumes `fetch_lineage`.

**Why:** `agent_outputs` records what was written and by whom, and nothing about inputs. "Maya's scripts were built from a value chain since superseded" is not a question the system can answer, and it has been true more than once without anything noticing.

Captured from the reads the tools actually serve, so it needs no agent cooperation and cannot be misreported. Citations come from the same mechanism rather than by parsing agent prose - an agent's own `source` field makes a claim checkable by a human; the captured edge is what the graph is built from.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lineage_capture.py`:

```python
# tests/test_lineage_capture.py
"""What an output was built from, taken from what its run actually read."""
import pytest
import pytest_asyncio

from api.database import get_connection, insert_project
from api.services.lineage_service import fetch_lineage

SLUG = "lineage-test"


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield tmp_path
    get_settings.cache_clear()


async def _output(conn, agent, output_type, version, is_current=1):
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
        " version, is_current, review_status) VALUES (1,?,?,?,?,?,'pending')",
        (agent, output_type, f"{output_type}_v{version}.json", version, is_current),
    )
    await conn.commit()
    return cur.lastrowid


@pytest.mark.asyncio
async def test_an_output_links_to_every_input_its_run_read(project):
    from agents.tools._db import link_output_sync, record_run_input_sync

    async with get_connection(SLUG) as conn:
        model = await _output(conn, "value_chain_mapper", "value_chain_model", 8)
        levers = await _output(conn, "value_lever_analyst", "value_levers", 2)

    record_run_input_sync(SLUG, 20, model)
    record_run_input_sync(SLUG, 20, levers)

    async with get_connection(SLUG) as conn:
        scripts = await _output(conn, "interaction_designer", "interview_scripts", 5)
    link_output_sync(SLUG, 20, scripts)

    async with get_connection(SLUG) as conn:
        rows = {r["output_id"]: r for r in await fetch_lineage(conn, project_id=1)}
    assert sorted(rows[scripts]["input_output_ids"]) == sorted([model, levers])


@pytest.mark.asyncio
async def test_reading_the_same_input_twice_makes_one_edge(project):
    from agents.tools._db import link_output_sync, record_run_input_sync

    async with get_connection(SLUG) as conn:
        model = await _output(conn, "value_chain_mapper", "value_chain_model", 8)
    record_run_input_sync(SLUG, 21, model)
    record_run_input_sync(SLUG, 21, model)

    async with get_connection(SLUG) as conn:
        scripts = await _output(conn, "interaction_designer", "interview_scripts", 6)
    link_output_sync(SLUG, 21, scripts)

    async with get_connection(SLUG) as conn:
        rows = {r["output_id"]: r for r in await fetch_lineage(conn, project_id=1)}
    assert rows[scripts]["input_output_ids"] == [model]


@pytest.mark.asyncio
async def test_an_output_that_read_nothing_has_no_ancestry(project):
    """Morgan works from documents. No state ancestry is the honest answer, and it must not
    read as an error or as freshness."""
    from agents.tools._db import link_output_sync

    async with get_connection(SLUG) as conn:
        levers = await _output(conn, "value_lever_analyst", "value_levers", 2)
    link_output_sync(SLUG, 22, levers)

    async with get_connection(SLUG) as conn:
        rows = {r["output_id"]: r for r in await fetch_lineage(conn, project_id=1)}
    assert rows[levers]["input_output_ids"] == []


@pytest.mark.asyncio
async def test_documents_retrieved_are_recorded_as_citations(project):
    from agents.tools._db import link_output_sync, record_run_document_sync

    async with get_connection(SLUG) as conn:
        await conn.execute(
            "INSERT INTO client_documents (id, project_id, filename, original_name,"
            " file_path, content_type, size_bytes) VALUES (3,1,'h.pdf','Annual.pdf','x','p',1)"
        )
        await conn.commit()
        levers = await _output(conn, "value_lever_analyst", "value_levers", 2)

    record_run_document_sync(SLUG, 22, 3)
    link_output_sync(SLUG, 22, levers)

    async with get_connection(SLUG) as conn:
        rows = {r["output_id"]: r for r in await fetch_lineage(conn, project_id=1)}
    assert rows[levers]["document_ids"] == [3]


@pytest.mark.asyncio
async def test_a_later_read_does_not_attach_to_an_earlier_write(project):
    """Links are taken at write time. Attaching everything a run ever read to everything it
    ever wrote would claim an output was built from something written after it."""
    from agents.tools._db import link_output_sync, record_run_input_sync

    async with get_connection(SLUG) as conn:
        first = await _output(conn, "interaction_designer", "interview_scripts", 7)
    link_output_sync(SLUG, 23, first)

    async with get_connection(SLUG) as conn:
        model = await _output(conn, "value_chain_mapper", "value_chain_model", 9)
    record_run_input_sync(SLUG, 23, model)

    async with get_connection(SLUG) as conn:
        rows = {r["output_id"]: r for r in await fetch_lineage(conn, project_id=1)}
    assert rows[first]["input_output_ids"] == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_lineage_capture.py -q`
Expected: FAIL - `No module named 'api.services.lineage_service'`

- [ ] **Step 3: Add the tables**

In `api/database.py`, registered on connection open:

```python
async def _migrate_lineage(conn: aiosqlite.Connection) -> None:
    """What a run read, and what each output was built from.

    run_inputs and run_documents accumulate during a run; output_lineage and
    output_citations are the durable edges, written when an output is created. Keeping both
    means a run's reads survive a process restart mid-run, and the edges do not depend on
    anything being held in memory.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS run_inputs (
            run_id    INTEGER NOT NULL,
            output_id INTEGER NOT NULL REFERENCES agent_outputs(id),
            PRIMARY KEY (run_id, output_id)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS run_documents (
            run_id INTEGER NOT NULL,
            doc_id INTEGER NOT NULL REFERENCES client_documents(id),
            PRIMARY KEY (run_id, doc_id)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS output_lineage (
            output_id       INTEGER NOT NULL REFERENCES agent_outputs(id),
            input_output_id INTEGER NOT NULL REFERENCES agent_outputs(id),
            PRIMARY KEY (output_id, input_output_id)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS output_citations (
            output_id INTEGER NOT NULL REFERENCES agent_outputs(id),
            doc_id    INTEGER NOT NULL REFERENCES client_documents(id),
            PRIMARY KEY (output_id, doc_id)
        )
    """)
    await conn.commit()
```

- [ ] **Step 4: Record reads and link writes**

In `agents/tools/_db.py`, three sync helpers using `INSERT OR IGNORE` so a repeated read makes one edge:

```python
def record_run_input_sync(slug: str, run_id: int, output_id: int) -> None:
    if not run_id or not output_id:
        return
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO run_inputs (run_id, output_id) VALUES (?,?)",
            (run_id, output_id),
        )
        conn.commit()


def record_run_document_sync(slug: str, run_id: int, doc_id: int) -> None:
    if not run_id or not doc_id:
        return
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO run_documents (run_id, doc_id) VALUES (?,?)",
            (run_id, doc_id),
        )
        conn.commit()


def link_output_sync(slug: str, run_id: int, output_id: int) -> None:
    """Link a new output to everything its run has read SO FAR.

    Taken at write time rather than at run end: a read that happens afterwards belongs to
    whatever is written next, and attaching it here would claim this output was built from
    something that did not exist when it was made.
    """
    if not output_id:
        return
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO output_lineage (output_id, input_output_id)"
            " SELECT ?, output_id FROM run_inputs WHERE run_id=? AND output_id != ?",
            (output_id, run_id, output_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO output_citations (output_id, doc_id)"
            " SELECT ?, doc_id FROM run_documents WHERE run_id=?",
            (output_id, run_id),
        )
        conn.commit()
```

Call `link_output_sync(self.slug, self.run_id, new_output_id)` at the end of `SQLiteStateTool`'s successful write, using the row id `insert_agent_output_sync` returns.

On the read branch, the output id for the file just resolved is needed. Add to `_db.py`:

```python
def output_id_for_path_sync(slug: str, file_path: str) -> int | None:
    """The agent_outputs row for a resolved output file, or None.

    None is normal rather than exceptional: files written by hand, or before versioning
    existed, have no row. A read of one records no lineage edge, which is honest.
    """
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        row = conn.execute(
            "SELECT id FROM agent_outputs WHERE file_path=? ORDER BY id DESC LIMIT 1",
            (file_path,),
        ).fetchone()
    return row[0] if row else None
```

and in `SQLiteStateTool._run`'s read branch, after resolving the path:

```python
            resolved = latest_output_path(file_path)
            if resolved is not None:
                try:
                    record_run_input_sync(
                        self.slug, self.run_id, output_id_for_path_sync(self.slug, str(resolved))
                    )
                except Exception:
                    # A read must never fail because its bookkeeping did - the agent needs
                    # the content, and a missing edge degrades the graph rather than the run.
                    pass
```

In `chroma_query.py`, after building citations, call `record_run_document_sync(self.slug, self.run_id, doc_id)` for each distinct `doc_id` served, and add `run_id: int = 0` as a tool field. In `registry.py`, pass `run_id=run_id` to every `ChromaQueryTool(...)`.

- [ ] **Step 5: Write the query service**

Create `api/services/lineage_service.py`:

```python
# api/services/lineage_service.py
"""What each output was built from, and whether it has been overtaken."""
from __future__ import annotations


async def fetch_lineage(conn, *, project_id: int) -> list[dict]:
    """One row per output, with its state ancestry and its cited documents."""
    async with conn.execute(
        "SELECT id, agent_name, output_type, version, is_current, review_status, created_at"
        " FROM agent_outputs WHERE project_id=? ORDER BY id",
        (project_id,),
    ) as cur:
        outputs = [dict(row) async for row in cur]

    async with conn.execute(
        "SELECT output_id, input_output_id FROM output_lineage"
    ) as cur:
        edges = [(r[0], r[1]) async for r in cur]
    async with conn.execute("SELECT output_id, doc_id FROM output_citations") as cur:
        citations = [(r[0], r[1]) async for r in cur]

    by_output: dict[int, list[int]] = {}
    for output_id, input_id in edges:
        by_output.setdefault(output_id, []).append(input_id)
    docs: dict[int, list[int]] = {}
    for output_id, doc_id in citations:
        docs.setdefault(output_id, []).append(doc_id)

    for output in outputs:
        output["input_output_ids"] = sorted(by_output.get(output["id"], []))
        output["document_ids"] = sorted(docs.get(output["id"], []))
    return outputs
```

- [ ] **Step 6: Run, mutation-test, commit**

Run: `./venv/bin/pytest tests/test_lineage_capture.py -q` - expect 5 passed.
Run both suites - expect 1032 backend passed.

```bash
# The link must be taken at write time, not over the whole run.
cp agents/tools/_db.py /tmp/db.bak
./venv/bin/python -c "
import pathlib;p=pathlib.Path('agents/tools/_db.py');s=p.read_text()
p.write_text(s.replace('WHERE run_id=? AND output_id != ?','WHERE run_id=? AND output_id != ? OR 1=1'))"
./venv/bin/pytest tests/test_lineage_capture.py -q   # expect failures
cp /tmp/db.bak agents/tools/_db.py
```

```bash
git add api/database.py api/services/lineage_service.py agents/tools/_db.py \
  agents/tools/sqlite_state.py agents/tools/chroma_query.py agents/tools/registry.py \
  tests/test_lineage_capture.py
git commit -m "feat(lineage): outputs record what their run read"
```

---

### Task 5: Staleness is derived

**Files:**
- Modify: `api/services/lineage_service.py`
- Test: `tests/test_staleness.py` (create)

**Interfaces:**
- Consumes: `fetch_lineage` from Task 4.
- Produces: `staleness(outputs: list[dict], approvals: dict[str, int]) -> dict[int, dict]`, pure, returning `{output_id: {"state": "fresh"|"stale"|"unknown", "behind": [{"output_type": str, "built_from": int, "approved": int}]}}`. Task 6 renders it.

**Why:** an output is stale when an input it was built from has a newer approved version. Measured against approval rather than the last write, because agents write several versions inside one run - Alex wrote `value_chain_tree` v7, v8 and v9 within ninety seconds - and flagging on every write would make downstream work flash stale three times during one upstream run.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_staleness.py`:

```python
# tests/test_staleness.py
"""Stale means: an input this was built from has been approved again since.

Pure, so the rule can be tested without a database and cannot quietly depend on one.
"""
from api.services.lineage_service import staleness

MODEL_V8 = {"id": 1, "output_type": "value_chain_model", "version": 8, "input_output_ids": [],
            "document_ids": []}
MODEL_V9 = {"id": 2, "output_type": "value_chain_model", "version": 9, "input_output_ids": [],
            "document_ids": []}
SCRIPTS = {"id": 3, "output_type": "interview_scripts", "version": 5,
           "input_output_ids": [1], "document_ids": []}
LEVERS = {"id": 4, "output_type": "value_levers", "version": 2,
          "input_output_ids": [], "document_ids": [3]}


def test_built_from_the_latest_approved_input_is_fresh():
    result = staleness([MODEL_V8, SCRIPTS], approvals={"value_chain_model": 8})
    assert result[3]["state"] == "fresh"


def test_a_newer_approved_input_makes_it_stale():
    result = staleness([MODEL_V8, MODEL_V9, SCRIPTS], approvals={"value_chain_model": 9})
    assert result[3]["state"] == "stale"
    assert result[3]["behind"] == [
        {"output_type": "value_chain_model", "built_from": 8, "approved": 9}
    ]


def test_a_newer_but_unapproved_input_does_not():
    """Alex wrote tree v7, v8 and v9 inside ninety seconds. Those are working state, and
    flagging each would make downstream work flash stale three times in one run."""
    result = staleness([MODEL_V8, MODEL_V9, SCRIPTS], approvals={"value_chain_model": 8})
    assert result[3]["state"] == "fresh"


def test_an_output_with_no_ancestry_is_unknown_not_fresh():
    """Morgan's levers have document ancestry and no state ancestry, and every output written
    before lineage existed has neither. Calling those fresh would assert something nothing
    knows."""
    result = staleness([LEVERS], approvals={})
    assert result[4]["state"] == "unknown"


def test_staleness_is_reported_for_every_stale_input_not_just_the_first():
    two_inputs = {**SCRIPTS, "input_output_ids": [1, 5]}
    other = {"id": 5, "output_type": "value_levers", "version": 1,
             "input_output_ids": [], "document_ids": []}
    result = staleness(
        [MODEL_V8, other, two_inputs],
        approvals={"value_chain_model": 9, "value_levers": 3},
    )
    assert len(result[3]["behind"]) == 2
```

- [ ] **Step 2: Run to verify it fails, then implement**

Run: `./venv/bin/pytest tests/test_staleness.py -q`
Expected: FAIL - `cannot import name 'staleness'`

Add to `api/services/lineage_service.py`:

```python
def staleness(outputs: list[dict], approvals: dict[str, int]) -> dict[int, dict]:
    """Which outputs have been overtaken by a newer approved input.

    `approvals` maps output_type to the highest approved version. Measured against approval
    rather than the newest write: agents write several versions inside one run, and those are
    working state rather than deliverables.

    An output with no recorded ancestry is `unknown`, never `fresh` - outputs written before
    lineage existed know nothing about their inputs, and claiming freshness for them would
    assert something nothing knows.
    """
    by_id = {o["id"]: o for o in outputs}
    result: dict[int, dict] = {}

    for output in outputs:
        inputs = output.get("input_output_ids") or []
        if not inputs:
            result[output["id"]] = {"state": "unknown", "behind": []}
            continue

        behind = []
        for input_id in inputs:
            source = by_id.get(input_id)
            if source is None:
                continue
            approved = approvals.get(source["output_type"])
            if approved is not None and approved > source["version"]:
                behind.append({
                    "output_type": source["output_type"],
                    "built_from": source["version"],
                    "approved": approved,
                })

        result[output["id"]] = {
            "state": "stale" if behind else "fresh",
            "behind": behind,
        }
    return result
```

- [ ] **Step 3: Run, mutation-test, commit**

Run: `./venv/bin/pytest tests/test_staleness.py -q` - expect 5 passed.

```bash
cp api/services/lineage_service.py /tmp/ls.bak
# M1: no ancestry reported as fresh
./venv/bin/python -c "
import pathlib;p=pathlib.Path('api/services/lineage_service.py');s=p.read_text()
p.write_text(s.replace('{\"state\": \"unknown\", \"behind\": []}','{\"state\": \"fresh\", \"behind\": []}'))"
./venv/bin/pytest tests/test_staleness.py -q   # expect 1 failed
cp /tmp/ls.bak api/services/lineage_service.py
# M2: measured against any newer version rather than approval
./venv/bin/python -c "
import pathlib;p=pathlib.Path('api/services/lineage_service.py');s=p.read_text()
p.write_text(s.replace('            if approved is not None and approved > source[\"version\"]:','            if True:'))"
./venv/bin/pytest tests/test_staleness.py -q   # expect failures
cp /tmp/ls.bak api/services/lineage_service.py
```

```bash
git add api/services/lineage_service.py tests/test_staleness.py
git commit -m "feat(lineage): staleness derived against the last approved input"
```

---

### Task 6: The lineage endpoint

**Files:**
- Modify: `api/routers/runs.py`, `api/services/lineage_service.py`
- Test: `tests/test_lineage_api.py` (create)

**Interfaces:**
- Consumes: `fetch_lineage`, `staleness`.
- Produces: `GET /projects/{slug}/lineage` returning `{"outputs": [...], "documents": {id: original_name}, "blocked_writes": [...]}`. Task 7 renders it.

**Why:** the tab needs one call carrying outputs, their ancestry, their staleness, the document names to render citations, and the blocked writes - which belong here because a blocked write is a lineage event: work that tried to attach itself to an artefact it did not own.

- [ ] **Step 1: Write the failing test**

Create `tests/test_lineage_api.py`:

```python
# tests/test_lineage_api.py
"""One call carrying everything the Lineage tab renders."""
import pytest

SLUG = "lineage-api-test"
PROJECT = {
    "client_slug": SLUG, "llm_mode": "standard", "sector": "utilities",
    "stakeholder_groups": [], "value_stream_labels": [], "crews_enabled": ["requirements"],
    "review_gates": True, "slack_channel": "",
}


@pytest.mark.asyncio
async def test_lineage_returns_outputs_with_state(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.get(f"/projects/{SLUG}/lineage")
    assert resp.status_code == 200
    body = resp.json()
    assert "outputs" in body and "documents" in body and "blocked_writes" in body


@pytest.mark.asyncio
async def test_documents_are_returned_by_name_not_by_stored_filename(client):
    """The stored name is a hash. Returning it would make every citation unreadable, which is
    the defect this whole thread started from."""
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection

    async with get_connection(SLUG) as conn:
        await conn.execute(
            "INSERT INTO client_documents (id, project_id, filename, original_name,"
            " file_path, content_type, size_bytes) VALUES (3,1,'d89a.pdf','Annual.pdf','x','p',1)"
        )
        await conn.commit()

    body = (await client.get(f"/projects/{SLUG}/lineage")).json()
    assert body["documents"]["3"] == "Annual.pdf"


@pytest.mark.asyncio
async def test_an_unknown_project_is_404(client):
    resp = await client.get("/projects/no-such-project/lineage")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify it fails, then add the endpoint**

Run: `./venv/bin/pytest tests/test_lineage_api.py -q`
Expected: FAIL - 404 on a project that exists.

Add to `api/services/lineage_service.py`:

```python
async def approved_versions(conn, *, project_id: int) -> dict[str, int]:
    """The highest approved version per output type."""
    async with conn.execute(
        "SELECT output_type, MAX(version) FROM agent_outputs"
        " WHERE project_id=? AND review_status='approved' GROUP BY output_type",
        (project_id,),
    ) as cur:
        return {row[0]: row[1] async for row in cur}
```

and in `api/routers/runs.py`:

```python
@router.get("/{slug}/lineage")
async def get_lineage(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    if not get_db_path(slug).exists():
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

        outputs = await fetch_lineage(conn, project_id=project["id"])
        approvals = await approved_versions(conn, project_id=project["id"])
        blocked = await fetch_blocked_writes(conn)
        async with conn.execute(
            "SELECT id, original_name FROM client_documents WHERE project_id=?",
            (project["id"],),
        ) as cur:
            documents = {str(row[0]): row[1] async for row in cur}

    states = staleness(outputs, approvals)
    for output in outputs:
        output.update(states[output["id"]])
    return {"outputs": outputs, "documents": documents, "blocked_writes": blocked}
```

- [ ] **Step 3: Run and commit**

Run: `./venv/bin/pytest tests/test_lineage_api.py -q` - expect 3 passed.
Run both suites - expect 1040 backend passed.

```bash
git add api/routers/runs.py api/services/lineage_service.py tests/test_lineage_api.py
git commit -m "feat(lineage): one endpoint for the lineage view"
```

---

### Task 7: The Lineage tab

**Files:**
- Modify: `ui/src/pages/Runs.tsx`, `ui/src/api/endpoints.ts`, `ui/src/types.ts`
- Create: `ui/src/components/LineageView.tsx`
- Test: `ui/src/__tests__/LineageView.test.tsx` (create)

**Interfaces:**
- Consumes: `GET /projects/{slug}/lineage`.

**Why:** the record is only useful if a person can see it. The Runs page has no tabs today - it is a flat list of runs - so it gains a tab bar following the pattern already in `Documents.tsx`.

- [ ] **Step 1: Write the failing test**

Create `ui/src/__tests__/LineageView.test.tsx`:

```typescript
// ui/src/__tests__/LineageView.test.tsx
// Lineage is only worth recording if a reader can act on it. The case that matters is the
// one that went unnoticed for days: scripts built from a value chain since superseded.
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import LineageView from '../components/LineageView'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    lineage: vi.fn().mockResolvedValue({
      outputs: [
        { id: 1, agent_name: 'value_chain_mapper', output_type: 'value_chain_model',
          version: 9, is_current: 1, state: 'unknown', behind: [],
          input_output_ids: [], document_ids: [] },
        { id: 3, agent_name: 'interaction_designer', output_type: 'interview_scripts',
          version: 5, is_current: 1, state: 'stale',
          behind: [{ output_type: 'value_chain_model', built_from: 8, approved: 9 }],
          input_output_ids: [1], document_ids: [] },
        { id: 4, agent_name: 'value_lever_analyst', output_type: 'value_levers',
          version: 2, is_current: 1, state: 'unknown', behind: [],
          input_output_ids: [], document_ids: [3] },
      ],
      documents: { '3': 'SPUK_2025_Annual_Accounts.pdf' },
      blocked_writes: [
        { id: 1, agent_name: 'interaction_designer', key: 'value_chain_registry',
          owner: 'value_chain_mapper', reason: 'not the owner',
          attempted_at: '2026-08-04T15:53:29' },
      ],
    }),
  },
}))

function Wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <LineageView slug="acme" />
    </QueryClientProvider>
  )
}

describe('LineageView', () => {
  it('marks a stale output with the version it was built from', async () => {
    render(<Wrapper />)
    expect(await screen.findByTestId('lineage-3')).toHaveTextContent(/stale/i)
    expect(screen.getByTestId('lineage-3')).toHaveTextContent(/built from v8/i)
    expect(screen.getByTestId('lineage-3')).toHaveTextContent(/v9/)
  })

  it('does not mark an output with no ancestry as stale', async () => {
    // Morgan's levers have document ancestry and no state ancestry. Rendering that as stale
    // would cry wolf on every document-driven output in the project.
    render(<Wrapper />)
    expect(await screen.findByTestId('lineage-4')).not.toHaveTextContent(/stale/i)
  })

  it('names cited documents so the citation can be checked', async () => {
    render(<Wrapper />)
    expect(await screen.findByTestId('lineage-4'))
      .toHaveTextContent(/SPUK_2025_Annual_Accounts\.pdf/)
  })

  it('shows a blocked write as an upstream finding', async () => {
    render(<Wrapper />)
    const blocked = await screen.findByTestId('blocked-writes')
    expect(blocked).toHaveTextContent(/interaction_designer/)
    expect(blocked).toHaveTextContent(/value_chain_registry/)
  })
})
```

- [ ] **Step 2: Run to verify it fails, then build the view**

Run: `cd ui && npx vitest run src/__tests__/LineageView.test.tsx`
Expected: FAIL - `LineageView` does not exist.

Add to `ui/src/api/endpoints.ts`:

```typescript
  lineage: (slug: string): Promise<LineageResponse> =>
    apiClient.get<LineageResponse>(`/projects/${slug}/lineage`).then((r) => r.data),
```

Add to `ui/src/types.ts`:

```typescript
export interface LineageOutput {
  id: number
  agent_name: string
  output_type: string
  version: number
  is_current: number
  state: 'fresh' | 'stale' | 'unknown'
  behind: { output_type: string; built_from: number; approved: number }[]
  input_output_ids: number[]
  document_ids: number[]
}

export interface LineageResponse {
  outputs: LineageOutput[]
  documents: Record<string, string>
  blocked_writes: {
    id: number; agent_name: string; key: string; owner: string | null
    reason: string; attempted_at: string
  }[]
}
```

Create `ui/src/components/LineageView.tsx`:

```typescript
// ui/src/components/LineageView.tsx
// What each output was built from, and whether it has been overtaken.
//
// The case this exists for went unnoticed for days: interview scripts built from a value
// chain that had since been approved again, with nothing anywhere saying so.
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, FileText, HelpCircle, ShieldAlert } from 'lucide-react'

import { projectsApi } from '../api/endpoints'
import type { LineageOutput, LineageResponse } from '../types'

function StateBadge({ output }: { output: LineageOutput }) {
  if (output.state === 'stale') {
    return (
      <span className="flex items-center gap-1 text-xs text-red-600">
        <AlertTriangle size={12} /> stale
      </span>
    )
  }
  if (output.state === 'fresh') {
    return (
      <span className="flex items-center gap-1 text-xs text-emerald-600">
        <CheckCircle2 size={12} /> current
      </span>
    )
  }
  // Unknown is not a failure. Outputs written before lineage existed know nothing about
  // their inputs, and an output built only from documents never will.
  return (
    <span className="flex items-center gap-1 text-xs text-muted">
      <HelpCircle size={12} /> no recorded ancestry
    </span>
  )
}

export default function LineageView({ slug }: { slug: string }) {
  const { data } = useQuery<LineageResponse>({
    queryKey: ['lineage', slug],
    queryFn: () => projectsApi.lineage(slug),
  })

  if (!data) return <p className="text-xs text-muted">Loading lineage…</p>

  const current = data.outputs.filter((o) => o.is_current)

  return (
    <div className="space-y-4">
      <ul className="space-y-1">
        {current.map((o) => (
          <li
            key={o.id}
            data-testid={`lineage-${o.id}`}
            className="rounded-lg bg-surface-card px-4 py-3"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm text-primary truncate">
                  {o.output_type} <span className="text-muted">v{o.version}</span>
                </p>
                <p className="text-xs text-secondary">{o.agent_name}</p>
              </div>
              <StateBadge output={o} />
            </div>

            {o.behind.map((b) => (
              <p key={b.output_type} className="text-xs text-red-600 mt-1">
                built from v{b.built_from} of {b.output_type}, now approved at v{b.approved}
              </p>
            ))}

            {o.document_ids.length > 0 && (
              <p className="text-xs text-secondary mt-1 flex items-center gap-1">
                <FileText size={11} />
                {o.document_ids.map((id) => data.documents[String(id)] ?? `doc ${id}`).join(', ')}
              </p>
            )}
          </li>
        ))}
      </ul>

      {data.blocked_writes.length > 0 && (
        <section data-testid="blocked-writes" className="space-y-1">
          <h3 className="text-xs font-bold text-muted uppercase tracking-widest">
            Blocked writes
          </h3>
          {/* Worded as an upstream finding. An agent reaching for another's artefact is
              usually a correct diagnosis of something missing, not misbehaviour. */}
          <p className="text-xs text-secondary">
            An agent tried to write an output it does not own. This usually means something it
            needed was missing upstream.
          </p>
          {data.blocked_writes.map((b) => (
            <p key={b.id} className="text-xs text-primary flex items-center gap-1">
              <ShieldAlert size={11} className="text-amber-500" />
              {b.agent_name} tried to write {b.key}
              {b.owner ? `, owned by ${b.owner}` : ', which no agent owns'}
            </p>
          ))}
        </section>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Add the tab to Runs**

In `ui/src/pages/Runs.tsx`, add `const [activeTab, setActiveTab] = useState<'runs' | 'lineage'>('runs')`
and a tab bar following the `tabCls` pattern in `Documents.tsx`, rendering `<LineageView slug={slug} />`
for the lineage tab.

- [ ] **Step 4: Run both suites and commit**

Run: `cd ui && npx vitest run && npx tsc --noEmit` - expect 358 passed, tsc silent.
Run: `./venv/bin/pytest -q --ignore=tests/integration` - expect 1040 passed.

```bash
git add ui/src/components/LineageView.tsx ui/src/pages/Runs.tsx ui/src/api/endpoints.ts \
  ui/src/types.ts ui/src/__tests__/LineageView.test.tsx
git commit -m "feat(ui): a Lineage tab on the Runs page"
```

---

### Task 8: Repair sp-gs-am

**Files:**
- Create: `scripts/repair_registry_current.py`
- Test: `tests/test_repair_registry_current.py` (create)

**Interfaces:**
- Produces: `repair_duplicate_current(conn, *, output_type) -> int`, returning rows corrected.

**Why:** two rows claim to be `is_current` for `value_chain_registry` in `sp-gs-am` - Alex's v5 and Maya's v1 - so "the current registry" is ambiguous. Task 3 stops it recurring and repairs nothing already broken.

Alex's original `value_chain_registry_v1.json` is **not recoverable**: `.gitignore` line 25 excludes `projects/*`. The loss is bounded - the registry's succession rules forbid dropping an id, and v5 holds every id v2 recorded, so no id meaning was lost. What is gone is the audit record of what the ledger said on 1 August. Maya's file stays on disk under its own name: deleting it would destroy the only evidence of what happened.

- [ ] **Step 1: Write the failing test**

Create `tests/test_repair_registry_current.py`:

```python
# tests/test_repair_registry_current.py
"""Exactly one row may claim to be the current version of an output type."""
import pytest
import pytest_asyncio

from api.database import get_connection, insert_project
from scripts.repair_registry_current import repair_duplicate_current

SLUG = "repair-test"


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
        for agent, version in (("value_chain_mapper", 5), ("interaction_designer", 1)):
            await conn.execute(
                "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
                " version, is_current, review_status) VALUES (1,?,?,?,?,1,'pending')",
                (agent, "value_chain_registry", f"r_v{version}.json", version),
            )
        await conn.commit()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_highest_version_stays_current(project):
    async with get_connection(SLUG) as conn:
        corrected = await repair_duplicate_current(conn, output_type="value_chain_registry")
        rows = await conn.execute_fetchall(
            "SELECT agent_name, version FROM agent_outputs"
            " WHERE output_type='value_chain_registry' AND is_current=1"
        )
    assert corrected == 1
    assert [tuple(r) for r in rows] == [("value_chain_mapper", 5)]


@pytest.mark.asyncio
async def test_running_it_twice_changes_nothing_further(project):
    async with get_connection(SLUG) as conn:
        await repair_duplicate_current(conn, output_type="value_chain_registry")
        second = await repair_duplicate_current(conn, output_type="value_chain_registry")
    assert second == 0
```

- [ ] **Step 2: Run to verify it fails, then write the repair**

Create `scripts/repair_registry_current.py`:

```python
# scripts/repair_registry_current.py
"""Leave exactly one current row per output type.

Version numbering and is_current were scoped per agent while filenames were not, so a second
agent writing the same output type produced a second row also claiming to be current. The
highest version wins, because that is what latest_output_path already resolves to on disk -
the database is being brought into line with what every reader already sees.
"""
from __future__ import annotations


async def repair_duplicate_current(conn, *, output_type: str) -> int:
    """Clear is_current from every row but the highest version. Returns rows corrected."""
    cur = await conn.execute(
        "UPDATE agent_outputs SET is_current=0"
        " WHERE output_type=? AND is_current=1 AND version < ("
        "   SELECT MAX(version) FROM agent_outputs WHERE output_type=? AND is_current=1)",
        (output_type, output_type),
    )
    await conn.commit()
    return cur.rowcount
```

- [ ] **Step 3: Run it against the live project and report**

```bash
./venv/bin/pytest tests/test_repair_registry_current.py -q   # expect 2 passed
./venv/bin/python -c "
import asyncio
from api.database import get_connection
from scripts.repair_registry_current import repair_duplicate_current

async def main():
    async with get_connection('sp-gs-am') as conn:
        n = await repair_duplicate_current(conn, output_type='value_chain_registry')
        rows = await conn.execute_fetchall(
            \"SELECT agent_name, version FROM agent_outputs\"
            \" WHERE output_type='value_chain_registry' AND is_current=1\")
        print('corrected:', n, '| current now:', [tuple(r) for r in rows])
asyncio.run(main())
"
```

Expected: `corrected: 1 | current now: [('value_chain_mapper', 5)]`. A count of zero means the
repair did not run rather than that there was nothing to do - check before accepting it.

- [ ] **Step 4: Commit**

```bash
git add scripts/repair_registry_current.py tests/test_repair_registry_current.py
git commit -m "fix(outputs): one current row per output type in sp-gs-am"
```

---

## After the last task

Restart the API server. Migrations run on connection open, so a server started before Tasks 2
and 4 has none of the new tables.

Lineage begins from the next run. Existing outputs have no recorded ancestry and will read as
`unknown`, which is the honest answer for them - nothing knows what they were built from.
