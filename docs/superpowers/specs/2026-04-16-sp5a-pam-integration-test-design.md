# SP5a — PAM Pipeline Integration Test
## Design Specification
**Date:** 2026-04-16
**Status:** Approved for implementation planning
**Branch base:** `master` (post SP4c merge)
**Working directory:** `/Users/pboagents/Documents/agentpool1`

---

## 1. Scope

Add a single end-to-end integration test for the PAM orchestration pipeline. The test calls `run_pam_crew()` directly with all five specialist crews running sequentially via `RunCrewTool`, verifies the `orchestration_runs` and `crew_runs` DB lifecycle, and checks that each crew produced its key output file.

**In scope:**
- `tests/integration/test_pam_orchestration.py` — one `@pytest.mark.integration` test
- Fixtures in the test file (slug, project_id, ChromaDB collection)
- LLM patch to Haiku for all six LLM clients (PAM + 5 sub-crews)
- `N8N_WEBHOOK_URL=""` override so `SlackNotifyTool` skips gracefully

**Out of scope:**
- HTTP layer (`POST /orchestrate` endpoint) — tested adequately in unit tests
- Retry / failure path (RunCrewTool error branch) — covered by unit tests
- Live Slack notifications

---

## 2. Architecture

```
test_pam_pipeline_end_to_end
  ├─ Setup fixtures
  │    ├─ test_slug_pam: "test-pam-{8hex}" (function scope)
  │    ├─ project_id_pam: insert project row + config.yaml with all crew fields
  │    └─ chroma_collection_pam: creates ChromaDB collection for slug
  │
  ├─ Patches (for test duration)
  │    ├─ agents.llm.get_crew_llm → get_test_llm()  (all sub-crews use Haiku)
  │    ├─ agents.llm.get_pam_llm  → get_test_llm()  (PAM itself uses Haiku)
  │    └─ N8N_WEBHOOK_URL env var → ""               (SlackNotifyTool skips)
  │
  ├─ Execution
  │    ├─ insert orchestration_run record (status="running")
  │    └─ asyncio.run(run_pam_crew(slug, orchestration_run_id))
  │
  └─ Assertions
       ├─ orchestration_runs.status == "completed"
       ├─ crew_runs: 5 rows, all status == "completed",
       │             one per crew (discovery, value_design, architecture,
       │             delivery, business_plan)
       └─ output files (one per crew):
            discovery     → outputs/value_chain.md
            value_design  → outputs/value_propositions.json
            architecture  → outputs/architecture_register.json
            delivery      → outputs/roadmap.html
            business_plan → outputs/business_plan.docx
```

---

## 3. File Layout

```
tests/
  integration/
    test_pam_orchestration.py    ← new
```

No other files are created or modified. The existing `tests/integration/conftest.py` (which sets `HITL_AUTO_RESPOND`, loads real API keys, and overrides `DATABASE_DIR`/`PROJECTS_DIR`) applies automatically.

---

## 4. Fixtures

All fixtures are defined in `test_pam_orchestration.py` — no changes to the shared conftest.

**`test_slug_pam` (function scope):**
```python
@pytest.fixture
def test_slug_pam() -> str:
    return f"test-pam-{uuid.uuid4().hex[:8]}"
```

**`project_id_pam` (function scope):**
- Creates `{PROJECTS_DIR}/{slug}/config.yaml` with all required fields:
  ```yaml
  llm_mode: standard
  sector: logistics
  stakeholder_groups: ["Operations", "Technology"]
  value_stream_labels: ["Asset Management", "Customer Delivery"]
  roadmap_time_axis: quarters
  crews_enabled:
    - discovery
    - value_design
    - architecture
    - delivery
    - business_plan
  review_gates: true
  slack_channel: ""
  ```
- Inserts a project row into SQLite via `aiosqlite` (matches existing integration test pattern)
- Returns the integer project ID

**`chroma_collection_pam` (function scope):**
- Creates a ChromaDB collection named `{slug}` using the existing `chroma_client` fixture from the shared conftest
- Teardown: deletes the collection after the test

---

## 5. LLM Patching

Two patches applied via `unittest.mock.patch` for the duration of the test:

```python
with patch("agents.llm.get_crew_llm", return_value=get_test_llm()), \
     patch("agents.llm.get_pam_llm", return_value=get_test_llm()):
    asyncio.run(run_pam_crew(slug, orchestration_run_id))
```

`get_test_llm()` returns `claude-haiku-4-5-20251001`. Patching at the `agents.llm` module level means every call to either function — whether from `build_and_run_crew` dispatching a sub-crew or from `create_pam_crew` setting up PAM — resolves to Haiku.

---

## 6. N8N / SlackNotifyTool Handling

`os.environ["N8N_WEBHOOK_URL"] = ""` is set before the test and restored via `monkeypatch` or a context manager. `SlackNotifyTool._run()` checks `if not settings.n8n_webhook_url: return "notification skipped"` — so all five PAM notification steps skip cleanly without raising.

`get_settings.cache_clear()` is called after setting the env var to force re-evaluation.

---

## 7. Assertions

```python
# 1. orchestration_runs record completed
with sqlite3.connect(db_path) as conn:
    row = conn.execute(
        "SELECT status FROM orchestration_runs WHERE id=?",
        (orchestration_run_id,)
    ).fetchone()
assert row[0] == "completed"

# 2. Five crew_run records, all completed
with sqlite3.connect(db_path) as conn:
    rows = conn.execute(
        "SELECT crew_name, status FROM crew_runs WHERE project_id=?",
        (project_id,)
    ).fetchall()
crew_map = {row[0]: row[1] for row in rows}
for name in ("discovery", "value_design", "architecture", "delivery", "business_plan"):
    assert crew_map.get(name) == "completed", f"{name} crew_run not completed"

# 3. Key output files per crew
outputs = Path(settings.projects_dir) / slug / "outputs"
assert (outputs / "value_chain.md").exists()
assert (outputs / "value_propositions.json").exists()
assert (outputs / "architecture_register.json").exists()
assert (outputs / "roadmap.html").exists()
assert (outputs / "business_plan.docx").exists()
```

---

## 8. Run Command

```bash
pytest tests/integration/test_pam_orchestration.py -v -m integration
```

Estimated run time: 15–40 minutes with Haiku against real API and ChromaDB.

---

## 9. Notes

- `HITL_AUTO_RESPOND=approved` is set by the existing integration conftest — all five within-crew HITL gates auto-respond, so no human interaction is needed.
- The test is `@pytest.mark.integration` and is excluded from the normal unit test run (`pytest --ignore=tests/integration`).
- The test uses synchronous `asyncio.run()` (not `@pytest.mark.asyncio`) to match the style of the existing 6 integration tests, all of which are sync functions.
- If `run_pam_crew` raises, it catches the exception internally and sets `orchestration_runs.status = "failed"`. The assertion on `status == "completed"` will catch this clearly.
