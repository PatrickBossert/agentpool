# Script Review Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move interview script review into the document a reviewer actually reads, gate approval on prior review, and delete the template-assignment layer that duplicates - wrongly - what the scripts already carry.

**Architecture:** Part B first: `interview_sessions` gains `script_id` so an answer's citation no longer depends on matching label text, then the `node_template_assignments` layer is removed. Part A then rebuilds the surface on clean ground - the ledger list becomes the approver's view (node id, review count, gated Approve), and reviewing happens inside an editable document view whose three exits each record a review event.

**Tech Stack:** Python 3.13, FastAPI, aiosqlite (raw SQL, no ORM), React 18 + TypeScript + Vite + Tailwind v3, pytest, Vitest.

## Global Constraints

- British English throughout: `-ise` not `-ize`, `-our` not `-or` - organise, behaviour, artefact, favour, centre.
- Short en dash ` - ` with spaces in prose. Never an em dash (`—`).
- Oxford comma in lists of three or more items.
- **No emoji in rendered web content** - stylised Lucide React icons only.
- Tailwind `brand` / `surface` / `text-*` tokens. **Never `sky-*` or `blue-*`.**
- Python 3.13 only: `./venv/bin/pytest`, `./venv/bin/python`. Never system python.
- Frontend commands run from `ui/`: `npx vitest run`, `npx tsc --noEmit`.
- **Never run `pytest -m integration`** - it calls the real Anthropic API and costs money.
- **Run the backend suite twice** and confirm identical counts. `tests/conftest.py` points `DATABASE_DIR` at a fixed path that persists between runs, so a test writing a hardcoded row id passes once and fails ever after.
- Adding a `_migrate_*` function **requires** bumping `_SCHEMA_VERSION` in `api/database.py` in the same change and adding the call to the migration block in `get_connection`. `_SCHEMA_VERSION` is currently **4**.
- `script_id` is a citation token. It is the identity everywhere in the database and never changes; only what a human is shown changes.
- Do not restart the API server while a crew run is in flight. Do not run a crew.

---

## File Structure

| File | Responsibility |
|---|---|
| `api/database.py` | `_migrate_interview_sessions_script_id`, `_SCHEMA_VERSION` bump, `insert_interview_session` gains `script_id`, review-count query |
| `api/services/interview_answer_service.py` | `script_for_session` resolves from the session, not the retired table |
| `api/services/script_review_service.py` | `edited` decision, review count, approve gate |
| `api/routers/script_reviews.py` | count on the ledger response, 409 on an ungated approval |
| `api/routers/projects.py` | PATCH gains `base_version`; `/node-templates` routes removed |
| `ui/src/components/tabs/ScriptReviewRow.tsx` | list row: node id, count, Open, gated Approve |
| `ui/src/components/tabs/ScriptReviewPanel.tsx` | new - the document view and its three exits |
| `ui/src/components/tabs/MayaOutputExtra.tsx` | wires list to panel |
| `ui/src/components/tabs/MayaSetupTab.tsx` | coverage-mapping section removed |

---

### Task 1: A session carries its own script

**Files:**
- Modify: `api/database.py` (migration, `_SCHEMA_VERSION`, `insert_interview_session`)
- Modify: `api/services/interview_answer_service.py:151-158`
- Test: `tests/test_session_script_citation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `interview_sessions.script_id TEXT`; `insert_interview_session(conn, *, project_id, orchestration_run_id, stakeholder_id, node_label, session_token, voice_config=None, script_id=None) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_script_citation.py
"""An answer learns which instrument produced it from the session, not from label text.

script_for_session used to resolve script_id by matching node_template_assignments on
node_label - the same label matching that makes publish_node_template 404 against an artefact
keyed by script_id. A session is *for* a script, so the session carries it.
"""
import json
import pytest
from pathlib import Path


@pytest.mark.asyncio
async def test_an_answer_resolves_its_script_from_the_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.database import get_connection, insert_interview_session
        from api.services.interview_answer_service import script_for_session
        from agents.tools._db import insert_agent_output_sync

        slug = "sess-cite"
        outputs = tmp_path / "projects" / slug / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)
        # Two scripts sharing a node_label, so a label match cannot pick the right one.
        scripts = {
            "SC-001": {"script_id": "SC-001", "node_id": "1.2", "node_label": "Shared", "sections": []},
            "SC-002": {"script_id": "SC-002", "node_id": "1.3", "node_label": "Shared", "sections": []},
        }
        (outputs / "interview_scripts.json").write_text(json.dumps(scripts))

        async with get_connection(slug) as conn:
            await conn.execute("INSERT INTO projects (slug) VALUES (?)", (slug,))
            await conn.execute(
                "INSERT INTO stakeholders (project_id, name) VALUES (1, 'Ana')")
            await conn.commit()
            insert_agent_output_sync(slug=slug, agent_name="interaction_designer",
                                     output_type="interview_scripts",
                                     file_path=str(outputs / "interview_scripts.json"))
            sid = await insert_interview_session(
                conn, project_id=1, orchestration_run_id=None, stakeholder_id=1,
                node_label="Shared", session_token="tok-1", script_id="SC-002")
            conn.row_factory = __import__("aiosqlite").Row
            cur = await conn.execute("SELECT * FROM interview_sessions WHERE id=?", (sid,))
            session = dict(await cur.fetchone())
            script = await script_for_session(conn, session, slug)

        assert script is not None
        assert script["script_id"] == "SC-002", (
            "the session named SC-002; a label match would have returned whichever of the two "
            "shared scripts came first"
        )
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/bin/pytest tests/test_session_script_citation.py -v`
Expected: FAIL - `insert_interview_session() got an unexpected keyword argument 'script_id'`.

- [ ] **Step 3: Add the migration**

In `api/database.py`, following the house style of the other `_migrate_*` functions:

```python
async def _migrate_interview_sessions_script_id(conn: aiosqlite.Connection) -> None:
    """Give a session the id of the script it is for.

    The citation from a stored answer back to its instrument used to be re-derived by
    matching node_template_assignments on node_label. Label matching is what makes
    publish_node_template 404 against an artefact keyed by script_id, and a label is not
    unique - two scripts can normalise to the same one. A session is for exactly one
    script, so it carries it.
    """
    cur = await conn.execute("PRAGMA table_info(interview_sessions)")
    cols = {row[1] for row in await cur.fetchall()}
    if "script_id" not in cols:
        await conn.execute("ALTER TABLE interview_sessions ADD COLUMN script_id TEXT")
    await conn.commit()
