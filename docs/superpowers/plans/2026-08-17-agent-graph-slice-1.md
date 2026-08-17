# Agent graph, slice 1 - identity and the derived core

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One module that assembles the agent/crew graph from the registries that already hold it, a permanent `agent_id` separated from a mutable display name, `RunCrewTool`'s description generated rather than written, and the stale restatements deleted.

**Architecture:** A new `agents/graph.py` assembles the graph at import time from existing symbols - it declares nothing that is already declared elsewhere. Identity gains `AGENT_IDENTITY`, mapping the permanent id to display name and image. Everything that currently restates a crew→agent or crew→label mapping reads the graph instead. Guard tests assert every declared edge resolves, in the shape `tests/test_proxy_prefix_coverage.py` established.

**Tech Stack:** Python 3.13, pytest, existing registries (`agents/tools/registry.py`, `agents/model_registry.py`, `api/services/crew_graph.py`, `api/services/run_service.py`), React 18 + TypeScript for the frontend maps.

## Global Constraints

- **British English** throughout - `-ise`, `-our`, `-re`, Oxford comma, spaced en dash ` - `, never an em dash. Binds comments, docstrings, UI copy, and documentation.
- **Python 3.13** via `./venv/bin/python`. No ORM - raw SQL in `api/database.py`. bcrypt direct, never passlib.
- **Frontend:** `brand` tokens only, never `sky-*` or `blue-*`. Lucide icons, no emoji. `describeError` imported from `ui/src/utils/describeError.ts`.
- **Backend suite twice with identical counts** - `DATABASE_DIR` is a fixed path that persists between runs, so a single green run proves nothing. Baseline **1717 passed, 2 skipped, 12 deselected**. Then `cd ui && npx vitest run && npx tsc --noEmit` - baseline **529 passed**, clean.
- **Power-check every new test**: revert the fix, confirm the test fails, restore it, verbatim output in the report. **Revert conditions one at a time, never as a group** - a group revert lets a neighbour do the refusing. **Confirm each mutation actually changes behaviour** before concluding a fix is unwitnessed; an inert edit that leaves the suite green proves nothing.
- **No test may assert a graph fact against a constant written in the same change.** A graph is unusually easy to test against itself. Assert against the registry the fact is derived from, or against behaviour.
- Stage explicit paths. **Never `git add -A`** - `data/` holds live client databases.
- Do not run anything against `data/`, and do not restart the servers on :8000 or :3000.

---

## File Structure

| File | Responsibility |
|---|---|
| `agents/graph.py` | **Create.** Assembles and exposes the graph. Declares nothing already declared elsewhere. |
| `agents/identity.py` | **Create.** `AGENT_IDENTITY`: permanent id → display name, image. The only mutable-label source. |
| `agents/tools/run_crew.py` | **Modify.** Description generated from the graph. |
| `api/services/run_service.py` | **Modify.** `_CREW_AGENT_NAMES` becomes the graph's source, not a duplicate. |
| `tests/test_agent_graph.py` | **Create.** Edge-resolution guards and the generated-description guard. |
| Frontend maps | **Modify.** Nine label maps collapse to one served source. |

---

### Task 1: The graph module, assembled from what exists

**Files:**
- Create: `agents/graph.py`
- Test: `tests/test_agent_graph.py`

**Interfaces:**
- Produces: `build_graph() -> Graph`, where `Graph` exposes `agents: dict[str, AgentNode]` and `crews: dict[str, CrewNode]`. `AgentNode` carries `agent_id`, `tier`, `tools`, `writes`. `CrewNode` carries `crew_id`, `agent_ids`, `depends_on`. Later tasks consume both.

- [ ] **Step 1: Read the four sources before writing anything**

