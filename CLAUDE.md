# CLAUDE.md — AgentPool project context

This file is loaded automatically by Claude Code. It captures conventions, key files, and context so new sessions can resume without re-reading the codebase.

---

## Style guide

These rules apply to all content produced for this project — UI labels, copy, comments, agent backstories, error messages, and documentation.

| Rule | Detail |
|------|--------|
| **English** | British English (UK) spellings throughout |
| **-ise / -ize** | Always `-ise` — e.g. *organise*, *prioritise*, *humanise*, *recognise* |
| **-our / -or** | Always `-our` — e.g. *behaviour*, *colour*, *favour*, *labour* |
| **-re / -er** | Always `-re` — e.g. *centre*, *fibre*, *theatre* |
| **-ogue / -og** | Always `-ogue` — e.g. *catalogue*, *dialogue* |
| **Dashes** | Short (en) dash ` - ` with spaces, not em dash (`—`) in web content |
| **Icons** | Stylised SVG icons (Lucide React) in all UI — no emoji in rendered web content |
| **Punctuation** | Oxford comma in lists of three or more items |

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Runtime | **Python 3.13 required** — see below |
| Backend | FastAPI (async), aiosqlite, Pydantic v2, pydantic-settings |
| AI crews | CrewAI, Anthropic Claude Opus (PAM always; others configurable) |
| Vector store | ChromaDB — `CloudClient` when `CHROMA_API_KEY` is set, else `HttpClient` on :8002 |
| Auth | JWT (python-jose), bcrypt (direct — NOT passlib; see below) |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS v3, React Router v6 |
| Email | Resend HTTP API (httpx — not SMTP) |
| Voice | ElevenLabs (TTS) + Web Speech API + Deepgram (STT) |
| Workflow | n8n (Docker, :5678) — triggers /orchestrate webhook |
| Infra | Docker Compose (ChromaDB + n8n), Caddy (prod), cloudflared (prod) |

---

## Critical: Python version

**Python 3.13 only. 3.14 will not install.** Both `crewai` and `litellm` declare `Requires-Python >=3.10,<3.14`, so pip on 3.14 silently falls back to ancient crewai versions and then fails with `No matching distribution found`.

Create the venv against a 3.13 interpreter explicitly:
```bash
uv python install 3.13                              # or: brew install python@3.13
$(uv python find 3.13) -m venv venv
./venv/bin/pip install -r requirements.txt
```

Never copy a `venv/` between machines — console-script shebangs hardcode absolute paths and break.

---

## Critical: bcrypt / passlib

**Do NOT use passlib.** It is incompatible with bcrypt 5.x (Homebrew Python 3.13).

Use `bcrypt` directly — see `api/auth.py`:
```python
import bcrypt

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())
```

---

## Test commands

```bash
# All tests
pytest

# With coverage
pytest --cov=api --cov-report=term-missing

# Single file
pytest tests/test_campaigns.py -v

# Integration tests — opt-in, and they cost money
pytest -m integration
```

Tests use in-memory SQLite — no running services required.

`tests/integration` is deselected by `addopts` in `pytest.ini`. Those tests call the real
Anthropic API and expect ChromaDB on :8002, so a bare `pytest` used to spend credit on
infrastructure that is usually not running. Collecting them also **changed the result of
unit tests** — see the patch-target entry below — so the deselection is not only about cost.

**Run the backend suite twice before believing it is green.** `tests/conftest.py` points
`DATABASE_DIR` at a fixed `/tmp/agentpool_test` that persists between runs, so a test which writes
a hardcoded row id poisons its own database: it passes once and fails on every run afterwards. That
defect shipped through eight task reviews before a second run caught it. Tests that need isolation
must use `monkeypatch.setenv("DATABASE_DIR", str(tmp_path))` with `get_settings.cache_clear()` on
both sides; tests using the shared `client` fixture must scope every assertion to a row they
created rather than hardcoding an id or counting globally.

## Reviewing changes: the recurring failure mode

Five times on this project a test has verified a property **one layer away from where it holds**.
In every case the shipped code was correct and the test could not distinguish correct from
incorrect:

- `check_write` tested; the tool calling it not.
- `staleness` tested; the endpoint assembling it not.
- An approval guard tested for one of its two conditions.
- `_fetch_change_requests` tested; the injection using it not.
- A radio tested as *rendered*; not as *sent*.
- `check_write` refused an undeclared key; the test asserted `"test_state" in write_result`,
  and the *refusal message quotes the key it is refusing*. The write half of a round-trip
  test could not fail. Assert the success prefix, not a substring drawn from your own call.
- Four crew tests patched `agents.tools.registry.get_tools_for_agent` — where the function
  is **defined** — while the crew module binds its own reference via `from ... import`.
  Patch where the name is *looked up*. Worse, their `import` sat inside the `with patch(...)`
  block, so the first test imported the module under the mock and the module kept that dead
  MagicMock for the whole session: one test poisoning the module made the next three pass.
  Alone, 12 passed; behind anything that imports the crew module first, 4 failed — and the
  production bug they were hiding (`create_business_plan_crew` raises `ValueError: Unknown
  agent: visual_illustrator`) had been live on master the entire time.

When a test passes alone and fails in the suite, the isolated pass is the thing to distrust —
it is usually the one running under state no production caller ever has.

Pure functions and rendered state are cheap to assert, so they get asserted — and the assertion
lands beside the property rather than on it. When reviewing, ask: **"what calls this, and is
*that* tested?"** and **"would this test fail if the code were wrong?"** The second question is
different from "does this test pass", and far more productive here.

---

## Database conventions

- **One SQLite file per project**: `data/<slug>.db`
- **System DB**: `data/system.db` — users, templates
- All DB access is async via `aiosqlite`
- All helpers are in `api/database.py` — no ORM
- Schema migrations are raw `ALTER TABLE` or `CREATE TABLE IF NOT EXISTS` run in `database.py` on connection open
- Test fixtures manually recreate relevant tables (check `conftest.py` and per-test fixtures)

When adding a new column to an existing table:
1. Add `ALTER TABLE ... ADD COLUMN` to the appropriate `ensure_*_table` function in `database.py`
2. Add the column to the `CREATE TABLE` statement so fresh DBs include it
3. Add the column to test fixtures that create that table manually

When adding a new `_migrate_*` function, bump `_SCHEMA_VERSION` in `api/database.py` in the
same change and add the new function to the migration block `get_connection` runs. Forgetting
fails unsafe, not loudly: `get_connection` only re-runs the migration block when
`PRAGMA user_version < _SCHEMA_VERSION`, so a new migration added without bumping the version
silently never runs on any database that has already been opened once at the current version -
no error, no warning, just rows that stay unmigrated forever on every existing deployment.

