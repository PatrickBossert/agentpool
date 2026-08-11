# Maya: one interview per node, and the stability that makes re-running safe - design

**Date:** 2026-08-11
**Status:** agreed, ready for planning

## Why

Maya's last run completed successfully and produced sixteen interview scripts. The value chain
registry holds eighty-nine activities. Nobody noticed the gap for four days, because nothing states
what Maya owes or checks whether she delivered it.

Measured against the current registry:

| Level | Nodes | Interviews | Uncovered |
|---|---|---|---|
| L0 | 3 | 3 | 0 |
| L1 | 7 | 7 | 0 |
| L2 | 17 | 4 | 13 |
| L3 | 62 | 2 | 60 |
| **Total** | **89** | **16** | **73** |

Mandatory levels are complete. L2 and L3 are sampled by a rule that exists only inside Maya's
prompt and is checked by nothing. Each selected script records a reason in `research_brief`, which
is genuine diligence, but with no stated target a run cannot be judged: sixteen is defensible, and
so would eighty-nine have been.

**The contract is now one interview per node.** Eighty-nine nodes, eighty-nine scripts. Stakeholders
are assigned to scripts separately in Jordan's setup tab, so one script may serve several people -
five frontline roles against one frontline instrument - and the count of interviews conducted is
not the count of scripts generated.

## The blocking problem: re-running is currently unsafe

Reaching eighty-nine will take several runs. Run 30 produced sixteen scripts in an hour, so the
whole set is roughly five hours of generation, and merge-on-write already accumulates across runs.
But two mechanics combine to make a second run destructive rather than additive.

**Maya never reads the existing scripts.** Her task reads `value_levers`, `value_chain_registry`,
and `value_chain_summary`. It never reads `interview_scripts`. She has no knowledge of what already
exists, so a re-run regenerates from the registry as though starting fresh.

**The merge key is a sequence number.** `_merge_with_current` does `merged.update(parsed)` - newest
wins per key - and the key is `script_id`. Today `SC-001` is node `0`, `SC-005` is node `1.2`.
Nothing anchors those; `SC-005` is simply the fifth script she happened to emit.

So a re-run over eighty-nine nodes emits `SC-001..SC-089` in whatever order she works, `SC-005`
lands on a different node than before, and the merge overwrites node `1.2`'s script with another
node's content. The result looks complete and is silently scrambled - worse than regenerating
everything, because the damage is invisible.

This is the same failure the value chain already solved, and the machinery is already half here.
`interview_script_registry` carries the mapping - `{id, node_id, level, relationship, node_label,
active}` - and `validate_script_registry_succession` already refuses redefining or dropping an id.
What is missing is that the write carrying the scripts never consults it. See the correction below.

## The design

### Coverage is checked on node_id

A pure validator beside `tree_validation` and `anchor_validation`, wired into the `_WARNERS` hook in
`sqlite_state.py` so it runs on every `interview_scripts` write and reports into the same warning
surface that carried Alex's `id_redefined`.

It matches **`node_id`**, not `level`. Node ids are unambiguous across both artefacts, which
sidesteps the level vocabulary problem entirely for this purpose.

One warning, not seventy-three: code `incomplete_coverage`, `measure` set to the covered fraction,
and `detail` naming the uncovered ids. A run that reaches full coverage raises nothing.

The warning is already injected into the next run's task by `_fetch_validation_warnings`, which is
how Alex received `missing_l0` and acted on it. So Maya is told what is missing without any new
plumbing.

### The scripts door must consult the script registry

Correction to the account above, established by reading the code rather than assuming: the
authority already exists, and it is already enforced - on one door only.

`validate_script_registry_succession` already refuses moving a registered `script_id` to a
different `node_id`, and already refuses dropping one, with reasoning that names the consequence
("every stored citation through it silently resolves to the wrong script"). But it runs from
`_validate_interview_script_registry`, so it fires only on a write to **`interview_script_registry`**.

The write that actually carries the scripts is checked by `_validate_interview_scripts`, which
verifies that each script anchors to a node the **value chain** registry holds, and that the anchor
is at the right level. It never consults the **script** registry. So a batch emitting `SC-005`
against node `2.7` passes: the node exists, the level is right, and nothing notices that `SC-005` is
registered against `1.2`. The merge then overwrites `1.2`'s script.

There is partial protection by accident - if Maya rewrites the script registry to match her new
numbering, succession refuses that write - but it depends on her writing both artefacts, and the
scripts write is the one that lands first.

This is the two-doors failure CLAUDE.md records: a rule enforced at one entrance and not the other,
where wiring only one silently turns the other's flows into no-ops.

The fix is one cross-check, not a new mechanism: `_validate_interview_scripts` gains a check that
every script whose `script_id` is already registered carries the registered `node_id`, refusing with
a message naming both nodes. The batch fails and the previous version stays current, which is the
established behaviour for a refused batch.

That is what makes the merge safe. `merged.update(parsed)` is correct once the key is stable, and
the key becomes stable once both doors agree.

### Maya generates only what is missing

