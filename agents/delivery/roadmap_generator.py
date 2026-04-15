# agents/delivery/roadmap_generator.py
import json
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_roadmap_generator(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Roadmap Generator",
        goal=(
            "Sequence approved initiatives into a time-phased delivery roadmap that tells "
            "the complete story of what changes, for whom, through what capability builds, "
            "and what benefits are realised."
        ),
        backstory=(
            "You are a delivery strategy specialist who transforms initiative registers "
            "into actionable roadmaps. You sequence work intelligently — enabling "
            "infrastructure first, then operational change, then business transformation — "
            "and map each initiative to the stakeholder groups and value streams it serves."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_roadmap_generator_task(
    agent: Agent,
    value_stream_labels: list[str],
    stakeholder_groups: list[str],
    roadmap_time_axis: str,
) -> Task:
    streams_str = ", ".join(value_stream_labels)
    groups_str = ", ".join(stakeholder_groups)
    streams_json = json.dumps(value_stream_labels)
    groups_json = json.dumps(stakeholder_groups)
    return Task(
        description=(
            "Build a time-phased delivery roadmap from the initiative register.\n\n"
            f"Project configuration:\n"
            f"- Value streams: {streams_str}\n"
            f"- Stakeholder groups: {groups_str}\n"
            f"- Time axis: {roadmap_time_axis}\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='initiative_register', "
            "agent_name='roadmap_generator' to retrieve the initiative register.\n"
            "2. Use SQLiteStateTool with operation='read', key='propositions', "
            "agent_name='roadmap_generator' to retrieve the value propositions.\n"
            "3. Use SQLiteStateTool with operation='read', key='value_levers', "
            "agent_name='roadmap_generator' to retrieve the value lever register.\n"
            "4. Sequence initiatives into named time periods:\n"
            "   - Order: enabling initiatives first (lower complexity_score first within "
            "category), then operating_model, then business_change.\n"
            "   - Name periods from the configured time axis:\n"
            f"     * 'quarters' → 'Q1 2026', 'Q2 2026', 'Q3 2026', etc.\n"
            f"     * 'years' → 'Year 1', 'Year 2', 'Year 3', etc.\n"
            f"     * 'horizons' → 'Horizon 1', 'Horizon 2', 'Horizon 3', etc.\n"
            "   - Generate as many periods as needed; minimum 3.\n"
            "   - Distribute initiatives across periods — avoid placing all in one period.\n"
            "5. For each initiative, assign:\n"
            "   - 'period': the sequenced time period name.\n"
            f"   - 'value_streams': which of [{streams_str}] this initiative supports "
            "(based on its proposition_ids and category).\n"
            "6. For each value proposition, assign:\n"
            "   - 'realisation_period': the period when benefits are realised — the period "
            "when its last supporting initiative completes, or the period immediately after.\n"
            f"   - 'value_streams': which of [{streams_str}] this proposition belongs to.\n"
            f"   - 'impacted_stakeholder_groups': carry forward from propositions register "
            f"(choose from: {groups_str}).\n"
            "   - 'value_levers': trace each proposition's supporting_evidence for items "
            "with type='lever', then look up the 'lever' field (e.g. 'Process Automation') "
            "in the value lever register. Return a list of lever name strings.\n"
            "7. Assemble the complete roadmap JSON object with this exact structure:\n"
            "   {\n"
            f'     "time_axis": {json.dumps(roadmap_time_axis)},\n'
            '     "periods": ["Q1 2026", ...],\n'
            f'     "value_streams": {streams_json},\n'
            f'     "stakeholder_groups": {groups_json},\n'
            '     "initiatives": [\n'
            '       {\n'
            '         "id": "INIT-001",\n'
            '         "title": "...",\n'
            '         "category": "enabling|operating_model|business_change",\n'
            '         "complexity_score": 2,\n'
            '         "period": "Q1 2026",\n'
            '         "value_streams": ["..."],\n'
            '         "proposition_ids": ["VP-001"]\n'
            '       }\n'
            '     ],\n'
            '     "propositions": [\n'
            '       {\n'
            '         "id": "VP-001",\n'
            '         "title": "...",\n'
            '         "value_estimate": "High|Medium|Low",\n'
            '         "change_articulation": "...",\n'
            '         "realisation_period": "Q2 2026",\n'
            '         "value_streams": ["..."],\n'
            '         "impacted_stakeholder_groups": ["..."],\n'
            '         "value_levers": ["Process Automation", "..."]\n'
            '       }\n'
            '     ]\n'
            '   }\n'
            "8. Use SQLiteStateTool with operation='write', key='roadmap_data', "
            "agent_name='roadmap_generator' to save the JSON object.\n"
            "9. Use HtmlRoadmapTool with:\n"
            "   - roadmap_data: the assembled JSON object\n"
            "   - filename: 'roadmap.html'\n"
            "   - agent_name: 'roadmap_generator'\n"
            "10. Use HumanInputTool with prompt: 'Please review the roadmap at "
            "outputs/roadmap.html and the underlying data at outputs/roadmap_data.json. "
            "Reply \"approved\" to conclude Delivery Planning, or provide revision notes.'\n"
            "11. If revision notes are received, revise the roadmap data and repeat "
            "steps 8–10. Maximum 3 revision cycles.\n"
        ),
        expected_output=(
            "A JSON roadmap saved to outputs/roadmap_data.json and a visual roadmap "
            "saved to outputs/roadmap.html, containing all initiatives sequenced into "
            "time periods with value streams, stakeholder group rows, capability builds, "
            "and benefits (value lever names + value estimate). "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
    )
