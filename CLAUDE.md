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
| Voice | ElevenLabs (TTS) + Deepgram (STT, primary since sp66) + Web Speech API (fallback) |
| Infra | Docker Compose (ChromaDB), Caddy (prod), cloudflared (prod) |

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

**Export `DATABASE_DIR`, `PROJECTS_DIR` and `DATA_DIR` to a private directory before invoking
pytest, and `mkdir -p` all three.** `conftest.py` reads all three with `setdefault`, so
exporting them is the whole of *pointing* the suite somewhere private - but it does not create
the directories, and not every test can. `test_agent_chat`'s fixture opens a bare
`aiosqlite.connect(db_path)`, which will not create a parent, so exporting without creating
produced **five errors, all `sqlite3.OperationalError: unable to open database file`, all
passing when that file was run alone**. That is precisely the shape the trap below describes -
filesystem errors, never an assertion - so it reads as somebody else's collision rather than as
your own missing `mkdir`. It self-heals on the second run, because a later test's
`get_connection` makes the directory, which is the worst available signal: the run that told
you something was wrong is the one you then cannot reproduce. The instruction stood here for
sprints without the two words, and cost sp66 an hour of chasing the wrong trap.
The fixed defaults are not only a hazard across *successive* runs: two agents running pytest at
once **corrupt each other**, because `conftest.py` `shutil.rmtree`s the default `DATA_DIR` at
import time, so a second session starting mid-flight deletes a directory under the first. The
tell is the shape of the failures - readonly database, `Directory not empty`, never an
assertion - and one such collision produced 77 failures and 28 errors, not one of them real. The
`rmtree` is guarded on the directory's own name being `agentpool_test_data`, which is precisely
what makes exporting the fix rather than a hope. Parallel agents are normal on this project now,
so this is a rule and not a precaution.

**The five tests catalogued for weeks as failing "against a fresh database" were never product
defects.** Three test files hardcoded `/tmp/agentpool_test` while the code under test reads
`get_settings().database_dir` and `.projects_dir`, so under isolation `test_projects_api`'s
autouse fixture scrubbed a directory nothing was using, `test_portfolio_register_returns_data`
wrote its fixture where the endpoint would never look, and `test_agent_chat` seeded one database
while the app opened another. Fixed in `51b8af1b` by reading the directories off the settings the
code under test reads. The consequence is the half worth keeping: **the suite's green depended on
those two paths coinciding**, which they do only while nobody exports the variables - so no clean
checkout, no new machine and no CI run has ever reproduced the counts this project has been
quoting, sp62's included.

**A second, unrelated reason the same sentence is true, found while verifying it.** `projects/`
holds exactly two tracked files, so a real checkout has no `sp-gs-am`, and four tests skip on the
absence of a fixture under it rather than the two this machine reports - two of them
(`test_sqlite_state_validation.py` and `test_value_chain_model.py`, both on
`value_chain_model_v2.json`) pass here only because a live crew run left the file behind, and two
in `test_value_chain_migration.py` are dark on every machine including this one. So **"2680
passed / 2 skipped" is a property of this workstation, not of the repository**; a clean clone
answers 2678 / 4 and nothing is wrong. The fix is committed fixtures under `tests/fixtures/`,
which the two dark tests already name as theirs.

Two things about that pair of numbers. **Recount both rather than adjusting one to match the
other** - the gap is exactly two today because exactly two tests depend on the stray file, and
nothing holds it there. And the four read a bare relative `Path("projects/sp-gs-am/outputs/…")`,
which reads neither `PROJECTS_DIR` nor the settings, so they are equally dark when `pytest` is run
from any directory but the repository root - `51b8af1b`'s settings repair does not reach them, and
committed fixtures still do.

**A module fixture that wipes the project `.db` is not enough.** `project_registry` lives in
the *shared system* database, and `POST /projects` registers with `INSERT OR IGNORE` - so a
test that reassigns a slug to another organisation leaves it owned by that organisation, and
the next test's freshly created project silently inherits the owner. This is the half of the
poisoned-database trap that no `.db` unlink reaches, and it applies to every module using the
sibling pattern: clear the registry row and the organisation too.

**A fixture that never runs reports nothing, and `asyncio_mode = strict` makes that the default
shape for an async one.** `pytest.ini` sets it, and under strict mode a plain `@pytest.fixture`
declared `async def` is handed to the test as an un-awaited async generator: the body never runs,
so neither the setup before the `yield` nor the clean-up after it happens, and nothing anywhere
complains. `tests/test_skill_agent_migration.py` and `tests/test_skill_description_migration.py`
each carried one written to stop the test leaving rows in `system.db`, and between them they had
never removed a row - the poisoned-database trap above, arriving through the fixture written to
prevent it. `@pytest_asyncio.fixture` is the fix, and it is sweepable **by AST rather than by
grep**, because a decorator can be spelled several ways and only a parse can tell
`@pytest.fixture`, `@pytest.fixture(autouse=True)` and an aliased `@fixture` apart from the right
one. Found by a second run seeing six rows where it had written two, which is the second run
catching what the first could not, again.

**Pass the clock, never read it.** A test written against "today" passes on the day it is
written and fails every day afterwards, and when it goes it does not announce itself as a clock
problem. Three tests in `ui/src/__tests__/milestoneVariance.test.ts` let `today` default to
`new Date()`; one detonated on 19 Aug 2026 and two more were dated to follow within the week -
while the block *below* them in the same file already carried a comment saying `today` is
passed explicitly "so these are deterministic". The lesson had been learned, written down, and
applied only to the tests being added at the time. Pass it everywhere, including where it
cannot currently matter, so the rule can be followed without deriving which arm a fixture hits.

Two things that look like evidence during forensics on `data/` and are not:

- **An AUTOINCREMENT high-water mark is not evidence of row churn here.** `init_system_db`
  runs on *every* system connection with no version gate, and its `INSERT OR IGNORE INTO
  organisations` bumps `sqlite_sequence` even when no row is created. It counts connection
  opens. It read as thousands of phantom inserts against one real row during sp57 and is
  nothing of the kind.
- **A running server on :8000 rewrites `data/system.db` while idle** - the scheduler restamps
  its heartbeat. Checksum before and after before attributing a change to the suite.

## Reviewing changes: the recurring failure mode

Repeatedly on this project a test has verified a property **one layer away from where it holds**.
In every case the shipped code was correct and the test could not distinguish correct from
incorrect (this sentence read "five times" for several sprints while the list below ran to
eight, which is its own small instance of the lesson - it is twelve now, and the word is there
so it cannot rot again):

- `check_write` tested; the tool calling it not.
- `staleness` tested; the endpoint assembling it not.
- An approval guard tested for one of its two conditions.
- `_fetch_change_requests` tested; the injection using it not.
- A radio tested as *rendered*; not as *sent*.
- The "why is this greyed out" note asserted per `<section>`, so any section already holding
  one satisfied every control in it and a newly gated field shipped with no explanation and a
  green suite. **An assertion scoped to a container is not an assertion about its contents** -
  the note now carries `data-explains` naming its fields, so the association is something the
  DOM holds rather than something proximity implies.
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
- A test that asserted one phase of a **multi-phase** screen. The rehearsal dialog draws the
  interviewer's face in five places across four phases; mutating each render back to the wrong
  agent in turn, **four of the five still passed**, because the first version asserted the
  device-setup screen alone. Right in one place and wrong in four is exactly what a screen looks
  like from its first frame. It now walks every phase, asserts every avatar on screen at each,
  and counts them so the loop cannot pass vacuously.
- Two doors answered a URL that nothing served, and both tests were green. The portrait test
  asserted the returned URL **equalled the literal the handler built**; the branding test
  asserted that literal and then fetched a *different* hardcoded path - so between them they
  proved a file was servable somewhere and that the door returned a string, and never that the
  two agreed. **A URL is a promise that something answers: fetch what the door returned.** The
  branding door had carried the defect since it was written, unseen because no deployment had
  ever uploaded a header image.
- **A budget asserted as arithmetic rather than as a deadline.** `find_duplicate_skill` bounded
  itself with `timeout=` and `max_retries=` on an `AsyncAnthropic` it built; routing it through
  `project_completion` left the deadline behind, because the seam accepts neither and imposes
  none of its own, and both clients behind it are sized for a caller that is waiting - 600s x 3
  hosted, 120s local - inside a crew run, for a nice-to-have attached to a revision that is
  already finished. The assertion that could not see it go was
  `_COMPARISON_TIMEOUT_SECONDS * (_COMPARISON_RETRIES + 1) <= 60`, true of two module constants
  whether or not anything sends them anywhere. **A budget is a property of the call, and it does
  not travel through a seam** - so it is `asyncio.wait_for` now and asserted as *behaviour*: an
  unanswered comparison resolves to "not a duplicate", logs, and does not hold the run.
- **A default and a write are indistinguishable until something chooses the other value.**
  Deleting `update_skill`'s `scope` write left every test of "a reviewer who approves without
  choosing stores `project`" green, because `insert_skill`'s default had already put `project`
  on the row and a handler that writes nothing satisfies that assertion perfectly. Only the
  widening control - the reviewer choosing `global` - could see the write had gone, and the
  margin was total: every one of the narrow-default tests passed, and the one control failed.
  **Assert a default and its opposite, or the test is about the schema rather than the code.**

When a test passes alone and fails in the suite, the isolated pass is the thing to distrust —
it is usually the one running under state no production caller ever has.

Pure functions and rendered state are cheap to assert, so they get asserted — and the assertion
lands beside the property rather than on it. When reviewing, ask: **"what calls this, and is
*that* tested?"** and **"would this test fail if the code were wrong?"** The second question is
different from "does this test pass", and far more productive here.

The same question asked of an agent is: **does anything one of its declared tools returns
actually fill the placeholder its description asks for?** Jordan's task told him to emit
`{url_base}/{session_token}`, and he has no route to a session token - his `SQLiteStateTool`
read of `interview_sessions` always answers "no state found", and none of
`InterviewSessionTool`'s four operations returns an existing one. `agents/reads.py` already
records which reads are unresolvable, so the answer is usually there to be looked up. The block
had never fired only because `public_interview_url_base` was `""` and falsy, so giving that
read a real value - a correct repair in itself - would have armed it, and the output would have
been a fabricated UUID forming a well-formed dead link on the deployment's own domain, written
into `draft_message`. **"This code has never run" is not "this code works"**, and repairing
whatever kept it from running is precisely when the difference arrives.

That shape has now arrived often enough to be expected rather than discovered: the branding
door that answered a URL nothing served, unseen because no deployment had ever uploaded a
header image; `insert_interview_session`, extended with a column production never populated;
`upsert_agent_config`, built three tasks before any door could write its table. **sp66's
Deepgram grant door is the sharpest instance, because two defects were sitting in it and the
repair that armed the path is what found both.** `GET /api/interviews/{session_token}/
deepgram-token` landed in `e1c075d4` on 13 May 2026 - mounted, tested, and called by no line
of `ui/src` for **four months**. It read `resp.json()["key"]` and posted
`{"grant_type": "instant"}`; Deepgram's
grant endpoint answers `access_token` and takes only `ttl_seconds`, so the first real call
would have been a `KeyError` and a 500. Beside it, `listenForAnswer` returned `''` when the
browser had no `SpeechRecognition`, so a participant in Firefox gave a full interview that
recorded nothing and told nobody. Both were green throughout, because a door nothing opens
cannot fail and a test can supply the recogniser the browser will not. **The lesson to take
is about the review question rather than about Deepgram**: for any path, ask *what calls this
in production* before asking whether its tests pass, and treat "nothing does" as a finding in
itself rather than as an absence of evidence.

**Quoting a rule is not applying it.** A guard was written on this branch whose docstring
*cited* this file's own "a guard's reach must be established, not described" - and then
described its reach instead of establishing it. It was defeated on the first attempt, by a
parser differential: `str.strip()` removes a strictly smaller set than the WHATWG URL parser,
which also strips tab, LF and CR from *anywhere* in the string before it reads a scheme, so
`ja\tvascript:` matched no scheme at the door, was stored verbatim, and was reassembled by the
browser into exactly the scheme being refused. Every refused scheme could be spelled with a tab
in it. **This is the fourth recorded instance of that failure and the first introduced by a
change quoting the other three**, and the citation did active harm: it read as evidence the rule
had been followed, to the reviewer as well as to the author. A comment citing a rule is evidence
about intent, and it is routinely read as evidence about behaviour. The repair is the one this
file already prescribes - the normaliser is now a pure function driven directly, in **both**
directions, so a hostile candidate that `str.strip()` already handles fails the test rather than
passing it, and an over-aggressive normaliser fails it too.

**A sentinel drawn from the system's own defaults cannot fail.** The end-to-end test wrote
`/agents/avery-singh.jpg` and asserted on it - and that string *is*
`agent_defaults("stakeholder_interviewer")["image_url"]`. Deleting the known-good write entirely
left all four parameters green: the assertion could not distinguish "the hostile value never
landed" from "there was never a row". Same family as the `check_write` case above, where the
refusal message quoted the key it was refusing, with the substring drawn from the system's
defaults rather than from the call. What makes it worth recording is where the rule already was:
**the same file states it thirty lines higher**, in `CHOSEN_VOICE`'s own comment - *a string
chosen to be visibly unlike any real id, so an assertion on it cannot accidentally pass because a
default happened to match* - written by the same author in the same change. A rule stated beside
code protects that code and nothing else, which is the milestone-clock lesson arriving in a
second form. The generalisable half is the repair: the sentinel is held against **every**
identity's image rather than against Avery's, because the collision was found by reading one
agent's default and the next agent added could be any of the eighteen.

**A fake is a claim about an external system, and nothing here can check one.** This is a
*different* mechanism from every entry above, and the difference decides where to look for it.
In those, the assertion is in the wrong place - one layer away from the property, scoped to a
container, drawn from the system's own defaults - and reading the test against the code finds
it. Here the assertion is in exactly the right place, asserting exactly the right thing, and
the simulated world it runs in is wrong; reading the test against the code finds nothing,
because the code and the test agree. The only thing that can contradict a fake is the
specification of the system it imitates.

Two of sp66's three Important findings were this, and both fakes were wrong **in the same
direction as the bug**, which is what made them invisible. `FakeSocket.drop()` fired `close`
alone; a real socket failing after open fires `error` **then** `close`, which is the exact case
the handover code exists for - so the non-idempotent handler started a second recogniser, the
first was orphaned holding the microphone for the rest of the interview, and the test that
existed to cover the handover watched one event and saw one handover. `FakeRecorder.stop()`
fired no `onstop`, so a flush that waited for the recorder's final chunk could not be
distinguished from one that did not wait at all. Neither was found by the suite. Both were
found by a reviewer reading the code against the WebSocket and MediaRecorder specifications.

So: **when a test's world is simulated, the fake needs its own review against the real thing's
contract, and it is worth writing the contract down beside it.** The fakes now fire `error`
then `close`, and hand over a final chunk before `onstop`, because that is what the real ones
do - and where a fake deliberately simplifies, the simplification is a comment rather than a
silence. The cheapest tell that you are in this territory: a test whose green depends on an
event ordering you have not read the specification for.

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

**Ask which database you are touching before reaching for `_SCHEMA_VERSION`, because the rule
is inverted between the two.** A *project* table needs the bump, for the reason below. A
`system.db` table needs none and must not have one: `init_system_db` is idempotent, has no
version gate, and runs on every system connection, so a `CREATE TABLE IF NOT EXISTS` there is
already enough - and bumping the constant would re-run every project migration on every
deployment for a table in a database it does not govern. Both halves are stated here; the
mistake is applying the correct rule to the wrong target, which neither half alone prevents.

When adding a new `_migrate_*` function, bump `_SCHEMA_VERSION` in `api/database.py` in the
same change and add the new function to the migration block `get_connection` runs. Forgetting
fails unsafe, not loudly: `get_connection` only re-runs the migration block when
`PRAGMA user_version < _SCHEMA_VERSION`, so a new migration added without bumping the version
silently never runs on any database that has already been opened once at the current version -
no error, no warning, just rows that stay unmigrated forever on every existing deployment.

