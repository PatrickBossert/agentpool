# api/services/skills_service.py
"""LLM helpers for the agent skills library."""
from __future__ import annotations

import json
from anthropic import AsyncAnthropic
from api.config import get_settings

_MODEL = "claude-haiku-4-5-20251001"


async def check_specificity(description: str) -> dict:
    """Return {is_specific, reason, suggestion}.

    is_specific=True means the description mentions client-specific details
    (org names, people, suppliers, contracts) that would make it unsuitable
    for reuse across projects.
    """
    client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    resp = await client.messages.create(
        model=_MODEL,
        max_tokens=512,
        system=(
            "You review skill descriptions for an AI agent skill library used across multiple "
            "client engagements. Determine whether the description contains client-specific "
            "references — organisation names, people, products, systems, suppliers, contracts, "
            "or locations — that would make it unsuitable for reuse in a different client context.\n\n"
            "Respond with valid JSON only, no other text:\n"
            '{"is_specific": true/false, "reason": "why it is specific or null", '
            '"suggestion": "reworded generic version or null"}'
        ),
        messages=[{"role": "user", "content": f"Skill description to check: {description!r}"}],
    )
    try:
        return json.loads(resp.content[0].text.strip())
    except Exception:
        return {"is_specific": False, "reason": None, "suggestion": None}


async def extract_skill(raw_input: str) -> dict:
    """Return {name, description} extracted from reviewer feedback text."""
    client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    resp = await client.messages.create(
        model=_MODEL,
        max_tokens=256,
        system=(
            "Extract a transferable skill lesson from reviewer feedback about an AI agent's work. "
            "The skill should be generic (no client-specific details) and imperative "
            "(what the agent should do or avoid in future).\n\n"
            "Respond with valid JSON only:\n"
            '{"name": "3-5 word title", "description": "1-2 sentences in imperative voice"}'
        ),
        messages=[{"role": "user", "content": f"Reviewer feedback:\n{raw_input}"}],
    )
    try:
        return json.loads(resp.content[0].text.strip())
    except Exception:
        return {"name": "Skill from feedback", "description": raw_input[:200]}


