# Feedback Capture and Change Requests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture the reviewer's intent alongside their feedback, and make change requests actually reach the agent on its next run.

**Architecture:** `output_changes` becomes the capture queue for every piece of feedback, gaining a `kind` that records the reviewer's intent and a `status` that stops a request being replayed forever. `run_service` injects open change requests beside the existing skill-notes injection. Nothing is moved out of the queue - later stages copy from it.

**Tech Stack:** Python 3.13, FastAPI, aiosqlite (raw SQL, no ORM), React 18 + TypeScript + Vite, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-06-reviewer-feedback-loop-design.md` - this plan is **stage 1 of 3**.

**Baseline:** 1050 backend passed / 2 skipped, 360 frontend passed, `tsc --noEmit` silent.

## Global Constraints

- **British English throughout** - `-ise` not `-ize`, `-our` not `-or`, `-re` not `-er`, `-ogue` not `-og`.
- **Spaced hyphen ` - ` in all content, never an em dash.** Oxford comma in lists of three or more.
- **No emoji in rendered web content.** Lucide React icons only.
- **Tailwind brand tokens** - `text-brand`, `bg-surface`, `text-primary`, `text-secondary`, `text-muted`. Never `sky-*` or `blue-*`. Semantic `text-red-*`, `text-emerald-*` and `text-amber-*` are established convention and permitted.
- **All raw SQL lives in `api/database.py`.** Schema changes run on connection open and must also be added to any test fixture that creates that table by hand.
- **Never modify `agents/tools/human_input.py`.**
- **Never run `git add -A` or `git add .`** - stage the exact paths each task lists.
- **Backend tests:** `./venv/bin/pytest -q --ignore=tests/integration`
- **Frontend tests:** `cd ui && npx vitest run` and `cd ui && npx tsc --noEmit`
- **Run the backend suite twice before claiming green.** `tests/conftest.py` points `DATABASE_DIR` at a fixed `/tmp/agentpool_test` that persists between runs, so a test that poisons its own database passes once and fails afterwards. That defect blocked a merge after passing eight task reviews.
- **Never execute anything against `data/sp-gs-am.db` or anything under `projects/`.** Live client data.

## Not in this plan

**Corrections** (stage 2) and **skills promotion** (stage 3). This stage records intent; only `change_request` is acted upon. A row classified `correction` or `skill` is captured and left for its stage.

**The existing ungated skill-note path.** `ReviewDialog.tsx:410` already posts free text to the global `agent_skill_notes` on rejection, bypassing any gate, and `_fetch_skill_notes` injects it into every project's runs for that agent. Stage 3 puts the curator gate in front of it. **This stage must not regress that behaviour and must not extend it** - leave the existing call exactly as it is.

## File Structure

| File | Responsibility |
|---|---|
| `api/database.py` | The `output_changes` migration, and helpers to fetch open change requests and mark them applied. |
| `api/routers/reviews.py` | Accepts and records the reviewer's intent. |
| `api/services/value_chain_store.py` | Records a rationale on manual edit, without blocking the save. |
| `api/services/run_service.py` | Injects open change requests; marks them applied. |
| `ui/src/components/ReviewDialog.tsx` | The three-way intent choice. |

---

### Task 1: The output_changes migration and helpers

**Files:**
- Modify: `api/database.py`
- Test: `tests/test_output_change_lifecycle.py` (create)

**Interfaces:**
- Produces: `fetch_open_change_requests(conn, *, output_ids) -> list[dict]`; `mark_change_requests_applied(conn, *, change_ids, run_id) -> int`. Task 4 consumes both.

**Why:** the queue needs to record what kind of feedback each row is, and whether a change request has already been acted upon. Without `status`, every run carries every change request ever made and the injected block grows without bound until it drowns the task description.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_output_change_lifecycle.py`:

