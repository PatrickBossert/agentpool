# tests/integration/conftest.py
"""
Integration test infrastructure for SP3a.

Requires:
- ANTHROPIC_API_KEY set in environment
- ChromaDB running: docker run -p 8002:8000 chromadb/chroma

Run with: pytest -m integration
"""
import os
import uuid
import json
import sqlite3
from pathlib import Path
import pytest
import chromadb

# Set env vars before any app imports so settings are correct
os.environ.setdefault("DATABASE_DIR", "/tmp/agentpool_integration_test")
os.environ.setdefault("PROJECTS_DIR", "/tmp/agentpool_integration_test_projects")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("LITELLM_PROXY_URL", "http://localhost:4000")
os.environ.setdefault("LLAMACPP_BASE_URL", "http://localhost:10000")
os.environ.setdefault("CHROMA_HOST", "localhost")
os.environ.setdefault("CHROMA_PORT", "8002")
# Auto-respond to all HITL prompts in integration tests
os.environ["HITL_AUTO_RESPOND"] = "approved"

Path("/tmp/agentpool_integration_test").mkdir(exist_ok=True)
Path("/tmp/agentpool_integration_test_projects").mkdir(exist_ok=True)


@pytest.fixture(scope="session")
def test_slug() -> str:
    return f"test-sp3a-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def chroma_client():
    return chromadb.HttpClient(host="localhost", port=8002)


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
    import yaml
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

    yield

    # Teardown: remove SQLite DB, project dir, ChromaDB collection
    import shutil
    db_path.unlink(missing_ok=True)
    shutil.rmtree(project_dir, ignore_errors=True)
    try:
        chroma_client.delete_collection(f"{test_slug}_docs")
    except Exception:
        pass


@pytest.fixture(scope="session")
def project_id(test_slug) -> int:
    from api.config import get_settings
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{test_slug}.db"
    conn = sqlite3.connect(db_path)
    cur = conn.execute("SELECT id FROM projects WHERE slug=?", (test_slug,))
    row = cur.fetchone()
    conn.close()
    return row[0]