---

## API conventions

- Router files: `api/routers/<resource>.py`
- Service functions: `api/services/<feature>_service.py`
- Auth: JWT bearer token. The dependency is `Depends(require_any_auth)`,
  `Depends(require_org_admin_or_above)`, or `Depends(require_sysadmin)`, always under its own
  name - `get_current_user` is not a symbol this codebase has, and importing one of these
  under that alias is how the milestone hole stayed invisible (see below)
- 404 helper: `_404(msg)` raises `HTTPException(404)`
- No ORM — all SQL is raw strings in `api/database.py`

**Every project gets a `project_registry` row at creation, whatever the creator's role.**
`check_project_access` resolves an `org_admin` by comparing the JWT's `org_id` to that row and
falls through to 403 when there is none. Registration used to be gated on the creator being an
`org_admin`, and a `sysadmin`'s token carries no `org_id` - so on a deployment where the
sysadmin creates everything, `project_registry` and `organisations` both held zero rows and the
first `org_admin` ever appointed would have been locked out of every project. It was invisible
because `sysadmin` returns before the registry is consulted, and `project_memberships` - where
the diagnosis would go - looks perfectly correct throughout.

There is **one** organisation: the consultancy, `home_org_slug` / `home_org_name`, seeded by
`init_system_db` so it exists on every deployment without an operator step. Not one per client.
A creator's own `org_id` wins when their token names one; otherwise the home organisation is
resolved **by slug** - never "the only row" and never the lowest id, since the wrong answer
hands an unrelated organisation's admin a real engagement.

Two verbs, and they are not interchangeable: `insert_project_registry` is an **upsert** and
backs `POST /auth/projects`, the operator's "this engagement belongs to that organisation";
`register_project_if_unregistered` is `INSERT OR IGNORE` and backs project creation, which
answers 200 to a re-POST and so must not drag an engagement back out of the organisation an
operator moved it to. `scripts/backfill_project_registry.py` covers projects created before
this - a script and not a migration, because `get_connection(slug)` would run the migration
block for probe-materialised slugs that are not projects.

`DELETE /auth/orgs/{id}` refuses (409) the home organisation, and any organisation still owning
registered projects. `organisations` is the parent of `project_registry` under ON DELETE
CASCADE, so one successful 204 silently unregisters everything it owned and recreates the
defect above. Two conditions because neither implies the other: the home organisation can be
empty of projects, and an organisation full of them need not be the home one.

**There are two review doors, and anything touching review feedback must serve both:**

| Door | Handler | Called from |
|------|---------|-------------|
| `POST /projects/{slug}/review` | `submit_review` | `RerunDialog.tsx` "Suggest a revision", `AgentStatusTab.tsx` inline "Revise" |
| `PATCH /projects/{slug}/reviews/{id}` | `resolve_hitl_review` | `ReviewDialog.tsx` |

Nothing in the code says why both exist. Wiring only one silently turns the other's flows into
no-ops — notes that save, display in the UI, and never reach the agent. `RerunDialog` also **fans
out**, posting one review per crew output, so anything assembling review feedback into a prompt
must deduplicate or it repeats the same instruction N times.

Authority on a project is read, never inferred. `caller_roles(slug, payload)` in
`api/services/authority_service.py` walks JWT to `users`, to `project_memberships` for that
slug, to the `stakeholders` row it names, and returns the roles that row carries -
`project_admin`, `governor`, `approver`, `reviewer`, or `participant`. It previously matched
the caller's account email against a stakeholder email - `_caller_matches_stakeholder_flag`
in `api/services/commit_service.py` - behind an
`if payload.get("role") == "sysadmin": return True` that did all the work in practice because
`users` was empty, granting content authority to whoever could administer accounts.

`is_sys_admin` is global and implies `project_admin` on every project, so a newly created
project - which has no stakeholders, and therefore nobody the walk could ever reach - can be
bootstrapped. It implies nothing about content. Administration and content are different axes.
**Both roles were ungrantable until sp44, and that had shaped three decisions before it was
fixed.** `_reject_undeclared_role_flags` 422'd every truthy attempt to set
`is_project_admin` or `is_governor`, so both were stored, migrated, walked, returned and
documented - and could be given to nobody. `_assert_may_grant_role_flags` replaces it with
the authority check it was waiting for: **`project_admin` on this project, and nothing
else**, read by `caller_may_grant_project_roles`. An org_admin who configures the whole
engagement still cannot mint one; `is_sys_admin` implies `project_admin` on every project,
and that implication is the recursion's only base case.

The sysadmin arm of `caller_may_grant_project_roles` reads the token rather than the walk,
and has to: `POST /auth/login` matches `ADMIN_USERNAME` from the environment *before* it
looks at `users`, so the built-in administrator - the one every deployment bootstraps with -
**has no `users` row at all**, and `caller_roles` answers `set()` for it. `caller_roles`
itself stays a pure database read, so a stale or forged `role="sysadmin"` claim still buys
nothing from the walk (`tests/test_admin.py::test_org_admin_cannot_promote_anyone_to_sysadmin`).
A fixture that seeds a users row with `is_sys_admin=1` proves the database implication and
cannot see this.

**Clearing either flag stays permitted without the check.** Revocation is the safe
direction, and it is the repair sp37's review round 2 required so a row holding a role with
no deliverable address is not locked out of losing it. The asymmetry is deliberate.

Every content gate tests one of exactly two conditions, and the pair is stated once in
`authority_service.py`:

| Gate | Roles | Where |
|------|-------|-------|
| `caller_may_contribute` | `{reviewer, approver}` | `POST /{slug}/review`, `PATCH /{slug}/reviews/{id}`, `POST /{slug}/changes`, `PATCH /{slug}/validation-warnings/{id}` |
| `caller_may_approve` | `{approver}` | `DELETE /{slug}/reviews/{id}`, `PUT` and `POST .../migrate` on `/{slug}/value-chain-model`, `POST /{slug}/outputs/{id}/revert`, `POST /{slug}/agent-chat/upload`, `POST /{slug}/agent-chat/link` |

Four older call sites hold the same two rules under their own names, and are *not* uniform -
the earlier wording here said they "all test for `reviewer` or `approver`", which was wrong of
two of them. `commit_service.caller_may_commit` and `caller_may_submit` now **delegate** to
`caller_may_approve` and `caller_may_contribute` rather than restating the role sets, so the
rule exists once; the remaining two read `caller_roles` inline and are not uniform.
Precisely: `script_reviews.py`'s **approval** branch tests `{approver}` alone; its
non-approval branches, `projects.py`'s script edit, and `permissions.py`'s report test the
disjunction.