Her task gains a first step: read `interview_scripts` and `interview_script_registry`, compare
against `value_chain_registry`, and generate scripts **only** for nodes with none. Existing scripts
are not re-emitted, so their text does not churn between runs and a human's edits survive.

The differential falls out of this. Alex adds one node, Maya's next run produces one script.

Her task must also stop directing work into undeclared keys. Run 30 made three refused writes at
the end - `l0_interview_summaries`, `interview_summaries`, and `audit_interview_summaries` - so the
instruction to fan output across keys is still present in her prompt even though the ownership guard
now refuses it.

### Re-running is manual, for now

The validator reports, a human re-runs, and each run picks up the differential. The stopping
condition is machine-checkable, which is the hard part of a loop, but the loop itself is not built
yet. Three reasons:

- A node with no distinct interviewee cannot be satisfied, and an automatic loop would spend hours
  rediscovering that.
- There is no concurrency control if a loop fires while an interview campaign is live. The
  standalone Casey guard exists for exactly this class of collision and covers only Casey.
- Nobody has yet read eighty-nine of these instruments. A loop optimises for the number going up,
  which is the wrong thing to optimise before the instruments are trusted.

Closing the loop later is a small change once those three are settled.

### Level and perspective are separated

A script's `level` currently carries two unrelated meanings: a tier for `L0`-`L3`, and a perspective
for `A`, `S`, `C`, and `F`. The same node is filed differently in the two artefacts:

```
node    registry.level   script.level
0.A     L0               A
0.S     L0               S
1.C     L1               C
1.F     L1               F
```

Both artefacts are internally consistent, which is why nothing has flagged it. The registry files a
role node at its structural tier; the script files it by perspective. Neither is wrong, and the
information is real - an interview with ISS technicians at `1.F` is a different instrument from one
with the Property GM at `1`. What is wrong is one column carrying both facts, so "what tier is this
interview at?" cannot be answered without special-casing.

Scripts gain a `perspective` field - `A`, `S`, `C`, `F`, or null - and `level` carries the tier
only. `MayaOutputExtra`'s two buckets currently render `VC_LEVELS` and `EXT_LEVELS` and **silently
drop anything in neither**, which is a filter masquerading as a layout; it becomes a split on
`perspective` with no possibility of a script vanishing.

Cheaper to do at sixteen scripts than at eighty-nine.

### The Output badge counts the wrong thing

`AgentDetailPanel.tsx:969` renders `{crewOutputs.length}` - the number of `agent_outputs` rows.
For Maya that is thirteen `interview_scripts` versions, plus `interview_script_registry`, plus a
stale `value_chain_registry` she wrote before the ownership guard existed: fifteen, beside a list
showing sixteen interviews.

The badge should count the items the tab displays. The stale `value_chain_registry` row should be
retired - it names an output owned by `value_chain_mapper`, and leaving it there both inflates the
badge and misattributes an artefact.

## Deferred, deliberately

**Section-level activity references, and coverage measured by evidence rather than by instrument.**

Questions carry no node reference - a question has `id`, `text`, `follow_up_count`,
`probing_instructions`, `follow_up_branches`, and `evasion_signals` - and `record_answers` tags every
answer from the script's own anchor. So a frontline technician describing a defect-capture problem
produces evidence filed against `1.F`, not against `1.5.4`.

Letting a section carry an activity reference would preserve interview economy while restoring
attribution, and would allow a node to be covered by evidence without an instrument anchored at it.
That is not being built now, for a stated reason: it trades direct referencability for inference,
and the practicality cannot be judged before a body of real transcripts exists. The retro-fit route
is Casey mapping evidence to additional nodes where the alignment is clear, which keeps the option
open without betting the evidence model on it.

Recorded so the decision survives rather than being rediscovered.

## What this costs

Eighty-nine scripts at roughly nineteen questions each is about **1,700 questions**. The machine
cost is a few hours of generation across several runs. The real cost falls on whoever quality-checks
the instruments, and it does not reduce with better tooling.

## Testing

- **Coverage is asserted against a real registry and a real artefact**, not a fixture pair invented
  for the test, and the warning it raises is read back from `validation_warnings` rather than from
  the validator's return value - the warning reaching the surface is the property, and this
  codebase has recorded seven occasions where an assertion landed one layer from the property it
  named.
- **A re-emitted `script_id` pointing at a different node is refused**, driven through
  `SQLiteStateTool`'s write rather than by calling the guard, because a guard the write does not
  consult is worthless.
- **A second run adds only the missing nodes**, asserted on the merged artefact: existing scripts
  unchanged byte for byte, new ones present. This is the property that makes the whole approach
  viable and it is the one most likely to be tested at the wrong layer, so it is driven through two
  successive writes rather than by inspecting a diff of what Maya was asked to generate.
- **The UI renders every script it is given**, with a script whose perspective is null and one whose
  perspective is unrecognised, since the current failure mode is silent omission.

## Out of scope

The two remaining `llm_mode` authorities are gone; nothing here reopens them. The illustration
pipeline remains sequenced behind the business case writer. Local model configuration is unaffected -
this work changes what Maya is asked to produce, not which model produces it.
