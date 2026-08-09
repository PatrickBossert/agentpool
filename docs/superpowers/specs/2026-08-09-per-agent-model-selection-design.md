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

## Out of scope

The two competing `llm_mode` authorities (`config.yaml` versus the `projects` column) are a known
defect recorded in the previous sub-project's review. This design reads the column, consistent with
`project_llm_mode`. Reconciling the two is separate work and is not made worse here.