**A migration's test must pin the version immediately below the constant, as a literal.** Not
`_SCHEMA_VERSION - 1`, which is *always* the version below the constant and therefore passes
under a constant that never moved; and not some older number, because `get_connection` re-runs
the whole block whenever `user_version` is lower, so a database stamped at 14 gains the table
under any constant above 14. Such a test proves the migration **function** works and never
proves the **bump** covers it - one digit between the two. sp60 nearly shipped exactly that: it
was paused at 15, master reached 17 while it waited, and its own test stamped 14, so resolving
the merge in master's favour - which is what "take the newer number" looks like - would have
left `_migrate_value_chain_ledger` sitting in the block, unreached on every database already
opened at 17, with twenty-two green tests over it. Demonstrated both ways rather than reasoned
about, and worth doing again for the next one: at constant 17 with the test pinned at 14 all 22
passed, and pinned at 17 it failed alone.

**A writer that requires columns its callers do not care about will be got wrong by one of
them.** `update_project_config` wrote `llm_mode`, `force_local_inference` and `sector` on every
call, all three mandatory, so a door that only wanted to merge one `config_json` key still had
to restate three columns it had no opinion about. Six such carry-through lines existed, every
one correct on the way in, and **five could be mutated with the whole backend suite green** -
so no test named the defect and no reviewer would have. Driven end to end, a wrong `llm_mode`
there flips a `sensitive` project to `standard` *immediately* (the writer drops the mode cache
on its way out), which permits `CLOUD_VECTOR_STORE`, which builds a `CloudClient`: the
engagement's corpus to Chroma Cloud, no error, no warning, triggerable by a `project_admin`
uploading a **logo** or an approver adding a link - both of whom are 403'd from changing
`llm_mode` through the front door.

The fix is a seam, not a walk. `merge_project_config` takes the **row** and reads the three
columns off it, so there is nothing for a caller to get wrong and nothing for two callers to
spell differently - which had already begun, two sites reading `sector` as `project["sector"]`
and `project.get("sector") or ""`. A source walk can only ever see a *new* caller, never a
wrong value; it is kept alongside purely to stop the seam being bypassed
(`test_the_wide_project_config_writer_has_exactly_one_production_caller`, set equality over the
two declared callers, so a vanished caller fails as loudly as a new one). Generally: when
a signature obliges every caller to restate state it does not own, the signature is the defect.
Give the writer the row, or narrow it.

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

**Nothing notifies a reviewer that a gate is waiting.** `HumanInputTool` writes the review to the
project database and polls it until a human decides. It used to post the review to an n8n webhook
first, which relayed to Slack; SP50 retired n8n and no channel replaced the post. The gate is
unaffected — the polling was always the mechanism and the post only a nudge, and any deployment
that never configured `N8N_WEBHOOK_URL` already ran exactly this way — but an agent can now sit on
a gate for the full 24-hour timeout with nobody aware. `tests/test_human_input.py` asserts the
absence at the boundary rather than describing it, so the state is checked rather than assumed.

The intended replacement, decided 2026-08-17, is a **message push carrying a link and a token that
brings the reviewer to the content on the server** — never the content itself. Half of it already
existed in the retired payload, which carried a `review_url` pointing at the dashboard; what it
lacked was a token and a channel that was not n8n. `deliver_reset` in
`api/services/invite_service.py` is the established shape for "one place delivery is decided", and
while `FROM_EMAIL` names an unverified Resend domain an administrator-visible link is the honest
channel — the same one the invite and reset doors run on today.

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

`POST /{slug}/node-ledger/{id}/review` and `POST /{slug}/lever-ledger/{id}/review` are in
**both** rows and are the only doors that are: one handler asks `caller_may_approve` when the
decision is `approved` and `caller_may_contribute` otherwise, because reading an item and
approving it are the same door with different consequences. They ask the two by name rather
than restating the role sets inline, which is what the four call sites below do and is why
those four are not uniform with each other.

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
branding header, and each agent's name, face and voice. Thirty-five project-scoped doors,
none of which takes a content gate, as project creation does not either. That is deliberate:
a consultant configures the engagement, and a client-side approver does not, however senior
they are on the project. They now split across the two administration rows:

| Gate | Doors |
|------|-------|
| `require_project_administration` (17) | `stakeholders.py` (5 - not `resend-invite`, and not the roster `GET`), `milestones.py` (4 - not `rebaseline`), `nonworking.py` (3), `projects.py` (2 - `PATCH /{slug}/settings` and `POST /{slug}/branding/image`), `assignment.py` (1 - `POST /{slug}/assignment`), `agent_config.py` (2 - `PUT .../agents/{agent_id}/config` and `POST .../agents/{agent_id}/image`) |
| `Depends(require_org_admin_or_above)` (18) | `campaigns.py` (10), `documents.py` (3), `assignment.py` (1 - `advance`), `orchestrate.py`, `run.py`, `voices.py`'s `POST /{slug}/voices/library`, and `stakeholders.py`'s `resend-invite` |

17 + 18 = the thirty-five. `POST /projects` sits outside the count and keeps the platform
tier of necessity: there is no slug yet to scope a per-project role by.

**Recounted in sp62 from `app.routes`, and the composition had drifted further than the
totals.** The file said 15 + 18 = 33; the measurement is 16 + 18 = 34, and *three* doors moved
under a total that changed by one. `stakeholders.py`'s roster `GET` came off the gate
(96863718 - it answers the roster to any member and drops the account-derived fields instead,
so the disclosure is narrowed in the response rather than at the door) and `assignment.py`'s
`POST /{slug}/assignment` moved onto it (64712393); **both predate sp62**, and only
`agent_config.py`'s `PUT` is this branch's. So the second row's total is unchanged while two
of its members are not the ones named, and the `require_project_administration` docstring's
"sixteen doors" - wrong for a sprint - was made *accidentally correct* by an unrelated task.
That is the case this file's "recount rather than adjusting one to match the other" was
written for: adjusting either number to agree with the other would have produced a table that
is internally consistent and wrong in three places.

**Recounted again in sp63 - 104 `{slug}` routes, 101 calling the floor, 17 on
`require_project_administration` - and the technique matters more than the totals, because a
text-keyed sweep can no longer produce them.** `get_agent_image` explains in its docstring why
it has no floor, and *contains the string `check_project_access` while doing so*, so a grep
counts it as gated and finds two exceptions where there are three. Parse each handler and look
for a **call**: a docstring cannot be an `ast.Call`. That is *enumerate by behaviour, not by
name* arriving a fourth time, in the one shape the earlier three did not take - not a file
hidden from the sweep, but a file the sweep saw and misread.

**What the second row's eighteen excludes, so the next recount does not find twenty-two and
assume drift.** Twenty-two `{slug}` routes carry `require_org_admin_or_above` or
`require_sysadmin` as a dependency. Four are deliberately outside the project-scoped
administration count: `admin.py`'s three (`DELETE /auth/projects/{slug}` and the two
`/auth/users/{user_id}/projects/{slug}` membership writes) are registry and account
administration, global by nature and governed by the exclusion rule above rather than by this
table; and `GET /projects/{slug}/data-architecture` is a **read**. An administration door is
one that changes how the engagement is run, so a read behind a platform-tier dependency is
not one of them.

**`PATCH /{slug}/settings` is on the widened list but is not uniformly widened.** Its body
carries `llm_mode`, `force_local_inference`, `dev_mode` and the six per-agent model ids
alongside the sector and the stakeholder groups, and those nine decide *where this
engagement's data is sent* rather than how it is configured. `_PLATFORM_TIER_SETTINGS` in
`projects.py` holds them, and a `project_admin` who changes any of them is refused with a 403 naming the fields. Flipping a
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
writes only `ProjectCreate`'s eight fields, of which `llm_mode` is the sole overlap, so on
every project before its first full settings save, eight of the nine protected fields are
simply not in `config_json` and a `field in current` test would have protected the mode alone.
Both counts move independently - recount rather than adjusting one to match the other.

The second group is not a judgement that those eighteen should stay - sp44 widened exactly
what its brief named, which is the set the design calls "configures the project and its
people". Whether a project_admin should start a crew run or import a campaign is a live
question, not a settled one. What is settled is the exclusion above: the membership,
account, and organisation-membership writes stay on the platform tier whatever else moves.

`POST /{milestone_id}/rebaseline` is the one door in `milestones.py` that took neither -
moving a promise is a content judgement, so it keeps `caller_may_commit` on top of the
membership floor.

*Content* is acting on what the crews produced: reviews, change requests, warning
dispositions, commits, submissions, activation, the canonical value chain, reverts,
milestone re-baselining, script reviews and script edits, and - since sp60 - per-node and
per-lever reviews. **Eighteen** doors ask the walk, sixteen at sp44 plus the two item-review
writes; `GET /{slug}/my-permissions` reads it and gates nothing, so it is not one of them. The
two item-review **reads** take the membership floor alone, like every other read.

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
- `/auth/*`, `/admin/skills/*` and templates carry no slug, so there is nothing to walk. They
  take login-role dependencies instead.

**A third question, and it is not one of the two axes.** Both axes ask who the caller is on
this engagement. Neither asks **which store the write reaches**, and since sp57 that is a
separate question with a separate answer, because a document filed at the sector tier leaves
the engagement entirely - on a consultancy deployment `sector_{sector}` spans different
clients. Four doors answer it, all through `require_writable_tier(slug, tier, payload,
action=...)` in `authority_service.py`:

| Door | Where the tier comes from | Verb |
|------|---------------------------|------|
| `POST /{slug}/documents/upload` | declared in the request, defaulting to `project` | `WRITE_ADD` (the default) |
| `POST /{slug}/agent-chat/upload` | declared in the request, defaulting to `project` | `WRITE_ADD` (the default) |
| `DELETE /{slug}/documents/{doc_id}` | read off the row - `_tier_of(doc)` | `WRITE_REMOVE` |
| `POST /{slug}/documents/{doc_id}/reingest` | read off the row - `_tier_of(doc)` | `WRITE_REINDEX` |

So a new write door has **four** things to remember, not three: the floor, the gate, the tier,
and the verb. The verb reaches the refusal *sentence* and nothing else - the rule does not
branch on it and must not start to, since adding, removing and re-indexing are all writes to
one store and the authority for a store is the same whichever verb reaches it. It defaults to
the upload doors', so forgetting it yields a slightly wrong sentence rather than a wrong
decision, and the wrong sentence matters: an operator refused a delete and told they "may not
add material" reads the product as broken rather than as refusing them.

The two upload doors *declare* a tier; the two that act on an existing document *read* the one
its row already carries. Never infer a tier from the caller or the project - a project belongs
to one organisation and one sector, but a tier is a property of the **document**.

`may_write_tier_on_project` decides in two halves and the order is load-bearing. The
login-role half (`assert_may_write_tier`, in `knowledge_tiers.py`) settles the **vocabulary** -
raising `ValueError` for a tier that does not exist rather than refusing it, because "no such
tier" and "not yours" owe the caller different answers, and `require_writable_tier` is the one
place they become 422 and 403 - and settles the **sector**, which is `sysadmin` alone and
needs no project to decide. The project-scoped half settles the other two: `organisation`
compares the project's `project_registry.org_id` through `may_access_org`, and `project` takes
platform authority *scoped to this project's organisation*, or `project_admin` or `approver`
from the walk.

Sector is deliberately the narrowest authority in the system. That is not a judgement about
how consequential the write feels; it is that the sector store is the only one whose
readership is other clients. **A consequence to expect rather than diagnose:** a sector-tier
document uploaded in error is removable by a `sysadmin` alone, so an `org_admin` cannot undo
their own misfiling. The refusal names the tier so they can say what to ask for.

**Removing material is a write**, and the check sits **before** the purge - a refusal raised
after the chunks are gone is not a refusal. `reingest` took the same check unasked, because it
re-writes the document's chunks into the store its row names; two adjacent doors where only
one asks is how the next sweep finds the second.

**Material only ever moves narrower**, and at the ingest path that is structural rather than
checked: the project branch passes neither the sector nor the organisation key to
`collection_for`, and no caller anywhere hands the ingest path a collection *name*. There is
no promotion door, deliberately - a document reaches a broader store only by being uploaded
there by somebody who may write there.

**Deleting from a shared store needs the slug on the chunk, not just the collection.**
`doc_id` is a per-project SQLite id, so deleting by `doc_id` alone in `org_` or `sector_`
would take a sibling project's chunks with it. `chunk_filter_for(slug, doc_id, tier)` in
`ingest_service.py` is the one place that is decided, and it is **asymmetric on purpose**:
`{"doc_id": ...}` at the project tier, `{"$and": [...]}` at the broader ones. The asymmetry is
a correctness requirement running in the direction that surprises people. Every chunk ingested
before sp57 carries no `slug` metadata at all, so a project-tier filter naming `slug` would
match none of them and the delete would remove nothing - a failure that looks like a working
delete. The broader tiers are safe to filter strictly for the mirror-image reason: nothing was
ever written there before.

`GET /my-permissions` answers `writable_knowledge_tiers`, project-scoped and broadest first,
and the upload dialog's tier picker filters on it. **Never restate the rule in TypeScript** - a
tier a caller cannot write must not be rendered at all.

**The store a document is in is recorded, not recalculated.**
`client_documents.knowledge_collection` holds the name Chroma was actually handed, written in
`update_document_ingested` at the moment the write succeeds - the moment an address stops
being a calculation and becomes a fact. The tier alone was durable from the start, and it is
only **one of three inputs** to a collection name; the other two were re-read at delete time
and both move through ordinary, correctly-gated doors. `projects.sector` sits deliberately
outside `_PLATFORM_TIER_SETTINGS`, so a `project_admin` may change it through `PATCH
/{slug}/settings`, and `insert_project_registry` is an upsert whose whole purpose is
reassigning an engagement. Change either between upload and delete, and the delete purged a
store the write had never touched, answered **204**, and removed the row and the file - leaving
the text permanently retrievable in a shared store with nothing left that could name it,
because the row was the handle. The organisation variant strands it in a *different client's*
store, and `get_or_create_collection` creates that store on the way past. Both doors now read
the recorded name and fall back to re-derivation only when it is blank, so no legacy document
becomes undeletable. This is the same principle stated below under *Resolving an output: ask
the ledger, never the disk* - an address that is re-derived is an address that can move
underneath the thing it points at.

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
properly: 108 handlers are mounted under a path containing `{slug}`, and the check is whether
each one calls `check_project_access`. **One hundred and five of the hundred and eight call it.**
The count was 104 at sp63 and gained sp60's four item-review doors, all of which ask the floor -
recount by enumerating `app.routes` rather than adjusting the number, because a count nobody
re-derives is the thing this paragraph warns about two rows below. The three that do not:

| Door | Why not |
|------|---------|
| `GET /projects/{slug}/branding/image` | Deliberate - no auth at all. The interview page renders it for a participant who has no login. If that image ever becomes client-confidential the fix is session-token scoping, not `check_project_access`. |
| `GET /projects/{slug}/agents/{agent_id}/image` | The same exception serving the same page - a participant sees the interviewer's face before they have any login to check. It multiplies the probe surface by eighteen without widening it: a 200 tells a caller who already knows the slug that a portrait exists, which is what the door is for. |
| `DELETE /auth/projects/{slug}` | Registry administration, `require_sysadmin`. Global by nature, and a sysadmin passes the floor unconditionally, so the call would be a no-op. |

**This table is keyed on `{slug}`, so it cannot show every unauthenticated door - and there is
a fourth.** `GET /api/agents/{agent_id}/image` (`api/routers/agent_assets.py`) serves the
deployment's promoted default portrait to the same participant, with no authentication and no
project at all, so the sweep above never sees it and a reader of the three rows concludes the
surface has three when it has four. It is the deliberate sibling of the second row rather than a
new decision: same page, same reason, and *less* to learn from it, since an address with no slug
in it cannot be used to probe whether an engagement exists. The caveat is the same one two
paragraphs below makes for a door taking its slug from the request body - this is one step
further out, a door with no slug anywhere.

`WEBSOCKET /ws/{slug}` was the third row and this file called it the largest remaining
exposure on the surface: open to anyone who could reach the port, streaming agent log lines
that carry client material verbatim. It is closed and has been for a while - `api/routers/
ws.py` reads the JWT out of `Sec-WebSocket-Protocol` (two offered names, the literal `bearer`
then the token) and calls `check_project_access` **before** `accept()`, so a refused caller
never holds a socket at all. A browser cannot set an `Authorization` header on a handshake,
which is why this stayed open; `?token=` was rejected as worse than the hole, since sessions
here roll for thirty days and a URL lands in proxy logs, history and referrers. **The row
outlived the defect by several sprints, which is the reason to distrust a table like this one
rather than the reason to delete it** - a stale hole lends false confidence to the entries
beside it.

