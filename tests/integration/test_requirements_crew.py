# tests/integration/test_requirements_crew.py
"""
Full end-to-end integration test for the Discovery Crew.

Runs the crew with claude-haiku-4-5-20251001 against a real SQLite DB and ChromaDB.
HITL pauses are auto-responded via HITL_AUTO_RESPOND env var set in conftest.

Takes 3-10 minutes. Run with: pytest -m integration -v
"""
import contextlib
import json
import sqlite3
import pytest
from pathlib import Path
from api.config import get_settings


@pytest.mark.integration
def test_requirements_crew_end_to_end(test_slug, project_id):
    """
    Run the full Discovery Crew and verify all outputs are produced.
    Uses synchronous execution (crew.kickoff()) for test simplicity.
    """
    from agents.llm import get_test_llm
    from agents.crews.requirements_crew import create_requirements_crew

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
    crew = create_requirements_crew(
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
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
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
        # The agents this crew actually holds. It used to assert value_chain_mapper, who
        # has not been in the requirements crew since the value chain moved to
        # discovery_mapping - _CREW_AGENT_NAMES["requirements"] is the authority, and it
        # names these two. Asserting an agent from another crew meant this test could only
        # ever fail.
        assert "requirements_capture" in agent_names, "Requirements Capture produced no output"
        assert "requirements_analyst" in agent_names, "Requirements Analyst produced no output"

        # 4. human_reviews: at least one HITL record for this run
        cur = conn.execute(
            "SELECT COUNT(*) FROM human_reviews WHERE crew_run_id=?", (run_id,)
        )
        hitl_count = cur.fetchone()[0]
    assert hitl_count >= 1, "No HITL reviews created during crew run"

    # 5. Output files
    #
    # Three assertions were removed here rather than repaired, because each named work this
    # crew no longer does:
    #
    #   value_chain.md, asserted to contain Mermaid "graph"/"flowchart" syntax - the value
    #     chain belongs to discovery_mapping now, and the Mermaid renderer was replaced by
    #     the value chain grid in the UI. There is no Mermaid left to assert.
    #   value_levers.json - value_levers is owned by value_lever_analyst, who runs in
    #     discovery_mapping. Belongs in that crew's test, not this one.
    #   requirements.json - never a declared output type. The two this crew owns are below.
    #
    # Declared outputs resolve through the ledger: SQLiteStateTool writes are renamed to a
    # _vN suffix, so the bare filename these assertions used never exists on disk.
    from agents.tools._db import current_output_path

    captured_path = current_output_path(test_slug, "captured_requirements")
    assert captured_path is not None, "captured_requirements not created"
    captured = json.loads(captured_path.read_text())
    assert isinstance(captured, list), "captured_requirements is not a JSON array"
    assert len(captured) >= 1, "captured_requirements contains no requirements"
    assert "id" in captured[0], "Requirements missing 'id' field"

    analysis_path = current_output_path(test_slug, "requirements_analysis")
    assert analysis_path is not None, "requirements_analysis not created"
    analysis = json.loads(analysis_path.read_text())
    assert analysis, "requirements_analysis is empty"