```

Add `script_id TEXT` to the `CREATE TABLE interview_sessions` statement in
`_migrate_interview_sessions` so fresh databases carry it too.

- [ ] **Step 4: Bump the schema version and register the migration**

Change `_SCHEMA_VERSION = 4` (line 1310) to `_SCHEMA_VERSION = 5`, and add to the migration
block in `get_connection`, after `_migrate_script_reviews(conn)`:

```python
            await _migrate_interview_sessions_script_id(conn)
```

Both are required. A migration added without the bump silently never runs on any database
already opened at version 4.

- [ ] **Step 5: Carry script_id through session creation**

In `api/database.py`, change `insert_interview_session` to accept and store it:

```python
async def insert_interview_session(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    orchestration_run_id: int | None,
    stakeholder_id: int,
    node_label: str,
    session_token: str,
    voice_config: str | None = None,
    script_id: str | None = None,
) -> int:
    cur = await conn.execute(
        "INSERT INTO interview_sessions "
        "(project_id, orchestration_run_id, stakeholder_id, node_label, session_token,"
        " voice_config, script_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (project_id, orchestration_run_id, stakeholder_id, node_label, session_token,
         voice_config, script_id),
    )
    await conn.commit()
    return cur.lastrowid
```

`script_id` is optional because no production code calls this yet - the live session-creation
path is not wired, which is why the project has zero sessions. Making it required would break
the tests that do call it without giving anyone a reason to pass it.

- [ ] **Step 6: Resolve from the session first**

In `api/services/interview_answer_service.py`, replace the `node_template_assignments` lookup:

```python
    # The session names its own script. The label scan below stays as a fallback for a
    # session created before that column existed; it cannot distinguish two scripts that
    # normalise to the same label, which is exactly why the column exists.
    script_id = session.get("script_id")
    if script_id and script_id in scripts:
        return normalise_script_fields(scripts[script_id])
    for script in scripts.values():
        if isinstance(script, dict) and script.get("node_label") == session["node_label"]:
            return normalise_script_fields(script)
    return None
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `./venv/bin/pytest tests/test_session_script_citation.py -v`
Expected: PASS

- [ ] **Step 8: Power-check**

Revert Step 6's `script_id` branch, leaving only the label scan. Re-run the test and confirm it
FAILS - the two scripts share a label, so the scan returns the wrong one. Report the observed
failure text. Restore.

- [ ] **Step 9: Run the full suite twice, then commit**

```bash
git add api/database.py api/services/interview_answer_service.py tests/test_session_script_citation.py
git commit -m "feat(interviews): a session carries the id of the script it is for"
```

---

### Task 2: The template-assignment layer is removed

**Files:**
- Delete: `api/services/auto_assign_service.py`, `ui/src/api/nodeTemplates.ts`
- Modify: `api/routers/projects.py` (remove `/node-templates` routes and `publish_node_template`), `api/database.py` (remove `node_template_assignments` helpers and its migration), `api/services/interview_service.py:138-165`, `ui/src/components/tabs/MayaSetupTab.tsx`, `ui/src/pages/Architecture.tsx`
- Test: `tests/test_template_layer_retired.py`

**Interfaces:**
- Consumes: Task 1's `interview_sessions.script_id`.
- Produces: nothing. The table, its routes, and its UI cease to exist.

- [ ] **Step 1: Establish what depends on it before deleting anything**

Run these and record the output in your report:

```bash
grep -rn "node_template_assignments\|auto_assign_interview_scripts\|node-templates\|publish_node_template" api/ agents/ ui/src/ tests/
```

Anything outside the file list above is a dependency the plan did not anticipate. Report it
rather than deleting around it.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_template_layer_retired.py
"""The template-assignment layer is gone, and nothing that mattered went with it.

It held a level that was wrong on 100% of its rows (103 of 103 said L2 regardless of the
node), a script_id duplicating the ledger's primary key, an activity_id duplicating the
script's node_id, and a node_label whose matching is what made publish 404 on every real
project.
"""
import pytest


def test_the_node_templates_routes_are_gone(client):
    r = client.get("/projects/any-slug/node-templates")
    assert r.status_code == 404, (
        f"the retired routes must not answer, got {r.status_code}"
    )


def test_the_auto_assign_service_is_gone():
    with pytest.raises(ModuleNotFoundError):
        import api.services.auto_assign_service  # noqa: F401