**`check_project_access` is not one of these gates.** It asks whether the caller belongs to
the engagement, and membership *is* read access by design - its `reviewer` branch returns on
a `project_memberships` row with no role test whatever, and its `sysadmin` and `org_admin`
branches return before looking at anything. That was safe only while `users` held no rows;
the invite loop creates the principal class it was never guarding against.

**Two axes, and a new write door belongs to exactly one of them.** Which it is turns on what
the door writes, not on how consequential it feels:

| Axis | Asked by | Decided | Scope |
|------|----------|---------|-------|
| **Administration, per project** | `require_project_administration(slug, payload)` in the handler body, after `check_project_access` | platform tier from the JWT, **or** `project_admin` from the walk | this engagement |
| **Administration, platform only** | `Depends(require_org_admin_or_above)` (or `require_sysadmin`) | before the handler runs, from the JWT's `role` | the login, globally |
| **Content** | `caller_may_contribute` / `caller_may_approve` in the handler body, after `check_project_access` | from the walk | this person, this project |

The administration axis has two rows because sp44 split it. Fifteen project-*configuration*
doors moved to `require_project_administration`, which is the disjunction "platform tier or
`project_admin` on this slug" stated once in `authority_service.py` rather than copied
fifteen times. The rest of the administration axis did not move, and the difference is not
cosmetic. Two rules decide which side a door belongs on, and both are about what the door
*produces*, not how consequential it feels:

**1. A door that lets a caller widen who counts as a member stays platform-tier.** A gate is
worth nothing if a caller can write themselves - or an accomplice - into the table it reads,
which is the escalation sp38 and sp42 each closed. So `POST`/`DELETE
/auth/users/{user_id}/projects/{slug}` (they write `project_memberships` outright), the whole
account-administration family, and `/auth/orgs/{org_id}/members` keep
`require_org_admin_or_above`.

**Precisely, because the absolute version of that sentence is false on this codebase:** the
widened stakeholder doors *do* write `project_memberships` - `_revoke_membership` fires on
delete, on reassignment, and when the last non-participant flag is cleared. What makes that
acceptable is not that they avoid the table but that they only ever **remove** rows, and only
on the caller's own slug: a `project_admin` can cut somebody out of the engagement they
already administer, which is within their remit, and cannot add anybody to anything. The
membership-grant doors are excluded because they *create* rows, and creation is what turns a
gate into a formality. If a stakeholder door ever gains an insert into `project_memberships`,
it belongs back on the platform tier.

**2. A door whose response body is a credential stays platform-tier.** `POST
.../resend-invite` returns a redeemable invite token and `POST /auth/accept` is
unauthenticated, so whoever can call it can mint a login - including one for a *real* address
that has no account yet, which a later legitimate invite onto another engagement then hands a
membership. That chain crosses a project boundary using only correctly-behaving doors, so the
door itself is the control. It is the one write in `stakeholders.py` that is not
`require_project_administration`.

The refusal sentences differ deliberately, so "this door widened and that one did not" is
assertable rather than merely intended.

*Administration* is running the engagement: stakeholders and their roles, campaigns and
reminder emails, the document library, starting a run or an orchestration, PAM assignment,
and `PATCH /{slug}/settings`, the milestone schedule, the non-working calendar, and the
branding header. Thirty-three project-scoped doors, none of which takes a content gate, as
project creation does not either. That is deliberate: a consultant configures the
engagement, and a client-side approver does not, however senior they are on the project.
They now split across the two administration rows:

| Gate | Doors |
|------|-------|
| `require_project_administration` (15) | `stakeholders.py` (6 - not `resend-invite`), `milestones.py` (4 - not `rebaseline`), `nonworking.py` (3), `projects.py` (2 - `PATCH /{slug}/settings` and `POST /{slug}/branding/image`) |
| `Depends(require_org_admin_or_above)` (18) | `campaigns.py` (10), `documents.py` (3), `assignment.py` (2), `orchestrate.py`, `run.py`, and `stakeholders.py`'s `resend-invite` |

15 + 18 = the thirty-three. `POST /projects` sits outside the count and keeps the platform
tier of necessity: there is no slug yet to scope a per-project role by.

**`PATCH /{slug}/settings` is on the widened list but is not uniformly widened.** Its body
carries `llm_mode`, `dev_mode` and the six per-agent model ids alongside the sector and the
stakeholder groups, and those eight decide *where this engagement's data is sent* rather than
how it is configured. `_PLATFORM_TIER_SETTINGS` in `projects.py` holds them, and a
`project_admin` who changes any of them is refused with a 403 naming the fields. Flipping a
sensitive project to `standard` would send every crew agent including PAM, the elaboration
press and Agent Chat to hosted Anthropic and stop keeping documents off Chroma Cloud - the
guarantee this file states as absolute - and repointing `local_deep_url` reaches the same
place more quietly.

Three details of that guard are load-bearing and each has its own test. It compares the
*transition*, not the field's presence, because the Settings tab round-trips the whole body
and refusing the key would refuse every save a project_admin makes. It reads `llm_mode` from
`projects.llm_mode` rather than the `config_json` copy, because a guard compared against a
copy is bypassed the moment the copy drifts. And it normalises both sides through
`ProjectSettings` rather than skipping fields absent from the stored config: `create_project`
writes only `ProjectCreate`'s nine fields, so on every project before its first full settings
save, seven of the eight protected fields are simply not in `config_json` and a
`field in current` test would have protected the mode alone.

The second group is not a judgement that those seventeen should stay - sp44 widened exactly
what its brief named, which is the set the design calls "configures the project and its
people". Whether a project_admin should start a crew run or import a campaign is a live
question, not a settled one. What is settled is the exclusion above: the membership,
account, and organisation-membership writes stay on the platform tier whatever else moves.

`POST /{milestone_id}/rebaseline` is the one door in `milestones.py` that took neither -
moving a promise is a content judgement, so it keeps `caller_may_commit` on top of the
membership floor.

*Content* is acting on what the crews produced: reviews, change requests, warning
dispositions, commits, submissions, activation, the canonical value chain, reverts,
milestone re-baselining, script reviews and script edits. Sixteen doors ask the walk.

