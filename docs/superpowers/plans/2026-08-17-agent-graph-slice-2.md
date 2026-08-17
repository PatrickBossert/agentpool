# Agent graph, slice 2 - what an agent reads, and what leaves the building

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Declare the three facts the graph cannot derive - each tool's egress, each agent's reads, and each crew's purpose and triggers - then make `DataArchitecture.tsx` render from them and close it to the public.

**Architecture:** Declarations live beside the code they describe and are assembled by `agents/graph.py`, as slice 1 established. Egress is declared **per tool** as what it reaches in principle, with the concrete destination resolved through `llm_mode` at read time. Guards assert every tool has a declaration and every artefact read is written by someone.

**Tech Stack:** Python 3.13, pytest, `agents/graph.py` and `agents/identity.py` from slice 1, React 18 + TypeScript.

## Global Constraints

- **British English** - `-ise`, `-our`, `-re`, Oxford comma, spaced en dash ` - `, never an em dash. Binds comments, docstrings, and page copy.
- **Python 3.13** via `./venv/bin/python`. No ORM.
- **Frontend:** `brand` tokens only, never `sky-*` or `blue-*`. Lucide icons, no emoji. `describeError` from `ui/src/utils/describeError.ts`.
- **Backend suite twice with identical counts** - `DATABASE_DIR` is a fixed path that persists between runs. Baseline **1791 passed, 2 skipped, 12 deselected**. Then `cd ui && npx vitest run && npx tsc --noEmit` - baseline **529 passed**, clean.
- **Clear `__pycache__` between a mutation and its revert.** A byte-neutral mutation reverted within the same second leaves `(mtime, size)` unchanged, so Python serves the mutated bytecode from a corrected file and the check passes for the wrong reason. This happened on slice 1. `find . -name "__pycache__" -type d -not -path "./venv/*" -exec rm -rf {} +`
- **Power-check every new test**, one thing at a time, never as a group, and **confirm each mutation actually changes behaviour** before concluding anything.
- **No declaration may be asserted against a list written in the same change.** Assert against the registry, the resolver, or behaviour.
- Stage explicit paths. **Never `git add -A`** - `data/` holds live client databases.
- Do not run anything against `data/`, and do not restart the servers on :8000 or :3000.

---

## File Structure

| File | Responsibility |
|---|---|
| `agents/egress.py` | **Create.** Per-tool declaration of what it reaches in principle, plus the `llm_mode` resolver. |
| `agents/reads.py` | **Create.** Per-agent artefact reads, with storage medium. |
| `agents/graph.py` | **Modify.** Assembles the new declarations; guards them. |
| `api/services/crew_graph.py` or a sibling | **Modify.** Crew purpose and triggers. |
| `ui/src/pages/DataArchitecture.tsx` | **Modify.** Renders from the graph; becomes administrator-only. |
| `tests/test_agent_egress.py` | **Create.** Coverage and resolution guards. |

---

### Task 1: Every tool declares what it reaches

**Files:** Create `agents/egress.py`, `tests/test_agent_egress.py`; modify `agents/graph.py`

**Interfaces:**
- Produces: `TOOL_EGRESS: dict[str, Egress]` keyed on tool class name; `resolve_egress(tool_name, llm_mode) -> Destination`. `AgentNode` gains `egress`, the resolved set for a given mode.

- [ ] **Step 1: Enumerate every tool, and report it before declaring anything**

List every tool class the registry can hand an agent, with `file:line`. **Include `ChainlitHumanInputTool`** - `get_tools_for_agent` substitutes it for `HumanInputTool` when `hitl_tool` is passed (`agents/tools/registry.py:160-161`), and slice 1's cross-check calls without it, so neither the graph nor its guard models the substituted class today. A declaration keyed on class name that omits it has a hole.

For each, say what it actually reaches, **read from the code, not from any document**. Known from research and not to be trusted without checking: `WebFetchTool` is unguarded, Tavily search is ungated on sensitive projects, and `ChromaQueryTool` varies by mode.

- [ ] **Step 2: Write the failing coverage guard**

```python
def test_every_tool_an_agent_can_hold_declares_its_egress():
    graph = build_graph()
    from agents.egress import TOOL_EGRESS
    held = {t for node in graph.agents.values() for t in node.tools}
    assert held <= set(TOOL_EGRESS), f"undeclared: {sorted(held - set(TOOL_EGRESS))}"
```

- [ ] **Step 3: Run it and watch it fail.** Expected: `ModuleNotFoundError`, then a list of undeclared tools.

- [ ] **Step 4: Declare each tool's egress in principle** - "a vector store", "the public internet", "an LLM", "none". Not a concrete host: that is the resolver's job.

- [ ] **Step 5: Write the resolver and its test**

`resolve_egress(tool_name, llm_mode)`. Assert the mode-dependent case both ways - `sensitive` and `standard` give different destinations for the same tool - and that a mode-independent tool gives the same answer in both.

- [ ] **Step 6: Both suites, twice. Power-check** by removing one declaration, and separately by making the resolver ignore its mode argument. Clear `__pycache__` between each.