```python
# tests/test_output_change_lifecycle.py
"""A change request is injected once, then never again.

Without a lifecycle every run carries every request ever made, and the block that carries
them grows until it crowds out the task it is attached to.
"""
import pytest
import pytest_asyncio

from api.database import (
    fetch_open_change_requests,
    get_connection,
    insert_output_change,
    insert_project,
    mark_change_requests_applied,
)

SLUG = "change-lifecycle-test"


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield
    get_settings.cache_clear()


async def _output(conn, output_type="value_chain_model", version=1):
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
        " version, is_current, review_status) VALUES (1,'value_chain_mapper',?,?,?,1,'pending')",
        (output_type, f"{output_type}_v{version}.json", version),
    )
    await conn.commit()
    return cur.lastrowid


@pytest.mark.asyncio
async def test_a_new_change_defaults_to_unclassified_and_open(project):
    """An unexplained manual edit must land somewhere, not nowhere."""
    async with get_connection(SLUG) as conn:
        output_id = await _output(conn)
        change_id = await insert_output_change(
            conn, output_id=output_id, requested_by="alice", source="edit",
            request="trimmed the summary", summary="",
        )
        row = await conn.execute_fetchall(
            "SELECT kind, status FROM output_changes WHERE id=?", (change_id,)
        )

    assert tuple(row[0]) == ("unclassified", "open")


@pytest.mark.asyncio
async def test_only_change_requests_are_fetched_for_injection(project):
    """A correction reaches the agent through RAG and a skill through the prompt library.
    Injecting them here as well would say the same thing twice, in the wrong voice."""
    async with get_connection(SLUG) as conn:
        output_id = await _output(conn)
        for kind in ("change_request", "correction", "skill", "unclassified"):
            await insert_output_change(
                conn, output_id=output_id, requested_by="alice", source="review",
                request=f"a {kind}", summary="", kind=kind,
            )
        rows = await fetch_open_change_requests(conn, output_ids=[output_id])

    assert [r["request"] for r in rows] == ["a change_request"]


@pytest.mark.asyncio
async def test_an_applied_request_is_not_fetched_again(project):
    async with get_connection(SLUG) as conn:
        output_id = await _output(conn)
        change_id = await insert_output_change(
            conn, output_id=output_id, requested_by="alice", source="review",
            request="use the approved figures", summary="", kind="change_request",
        )
        first = await fetch_open_change_requests(conn, output_ids=[output_id])
        marked = await mark_change_requests_applied(
            conn, change_ids=[change_id], run_id=77
        )
        second = await fetch_open_change_requests(conn, output_ids=[output_id])
        row = await conn.execute_fetchall(
            "SELECT status, applied_run_id FROM output_changes WHERE id=?", (change_id,)
        )

    assert len(first) == 1
    assert marked == 1
    assert second == []
    assert tuple(row[0]) == ("applied", 77)


@pytest.mark.asyncio
async def test_marking_nothing_is_safe(project):
    """The caller marks whatever it injected. Injecting nothing is the ordinary case on a
    first run, and must not raise or build an empty IN () clause."""
    async with get_connection(SLUG) as conn:
        assert await mark_change_requests_applied(conn, change_ids=[], run_id=77) == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_output_change_lifecycle.py -q`
Expected: FAIL - `cannot import name 'fetch_open_change_requests' from 'api.database'`

- [ ] **Step 3: Add the migration**

In `api/database.py`, add beside the other migrations, following the `PRAGMA table_info` pattern used by `_migrate_interview_sessions_ratings`:

```python
async def _migrate_output_changes_kind(conn: aiosqlite.Connection) -> None:
    """Record what kind of feedback a change is, and whether it has been acted upon.

    kind carries the reviewer's intent - a correction and a skill are captured here but
    reach the agent through RAG and the skill library respectively, so only a
    change_request is ever injected. status stops a request being replayed on every run
    thereafter.
    """
    async with conn.execute("PRAGMA table_info(output_changes)") as cur:
        cols = {row["name"] async for row in cur}
    if "kind" not in cols:
        await conn.execute(
            "ALTER TABLE output_changes ADD COLUMN kind TEXT NOT NULL DEFAULT 'unclassified'"
        )
    if "status" not in cols:
        await conn.execute(
            "ALTER TABLE output_changes ADD COLUMN status TEXT NOT NULL DEFAULT 'open'"
        )
    if "applied_run_id" not in cols:
        await conn.execute("ALTER TABLE output_changes ADD COLUMN applied_run_id INTEGER")
    await conn.commit()
```

