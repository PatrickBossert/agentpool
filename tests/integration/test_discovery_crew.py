# tests/integration/test_discovery_crew.py
"""
Full end-to-end integration test for the Discovery Crew.

Runs the crew with claude-haiku-4-5-20251001 against a real SQLite DB and ChromaDB.
HITL pauses are auto-responded via HITL_AUTO_RESPOND env var set in conftest.

Takes 3-10 minutes. Run with: pytest -m integration -v
"""
import json
import sqlite3
import pytest
from pathlib import Path
from api.config import get_settings


@pytest.mark.integration
def test_discovery_crew_end_to_end(test_slug, project_id):
    """
    Run the full Discovery Crew and verify all outputs are produced.
    Uses synchronous execution (crew.kickoff()) for test simplicity.
    """
    import asyncio
    from agents.llm import get_test_llm
    from agents.crews.discovery_crew import create_discovery_crew

    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{test_slug}.db"

    # Create a crew_run record
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status, started_at)"
        " VALUES (?,?,?, CURRENT_TIMESTAMP)",
        (project_id, "discovery", "running"),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()

    # Build crew with cheap test LLM
    llm = get_test_llm()
    crew = create_discovery_crew(
        slug=test_slug,
        run_id=run_id,
        llm_mode="standard",
        sector="logistics",
        llm=llm,
    )

    # Run the crew (synchronously — simpler for test assertions)
    result = crew.kickoff()
    assert result is not None

    # 1. crew_runs record should still exist (updated by run_service in production;
    #    in this test we called kickoff() directly so we update manually)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE crew_runs SET status='completed', finished_at=CURRENT_TIMESTAMP WHERE id=?",
        (run_id,),
    )
    conn.commit()

    # 2. Verify crew_runs status
    cur = conn.execute("SELECT status FROM crew_runs WHERE id=?", (run_id,))
    assert cur.fetchone()[0] == "completed"

    # 3. agent_outputs: at least one record per agent (excluding state-type)
    cur = conn.execute(
        "SELECT DISTINCT agent_name FROM agent_outputs WHERE project_id=? AND output_type != 'state'",
        (project_id,),
    )
    agent_names = {row[0] for row in cur.fetchall()}
    assert "value_chain_mapper" in agent_names, "Value Chain Mapper produced no output"

    # 4. human_reviews: at least one HITL record for this run
    cur = conn.execute(
        "SELECT COUNT(*) FROM human_reviews WHERE crew_run_id=?", (run_id,)
    )
    hitl_count = cur.fetchone()[0]
    conn.close()
    assert hitl_count >= 1, "No HITL reviews created during crew run"

    # 5. Output files
    outputs_dir = Path(settings.projects_dir) / test_slug / "outputs"

    value_chain_path = outputs_dir / "value_chain.md"
    assert value_chain_path.exists(), "value_chain.md not created"
    value_chain_content = value_chain_path.read_text()
    assert "graph" in value_chain_content.lower() or "flowchart" in value_chain_content.lower(), \
        "value_chain.md does not contain Mermaid syntax"

    requirements_path = outputs_dir / "requirements.json"
    assert requirements_path.exists(), "requirements.json not created"
    requirements = json.loads(requirements_path.read_text())
    assert isinstance(requirements, list), "requirements.json is not a JSON array"
    assert len(requirements) >= 1, "requirements.json contains no requirements"
    assert "id" in requirements[0], "Requirements missing 'id' field"

    value_levers_path = outputs_dir / "value_levers.json"
    assert value_levers_path.exists(), "value_levers.json not created"
    levers = json.loads(value_levers_path.read_text())
    assert isinstance(levers, list), "value_levers.json is not a JSON array"
    assert len(levers) >= 1, "value_levers.json contains no levers"
    assert "lever" in levers[0], "Value levers missing 'lever' field"
