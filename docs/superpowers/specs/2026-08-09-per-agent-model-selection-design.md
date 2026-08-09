# Per-agent model selection - design

**Date:** 2026-08-09
**Status:** agreed, ready for planning

## Why

Agents in one crew have genuinely different needs. Casey, the Synthesis Analyst, reasons across
hundreds of interviews and their answers. Avery and Taylor coordinate sessions and dispatch. Alex
produces the value chain spine that everything downstream inherits. The current structure cannot
express any of that: a crew factory picks one model and hands it to every agent it builds.

Where per-agent differentiation does exist, it is hardcoded per factory and thrown away in secure
mode. `agents/crews/value_design_crew.py:35-43` is the shape of the problem:

```python
if llm is not None:
    vpg_llm = pm_llm = llm
elif llm_mode == "sensitive":
    _local = get_crew_llm("sensitive")
    vpg_llm = pm_llm = _local      # both collapse to one local model
else:
    vpg_llm = get_pam_llm()        # Opus
    pm_llm = get_haiku_llm()       # Haiku
```

Standard mode differentiates; sensitive mode collapses. And `LOCAL_LLM_MODEL` is a single setting,
so secure mode is structurally incapable of running more than one local model however the factories
are written.

The cost of knowledge living in eleven factories was demonstrated during the previous sub-project:
`discovery_interviews_crew.py` declared `llm_mode` as a parameter and never read it, putting Casey
on a hosted model while it held `ChromaQueryTool` over the project's own interview answers. Sixteen
task-scoped reviews passed it. Only a whole-branch read caught it.

## The design

### Two tiers, declared by the agent

`agents/model_registry.py` holds two tables and one resolver, mirroring how
`agents/tools/registry.py` already maps an agent to its tools:

```
AGENT_TIER  : agent_name -> "fast" | "deep"
resolve     : (tier, llm_mode, project_settings) -> LLM
```

| Tier | Agents |
|---|---|
| **fast** | `interview_coordinator`, `stakeholder_interviewer`, `stakeholder_manager`, `portfolio_manager`, `roadmap_generator` |
| **deep** | `interaction_designer`, `synthesis_analyst`, `value_chain_mapper`, `value_lever_analyst`, `value_proposition_generator`, `enterprise_architect`, `initiative_identifier`, `requirements_capture`, `requirements_analyst`, `business_plan_generator`, `visual_illustrator`, `pam` |

Fast is coordination and mechanical assembly: creating sessions, dispatching outreach, sequencing a
roadmap from a register that already exists. Deep is anything reasoning across a corpus, or
producing a structure that others inherit and cannot easily correct.

Three assignments are changes from today, each deliberate:

- **Casey rises to deep.** It reasons over every answer in a campaign - potentially hundreds of
  interviews - and its output is what the business case rests on.
- **Maya rises to deep.** She generates the instruments the whole campaign is conducted through; a
  weak question is not recoverable after the fact.
- **PAM takes no exemption.** CLAUDE.md currently states PAM always uses `claude-opus-4-6`
  regardless of sensitive mode. PAM holds `SQLiteStateTool` and can therefore read project outputs,
  so that exemption was a hole in the secure-mode guarantee. PAM is `deep` and routes locally like
  everything else. **CLAUDE.md line 208 must be rewritten as part of this work.**

`portfolio_manager` stays fast because it already deliberately uses Haiku today.

### Crew factories stop choosing models

Every factory calls `get_llm_for_agent(agent_name, llm_mode, slug)` per agent, exactly as it already
calls `get_tools_for_agent(agent_name, ...)`. No factory contains a model name or a mode branch.

This is the structural point rather than a tidiness one: a factory that cannot choose a model cannot
forget to consult `llm_mode`, which is the defect that shipped past sixteen reviews. The `llm=`
override parameter stays - integration tests inject a cheap model through it, and it is the only
consumer of `get_test_llm`.

### Configuration lives in project settings, and nowhere else

Four fields per project, each falling back to a code default when unset:

| Setting | Default |
|---|---|
| `anthropic_fast_model` | `claude-haiku-4-5` |
| `anthropic_deep_model` | `claude-opus-4-6` |
| `local_fast_model` + `local_fast_url` | `gemma-4` @ `http://localhost:11434/v1` |
| `local_deep_model` + `local_deep_url` | `qwen3.5-27b` @ `http://localhost:11434/v1` |