**Reproduce the sweep by enumerating `app.routes`, not by grepping decorators.** The recipe
this file used to give - an AST walk joining each `APIRouter(prefix=...)` to its
`@router.<method>` paths - undercounts by two today, because `api/routers/inbound_mail.py`
names its second router `replies_router` and both its doors are invisible to a walk keyed on
the name `router`. They do call `check_project_access`; the point is that the technique could
not have told you. That is *enumerate by behaviour, not by name* biting the recipe written to
enforce it, which is the third time on this codebase a name-keyed sweep has missed a file.

**The sweep counts routes whose *path* holds `{slug}` and nothing else.** A project-scoped
door taking its slug from the request *body* does not appear in it - `POST
/api/interviews/test/elaboration-press` is that shape, and does call `check_project_access`,
but the technique cannot see it. One hundred and eight is not a completeness guarantee - and
this sentence said "one hundred and four" for a while after the recount two paragraphs above
it moved the number, which is the drift the paragraph above warns about, happening inside the
warning. **Recount both figures rather than adjusting one to match the other**, and when the
count moves, grep this file for the old number before believing it has been updated.

**There are two body-slug doors now, and the second one arrived carrying a live hole.**
`POST /api/interviews/test/speak` had no slug at all until sp62 gave it one so it could
resolve the rehearsed agent's voice per project - and **adding the slug added the exposure**,
because a door with nothing to scope by needs no floor and a door with a slug does. An
`org_admin` of an *unrelated* organisation was answered 200 and the wire carried that
project's private voice. `check_project_access(body.slug, payload)` is now the first line of
both, before the slug reaches a database. Two things generalise. A door that gains a slug
gains a floor in the same change, and the sweep will not remind you. And the refusal was
asserted **on the wire**, not on the status: moving the check to after `speak` returns still
answers 403, so a status-only test passes a door that synthesises the private voice and
*then* refuses. Nothing anywhere sweeps for handlers reading a slug from the body; that is
its own task, and the count above is the reason it is easy to keep forgetting.

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

**Revocation also deletes the outstanding invite** - `cancel_invite` in `invite_service.py`,
called from the same handler. The membership is what a login already holds; the unredeemed
token is what a login could still be *made* from, and `POST /auth/accept` takes no
authentication, so leaving it live left the access nominally withdrawn and actually
available. The row is deleted rather than stamped `used_at`: nobody redeemed it, and a
re-grant should insert a fresh one through `issue_invite`'s normal path rather than refresh a
tombstone. Expect the `auth_tokens` row to be *gone* after a revocation - that is designed,
not a missing write. `access_state` additionally asks the role question before the invite
question, so a role-less row cannot read `invited` even if a token survives by some path
neither of these covers.

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
`/projects`, `/auth`, `/admin`, `/system`, `/api`, and `/ws` - six since sp65 deleted the
`/agent-skill-notes` router, and the count moves whenever a router does. A prefix
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

**Each tab of `AgentDetailPanel` means one thing, and the test that decides is: if this agent
were renamed or replaced, would this content move with them?** *Agents* is who the agent is and
how they behave, keyed on the agent (`AGENT_SETUP_SECTION` in `tabs/CrewAgentsTab.tsx`);
*Setup* is how the engagement is configured and *Status* is what it is doing, both keyed on the
crew (`CREW_SETUP_SECTION` / `CREW_STATUS_SECTION` in `AgentDetailPanel.tsx`). Six panels were
on Agents because their **components were named after agents** - `PamSetupTab`, `AlexSetupTab`,
`MayaSetupTab`, `JordanSetupTab`, `TaylorSetupTab` - and asked the question, five of them held
the engagement's schedule, brief, disciplines, mapping and roster rather than anything of the
agent's. Only Avery's interviewing style survives, and the Agents tab being thin is the correct
outcome. **All five files were renamed** - `ProjectScheduleSetup`, `DiscoveryBriefSetup`,
`InterviewProgrammePanel`, `StakeholderMappingSetup`, `StakeholderSummaryPanel` - because the
filename was the *mechanism* of the misclassification rather than a symptom of it: a component
called `PamSetupTab` is configuration **for** an agent read as configuration **of** one, and
moving it while leaving the name would hand the next reader the same wrong signal and invite the
same decision back. `ui/src/__tests__/TabClassification.test.tsx` states the classification as a
property: set equality per tab over each panel's `data-panel-section`, so a seventh panel
registered with no decision about where it belongs fails rather than lands.

Three consequences worth knowing before touching it. **Every absence assertion must be scoped
with `within()` on the tab's own panel and made after every tab has been opened** - Output,
Setup and Agents render `hidden` rather than unmounted (a half-typed brief must survive a trip
to Output), so a screen-level `queryByText` finds content on an inactive tab and an assertion
made before a tab mounts passes against the mount latch instead of against the placement.
**Hidden means latched**: `setupOpened` / `agentsOpened` stop a panel opened on Output fetching
a schedule nobody asked for, and they are effects on `tab`, not click handlers, because a deep
link can open the panel straight onto either. And **two deep links name a tab** -
`AssignmentRedirect` in `router.tsx` and Runs' "Assign stakeholders" - so anything that moves
the stakeholder mapping moves both; they are driven to the content in
`ui/src/__tests__/AssignmentRouteRetired.test.tsx` rather than checked for a string, because a link that lands on
the right crew and the wrong tab looks exactly like working navigation.

**`ui/public` is served under the `/dashboard` base, so a bare `/agents/*.jpg` 404s in the
browser.** `AGENT_AVATAR_IMAGE` in `agentStatus.ts` is the only map that knows the base - it
prefixes `import.meta.env.BASE_URL` - while `AGENT_IDENTITY.image` on the server is the
unprefixed path. They mean the same file and `tests/test_persona_transcription.py` holds them
equal, so the difference is one of **address** rather than of content, and rendering the server's
resolved default turns a bug about one face into a bug about eighteen. This has caught three
separate pieces of work on one branch, which is why it is here rather than in a comment.
`useAgentIdentity` is where it is decided - the project's override first, then a default the
front end can actually fetch - and `??` rather than `||`, because `''` is a portrait a project
has **deliberately cleared** and must reach the initials rather than reinstate the map over that
decision. The consequence for anything drawing a default: a **promoted** default is a URL this
deployment serves and resolves, a **built-in** one is that bare path and does not, so the server's
answer has to say which it handed over. Never sniff an `/api/` prefix in the client.
`AgentAvatar` owns the missing-portrait fallback - initials on a plain background, never a broken
image and never some other agent's face - and six older sites still carry their own copy of that
rule, which `agentInitials` is exported so they can stop doing.

`StakeholderForm.tsx` offers five role checkboxes, and the last two - Project Administrator
and Governor - render only when `GET /my-permissions` answers `can_grant_roles`, because the
server refuses both to anyone without `project_admin` on that slug and a checkbox that always
403s is worse than no checkbox. The half that matters more is what is *sent*: a caller who
may not grant them omits both keys entirely rather than sending `false`. The form posts its
whole state, so without that an org_admin editing a job title on somebody who already holds
`project_admin` would resend `is_project_admin: true` and be refused for a grant nobody asked
to make - and sending `false` instead would silently revoke it. Neither flag is declared on
`StakeholderIn`/`StakeholderPatch`, so a write that does not mention them does not touch them.

**Every control on `Settings.tsx` spreads `fieldProps(field)`**, which sets `disabled` from
`/my-permissions`' `platform_tier_settings` *and* sets `id` to the field name. The two arrive
together deliberately: `tests/test_settings_platform_tier_wiring.py` walks the page for any
control that renders without asking, and the whole-set test finds controls by
`getElementById(field)`, so a tenth field whose control used some other id would gate correctly
and pass **vacuously**. A field rendered as several controls passes a `variant` - the gate is
still the field's. Two consequences when writing tests here: a locked control needs a
`PlatformTierNote` whose `data-explains` names it, and a test that *edits* one of these fields
must `await waitFor(() => expect(control).toBeEnabled())` first - `fireEvent.change` on a
disabled input is silently ignored, which had already made one existing test racy rather than
failing.

**Every field `Settings.tsx` promises to send is declared in `ui/src/types.ts`, and required.**
That is the 22 fields in the page's `DEFAULTS`, out of `ProjectSettings`' **38**, and it is the
whole of what `test_every_field_the_page_promises_to_send_is_declared_required` holds. Settings
are saved by posting the page's whole state, assembled as `{ ...DEFAULTS, ...settings }` - an
untyped spread, so an undeclared field survives the round-trip by luck and vanishes the moment
anybody builds that payload field by field. It fails silently in the worst direction: a dropped
`interviewer_selection` **puts a project that chose one interviewer back on a coin toss per
session**, by a system reporting success. No error, no 403, nothing on the screen.
`interviewer_selection` and `interview_accent` were the third and fourth fields to need this,
and `locale` the fifth - `force_local_inference` and `dev_mode` were already declared for
exactly this reason, the second found undeclared *one field over* from the first, and `locale`
found the same way again. So: **a field the page sends with no declaration here is a defect
waiting for a typed request body, not a stylistic gap**, and optionalising one
(`some_field?: string`) reopens the hazard as completely as omitting it.
The walk is keyed on `DEFAULTS`, so it cannot see a field removed from *both* `DEFAULTS` and
the type - the parametrisation simply shrinks and complains about nothing. That is why
`test_the_interview_programme_settings_are_carried_by_the_defaults` names
`interviewer_selection` explicitly: guarded by name rather than by the walk that cannot see it
go. **`interview_accent` was named beside it and is retired in sp64**, which is the one removal
that list must not resist - so a name comes off it only alongside the `ProjectSettings` field
it guards, and that pairing is itself asserted, in
`tests/test_voice_catalogue.py::test_neither_side_declares_the_retired_interview_accent_setting`.
Every count in this section moved by one when it went - recount rather than adjusting one to
match another, which is the instruction the platform-tier section beside it already gives.

**The other sixteen fields are outside that guard, and the sentence above used to claim them.**
It read *every `ProjectSettings` field*, which was untrue of sixteen of thirty-eight - and untrue
of three fields **this branch itself touched**, so the commit declaring the class closed left
three of its own inside it. Recount rather than trusting either number; they move independently:

| | count | |
|---|---|---|
| declared **required** | 22 | exactly `DEFAULTS`, and exactly what the guard walks |
| declared **optional** (`?:`) | 13 | includes `brand_header_image_url`, which this section warns about by name |
| **not declared at all** | 3 | `brand_interviewer_name`, `brand_interviewer_image_url`, `brand_interviewer_tagline` |

They are outside the guard because none of them is in `DEFAULTS`, so the Settings page makes no
promise about them - not because they are safe. **Five call sites build this body, not one**:
`Settings.tsx`, `Schedule.tsx`, `PamSetupTab.tsx`, `MayaSetupTab.tsx` and `AlexSetupTab.tsx`, and
the four besides Settings spread the *fetched* row (`{ ...settings, sched_start: … }`) to change
one field. TypeScript's excess-property check does not apply through a spread, so the three
undeclared fields ride all five by the same luck, and the thirteen optional ones are declared but
carry no obligation - `tsc` has nothing to say about an omitted optional key. Declaring the
sixteen is the fix; until then this is a known sixteen rather than a closed class.

Of the three undeclared, **`brand_interviewer_tagline` is live** - `interview_service.py:184`
reads it onto the interview page - so it is the one carrying real risk today.
**`brand_interviewer_name` and `brand_interviewer_image_url` are dead.** Nothing reads either:
`get_session_with_script` builds the participant's branding from `_interviewer_identity`, the
session's own stamp, which is what *The interviewer and the voice are stamped on the session*
below is describing - and no UI has ever set them. Every stored `config_json` on the deployment
still holds the shipped literal `"Avery Singh"`, which is precisely why they had to stop being
read: a project could not distinguish "we branded this" from "this is what shipped", and with
two interviewers roughly half of every project's participants would have heard Laura and read
Avery. So a **deletion, not a migration** - nothing reads the stored value, so nothing has to be
moved. They are named here rather than left as two undocumented unused fields that read as
somebody's unfinished intent.

`AGENT_IDS` in `ui/src/components/agentStatus.ts` bridges the front end's role keys
(`'Stakeholder Interviewer'`) to the server's permanent ids (`'stakeholder_interviewer'`), and
it is **declared, never derived**. 18 entries, of which **17 derive** from
`id.replace('_',' ').title()` and only `pam` resists. One exception out of eighteen is the whole
argument, and it is the *more* dangerous ratio rather than the safer one: a derivation correct
for seventeen entries reads as correct at every call site while the eighteenth fails silently -
silently being precise, because a wrong id that happens to exist configures a different agent
and answers 200. The count is held by
`test_the_bridge_is_not_a_formatting_of_the_id`, which asserts both the number and that PAM is
the one, so making PAM derivable asks for the decision again instead of quietly making a
`.title()` one-liner look safe. (An earlier comment claimed nine of eighteen and named both
interviewers among the exceptions; both derive cleanly. It rotted because nothing could
contradict it.)

**Two Setup tabs still persist to `localStorage`, and neither has ever reached an agent.**
`AverySetupTab.tsx` writes `agentpool-avery-voice-config-<slug>` - six *behavioural* preferences
(interviewing style, question depth, follow-up persistence, silence tolerance and two more) and,
despite the key's name, **no voice field at all**. `TaylorSetupTab.tsx` writes
`agentpool-taylor-invite-config-<slug>`, the invite chase rules. Both are per browser as well as
per slug, neither reaches the server, and therefore neither has ever reached an interview or a
reminder: a consultant configures them, a colleague opens the same project and sees defaults, and
the crew sees nothing either way. They owe the same fix - a table and a door, the shape
`project_agent_config` now has - and are recorded together because finding one and repairing it
alone leaves the other reading as deliberate.

*Correcting the design document while we are here*, because the specifics are what a reader would
act on: `docs/superpowers/specs/2026-09-04-agent-config-and-interviewer-selection-design.md` says
Avery's **voice** choice lived in `agentpool-avery-voice-config`. It did not - that key holds no
voice field, and never did. The diagnosis was right in substance and stronger than it read: there
was no voice choice *anywhere*, in `localStorage` or otherwise, so nothing was migrated out of it
and the voice is new configuration in a new table behind a new door.

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

A project not granted `HOSTED_INFERENCE` - `sensitive`, or any mode with
`force_local_inference` set - and with no local model configured for a tier raises
`LocalModelUnavailable` rather than falling back. There is no hosted fallback and no borrowing
of the other tier. `get_llm_for_agent` asks `project_permits`, never a mode name; the mode is
read only to word that refusal, and two seams that both look like the routing decision is how a
test stub lands on the wrong one.

### Configuring an agent: the id is the key, everything else is data

**Agent configuration keys on the permanent `agent_id`. The name, the image, the voice and the
synthesis model are data.** `project_agent_config` is one row per project per agent;
`resolve_agent_config(slug, agent_id)` resolves each column against `AGENT_IDENTITY`'s default,
where NULL means "use the default" and `''` does not. `agents/identity.py` separated a permanent
id from a mutable display name before any of this existed, and **this is what that separation
was for**: renaming an agent, or running an engagement where it is called something else, moves
no identity, breaks no history, and reconfigures nothing. The same rule the email seam states as
*the name is the person, the address is the role*, one axis over.

**"Who can conduct an interview" is answered in one place, and the answer is a rule rather than
a roll.** `interviewer_agent_ids()` - an identity with a `voice_id` - lives in
`agents/identity.py`, and both callers read it from there: `interviewer_selection.py` for the
crew's choice of interviewer, and `agent_config_service.is_interviewer` for the rehearsal button.
It is in `identity.py` and not in `interviewer_selection.py` because the second import is
**circular** - `interviewer_selection` already imports `resolve_agent_config` - so the design
document's sentence locating it there is one hop stale. `is_interviewer` is **derived onto the
configuration response, never stored beside the row**, as is which kind of default a face came
from: an agent given a voice becomes an interviewer with nothing to migrate, and the alternative
is a second roster in TypeScript that has to be kept in step with this one.

