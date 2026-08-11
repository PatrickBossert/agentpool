# Maya: One Interview Per Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Maya produce one interview script for every value chain node, across as many runs as it takes, with each run adding only what is missing and never disturbing what exists.

**Architecture:** Three mechanisms, all extending patterns already in the codebase. A coverage validator beside `tree_validation` and `anchor_validation`, reporting into the same warning surface. A cross-check in the scripts validator so the script registry - which is already authoritative on its own door - is consulted on the door that actually carries the scripts. And a change to Maya's task so she reads what exists before generating.

**Tech Stack:** Python 3.13, CrewAI, aiosqlite, pytest + pytest-asyncio (`asyncio_mode = strict`), React 18 + TypeScript + Vitest.

**Spec:** `docs/superpowers/specs/2026-08-11-maya-full-node-coverage-design.md`

## Global Constraints

- **British English throughout** - `-ise` not `-ize`, `-our` not `-or` (organise, behaviour, centre, artefact). Comments, docstrings, error messages, and UI copy.
- **Short en dash ` - ` with spaces in prose, never an em dash.**
- **Oxford comma** in lists of three or more.
- **No emoji in UI**; Lucide React icons only. Tailwind `brand`/`surface`/`text-*` tokens, **never `sky-*` or `blue-*`**.
- **Python 3.13 only.** Use `./venv/bin/pytest` and `./venv/bin/python`, never system Python.
- **Async fixtures must use `@pytest_asyncio.fixture`** - `asyncio_mode = strict`.
- **`projects` has no `name` column.** Insert with `(slug, sector)` or `(slug, llm_mode, sector, config_json)`.
- **`agent_outputs` has no `run_id` column**; `interview_sessions.stakeholder_id` has an enforced foreign key.
- **Run the backend suite twice before believing it is green.** `tests/conftest.py` points `DATABASE_DIR` at a fixed `/tmp/agentpool_test` that persists between runs.
- **Never resolve an output by filename.** Use `current_output_path(slug, output_type)` from `agents/tools/_db.py`.
- **Integration tests are opt-in** (`pytest -m integration`) and cost real credit. Nothing here needs them.
- **Do not restart the API server**, and run uvicorn without `--reload`.

**Existing machinery this plan extends - read before writing anything:**

| Thing | Where | Contract |
|---|---|---|
| `_VALIDATORS` | `agents/tools/sqlite_state.py:155` | key → `(parsed: dict, slug: str) -> list[str]`. A non-empty list **refuses** the write. |
| `_WARNERS` | `agents/tools/sqlite_state.py:194` | key → `(parsed: object, slug: str) -> list[dict]`. Runs **after** a successful write; records and lets it through. |
| `_WARNER_SOURCE` | `agents/tools/sqlite_state.py:201` | key → the `source` string recorded against each warning. |
| Warning dict | `api/services/anchor_validation.py:58` | `{"subject": str|None, "code": str, "measure": float|None, "detail": str}` |
| `_current_registry(slug)` | `agents/tools/sqlite_state.py:57` | the current **value chain** registry as a dict |
| `_current_script_registry(slug)` | `agents/tools/sqlite_state.py:82` | the current **script** registry as a dict |
| `record_validation_warnings_sync` | `agents/tools/_db.py:350` | `(slug, run_id, source, warnings, *, complete=False)` |

---

## File Structure

**New files**

| File | Responsibility |
|---|---|
| `api/services/coverage_validation.py` | One pure function: which registry nodes have no script. Nothing else. |
| `tests/test_coverage_validation.py` | The validator, and the warning reaching the surface. |

**Modified files**

| File | Change |
|---|---|
| `agents/tools/sqlite_state.py` | Register the coverage warner; cross-check script ids in the scripts validator |
| `api/services/interview_script_model.py` | The script-id cross-check function |
| `agents/discovery/interaction_designer.py` | Read what exists; generate only what is missing; stop undeclared keys |
| `ui/src/components/tabs/MayaOutputExtra.tsx`, `ui/src/types.ts` | Split on `perspective`, render everything |
| `ui/src/components/AgentDetailPanel.tsx` | Badge counts displayed items |

---

## Task 1: The scripts door consults the script registry

The blocking fix. `validate_script_registry_succession` already refuses moving a registered `script_id` to a different node, but it runs from `_validate_interview_script_registry` - so it fires only on a write to the registry. `_validate_interview_scripts` checks that a script's anchor names a node the **value chain** registry holds and is at the right level, and never consults the **script** registry.

So a batch emitting `SC-005` against node `2.7` passes while `SC-005` is registered against `1.2`, and `_merge_with_current`'s `merged.update(parsed)` then overwrites `1.2`'s script. Nothing anchors a script id to a node today: `SC-005` is node `1.2` only because it was the fifth script emitted.