Register it in `get_connection` beside the other `_migrate_*` calls, and add the three columns to the `CREATE TABLE output_changes` statement so fresh databases have them without the migration.

- [ ] **Step 4: Add the helpers**

In `api/database.py`, beside the existing `insert_output_change` and `fetch_output_changes`:

```python
async def fetch_open_change_requests(
    conn: aiosqlite.Connection, *, output_ids: list[int]
) -> list[dict]:
    """Open change requests for these outputs, oldest first.

    Only kind='change_request'. A correction reaches the agent through RAG and a skill
    through the prompt library; injecting them here too would say the same thing twice.
    """
    if not output_ids:
        return []
    marks = ",".join("?" * len(output_ids))
    async with conn.execute(
        f"SELECT * FROM output_changes"
        f" WHERE output_id IN ({marks}) AND kind='change_request' AND status='open'"
        f" ORDER BY id ASC",
        tuple(output_ids),
    ) as cur:
        return [dict(row) async for row in cur]


async def mark_change_requests_applied(
    conn: aiosqlite.Connection, *, change_ids: list[int], run_id: int | None
) -> int:
    """Close the requests a run consumed. Returns rows changed.

    An empty list is the ordinary case on a first run and must not build an IN () clause.
    """
    if not change_ids:
        return 0
    marks = ",".join("?" * len(change_ids))
    cur = await conn.execute(
        f"UPDATE output_changes SET status='applied', applied_run_id=?"
        f" WHERE id IN ({marks}) AND status='open'",
        (run_id, *change_ids),
    )
    await conn.commit()
    return cur.rowcount
```

Add a `kind: str = "unclassified"` keyword parameter to `insert_output_change` and include it in the INSERT.

- [ ] **Step 5: Run and commit**

Run: `./venv/bin/pytest tests/test_output_change_lifecycle.py -q` - expect 4 passed.
Run: `./venv/bin/pytest -q --ignore=tests/integration` **twice** - expect 1054 passed / 2 skipped both times.
Run: `cd ui && npx vitest run && npx tsc --noEmit` - expect 360 passed, tsc silent.

```bash
git add api/database.py tests/test_output_change_lifecycle.py
git commit -m "feat(feedback): record the kind and lifecycle of a change request"
```

---

### Task 2: Reviewers record their intent

**Files:**
- Modify: `api/routers/reviews.py`
- Test: `tests/test_review_intent.py` (create)

**Interfaces:**
- Consumes: `insert_output_change` with `kind`, from Task 1.

**Why:** the rationale decides the destination, and only the reviewer holds it. "Remove that number" is a correction, a skill, or a one-off depending entirely on why - no classifier can tell from the edit alone.

- [ ] **Step 1: Write the failing test**

Create `tests/test_review_intent.py`:

