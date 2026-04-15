# tests/test_html_roadmap.py
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture(autouse=True)
def isolated_projects_dir(tmp_path, monkeypatch):
    """Redirect PROJECTS_DIR to a temp directory for each test."""
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def slug(isolated_projects_dir):
    slug = "html-roadmap-test"
    project_dir = isolated_projects_dir / slug
    outputs_dir = project_dir / "outputs"
    outputs_dir.mkdir(parents=True)
    return slug


@pytest.fixture
def sample_roadmap_data():
    return {
        "time_axis": "quarters",
        "periods": ["Q1 2026", "Q2 2026", "Q3 2026"],
        "value_streams": ["Operations", "IT"],
        "stakeholder_groups": ["Investor", "Customer", "Operations"],
        "initiatives": [
            {
                "id": "INIT-001",
                "title": "Automate Order Entry",
                "category": "enabling",
                "complexity_score": 2,
                "period": "Q1 2026",
                "value_streams": ["Operations"],
                "proposition_ids": ["VP-001"],
            },
            {
                "id": "INIT-002",
                "title": "Integrate WMS",
                "category": "operating_model",
                "complexity_score": 3,
                "period": "Q2 2026",
                "value_streams": ["IT"],
                "proposition_ids": ["VP-002"],
            },
        ],
        "propositions": [
            {
                "id": "VP-001",
                "title": "Automated Order Management",
                "value_estimate": "High",
                "change_articulation": "Replace manual order entry.",
                "realisation_period": "Q2 2026",
                "value_streams": ["Operations"],
                "impacted_stakeholder_groups": ["Investor", "Customer", "Operations"],
                "value_levers": ["Process Automation", "OpEx Reduction"],
            },
        ],
    }


def test_html_roadmap_writes_file(slug, sample_roadmap_data):
    """HtmlRoadmapTool creates an .html file at the expected path."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    assert Path(result).exists()


def test_html_roadmap_returns_absolute_path(slug, sample_roadmap_data):
    """Return value is an absolute path ending in .html."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    assert Path(result).is_absolute()
    assert result.endswith(".html")


def test_html_roadmap_contains_value_streams(slug, sample_roadmap_data):
    """HTML contains value stream labels as section headers."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    content = Path(result).read_text()
    assert "Operations" in content
    assert "IT" in content


def test_html_roadmap_contains_period_headers(slug, sample_roadmap_data):
    """HTML contains all period names as column headers."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    content = Path(result).read_text()
    assert "Q1 2026" in content
    assert "Q2 2026" in content
    assert "Q3 2026" in content


def test_html_roadmap_contains_stakeholder_rows(slug, sample_roadmap_data):
    """HTML contains stakeholder group names as row labels."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    content = Path(result).read_text()
    assert "Investor" in content
    assert "Customer" in content


def test_html_roadmap_contains_initiative_titles(slug, sample_roadmap_data):
    """HTML contains initiative titles in the Capability Builds rows."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    content = Path(result).read_text()
    assert "Automate Order Entry" in content
    assert "Integrate WMS" in content


def test_html_roadmap_contains_value_levers(slug, sample_roadmap_data):
    """HTML contains value lever names in the Benefits rows."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap.html",
            agent_name="roadmap_generator",
        )
    content = Path(result).read_text()
    assert "Process Automation" in content
    assert "OpEx Reduction" in content


def test_html_roadmap_appends_html_extension(slug, sample_roadmap_data):
    """filename without .html extension gets it added automatically."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="roadmap_no_ext",
            agent_name="roadmap_generator",
        )
    assert result.endswith(".html")
    assert Path(result).exists()


def test_html_roadmap_error_on_write_failure(slug, sample_roadmap_data):
    """Returns error string when the file cannot be saved."""
    from agents.tools.html_roadmap import HtmlRoadmapTool
    with patch("agents.tools.html_roadmap.insert_agent_output_sync"), \
         patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
        tool = HtmlRoadmapTool(slug=slug)
        result = tool._run(
            roadmap_data=sample_roadmap_data,
            filename="fail.html",
            agent_name="roadmap_generator",
        )
    assert result.startswith("Error: render failed")
