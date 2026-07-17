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


async def extract_skills_many(raw_input: str) -> list[dict]:
    """Return [{name, description}] — one entry per distinct skill identified in raw_input."""
    client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    resp = await client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=(
            "You analyse free-form text submitted by a user who wants to teach an AI agent new skills. "
            "The text may be a mix of feature requests, observations, outputs, and process descriptions. "
            "Extract the distinct, reusable, transferable skills embedded in the text.\n\n"
            "NAMING RULES — the name must:\n"
            "- Be 3–5 words, title-cased\n"
            "- Capture the specific capability (e.g. 'Governance Layer Interview Design', 'Data Maturity Probing', 'Authority Boundary Flagging')\n"
            "- Never be generic ('Skill from input', 'New skill', 'Agent skill')\n\n"
            "DESCRIPTION RULES — each description must:\n"
            "- Be 1–3 sentences in imperative voice ('Do X. Never Y. Before Z, check W.')\n"
            "- Be generic — remove all client names, project names, and specific organisations\n"
            "- Be self-contained and actionable\n\n"
            "Extract between 1 and 5 distinct skills. "
            "Return valid JSON only — no markdown, no commentary, no code fences:\n"
            '[{"name": "Specific Capability Name", "description": "Imperative instruction."}, ...]'
        ),
        messages=[{"role": "user", "content": f"Extract skills from this input:\n\n{raw_input}"}],
    )
    raw_text = resp.content[0].text.strip()
    # Strip markdown code fences if the model wraps the JSON
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()
    try:
        result = json.loads(raw_text)
        if isinstance(result, list):
            return result
        return [result]
    except Exception:
        # Last-resort fallback: derive a name from the first meaningful phrase
        first_line = raw_input.strip().split("\n")[0][:60].strip()
        name = " ".join(first_line.split()[:5]).rstrip(".,;:-")
        return [{"name": name or "New Agent Skill", "description": raw_input[:300]}]


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
# agents is a list — a skill can be shared across multiple agents.
# No icons (those are UI-only).
BASELINE_SKILLS: list[dict] = [
    # PAM
    {"agents": ["PAM"], "name": "Pipeline Orchestration", "description": "Dispatch crews in strict dependency order: Discovery → Value Chain → Interaction Design → Stakeholder Management → Interview Coordination → Synthesis → Value Propositions → Portfolio → Architecture → Initiatives → Roadmap → Business Plan. Never start a phase until all its upstream prerequisites have been reviewed and approved."},
    {"agents": ["PAM"], "name": "Phase Gating", "description": "Block every downstream dispatch until the project team explicitly confirms human review. If review is pending, output the review request and halt — never proceed without confirmation."},
    {"agents": ["PAM"], "name": "Schedule Management", "description": "At every orchestration step, compare current progress against the milestone plan. If slippage exceeds one day, flag it with a specific corrective action and a named owner before continuing."},
    {"agents": ["PAM"], "name": "Status Reporting", "description": "When producing a status report, cover all six dimensions in order: RAG health, schedule, per-crew progress, risks, issues, and next actions. Never omit a dimension — an incomplete status report is worse than no report."},
    {"agents": ["PAM"], "name": "Risk Management", "description": "Before each crew dispatch, scan for engagement risks across five areas: knowledge gaps, stakeholder coverage, schedule slippage, review backlogs, and interview completion. Rate every risk and provide a mitigation before continuing."},
    {"agents": ["PAM"], "name": "Issue Management & Escalation", "description": "For each active issue, generate a specific escalation recommendation that names an owner, an action, and a deadline. Never report an issue without a resolution path — an issue without a recommendation is noise, not an escalation."},
    {"agents": ["PAM"], "name": "State Awareness", "description": "Before any orchestration decision, read the full project state — run history, review statuses, stakeholder counts, milestone dates, and interview completions. Never act on assumptions or knowledge from a previous run."},
    {"agents": ["PAM"], "name": "Decision Intelligence", "description": "Apply this rule when deciding whether to proceed: if the output is approved, proceed; if it is pending review, hold; if review is overdue by more than 24 hours, escalate. Never infer approval from silence."},
    # Value Chain Mapper
    {"agents": ["Value Chain Mapper"], "name": "Value Chain Analysis", "description": "Decompose the organisation using Porter's Value Chain: map L1 value streams first, then L2 process stages within each stream, then L3 activities. Assign n.n.n IDs immediately on creation — never produce an unnumbered activity."},
    {"agents": ["Value Chain Mapper"], "name": "Stable ID Registry", "description": "Write every ID assignment to value_chain_registry.json before producing any other output. If removing an activity, mark it inactive rather than deleting it — IDs must never be reassigned or reused."},
    {"agents": ["Value Chain Mapper", "Requirements Analyst"], "name": "Document Ingestion", "description": "Before producing any output, read all uploaded client documents in full. Capture exact terminology the client uses — do not paraphrase. Flag every named system, process, or entity for inclusion in the analysis."},
    {"agents": ["Value Chain Mapper", "Value Lever Analyst", "Requirements Analyst", "Enterprise Architect"], "name": "Web Search", "description": "Validate your outputs against peer organisations and published benchmarks. Cite the source and date for every external data point — never assert a benchmark without attribution."},
    {"agents": ["Value Chain Mapper", "Value Lever Analyst", "Requirements Analyst", "Enterprise Architect"], "name": "Semantic Search", "description": "Query the vector knowledge base before making any claim about the organisation. If relevant prior outputs exist, ground your work in them rather than starting from first principles."},
    {"agents": ["Value Chain Mapper", "Enterprise Architect"], "name": "Diagram Rendering", "description": "Produce a valid Mermaid diagram alongside every JSON output. Validate the syntax before writing the file — a diagram with syntax errors must not be included in the output."},
    # Human Review Gate — shared across all agents that gate on human approval
    {"agents": [
        "Value Chain Mapper", "Interaction Designer", "Stakeholder Manager",
        "Requirements Capture", "Requirements Analyst", "Value Lever Analyst",
        "Interview Coordinator", "Stakeholder Interviewer", "Synthesis Analyst",
        "Value Proposition Generator", "Portfolio Manager", "Enterprise Architect",
        "Initiative Identifier", "Roadmap Generator", "Business Plan Generator",
    ], "name": "Human Review Gate", "description": "At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed."},
    # Interaction Designer
    {"agents": ["Interaction Designer"], "name": "Interview Script Design", "description": "Write one interview script per active L1 and L2 node. L1 scripts must ask strategic 'why' questions aimed at GMs; L2 scripts must ask operational 'how' questions aimed at process managers. Number all questions with n.n.n IDs — never produce an unnumbered question."},
    {"agents": ["Interaction Designer"], "name": "Maturity Questionnaire Design", "description": "For each node, write a five-point maturity questionnaire where level 1 is ad hoc and level 5 is optimised and continuously improving. Align every level descriptor to the configured framework — no descriptor may be written without a traceable standard clause."},
    {"agents": ["Interaction Designer"], "name": "Coherent Instrument Design", "description": "Design scripts and questionnaires as a paired set for each node. Before finalising, confirm the interview questions and maturity descriptors cover the same capability dimensions — never submit a set where a topic appears in one instrument but not the other."},
    {"agents": ["Interaction Designer"], "name": "Standards Grounding", "description": "Before writing any instrument content, retrieve the configured framework standards from the project setup. Every question and maturity descriptor must be traceable to a specific standard clause or principle — reject content that cannot be traced."},
    {"agents": ["Interaction Designer"], "name": "Template Auto-Assignment", "description": "On completing the instrument set, publish each script and questionnaire as a named template and assign it to its value chain node by n.n.n ID. Confirm the assignment in the output before ending the run — unassigned templates are incomplete."},
    # Stakeholder Manager
    {"agents": ["Stakeholder Manager"], "name": "Coverage Analysis", "description": "Calculate stakeholder coverage at L1, L2, and L3 separately. List every node with zero assigned stakeholders explicitly — never aggregate gaps or describe them vaguely. A coverage report without a node-level breakdown is incomplete."},
    {"agents": ["Stakeholder Manager"], "name": "Communication Management", "description": "Draft communications in escalating urgency: invitation, then first reminder, then second reminder, then re-engagement escalation. Match the tone to the stakeholder's level — never send an escalation tone to a first-time contact."},
    {"agents": ["Stakeholder Manager"], "name": "Engagement Planning", "description": "Write the engagement plan to stakeholder_engagement_plan.json with a specific next action for every stakeholder. A plan entry without a named next action is incomplete — every stakeholder must have a clear instruction."},
    {"agents": ["Stakeholder Manager"], "name": "Interview Session Tracking", "description": "Before sending any communication, check interview session status. Never send a reminder to a stakeholder who has already completed their session — check completion status every time, without exception."},
    {"agents": ["Stakeholder Manager"], "name": "Slack Notifications", "description": "Send a Slack notification when coverage gaps are identified, communications are dispatched, or the engagement plan is updated. Include the specific gap or action in every notification — never send a generic status message."},
    # Requirements Capture
    {"agents": ["Requirements Capture"], "name": "Requirements Elicitation", "description": "Ask the project team structured questions to surface requirements, constraints, and priorities. Record only what the team explicitly states, using their exact wording — never infer requirements or paraphrase what was said."},
    {"agents": ["Requirements Capture"], "name": "State Management", "description": "Write all captured requirements to the project state store in structured JSON before ending the session. Do not rely on conversation history — write every requirement out explicitly and confirm the write before finishing."},
    # Requirements Analyst
    {"agents": ["Requirements Analyst"], "name": "Requirements Analysis", "description": "Read all captured requirements and all uploaded documents before identifying any gap or conflict. Ground every finding in evidence — never assert a gap without citing what is missing and why it matters."},
    # Value Lever Analyst
    {"agents": ["Value Lever Analyst"], "name": "Value Lever Identification", "description": "Validate every identified value lever against at least one published benchmark or industry dataset before submitting it. Cite the source and date — never assert an impact estimate without external evidence."},
    # Interview Coordinator
    {"agents": ["Interview Coordinator"], "name": "Interview Session Management", "description": "Create a session for each assigned stakeholder and generate a unique interview link. Produce a scheduling plan that groups sessions by value stream and staggers timing to avoid conflicting demands on the same stakeholder group."},
    # Stakeholder Interviewer
    {"agents": ["Stakeholder Interviewer"], "name": "Live Interview Facilitation", "description": "Follow the interview script in sequence. If a response is ambiguous, ask one clarifying question before moving on. Mark a section complete only when a substantive answer has been recorded — never mark a section complete with a blank or single-word response."},
    # Synthesis Analyst
    {"agents": ["Synthesis Analyst"], "name": "Theme Extraction", "description": "Read all completed transcripts before identifying any theme. Only flag a theme if it appears across multiple transcripts — single-respondent observations belong in 'individual perspectives', not in cross-cutting themes. Never extrapolate a theme from one voice."},
    # Value Proposition Generator
    {"agents": ["Value Proposition Generator"], "name": "Proposition Structuring", "description": "Structure every proposition with three mandatory components: problem statement, proposed intervention, and expected benefit. Map each to the specific value chain node it addresses. A proposition missing any component must not be submitted."},
    # Portfolio Manager
    {"agents": ["Portfolio Manager"], "name": "IIRC Six Capitals Scoring", "description": "Score every initiative across all eight capital dimensions before ranking anything. Never skip a dimension — if data is insufficient, assign a score of 0 and note the gap explicitly in the output."},
    {"agents": ["Portfolio Manager"], "name": "Portfolio Ranking", "description": "Rank initiatives by composite score. Where two initiatives share the same composite score, use lower implementation complexity as the tiebreaker — prefer the simpler initiative."},
    # Enterprise Architect
    {"agents": ["Enterprise Architect"], "name": "Architecture Design", "description": "Design the target architecture from the initiative portfolio, not from first principles. Map every architectural component to at least one initiative it enables — never include an element that cannot be linked to a portfolio initiative."},
    # Initiative Identifier
    {"agents": ["Initiative Identifier"], "name": "Initiative Decomposition", "description": "Decompose the architecture into initiatives with defined scope, outputs, and dependencies. Every initiative must either name its dependencies explicitly or state that it is independent — no initiative may have an undefined dependency status."},
    # Roadmap Generator
    {"agents": ["Roadmap Generator"], "name": "Roadmap Sequencing", "description": "Sequence initiatives so all dependencies are resolved before each initiative begins. If circular dependencies exist, flag them immediately and halt — never silently reorder to avoid a dependency conflict."},
    {"agents": ["Roadmap Generator"], "name": "Roadmap Rendering", "description": "Generate the HTML roadmap and roadmap_data.json in the same run. A roadmap HTML file without a corresponding JSON data file is an incomplete output — both are required."},
    # Business Plan Generator
    {"agents": ["Business Plan Generator"], "name": "Financial Modelling", "description": "Calculate NPV, IRR, and payback period using the configured financial assumptions. If any required assumption is missing, stop and request it from the project team — never substitute a default value for a client engagement."},
    {"agents": ["Business Plan Generator"], "name": "Business Plan Narrative", "description": "Write the narrative in this order: executive summary, strategic context, value chain findings, initiative portfolio, financial model, roadmap. Never reorder sections or combine them — section order is mandated by the output standard."},
    {"agents": ["Business Plan Generator"], "name": "Word Export", "description": "Generate the Word document and confirm its file path in the output. If generation fails, report the error explicitly — never report success without verifying the file exists on disk."},
    {"agents": ["Business Plan Generator"], "name": "PowerPoint Export", "description": "Condense the business plan to executive decision points only. Never include raw data tables in the slide deck — summarise everything to headline numbers and key insights at board level."},
]
