# Maya's Incremental Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Maya build an interview script set one batch at a time, so the artefact accumulates instead of being overwritten, and so a script cannot be filed against a node of the wrong level.

**Architecture:** A write to `interview_scripts` merges by script id into the current version rather than replacing it. Validation runs on the merged whole, so each accepted version is strictly more complete than the last. A new anchor-level check closes the gap that let an L0 board interview be filed under an L1 entity.

**Tech Stack:** Python 3.13, FastAPI, aiosqlite (raw SQL, no ORM), CrewAI, pytest.

## Global Constraints

- British English, `-ise` / `-our` / `-re`, Oxford comma. En dash ` - ` with spaces, never an em dash.
- Python 3.13 only. `./venv/bin/pytest`, `./venv/bin/python`.
- **Run the backend suite twice.** `tests/conftest.py` uses a fixed `/tmp/agentpool_test`. Isolate with `monkeypatch.setenv("DATABASE_DIR", str(tmp_path))` plus `get_settings.cache_clear()` on both sides; tests using the shared `client` fixture must scope every assertion to a row they created.
- Assert the property where it holds. For each test: *what calls this, and is that tested?*
- Any destructive data step backs up first and defaults to a dry run, as `scripts/prune_fragmented_outputs.py` does.

---

## Why this plan exists, and what it must not do first

**The failure.** Run 26 wrote seven versions of `interview_scripts` in 50 minutes - v33 (SC-001), v34 (SC-002), v35 (SC-001, SC-002), v36 (SC-003, SC-004), v37 (SC-005), v38 (SC-006, SC-007), v39 (SC-008) - then died with `Invalid response from LLM call - None or empty`. `is_current` now points at v39, which holds **one script of eighteen**.

Maya's brief asks for one integrated script per L0, L1, L2, L3, C, A, F and S node as a single artefact. At ~22KB per script that is ~400KB against `max_tokens=16384`. It cannot be written in one call, so she batches - and every batch overwrites the last, because they all go to one key.

**Why she cannot batch the old way.** Her last success, run 20 on 4 August, spread the work across eight keys: `interview_script_registry` plus seven `*_interview_summaries`. The ownership boundary landed 5 August (`494bf623`) and `check_write` now refuses every one of them - correctly, since that fragmentation is what the clean baseline removed. Run 26 is the first Maya run under the boundary, and it left her one writable key with no way to accumulate into it.

### The prerequisite: the L0 must exist before Maya rebuilds

**A rebuild against the current registry does not fail validation. It silently mis-anchors, which is worse.**

`value_chain_registry` v5 holds 81 ids and no `"0"`. Three of the eighteen declared scripts anchor there - SC-001 (Board and C-Suite), SC-015 (customer) and SC-016 (audit). `validate_scripts_against_registry` refuses any script anchored to a node the registry does not hold, so Maya routed around the refusal: **in run 26 she wrote SC-001 with `level: "L0"` and `node_id: "1"` - the board interview filed under Property Asset Management.** SC-002, the Property L1 interview, carries the same `node_id`. The validator accepted both, because it checks that the node *exists* and never that its *level agrees* with the script's.

The succession rule then makes that permanent. Both directions are refused today:

```
Rebuilding with SC-001 -> node "1":
  - script_id SC-001 is registered against node 0 and this moves it to 1 -
    take an unused id for the new script, because stored answers cite this one

Later, moving SC-001 back to the real L0 node "0":
  - script_id SC-001 is registered against node 1 and this moves it to 0 -
    take an unused id for the new script, because stored answers cite this one
```

So a clean rebuild now anchors the board interview to Property and **locks it there**. Correcting it after the L0 lands costs retiring SC-001 and issuing a new id, and every stored answer citing SC-001 then resolves to a retired script.

| Script | Level | Anchors to | Today | After A+B |
|---|---|---|---|---|
| SC-001 Board and C-Suite | L0 | `0` | mis-anchored to an L1 | anchors to `0` |
| SC-015 Customer | C | `0` | mis-anchored | anchors to `1.C` / `2.C` |
| SC-016 Audit | A | `0` | mis-anchored | anchors to `0.A` |
| SC-018 Corporate Services | S | `3.3` | passes, wrong altitude | anchors to `0.S` |
| SC-017 Frontline | F | `1.5` | passes, wrong altitude | anchors to `1.F` |

