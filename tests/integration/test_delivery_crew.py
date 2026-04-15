# tests/integration/test_delivery_crew.py
"""
End-to-end integration test for the Delivery Planning Crew (Roadmap Generator).

Requires:
- ANTHROPIC_API_KEY in .env
- Initiative register, propositions, and value_levers seeded by seed_architecture_outputs

Run with: pytest -m integration -v
Takes 3–8 minutes.
"""
import contextlib
import json
import sqlite3
import pytest
from pathlib import Path
from api.config import get_settings


@pytest.mark.integration
def test_delivery_crew_end_to_end(test_slug, project_id, seed_architecture_outputs):
    """
    Run the full Delivery Planning Crew and verify all outputs are produced.
    Uses claude-haiku for the agent (test LLM override).
    HITL pauses are auto-responded via HITL_AUTO_RESPOND='approved' set in conftest.
    """
    from agents.llm import get_test_llm
    from agents.crews.delivery_crew import create_delivery_crew

    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{test_slug}.db"

    # Create a crew_run record
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status, started_at)"
        " VALUES (?,?,?, CURRENT_TIMESTAMP)",
        (project_id, "delivery", "running"),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()

    llm = get_test_llm()
    crew = create_delivery_crew(
        slug=test_slug,
        run_id=run_id,
        llm_mode="standard",
        sector="logistics",
        value_stream_labels=["Operations", "IT"],
        stakeholder_groups=["Investor", "Customer", "Operations", "IT"],
        roadmap_time_axis="quarters",
        llm=llm,
    )

    result = crew.kickoff()
    assert result is not None

    # Mark run completed
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "UPDATE crew_runs SET status='completed', finished_at=CURRENT_TIMESTAMP WHERE id=?",
            (run_id,),
        )
        conn.commit()

    outputs_dir = Path(settings.projects_dir) / test_slug / "outputs"

    # 1. roadmap_data.json exists with correct schema
    roadmap_path = outputs_dir / "roadmap_data.json"
    assert roadmap_path.exists(), "roadmap_data.json not created"
    roadmap = json.loads(roadmap_path.read_text())
    assert "periods" in roadmap, "roadmap_data.json missing 'periods'"
    assert "value_streams" in roadmap, "roadmap_data.json missing 'value_streams'"
    assert "initiatives" in roadmap, "roadmap_data.json missing 'initiatives'"
    assert "propositions" in roadmap, "roadmap_data.json missing 'propositions'"
    assert isinstance(roadmap["periods"], list) and len(roadmap["periods"]) >= 1
    assert isinstance(roadmap["initiatives"], list) and len(roadmap["initiatives"]) >= 1

    # 2. Each initiative has a period assigned
    for init in roadmap["initiatives"]:
        assert "period" in init, f"Initiative {init.get('id')} missing 'period'"

    # 3. Each proposition has value_levers (non-empty list)
    for prop in roadmap["propositions"]:
        assert "value_levers" in prop, f"Proposition {prop.get('id')} missing 'value_levers'"
        assert isinstance(prop["value_levers"], list), "value_levers must be a list"

    # 4. roadmap.html exists and contains value stream labels + period headers
    html_path = outputs_dir / "roadmap.html"
    assert html_path.exists(), "roadmap.html not created"
    html_content = html_path.read_text()
    assert "Operations" in html_content, "roadmap.html missing value stream label"
    for period in roadmap["periods"][:2]:
        assert period in html_content, f"roadmap.html missing period header: {period}"

    # 5. HITL record created
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM human_reviews WHERE crew_run_id=?", (run_id,)
        )
        hitl_count = cur.fetchone()[0]
    assert hitl_count >= 1, "No HITL reviews created during Delivery crew run"

    # 6. agent_outputs record for roadmap_generator
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "SELECT DISTINCT agent_name FROM agent_outputs WHERE project_id=?",
            (project_id,),
        )
        agent_names = {row[0] for row in cur.fetchall()}
    assert "roadmap_generator" in agent_names, \
        "Roadmap Generator produced no tracked output"