Everything else in this plan assumes re-running is safe. This is what makes it safe.

**Files:**
- Modify: `api/services/interview_script_model.py`, `agents/tools/sqlite_state.py` (`_validate_interview_scripts`)
- Test: `tests/test_interview_script_model.py`, `tests/test_sqlite_state_validation.py`

**Interfaces:**
- Consumes: `_current_script_registry(slug) -> dict` from `agents/tools/sqlite_state.py:82`
- Produces: `validate_scripts_against_script_registry(scripts: dict, script_registry: dict) -> list[str]`

- [ ] **Step 1: Write the failing unit test**

```python
# tests/test_interview_script_model.py  (append)
def test_a_script_id_may_not_move_to_another_node():
    """The registry says SC-005 is node 1.2. A batch filing it against 2.7 must be refused.

    validate_script_registry_succession already refuses this - on writes to the registry. The
    write that carries the scripts never consulted it, so the batch landed and the merge, which
    keys on script_id, overwrote 1.2's script with 2.7's content.
    """
    from api.services.interview_script_model import validate_scripts_against_script_registry
    registry = {"scripts": [{"id": "SC-005", "node_id": "1.2", "active": True}]}
    scripts = {"SC-005": {"script_id": "SC-005", "node_id": "2.7"}}
    problems = validate_scripts_against_script_registry(scripts, registry)
    assert len(problems) == 1
    assert "SC-005" in problems[0] and "1.2" in problems[0] and "2.7" in problems[0]


def test_an_unregistered_script_id_is_free():
    """Growth is free. A new id is how every script starts."""
    from api.services.interview_script_model import validate_scripts_against_script_registry
    registry = {"scripts": [{"id": "SC-005", "node_id": "1.2", "active": True}]}
    scripts = {"SC-090": {"script_id": "SC-090", "node_id": "3.4"}}
    assert validate_scripts_against_script_registry(scripts, registry) == []


def test_a_registered_id_kept_on_its_own_node_is_free():
    """Re-emitting a script for the node it already serves is a revision, not a move."""
    from api.services.interview_script_model import validate_scripts_against_script_registry
    registry = {"scripts": [{"id": "SC-005", "node_id": "1.2", "active": True}]}
    scripts = {"SC-005": {"script_id": "SC-005", "node_id": "1.2"}}
    assert validate_scripts_against_script_registry(scripts, registry) == []


def test_an_empty_script_registry_accepts_anything():
    """A first run has no registry, and must not be blocked by one it has not written yet."""
    from api.services.interview_script_model import validate_scripts_against_script_registry
    scripts = {"SC-001": {"script_id": "SC-001", "node_id": "0"}}
    assert validate_scripts_against_script_registry(scripts, {}) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_interview_script_model.py -k script_registry -v`
Expected: FAIL with `ImportError: cannot import name 'validate_scripts_against_script_registry'`

- [ ] **Step 3: Write the function**

In `api/services/interview_script_model.py`, beside `validate_scripts_against_registry`:

```python
def validate_scripts_against_script_registry(scripts: dict, script_registry: dict) -> list[str]:
    """Every script whose id is registered against a different node.

    The script registry is the ledger for script ids, and validate_script_registry_succession
    already holds writes to it to that contract. This is the same rule on the other door - the
    one that actually carries the scripts - because a rule enforced at one entrance is not
    enforced.

    It matters because _merge_with_current keys on script_id: an id that moves does not add a
    script, it silently replaces the one already filed under that id, and every stored answer
    citing it then resolves to the wrong instrument.

    An empty registry accepts anything, which is what a first run needs.
    """
    registered = {
        entry.get("id"): entry.get("node_id")
        for entry in script_registry.get("scripts", [])
    }
    if not registered:
        return []
    problems: list[str] = []
    for key, script in scripts.items():
        script_id = script.get("script_id") or key
        held = registered.get(script_id)
        if held is not None and script.get("node_id") != held:
            problems.append(
                f"script_id {script_id} is registered against node {held} and this batch files "
                f"it against {script.get('node_id')} - take an unused id for the new script, "
                f"because the merge keys on script_id and stored answers cite it"
            )
    return problems
```

- [ ] **Step 4: Run to verify it passes**

Run: `./venv/bin/pytest tests/test_interview_script_model.py -k script_registry -v`
Expected: PASS, four tests

- [ ] **Step 5: Write the failing test for the door**

The function existing proves nothing. This asserts the write refuses.