**Therefore Tasks 2, 3, 4 and 5 of `2026-08-06-l0-anchor-and-level-anchored-synthesis.md` must land, and Alex must have produced a tree carrying the root and role nodes, before Task 7 of this plan resets Maya's artefacts.** Tasks 1 to 6 here are independent of that and can be built at any time.

---

## File Structure

| File | Responsibility |
|---|---|
| `agents/tools/sqlite_state.py` | `_MERGE_ON_WRITE` set and the merge step, ahead of validation. |
| `api/services/interview_script_model.py` | `validate_anchor_levels` - a script's level must match its node's. |
| `agents/discovery/interaction_designer.py` | Tell Maya to batch deliberately rather than accidentally. |
| `scripts/reset_interview_artefacts.py` *(new)* | Back up, then clear every interview artefact. Dry run by default. |

---

## Task 1: Merge on write

**Files:**
- Modify: `agents/tools/sqlite_state.py` (new `_MERGE_ON_WRITE`, merge step in `_run` before the validator call at line ~222)
- Test: `tests/test_merge_on_write.py` *(new)*

**Interfaces:**
- Produces: `_MERGE_ON_WRITE: frozenset[str]` and `_merge_with_current(key: str, parsed: dict, slug: str) -> dict`.

Merging happens **before** validation, so the validator judges the artefact that will actually be stored. A batch that would corrupt the accumulated set is refused, and the previous version stays current - nothing is lost.

Retirement stays in the script registry's `active: false`. Making the merge additive-only is deliberate: a key absent from a batch means "not in this batch", never "delete this".

- [ ] **Step 1: Write the failing test**

```python
# tests/test_merge_on_write.py
import json
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection
from agents.tools._db import latest_output_path


@pytest.fixture
async def maya_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "merge-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, name, sector) VALUES (?,?,?)",
            (slug, "Merge Test", "test"))
        await conn.commit()
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    # A registry every anchor below resolves against, so anchor checks never mask a
    # merge failure.
    (outputs / "value_chain_registry.json").write_text(json.dumps({"activities": [
        {"id": "0", "level": "L0", "active": True},
        {"id": "1", "level": "L1", "active": True},
        {"id": "2", "level": "L1", "active": True},
    ]}))
    yield slug, outputs
    get_settings.cache_clear()


def _script(sid, node, level):
    return {sid: {
        "script_id": sid, "node_id": node, "level": level,
        "node_label": f"{sid} interview", "relationship": "internal",
        "sections": [{
            "section_id": "S1", "title": "Context", "discipline": "governance",
            "question_intent": "context", "elicitation": "unprompted",
            "questions": [{"id": "Q1.1", "text": "How does this work today?"}],
        }],
    }}


def _write(slug, payload):
    from agents.tools.sqlite_state import SQLiteStateTool
    return SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)._run(
        operation="write", key="interview_scripts",
        agent_name="interaction_designer", value=json.dumps(payload))


def _current(outputs):
    return json.loads(
        Path(latest_output_path(outputs / "interview_scripts.json")).read_text())


@pytest.mark.asyncio
async def test_a_second_batch_accumulates_rather_than_replacing(maya_project):
    """The defect this plan exists to remove: run 26 wrote seven versions and the last
    one held a single script."""
    slug, outputs = maya_project
    assert not _write(slug, _script("SC-001", "0", "L0")).startswith("Error")
    assert not _write(slug, _script("SC-002", "1", "L1")).startswith("Error")

    got = _current(outputs)
    assert sorted(got) == ["SC-001", "SC-002"], f"the batch replaced instead of merging: {sorted(got)}"


@pytest.mark.asyncio
async def test_each_version_is_at_least_as_complete_as_the_one_before(maya_project):
    slug, outputs = maya_project
    sizes = []
    for sid, node, level in [("SC-001", "0", "L0"), ("SC-002", "1", "L1"),
                             ("SC-003", "2", "L1")]:
        _write(slug, _script(sid, node, level))
        sizes.append(len(_current(outputs)))
    assert sizes == [1, 2, 3], f"version history must only grow, got {sizes}"


@pytest.mark.asyncio
async def test_rewriting_a_script_replaces_that_script_only(maya_project):
    slug, outputs = maya_project
    _write(slug, _script("SC-001", "0", "L0"))
    _write(slug, _script("SC-002", "1", "L1"))

    corrected = _script("SC-001", "0", "L0")
    corrected["SC-001"]["node_label"] = "Corrected board interview"
    _write(slug, corrected)

    got = _current(outputs)
    assert sorted(got) == ["SC-001", "SC-002"]
    assert got["SC-001"]["node_label"] == "Corrected board interview"


@pytest.mark.asyncio
async def test_a_refused_batch_leaves_the_accumulated_set_intact(maya_project):
    """A bad batch must cost the batch, never the work already banked."""
    slug, outputs = maya_project
    _write(slug, _script("SC-001", "0", "L0"))
    _write(slug, _script("SC-002", "1", "L1"))

    result = _write(slug, _script("SC-003", "9.9.9", "L1"))   # anchor does not exist
    assert result.startswith("Error"), result

    got = _current(outputs)
    assert sorted(got) == ["SC-001", "SC-002"], "a refusal must not disturb what was banked"


@pytest.mark.asyncio
async def test_a_key_absent_from_a_batch_is_not_a_deletion(maya_project):
    """Additive by design: retirement is expressed in the script registry's active flag,
    never by omission from a batch."""
    slug, outputs = maya_project
    _write(slug, _script("SC-001", "0", "L0"))
    _write(slug, _script("SC-002", "1", "L1"))
    assert sorted(_current(outputs)) == ["SC-001", "SC-002"]


@pytest.mark.asyncio
async def test_a_non_merging_key_still_replaces(maya_project):
    """Only the keys in _MERGE_ON_WRITE change behaviour."""
    slug, outputs = maya_project
    from agents.tools.sqlite_state import _MERGE_ON_WRITE
    assert "value_chain_model" not in _MERGE_ON_WRITE
    assert "interview_scripts" in _MERGE_ON_WRITE
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_merge_on_write.py -v`
Expected: FAIL on `test_a_second_batch_accumulates_rather_than_replacing` - `sorted(got) == ["SC-002"]`

