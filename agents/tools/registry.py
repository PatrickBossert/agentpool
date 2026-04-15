# agents/tools/registry.py
"""
Maps agent names to their tool lists.

Usage:
    tools = get_tools_for_agent("value_chain_mapper", slug="acme", run_id=7, sector="logistics")
"""
import logging
from pathlib import Path
from crewai.tools import BaseTool
from api.config import get_settings, load_project_config

_log = logging.getLogger(__name__)


def get_tools_for_agent(
    agent_name: str,
    slug: str,
    run_id: int = 0,
    sector: str = "",
) -> list[BaseTool]:
    """Return instantiated tools for the given agent, scoped to the project slug."""
    from agents.tools.sqlite_state import SQLiteStateTool
    from agents.tools.human_input import HumanInputTool
    from agents.tools.document_ingestion import DocumentIngestionTool
    from agents.tools.chroma_query import ChromaQueryTool
    from agents.tools.tavily_search import TavilySearchTool
    from agents.tools.mermaid_render import MermaidRenderTool

    if not sector:
        settings = get_settings()
        try:
            config = load_project_config(Path(settings.projects_dir) / slug)
            sector = config.get("sector", "")
        except Exception as e:
            _log.warning("Could not load project config for %s: %s", slug, e)
            sector = ""

    tool_map: dict[str, list[BaseTool]] = {
        "value_chain_mapper": [
            DocumentIngestionTool(slug=slug),
            TavilySearchTool(),
            ChromaQueryTool(slug=slug, sector=sector),
            MermaidRenderTool(slug=slug),
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
        "requirements_capture": [
            HumanInputTool(slug=slug, run_id=run_id),
            SQLiteStateTool(slug=slug),
        ],
        "requirements_analyst": [
            DocumentIngestionTool(slug=slug),
            ChromaQueryTool(slug=slug, sector=sector),
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
        "value_lever_analyst": [
            ChromaQueryTool(slug=slug, sector=sector),
            TavilySearchTool(),
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
        "pam": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
        ],
    }

    tools = tool_map.get(agent_name)
    if tools is None:
        raise ValueError(f"Unknown agent: {agent_name}")
    return tools