# Baseline skills seeded from the hardcoded AGENT_SKILLS in agentStatus.ts.
# Only agent_name + name + description — no icons (those are UI-only).
BASELINE_SKILLS: list[dict] = [
    # PAM
    {"agent_name": "PAM", "name": "Pipeline Orchestration", "description": "Sequences the full engagement pipeline — from Value Chain Mapping through to Business Plan — dispatching each crew in the correct order, respecting dependencies, and ensuring no phase begins before its prerequisites are satisfied."},
    {"agent_name": "PAM", "name": "Phase Gating", "description": "Holds the gate between phases, preventing downstream crews from running until human review has been confirmed. Ensures the project team has an opportunity to validate outputs at every critical transition."},
    {"agent_name": "PAM", "name": "Schedule Management", "description": "Maintains the project schedule — critical milestones, due dates, and completion tracking. Monitors progress against plan, identifies slippage early, and recommends corrective actions before schedule risk becomes schedule fact."},
    {"agent_name": "PAM", "name": "Status Reporting", "description": "Produces a live status report at any point in the engagement: overall RAG health, progress against plan, per-crew output summary, active risks with mitigations, and issues with escalation recommendations."},
    {"agent_name": "PAM", "name": "Risk Management", "description": "Continuously evaluates engagement risk from project state — knowledge base gaps, stakeholder coverage, schedule slippage, review backlogs, and interview completion. Derives risk severity and recommended mitigations algorithmically from live data."},
    {"agent_name": "PAM", "name": "Issue Management & Escalation", "description": "Identifies active issues — failed crew runs, overdue milestones, stalled phase gates, low interview completion — and generates specific, actionable escalation recommendations for each."},
    {"agent_name": "PAM", "name": "State Awareness", "description": "Reads the full project state — crew run history, output versions, review status, stakeholder data, milestones, and interview sessions — before any decision, ensuring recommendations are grounded in the current picture of the engagement."},
    {"agent_name": "PAM", "name": "Decision Intelligence", "description": "Applies engagement-level judgement to determine when revision cycles are exhausted, when a crew output is sufficient to proceed, and when human input is genuinely required versus when it can be inferred from project context."},
    # Value Chain Mapper
    {"agent_name": "Value Chain Mapper", "name": "Value Chain Analysis", "description": "Applies Porter's Value Chain framework to decompose the organisation into L1 value streams, L2 process stages, and L3 activities. Produces a structured n.n.n numbered activity tree and a summary narrative for downstream agents."},
    {"agent_name": "Value Chain Mapper", "name": "Stable ID Registry", "description": "Maintains a permanent value_chain_registry.json with n.n.n IDs. IDs are assigned once and never reassigned — new activities extend the sequence, removed activities are marked inactive."},
    {"agent_name": "Value Chain Mapper", "name": "Document Ingestion", "description": "Reads and parses uploaded client documents — strategy papers, annual reports, operational procedures — into structured content that informs the value chain decomposition."},
    {"agent_name": "Value Chain Mapper", "name": "Web Search", "description": "Searches the internet for current sector intelligence, comparable value chains, and industry benchmarks to validate the decomposition against peer organisations."},
    {"agent_name": "Value Chain Mapper", "name": "Semantic Search", "description": "Queries the project vector knowledge base for relevant corporate context — prior outputs, ingested documents, and historical assessments — to ground the value chain in organisational reality."},
    {"agent_name": "Value Chain Mapper", "name": "Diagram Rendering", "description": "Creates and renders Mermaid diagrams as visual outputs, producing the authoritative value chain tree diagram alongside the JSON registry."},
    {"agent_name": "Value Chain Mapper", "name": "Human Review", "description": "Pauses for human approval after completing the value chain draft, allowing the project team to validate decomposition boundaries and naming before assessment instruments are designed."},
    # Interaction Designer
    {"agent_name": "Interaction Designer", "name": "Interview Script Design", "description": "Creates tailored interview scripts for every active L1 and L2 value chain node, following n.n.n numbering. L1 scripts target GMs with strategic questions; L2 scripts target process managers with operational questions."},
    {"agent_name": "Interaction Designer", "name": "Maturity Questionnaire Design", "description": "Develops maturity assessment questionnaires for all active L1 and L2 nodes, using a 1–5 maturity scale aligned with configured frameworks (ISO 55001, IIMM, PAS 55, IIRC Six Capitals)."},
    {"agent_name": "Interaction Designer", "name": "Coherent Instrument Design", "description": "Designs interview scripts and maturity questionnaires together as a unified assessment set, ensuring the two instruments reinforce each other rather than duplicating or contradicting."},
    {"agent_name": "Interaction Designer", "name": "Standards Grounding", "description": "Grounds all instrument content in the standards and references configured in the Value Chain Setup. Queries the project knowledge base for corporate context relevant to each node."},
    {"agent_name": "Interaction Designer", "name": "Template Auto-Assignment", "description": "On completion, automatically publishes each script and questionnaire as a named template in the system library and assigns it to the corresponding value chain node by n.n.n activity ID."},
    {"agent_name": "Interaction Designer", "name": "Human Review", "description": "Requests approval of the completed instrument set (both scripts and questionnaires) before deployment to stakeholders, allowing the project team to validate coverage, tone, and alignment with assessment objectives."},
    # Stakeholder Manager
    {"agent_name": "Stakeholder Manager", "name": "Coverage Analysis", "description": "Monitors stakeholder-to-node assignments across L1, L2, and L3 value chain levels. Calculates coverage ratios per level and per value stream, identifies nodes with no assigned stakeholders."},
    {"agent_name": "Stakeholder Manager", "name": "Communication Management", "description": "Drafts and tracks a progressive sequence of stakeholder communications calibrated to urgency and seniority — from initial invitation through to re-engagement escalation."},
    {"agent_name": "Stakeholder Manager", "name": "Engagement Planning", "description": "Writes a structured stakeholder_engagement_plan.json documenting current coverage status, communication history, session completion rates, and recommended next actions per stakeholder."},
    {"agent_name": "Stakeholder Manager", "name": "Interview Session Tracking", "description": "Queries interview session status for every assigned stakeholder and uses completion data to prioritise follow-up communications, avoiding reminders to stakeholders who have already participated."},
    {"agent_name": "Stakeholder Manager", "name": "Slack Notifications", "description": "Sends actionable summary notifications to the project team Slack channel when coverage gaps are identified, communications are dispatched, and the engagement plan is updated."},
    # Requirements Capture
    {"agent_name": "Requirements Capture", "name": "Human Review", "description": "Engages directly with the project team to capture requirements, constraints, and priorities through structured conversation — ensuring the discovery phase is grounded in what the client has explicitly articulated."},
    {"agent_name": "Requirements Capture", "name": "State Management", "description": "Persists captured requirements to the project state store in structured form, making them available to the Requirements Analyst and downstream agents without loss of fidelity."},
    # Requirements Analyst
    {"agent_name": "Requirements Analyst", "name": "Document Ingestion", "description": "Reads and parses uploaded client documents to surface implicit requirements, constraints, and strategic intent that may not have been captured in the direct requirements session."},
    {"agent_name": "Requirements Analyst", "name": "Semantic Search", "description": "Finds related requirements, precedents, and context in the project knowledge base to identify gaps, conflicts, and hidden dependencies in the captured requirement set."},
    {"agent_name": "Requirements Analyst", "name": "Human Review", "description": "Validates the analysed requirement set with the project team before value lever identification, ensuring no material requirements are misread or mis-prioritised."},
    # Value Lever Analyst
    {"agent_name": "Value Lever Analyst", "name": "Semantic Search", "description": "Queries the project knowledge base for value-driving patterns, prior initiative outcomes, and corporate context relevant to the identified value levers."},
    {"agent_name": "Value Lever Analyst", "name": "Web Search", "description": "Benchmarks identified value levers against published industry data, analyst reports, and peer organisation case studies to validate expected impact ranges."},
    {"agent_name": "Value Lever Analyst", "name": "Human Review", "description": "Confirms the prioritised lever set with the project team before value proposition generation, ensuring commercial judgement is applied to analytical output."},
    # Interview Coordinator
    {"agent_name": "Interview Coordinator", "name": "Interview Management", "description": "Creates, tracks, and closes interview sessions for each assigned stakeholder. Generates unique interview links, monitors session state, and produces a scheduling plan that sequences interviews efficiently."},
    {"agent_name": "Interview Coordinator", "name": "Human Review", "description": "Confirms the interview scheduling plan with the project team before sessions are activated, allowing adjustments for stakeholder availability and sequencing preferences."},
    # Stakeholder Interviewer
    {"agent_name": "Stakeholder Interviewer", "name": "Interview Management", "description": "Manages interview session state throughout the lifecycle — launching sessions, recording responses, tracking progress through script sections, and marking completion. Ensures each session produces a complete, structured transcript."},
    {"agent_name": "Stakeholder Interviewer", "name": "Human Review", "description": "Requests clarification from stakeholders during live interview flows when responses are ambiguous or incomplete, ensuring the transcript is actionable for synthesis."},
    # Synthesis Analyst
    {"agent_name": "Synthesis Analyst", "name": "Theme Extraction", "description": "Reads all completed interview transcripts across L1 and L2 stakeholder groups and extracts cross-cutting themes — maturity gaps, capability strengths, strategic tensions, and consensus priorities — that transcend individual responses."},
    {"agent_name": "Synthesis Analyst", "name": "Human Review", "description": "Validates synthesised themes and key findings with the project team before value proposition generation, ensuring interpretive judgements are grounded in stakeholder intent."},
    # Value Proposition Generator
    {"agent_name": "Value Proposition Generator", "name": "Proposition Structuring", "description": "Translates synthesised interview findings and identified value levers into a structured set of value propositions — each with a clear problem statement, proposed intervention, and expected benefit — mapped to the relevant value chain area."},
    {"agent_name": "Value Proposition Generator", "name": "Human Review", "description": "Requests review of the proposition set before portfolio scoring, allowing the project team to refine framing, merge duplicates, and validate strategic alignment."},
    # Portfolio Manager
    {"agent_name": "Portfolio Manager", "name": "IIRC Six Capitals Scoring", "description": "Scores each initiative across eight dimensions derived from the IIRC Integrated Reporting framework — financial, manufactured, intellectual, human, social/relationship, and natural capitals. Applies configured weights to produce a composite portfolio score."},
    {"agent_name": "Portfolio Manager", "name": "Portfolio Ranking", "description": "Produces a ranked, prioritised initiative register with composite scores, individual capital ratings, cost estimates, and initiative type classifications — providing a defensible, evidence-based basis for investment decisions."},
    {"agent_name": "Portfolio Manager", "name": "Human Review", "description": "Requests approval of the portfolio prioritisation before architecture design, ensuring commercial and strategic judgement is applied to the quantitative scoring."},
    # Enterprise Architect
    {"agent_name": "Enterprise Architect", "name": "Architecture Design", "description": "Designs the enterprise architecture required to deliver the prioritised initiative portfolio — covering capability gaps, technology enablers, integration patterns, and organisational design implications."},
    {"agent_name": "Enterprise Architect", "name": "Semantic Search", "description": "Queries the project knowledge base for existing architecture context — current-state capabilities, adopted standards, prior design decisions — to ensure the target architecture is grounded in organisational reality."},
    {"agent_name": "Enterprise Architect", "name": "Diagram Rendering", "description": "Produces architecture diagrams as Mermaid visuals — capability maps, integration diagrams, and solution blueprints — for inclusion in the business plan and stakeholder presentations."},
    {"agent_name": "Enterprise Architect", "name": "Human Review", "description": "Validates the architecture blueprint with the project team before initiative decomposition, ensuring technical assumptions are confirmed and design constraints are acknowledged."},
    # Initiative Identifier
    {"agent_name": "Initiative Identifier", "name": "Initiative Decomposition", "description": "Reads the architecture blueprint and decomposes it into a discrete set of initiatives — each with a defined scope, expected outputs, dependencies, value stream alignment, and indicative cost band."},
    {"agent_name": "Initiative Identifier", "name": "Human Review", "description": "Validates initiative scope, boundaries, and dependencies with the project team, ensuring the decomposition reflects delivery realities rather than architectural ideals."},
    # Roadmap Generator
    {"agent_name": "Roadmap Generator", "name": "Roadmap Sequencing", "description": "Sequences initiatives across value streams and time horizons — short, medium, and long — taking into account dependencies, resource constraints, quick-win opportunities, and strategic priority scores from the portfolio."},
    {"agent_name": "Roadmap Generator", "name": "Roadmap Rendering", "description": "Generates an interactive HTML roadmap for client presentation — with swim-lane layout by value stream, hover detail per initiative, and print-ready formatting. Also writes roadmap_data.json for the Gantt chart view."},
    {"agent_name": "Roadmap Generator", "name": "Human Review", "description": "Confirms roadmap timing, value stream allocation, and phasing with the project team before business plan finalisation."},
    # Business Plan Generator
    {"agent_name": "Business Plan Generator", "name": "Financial Modelling", "description": "Calculates NPV, IRR, payback period, and maximum borrowing capacity based on initiative costs, benefit profiles, and configured financial assumptions. Produces a rigorous investment case grounded in the initiative portfolio."},
    {"agent_name": "Business Plan Generator", "name": "Business Plan Narrative", "description": "Compiles the full business plan narrative — executive summary, strategic context, value chain assessment findings, initiative portfolio, financial model, and delivery roadmap — drawing on all prior crew outputs."},
    {"agent_name": "Business Plan Generator", "name": "Word Export", "description": "Generates a formatted Word document business plan suitable for board and executive distribution — with structured headings, embedded tables, and branded section formatting."},
    {"agent_name": "Business Plan Generator", "name": "PowerPoint Export", "description": "Generates an executive summary slide deck — condensing key findings, portfolio priorities, financial headline, and roadmap into presentation-ready slides."},
    {"agent_name": "Business Plan Generator", "name": "Human Review", "description": "Requests sign-off on financial assumptions before modelling, ensuring the business case reflects commercially agreed parameters rather than analytical defaults."},
]
