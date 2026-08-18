# Three knowledge tiers - implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make sector, organisation and project explicit tiers of the knowledge store; remove the silent fallback that makes the sector store the answer to any unrecognised name; add the organisation tier that the data model has but retrieval does not; and enforce that material only ever moves narrower.

**Architecture:** Collections are named by tier - `sector_{sector}`, `org_{org_slug}`, `{slug}_documents`, `{slug}_interviews`. `ChromaQueryTool` names its tier explicitly and refuses anything else. Write authority follows the tier: project administration, `org_admin`, and `sysadmin` respectively. `agents/reads.py` declares which tier each read is against, so the privacy page can say which material is shared.

**Spec:** `docs/superpowers/specs/2026-08-18-knowledge-tiers-design.md`

## Global Constraints

- **British English** - `-ise`, `-our`, `-re`, Oxford comma, spaced en dash ` - `, never an em dash. Binds page copy a client may read.
- **`brand` tokens only**, never `sky-*`/`blue-*`. Lucide icons, no emoji. `describeError` from `ui/src/utils/describeError.ts`.
- **Python 3.13** via `./venv/bin/python`. No ORM - raw SQL in `api/database.py`.
- A new `_migrate_*` must bump `_SCHEMA_VERSION` in the same change and join the block `get_connection` runs. CLAUDE.md: forgetting fails unsafe, not loudly.
- **Backend suite twice with identical counts.** Baseline **1925 passed, 2 skipped, 12 deselected**. Frontend **593**, `tsc` clean.
- **Enforce in the service, not the router.** CLAUDE.md: routers translate a refusal into a status code; they do not own the rule.
- Clear `__pycache__` between a mutation and its revert. `git checkout` cannot revert a mutation to a new untracked file - copy it aside and verify with `diff`.
- **Power-check each tier separately.** A shared resolver lets one tier's test cover another's - this exact masking bit an earlier branch.
- Stage explicit paths. **Never `git add -A`.** Do not restart the servers on :8000 or :3000. Nothing destructive against `data/`.

---

### Task 1: The tiers exist, and the fallback goes

**Files:** Modify `agents/tools/chroma_query.py`, `api/services/chat_retrieval_service.py`; Create `tests/test_knowledge_tiers.py`

**Interfaces:**
- Produces: a tier vocabulary - `sector`, `organisation`, `project`, `interviews` - and a resolver `collection_for(tier, *, slug, sector, org_slug) -> str`. Tasks 2, 3 and 4 consume it.

- [ ] **Step 1: Report the current shape before changing it**

`ChromaQueryTool` takes `collection: Literal["project", "interviews", "sector"]` and resolves with `.get(collection, f"sector_{self.sector}")` (`agents/tools/chroma_query.py:115-118`). Find every caller and every other place a collection name is built - `ingest_service`, `chat_retrieval_service`, `interview_answer_service` were all named in the egress work. Report them.

- [ ] **Step 2: Write the failing test**

```python
def test_an_unrecognised_tier_is_refused_not_answered_from_the_sector_store():
    with pytest.raises(ValueError):
        collection_for("sectr", slug="acme", sector="energy", org_slug="sp")
```

- [ ] **Step 3: Run it and watch it fail** - today it returns `sector_energy`.

- [ ] **Step 4: Add the resolver and the organisation tier.** `org_slug` comes from `project_registry.org_id`, which every project now has. A project with no registry row is a real state - decide what it means for the organisation tier and say.

- [ ] **Step 5: Suites twice. Power-check each tier separately**, and separately again for the refusal. Commit.

---

### Task 2: Material only ever moves narrower

**Files:** Modify `api/services/ingest_service.py`, `api/routers/documents.py`; Test: as above

- [ ] **Step 1: Establish where ingestion writes today** and report it. Documents are per-project; interviews are embedded by `interview_answer_service.py:217`.

- [ ] **Step 2: Write the failing test** - a project ingestion cannot write `org_` or `sector_`, whatever it is asked for.

- [ ] **Step 3: Enforce it in the service.** Promotion to a broader tier is a deliberate act with authority for the **destination**, never a side effect of ingestion. If you add a promotion path, it is explicit and separately authorised; if you do not, say so plainly rather than leaving the gap unnamed.

- [ ] **Step 4: Upload declares a tier**, defaulting to **project**, the narrowest. A default of anything broader would make the safe case the one requiring thought.

- [ ] **Step 5: Suites twice, power-check, commit.**

---

### Task 3: Write authority follows the tier

**Files:** Modify `api/routers/documents.py` and the services behind it; Test: as above

- [ ] **Step 1: Map each tier to its authority**

| Tier | Written by |
|---|---|
| Project | project administration - `require_project_administration` |
| Organisation | `org_admin` or above, **for that organisation** |
| Sector | `sysadmin` |

Sector is deliberately the narrowest: on a consultancy deployment a sector store spans **different clients**, so the authority to put something there is the tightest in the system.

- [ ] **Step 2: Write the failing tests, driven over HTTP** - a project administrator refused at the organisation tier; an `org_admin` refused at sector, and refused at **another organisation's** tier; a `sysadmin` permitted at all three.

- [ ] **Step 3: Enforce in the service.** The org-boundary check must not be satisfiable by a caller who can write the row it reads - sp42 closed exactly that shape, where a guard read `org_memberships` and two doors let a caller write it.

- [ ] **Step 4: Suites twice. Revert each condition singly**, never as a group. Commit.

---

### Task 4: Secure mode resolves every tier locally

**Files:** Modify the Chroma client resolution; `agents/egress.py`, `agents/reads.py`; Test: as above

- [ ] **Step 1: Establish what `llm_mode` currently routes.** `get_chroma_client` is one of only two places consulting it. Confirm, and report what a sensitive project resolves for each of the four collections today.

- [ ] **Step 2: Write the failing test** - a **sensitive** project resolves `org_` and `sector_` to the local instance, never Chroma Cloud.

- [ ] **Step 3: Make it so.** On a licensed private server every tier is local and this is moot; on the consultancy's own deployment it is not, and that is the deployment where a sector store spans clients.

- [ ] **Step 4: Declare the tier on each read.** `agents/reads.py` gains the tier, so the privacy page can say which material is shared and why - it currently reports `sector_{sector}` as "not scoped to this project" with no vocabulary for the reason, and no organisation tier at all.

- [ ] **Step 5: Suites twice, `tsc` clean, power-check each separately. Commit.**

---

## Self-Review

**Spec coverage:** tier vocabulary and refused fallback (1), organisation tier (1), one-way rule (2), tier declared on upload (2), write authority per tier (3), secure mode across tiers (4), tiers declared in the graph (4).

**Placeholder scan:** none. Tasks 1, 2 and 4 each open by establishing facts from the code, because briefs on this project have been wrong about details ten times in recent slices - including four counts in the brief for the graph view.

**Type consistency:** `collection_for(tier, *, slug, sector, org_slug)` is defined in Task 1 and consumed in 2, 3 and 4. The tier vocabulary from Task 1 is what Task 4 declares in `agents/reads.py`.

**Not in scope:** migrating what is already in `sector_{sector}` - one store, one deployment, knowable contents, and far easier to decide once the tiers exist. Cross-tier ranking or merging - a query names one tier and gets that tier.

**One ordering note:** Task 3 depends on Task 1's vocabulary and Task 2's write path; Task 4 depends on all three. Tasks 2 and 3 could swap, but enforcing authority before the one-way rule would leave a window where a correctly-authorised caller could still write outward.
