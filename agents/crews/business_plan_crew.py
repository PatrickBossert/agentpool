# agents/crews/business_plan_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_pam_llm, get_crew_llm
from agents.tools.registry import get_tools_for_agent
from agents.delivery.visual_illustrator import (
    create_visual_illustrator,
    create_visual_illustrator_task,
)
from agents.business_plan.business_plan_generator import (
    create_business_plan_generator,
    create_business_plan_generator_task,
)


def create_business_plan_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
    hitl_tool=None,
    # Defaulted so every existing caller keeps working; run_service passes the real one.
    client_name: str = "",
) -> Crew:
    """
    Assemble and return the Business Plan Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
            Sensitive mode uses the local LLM. Standard and fallback both use Opus 4.6
            via get_pam_llm() — business plan quality requires Opus regardless of mode.
        sector: Client sector (passed to tool registry).
        llm: Optional LLM override (used in tests to inject a cheap model).
    """
    if llm is not None:
        bpg_llm = llm  # injected override
    elif llm_mode == "sensitive":
        bpg_llm = get_crew_llm("sensitive")  # local LLM for sensitive data
    else:
        bpg_llm = get_pam_llm()  # Claude Opus 4.6

    bpg = create_business_plan_generator(
        slug=slug,
        llm=bpg_llm,
        tools=get_tools_for_agent(
            "business_plan_generator", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool
        ),
    )

    # The Illustrator renders the value chain, the propositions, the roadmap and the
    # financials in one consistent style. He sat in delivery, where he could only see the
    # roadmap; here everything he illustrates already exists.
    vi = create_visual_illustrator(
        # The same resolved LLM the writer uses - passing the raw `llm` argument gave the
        # Illustrator None whenever the caller had not injected one, and CrewAI then tried
        # to build a default and failed on an empty model name.
        slug=slug,
        llm=bpg_llm,
        tools=get_tools_for_agent(
            "visual_illustrator", slug=slug, run_id=run_id, sector=sector, hitl_tool=hitl_tool
        ),
    )

    bpg_task = create_business_plan_generator_task(agent=bpg)
    vi_task = create_visual_illustrator_task(agent=vi, sector=sector, client_name=client_name)

    return Crew(
        agents=[bpg, vi],
        tasks=[bpg_task, vi_task],
        process=Process.sequential,
        verbose=True,
    )