@pytest.mark.asyncio
async def test_the_questionnaire_lookup_no_longer_reads_the_retired_table(tmp_path, monkeypatch):
    """interview_service read an assignment only to find a questionnaire_template_id. Exactly
    1 of 103 rows had one, and questionnaires moved inline when questionnaire_builder was
    removed. A session must still open with the table gone."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.database import get_connection
        async with get_connection("q-gone") as conn:
            cur = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='node_template_assignments'")
            assert await cur.fetchone() is None, "the table must not be created on a fresh DB"
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 3: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_template_layer_retired.py -v`
Expected: FAIL - the routes answer, the module imports, and the table is created.

- [ ] **Step 4: Remove the backend**

Delete `api/services/auto_assign_service.py`. In `api/routers/projects.py` remove
`publish_node_template`, the `/node-templates` routes, and every `auto_assign_interview_scripts`
call. In `api/database.py` remove `_migrate_node_template_assignments`, its call in the
migration block, and the `node_template_assignments` helpers
(`fetch_node_template_assignments` and its siblings - find them by grep).

Do **not** bump `_SCHEMA_VERSION` for the removal. `CREATE TABLE IF NOT EXISTS` simply stops
running; existing databases keep the table as an inert relic, which is the safe direction - a
`DROP TABLE` would destroy the only record of what was assigned if anyone ever needs to look.
Say in your report that the table survives on existing databases and is no longer written or
read.

- [ ] **Step 5: Remove the questionnaire branch**

In `api/services/interview_service.py`, delete the block that fetches node assignments to find
a `questionnaire_template_id` (around lines 138-165), and return `questionnaire=None`. Keep the
key in the returned dict so the frontend contract does not change.

- [ ] **Step 6: Remove the frontend**

Delete `ui/src/api/nodeTemplates.ts`. In `ui/src/components/tabs/MayaSetupTab.tsx` remove the
coverage-mapping section, its queries, and the "Edit Script" and "Publish" actions - the editor
moves to the Output tab in Task 6, so removing it here leaves no gap for a reviewer. Remove the
mention in `ui/src/pages/Architecture.tsx`.

- [ ] **Step 7: Run the tests, then both suites, then commit**

Run `./venv/bin/pytest tests/test_template_layer_retired.py -v`, then the full backend suite
twice with identical counts, then from `ui/`: `npx vitest run && npx tsc --noEmit`.

Expect failures in `tests/test_auto_assign_anchor.py`, `tests/test_autostart_service.py`, and
`tests/test_projects_api.py`. For **each** test you delete, say in your report whether the
behaviour is gone by design or merely inconvenient to keep working. A test deleted because it
failed is how coverage silently disappears.

```bash
git add -A && git commit -m "refactor(scripts): retire the template-assignment layer"
```

---

### Task 3: The review count, and `edited` as a review

**Files:**
- Modify: `api/services/script_review_service.py:11` and its `record_script_review`
- Modify: `api/routers/script_reviews.py` (count on the ledger response)
- Test: `tests/test_script_review_count.py`

**Interfaces:**
- Consumes: `record_script_review(conn, *, project_id, script_id, reviewer, decision, notes="", at_version=0, return_to=None) -> dict`.
- Produces: `VALID_DECISIONS = ("reviewed", "edited", "approved", "changes_requested")`; `review_count(conn, *, project_id, script_id) -> int`; every ledger row from `GET /projects/{slug}/script-ledger` carries `review_count: int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_script_review_count.py
"""The count an approver sees is "has a human read this", so all three reading exits count.