Read and note the exact symbol names: `tool_map` (`agents/tools/registry.py`), `AGENT_TIER` (`agents/model_registry.py`), `CREW_DEPENDENCIES` (`api/services/crew_graph.py`), `_CREW_AGENT_NAMES` and `OUTPUT_OWNERS` (`api/services/run_service.py`). `tests/test_model_registry.py:54` already asserts `tool_map`'s keys equal `AGENT_TIER`'s - that guard is the precedent for this task and must keep passing.

- [ ] **Step 2: Write the failing test**

```python
def test_every_agent_in_a_crew_exists_in_the_registries():
    graph = build_graph()
    for crew in graph.crews.values():
        for agent_id in crew.agent_ids:
            assert agent_id in graph.agents, (
                f"crew {crew.crew_id} names {agent_id}, which no registry knows"
            )


def test_the_graph_agrees_with_the_registry_it_derives_from():
    from agents.model_registry import AGENT_TIER
    assert set(build_graph().agents) == set(AGENT_TIER)
```

- [ ] **Step 3: Run it and watch it fail**

Run: `./venv/bin/pytest tests/test_agent_graph.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'agents.graph'`

- [ ] **Step 4: Write `agents/graph.py`**

Assemble from the four sources. Do not copy any list. `writes` inverts from `OUTPUT_OWNERS`. Raise at import time if a crew names an unknown agent, rather than returning a partial graph - a graph that silently omits a broken edge is the artefact this replaces.

- [ ] **Step 5: Run and watch it pass**

Run: `./venv/bin/pytest tests/test_agent_graph.py -v` → PASS. Then the full backend suite twice.

- [ ] **Step 6: Power-check**

Add a crew naming a nonexistent agent to a local copy of `_CREW_AGENT_NAMES`; confirm Step 2's first test fails and the import raises. Restore. Record verbatim.

- [ ] **Step 7: Commit**

```bash
git add agents/graph.py tests/test_agent_graph.py
git commit -m "feat(graph): assemble the agent and crew graph from the registries that hold it"
```

---

### Task 2: Permanent id, mutable display name

**Files:**
- Create: `agents/identity.py`
- Modify: `agents/graph.py`
- Test: `tests/test_agent_graph.py`

**Interfaces:**
- Produces: `AGENT_IDENTITY: dict[str, Identity]` where `Identity` carries `display_name: str` and `image: str | None`. `AgentNode` gains `display_name` and `image`, resolved through it.

- [ ] **Step 1: Establish what is stored today**

Report, before changing anything: every column holding an agent name, and its row count. Known: `agent_outputs.agent_name`, and `agent_skill_assignments` keyed on **display** names. Note that `api/services/pam_report_job.py` writes `agent_name='PAM'` where every other writer uses a snake key. **Do not migrate stored rows in this task** - the ids are the existing snake keys, so no backfill is needed; record anything that would need one.

- [ ] **Step 2: Write the failing test**

```python
def test_every_agent_has_an_identity_and_no_identity_is_orphaned():
    graph = build_graph()
    from agents.identity import AGENT_IDENTITY
    assert set(AGENT_IDENTITY) == set(graph.agents)


def test_a_display_name_is_never_used_as_a_key():
    graph = build_graph()
    for node in graph.agents.values():
        assert node.agent_id in AGENT_TIER
        assert node.display_name not in graph.agents or node.display_name == node.agent_id
```

- [ ] **Step 3: Run it and watch it fail.** Expected: `ModuleNotFoundError`.

- [ ] **Step 4: Write `agents/identity.py` and wire it into `AgentNode`**

The id is the existing snake key. The display name is what a human reads. **Neither may be derived from the other by a `.replace()`** - that would recreate the coupling this task exists to break.

- [ ] **Step 5: Run, then the full suite twice.**

- [ ] **Step 6: Power-check** - rename one display name and confirm no key-based test breaks; then rename one *id* and confirm the graph test does. Record both.

- [ ] **Step 7: Commit**