- [ ] **Step 3: Add the merge**

In `agents/tools/sqlite_state.py`, after the `_VALIDATORS` dict:

```python
# Keys whose write merges into the current version instead of replacing it.
#
# Maya's script set is roughly 400KB of JSON and max_tokens is 16384, so it cannot be
# written in one call. Before this, every batch clobbered the last: run 26 produced seven
# versions in fifty minutes and the one marked current held one script of eighteen. The
# version history recorded seven revisions where there had only been chunking.
#
# Merging is additive on purpose. A script absent from a batch means "not in this batch",
# never "delete this" - an agent that omits a key under context pressure would otherwise
# silently destroy work. Retirement is expressed in interview_script_registry's
# active: false, where it is explicit and reversible.
_MERGE_ON_WRITE: frozenset[str] = frozenset({"interview_scripts"})


def _merge_with_current(key: str, parsed: dict, slug: str) -> dict:
    """The current artefact with this batch applied over it, newest wins per id."""
    settings = get_settings()
    current_path = latest_output_path(
        Path(settings.projects_dir) / slug / "outputs" / f"{key}.json"
    )
    if current_path is None:
        return parsed
    try:
        current = json.loads(current_path.read_text())
    except (OSError, json.JSONDecodeError):
        return parsed          # an unreadable current version is no base, not a blocker
    if not isinstance(current, dict) or not isinstance(parsed, dict):
        return parsed
    merged = dict(current)
    merged.update(parsed)
    return merged
```

- [ ] **Step 4: Apply it before validation**

In `_run`, between the `json.loads(value)` block and the `validator = _VALIDATORS.get(key)` line:

```python
            # Merge before validating, so the validator judges the artefact that will
            # actually be stored rather than the fragment that arrived. A batch that would
            # corrupt the accumulated set is refused whole, and the previous version stays
            # current - the refusal costs the batch, never the work already banked.
            if key in _MERGE_ON_WRITE:
                parsed = _merge_with_current(key, parsed, self.slug)
                value = json.dumps(parsed, indent=2)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_merge_on_write.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add agents/tools/sqlite_state.py tests/test_merge_on_write.py
git commit -m "feat(scripts): a batch of interview scripts accumulates instead of clobbering"
```

---

## Task 2: A script's level must match its node's

**Files:**
- Modify: `api/services/interview_script_model.py` (new `validate_anchor_levels`)
- Modify: `agents/tools/sqlite_state.py` (`_validate_interview_scripts` calls it)
- Test: `tests/test_anchor_levels.py` *(new)*

**Interfaces:**
- Produces: `validate_anchor_levels(scripts: dict, registry: dict) -> list[str]`.

