# agents/delivery/visual_illustrator.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_visual_illustrator(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Visual Illustrator",
        goal=(
            "Produce richly contextualised illustration briefs for every major project "
            "output — value chain vision, value proposition vignettes, architecture schematic, "
            "roadmap, operating model change, and future state — so the project team can feed "
            "them directly into any image generation tool and receive a usable result."
        ),
        backstory=(
            "You are a visual strategist and graphic recorder who translates complex "
            "organisational models into hand-sketched illustrations that stakeholders can "
            "literally point at. You studied isometric technical drawing and have spent "
            "years as a visual facilitator on large transformation programmes. You believe "
            "a well-crafted image compresses six slides of explanation into a single glance. "
            "You never invent details — every element in your briefs is grounded in the "
            "actual project data: sector, entity names, L1 and L2 stage labels, initiative "
            "titles, and proposition statements."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_visual_illustrator_task(
    agent: Agent,
    sector: str,
    client_name: str,
) -> Task:
    return Task(
        description=(
            "Generate illustration briefs for all major project outputs.\n\n"
            f"Client context: {client_name} — sector: {sector}\n\n"
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='value_chain_summary', "
            "agent_name='visual_illustrator' to retrieve the value chain summary.\n"
            "2. Use SQLiteStateTool with operation='read', key='value_chain_registry', "
            "agent_name='visual_illustrator' to retrieve the full value chain registry "
            "(L1 nodes, L2 nodes with entity context).\n"
            "3. Use SQLiteStateTool with operation='read', key='propositions', "
            "agent_name='visual_illustrator' to retrieve the value propositions.\n"
            "4. Use SQLiteStateTool with operation='read', key='architecture_blueprint', "
            "agent_name='visual_illustrator' to retrieve the architecture blueprint.\n"
            "5. Use SQLiteStateTool with operation='read', key='roadmap_data', "
            "agent_name='visual_illustrator' to retrieve the roadmap sequencing data.\n"
            "6. For each illustration type below, write one brief in the output JSON.\n\n"
            "ILLUSTRATION TYPE 1 — Vision (Value Chain)\n"
            "  Goal: A compact 16:9 hand-sketched isometric image showing ALL L1 value "
            "streams and their L2 stage sequences, with relevant entities/systems labelled "
            "at L2 level only. Flow arrows connect L2 stages left-to-right within each L1 "
            "swim lane. L1 banners span the full width of their swim lane.\n"
            "  Prompt structure:\n"
            "  - Open with: 'You are a graphic artist creating a hand-sketched isometric "
            f"illustration for {client_name} ({sector} sector).'\n"
            "  - List every L1 value stream by name and the ordered sequence of its L2 "
            "stages — use the actual names from the registry, not placeholders.\n"
            "  - For each L2 stage, include up to two relevant system/entity names from "
            "the registry as label annotations.\n"
            "  - Specify: white background, hand-sketched style, isometric viewpoint, "
            "text labels for L1 and L2 only, single-headed flow arrows between L2 stages "
            "that do not dominate the image, no duplicate L2 stages.\n"
            "  - Close with: 'Do not add decorative elements not listed. Do not invent "
            "system names. Maintain consistent scale across all swim lanes.'\n\n"
            "ILLUSTRATION TYPE 2 — Value Proposition Vignettes (one brief per proposition)\n"
            "  Goal: A paired before/after vignette for each value proposition.\n"
            "  Prompt structure per proposition:\n"
            "  - Name the proposition and its value chain node reference.\n"
            "  - Before panel: describe the current pain point scene — the key stakeholder "
            "role, the process context from the L2 stage name, and the specific friction "
            "or gap articulated in the proposition's change_articulation field.\n"
            "  - After panel: describe the improved state — same stakeholder, same context, "
            "but with the proposed intervention in place.\n"
            "  - Style: hand-sketched split panel, no text beyond minimal labels, "
            "white background, consistent character style across panels.\n\n"
            "ILLUSTRATION TYPE 3 — Architecture Schematic\n"
            "  Goal: A technical illustration of the target capability model.\n"
            "  Prompt structure:\n"
            "  - Group capabilities into labelled zones drawn from the architecture "
            "blueprint (e.g. operational technology, data and analytics, integration, "
            "digital channels).\n"
            "  - Show connection lines between zones with brief labels on the connections.\n"
            "  - Highlight which zones are impacted by which initiative categories "
            "(enabling, operating model, business change).\n"
            "  - Style: hand-sketched technical diagram, blueprint aesthetic, "
            "white or light blue background, labels in a clean sans-serif style.\n\n"
            "ILLUSTRATION TYPE 4 — Roadmap Illustration\n"
            "  Goal: A static timeline swim-lane illustration drawn from the roadmap data.\n"
            "  Prompt structure:\n"
            "  - Rows = value streams from roadmap_data.value_streams.\n"
            "  - Columns = time periods from roadmap_data.periods.\n"
            "  - Each initiative as a labelled block in the correct cell, "
            "colour-coded by category (enabling=blue, operating_model=amber, "
            "business_change=teal).\n"
            "  - Style: hand-sketched swimlane grid, white background, "
            "initiative blocks with rounded corners, clear period column headers.\n\n"
            "ILLUSTRATION TYPE 5 — Operating Model Change Initiatives\n"
            "  Goal: One split-composition brief per operating_model initiative "
            "from the roadmap.\n"
            "  Prompt structure per initiative:\n"
            "  - Name the initiative and its value stream.\n"
            "  - Left panel: current operating model state relevant to this initiative "
            "(process, roles, tools as described in the architecture blueprint or "
            "proposition context).\n"
            "  - Right panel: target operating model state after the initiative.\n"
            "  - Style: hand-sketched split illustration, landscape format, "
            "minimal text labels, white background.\n\n"
            "ILLUSTRATION TYPE 6 — Future State Operating Model\n"
            "  Goal: A single high-level one-page illustration of the target "
            "operating model showing principal functions, enabling technology layer, "
            "and value flows.\n"
            "  Prompt structure:\n"
            "  - List the principal functions derived from L1 value streams.\n"
            "  - Show the enabling technology backbone (from architecture zones) "
            "as a horizontal layer beneath the functions.\n"
            "  - Indicate value flows between functions with directional arrows.\n"
            "  - Style: hand-sketched isometric, white background, "
            "L1 function labels only, clean and executive-ready.\n\n"
            "7. Assemble all briefs as a JSON object with this structure:\n"
            "   {\n"
            '     "generated_for": "<client_name>",\n'
            '     "sector": "<sector>",\n'
            '     "briefs": [\n'
            "       {\n"
            '         "type": "vision|value_proposition_vignette|architecture_schematic'
            '|roadmap|operating_model_change|future_state",\n'
            '         "title": "descriptive title (e.g. \'Property Value Chain Vision\')",\n'
            '         "reference_id": "null or e.g. VP-001 for proposition-level briefs",\n'
            '         "prompt": "the full image generation prompt as a single string",\n'
            '         "elements": { "key structured elements used in the prompt" }\n'
            "       }\n"
            "     ]\n"
            "   }\n"
            "8. Use SQLiteStateTool with operation='write', key='illustration_briefs', "
            "agent_name='visual_illustrator' to save the JSON object.\n"
            "9. Use FileWriteTool with filename='illustration_briefs.json', "
            "agent_name='visual_illustrator', and content as the JSON string.\n"
            "10. Use HumanInputTool with prompt: 'Illustration briefs have been written "
            "to outputs/illustration_briefs.json. Please review the briefs and reply "
            '\"approved\" to conclude, or provide revision notes for any specific brief.\'\\n'
            "11. If revision notes are received, revise the relevant briefs and repeat "
            "steps 8–10. Maximum 2 revision cycles.\n"
        ),
        expected_output=(
            "A JSON file at outputs/illustration_briefs.json containing one illustration "
            "brief per output type — vision (value chain), value proposition vignettes "
            "(one per proposition), architecture schematic, roadmap, operating model change "
            "initiatives, and future state operating model. Each brief contains a complete, "
            "context-grounded image generation prompt and a structured elements object. "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
    )
