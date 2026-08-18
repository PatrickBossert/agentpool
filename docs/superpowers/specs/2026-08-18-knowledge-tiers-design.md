# Three knowledge tiers - sector, organisation, project

**Date:** 2026-08-18
**Status:** draft for review

## Why

An organisation licenses this agent team and runs it on a private server, spinning up a project
per division or value chain. So some knowledge is genuinely shared and some is genuinely not, and
the difference should be a declaration rather than an accident.

Today it is an accident. `ChromaQueryTool` accepts `collection: Literal["project", "interviews",
"sector"]` and resolves it with:

```python
}.get(collection, f"sector_{self.sector}")
```

The shared sector store is the **fallback for any unrecognised name**. A typo lands in a store
shared with every other engagement in that sector, silently. Three agents are declared to read it;
six can reach it. Nothing distinguishes "deliberately shared" from "a name nobody matched".

There is also **no organisation tier at all** - not in ingest, not in retrieval - although the data
exists: `organisations`, and `project_registry.org_id`, which every project now has.

## The tiers

Broadest to narrowest, a containment hierarchy:

| Tier | Example | Holds |
|---|---|---|
| **Sector** | energy | industry trends, regulatory context, benchmarks |
| **Organisation** | Scottish Power | annual reports, strategy, group policy |
| **Project** | property | specific investment proposals, division documents, interviews |

A project belongs to exactly one organisation (`project_registry.org_id`) and one sector
(the project's `sector` setting). An organisation may span several sectors across its projects;
that is allowed and means a document's tier is a property of the **document**, not derivable from
who uploaded it.

## What "precedence" means here

Containment, not override. An agent working on a project may read all three tiers: its own
documents, its organisation's, and its sector's. Narrower is more specific; broader is still
relevant. Nothing at a broader tier is hidden by something narrower.

**A query names its tier.** The tool's `collection` argument becomes explicit about which of the
three it means, and **the fallback goes** - an unrecognised name is refused, not quietly answered
from the widest store.

## Naming, and the one-way rule

Collections are named by tier: `sector_{sector}`, `org_{org_slug}`, `{slug}_docs`,
`{slug}_interviews`.

**Material only ever moves narrower.** A project's documents never land in its organisation's
store, and an organisation's never land in its sector's. Promotion is a deliberate act by a human
with the authority for the destination tier, never a side effect of ingestion. Without that rule
one division's investment proposals become another division's search results.

## Who may write each tier

This falls out of work already done:

| Tier | Written by |
|---|---|
| Project | project administration - the axis `require_project_administration` already expresses |
| Organisation | `org_admin` or above for that organisation |
| Sector | `sysadmin` - a sector store spans licensees |

The last is the sharpest: on a consultancy deployment a sector store spans **different clients**.
That is either the product's value or its worst leak, depending entirely on what goes in, so the
authority to put something there should be the narrowest in the system.

## Secure mode

`llm_mode` routes the vector store: Chroma Cloud on a standard project, the local instance on a
sensitive one. Two questions the tiers raise, and the answers must be stated rather than emergent:

1. **A sensitive project's documents must not reach a shared tier.** The one-way rule already
   forbids it, but it should be enforced rather than assumed.
2. **A sensitive project reading a shared tier** must read a local one. On a licensed private
   server every tier is local and the question is moot; on the consultancy's own deployment it is
   not. A sensitive project must not resolve `org_` or `sector_` to Chroma Cloud.

## What this changes

- `ChromaQueryTool`'s `collection` becomes the four explicit names, **the fallback is removed**,
  and an unrecognised value is refused.
- An organisation tier is added to ingest and retrieval, keyed on `project_registry.org_id`.
- Document upload declares a tier; the default is **project**, the narrowest.
- The graph's `agents/reads.py` declares which tier each read is against, so the privacy page can
  say plainly which material is shared and which is not - it currently reports `sector_{sector}` as
  "not scoped to this project" but has no vocabulary for why, or for an organisation tier.
- The `reachable_by` versus `read_by` gap the privacy page already shows becomes narrower, because
  a refused fallback means reaching a tier requires naming it.

## Testing

- An unrecognised collection name is **refused**, not answered from the sector store. This is the
  defect; it must fail loudly.
- Material never moves outward: a project ingestion cannot write `org_` or `sector_`.
- Each tier's write authority is enforced at the service, not the router.
- A sensitive project resolves every tier locally.
- The three tiers are independently witnessed - revert each separately, since a shared resolver can
  let one tier's test cover another's.

## Out of scope

Migrating what is already in `sector_{sector}`. It is one store on one deployment and its contents
are known; decide its disposition when the tiers exist rather than guessing now. Cross-tier ranking
or merging of results - a query names one tier and gets that tier.
