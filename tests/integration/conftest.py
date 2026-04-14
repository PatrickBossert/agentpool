# tests/integration/conftest.py
"""
Integration test infrastructure for SP3a.

Requires:
- ANTHROPIC_API_KEY in .env (or environment)
- CHROMA_API_KEY in .env for ChromaDB Cloud, or a local ChromaDB on port 8002

Run with: pytest -m integration
"""
import os
import uuid
import json
import sqlite3
import shutil
import yaml
from pathlib import Path
import pytest
import chromadb
from dotenv import load_dotenv

# Load .env with override=True so real keys take precedence over the dummy
# values set by tests/conftest.py (which runs first as the parent conftest).
_env_file = Path(__file__).parents[2] / ".env"
load_dotenv(_env_file, override=True)

# Override dirs to isolated tmp paths, then clear the cached settings so
# get_settings() re-reads all values (including real API keys from .env).
from api.config import get_settings
os.environ["DATABASE_DIR"] = "/tmp/agentpool_integration_test"
os.environ["PROJECTS_DIR"] = "/tmp/agentpool_integration_test_projects"
get_settings.cache_clear()

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
os.environ.setdefault("ADMIN_USERNAME", "admin")
# Auto-respond to all HITL prompts in integration tests
os.environ["HITL_AUTO_RESPOND"] = "approved"

Path("/tmp/agentpool_integration_test").mkdir(exist_ok=True)
Path("/tmp/agentpool_integration_test_projects").mkdir(exist_ok=True)


@pytest.fixture(scope="session")
def test_slug() -> str:
    return f"test-sp3a-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def chroma_client():
    settings = get_settings()
    if settings.chroma_api_key:
        return chromadb.CloudClient(
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
            api_key=settings.chroma_api_key,
        )
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)