`validate_scripts_against_registry` checks that a node **exists**. It never checks that the node's level agrees with the script's, which is how run 26 filed an `L0` board interview against node `"1"`, an L1 entity, alongside the L1 script that legitimately owns it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_anchor_levels.py
from api.services.interview_script_model import validate_anchor_levels

REGISTRY = {"activities": [
    {"id": "0", "level": "L0", "active": True},
    {"id": "0.A", "level": "L0", "active": True},
    {"id": "0.S", "level": "L0", "active": True},
    {"id": "1", "level": "L1", "active": True},
    {"id": "1.C", "level": "L1", "active": True},
    {"id": "1.F", "level": "L1", "active": True},
    {"id": "1.1", "level": "L2", "active": True},
    {"id": "1.1.1", "level": "L3", "active": True},
]}

LEGACY = {"activities": [
    {"id": "1", "level": "L1", "active": True},
    {"id": "1.1", "level": "L2", "active": True},
]}


def _s(level, node):
    return {"SC-001": {"script_id": "SC-001", "level": level, "node_id": node}}


def test_the_run_26_defect_is_caught():
    """An L0 board interview filed against node "1", an L1 entity."""
    problems = validate_anchor_levels(_s("L0", "1"), REGISTRY)
    assert len(problems) == 1
    assert "L0" in problems[0] and "'1'" in problems[0] and "L1" in problems[0]


def test_matching_levels_are_silent():
    for level, node in [("L0", "0"), ("L1", "1"), ("L2", "1.1"), ("L3", "1.1.1")]:
        assert validate_anchor_levels(_s(level, node), REGISTRY) == [], (level, node)


def test_a_role_script_must_anchor_to_its_own_role_node():
    assert validate_anchor_levels(_s("A", "0.A"), REGISTRY) == []
    assert validate_anchor_levels(_s("C", "1.C"), REGISTRY) == []
    assert validate_anchor_levels(_s("F", "1.F"), REGISTRY) == []
    assert validate_anchor_levels(_s("S", "0.S"), REGISTRY) == []
    problems = validate_anchor_levels(_s("A", "1.1"), REGISTRY)
    assert len(problems) == 1 and "0.A" in problems[0]


def test_role_checks_are_skipped_when_the_registry_has_no_role_nodes():
    """A project whose value chain predates role nodes must not be blocked - the check
    activates when the nodes it judges against exist."""
    assert validate_anchor_levels(_s("A", "1.1"), LEGACY) == []
    assert validate_anchor_levels(_s("S", "1.1"), LEGACY) == []


def test_level_checks_still_apply_without_role_nodes():
    assert validate_anchor_levels(_s("L0", "1"), LEGACY) != []


def test_an_empty_registry_accepts_anything():
    assert validate_anchor_levels(_s("L0", "1"), {"activities": []}) == []


def test_an_unknown_anchor_is_left_to_the_existence_check():
    """Two validators, one message each - a missing node is reported once, not twice."""
    assert validate_anchor_levels(_s("L0", "9.9"), REGISTRY) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_anchor_levels.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate_anchor_levels'`

- [ ] **Step 3: Write the validator**

Append to `api/services/interview_script_model.py`:

```python
_ROLE_LEVELS = ("C", "A", "F", "S")


def validate_anchor_levels(scripts: dict, registry: dict) -> list[str]:
    """Every script whose level disagrees with the level of the node it anchors to.

    validate_scripts_against_registry proves the node exists. This proves it is the right
    kind of node. Without it an L0 board interview can be filed against an L1 entity and
    accepted - which is what run 26 did, putting the Board and C-Suite script on node "1",
    Property Asset Management, beside the L1 script that legitimately owns it.

    An anchor that resolves to nothing is not reported here; the existence check owns that
    message, and reporting it twice would make one fault look like two.
    """
    levels = {
        entry.get("id"): entry.get("level")
        for entry in registry.get("activities", [])
    }
    if not levels:
        return []

    has_role_nodes = any(
        str(node_id).rsplit(".", 1)[-1] in _ROLE_LEVELS for node_id in levels
    )

    problems: list[str] = []
    for key, script in scripts.items():
        node_id = script.get("node_id")
        if node_id not in levels:
            continue
        name = script.get("script_id") or key
        level = script.get("level")

        if level in ("L0", "L1", "L2", "L3"):
            node_level = levels[node_id]
            if node_level != level:
                problems.append(
                    f"script {name} is a {level} interview anchored to node {node_id!r}, "
                    f"which is {node_level}. A script filed at the wrong altitude sends its "
                    f"evidence to the wrong level of the value chain."
                )
        elif level in _ROLE_LEVELS and has_role_nodes:
            suffix = str(node_id).rsplit(".", 1)[-1]
            if suffix != level:
                expected = "0." + level if level in ("A", "S") else "<entity>." + level
                problems.append(
                    f"script {name} is a {level} interview anchored to node {node_id!r}, "
                    f"which is not a {level} role node. Anchor it to {expected}."
                )
    return problems
```

