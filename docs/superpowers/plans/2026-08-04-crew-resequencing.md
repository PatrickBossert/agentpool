# Crew Re-sequencing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-order the crews downstream of the interviews so each consumes what the one before it produced, move Morgan to where her inputs are, and rename two crews to what they do.

**Architecture:** Task 1 changes the sequence itself - the dependency graph that enforces it and the order that displays it. Task 2 moves Morgan. Task 3 renames two crews and migrates the rows that name them. Task 4 follows with the factories and outputs. Task 5 corrects the agent bios and tasks that are now wrong.

**Tech Stack:** FastAPI, aiosqlite, CrewAI, pytest. React 18, TypeScript, Vitest.

## Global Constraints

- British English (`-ise`, `-our`, `-re`) in comments, copy, prompts, and test names.
- Spaced hyphen ` - ` in prose, never an em dash `—`. Hyphenated compound adjectives are fine.
- All raw SQL lives in `api/database.py`. `agents/tools/human_input.py` must not be modified.
- **A crew's identity is declared in five places** - `CREW_DEPENDENCIES` (api), `_CREW_AGENT_NAMES` (api), `CREW_ORDER`, `CREW_AGENT_NAMES` and `CREW_AGENTS` (ui). They are declarations of one fact and have drifted before. Change them together; test that they agree.
- **Baselines: backend 853 passed / 2 skipped, frontend 346 passed.** Report both actual totals every task.
- Never `git add -A` or `git add .`. Stage by name.

---

### Task 1: The sequence, enforced and displayed

**Files:**
- Modify: `api/services/crew_graph.py` - `CREW_DEPENDENCIES`
- Modify: `ui/src/components/agentStatus.ts` - `CREW_ORDER`
- Test: `tests/test_crew_graph.py` (extend or create), `ui/src/__tests__/CrewSequence.test.ts` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: the sequence every later task assumes. Crew keys are **unchanged in this task** - `architecture` and `discovery` keep their names until Task 3, so the rename is not tangled with the re-order.

**Why:** `CREW_DEPENDENCIES` is what readiness and autostart compute from, and it currently gives `discovery` **no dependencies at all** - it may run at any time, including before the interviews it is meant to follow. `CREW_ORDER` displays a sequence the graph does not enforce.

- [ ] **Step 1: Write the failing tests**

```python
def test_requirements_waits_for_the_capabilities_that_scope_it():
    # discovery had no dependencies at all, so it could run before the interviews it is
    # meant to follow - the defect that makes the displayed order a fiction.
    assert CREW_DEPENDENCIES["discovery"] == ["architecture"]


def test_value_design_no_longer_waits_for_requirements():
    # Value propositions come from Casey's themes. Waiting on a crew that now runs two
    # steps later would deadlock the pipeline outright.
    assert CREW_DEPENDENCIES["value_design"] == ["discovery_interviews"]


def test_delivery_waits_for_requirements_not_for_capabilities():
    assert CREW_DEPENDENCIES["delivery"] == ["discovery"]


def test_the_graph_is_acyclic_and_every_crew_is_reachable():
    # A cycle deadlocks the board silently: every crew waits and none is ever ready.
    ...
```

```ts
it('displays the crews in an order the dependency graph permits', () => {
  // Two declarations of one sequence. A display order that contradicts the graph shows a
  // crew as next when it cannot run, which is worse than showing nothing.
  // CREW_DEPENDENCIES is mirrored in the test fixture; assert every crew appears after
  // all of its dependencies.
  ...
})
```

- [ ] **Step 2: Run to verify they fail, then change both**

```python
CREW_DEPENDENCIES: dict[str, list[str]] = {
    "discovery_mapping":      [],
    "assessment_design":      ["discovery_mapping"],
    "stakeholder_management": ["assessment_design"],
    "discovery_interviews":   ["assessment_design", "stakeholder_management"],
    "value_design":           ["discovery_interviews"],
    "architecture":           ["value_design"],
    "discovery":              ["architecture"],
    "delivery":               ["discovery"],
    "business_plan":          ["delivery"],
}
```

`CREW_ORDER` moves `discovery` from fifth to seventh, after `architecture`.

- [ ] **Step 3: Run everything and commit**

Run: `./venv/bin/pytest -q --ignore=tests/integration`, then `npx vitest run && npx tsc --noEmit` from `ui/`.

```bash
git add api/services/crew_graph.py ui/src/components/agentStatus.ts tests/ ui/src/__tests__/
git commit -m "feat(crews): requirements runs after capabilities, and the graph says so"
```

---

### Task 2: Morgan joins value chain mapping

**Files:**
- Modify: `api/services/run_service.py` - `_CREW_AGENT_NAMES`
- Modify: `ui/src/components/agentStatus.ts` - `CREW_AGENT_NAMES`, `CREW_AGENTS`
- Modify: `agents/crews/discovery_mapping_crew.py`, `agents/crews/discovery_crew.py`
- Test: `tests/test_crew_membership.py` (create)