**Administration mints content, within one project.** Setting `is_approver` is stakeholder
administration, and stakeholder administration is one of the sixteen widened doors - so a
`project_admin` can PATCH their own stakeholder row and hold approver authority a moment
later. This is not new in kind (an org_admin could always set `is_approver` on a row linked
to their own login) but it is new in *who*: sp44 moves it from the consultant to the client's
own project administrator. It is bounded by the project - the promotion is a write to a row
on that slug, and `caller_roles` keys its lookup on the membership for that slug - and it is
recorded as an asserted property in
`tests/test_grantable_roles.py::test_a_project_admin_can_promote_themselves_to_approver_on_their_own_project`
rather than left to be rediscovered. **If content authority is ever meant to be
un-self-grantable, the fix is on the stakeholder write, not on the role.**

**`governor` gates nothing.** It is grantable, and the only thing holding it does is put the
person on the recipient list for PAM's daily report (`REVIEW_FLAGS` in
`api/services/pam_report_job.py`). The design also says governors "complete" milestones;
there is no distinct milestone-completion action in the code - `rebaseline` is the nearest
and is content-gated on `approver` - so sp44 deliberately invented none and left that to
sub-project C, where the milestone schedule is being designed. A governor configures
nothing, approves nothing, and grants nothing:
`tests/test_grantable_roles.py::test_the_governor_role_gates_nothing_else` says so, so this
paragraph fails rather than rots when it stops being true.

The two axes cross in exactly one place, on purpose. `POST /{slug}/agent-chat/upload` is
approver-gated while `POST /{slug}/documents/upload` is administration - the same `documents`
row and the same Chroma ingest, reached by different people, because the chat door exists for
the approver reading an agent's output. It is the one door where content authority buys a
corpus write, and it is gated on `caller_may_approve` (the stricter of the two) for that
reason.

**So, for a new door:** does it change how the engagement is *run* - who is on it, what is
scheduled, what gets started, what is configured? Administration; copy its neighbours in that
router. Does it record an opinion about, or change, what the project currently *says*?
Content - `caller_may_contribute` for the former, `caller_may_approve` for the latter. Never
`check_project_access` alone, which is read access. A pure read needs neither.

Three sets of writes have neither gate, and all three are deliberate:

- `POST /{slug}/agent-chat` and `DELETE /{slug}/agent-chat/history` write only rows keyed to
  the caller's own `username` - a personal scratchpad attached to read access, not authority.
- `/api/interviews/{session_token}/...` authenticates by the session token itself; a
  participant has no login for the walk to start from.
- `/auth/*`, `/admin/skills/*`, templates and skill notes carry no slug, so there is nothing
  to walk. They take login-role dependencies instead.

**Never alias an auth dependency on import.** `milestones.py` and `nonworking.py` used to do
`from api.auth import require_any_auth as get_current_user`, and it hid a cross-project hole
for as long as the files existed: every handler read `Depends(get_current_user)`, which is
the name this project's conventions use for a *gated* door, so every reader's eye confirmed a
guard that was not there - and a grep for `require_any_auth` did not find either file. Neither
called `check_project_access`, so any valid token could read and rewrite any slug's milestones
and calendar, and `POST /{slug}/branding/image` was the same under `get_token_payload`. Closed
in sp38: the imports use the real names, `nonworking.py` binds its payload rather than `_`, all
twelve doors call `check_project_access`, the writes take the administration gate (sp38's
`require_org_admin_or_above`, widened to `require_project_administration` in sp44), and
`POST /{milestone_id}/rebaseline` keeps `caller_may_commit` on top of the floor because moving
a promise is a content judgement rather than configuration.
`tests/test_milestone_door_authority.py` drives every one of them over HTTP: a real member of
the project against every door, a real administrator of a *different* engagement against
every door, and a real non-member against the reads and `rebaseline`. The non-member is not
driven against the eight writes because the administration axis refuses it first, so the call
would say nothing about the floor. The middle caller is the one that matters - it is the case
an "anonymous is refused" test would have passed before the fix.

`GET /projects/{slug}/milestones` used to seed the default milestones when the table came
back empty, which put the operation `POST /milestones/seed` is administration-gated for
behind a door any member can open. The repair was to take the write out of the read, not to
widen the gate: `create_project` seeds once, where an administrator is present by definition.
**A read door does not write on this codebase** - if a lazy write looks necessary, the
question is which authenticated write path should have done it earlier.

**Enumerate by behaviour, not by name.** The alias hid two files from a `require_any_auth`
grep; `pam_report.py` then hid from the *alias* sweep by not aliasing, and it had the same
hole. Two accidental discoveries meant the enumeration was wrong twice, so it was done
properly: 96 handlers are mounted under a path containing `{slug}`, and the check is whether
each one calls `check_project_access`. Reproduce it with an AST walk over `api/routers/*.py`
that joins each `APIRouter(prefix=...)` to its `@router.<method>` paths - not with a grep for
a dependency name, which is what missed it both times. **Ninety-three of the ninety-six call
it.** The three that do not:

| Door | Why not |
|------|---------|
| `GET /projects/{slug}/branding/image` | Deliberate - no auth at all. The interview page renders it for a participant who has no login. If that image ever becomes client-confidential the fix is session-token scoping, not `check_project_access`. |
| `DELETE /auth/projects/{slug}` | Registry administration, `require_sysadmin`. Global by nature, and a sysadmin passes the floor unconditionally, so the call would be a no-op. |
| `WEBSOCKET /ws/{slug}` | **Open, and unauthenticated entirely** - no token, no dependency. Streams agent log lines for any slug to anyone who can reach the port. `useWebSocket.ts` connects with no credential, so closing it needs a token-passing scheme (subprotocol or query parameter) before a gate can exist at all. The largest remaining exposure on this surface. |

**The sweep counts routes whose *path* holds `{slug}` and nothing else.** A project-scoped
door taking its slug from the request *body* does not appear in it - `POST
/api/interviews/test/elaboration-press` is that shape, and does call `check_project_access`,
but the technique cannot see it. Ninety-six is not a completeness guarantee.

`POST` and `DELETE /auth/users/{user_id}/projects/{slug}` were the sweep's most important
find and are closed. They write the `project_memberships` table that every
`check_project_access` reads, and they never asked whose engagement the slug was, so an
org_admin could grant themselves a row on another organisation's project and then pass every
gate in the API as a legitimate member. **A gate that reads a table is worth nothing if a
caller can write themselves into it** - the other holes bypassed the floor, this one
manufactured it. Scoping rather than new policy: `svc_create_user` already forces `org_id`
to the caller's own, and the floor's own org_admin branch already compares
`project_registry.org_id` to the JWT's. `sysadmin` keeps its early return, so administering
across organisations stays a sysadmin capability.

`GET /projects/{slug}/pam-report` and `GET /api/interviews/sessions/{slug}` were the two
found by this sweep and are now closed. The second was the sharpest hole on the branch: it
returns every stakeholder's `session_token`, which is the only credential the public half of
`api/routers/interviews.py` checks, so an unscoped read of it was a way in as somebody else's
interviewee rather than a metadata leak. It also called `get_connection(slug)` before any
check, so probing slugs created a database file per guess.