Editing, sending back, and signing off each mean somebody opened the instrument and formed a
judgement. Approving does not count towards its own gate.
"""
import pytest
from api.database import get_connection
from api.services.script_review_service import record_script_review, review_count


@pytest.fixture
async def project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    async with get_connection("count-test") as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES ('count-test')")
        await conn.execute(
            "INSERT INTO interview_script_ledger (script_id, project_id, node_id, last_version)"
            " VALUES ('SC-001', 1, '1.2', 3)")
        await conn.commit()
        yield conn
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_all_three_reading_exits_count(project):
    for decision, kwargs in (
        ("reviewed", {}),
        ("edited", {}),
        ("changes_requested", {"return_to": "agent", "notes": "fix Q3"}),
    ):
        await record_script_review(project, project_id=1, script_id="SC-001",
                                   reviewer="ana", decision=decision, at_version=3, **kwargs)
    assert await review_count(project, project_id=1, script_id="SC-001") == 3


@pytest.mark.asyncio
async def test_approving_does_not_count_towards_its_own_gate(project):
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="ana", decision="reviewed", at_version=3)
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="ana", decision="approved", at_version=3)
    assert await review_count(project, project_id=1, script_id="SC-001") == 1


@pytest.mark.asyncio
async def test_the_count_is_scoped_to_its_own_script(project):
    await project.execute(
        "INSERT INTO interview_script_ledger (script_id, project_id, node_id) "
        "VALUES ('SC-002', 1, '1.3')")
    await project.commit()
    await record_script_review(project, project_id=1, script_id="SC-002",
                               reviewer="ana", decision="reviewed", at_version=1)
    assert await review_count(project, project_id=1, script_id="SC-001") == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_script_review_count.py -v`
Expected: FAIL - `ImportError: cannot import name 'review_count'`.

- [ ] **Step 3: Add `edited` and the count**

In `api/services/script_review_service.py`:

```python
VALID_DECISIONS = ("reviewed", "edited", "approved", "changes_requested")
```

and:

```python
async def review_count(conn: aiosqlite.Connection, *, project_id: int, script_id: str) -> int:
    """How many times a human has read this script and said something about it.

    Derived on every read rather than stored. A stored counter is a second source of truth
    for something one query answers, and a derived field going stale has already cost this
    codebase a fix round.

    'approved' is excluded: an approval must not satisfy its own gate.
    """
    cur = await conn.execute(
        "SELECT COUNT(*) FROM script_reviews"
        " WHERE project_id=? AND script_id=? AND decision != 'approved'",
        (project_id, script_id),
    )
    return (await cur.fetchone())[0]
```

- [ ] **Step 4: Put the count on the ledger response**

In `api/routers/script_reviews.py`'s `get_script_ledger`, after fetching the rows:

```python
        rows = [dict(r) for r in await cur.fetchall()]
        for row in rows:
            row["review_count"] = await review_count(
                conn, project_id=project["id"], script_id=row["script_id"])
        return rows
```

- [ ] **Step 5: Run the tests, then the suite twice, then commit**

```bash
git add api/services/script_review_service.py api/routers/script_reviews.py tests/test_script_review_count.py
git commit -m "feat(review): count the reading exits, and add edited as one of them"
```

---

### Task 4: Approve is gated on the server

**Files:**
- Modify: `api/services/script_review_service.py` (new exception, gate in `record_script_review`)
- Modify: `api/routers/script_reviews.py` (status mapping)
- Test: `tests/test_approve_gate.py`

**Interfaces:**
- Consumes: `review_count` from Task 3.
- Produces: `class NotYetReviewedError(ValueError)`, raised when `approved` is recorded against a script with a zero review count; the router returns **409** for it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_approve_gate.py
"""A disabled button is a hint. The gate has to hold at the endpoint or it is decoration."""
import pytest


def test_approving_an_unreviewed_script_is_refused(client, seeded_ledger_script):
    slug, script_id = seeded_ledger_script
    r = client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                    json={"decision": "approved"})
    assert r.status_code == 409, r.text
    assert "no reviews" in r.text.lower()


def test_approving_is_permitted_once_the_script_has_been_reviewed(client, seeded_ledger_script):
    slug, script_id = seeded_ledger_script
    first = client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                        json={"decision": "reviewed"})
    assert first.status_code == 200, first.text
    r = client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                    json={"decision": "approved"})
    assert r.status_code == 200, r.text
    assert r.json()["review_status"] == "approved"


def test_the_approvers_own_review_satisfies_the_gate(client, seeded_ledger_script):
    """A smaller engagement may have one person holding both roles. Someone who opened a
    script, read it, and marked it reviewed has genuinely read it - the gate asks whether it
    has been read, not whether somebody else read it."""
    slug, script_id = seeded_ledger_script
    client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                json={"decision": "reviewed"})
    r = client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                    json={"decision": "approved"})
    assert r.status_code == 200, r.text
```

Write the `seeded_ledger_script` fixture yourself against `tests/conftest.py`'s existing
`client` fixture - read it rather than inventing one. It must insert a `projects` row before
any ledger row, because `PRAGMA foreign_keys = ON` is set by `get_connection`. Scope every
assertion to the row you created.

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_approve_gate.py -v`
Expected: FAIL - the first approval succeeds with 200.

- [ ] **Step 3: Add the gate**

In `api/services/script_review_service.py`:

```python
class NotYetReviewedError(ValueError):
    """An approval on a script nobody has read yet."""
```

and inside `record_script_review`, beside the existing already-approved check:

```python
    if decision == "approved":
        if await review_count(conn, project_id=project_id, script_id=script_id) == 0:
            raise NotYetReviewedError(
                f"script {script_id} has no reviews - it must be read before it is approved"
            )
```

- [ ] **Step 4: Map it to 409**

In `api/routers/script_reviews.py`, catch it beside `AlreadyApprovedError`, which already
establishes the pattern for a stateful refusal:

```python
        except (AlreadyApprovedError, NotYetReviewedError) as e:
            raise HTTPException(status_code=409, detail=str(e))
```

Branch on the exception type, never on the message text - a reworded message must not
reclassify the status.

- [ ] **Step 5: Run the tests, then the suite twice, then commit**

Power-check first: revert the gate in Step 3, confirm
`test_approving_an_unreviewed_script_is_refused` FAILS, report the observed status code,
restore.

```bash
git add api/services/script_review_service.py api/routers/script_reviews.py tests/test_approve_gate.py
git commit -m "feat(review): approve is refused until somebody has read the script"
```

---

### Task 4a: The caller can ask what they are allowed to do

**Files:**
- Create: `api/routers/permissions.py`
- Modify: `api/main.py` (register the router), `ui/src/api/endpoints.ts`, `ui/src/types.ts`
- Test: `tests/test_my_permissions.py`

**Interfaces:**
- Consumes: `_caller_matches_stakeholder_flag(slug, payload, *, flags) -> bool` from `api/services/commit_service.py`.
- Produces: `GET /projects/{slug}/my-permissions` returning `{"can_review": bool, "can_approve": bool}`; `projectsApi.getMyPermissions(slug) -> Promise<MyPermissions>`; `interface MyPermissions { can_review: boolean; can_approve: boolean }`.

Without this, the UI cannot know whether to offer Approve, and the alternative - offering it to
everyone and letting the server's 403 explain - teaches a reviewer that the button is broken
rather than that the action is not theirs.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_my_permissions.py
"""What the caller may do, asked once rather than inferred from a refusal.