**Interfaces:**
- Consumes: Task 1's sequence.
- Produces: `discovery_mapping` holds `value_chain_mapper` and `value_lever_analyst`; `discovery` holds `requirements_capture` and `requirements_analyst`.

**Why:** two jobs were conflated. *What levers and KPIs does this organisation already talk about* is document analysis and belongs early, before Maya designs against them. *Which levers does the evidence support* is the Value Proposition Generator's job, later. Morgan currently sits in a crew that runs before the interviews while doing work that needs their evidence.

- [ ] **Step 1: Write the failing tests**

```python
def test_morgan_is_in_the_mapping_crew():
    assert "value_lever_analyst" in _CREW_AGENT_NAMES["discovery_mapping"]


def test_morgan_is_in_exactly_one_crew():
    # Asserting only the new home would pass while the agent ran twice per pipeline.
    homes = [c for c, a in _CREW_AGENT_NAMES.items() if "value_lever_analyst" in a]
    assert homes == ["discovery_mapping"]


def test_every_agent_belongs_to_exactly_one_crew():
    # The general form. A move that duplicated any agent would be caught here whether or
    # not anyone wrote a test for that agent.
    ...


def test_the_three_membership_declarations_agree():
    """_CREW_AGENT_NAMES here, CREW_AGENT_NAMES and CREW_AGENTS in the frontend. Reading
    one and asserting against a literal proves nothing about the other two, and they have
    drifted before - the frontend comment says it mirrors this map, which is a promise
    nothing checks."""
    # Parse the frontend declarations from agentStatus.ts and compare.
    ...
```

- [ ] **Step 2: Run to verify they fail, then move her**

Move `value_lever_analyst` between the two maps in each of the three declarations, and between the two crew factories. Morgan runs **after** Alex within `discovery_mapping`: her levers are read from documents, and Alex's chain gives her the structure to hang them on.

- [ ] **Step 3: Run everything and commit**

```bash
git add api/services/run_service.py ui/src/components/agentStatus.ts agents/crews/ tests/test_crew_membership.py
git commit -m "feat(crews): Morgan analyses levers where her inputs are"
```

---

### Task 3: The renames, and the rows that carry them

**Files:**
- Modify: every file declaring a crew key - `api/services/crew_graph.py`, `run_service.py`, `agent_chat_service.py`, `pam_report_service.py`, `skills_service.py`, `api/models.py`, and the frontend's `agentStatus.ts`, `crewOutputs.ts`, `crewIcons.tsx`, `AgentDetailPanel.tsx`, `AgentStatusTab.tsx`, `ReviewDialog.tsx`, `OrgChart.tsx`, `Dashboard.tsx`, `Settings.tsx`
- Modify: `api/database.py` - a migration
- Test: `tests/test_crew_rename_migration.py` (create)

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: `architecture` → `capabilities`, `discovery` → `requirements`, everywhere including stored rows.

**Why:** a key reading `discovery` for a crew running seventh is the stale name this exercise exists to remove. And `crew_runs.crew_name` holds 13 rows for one project, with `approval_commits` and `crew_submissions` carrying the same column: rename in code alone and every historical run belongs to a crew that no longer exists, so it vanishes from the board rather than reading as history.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_a_historical_run_is_renamed_not_orphaned(client):
    """Asserting that new rows use the new name would pass while every past run
    disappeared from the board - which is the whole risk of a rename."""
    # Insert a crew_runs row named 'architecture', run the migration, assert it reads
    # 'capabilities' and still appears in the project's run history.
    ...


@pytest.mark.asyncio
async def test_commits_and_submissions_are_renamed_too(client):
    # Both carry crew_name. Migrating only crew_runs would leave a commit gate keyed to a
    # crew nothing can run.
    ...


def test_no_code_path_still_writes_the_old_names():
    # A grep-style assertion over the declaration sites, so a half-finished rename fails
    # here rather than at runtime on someone's board.
    ...