**The sex filter derives from the voice, never from a table.** `interviewer_selection.py`
refuses an agent-to-sex mapping in writing, because the sex is a property of the *voice* and a
project that gives Avery a female voice has said something a table in this repository would
contradict while looking authoritative. So `GET /projects/{slug}/voices` takes
`current_voice_id`, answers `voice_sex` from `ask_voice_sex`, and the picker pre-sets its filter
from that. **A default, not a lock** - and the mechanism is the file's existing `null`/`''`
distinction rather than a "has the user overridden this" flag: `null` means the consultant has
not touched the control, `''` means they cleared it and want every sex, exactly as `accent`
already used them, so default-not-lock is structural rather than a boolean free to drift. It
pre-sets only when the listing actually offers that sex, because a filter narrowing to nothing
is indistinguishable from an account with no voices, which is the worst outcome available.

**A portrait is uploaded, not typed.** `prepare_portrait` in `api/services/image_intake.py` is a
pure function over bytes - no HTTP, no filesystem, no project - so every property it holds can be
driven directly. It checks the declared content type against the format Pillow actually decodes,
fits the longest edge to 512px, honours the EXIF orientation flag **and then** rebuilds the image
from raw pixels to discard everything else. The order is not interchangeable: strip first and the
portrait renders sideways, because the rotation lives in the metadata. The stripping is a privacy
control rather than tidiness - a phone photograph carries GPS, and this image is served from the
interview page, which has **no authentication by design** - and it rebuilds rather than "saving
without EXIF", because the encoder dropping a block it was not handed is today's default and a
default is not a guarantee.

**An agent's face resolves in four steps, and the second is unique in this product.** The
project's own override wins; then the deployment's promoted default; then the portrait shipped in
the repository; then initials. `api/services/agent_default_images.py` holds that table and the
reasoning, and **level 2 is inserted in exactly one place** - `agent_defaults`, where level 3 was
already read - so the interview page and the Setup section cannot come to disagree about a face.
The promotion fires only for an agent with **no** built-in portrait and only for the first
upload: it is claimed with `INSERT OR IGNORE` on `agent_id` and the file is written **only on a
won claim**, because check-then-write here is two clients' photographs racing. It is served from
its own unauthenticated door rather than from the project it came from, or every engagement's
rendering would depend on the continued existence of whichever one uploaded first, and that
slug would appear in an unrelated client's markup. `agent_default_images` is a `system.db` table
and therefore takes **no `_SCHEMA_VERSION` bump** - the rule above, in the direction people get
backwards. Provenance is recorded rather than inferred from file timestamps, because this is the
one write in the product where **an upload on one engagement changes what a different client's
engagement displays**. All eighteen agents carry a portrait today, so the rule currently has no
subject: it is for the next agent declared, in the window between being declared and being drawn,
and its tests use a synthetic faceless one for that reason.

**Two different things in this product are called a model id, and one of them is a security
control.** `project_agent_config.model_id` is the **ElevenLabs speech synthesis model** -
`DEFAULT_TTS_MODEL_ID` in `agents/identity.py`, threaded through `synthesise(text, voice_id,
model_id)` and into the TTS cache key. The six in `_PLATFORM_TIER_SETTINGS`
(`anthropic_fast_model`, `local_deep_url` and their siblings) decide **where an engagement's
prompts are sent** and 403 a `project_admin`. The agent Setup section is therefore labelled
"Speech synthesis model", with a line disclaiming the language models on the Settings page, and
that label is load-bearing rather than cosmetic: a field called "Model" reads as the LLM to the
consultant who set the LLM one screen earlier, and the two live on the same page of the same
product at different tiers. Anything new that adds a "model" field owes the same disambiguation
in the label, not only in a docstring.

**The interviewer and the voice are stamped on the session, not re-derived from it.**
`interview_sessions.interviewer_agent_id` and the `voice_config` beside it record who conducted
the session and what they sounded like, at creation. Same rule as
`client_documents.knowledge_collection` and for the same reason - a re-derived address moves
underneath the thing it points at - but with two consequences that case could not show. With two
interviewers on the roster, a transcript that cannot say who conducted it has to **guess**. And
`interviewer_selection` defaults to `random`, so an unstamped choice would be **re-rolled**: a
participant who closes their browser and returns to the same link meets a different person, in a
different voice, under a different name. The stamp is why `_create` ignores any `voice_config` an
agent proposes in its plan, which is the structural half of retiring the prompt's locale table.

**A picker never applies a filter its own control cannot show.** `GET /projects/{slug}/voices`
unions the ElevenLabs account listing with a deliberately *unfiltered* library probe, and the
union is load-bearing rather than belt-and-braces. Measured on the live account, 5 September
2026: **Irish** is in the library and not in the account; **Scottish** is in the account and not
in the library's first page. Of the four planned engagements - Scottish, Irish, New Zealand and
Australian - **neither listing alone serves all four**. The general shape is worth more than the
measurement, which is a moving target: a listing narrowed to `british` answers `british`, so a
dropdown built from the narrowed answer offers exactly the option already selected and there is
no way back. Correct-looking, and a closed loop. The same argument repeats one layer up in the
picker, where the *sex* options come from a second unfiltered question for the identical reason.
`library_has_more` exists because the library listing is one bounded page and must never be
presented as a complete list - a picker showing five voices where ninety exist gets diagnosed as
"there are no Scottish voices", and somebody reconfigures a project that was never wrong.

**Language is the axis; accent is a narrowing (sp64).** `en` is the language; `british`,
`irish`, `american` and `new zealand` are accents *of* it, and ElevenLabs keeps them as separate
query parameters. The door used to open filtered to the project's `interview_accent`, `british`
by default, which showed **6 of 41** account voices - an axis that should broaden used as one
that narrows. So the default sits on the language (`DEFAULT_LIBRARY_LANGUAGE` in
`voice_catalogue.py`, never in TypeScript), the accent narrows nothing until asked, and the
picker carries a control for each. The account listing is deliberately **never** narrowed by
language: those are the deployment's own voices, every one added on purpose, and the parameter
is simply not passed rather than a rule to remember.

`interview_accent` is **retired**, model and type together. It had one production reader - that
default filter - and reached no interview: the accent an interview is conducted in is a property
of the voice each interviewer is given, chosen per agent and stamped on the session.

**The vocabulary probe walks several pages, and the reason is a moving target.** The library's
first unfiltered page is a *selection*, not a prefix: on 7 September `irish` was on page 0 at
04:44 and on page 1 by 15:00, same account, same query, no code change - so the accent dropdown
lost Irish while `?accent=irish` still returned 85 voices. Cumulative distinct accents that
afternoon were 22 after page 0, 46 after page 1, 54 after page 2, 64 after page 3, and
`page_size` above 100 is a 400. `LIBRARY_PROBE_PAGES` bounds the walk at four, stopping early on
`has_more`, cached for process life so the cost is per process rather than per keystroke. It is
still **partial** and says so, and the repair for a missing accent is a wider window and an
honest flag - **never naming an accent**, which would be the sixth declaration of voice facts
and wrong the first time the provider adds one.

**Two notions of an engagement's locale, and nothing reconciles them.** The picker's accent is
chosen per agent, per project, when a voice is picked - the **speaking** side. An agent's
`language` and `country_code` are also per agent per project, set in the agent Setup section,
stamped into `voice_config` at session creation, and `VoiceInterview.tsx` joins them into
`recognition.lang` for the browser's speech-to-text - the **listening** side (a line number
stood here for a sprint and was 168 lines out by sp66; name the symbol). Neither moves the
other. **So an Irish engagement given an Irish voice still listens as `en-GB`**, until somebody
separately edits Avery's `country_code`. Of the four planned engagements - Scottish, Irish, New
Zealand, Australian - this reaches the recognition side of all but the British default. sp64
narrowed the gap without closing it: retiring `interview_accent` removed the *project-level*
half of the disagreement, so both sides are now per agent per project and could in principle be
joined, but nothing joins them. Both halves are correct on their own terms, both are
operator-editable, and what is missing is the **link**; whether a chosen voice's accent should
drive the recogniser's locale is a design decision, not a defect to patch, so it is recorded
rather than fixed. It also corrects
the design document
(`docs/superpowers/specs/2026-09-04-agent-config-and-interviewer-selection-design.md`), which
says *"the gap is on the speaking side, not the listening side"*. That is now incomplete: the
listening side is correct and **unconnected**, which is a different thing from correct.

**Since sp66 the listening side is two engines, and they are told the locale in two
resolutions.** Deepgram is sent the bare `language` off the session's stamp (`en`), because
that is what its `language` parameter takes; the browser's recogniser is still given
`language-country_code` (`en-GB`). Both read the same stamped row, so they cannot disagree
about the engagement - but they are not the same string, and a future attempt to join the
accent to the recogniser has **two** consumers to satisfy rather than one.

Three smaller things about that branch, recorded so they are known rather than rediscovered.
The design document's Testing section still reads *"`always_female` never yields Avery, and
`always_male` never yields Laura"*, which the code deliberately reinterprets and improves on -
the sex follows the **configured voice**, not the agent, so a project that gives Avery a female
voice gets Avery under `always_female`
(`test_the_sex_follows_the_configured_voice_and_not_the_agent`). The spec sentence was left
standing when the file was edited; the code is the right one.
`test_resolving_the_interviewer_does_not_migrate_the_participants_database` is an **AST guard
with no behavioural half**, and its docstring says so honestly - the participant-facing
consequence is covered beside it by
`test_an_unmigrated_database_answers_the_defaults_rather_than_five_hundred`, and a `PRAGMA
user_version` assertion around a real participant request is what would close the rest.
And `AgentConfigSection.tsx`'s Image help text is still **narrower than the door accepts**:
`_assert_renderable_image` deliberately permits off-site `http`/`https`, and the text names only
the selector and a path. sp63 gave the field a `Choose image…` control and the same-origin upload
behind it, so the help is now accurate about the *ordinary* route and the text box survives as
the escape hatch - which means it is still guidance rather than the rule, and still silent about
the reach described below.

**A guard on one door is not a guard on a field.** `PUT .../agents/{agent_id}/config` refuses an
`image_url` whose scheme is not `http` or `https`. `brand_header_image_url` reaches **the same
`<img src>` on the same unauthenticated interview page**, through `PATCH /{slug}/settings`, with
**no validator of any kind**, and takes any scheme. So the *scheme* half of that check is exactly
one door wide, as the *off-site* half openly is - and the scheme half is the one a reader assumes
is closed, precisely because the paragraph beside it reasons so carefully about the other. The
interview page has **no login by design** - a participant has none, `GET /{slug}/branding/image`
and `GET /{slug}/agents/{agent_id}/image` are two of the three deliberate floor exceptions above
for exactly that reason, and the rest of the page authenticates by session token - so an
administrator-chosen off-site URL discloses every
participant's IP address, user agent and the timing of a live interview, on an engagement whose
documents and inference are otherwise on-premises. **The follow-up is a task, not a wish: the two
fields owe a shared validator**, which closes both halves - scheme and off-site - for both fields
at once. It is deliberately *not* the same-origin uploader: both fields have one already (`POST
/{slug}/branding/image` and `POST /{slug}/agents/{agent_id}/image`), and an uploader beside a
free-text box changes the ordinary route without narrowing what the write door accepts. Until it
lands, `agents/egress.py`
names both fields in `PARTICIPANT_IMAGE_EGRESS` and **nothing renders that row** -
`data_architecture()` builds the auditor's privacy page from agents and the tools they hold, and
this reach is neither, because the request is made by a *participant's browser* and not by this
deployment. Attributing it to an agent would be false, so it is a known limitation of the privacy
view rather than an oversight; surfacing it belongs with the upload path, not before it.

### Listening to a participant: the recogniser, its vocabulary, and its fallback

**Deepgram is the recogniser and the browser's is the fallback, and that has only been true
since sp66.** The door issuing the grant was written in May 2026 and called by nothing for four
months - argued in full under *Reviewing changes*, because the two defects sitting in it are a
lesson about review rather than about speech. What matters here is the shape that came out of
connecting it, which is four decisions a future change must not quietly undo.

**The model and the boost parameter are one decision, and a mismatch is silent.** `keyterm` is
Nova-3's; `keywords` is Nova-2's legacy feature with a different syntax. Send either to the
model that does not implement it and Deepgram **ignores the parameter** rather than refusing the
connection - the socket opens, transcription is perfect, and nothing is boosted, which is
indistinguishable from the vocabulary work never having been done. So `DEEPGRAM_MODEL` and
`DEEPGRAM_KEYTERM_PARAM` live beside each other in `interview_service.py`, travel to the browser
in a single `listen_params` dict, and are asserted together
(`test_the_model_and_the_boost_parameter_are_chosen_together`). **The client decides neither**,
and must not start to: a vocabulary assembled in TypeScript is a second declaration of a
server-side pairing, free to fall behind it.

**The grant JWT goes in the URL as `?access_token=`, not in `Sec-WebSocket-Protocol`.** The
documented `Sec-WebSocket-Protocol: token, <value>` form is for an API **key**; a temporary JWT
offered that way is answered 401. A browser cannot set an `Authorization` header on a handshake,
so the URL is the only route. This is worth a line for one reason: **this repository's own
`api/routers/ws.py` authenticates its JWTs by the subprotocol form**, so the nearest local
precedent is the wrong one, and anybody reaching for "how do we do WebSocket auth here?" is led
directly into the 401.

**The vocabulary comes from the project's own material, never from a list in this repository.**
`keyterms_for_project(slug)` reads two sources - `value_chain_ledger` labels where `active = 1`,
and the proper nouns extracted from the `interview_scripts` artefact - so an engagement's terms
are whatever that engagement has already declared and written. This is the rule the voice work
reached after five disagreeing declarations of the same facts, arriving one layer over, and the
failure mode here is worse than a wrong voice id: a hardcoded vocabulary is a **list of one
client's names, committed to this repository and sent up with every other client's interview**.
The extraction is positional rather than a stopword list (a capitalised run that *opens* a
sentence and is one word long is discarded, which is what removes "How" and "Please" without
anybody listing them), capped at `MAX_KEYTERMS = 100`, registry labels first because declared
vocabulary should outrank inferred. The cost is stated where it is paid: a proper noun that only
ever opens a sentence is missed, which is the safe direction - a missing term costs one word's
accuracy, a junk term costs a place on the cap.

**The fallback is behaviour, not a `catch` block, and four cases are deliberately not the same
case.** No Deepgram key, no streaming support, or a socket that will not open: **silent** fall
back to the browser's recogniser, and after two consecutive failures the client stops asking, so
a deployment without Deepgram does not pay a failed round trip before every answer. A socket
that **drops mid-answer**: what was already heard is kept, the browser's recogniser picks up
*the same answer*, and the participant is told - both halves, because neither is enough alone.
Microphone access lost: a plain notice naming what to do. And **nothing in this browser can
listen at all**: said plainly, in an `alert` live region that does not clear itself, because the
sentence it carries is *"nothing you say is being recorded"* and a notice that times out is gone
before somebody mid-sentence looks up. That last case is a change in behaviour rather than a
new message - before sp66 an interview in a browser with no `SpeechRecognition` ran to the end
recording nothing and telling nobody.

Two properties of that fallback are easy to remove by accident. `onDropped` is **at most once**,
guarded in `deepgram.ts` rather than in the page, because "an abnormal post-open failure fires
`error` then `close`" is knowledge about WebSockets and one file should hold it - without the
guard a second recogniser starts on one microphone and the first is orphaned, holding the
microphone for the rest of the interview. And `stop()` **waits for the flush**, bounded at
`FLUSH_TIMEOUT_MS = 1500`: closing the socket in the same tick discarded the tail of any answer
ended by tapping "Done speaking", which was a regression against the path being replaced -
`recognition.stop()` delivers a pending `onresult` before `onend`, so the browser engine never
lost it. The deadline is a ceiling and not a cost; the ordinary wait is one round trip.

**Two things travel to Deepgram, not one**, and `PARTICIPANT_SPEECH_EGRESS` in `agents/egress.py`
names both - the participant's audio, and this engagement's vocabulary, which is client material
and is *not* audio. That is the sp62 ElevenLabs correction arriving again and it is argued under
*Egress is granted, never assumed*; the point to carry here is that the vocabulary is the half a
row naming only the audio would silently exclude.