Clearing a stakeholder's last non-participant flag, or deleting the row, removes the
`project_memberships` row - `_revoke_membership_if_no_longer_privileged` in
`stakeholders.py`, the mirror of `_issue_invite_if_newly_privileged` beside it. Without that
the flags said one thing and `check_project_access` another. The `users` row stays: it is a
global login that may hold memberships on other engagements. Revocation is keyed on
`stakeholder_id`, not on the email, because the email may have been edited since the invite
was accepted - and an administrator-granted membership (`insert_project_membership`, NULL
`stakeholder_id`) is deliberately out of its reach. Re-granting the role afterwards issues a
fresh invite, which is the route back: redeeming it restores the membership and sends the
person to sign in with the password they already have.

**Changing a stakeholder's email is a change of person, not of detail.** "Dougie has left,
Sam has the seat now" is the ordinary handover edit, and it moves no flag - so the two
transition handlers above, which both key on the *role* changing, saw nothing happen while
the membership (keyed on `stakeholder_id`, which an email edit cannot dislodge) kept the
departed holder's login reading the engagement indefinitely. `_revoke_membership_if_
reassigned` cuts it, and the `_is_reassignment` conjunct in `_issue_invite_if_newly_
privileged` invites the arriving holder as the fresh grant they are: both halves, in that
order, or the seat has either two occupants or none. Addresses are compared
`.strip().lower()`, matching `_stakeholder_matches_invite` rather than inventing a third
convention, so a casing or whitespace correction is not a handover - it must not be, since
`users.username` is `TEXT UNIQUE` under binary collation and a spurious handover would revoke
a live membership and then invite an address whose login already holds one. The departed
holder's unredeemed invite needs no clean-up: `_stakeholder_matches_invite` re-reads the
row's own email at redemption and refuses a token that no longer matches it.

`is_sys_admin` is derived from `role` by `insert_user` and `update_user`, not passed in.
Nothing wrote it before, so a sysadmin created through `POST /auth/users` carried
`is_sys_admin=0` and behaved differently under `caller_roles` from one flagged by hand.

Because it is derived, **every path that can set `role` needs the caller guard**, not only
the creation path. `svc_create_user` refuses an `org_admin` who names `sysadmin`;
`svc_update_user` carries the same rule, raising `ForbiddenRoleChange` (409) rather than
returning `None`, which on that function already means "no such user" and would have answered
a refused promotion with 404. Without it an `org_admin` could create a reviewer and promote
it - or promote themselves - and `caller_roles` would read the result back as `project_admin`
on every project in the system.

**The role being granted and the account being acted on are two different questions**, and
only the first was ever asked. `svc_update_user`'s guard above tests the role in the request;
`_assert_may_administer` in `admin_service.py` tests the target, and is the only place that
question is answered - `svc_update_user`, `svc_delete_user`, and `svc_issue_reset_link` all
call it, and a fourth account door must too rather than carry a copy. Two refusals: an
`org_admin` may not act on a `sysadmin`'s account whatever role the request carries, nor on an
account outside their own organisation. Both answer 409 with the *same* sentence, deliberately
- told apart they say which accounts hold the platform role and which belong to another
organisation, by enumerating ids. `sysadmin` returns early, so administering across
organisations stays a sysadmin capability. Until sp42 this was live: `PATCH /auth/users/{id}`
with `role="org_admin"` and a password of the caller's choosing demoted the platform
administrator and took their login in one request, because the role being granted was not
`sysadmin` and nothing looked at whose account it was. `DELETE /auth/users/{id}` asked nothing
at all - its dependency sat in the decorator, so the handler had no payload to ask with.
`tests/test_account_administration_authority.py` asserts all three doors refuse in one voice,
and proves each refusal by signing in with the target's old password afterwards.

**The organisation half of that guard reads a table, so every door that writes it is scoped
too.** `org_memberships` is what decides "is this account in my organisation?", and `POST`,
`PATCH`, and `DELETE /auth/orgs/{org_id}/members` write it - all three now call
`check_org_access` (`api/auth.py`), the organisation-level sibling of `check_project_access`.
Unscoped they were a three-request bypass at the same tier: refused on another organisation's
account, remove its membership, add it to your own, come back. Two further rules make the
premise trustworthy rather than merely harder to rewrite. `_assert_may_administer` requires
the caller's organisation to be the target's **only** one (`fetch_user_org_ids`, not
`fetch_user_org` - the first row of several is an arbitrary choice, and reading it let an
org_admin *claim* an account in one request rather than three). And `svc_add_org_member`
refuses an org_admin who adds an account another organisation already holds - claiming is the
half that scoping the path cannot see. A sysadmin may still move accounts between
organisations, and an account genuinely in two is administrable by neither org_admin.

A consequence worth knowing: an account with **no** `org_memberships` row is unreachable by
any org_admin - `fetch_user_org_ids` returns `[]`, which is never `[caller_org]`. That is
consistent rather than awkward, since `fetch_users_by_org` joins the same table and such an
account never appears in an org_admin's list either. A sysadmin administers it, or an
org_admin adds it to their organisation first.

**A password reset does not invalidate live sessions.** JWTs here are stateless, so a token
minted before the reset stays valid until `ACCESS_TOKEN_EXPIRE_HOURS` (or the absolute
session ceiling) runs out - somebody resetting because they think they are compromised does
not cut the other session off. Bounded rather than open-ended, and closing it needs a
`password_changed_at` claim check or a revocation list, not a change to the reset doors.

`caller_roles` must never create a database. It returns the roles gathered so far rather than
calling `get_connection(slug)` on a slug whose file does not exist, because every gated
endpoint calls it and a caller probing slugs would otherwise materialise one file per guess.
`_stakeholder_matches_invite` in `invite_service.py` carries the same guard, for the same
reason.

Setting any role other than `is_participant` on a person with no login issues an invite; a
participant never gets one, because they are reached by interview URL and token. One live
invite per person **per project** - not per person, since a second engagement must not
overwrite the first one's `project_slug` and `stakeholder_id` - re-issuable when the email is
lost, and the same `auth_tokens` table serves password resets.

**Two reset doors, one delivery seam.** `POST /auth/reset-request` is self-service and answers
**204 always**, token discarded: it must never reveal whether an address has an account, so
nothing in it - status, body, or header - may branch on the outcome, and the page posting to
it says "if that address has an account, a link is on its way". `POST
/auth/users/{id}/reset-link` is the administrator door, gated on the platform tier, and
returns the raw token to deliver by hand - the arrangement the invite loop already runs on,
because `FROM_EMAIL` names a domain Resend has not verified. Both call `deliver_reset`
(`invite_service.py`), which is **the one place to wire Resend**; its docstring carries the
two constraints that survive the wiring (the 204 must stay outcome-blind, and the send must go
off the request path or it reopens the timing tell `issue_reset` closed).

The self-service door has a blind spot worth knowing before trusting it: `issue_reset`
resolves its account by `users.username`, so a login whose username is not its email address -
routine for an administrator-created account - cannot be reached by typing that email, and the
204 makes the miss look exactly like success. **A 204 from `/auth/reset-request` is not
evidence a link was sent.** The administrator door covers those accounts (it passes
`users.username` deliberately); fixing the self-service one means resolving by username *or*
email without reintroducing a timing difference between a known and an unknown address.

### Reaching the API: nothing may name a host, and both proxies must cover every prefix

The dashboard sends **origin-relative** URLs. `API_BASE` in `ui/src/api/client.ts` is `''` on
purpose, so a call goes to whatever origin served the page - Vite in development, Caddy in
production. It was the literal `http://localhost:8000` until sp43, which sent every call to the
*viewer's* machine and bypassed both proxies. `useWebSocket.ts` is the same rule, expressed as
`window.location` because `new WebSocket` refuses a relative URL.

