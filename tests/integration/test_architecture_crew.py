# tests/integration/test_architecture_crew.py
"""
End-to-end integration test for the Architecture Crew.

Requires:
- ANTHROPIC_API_KEY in .env
- ChromaDB with the project test collection (seeded by setup_test_project)
- Value Design outputs seeded by seed_value_design_outputs fixture (for Initiative Identifier)

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
def test_architecture_crew_end_to_end(test_slug, project_id, seed_value_design_outputs):
    """
    Run the full Architecture Crew and verify all outputs are produced.
    seed_value_design_outputs also pulls in seed_discovery_outputs (via fixture dependency).
    Uses claude-haiku for both agents (test LLM override).
    HITL pauses are auto-responded via HITL_AUTO_RESPOND='approved' set in conftest.
    """
    from agents.llm import get_test_llm
    from agents.crews.architecture_crew import create_architecture_crew

    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{test_slug}.db"

    # Create a crew_run record
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status, started_at)"
        " VALUES (?,?,?, CURRENT_TIMESTAMP)",
        (project_id, "architecture", "running"),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()

    llm = get_test_llm()
    crew = create_architecture_crew(
        slug=test_slug,
        run_id=run_id,
        llm_mode="standard",
        sector="logistics",
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

    # 1. architecture_register.json exists and has all three layers
    arch_path = outputs_dir / "architecture_register.json"
    assert arch_path.exists(), "architecture_register.json not created"
    arch = json.loads(arch_path.read_text())
    assert "data_layer" in arch, "architecture_register.json missing 'data_layer'"
    assert "technology_layer" in arch, "architecture_register.json missing 'technology_layer'"
    assert "organisation_layer" in arch, "architecture_register.json missing 'organisation_layer'"
    assert isinstance(arch["technology_layer"], list), "technology_layer is not a list"
    assert len(arch["technology_layer"]) >= 1, "technology_layer contains no entities"

    # 2. Three Mermaid diagrams exist
    for diagram_name in [
        "architecture_data_layer.md",
        "architecture_technology_layer.md",
        "architecture_org_layer.md",
    ]:
        path = outputs_dir / diagram_name
        assert path.exists(), f"{diagram_name} not created"
        content = path.read_text()
        assert "graph" in content.lower() or "flowchart" in content.lower(), \
            f"{diagram_name} does not contain Mermaid syntax"

    # 3. initiative_register.json exists and has valid structure
    init_path = outputs_dir / "initiative_register.json"
    assert init_path.exists(), "initiative_register.json not created"
    initiatives = json.loads(init_path.read_text())
    assert isinstance(initiatives, list), "initiative_register.json is not a JSON array"
    assert len(initiatives) >= 1, "initiative_register.json contains no initiatives"
    first = initiatives[0]
    assert "id" in first, "Initiative missing 'id' field"
    assert "title" in first, "Initiative missing 'title' field"
    assert "category" in first, "Initiative missing 'category' field"
    assert first["category"] in ("enabling", "operating_model", "business_change"), \
        f"Invalid initiative category: {first['category']}"
    assert "complexity_score" in first, "Initiative missing 'complexity_score' field"
    assert 1 <= first["complexity_score"] <= 5, \
        f"complexity_score out of range: {first['complexity_score']}"

    # 4. HITL records created for both agents
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM human_reviews WHERE crew_run_id=?", (run_id,)
        )
        hitl_count = cur.fetchone()[0]
    assert hitl_count >= 2, \
        f"Expected at least 2 HITL reviews (one per agent), got {hitl_count}"

    # 5. agent_outputs records for both agents
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "SELECT DISTINCT agent_name FROM agent_outputs WHERE project_id=?",
            (project_id,),
        )
        agent_names = {row[0] for row in cur.fetchall()}
    assert "enterprise_architect" in agent_names, \
        "Enterprise Architect produced no tracked output"
    assert "initiative_identifier" in agent_names, \
        "Initiative Identifier produced no tracked output"
