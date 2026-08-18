# A platform setting an administrator can change - implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `PUBLIC_URL` becomes a setting a `sysadmin` changes in the browser, stored in `system.db`, overriding the environment variable, and read by every place that builds a link a person clicks.

**Architecture:** A one-row `platform_settings` table with declared columns. A **synchronous** accessor `platform_public_url()` resolving stored → environment → default, cached in-process and invalidated on write. A `sysadmin`-only door under `/admin`. The five readers and the two vestigial `run_service` sites all move onto the accessor.

**Spec:** `docs/superpowers/specs/2026-08-19-platform-public-url-design.md`

## Global Constraints

- **British English** - `-ise`, `-our`, `-re`, Oxford comma, spaced en dash ` - `, never an em dash. Binds copy an administrator reads.
- **`brand` tokens only**, never `sky-*`/`blue-*`. Lucide icons, no emoji. `describeError` from `ui/src/utils/describeError.ts`.
- **Python 3.13** via `./venv/bin/python`. No ORM - raw SQL in `api/database.py`.
- **`system.db` has no version gate.** `init_system_db` runs on every system connection and is idempotent, so a new table is a `CREATE TABLE IF NOT EXISTS` there. **Do not bump `_SCHEMA_VERSION`** - it gates *project* databases only, and bumping it would re-run every project migration for nothing.
- **Backend suite twice with identical counts.** Baseline **2250 passed, 2 skipped, 12 deselected**. Frontend **630**, `tsc --noEmit` clean. Establish both from HEAD yourself and report them; numbers written in documents on this project have been stale four times.
- **Enforce in the service, not the router.** Routers translate a refusal into a status code.
- **Power-check each property separately.** A shared resolver lets one precedence step's test cover another's.
- Clear `__pycache__` between a mutation and its revert; commit before the first mutation.
- Stage explicit paths. **Never `git add -A`.** Write nothing to `data/`. Do not restart the servers on :8000 or :3000.

---

### Task 1: The table, and a synchronous accessor with a precedence chain

**Files:** Modify `api/database.py`; Create `api/services/platform_settings.py`, `tests/test_platform_settings.py`

**Interfaces:**
- Produces: `platform_public_url() -> str` and `forget_platform_settings() -> None`. Tasks 2, 3 consume both.

- [ ] **Step 1: Add the table to `init_system_db`**, in the same `executescript` as its neighbours.

```sql
CREATE TABLE IF NOT EXISTS platform_settings (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    public_url TEXT NOT NULL DEFAULT '',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

The `CHECK (id = 1)` is the point: it is a singleton, and a second row must be impossible rather than merely unwritten. `scheduler_heartbeat` is the existing singleton in this file - read it first and match its style.

- [ ] **Step 2: Write the failing tests - each precedence step alone**

```python
def test_the_stored_value_wins_over_the_environment(...):
    # stored "https://stored.example", env "https://env.example"
    assert platform_public_url() == "https://stored.example"

def test_the_environment_wins_when_nothing_is_stored(...):
    # platform_settings empty, env "https://env.example"
    assert platform_public_url() == "https://env.example"

def test_a_blank_stored_value_does_not_shadow_the_environment(...):
    # stored "", env "https://env.example"
    assert platform_public_url() == "https://env.example"