```python
# tests/test_review_intent.py
"""The reviewer's intent is captured with their words, or defaults to the harmless one."""
import pytest

SLUG = "review-intent-test"
PROJECT = {
    "client_slug": SLUG, "llm_mode": "standard", "sector": "utilities",
    "stakeholder_groups": [], "value_stream_labels": [], "crews_enabled": ["requirements"],
    "review_gates": True, "slack_channel": "",
}


async def _seed_review(client) -> tuple[int, int]:
    """Create a project with one output and one pending review. Returns (review_id, output_id)."""
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection

    async with get_connection(SLUG) as conn:
        cur = await conn.execute(
            "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
            " version, is_current, review_status)"
            " VALUES (1,'value_chain_mapper','value_chain_model','m_v1.json',1,1,'pending')"
        )
        output_id = cur.lastrowid
        cur = await conn.execute(
            "INSERT INTO human_reviews (output_id, decision) VALUES (?, 'pending')",
            (output_id,),
        )
        review_id = cur.lastrowid
        await conn.commit()
    return review_id, output_id


@pytest.mark.asyncio
async def test_intent_is_recorded_against_the_output(client):
    review_id, output_id = await _seed_review(client)

    resp = await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": "ISS only maintains property",
              "intent": "correction"},
    )
    assert resp.status_code == 200

    from api.database import get_connection

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT kind, request FROM output_changes WHERE output_id=?", (output_id,)
        )
    assert tuple(rows[0]) == ("correction", "ISS only maintains property")


@pytest.mark.asyncio
async def test_no_intent_given_defaults_to_change_request(client):
    """The default is the option with no persistence beyond the next run. A reviewer in a
    hurry must not be able to seed project truth or the global library by accident."""
    review_id, output_id = await _seed_review(client)

    await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": "tighten the summary"},
    )

    from api.database import get_connection

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT kind FROM output_changes WHERE output_id=?", (output_id,)
        )
    assert rows[0][0] == "change_request"


@pytest.mark.asyncio
async def test_approving_records_no_change(client):
    """An approval is not feedback. Recording one would inject an instruction to do nothing."""
    review_id, output_id = await _seed_review(client)

    await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "approved", "notes": ""},
    )

    from api.database import get_connection

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT COUNT(*) FROM output_changes WHERE output_id=?", (output_id,)
        )
    assert rows[0][0] == 0


@pytest.mark.asyncio
async def test_an_unknown_intent_is_rejected(client):
    review_id, _ = await _seed_review(client)

    resp = await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": "x", "intent": "whatever"},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_review_intent.py -q`
Expected: FAIL - no `output_changes` row is written, so the first assertion finds no row.

- [ ] **Step 3: Accept and record the intent**

In `api/routers/reviews.py`, extend the request model and the handler:

```python
_INTENTS = ("change_request", "correction", "skill")


class HITLReviewRequest(BaseModel):
    decision: str   # "approved" | "changes_requested"
    notes: str = ""
    intent: str = "change_request"
```

In `resolve_hitl_review`, after `update_review` succeeds, validate and record:

```python
    if req.intent not in _INTENTS:
        raise HTTPException(
            status_code=422, detail=f"intent must be one of {', '.join(_INTENTS)}"
        )
    # An approval is not feedback. Recording one would inject an instruction to do nothing.
    if req.decision == "changes_requested" and req.notes.strip():
        review = await fetch_review(conn, review_id=review_id)
        if review and review.get("output_id"):
            await insert_output_change(
                conn,
                output_id=review["output_id"],
                requested_by=payload.get("sub", "unknown"),
                source="review",
                request=req.notes.strip(),
                summary="",
                kind=req.intent,
            )
```

Validate the intent **before** `update_review` runs, so a bad request does not half-apply. Import `insert_output_change` and whatever helper reads a review row by id; if no such helper exists, add one to `api/database.py` rather than writing SQL in the router.

- [ ] **Step 4: Run and commit**

Run: `./venv/bin/pytest tests/test_review_intent.py -q` - expect 4 passed.
Run: `./venv/bin/pytest -q --ignore=tests/integration` **twice** - expect 1058 passed / 2 skipped.
Run: `cd ui && npx vitest run && npx tsc --noEmit`.

```bash
git add api/routers/reviews.py api/database.py tests/test_review_intent.py
git commit -m "feat(feedback): capture the reviewer's intent with their feedback"
```

---

### Task 3: A manual edit can carry a rationale, and still saves without one

**Files:**
- Modify: `api/services/value_chain_store.py`
- Test: `tests/test_manual_edit_rationale.py` (create)

**Interfaces:**
- Consumes: `insert_output_change` with `kind`, from Task 1.

**Why:** today a manual edit records `source="edit"` with no rationale and nothing reads it, so the next run silently reverts the edit. That is worse than the review path, because the reviewer believes they have fixed it.

**Demanding a rationale before someone can save is how people stop editing.** The save must never be blocked.

- [ ] **Step 1: Write the failing test**

Create `tests/test_manual_edit_rationale.py`:

```python
# tests/test_manual_edit_rationale.py
"""A manual edit may explain itself. It must save either way.

Blocking a save to demand a rationale is how people stop editing, and an unexplained edit
recorded as unclassified is still better than an edit silently reverted on the next run.
"""
import pytest
import pytest_asyncio

from api.database import get_connection, insert_project

SLUG = "manual-edit-test"


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    (tmp_path / "projects" / SLUG / "outputs").mkdir(parents=True)
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_an_edit_with_a_rationale_records_the_intent(project):
    from api.services.value_chain_store import save_value_chain_model

    await save_value_chain_model(
        SLUG, {"segments": []}, saved_by="alice",
        rationale="ISS only maintains property", intent="correction",
    )

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT kind, request FROM output_changes ORDER BY id DESC"
        )
    assert tuple(rows[0]) == ("correction", "ISS only maintains property")


@pytest.mark.asyncio
async def test_an_edit_without_a_rationale_still_saves(project):
    """The load-bearing case. An unexplained edit lands unclassified for later triage."""
    from api.services.value_chain_store import save_value_chain_model

    output_id = await save_value_chain_model(SLUG, {"segments": []}, saved_by="alice")

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT kind FROM output_changes ORDER BY id DESC"
        )
    assert output_id is not None
    assert rows[0][0] == "unclassified"
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_manual_edit_rationale.py -q`
Expected: FAIL - `save_value_chain_model() got an unexpected keyword argument 'rationale'`

Read the real signature first; the function name in this plan is indicative and the actual name in `value_chain_store.py` governs. If it differs, use the real one and say so in your report.

- [ ] **Step 3: Accept the rationale**

In `api/services/value_chain_store.py`, add `rationale: str = ""` and `intent: str = "change_request"` keyword parameters, and pass them through to the existing `insert_output_change` call:

```python
        await insert_output_change(
            conn,
            output_id=output_id,
            requested_by=saved_by,
            source="edit",
            # The reviewer's words when they gave them, otherwise the mechanical summary -
            # which is a record that an edit happened, not a reason it did.
            request=rationale.strip() or summary,
            summary=f"saved value chain model version {version}",
            kind=intent if rationale.strip() else "unclassified",
        )
```

An edit with no rationale is `unclassified`, whatever intent was passed - an intent with no reason behind it is a button press, not a judgement.

- [ ] **Step 4: Run and commit**

Run: `./venv/bin/pytest tests/test_manual_edit_rationale.py -q` - expect 2 passed.
Run both suites, backend twice - expect 1060 passed / 2 skipped.

```bash
git add api/services/value_chain_store.py tests/test_manual_edit_rationale.py
git commit -m "feat(feedback): a manual edit can explain itself without being blocked"
```

---

### Task 4: Change requests reach the agent, once

**Files:**
- Modify: `api/services/run_service.py`
- Test: `tests/test_change_request_injection.py` (create)

**Interfaces:**
- Consumes: `fetch_open_change_requests`, `mark_change_requests_applied` from Task 1.

**Why:** this is the point of the stage. Everything above records intent; this is what makes a change request change anything.

- [ ] **Step 1: Write the failing test**

Create `tests/test_change_request_injection.py`:

```python
# tests/test_change_request_injection.py
"""Open change requests reach the agent's task, then stop.

A request injected on every subsequent run would grow the block without bound until it
crowded out the task it was attached to.
"""
import pytest
import pytest_asyncio

from api.database import get_connection, insert_output_change, insert_project

SLUG = "injection-test"


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield
    get_settings.cache_clear()


async def _output(conn, *, is_current=1, version=1):
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
        " version, is_current, review_status)"
        " VALUES (1,'value_chain_mapper','value_chain_model',?,?,?,'pending')",
        (f"m_v{version}.json", version, is_current),
    )
    await conn.commit()
    return cur.lastrowid


@pytest.mark.asyncio
async def test_open_requests_are_gathered_for_the_crew(project):
    from api.services.run_service import _fetch_change_requests

    async with get_connection(SLUG) as conn:
        output_id = await _output(conn)
        await insert_output_change(
            conn, output_id=output_id, requested_by="alice", source="review",
            request="use the approved figures", summary="", kind="change_request",
        )

    text, ids = await _fetch_change_requests(SLUG, "discovery_mapping")

    assert "use the approved figures" in text
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_a_request_against_a_superseded_output_is_not_replayed(project):
    """Scoped to current outputs, matching how commit_service already scopes them."""
    from api.services.run_service import _fetch_change_requests

    async with get_connection(SLUG) as conn:
        old = await _output(conn, is_current=0, version=1)
        await _output(conn, is_current=1, version=2)
        await insert_output_change(
            conn, output_id=old, requested_by="alice", source="review",
            request="an old request", summary="", kind="change_request",
        )

    text, ids = await _fetch_change_requests(SLUG, "discovery_mapping")

    assert text == ""
    assert ids == []


@pytest.mark.asyncio
async def test_a_crew_with_no_requests_gathers_nothing(project):
    """The ordinary first run. Must return empty rather than an empty heading."""
    from api.services.run_service import _fetch_change_requests

    async with get_connection(SLUG) as conn:
        await _output(conn)

    text, ids = await _fetch_change_requests(SLUG, "discovery_mapping")

    assert text == ""
    assert ids == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `./venv/bin/pytest tests/test_change_request_injection.py -q`
Expected: FAIL - `cannot import name '_fetch_change_requests' from 'api.services.run_service'`

- [ ] **Step 3: Gather the requests**

In `api/services/run_service.py`, beside `_fetch_skill_notes`:

```python
async def _fetch_change_requests(slug: str, crew_name: str) -> tuple[str, list[int]]:
    """Open change requests for this crew's current outputs, and the ids to close after.

    Scoped to current outputs, the same scoping commit_service already uses, so a request
    against a superseded version is not replayed against its replacement.
    """
    from api.database import (
        fetch_agent_outputs, fetch_open_change_requests, fetch_project,
    )
    agents = set(_CREW_AGENT_NAMES.get(crew_name, []))
    if not agents:
        return "", []
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return "", []
        outputs = await fetch_agent_outputs(conn, project_id=project["id"])
        output_ids = [
            o["id"] for o in outputs if o["agent_name"] in agents and o.get("is_current")
        ]
        rows = await fetch_open_change_requests(conn, output_ids=output_ids)
    if not rows:
        return "", []
    lines = "\n".join(f"- {r['request']}" for r in rows)
    header = (
        "REQUESTED CHANGES (a reviewer asked for these on your last output; apply them):\n"
    )
    return header + lines, [r["id"] for r in rows]
```

- [ ] **Step 4: Inject and close**

In the same file, at the injection site beside the existing skill-notes block:

```python
    change_text, change_ids = await _fetch_change_requests(slug, crew_name)
    if change_text:
        for task in crew.tasks:
            task.description = change_text + "\n\n" + task.description

    result = await crew.kickoff_async()

    if change_ids:
        try:
            async with get_connection(slug) as conn:
                await mark_change_requests_applied(
                    conn, change_ids=change_ids, run_id=run_id
                )
        except Exception:
            # A request left open is re-injected next run, which is noisy but harmless.
            # Failing the run because bookkeeping failed would discard completed work.
            log.exception("could not close change requests for %s", crew_name)

    return result
```

Requests are closed **after** the run completes, not before. Closing first would lose them if the run failed, and the whole point is that a reviewer's request survives until it is acted on. Read the real variable names for the run id and logger in that function rather than assuming these.

- [ ] **Step 5: Run and commit**

Run: `./venv/bin/pytest tests/test_change_request_injection.py -q` - expect 3 passed.
Run both suites, backend twice - expect 1063 passed / 2 skipped, 360 frontend.

```bash
git add api/services/run_service.py tests/test_change_request_injection.py
git commit -m "feat(feedback): change requests reach the agent and are closed once applied"
```

---

### Task 5: The reviewer chooses an intent

**Files:**
- Modify: `ui/src/components/ReviewDialog.tsx`, `ui/src/api/endpoints.ts`
- Test: `ui/src/__tests__/ReviewIntent.test.tsx` (create)

**Interfaces:**
- Consumes: `PATCH /projects/{slug}/reviews/{id}` with `intent`, from Task 2.

**Why:** the reviewer is the only one who holds the rationale, and the wording must be in their language. They do not think "is this a skill" - they think "should this happen again".

- [ ] **Step 1: Write the failing test**

Create `ui/src/__tests__/ReviewIntent.test.tsx`:

```typescript
// ui/src/__tests__/ReviewIntent.test.tsx
// The reviewer chooses in their own words. The default is the option that persists nothing,
// so a reviewer in a hurry cannot seed project truth or the global library by accident.
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import ReviewDialog from '../components/ReviewDialog'

