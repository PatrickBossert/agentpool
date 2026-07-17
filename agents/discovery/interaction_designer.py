# agents/discovery/interaction_designer.py
"""Interaction Designer — designs interview scripts and maturity questionnaires together."""
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool

_CONCEPTUAL_SHIFT = """\
CONCEPTUAL SHIFT — L1 → L2 → L3
─────────────────────────────────
L3 interviews:  Focus on execution fidelity, data freshness, bottleneck removal.
                Talk to practitioners. Uncover where effort is wasted, where data
                is missing or stale, and where a smarter tool would change behaviour.

L2 interviews:  Focus on orchestration logic, decision architecture, portfolio coherence.
                Talk to process managers. Surface how work is sequenced, where decisions
                are made without adequate information, and how trade-offs are resolved.

L1 interviews:  Focus on strategic alignment, capability roadmaps, value realisation.
                Talk to GMs and value-stream owners. Explore where investment is not
                yielding returns, what capabilities are missing, and how value is measured.

Instruments must reflect this shift: L3 scripts probe the texture of daily work;
L2 scripts probe decision quality and orchestration; L1 scripts probe strategy and
portfolio coherence. All three levels contribute different data that the Synthesis
Analyst will triangulate into a unified set of findings.
"""

_L2_L3_FRAMEWORK = """\
L2 vs L3 INTERVIEW DESIGN — STRUCTURAL REFERENCE
──────────────────────────────────────────────────
Use this reference to calibrate every design decision when building L2 and L3 scripts.
Each row is a design constraint, not a suggestion.

Dimension            | L3 Interview                              | L2 Interview
─────────────────────┼───────────────────────────────────────────┼─────────────────────────────────────────────
Core Question        | "How do we execute faster & better?"      | "How do we orchestrate & decide better?"
Locus of Value       | Efficiency (speed, cost, error reduction)  | Effectiveness (decision quality, strategy, maturity)
Data Focus           | Freshness, completeness, accessibility     | Integration, governance, trust across sources
Maturity Anchor      | Repeatability, discipline, fidelity        | Evidence-base, rigor, learning loops, governance
Feedback Loops       | Defect/rework cycles                      | Decision outcome tracking & assumption validation
Stakeholder Span     | Single execution team + direct handoffs    | Multiple decision-makers + cross-functional dependencies
Complexity assessed  | Operational friction (wait, rework, manual)| Orchestration friction (misalignment, siloed decisions)
AI Opportunity       | Automation — RPA, ML classification, routing| Decision support — scenario modelling, real-time optimisation, prediction
Time Horizon         | Immediate (next task / next day)           | Strategic (next quarter / next year)
Success Metric       | Cycle time, error rate, cost per execution | Decision quality, strategic alignment, value realisation

KEY DESIGN IMPLICATIONS
───────────────────────
- Opening framing: anchor the conversation on the Core Question for that level from the first exchange.
- Aspiration section: L3 → ask about automation ("what would you automate?"); L2 → ask about decision
  support ("what would help you decide better / faster?"). Do not conflate these.
- Impact & Monetisation: L3 → frame around cost of execution failure (rework, downtime, error);
  L2 → frame around cost of poor decisions (misallocated investment, missed signals, delayed pivots).
- Questionnaire dimensions (L2 only): anchor dimensions to the maturity anchors above —
  evidence-base, rigor, learning loops, governance. Not operational metrics.
- Interviewee persona: L3 practitioners think in tasks and days; L2 managers think in quarters and
  portfolios. Match language, examples, and follow-up probes to that time horizon.
"""