```python
# tests/test_sqlite_state_validation.py  (append)
@pytest.mark.asyncio
async def test_a_scripts_write_moving_a_registered_id_is_refused(seeded_project):
    """Driven through SQLiteStateTool's write, not by calling the validator.

    A guard the write does not consult is worthless, which is the whole finding this task
    exists for - the rule was already written and already enforced on the other door.
    """
    import json
    from agents.tools.sqlite_state import SQLiteStateTool
    slug = seeded_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=0)

    tool._run(operation="write", key="interview_script_registry",
              agent_name="interaction_designer",
              value=json.dumps({"scripts": [
                  {"id": "SC-005", "node_id": "1.2", "level": "L2",
                   "relationship": "internal", "node_label": "Portfolio", "active": True}]}))

    result = tool._run(operation="write", key="interview_scripts",
                       agent_name="interaction_designer",
                       value=json.dumps({"SC-005": {
                           "script_id": "SC-005", "node_id": "2.7", "level": "L2",
                           "relationship": "internal", "node_label": "Elsewhere",
                           "sections": []}}))
    assert result.startswith("Refused"), result
    assert "SC-005" in result and "1.2" in result
```

Build `seeded_project` as a `@pytest_asyncio.fixture` creating a project whose `value_chain_registry` holds both `1.2` and `2.7` as active L2 activities, so the pre-existing anchor checks pass and this test fails for its own reason rather than an unrelated one. Follow the fixture shape already in `tests/test_sqlite_state_validation.py`.

- [ ] **Step 6: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_sqlite_state_validation.py -k moving_a_registered -v`
Expected: FAIL - the write returns `Written to ...`, because the scripts validator does not consult the script registry.

- [ ] **Step 7: Wire the cross-check into the door**

In `agents/tools/sqlite_state.py`, inside `_validate_interview_scripts`, add to the imports and after the existing `validate_anchor_levels` line:

```python
    # The script registry is the ledger for script ids, and succession already holds writes to
    # it to that contract. This is the same rule on the door the scripts actually come through:
    # the merge keys on script_id, so an id that moves replaces rather than adds.
    problems.extend(
        validate_scripts_against_script_registry(parsed, _current_script_registry(slug))
    )
```

- [ ] **Step 8: Run both suites**

Run: `./venv/bin/pytest tests/test_sqlite_state_validation.py tests/test_interview_script_model.py -q`
Expected: PASS

- [ ] **Step 9: Verify the door test has power**

Remove the `problems.extend(...)` line you just added, confirm `test_a_scripts_write_moving_a_registered_id_is_refused` fails, restore it, confirm it passes. Report both directions - the unit tests would stay green either way, which is exactly why the door test exists.

- [ ] **Step 10: Full suite twice, then commit**

Run: `./venv/bin/pytest -q` twice, identical counts.

```bash
git add api/services/interview_script_model.py agents/tools/sqlite_state.py tests/
git commit -m "fix(scripts): the scripts door consults the script registry

validate_script_registry_succession already refused moving a registered script_id to another
node - on writes to interview_script_registry. The write that carries the scripts checked only
that the anchor names a node the value chain registry holds, and never consulted the script
registry.

So a batch filing SC-005 against 2.7 passed while SC-005 was registered against 1.2, and
_merge_with_current, which keys on script_id, overwrote 1.2's script with 2.7's content. The
set would look complete and be silently scrambled.

A rule enforced at one entrance is not enforced. Same rule, other door."
```

---

## Task 2: The coverage validator

With re-running safe, a run can be judged. The contract is one script per node: eighty-nine activities, eighty-nine scripts. Today sixteen, and nothing says so.

This is a **warner**, not a validator: incomplete coverage must not refuse the write. Partial work across several runs is the intended way to reach eighty-nine, so refusing an incomplete batch would make the contract unreachable.

**Files:**
- Create: `api/services/coverage_validation.py`, `tests/test_coverage_validation.py`
- Modify: `agents/tools/sqlite_state.py` (`_WARNERS`, `_WARNER_SOURCE`)

**Interfaces:**
- Consumes: `_current_registry(slug) -> dict` from `agents/tools/sqlite_state.py:57`
- Produces: `validate_node_coverage(scripts: dict, registry: dict) -> list[dict]` returning zero or one warning dict shaped `{"subject": None, "code": "incomplete_coverage", "measure": float, "detail": str}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coverage_validation.py
"""The contract is one interview per node, and a run that misses nodes must say so.

Maya's last run completed with sixteen scripts against eighty-nine activities and nobody
noticed for four days, because nothing stated what she owed or checked whether she delivered.
"""
from api.services.coverage_validation import validate_node_coverage