**Nothing on this path has ever spoken to the real Deepgram.** The `access_token`-in-URL form,
the `keyterm` spelling and the webm/opus stream are all read off documentation, so every test
encodes a *reading of the docs* rather than the provider's behaviour, and a wrong reading opens a
socket that transcribes and boosts nothing. This is the same honesty the ElevenLabs add-voice
door is recorded with under *Known issues* - "never confirmed against the real provider" - and
the mitigation is the fallback: a wrong guess degrades to the behaviour every interview before
sp66 had, rather than losing an interview. **Treat the first live interview as the test.**

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

### Reviewing a collection: the unit of review is the unit of regeneration

**An agent output that is a collection of items needs per-item review state before it needs a
review surface.** A reviewer who can only send the whole artefact back makes the agent rewrite
everything, and then cannot tell what changed - which is why the whole-artefact loop was built,
works, and went unused. Maya's is used because a script *is* a row: SC-014 went back with a
note, run 37 regenerated that one script, and the other 85 came back byte-identical. That is
what a new output type is measured against, and it is a question about the **table**, not about
the dialog.

Three ledgers now, one shape, each maintained by the write path rather than by its agent - for
the reason run 32 gives above, that an artefact the agent must remember to write is a guarantee
which holds only when the agent finishes:

| Ledger | Item id | Registered by | Owner |
|---|---|---|---|
| `interview_script_ledger` | `script_id` | `register_scripts_sync` | Maya |
| `value_chain_ledger` | `node_id` | `register_nodes_sync`, from **both** registry doors | Alex |
| `value_lever_ledger` | `lever_id` | `register_levers_sync` | Morgan |

All three register `ON CONFLICT(<id>) DO NOTHING` and none of them deletes, so "may grow, may
retire, may never redefine or forget" is a property of the table rather than an instruction in
a prompt.

**The id is permanent and the label is not.** `value_levers` had no id at all: its only
identifying field was `lever`, a full sentence, and Morgan rewords every one of them on every
run - v4 to v5 reworded all ten while v3 to v4 merely reordered them - so review state keyed on
the title, or on the position, matches nothing by the time the reviewer reads the answer. sp60
assigned `LV-001`.. once to the existing ten and **wrote them back into the artefact**, which is
the half that makes them visible to the one agent who has to preserve them; an id is never
re-derived from position or title. `ITEM_IDENTITY` in `agents/tools/ownership.py` declares, per
output type, whether it is a collection and which field identifies an item, so the question is
answered when an agent is built rather than when somebody wants to review its output.

**`item_reviews` is one event table with an `item_kind`, not one table per ledger.** A node id
and a lever id are different namespaces and nothing stops a project holding the same string in
both, so the discriminator is stored rather than inferred from the shape of the id - and two
tables would have been two copies of one recorder. `record_item_review`
(`api/services/item_review_service.py`) serves both over `ITEM_LEDGERS`, which is the whole of
the difference between them. Its vocabulary is three where the script ledger's is four:
`edited` is **refused** rather than merely unoffered, because levers are review-only by decision
and the value chain model has its own editor, so a decision no surface can produce would arrive
in `review_status` as a state the reviewer could never explain.

**The recorder takes no version argument.** `record_script_review` takes `at_version` and its
single door fills it correctly; there are two doors here, so the recorder reads `last_version`
off the row it has already selected and stamps from that - there is no parameter for a door to
forget, and `test_the_recorder_takes_no_version_argument` asserts the signature so it cannot be
reintroduced quietly. That is `merge_project_config`'s rule under *Database conventions*
arriving a second time: when a signature obliges every caller to restate state it does not own,
the signature is the defect. The stamp is written on **every** decision rather than only on
`changes_requested`, because the staleness a reviewer reads - "changed since v3 to v7" - is the
same number.

**The failure direction was chosen, and it is the inverse of the migration trap above.**
`nodes_awaiting_regeneration` spells its staleness guard `COALESCE(reviewed_at_version,
last_version, 0) >= COALESCE(last_version, 0)`, deliberately *not* the way
`scripts_awaiting_regeneration` spells the same idea, so a NULL stamp falls through to "still
awaiting" rather than to "excluded". A recorder that set `review_status` and forgot the stamp
therefore reaches the agent on **every** run until something clears it, rather than on **none**
of them, silently. Both are defects; only one announces itself in the prompt.

**A send-back is scoped by ledger ownership, not by crew.** `discovery_mapping` holds two
agents, so a crew-scoped block would hand Alex Morgan's lever notes and Morgan Alex's node
notes - a failure invisible from outside, because the agent who should have been told is told
and nothing anywhere records that the other one was as well. `_pending_discovery_revisions` in
`run_service.py` asks which agent owns which ledger, which also means "`discovery_mapping`
only" falls out of ownership rather than becoming a third list beside `_CREW_AGENT_NAMES` and
`OUTPUT_OWNERS`. `_fetch_regeneration_requests` scopes on the crew and is right to:
`assessment_design` holds one agent, so there the two are the same question.

**Alex's clearing is weaker than Maya's, and the surface says so rather than implying
otherwise.** A send-back clears on evidence - `register_nodes_sync` stamping `last_version`
past the version the reviewer read - and nothing closes it out. Maya regenerates only what was
returned to her, so her stamps move on exactly what she rewrote; Alex rebuilds the whole chain
on every run (one run re-emitted 59 labels and not one was a redefinition), so **any** run of
his clears a send-back whether or not he addressed the note. `DiscoveryReviewExtra.tsx` says
so per ledger section, keyed by `data-testid="clearing-note-{kind}"`, because a note on one
section does not explain the other.

**What legitimately moves on a single-item send-back.** The byte-identical claim is *within the
ledger* - `tests/test_node_and_lever_review_loop.py` sends one node back through the door and
hashes all 89 rows either side of it. `value_chain_tree` and `value_chain_summary` are derived
from the model and will legitimately be rewritten end to end by a one-node change. Say which
artefacts are expected to move before the first reviewer diffs a run, or a correct regeneration
reads as a leak.

### One mechanism: a correction becomes a proposal, and the approval carries a scope

**There is one way a reviewer's correction becomes standing behaviour, and it has four steps.**
The correction improves the output in hand; the general rule behind it is *proposed*; a human
approves it; and the approval carries a **scope**. `project` is the default and `global` is the
deliberate act, because widening a rule to engagements the reviewer has never seen should be
something they chose rather than something they got by clicking through.

There used to be two ways, and only one of them was designed. `agent_skill_notes` took a
reviewer's sentence, had a model distil it, and prepended the result to every task of every crew
on every engagement - no queue, no approval, no scope. **Patrick's account, 8 September: there
was never any intent for a notes mechanism.** Feedback was always meant to improve the output in
hand and then be *evaluated* as a project-level or global skill for that agent through the skills
review. sp65 deleted it - the table's `CREATE`, `create_skill_note`, `_note_may_travel`, the
router, its API client and the rejection-path box that fed it - and nothing was lost. The
immediate half already reached the agent through `_fetch_change_requests`, which
`run_service.py` said in its own comment throughout; the standing half is what a scoped,
approved skill does properly.

**The worked example is the whole design in one case, and it belongs in the product's copy
rather than only here.** A correction on one engagement of *"$350m CapEx allocation"* to
*"renewals CapEx allocation"* yields a rule for Maya - *do not include specific investment
figures; the number may change and not every interviewee knows the full amount, so refer to
investments by their purpose*. That is **global**: it is about how to write an instrument, and
it is true of every client. The same box on the same day might instead produce *"this client
calls it the renewals programme, not the CapEx allocation"*, which is **project**, and would be
wrong somewhere else. Same reviewer, same control, different answers. **The scope cannot be
derived from the text**, which is why a human chooses it and why no default can be right for
both.

**sp61's four Critical findings were not four leaks. They were one absence seen from four
directions** - material with no scope defaulting to the widest scope. Each was patched where it
surfaced and each patch was correct, but the class stayed open, because nothing in the system
could say where a rule applied and so the answer was always "everywhere". `skills.scope` is what
closes the class; the four guards were the symptom being treated. **When several findings in one
sprint share a shape, the shape is the finding** - and this file recorded the four separately
for a sprint, which is how the shape stayed unnamed.

`skills.scope` is `project` or `global`, NOT NULL under a `CHECK`, beside the `source_project`
that already recorded where a rule came *from*. Provenance and reach are two questions, and this
file conflated them until sp65 because there had only ever been one answer.
`_skill_applies_here` in `run_service.py` is the filter and `_fetch_skill_notes` applies it: a
`global` skill reaches every engagement, a `project` one reaches only the engagement its own
`source_project` names, and a row that names neither reaches nothing - the safe direction, since
an unattributable rule cannot be shown to belong to the engagement being run. `PATCH
/admin/skills/{id}` is where the reviewer decides, from the "Where this rule applies" radios on
`AdminSkills.tsx`, and the Approve button reads *Approve everywhere* or *Approve for this
engagement* so its label names what it will do. **`scope` absent from the PATCH body means
"leave the row alone", not `project`** - the two are the same today only because nothing else
writes the column, and the difference is what lets a reviewer *demote* a global rule.

**The existing 53 are `global`.** Patrick's decision, 8 September, and it is the honest reading
of what their authors intended when global was the only thing a skill could be. Said plainly:
**this affirms 53 rules as universal without anybody re-reading them.** They are demotable one
at a time by a reviewer who finds one that was really about a single engagement, and the
migration does not make that judgement for them. The route is the library tab of
`AdminSkills.tsx`: every approved card carries a badge saying where the rule applies - *Applies
everywhere*, or *Applies to `<slug>`* naming the engagement - and Edit opens the same "Where
this rule applies" control the queue uses, with the consequence sentence bound to **Save**.
Until sp65's review that action existed only as a hand-made `PATCH` while two documents
described it as a thing a reviewer does.

The backfill sits *inside* the add-column branch in `init_system_db` so it can never run twice,
and it is a different fact from the column's default. **Two different defaults, and they are
asserted separately** - stated precisely here because this file previously said something false
about them. A column declared `DEFAULT 'global'` would silently make every future raw insert
universal, and `test_the_existing_skills_are_global_and_a_new_one_is_not` does *not* catch that:
it writes its new row through `insert_skill`, so what it pins is that function's **Python
parameter default**. sp65's review flipped the DDL default and ran the whole backend suite
green. `test_a_raw_insert_that_omits_the_scope_still_gets_the_narrow_one` is the assertion that
closes it, parametrised over both pieces of DDL - the `CREATE TABLE` a fresh deployment gets and
the `ALTER TABLE` every existing one gets - because they are written out independently and are
free to disagree. *A guard's reach must be established, not described*, and that rule has now
caught a guard on this very column.

**A narrow default bites the one writer that legitimately means "everywhere".** The baseline
seed approves its own rows and gives them no `source_project`, so at `scope='project'` every one
of `BASELINE_SKILLS` would have reached no engagement, and `POST /admin/skills/seed?force=true`
would have rebuilt the factory library **dead** - every row present, every row correct-looking,
none of them injected anywhere. It passes `scope="global"` explicitly for that reason, and it is
the only writer that names a scope; everything else files `pending` and lets the reviewer
decide. When a default is narrowed for safety, the writer to go and read is the one whose whole
purpose is the other value.

A number worth not quoting from memory: the live library holds **53** rows, 43 of them `source =
'baseline'`, while `BASELINE_SKILLS` holds **42** today. The list has moved since the deployment
was seeded, which is exactly the drift `force=true`'s own comment warns about - it would retire
the row the list no longer carries. The 53 are what the migration made global; 42 is what a
re-seed would write.

**An agent that can be sent work back proposes the general rule behind the correction, not the
correction.** A requirement about every agent rather than a step in one agent's task, so the
mechanism is a tool: `SkillProposalTool` (`agents/tools/skill_proposal.py`) is registered for all
seventeen agents `_CREW_AGENT_NAMES` dispatches, and `_SKILL_PROPOSAL_INSTRUCTION` in
`run_service.py` is injected on a send-back and on nothing else - once, however many of the two
revision blocks fired, so an ordinary run pays nothing.

The worked pair is in the instruction because the distinction *is* the requirement. The note left
on interview script SC-014 was *"'not a performance review' appears twice, and the framing repeats
the welcome"*; the rule behind it is *"the welcome carries privacy and tone, the framing carries
the interview's purpose"*. The first is about one script and dies with it. The second is about
every script Maya will ever write, on every engagement - and before this loop existed, 53 skills
were assigned to agents and injected into every run with **not one of them from a review**. The
correction was made, well, and the lesson evaporated.

PAM is excluded on both halves of the rule: she orchestrates rather than producing a reviewable
artefact, and she appears in no `_CREW_AGENT_NAMES` entry, so a proposal of hers would be queued,
approvable, and would still reach no prompt. `test_pam_does_not_hold_it` keeps that a decision
rather than an omission.

Four properties of the queue, and the first is the whole safety argument:

**Nothing proposed reaches a prompt.** `propose_skill` writes `status='pending'`;
`_fetch_skill_notes` selects `status='approved'`. That is the whole safety argument for letting an
agent propose freely, and it is asserted against **what reaches the prompt**, never against what
the table holds.

**A near-duplicate increments `occurrences` and accumulates provenance rather than inserting a
second row.** A match is not noise to discard - it is the second sighting, the recurrence a
periodic sweep over review history would have existed to find, arriving without waiting for one.
So recurrence is the evidence a reviewer approves from: `skill_occurrences` holds one row per
sighting including the first, which makes "how many, and where" a query rather than a blob, and
`fetch_skills` orders the queue `occurrences DESC, created_at DESC, id DESC` with no parameter, so
there is one answer and nothing for two callers to spell differently. `rejected` is excluded from
the candidates a proposal is compared against - a human has already refused that rule, and
incrementing it files the recurrence where the queue does not look. **The third sort key is not
decoration**: `created_at` is whole seconds, so two proposals written in the same second tied on
both of the others and the order fell to whatever SQLite happened to return, which a reviewer
experiences as a queue that reshuffles on reload.

**Approving a `global` skill changes that agent's behaviour on every engagement**, from its next
run, including engagements the reviewer has never seen; approving a `project` one changes it on
the engagement the rule came from and nowhere else. It is the most consequential button on
`AdminSkills.tsx`, so the page says which of the two it is about to do, bound to the button by
`aria-describedby` rather than left beside it. "Approving changes that agent's behaviour on
every engagement" was true of every approval until a rule had a scope, and is now true of one of
the two.

**`skills` is in `system.db`, so none of this took a `_SCHEMA_VERSION` bump.** The rule is stated
under *Database conventions* and this is the direction people get backwards: `occurrences`,
`proposed_by_agent`, `source_ref` and the `skill_occurrences` table all go into `init_system_db`
as `CREATE TABLE IF NOT EXISTS` plus `ALTER`, which runs on every system connection and is
therefore already enough. Bumping the constant would re-run every *project* migration on every
deployment for a table in a database it does not govern.

**Two doors onto the skills library, and they route differently** - argued in full under *Routing
a call outside a crew*, and repeated here only as far as the decision. `find_duplicate_skill` asks
`project_completion(slug, "fast", ...)`, so an agent's proposal on a sensitive engagement is
compared on that project's own model and nothing leaves; the administrator's global skills page
carries no project and stays hosted Haiku. The blanket exemption that used to cover both was
justified on the library being global, carrying no slug, and holding reviewer feedback rather than
client material - and `propose_skill` has a slug and carries an agent's sentence about a named
engagement.

**The generic review door's `intent='skill'` is routed now, and the sentence it replaces was
wrong in both halves.** `PATCH /{slug}/reviews/{id}` accepts an `intent` of `change_request`,
`correction` or `skill`. This file used to say the third was *captured and not routed* because
nothing read `kind` - and `kind` **is** read: `fetch_open_change_requests` selects
`kind='change_request'` alone, so a `'skill'` row was written to `output_changes`, counted in the
reviewer's change count, shown in the change log, and delivered to nothing. Captured, counted,
and routed nowhere is a different claim from captured and unread, and it is the worse one,
because the reviewer was shown a number that said their rule had landed. It now calls
`propose_skill` with the reviewer's text, the slug from the path and the agent whose output was
reviewed, and files `pending` for the queue this section describes. The `output_changes` row is
still written unchanged: the change log is the record of what a reviewer asked of an output, and
a rule on the queue is not that record. `intent='change_request'` is untouched and still reaches
the agent through `_fetch_change_requests` - the half a careless routing change breaks in
silence, so it is asserted on what that function returns rather than on the request being
accepted.