```bash
git add agents/identity.py agents/graph.py tests/test_agent_graph.py
git commit -m "feat(graph): an agent's id is permanent and its name is not"
```

---

### Task 3: `RunCrewTool`'s description is generated

**Files:**
- Modify: `agents/tools/run_crew.py`
- Test: `tests/test_agent_graph.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_tool_offers_pam_exactly_the_crews_that_exist():
    from agents.tools.run_crew import RunCrewTool
    tool = RunCrewTool(slug="any", orchestration_run_id=1)
    offered = {c.strip() for c in tool.description.split("one of:")[1].split(",")}
    assert offered == set(build_graph().crews)
```

- [ ] **Step 2: Run it and watch it fail**

Expected: FAIL. The current description names `discovery` and `architecture`, which no crew provides, and omits `assessment_design`, `stakeholder_management`, `requirements` and `capabilities`.

- [ ] **Step 3: Generate the description from the graph.**

- [ ] **Step 4: Run, then the full suite twice.**

- [ ] **Step 5: Power-check** - hand-write a crew name into the description; confirm the test fails. Restore.

- [ ] **Step 6: Commit**

```bash
git add agents/tools/run_crew.py tests/test_agent_graph.py
git commit -m "fix(graph): PAM is offered the crews that exist, not the ones somebody typed"
```

---

### Task 4: Delete the restatements

**Files:**
- Modify: `agents/tools/_db.py`, `api/services/pam_report_service.py`, `api/services/run_service.py` (`_AGENT_TO_CREW`), `ui/src/components/OrgChart.tsx`, and the remaining crew-label maps
- Test: `tests/test_agent_graph.py`, plus the frontend tests covering the maps

- [ ] **Step 1: Enumerate before deleting**

Report every crew→agent map, crew-label map, persona list and `OUTPUT_TYPE_LABELS` you find, with `file:line`, and say for each whether it agrees with the graph. The research found nine, four, six and three respectively, five of them stale. **If your count differs from the research, say so and reconcile** rather than assuming either is right.

- [ ] **Step 2: Write the failing guard**

```python
def test_no_module_declares_its_own_crew_to_agent_map():
    """The graph is the only place this mapping lives. A second copy is how
    RunCrewTool came to name two crews that do not exist."""
```

Assert by import and comparison, not by grepping source text - a grep guard breaks on formatting and passes on a renamed variable.

- [ ] **Step 3: Delete each restatement, one commit per module**, repointing its consumers at the graph. Run the full suite after each.

- [ ] **Step 4: Serve the labels the frontend needs**

The nine frontend maps need one source. Add it to an existing endpoint rather than a new route - if you add a route, `tests/test_proxy_prefix_coverage.py` must still pass.

- [ ] **Step 5: Both suites twice, `tsc --noEmit` clean.**

- [ ] **Step 6: Commit**

---

## Self-Review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| Derived core assembled from existing registries | 1 |
| Permanent `agent_id`, mutable display name and image | 2 |
| `RunCrewTool` generated | 3 |
| Restatements deleted | 4 |
| Declared reads, egress, purposes, triggers | none - slice 2 |
| Per-project overrides | none - slice 3 |
| n8n removal | none - slice 4 |
| Enforcement | none - slice 5 |

**Placeholder scan:** none. Task 2 Step 1 and Task 4 Step 1 direct the implementer to establish facts from the code rather than trust this plan, because the research this plan rests on is one agent's reading and briefs on this project have been wrong about details repeatedly - twice in this session alone.

**Type consistency:** `build_graph() -> Graph` is defined in Task 1 and consumed in 2, 3 and 4. `AGENT_IDENTITY` is defined in Task 2 and consumed in 4. `AgentNode.agent_id` is the permanent key throughout; `display_name` never keys anything.

**One ordering note:** Task 3 depends on Task 1 only, and Task 4 on all three. Task 2 could follow Task 3, but is placed second so the identity split lands before anything starts reading display names from the graph.