_L2_PRINCIPLES = """\
L2 INTERVIEW PRINCIPLES — MAYA'S JUDGMENT HEURISTICS
──────────────────────────────────────────────────────
Apply these throughout every L2 interview design and execution. They are not steps —
they are persistent lenses to hold across the entire conversation.

1. FRAME AS DECISION CLUSTER, NOT SEQUENCE
   L3 thinking maps a sequence: Step 1 → Step 2 → Step 3.
   L2 thinking maps a cluster: "These 3–6 L3s feed into a shared strategic decision."
   Always ask: What decision do these L3s collectively enable? Then design questions
   around that decision's quality, not the execution steps.
   ✗ "How long does maintenance execution take?"
   ✓ "How do decisions flow across planning, scheduling, execution, and improvement
      to create value? Where does that chain break down?"

2. SEPARATE STATED PROBLEMS FROM ROOT CONSTRAINTS
   Stated: "Our planning takes 6 weeks; we need faster tools."
   Root:   "We manually validate 30% of inputs — data governance is the constraint."
   Opportunity: Better data governance unlocks real-time planning (not faster tools).
   Technique: Acknowledge stated pain → probe "What's stopping faster?" →
   probe "If [constraint removed], what would you do differently?"

3. ALWAYS MONETISE IMPACT
   L2 decisions affect capex, ROI, and strategic feasibility. Translate pain into £:
   - Frequency × Impact = Cost  (e.g. 10 assets/year × £500k rework = £5M)
   - Decision quality × Volume = Value  (e.g. 5% better prioritisation × £350M = £17.5M)
   Prepare 2–3 monetisation narratives before each interview. Never leave "slow planning"
   as an abstract complaint — land it as a number.

4. TRIANGULATE ACROSS FOUR PERSPECTIVES
   One person's critical bottleneck is another's non-issue. Interview the same L2 from:
   - Owner:       "I drive this decision."
   - Consumer:    "I execute based on this decision."
   - Governance:  "I approve / audit this decision."
   - Support:     "I provide data / tools for this decision."
   The true root cause usually only surfaces after all four.

5. ASSESS MATURITY WITHOUT JARGON
   Do not use CMMI, COBIT, or ISO maturity language in the interview room — interviewees
   disengage. Use narrative questions that map onto the five-level ladder:
   Ad-hoc → Repeatable → Measured → Optimised → Predictive
   "Do you follow a documented process?" (Repeatable?)
   "Do you measure outcomes?" (Measured?)
   "Do you learn from past decisions?" (Optimised?)
   "Could you predict the impact before deciding?" (Predictive?)

6. PROBE DECISION GOVERNANCE EXPLICITLY
   Many organisations have fuzzy decision rights — slow, misaligned outcomes follow.
   Red flag phrase: "It depends who's in the room." → Governance gap.
   Questions: Who decides? By what criteria? How often do criteria change? What happens
   when stakeholders disagree? Could you defend this to the board?

7. MAP DATA AS A STRATEGIC ASSET
   Common pattern: L2 maturity is bottlenecked by data architecture, not process design.
   For each key decision: list input data sources → rate integration level (Siloed /
   Partially integrated / Fully integrated / Real-time) → identify highest-impact gaps
   → estimate effort and value unlock.

8. IDENTIFY FEEDBACK LOOP ASYMMETRIES
   Decisions flow down (L2 → L3). Learning rarely flows back (L3 → L2).
   Consequence: Decision assumptions ossify; outcomes are never validated.
   Questions: After a major decision, do you track whether it delivered expected value?
   Do you compare forecast vs. actual for lifecycle assumptions? When execution diverges
   from plan, do you ask why? Closing these loops is often the highest-value L4+ move.

9. DISTINGUISH QUICK WINS FROM STRATEGIC FOUNDATIONS
   Quick wins (efficiency, 6 months): faster reporting, better dashboards, automated alerts.
   Strategic foundations (effectiveness, 12–24 months): data governance, decision architecture.
   Aspirational (transformation, 18–36 months): real-time optimisation, predictive analytics.
   Do not oversell quick wins — they rarely move decision quality. Foundations unlock everything
   downstream. Aspirational changes require all upstream layers to be solid first.

10. SURFACE ORGANISATIONAL POLITICS
    L2 decisions cross silos — turf and incentive conflicts are inevitable.
    Surface questions: "Who would be threatened by better data visibility?"
    "What changes in people's roles if this becomes automated?"
    "Are there incentive misalignments?" (Finance optimises for cost; Operations for quality.)
    Maya's role: not to resolve politics, but to name them — this defines change management scope.
"""