**A side effect must not veto the thing it is a side effect of.** A proposal that cannot be
filed - a locked system database, a model that will not answer, an agent id `_SNAKE_TO_DISPLAY`
has no entry for - does **not** fail the PATCH. That door is what releases a paused crew:
`HumanInputTool` polls `human_reviews` for up to twenty-four hours and this write is what ends
the wait, so refusing it to protect a suggestion would hold the crew shut. `_propose_from_review`
in `api/routers/reviews.py` logs loudly and returns the outcome in `skill_proposal`, the same
contract `SkillProposalTool` states for itself one door over. **The cost is on the record**:
nothing in the UI reads `skill_proposal` yet, so a reviewer whose rule was not filed is not told.

The rejection path lost its second box with the notes mechanism - *"What should Maya do
differently next time?"* was the only caller of the notes door - and that question is asked on
Request revision instead. A reviewer who rejects outright records a reason and no rule.

**Adding the column falsified two exemptions that were justified on "approved means
everywhere".** Both were pre-existing code the branch did not otherwise touch, both were
diagnosed correctly in this file before they were repaired, and both were then *left* that way
for a whole branch until sp65's review reproduced them. **They are now closed, and the repair
is one substitution made twice:**

| Exemption | What justified it | What the scope column did to it |
|---|---|---|
| `list_skills` returned every `approved` row to any login | "an approved skill is that agent's instruction everywhere, which is what makes it not one client's material" | an approved `project`-scoped rule **is** one client's material, and `_derive_skill_name` puts the first five words of the rule in the name. It now answers a non-sysadmin `approved` **and** `scope='global'`. |
| `_candidates_that_may_travel` exempted every `approved` candidate from the egress test | "it is already injected into that agent's prompt on every engagement" | a `sensitive` engagement's approved `project`-scoped rule travelled to hosted Haiku the moment a `standard` engagement proposed for the same agent. It now exempts `scope='global'`, and the status is not read at all. |

**One sentence covers both: what may be seen follows what may travel, and both follow the
scope.** The status is now irrelevant to either question - a *pending* global proposal is
exempt from the egress test, asserted deliberately, because the test is "what makes this
material already shared" and a scope is the answer to it while a status is not.

This is this file's own rule arriving again - **an exemption is a claim about content, and the
file it lives in is not** - and the first time it has arrived because a *new column* changed
what the content could be. When a change gives a row a way to mean something narrower, every
exemption phrased "this kind of row is global" is a caller of it, and `status='approved'` was
the spelling of "global" in both places. The second lesson is cheaper to state than it was to
learn: **diagnosing an exemption in this file is not closing it.** Both entries above were
written as prose, accurately, a week before either line of code changed.

Both exemptions are now allow-lists on the exact string `global` rather than tests for "not
project", so a third scope value has to prove itself rather than inherit the exemption by not
being named - and that shape is asserted, parametrised over scope values that do not exist.

The design's related decision - **an approved `project`-scoped skill is not offered as a
deduplication candidate to another project** - is **not implemented**. The plan expected it to
fall out of the injection filter and it does not: `_rules_already_held` reads `_DEDUP_STATUSES`
and never looks at `scope`. *Pending* proposals are deliberately still offered across
engagements, and that half is right - two engagements independently proposing the same rule is
exactly the evidence that it is global, and a pending proposal is not yet scoped.

### Clusters, and the edges between crews

A **cluster** is one orchestrator and the crews it owns. There is one - `pmo`, orchestrated by
`pam` - and the concept exists so that a second PMO is a data addition rather than a rewrite.
Membership is declared once, on the crew, as `Charter.cluster`; `agents/clusters.py` declares only
the cluster's id, label, orchestrator and note. `agents/graph.py` inverts the first into
`ClusterNode.crew_ids` and refuses five disagreements, including an orchestrator that runs inside
one of its own crews and one that can start none of them - the last derived from the tool it holds
against the triggers its crews declare, so `orchestrator` is checked rather than believed.

**Edges between crews are derived, never declared.** `CREW_DEPENDENCIES` says a crew waits on
another; it does not say whether anything travels. `Graph.edges` meets each crew's writes
(`OUTPUT_OWNERS` inverted) with the next crew's reads (`AGENT_READS`, artefacts only) and
classifies:

| Kind | Meaning | Count today |
|------|---------|-------------|
| `information` | Waits on it, and reads an artefact it wrote | 6 |
| `sequencing` | Waits on it, and reads **nothing** it wrote - ordering only | 3 |
| `inherited` | Reads an artefact it wrote without waiting on it directly | 12 |

The `sequencing` three (`assessment_design -> stakeholder_management`,
`stakeholder_management -> discovery_interviews`, `requirements -> delivery`) are why the edges
are derived at all: an unlabelled arrow would present them as the same relationship as the six
that hand material over.

The radial view on `/data-architecture/{slug}` is drawn from these two - `ui/src/components/
agentGraphLayout.ts` is trigonometry over `ClusterNode.crew_ids`, with **no force simulation and
no layout library**, because the page is shown to clients and auditors and "the third crew
clockwise" must mean the same thing tomorrow. Nothing the picture shows is absent from the tables
below it.

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

The slug is required, not defaulted. `project_llm_mode("")` used to find no database and
answer `"standard"`, so a forgotten slug was a silent hosted call - which is exactly how the
test interview dialog sent a sensitive project's answers to Anthropic while holding the slug
in its props and discarding it. A blank or whitespace-only slug now **raises**, and the other
two branches are untouched and asserted apart from it: a database that does not exist still
answers `"standard"` (a genuinely absent project has no secrets, and `create_project` resolves
a mode inside the window between `get_connection` and `insert_project`), and a database that
exists but cannot be read still fails closed to `"sensitive"`, uncached. Three branches, not
two - a later tidy-up that flattens them re-opens whichever one it merges away.

**What is covered, precisely:**

Read the column as "routed by what the *project* resolves to" - `llm_mode` narrowed by
`force_local_inference`, which is the same answer wherever the two agree and the only one any
of these paths asks for.

| Path | Routed by `llm_mode`? |
|------|----------------------|
| Every crew agent, including PAM | Yes - `get_llm_for_agent` |
| Live interview elaboration press (`interview_service._press_call`) | Yes |
| Test-interview press (`POST /interviews/test/elaboration-press`) | Yes - slug required, 422 without it |
| Agent Chat (`run_agent_chat`) | Yes, text and retrieved chunks |
| Agent Chat with an **image** attached, sensitive project | **Refused** (503) - image blocks have no chat-completions equivalent here, and dropping or sending them are both wrong |
| An agent's skill proposal (`skills_service.propose_skill` -> `find_duplicate_skill`) | Yes - `project_completion(source_project, "fast", ...)`, slug required, raises without it |
| The global skills library door (`check_specificity`, `extract_skill`, `extract_skills_many`) | **No** - always hosted Haiku |

**Two doors onto this table family now, and one of them is still the hosted gap.** That row used
to say "skills library - no", one row for one file, and it was true until an agent could reach
the library from inside a run. It was still wrong afterwards, for a second reason: it also
covered `api/routers/skill_notes.py`, which distilled a reviewer's *verbatim sentence about one
engagement* and whose one caller held the slug in its props and discarded it - the same "held the
slug and discarded it" defect this file already records on the test-interview press. sp61 routed
that door; sp65 deleted it with the mechanism behind it, which is why the list is two and not
three. Three separate paths have left that one justification in three sprints, and it was
rewritten once each time: **when a justification stops covering one member of a list, re-read it
against the others rather than editing the one member.**

The remaining gap is the **administrator's skills page**, and it is deliberate rather than an
oversight, on two facts that are both about *that door*: the library is global across
engagements, its endpoints carry no slug, and the text is reviewer feedback about an agent's
behaviour rather than client material. A project-scoped skills library is the fix if that ever
stops being acceptable - not a default slug.

**Both facts stopped being true of the agent's door, which is why it moved.** `propose_skill`
takes the slug - it is the provenance the queue sorts on - so a mode was available to route by;
and what it compares is not reviewer feedback but the agent's own generalisation from a
correction made on a named engagement, free to name the client, its people or its systems in
the course of stating the rule. The exemption survived the change that invalidated it because
it had been written about the door rather than about the data. **When a path gains a slug, or
starts carrying something a person wrote about one client, re-read the exemption it is sitting
under** - an exemption is a claim about content, and the file it lives in is not.

`find_duplicate_skill` takes the slug as its **first positional argument**, and
`propose_skill` raises on a blank one rather than treating it as "no project". An optional
`slug=None` falling back to the hosted branch is the shape this rule exists to forbid.

### Egress is granted, never assumed

`api/services/deployment_modes.py` declares, per mode, what it may do with a project's
material - `CLOUD_VECTOR_STORE`, `HOSTED_INFERENCE` - and a site asks whether the capability is
granted rather than comparing a mode name. **Two questions, not one:** `permits(mode,
capability)` is what the mode *declares*; `project_permits(slug, capability)` is what the
project *resolves to*, and a site about to move material asks the second. Three routing sites
ask it - the Chroma client, the crew LLM, the non-crew completion - and the fourth, the
auditor-facing privacy view, reports rather than routes, so it asks `project_grants(slug)` and
shows the difference from `granted_to(mode)` as what the project has narrowed. All four used to
ask `mode == "sensitive"` and hand everything else the off-premises branch. That shape is safe
for exactly as long as nobody adds a mode, `api/models.py` already declared three, and a
fourth - sovereign: hosted models, a local vector store - is planned. **A mode absent from the table is granted
nothing**, warned about rather than raised (matching `project_llm_mode`'s neighbouring
fail-closed-and-warn), so the cost of forgetting is a project that will not run rather than a
project that leaks. The miss falls towards containment; the fallback this branch deleted -
`ChromaQueryTool`'s `.get(collection, f"sector_{self.sector}")` - fell towards disclosure. A
default is not a defect; a default pointing the wrong way is.

Adding a mode means a row here **and** a value in *both* `Literal`s in `api/models.py`
(`ProjectCreate` and `ProjectSettings`, which is one more than anybody remembers), and the
declaration is held equal to those and to five frontend option lists - including
`Settings.tsx`, the door that changes an *existing* project's mode. The frontend lists are
extracted structurally rather than by searching for the three known names, because a
name-keyed search catches a *missing* mode and is blind to an *extra* one, which is the
dangerous direction: selectable by a user, unknown to the server.

**A mode is not the last word.** `projects.force_local_inference` removes `HOSTED_INFERENCE`
from whatever the mode grants, so a `standard` engagement can measure local model performance
while its documents stay in Chroma Cloud. **It does not move the vector store** - that is the
whole reason it exists rather than a fourth mode, since `sensitive` moves inference and vectors
together and only one of them was wanted. Narrowing is **set difference**, and there is
deliberately no table anywhere of capabilities an override *adds*, so "a sensitive project can
never be forced hosted" holds by construction rather than by a rule, whatever overrides land
later. Asserted rather than trusted, over every declared mode against both states of the flag:
`tests/test_local_inference_override.py::test_no_project_ever_resolves_to_more_than_its_mode_declares`.
A union in `project_grants` is the single line a reviewer should refuse.

**Two reads whose failures mean different things must not share a query.** Reading the flag in
the same `SELECT` as `llm_mode` looks obviously better and is wrong: on a `projects` table
without the column the statement raises, `project_llm_mode`'s fail-closed `except` catches it,
and every such project reports **sensitive** - a missing column indistinguishable from a
security posture. Both reads fail closed and they fail closed in *different directions* (the
mode to `sensitive`, the flag to `True`, each the narrowing answer for its own question); only
separate queries can say so. The flag asks `PRAGMA table_info` rather than matching sqlite's
"no such column" message, so the absent-column branch is structural.

**Enumerating the egress sites takes two sweeps, not one.** `permits(` / `project_permits(` /
`granted_to(` finds every site that *asks*, and is blind by construction to a site that decides
egress **without** asking. A second sweep for direct construction - `CloudClient`, `HttpClient`,
`AsyncAnthropic`, `LLM(` - is what finds those, and it is why `skills_service.py` is *known* to
be the one remaining hosted inference path rather than assumed to be. Sweep for the question and
for the mechanism, or the answer only ever describes the sites already doing it properly.
`skills_service.py` still answers that second sweep, and now needs the first one too: it builds
`AsyncAnthropic` for its global door and asks `project_completion` for the agent's.

**Routing a call by one project says nothing about the other projects' material inside it.**
The seam takes a slug and sends the payload where that slug's grants allow, which is the right
question asked of the wrong scope the moment a payload carries anything belonging to a second
engagement. `find_duplicate_skill` was exactly that: routed correctly on the proposing
project, and carrying every *other* engagement's pending rules as the candidates to compare
against - so a `sensitive` engagement's rule went to hosted Haiku whenever any `standard` one
proposed a rule for the same agent. Nothing was wrong with the routing; the payload had a
second owner and only one of them was asked.

So when a payload is assembled from more than one project, **ask `project_permits` of each
contributor's own slug, not of the caller's**. `_candidates_that_may_travel` in
`skills_service.py` is the shape: if the call is not leaving the deployment nothing is
withheld, and if it is, each contribution must show its own grant. Note which way the two
halves fall - an artefact that applies to every engagement travels freely, and anything that
cannot be attributed to an engagement is withheld, because "may this travel" has no answer
without a project to ask about.

**The first of those halves had a premise the code stopped establishing, and the gap between
noticing and repairing it is the thing to take from this entry.** The exemption was keyed on
`status='approved'`, which *meant* "applies everywhere" until `skills.scope` existed. For the
length of a branch it did not, so an approved `project`-scoped rule from a `sensitive`
engagement travelled with a comparison routed on a `standard` one - written up accurately here,
in two places, and not fixed in either. It now reads `scope='global'`, which is what the
exemption was always trying to say, and the status is not consulted at all.

**A prompt is a payload too, and it is the one this codebase kept forgetting.**
`_fetch_skill_notes` in `run_service.py` had the same defect in a worse form: it took no slug
at all, so it could not ask, and it prepended every stored `agent_skill_notes` row to every
task of every crew on every project - a note being a model's distillation of a reviewer's
sentence about one named engagement, injected as *instruction*, with no approval step. sp61 gave
it the slug `build_and_run_crew` already held; sp65 deleted the notes half outright, and the
slug it was handed is what `_skill_applies_here` now reads the scope against. **A function that
assembles prompt text and takes no slug cannot be asked the question**, which is why the
signature is the first thing to look at - and the repair that made the signature right outlived
the mechanism that forced it.

That paragraph used to end on a gap: notes had no approval gate of the kind `skills` has, and
that was on the record rather than accepted. It is closed, and by **removal** rather than by the
gate it asked for - a note could not have been given one without becoming a skill, which is what
this branch concluded and acted on. Two things that survive, so the rule is not mistaken for
more than it is. **Egress is not scope**: two engagements that both permit hosted inference
still share whatever the *scope* rule lets them, and a wholly local deployment shares everything
internally, so `_candidates_that_may_travel` answers "may this leave the premises" and
`_skill_applies_here` answers "does this rule apply here" - neither substitutes for the other,
and the same row can pass one and fail the other. And a prompt asking a model to behave -
`_EXTRACT_SYSTEM`'s "no client-specific details" clause, which its sibling `extract_skill` still
carries - is a second line of defence, never the guarantee.

**The boundary, stated honestly.** For those two declared capabilities, nothing leaves a
`sensitive` deployment. Five paths still send material off-premises with **no mode question
asked at all** - the global skills library door, `TavilySearchTool`, `WebFetchTool`,
Deepgram/ElevenLabs, and Resend - every one pre-existing, none widened here, and each documented
in this file or declared in `agents/egress.py` (where an ungated reach resolves to the same
`Destination` in both modes, written out rather than left implicit, because that sameness *is*
the finding). "Nothing escapes secure mode" is true of the two capabilities and of nothing wider.