Authority already lives in _caller_matches_stakeholder_flag - the stakeholder flags
is_reviewer and is_approver, not the login role. This endpoint reports that same decision
so the UI can offer only what the server would accept. It deliberately does not re-implement
the rule: a second copy would drift, and the copy the UI trusted would be the wrong one.
"""
from unittest.mock import AsyncMock, patch


def test_it_reports_what_the_shared_authority_check_says(client, seeded_project_slug):
    slug = seeded_project_slug
    with patch("api.routers.permissions._caller_matches_stakeholder_flag",
               new=AsyncMock(side_effect=[True, False])) as gate:
        r = client.get(f"/projects/{slug}/my-permissions")
    assert r.status_code == 200, r.text
    assert r.json() == {"can_review": True, "can_approve": False}
    # The flags each question asks are the rule; the booleans are only its shadow.
    assert gate.call_args_list[0].kwargs["flags"] == ("is_reviewer", "is_approver")
    assert gate.call_args_list[1].kwargs["flags"] == ("is_approver",)


def test_a_caller_with_neither_flag_is_told_so(client, seeded_project_slug):
    slug = seeded_project_slug
    with patch("api.routers.permissions._caller_matches_stakeholder_flag",
               new=AsyncMock(return_value=False)):
        r = client.get(f"/projects/{slug}/my-permissions")
    assert r.json() == {"can_review": False, "can_approve": False}


def test_an_unknown_project_is_404_not_a_silent_false(client):
    r = client.get("/projects/no-such-project/my-permissions")
    assert r.status_code == 404, r.text
```

Write the `seeded_project_slug` fixture against `tests/conftest.py`'s existing `client` fixture -
read it rather than inventing one. Patch where the name is **looked up**
(`api.routers.permissions`), not where it is defined: the router binds its own reference with
`from ... import`, and CLAUDE.md records four tests that got this wrong and hid a live bug for
weeks.

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_my_permissions.py -v`
Expected: FAIL - 404 on every call, because the router does not exist.

- [ ] **Step 3: Write the router**

Create `api/routers/permissions.py`:

```python
# api/routers/permissions.py
"""What the calling user may do on one project.

The rule itself lives in _caller_matches_stakeholder_flag and is not restated here. Authority
comes from the stakeholder assignment - is_reviewer and is_approver - rather than the login
role, and that helper is what commit and submission already consult.