Separate URLs per tier, so a deployment may run one llama.cpp server per model on its own port, or a
single Ollama endpoint serving both by name.

**`LOCAL_LLM_MODEL` and `LLAMACPP_BASE_URL` are removed rather than kept as a fallback.** The
whole-branch review of the previous sub-project found `llm_mode` already has two competing
authorities - `projects/<slug>/config.yaml` and the `projects.llm_mode` column - where the YAML
fails *open*, meaning a drifted file routes a sensitive project's agents to Anthropic. Adding
environment variables beside project settings would make a third source for the same class of fact.
Code default, then project setting. Nothing else.

Every new field must be declared on `ProjectSettings` in `api/models.py`. A field absent from that
model is dropped inbound by Pydantic's `extra='ignore'`, deleted from `config_json` by
`update_project_settings`'s wholesale `model_dump()`, and stripped outbound by `response_model` -
which is precisely how the elaboration press budget shipped inert with two passing tests.

### Secure mode fails closed

A sensitive project whose tier has no reachable model **refuses the run**, naming the tier and the
setting that would fix it. It never falls back to a hosted model, and never silently borrows the
other tier's model. A deployment with only one local model may point both tiers at it, but only by
writing it in both settings - the collapse must be someone's decision rather than the code's.

### The live follow-up stays local

`elaboration_press` is not an agent and takes no tier. It is a direct API call on the interviewee's
request path, already routed by `project_llm_mode` and already bounded by a configurable budget.

There is a real question whether a local model answers follow-ups fast enough for a live
conversation. The answer for now is the budget that already exists: an over-budget press returns no
press and the interview continues to the next scripted question, which costs depth on one answer
rather than a silence. **This work adds duration logging on every press, and a count of skips**, so
that decision can be made from one real campaign's numbers rather than a guess. No hosted override
is built until that data exists.

Note for whoever revisits it: an override would send `response_text` - the interviewee's verbatim
answer - to Anthropic, so it is a confidentiality decision presented to a user as such, not a
performance toggle.

## Running two local models at once

Two tiers means two models resident simultaneously, which is a deployment concern rather than
application configuration. It belongs in the runbook, but the constraints shape this design and are
recorded here.

### The local path must set max_tokens

`agents/llm.py` sets `max_tokens=16384` on the hosted path with the comment *"the default 4096
clips large tool-call JSON outputs (e.g. questionnaire scripts ~8K tokens, value chain tree ~2.5K
tokens)"*. The sensitive branch immediately below sets nothing, so secure mode clips exactly the
outputs that comment describes. **This work must set `max_tokens` on both paths.** It is a
pre-existing defect, but it would be indistinguishable from the local models being incapable, and
would be diagnosed as such.

### Context sizing, from measured artefacts

Ollama's default `num_ctx` is 4096 and it truncates **silently** - the oldest tokens go first, which
are the instructions. Measured against the live project:

| Artefact | Approx tokens |
|---|---|
| `value_chain_tree` | 2,900 |
| `value_chain_registry` | 3,482 |
| `value_chain_model` | 12,230 |
| `interview_scripts` (accumulated) | 130,523 |

An agent's system prompt plus task plus a single `value_chain_model` read already exceeds 4096.
Recommended starting points: **16384 for the deep model, 8192 for the fast model**, raised from
`ollama ps` once real footprints are known.

The accumulated `interview_scripts` figure is deliberately not a sizing target. Maya's merge happens
inside `SQLiteStateTool`, not in the model's context, and Casey retrieves through `ChromaQueryTool`
rather than reading the corpus whole. If any agent is ever asked to read that artefact directly, it
will need a different approach rather than a larger window.

### Keep-alive, and the setting that silently defeats the others

```
OLLAMA_KEEP_ALIVE=-1          # never unload; both models stay resident
OLLAMA_MAX_LOADED_MODELS=2    # at least 2, or the models evict each other
OLLAMA_NUM_PARALLEL=4         # concurrent requests per model
```

`OLLAMA_MAX_LOADED_MODELS` is the important one. At its default of 1 the two models evict each other
on every alternation regardless of keep-alive and regardless of free memory, which presents as the
local models being slow rather than as a configuration problem.

Keep-alive matters because interviewees arrive at lunchtimes with hours of silence between. At the
5 minute default the fast model is cold-loaded repeatedly, and a multi-gigabyte load from disk in
front of a waiting interviewee is precisely the latency the press budget would then skip - so the
budget would mask a configuration fault as a model limitation.