**That disjunction was doing more work than it looked, and sp66 found out how.** It reads "in
this file **or** declared in `agents/egress.py`", and for Deepgram only the first arm was ever
true - `TOOL_EGRESS` is keyed on tool class names and Deepgram is not a tool, so
`agents/egress.py` held no reference to it at all. The prose arm was worse than absent: the
rendered privacy page said *"interview audio is streamed for transcription with content
retention disabled"*, which was an **undertaking about a path nothing had ever called**. So a
reader checking the boundary found a sentence, believed the path was surveyed, and the path did
not exist. Closed in sp66 - `PARTICIPANT_SPEECH_EGRESS` is declared, on its own
`Reach.PARTICIPANT_TRANSCRIPTION`, following the `PARTICIPANT_IMAGE_EGRESS` precedent because
the request is made by the participant's browser rather than by this deployment - and it names
**two** things travelling where the prose named one: the audio, and this engagement's
vocabulary, its value chain labels and the proper nouns from its interview scripts. That second
half is client material and is not audio, which is exactly the correction sp62 made to the
ElevenLabs row two paragraphs down; a row naming one shape reads as an assurance about all of
them. **ElevenLabs is still prose-only**, so the disjunction still has one member leaning on its
weaker arm - when that is closed, the sentence above can lose the "or". `EGRESS_GRANTS` is
deliberately not extended for either: a capability nothing consults reads as a gate that is not
there.

**Two of those five are reachable from inside a crew run**, and knowing which two is the
claim worth keeping true. `TOOL_EGRESS` in `agents/egress.py` is the table that says so:
`value_chain_mapper` holds `TavilySearchTool` and `WebFetchTool`, `value_lever_analyst` holds
`TavilySearchTool`. So an agent reaching an ungated path is not unprecedented, and a reader
told otherwise would mis-weigh the next one.

**No ungated *inference* path is reachable from inside a crew run**, which is the narrower
claim and the interesting one. `SkillProposalTool` was briefly the exception - the first tool
an agent held that made a second **model** call of its own, declared honestly in
`agents/egress.py` as `Reach.UNGATED_INFERENCE` and routed properly a commit later, which is
how the member came and went. If a sixth ungated path is ever added, ask whether an agent can
reach it before asking anything else: an ungated door an administrator opens and an ungated
door an agent can open on a client's behalf are not the same finding.

The wider version of that sentence shipped here and was false on the day it was written, in
the section about not writing false sentences, citing the table that contradicted it. A claim
of the form "none of these is X" is worth checking against the declaration rather than against
memory - which for this one is a three-line read of `TOOL_EGRESS`.

The ElevenLabs entry covers **two shapes of request now, not one.** It was interview text
going to `/v1/text-to-speech`; sp62 added the voice listings and the add-a-voice write
(`api/services/voice_catalogue.py`), which carry an accent, a sex, a search term and a name.
Widening what a listed path sends is worth a line even when the new content is innocuous - a
row that names one shape reads as an assurance about all of them, and the next reader checking
"what leaves a sensitive engagement?" would have been told something untrue about a path they
had already accepted.

**The guard, and its blind spot.** `tests/test_deployment_modes.py` inventories every literal
mode name under `api/`, `agents/` and `scripts/`, attributed to `path::qualname` and
**counted**, held equal to a ten-entry table in which each entry carries its reason. Syntax
stops mattering - a comparison, a tuple membership, a `match` case, a dict subscript and a
default argument are all one `ast.Constant` - and the count is load-bearing, because
`resolve_model` legitimately holds two, so a fifth decision *inside* it would create no new
key. The first version matched only `ast.Compare` against a constant and walked past
everything else; the tell was that the author's own power-check technique had adopted the
membership form *because* it evaded the guard. A technique adopted to evade a guard is
evidence about the guard. What the inventory still cannot see is a name assembled at run time,
and **a mode name written before it is declared**, since it keys on the table's own values -
so it is weakest during exactly the change it protects. **When sovereign lands, add it to
`EGRESS_GRANTS` first, then wire the routing.**

**A guard's reach must be established, not described** - four times now a guard's own account
of its coverage has been wrong. The inventory above, sp58's `public_url` walk, and sp59's
Settings-page walk, whose opener list omitted `<button` so neither `role="switch"` toggle was
examined - **including the control that task had just added** - while the comment beside the
list said they were. The repair is the same each time: make the walk a **pure function over
given text**, and drive one of each kind through it *both gated and ungated*, since a one-sided
test passes against a walk that reports everything and against one that reports nothing. A walk
that can only run against the real source is a walk that cannot be asked what it saw.

The fourth is sp62's and it is not a walk, so it is worth stating separately.
`test_previewing_a_voice_reaches_no_text_to_speech_call` asserts on an `httpx.MockTransport`
and its docstring claimed it *"fails whatever route a synthesis call arrives by"*, while
`_catalogue_wire` installed the recorder with
`setattr("api.services.voice_catalogue.get_tts_client", ...)` - **one module's imported name**.
`interview_service` binds its own copy, so `await speak(...)` added to `list_voices` did not
stay green - it failed noisily, and for the wrong reason. The twist that makes it worse than a
blind spot: the same fixture writes a non-empty `elevenlabs_api_key` onto the shared settings
object, which disarms `synthesise`'s "not configured" guard - so the call the recorder could
not see **went to the real provider**, refused 400, taking the file to 23 failed of 36 rather
than reporting on the one assertion that names it. A fixture that blinds the recorder and
unlocks the network is worse than no fixture. The repair generalises the walk one above:
**install the recorder on the shared resource, not on a name** - `http_clients._tts_client` is
the object every `get_tts_client()` returns, so every module and every import spelling now
lands on the mock - and *establish* it,
which is `test_the_wire_recorder_sees_a_synthesis_call_from_another_module` deliberately
calling through the other module's binding. The residue is stated rather than papered over: a
caller that builds its own `httpx.AsyncClient` (as `voice_metadata.py` does on purpose) is
still outside it, and the name-keyed import guard beside it is what covers that.

---

## Sending an email: one seam, and one face per audience

Everything outbound goes through `api/services/outbound_mail.py`. Never build an httpx
request to Resend, never reach for the `resend` SDK or `smtplib`, and never take a slug's
mode from a caller. Two entry points:

| Function | For | Redirects on `dev_mode`? |
|---|---|---|
| `send_project_mail(slug, audience, to, subject, body)` | anything belonging to a project | yes |
| `send_platform_mail(to, subject, body)` | correspondence from the product itself | no - there is no project to ask |

This is the same property the LLM seam above has, and it exists for the same reason.
`dev_mode` reads as "hold all outbound mail for this project" and covered **two of five**
send paths, because each of the two carried its own copy of the redirect and there was no
single thing for the other three to call. The three it missed - interview reminders, the
transcript copy, and the welcome email - are exactly the ones that reach *stakeholders*
rather than the operator. `dev_mode` also defaults to `True`, so nothing sending looks
identical to the setting working, which is how it survived.

`test_only_the_seam_posts_to_resend` walks every non-test `.py` and fails if any file
other than `outbound_mail.py` contains `api.resend.com`. It is a substring match on one
hostname, so it catches a copy-pasted httpx sender but would not catch the `resend` SDK or
a URL assembled from parts - tighten it rather than working around it.

**`slug` is required and never defaulted**, for the reason the LLM seam gives one file up:
a forgotten slug must not become "no project, so no hold". `project_holds_mail` fails
closed in every direction - absent key, missing database, or a read that raises all hold
the mail.

**One face per audience, not per composing agent.** The seam owns the sender identity while
any agent remains the author, because a participant receiving programme updates from one
person, interview requests from a second and a thank-you from a third experiences the org
chart rather than a correspondent:

| Audience | Correspondent |
|---|---|
| `STAKEHOLDERS` - reminders, interview requests, transcripts, thank-yous | `stakeholder_manager` |
| `GOVERNANCE` - status reports, crew notices, approval and milestone notices | `pam` |
| a new login | neither - platform correspondence, unsigned |

Both names resolve through `agents/identity.py` **at send time**. Never hard-code "Jordan"
or "Pamela"; the permanent `agent_id` beside a mutable display name exists precisely so a
rename is a one-file change, and
`test_renaming_the_correspondent_renames_the_face_and_not_the_address` fails if anybody
writes a literal.

**The name is the person; the address is the role.** `From` carries two independent fields
and they are two different kinds of thing:

```
From: "Jordan Williams" <stakeholder-manager@taskreimagination.ai>
```

| Half | What it is | Keyed on | Changes when |
|---|---|---|---|
| display name | the person | nothing - free text | the persona is renamed, or (future work) per project |
| address | the role | the permanent `agent_id` | never |

A reply reaches whoever does stakeholder engagement, not a particular person, so the
address must outlive the agent being renamed, re-personed or replaced, and a year-old
thread must still route - the same reason `accounts@` and `admissions@` outlive the people
behind them. The operational consequence: **one mailbox per role, ever.** Per-project
display names add none, and a coding-agent crew would add one, not one per engagement.

**A per-project display name does not reach the correspondence, and that is now an open
question rather than a hypothetical.** `outbound_mail.py` resolves the correspondent through
`agents/identity.py` **at send time**, and none of `resolve_agent_config`'s callers is it - so a
project that renames its interviewer gives the participant one name on screen and in the speech,
and **a different name in their inbox**. The gap was unreachable before sp62, because there was
no per-project name to disagree with. It is a design question and not a missing line: this
section already says the display name is the person and the address is the role, and whether a
per-project name may change a *correspondent* is an argument that starts there. Left open
deliberately; whoever closes it should decide the rule, not patch the one call site.

The local part is the `agent_id` with underscores as hyphens - `stakeholder_manager` →
`stakeholder-manager`, `pam` → `pam`. It is a **rule over the id, never a table**: a
mapping of ids to addresses is a second registry free to drift from `agents/identity.py`.
The domain is parsed out of `FROM_EMAIL` so a deployment cannot half-move; there is no
second domain setting, and a `FROM_EMAIL` with no address raises rather than minting
`pam@`. Platform mail (the welcome email) keeps `FROM_EMAIL` **entire**, name and address
both - no role owns it, and `noreply@` is honest for a message nobody should answer.

Two things are **assumed and unconfirmed**, because the domain is not verified in Resend
and nothing can be tested against it: that Resend permits sending from arbitrary local
parts on a verified domain (verification is per-domain, so almost certainly yes), and that
inbound routing can fan several addresses into one webhook. Confirm both when the domain is
verified, before relying on either.

No `reply_to` is set anywhere, deliberately: nothing can receive - the domain is
unverified, and there is no inbound routing, mailbox or threading token. A `reply_to` that
bounces is worse than none. A role-keyed `From` does not change that yet, but it does mean
that when the mailboxes exist a reply already goes to the right place by default, and a
`reply_to` would only be needed to say something *different*. Inbound routing itself -
associating an arbitrary reply with a project and a person - remains unbuilt.

**The welcome email is not held by anything**, and neither will reset links be. A
project-scoped hold cannot honestly cover a message with no project; the fix, if it is ever
wanted, is a platform-level hold, not a default slug. `dev_mode`'s redirect address is
`DEV_MODE_ADDRESS` in settings, and sub-project D's test mode - resolving it to a project's
own administrators - must **refuse to send** when a project has none. A fallback to the
intended recipients would make this switch fail open, which is the worst direction for it.

One consequence of the hold is worth knowing before diagnosing it as a bug, and this paragraph
used to overstate who meets it. With `dev_mode` on, `POST
/api/interviews/{session_token}/email-transcript` answers `{"sent": true}`, delivers nothing to
the participant, and puts the transcript in the operator's inbox. The door still does exactly
that - but **no participant can reach it any more**: sp66 removed the review step's "email me a
copy" checkbox, which was its only caller, so the one path in the product where the *recipient*
triggered a send and was told it worked is now reachable only by hand. See *Known issues* for
why the door was kept. **Corrected rather than deleted**, because the shape is what to watch for
in the next send path rather than a fact about this one: a hold that answers success to the very
person it is holding from has to be written down somewhere, or it is diagnosed as a delivery
failure.

---

## The deployment's public URL: a setting, not an environment variable

`PUBLIC_URL` is the address this deployment answers on, and it is in front of a person every
time it is used - the interview link a participant clicks, the reminder, the welcome email's
login link, the report and commit notices. It is now a setting a sysadmin changes in the
browser, and `PUBLIC_URL` is the **bootstrap**: the value in force until one is stored, so a
fresh deployment mails correct links before anybody opens the admin page. Precedence is
**stored → `PUBLIC_URL` → the `api/config.py` default**, first non-empty wins, stated once in
`_resolve`. The consequence to expect rather than diagnose: on a deployment that has ever
saved one, editing `.env` and restarting changes nothing.

**Read it with `platform_public_url()` (`api/services/platform_settings.py`), never
`get_settings().public_url`.** A direct read collects two defects at once, because the four
original readers' own `.rstrip('/')` calls were deleted once the accessor owned normalisation:
it ignores the stored setting *and* re-opens the trailing-slash bug that put
`https://host//dashboard/login` in the welcome email.
`test_nothing_reads_public_url_off_settings_outside_the_accessor` walks the source so this is a
mechanism rather than a paragraph; its docstring says what the walk cannot see.

The accessor is **synchronous** because `interview_service.interview_url` is a plain `def`, and
it opens `system.db` **read-only** so asking the question can never materialise the database -
the rule `caller_roles` and `_stakeholder_matches_invite` already follow. **A failed read falls
back to the environment rather than raising, deliberately unlike the `llm_mode` seam**: a wrong
`llm_mode` sends client material to the wrong country, while this falls back to a correct link
built the old way, and a link builder that raised would take interview invitations down for a
transient lock. Only a successful read is cached, and every write must call
`forget_platform_settings()` or the process serves the old URL until restart - which is why
reverting is an explicit `DELETE /admin/platform-settings` rather than a hand edit of the row.

**`sysadmin` alone may set it**, a tier tighter than `_PLATFORM_TIER_SETTINGS`. Not seniority:
whoever sets it decides where every interview invitation and welcome email points, and a
participant clicks that link and signs in, so it is a credential-phishing vector rather than a
misconfiguration. `platform_settings` is a **singleton row** in `system.db` - declared columns
under `CHECK (id = 1)`, not a key/value store, so a new platform setting is a column and not a
drawer of undeclared strings.

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
| `api/services/campaign_service.py` | Interview campaigns; composes reminders, does not deliver them |
| `api/services/outbound_mail.py` | **Every** outbound email - the only caller of Resend |
| `agents/crews/pam_crew.py` | Project Automation Manager (top-level orchestrator) |
| `agents/tools/registry.py` | Agent name → tool list mapping |
| `ui/src/router.tsx` | All frontend routes |
| `ui/src/pages/Architecture.tsx` | Hidden `/architecture` reference page |
| `docker-compose.yml` | ChromaDB — the only Docker service since n8n was retired |
| `.env.example` | All environment variables documented |

---

## Sprint history summary

This project was built across 16 sprints (SP1–SP16). The memory index in `~/.claude/projects/.../memory/MEMORY.md` has one entry per completed sprint with branch name, test counts, and key changes.

The main branch is `master`. Feature branches follow `feature/sp<N><letter>-<short-description>`.

---

## Known issues / tech debt

- **Four tests read a bare relative `Path("projects/sp-gs-am/outputs/…")` and skip silently
  when it is not there** - `test_sqlite_state_validation.py`, `test_value_chain_model.py`, and
  two in `test_value_chain_migration.py`. `projects/` holds two tracked files, so a clean clone
  runs none of them, and neither does this workstation when `pytest` is started from anywhere
  but the repository root: the path reads neither `PROJECTS_DIR` nor the settings. Its own
  task, and the fix is committed fixtures under `tests/fixtures/` - which the two permanently
  dark tests already name as theirs. Argued in full under *Test commands*; recorded here so it
  is findable as work.
- `python-pptx` must be installed inside the venv (not system pip on macOS with Homebrew Python 3.13 / PEP 668)
- `taskreimagination.ai` must be a verified sender domain in Resend before reminder emails deliver
- The Architecture page (`/architecture`) is not linked from the nav — navigate directly
- The `business_plan` crew has never completed a real run. It only became buildable when
  `visual_illustrator` was registered; before that `create_business_plan_crew` raised
  before its first task. Treat its first run as an experiment.
