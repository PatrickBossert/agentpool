# L0 Anchor and Level-Anchored Synthesis - Design

**Status:** agreed 2026-08-06

**Goal:** Make the value chain tree an absolute reference with an organisation-level root and
role nodes, and make Casey anchor themes at the level where the insight actually lives.

## Why

Two problems, one cause.

**The L0 is missing from the tree.** `DeriveRegistryTool` derives the registry by flattening
`value_chain_tree.json`, so a node reaches the registry only if it is in the tree. Alex's tree is
a bare list of L1 entities with no root, and the evidence is unambiguous:

| Registry | Activities | L0 present |
|---|---:|---|
| `v1` - written by `interaction_designer` | 82 | `('0', 'GS UK Portfolio (Organisation)')` |
| `v2` to `v5` - written by `value_chain_mapper`, **v5 current** | 79 to 81 | none |

The only registry that ever contained an L0 was the one Maya hand-wrote, bypassing derivation.
That write is now refused by the ownership boundary, correctly - it was not her artefact - but it
was a correct diagnosis of a real upstream gap, and the `blocked_writes` record is what preserves
the finding.

**Themes anchor only at `n.n.n`.** Casey's theme schema offers `activity_ids` and nothing else, so
even a well-instructed Casey has nowhere to put a governance theme except on an arbitrary L3
child. This does not merely lose resolution: it **systematically biases downstream value
proposition generation toward L3 efficiency**, because that is the only altitude the evidence is
ever expressed at. It is a pipeline-shaping property, not a formatting detail.

The two are the same problem. Casey can only anchor a theme at L0 if an L0 exists to anchor it to.

## The node model

The tree is the canonical spine. Every node is addressable, permanent, and derivable.

```
0                    GS-UK                        L0   organisation
├─ 0.A               Audit                        L0   role node
├─ 0.S               Corporate Services frontline L0   role node
├─ 1                 Property                     L1   entity
│  ├─ 1.C            Property customer            L1   role node
│  ├─ 1.F            Property frontline           L1   role node
│  ├─ 1.1            Strategic Planning           L2   stage
│  │  └─ 1.1.1       Asset Hierarchy              L3   activity
│  └─ 1.2 …
├─ 2                 Fleet                        L1
│  ├─ 2.C  2.F …
└─ 3                 Support Services             L1
```

**L2 and L3 belong to exactly one L1.** Nothing is shared or duplicated across entities. A third
party such as ISS appears as activities within the entity whose value chain it participates in,
and gets interview scripts written for it like any other participant.

**Role nodes are activities.** `0.A`, `0.S`, `<L1>.C` and `<L1>.F` are ordinary registry entries -
assignable by Jordan, anchorable by Casey, visible in the value chain. They exist to give an
outside-in and bottom-up view of how well things are working: `C` is what the organisation looks
like from outside, `F` what it feels like from underneath.

Audit and Corporate Services frontline sit at L0 because they are organisation-level activities.
Customer and Frontline sit at L1 because a Fleet customer and a Property customer need different
interview scripts, as do a Fleet frontline worker and a Property one.

Whether a given L1 warrants `C` or `F` is Alex's judgement per project. Support Services may
warrant neither, since `0.S` already covers corporate services frontline.

**IDs are a permanent contract.** The registry's succession rule - may grow, may retire, may never
redefine or forget - now binds the tree as well, because Architecture's corporate capability model
will be built against these IDs and downstream requires absolute consistency.

**Role nuance never lives on the node.** It lives on the stakeholder, as a free-text
`role_description` the interviewer reads as context. That is what lets a single `F` programme
serve both `1.F` and `2.F` while the answers still differ - Property frontline lacking mobile
tooling, Fleet frontline triple-processing applications. Casey derives distinct themes per node
from the same instrument.

## How nodes get there, and stay there

Alex emits the root and role nodes in `value_chain_tree`. **`DeriveRegistryTool` needs no
change** - it already recurses `children` and assigns `parent_id`, so the L0 and role nodes
flatten into the registry for free, and anything dropped from the tree is marked `inactive` rather
than deleted.

What is new is a **structural validator**: a pure function taking the new tree and the previous
registry, returning warnings. It runs in `SQLiteStateTool`'s write path for `value_chain_tree`,
beside the existing `_VALIDATORS` entries, so it fires wherever the tree is written.

| Check | Code | On failure |
|---|---|---|
| Root `0` exists, is `L0`, and every L1 descends from it | `missing_l0` | warn and record |
| Each L1 carries the role nodes it carried in the previous registry | `missing_role_node` | warn and record |
| No previously-active ID has been redefined or silently dropped | `id_redefined` | warn and record |

**On the first run there is no previous registry**, so the second and third checks have no baseline
and are skipped. Only `missing_l0` applies, because the root is required unconditionally. This is
stated explicitly because a validator that silently passes when it has nothing to compare against
is indistinguishable from one that is broken.

**Role IDs end in an alphabetic segment** - `0.A`, `1.C`. `api/services/value_chain_model.py:35`
already tolerates this (`int(part) if part.isdigit() else _UNORDERABLE`), so ordering is defined
and nothing crashes; role nodes simply do not interleave with their numbered siblings. No change
is needed there, but the implementer should confirm it rather than assume it.

