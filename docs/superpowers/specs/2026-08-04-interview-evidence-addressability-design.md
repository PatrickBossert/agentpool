# Interview Evidence Addressability - Design

**Date:** 2026-08-04
**Status:** Approved for planning

Makes every interview answer addressable, tagged, and retrievable, so Casey can group
strategic requirements from evidence rather than from prose - and separates the two levels of
requirement that currently overwrite one another.

## Why

Casey's job is to identify **strategic requirements**: the challenges and opportunities in
value chain activity or maturity that the organisation must address to unlock value. Sam and
Riley do something different - the **change requirements** that deliver the capability uplift
initiatives Sage defines. Different levels, different evidence, different consumers.

He cannot do his job today, for three separate reasons.

### The two requirement levels collide in one slot

Casey writes `key='requirements'` at step 4. Riley writes `key='requirements'` at step 7. Sage
reads `requirements` at step 6 and gets Casey's strategic set, which is correct. Riley then
overwrites the slot at step 7, so the roadmap (step 8) and the business plan (step 9) read the
same key and get change requirements, with the strategic set gone.

This is live data loss on every full pipeline run, and nothing reports it.

### No interview script links to a node

`node_label` is the script's own title in every case:

| Level | `node_label` |
|---|---|
| L0 | `GS UK Portfolio — L0 Board Interview` |
| L1 | `PROPERTY VALUE CHAIN L1 Interview` |
| L2 | `Strategic Planning & Standards L2 Interview` |
| A | `GS UK Internal Audit & Compliance Assessment Interview` |
| C | `Scottish Power Networks Regional Operations Customer Interview` |

A reader can map the L1 title to segment `1`. No code can. A and C are the hardest cases
because no node name appears at all, but the missing join is universal - the value chain has
stable `Ln.n.n` IDs and nothing references them.

There is also nothing for A and C to anchor *to*. The model's top level is the three chains;
GS UK exists as a *party*, which is a contributor to chains rather than a node.

### There is no vertical axis to group by

The scripts contain **178 distinct section titles**. Maturity dimensions are free text scoped
to one node - `"Decision Clarity — Strategic Planning & Standards"`, `"Composite Capability
Maturity — Fleet Value Chain"` - and only L1 and L2 sections carry them at all; A, C, F and S
scripts have none. Some `section_id` values are `null`. Question ids are `Q1.1`,
section-relative, so every one of the 17 L2 scripts emits `Q1.1`.

So grouping "within a discipline" today means clustering prose, and a citation resolves to
whichever script the reader happened to be looking at.

**No interview data exists yet** - 2 stakeholders, 0 sessions, 0 assignments. Every decision
below is a design-time choice rather than a migration.

## The design

### 1. The anchor: a reserved root node

The value chain registry gains a reserved root node with the fixed ID `0`, representing the L0
entity. The three chains become its children. `n.n.n` numbering is untouched because `0` sits
above it.

```
0          SP-GS / GS UK              L0 entity
├ 1        Property                   L1 chain
│  └ 1.2     Planned Maintenance      L2 stage
│     └ 1.2.3  Statutory Inspection   L3 activity
├ 2        Fleet
└ 3        Services
```

Its label comes from the project's `client_name`, editable in Alex's Setup alongside the
entity list. Exactly one L0 node exists; its ID is always `0`; it is never removed and never
renumbered.

### 2. Every script carries a node ID and a relationship

Scripts gain two fields. `node_label` survives as the display title and stops being the join.

```json
{
  "script_id": "SC-014",
  "node_id": "1.2",
  "level": "L2",
  "relationship": "internal",
  "node_label": "Strategic Planning & Standards L2 Interview"
}
```

Anchoring by type:

| Type | Anchors to |
|---|---|
| L0 | `0` |
| L1 | a chain - `1`, `2`, `3` |
| L2 | an `n.n` stage |
| L3 | an `n.n.n` activity |
| A, C, S | `0`, or a chain when genuinely scoped to one - a fleet operator-licence regulator anchors to `2` |
| F | the L2 or L3 the person actually works in |

`relationship` is one of `internal`, `customer`, `regulator`, `supplier`, `partner`. It is
what makes "external, but still about SP-GS" a stored fact rather than an inference. A
customer script anchored to `0` with relationship `customer` reads correctly whether the
interviewee sits in SPN or in a renewable energy company - they are a customer of the L0
entity either way.

**Why anchoring alone is not enough:** without `relationship`, an auditor's script and a board
member's script both anchor to `0` and become indistinguishable. Casey needs to know that six
answers about governance came from one regulator and five internal managers, not eleven
internal managers.

### 3. Citation integrity

