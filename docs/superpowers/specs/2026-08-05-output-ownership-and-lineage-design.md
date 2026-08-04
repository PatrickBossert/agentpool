# Output Ownership and Lineage - Design

**Date:** 2026-08-05
**Status:** Approved for planning

Gives every output key one owning agent, records what each output was built from, and derives
staleness from that record rather than from anyone remembering.

## Why

On 2026-08-04 Maya wrote Alex's `value_chain_registry`. She was not wrong to want it - the L0
entity was genuinely missing - but the write destroyed a file, produced two rows both claiming
to be current, and had no effect, because nothing reads the version it landed on.

Three independent gaps made that possible. **Any one of them alone would have prevented the
damage.**

### The tool has no owner

`SQLiteStateTool` is constructed with `slug` and nothing else. Both `key` and `agent_name` are
arguments the calling agent supplies at call time:

```python
class SQLiteStateToolInput(BaseModel):
    key: str         = Field(description="Unique key for this state blob (used as filename)")
    agent_name: str  = Field(description="Name of the agent writing/reading this state")
```

An agent's output instruction lives in its prompt, and a prompt is guidance rather than a
boundary. Nothing restricts which keys an agent may write, and nothing checks that the claimed
`agent_name` is the agent actually calling. Maya did not impersonate anyone - she wrote
`agent_name='interaction_designer'` honestly. She wrote a key that was not hers, because
nothing said she could not.

### The version and filename namespaces disagree

```
version  = MAX(version) WHERE project_id AND agent_name AND output_type   ← per agent
filename = {key}_v{version}.json                                          ← per output type
```

Her first `value_chain_registry` was numbered v1, and v1 was a filename Alex had already used.
`insert_agent_output_sync` renames the output to its versioned path, so the rename overwrote
his file.

`is_current` supersession is scoped the same way, so marking hers current never cleared his.

### An existing guard covers intent, not behaviour

`test_no_output_key_has_two_writers` asserts that no state key has two writers - but it reads
the *declared task descriptions*. Maya's registry write was never declared; she improvised it
mid-run. Intent and behaviour need different mechanisms, and ownership belongs in the tool, at
call time.

### Nothing records what an output was built from

`agent_outputs` records what was written and by whom. It records nothing about inputs, so
"Maya's scripts were built from a value chain that has since been superseded" is not a
question the system can answer. It has happened more than once without anything noticing.

### Citations are instructed and impossible

`ChromaQueryTool` returns `results["documents"]` and discards `metadatas`:

```python
docs = results.get("documents", [[]])[0]
return "\n\n---\n\n".join(docs)
```

So Morgan cannot know which document a chunk came from, and her required `source` field can
only be inferred from the prose or invented - every existing value should be treated as
unverified. Casey has the same problem for `answer_id`, which is instructed and sits in the
metadata the tool throws away.

The metadata also carries `filename`, which is the *hashed* stored name
(`d89a0be7c73442a08cde5080b0797c16.pdf`). A citation naming that is useless to a reader; a
citation naming `doc_id` resolves through `client_documents` to `SPUK_2025_Annual_Accounts.pdf`
and can be checked.

## The design

### 1. Identity moves from the argument into the tool

`get_tools_for_agent(agent_name, ...)` already knows which agent it is building tools for, so
the tool takes its identity at construction:

```python
SQLiteStateTool(slug=slug, agent_name=agent_name)
```

The call argument stays for compatibility and is **verified rather than trusted** - a claimed
`agent_name` that differs from the tool's own identity is refused. An identity an agent asserts
about itself is not an identity.

### 2. One owner per output key

`OUTPUT_OWNERS` in `agents/tools/registry.py` maps each state key to its owning agent. Writes
to a key you do not own are refused. **Reads stay open** - reading upstream is the normal case
and the whole pipeline depends on it.

Keys owned by nobody are refused too, because every legitimate write is a declared one.

**This also ends the batching.** Maya wrote her scripts as `interview_scripts_batch1` through
`batch9`, which left the Output tab showing a version from 24 July, the review queue empty, and
every validator bypassed - `_VALIDATORS` keys on the exact string `interview_scripts`. All
three symptoms had that one cause. If she may write only `interview_scripts`, none of them can
recur.

`test_no_output_key_has_two_writers` becomes the map's keeper: every key a task description
tells an agent to write must be owned by that agent. The map is the authority, and the test
holds the prompts to it.

### 3. Blocked writes are recorded