_REGISTRY = {"activities": [
    {"id": "0",   "level": "L0", "active": True},
    {"id": "1",   "level": "L1", "active": True},
    {"id": "1.F", "level": "L1", "active": True},
    {"id": "1.2", "level": "L2", "active": True},
]}


def _script(node_id):
    return {"script_id": f"SC-{node_id}", "node_id": node_id}


def test_full_coverage_raises_nothing():
    scripts = {n: _script(n) for n in ("0", "1", "1.F", "1.2")}
    assert validate_node_coverage(scripts, _REGISTRY) == []


def test_a_missing_node_is_named():
    scripts = {n: _script(n) for n in ("0", "1", "1.F")}
    warnings = validate_node_coverage(scripts, _REGISTRY)
    assert len(warnings) == 1, "one warning, not one per missing node"
    w = warnings[0]
    assert w["code"] == "incomplete_coverage"
    assert "1.2" in w["detail"]
    assert w["measure"] == 0.75


def test_role_nodes_are_matched_on_node_id_not_level():
    """The registry files 1.F at its structural tier, L1; the script files it by perspective, F.
    Coverage matches on node_id, which is unambiguous in both artefacts, so the two level
    vocabularies cannot make a covered node read as uncovered."""
    scripts = {"SC-x": {"script_id": "SC-x", "node_id": "1.F", "level": "F"}}
    detail = validate_node_coverage(scripts, _REGISTRY)[0]["detail"]
    assert "1.F" not in detail


def test_a_retired_activity_is_not_owed_a_script():
    registry = {"activities": [
        {"id": "0", "level": "L0", "active": True},
        {"id": "9", "level": "L3", "active": False},
    ]}
    assert validate_node_coverage({"SC-1": _script("0")}, registry) == []


def test_an_empty_registry_raises_nothing():
    """A project whose value chain is not built yet owes no interviews."""
    assert validate_node_coverage({}, {"activities": []}) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_coverage_validation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.coverage_validation'`

- [ ] **Step 3: Write the validator**

```python
# api/services/coverage_validation.py
"""Which value chain nodes have no interview script.

The contract is one interview per node. Stakeholders are assigned to scripts separately, so one
script may serve several people - five frontline roles against one frontline instrument - and the
count of interviews conducted is not the count of scripts owed.

Matches on node_id rather than level, deliberately. The registry files a role node at its
structural tier (0.A is L0) and the script files it by perspective (0.A is A), so a level
comparison would report all six role nodes uncovered while they are covered. Node ids are
unambiguous in both artefacts.
"""

_MAX_NAMED = 12


def validate_node_coverage(scripts: dict, registry: dict) -> list[dict]:
    """Zero warnings when every active activity has a script, otherwise exactly one.

    One warning rather than one per node: seventy-three findings would bury the surface they are
    reported into, and the actionable fact is the set, not each member of it.
    """
    owed = [a.get("id") for a in registry.get("activities", []) if a.get("active", True)]
    if not owed:
        return []
    covered = {s.get("node_id") for s in scripts.values() if isinstance(s, dict)}
    missing = [node_id for node_id in owed if node_id not in covered]
    if not missing:
        return []

    named = ", ".join(missing[:_MAX_NAMED])
    if len(missing) > _MAX_NAMED:
        named += f", and {len(missing) - _MAX_NAMED} more"
    return [{
        "subject": None,
        "code": "incomplete_coverage",
        "measure": round((len(owed) - len(missing)) / len(owed), 4),
        "detail": (
            f"{len(owed) - len(missing)} of {len(owed)} value chain nodes have an interview "
            f"script. Missing: {named}. Every active node needs one - re-run to add the "
            f"remainder; existing scripts are kept."
        ),
    }]
```

- [ ] **Step 4: Run to verify it passes**

Run: `./venv/bin/pytest tests/test_coverage_validation.py -v`
Expected: PASS, five tests

- [ ] **Step 5: Wire it as a warner**

In `agents/tools/sqlite_state.py`, beside `_warn_themes` and `_warn_value_chain_tree`:

```python
def _warn_interview_coverage(parsed: object, slug: str) -> list[dict]:
    from api.services.coverage_validation import validate_node_coverage

    if not isinstance(parsed, dict):
        return []
    return validate_node_coverage(parsed, _current_registry(slug))
```

Then add to both maps:

```python
_WARNERS: dict[str, Callable[[object, str], list[dict]]] = {
    "value_chain_tree": _warn_value_chain_tree,
    "themes": _warn_themes,
    "interview_scripts": _warn_interview_coverage,
}

_WARNER_SOURCE: dict[str, str] = {
    "value_chain_tree": "value_chain_tree",
    "themes": "theme_anchor",
    "interview_scripts": "interview_coverage",
}
```