- [ ] **Step 7: Commit**

```bash
git add agents/egress.py agents/graph.py tests/test_agent_egress.py
git commit -m "feat(graph): every tool declares what it reaches, resolved by mode"
```

---

### Task 2: Every agent declares what it reads

**Files:** Create `agents/reads.py`; modify `agents/graph.py`, `tests/test_agent_graph.py`

- [ ] **Step 1: Establish the reads from the task descriptions, and report what you find**

An agent's inputs exist today only as English inside CrewAI task descriptions. Research found **three already wrong**: `user_journeys` has no writer at all, and `stakeholder_assignments` and `interview_sessions` are tables the state tool cannot see. **Verify each of those three yourself** and report any others - a declaration that copies a wrong description is worse than none, because a guard will then bless it.

- [ ] **Step 2: Write the failing guard**

```python
def test_every_artefact_read_is_written_by_someone():
    graph = build_graph()
    written = {w for node in graph.agents.values() for w in node.writes}
    for node in graph.agents.values():
        unwritable = set(node.reads) - written
        assert not unwritable, f"{node.agent_id} reads what nobody writes: {sorted(unwritable)}"
```

- [ ] **Step 3: Run it and watch it fail** - on the three wrong reads, if they are real.

- [ ] **Step 4: Declare the reads, with storage medium**, and **fix or exclude the three wrong ones**. If a read is genuinely of a database table rather than an artefact, the model needs a medium for that - say so rather than forcing it into the artefact vocabulary.

- [ ] **Step 5: Suites twice; power-check by adding a read nobody writes.** Clear `__pycache__`.

- [ ] **Step 6: Commit**

---

### Task 3: Every crew declares its purpose and triggers

**Files:** Modify `api/services/crew_graph.py` (or a sibling if that file should not grow), `agents/graph.py`, tests

- [ ] **Step 1: Enumerate the dispatch paths, and report them**

Four are known: the REST path, `autostart_service`, PAM's `RunCrewTool`, and n8n's `/orchestrate` webhook. Confirm each, find any fifth, and say for each crew which can start it and whether anything is time-triggered via `scheduler_service` or `scheduled_jobs`.

- [ ] **Step 2: Write the failing guard** - every crew has a purpose and at least one trigger; every trigger named is a dispatch path that exists.

- [ ] **Step 3: Run, fail, declare, pass. Suites twice. Power-check** by naming a trigger that does not exist.

- [ ] **Step 4: Commit**

---

### Task 4: The privacy page renders from the graph, and closes to the public

**Files:** Modify `ui/src/pages/DataArchitecture.tsx`, `ui/src/router.tsx`, tests

- [ ] **Step 1: Close the route**

`/data-architecture` is currently outside `ProtectedRoute` - public by omission, not design: nothing public links to it, its only link sits inside `ProtectedRoute`, and `/architecture` beside it is already guarded. Wrap it, administrator-only. **Check for a public consumer before you do** - an interview participant has no login, and if any campaign email or interview page references it, stop and report rather than breaking that path.

- [ ] **Step 2: Write the failing test** - the route is unreachable without a session, and reachable with an administrator's.

- [ ] **Step 3: Render the egress table from the graph**, per project, so the answer reflects that project's `llm_mode`. The page currently names Anthropic 44 times, Tavily 17, and **`WebFetch` zero times** - the generated table must include everything declared in Task 1, whether or not the old prose mentioned it.

- [ ] **Step 4: Keep what the graph cannot say.** The page carries retention and processing commitments that are not derivable - Deepgram and ElevenLabs streamed with no retention, the skills library's deliberate hosted exception. Preserve those as prose, clearly separated from the generated table, and say in your report which is which.

- [ ] **Step 5: Both suites twice, `tsc` clean. Power-check** the route guard and the generated table separately.

- [ ] **Step 6: Commit**

---

## Self-Review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| Each tool's egress declared, resolved through `llm_mode` | 1 |
| An agent's reads declared, with storage medium | 2 |
| Each crew's purpose and triggers declared | 3 |
| `DataArchitecture.tsx` renders from the graph | 4 |
| The page becomes administrator-only | 4 |
| The graph viewer | none - follows this slice |
| Per-project overrides | none - slice 3 |
| n8n removal | none - slice 4 |
| Enforcement | none - slice 5 |

**Placeholder scan:** none. Tasks 1, 2 and 3 each open by directing the implementer to establish facts from the code and report them, because the research this rests on is one agent's reading and my briefs were wrong four times during slice 1 - including a module location, a test guard that whitelisted the coupling it guarded, and a cycle-safety claim that did not hold.

**Type consistency:** `TOOL_EGRESS` and `resolve_egress` are defined in Task 1 and consumed in 4. `AgentNode.egress` and `.reads` are added in Tasks 1 and 2 and consumed in 4. Crew purpose and triggers are added in Task 3 and consumed in 4.

**One ordering note:** Task 4 depends on all three. Tasks 1-3 are independent of each other and could run in any order; egress is first because it is the fact the privacy page most needs and the one most likely to surface something uncomfortable.