Memory, at Q4_K_M: roughly 3 GB for a 4B fast model and 17 GB for a 27B reasoning model, before KV
cache. On 24 GB that is workable but not comfortable, which is why the context sizes above start
conservative and are raised from measurement rather than set optimistically.

### Casey must not run while interviews are live

Running the Synthesis Analyst saturates the reasoning model while the fast model is serving live
follow-ups. Within the crew this is already impossible: `discovery_interviews_crew` is
`Process.sequential`, Casey's task takes `context_tasks=[t2]`, and Avery's task blocks on
`HumanInputTool` until a consultant replies "ready" - the prompt says "when all interviews are
complete".

The standalone agent dispatch bypasses it. `api/services/run_service.py:626` builds Casey's task
with `context_tasks=[]`, so re-running Casey from the agent panel during a live campaign runs it
immediately. That is the only path where the collision is reachable.

**Standalone dispatch of `synthesis_analyst` must refuse when the project has interview sessions in
`pending` or `active` status**, naming how many and telling the consultant to wait or to mark them
abandoned. A refusal rather than a queue: the crew path already expresses "wait for interviews"
correctly, and a second mechanism for the same idea is how two authorities for one fact come about.

## Deferred: the illustration pipeline

`visual_illustrator` currently writes `illustration_briefs` - text prompts grounded in real project
data, with an explicit instruction never to invent system names. That is reasoning work, which is
why it takes the `deep` tier here.

It will need a genuine image-generation pipeline, with different backends for different illustration
types. That is **not** a third model tier: Mermaid is a renderer and Flux.2 [klein] 4B runs via a
shell, and neither returns an `LLM`. Folding them into `TIER_MODEL` would make one resolver return
two incompatible kinds of thing. The pipeline belongs in the tool layer, which already gives one
agent several capabilities.

Recorded requirement, to be designed separately:

- Different backends per illustration type - technical schematics differ from as-is/to-be vignettes.
- Secure mode: Mermaid for technical drawings, Flux.2 [klein] 4B via shell for vignettes, both local.
- Standard mode has no backend chosen. That is the first question the separate design must answer,
  and it is open deliberately rather than pending: the local pair above is a firm requirement, while
  the hosted equivalent depends on what the business case actually needs from an illustration once
  one has been produced.
- The six illustration types the Illustrator's task already defines (vision, proposition vignettes,
  architecture schematic, roadmap, operating model change, future state) are the input to that
  design.

**Sequencing: this is addressed after the business case writer is built and tested.** The
`business_plan` crew became buildable only recently, when `visual_illustrator` was registered, and it
has never completed a real run. Designing an illustration pipeline for a crew that has not yet
produced a business case would be designing against assumptions.

## Testing

The load-bearing test: **every agent in the tool registry has a tier**, asserted as a set equality.
That is the shape that caught `visual_illustrator` missing from `tool_map`, where the crew raised
before its first task and four unit tests passed anyway.

Then:

- **Two agents in one crew receive different models.** The collapse in `value_design_crew` is the
  defect being fixed, so it is asserted directly rather than inferred from the registry.
- **A sensitive project resolves both tiers to local URLs, with two projects interleaved in one
  process.** A per-deployment implementation passes every single-project test and fails only this
  shape.
- **An unconfigured tier raises in secure mode** rather than falling back, and the error names the
  tier and the setting.
- **The settings round-trip** through `PATCH /{slug}/settings` and back through `GET`, driving the
  real endpoints rather than mocking the API client. Both of the press budget's tests mocked the
  client, which is why a dead field passed review.
- **No crew factory contains a model name or a mode branch**, as a source guard - the same technique
  used for bare-filename reads and raw database connections, both of which recurred across six and
  seven sites respectively before a guard was added.
- **Both LLM paths set `max_tokens`**, asserted on the constructed object rather than by reading the
  source, so the sensitive branch cannot regress to the unset state it is in today.
- **Standalone Casey refuses while sessions are pending or active**, driven through the dispatch
  entry point rather than by calling a guard helper - the guard is worthless if the dispatch does
  not consult it, which is the failure this codebase has recorded seven times.

## Out of scope

The two competing `llm_mode` authorities (`config.yaml` versus the `projects` column) are a known
defect recorded in the previous sub-project's review. This design reads the column, consistent with
`project_llm_mode`. Reconciling the two is separate work and is not made worse here.