Scripts are keyed by a registered `script_id` - `SC-001`, `SC-002` - assigned in order, never
changed and never reused, under the same succession rules the value chain registry already
enforces. The ID is opaque: the node is a field on the script, not something parsed out of the
ID, so a script that moves node keeps its identity and every citation to it stays valid.

Node-derived script IDs were rejected: node `0` carries several scripts at once (L0, A, C, and
one per S function), so a node-derived key collides on the very node this design exists to
make usable.

`section_id` becomes mandatory and unique within its script. A question ID is then
`<script_id>.<section_id>.<question_no>`:

```
SC-014.S3.Q2
```

Unique by construction rather than by luck of the sample, and stable across Maya rewriting any
title.

### 4. The answer store

**`interview_answers` in SQLite is the system of record.** One row per question per session,
written by the interview service at session completion - it is a fact of the session, not an
agent's opinion, so no agent writes it.

```sql
CREATE TABLE IF NOT EXISTS interview_answers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES interview_sessions(id),
    stakeholder_id  INTEGER NOT NULL REFERENCES stakeholders(id),
    script_id       TEXT    NOT NULL,
    section_id      TEXT    NOT NULL,
    question_id     TEXT    NOT NULL,
    question_text   TEXT    NOT NULL,
    answer_text     TEXT    NOT NULL DEFAULT '',
    answered        INTEGER NOT NULL DEFAULT 1,
    follow_up       INTEGER NOT NULL DEFAULT 0,
    node_id         TEXT    NOT NULL,
    chain           TEXT,
    level           TEXT    NOT NULL,
    relationship    TEXT    NOT NULL,
    party_id        TEXT,
    discipline      TEXT    NOT NULL,
    question_intent TEXT    NOT NULL,
    elicitation     TEXT    NOT NULL,
    rating          INTEGER,
    answered_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

`chain` is the root of `node_id` - `1`, `2`, or `3` - and is null for a script anchored to `0`,
because an interview about the entity is not about one chain. A query for "everything about
Fleet" that silently included entity-level answers would attribute a board member's remark to
a chain they never mentioned.

**A skipped question still produces a row**, with `answered = 0` and empty `answer_text`. An
absent row would mean "not asked" and a blank one means "asked and not answered", and coverage
cannot tell an instrument that missed a topic from a stakeholder who declined it unless both
are recorded.

#### The session has to record which question an answer belongs to

Today it does not. `qa_pairs` is `{question: string, answer: string}[]` - the question **text**
and nothing else - so an answer cannot be traced to the question that produced it even within
its own script. The pairs also mix three different things without distinguishing them: scripted
questions, LLM-generated follow-up probes, pre-scripted follow-up branches, and section-level
prompts (synthesis check, peer referral, forward roadmap).

So the capture contract changes:

| Kind | `question_id` | `follow_up` |
|---|---|---|
| Scripted question | the script's ID - `SC-014.S3.Q2` | 0 |
| Pre-scripted branch | parent question's ID, suffixed `.B1`, `.B2` | 1 |
| Generated probe | parent question's ID, suffixed `.F1`, `.F2` | 1 |
| Section-level prompt | the section's ID - `SC-014.S3` | 0 |

A follow-up carries its parent's tags, including `elicitation`: a probe is further evidence
about the same question, not a new one. Counting probes as separate questions would overstate
both coverage and the weight of a theme - an interviewee pressed three times on one point would
read as three stakeholders' worth of agreement.

The tags are denormalised onto the row deliberately. Casey groups by an exact value without a
four-way join, and every tag is a fact fixed at the moment the answer was given - a later
rename of a node must not retrospectively change what an interview was about.

Rows are append-only, which is what makes `interview_answers.id` usable as a citation token.

**Chroma collection `<slug>_interviews` carries one document per answer.** The embedded text
is a short context preamble followed by the question and the answer, so a semantic hit arrives
with its own frame rather than as an orphan sentence:

```
[Property > Planned Maintenance (1.2) | L2 | internal | discipline: data]
Q: How confident are you that the asset condition record reflects reality?
A: For compliance reporting, yes. For deciding what to replace next year, no...
```

Metadata carries the same tags, so retrieval filters before it ranks - "answers about data
from customers of the Fleet chain" is a filtered query, not a hope about embedding similarity.

`ChromaQueryTool` gains `collection='interviews'` alongside `project` and `sector`.

**Exact grouping and coverage come from SQL; recall comes from Chroma. Neither does the
other's job.** Counting how many stakeholders mentioned something is a fact, and a vector
search is the wrong instrument for a fact.

### 5. The tag set

**Derived at ingestion, never authored** - `node_id`, `chain`, `level`, `relationship`,
`party_id`, `stakeholder_id`, `script_id`, `section_id`, `question_id`. These come from the
script and the stakeholder record. Nobody types them, so nobody can mistype them.

**Authored by Maya at design time:**

`discipline` - a closed vocabulary configured once per project, set on a section and inherited
by its questions, overridable per question:

| Value | Meaning |
|---|---|
| `governance` | Governance and accountability |
| `data` | Data and information |
| `technology` | Technology and applications |
| `process` | Process and operating model |
| `people` | People and capability |
| `commercial` | Commercial and contract management |
| `assurance` | Risk, compliance, and assurance |
| `finance` | Finance and investment |
| `sustainability` | Sustainability and carbon |

Configured in Maya's Setup tab, because designing what the instruments measure is her job.
Because the list is closed, a value off it fails at write time the way an unknown value chain
ID already does, and PAM can report interview coverage per discipline.

`question_intent` - one of `context`, `evidence`, `maturity`, `challenge`, `opportunity`.
Casey's remit is challenges *and* opportunities; tagging the question's intent makes that split
a query rather than a judgement he has to re-derive from prose, and it keeps scene-setting
questions out of the evidence base.

`elicitation` - `unprompted` or `prompted`. Whether the question named the thing it was asking
about. This is a separate axis from intent, and it is what makes a count readable: "six
stakeholders raised data quality" means something entirely different if five of them were
handed the phrase. Casey weights unprompted mentions higher because the tag lets him, rather
than because he inferred it from the wording.

**Derived by Casey** - nothing. He writes themes and requirements that cite answer IDs.

**Considered and rejected:** sentiment (Casey's analysis, not a fact of the answer); stakeholder
seniority (already on the stakeholder record, so denormalising it adds a second copy of a fact
that can drift); and a free-text keyword field (the thing this design exists to replace).

### 6. Testing Morgan's hypotheses without anchoring on them

Morgan reads the annual report and the client's other material and produces value levers and
KPIs as hypotheses. Maya must reference them, and must not reference them first.

**Maya reads `value_levers`**, which she does not today - she reads only the registry and the
summary. An untested hypothesis is worse than an absent one: unreferenced, Morgan's levers
flow to value design unverified, which is exactly what framing them as hypotheses was meant to
prevent.

**The ordering rule: unaided sections precede prompted ones, and the order is never reversed.**

- Early sections ask unaided - what gets in the way, what you would change, what happens when
  it goes wrong. A lever nobody wrote in the annual report can only surface here.
- A late section tests Morgan's levers by name: *"Your annual report names fleet availability
  and carbon reduction as priorities. Does that match what you see? Which is real and which is
  aspirational?"* An interviewee can contradict the annual report, which is the outcome that
  makes the exercise worth running.

Naming a lever early buys agreement rather than evidence, most sharply from the junior and
frontline voices that most need to be heard cleanly. Sequencing is the fix; omission is not.

**The interviewee is the wrong source for value magnitude.** A depot manager knows the van has
been off the road for nine days and knows the workaround; they do not know what that costs the
business. The split is: the interviewee supplies the challenge, its frequency, the workaround,
and the consequence; Morgan and the value design crew supply what it is worth.

**Each lever acquires a status derived from the answers**, not asserted by anyone:

| Status | Meaning |
|---|---|
| `contradicted` | Prompted answers dispute it |
| `confirmed_unprompted` | Raised without being named - the strongest result |
| `confirmed_prompted` | Only agreed with once named - visibly the weaker result |
| `untested` | No question referenced it |

`untested` is the one that matters most, because it is the failure the current design cannot
see at all: a lever that reached value design without a single interview touching it.

### 7. Casey's two artefacts

A theme is a pattern in the evidence - what people said. A strategic requirement is what the
organisation must therefore be able to do. Keeping them separate means a reviewer can accept
the evidence and still challenge the conclusion, and a requirement supported by three themes
is written once.

```json
{
  "id": "TH-04",
  "kind": "vertical",
  "discipline": "data",
  "statement": "Asset condition data is trusted for compliance but not for investment",
  "node_ids": ["1.2.3", "1.4.1", "2.3.2"],
  "evidence": [{"answer_id": 812, "stakeholder_id": 7}, {"answer_id": 903, "stakeholder_id": 11}]
}
```

```json
{
  "id": "SR-07",
  "statement": "A single asset condition record that investment planning can rely on",
  "kind": "challenge",
  "from_themes": ["TH-04", "TH-09"],
  "node_ids": ["1.2.3", "1.4.1", "2.3.2"]
}
```

Horizontal themes group by node position across the chain; vertical themes group by
`discipline`. Both axes are now stored facts, which is the whole point of the tagging.

Every theme carries evidence from at least two different stakeholders. One voice is an
individual perspective.

### 8. The two requirement levels, separated

| Artefact | Owner | Step | Key |
|---|---|---|---|
| themes | Casey | 4 | `themes` |
| strategic requirements | Casey | 4 | `strategic_requirements` |
| change requirements | Sam | 7 | `captured_requirements` |
| requirements analysis | Riley | 7 | `requirements_analysis` |

`requirements` is retired as a key. Sage reads `strategic_requirements`. The roadmap and the
business plan read both, named explicitly, so a document that needs the strategic framing and
the delivery detail gets both rather than whichever ran last.

Riley's rename is bio-neutral: "produces a structured, prioritised requirement analysis" is
his own wording, and his job is unchanged.

### 9. Coverage follows the anchor

Coverage becomes a query over (node, relationship) rather than node alone, so "node `0` has
internal coverage but no customer coverage" is expressible.

Anchoring A and C scripts to `0` therefore gives L0 coverage only. It does not inflate
coverage of the chains beneath, consistent with the existing rule that an executive
interviewed with an L0 script does not represent coverage for the stages below them.

## Existing scripts are regenerated, not migrated

The 26 script files have no node IDs, no disciplines, inconsistent `section_id` including
`null`, and 178 distinct section titles. Migrating means guessing an anchor for each one.
Since no interviews have run, Maya regenerates them under the new schema - cheaper, and honest
about the fact that the anchors were never recorded.

## Phasing

Each phase depends on the one before it, except the first.

1. **The requirement key split** (section 8). Independent of everything else and fixes live
   data loss today.
2. **Root node `0`, script IDs, and anchoring** (sections 1, 2, 3).
3. **The tag vocabularies** (section 5) - discipline, question intent, and elicitation, in
   Maya's Setup and her output schema.
4. **Morgan's levers reach Maya, and the ordering rule** (section 6) - Maya reads
   `value_levers`, unaided sections precede prompted ones, and lever status is derived.
5. **The answer store** (section 4) - SQLite table, Chroma collection, ingestion at session
   completion.
6. **Casey's themes and strategic requirements** (section 7), citing answer IDs.

## Testing

**Citations:**
- Two scripts at the same level produce no colliding question IDs. The current fixture holds
  one script per level and cannot fail this - the test needs two nodes at one level, or it
  asserts a property of the sample rather than of the scheme.
- A section is addressable by an ID that survives Maya rewriting its title.
- A theme citing an answer resolves to exactly one answer, in one session, on one node.

**Anchoring:**
- Every script resolves to exactly one registry node; a script anchored to an unknown node
  fails at write time rather than at read time.
- An A or C script anchored to `0` contributes L0 coverage and no chain coverage.
- Coverage distinguishes relationships: a node with only internal interviews reports missing
  customer coverage rather than full coverage.

**Tagging:**
- A discipline outside the configured vocabulary fails at write.
- A question with no discipline of its own inherits its section's; an overridden question keeps
  its own.
- An answer row's tags match its script's at ingestion time, and a later node rename does not
  change them.

**Session capture:**
- A completed session writes one answer row per Q&A pair, and every row resolves to a question
  or section that exists in that session's script.
- A generated follow-up carries its parent's question ID and tags, and does not count as a
  separate question for coverage. A test with one question and two probes must report one
  question covered, not three.

**Elicitation and the ordering rule:**
- In every script, the first section tagged `prompted` comes after the last section tagged
  `unprompted`. This is the whole rule, and it is checkable, so it is checked rather than left
  to Maya's instructions.
- A script that names a value lever in an unaided section fails: the lever text appearing in a
  question tagged `unprompted` is precisely the anchoring this design forbids.
- Lever status is derived from the answers, not asserted. A test that seeds one prompted
  agreement and one unprompted mention of the same lever must yield `confirmed_unprompted`,
  not whichever was written last.
- A lever no question references reports `untested`. Asserting only that confirmed levers are
  labelled would pass while an untested lever reached value design looking established, which
  is the failure this status exists to surface.

**The key split:**
- Casey's strategic requirements survive a full pipeline run. Asserting only that Riley's
  analysis is present would pass today, while Casey's set is being destroyed.
- No code path still writes or reads `requirements` as a bare key.

## Out of scope

**What Casey's themes actually say**, how strategic requirements are worded, and how Sage
weighs them - agent instructions rather than structure.

**Voice and transcript capture mechanics** beyond the `question_id` contract in section 4.
How the interview is conducted, spoken, paced, and checkpointed is unchanged; only what the
completed session records about each answer changes.

**Re-running the pipeline on sp-gs-am.** Regenerating the scripts is a project action, not
part of the implementation.