_L2_MATURITY_TEMPLATE = """\
MATURITY ASSESSMENT TEMPLATE — PER L2 NODE
────────────────────────────────────────────
Complete this template as a synthesis output after each L2 interview series.
Use narrative evidence from interviews to justify each rating.

Decision clarity:    [Ad-hoc / Repeatable / Measured / Optimised / Predictive]
Evidence-base:       [Ad-hoc / Repeatable / Measured / Optimised / Predictive]
Data integration:    [Siloed / Partially integrated / Integrated / Real-time intelligent]
Feedback loops:      [None / Annual / Quarterly / Monthly / Real-time]
Overall maturity:    [L1 / L2 / L3 / L4 / L5]
"""

_L2_OUTPUT_TEMPLATE = """\
L2 INTERVIEW SUMMARY TEMPLATE — OUTPUT FORMAT PER NODE
────────────────────────────────────────────────────────
Produce one summary per L2 node in this structure. This is the deliverable, not just notes.

## Strategic Intent
- Primary decision(s): [What decision(s) does this L2 make?]
- Stakeholders: [Who decides? Who executes? Who approves?]
- Frequency: [Annual / Quarterly / Monthly / Real-time]
- Strategic priority: [Net-zero / Cost control / Risk / Service / other]

## Current Maturity
- Decision clarity:  [L1–L5 + one-sentence rationale]
- Evidence-base:     [L1–L5 + key gaps identified]
- Data integration:  [Siloed / Partial / Integrated / Real-time]
- Feedback loops:    [None / Annual / Quarterly / Monthly / Real-time]
- Overall maturity:  [L1–L5]

## Key Decision Quality Gaps
1. [Gap and monetised impact — e.g. "Risk prioritisation is gut-feel: est. £5M annual overrun"]
2. [Gap and monetised impact]
3. [Gap and monetised impact]

## Data Landscape
| Source      | Current State   | Issue         | Opportunity              |
|-------------|-----------------|---------------|--------------------------|
| [System 1]  | Siloed          | [Problem]     | [Fix → £ value estimate] |
| [System 2]  | Manual combine  | [Problem]     | [Fix → £ value estimate] |

## Orchestration Friction
- Upstream blockers:    [What delays inputs from L3s?]
- Cross-L2 conflicts:   [Where do other L2s' decisions conflict?]
- Downstream misalignment: [How well do L3s execute against this L2's decisions?]

## Maturity Trajectory & Prerequisites
- Current state: [e.g. L2–L3 analytical, annual review cycle, siloed data]
- Aspiration:    [e.g. L4 real-time, continuous learning, integrated data]
- Prerequisites to unlock:
  - [Data integration (6–9 months)]
  - [Decision governance review (2–3 months)]
  - [Analytical tooling (4–6 months)]
  - [Capability building (3–6 months)]

## Quick Wins (6–12 months)
1. [Win, £ value estimate, effort level]
2. [Win, £ value estimate, effort level]

## Strategic Transformation (12–24 months)
1. [Initiative, £ value estimate, effort, key risk]
2. [Initiative, £ value estimate, effort, key risk]

## Organisational Readiness
- Change appetite:  [Low / Medium / High]
- Key risks:        [Technical / Governance / Political / Capability]
- Critical sponsors: [Roles needed]

## Peer Interview Priorities
- [ ] [Upstream L3 lead]
- [ ] [Downstream executor]
- [ ] [Finance / governance stakeholder]
- [ ] [Data / IT stakeholder]
"""