- [ ] **Step 4: Call it from the write path**

In `agents/tools/sqlite_state.py`, inside `_validate_interview_scripts`, add the import and the call after `validate_scripts_against_registry`:

```python
    problems.extend(validate_anchor_levels(parsed, _current_registry(slug)))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_anchor_levels.py tests/test_merge_on_write.py -v`
Expected: all pass

- [ ] **Step 6: Prove the tool refuses the real defect**

Add to `tests/test_merge_on_write.py`:

```python
@pytest.mark.asyncio
async def test_the_tool_refuses_a_script_filed_at_the_wrong_altitude(maya_project):
    """One layer away from Task 2: the tool that calls the validator must act on it."""
    slug, outputs = maya_project
    result = _write(slug, _script("SC-001", "1", "L0"))   # L0 script on an L1 node
    assert result.startswith("Error"), result
    assert "altitude" in result
    assert latest_output_path(outputs / "interview_scripts.json") is None
```

Run: `./venv/bin/pytest tests/test_merge_on_write.py -v`
Expected: 7 passed

- [ ] **Step 7: Commit**

```bash
git add api/services/interview_script_model.py agents/tools/sqlite_state.py tests/test_anchor_levels.py tests/test_merge_on_write.py
git commit -m "feat(scripts): a script's level must match the level of the node it anchors to"
```

---

## Task 3: Tell Maya to batch deliberately

**Files:**
- Modify: `agents/discovery/interaction_designer.py` (the write instruction, line ~3136; `expected_output`, line ~3146)
- Test: `tests/test_interaction_designer_prompt.py` *(new)*

**Interfaces:** none - prompt text only.

She is already batching. The prompt tells her to produce everything at once, so the batching is improvisation under pressure rather than a described strategy - which is why the batches were erratic (one script, then two, then a re-send of both).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interaction_designer_prompt.py
import inspect
from agents.discovery import interaction_designer


def test_the_prompt_describes_batching():
    src = inspect.getsource(interaction_designer)
    assert "batch" in src.lower()
    assert "merged into" in src or "merges into" in src


def test_the_prompt_says_omission_is_not_deletion():
    src = inspect.getsource(interaction_designer)
    assert "active: false" in src
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_interaction_designer_prompt.py -v`
Expected: FAIL on `assert "merged into" in src`

- [ ] **Step 3: Replace the write instruction**

Replace the two lines at ~3136:

```python
            "   Use SQLiteStateTool with operation='write', key='interview_scripts', "
            "agent_name='interaction_designer' to save this. The whole set will not fit in "
            "one response, so write it in BATCHES of two or three scripts. Each write is "
            "merged into the current artefact by script id, so a later batch adds to the "
            "earlier ones rather than replacing them - you never need to re-send a script "
            "you have already written, and re-sending one only rewrites that script. "
            "Omitting a script from a batch does NOT remove it; retire a script you no "
            "longer need by setting active: false in the registry below. Work through the "
            "nodes in registry order and stop when every node has a script.\n"