const resolveReview = vi.fn().mockResolvedValue({})

vi.mock('../api/endpoints', () => ({
  projectsApi: { resolveReview: (...a: unknown[]) => resolveReview(...a) },
  skillNotesApi: { create: vi.fn().mockResolvedValue({}) },
}))

const review = {
  id: 1, crew_name: 'discovery_mapping', prompt: 'Please review the value chain.',
  decision: 'pending',
}

function Wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <ReviewDialog slug="acme" review={review as never} outputs={[]} onClose={() => {}} />
    </QueryClientProvider>
  )
}

describe('review intent', () => {
  beforeEach(() => resolveReview.mockClear())

  it('offers the three choices in the reviewer\'s language', async () => {
    render(<Wrapper />)
    fireEvent.click(screen.getByRole('button', { name: /request changes/i }))
    expect(screen.getByLabelText(/fix this output/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/true of this client/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/every project/i)).toBeInTheDocument()
  })

  it('defaults to fixing this output', async () => {
    render(<Wrapper />)
    fireEvent.click(screen.getByRole('button', { name: /request changes/i }))
    expect(screen.getByLabelText(/fix this output/i)).toBeChecked()
  })

  it('sends the chosen intent', async () => {
    render(<Wrapper />)
    fireEvent.click(screen.getByRole('button', { name: /request changes/i }))
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'ISS only maintains property' },
    })
    fireEvent.click(screen.getByLabelText(/true of this client/i))
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() =>
      expect(resolveReview).toHaveBeenCalledWith(
        'acme', 1, 'changes_requested', 'ISS only maintains property', 'correction',
      ),
    )
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && npx vitest run src/__tests__/ReviewIntent.test.tsx`
Expected: FAIL - no element matches `/fix this output/i`.

Read `ReviewDialog.tsx` before implementing. The button labels above are indicative; use whatever the component actually renders for its revise action, and adjust the test's queries to match rather than renaming working UI. Say in your report which labels you used.

- [ ] **Step 3: Add the choice**

Add a three-option radio group inside the revise branch, above the notes textarea, using the brand tokens:

- `Fix this output` - value `change_request`, **checked by default**
- `This is true of this client` - value `correction`
- `Do this on every project` - value `skill`

Each option carries a one-line explanation in `text-muted` of what it means: applies to the next run only; becomes a standing fact for this client; becomes a capability this agent uses everywhere.

Extend `projectsApi.resolveReview` in `ui/src/api/endpoints.ts` to take and send `intent`, defaulting to `'change_request'` so existing callers are unaffected.

**Leave the existing `skillNotesApi.create` call on the reject path exactly as it is.** Gating it belongs to stage 3, and changing it here would either regress the current behaviour or extend an ungated path.

- [ ] **Step 4: Run both suites and commit**

Run: `cd ui && npx vitest run && npx tsc --noEmit` - expect 363 passed, tsc silent.
Run: `./venv/bin/pytest -q --ignore=tests/integration` **twice** - expect 1063 passed / 2 skipped, unchanged.

```bash
git add ui/src/components/ReviewDialog.tsx ui/src/api/endpoints.ts \
  ui/src/__tests__/ReviewIntent.test.tsx
git commit -m "feat(ui): reviewers choose what should happen to their feedback"
```

---

## After the last task

Restart the API server so the `output_changes` migration runs against existing project databases.

Stage 2 (corrections) and stage 3 (skills promotion) follow, per the spec. Until stage 3 lands, a row classified `skill` is captured and acted upon by nobody, and the pre-existing ungated path at `ReviewDialog.tsx`'s reject branch still writes directly to the global library.
