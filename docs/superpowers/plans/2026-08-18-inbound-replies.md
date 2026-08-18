# Inbound replies, and a name a participant recognises

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A participant can reply to an email and it reaches the right correspondent, on the right project, about the right person - and the mail they receive is headed with a name they recognise rather than an internal slug.

**Architecture:** Outbound mail is plus-addressed on the role address already built - `stakeholder-manager+<token>@domain`. The token is minted and stored the way `auth_tokens` already does it, carrying `project_slug` and `stakeholder_id`. An inbound webhook verifies the provider's signature, resolves the token, stores the reply against the project and person, and surfaces it. A `client_name` setting supplies the participant-facing project name used in subjects.

**Spec context:** `docs/superpowers/specs/2026-08-17-agent-crew-graph-design.md` records "review is a link, not a payload". This is the same principle applied to correspondence - the reply arrives, is identified, and is stored; nothing about the project leaves in the address.

## Global Constraints

- **British English** - `-ise`, `-our`, `-re`, Oxford comma, spaced en dash ` - `, never an em dash. **Participant-facing copy**, so this matters more than usual.
- **Python 3.13** via `./venv/bin/python`. No ORM - raw SQL in `api/database.py`.
- A new `_migrate_*` bumps `_SCHEMA_VERSION` **in the same change** and joins the block `get_connection` runs. `tests/test_stakeholder_synthetic_migration.py` shows how to make a missed bump catchable - **copy that pattern**.
- **Backend suite twice with identical counts.** Baseline **2024 passed, 2 skipped, 12 deselected**. Frontend **611**, `tsc` clean.
- **All outbound mail goes through `api/services/outbound_mail.py`.** A structural guard fails if anything else posts to Resend. Do not add a second sender.
- Clear `__pycache__` between a mutation and its revert; `git checkout` cannot revert a mutation to a new untracked file - copy aside and verify with `diff`.
- Stage explicit paths. **Never `git add -A`.** Write nothing to `data/`; do not restart the servers on :8000 or :3000.

## What cannot be tested here

`taskreimagination.ai` is **not a verified sender domain in Resend**, so nothing sends and nothing can receive. Every assertion is against a mock transport or a synthetic webhook payload. **Say so plainly; never imply otherwise.**

Two assumptions the design rests on, to be confirmed before the domain is verified and **not** built around speculatively:

1. Resend permits arbitrary local parts on a verified domain (verification is per-domain, so likely).
2. **Inbound routing preserves the full recipient address including the `+tag`.** Some providers normalise it away. The whole design rests on this - if it is false, the fallback is `In-Reply-To` matched against a stored `Message-ID`, so record the sent id from the start regardless.

---

### Task 1: A name the participant recognises

**Files:** Modify `api/models.py`, the settings surface, `api/services/outbound_mail.py`; Test: new

- [ ] **Step 1: Add `client_name` to `ProjectSettings`**, defaulting to empty. Patrick's example: a participant sees "GS Asset Management - Your Interview", never `sp-gs-am`.

- [ ] **Step 2: Decide the fallback and say which you chose.** An empty `client_name` must not produce a subject reading "- Your Interview" or leak the slug. Falling back to the registry `display_name`, or omitting the prefix entirely, are both defensible.

- [ ] **Step 3: Apply it in the seam**, not at each call site - the seam is the one place mail is composed. Confirm the structural guard still holds.

- [ ] **Step 4: Test the subject that reaches the transport**, not a helper's return value. Assert the slug appears in **no** participant-facing subject. Power-check, commit.

---

### Task 2: A reply token

**Files:** Modify `api/database.py`, `api/services/outbound_mail.py`; Test: new

**Interfaces:** produces `mint_reply_token(slug, stakeholder_id) -> str` and `resolve_reply_token(raw) -> (slug, stakeholder_id) | None`. Task 3 consumes both.

- [ ] **Step 1: Read `auth_tokens` first and report what you find.** It already carries `token_hash`, `email`, `project_slug`, `stakeholder_id`, `purpose`, `expires_at`, `used_at` - the routing key you need is already a column. Decide whether a reply token is a new `purpose` on that table or its own table, and justify it. A reply token is **long-lived and reusable**, unlike every existing purpose, which is the strongest argument for separating them.

- [ ] **Step 2: The token is opaque.** Not a name, not an email, not a slug. It reveals nothing to anyone who sees the address, survives a rename, and can be revoked. Store the hash, never the token - `invite_service` is the established pattern, and note it uses SHA-256 rather than bcrypt **deliberately**, because a salted hash cannot be looked up.

- [ ] **Step 3: Mint per stakeholder per project**, and reuse it across messages so a thread stays coherent. Say what happens when a stakeholder is removed or their assignment retired.

- [ ] **Step 4: Test resolution end to end** - mint, round-trip through an address, resolve. Assert an unknown token resolves to `None` and **reveals nothing about whether it ever existed**. Power-check, commit.

---

### Task 3: The inbound endpoint

**Files:** Create `api/routers/inbound_mail.py` and its service; Test: new

**This is the first inbound webhook in the application. It is a public endpoint that writes to project databases.**

- [ ] **Step 1: Verify the provider's signature before anything else.** Resend signs webhooks; an unverified endpoint that writes to a project database is a serious hole. Reject unsigned and badly-signed payloads before parsing. **Test the rejection**, and test that a valid signature with a tampered body is rejected.

- [ ] **Step 2: Resolve the token from the recipient address.** Parse the `+tag`, resolve it, and route to the project and stakeholder. **An unresolvable token is dropped quietly with a log line** - it must not answer differently from a resolvable one, or the endpoint becomes an oracle for which tokens exist.

- [ ] **Step 3: Store the reply against the project and the stakeholder.** It is client material arriving from outside: decide where it lands and justify it. **It does not go into a RAG store automatically** - the knowledge-tier work makes that a deliberate act with authority, and an unauthenticated webhook has none.

- [ ] **Step 4: Bound what you accept.** Size, attachments, content type. An unauthenticated endpoint that stores arbitrary content needs limits, and say what you chose.

- [ ] **Step 5: Surface it.** A reply nobody sees is a reply lost. The correspondent owns it - engagement replies to the stakeholder manager's surface, governance to PAM's. **Jordan responding is out of scope**; this task delivers it to a human.

- [ ] **Step 6: `tests/test_proxy_prefix_coverage.py` enumerates routes from `app.routes`** - a new prefix must be covered in the Caddyfile and the Vite proxy or it fails. Keep it passing.

- [ ] **Step 7: Test the whole chain** - mint, send, reply arrives, resolves, stored, surfaced. Power-check each link **separately**; a shared resolver lets one link's test cover another's.

---

## Self-Review

**Spec coverage:** friendly name (1), opaque routing token (2), plus-addressed outbound (2), signature-verified inbound (3), project and person resolution (3), surfaced to the correspondent (3).

**Placeholder scan:** none. Tasks 1 and 2 each open by establishing facts from the code; briefs on this project have been wrong about details a dozen times, twice about this very mail code.

**Type consistency:** `mint_reply_token` and `resolve_reply_token` are defined in Task 2 and consumed in Task 3. `client_name` is added in Task 1 and used by the seam thereafter.

**Not in scope:** Jordan or PAM composing a reply; inbound attachments reaching a RAG store; threading by `Message-ID`, though the sent id should be recorded from the start in case `+tag` does not survive.

**One ordering note:** Task 1 is independent and could go last, but it is first because it is small, participant-visible, and touches the seam that Tasks 2 and 3 both build on - so it settles the seam's shape before anything harder lands in it.