```

Then update `expected_output` so it describes the accumulated artefact rather than a single write, keeping its existing per-level detail intact and adding:

```python
            "interview_scripts.json is built across several batched writes that merge by "
            "script id; the final artefact holds one script per node. "
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_interaction_designer_prompt.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add agents/discovery/interaction_designer.py tests/test_interaction_designer_prompt.py
git commit -m "feat(assessment): Maya is told to batch, rather than improvising it under pressure"
```

---

## Task 4: The reset script

**Files:**
- Create: `scripts/reset_interview_artefacts.py`
- Test: `tests/test_reset_interview_artefacts.py` *(new)*

**Interfaces:**
- Produces: `reset_interview_artefacts(slug: str, *, apply: bool = False) -> dict` returning `{"rows": int, "files": int, "backup_db": str|None, "archive": str|None}`.

**Dry run by default**, exactly as `scripts/prune_fragmented_outputs.py` is, and for the same reason: the last bulk operation on outputs demoted two live artefacts before anyone noticed.

Interview **sessions and answers are not touched.** `sp-gs-am` currently has zero of each, so nothing is at risk today, but a reset that silently destroyed interview evidence would be unrecoverable on a project that had some.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reset_interview_artefacts.py
import json
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection

TYPES = [
    "interview_scripts", "interview_script_registry",
    "l0_interview_summaries", "l1_interview_summaries", "l2_interview_summaries",
    "customer_interview_summaries", "audit_interview_summaries",
    "frontline_interview_summaries", "corp_services_interview_summaries",
]


@pytest.fixture
async def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "reset-test"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, name, sector) VALUES (?,?,?)",
            (slug, "Reset Test", "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            pid = (await cur.fetchone())[0]
        for i, t in enumerate(TYPES, start=1):
            p = outputs / f"{t}_v{i}.json"
            p.write_text(json.dumps({"seeded": t}))
            await conn.execute(
                "INSERT INTO agent_outputs"
                " (project_id, agent_name, output_type, file_path, version, is_current)"
                " VALUES (?,?,?,?,?,1)",
                (pid, "interaction_designer", t, str(p), i))
        # A value chain output that must survive untouched.
        vc = outputs / "value_chain_tree_v1.json"
        vc.write_text(json.dumps([{"id": "0", "level": "L0"}]))
        await conn.execute(
            "INSERT INTO agent_outputs"
            " (project_id, agent_name, output_type, file_path, version, is_current)"
            " VALUES (?,?,?,?,?,1)",
            (pid, "value_chain_mapper", "value_chain_tree", str(vc), 1))
        await conn.commit()
    yield slug, outputs
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_dry_run_changes_nothing(seeded):
    slug, outputs = seeded
    from scripts.reset_interview_artefacts import reset_interview_artefacts

    report = reset_interview_artefacts(slug)
    assert report["rows"] == len(TYPES)
    assert report["backup_db"] is None

    async with get_connection(slug) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM agent_outputs WHERE output_type LIKE '%interview%'"
        ) as cur:
            assert (await cur.fetchone())[0] == len(TYPES), "a dry run must not delete"
    assert (outputs / "interview_scripts_v1.json").exists()


@pytest.mark.asyncio
async def test_apply_clears_every_interview_artefact(seeded):
    slug, outputs = seeded
    from scripts.reset_interview_artefacts import reset_interview_artefacts

    report = reset_interview_artefacts(slug, apply=True)
    assert report["rows"] == len(TYPES)
    assert Path(report["backup_db"]).exists(), "apply must back the database up first"

    async with get_connection(slug) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM agent_outputs WHERE output_type LIKE '%interview%'"
        ) as cur:
            assert (await cur.fetchone())[0] == 0
    for t in TYPES:
        assert not list(outputs.glob(f"{t}_v*.json")), f"{t} files remain"


@pytest.mark.asyncio
async def test_the_value_chain_is_left_alone(seeded):
    """The last bulk output operation demoted two live artefacts. This one must not."""
    slug, outputs = seeded
    from scripts.reset_interview_artefacts import reset_interview_artefacts

    reset_interview_artefacts(slug, apply=True)
    assert (outputs / "value_chain_tree_v1.json").exists()
    async with get_connection(slug) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM agent_outputs WHERE output_type='value_chain_tree'"
        ) as cur:
            assert (await cur.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_files_are_archived_not_deleted(seeded):
    slug, outputs = seeded
    from scripts.reset_interview_artefacts import reset_interview_artefacts

    report = reset_interview_artefacts(slug, apply=True)
    archive = Path(report["archive"])
    assert archive.is_dir()
    assert (archive / "interview_scripts_v1.json").exists()


@pytest.mark.asyncio
async def test_interview_sessions_and_answers_are_never_touched(seeded):
    """Scripts are reproducible; a transcript is not."""
    slug, _ = seeded
    from scripts.reset_interview_artefacts import reset_interview_artefacts
    import inspect
    from scripts import reset_interview_artefacts as mod

    src = inspect.getsource(mod)
    assert "DELETE FROM interview_sessions" not in src
    assert "DELETE FROM interview_answers" not in src
    reset_interview_artefacts(slug, apply=True)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_reset_interview_artefacts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.reset_interview_artefacts'`

