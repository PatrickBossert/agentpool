# tests/integration/test_pam_orchestration.py
"""
End-to-end integration test for the PAM orchestration pipeline.

Calls run_pam_crew() directly with all five specialist crews running
sequentially via RunCrewTool. Verifies DB lifecycle and output files.

Requires: ANTHROPIC_API_KEY in .env (loaded by tests/integration/conftest.py)

Run with:
    pytest tests/integration/test_pam_orchestration.py -v -m integration

Estimated time: 15–40 minutes with Haiku against real API and ChromaDB.
"""
import asyncio
import json
import os
import shutil
import sqlite3
import uuid
import yaml
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from api.config import get_settings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_slug_pam() -> str:
    return f"test-pam-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def project_id_pam(test_slug_pam) -> int:
    """
    Create an isolated project directory, config.yaml, and SQLite DB for the
    PAM test. Inserts a project row and all required tables (including
    orchestration_runs). Tears down after the test.
    """
    import api.config as cfg
    cfg.get_settings.cache_clear()
    settings = get_settings()
    slug = test_slug_pam

    project_dir = Path(settings.projects_dir) / slug
    docs_dir = project_dir / "docs"
    outputs_dir = project_dir / "outputs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # Seed a fixture document so ChromaQueryTool has content to retrieve
    (docs_dir / "test_document.txt").write_text(
        "This document describes a logistics company's digital transformation needs.\n"
        "The organisation operates a hub-and-spoke distribution network across 12 regions.\n"
        "Key pain points: manual order tracking, disconnected warehouse management systems,\n"
        "and lack of real-time visibility across the supply chain.\n"
        "Strategic priorities: automate order processing, integrate WMS with ERP,\n"
        "and implement predictive demand forecasting.\n"
        "Budget constraint: £2M over 18 months. Regulatory: GDPR compliance required.\n"
    )

    config = {
        "llm_mode": "standard",
        "sector": "logistics",
        "stakeholder_groups": ["Operations", "Technology"],
        "value_stream_labels": ["Asset Management", "Customer Delivery"],
        "roadmap_time_axis": "quarters",
        "crews_enabled": [
            "discovery",
            "value_design",
            "architecture",
            "delivery",
            "business_plan",
        ],
        "review_gates": True,
        "slack_channel": "",
    }
    (project_dir / "config.yaml").write_text(yaml.dump(config))

    db_path = Path(settings.database_dir) / f"{slug}.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            llm_mode TEXT NOT NULL DEFAULT 'standard',
            sector TEXT,
            config_json TEXT,
            status TEXT NOT NULL DEFAULT 'created',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS crew_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            crew_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result_json TEXT,
            started_at DATETIME,
            finished_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS agent_outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            agent_name TEXT NOT NULL,
            output_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            review_status TEXT NOT NULL DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS human_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            output_id INTEGER REFERENCES agent_outputs(id),
            crew_run_id INTEGER REFERENCES crew_runs(id),
            reviewer TEXT,
            decision TEXT NOT NULL DEFAULT 'pending',
            prompt TEXT,
            notes TEXT,
            reviewed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS client_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            content_type TEXT,
            size_bytes INTEGER,
            ingested INTEGER NOT NULL DEFAULT 0,
            uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS orchestration_runs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id),
            status       TEXT NOT NULL DEFAULT 'running',
            started_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME
        );
    """)
    conn.execute(
        "INSERT OR IGNORE INTO projects (slug, llm_mode, sector, config_json) VALUES (?,?,?,?)",
        (slug, "standard", "logistics", json.dumps(config)),
    )
    conn.commit()
    project_id = conn.execute(
        "SELECT id FROM projects WHERE slug=?", (slug,)
    ).fetchone()[0]
    conn.close()

    yield project_id

    # Teardown
    db_path.unlink(missing_ok=True)
    shutil.rmtree(project_dir, ignore_errors=True)


@pytest.fixture
def chroma_collection_pam(test_slug_pam, chroma_client, project_id_pam):
    """
    Create a ChromaDB collection named '{slug}_docs' and seed it with the
    fixture document so agents using ChromaQueryTool can retrieve content.
    Tears down the collection after the test.

    Depends on project_id_pam so the docs directory is already populated.
    """
    settings = get_settings()
    slug = test_slug_pam
    docs_dir = Path(settings.projects_dir) / slug / "docs"

    collection_name = f"{slug}_docs"
    collection = chroma_client.get_or_create_collection(collection_name)

    try:
        doc_text = (docs_dir / "test_document.txt").read_text()
        chunks, start = [], 0
        while start < len(doc_text):
            chunks.append(doc_text[start : start + 500])
            start += 400
        chunks = [c for c in chunks if c.strip()]
        collection.upsert(
            documents=chunks,
            ids=[f"test_document.txt::{i}" for i in range(len(chunks))],
            metadatas=[
                {"filename": "test_document.txt", "chunk": i}
                for i in range(len(chunks))
            ],
        )
    except Exception as e:
        print(f"WARNING: ChromaDB seeding failed: {e}")

    yield collection

    try:
        chroma_client.delete_collection(collection_name)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_pam_pipeline_end_to_end(test_slug_pam, project_id_pam, chroma_collection_pam):
    """
    Run the full PAM pipeline end-to-end and verify:
      1. orchestration_runs.status == 'completed'
      2. Five crew_run rows, all status == 'completed'
      3. Key output file exists for each crew

    All LLM factories (PAM + 5 sub-crews) are patched to Haiku.
    SlackNotifyTool skips silently because N8N_WEBHOOK_URL is set to "".
    HITL gates auto-respond because HITL_AUTO_RESPOND='approved' is set by
    tests/integration/conftest.py.
    """
    import api.config as cfg
    from agents.llm import get_test_llm
    from api.database import fetch_project, get_connection, insert_orchestration_run
    from api.services.orchestration_service import run_pam_crew

    settings = get_settings()
    slug = test_slug_pam
    db_path = Path(settings.database_dir) / f"{slug}.db"

    # Insert the orchestration_run record.
    # get_connection() calls init_db() which re-creates any missing tables,
    # so this is safe even if the fixture used synchronous sqlite3 above.
    async def _insert_run() -> int:
        async with get_connection(slug) as conn:
            project = await fetch_project(conn, slug=slug)
            return await insert_orchestration_run(conn, project_id=project["id"])

    orchestration_run_id = asyncio.run(_insert_run())

    # Override N8N_WEBHOOK_URL so SlackNotifyTool returns "notification skipped"
    # instead of attempting an HTTP call. Restore on exit.
    original_n8n = os.environ.get("N8N_WEBHOOK_URL")
    os.environ["N8N_WEBHOOK_URL"] = ""
    cfg.get_settings.cache_clear()

    try:
        test_llm = get_test_llm()
        # Patch every LLM factory at the module where the name is bound.
        # Patching agents.llm directly has no effect because each crew file
        # uses `from agents.llm import get_crew_llm` (local binding).
        with ExitStack() as stack:
            stack.enter_context(
                patch("agents.crews.discovery_crew.get_crew_llm", return_value=test_llm)
            )
            stack.enter_context(
                patch("agents.crews.value_design_crew.get_crew_llm", return_value=test_llm)
            )
            stack.enter_context(
                patch("agents.crews.value_design_crew.get_pam_llm", return_value=test_llm)
            )
            stack.enter_context(
                patch("agents.crews.value_design_crew.get_haiku_llm", return_value=test_llm)
            )
            stack.enter_context(
                patch("agents.crews.architecture_crew.get_crew_llm", return_value=test_llm)
            )
            stack.enter_context(
                patch("agents.crews.delivery_crew.get_crew_llm", return_value=test_llm)
            )
            stack.enter_context(
                patch("agents.crews.business_plan_crew.get_crew_llm", return_value=test_llm)
            )
            stack.enter_context(
                patch("agents.crews.business_plan_crew.get_pam_llm", return_value=test_llm)
            )
            stack.enter_context(
                patch("agents.crews.pam_crew.get_pam_llm", return_value=test_llm)
            )
            asyncio.run(run_pam_crew(slug, orchestration_run_id))
    finally:
        if original_n8n is None:
            os.environ.pop("N8N_WEBHOOK_URL", None)
        else:
            os.environ["N8N_WEBHOOK_URL"] = original_n8n
        cfg.get_settings.cache_clear()

    # ── Assertion 1: orchestration_runs record completed ─────────────────────
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM orchestration_runs WHERE id=?",
            (orchestration_run_id,),
        ).fetchone()
    assert row is not None, "orchestration_run record not found"
    assert row[0] == "completed", (
        f"orchestration_runs.status={row[0]!r}, expected 'completed'"
    )

    # ── Assertion 2: five crew_run rows, all completed ────────────────────────
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT crew_name, status FROM crew_runs WHERE project_id=?",
            (project_id_pam,),
        ).fetchall()
    crew_map = {r[0]: r[1] for r in rows}
    for name in (
        "discovery",
        "value_design",
        "architecture",
        "delivery",
        "business_plan",
    ):
        assert crew_map.get(name) == "completed", (
            f"{name} crew_run not completed (got {crew_map.get(name)!r})"
        )

    # ── Assertion 3: key output file per crew ────────────────────────────────
    outputs = Path(settings.projects_dir) / slug / "outputs"
    assert (outputs / "value_chain.md").exists(), (
        "discovery: value_chain.md not created"
    )
    assert (outputs / "propositions.json").exists(), (
        "value_design: propositions.json not created"
    )
    assert (outputs / "initiative_register.json").exists(), (
        "architecture: initiative_register.json not created"
    )
    assert (outputs / "roadmap.html").exists(), (
        "delivery: roadmap.html not created"
    )
    assert (outputs / "business_plan.docx").exists(), (
        "business_plan: business_plan.docx not created"
    )