```sql
CREATE TABLE IF NOT EXISTS blocked_writes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id),
    run_id        INTEGER,
    agent_name    TEXT NOT NULL,
    key           TEXT NOT NULL,
    owner         TEXT,
    reason        TEXT NOT NULL,
    attempted_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

A refusal alone throws away a signal. Maya reaching for the registry was a correct diagnosis of
a real upstream gap, and PAM reporting "Maya was blocked writing Alex's registry" states the
gap rather than the misbehaviour.

The attempted payload is deliberately **not** stored - it can be large, and the useful fact is
that the reach happened and why.

### 4. The namespace fix

Version numbering and `is_current` supersession drop `agent_name` from their scope, so both
match the filename namespace. Ownership makes cross-agent writes impossible, which leaves this
as belt-and-braces - but it is the difference between a refused write and a destroyed file.

### 5. Lineage is captured, not declared

`SQLiteStateTool` records every read it serves - `(run_id, key, version_resolved)` - and on
write links the new output to every state input read during that run.

```sql
CREATE TABLE IF NOT EXISTS output_lineage (
    output_id       INTEGER NOT NULL REFERENCES agent_outputs(id),
    input_output_id INTEGER NOT NULL REFERENCES agent_outputs(id),
    PRIMARY KEY (output_id, input_output_id)
);
```

Captured from what actually happened rather than declared, so it needs no agent cooperation and
cannot be misreported. Run granularity is deliberate: an agent that reads four inputs and writes
three outputs links all three to all four. Per-write attribution is fussier and buys nothing a
reader would act on.

### 6. Document citations are the second edge type

An output built from documents has no state ancestry and real document ancestry. Both belong in
lineage:

```sql
CREATE TABLE IF NOT EXISTS output_citations (
    output_id  INTEGER NOT NULL REFERENCES agent_outputs(id),
    doc_id     INTEGER NOT NULL REFERENCES client_documents(id),
    locator    TEXT,
    PRIMARY KEY (output_id, doc_id, locator)
);
```

For this to be possible at all, **`ChromaQueryTool` must return metadata alongside text**. Each
result carries its `doc_id` and the document's `original_name` - not the hashed stored filename
- so an agent can cite something a person can open. For the `interviews` collection it carries
`answer_id` and the answer's tags, which is what Casey was already instructed to cite and could
not.

A cited `doc_id` absent from `client_documents` is a broken citation and is detectable. That is
the difference between a citation and a claim.

### 7. Staleness is derived, never stored

An output is **stale** when any input it was built from has a newer *approved* version.

Measured against approval rather than the last write, because agents write several versions
inside one run - Alex wrote `value_chain_tree` v7, v8 and v9 within ninety seconds - and those
are working state rather than deliverables. Flagging on every write would make a downstream
artefact flash stale three times during one upstream run and settle only when it finished.

Derived by query rather than stored as a flag, so it cannot drift, and outputs written before
this feature exists have no lineage and read as **unknown** rather than fresh. Unknown is the
honest answer for them.

### 8. The Lineage tab

A tab on the Runs page: current outputs per agent, what each was built from with the version it
read, and stale markers naming the version gap.

```
Alex    value_chain_model      v16   approved
          └ Maya    interview_scripts   v5    STALE - built from v15
              └ Jordan  assignments     v3    STALE - built from scripts v5
          └ Morgan  value_levers        v2    ok - 3 documents cited
```

Document ancestry renders as a count with the documents named on expansion, so an output with
no state ancestry reads as evidenced rather than as an orphan.

## Repairing the existing damage

Two `is_current` rows for `value_chain_registry` in `sp-gs-am`, and Alex's original
`value_chain_registry_v1.json` overwritten by Maya's 82-entry version.

**The original content is not recoverable.** `.gitignore` line 25 excludes `projects/*`, so no
copy exists. The loss is bounded rather than serious: the registry's succession rules forbid
dropping an id, and v5 contains every id v2 recorded, so no id meaning was lost - what is gone
is the audit record of what the ledger said on 1 August.

The repair marks Maya's row superseded so one `is_current` row remains, and leaves the file in
place under a name that no longer claims to be Alex's v1. Deleting it would destroy the only
evidence of what happened.

## Testing

**Ownership:**
- An agent writing a key it does not own is refused, and the refusal names the owner.
- An agent writing a key nobody owns is refused - this is the batching case, and asserting only
  the cross-agent case would let `interview_scripts_batch1` through.
- A claimed `agent_name` differing from the tool's own identity is refused.
- Reads of another agent's key still succeed. A boundary that blocked reads would stop the
  pipeline, so this is asserted rather than assumed.
- Every key any task description instructs an agent to write is owned by that agent.

**Blocked writes:**
- A refused write leaves a `blocked_writes` row naming the agent, the key, and the owner.
- The refusal is still returned to the agent. Recording it instead of telling it would leave
  the agent looping on a write it cannot see failing.

**Namespaces:**
- Two agents writing the same output type produce different filenames, and neither file is
  overwritten. The current fixture cannot fail this - it needs two agents.
- Only one row per (project, output_type) is `is_current` after both writes.

**Lineage:**
- An output written after reading two inputs links to both.
- An output that read nothing has no lineage rows, and reads as unknown rather than fresh.
- Reading the same input twice in one run produces one edge, not two.

**Citations:**
- `ChromaQueryTool` returns `doc_id` and `original_name` for project documents, and `answer_id`
  for the interviews collection.
- The hashed stored filename is not what is offered for citation - asserting only that some
  identifier is present would pass with the useless one.
- A citation naming a `doc_id` absent from `client_documents` is reported as broken.

**Staleness:**
- An output built from v15 is stale once v16 is approved, and not before.
- Intermediate versions written during an upstream run do not mark anything stale.
- A downstream output rebuilt after the approval is no longer stale.

## Out of scope

**The differential.** Telling a re-run what changed - "1.4 added, 2.3 relabelled" - so it can
rebuild only the affected parts. Deliberately set aside: it needs a differ per artefact type and
a rule for what an agent does with a diff it only partly understands.

**Automatic re-runs.** Staleness is reported; a human decides what to re-run.

**The tree-entity validation and Maya's own re-run**, which belong to the existing fix queue
rather than to this design.
