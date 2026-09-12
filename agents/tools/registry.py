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
    """Return instantiated tools for the given agent, scoped to the project slug.

    What this returns is what `tool_map` names, class for class. There was once a `hitl_tool`
    parameter that substituted a caller's own tool for every `HumanInputTool` in the list, and
    the Chainlit console was the only thing that ever passed it. It made the tool lists a
    property of the caller rather than of the agent, which every reader of the registry - the
    graph, the egress declaration, the privacy page - had to be told about and could not see.
    """
    from agents.tools.sqlite_state import SQLiteStateTool
    from agents.tools.human_input import HumanInputTool
    from agents.tools.run_crew import RunCrewTool
    from agents.tools.document_ingestion import DocumentIngestionTool
    from agents.tools.chroma_query import ChromaQueryTool
    from agents.tools.tavily_search import TavilySearchTool
    from agents.tools.mermaid_render import MermaidRenderTool
    from agents.tools.excel_output import ExcelOutputTool
    from agents.tools.html_roadmap import HtmlRoadmapTool
    from agents.tools.word_output import WordOutputTool
    from agents.tools.powerpoint_output import PowerPointOutputTool
    from agents.tools.financial_model import FinancialModelTool
    from agents.tools.web_fetch_tool import WebFetchTool
    from agents.tools.interview_session_tool import InterviewSessionTool
    from agents.tools.derive_registry import DeriveRegistryTool
    from agents.tools.skill_proposal import SkillProposalTool

    if not sector:
        settings = get_settings()
        try:
            config = load_project_config(Path(settings.projects_dir) / slug)
            sector = config.get("sector", "")
        except Exception as e:
            _log.warning("Could not load project config for %s: %s", slug, e)
            sector = ""

    # `SkillProposalTool` is last in every list below except PAM's, and the rule for that is
    # **not** "everyone": it is held by an agent that produces an output a reviewer can send
    # back, because the proposal is drawn from a correction the agent has just made. That set
    # is exactly the seventeen agents `_CREW_AGENT_NAMES` dispatches - every one of them writes
    # `agent_outputs` rows a reviewer's note reaches through `_fetch_change_requests` - and
    # `test_skill_proposal_tool.py` holds this map against that one rather than against a list
    # typed twice.
    #
    # PAM is excluded on both halves of the rule. She orchestrates rather than producing an
    # artefact, so nothing of hers is ever sent back; and she is in no `_CREW_AGENT_NAMES`
    # entry, so `_fetch_skill_notes` injects nothing for her - a proposal of hers could be
    # queued, approved, and still reach no prompt, which is the naming trap this design has a
    # section about, arriving from a third direction. If PAM's skills are ever injected, this
    # exclusion should be revisited with them.
    tool_map: dict[str, list[BaseTool]] = {
        "value_chain_mapper": [
            DocumentIngestionTool(slug=slug),
            TavilySearchTool(),
            WebFetchTool(),
            ChromaQueryTool(slug=slug, sector=sector, run_id=run_id, agent_name=agent_name),
            # No MermaidRenderTool: this agent emits the structured value chain model, and
            # holding the tool would let it write a value_chain_v<n>.md whatever the task
            # asks for. The Enterprise Architect below keeps it.
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            DeriveRegistryTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        "requirements_capture": [
            HumanInputTool(slug=slug, run_id=run_id),
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        "requirements_analyst": [
            DocumentIngestionTool(slug=slug),
            ChromaQueryTool(slug=slug, sector=sector, run_id=run_id, agent_name=agent_name),
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            HumanInputTool(slug=slug, run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        "value_lever_analyst": [
            ChromaQueryTool(slug=slug, sector=sector, run_id=run_id, agent_name=agent_name),
            TavilySearchTool(),
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            HumanInputTool(slug=slug, run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        "pam": [
            RunCrewTool(slug=slug, orchestration_run_id=run_id),
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
        ],
        "value_proposition_generator": [
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            HumanInputTool(slug=slug, run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        "portfolio_manager": [
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            HumanInputTool(slug=slug, run_id=run_id),
            ExcelOutputTool(slug=slug),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        "enterprise_architect": [
            ChromaQueryTool(slug=slug, sector=sector, run_id=run_id, agent_name=agent_name),
            MermaidRenderTool(slug=slug),
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            HumanInputTool(slug=slug, run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        "initiative_identifier": [
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            HumanInputTool(slug=slug, run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        "roadmap_generator": [
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            HumanInputTool(slug=slug, run_id=run_id),
            HtmlRoadmapTool(slug=slug),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        "business_plan_generator": [
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            HumanInputTool(slug=slug, run_id=run_id),
            WordOutputTool(slug=slug),
            PowerPointOutputTool(slug=slug),
            FinancialModelTool(slug=slug),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        # One working tool, because his task needs exactly one: he reads five upstream outputs
        # and writes illustration_briefs, and SQLiteStateTool does both. It also writes the file
        # to outputs/, which is why the task no longer asks for a separate file-write step.
        # (SkillProposalTool below is not part of that count - it is held by every agent that
        # produces a reviewable output, and does no work on the task.)
        #
        # No HumanInputTool: the Illustrator has no approval gate, which
        # test_vi_task_has_no_hitl_gate states of the task and this states of the tool list.
        # A tool an agent holds is a tool it can decide to call.
        #
        # No MermaidRenderTool: he produces prompts for an image generator, not diagrams.
        "visual_illustrator": [
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        "interview_coordinator": [
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            HumanInputTool(slug=slug, run_id=run_id),
            InterviewSessionTool(slug=slug, orchestration_run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        "stakeholder_interviewer": [
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            HumanInputTool(slug=slug, run_id=run_id),
            InterviewSessionTool(slug=slug, orchestration_run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        # Laura's list is Avery's, class for class, because the job is his: she is a second
        # voice, not a second brief. Written out rather than aliased to his entry, because
        # `agents/graph.py` reads this literal with an AST walk and a reference to another key
        # is not a list it can read - and the guard that holds this reading against what the
        # function actually returns would then be checking nothing for her.
        "second_interviewer": [
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            HumanInputTool(slug=slug, run_id=run_id),
            InterviewSessionTool(slug=slug, orchestration_run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        "synthesis_analyst": [
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            # The interview corpus is too large to read whole, and a transcript blob cannot
            # be filtered by discipline or relationship. He queries the answers.
            ChromaQueryTool(slug=slug, sector=sector, run_id=run_id, agent_name=agent_name),
            HumanInputTool(slug=slug, run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        "interaction_designer": [
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            ChromaQueryTool(slug=slug, sector=sector, run_id=run_id, agent_name=agent_name),
            HumanInputTool(slug=slug, run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
        # No InterviewSessionTool: the interview process is the Interview Coordinator's, and a
        # tool an agent holds is a tool it can decide to call. Jordan owns the roster and its
        # coverage of the value chain; sessions, invitations and reminders are not his.
        "stakeholder_manager": [
            SQLiteStateTool(slug=slug, agent_name=agent_name, run_id=run_id),
            SkillProposalTool(slug=slug, agent_name=agent_name),
        ],
    }

    tools = tool_map.get(agent_name)
    if tools is None:
        raise ValueError(f"Unknown agent: {agent_name}")

    return tools