```

Three separate tests because a resolver that returned the environment unconditionally would pass the second and third together.

- [ ] **Step 3: Write the accessor. It must be `def`, not `async def`.**

`interview_service.interview_url` is a plain `def`, so an async accessor cannot be called from it. Open a plain `sqlite3` connection **read-only** (`file:...?mode=ro`, `uri=True`) so a caller can never materialise `system.db` by asking a question - the rule `caller_roles` and `_stakeholder_matches_invite` already follow.

Two failures, treated differently and mirroring `project_llm_mode` directly above this shape in `chroma_client.py`:

- **The file does not exist** - a deployment that has not started. Fall back to the environment, **do not cache**: the database will appear.
- **The read raises** (locked, no such table on a database predating this change, corrupt) - fall back to the environment, log a warning, **do not cache**. Caching a guess born of a failed read is what turns one bad read into a permanent wrong answer.

Only a successful read is cached.

- [ ] **Step 4: `forget_platform_settings()` clears the cache.** One line, and Task 2 calls it on every write.

- [ ] **Step 5: Run the tests, power-check each precedence step singly, commit.** Reverting the `stored or env` fallback to `stored` alone must fail steps 2 and 3 and not step 1.

---

### Task 2: The door, and what it refuses

**Files:** Create `api/routers/platform_settings.py`; Modify `api/main.py`; Test: extend `tests/test_platform_settings.py`

**Interfaces:**
- Consumes: `platform_public_url`, `forget_platform_settings` from Task 1.
- Produces: `GET /admin/platform-settings`, `PATCH /admin/platform-settings`.

- [ ] **Step 1: Establish where `/admin` routes already live and report it.** `/admin/skills/*` exists. Decide whether this is a new router file or an addition to an existing one, and say why. `/admin` is already covered by both the `Caddyfile` and `vite.config.ts`, so no proxy change is needed - **confirm that rather than assuming it**, and keep `tests/test_proxy_prefix_coverage.py` passing.

- [ ] **Step 2: Write the failing authority test - and pick the right caller**

```python
async def test_an_org_admin_may_not_change_the_platform_url(client, ...):
    resp = await client.patch("/admin/platform-settings",
                              json={"public_url": "https://evil.example"},
                              headers=org_admin_headers)
    assert resp.status_code == 403
```

**An `org_admin`, not an anonymous caller.** Anonymous is refused by the dependency before any rule is reached, so it would prove nothing about this door. This project has the same note against its milestone-door tests.

- [ ] **Step 3: Gate on `require_sysadmin`.** The reason is in the spec and belongs in the handler's docstring: whoever sets this decides where every interview invitation and welcome email points, and a participant clicks it and signs in.

- [ ] **Step 4: Validate and normalise, in the service**

```python
def normalise_public_url(raw: str) -> str:
    """The stored form of a public URL, or a refusal saying which rule it broke."""
    parsed = urlparse(raw.strip())
    if parsed.scheme not in ("http", "https"):
        raise PublicUrlRefused(f"...must begin http:// or https://, not {parsed.scheme!r}...")
    if not parsed.netloc:
        raise PublicUrlRefused("...names no host...")
    if parsed.username or parsed.password:
        raise PublicUrlRefused("...must not carry credentials...")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
```

Store without a trailing slash. Four of the five readers already call `.rstrip('/')` - the same rule written five times because nothing enforced it once.

**Each refusal is asserted by its own sentence**, never by a substring the test supplied. CLAUDE.md records a refusal message that quoted the key it was refusing, so the assertion could not fail.

- [ ] **Step 5: The write calls `forget_platform_settings()`.** Test it end to end: PATCH, then read, in one process, and get the new value. Power-check by removing the call - the test must fail.

- [ ] **Step 6: Suites twice. Commit.**

---

### Task 3: Every reader moves onto the accessor, including two that could never work

**Files:** Modify `api/services/interview_service.py`, `campaign_service.py`, `admin_service.py`, `pam_report_job.py`, `commit_notify_service.py`, `run_service.py`; Test: new

- [ ] **Step 1: Move the five readers.** Each currently reads `settings.public_url` / `get_settings().public_url`. Report each before and after.

- [ ] **Step 2: Repoint the two `run_service` sites - this fixes a live defect.** `run_service.py:478` and `:769` read `config.get("public_url", "")` and pass it to the stakeholder-management crew as `public_interview_url_base`. **`public_url` is not declared on `ProjectSettings`, so nothing can ever set it** - the value has always been `""` and Jordan has always been handed an empty URL base. Confirm that yourself before changing it, then point both at `platform_public_url()`.

- [ ] **Step 3: Assert the URL that reaches the transport, not the helper's return value.** `outbound_mail.py` is the single seam every email goes through, and this project's tests already drive it with a mock transport - follow that. A test asserting `platform_public_url()` returns a string proves nothing about what a participant receives.

- [ ] **Step 4: Power-check each reader separately.** One shared accessor makes it very easy for one reader's test to cover another's; that masking has bitten this project twice. Commit.

---

### Task 4: The administrator can see it and change it

**Files:** Modify `ui/src/pages/AdminDashboard.tsx`, `ui/src/api/` (one file per resource), `ui/src/types.ts`; Test: frontend

- [ ] **Step 1: Find where the admin area renders and report what is there.** `AdminDashboard.tsx` is the page; establish its existing sections and follow them rather than inventing a layout.

- [ ] **Step 2: Show the resolved value and where it came from.** An administrator needs to know whether they are looking at a stored value or the environment fallback - otherwise "it says the right thing but the links are wrong" is undiagnosable. The `GET` returns both; render the distinction plainly.

- [ ] **Step 3: The field is visible to a `sysadmin` only.** A control that 403s on submit is worse than one that is not there - this project has established that twice. Gate on the role the token already carries.

- [ ] **Step 4: Assert what is sent, not what renders.** `ui/src/__tests__/client.test.ts` is the axios-adapter pattern. Show the refusal from the server through `describeError` rather than a fixed string - the server's sentence says which rule was broken, and a fixed string cannot.

- [ ] **Step 5: Frontend suite, `tsc --noEmit` clean, power-check, commit.**

---

## Self-Review

**Spec coverage:** one-row declared table (1), precedence stored → env → default (1), synchronous accessor and cache (1), fallback rather than raise on read failure (1), `sysadmin`-only door (2), validation and trailing-slash normalisation (2), cache invalidation on write (2), five readers moved (3), the latent `run_service` defect closed (3), administrator UI (4).

**Placeholder scan:** none. Tasks 2, 3 and 4 each open by establishing facts from the code, because briefs on this project have been wrong about details more than a dozen times - including four counts and, on the last branch, a whole task premise.

**Type consistency:** `platform_public_url() -> str` and `forget_platform_settings() -> None` are defined in Task 1 and consumed in 2 and 3. `normalise_public_url(raw: str) -> str` is defined in Task 2 and used only there.

**Not in scope:** moving `dev_mode`'s redirect address into the table (it belongs with test mode), per-project vanity domains, retiring `PUBLIC_URL` from the environment - it remains the bootstrap.

**One ordering note:** Task 3 could precede Task 2, since the readers only need Task 1. It comes after because the door is what makes the stored value reachable, and moving the readers first would leave a branch state where the accessor is used everywhere and nothing can set what it reads.