def create_interaction_designer(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Interaction Designer",
        goal=(
            "Design a coherent set of interview scripts and maturity assessment questionnaires "
            "for every active L1, L2, and L3 value chain node, ensuring instruments at each "
            "level probe the right type of insight so findings can be triangulated across levels."
        ),
        backstory=(
            "You are a specialist in organisational assessment design. You combine management "
            "consulting interview technique with structured questionnaire design and deep "
            "knowledge of asset management standards (ISO 55001, IIMM, PAS 55) and the IIRC "
            "Six Capitals framework. You design instruments as a system: the interview script "
            "probes for qualitative insight and narrative while the questionnaire captures "
            "structured maturity ratings — both anchored to the same dimensions so the two "
            "data sources can be compared and synthesised.\n\n"
            + _CONCEPTUAL_SHIFT + "\n"
            + _L2_L3_FRAMEWORK + "\n"
            + _L2_PRINCIPLES +
            "\nYou never flatten these distinctions. A script written at the wrong level — "
            "asking a practitioner about strategy, or asking a GM about daily execution steps "
            "— wastes an interview slot. Every script must be calibrated to its audience, "
            "their time horizon, their complexity frame, and the AI opportunity relevant to "
            "their level."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_interaction_designer_task(
    agent: Agent,
    standards_references: str = "",
    preferred_sections: int = 4,
    preferred_questions: int = 3,
) -> Task:
    standards_block = (
        f"Standards and frameworks to draw on:\n{standards_references}\n\n"
        if standards_references
        else "Draw on ISO 55001, IIMM, PAS 55, IIRC Six Capitals, and sector best-practice.\n\n"
    )

    return Task(
        description=(
            "Design interview scripts AND maturity questionnaires for every active L1, L2, and "
            "L3 value chain node. L1 and L2 nodes require both an interview script and a maturity "
            "questionnaire. L3 nodes require an interview script only — the interview captures the "
            "qualitative, execution-level evidence that L2 questionnaires cannot reach.\n\n"
            + _CONCEPTUAL_SHIFT + "\n"
            + _L2_L3_FRAMEWORK + "\n"
            + standards_block +
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='value_chain_registry', "
            "agent_name='interaction_designer' to load the activity registry. "
            "Collect every entry where active=true and level is 'L1', 'L2', or 'L3'.\n"
            "2. Use SQLiteStateTool with operation='read', key='value_chain_summary', "
            "agent_name='interaction_designer' to understand the client's operations.\n"
            "3. Use ChromaQueryTool with collection='project' to gather corporate context "
            "(governance posture, known capability gaps, adopted standards, language used).\n\n"

            "── L1 NODES (strategic / portfolio level — GMs and value-stream owners) ────────\n"
            "4. For each L1 node:\n"
            "   a) Identify 3–4 strategic assessment dimensions focusing on strategic alignment, "
            "capability roadmaps, and value realisation "
            "(e.g. Vision & Strategy, Portfolio Governance, Capability Investment, "
            "Value Realisation).\n"
            "   b) Design an INTEGRATED INTERVIEW SCRIPT where each section covers one dimension "
            "with both narrative questions AND an embedded maturity rating at the end:\n"
            "      - 3–4 sections, one per strategic dimension\n"
            f"      - {preferred_questions} narrative questions per section (open, exploratory)\n"
            "      - Each section ends with a maturity_rating block (see schema below) — the "
            "rating is captured AFTER the narrative discussion, not before\n"
            "      - welcome_message and closing_message (warm, senior-level tone)\n"
            "      - research_brief and study_objectives framed at portfolio level\n"
            "      - follow_up_branches and evasion_signals per question\n"
            "      - target duration: 20–25 minutes\n"
            "   No separate questionnaire. The maturity ratings are embedded in the script.\n\n"

            "── L2 NODES (operational / process-stage level — process managers) ─────────────\n"
            "5. For each L2 node, apply all 10 L2 Interview Principles from your backstory. "
            "Core question: 'How do we orchestrate & decide better?' Time horizon: next quarter/year. "
            "AI opportunity: decision support. Success metric: decision quality / value realisation.\n\n"
            "   BEFORE designing the script, complete this preparation:\n"
            "   - Identify all L3 nodes that feed this L2 (from value_chain_registry)\n"
            "   - Identify the downstream consumers of this L2's decisions\n"
            "   - Draft a monetisation narrative: what is the £ impact of poor decisions here?\n"
            "     Apply the formula: Frequency × Impact = Cost OR Decision quality × Volume = Value\n"
            "   - Sketch the decision architecture: what decisions are made, who makes them, "
            "what data flows in?\n"
            "   - Identify 3–5 peer interviewee perspectives to triangulate: owner, consumer, "
            "governance, support\n\n"
            "   a) Frame the L2 as a DECISION CLUSTER, not a sequence. The sections of the "
            "interview script should map to the orchestration logic across the L3s, not to "
            "the execution steps of any single L3. Ask: what decision do these L3s collectively "
            "enable?\n\n"
            "   b) Identify 3–5 assessment dimensions rooted in the L2 maturity anchors: "
            "evidence-base, rigor, learning loops, governance "
            "(e.g. Decision Evidence, Process Governance, Cross-functional Coordination, "
            "Outcome Tracking, Improvement Rigour).\n\n"
            "   c) Design an INTERVIEW SCRIPT with:\n"
            "      - 4–5 sections aligned to the L2 orchestration dimensions\n"
            f"      - {preferred_questions} questions per section, probing orchestration "
            "friction: misalignment, siloed decisions, slow feedback loops\n"
            "      - Opening framing: anchor on 'How do we orchestrate & decide better?' — "
            "use portfolio-level language (quarters, capex, strategic feasibility)\n"
            "      - Root constraint probe per section: after each stated pain, include a "
            "follow-up that separates the stated problem from the root constraint "
            "(e.g. 'What's actually stopping a faster decision here?')\n"
            "      - Feedback loop probe: 'After this decision was made, did you track "
            "whether it delivered the expected value?'\n"
            "      - Governance probe: 'Who makes this decision? Is that clear to everyone?'\n"
            "      - Data mapping probe: for each decision, ask which data sources feed it "
            "and rate their integration (Siloed / Partially integrated / Integrated / Real-time)\n"
            "      - Aspiration section: ask about DECISION SUPPORT — what would help them "
            "decide better or faster; do NOT ask about automation (that is L3)\n"
            "      - Impact section: frame around cost of poor DECISIONS — misallocated "
            "investment, missed signals, delayed pivots. Monetise with Frequency × Impact "
            "or Decision quality × Volume formulae. Not operational rework/downtime (L3).\n"
            "      - welcome_message and closing_message (professional, strategic tone)\n"
            "      - research_brief and study_objectives framed at process orchestration level\n"
            "      - follow_up_branches (2 per question) and evasion_signals per question\n"
            "      - target duration: 25–30 minutes\n\n"
            "   d) Each section of the L2 script must end with a maturity_rating block "
            "(see schema below). The rating is always captured AFTER the narrative questions "
            "in that section — never before. The interviewer should say something like: "
            "'Based on what you've just described, how would you rate [dimension] for this "
            "decision? Let me read you the levels.' Then read the scale and record the response.\n"
            "   The five levels for L2 ratings (use these labels verbatim in the scale object):\n"
            "      0 — Ad-hoc: no structured approach; decisions are informal and undocumented\n"
            "      1 — Initial: some attempts at structure, but inconsistent and unverified\n"
            "      2 — Developing: documented process but not consistently applied or reviewed\n"
            "      3 — Managed: systematic approach with regular review and outcome tracking\n"
            "      4 — Predictive: real-time evidence, continuous learning, anticipates outcomes\n"
            "   No separate questionnaire. The ratings are fully embedded in the script.\n\n"
            "   e) After drafting, produce one L2 Interview Summary using this template:\n"
            + _L2_OUTPUT_TEMPLATE + "\n"

            "── L3 NODES (activity level — practitioners and operational staff) ──────────────\n"
            "6. For each L3 node — anchored to the L2 vs L3 framework: core question is "
            "'How do we execute faster & better?', time horizon is next task/next day, "
            "AI opportunity is automation (RPA, ML classification, routing), success metric "
            "is cycle time / error rate / cost per execution. Complexity is operational "
            "friction: wait time, rework, manual steps.\n"
            "   The script must surface where effort is wasted, where data is missing or stale, "
            "and where a smarter tool would change behaviour.\n"
            "   Design an INTERVIEW SCRIPT with EXACTLY these 8 sections in this order, "
            "each with a target_minutes field and the question framing shown:\n\n"
            "   Section 1 — Opening (target_minutes: 5)\n"
            "     Context question: Explain you are mapping [L3 process] to understand how "
            "AI/digital could help.\n"
            "     Framing question: 'I want to understand both what's slow and what's uncertain.'\n\n"
            "   Section 2 — Current State (target_minutes: 10)\n"
            "     Walk-through: 'Take me through a recent [process instance].'\n"
            "     Frequency: 'How often does this happen?'\n"
            "     Effort: 'How long? Who's involved? What are the steps?'\n"
            "     Pain: 'What frustrates you most about this?'\n\n"
            "   Section 3 — Decision Quality (target_minutes: 8)\n"
            "     Outcomes: 'How do you know if you did this well?'\n"
            "     Confidence: 'How confident are you in the outcomes?'\n"
            "     Maturity: 'How repeatable / consistent is this?'\n"
            "     Unmet needs: 'What would you decide differently if you could?'\n\n"
            "   Section 4 — Data & Dependencies (target_minutes: 7)\n"
            "     Inputs: 'Where does your data come from?'\n"
            "     Quality: 'Do you trust it? Is it fresh?'\n"
            "     Handoffs: 'Who upstream feeds you? Who downstream depends on you?'\n"
            "     Gaps: 'What's missing or siloed?'\n\n"
            "   Section 5 — Impact & Monetisation (target_minutes: 5)\n"
            "     Frame around OPERATIONAL failure cost (not strategic misalignment — that is L2):\n"
            "     Cost of failure: 'What happens when this process goes wrong — rework, "
            "downtime, errors passed downstream?'\n"
            "     Frequency: 'How often does that happen?'\n"
            "     Prevention potential: 'How much could we reduce with better automation or "
            "real-time visibility?'\n"
            "     Value at stake: 'Rough estimate of cost per occurrence or per year?'\n\n"
            "   Section 6 — Scenario & Resilience (target_minutes: 5)\n"
            "     Edges: 'What's the hardest situation you've encountered with this activity?'\n"
            "     Adaptation: 'How did you handle it?'\n"
            "     Robustness: 'What conditions would cause this process to break down?'\n\n"
            "   Section 7 — Aspiration (target_minutes: 5)\n"
            "     Frame around AUTOMATION opportunity (not decision support — that is L2):\n"
            "     Automation target: 'If you could automate one step in this process, "
            "what would it be and why?'\n"
            "     New capability: 'If the manual steps disappeared, what would you spend "
            "that time on instead?'\n"
            "     Readiness: 'What would it take for you to trust an AI tool to handle "
            "part of this?'\n\n"
            "   Section 8 — Closing (target_minutes: 2)\n"
            "     Referral: 'Who else should I talk to to understand this?'\n\n"
            "   Additional L3 script requirements:\n"
            "     - welcome_message: warm, peer-to-peer tone, emphasise no right/wrong answers\n"
            "     - closing_message: thank the practitioner, explain how insights will be used\n"
            "     - research_brief and study_objectives framed at activity level\n"
            "     - Each question must have follow_up_branches (2 probing follow-ups) and "
            "evasion_signals (phrases that indicate the interviewee is being vague)\n"
            "     - Total target_minutes across all 8 sections must be 47; the interview "
            "itself runs 20–30 minutes because not every branch is taken\n"
            "     - L3 sections do NOT include a maturity_rating block — omit the field entirely\n\n"

            "── OUTPUT ───────────────────────────────────────────────────────────────────────\n"
            "7. Output ALL INTERVIEW SCRIPTS (L1, L2, and L3) as a single JSON object keyed "
            "by node_label. L1 and L2 sections include a maturity_rating block; L3 sections "
            "do not. This is the ONLY script artefact — there is no separate questionnaire.\n"
            "   {\n"
            "     \"<node_label>\": {\n"
            "       \"node_label\": \"<node_label>\",\n"
            "       \"level\": \"L1\" | \"L2\" | \"L3\",\n"
            "       \"research_brief\": \"...\",\n"
            "       \"study_objectives\": [\"...\"],\n"
            "       \"welcome_message\": \"...\",\n"
            "       \"closing_message\": \"...\",\n"
            "       \"sections\": [\n"
            "         {\n"
            "           \"title\": \"...\",\n"
            "           \"target_minutes\": <int>,\n"
            "           \"questions\": [\n"
            "             {\n"
            "               \"id\": \"Q1\",\n"
            "               \"text\": \"...\",\n"
            "               \"follow_up_count\": 2,\n"
            "               \"probing_instructions\": \"...\",\n"
            "               \"follow_up_branches\": [\"...\", \"...\"],\n"
            "               \"evasion_signals\": [\"not sure\", \"it varies\"]\n"
            "             }\n"
            "           ],\n"
            "           \"maturity_rating\": {   // PRESENT for L1 and L2 sections; OMIT for L3\n"
            "             \"dimension\": \"<assessment dimension name>\",\n"
            "             \"prompt\": \"Based on what you've just shared, how would you rate "
            "[dimension] here? Let me read you the levels.\",\n"
            "             \"scale\": {\n"
            "               \"0\": \"<label describing Ad-hoc state for this dimension>\",\n"
            "               \"1\": \"<label describing Initial state>\",\n"
            "               \"2\": \"<label describing Developing state>\",\n"
            "               \"3\": \"<label describing Managed state>\",\n"
            "               \"4\": \"<label describing Predictive/Optimised state>\"\n"
            "             },\n"
            "             \"capture_after\": \"narrative_complete\",\n"
            "             \"probe_on_mismatch\": \"You described [X] but rated it [N] — "
            "what would a [N+1] look like for you?\"\n"
            "           }\n"
            "         }\n"
            "       ]\n"
            "     }\n"
            "   }\n"
            "   The scale labels must be SPECIFIC to the dimension — not generic. "
            "E.g. for 'Evidence-base' in an L2 risk decision: 0='Risk decisions are gut-feel "
            "with no documented evidence', 4='Risk scoring is driven by real-time sensor data "
            "and predictive models'. Make each label a concrete description of that state "
            "in the client's operational context.\n"
            "   Use SQLiteStateTool with operation='write', key='interview_scripts', "
            "agent_name='interaction_designer' to save this.\n\n"
            "8. Save L2 INTERVIEW SUMMARIES (one per L2 node, produced in step 5e) as a "
            "JSON object keyed by node_label:\n"
            "   { \"<node_label>\": { <fields from L2 Interview Summary Template> } }\n"
            "   Use SQLiteStateTool with operation='write', key='l2_interview_summaries', "
            "agent_name='interaction_designer' to save this.\n\n"
            "9. Use HumanInputTool with prompt: 'Assessment instruments saved. Please review:\n"
            "   • outputs/interview_scripts.json — integrated scripts for all L1, L2, and L3 "
            "nodes. L1 and L2 sections each end with an embedded maturity rating. Check that:\n"
            "     - Each rating prompt reads naturally after the section's narrative questions\n"
            "     - Scale labels are specific to the dimension and client context (not generic)\n"
            "     - The probe_on_mismatch phrase is usable by the interviewer in conversation\n"
            "     - L3 sections have no maturity_rating block\n"
            "   • outputs/l2_interview_summaries.json — decision architecture prep per L2 node\n"
            "   Reply \"approved\" to proceed, or provide revision notes.'\n"
            "10. If revision notes received, revise and call HumanInputTool again. "
            "Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "Two artefacts saved via SQLiteStateTool: (1) interview_scripts.json — one "
            "integrated script per L1, L2, and L3 node; L1 and L2 sections each contain a "
            "maturity_rating block with dimension-specific scale labels captured after the "
            "narrative discussion; L3 scripts have exactly 8 sections with no maturity_rating; "
            "(2) l2_interview_summaries.json — one L2 Interview Summary per L2 node containing "
            "decision architecture, data landscape, orchestration friction, monetised opportunity, "
            "and peer interview priorities. No separate questionnaire artefact. "
            "All approved by human reviewer."
        ),
        agent=agent,
    )