@pytest.fixture(scope="session", autouse=True)
def setup_test_project(test_slug, chroma_client):
    """Create a full project environment for integration tests."""
    from api.config import get_settings
    settings = get_settings()

    # Create project directory structure
    project_dir = Path(settings.projects_dir) / test_slug
    docs_dir = project_dir / "docs"
    outputs_dir = project_dir / "outputs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # Write a fixture document
    (docs_dir / "test_document.txt").write_text(
        "This document describes a logistics company's digital transformation needs.\n"
        "The organisation operates a hub-and-spoke distribution network across 12 regions.\n"
        "Key pain points: manual order tracking, disconnected warehouse management systems,\n"
        "and lack of real-time visibility across the supply chain.\n"
        "Strategic priorities: automate order processing, integrate WMS with ERP,\n"
        "and implement predictive demand forecasting.\n"
        "Budget constraint: £2M over 18 months. Regulatory: GDPR compliance required.\n"
    )

    # Write config.yaml
    config = {
        "client_slug": test_slug,
        "llm_mode": "standard",
        "sector": "logistics",
        "stakeholder_groups": ["Operations", "IT", "Finance"],
        "value_stream_labels": ["Inbound", "Warehousing", "Outbound", "Last Mile"],
        "crews_enabled": ["discovery"],
        "review_gates": True,
        "slack_channel": "",
        "requirements_capture_max_turns": 3,
    }
    (project_dir / "config.yaml").write_text(yaml.dump(config))

    # Create SQLite DB with project row
    db_path = Path(settings.database_dir) / f"{test_slug}.db"
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
    """)
    conn.execute(
        "INSERT OR IGNORE INTO projects (slug, llm_mode, sector, config_json) VALUES (?,?,?,?)",
        (test_slug, "standard", "logistics", json.dumps(config)),
    )
    conn.commit()
    conn.close()

    # Seed the test document into ChromaDB so agents that use ChromaQueryTool
    # (e.g. Enterprise Architect) can retrieve content without needing a live
    # DocumentIngestionTool call.
    try:
        collection = chroma_client.get_or_create_collection(f"{test_slug}_docs")
        doc_text = (docs_dir / "test_document.txt").read_text()
        # Chunk into ~500-char pieces with 100-char overlap
        chunks, start = [], 0
        while start < len(doc_text):
            chunks.append(doc_text[start: start + 500])
            start += 400
        chunks = [c for c in chunks if c.strip()]
        collection.upsert(
            documents=chunks,
            ids=[f"test_document.txt::{i}" for i in range(len(chunks))],
            metadatas=[{"filename": "test_document.txt", "chunk": i} for i in range(len(chunks))],
        )
    except Exception as e:
        print(f"WARNING: ChromaDB seeding failed: {e}")

    yield

    # Teardown: remove SQLite DB, project dir, ChromaDB collection
    db_path.unlink(missing_ok=True)
    shutil.rmtree(project_dir, ignore_errors=True)
    try:
        chroma_client.delete_collection(f"{test_slug}_docs")
    except Exception:
        pass


@pytest.fixture(scope="session")
def project_id(test_slug, setup_test_project) -> int:
    from api.config import get_settings
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{test_slug}.db"
    conn = sqlite3.connect(db_path)
    cur = conn.execute("SELECT id FROM projects WHERE slug=?", (test_slug,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise RuntimeError(f"Project with slug '{test_slug}' not found in database")
    return row[0]


@pytest.fixture(scope="session")
def seed_discovery_outputs(test_slug, setup_test_project):
    """
    Write mock Discovery crew outputs to the test project's outputs directory.
    Required by Value Design integration tests (VPG reads these via SQLiteStateTool).
    """
    from api.config import get_settings
    import json
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / test_slug / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    requirements = [
        {
            "id": "REQ-001",
            "description": "Automate manual order entry process end-to-end",
            "stakeholder_group": "Operations",
            "priority": "high",
            "source": "stakeholder_interview",
        },
        {
            "id": "REQ-002",
            "description": "Integrate warehouse management system with ERP",
            "stakeholder_group": "IT",
            "priority": "high",
            "source": "document_analysis",
        },
        {
            "id": "REQ-003",
            "description": "Implement real-time supply chain visibility dashboard",
            "stakeholder_group": "Operations",
            "priority": "medium",
            "source": "stakeholder_interview",
        },
    ]
    (outputs_dir / "requirements.json").write_text(json.dumps(requirements))

    value_levers = [
        {
            "lever": "Process Automation",
            "description": "Automate high-volume manual processes across order management",
            "value_impact": "high",
            "effort": "medium",
            "related_requirements": ["REQ-001"],
            "evidence": "Industry benchmarks show 60–80% reduction in processing time",
        },
        {
            "lever": "Systems Integration",
            "description": "Connect disparate WMS, ERP and CRM platforms",
            "value_impact": "high",
            "effort": "high",
            "related_requirements": ["REQ-002"],
            "evidence": "Eliminates manual data re-entry across 3 systems",
        },
        {
            "lever": "Real-time Visibility",
            "description": "End-to-end tracking and reporting across the supply chain",
            "value_impact": "medium",
            "effort": "medium",
            "related_requirements": ["REQ-003"],
            "evidence": "Reduces exception resolution time by ~50%",
        },
    ]
    (outputs_dir / "value_levers.json").write_text(json.dumps(value_levers))

    value_chain_summary = {
        "activities": [
            "Inbound Logistics",
            "Warehouse Operations",
            "Outbound Logistics",
            "Customer Service",
        ],
        "sector": "logistics",
    }
    (outputs_dir / "value_chain_summary.json").write_text(json.dumps(value_chain_summary))

    yield  # no teardown needed — project dir is cleaned up by setup_test_project


@pytest.fixture(scope="session")
def seed_value_design_outputs(test_slug, seed_discovery_outputs):
    """
    Write mock Value Design crew outputs to the test project's outputs directory.
    Required by Architecture integration tests (Initiative Identifier reads propositions).
    """
    from api.config import get_settings
    import json
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / test_slug / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    propositions = [
        {
            "id": "VP-001",
            "title": "Automated Order Management",
            "change_articulation": (
                "Replace manual order entry with an end-to-end automated order management platform. "
                "Eliminates data re-entry errors and reduces processing time from 4 hours to 15 minutes."
            ),
            "impacted_stakeholder_groups": ["Operations", "Finance"],
            "value_estimate": "High",
            "value_estimate_rationale": "Addresses the highest-priority requirement with clear ROI benchmark evidence.",
            "supporting_evidence": [
                {"type": "requirement", "ref": "REQ-001", "summary": "Automate manual order entry"},
                {"type": "lever", "ref": "lever_0", "summary": "Process Automation"},
            ],
        },
        {
            "id": "VP-002",
            "title": "Integrated Supply Chain Platform",
            "change_articulation": (
                "Connect WMS, ERP, and CRM into a unified integration layer. "
                "Provides a single source of truth for inventory, orders and customer data."
            ),
            "impacted_stakeholder_groups": ["IT", "Operations"],
            "value_estimate": "High",
            "value_estimate_rationale": "Resolves the root cause of data inconsistency across three systems.",
            "supporting_evidence": [
                {"type": "requirement", "ref": "REQ-002", "summary": "Integrate WMS with ERP"},
                {"type": "lever", "ref": "lever_1", "summary": "Systems Integration"},
            ],
        },
    ]
    (outputs_dir / "propositions.json").write_text(json.dumps(propositions))

    yield  # no teardown needed