All three **warn and record rather than refuse.** A refusal would block the run and lose the work;
a silent pass loses the signal. Recording makes the gap a finding - the same move the ownership
work made with `blocked_writes`, where a refused write became the only surviving evidence that the
L0 was missing.

The third check is the one that turns "IDs are stable only by prompt" into something observable.
It cannot stop Alex renumbering, but it makes renumbering visible the moment it happens rather
than when a downstream capability model fails to resolve.

`DeriveRegistryTool` deliberately does **not** synthesise a missing root. It cannot repair the
tree - `value_chain_tree` is Alex's key and the write would be refused by the ownership boundary -
so synthesising would leave the registry holding anchors the tree and the value chain UI cannot
display, reintroducing a resolution gap through a different door.

## Where warnings are recorded

One new table, written by both validators:

```sql
validation_warnings (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id  INTEGER NOT NULL REFERENCES projects(id),
  run_id      INTEGER,
  source      TEXT NOT NULL,   -- 'value_chain_tree' | 'theme_anchor'
  subject     TEXT,            -- node id or theme id
  code        TEXT NOT NULL,
  detail      TEXT NOT NULL,
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

Surfaced in the agent's **Status tab**, which is already this project's home for an artefact's
history, and in the **PAM report**, because Pamela cannot report accurately on a crew whose output
is structurally suspect.

Deliberately not `blocked_writes`. That table means "an agent reached for something it does not
own", which is a different fact; overloading it would blur a distinction the ownership work paid
to establish.

## Casey's level-anchored synthesis

Casey produces horizontal themes (efficiency and effectiveness) and vertical themes (maturity),
then summarises `strategic_requirements` from both - some of which are smaller tactical items
rather than systemic ones.

The theme schema replaces `activity_ids` with `anchors`, which may reference **any** registry node:

```json
{"id": "TH-01", "kind": "horizontal|vertical", "theme": "...", "description": "...",
 "anchors": ["1.F", "2.F"], "evidence": [{"answer_id": 812, "stakeholder_id": 1, "quote": "..."}]}
```

The level expectation Casey designs against:

| Anchor level | What belongs there |
|---|---|
| **L0** - `0`, `0.A`, `0.S` | Governance, assurance, and vertical/maturity themes |
| **L1** - `1`, `1.C`, `1.F` | Functional: exec-level customer, frontline sentiment, data and process governance, maturity rankings across vertical themes |
| **L2** - `n.n` | Decision: the bulk of effectiveness-related, data-enabled decision and maturity change |
| **L3** - `n.n.n` | Tactical and efficiency, with some effectiveness |

Existing rules that stay: cite `answer_id` never a label; weight unprompted mentions above
prompted agreement; every theme carries at least two evidence entries from different stakeholders.

The **anchor validator** is pure - themes plus registry in, warnings out - and raises two distinct
kinds of warning:

1. **Per-theme mismatch** (`anchor_level_mismatch`) - a vertical/maturity theme anchored below L1,
   or a governance theme anchored at L3.
2. **Distribution skew** (`l3_skew`) - when more than 70% of themes anchor exclusively at L3, and
   there are at least five themes. The threshold is a starting value, not a derived one; it is
   stated here so the implementation does not invent its own, and it lives in one named constant
   so it can be tuned once evidence exists. The minimum-count guard stops a run with two themes,
   both legitimately tactical, from raising a skew warning that means nothing.

The second matters most. It is the signature of the bias rather than any individual mistake, and
no single theme looks wrong when it happens: every individual L3 anchor can be perfectly
defensible while the set is badly skewed. Per-item validation cannot catch an emergent property;
only looking at the population can.

## Project context record

The L3-bias factor is recorded in `CLAUDE.md`, which is loaded into every session, with this spec
as the fuller account. The statement to record:

> Themes and requirements must anchor at the level where the insight lives - L0 for governance,
> assurance and vertical themes; L1 for functional; L2 for decision and effectiveness; L3 for
> tactical and efficiency. Anchoring everything at `n.n.n` loses resolution and systematically
> skews value proposition generation toward L3 efficiency.

## Testing

- **Tree validator** - pure. Fixtures: a tree missing the root; one that redefines a previously
  active ID; one that drops a role node an earlier version carried; a correct one. Each asserts
  the exact warning code, and the correct tree asserts silence.
- **Anchor validator** - pure. Fixtures: a vertical theme anchored at L3; a governance theme at
  L3; a set of ten themes where eight anchor exclusively at L3 while every individual theme is
  defensible, proving the distribution check fires when per-item checks do not; a set of four
  all-L3 themes proving the minimum-count guard suppresses it; and a balanced set proving silence.
- **`DeriveRegistryTool`** - a tree containing a root and role nodes produces a registry
  containing the L0 and those role nodes with correct `parent_id` values. This is the regression
  that started all of this.
- **Warnings** - a warning is written once per occurrence, and re-running does not duplicate it.

## Not in this spec

`role_description` on the stakeholder record (sub-project F, Jordan's directory); Maya's
incremental build (E); the reviewer feedback loop (C); tokenised review links and the Slack stub
(D); multiple types per role code; and `n.n.n.F` activity-specific role nodes such as a
call-centre frontline supporting sales. The last two are extensibility we have deliberately
deferred - the current model is insightful enough without over-complicating it.