- [ ] **Step 6: Write the failing test that the warning reaches the surface**

```python
# tests/test_coverage_validation.py  (append)
@pytest.mark.asyncio
async def test_an_incomplete_write_records_a_warning(seeded_project):
    """Read back from validation_warnings, not from the validator's return value.

    The warning reaching the surface is the property. A warner that computes correctly and is
    never wired up looks identical from the validator's own tests.
    """
    import json
    from agents.tools.sqlite_state import SQLiteStateTool
    from api.database import get_connection, fetch_validation_warnings

    slug = seeded_project      # registry holds 1.2 and 2.7; we write a script for one
    SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=0)._run(
        operation="write", key="interview_scripts", agent_name="interaction_designer",
        value=json.dumps({"SC-001": {"script_id": "SC-001", "node_id": "1.2", "level": "L2",
                                     "relationship": "internal", "node_label": "Portfolio",
                                     "sections": []}}))

    async with get_connection(slug) as conn:
        cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (slug,))
        project_id = (await cur.fetchone())[0]
        rows = await fetch_validation_warnings(conn, project_id=project_id)
    coverage = [r for r in rows if r["code"] == "incomplete_coverage"]
    assert len(coverage) == 1
    assert "2.7" in coverage[0]["detail"]
```

Reuse the `seeded_project` fixture from Task 1 - move it to `tests/conftest.py` if both files need it rather than duplicating it.

- [ ] **Step 7: Run, then verify power**

Run: `./venv/bin/pytest tests/test_coverage_validation.py -v`
Expected: PASS

Then remove the `"interview_scripts"` entry from `_WARNERS`, confirm only the surface test fails while the five unit tests stay green, restore it, confirm all pass. Report both directions.

- [ ] **Step 8: Full suite twice, then commit**

```bash
git add api/services/coverage_validation.py agents/tools/sqlite_state.py tests/
git commit -m "feat(scripts): warn when nodes have no interview script

The contract is one interview per node. Maya's last run completed with sixteen scripts against
eighty-nine activities and nobody noticed for four days, because nothing stated what she owed.

A warner rather than a validator: reaching eighty-nine takes several runs, so refusing an
incomplete batch would make the contract unreachable. One warning naming the missing ids, not
seventy-three findings burying the surface they report into.

Matches on node_id, not level. The registry files a role node at its structural tier and the
script files it by perspective, so a level comparison would report all six role nodes uncovered
while they are covered."
```

---

## Task 3: Maya generates only what is missing

Her task reads `value_levers`, `value_chain_registry`, and `value_chain_summary`, and never reads `interview_scripts`. So a re-run regenerates from the registry as though starting fresh.

With Task 1 in place that is now safe rather than destructive - a moved id is refused - but it is still wasteful and it churns text a human may have edited. This makes the run additive by design rather than by guard.

