# Forcing local inference without moving the vector store

**Date:** 2026-08-19
**Status:** draft for review

## Why

`sp-gs-am` runs against Chroma Cloud so the project is portable between clients. Measuring local
model performance today means switching it to `sensitive`, which also repoints Chroma at the
local instance and takes every document and interview embedding out of reach. The two things
move together and only one of them is wanted.

**This cell was ruled out by mistake.** The deployment-modes note called local-inference-with-
cloud-vectors "the nonsense cell nobody wants". It is a development-testing configuration and a
real one, and had sovereign mode been built on that assumption it would have been foreclosed.

## What already exists

sp57's egress inversion separated the axes without knowing this would be asked for. One grants
table, two independent capabilities, and two routers asking independent questions of it:

| Mode | `CLOUD_VECTOR_STORE` | `HOSTED_INFERENCE` |
|---|---|---|
| `standard`, `fallback` | granted | granted |
| `sensitive` | - | - |

`agents/model_registry.py` asks about `HOSTED_INFERENCE`; `api/services/chroma_client.py` asks
about `CLOUD_VECTOR_STORE`. All four cells of the matrix are already expressible. Nothing here
needs a new concept - only a way to say "this project, not this mode".

## The shape: narrowing only, never a fourth mode

A per-project flag, `force_local_inference`, that **removes** `HOSTED_INFERENCE` from whatever
the project's mode grants. It can never add a capability.

Three reasons this beats a fourth enum value:

**It cannot open anything.** Set subtraction only shrinks, so no setting of the flag creates an
egress path the mode did not already carry. A new mode is a new row in the grants table that has
to be got right, and sp57 exists because getting that class of thing wrong is silent.

**Its failure is loud, and correct.** With no local model configured for a tier,
`get_llm_for_agent` raises `LocalModelUnavailable` rather than substituting a hosted model. For
a performance measurement that is the only acceptable answer - a silent fallback would benchmark
Anthropic and report it as local.

**It is not a client-facing configuration.** `sensitive`, `sovereign` and `global` describe what
a client bought. This describes what an engineer is measuring this afternoon. Putting it in the
mode enum makes the client-facing list longer and stranger for no gain.

## Where it is asked

`permits(mode, capability)` takes a **mode**, not a slug, so the flag cannot be consulted inside
it. A second function is added beside it:

```
project_grants(slug)            -> granted_to(mode) minus the project's forced removals
project_permits(slug, capability)
```

The two routers move from `permits(mode, ...)` to `project_permits(slug, ...)`; both already
hold the slug. `permits` stays, because the **declared** question - what does this mode grant -
is still a real one and is what the mode-name inventory guards.

The removal is expressed as set difference and nothing else. A union anywhere in this path is
the defect.

## Storage

A column on `projects`, not a `config_json` key. `llm_mode` is a column for a stated reason -
`_refuse_platform_tier_setting_changes` reads `projects.llm_mode` rather than the `config_json`
copy, because a guard compared against a copy is bypassed the moment the copy drifts - and the
same reasoning applies to a flag that decides egress.

This is a **project** database, so it needs a `_migrate_*`, a `_SCHEMA_VERSION` bump in the same
change, the column added to `CREATE TABLE`, and the test fixtures that build `projects` by hand.
That is the opposite of the rule for `system.db`, where `init_system_db` has no version gate.

Resolution must be **synchronous**, because both routers are, and cached the way
`project_llm_mode` is - registered with `process_cache` so the suite's isolation covers it
without anybody remembering. Reading it in the same query as `llm_mode` is worth considering,
since every call site that wants one wants the other.

## Who may set it

`_PLATFORM_TIER_SETTINGS`, beside `llm_mode`. Turning it **on** only narrows, but turning it
**off** widens, and a client-side `project_admin` must not be able to do that. The existing
guard compares the *transition* rather than the field's presence, so it already handles the
Settings tab round-tripping the whole body.

## The privacy page must show the resolved answer

`/data-architecture/{slug}` derives from the grants table. If the flag narrows what a project
may do and the page still renders the mode's declared row, **it tells an auditor prompts go to
Anthropic while they are going to Ollama**. Wrong in a harmless direction, on the one surface
whose purpose is being right.

This is the largest piece of the work and the reason the task is not just a boolean.

## What must remain impossible

**Forcing hosted inference on a sensitive project.** The narrowing-only rule delivers this by
construction, and "by construction" is the kind of claim this project asserts rather than
trusts. It gets its own test: a sensitive project with the flag in every state still resolves
locally, and no combination reaches `HOSTED_INFERENCE`.

## Testing

- A `standard` project with the flag set resolves **local models and Chroma Cloud** - the cell
  the whole change exists for. Assert the client and the LLM that are built, not a helper's
  return value.
- A sensitive project is unaffected in every flag state.
- `LocalModelUnavailable` is raised, not a hosted fallback, when local models are unconfigured.
- The privacy page reports the resolved grants, not the declared ones.
- A `project_admin` is refused the flag; a platform-tier caller is not.
- The mode-name inventory still passes, and **a new guard covers the flag**: nothing outside the
  resolver may read it directly. sp58 built two source-walk guards of this shape; follow them,
  and state in the docstring what the walk cannot see.

## Out of scope

Sovereign mode. Renaming `standard` to `global`. Renaming `_TIER_SETTINGS`' second key from mode
names to `local`/`hosted` - already queued, and it should land before sovereign or the key
becomes actively misleading. A reverse flag forcing hosted inference: it has no use and would
break the guarantee the narrowing rule provides.