- Deepgram (STT) and ElevenLabs (TTS) are used in secure mode by decision, both being
  streamed with no content retention. Local speech services are future work, not a
  current requirement. **For Deepgram that sentence described an intention until sp66, not a
  practice**: the grant door had existed since May 2026 and nothing in `ui/src` had ever called
  it, so the decision, the undertaking on the privacy page and the entry here were all about a
  path with no traffic on it. It is connected now, it is the primary recogniser with the
  browser's as the fallback, and what travels on it is **two things rather than one** - the
  participant's audio and this engagement's vocabulary. Both are declared in
  `PARTICIPANT_SPEECH_EGRESS`; the decision itself is unchanged. The residual is the one
  ElevenLabs' add-voice door already carries below: **no part of this path has spoken to the
  real provider.** The URL form, the `keyterm` spelling and the webm/opus stream are read off
  documentation, so a wrong reading opens a socket that boosts nothing, and the fallback is
  what keeps the worst case at "today's behaviour" rather than "a lost interview". Argued in
  full under *Listening to a participant*. ElevenLabs is reached for a **second** kind of request - the two
  voice listings behind `GET /projects/{slug}/voices` (`api/services/voice_catalogue.py`) -
  and that request carries no client material at all: an accent, a sex, and a search term the
  consultant typed. It is recorded because the row said "interview text" and would otherwise
  have been quietly wrong about what leaves, not because it changes the decision. The one
  ElevenLabs call that *writes* anything is `POST /projects/{slug}/voices/library`, which
  copies a Voice Library voice into the deployment's account and sends only a name. That door
  is **platform tier, one step tighter than the axis rules would put it**, and deliberately:
  it looks like project configuration, but one ElevenLabs account serves every engagement, so
  the write leaves the project the way a sector-tier document does. Do not widen it to
  `require_project_administration` on the grounds that it configures an agent - the reason is
  the shared account, not the field. It is also the one path on this surface **never confirmed
  against the real provider**: `POST /v1/voices/add/{owner}/{voice}` is assumed from the
  documented API, because verifying a write to the shared account means performing it. It could
  fail in production having passed every test. Its failure is reported to the operator rather
  than swallowed, and it refuses to fall back to the library id, so the worst case is a clear
  message rather than a well-formed dead configuration.
- Avery still blocks on `HumanInputTool` for up to 24 hours during an interview programme,
  and nothing notifies the crew when a session completes. It does not affect interviewee
  experience, which is why sub-project B left it alone.
- **`POST /api/interviews/{session_token}/email-transcript` is orphaned and deliberately kept.**
  sp66 removed the review step's "email me a copy" checkbox - it promised a delivery that
  `dev_mode` was holding, and it was the *only* reader of the participant's edits, so a
  participant who corrected a mangled answer and left the box unticked had their corrections
  discarded. The door behind it is still mounted, still tested (five backend files touch it),
  and now has **no caller in `ui/src`**. Kept rather than retired for one reason: it is a
  working, well-guarded send path and the product wants *some* route to a participant's own
  transcript, so deleting it would be deleting the mechanism rather than the promise. **Who can
  call it, and what happens:** anybody holding a `session_token` for a completed session, by
  hand - no login. It refuses a destination that is not the stakeholder's own address on file,
  caps the body, and rate-limits to three sends per session per hour, so a leaked token cannot
  relay attacker-chosen text from the sending domain. Under `dev_mode` it answers
  `{"sent": true}` and the transcript goes to the operator, which is the corrected sentence in
  the mail section above. **If it is ever retired, it takes the router handler, the request
  model, the rate-limit registration, and tests in five files with it** - and that mail-section
  paragraph must be corrected a second time, since it would then describe no door at all.
- **The keyterm read widens what a session token discloses, and that is a judgement rather
  than an oversight.** `GET /api/interviews/{session_token}/deepgram-token` answers the whole
  **active** `value_chain_ledger`, while the session itself is anchored to one node. The
  holder of that token is already served their entire interview script verbatim one endpoint
  over, so the script half of the vocabulary is a strict subset - the ledger half is not: it
  discloses the shape of the whole value chain. Judged acceptable (a node label is a few words
  naming an activity, and the interview discusses the value chain with that person anyway), and
  recorded because somebody may reasonably disagree. **Narrowing it to the session's own node
  and script is a one-line change** in `keyterms_for_project`.
- A Deepgram socket is opened **per answer**, not per interview, which costs a handshake of
  latency before each one. It matches the `new SpeechRecognition()` per answer it replaces and
  it fits the grant's 30-second TTL exactly, and the microphone stream *is* held for the whole
  interview so the browser's recording indicator does not flicker. If the latency is felt, the
  fix is to open the next socket while the question is being spoken, not to lengthen the grant.
- `complete_session` and `_find_session_db` in `api/services/interview_service.py` open
  their connections with a bare `aiosqlite.connect(db_path)`, not
  `api.database.get_connection(slug)`. WAL survives that, because it is a persistent
  property of the database file once any code path sets it; `busy_timeout` does not, since
  it is per-connection and nothing sets it on this path. Found while proving twenty
  concurrent interview completions in `tests/test_interview_concurrency.py` - it did not
  fail the test on this workload, but the `get_connection` guarantee does not actually
  reach the `/complete` endpoint's writes. Worth a follow-up task.

  **`_find_session_db` also runs twice per grant request**, and that path is now per answer
  rather than per interview, so the cost is newly worth something: each call scans every
  project database. `api/routers/interviews.py` calls it once inside `get_session_with_script`
  and again to recover the slug the keyterms need - and `get_session_with_script` **already
  computes that slug** and simply does not return it. Returning it removes both scans; the
  `speak` door has the same shape and would be fixed by the same line.
- Secure mode runs two local models concurrently. `OLLAMA_MAX_LOADED_MODELS` defaults to 1, which
  makes them evict each other on every alternation regardless of free memory - see
  `docs/runbook-local-models.md` before diagnosing local models as slow.
- `build_and_run_agent` - the standalone "run this one agent" dispatch - fetches no validation
  warnings, library skills, or change requests, so an agent dispatched that way is missing all
  three feedback channels `build_and_run_crew` gives it. Not currently reachable from the UI:
  `runAgent` is defined in `ui/src/api/endpoints.ts` and called by nothing, so every human
  re-run goes through the crew path. It is reachable from the API.
- The Interview Coordinator still matches a stakeholder to a script by `node_label` when it
  plans a session, because `stakeholder_assignments` carries no script id. The match is now made
  once and recorded on `interview_sessions.script_id` rather than re-derived per answer, so the
  ambiguity is no longer repeated - but the single arbitrary choice at plan time remains, and
  `_resolve_script_id` deliberately stores NULL rather than guessing when a label is ambiguous.
  The real fix is a `script_id` column on `stakeholder_assignments`.
- **A helper with no production caller is a helper that will drift from production.**
  `api.database.insert_interview_session` was the recorded instance - driven by tests alone, and
  extended on one branch with a `script_id` column production never populated. **This entry is
  closed**: sp62 moved it to `tests/support_interview_sessions.py` (28 call sites, 11 files),
  where being test-only is what it says on the tin, and
  `tests/test_interviewer_selection.py` asserts it has not come back to `api/database.py`.
  `InterviewSessionTool._create` is the sole producer. It is recorded rather than deleted
  because the shape recurred immediately: `upsert_agent_config` and `resolve_agent_config`
  landed with the table in sp62 Task 1, and **nothing but a test could write that table** until
  the door landed in Task 5 - three tasks during which the resolver, the stamp and the migration
  were all built against a column no production path could set. The rule from the first instance
  is the rule for the second: **delete it, or make it the producer; do not leave both.** Finding
  it the expensive way twice is the argument for asking the question when the helper is written,
  not when the door is.
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
- **Retiring a lever is not expressible at all** - the same shape as the entry above and one
  step worse. `value_lever_ledger` has no `active` column, declined in sp60 Task 2 as
  speculative, so a lever Morgan has dropped keeps a live ledger row for ever and
  `levers_awaiting_regeneration` has no clause to exclude it - where
  `nodes_awaiting_regeneration` filters `active=1` and its query is written beside this one.
  The consequence is bounded and real: a send-back recorded against a lever before it was
  dropped outlives the lever, and is injected into Morgan's prompt on every run until she
  re-emits that `lever_id`, which by then she has no reason to. The fix is the column, a
  `_SCHEMA_VERSION` bump, and the clause - not a filter in the reader.
- **Fifteen of the eighteen declared collections have no per-item review state**, and the rule
  they are owed is stated under *Crew / agent conventions*: the unit of review is the unit of
  regeneration. Three have a ledger (`interview_scripts`, `value_chain_registry`,
  `value_levers`). Two of the rest are written today and are deliberate exclusions -
  `value_chain_model` has `StructureTab` and a workflow of its own, and `value_chain_tree`
  restates the registry's ids rather than holding any. The other thirteen have **never been
  written at all**: `activity_insights`, `architecture_register`, `captured_requirements`,
  `illustration_briefs`, `initiative_register`, `interview_plan`, `interview_transcripts`,
  `portfolio_register`, `propositions`, `requirements_analysis`, `roadmap_data`,
  `strategic_requirements`, and `themes`. Most are registers by name. They are listed as owing
  a ledger rather than given one here, so the next agent to be built is measured against the
  rule while it is cheap - after the artefact exists, adding per-item identity means a backfill
  that assigns ids to items a reviewer has already read.
- **Both sp60 backfills are written and have not run.** `scripts/backfill_value_chain_ledger.py`
  (89 nodes) and `scripts/backfill_value_lever_ledger.py` (10 levers) are proven on copies of
  `data/sp-gs-am.db` and skip against the live one, because the migrations have not reached the
  running server's database - it is still at `PRAGMA user_version = 17` and holds neither
  ledger. So a live `sp-gs-am` shows **empty** node and lever review panels until the API is
  restarted and the backfills are run, in that order. A data state, not a defect in the
  surface; diagnose it here before diagnosing it in `DiscoveryReviewExtra`.
- `register_scripts_sync` carries a near-copy of `scripts_awaiting_regeneration`'s WHERE
  clause to reset a regenerated script's `review_status`, and the two have **already
  diverged**: the query filters `active=1` and `project_id`, the copy does neither. A retired
  row sent back to the agent is therefore invisible to the query but still reset by the copy -
  a send-back cleared without ever having been actionable. Unreachable only because
  retirement is (see above). Extract the condition rather than copying it a third time.
- **`POST /projects` lets an `org_admin` claim an unregistered project.** It is the one route
  in `api/routers/projects.py` with no `check_project_access`, it answers **200** to a re-POST
  of a slug that already exists, and it registers that slug to the *caller's* organisation. So
  an org_admin of an unrelated organisation goes 403, re-POSTs the slug, and then reads the
  whole engagement as a legitimate member. Bounded twice: `register_project_if_unregistered`
  is `INSERT OR IGNORE`, so a project that *has* a registry row cannot be dragged out of its
  organisation, and `list_all_projects` filters by organisation, so the slug is never disclosed
  to the attacker - they must already know it, and slugs travel in URLs and report headers.
  Not merely an access grant: claiming repoints the project's **organisation store**, read and
  write, so an org-tier upload afterwards lands in the claimant's `org_` collection. The
  precondition is non-empty on the current deployment - `vc-sort-check` is a project database
  with no `project_registry` row. Its own task, not a patch inside a tier rule: the same fix
  is `check_project_access` on `POST /projects` for the whole engagement.
- **`brand_header_image_url` and `project_agent_config.image_url` owe a validator, not an
  upload path.** Two doors onto one hazard: both put an administrator-chosen URL into the same
  `<img src>` on the unauthenticated interview page. Its own task, because the fix serves both
  fields and closes both halves - scheme and off-site - at once, and surfacing the reach to the
  auditor belongs with it rather than before it. Argued in full under *Crew / agent
  conventions*; recorded here so it is findable as work.

  **Both fields now have a same-origin upload path, and the asymmetry that is left is the
  validator.** `POST /{slug}/branding/image` has served the header since before sp63 and is
  wired into the field (`Settings.tsx` writes the URL it answers straight into
  `brand_header_image_url`); sp63 added `POST /{slug}/agents/{agent_id}/image` as its
  equivalent for the portrait, and fixed the address the branding door returns. So the
  ordinary route is same-origin for both. What differs is what happens when the free-text box
  beside each is used instead: `PUT .../agents/{agent_id}/config` refuses an `image_url` whose
  scheme is not `http` or `https`, and `PATCH /{slug}/settings` accepts anything at all for
  `brand_header_image_url`. **An upload path is not a validator** - neither field's text box is
  removed, so as long as one exists the hazard is decided by what the *write* door checks, and
  writing "there is an uploader now" where the sentence means "the field is guarded" is exactly
  the substitution this entry was corrected for.
- **A failed reingest leaves chunks behind with `ingested=0`.** The first ingest's chunks stay
  in the store while the row is marked not-ingested, and `DELETE /{slug}/documents/{doc_id}`
  purges only `if doc["ingested"]` (`api/routers/documents.py:225`) - so the delete answers
  204 and removes nothing. Pre-existing. `knowledge_collection` now records the handle that
  would close it.
- **`api/services/interview_answer_service.py:217` still builds `f"{slug}_interviews"` by
  hand** - the sixth site constructing a collection name outside `collection_for`, and the
  shape this class of defect keeps arriving in.
- **A migration that raises takes every later migration in the block down with it**, so each
  one must be defensive about the shape it finds. SQLite prepares a correlated subquery when
  the statement is prepared rather than when a row matches, so a `SELECT p.sector ...` raises
  on any database whose hand-built `projects` table lacks the column - several test fixtures
  build that table by hand. Guard each half with `PRAGMA table_info` and skip *itself* rather
  than the rest of the block.
- `agents/model_registry.py`'s `_TIER_SETTINGS` has a second key spelled `"standard"` /
  `"sensitive"` but **meaning** hosted / local, and any non-granted mode now reads its
  `"sensitive"` row - as, since sp59, does a `standard` project with `force_local_inference`
  set, so the key is already lying about a live case. Rename it to local/hosted **before**
  sovereign lands, or a hosted-inference-with-local-vectors mode will read
  `("deep", "standard")` and the key becomes
  actively misleading rather than merely dated. Not renamed already because `llm_client.py`
  imports the table.
- **The design's "an approved project-scoped skill is not offered as a deduplication candidate
  to another project" is built only for comparisons that leave the deployment.**
  `_candidates_that_may_travel` withholds a `project`-scoped candidate from any payload going
  off-premises, which closes the disclosure; `_rules_already_held`, which assembles the list in
  the first place, still reads `_DEDUP_STATUSES` and never looks at `scope`.

  **Two corrections to the obvious reading of that, both driven rather than reasoned.** It is
  **not** confined to an all-`standard` deployment: `_candidates_that_may_travel` returns early
  when the *proposer* lacks `HOSTED_INFERENCE`, so a `sensitive` engagement is compared against
  other clients' narrow rules **on its own model** - nothing leaves, and the separation is still
  absent. And *compared against* does not mean nothing comes back: on a match `propose_skill`
  answers `held["name"]`, which for an auto-named row is the first five words of the other
  engagement's rule, into `PATCH /reviews/{id}`'s `skill_proposal.name`. That is latent rather
  than live - `_describe` drops it and no UI reads it - and it is pre-existing, but a follow-up
  scoped from the shorter description would fix the wrong half.

  It remains a separation the spec asked for rather than a leak: the comparison happens inside a
  trust boundary the deployment already accepts for both projects. The fix belongs in
  `_rules_already_held`, not in the egress narrowing, which answers a different question.
  (The two exemptions that read `status='approved'` as "applies everywhere" **are** closed -
  see *One mechanism* above. They were on this list for a whole branch first.)
- `_fetch_skill_notes` in `run_service.py` **fetches no notes** - the mechanism it was named for
  is deleted and it returns library skills. The name is kept because every caller, test and
  paragraph in this file refers to it; renaming touches eight files including this one. Its
  docstring says so, which is the least a misnamed function can do.

---

## Environment variables

All env vars are documented in `.env.example`. Never commit `.env`. Key vars:

- `ADMIN_USERNAME` / `ADMIN_PASSWORD` — **required**, no defaults
- `JWT_SECRET` — generate with `openssl rand -hex 32`
- `PUBLIC_URL` - full public URL used in every emailed link. The **bootstrap only**: a URL
  stored through `/admin/platform-settings` wins over it, so editing this and restarting is a
  no-op on a deployment that has ever saved one. See the public-URL section above.