The other half is that both proxies must forward **every** top-level prefix the API mounts:
`/projects`, `/auth`, `/admin`, `/system`, `/agent-skill-notes`, `/api`, and `/ws`. A prefix
missing from the `Caddyfile` does not 404 - it falls through to the static file server and
answers the landing page with a **200**, and a prefix missing from `vite.config.ts` is answered
by the SPA fallback. Both failures look like a frontend bug. `tests/test_proxy_prefix_coverage.py`
enumerates `app.routes` and fails when either config stops covering them, matching **whole paths**
rather than prefixes - `handle /projects/*` does not match the bare `POST /projects`, which is
why the matchers are written `/projects*`.

FastAPI's `/docs`, `/redoc`, and `/openapi.json` are named in that test's `FRAMEWORK_PATHS` and
deliberately left unproxied. The exemption cannot be abused: the test asserts every exempted
path is a framework-supplied Starlette `Route`, so an application endpoint cannot be excused
into it.

**Intended end state: mount every router under `/api` and delete the two conventions.** One
rule forever, and no per-prefix list to keep in step. It was not done in sp43 because it touches
every router and every URL in a 1600-test suite, and that belongs in a change of its own rather
than smuggled into a proxy fix. Until then, the split is real: `/api/templates` and
`/api/interviews` carry the prefix and nothing else does, so no single rewrite rule serves both.

---

## Frontend conventions

- Pages: `ui/src/pages/` — one file per route
- API client: `ui/src/api/` — one file per resource (`campaigns.ts`, etc.)
- Auth: `useAuth()` from `ui/src/context/AuthContext.tsx`
- Router: `ui/src/router.tsx` — basename `/dashboard`
- Colours: Tailwind config at `ui/tailwind.config.js`
  - Brand teal: `text-brand`, `bg-brand`
  - Surfaces: `bg-surface`, `bg-surface-raised`, `bg-surface-card`
  - Text: `text-primary`, `text-secondary`, `text-muted`

Do NOT use `sky-*` or `blue-*` classes — these were replaced with `brand` tokens.

`StakeholderForm.tsx` offers five role checkboxes, and the last two - Project Administrator
and Governor - render only when `GET /my-permissions` answers `can_grant_roles`, because the
server refuses both to anyone without `project_admin` on that slug and a checkbox that always
403s is worse than no checkbox. The half that matters more is what is *sent*: a caller who
may not grant them omits both keys entirely rather than sending `false`. The form posts its
whole state, so without that an org_admin editing a job title on somebody who already holds
`project_admin` would resend `is_project_admin: true` and be refused for a grant nobody asked
to make - and sending `false` instead would silently revoke it. Neither flag is declared on
`StakeholderIn`/`StakeholderPatch`, so a write that does not mention them does not touch them.

`describeError` lives in `ui/src/utils/describeError.ts` and is imported, not copied. Four
identical copies had grown before sp44 moved it - `StakeholderForm`, `ScriptReviewPanel`,
`MayaOutputExtra` and `InterviewTemplateEditor`. It exists because several of this API's
refusals say something a fixed string cannot - "email is required to invite a stakeholder
holding a role beyond participant" is the only thing in the product that tells an
administrator they have just created a role nobody can be invited to.

Reviewing an interview script happens in the document, not the list. `ScriptReviewRow` is the
approver's view - node id, title, status, review count, and a gated Approve - and
`ScriptReviewPanel` is where a reviewer reads the instrument and leaves by one of three exits,
each of which records a review: `edited`, `changes_requested`, or `reviewed`. `approved` is
excluded from the count so an approval cannot satisfy its own gate, and the gate is enforced in
`record_script_review`, not only by a disabled button.

A script is shown by its value chain node id. `script_id` remains the identity - stakeholder
assignments and stored answers cite it - and is never displayed.

---

## Crew / agent conventions

- Crew factories: `agents/crews/<crew_name>_crew.py`
- Agent modules: `agents/<domain>/<agent_name>.py` — grouped by domain, not suffixed. Domains are `discovery`, `value_design`, `architecture`, `delivery`, `business_plan`, `pam` (e.g. `agents/discovery/interview_coordinator.py`)
- Tool modules: `agents/tools/<tool_name>.py` — no `_tool` suffix (e.g. `agents/tools/chroma_query.py`)
- Tool registry: `agents/tools/registry.py` — `get_tools_for_agent(agent_name, slug, ...)` maps **agent** names to tool lists
- Crew dispatch: `api/services/run_service.py` — `build_and_run_crew()` imports each crew factory inline; `_CREW_AGENT_NAMES` maps crew names to their agent lists. There is no standalone crew registry module.
- All crews return structured JSON; output files written to `projects/<slug>/outputs/`

There is no top-level `crews/` directory — everything lives under `agents/`.

Each agent declares a capability tier in `agents/model_registry.py` - `fast` or `deep` - and the
project's `llm_mode` binds that tier to a model. Crew factories never choose a model; they call
`get_llm_for_agent(agent_name, slug)`, and a source guard fails if one names a model.

PAM has no exemption. It is `deep` and routes to the local model for a sensitive project like
every other agent, because it holds `SQLiteStateTool` and can read project outputs - an
always-hosted orchestrator was a hole in the secure-mode guarantee rather than a quality choice.