- [ ] **Step 3: Write the script**

```python
# scripts/reset_interview_artefacts.py
"""Clear every interview artefact so Maya rebuilds from scratch.

Dry run by default. --apply is required to act, for the same reason
prune_fragmented_outputs.py requires it: the previous bulk operation on outputs demoted
two live artefacts because a filename family was split across output types.

Interview SESSIONS and ANSWERS are deliberately untouched. A script is reproducible - Maya
writes it again in an hour. A transcript is a thing a person said once, and no rerun brings
it back.
"""
from __future__ import annotations
import argparse
import contextlib
import json
import shutil
import sqlite3
from datetime import date
from pathlib import Path

from api.config import get_settings

INTERVIEW_OUTPUT_TYPES = (
    "interview_scripts",
    "interview_script_registry",
    "l0_interview_summaries",
    "l1_interview_summaries",
    "l2_interview_summaries",
    "customer_interview_summaries",
    "audit_interview_summaries",
    "frontline_interview_summaries",
    "corp_services_interview_summaries",
)


def reset_interview_artefacts(slug: str, *, apply: bool = False) -> dict:
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{slug}.db"
    outputs = Path(settings.projects_dir) / slug / "outputs"

    placeholders = ",".join("?" * len(INTERVIEW_OUTPUT_TYPES))
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute(
            f"SELECT id, output_type, version, file_path FROM agent_outputs"
            f" WHERE output_type IN ({placeholders})",
            INTERVIEW_OUTPUT_TYPES,
        ).fetchall()

    # Every file whose stem belongs to one of these types, not only the paths the database
    # names - a version written and then renamed can leave a file no row points at.
    files: list[Path] = []
    for output_type in INTERVIEW_OUTPUT_TYPES:
        files.extend(sorted(outputs.glob(f"{output_type}_v*.json")))
        exact = outputs / f"{output_type}.json"
        if exact.exists():
            files.append(exact)

    report = {
        "rows": len(rows), "files": len(files),
        "backup_db": None, "archive": None,
        "types": sorted({r[1] for r in rows}),
    }
    if not apply:
        print(json.dumps(report, indent=2))
        print("\nDRY RUN - nothing changed. Pass --apply to act.")
        return report

    backup = db_path.with_suffix(f".pre-interview-reset-{date.today().isoformat()}.db")
    shutil.copy2(db_path, backup)
    report["backup_db"] = str(backup)

    archive = outputs.parent / f"_interview_reset_{date.today().isoformat()}"
    archive.mkdir(parents=True, exist_ok=True)
    report["archive"] = str(archive)
    for f in files:
        shutil.move(str(f), str(archive / f.name))

    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        ids = [r[0] for r in rows]
        if ids:
            marks = ",".join("?" * len(ids))
            # Dependants first: the foreign keys added by the lineage work refuse a delete
            # that leaves them dangling.
            for table, column in (
                ("output_citations", "output_id"),
                ("output_lineage", "output_id"),
                ("output_changes", "output_id"),
                ("approval_commit_outputs", "output_id"),
                ("human_reviews", "output_id"),
                ("run_inputs", "output_id"),
            ):
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute(f"DELETE FROM {table} WHERE {column} IN ({marks})", ids)
            conn.execute(f"DELETE FROM agent_outputs WHERE id IN ({marks})", ids)
        conn.commit()

    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("--apply", action="store_true", help="actually clear them")
    args = parser.parse_args()
    reset_interview_artefacts(args.slug, apply=args.apply)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_reset_interview_artefacts.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/reset_interview_artefacts.py tests/test_reset_interview_artefacts.py
git commit -m "feat(scripts): a reversible reset of every interview artefact"
```

---

## Task 5: Full-suite verification

- [ ] **Step 1: Run the backend suite twice**

Run: `./venv/bin/pytest -q && ./venv/bin/pytest -q`
Expected: identical both times; no new failures against the known baseline of 10.

- [ ] **Step 2: Confirm the merge does not disturb other writers**

Run: `./venv/bin/pytest tests/ -q -k "script or state or output"`
Expected: no new failures. `interview_scripts` is the only merging key; everything else replaces as before.

---

## Task 6: Dry-run the reset on the live project

- [ ] **Step 1: Inspect what would be cleared**

Run: `./venv/bin/python -m scripts.reset_interview_artefacts sp-gs-am`