**Files:**
- Modify: `agents/discovery/interaction_designer.py` (the task's numbered steps, from step 1 at line ~2488)
- Test: `tests/test_discovery_interviews_agents.py` or whichever file asserts Maya's task text - find it with `grep -rln interaction_designer tests/`

**Interfaces:**
- Consumes: nothing new. `interview_scripts` and `interview_script_registry` are both readable through `SQLiteStateTool` already.

- [ ] **Step 1: Write the failing test**

```python
def test_maya_reads_what_exists_before_generating(mock_llm):
    """A re-run must add the missing nodes, not regenerate the set.

    Task 1 makes a moved script id refusable, so a blind re-run can no longer scramble the set -
    but it would still rewrite every existing script, churning text a human may have edited.
    """
    from agents.discovery.interaction_designer import (
        create_interaction_designer, create_interaction_designer_task,
    )
    agent = create_interaction_designer(slug="t", llm=mock_llm, tools=[])
    text = create_interaction_designer_task(agent=agent, sector="energy").description
    assert "key='interview_scripts'" in text, "must read the existing scripts"
    assert "key='interview_script_registry'" in text, "must read the script ledger"
    lowered = text.lower()
    assert "only" in lowered and "missing" in lowered, "must say to generate only what is missing"


def test_maya_is_told_the_contract_is_every_node(mock_llm):
    """Sixteen was defensible because no target was stated. State it."""
    from agents.discovery.interaction_designer import (
        create_interaction_designer, create_interaction_designer_task,
    )
    agent = create_interaction_designer(slug="t", llm=mock_llm, tools=[])
    text = create_interaction_designer_task(agent=agent, sector="energy").description.lower()
    assert "every active" in text or "one interview script for every" in text


def test_maya_is_not_told_to_write_undeclared_keys(mock_llm):
    """Run 30 made three refused writes at the end - l0_interview_summaries,
    interview_summaries, and audit_interview_summaries - so the instruction to fan output across
    keys survived the ownership guard that now refuses it."""
    from agents.discovery.interaction_designer import (
        create_interaction_designer, create_interaction_designer_task,
    )
    agent = create_interaction_designer(slug="t", llm=mock_llm, tools=[])
    text = create_interaction_designer_task(agent=agent, sector="energy").description
    assert "_interview_summaries" not in text
    assert "interview_summaries" not in text
```

Check the real signature of `create_interaction_designer_task` before writing these - it may take more than `agent` and `sector`.

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/ -k maya_reads_what_exists -v`
Expected: FAIL - the task never reads `interview_scripts`.

- [ ] **Step 3: Rewrite the opening steps**

Replace the current step 1 with these, renumbering the rest:

```
"1. Use SQLiteStateTool with operation='read', key='value_chain_registry', "
"agent_name='interaction_designer' to load the activity registry. Collect every entry where "
"active=true. You owe one interview script for every one of them.\n"
"2. Use SQLiteStateTool with operation='read', key='interview_scripts', "
"agent_name='interaction_designer' to see which scripts already exist. An 'Error: no state "
"found' reply means none do, and you are starting from nothing.\n"
"3. Use SQLiteStateTool with operation='read', key='interview_script_registry', "
"agent_name='interaction_designer' to see which script id is already registered against which "
"node. A script id means one node for the life of the project: never file a registered id "
"against a different node, and take the next unused number for a new script.\n"
"4. Generate scripts ONLY for activities with no script yet. Do not re-emit an existing "
"script: it may have been edited by a consultant, and re-emitting it would overwrite that "
"work. Reaching every node across several runs is expected - each run adds what is missing.\n"
```

Then remove whatever instructs writing to `*_interview_summaries` keys. Find it with
`grep -n "summaries" agents/discovery/interaction_designer.py`.

- [ ] **Step 4: Run to verify it passes**

Run: `./venv/bin/pytest tests/ -k "maya_reads_what_exists or contract_is_every_node or undeclared_keys" -v`
Expected: PASS

- [ ] **Step 5: Check the rest of the task still reads coherently**

Read the whole task description once. The steps are numbered and cross-referenced; renumbering the opening breaks any later "as described in step 2". Fix any reference you broke, and say in your report which you found.

- [ ] **Step 6: Full suite twice, then commit**

```bash
git add agents/discovery/interaction_designer.py tests/
git commit -m "feat(maya): read what exists, generate only what is missing

Her task read the value chain registry, the summary, and the levers, and never read
interview_scripts - so a re-run regenerated the set as though starting fresh. Task 1 made that
safe rather than destructive, but it would still rewrite every existing script and churn text a
consultant may have edited.

Also states the contract - one script for every active activity - and removes the instruction to
fan output across *_interview_summaries keys, which produced three refused writes at the end of
run 30 even though the ownership guard now stops them."
```

---

## Task 4: Level and perspective are separate fields

A script's `level` carries a tier for `L0`-`L3` and a perspective for `A`, `S`, `C`, and `F` in one column, so "what tier is this interview at?" cannot be answered without special-casing. `MayaOutputExtra` splits on two hardcoded level sets and **renders nothing outside them** - a filter masquerading as a layout.

Cheaper at sixteen scripts than at eighty-nine.

**Files:**
- Modify: `api/services/interview_script_model.py` (schema validation), `agents/discovery/interaction_designer.py` (the output shape it asks for), `ui/src/types.ts`, `ui/src/components/tabs/MayaOutputExtra.tsx`
- Test: `tests/test_interview_script_model.py`, `ui/src/__tests__/MayaOutputExtra.test.tsx`

**Interfaces:**
- Produces: scripts carry `level` (`L0`|`L1`|`L2`|`L3`) and `perspective` (`A`|`S`|`C`|`F`|`null`)

- [ ] **Step 1: Write the failing UI test**

```tsx
// ui/src/__tests__/MayaOutputExtra.test.tsx
it('renders every script it is given, including one with an unrecognised perspective', async () => {
  // The current two buckets drop anything outside them silently - no message, no count.
  vi.mocked(projectsApi.getInterviewScripts).mockResolvedValue({
    'SC-1': { script_id: 'SC-1', node_id: '1',   level: 'L1', perspective: null, node_label: 'Property', sections: [] },
    'SC-2': { script_id: 'SC-2', node_id: '1.F', level: 'L1', perspective: 'F',  node_label: 'Frontline', sections: [] },
    'SC-3': { script_id: 'SC-3', node_id: '9',   level: 'L3', perspective: 'X',  node_label: 'Odd one',   sections: [] },
  } as never)
  render(<Wrapper><MayaOutputExtra slug="p" /></Wrapper>)
  expect(await screen.findByText(/Property/)).toBeInTheDocument()
  expect(await screen.findByText(/Frontline/)).toBeInTheDocument()
  expect(await screen.findByText(/Odd one/)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && npx vitest run MayaOutputExtra`
Expected: FAIL - "Odd one" is not rendered.

- [ ] **Step 3: Split the field**

In `ui/src/types.ts`, add `perspective: 'A' | 'S' | 'C' | 'F' | null` to `InterviewScript` and leave `level` as the tier.

In `MayaOutputExtra.tsx`, replace the two level sets and the two filters:

```tsx
// Split on perspective, not level. The previous version filtered on two hardcoded level sets and
// rendered nothing outside them, so a script with an unexpected level vanished with no message.
const vcScripts  = scripts.filter(s => !s.perspective)
const extScripts = scripts.filter(s => !!s.perspective)
```

In `api/services/interview_script_model.py`'s `validate_scripts`, accept `perspective` as an optional field constrained to `A`, `S`, `C`, `F`, or absent, and constrain `level` to the four tiers. Read the existing validation before changing it so the error messages stay in the file's established voice.

In `agents/discovery/interaction_designer.py`, change the output shape the task asks for so a role-node script emits `"level": "L1", "perspective": "F"` rather than `"level": "F"`.

- [ ] **Step 4: Run both suites**

Run: `cd ui && npx vitest run && npx tsc --noEmit`, then `./venv/bin/pytest tests/test_interview_script_model.py -q`
Expected: PASS, `tsc` clean

- [ ] **Step 5: Decide what happens to the sixteen existing scripts**

They carry `level: 'F'` and no `perspective`. Check whether `validate_scripts` now refuses them on the next write, and whether `MayaOutputExtra` still renders them. If either breaks, add a read-time normalisation - a script whose `level` is a role letter is read as `level: null, perspective: <letter>` - rather than a migration script. Say which you found and what you chose.

- [ ] **Step 6: Full suite twice, then commit**

```bash
git add api/services/interview_script_model.py agents/discovery/interaction_designer.py ui/src/types.ts ui/src/components/tabs/MayaOutputExtra.tsx tests/ ui/src/__tests__/
git commit -m "refactor(scripts): level carries the tier, perspective carries the role

One column carried two unrelated facts - a tier for L0-L3 and a perspective for A/S/C/F - so the
same node was filed differently in the registry and the script, and no code could ask what tier
an interview sat at without special-casing.

The UI split on two hardcoded level sets and rendered nothing outside them, which is a filter
wearing a layout's clothes: a script with an unexpected level disappeared with no message and no
count."
```

---

## Task 5: The Output badge counts what the tab shows

`AgentDetailPanel.tsx:969` renders `{crewOutputs.length}` - the number of `agent_outputs` rows. For Maya that is thirteen `interview_scripts` versions, plus `interview_script_registry`, plus a stale `value_chain_registry` she wrote before the ownership guard existed. Fifteen, beside a list showing sixteen interviews.

**Files:**
- Modify: `ui/src/components/AgentDetailPanel.tsx:968-969`
- Test: `ui/src/__tests__/AgentDetailPanel.test.tsx`
- Data: retire the stale `value_chain_registry` row owned by `interaction_designer`

- [ ] **Step 1: Write the failing test**

```tsx
it('does not badge the Output tab with a version count', async () => {
  // Thirteen versions of one artefact is not thirteen outputs, and it read as a count of
  // interviews sitting one below the sixteen the tab listed.
  const outputs = Array.from({ length: 13 }, (_, i) => ({
    id: i + 1, output_type: 'interview_scripts', version: i + 1, agent_name: 'interaction_designer',
  }))
  render(<Wrapper><AgentDetailPanel slug="p" crewKey="assessment_design" outputs={outputs as never} /></Wrapper>)
  expect(screen.queryByText('13')).not.toBeInTheDocument()
})
```

Read `AgentDetailPanel`'s real props before writing this - it may not take `outputs` directly.

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && npx vitest run AgentDetailPanel`
Expected: FAIL

- [ ] **Step 3: Count distinct artefacts, not rows**

```tsx
{t.key === 'output' && distinctOutputTypes > 0 && (
  <span className="ml-1 text-[9px] bg-gray-200 text-gray-500 rounded-full px-1">
    {distinctOutputTypes}
  </span>
)}
```

with `const distinctOutputTypes = new Set(crewOutputs.map(o => o.output_type)).size` alongside the existing `crewOutputs` derivation. One artefact written thirteen times is one artefact.

- [ ] **Step 4: Retire the stale row**

`interaction_designer` owns a `value_chain_registry` row, written before the ownership guard refused it. It inflates the badge and misattributes an artefact.

```bash
./venv/bin/python -c "
import sqlite3
c = sqlite3.connect('data/sp-gs-am.db')
n = c.execute(\"UPDATE agent_outputs SET is_current=0 WHERE agent_name='interaction_designer' AND output_type='value_chain_registry'\").rowcount
c.commit(); print('rows demoted:', n)"
```

Demote rather than delete: `id` is a citation token and the file is still on disk. Confirm afterwards that `current_output_path('sp-gs-am', 'value_chain_registry')` still resolves to Alex's copy.

- [ ] **Step 5: Run the frontend suite, then commit**

```bash
git add ui/src/components/AgentDetailPanel.tsx ui/src/__tests__/
git commit -m "fix(ui): the Output badge counts artefacts, not rows

It rendered crewOutputs.length - agent_outputs rows - so Maya's thirteen versions of one
artefact plus two others read as fifteen, one below the sixteen interviews the tab listed."
```

---

## Task 6: Prove it end to end

- [ ] **Step 1: Verify the two power checks still hold**

Re-run the reverts from Task 1 Step 9 and Task 2 Step 7, confirm the same tests fail and no others, restore, confirm green. Report both.

- [ ] **Step 2: Check coverage against the live project**

```bash
./venv/bin/python -c "
import json
from pathlib import Path
from agents.tools._db import current_output_path
from api.services.coverage_validation import validate_node_coverage
reg = json.loads(Path(current_output_path('sp-gs-am','value_chain_registry')).read_text())
scr = json.loads(Path(current_output_path('sp-gs-am','interview_scripts')).read_text())
for w in validate_node_coverage(scr, reg): print(w['measure'], w['detail'][:200])"
```

Expected: a measure near `0.18` and a detail naming missing L2 and L3 ids. This is the number the next Maya run has to move.

- [ ] **Step 3: Full suites**

Run: `./venv/bin/pytest -q` twice with identical counts, then `cd ui && npx vitest run && npx tsc --noEmit`.

- [ ] **Step 4: Update CLAUDE.md**

Add under Crew / agent conventions:

```markdown
Maya owes one interview script per active value chain activity. Coverage is checked on every
`interview_scripts` write by `api/services/coverage_validation.py` and reported as
`incomplete_coverage` into `validation_warnings`, which the next run reads back through
`_fetch_validation_warnings`. Reaching every node across several runs is expected: each run adds
only the missing nodes, and `_merge_with_current` accumulates.

A script id means one node for the life of the project. Both doors enforce it now -
`validate_script_registry_succession` on the registry write, and
`validate_scripts_against_script_registry` on the scripts write. The second was missing, and
because `_merge_with_current` keys on `script_id`, a moved id replaced a script rather than
adding one.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the coverage contract and the two script-id doors"
```

---

## Self-review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| Contract: one interview per node | 2, 3 |
| Coverage validator matching node_id | 2 |
| One warning, not one per node | 2 |
| Warning reaches the next run's prompt | 2 (existing `_fetch_validation_warnings`) |
| Scripts door consults the script registry | 1 |
| Maya reads what exists, generates the differential | 3 |
| Maya stops writing undeclared keys | 3 |
| Re-running stays manual | all - no loop is built |
| Level and perspective separated | 4 |
| UI renders every script | 4 |
| Badge counts displayed items | 5 |
| Stale `value_chain_registry` row retired | 5 |
| Evidence-level coverage deferred | none - deliberately not built |

**Placeholder scan:** none. Three steps direct the implementer to read a real signature rather than trust the plan - Task 3 Step 1, Task 4 Step 5, and Task 5 Step 1 - which is stated explicitly rather than left implicit, because this plan's briefs have been wrong about details repeatedly on this project.

**Type consistency:** `validate_scripts_against_script_registry(scripts: dict, script_registry: dict) -> list[str]` is defined in Task 1 and called in Task 1 Step 7 only. `validate_node_coverage(scripts: dict, registry: dict) -> list[dict]` is defined in Task 2 and called in Task 2 Step 5 and Task 6 Step 2. The warning dict shape matches `anchor_validation.py:23` exactly - `subject`, `code`, `measure`, `detail`. `perspective` is introduced in Task 4 and used in the same task's UI filter and test.

**One ordering note:** Task 4 changes the shape Maya emits, and Task 3 changes what she reads. Both edit `agents/discovery/interaction_designer.py`. Task 3 first is deliberate - the differential is the load-bearing change, and doing it before the schema split keeps each diff readable.