A sensitive project with no local model configured for a tier raises `LocalModelUnavailable`
rather than falling back. There is no hosted fallback and no borrowing of the other tier.

Maya owes one interview script per active value chain activity. Coverage is checked on every
`interview_scripts` write by `api/services/coverage_validation.py` and reported as
`incomplete_coverage` into `validation_warnings`, which the next run reads back through
`_fetch_validation_warnings`. Reaching every node across several runs is expected: each run adds
only the missing nodes, and `_merge_with_current` accumulates.

A script id means one node for the life of the project. `interview_scripts` is the only write
that reaches this rule now - the separate `interview_script_registry` artefact and its write
door retired (script-ledger-as-a-table Task 3), and `interview_script_ledger` is a table, not
a file. Two layers enforce it: `validate_scripts_against_script_registry`
(`api/services/interview_script_model.py`) refuses a batch that files a registered id against
a different node before anything is written, because `_merge_with_current` keys on
`script_id` and a moved id would otherwise replace a script rather than add one; and
`register_scripts_sync` (`agents/tools/_db.py`) registers with `ON CONFLICT(script_id) DO
NOTHING`, so even a write that reached the table could never move a `node_id` it already
held. There is no `DELETE FROM interview_script_ledger` anywhere, so dropping an id
(the JSON-artefact-era registry's other worry) is structurally impossible rather than merely
refused.

The script ledger is a table, `interview_script_ledger`, with `script_id` as its primary
key. It is maintained by the write path: every `interview_scripts` write registers ids it
has not seen, and never moves one it has. Maya does not write it - the JSON
`interview_script_registry` artefact is retired, and the output type has no owner, so a
write to it is refused. Run 32 is why: it wrote 41 scripts, hit CrewAI's default
`max_iter` before its ledger write, and reported `completed` with 41 ids outside the
succession guarantee.

Review is per script, not per artefact version. `script_reviews` holds one row per review
event and the ledger row carries the derived state, because a script is reviewed by
several people and approved once. A send-back carries `review_return_to`: only `agent`
enters Maya's differential, because a return to `reviewer` that regenerated the script
would rewrite the instrument the reviewer was about to re-read.

### Routing a call outside a crew: two protocols, one setting

Anything that is not a CrewAI agent goes through `project_completion(slug, tier, messages)` in
`api/services/llm_client.py`. Never build a provider client directly, and never take a slug's
mode from a caller.

The trap it exists to close: "route it locally" is **two different wire formats**. Agents build
`LLM(model=f"openai/{model}", base_url=...)` and LiteLLM POSTs `{base_url}/chat/completions`.
Reaching for `AsyncAnthropic(base_url=...)` instead POSTs `{base_url}/v1/messages` - and because
`local_fast_url` already ends in `/v1`, actually `{base_url}/v1/v1/messages`. Ollama serves no
`/v1/messages` at any path, so the settings agreed while every call raised `NotFoundError`. A
test that swaps the client class cannot see this; assert against an `httpx.MockTransport` and
read the request's real URL.

The slug is required, not defaulted. `project_llm_mode("")` finds no database and answers
`"standard"`, so a forgotten slug is a silent hosted call - which is exactly how the test
interview dialog sent a sensitive project's answers to Anthropic while holding the slug in its
props and discarding it.

**What is covered, precisely:**

| Path | Routed by `llm_mode`? |
|------|----------------------|
| Every crew agent, including PAM | Yes - `get_llm_for_agent` |
| Live interview elaboration press (`interview_service._press_call`) | Yes |
| Test-interview press (`POST /interviews/test/elaboration-press`) | Yes - slug required, 422 without it |
| Agent Chat (`run_agent_chat`) | Yes, text and retrieved chunks |
| Agent Chat with an **image** attached, sensitive project | **Refused** (503) - image blocks have no chat-completions equivalent here, and dropping or sending them are both wrong |
| Skills library (`api/services/skills_service.py`, `api/routers/skill_notes.py`) | **No** - always hosted Haiku |

The skills library is the one remaining hosted path. It is a deliberate gap rather than an
oversight: the library is global across engagements, its endpoints carry no slug, and the text
is reviewer feedback about an agent's behaviour rather than client material. It is still
reviewer feedback typed on a sensitive engagement, so a project-scoped skills library is the
fix if that ever stops being acceptable - not a default slug.

---

## Anchoring: themes and requirements sit where the insight lives

Themes and requirements must anchor at the level where the insight lives - L0 for
governance, assurance and vertical themes; L1 for functional; L2 for decision and
effectiveness; L3 for tactical and efficiency. Anchoring everything at `n.n.n` loses
resolution and systematically skews value proposition generation toward L3 efficiency.

This is a pipeline-shaping property, not a formatting preference. If nothing else exists to
anchor to, L3 becomes the only altitude the evidence is ever expressed at, and every
proposition built downstream inherits the bias.

The tree is the canonical spine. `0` is the organisation; `0.A` and `0.S` are its
organisation-level role nodes (audit, corporate services frontline); each L1 entity carries
the `<L1>.C` and `<L1>.F` role nodes it warrants. L2 and L3 belong to exactly one L1 -
nothing is shared or duplicated. Role nuance never lives on the node; it lives on the
stakeholder, which is what lets one `F` programme serve both `1.F` and `2.F` while the
answers still differ.

**IDs are a permanent contract.** The ledger may grow and may retire, but may never
redefine or forget. Two things enforce that, and neither is a refusal: `DeriveRegistryTool`
keeps the label an id already carries, so a regenerated tree cannot rewrite the ledger; and
`tree_validation` raises `id_redefined` when a label changes in a way that is not merely
typographic. Alex rebuilds the whole chain on every run and re-emits every label, so
punctuation drift is routine - one run produced 59 label changes and not one was a
redefinition.

Fuller account: `docs/superpowers/specs/2026-08-06-l0-anchor-and-level-anchored-synthesis-design.md`.

---

## Resolving an output: ask the ledger, never the disk

`agent_outputs.is_current` + `file_path` is the authority on which version of an output is
current. `insert_agent_output_sync` maintains it on every write and `revert_to_version`
repoints it on every revert - which is the case a filename-ordering scheme cannot express,
since the newer files stay on disk.

**Use `current_output_path(slug, output_type)`, not `latest_output_path`.** The latter
globs `stem_v*` and returns the highest number, which caused four separate incidents: the
clean-baseline demotion, the `value_chain_tree_v13` shadow, a version-counter reset, and
Maya reading a 15 July summary on every run for three weeks - naming a party a human had
corrected out on 4 August. `latest_output_path` survives only as the fallback for a first
write and for hand-written files.

Two invariants this depends on, both asserted in `tests/test_output_type_families.py`: one
filename family answers to exactly one output type, and one output type has exactly one
`is_current` row.

Fuller account: `docs/superpowers/specs/2026-08-06-output-resolution-by-ledger-design.md`.

---

## Running the API while agents are running

Start the server **without `--reload`**. Editing any watched `.py` file restarts the worker
and kills every in-flight crew run - the error surfaces as
`{"error": "Server restart interrupted run"}`, which is what killed runs 21 and 27. The
cost is that the server no longer picks up code changes: restart it after backend edits,
and never while a run is in flight.

---

## Key files

| File | Purpose |
|------|---------|
| `api/main.py` | App factory, router registration, lifespan |
| `api/config.py` | All settings (reads `.env`) |
| `api/database.py` | All DB helpers — read this first when adding data |
| `api/auth.py` | JWT + bcrypt — **bcrypt direct, no passlib** |
| `api/services/run_service.py` | Crew execution dispatch |
| `api/services/orchestration_service.py` | PAM two-phase orchestration |
| `api/services/campaign_service.py` | Interview campaigns + Resend email dispatch |
| `agents/crews/pam_crew.py` | Project Automation Manager (top-level orchestrator) |
| `agents/tools/registry.py` | Agent name → tool list mapping |
| `ui/src/router.tsx` | All frontend routes |
| `ui/src/pages/Architecture.tsx` | Hidden `/architecture` reference page |
| `docker-compose.yml` | ChromaDB + n8n (credentials from `.env`) |
| `.env.example` | All environment variables documented |

---

## Sprint history summary

This project was built across 16 sprints (SP1–SP16). The memory index in `~/.claude/projects/.../memory/MEMORY.md` has one entry per completed sprint with branch name, test counts, and key changes.

The main branch is `master`. Feature branches follow `feature/sp<N><letter>-<short-description>`.

---

## Known issues / tech debt

- `python-pptx` must be installed inside the venv (not system pip on macOS with Homebrew Python 3.13 / PEP 668)
- Slack bot must be manually invited to the target channel (`/invite @TaskReimagination` in Slack) before `SlackNotifyTool` works
- `taskreimagination.ai` must be a verified sender domain in Resend before reminder emails deliver
- The Architecture page (`/architecture`) is not linked from the nav — navigate directly
- The `business_plan` crew has never completed a real run. It only became buildable when
  `visual_illustrator` was registered; before that `create_business_plan_crew` raised
  before its first task. Treat its first run as an experiment.
- Deepgram (STT) and ElevenLabs (TTS) are used in secure mode by decision, both being
  streamed with no content retention. Local speech services are future work, not a
  current requirement.
- Avery still blocks on `HumanInputTool` for up to 24 hours during an interview programme,
  and nothing notifies the crew when a session completes. It does not affect interviewee
  experience, which is why sub-project B left it alone.
- `complete_session` and `_find_session_db` in `api/services/interview_service.py` open
  their connections with a bare `aiosqlite.connect(db_path)`, not
  `api.database.get_connection(slug)`. WAL survives that, because it is a persistent
  property of the database file once any code path sets it; `busy_timeout` does not, since
  it is per-connection and nothing sets it on this path. Found while proving twenty
  concurrent interview completions in `tests/test_interview_concurrency.py` - it did not
  fail the test on this workload, but the `get_connection` guarantee does not actually
  reach the `/complete` endpoint's writes. Worth a follow-up task.
- Secure mode runs two local models concurrently. `OLLAMA_MAX_LOADED_MODELS` defaults to 1, which
  makes them evict each other on every alternation regardless of free memory - see
  `docs/runbook-local-models.md` before diagnosing local models as slow.
- `build_and_run_agent` - the standalone "run this one agent" dispatch - fetches no validation
  warnings, skill notes, or change requests, so an agent dispatched that way is missing all
  three feedback channels `build_and_run_crew` gives it. Not currently reachable from the UI:
  `runAgent` is defined in `ui/src/api/endpoints.ts` and called by nothing, so every human
  re-run goes through the crew path. It is reachable from the API and from n8n.
- The Interview Coordinator still matches a stakeholder to a script by `node_label` when it
  plans a session, because `stakeholder_assignments` carries no script id. The match is now made
  once and recorded on `interview_sessions.script_id` rather than re-derived per answer, so the
  ambiguity is no longer repeated - but the single arbitrary choice at plan time remains, and
  `_resolve_script_id` deliberately stores NULL rather than guessing when a label is ambiguous.
  The real fix is a `script_id` column on `stakeholder_assignments`.
- `api.database.insert_interview_session` has no production caller - `InterviewSessionTool._create`
  is the only thing that inserts a session. The helper is driven by tests alone, which is exactly
  how a branch once extended it with a `script_id` column that production never populated. Delete
  it, or make it the producer; do not leave both.
- Retiring an interview script - `interview_script_ledger.active = 0` - is unreachable in
  practice. `SET active` appears exactly once in the codebase
  (`register_scripts_sync`, `agents/tools/_db.py`), its only route is an
  `interview_scripts` write carrying `active` on a script body, and Maya's own prompt
  (`agents/discovery/interaction_designer.py`) now tells her retirement is not done through
  that write - step 4 limits her to nodes with no script yet plus anything sent back, so an
  existing script is not hers to re-emit even to retire it. No UI offers it either. The
  mechanism works and is tested; nothing can currently ask for it. Nothing depends on it
  today - `scripts_awaiting_regeneration` filters on `active=1`, which is simply always
  true - and the design's one dependency is deferred with a soft revert, so this is a gap
  rather than a hole. The fix, when it is wanted, is a door (a UI action or an explicit
  instruction), not a change to the ledger.
- `register_scripts_sync` carries a near-copy of `scripts_awaiting_regeneration`'s WHERE
  clause to reset a regenerated script's `review_status`, and the two have **already
  diverged**: the query filters `active=1` and `project_id`, the copy does neither. A retired
  row sent back to the agent is therefore invisible to the query but still reset by the copy -
  a send-back cleared without ever having been actionable. Unreachable only because
  retirement is (see above). Extract the condition rather than copying it a third time.

---

## Environment variables

All env vars are documented in `.env.example`. Never commit `.env`. Key vars:

- `ADMIN_USERNAME` / `ADMIN_PASSWORD` — **required**, no defaults
- `JWT_SECRET` — generate with `openssl rand -hex 32`
- `N8N_BASIC_AUTH_USER` / `N8N_BASIC_AUTH_PASSWORD` — must match docker-compose.yml
- `PUBLIC_URL` — full public URL used in interview email links