Expected: a report naming roughly 30 rows across the nine types (11 `interview_scripts` versions including v33-v39, 1 registry, and the seven summary families), with `backup_db: null` and nothing changed on disk.

- [ ] **Step 2: Read the report before going further**

Confirm the `types` list contains no `value_chain_*` entry and no `state`. If either appears, stop - that is the clean-baseline defect recurring, and the type list needs narrowing before anything is applied.

---

## Task 7: Apply the reset - **after the L0 lands**

**Do not run this task until all of the following hold:**

1. Tasks 2, 3, 4 and 5 of `2026-08-06-l0-anchor-and-level-anchored-synthesis.md` are merged.
2. A `discovery_mapping` run has produced a `value_chain_tree` whose single root is `0`, and `DeriveRegistryTool` has flattened it into a registry containing `0` and the role nodes.
3. `validate_anchor_levels` (Task 2 here) is in the write path.

Running it before then rebuilds a complete script set anchored to the wrong nodes, and the succession rule then refuses to move any of them - correcting SC-001 afterwards costs retiring it and issuing a new id, and every stored answer citing it resolves to a retired script.

- [ ] **Step 1: Confirm the registry holds the L0 and the role nodes**

```bash
./venv/bin/python -c "
import json
from pathlib import Path
from agents.tools._db import latest_output_path
p = latest_output_path(Path('projects/sp-gs-am/outputs/value_chain_registry.json'))
ids = {a['id'] for a in json.loads(Path(p).read_text())['activities']}
print('registry:', p)
print('L0 present:', '0' in ids)
roles = sorted(i for i in ids if i.rsplit('.',1)[-1] in ('A','S','C','F'))
print('role nodes:', roles)
assert '0' in ids, 'the L0 is still missing - do not reset yet'
assert roles, 'no role nodes - do not reset yet'
"
```

Expected: `L0 present: True` and a non-empty role node list. **If either assertion fails, stop.**

- [ ] **Step 2: Apply the reset**

Run: `./venv/bin/python -m scripts.reset_interview_artefacts sp-gs-am --apply`
Expected: a report naming the backup database and the archive directory.

- [ ] **Step 3: Confirm the value chain is untouched**

```bash
./venv/bin/python -c "
import sqlite3
c = sqlite3.connect('data/sp-gs-am.db')
print('interview rows:', c.execute(\"SELECT COUNT(*) FROM agent_outputs WHERE output_type LIKE '%interview%'\").fetchone()[0])
print('value chain rows:', c.execute(\"SELECT COUNT(*) FROM agent_outputs WHERE output_type LIKE 'value_chain%'\").fetchone()[0])
"
```

Expected: interview rows 0, value chain rows unchanged from before the reset.

- [ ] **Step 4: Run Maya**

```bash
curl -s -X POST http://127.0.0.1:8000/projects/sp-gs-am/run \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"crew":"assessment_design"}'
```

- [ ] **Step 5: Verify the artefact accumulated**

```bash
./venv/bin/python -c "
import json, sqlite3
from pathlib import Path
from agents.tools._db import latest_output_path
p = latest_output_path(Path('projects/sp-gs-am/outputs/interview_scripts.json'))
d = json.loads(Path(p).read_text())
print('current:', p, '->', len(d), 'scripts')
c = sqlite3.connect('data/sp-gs-am.db')
print('versions:', c.execute(\"SELECT version, is_current FROM agent_outputs WHERE output_type='interview_scripts' ORDER BY version\").fetchall())
reg = json.loads(Path(latest_output_path(Path('projects/sp-gs-am/outputs/value_chain_registry.json'))).read_text())
levels = {a['id']: a['level'] for a in reg['activities']}
bad = [k for k, s in d.items() if s.get('level') in ('L0','L1','L2','L3') and levels.get(s.get('node_id')) != s.get('level')]
print('mis-anchored:', bad or 'none')
"
```

Expected: the current version holds **every** script rather than the last batch; the version count matches the number of batches; and `mis-anchored: none`. That last line is the run-26 defect, checked directly.

---

## Sequencing

```
A+B Tasks 2-5  ──► Alex emits the L0 and role nodes  ──► E Task 7 (reset + rebuild)
                                                     ▲
E Tasks 1-6 (merge, anchor levels, prompt, script) ──┘
```

Tasks 1 to 6 are independent and can be built immediately. Task 7 is the only one gated on the L0, and it is gated hard: its first step asserts the registry holds `0` and the role nodes, and stops if it does not.