It currently answers True for a sysadmin, and every login is sysadmin against an empty users
table, so this reports true for everyone today. That is the same latency the rest of the
authority model has, and it tightens with no change here once real accounts exist.
"""
from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_any_auth, check_project_access
from api.database import get_connection, fetch_project
from api.services.commit_service import _caller_matches_stakeholder_flag

router = APIRouter(prefix="/projects", tags=["permissions"])


@router.get("/{slug}/my-permissions")
async def get_my_permissions(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        if not await fetch_project(conn, slug=slug):
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return {
        "can_review": await _caller_matches_stakeholder_flag(
            slug, payload, flags=("is_reviewer", "is_approver")),
        "can_approve": await _caller_matches_stakeholder_flag(
            slug, payload, flags=("is_approver",)),
    }
```

Register it in `api/main.py` beside the other routers.

- [ ] **Step 4: Add the client call and type**

In `ui/src/types.ts`:

```ts
export interface MyPermissions {
  can_review: boolean
  can_approve: boolean
}
```

In `ui/src/api/endpoints.ts`:

```ts
  getMyPermissions: (slug: string): Promise<import('../types').MyPermissions> =>
    apiClient.get(`/projects/${slug}/my-permissions`).then((r) => r.data),
```

- [ ] **Step 5: Run the tests, power-check, then commit**

Power-check by swapping the two flag tuples in Step 3 and confirming the first test fails on
the `flags` assertions rather than on the booleans - the flags each question asks are the
property, and two booleans that happen to be right for the wrong reason would pass a weaker
test. Report the observed failure verbatim, then restore.

Run the full backend suite twice with identical counts, and `npx tsc --noEmit` from `ui/`.

```bash
git add api/routers/permissions.py api/main.py ui/src/api/endpoints.ts ui/src/types.ts tests/test_my_permissions.py
git commit -m "feat(auth): report what the caller may do, rather than making them find out"
```

---

### Task 5: A stale edit is refused rather than silently winning

**Files:**
- Modify: `api/routers/projects.py` (PATCH `/interview-scripts/{script_id}`)
- Test: `tests/test_interview_script_edit.py` (extend)

**Interfaces:**
- Consumes: nothing.
- Produces: `InterviewScriptPatch` gains `base_version: int | None = None`; the PATCH returns **409** when the current artefact version is newer.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_interview_script_edit.py
def test_an_edit_from_a_superseded_version_is_refused(client, seeded_scripts):
    """Several reviewers can edit, so last-write-wins silently discards somebody's work and
    they have no way to learn it happened. This codebase has already lost a human edit to a
    silent write once."""
    slug = seeded_scripts
    ledger = {r["script_id"]: r for r in client.get(f"/projects/{slug}/script-ledger").json()}
    opened_at = ledger["SC-001"]["last_version"]
    before = client.get(f"/projects/{slug}/interview-scripts").json()

    first = client.patch(f"/projects/{slug}/interview-scripts/SC-001",
                         json={"script": {**before["SC-001"], "node_label": "Ana's edit"},
                               "base_version": opened_at})
    assert first.status_code == 200, first.text

    # Bo opened the same version Ana did, and saves after her.
    second = client.patch(f"/projects/{slug}/interview-scripts/SC-001",
                          json={"script": {**before["SC-001"], "node_label": "Bo's edit"},
                                "base_version": opened_at})
    assert second.status_code == 409, second.text

    after = client.get(f"/projects/{slug}/interview-scripts").json()
    assert after["SC-001"]["node_label"] == "Ana's edit", "the first edit must survive"


def test_an_edit_with_no_base_version_still_works(client, seeded_scripts):
    """base_version is optional so an older client, or a caller with nothing to be stale
    against, is not broken by the check."""
    slug = seeded_scripts
    before = client.get(f"/projects/{slug}/interview-scripts").json()
    r = client.patch(f"/projects/{slug}/interview-scripts/SC-001",
                     json={"script": {**before["SC-001"], "node_label": "No base"}})
    assert r.status_code == 200, r.text
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/pytest tests/test_interview_script_edit.py -v`
Expected: FAIL - the second PATCH returns 200 and Bo's edit wins.

- [ ] **Step 3: Add the check**

In `api/routers/projects.py`, add `base_version: int | None = None` to `InterviewScriptPatch`,
and in `patch_interview_script`, before the write:

```python
    if body.base_version is not None:
        async with get_connection(slug) as conn:
            project = await fetch_project(conn, slug=slug)
            cur = await conn.execute(
                "SELECT last_version, last_author FROM interview_script_ledger"
                " WHERE script_id=? AND project_id=?", (script_id, project["id"]))
            held = await cur.fetchone()
        if held and held[0] is not None and held[0] > body.base_version:
            raise HTTPException(
                status_code=409,
                detail=(f"{script_id} was changed by {held[1] or 'someone else'} since you "
                        f"opened it (you have v{body.base_version}, current is v{held[0]}) - "
                        f"reopen it and reapply your changes"),
            )
```

- [ ] **Step 4: Run the tests, power-check, then the suite twice, then commit**

Revert the check, confirm `test_an_edit_from_a_superseded_version_is_refused` FAILS with Bo's
edit surviving, report it verbatim, restore.

```bash
git add api/routers/projects.py tests/test_interview_script_edit.py
git commit -m "fix(scripts): a stale edit is refused, not silently applied"
```

---

### Task 6: The review panel - reading, editing, and the three exits

**Files:**
- Create: `ui/src/components/tabs/ScriptReviewPanel.tsx`
- Modify: `ui/src/api/endpoints.ts`, `ui/src/types.ts`
- Test: `ui/src/__tests__/ScriptReviewPanel.test.tsx`

**Interfaces:**
- Consumes: `GET /projects/{slug}/interview-scripts`, `PATCH /projects/{slug}/interview-scripts/{script_id}` with `base_version`, `POST /projects/{slug}/script-ledger/{script_id}/review`.
- Produces: `<ScriptReviewPanel slug script row onClose />` where `row: ScriptLedgerRow`; `ScriptLedgerRow` gains `review_count: number`.

- [ ] **Step 1: Add the type and client call**

In `ui/src/types.ts`, add `review_count: number` to `ScriptLedgerRow`. In
`ui/src/api/endpoints.ts`, extend the script PATCH to carry the base version:

```ts
  patchInterviewScript: (slug: string, scriptId: string,
                         body: { script: unknown; base_version?: number | null }) =>
    apiClient.patch(`/projects/${slug}/interview-scripts/${scriptId}`, body).then((r) => r.data),
```

- [ ] **Step 2: Write the failing test**

```tsx
// ui/src/__tests__/ScriptReviewPanel.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ScriptReviewPanel } from '../components/tabs/ScriptReviewPanel'

const row = {
  script_id: 'SC-042', node_id: '1.4.2', node_label: 'Work Order Dispatch',
  review_status: 'pending' as const, reviewed_at_version: null,
  review_return_to: null, last_version: 3, last_author: 'interaction_designer',
  review_count: 0,
}
const script = { script_id: 'SC-042', node_id: '1.4.2', node_label: 'Work Order Dispatch',
                 level: 'L3', sections: [] }

const patchMock = vi.fn(() => Promise.resolve({}))
const reviewMock = vi.fn(() => Promise.resolve({}))
vi.mock('../api/endpoints', () => ({
  projectsApi: {
    patchInterviewScript: (...a: unknown[]) => patchMock(...a),
    reviewScript: (...a: unknown[]) => reviewMock(...a),
  },
}))

beforeEach(() => { patchMock.mockClear(); reviewMock.mockClear() })

it('records a review when the reader signs off without changing anything', async () => {
  render(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /reviewed, no changes/i }))
  await waitFor(() => expect(reviewMock).toHaveBeenCalled())
  expect(reviewMock.mock.calls[0][2]).toMatchObject({ decision: 'reviewed' })
  expect(patchMock).not.toHaveBeenCalled()
})

it('sends the version it opened, so a stale save can be refused', async () => {
  render(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.change(screen.getByLabelText(/script title/i), { target: { value: 'Retitled' } })
  fireEvent.click(screen.getByRole('button', { name: /save changes/i }))
  await waitFor(() => expect(patchMock).toHaveBeenCalled())
  expect(patchMock.mock.calls[0][2]).toMatchObject({ base_version: 3 })
})

it('records an edited review after a successful save', async () => {
  render(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.change(screen.getByLabelText(/script title/i), { target: { value: 'Retitled' } })
  fireEvent.click(screen.getByRole('button', { name: /save changes/i }))
  await waitFor(() => expect(reviewMock).toHaveBeenCalled())
  expect(reviewMock.mock.calls[0][2]).toMatchObject({ decision: 'edited' })
})

it('sends back with the note and the target the reader chose', async () => {
  render(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /send back/i }))
  fireEvent.change(screen.getByLabelText(/feedback/i), { target: { value: 'anchors are wrong' } })
  fireEvent.click(screen.getByRole('button', { name: /to maya/i }))
  await waitFor(() => expect(reviewMock).toHaveBeenCalled())
  expect(reviewMock.mock.calls[0][2]).toMatchObject({
    decision: 'changes_requested', return_to: 'agent', notes: 'anchors are wrong',
  })
})

it('surfaces a stale-save refusal rather than failing silently', async () => {
  patchMock.mockRejectedValueOnce({
    response: { data: { detail: 'SC-042 was changed by ana since you opened it' } },
  })
  render(<ScriptReviewPanel slug="p" script={script} row={row} onClose={() => {}} />)
  fireEvent.change(screen.getByLabelText(/script title/i), { target: { value: 'Mine' } })
  fireEvent.click(screen.getByRole('button', { name: /save changes/i }))
  expect(await screen.findByText(/changed by ana/i)).toBeInTheDocument()
  expect(reviewMock).not.toHaveBeenCalled()
})
```

- [ ] **Step 3: Run to verify it fails**

Run from `ui/`: `npx vitest run ScriptReviewPanel`
Expected: FAIL - cannot resolve `../components/tabs/ScriptReviewPanel`.

- [ ] **Step 4: Build the panel**

Create `ui/src/components/tabs/ScriptReviewPanel.tsx`. It renders the script for reading -
reuse `MayaOutputExtra`'s existing `ScriptCard` rendering rather than writing a second one;
read that file and export what you need. Beneath it, an editable title and the three exits.

The behaviour the tests above pin down:

- **Save changes** PATCHes with `base_version: row.last_version`, and **only on success**
  records a `edited` review. A failed save must not record a review - the reader has not
  landed a change.
- **Reviewed, no changes** records `reviewed` and writes nothing to the artefact.
- **Send back** collects a note and a target, and records `changes_requested`. Label the
  targets **"To Maya"** (`agent`) and **"To reviewers"** (`reviewer`), because "agent" and
  "reviewer" are the wire values, not what a person calls them. Disable "To Maya" while the
  note is empty - a regeneration request with no guidance tells Maya nothing.
- Any failure surfaces the server's `detail`, never a fixed string.

- [ ] **Step 5: Run the tests, then power-check**

Run from `ui/`: `npx vitest run ScriptReviewPanel`

Then power-check the two that matter: make **Save changes** record its review before awaiting
the PATCH, and confirm the stale-refusal test fails; and hardcode `return_to: 'agent'`, and
confirm the send-back test fails. Report both verbatim. Restore.

- [ ] **Step 6: Run the frontend suite and tsc, then commit**

```bash
git add ui/src/components/tabs/ScriptReviewPanel.tsx ui/src/api/endpoints.ts ui/src/types.ts ui/src/__tests__/ScriptReviewPanel.test.tsx
git commit -m "feat(ui): review a script by reading it, with three ways out"
```

---

### Task 7: The list becomes the approver's view

**Files:**
- Modify: `ui/src/components/tabs/ScriptReviewRow.tsx`, `ui/src/components/tabs/MayaOutputExtra.tsx`
- Test: `ui/src/__tests__/ScriptReviewRow.test.tsx` (extend)

**Interfaces:**
- Consumes: `ScriptReviewPanel` from Task 6, `review_count` from Task 3.
- Produces: nothing later tasks rely on.

- [ ] **Step 1: Write the failing test**

```tsx
// append to ui/src/__tests__/ScriptReviewRow.test.tsx
const base = {
  script_id: 'SC-042', node_id: '1.4.2', node_label: 'Work Order Dispatch',
  review_status: 'pending' as const, reviewed_at_version: null,
  review_return_to: null, last_version: 3, last_author: 'interaction_designer',
  review_count: 0,
}

it('identifies a script by its value chain id, not its internal script id', () => {
  // SC-042 is a citation token - it means nothing to a reviewer, while 1.4.2 is the
  // reference used consistently everywhere else in the application.
  render(<ScriptReviewRow row={base} onOpen={() => {}} onApprove={() => {}} canApprove />)
  expect(screen.getByText('1.4.2')).toBeInTheDocument()
  expect(screen.queryByText('SC-042')).not.toBeInTheDocument()
})

it('disables approve until the script has been read', () => {
  render(<ScriptReviewRow row={base} onOpen={() => {}} onApprove={() => {}} canApprove />)
  expect(screen.getByRole('button', { name: /approve/i })).toBeDisabled()
})

it('enables approve once it has a review, and shows how many', () => {
  render(<ScriptReviewRow row={{ ...base, review_count: 3 }}
                          onOpen={() => {}} onApprove={() => {}} canApprove />)
  expect(screen.getByRole('button', { name: /approve/i })).not.toBeDisabled()
  expect(screen.getByText(/3 reviews/i)).toBeInTheDocument()
})

it('offers no approve at all to somebody who is not an approver', () => {
  render(<ScriptReviewRow row={{ ...base, review_count: 3 }}
                          onOpen={() => {}} onApprove={() => {}} canApprove={false} />)
  expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
})

it('opens the script rather than judging it from the list', () => {
  const onOpen = vi.fn()
  render(<ScriptReviewRow row={base} onOpen={onOpen} onApprove={() => {}} canApprove />)
  fireEvent.click(screen.getByRole('button', { name: /open/i }))
  expect(onOpen).toHaveBeenCalledWith('SC-042')
  expect(screen.queryByRole('button', { name: /mark reviewed/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /send back/i })).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run to verify they fail**

Run from `ui/`: `npx vitest run ScriptReviewRow`
Expected: FAIL - the row still renders "Mark reviewed" and "Send back" and has no Open.

- [ ] **Step 3: Rewrite the row**

Change `ScriptReviewRow`'s props to
`{ row, onOpen, onApprove, canApprove }` where `onOpen: (scriptId: string) => void` and
`onApprove: (scriptId: string) => void`. Render the **node id** as the identity, the title, the
status, `{n} reviews`, and the staleness indicator. Keep the existing staleness computation
exactly as it is - both fields are nullable and NULL must never render as stale.

Two actions: **Open**, always; and **Approve**, rendered only when `canApprove`, disabled when
`row.review_count === 0`.

Remove the inline send-back form entirely - it now lives in the panel.

- [ ] **Step 4: Wire the list to the panel**

In `MayaOutputExtra.tsx`, hold the open script in state. `onOpen` fetches that script from the
`['interview-scripts', slug]` query already in the file and renders `ScriptReviewPanel`;
closing it invalidates both `['interview-scripts', slug]` and `['script-ledger', slug]` so the
count and status refresh.

Derive `canApprove` from `projectsApi.getMyPermissions(slug)` (Task 4a), keyed
`['my-permissions', slug]`. While the query is loading, render the row without an Approve
button rather than with a disabled one - a button that appears and then becomes clickable reads
as a bug, and a missing one that appears reads as loading.

- [ ] **Step 5: Run the tests, power-check, then commit**

Power-check by setting `review_count` to `0` in the enabled-approve test and confirming it
fails, and by rendering `SC-042` alongside the node id and confirming the identity test fails.

Run the frontend suite and `npx tsc --noEmit` from `ui/`, and `./venv/bin/pytest -q` once to
confirm the backend is untouched.

```bash
git add ui/src/components/tabs/ScriptReviewRow.tsx ui/src/components/tabs/MayaOutputExtra.tsx ui/src/__tests__/ScriptReviewRow.test.tsx
git commit -m "feat(ui): the list approves, the document reviews"
```

---

### Task 8: Prove it end to end, and record it

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Drive the whole loop against a scratch project**

Do **not** use `data/sp-gs-am.db`. On a scratch project seeded through `SQLiteStateTool`,
drive: open a script, save an edit, confirm the count is 1 and approve becomes permitted,
approve it, confirm a second approval is refused, send another script back to Maya with a note,
and confirm `scripts_awaiting_regeneration` returns exactly that one. Report each observation.

- [ ] **Step 2: Confirm the retired layer left nothing behind**

```bash
grep -rn "node_template_assignments\|auto_assign_interview_scripts\|node-templates\|publish_node_template" api/ agents/ ui/src/
```

Expected: no hits outside comments recording the retirement. Report anything else.

- [ ] **Step 3: Run both suites**

`./venv/bin/pytest -q` twice with identical counts, then from `ui/`:
`npx vitest run && npx tsc --noEmit`.

- [ ] **Step 4: Update CLAUDE.md**

Remove the two known-issues entries this work resolves - `publish_node_template` looking up by
`node_label`, and `api/routers/interviews.py` reading a bare `interview_scripts.json` if Task 2
removed it. Verify each claim below against the code before writing it, then add under
**Frontend conventions**:

```markdown
Reviewing an interview script happens in the document, not the list. `ScriptReviewRow` is the
approver's view - node id, title, status, review count, and a gated Approve - and
`ScriptReviewPanel` is where a reviewer reads the instrument and leaves by one of three exits,
each of which records a review: `edited`, `changes_requested`, or `reviewed`. `approved` is
excluded from the count so an approval cannot satisfy its own gate, and the gate is enforced in
`record_script_review`, not only by a disabled button.

A script is shown by its value chain node id. `script_id` remains the identity - stakeholder
assignments and stored answers cite it - and is never displayed.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record where reviewing happens and what the count means"
```

---

## Self-Review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| `interview_sessions` gains `script_id`; citation no longer matches labels | 1 |
| Template layer removed - table, service, routes, UI | 2 |
| Dead questionnaire branch removed | 2 |
| `script_reviews.decision` gains `edited` | 3 |
| Review count derived, never stored, on the ledger endpoint | 3 |
| All three reading exits count; `approved` excluded | 3 |
| Approve gated server-side on ≥ 1 review | 4 |
| One person may review then approve | 4 |
| Caller can ask what they may do (approve gate legible in the UI) | 4a |
| Version conflict refused with 409 | 5 |
| Reviewing happens in the document, three exits | 6 |
| Send-back carries a note and a target | 6 |
| List shows node id, count, gated Approve | 7 (gate driven by 4a) |
| End-to-end proof and CLAUDE.md | 8 |
| Soft revert, retirement door, review workbench | none - deferred by the spec |

**Placeholder scan:** none. Four steps direct the implementer to read real code rather than
trust the plan - Task 2 Step 1's dependency sweep, Task 4 Step 1's fixture, Task 6 Step 4's
reuse of `ScriptCard`, and Task 7 Step 4's query wiring - stated explicitly because briefs on
this project have been wrong about details repeatedly.

**Type consistency:** `review_count(conn, *, project_id, script_id) -> int` is defined in Task 3
and consumed in Tasks 3 and 4. `NotYetReviewedError(ValueError)` is defined in Task 4 and caught
in the same task. `ScriptLedgerRow.review_count: number` is added in Task 6 Step 1 and consumed
in Tasks 6 and 7. `ScriptReviewPanel`'s props - `slug`, `script`, `row`, `onClose` - match
between Task 6's tests and Task 7's wiring. `ScriptReviewRow`'s new props - `row`, `onOpen`,
`onApprove`, `canApprove` - are introduced and consumed in Task 7 only.

**One ordering note:** Task 2 removes the Setup tab's "Edit Script" action before Task 6 builds
its replacement, so between those commits there is no way to edit a script from the UI. That is
deliberate: the alternative leaves two editors live at once, one of them writing through a path
the branch is deleting, and a reviewer could reach the wrong one. No interview depends on
editing in that window.