```

- [ ] **Step 2: Run to verify they fail, then rename**

Do the code rename and the migration in one change - a deploy with one and not the other is exactly the broken state the tests describe. The migration is idempotent (`UPDATE ... WHERE crew_name = 'architecture'`), so running it twice is harmless.

- [ ] **Step 3: Run everything, check the live project, commit**

Report how many rows the live `sp-gs-am` migration renamed. It holds 13 crew runs; a count of zero means the migration did not run rather than that there was nothing to do.

```bash
git add api/ ui/src/ tests/test_crew_rename_migration.py
git commit -m "feat(crews): architecture becomes capabilities, discovery becomes requirements"
```

---

### Task 4: Factories and outputs follow

**Files:**
- Rename: `agents/crews/architecture_crew.py` → `capabilities_crew.py`, `agents/crews/discovery_crew.py` → `requirements_crew.py`
- Modify: `api/services/run_service.py` - `build_and_run_crew`'s inline imports
- Modify: `ui/src/components/crewOutputs.ts` - `CREW_OUTPUT_TYPE`
- Test: `tests/test_crew_output_types.py` (existing - it derives the allowed set from the agent modules)

**Interfaces:**
- Consumes: Task 3's names.
- Produces: `capabilities` → `initiative_register`; `requirements` → `requirements`; `discovery_mapping` keeps `value_chain_model` as primary with `value_levers` secondary.

**Why:** `CREW_OUTPUT_TYPE.discovery` currently names `value_levers`, which left with Morgan. Left alone, the renamed Requirements crew would declare a primary artefact none of its agents writes - and `tests/test_crew_output_types.py` derives the allowed values from the agent modules, so it will say so.

- [ ] **Step 1: Run the existing test to see it fail**

Run: `./venv/bin/pytest tests/test_crew_output_types.py -q`
Expected: FAIL once Task 3 lands - `requirements` claims an output nothing in it produces.

- [ ] **Step 2: Rename the factories, repoint the map**

`value_levers` becomes a **secondary** output of `discovery_mapping`: real, versioned, in Status, and not the artefact the crew is judged on. Alex's `value_chain_model` stays primary.

- [ ] **Step 3: Run everything and commit**

```bash
git add agents/crews/ api/services/run_service.py ui/src/components/crewOutputs.ts
git commit -m "feat(crews): factories and primary outputs follow the rename"
```

---

### Task 5: The bios that are now wrong

**Files:**
- Modify: `ui/src/components/agentStatus.ts` - `AGENT_ROLE`, `AGENT_SKILLS`
- Modify: `agents/discovery/value_lever_analyst.py`, `agents/discovery/requirements_capture.py`, `agents/discovery/synthesis_analyst.py`, `agents/architecture/*.py`
- Test: `tests/test_agent_bios.py` (create)

**Interfaces:**
- Consumes: everything above.
- Produces: no importable interface.

**Why:** the panel shows `AGENT_ROLE` and `AGENT_SKILLS` to a reader deciding whether an agent is doing its job. Four now describe work that has moved or changed.

| Agent | What is now wrong |
|---|---|
| **Value Lever Analyst** | Described as working from "discovery findings". Works from **documents**, before the interviews, and her output is **hypotheses to test** rather than findings |
| **Requirements Capture** | Runs an open dialogue producing `interview_transcript`. Running seventh against existing initiatives, the job is initiative-scoped enumeration, and that key reads as one of Avery's stakeholder interviews |
| **Synthesis Analyst** | Describes synthesis only; now owns the horizontal and vertical themes |
| **Enterprise Architect / Initiative Identifier** | Described in architecture terms; compile as-is capabilities and derive uplift initiatives from a value proposition gap |

**Requirements Analyst keeps his bio unchanged.** Riley analyses a captured requirement set for completeness, consistency and conflict - unchanged work, moved turn. Do not rewrite it, and say in your report that you did not: a re-sequencing that quietly rewrote every bio would lose the difference between a changed job and a moved turn.

- [ ] **Step 1: Write the failing tests**

```python
def test_morgans_bio_no_longer_claims_she_works_from_discovery_findings():
    # Assert on the phrase that is now WRONG, not on the presence of a new one. Adding a
    # sentence while leaving the stale one is the likely half-fix and would pass the
    # other form.
    assert "discovery findings" not in AGENT_ROLE["Value Lever Analyst"]


def test_morgans_task_frames_her_output_as_hypotheses():
    """Levers read out of documents are what the organisation claims to care about. If
    Maya treats them as established, the interviews anchor on them and lose the ability to
    contradict them - and the value of Casey's themes is that they come from what people
    actually said."""
    ...


def test_rileys_bio_is_untouched():
    # The one that must NOT change. Pinning it makes the distinction deliberate rather
    # than incidental.
    ...
```

Read `AGENT_ROLE` from `agentStatus.ts` in the Python test the way `tests/test_crew_output_types.py` already reads a frontend map, or write this one in Vitest - follow whichever pattern that test established rather than inventing a second.

- [ ] **Step 2: Run to verify they fail, then rewrite the four**

- [ ] **Step 3: Run everything and commit**

Run both suites. This is the last task, so the pair confirms nothing drifted.

```bash
git add ui/src/components/agentStatus.ts agents/ tests/test_agent_bios.py
git commit -m "fix(agents): bios describe the work each agent now does"
```

---

## Not in this plan

**The citation integrity fix** - scripts keyed by `node_label`, sections with no id, and
question ids that collide across every script at the same level. Casey cannot cite an
interview section durably until that is fixed, and it changes Maya's output format, so it is
its own piece of work and a prerequisite for the *content* of themes rather than for this
re-sequencing.

**What Casey's themes actually say**, how value propositions are worded, and how complexity or
cost are estimated - agent instructions rather than structure.
