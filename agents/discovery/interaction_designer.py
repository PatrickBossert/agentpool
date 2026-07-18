# agents/discovery/interaction_designer.py
"""Interaction Designer — designs interview scripts and maturity questionnaires together."""
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool

_CONCEPTUAL_SHIFT = """\
CONCEPTUAL SHIFT — L0 → L1 → L2 → L3  |  C (Customer — outside-in)
─────────────────────────────────────────────────────────────────────
L0 interviews:  Focus on portfolio logic, capital allocation, and competitive positioning.
                Talk to board members and C-suite executives. Understand where investment
                should go across the full asset-management portfolio, what trade-offs are
                acceptable, and what governance ensures value realisation at portfolio level.

L1 interviews:  Focus on strategic alignment, capability roadmaps, value realisation.
                Talk to GMs and value-stream owners. Explore where investment is not
                yielding returns, what capabilities are missing, and how value is measured.

L2 interviews:  Focus on orchestration logic, decision architecture, portfolio coherence.
                Talk to process managers. Surface how work is sequenced, where decisions
                are made without adequate information, and how trade-offs are resolved.

L3 interviews:  Focus on execution fidelity, data freshness, bottleneck removal.
                Talk to practitioners. Uncover where effort is wasted, where data
                is missing or stale, and where a smarter tool would change behaviour.

C  interviews:  OUTSIDE-IN (SERVICE) — focus on service quality, reliability, and
                partnership experience as perceived by customers whose operations depend
                on managed assets. Talk to Regional Operations Leaders, Field Teams,
                Network Planners, and customer-facing functions. Reveal what actually
                matters to customers (vs. what we think matters), expose gaps between
                internal narrative and external reality, identify unmet needs, and
                validate the ROI narrative ("will transformation improve customer
                experience?"). Customer voice is the most credible external evidence
                for the change business case.

A  interviews:  OUTSIDE-IN (GOVERNANCE) — focus on whether controls are working,
                promises are being kept, risks are managed, and the organisation is
                delivering what it committed to. Talk to internal and external auditors,
                compliance officers, and regulators (e.g. Ofgem, ORR). Provide
                independent assessment of governance maturity, compliance status,
                financial controls, KPI data integrity, third-party management, and
                transformation readiness. Audit voice is the most credible evidence
                for governance credibility and remediation priorities.

Instruments must reflect these shifts:
  L3 scripts probe the texture of daily work;
  L2 scripts probe decision quality and orchestration;
  L1 scripts probe strategy and capability maturity;
  L0 scripts probe portfolio logic and capital allocation;
  C  scripts probe service quality, friction, and transformation readiness from
     the customer's operational lens — not the organisation's internal perspective;
  A  scripts probe governance maturity, control effectiveness, compliance status,
     and transformation risk from an independent assurance perspective.
All six instrument types contribute different data that the Synthesis Analyst will
triangulate into a unified set of findings.
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

_L2_FRAMING_TEMPLATE = """\
L2 FRAMING BLOCK — MANDATORY OPENING STRUCTURE
────────────────────────────────────────────────
Every L2 script must begin with a framing_block that orients the interviewee to the
decision-cluster model BEFORE any questions are asked. This is separate from the
welcome_message (which is personal and warm) and from Section 1 (which probes).

The framing_block has three fixed parts. Customise each to the specific node:

POSITIONING (1–2 sentences)
   Template: "We're mapping [L2 cluster name] — the strategic layer that coordinates
   [list of L3 activity names] and feeds [key decisions, e.g. capex prioritisation,
   fleet strategy, works programming]."
   Purpose: Signals immediately that this is not an operational interview; it is
   a decision architecture conversation. Sets the cognitive frame before Q1.

CONTEXT SETTING (2–3 bullets)
   Template:
   • "This cluster sits between [upstream governance / L1 node name] and
      [downstream execution teams / L3 node names]."
   • "We want to understand how decisions *flow* through this cluster — not just
      what happens, but where decision quality is built in or lost."
   • "And where better data, clearer governance, or smarter analysis could unlock
      more value for [strategic objective, e.g. the net-zero programme / capex ROI]."
   Purpose: Establishes the L2's position in the value chain so the interviewee can
   speak to upstream/downstream relationships without prompting.

DUAL LENSES (2 framing statements)
   Efficiency lens (fixed): "First, I want to understand coordination friction —
   what slows decisions down, creates rework, or blocks alignment."
   Effectiveness lens (fixed): "And second, I want to understand decision quality —
   what decisions are being made here, how confident you are in them, and what
   decisions you *should* be making but currently can't."
   Purpose: Names both lenses explicitly so the interviewee knows you are interested
   in more than operational speed. The effectiveness lens often unlocks disclosures
   that a pure efficiency frame would never surface.

TONE NOTE: The framing_block is spoken by the interviewer, not read from a screen.
Write it in natural spoken English — shorter sentences, no jargon, no bullet structure.
"""

_L2_SECTION_LIBRARY = """\
L2 SECTION LIBRARY — SELECT 4–5 SECTIONS FOR EACH NODE
────────────────────────────────────────────────────────
The following 8 thematic sections form a reference library. Maya selects the most
relevant 4–5 sections for each node based on its strategic priority and available
interview time (target: 25–30 minutes standard; 45–60 minutes for senior stakeholders
or high-priority nodes). Sections S1 and S2 are mandatory for every L2.

Each section maps to a theme — design specific questions from these themes, informed
by the node's L3 inputs, downstream consumers, and corporate context.

MANDATORY ─────────────────────────────────────────────────────────────────────────

S1. Strategic Intent & Decision Architecture (~8 min standard, ~12 min deep-dive)
   Core themes:
   - Decision mapping: what strategic or operational decisions does this L2 exist to support?
   - Decision dependency: who makes each decision, at what cadence, based on what inputs?
   - Unmade decisions: what decision would be *better* if you had perfect information?
   - Decision quality: confidence levels, how errors surface, how often decisions are reversed
   - Strategic alignment: which corporate KPI does this L2's output directly trace to?
   Maturity anchor: Decision Clarity
   Maturity narrative signals:
     0 (Ad-hoc): "It depends who's in the room." / "The boss decides."
     1 (Initial): "We have a process but people don't always follow it."
     2 (Developing): "We have documented criteria; we use them most of the time."
     3 (Managed): "We measure decision inputs and track outcomes quarterly."
     4 (Predictive): "We model scenarios and forecast impacts before deciding."

S2. Decision Maturity & Governance (~10 min)
   Core themes:
   - Maturity assessment: how structured, documented, and evidence-based are decisions?
     (Use narrative diagnostic questions from S1 maturity signals — do NOT use jargon)
   - Decision rights: who decides at each step? Is it clear, documented, and stable?
   - Evidence & discipline: what data is used? Are assumptions documented? Can decisions
     be defended if challenged?
   - Red flag signals: "It depends who's in the room" → governance gap; "gut feel mostly"
     → ad-hoc; "we have a template but skip steps" → developing
   Maturity anchor: Evidence-base & Governance
   Maturity narrative signals:
     0: "No one asks us to justify decisions — we just make them."
     1: "We collect some data but it's not integrated into the decision."
     2: "We have a template for documenting our assumptions."
     3: "We document assumptions and revisit them at quarterly reviews."
     4: "We track decision outcomes and update our models from results."

RECOMMENDED — INCLUDE 2–3 BASED ON NODE CONTEXT ──────────────────────────────────

S3. Data Landscape & Decision Enablement (~8 min)
   Core themes:
   - Input data inventory: for each key decision, what data feeds it? Name systems.
   - Integration maturity: is data manual-combined, partially automated, or real-time?
     (Siloed / Partially integrated / Integrated / Real-time intelligent)
   - Data trust: do decision-makers trust the data? What would need to be true to trust
     it fully? Who is accountable if data is wrong?
   - Hidden opportunities: what data exists in adjacent systems that isn't used?
     What's stopping integration? (Technical / Ownership / Governance / Friction)
   - Hidden cost: how many hours per week does the team spend extracting or combining
     data manually? (Often 20–50 hrs/week — translate to £ per year)
   Best for: nodes where data governance is a known pain, or where integration is fragmented

S4. Decision Velocity & Orchestration Friction (~8 min)
   Core themes:
   - Cycle time: how long from "we need to make this decision" to "decision communicated"?
     Break down into active work / wait time / rework time
   - Bottleneck: of that time, what's unavoidable? What's friction? If you had to cut it
     in half, where would you start?
   - L3 handoffs: which L3 outputs does this L2 depend on? Are they reliable, timely,
     fit for purpose? What are the workarounds when they're not?
   - Cross-L2 dependencies: does this L2 depend on outputs from another L2? How are
     changes in that upstream L2 handled?
   Best for: nodes where decision cycle time is a known pain, or where cross-L2 misalignment
   is visible in the project context

S5. Decision Quality Gaps & Maturity Opportunities (~8 min)
   Core themes:
   - Scenario planning: do decision-makers consider multiple scenarios, or make a best guess?
     (Ad-hoc / Structured upside-downside / 3–5 weighted scenarios / Adaptive forecasting)
   - Learning loops: after a major decision, is outcome tracked? How long until you find out
     if it was right? What prevents learning faster?
   - Hidden opportunity ceiling: what decision *would you like* to make in this L2 but can't?
     What would it take? (Data? Analysis? Governance? Tools?)
   - Aspiration monetisation: how much value would that new capability unlock?
   Best for: high-priority nodes where aspiration and value opportunity need to be quantified

S6. Orchestration Effectiveness & Downstream Impact (~8 min)
   Core themes:
   - Execution fidelity: what % of this L2's decisions/plans are executed as intended at L3?
     What causes deviation? (Unrealistic plan / conditions changed / communication unclear /
     resources unavailable / L3 has better local information)
   - Value realisation: can you trace a decision in this L2 to a specific business outcome?
     Do you measure the value your decisions create?
   - Feedback from L3 executors: "I'm going to ask your downstream teams the same questions —
     what should I expect to hear?" (Confident positive = alignment; defensive/qualified =
     friction; "I'm not sure" = transparency gap)
   Best for: nodes where L3 execution fidelity is a concern, or where value realisation
   is not being tracked

OPTIONAL — INCLUDE FOR SENIOR STAKEHOLDERS OR HIGH-PRIORITY NODES ──────────────────

S7. Hidden Orchestration Opportunities (~6 min)
   Core themes:
   - Cross-L3 optimisation: are there decisions within individual L3s that, if coordinated
     at this L2, could produce better outcomes? What's blocking that coordination?
   - New decision opportunities: are there decisions that *should* live in this L2 but
     currently don't? Why not? (Too complex / No authority / Data unavailable /
     Too many stakeholders)
   - Feedback loop redesign: what would happen if you had real-time feedback on L3 outcomes?
     What is the latency cost of the current feedback loop?
   Best for: strategically critical nodes, or where the interviewee is a senior decision-maker
   with cross-portfolio visibility

NOTE ON SECTION 7 (Comparative Assessment from 9-section reference):
   Do NOT include cross-L2 comparative ranking questions in the interview script.
   Asking interviewees to rank this L2 against others they may not govern produces
   unreliable answers. Comparative assessment is Maya's analyst synthesis task,
   done after all interviews, not an interview question.

CLOSING (ALWAYS INCLUDE — see synthesis_check schema) ──────────────────────────────
   After all sections: synthesis_check (described in schema below), then peer referral
   ("Who else should I speak to?"), then closing_message.
   Target: 5 minutes.

SECTION SELECTION RULES
   Standard L2 (25–30 min):  S1 + S2 + select 2 from {S3, S4, S5, S6} + closing
   Deep-dive L2 (45–60 min): S1 + S2 + S3 + S4 + select 1–2 from {S5, S6, S7} + closing
   Priority signals for selection:
   - Known data governance pain → include S3
   - Decision cycle time > 4 weeks → include S4
   - High-value strategic node → include S5
   - L3 execution complaints → include S6
   - Senior interviewee with cross-portfolio view → add S7
"""

_L2_SYNTHESIS_TEMPLATE = """\
L2 SYNTHESIS CHECK — MANDATORY CLOSING ELEMENT
────────────────────────────────────────────────
Before closing_message, every L2 script must include a synthesis_check that validates
the interviewer's emerging picture with the interviewee. This is not a question — it
is a reflective summary offered to the interviewee for correction and endorsement.

The synthesis_check has four elements:

1. SYNTHESIS PROMPT (interviewer speaks this)
   Template: "Before I let you go — based on what you've told me, here's how I see
   this cluster: [brief synthesis of strategic intent], [current maturity level and
   why], [the biggest constraint on decision quality], [the key data gap], [the value
   opportunity]. Does that match your assessment?"
   This must be customised to the node in the script. Do not leave it as a template —
   Maya should draft a plausible synthesis based on the node's known context, which the
   interviewee will then confirm or correct.

2. RESPONSE PROBES (interviewer uses one based on the reply)
   - If positive confirmation: "Good — what would you add or emphasise differently?"
   - If qualified or defensive: "Where does my picture differ from yours?"
     (This is the most valuable response — it surfaces blind spots or political sensitivities
     that the interviewee would not have volunteered as an answer to a direct question.)
   - If uncertain or deflecting: "What would you want me to verify with others?"
     (Flags where this interviewee's view may be incomplete or isolated.)

3. PEER REFERRAL
   "Who else should I speak to in order to get a full picture of this cluster?
   I'm looking for [upstream input providers / downstream executors /
   governance stakeholders / data and IT owners]."

4. FORWARD ROADMAP
   "If you were shaping how we improve this cluster, where would you start —
   quick wins in the next 6 months, or building the foundations for the next 2 years?
   And what's your biggest concern about making that change?"

TONE NOTE: The synthesis should feel like a collegial debrief, not a report-back.
The interviewer is checking understanding and inviting correction — not presenting
conclusions. Language: "Here's how I see it — tell me where I'm wrong."
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
- Decision clarity:  [0–4 rating: 0=Ad-hoc, 1=Initial, 2=Developing, 3=Managed, 4=Predictive + rationale]
- Evidence-base:     [0–4 rating + key gaps identified]
- Data integration:  [Siloed / Partially integrated / Integrated / Real-time]
- Feedback loops:    [None / Annual / Quarterly / Monthly / Real-time]
- Overall maturity:  [0–4 composite + one-sentence justification]

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
- Current state: [e.g. 2 (Developing) — analytical but annual cycle, siloed data]
- Aspiration:    [e.g. 4 (Predictive) — real-time, continuous learning, integrated data]
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


_L0_PRINCIPLES = """\
L0 INTERVIEW PRINCIPLES — MAYA'S JUDGMENT HEURISTICS
──────────────────────────────────────────────────────
These six principles govern every L0 design and execution. L0 interviews are shorter,
more focused, and more decision-oriented than any other level.

1. PORTFOLIO THINKING — NEVER OPTIMISE ONE L1 IN ISOLATION
   L0 interviewees govern the whole portfolio. Never ask about one L1 capability alone —
   always ask how the capabilities fit together. "Which L1 do you prioritise?" reveals real
   allocation logic. "How do they interact?" reveals portfolio coherence or its absence.
   ✗ "How important is Property transformation to you?"
   ✓ "How do Property and Fleet transformation fit together in your capital agenda —
      and if forced to sequence, which goes first and why?"

2. EXECUTIVE BREVITY — 30 MINUTES MAXIMUM
   Board-level interviewees will not tolerate drift. State the structure upfront. Hold to it.
   Keep each section to its target. Skip questions the interviewee has already answered.
   Do not let any single answer run past 3 minutes without redirecting. Silence is not
   time to fill — it is time to think.

3. CAPITAL DISCIPLINE — ALWAYS TIE TO £ AND ROI
   "Important" and "strategic" are not investments. Tie every claim to a number: total capex,
   expected ROI, payback period, hurdle rate, risk-adjusted downside. If the interviewee
   cannot quantify, probe why: "What would it take to put a number on that?"
   Unquantified value = undefendable investment at board level.

4. RISK REALISM — NAME THE HARD TRUTHS
   Executives respect candour more than optimism. Name execution risks, governance gaps, and
   strategic trade-offs directly. Probe: "What could break this?" "What's your worst case?"
   "If the ROI comes in at 1.2x — do you hold or fold?"
   Do not let "it will work out" stand as a risk management answer.

5. DECISION CLARITY — CLARIFY WHAT IS BEING DECIDED AND BY WHOM
   L0 interviews serve one purpose above all others: clarifying the decision.
   "What are you asking the board to approve?" If vague, the governance process is not ready.
   Before closing, every L0 interview must produce a clear statement of: the decision, the
   decision-maker, the criteria, and the timing.

6. ALIGNMENT TEST — TRIANGULATE ACROSS EXECUTIVES
   Different L0 interviewees (CEO, CFO, Chair) give different answers on priorities, ROI
   expectations, and risk tolerance. These discrepancies are findings. Name them in the output
   summary: "The CFO expects 2.5× ROI; the operations head expects 1.8× — this gap needs
   resolution before board approval." Do not smooth over executive disagreements.
"""

_L0_FRAMING_TEMPLATE = """\
L0 FRAMING BLOCK — MANDATORY OPENING STRUCTURE
────────────────────────────────────────────────
Every L0 script must begin with a framing_block that positions the conversation at
portfolio level before any questions are asked. This is separate from the welcome_message
(personal, brief, professional) and from Section 1 (which probes strategic mandate).

POSITIONING (framing_block.positioning — 1–2 sentences)
   Template: "We're assessing [organisation]'s total portfolio of asset-management
   transformations — [L1 capabilities listed]. We want to understand: how these fit
   your corporate strategy, where investment should concentrate, what constraints apply,
   and what governance ensures value realisation."
   Frame as a portfolio assessment, not an individual capability review.

CONTEXT SETTING (framing_block.context_setting — 4–5 bullets)
   Template bullets:
   • "Strategic coherence: how do [L1 capabilities] fit your corporate strategy and
      compete for capital against other priorities?"
   • "Capital efficiency: are we investing in the right things, at the right scale,
      in the right sequence?"
   • "Risk & trade-offs: what constraints apply, and which strategic trade-offs
      most concern you?"
   • "Governance: who is accountable, how is progress tracked, and what is the
      course-correction mechanism?"
   • "Competitive positioning: where do you want to lead — and what would it take?"

DUAL LENSES (framing_block.dual_lenses — L0 variant)
   dual_lenses.efficiency (portfolio investment health):
   "First, I want to understand the current investment logic — where capital is going,
   what return is expected, and where the constraints are."

   dual_lenses.effectiveness (portfolio transformation potential):
   "Second, I want to understand what should be true — where to concentrate investment,
   what sequencing makes strategic sense, and how to build board confidence in the case."
"""

_L0_SECTION_GUIDE = """\
L0 SECTION GUIDE — FIXED 6-SECTION STRUCTURE
──────────────────────────────────────────────
L0 interviews use a FIXED structure — all 6 sections are always included. Unlike L1 and L2,
there is no section library or selection logic. The 30-minute constraint is met by keeping
each section to its target and skipping questions the interviewee has already answered.

Total section time: ~40 minutes on paper; runs ~25–30 minutes in practice because senior
interviewees typically answer multiple questions in a single response.

DO NOT include maturity_rating blocks in any L0 section. Maturity assessment is L1's job.
L0 interviewees assess portfolio logic and capital decisions, not operational capability.

S1. Strategic Mandate & Portfolio Logic (~8 min)
   Core themes:
   - Portfolio role: How do the L1 capabilities fit the corporate strategy — strategic
     enablers, cost centres, or competitive differentiators?
   - Trade-off framing: How do the L1 capabilities compete for capital, talent, or executive
     attention? Where are they interdependent?
   - Capital allocation philosophy: priority ranking; ROI hurdle rates by category; multi-year
     commitment vs. annual discretionary.
   - Gating factor: "Are you more constrained by capex budget, organisational capacity, or
     strategic clarity?" Reveals the binding portfolio constraint.
   - Forced choice: "If you could do only ONE transformation in the next 3 years, which and why?"
     Reveals true priority; often surfaces misalignment with L1 leaders.

S2. Competitive Positioning & Disruption (~6 min)
   Core themes:
   - Benchmarking: How does the organisation's portfolio compare to competitors? Digital maturity,
     cost competitiveness, net-zero readiness, talent attraction?
   - Biggest threat: What threatens the current operating model? Disruption / regulation /
     economics / talent / technology?
   - Upside: What is the competitive advantage if transformation succeeds?
   - Contingencies: What would cause significant change of direction? Acceleration or delay
     triggers? Monetise the contingency scenarios.

S3. Capital Allocation & ROI Discipline (~8 min)
   Core themes:
   - ROI expectations: Total investment (£X over Y years); quantified benefits; payback period;
     risk-adjusted range (best / likely / worst).
   - Measurable vs. strategic: How do you balance cost-reduction ROI (quantifiable) vs.
     strategic enablement (harder to quantify but often the real value driver)?
   - Downside tolerance: Breakeven point; "if ROI comes in at 1.2× — do you hold or fold?"
   - Value tracking: How will realisation be tracked? "We'll know it when we see it" → probe for
     specifics. Single KPI framework or per-capability dashboards?
   - Course-correction trigger: "If returns lag forecast by 20%, what happens?"

S4. Organisational Readiness & Execution Risk (~7 min)
   Core themes:
   - Parallel vs. sequential: Can the organisation execute multiple L1 transformations
     simultaneously? Shared dependencies (data platform, talent, sponsors)?
   - Top execution risks: Technical (integration, legacy) / organisational (skills, capacity,
     leadership turnover) / financial (overrun, benefit slippage) / market / partnership /
     governance.
   - Mitigation: "What is your mitigation strategy for the top 3 risks?"
   - Key person dependency: Critical leaders and succession risk.
   - Course-correction mechanism: "How will you know if you're off track?"

S5. Governance, Accountability & Measurement (~6 min)
   Core themes:
   - Accountability: Who is accountable for portfolio ROI? "Shared" → diffused accountability
     (will underperform). "I'm not sure" → governance gap.
   - Review cadence: Monthly / quarterly / annual / ad-hoc.
   - Metrics: What metrics matter most — cost, schedule, value realisation, capability, risk?
   - Short vs. long-term balance: How do you protect transformation investment from short-term
     cost pressure? Many programmes fail because investment is cut mid-stream.
   - Kill criteria: "What could cause the board to cancel or significantly deprioritise this?"

S6. Strategic Priorities & Board Questions (~5 min)
   Core themes:
   - Key message: "What is the #1 thing you want the board to understand?" Vague answer
     reveals strategic clarity gap.
   - Board Q&A readiness: "What board questions do you anticipate? How will you answer them?"
     Standard board questions: Why now? What's the ROI? What could go wrong? Can you execute?
     How does this compare to other investments? When will we see value?
   - Board alignment: "Are you aligned with the board on this strategy?" If vague → governance
     gap. Probe what is uncertain or contested.
   - Decision statement: "What specific decision are you asking the board to make?" Should be
     crisp and actionable. Vague = not board-ready.
"""

_L0_SYNTHESIS_TEMPLATE = """\
L0 SYNTHESIS CHECK — MANDATORY CLOSING ELEMENT
────────────────────────────────────────────────
L0 synthesis_check has FOUR elements — two more than L1/L2. The additional elements
(portfolio_options and sponsorship_check) are unique to board/exec level and use
two new optional schema fields not present in L1/L2 synthesis_checks.

1. SYNTHESIS PROMPT (interviewer speaks this)
   Template: "Based on what you've told me, here's the strategic picture: [L1 capabilities]
   transformation is [strategic/tactical] to [organisation]; total investment envelope is
   [£X] over [Y years], with ROI expectations of [Z] and payback by [period]; the key
   constraint is [capex/capacity/clarity]; the biggest execution risk is [named risk]; and
   the decision the board needs to make is [clear decision statement].
   Does that capture it correctly? What am I missing?"
   MUST be customised to the specific interviewee and portfolio context. No placeholders.

2. RESPONSE PROBES
   - If positive: "Good — what would you emphasise differently, or what did I miss?"
   - If qualified or defensive: "Where does my picture differ from yours — and why?"
     (Surfaces undisclosed constraints or political tensions at exec level.)
   - If uncertain: "What needs to be resolved before you'd be confident in that picture?"
     (Reveals what is genuinely unknown vs. what is being avoided.)

3. PORTFOLIO OPTIONS (unique to L0 — put in synthesis_check.portfolio_options field)
   Present three sequencing options for validation; do not ask which is best — ask which
   resonates and what the interviewee would add or change.
   Template: "Following discovery interviews, I'll present three portfolio options:
   Option A: Sequential — [first L1] established first, then [second L1].
             Lower risk, slower combined value, tests the model before scaling.
   Option B: Parallel — both capabilities transform simultaneously.
             Higher complexity, faster combined value, shared infrastructure leverage.
   Option C: Phased with gates — begin both, with defined decision gates at [milestones].
             Balanced risk; allows sequencing adjustment if capacity constraints emerge.
   We'll present a recommendation within [4–6 weeks]. Which framing resonates at this stage
   — or is there a fourth option you would add?"

4. SPONSORSHIP CHECK (unique to L0 — put in synthesis_check.sponsorship_check field)
   Template: "Can we count on your support to unblock barriers as they emerge — particularly
   [specific barrier named in the interview, e.g. funding approval, cross-functional alignment,
   partner readiness, board bandwidth]?"
   Listen for:
   - Direct commitment → strong sponsorship signal
   - "That is up to [someone else]" → reveals where real authority sits
   - "Within limits" → conditional — probe the limits explicitly
   - Deflection → sponsorship risk; flag in output summary

TONE NOTE: At L0, the synthesis is presented with confidence. You hold a cross-cutting view
across all levels that the executive does not. Present as a peer debrief: "Here is my read —
correct me where I am wrong." Do not present as a learner summarising notes.
"""

_L0_OUTPUT_TEMPLATE = """\
L0 INTERVIEW SUMMARY TEMPLATE — OUTPUT FORMAT
───────────────────────────────────────────────
Produce one portfolio-level summary per L0 interview.

## Portfolio Logic
- Strategic role:              [L1 capabilities as enablers / cost centres / differentiators]
- Priority ranking:            [L1a > L1b — rationale from the interviewee]
- Capital allocation philosophy: [ROI-driven / net-zero first / risk-weighted / unclear]
- Gating factor named:         [Capex / Capacity / Strategic clarity]
- Forced-choice answer:        [[L1 named], because [reason] — aligned with L1 leaders?]

## Competitive Context
- vs. industry peers:          [Ahead / On par / Behind — dimensions named]
- Biggest threat:              [Named threat + strategic implication]
- Upside if transformation succeeds: [Named advantage + £ estimate if given]
- Change-of-direction triggers: [Acceleration trigger / Delay trigger / Kill trigger]

## Capital Allocation & ROI
- Total investment:            [£X over Y years]
- Expected ROI:                [£Xm return; Yx multiple; Z-year payback]
- Risk-adjusted range:         [Best case / Likely / Worst case]
- Downside tolerance:          [At what ROI threshold do they pause or exit?]
- Value tracking mechanism:    [KPI framework / TBD / Ad-hoc]

## Execution Risk Assessment
| Risk                | Probability | Impact | Mitigation named?      |
|---------------------|-------------|--------|------------------------|
| Technical           | H/M/L       | H/M/L  | [Yes / Partial / None] |
| Organisational      | H/M/L       | H/M/L  | [Yes / Partial / None] |
| Financial           | H/M/L       | H/M/L  | [Yes / Partial / None] |
| Partnership         | H/M/L       | H/M/L  | [Yes / Partial / None] |
| Governance          | H/M/L       | H/M/L  | [Yes / Partial / None] |
- Key person dependency:       [Named individuals + succession risk]
- Parallel vs. sequential:     [Can execute simultaneously? Evidence for / against]

## Governance & Accountability
- ROI accountability:          [Named role / Shared / Unclear]
- Review cadence:              [Monthly / Quarterly / Annual / Ad-hoc]
- Metrics that matter:         [Top 3–5 metrics named by the interviewee]
- Kill criteria:               [What would trigger cancellation or major de-scope]

## Board Alignment
- #1 board message:            [What the interviewee wants the board to understand]
- Decision needed:             [Specific, actionable decision statement — or 'unclear']
- Board alignment level:       [Confident / Qualified / Uncertain — evidence]
- Board Q&A preparedness:      [Ready / Partially ready / Not prepared]

## Strategic Misalignments (Cross-Level)
- vs. L1 leaders:              [Where L0 framing differs from L1 interviewee answers]
- Across L0 interviewees:      [Where CEO / CFO / Chair answers diverge — and on what]
- Implications:                [What must be resolved before board presentation]

## Portfolio Option Resonance
- Option A (Sequential):       [Interviewee reaction]
- Option B (Parallel):         [Interviewee reaction]
- Option C (Phased / gated):   [Interviewee reaction]
- Preferred framing:           [Which resonated / what conditions named]

## Sponsorship Assessment
- Commitment level:            [Strong / Conditional / Weak — evidence from interview]
- Commitment scope:            [What they will unblock / what they will not]
- Escalation path:             [If barriers emerge, who has authority to resolve?]
"""


_CUSTOMER_PRINCIPLES = """\
CUSTOMER INTERVIEW PRINCIPLES — MAYA'S JUDGMENT HEURISTICS
────────────────────────────────────────────────────────────
These eight principles govern every customer interview design and execution.
Customer interviews are fundamentally different from L0–L3: the interviewee is
external, assesses service quality from their operational reality, and has no
obligation to be candid. Every technique serves the goal of honest, specific,
actionable insight.

1. OUTSIDE-IN LENS — FRAME EVERYTHING FROM THE CUSTOMER'S OPERATIONAL IMPACT
   Customer interviews reveal what VALUE customers PERCEIVE and NEED — not what
   the organisation thinks it provides. Every question must centre the customer's
   reality: "How does this impact YOUR team?" not "How are we performing?"
   ✗ "How do you rate our maintenance response times?"
   ✓ "When an asset fails unexpectedly, what's the impact on YOUR operations —
      on safety, on your ability to serve customers, on your team's morale?"

2. LISTEN MORE THAN TALK — SILENCE IS DATA
   Pause after every question. Hold silence for 3–5 seconds. Customers weigh
   whether to share the critical thing — silence precedes the most useful insight.
   Talking more than 20% of the interview is a technique failure.
   Never fill a pause with a restatement or an easier version of the question.

3. QUANTIFY FRICTION — NEVER ACCEPT VAGUE ANSWERS
   "Some frustration" is not a finding. Push for hours per week managing asset
   issues, frequency of unexpected failures, number of safety incidents, cost per
   occurrence, people considering leaving due to asset frustration.
   Unquantified pain = undefendable business case.
   ✗ "There's some frustration with maintenance scheduling"
   ✓ "We spend roughly 30% of operational time managing asset-related issues —
      that's 1.5 days per week per team lead that should be on core mission work"

4. NPS HONESTY — TEST SATISFACTION WITHOUT FISHING FOR POSITIVES
   Always ask the 1–10 satisfaction rating (Property and Fleet separately).
   Always probe what would drop them BELOW 5 — not just what would lift them.
   Below-5 risk factors are often more strategically important than aspirations.
   Do not lead with positives or frame questions to elicit favourable responses;
   false signals corrupt the change business case.

5. NEED BEHIND THE WANT — PROBE THE VALUE, NOT THE FEATURE
   Customers state feature requests ("I want a real-time dashboard"). These are
   solutions, not needs. Probe: "What would that enable for you?" "What decision
   would you make differently with that information?" Design the business case
   around needs: "eliminate 2 hours/day of asset-status chasing" not "dashboard."

6. CHANGE READINESS — ALWAYS ASSESS OPENNESS AND PREFERRED CHANNEL
   If customers would resist or ignore new capabilities, the ROI will not
   materialise. Always probe: "If we made major improvements, would that be
   welcome?" "What would concern you?" "Would you participate in a pilot?"
   "How do you prefer to be communicated with about changes?"
   Change-resistant customers are a constraint that must be named in the output.

7. CHAMPIONS AND DETRACTORS — IDENTIFY BOTH BEFORE CLOSING
   Champions (enthusiastic, willing to co-design) accelerate adoption. Detractors
   (frustrated but resigned, or hostile) must be managed. Assess every interviewee:
   Would they advocate for or resist transformation? The customer persona output
   must classify each interviewee on this dimension with evidence.

8. EXTERNAL CREDIBILITY — CAPTURE VIVID QUOTES FOR THE BUSINESS CASE
   Internal teams can be accused of bias. Customer testimony is much harder to
   dismiss. A customer who says "better asset management would save my team 15%
   of their time" is worth ten internal ROI calculations. Capture specific,
   vivid, attributed quotes (anonymise as needed) that can go directly into the
   board narrative and change business case.
"""

_CUSTOMER_FRAMING_TEMPLATE = """\
CUSTOMER INTERVIEW FRAMING — MANDATORY OPENING STRUCTURE
──────────────────────────────────────────────────────────
Customer interviews begin with a framing_block that positions the conversation as
a service improvement exercise — not a performance audit, complaint session, or
internal process review. The framing must make the interviewee feel heard and
respected before any probing begins.

POSITIONING (framing_block.positioning — 1–2 sentences)
   Template: "This is not a complaint session. We're genuinely trying to understand
   what would unlock value for your team — your honest, direct feedback helps us
   prioritise the right improvements rather than the wrong ones."
   Frame as: partnership-building, customer-centric, honest, safe.
   NEVER frame as: "We're reviewing our internal processes" or "We're doing a
   performance review of Asset Management." These frames make customers diplomatic
   rather than candid — they optimise for politeness, not truth.

CONTEXT SETTING (framing_block.context_setting — 5 bullets)
   Template bullets — customise with client's operational language and asset types:
   • "We want to understand what's working well today with [property/fleet] assets"
   • "Where asset management creates friction or disruption for your team"
   • "What would make your job easier or more effective on a day-to-day basis"
   • "What your biggest constraints in the field actually are"
   • "How better assets, planning, or data could help you and your team"

DUAL LENSES (framing_block.dual_lenses — customer variant)
   dual_lenses.efficiency (current friction lens):
   "First, I want to understand the friction — where assets slow you down, create
   unexpected problems, or force workarounds. I'll push for specifics: hours,
   frequency, cost, what it means for your team's ability to do their job."

   dual_lenses.effectiveness (aspiration lens):
   "Second, I want to understand what you'd want. If asset management were
   genuinely excellent — if property and fleet assets were best-in-class — what
   would that look like for your team? What would it enable that you can't do today?"
"""

_CUSTOMER_SECTION_GUIDE = """\
CUSTOMER INTERVIEW SECTION GUIDE — FIXED 8-SECTION STRUCTURE
──────────────────────────────────────────────────────────────
Customer interviews use a FIXED 8-section structure — all sections are always
included. Unlike L1 and L2, there is no section selection logic. The 50-minute
total allows genuine conversation. Skip questions the customer has already answered;
never rush through all questions if a section is yielding rich material.

DO NOT include maturity_rating blocks in any customer interview section.
Customers assess service quality from their operational perspective, not the
operational maturity of internal processes. Maturity ratings are L1/L2 instruments.

S1. Operational Context & Asset Dependence (~6 min)
   Core themes:
   - Walk-through: how do property and fleet assets enable their day-to-day work?
     Listen for: assets as enabler (unremarkable) vs. bottleneck (constantly managed).
   - Time burden: what % of time managing asset-related issues vs. core mission?
     5–10% = reliable background; 20–30% = significant friction; 40%+ = broken.
   - Failure impact: when assets fail or perform poorly, what's the impact on THEM?
     Probe four dimensions: operational (can't do job, must improvise); safety-critical
     (safety incidents or near-misses?); customer-facing (their customers affected?);
     personal (stress, overtime, frustration).
   - Priority comparison: property vs. fleet — which constrains them more, and why?
   - External benchmark: how does asset management here compare to other organisations
     they've worked with or know of? Reveals competitive positioning from customer view.

S2. Current Pain Points & Friction (~10 min)
   Core themes:
   - Biggest property frustration: listen for reliability (unexpected failures),
     predictability (no visibility into maintenance schedule), transparency (left in dark
     about issues), communication (find out after the fact), escalation (hard to reach
     someone), documentation (no history of what's been done).
   - Team impact: probe for workarounds (do they improvise?), time (hours/week),
     stress (source of anxiety?), effectiveness (fighting fires instead of core job?),
     morale (people considering leaving due to asset frustration?).
   - Fleet-specific frustrations: vehicle availability, uptime, maintenance timing,
     EV readiness, visibility into vehicle status or maintenance history.
   - Response to issues previously raised: "they listened and fixed it" → responsive;
     "they acknowledged it but nothing changed" → broken follow-through;
     "we didn't bother raising it" → broken feedback loop entirely.
   - Data/visibility potential: would transparency alone help, or is it a
     process or relationship problem? (Separates tool fix from relationship fix.)
   - Quantified cost of friction: hours/week, % of failures preventable, safety
     incidents, morale impact, people considering leaving.

S3. Unmet Needs & Aspirations (~8 min)
   Core themes:
   - Single highest-priority ask: "If you could ask for ONE thing better, what?"
     Listen for: visibility (real-time dashboard), predictability (maintenance schedule
     3 months ahead), responsiveness (2-hour SLA), proactivity (fix before failure),
     partnership (treat as partner not client), innovation (EV / net-zero transition).
   - Value behind the want: "What would that enable for your team?"
     Push for: productivity (hours saved), reliability (failures prevented), safety
     (incidents avoided), employee experience (stress reduced, morale improved),
     customer impact (their customers better served).
   - Aspirational best-in-class: unconstrained vision — "if assets were excellent,
     what would that look like?" Examples: never break unexpectedly; maintenance never
     disrupts operations; real-time visibility; proactive alerts; zero safety incidents;
     GS UK proactively helps us succeed.
   - Sustainability priority: how important is EV transition / net-zero?
     Critical (org has targets) / Important (customers expect it) / Nice-to-have /
     Not our concern. Many customers have their own climate commitments that create
     urgency independent of ours.
   - Trust signals: what would make them MORE confident in the partnership?
     Reveals accountability indicators, transparency preferences, partnership expectations.

S4. Satisfaction & Performance Perception (~6 min)
   Core themes:
   - Property satisfaction: 1–10. Then probe all three:
     "What would move you to 9–10?" "Why not [current score + 1]?"
     "What would move you BELOW 5?" (Below-5 risk factors are often more important
     than aspirations — they reveal fragility and switching triggers.)
   - Fleet satisfaction: 1–10. (Typically different from property — compare and probe why.)
   - Improvement trajectory confidence: "very / some / not really / negative / no idea."
     "I have no idea" is a visibility gap, not a neutral response — probe further.
   - Peer comparison: "What are you hearing from peers about our assets?"
     Listen for: happy/lucky; mixed; frustrated/compare poorly; complaining as liability.
   - NPS-like question: "If you had to recommend us to another organisation, what would
     you say?" Often more honest than the satisfaction question — reveals true sentiment.

S5. Data, Transparency & Partnership Quality (~7 min)
   Core themes:
   - Current visibility inventory: ask about each in turn:
     Asset condition (know how old/worn assets are?), maintenance schedules (know when
     work will happen?), work order status (can track what's being done?), performance
     metrics (see SLA compliance, downtime?), planned improvements (know what's coming?).
     For each dimension: accurate? timely? usable format?
   - Data wishlist: "What data would help you do your job better?"
     Examples: real-time asset status, predictive alerts (asset will fail in X weeks),
     maintenance history per asset, benchmarking vs. peers, planned-failure forecast.
   - ISS / DXI relationship quality: responsive, professional, listens to needs, proactive
     vs. reactive, would they recommend them? Where could they improve?
   - Partnership perception: "Do you feel treated as a partner or as a cost to manage?"
     Critical for change adoption — customers who feel managed, not partnered, resist
     transformation even when it would benefit them.
   - Dialogue gap: "If you could have a standing monthly call with leadership, what would
     you want to discuss?" Reveals unmet needs for direct engagement.

S6. Change & Transformation Readiness (~5 min)
   Core themes:
   - Welcome test: "If we made major improvements — better data, predictive maintenance,
     faster response — would that be welcome?" Test receptiveness before showing details.
   - Excitement vs. concern split: what would they be excited about vs. what would concern
     them? (Concerns: disruption, new tools, increased complexity, relationship changes.)
   - Disruption tolerance: if transformation meant temporary disruption, what's acceptable?
     Probe time window, what's too painful, what's manageable.
   - Communication preference: email, town halls, dedicated contact, dashboards?
     Ensures the adoption strategy uses the right channel for this customer segment.
   - Co-creation willingness: "Would you participate in a pilot or co-design?"
     Champions identify themselves here; detractors decline or hedge.

S7. Competitive & Market Context (~4 min)
   Core themes:
   - Strategic importance: how important is our asset management capability to their
     ability to compete or serve their own customers? Reveals dependency level —
     high dependency = high leverage AND high risk of reputational impact if things go wrong.
   - Alternatives awareness: are they aware of or considering alternatives?
     Handle delicately — this is a hidden retention-risk question.
   - Switching triggers: what would make them consider an alternative?
     (assets getting worse / cost increase / capability gap we can't fill / cost to self-manage)
   - Our competitive advantage: from their perspective, what's our biggest strength?
     External view of strengths — use directly in the change narrative and board presentation.

S8. Wrap-Up & Partnership (~4 min — this IS the synthesis_check)
   This section maps directly to the synthesis_check fields:
   - SUMMARISE → synthesis_prompt: restate their biggest friction, team impact, what
     would make the biggest difference, satisfaction rating and what would move it.
   - VALIDATE → response_probes: confirm the synthesis or surface what was missed.
   - NEXT STEPS → forward_roadmap: preview proposed transformation outcomes for customer
     validation (better visibility, predictive capabilities, closer partnership, EV support).
   - ONGOING → peer_referral: invite ongoing engagement and identify other contacts.
"""

_CUSTOMER_SYNTHESIS_TEMPLATE = """\
CUSTOMER INTERVIEW SYNTHESIS CHECK — SECTION 8 WRAP-UP
────────────────────────────────────────────────────────
The customer synthesis_check is relational, not analytical. Unlike L0/L1/L2 where
synthesis is about strategic/operational insight, customer synthesis is about being
heard and building confidence in partnership. The interviewee should leave feeling
respected and optimistic — even if they gave critical feedback.

SYNTHESIS PROMPT (synthesis_check.synthesis_prompt — interviewer speaks this)
   Template: "So if I understand correctly: your biggest friction with [property/fleet]
   assets is [X]; the impact on your team is [Y, quantified]; what would make the
   biggest difference is [Z]; and you're [A]/10 satisfied, and would move to [target]
   if [specific condition]. Does that capture it? What am I missing?"
   MUST be customised to what was actually said in this interview — no template
   placeholders. Speak with confidence, as a peer debrief: "Here is what I heard —
   correct me where I've got it wrong."

RESPONSE PROBES (synthesis_check.response_probes)
   - if_positive: "Good — what would you add or emphasise differently?"
   - if_defensive: "Where does my picture differ from what you'd say?
     Let's make sure I take back the right thing." (Customers are often diplomatic —
     probe gently for the honest view behind polite agreement.)
   - if_uncertain: "What would you want me to take back that I might have missed?
     Even something small might be important for how we prioritise."

PEER REFERRAL / ONGOING ENGAGEMENT (synthesis_check.peer_referral)
   Template: "Can we stay connected? We'd like your perspective as improvements are
   made — not just a one-time survey. And is there someone else on your team or in
   your network whose operational view I should also capture?"
   Dual purpose: identify additional customer contacts for interviews, and establish
   ongoing relationship for change adoption and co-design participation.

FORWARD ROADMAP / TRANSFORMATION PREVIEW (synthesis_check.forward_roadmap)
   Template: "As we look at improvements, we're exploring a few things and would
   value your reaction: better real-time visibility into asset status — would that
   change how your team plans? Predictive alerts before failures — would that let
   you take different action? Closer partnership with quarterly check-ins — would
   that be useful? And support for your EV transition — how can we help your team
   prepare for that?"
   Listen for: enthusiasm (champion signal), indifference (priority mismatch),
   concern (adoption risk), or a redirect to a completely different priority
   (reveals what we missed earlier in the interview).
"""

_CUSTOMER_OUTPUT_TEMPLATE = """\
CUSTOMER INTERVIEW SUMMARY TEMPLATE — OUTPUT FORMAT
─────────────────────────────────────────────────────
Produce one customer persona summary per customer interview.

## Customer Profile
- Role / title:               [Role, operational scope, and organisation context]
- Asset dependency level:     [High / Medium / Low — evidence from interview]
- Time burden on asset issues: [% of time; hours/week equivalent]
- Primary asset concern:      [Property / Fleet / Both equally — and why]
- External benchmark:         [How they compare GS UK to other organisations they know]

## Top 3 Friction Points (specific and quantified)
1. [Pain point — named, with frequency, impact, and any £ or time estimate given]
2. [Pain point — named, with frequency, impact, and any £ or time estimate given]
3. [Pain point — named, with frequency, impact, and any £ or time estimate given]

## Satisfaction Assessment
- Property satisfaction:      [X/10 — what would move them to 9–10]
- Fleet satisfaction:         [X/10 — what would move them to 9–10]
- Below-5 risk factors:       [What would drop their satisfaction sharply — switching triggers]
- Improvement confidence:     [Very / Some / Not really / Negative / No idea — evidence]
- NPS sentiment:              [Promoter / Passive / Detractor — evidence from NPS-like question]
- Peer comparison view:       [What they hear from peers about our performance]

## Unmet Needs & Aspirations
- Single highest-priority ask: [Verbatim or close paraphrase]
- Value behind the ask:        [What it would enable: productivity / safety / morale / customers]
- Aspirational best-in-class:  [Their unconstrained vision of excellent asset management]
- Sustainability priority:     [Critical / Important / Nice-to-have / Not our concern]
- Trust signals:               [What would increase their confidence in the partnership]

## Data & Partnership Quality
- Visibility — asset condition:      [Adequate / Partial / None — evidence]
- Visibility — maintenance schedule: [Adequate / Partial / None — evidence]
- Visibility — work order status:    [Adequate / Partial / None — evidence]
- Visibility — performance metrics:  [Adequate / Partial / None — evidence]
- Data wishlist top item:            [Most wanted data capability, in their words]
- Partnership perception:            [Partner / Cost to manage — specific evidence]
- ISS / DXI relationship quality:    [Responsive / Reactive / Absent — evidence]
- Dialogue gap:                      [What they would raise on a standing monthly call]

## Change Readiness
- Welcome to change:          [Enthusiastic / Willing / Cautious / Resistant — evidence]
- Excited about:              [Specific improvements they mentioned positively]
- Concerns about:             [Specific risks or disruptions they named]
- Disruption tolerance:       [What's acceptable; what would be too painful]
- Co-creation willingness:    [Yes / Conditional / No — evidence]
- Communication preference:   [Channel: email / town halls / dedicated contact / dashboards]

## Competitive & Market Context
- Asset management importance: [Strategic / Operational / Background — to their mission]
- Alternative awareness:       [None aware / Aware but not considering / Considering]
- Switching triggers:          [Specific conditions named that would push them to alternatives]
- Our competitive advantage:   [Their view of our biggest strength — use in change narrative]

## Champion / Detractor Classification
- Classification:              [Champion / Passive / Detractor]
- Evidence:                    [Specific signals: enthusiasm level, co-design willingness,
                               NPS sentiment, language used about the relationship]
- Engagement potential:        [Pilot participant / Ongoing feedback panel / Co-design partner /
                               None — basis for engagement strategy]

## Key Quotes for Business Case
- [Quote 1 — vivid, specific, quantified; relevant to transformation ROI narrative]
- [Quote 2 — vivid, specific; relevant to change readiness or partnership quality]
- [Quote 3 — vivid, specific; relevant to the board-level change business case]
(Anonymise role if required but preserve specificity and vividness of the language.)
"""


_AUDIT_PRINCIPLES = """\
AUDIT / ASSURANCE / REGULATOR INTERVIEW PRINCIPLES — MAYA'S JUDGMENT HEURISTICS
──────────────────────────────────────────────────────────────────────────────────
These eight principles govern every audit and regulator interview design and execution.
Audit interviews are fundamentally different from all other levels: the interviewee has
independent authority to find fault, and the organisation has no right to push back on
their assessment during the interview. Never seek validation — seek truth.

1. INDEPENDENT PERSPECTIVE — LISTEN WITHOUT DEFENDING
   The auditor/regulator has no stake in the outcome. Their observations may be
   uncomfortable. Never use the interview to explain, justify, or contextualise
   findings. The moment Maya defends, the auditor stops being candid.
   ✗ "We understand that, but we have a plan to fix it"
   ✓ "That's helpful — can you tell me more about where you see that gap?"

2. CONTROLS BEFORE STRATEGY — DON'T OVERSELL TRANSFORMATION
   Auditors don't assess whether strategy is smart. They assess whether controls
   are working, whether promises are being kept, and whether risks are managed.
   Ask "are controls working?" before asking "what do you think of the strategy?"
   A brilliant strategy with broken controls is a governance failure.

3. DATA INTEGRITY IS THE FOUNDATION
   All governance, KPI reporting, compliance evidence, and financial controls rest
   on trustworthy data. If data cannot be trusted, no finding can be trusted.
   Always probe: "How confident are you in the data behind that?" "Has data ever
   been restated?" "Is there independent verification?" Low data integrity is a
   material finding regardless of what the numbers say.

4. PROBE HISTORY — PAST ISSUES PREDICT FUTURE RISK
   Repeat findings, recurring control gaps, and unresolved audit observations are
   the single strongest predictor of future governance failure. Always ask: "Has GS UK
   addressed prior audit findings?" "Do you see recurring issues?" Patterns matter
   more than any single incident.

5. THIRD-PARTY RISK — VENDOR PERFORMANCE IS GOVERNANCE PERFORMANCE
   ISS (Property) and DXI (Fleet) performance directly impacts GS UK's governance
   health. If ISS/DXI SLA compliance is unmonitored, GS UK's compliance is unknowable.
   If audit does not independently test vendor performance, vendor reporting cannot
   be trusted. Ask whether there is independent vendor audit — "we rely on their
   reporting" is not a control.

6. TRANSFORMATION AMPLIFIES RISK — CONTROLS BREAK DURING CHANGE
   Major transformation programmes are when control failures are most likely. Budget
   overruns, compliance slippage, accountability diffusion, and data integrity failures
   all cluster around major change. Always ask: "How will controls be maintained during
   transformation?" "Who is accountable if controls weaken?" "What triggers escalation?"

7. BOARD NEEDS TRUTH — THE AUDITOR'S ROLE IS INDEPENDENT REPORTING
   Auditors report to the board and audit committee, not to management. Their
   observations belong in the boardroom, not filtered through management narrative.
   Always probe board oversight: "Does the board see enough detail on material risks?"
   "Are material findings reported without dilution?"

8. THREE-TIER FINDING FRAMEWORK — MATERIAL / SIGNIFICANT / ADVISORY
   Not all gaps are equal. Probe for materiality explicitly: "Is this a material
   finding that affects the integrity of governance, or is it advisory?"
   Material findings require board-level remediation. Significant findings require
   management action plan. Advisory findings are improvement opportunities.
   Conflating these obscures where urgent action is needed.
"""

_AUDIT_FRAMING_TEMPLATE = """\
AUDIT INTERVIEW FRAMING — MANDATORY OPENING STRUCTURE
───────────────────────────────────────────────────────
Audit interviews begin with a framing_block that positions the conversation as a
governance assessment exercise — not a process improvement exercise or a performance
review. The auditor/regulator must feel that their independent observations are being
genuinely sought, not screened or filtered through management's lens.

POSITIONING (framing_block.positioning — 1–2 sentences)
   Template: "We are not looking to defend our current position. We want your honest,
   independent assessment of governance, controls, and compliance — so we can address
   gaps with the right priority. This informs our transformation strategy directly."
   Frame as: independent, non-defensive, seeking truth over validation.
   NEVER frame as: "Here's what we're planning — does that address your concerns?"
   or "We believe our governance is strong — does that match your view?" These frames
   invite diplomatic agreement rather than independent assessment.

CONTEXT SETTING (framing_block.context_setting — 5 bullets)
   Template bullets — customise with client's specific regulatory and audit context:
   • "We want to know: are we doing what we say we'll do — governance, compliance, controls?"
   • "Are controls adequate for the risks we're taking with [property/fleet capex]?"
   • "What are your observations about accountability and decision-making quality?"
   • "Where are the material gaps or risks we may not be seeing clearly ourselves?"
   • "What areas concern you most about our asset management programme?"

DUAL LENSES (framing_block.dual_lenses — audit variant)
   dual_lenses.efficiency (controls lens):
   "First, I want to understand whether controls are working as intended — governance,
   compliance, financial discipline, data integrity, vendor management. Are the
   mechanisms we have in place actually catching failures before they cascade?"

   dual_lenses.effectiveness (gap lens):
   "Second, where the material gaps are — the things that, if they remain unaddressed,
   represent genuine risk to the organisation, to delivered outcomes, or to its
   obligations to regulators and stakeholders."
"""

_AUDIT_SECTION_GUIDE = """\
AUDIT INTERVIEW SECTION GUIDE — FIXED 9-SECTION STRUCTURE
───────────────────────────────────────────────────────────
Audit interviews use a FIXED 10-section structure — all sections are always included.
Unlike L1 and L2, there is no section selection logic. The 68-minute total allows
thorough governance coverage. Follow the auditor's thread — if a section yields
material findings, let it run over and compress advisory sections.

DO NOT include maturity_rating blocks in any audit interview section.
Auditors give qualitative maturity assessments (Ad-hoc / Repeatable / Managed / etc.)
conversationally within sections — these are captured as narrative, not structured
0–4 per-section ratings. The overall governance maturity rating goes in the synthesis.

S1. Governance & Accountability Framework (~8 min)
   Core themes:
   - Decision authority: Is it documented? Who decides what? Are authorities clear
     and enforced, or informal and assumed?
   - Accountability clarity: Who is accountable for what outcomes? Is accountability
     single-threaded (named owner) or diffused (committee)?
   - Escalation paths: How do material issues surface to board level? Is the
     mechanism defined, tested, and used — or theoretical?
   - Board oversight adequacy: Does the board see enough detail on material risks?
     Do they understand the risks they're approving?
   - Conflicts of interest: procurement separation of duties, vendor management
     independence, incentive alignment checks.
   - Historical responsiveness: has GS UK addressed prior audit findings, or do
     recurring issues indicate a pattern of non-remediation?
   - Ultimate accountability test: "If a major capex overrun or safety incident
     occurred, would it be caught? Who is accountable?" (Tests control effectiveness.)

S2. Contract & Compliance Management (~8 min)
   Core themes:
   - Material obligations: SLAs, KPIs, performance standards, capex responsibilities,
     change control process, performance incentives, exit clauses with ISS (Property)
     and DXI (Fleet).
   - Compliance status: are obligations being met? Listen for: fully compliant
     (ask for evidence) / mostly (which exceptions? how managed?) / not consistently
     (recurring breaches: red flag) / uncertain or not tracked (bigger red flag).
   - Regulatory obligations scope: Health & Safety (RIDDOR), Environmental (asbestos,
     waste, emissions), Energy efficiency (MEES for property, DVSA for fleet),
     Financial (capex reporting, depreciation), Accessibility, Net-zero / carbon
     (increasingly material).
   - Regulatory compliance status: any violations, fines, or enforcement actions?
     Is there a compliance calendar with monitored deadlines?
   - Systematic vs. ad-hoc compliance: "We're compliant but don't have a systematic
     process" is a control gap, not a clean bill of health.

S3. Financial Controls & Capex Discipline (~8 min)
   Core themes:
   - Budget control dimensions: annual forecast vs. actuals variance; approval
     process at each spend level (enforced vs. nominal); monthly tracking against
     approved budget; change control for overruns; complete audit trail to decisions;
     benefits tracked against spend.
   - Variance assessment: tight (within 5%) / reasonable (10–15%) / loose (20%+) /
     poor (surprised by overruns).
   - Contingency transparency: Are risk reserves explicit and disclosed, or hidden
     in optimistic best-case budgets?
   - Major overrun history: "Has there been a material capex overrun in the last
     3–5 years? How was it managed? What did you learn?" Reveals organisational
     maturity — whether it learns from failures.
   - Accounting integrity: depreciation/amortisation treatment for major assets,
     especially property revaluations.
   - Separation of duties: who can approve spend? Who can modify the approval
     framework? Are those functions independent?
   - Financial data confidence: 1–10 confidence in integrity of financial data for
     property and fleet. Press for what drives any confidence below 8.

S4. Performance Tracking & KPI Integrity (~8 min)
   Core themes:
   - KPI coverage: should include availability/uptime, cost (capex + opex per
     asset), quality/defects, safety incidents, compliance, customer satisfaction,
     sustainability/carbon.
   - Tracking discipline: monthly dashboards trended and reported to board vs.
     partial/manual/ad-hoc vs. targets set but actuals not tracked.
   - Data integrity concerns: multiple systems requiring manual reconciliation;
     frequently changing definitions; data errors found in prior audits; KPI owners
     with incentive to inflate; no independent verification.
   - Independent verification: annual audit of key KPIs vs. internal review only
     vs. management-certified with no external check.
   - Restatement history: have KPIs ever been restated due to data errors?
     Transparent correction = mature governance; denial = risk signal.
   - Incentive alignment: KPIs tied to management compensation? If yes, verify
     the metrics are robust — compensation linkage creates measurement gaming risk.
   - Trend reliability: "If I looked at the last 12 months of KPI reports, what
     would I find?" Are trends real or artefacts of measurement changes?

S5. Risk Identification & Mitigation (~8 min)
   Core themes:
   - Material risk scope: operational (asset failure, downtime, safety); financial
     (capex overrun, benefit shortfall, vendor cost escalation); regulatory
     (non-compliance, violations, environmental liability); strategic (market
     disruption, technology obsolescence, talent loss); organisational (key person
     dependency, change capacity); partnership (ISS/DXI underperformance, vendor
     failure); reputational (public safety incident, environmental issue).
   - Risk register: maintained quarterly and reported to Audit Committee vs.
     partially documented vs. managed ad-hoc vs. no systematic process.
   - Mitigation strategy types: preventive controls (design out), detective controls
     (catch early), corrective controls (fix fast), insurance (transfer), acceptance
     (knowingly taking).
   - Mitigation effectiveness: monitored with evidence vs. assumed without testing
     vs. past instances of mitigation failure.
   - Emerging risks: EV transition complexity and technology readiness; talent
     shortage in skilled trades; regulatory tightening (environmental, safety);
     supply chain disruption; cybersecurity for connected assets and operational data.
   - Control gap evidence: near-miss incidents or past control failures that revealed
     gaps — and whether the organisation learned from them.
   - Overall risk rating: 1–10 auditor assessment of property/fleet risk profile.
     Press for what would change the rating in either direction.

S6. Data & Information Quality (~7 min)
   Core themes:
   - Asset data quality dimensions: completeness (% of assets in system, historical
     data present?); accuracy (conflicts between systems, age of records?);
     consistency (definitions aligned across property and fleet?); timeliness
     (real-time feeds or batch-updated?); security (access controlled?);
     auditability (can you trace data lineage to the source decision?).
   - Data governance controls: formal data governance office with policies and
     standards vs. partial/ad-hoc controls vs. no formal governance at all.
   - Data quality issues found in prior audits: significant cross-system
     inconsistencies; incomplete or inaccurate asset register; data integrity not
     verified before use in decisions; historical data lost or unreliable.
   - Data ownership: is there a named data owner accountable for quality and
     completeness? "Everyone owns it" = no one owns it.
   - Systems integration: how integrated is asset data across platforms (Tririga,
     SAP, Primavera, BI tools)? Fully automated feeds vs. manual reconciliation
     vs. siloed systems with significant manual effort.
   - Strategic decision trust: "Would you trust this data for a £100M capex
     allocation decision?" If not — what specifically prevents that trust?

S7. Third-Party Management — ISS & DXI (~8 min)
   Core themes:
   - SLA and KPI monitoring rigor: is compliance data generated independently (GS UK
     systems) or self-reported by ISS/DXI? Are there penalties for SLA breach and
     are they enforced?
   - Performance reporting independence: "We rely on their reporting" is not a control.
     Is there any independent verification of ISS/DXI performance claims?
   - Conflict of interest checks: same person negotiating contract and managing
     performance (conflict); procurement with adequate separation of duties (good);
     ISS/DXI incentives to inflate scope or costs (monitor).
   - Audit frequency: quarterly compliance audits + annual detailed audit vs.
     annual audit + ad-hoc vs. relying solely on vendor reporting.
   - Compliance/performance gap findings: have prior audits found gaps with ISS or
     DXI? Were they remediated? Do they recur?
   - Transformation capability: confidence in ISS/DXI ability to support major
     transformation (EV transition, digital capability) — high/medium/low/uncertain.
   - Vendor lock-in risk: if GS UK needed to exit ISS or DXI contracts, what is
     the risk? What alternative sourcing options exist?

S8. Transformation & Change Governance (~6 min)
   Core themes:
   - Organisational readiness signals: change history (successful past
     transformations?); programme governance (formal PMO?); executive sponsorship
     (named owner with authority?); capacity (bandwidth to execute alongside BAU?);
     culture (openness to failure as learning, not blame?).
   - Transformation risk concerns: over-ambition (scope/timeline mismatch);
     resource constraints; historical overrun patterns; benefit realisation
     measurement gaps; change capacity (org already stressed); accountability
     diffusion (who is really accountable?).
   - Governance structure for the programme: steering committee mandate, board
     oversight triggers, programme controls. Red flags: "not yet defined" /
     "committee-based with diffused accountability" / "PMO will handle it" with no
     named executive sponsor.
   - Control continuity during change: parallel controls (maintain old while building
     new); enhanced monitoring during transition; internal audit embedded in programme.
     Red flag: "we haven't thought about that."
   - High-risk escalation triggers: what would cause the auditor to flag the
     transformation programme as requiring enhanced oversight or board intervention?

S9. Comparative & Peer Assessment (~5 min)
   Core themes:
   - Governance benchmarking vs. peers (other UK utilities, rail, similar
     organisations): ahead / in line / behind / not benchmarked.
   - Best-practice opportunities: specific practices from other organisations that
     should be adopted.
   - Regulatory trend horizon: carbon reporting / net-zero accountability;
     cybersecurity for connected assets; stricter environmental compliance;
     workforce skills and apprenticeship requirements; financial reporting changes.
   - Overall capability confidence vs. peers: 1–10 comparative assessment.
     Press for what evidence supports the rating.

S10. Wrap-Up & Critical Observations (~5 min — this IS the synthesis_check)
   This section maps directly to the synthesis_check fields:
   - SUMMARISE → synthesis_prompt: multi-dimensional summary covering governance
     maturity, material control gaps, compliance status, data integrity, vendor
     management quality, transformation readiness, overall risk rating, and top
     priorities for remediation.
   - VALIDATE → response_probes: "Do these observations align with your team's
     assessment? What am I missing or mischaracterising?"
   - FUTURE ENGAGEMENT → peer_referral: ongoing involvement during transformation
     ("I'd recommend periodic check-ins to ensure controls are maintained").
   - NEXT STEPS → forward_roadmap: key findings for board/management/regulatory
     body, recommendations, follow-up actions, timeline for re-assessment.
"""

_AUDIT_SYNTHESIS_TEMPLATE = """\
AUDIT INTERVIEW SYNTHESIS CHECK — SECTION 10 WRAP-UP
─────────────────────────────────────────────────────
Audit synthesis is multi-dimensional and evidence-anchored. Unlike the relational
synthesis in customer interviews, audit synthesis is an independent assessment
summary — findings, ratings, gaps, and recommendations. Present with confidence;
the auditor should recognise their own observations in the synthesis.

SYNTHESIS PROMPT (synthesis_check.synthesis_prompt — interviewer speaks this)
   Template: "Based on our discussion, here is my summary of your assessment:
   Governance maturity: [Ad-hoc / Repeatable / Managed — evidence];
   material control gaps: [1–3 named gaps];
   compliance status: [on track / at risk / issues found];
   data integrity: [high confidence / adequate / concerns — what drives this];
   vendor management: [strong / adequate / gaps with ISS/DXI];
   transformation readiness: [ready / adequate / concerns — named risks];
   overall risk rating: [X/10 — your assessment];
   and the top priorities you would recommend addressing: [1–3].
   Do those observations align with your assessment? What am I missing or
   mischaracterising?"
   MUST be customised to what was actually said. Material findings stated directly.
   Do not soften or qualify the auditor's observations in the synthesis — state
   them as they gave them. This is the auditor's independent view, not management's.

RESPONSE PROBES (synthesis_check.response_probes)
   - if_positive: "Good — what would you emphasise differently, or what's the
     single most urgent thing we should act on first?"
   - if_defensive: "Where does my characterisation differ from yours? I want to
     make sure I take back an accurate picture." (Auditors may have been diplomatic
     mid-interview — the synthesis is often where the real view surfaces.)
   - if_uncertain: "What would you want verified independently before you'd be
     confident in that assessment? What data would change your view?"

FUTURE ENGAGEMENT (synthesis_check.peer_referral)
   Template: "I'd recommend periodic check-ins during the transformation programme
   to ensure controls are maintained and risks are proactively managed. Would you
   or your team be available for that? And is there a colleague — perhaps in a
   different assurance function or a regulatory contact — whose independent view
   I should also capture?"
   Purpose: establish ongoing audit engagement as a programme governance mechanism,
   not just a point-in-time assessment. Also surface additional assurance contacts.

NEXT STEPS (synthesis_check.forward_roadmap)
   Template: "I'll compile your observations into the governance assessment.
   Key outputs will include: the material findings for board and audit committee;
   specific control improvement recommendations with priority and timeline; suggested
   follow-up actions for the transformation programme governance; and a proposed
   schedule for re-assessment at key programme milestones. Do the areas I've mentioned
   cover what's most important from your perspective?"
   Listen for: gaps in coverage (areas the auditor expected to be assessed but
   weren't), urgency signals (something that needs to go to board immediately),
   or scope expansion (areas outside the original brief that should be included).
"""

_AUDIT_OUTPUT_TEMPLATE = """\
AUDIT INTERVIEW SUMMARY TEMPLATE — OUTPUT FORMAT
──────────────────────────────────────────────────
Produce one audit summary per interviewee / assurance function.

## Auditor / Regulator Profile
- Name / organisation:         [Name, audit function, and mandate]
- Audit scope:                 [What they cover: enterprise risk / external / regulatory]
- Prior engagement with GS UK: [Audit history; prior findings and remediation status]

## Governance Assessment
- Decision authority clarity:  [Clear / Adequate / Gaps / Unclear — evidence]
- Accountability framework:    [Documented / Partially / Ad-hoc — evidence]
- Escalation process:          [Defined / Informal / Missing — tested or theoretical?]
- Board oversight adequacy:    [Adequate / Needs strengthening — evidence]
- Conflicts of interest managed: [Yes / Partially / Gap found — evidence]
- Governance maturity rating:  [Ad-hoc / Repeatable / Managed / Optimised — justification]
- Prior audit findings addressed: [Yes / Partially / Recurring issues — detail]

## Compliance & Regulatory Status
- ISS / DXI obligations:       [Compliant / Minor breaches / Recurrent / Untracked]
- Regulatory obligations:      [Compliant / At risk / Violations found — by category]
- Documentation & audit trail: [Strong / Adequate / Gaps]
- Compliance calendar:         [Systematic / Ad-hoc / None]
- Material compliance risks:   [List named gaps with severity — Material / Significant / Advisory]

## Financial Controls Assessment
- Capex discipline:            [Tight (±5%) / Reasonable (±15%) / Loose (±20%+)]
- Budget variance pattern:     [Evidence from last 3–5 years]
- Change control:              [Enforced / Partially / Weak]
- Contingency / risk reserves: [Explicit & disclosed / Hidden / Absent]
- Separation of duties:        [Adequate / Partial / Gap found]
- Financial data confidence:   [X/10 — what drives any score below 8]
- Major overrun history:       [Incidents named; how managed; what was learnt]

## KPI & Performance Tracking
- KPI coverage:                [Comprehensive / Adequate / Material gaps — what's missing]
- Tracking discipline:         [Monthly trended to board / Partial / Ad-hoc / Missing]
- Data integrity concerns:     [None / Minor / Material — specifics]
- Independent verification:    [Annual external / Internal review / None]
- Restatement history:         [Clean / One-off corrected / Pattern]
- Incentive alignment risk:    [KPIs tied to comp — robust metrics / gaming risk]
- Trend reliability:           [Trust trends / Question assumptions — reason]

## Risk Management
- Risk register status:        [Maintained quarterly / Partial / None]
- Material risks identified:   [Comprehensive / Adequate / Material omissions — what's missing]
- Mitigation effectiveness:    [Monitored with evidence / Assumed / Past failures found]
- Emerging risks flagged:      [EV / Talent / Regulatory / Cyber / Supply chain — detail]
- Near-miss / gap revelations: [Any incidents that exposed control gaps]
- Overall risk rating:         [X/10 — what would move it in either direction]

## Data & Information Quality
- Asset data completeness:     [% assets in system; historical data present]
- Accuracy & consistency:      [Cross-system conflicts; definition alignment]
- Timeliness:                  [Real-time / Batch / Unreliable]
- Data governance controls:    [Formal governance / Partial / None]
- Data issues in prior audits: [Named issues; remediated / open]
- Data ownership:              [Named owner / Shared / None]
- Systems integration:         [Automated feeds / Manual reconciliation / Siloed]
- Strategic decision trust:    [Would trust for £100M decision? Evidence]

## Third-Party Management (ISS / DXI)
- SLA monitoring rigor:        [Independent / Self-reported / Not monitored]
- Independent vendor audit:    [Quarterly / Annual / Ad-hoc / None]
- Prior compliance gaps:       [Found and remediated / Found and open / None found]
- Conflict of interest:        [Well managed / Partial / Gap found]
- Transformation capability:   [Confident / Medium / Low / Unassessed]
- Vendor lock-in risk:         [Low / Medium / High — exit options available?]

## Transformation Readiness
- Governance capability:       [Ready / Adequate / Concerns — evidence]
- Programme governance:        [PMO + sponsor / Partial / Not yet defined]
- Control continuity plan:     [Parallel controls planned / Ad-hoc / Not addressed]
- Execution risk level:        [Low / Moderate / High]
- Escalation triggers:         [What would prompt board-level intervention]

## Comparative & Peer Assessment
- Governance vs. peers:        [Ahead / In line / Behind / Not benchmarked]
- Best-practice opportunities: [Named practices from other organisations]
- Regulatory trend horizon:    [Named upcoming requirements that need preparation]
- Capability confidence vs. peers: [X/10 — evidence basis]

## Overall Audit Assessment
- Governance maturity:         [Ad-hoc / Repeatable / Managed / Optimised]
- Material control gaps:       [1–3 most urgent findings — material only]
- Compliance status:           [On track / At risk / Issues requiring board reporting]
- Data integrity:              [High / Medium / Concerns]
- Overall risk rating:         [X/10]

## Key Recommendations (Priority-ordered)
1. [Material finding — action required, owner, timeline]
2. [Significant finding — action plan, deadline]
3. [Advisory improvement opportunity]

## Follow-Up Actions
- [ ] Board / Audit Committee reporting for material findings
- [ ] Management response and remediation plan
- [ ] Transformation programme governance alignment
- [ ] Enhanced monitoring schedule during change
- [ ] Re-assessment date at programme milestones
"""


_L1_PRINCIPLES = """\
L1 INTERVIEW PRINCIPLES — MAYA'S JUDGMENT HEURISTICS
──────────────────────────────────────────────────────
Apply these throughout every L1 interview design and execution. They are not steps —
they are persistent lenses to hold across the entire conversation.

1. FRAME AS CAPABILITY ASSESSMENT, NOT PROCESS AUDIT
   L3 asks: "How do you execute this task?" L2 asks: "How do you make this decision?"
   L1 asks: "Does this capability deliver the value we need, and what would unlock more?"
   Reframe every question away from operational process toward strategic asset.
   ✗ "Walk me through how you manage property maintenance."
   ✓ "How does Property Management create strategic value — and where is it falling short
      of its potential?"

2. SURFACE STRATEGIC CLARITY BEFORE OPERATIONS
   Most L1 interviews drift to operational detail within 5 minutes. Hold the strategic frame.
   If the interviewee starts describing process, acknowledge and pivot: "That's useful context
   — let me stay at the strategic level. What is this capability FOR?"
   Test: can the interviewee state the strategic mandate in one sentence? If not, that is
   a finding in itself — misaligned leadership, not just an interview technique problem.

3. PROBE COMPETITIVE CONTEXT EXPLICITLY
   L1 leaders tend to think inward. Benchmarking questions surface assumptions they have
   never tested: "How do peers manage this?" "Where are you ahead? Behind?"
   "What would a best-in-class operator do differently?" Most will say "I don't know" —
   which is itself a finding: inward focus, no competitive intelligence practice.

4. MONETISE THE VALUE OPPORTUNITY (TOTAL ADDRESSABLE VALUE)
   Never accept "significant" or "substantial" as a value estimate. Use the TAV formula:
   "If you optimised this capability — better decisions, less rework, faster cycle times —
   what's the total annual value? Cost reduction? Revenue protection? Risk avoided?"
   Then: "What percentage of that are you realising today?" The gap IS the opportunity.
   Prepare 2–3 monetisation narratives before each interview.

5. ASSESS MATURITY HOLISTICALLY ACROSS FIVE DIMENSIONS
   L1 maturity is never uniform. A capability can have mature processes but ad-hoc data.
   Assess all five: Data, Decision Architecture, Process, Technology, Organisation.
   Ask the interviewee to self-rate each (0–4), then form your own assessment from the
   evidence. Discrepancies reveal either genuine blind spots or unexamined assumptions.
   The binding constraint — the dimension holding back all others — drives sequencing.

6. MAP TRANSFORMATION READINESS, NOT JUST ASPIRATION
   "What would you like AI to do?" reveals aspiration. "What would it take?" reveals
   readiness. Probe both: technical readiness (data, systems), organisational readiness
   (change appetite, capacity, skills), and strategic readiness (mandate, sponsorship, budget).
   High aspiration with low readiness is a risk to name, not an opportunity to celebrate.

7. TEST LEADERSHIP ALIGNMENT DIRECTLY
   Misalignment at L1 kills transformation. Ask: "How aligned is your leadership team
   on the strategy for this capability?" Then test it: "If I asked your CFO / CTO /
   Operations VP the same question, would they give the same answer?"
   Leaders who are genuinely aligned welcome the test. Those who qualify ("mostly aligned")
   or deflect ("hard to say") are flagging a change management risk that must be surfaced.

8. DISTINGUISH HORIZON 1 / 2 / 3 EXPLICITLY
   Most L1 leaders conflate quick wins with transformation. Distinguish clearly:
   H1 (0–12 months): Foundation — data governance, process clarity, decision architecture.
   H2 (12–24 months): Capability build — system integration, analytics, automation pilots.
   H3 (24+ months): Optimisation — AI-driven decisions, competitive advantage.
   Quick wins build momentum but do not move decision quality. Foundations unlock everything.
   Do not let the interviewee skip H1 in pursuit of H3 aspirations.

9. IDENTIFY THE BINDING CONSTRAINT AND ITS REMOVAL SEQUENCE
   Find the constraint across the five maturity dimensions: Data → Decision → Process →
   Technology → Organisation (typical sequence, but not always). Probe: "Which dimension,
   if improved, would unlock the most in the others?" This answer determines the improvement
   priority that downstream initiative design must respect.

10. TEST CSF CONFIDENCE AND RISK APPETITE BEFORE CLOSING
    Probe the five Critical Success Factors: executive sponsorship, data governance,
    organisational alignment, technology integration, benefit realisation.
    For each: "Green / Yellow / Red?" Then: "What's your mitigation for the Yellows and Reds?"
    Leaders who cannot answer the mitigation question have not stress-tested their plan.
    This is the most important closing test — do not skip it in the interest of time.
"""

_L1_FRAMING_TEMPLATE = """\
L1 FRAMING BLOCK — MANDATORY OPENING STRUCTURE
────────────────────────────────────────────────
Every L1 script must begin with a framing_block that orients the interviewee to the
capability assessment frame BEFORE any questions are asked. This is separate from the
welcome_message (personal and warm) and from Section 1 (which probes strategy).

The framing_block uses the same schema fields as L2 but carries L1-specific content.
Customise each part to the specific L1 capability area and client context:

POSITIONING (framing_block.positioning — 1–2 sentences)
   Template: "We're assessing [L1 capability area] as a strategic asset for [organisation].
   We want to understand: how you currently create value from this capability, what
   strategic constraints you face, where digital and AI could unlock competitive advantage,
   and how to prioritise transformation for maximum ROI."

   The framing must signal IMMEDIATELY that this is a capability strategy conversation,
   not an operational process review.
   ✗ "We're mapping the Property Management value chain to understand your processes."
   ✓ "We're assessing Property Management as a strategic asset — how it creates value
      today, where it faces constraints, and what transformation could unlock."

CONTEXT SETTING (framing_block.context_setting — 4–5 bullets)
   The capability health check agenda. These bullets tell the interviewee exactly what
   the conversation will cover, and prime them to think at the right level.
   Template bullets (customise language to the client and capability):
   • "Strategic clarity: are we aligned on what this capability is for — and what
      'excellent' would look like in your specific context?"
   • "Competitive position: how does this capability compare to industry peers, and
      where are the gaps that matter most?"
   • "Maturity trajectory: where is this capability today, where should it be in 3 years,
      and what is blocking the journey?"
   • "Digital readiness: what data, decisions, or workflows would most benefit from
      AI or automation — and what foundation is needed first?"
   • "Transformation roadmap: how do we sequence improvement for maximum ROI, and
      what are the critical success factors?"

DUAL LENSES (framing_block.dual_lenses — L1 variant)
   For L1, the "efficiency" field carries the CAPABILITY HEALTH lens and the
   "effectiveness" field carries the TRANSFORMATION POTENTIAL lens. The field names
   are schema artefacts — the spoken content is what matters.

   dual_lenses.efficiency (capability health):
   "First, I want to understand how this capability creates value today — where
   investment is working, where constraints limit returns, and what the true cost
   of the current maturity ceiling is."

   dual_lenses.effectiveness (transformation potential):
   "Second, I want to understand what is possible — where digital and AI could
   unlock the next level of capability, how to sequence that journey, and what
   ROI is realistic."

   These two lenses prevent the conversation from drifting into pure problem-listing
   (no vision) or pure aspiration (no grounding in reality).

TONE NOTE: The framing_block is spoken by the interviewer, not read from a screen.
Write it in natural spoken English — shorter sentences, no jargon, no bullet structure.
The context_setting bullets become a spoken list: "Five things I want to explore with you..."
"""

_L1_SECTION_LIBRARY = """\
L1 SECTION LIBRARY — SELECT 4–5 SECTIONS FOR EACH NODE
────────────────────────────────────────────────────────
The following 8 thematic sections form a reference library. Maya selects the most
relevant sections for each L1 node based on its strategic context and available
interview time. Sections S1, S2, and S3 are mandatory for every L1 interview.

Target durations: Standard L1 (45–55 min); Deep-dive L1 (60–75 min for senior
stakeholders or transformationally critical capabilities).

MANDATORY ─────────────────────────────────────────────────────────────────────────

S1. Strategic Intent & Competitive Position (~12 min)
   Core themes:
   - Strategic mandate: What is the #1 strategic objective for this capability?
     Explicit vs. implicit; conflicting objectives across leaders; parent company framing.
   - KPIs and measurement: How is performance measured? What is board-reported?
     Are incentives tied to these metrics? Are there conflicting KPIs?
   - Winning definition: What would "winning" look like in 2026? 2030?
     Quantified / vague / aspirational but uncertain / missing entirely.
   - Strategic constraints: Capex limit, carbon target, resource shortage, technology
     immaturity, organisational readiness. Which one, if removed, has the biggest impact?
   - Competitive benchmarking: How does this capability compare to peers?
     Where ahead? Behind? What is the "moat"? What threatens position or could disrupt?
   - Leadership alignment: How aligned is the leadership team? Where is the biggest
     disagreement? How are disagreements resolved? Metacognitive test: "Would your
     CFO / CTO give me the same answer?"
   Maturity anchor: Strategic Clarity & Alignment
   Maturity narrative signals:
     0: "No clear strategic mandate; each leader has their own agenda."
     1: "Strategy exists on paper but is not driving decisions or investment."
     2: "Clear mandate; most leaders aligned; some KPI misalignment persists."
     3: "Fully aligned; KPIs linked to mandate; board-level visibility; reviewed quarterly."
     4: "Real-time alignment; mandate adapts to market signals; competitive intelligence embedded."

S2. Value Creation & Business Model (~10 min)
   Core themes:
   - Value streams: How does this capability create value — cost avoidance, revenue
     protection, strategic enablement, risk reduction, capital efficiency? Quantify each.
   - TAV (Total Addressable Value): If fully optimised, what is the annual value potential?
     What % is being realised today? The gap is the transformation opportunity.
   - Value tracking: Is value realisation tracked? Are there KPIs? Is realised vs.
     forecast formally monitored? If not — why not?
   - Strategic initiatives: What initiatives are funded? ROI for each? Sequencing logic?
     Biggest barrier to accelerating?
   - Capability investment: People, tools, process, organisational design, external
     partners. Biggest capability gap? Cost of inaction if the gap is not closed?
   Maturity anchor: Value Architecture & ROI Clarity
   Maturity narrative signals:
     0: "We cannot quantify the value this function creates — it just keeps the lights on."
     1: "Some value tracked — mostly cost. Revenue protection and risk reduction unmeasured."
     2: "Multiple value streams identified and roughly quantified. No formal realisation tracking."
     3: "Value tracked quarterly; gap vs. potential monitored; investment linked to ROI forecast."
     4: "Real-time value dashboard; TAV vs. realised reported to board; investment rebalanced dynamically."

S3. Current State Capability Maturity (~12 min)
   Core themes:
   - Five-dimension self-assessment — probe all five; capture interviewee ratings per dimension:
     • DATA: completeness, quality, integration, governance, trust. Self-rate 0–4.
     • DECISION ARCHITECTURE: clarity, rigor, traceability, adaptation. Self-rate 0–4.
     • PROCESS: standardisation, discipline, control, continuous improvement. Self-rate 0–4.
     • TECHNOLOGY: system integration, automation %, analytics capability, real-time lag. 0–4.
     • ORGANISATION: alignment, capability, culture, incentive design. Self-rate 0–4.
   - Narrative diagnostic (never use maturity jargon; use these questions):
     "How much of your decision-making is reactive vs. proactive?"
     "How well integrated is your data across systems?"
     "How data-driven are your decisions — gut feel, data-informed, or AI-optimised?"
     "How fast do you learn from outcomes — annual reviews, or real-time?"
     "What % of your team's effort goes to heroics vs. systematic execution?"
   - Binding constraint: "Of these five dimensions, which is holding back capability growth?"
     Probe the root cause. Identify the constraint removal sequence.
   - Maturity gap: Current composite → target composite → prerequisites to unlock next level.
   Overall maturity anchor: Composite across all five dimensions (single 0–4 rating)
   Maturity narrative signals:
     0: "Ad-hoc across all — reactive, siloed data, gut-feel decisions, heroic daily effort."
     1: "Basic discipline emerging; some processes documented; data captured but not integrated."
     2: "Managed in most dimensions; data integrated in main systems; decisions informed not optimised."
     3: "All five performing well; real-time visibility; systematic learning; competitive benchmark met."
     4: "AI-optimised; real-time adaptive planning; significant competitive advantage established."

RECOMMENDED — INCLUDE 2–3 BASED ON NODE CONTEXT ──────────────────────────────────

S4. Digital & AI Transformation Readiness (~10 min)
   Core themes:
   - Track record: What digital/technology initiatives ran in the last 3–5 years?
     Outcome per initiative — successful / partial / failed. Lessons learned.
     "How will this transformation be different?" (Reveals whether they have reflected on past.)
   - Change appetite: How does the organisation feel about AI, automation, data-driven
     decisions? Specific concerns: job displacement, trust in AI recommendations, control,
     change capacity, execution risk. Each concern signals a specific change management need.
   - Aspiration (magic wand): If no constraints, what would this capability look like in 5 years?
     Value that unlocks? Gap between vision and today? Cost of NOT pursuing the vision?
   - Absorption capacity: Dedicated transformation team / absorbed into BAU / external support?
   - Prioritisation stance: "Would you prioritise automation (faster execution) or decision
     optimisation (better decisions)?" Reveals the dominant constraint in their mental model.
   Maturity anchor: Digital Maturity & Transformation Readiness
   Maturity narrative signals:
     0: "We have failed digital initiatives; low confidence in technology change delivery."
     1: "Some tools deployed; appetite varies; no clear digital strategy or investment thesis."
     2: "Clear digital strategy; some analytics in use; cautiously positive appetite."
     3: "Track record of successful digital change; AI actively explored; dedicated capacity."
     4: "Digital-first mindset; AI embedded in key decisions; clear investment thesis and roadmap."

S5. Strategic Roadmap & Transformation Priorities (~10 min)
   Core themes:
   - Three-horizon sequencing:
     H1 Foundation (0–12m): data governance, process clarity, quick wins, decision architecture.
     H2 Capability Build (12–24m): system integration, analytics, automation pilots, change mgmt.
     H3 Optimisation (24–36m+): AI-driven decisions, competitive advantage, autonomous execution.
     "Where should we focus first?" If they skip H1: "What does H1 look like for you?"
   - Initiative sequencing: Which initiatives are critical path? What runs in parallel?
     What blocks progress if delayed? Have dependencies been mapped?
   - Investment profile: Total budget; H1/H2/H3 distribution; ROI forecast; stress-tested
     scenarios (50% timeline overrun, slower adoption, budget cuts mid-programme).
     Tolerance for variance?
   - Critical Success Factors: 3–5 non-negotiables. Confidence level each (Green/Yellow/Red)?
     Mitigation for each Red/Yellow?
   - Risks: Technical, organisational, execution, strategic, financial. Probability,
     monetised impact, mitigation plan for each.
   Maturity anchor: Planning & Sequencing Maturity
   Maturity narrative signals:
     0: "No roadmap; initiatives run opportunistically; no sequencing logic."
     1: "Annual planning cycle; some initiatives; no formal horizon framework."
     2: "Multi-year roadmap exists; dependencies partially mapped; CSFs identified but not RAG-rated."
     3: "Full H1/H2/H3 roadmap; critical path validated; CSFs and mitigations defined; board-approved."
     4: "Adaptive roadmap; reprioritised mid-cycle on evidence; continuous investment rebalancing."

S6. Organisational Capability & Change Readiness (~8 min)
   Core themes:
   - Change readiness self-assessment: 1–10 rating; history with large transformations;
     % excited vs. resistant; what scares people most; what would move resistant to supportive?
   - Skills & talent: New skills needed? Sources — hire / train / partner? Retention risk?
     Retention strategy for key people during the transformation programme?
   - Governance & sponsorship: Who is the executive sponsor? Board commitment confirmed?
     What would cause this to be deprioritised? How is it protected from competing priorities?
   - Incentive alignment: Do KPIs align with the transformation strategy? Conflicting incentives
     between functions (Finance: cost; Operations: quality; IT: control)?
   Maturity anchor: Organisational Readiness & Change Capability
   Maturity narrative signals:
     0: "No change management history; significant resistance; no executive sponsorship."
     1: "Some change experience; sponsor identified; majority neutral to sceptical."
     2: "Positive track record; clear sponsor; majority supportive; pockets of resistance remain."
     3: "Strong change management function; systematic engagement; aligned incentives; board oversight."
     4: "Change-as-usual culture; distributed ownership; rapid adoption; self-reinforcing learning."

OPTIONAL — INCLUDE FOR SENIOR STAKEHOLDERS OR HIGH-PRIORITY NODES ──────────────────

S7. Value Realisation & Success Metrics (~8 min)
   Core themes:
   - Value category mix: cost reduction, revenue protection, risk reduction, strategic
     enablement, organisational capability. Which categories matter most? Rough % split?
   - KPI design: For each value stream — KPI name, baseline, target, measurement frequency,
     data source, owner, monetisation formula. Cap at 5–10 KPIs.
   - Accountability: Who is accountable for value realisation? What happens if value lags?
     Are quarterly reviews built in? Is causality formally isolated or estimated?
   - Quick wins: 5–10 wins in H1, aggregate target £3–5M. Visible, credible, meaningful,
     low-risk. How will they be communicated? What could block them?
   Maturity anchor: Value Realisation & Accountability
   Maturity narrative signals:
     0: "No formal value tracking; success is 'it feels better'."
     1: "Some KPIs exist; no formal realisation tracking; Finance not engaged."
     2: "KPIs defined; quarterly tracking; Finance-owned; causality not formally isolated."
     3: "Full realisation framework; accountability assigned; monthly review; scenario-modelled."
     4: "Real-time value dashboard; dynamic reforecast; causal attribution modelled; board-reported."

S8. Peer Contextualisation & Portfolio Fit (~6 min)
   Core themes:
   - Cross-capability comparison: How does this L1 compare to other L1 capabilities in
     digital maturity? Which needs transformation more urgently? Can lessons transfer?
   - Industry positioning: Ahead / on par / behind peers? Competitive moat? Vulnerability
     to disruption (technology, business model, talent, regulatory, economic pressure)?
   - Portfolio interdependencies: What else is happening across the organisation (capex
     cycles, restructures, other digital programmes)? Shared platforms / learning possible?
     Could this transformation block or enable other strategic initiatives?
   - Corporate strategy alignment: How does this connect to corporate-level programmes
     (net-zero, digital, M&A, regulatory)? Missing alignment = siloed solutions.
   Maturity anchor: Strategic Integration & Portfolio Coherence
   Maturity narrative signals:
     0: "This capability is managed in isolation; no visibility of peers or industry."
     1: "Some awareness of peer capabilities; ad-hoc sharing; no systematic benchmarking."
     2: "Periodic benchmarking; some cross-capability learning; limited portfolio coordination."
     3: "Systematic benchmarking; cross-capability learning loops; portfolio roadmap coordinated."
     4: "Continuous competitive intelligence; portfolio optimisation; integrated transformation governance."

NOTE: S8 involves questions the interviewee may not be positioned to answer if they govern
only one L1 capability. Calibrate depth to their cross-portfolio visibility.

SECTION SELECTION RULES
   Standard L1 (45–55 min): S1 + S2 + S3 + select 1–2 from {S4, S5, S6} + closing
   Deep-dive L1 (60–75 min): S1 + S2 + S3 + S4 + select 2–3 from {S5, S6, S7, S8} + closing
   Priority signals for selection:
   - Digital transformation is the primary agenda → include S4
   - Roadmap or sequencing clarity needed → include S5
   - Change readiness or sponsorship risk identified → include S6
   - Value case rigour needed for board approval → include S7
   - Interviewee has cross-L1 or cross-organisation visibility → add S8
"""

_L1_SYNTHESIS_TEMPLATE = """\
L1 SYNTHESIS CHECK — MANDATORY CLOSING ELEMENT
────────────────────────────────────────────────
Before closing_message, every L1 script must include a synthesis_check that validates
the interviewer's strategic picture with the interviewee. This is a collegial debrief
— the interviewer offers their emerging synthesis for correction and endorsement.

The synthesis_check has four elements:

1. SYNTHESIS PROMPT (interviewer speaks this)
   Template: "Based on what you've told me, here's how I see the strategic picture for
   [L1 capability area]: the mandate is [strategic objective]; current maturity sits at
   [overall level] — constrained mainly by [binding dimension]; the value opportunity
   is in the range of [£estimate]; the critical path runs [H1 priority → H2 goal]; and
   the biggest transformation risk is [key CSF Red/Yellow]. Does that match your assessment?"

   This MUST be customised to the specific L1 node. Draft it using evidence gathered in
   the interview. Do not leave placeholders — write a plausible synthesis the interviewee
   will confirm or correct.

2. RESPONSE PROBES (use one based on the interviewee's reply)
   - If validation: "Good — what would you emphasise differently, or what did I miss?"
     (Even positive responses often surface useful nuance or priority corrections.)
   - If qualified or defensive: "Where does my picture differ from yours — and why?"
     (The most valuable response: reveals blind spots or undisclosed constraints.)
   - If uncertain or deflecting: "What would you want me to verify with other stakeholders
     before I rely on this summary?"
     (Signals where this view may be incomplete or politically sensitive.)

3. PEER REFERRAL (executive stakeholder mapping)
   "To validate this strategic picture, I need to speak with a few more people. I'm thinking
   [CFO or Finance VP] for ROI and investment rigour, [CTO or IT lead] for digital architecture
   readiness, [HR or OD lead] for change readiness and talent, and [COO or Operations VP] for
   execution capacity and risk. Who would you add? And is there anyone whose perspective I
   should be especially careful to get?"
   Customise the role list to the organisation's structure. Add partner or supplier stakeholders
   where the L1 involves significant external dependency.

4. FORWARD ROADMAP & COMMITMENT CHECK
   "If you were shaping the first 90 days of this transformation — what would you start with?
   And are you personally committed to making this happen?"
   Listen for:
   - H1 thinking (data, governance, quick wins) → sequencing maturity
   - Direct personal commitment → sponsorship confidence
   - Conditional commitment ("if the business case stacks up") → conditional support only
   - Weak commitment ("I support it in principle") → change management risk

TONE NOTE: Offer the synthesis with curiosity, not authority.
"Here's how I see it — tell me where I'm wrong" is more productive than "here's the summary."
An interviewee correcting you is a better outcome than nodding agreement.
"""

_L1_OUTPUT_TEMPLATE = """\
L1 INTERVIEW SUMMARY TEMPLATE — OUTPUT FORMAT PER NODE
────────────────────────────────────────────────────────
Produce one summary per L1 node in this structure.

## Strategic Mandate
- Primary objective:        [What is this capability FOR — one sentence]
- Parent company framing:   [Strategic enabler / Operational necessity / Cost centre]
- KPIs and board reporting: [What gets measured and reported at board level]
- "Winning" definition:     [2026 and 2030 targets — quantified, vague, or missing]
- Strategic constraints:    [Binding constraint and "most impactful to relax" answer]
- Leadership alignment:     [Fully / Mostly / Partially / Not aligned — evidence]

## Competitive Position
- vs. peers:                [Ahead / On par / Behind — evidence and key dimensions]
- Competitive moat:         [What would be hard to replicate]
- Threats:                  [Technology / Regulatory / Competitive / Talent / Inertia]
- Missing capability:       [What they would acquire from a best-in-class peer]

## Current Maturity (0–4)
- Data:                     [0–4 + one-sentence rationale from interview evidence]
- Decision architecture:    [0–4 + one-sentence rationale]
- Process:                  [0–4 + one-sentence rationale]
- Technology:               [0–4 + one-sentence rationale]
- Organisation:             [0–4 + one-sentence rationale]
- Composite:                [0–4 + binding constraint dimension]
- Binding constraint:       [Which dimension holds back the others, and why]

## Value Architecture
- Value streams (quantified):
  | Stream               | Current £ value | TAV potential | Realisation % |
  |----------------------|-----------------|---------------|---------------|
  | Cost avoidance       | [£]             | [£]           | [%]           |
  | Revenue protection   | [£]             | [£]           | [%]           |
  | Risk reduction       | [£]             | [£]           | [%]           |
  | Strategic enablement | [qualitative]   | [qualitative] | n/a           |
- Total TAV:              [£Xm–£Ym annual estimate]
- Realised today:         [% of TAV]
- Value gap (opportunity): [£ estimate driving transformation urgency]

## Digital Transformation Readiness
- Digital track record:    [Successful / Mixed / Poor — key examples and lessons]
- Change appetite:         [High / Medium / Low — tone and specific concerns named]
- Aspiration (magic wand): [5-year capability description + value unlocked]
- Absorption capacity:     [Dedicated team / BAU / External support required]
- Prioritisation stance:   [Automation / Decision optimisation / Both]

## Three-Horizon Roadmap
- H1 (0–12m):   [Priority initiatives + expected value + key risk]
- H2 (12–24m):  [Priority initiatives + expected value + key risk]
- H3 (24–36m+): [Optimisation goal + competitive advantage description]
- Critical path: [Sequence logic — what must happen first, what can parallel]
- Budget:        [Total + H1/H2/H3 distribution if stated]
- ROI estimate:  [Payback period / benefit multiple / risk-adjusted range]

## Critical Success Factors
| CSF                         | Status        | Mitigation                       | Owner   |
|-----------------------------|---------------|----------------------------------|---------|
| Executive sponsorship       | Green/Amber/Red | [Action]                        | [Role]  |
| Data governance foundation  | Green/Amber/Red | [Action]                        | [Role]  |
| Organisational alignment    | Green/Amber/Red | [Action]                        | [Role]  |
| Technology integration      | Green/Amber/Red | [Action]                        | [Role]  |
| Benefit realisation         | Green/Amber/Red | [Action]                        | [Role]  |

## Commitment Assessment
- Personal commitment level: [Strong / Conditional / Weak — evidence from interview]
- Deprioritisation triggers: [Events that would cause this to be cut or paused]
- Board-level protection:    [Yes / No / Unknown]

## Peer Interview Priorities
Executive stakeholders:
- [ ] [CFO / Finance VP — ROI and investment rigour]
- [ ] [CTO / IT lead — digital architecture readiness]
- [ ] [HR / OD lead — change readiness and talent gaps]
- [ ] [COO / Operations VP — execution capacity and risk]
Functional L2 leaders:
- [ ] [Key L2 node leads sitting under this L1 — by node label]
Partner stakeholders:
- [ ] [Major external partners or suppliers where applicable]
"""


def create_interaction_designer(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Interaction Designer",
        goal=(
            "Design a coherent set of interview scripts for every active L0, L1, L2, and L3 "
            "value chain node, ensuring instruments at each level probe the right type of insight "
            "so findings can be triangulated across levels. L0 instruments capture portfolio logic "
            "and capital allocation decisions; L1 captures strategic capability and transformation "
            "maturity; L2 captures decision architecture and orchestration quality; L3 captures "
            "execution fidelity and operational bottlenecks."
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
            + _AUDIT_PRINCIPLES + "\n"
            + _CUSTOMER_PRINCIPLES + "\n"
            + _L0_PRINCIPLES + "\n"
            + _L1_PRINCIPLES + "\n"
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
            "Design integrated interview scripts for every active L0, L1, L2, and L3 value chain "
            "node, PLUS one customer interview script per identified customer segment (level='C'), "
            "PLUS one audit/assurance interview script per identified auditor or regulator contact "
            "(level='A'). "
            "All instruments use a single script artefact per node/segment. Maturity ratings "
            "(maturity_rating blocks) appear in L1 and L2 sections only — captured after narrative "
            "discussion. L0, L3, and C (customer) nodes have no maturity_rating blocks. "
            "There is no separate questionnaire artefact.\n\n"
            + _CONCEPTUAL_SHIFT + "\n"
            + _L2_L3_FRAMEWORK + "\n"
            + _AUDIT_FRAMING_TEMPLATE + "\n"
            + _AUDIT_SECTION_GUIDE + "\n"
            + _AUDIT_SYNTHESIS_TEMPLATE + "\n"
            + _CUSTOMER_FRAMING_TEMPLATE + "\n"
            + _CUSTOMER_SECTION_GUIDE + "\n"
            + _CUSTOMER_SYNTHESIS_TEMPLATE + "\n"
            + _L0_FRAMING_TEMPLATE + "\n"
            + _L0_SECTION_GUIDE + "\n"
            + _L0_SYNTHESIS_TEMPLATE + "\n"
            + _L1_FRAMING_TEMPLATE + "\n"
            + _L1_SECTION_LIBRARY + "\n"
            + _L1_SYNTHESIS_TEMPLATE + "\n"
            + _L2_FRAMING_TEMPLATE + "\n"
            + _L2_SECTION_LIBRARY + "\n"
            + _L2_SYNTHESIS_TEMPLATE + "\n"
            + standards_block +
            "Steps:\n"
            "1. Use SQLiteStateTool with operation='read', key='value_chain_registry', "
            "agent_name='interaction_designer' to load the activity registry. "
            "Collect every entry where active=true and level is 'L0', 'L1', 'L2', or 'L3'.\n"
            "2. Use SQLiteStateTool with operation='read', key='value_chain_summary', "
            "agent_name='interaction_designer' to understand the client's operations.\n"
            "3. Use ChromaQueryTool with collection='project' to gather corporate context "
            "(governance posture, known capability gaps, adopted standards, language used).\n\n"

            "── L0 NODES (portfolio / board level — C-suite and board members) ─────────────\n"
            "4. For each L0 node, apply all 6 L0 Interview Principles from your backstory. "
            "Core question: 'Where should capital go, in what sequence, and how do we ensure "
            "value realisation at portfolio level?' Time horizon: 3–5 year strategic cycle. "
            "AI opportunity: portfolio optimisation, capital efficiency, governance assurance. "
            "Success metric: ROI realised, strategic mandate delivered, board confidence.\n\n"
            "   PREPARATION (before designing any section):\n"
            "   - Identify which L1 capabilities sit beneath this L0 (from value_chain_registry)\n"
            "   - Draft a portfolio investment narrative: total £X across L1 capabilities, ROI range,\n"
            "     payback timeline, biggest execution risk\n"
            "   - Identify which L0 interviewees will be interviewed (CEO, CFO, Chair, COO, etc.)\n"
            "     so cross-executive misalignments can be tracked\n\n"
            "   a) FRAMING BLOCK — mandatory, written before sections.\n"
            "   Using the L0 Framing Block guide from your task context, write a framing_block\n"
            "   object customised to this portfolio context:\n"
            "   - positioning: 1–2 sentences stating this is a portfolio-level assessment naming\n"
            "     the L1 capabilities, and the four things being assessed (fit to corporate strategy,\n"
            "     capital concentration, constraints, governance for value realisation)\n"
            "   - context_setting: 4–5 bullets covering strategic coherence, capital efficiency,\n"
            "     risk & trade-offs, governance, and competitive positioning — customised with the\n"
            "     client's language and their specific L1 capability names\n"
            "   - dual_lenses.efficiency (portfolio investment health): current investment logic,\n"
            "     where capital is going, expected return, and constraints\n"
            "   - dual_lenses.effectiveness (portfolio transformation potential): where investment\n"
            "     should concentrate, sequencing strategy, board confidence building\n\n"
            "   b) FIXED SECTION STRUCTURE — L0 uses all 6 sections from the L0 Section Guide.\n"
            "   There is NO section selection at L0 — all 6 sections are always included.\n"
            "   Design specific questions for each section from the themes defined in the L0 Section Guide.\n"
            f"   Use {preferred_questions} narrative questions per section, plus follow_up_branches (2 per\n"
            "   question) and evasion_signals (phrases signalling drift from portfolio framing).\n"
            "   NO maturity_rating blocks in any L0 section.\n\n"
            "   c) SYNTHESIS CHECK — mandatory closing element with FOUR components.\n"
            "   Using the L0 Synthesis Check guide from your task context, write a synthesis_check\n"
            "   object with all four components:\n"
            "   - synthesis_prompt: customised portfolio synthesis covering strategic role, total\n"
            "     investment (£), ROI expectations, key constraint, biggest execution risk, and\n"
            "     the board decision needed. End with 'Does that capture it correctly?'\n"
            "     MUST be customised — no generic placeholders.\n"
            "   - response_probes: three probe phrases for positive / qualified / uncertain replies\n"
            "   - peer_referral: stakeholder mapping question naming who else to interview\n"
            "   - forward_roadmap: 90-day question ('What would you do first?')\n"
            "   - portfolio_options: present Options A (Sequential), B (Parallel), C (Phased/gated)\n"
            "     using the L1 capability names. End: 'Which framing resonates at this stage?'\n"
            "   - sponsorship_check: commitment question naming a specific barrier from the interview\n\n"
            "   d) Complete script fields:\n"
            "      - research_brief and study_objectives framed at portfolio / capital allocation level\n"
            "      - welcome_message: brief, professional, board-appropriate tone. State the purpose\n"
            "        (portfolio assessment across [L1 capabilities]), the structure (6 sections,\n"
            "        ~30 min), and that findings will inform a board recommendation.\n"
            "      - closing_message: concise thanks, confirm next steps (portfolio options paper\n"
            "        within [4–6 weeks]), confirm when findings will be shared\n\n"
            "   e) After drafting, produce one L0 Interview Summary using this template:\n"
            + _L0_OUTPUT_TEMPLATE + "\n"

            "── L1 NODES (strategic / portfolio level — GMs and value-stream owners) ────────\n"
            "5. For each L1 node, apply all 10 L1 Interview Principles from your backstory. "
            "Core question: 'Does this capability deliver the value we need?' "
            "Time horizon: 3–5 years. "
            "AI opportunity: decision optimisation, competitive advantage, strategic enablement. "
            "Success metric: TAV realised, maturity trajectory, transformation ROI.\n\n"
            "   PREPARATION (before designing any section):\n"
            "   - Review which L2 nodes and activities sit beneath this L1 (from value_chain_registry)\n"
            "   - Draft a TAV narrative: cost avoidance + revenue protection + risk reduction + strategic value\n"
            "   - Assess node strategic priority: standard (45–55 min) or senior deep-dive (60–75 min)\n"
            "   - Identify triangulation stakeholders: which executive peers should be interviewed after\n\n"
            "   a) FRAMING BLOCK — mandatory, written before sections.\n"
            "   Using the L1 Framing Block guide from your task context, write a framing_block\n"
            "   object customised to this specific L1 capability area:\n"
            "   - positioning: 1–2 sentences framing the capability as a strategic asset,\n"
            "     naming the four things the assessment will explore (value creation, strategic\n"
            "     constraints, digital opportunity, ROI). Do NOT say 'we're mapping the value chain'.\n"
            "   - context_setting: 4–5 bullets naming the capability health check dimensions —\n"
            "     strategic clarity, competitive position, maturity trajectory, digital readiness,\n"
            "     transformation roadmap — customised with the client's language and context\n"
            "   - dual_lenses.efficiency: capability health lens — 'First, I want to understand\n"
            "     how this capability creates value today — constraints, ROI, and the cost of\n"
            "     the current maturity ceiling'\n"
            "   - dual_lenses.effectiveness: transformation lens — 'Second, what's possible —\n"
            "     where digital and AI could unlock the next level, and how to sequence for ROI'\n"
            "   The framing_block is spoken before Section 1. It ensures the interviewee thinks\n"
            "   strategically, not operationally, from the first question.\n\n"
            "   b) SECTION SELECTION — select 4–5 sections from the L1 Section Library.\n"
            "   Sections S1, S2, and S3 are mandatory for every L1 interview.\n"
            "   Select 1–2 additional sections based on:\n"
            "   - Digital transformation is the primary agenda → include S4\n"
            "   - Roadmap or sequencing clarity needed → include S5\n"
            "   - Change readiness or sponsorship risk identified → include S6\n"
            "   - Value case rigour needed for board approval → include S7\n"
            "   - Interviewee has cross-L1 or cross-organisation visibility → add S8\n"
            "   Standard L1 (45–55 min): S1 + S2 + S3 + select 1 from {S4, S5, S6} + closing\n"
            "   Deep-dive L1 (60–75 min): S1 + S2 + S3 + S4 + select 2 from {S5, S6, S7, S8} + closing\n\n"
            "   c) SECTION DESIGN — for each selected section, design specific questions from its\n"
            "   themes (defined in the L1 Section Library). For every section:\n"
            f"      - {preferred_questions} narrative questions per section, probing the section themes\n"
            "      - follow_up_branches: 2 probing follow-ups per question\n"
            "      - evasion_signals: phrases signalling the interview has drifted to the wrong level —\n"
            "        watch for operational drift ('it depends on the team', 'the process varies by site')\n"
            "        and strategic deflection ('we're well aligned', 'finance drives that')\n"
            "      - Listen patterns to embed as probing_instructions for critical L1 signals:\n"
            "        Strategic clarity: explicit / implicit / conflicting / missing mandate\n"
            "        Value framing: 'strategic enabler' / 'operational necessity' / 'cost centre'\n"
            "        Alignment test: 'would peers give the same answer?' — confident / qualified / deflecting\n"
            "        Maturity signals: reactive/proactive ratio, data integration, decision confidence,\n"
            "        feedback loop speed, heroics vs. routine effort ratio\n"
            "      - target_minutes per section aligned to the library guidance\n\n"
            "   d) MATURITY RATINGS — each section ends with a maturity_rating block.\n"
            "   Rating is ALWAYS captured after the narrative, never before.\n"
            "   Use the maturity narrative signals from the L1 Section Library for the selected section.\n"
            "   Labels must use 0–4 notation and echo the narrative language — not generic terms.\n"
            "   For S3 (Current State Capability Maturity): the maturity_rating captures the COMPOSITE\n"
            "   maturity across all five dimensions. Phrase the prompt so the interviewee gives an\n"
            "   overall 0–4 that reflects all dimensions together. The binding constraint dimension\n"
            "   is captured in the narrative questions, not the rating.\n\n"
            "   e) SYNTHESIS CHECK — mandatory closing element, written after sections.\n"
            "   Using the L1 Synthesis Check guide from your task context, write a synthesis_check\n"
            "   object with:\n"
            "   - synthesis_prompt: a draft synthesis of the L1's strategic mandate, composite\n"
            "     maturity, binding constraint, value opportunity (£ estimate), critical path,\n"
            "     and biggest transformation risk — written as the interviewer would speak it,\n"
            "     ending with 'Does that match your assessment?' Customise to the node.\n"
            "   - response_probes: three probe phrases covering positive / defensive / uncertain replies\n"
            "   - peer_referral: stakeholder mapping question naming CFO, CTO, HR/OD, COO, and any\n"
            "     major external partners relevant to this L1 node\n"
            "   - forward_roadmap: 90-day question ('What would you start with?') plus commitment\n"
            "     check ('Are you personally committed to making this happen?')\n\n"
            "   f) Complete script fields:\n"
            "      - research_brief and study_objectives framed at strategic / portfolio level\n"
            "      - welcome_message: warm, senior-appropriate, frames this as a strategic dialogue\n"
            "        about capability and transformation — not about operational processes\n"
            "      - closing_message: follows synthesis_check; thanks, confirms stakeholder\n"
            "        interviews to follow and when findings will be shared\n\n"
            "   g) After drafting, produce one L1 Interview Summary using this template:\n"
            + _L1_OUTPUT_TEMPLATE + "\n"

            "── L2 NODES (operational / process-stage level — process managers) ─────────────\n"
            "6. For each L2 node, apply all 10 L2 Interview Principles from your backstory. "
            "Core question: 'How do we orchestrate & decide better?' Time horizon: next quarter/year. "
            "AI opportunity: decision support. Success metric: decision quality / value realisation.\n\n"
            "   PREPARATION (before designing any section):\n"
            "   - Identify all L3 nodes that feed this L2 (from value_chain_registry)\n"
            "   - Identify the downstream consumers of this L2's decisions\n"
            "   - Draft a monetisation narrative: Frequency × Impact = Cost, or "
            "Decision quality × Volume = Value\n"
            "   - Assess node strategic priority: standard (25–30 min) or high-priority (45–60 min)\n"
            "   - Identify peer interviewees for triangulation: owner, consumer, governance, support\n\n"

            "   a) FRAMING BLOCK — mandatory, written before sections.\n"
            "   Using the L2 Framing Block guide from your task context, write a framing_block\n"
            "   object with three parts customised to this specific node:\n"
            "   - positioning: one sentence naming the cluster, its L3 inputs, and the decisions it feeds\n"
            "   - context_setting: 2–3 bullets placing the L2 between upstream governance and "
            "downstream L3 execution, naming both by label\n"
            "   - dual_lenses: efficiency frame ('coordination friction') and effectiveness frame "
            "('decision quality — what you make and what you can't yet make')\n"
            "   The framing_block is spoken before the first question. It sets the cognitive frame "
            "so the interviewee knows this is a decision architecture conversation, not an "
            "operational audit.\n\n"

            "   b) SECTION SELECTION — select 4–5 sections from the L2 Section Library.\n"
            "   Sections S1 and S2 are mandatory. Select 2–3 additional sections based on:\n"
            "   - Known data governance pain → include S3\n"
            "   - Decision cycle time > 4 weeks or cross-L2 misalignment → include S4\n"
            "   - High-value strategic node or aspiration quantification needed → include S5\n"
            "   - L3 execution fidelity is a concern → include S6\n"
            "   - Senior interviewee with cross-portfolio view → add S7\n"
            "   Standard L2 (25–30 min): S1 + S2 + 2 from {S3, S4, S5, S6} + closing\n"
            "   Deep-dive L2 (45–60 min): S1 + S2 + S3 + S4 + 1–2 from {S5, S6, S7} + closing\n\n"

            "   c) SECTION DESIGN — for each selected section, design specific questions from "
            "its themes (defined in the Section Library). For every section:\n"
            f"      - {preferred_questions} narrative questions per section, probing the section theme\n"
            "      - follow_up_branches: 2 probing follow-ups per question\n"
            "      - evasion_signals: phrases that indicate vagueness (e.g. 'it depends', "
            "'we do our best', 'the system handles it')\n"
            "      - root_constraint_probe in each section: one question that separates the "
            "stated problem from the underlying constraint "
            "('What's actually stopping a faster decision here?')\n"
            "      - target_minutes per section: keep each section to 6–10 minutes\n\n"

            "   d) MATURITY RATINGS — each section ends with a maturity_rating block.\n"
            "   The rating is ALWAYS captured after the narrative, never before.\n"
            "   Use the maturity narrative signals from the Section Library for the selected\n"
            "   section to anchor the scale labels. Labels must use 0–4 notation and must\n"
            "   echo the narrative language just used — not generic CMMI/COBIT terms.\n"
            "   The five levels:\n"
            "      0 — Ad-hoc: no structured approach; decisions are informal and undocumented\n"
            "      1 — Initial: some attempts at structure, but inconsistent and unverified\n"
            "      2 — Developing: documented process but not consistently applied or reviewed\n"
            "      3 — Managed: systematic approach with regular review and outcome tracking\n"
            "      4 — Predictive: real-time evidence, continuous learning, anticipates outcomes\n"
            "   Each scale label must be SPECIFIC to the dimension and client context.\n\n"

            "   e) SYNTHESIS CHECK — mandatory closing element, written after sections.\n"
            "   Using the L2 Synthesis Check guide from your task context, write a synthesis_check\n"
            "   object with:\n"
            "   - synthesis_prompt: a draft synthesis of the node's strategic intent, current\n"
            "     maturity, biggest constraint, key data gap, and value opportunity — written\n"
            "     as the interviewer would speak it, ending with 'Does that match your assessment?'\n"
            "     Customise this to the node; do not leave it as a template.\n"
            "   - response_probes: three probe phrases for positive / defensive / uncertain replies\n"
            "   - peer_referral: a referral question naming the four triangulation perspectives\n"
            "   - forward_roadmap: a roadmap question asking where to start and what risks concern them\n\n"

            "   f) Complete script fields:\n"
            "      - research_brief and study_objectives framed at decision orchestration level\n"
            "      - welcome_message: warm, professional, invites the interviewee to think in\n"
            "        quarters and portfolios — 'your perspective on how decisions are made here'\n"
            "      - closing_message: follows synthesis_check; brief thanks and next steps\n\n"

            "   g) After drafting, produce one L2 Interview Summary using this template:\n"
            + _L2_OUTPUT_TEMPLATE + "\n"

            "── L3 NODES (activity level — practitioners and operational staff) ──────────────\n"
            "7. For each L3 node — anchored to the L2 vs L3 framework: core question is "
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

            "── CUSTOMER INTERVIEWS (outside-in — customer segments) ────────────────────────\n"
            "8. Design customer interview scripts for each customer segment identified in the\n"
            "discovery context. Apply all 8 Customer Interview Principles from your backstory.\n"
            "Core question: 'What service quality do customers PERCEIVE and NEED?' "
            "Focus: reliability, responsiveness, transparency, partnership, and transformation "
            "readiness from the customer's operational lens — not internal process performance.\n\n"
            "   PREPARATION (before designing):\n"
            "   - Review the discovery_brief (step 2) and ChromaDB context (step 3) to identify\n"
            "     customer segments: who depends on the managed assets operationally?\n"
            "     Examples: Regional Operations Leaders, Field Teams, Network Planners, customer-facing\n"
            "     functions using the managed assets.\n"
            "   - Identify 1–3 distinct segments (different roles may have very different perspectives;\n"
            "     a field team and a network planner have different friction points)\n"
            "   - Note what's known about current pain points and satisfaction from discovery documents\n\n"
            "   a) FRAMING BLOCK — mandatory, written before sections.\n"
            "   Using the Customer Framing guide from your task context, write a framing_block\n"
            "   customised to this customer segment and asset context:\n"
            "   - positioning: 1–2 sentences: partnership not performance-review; safe to be candid\n"
            "   - context_setting: 5 bullets covering what's working, friction, what would help,\n"
            "     constraints, and how data/planning could help — using client's language\n"
            "   - dual_lenses.efficiency: friction lens (assets slowing them down, creating problems)\n"
            "   - dual_lenses.effectiveness: aspiration lens (what excellent would look like for them)\n\n"
            "   b) SECTION DESIGN — all 8 sections are mandatory. Design questions from the themes in\n"
            "   the Customer Section Guide. For every section:\n"
            f"      - {preferred_questions} narrative questions per section, probing the section themes\n"
            "      - follow_up_branches: 2 probing follow-ups per question\n"
            "      - evasion_signals: phrases signalling the customer is being diplomatic rather\n"
            "        than candid (e.g. 'it's generally fine', 'no real complaints', 'I couldn't say')\n"
            "      - probing_instructions: embed quantification reminders where appropriate\n"
            "        ('push for hours/week or frequency' / 'probe below 5 risk factors')\n"
            "      - NO maturity_rating block in any section\n\n"
            "   c) SYNTHESIS CHECK — maps to Section 8 (Wrap-Up). Using the Customer Synthesis guide:\n"
            "   - synthesis_prompt: customised summary of their biggest friction, team impact,\n"
            "     what would make the biggest difference, and their satisfaction rating. No placeholders.\n"
            "   - response_probes: three probes for positive / defensive (diplomatic) / uncertain\n"
            "   - peer_referral: ongoing engagement invitation plus additional customer contact question\n"
            "   - forward_roadmap: transformation preview to validate (visibility, predictive,\n"
            "     partnership, EV transition) — probe for enthusiasm, concern, or redirection\n\n"
            "   d) Complete script fields:\n"
            "      - node_label: '[Segment name] Customer Interview' (e.g. 'Field Team Customer Interview')\n"
            "      - level: 'C'\n"
            "      - research_brief and study_objectives framed at customer perception level:\n"
            "        'Understand service quality as experienced by [segment]'\n"
            "      - welcome_message: warm, peer-to-peer, grateful tone. Emphasise: no right/wrong\n"
            "        answers, honest feedback is most valuable, this shapes real decisions\n"
            "      - closing_message: thank the customer warmly, explain how feedback will be used,\n"
            "        confirm when they'll hear about outcomes\n\n"
            "   e) After drafting, produce one Customer Interview Summary using this template:\n"
            + _CUSTOMER_OUTPUT_TEMPLATE + "\n"

            "── AUDIT / ASSURANCE / REGULATOR INTERVIEWS (outside-in — governance) ──────────\n"
            "9. Design audit interview scripts for each auditor or regulator identified in the\n"
            "discovery context. Apply all 8 Audit Interview Principles from your backstory.\n"
            "Core question: 'Are controls working? Are promises being kept?' "
            "Focus: governance maturity, compliance status, financial discipline, KPI data "
            "integrity, risk management, third-party management, and transformation readiness — "
            "all assessed from an independent assurance perspective.\n\n"
            "   PREPARATION (before designing):\n"
            "   - Review the discovery_brief and ChromaDB context to identify audit/assurance\n"
            "     contacts: internal audit (enterprise risk, finance, compliance), external\n"
            "     auditors (EY, KPMG, etc.), and relevant regulatory bodies (Ofgem, ORR, etc.)\n"
            "   - Review any available prior audit findings or regulatory reports to understand\n"
            "     existing observations and remediation status\n"
            "   - Identify applicable regulations (Health & Safety, Environmental, Energy\n"
            "     efficiency, Financial, Net-zero) for the client's sector\n\n"
            "   a) FRAMING BLOCK — mandatory, written before sections.\n"
            "   Using the Audit Framing guide from your task context, write a framing_block:\n"
            "   - positioning: 1–2 sentences: non-defensive, seeking independent assessment;\n"
            "     'we want to address gaps, not defend our position'\n"
            "   - context_setting: 5 bullets: doing what we say, controls adequate, governance\n"
            "     observations, material gaps/risks, biggest concerns — customised to client\n"
            "   - dual_lenses.efficiency: controls lens — are mechanisms catching failures?\n"
            "   - dual_lenses.effectiveness: gap lens — what material risks remain unaddressed?\n\n"
            "   b) SECTION DESIGN — all 10 sections are mandatory. Design questions from the\n"
            "   themes in the Audit Section Guide. For every section:\n"
            f"      - {preferred_questions} narrative questions per section, probing the section themes\n"
            "      - follow_up_branches: 2 probing follow-ups per question\n"
            "      - evasion_signals: phrases signalling the auditor is being diplomatic rather\n"
            "        than direct (e.g. 'generally adequate', 'no major concerns', 'we monitor it')\n"
            "      - probing_instructions: embed evidence-seeking reminders ('ask for evidence,\n"
            "        not assertion' / 'probe whether control has been tested, not just designed')\n"
            "      - NO maturity_rating block in any section (auditors give narrative assessments\n"
            "        and 1–10 confidence ratings, not structured 0–4 per-section ratings)\n\n"
            "   c) SYNTHESIS CHECK — maps to Section 10 (Wrap-Up). Using the Audit Synthesis guide:\n"
            "   - synthesis_prompt: multi-dimensional summary covering governance maturity, material\n"
            "     control gaps, compliance status, data integrity, vendor management, transformation\n"
            "     readiness, overall risk rating, and top priorities. MUST be customised — no\n"
            "     placeholders. State findings directly as the auditor gave them.\n"
            "   - response_probes: three probes for aligned / diplomatic (hedged) / uncertain\n"
            "   - peer_referral: ongoing engagement invitation during transformation + additional\n"
            "     assurance contacts (other audit functions or regulatory bodies)\n"
            "   - forward_roadmap: next steps — key findings for board/audit committee,\n"
            "     recommendations, remediation plan, re-assessment schedule\n\n"
            "   d) Complete script fields:\n"
            "      - node_label: '[Auditor/Regulator name] Audit Interview' or '[Function] Assessment'\n"
            "      - level: 'A'\n"
            "      - research_brief and study_objectives framed at governance/assurance level:\n"
            "        'Assess governance maturity, control effectiveness, and transformation readiness\n"
            "        from the perspective of [auditor/regulatory function]'\n"
            "      - welcome_message: professional, grateful, non-defensive. Acknowledge their\n"
            "        independent mandate. State the purpose: 'We want your honest, unfiltered\n"
            "        assessment to inform our transformation priorities.'\n"
            "      - closing_message: thank them for their independent perspective, confirm\n"
            "        how findings will feed into the governance assessment and board reporting\n\n"
            "   e) After drafting, produce one Audit Interview Summary using this template:\n"
            + _AUDIT_OUTPUT_TEMPLATE + "\n"

            "── OUTPUT ───────────────────────────────────────────────────────────────────────\n"
            "10. Output ALL INTERVIEW SCRIPTS (L0, L1, L2, L3, C, and A) as a single JSON object keyed "
            "by node_label. L0, L1, L2, C, and A scripts include framing_block and synthesis_check. "
            "L1 and L2 sections include a maturity_rating block; L0, L3, C, and A sections do not. "
            "L0 synthesis_check includes the additional portfolio_options and sponsorship_check fields. "
            "This is the ONLY script artefact — there is no separate questionnaire.\n"
            "   {\n"
            "     \"<node_label>\": {\n"
            "       \"node_label\": \"<node_label>\",\n"
            "       \"level\": \"L0\" | \"L1\" | \"L2\" | \"L3\" | \"C\" | \"A\",\n"
            "       \"research_brief\": \"...\",\n"
            "       \"study_objectives\": [\"...\"],\n"
            "       \"welcome_message\": \"...\",\n"
            "       // L0, L1, L2, C, and A — framing block spoken before any questions:\n"
            "       \"framing_block\": {   // PRESENT for L0, L1, L2, C, and A; OMIT for L3\n"
            "         \"positioning\": \"We're mapping [L2 cluster] — the strategic layer "
            "that coordinates [L3 names] and feeds [key decisions].\",\n"
            "         \"context_setting\": [\n"
            "           \"This cluster sits between [upstream L1/governance] and "
            "[downstream L3 execution teams].\",\n"
            "           \"We want to understand how decisions flow through this cluster — "
            "where decision quality is built in or lost.\",\n"
            "           \"And where better data, clearer governance, or smarter analysis "
            "could unlock value for [strategic objective].\"\n"
            "         ],\n"
            "         \"dual_lenses\": {\n"
            "           \"efficiency\": \"First, I want to understand coordination friction — "
            "what slows decisions down, creates rework, or blocks alignment.\",\n"
            "           \"effectiveness\": \"And second, decision quality — what decisions "
            "are being made, how confident you are in them, and what decisions you should "
            "be making but currently can't.\"\n"
            "         }\n"
            "       },\n"
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
            "           \"maturity_rating\": {   // PRESENT for L1 and L2 sections only; OMIT for L0, L3, C, and A\n"
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
            "       ],\n"
            "       // L0, L1, L2, C, and A — synthesis check spoken after sections, before closing:\n"
            "       \"synthesis_check\": {   // PRESENT for L0, L1, L2, C, and A; OMIT for L3\n"
            "         \"synthesis_prompt\": \"Before I let you go — based on what you've "
            "told me, here's how I see this cluster: [customised synthesis of intent, "
            "maturity, constraint, data gap, opportunity]. Does that match your assessment?\",\n"
            "         \"response_probes\": {\n"
            "           \"if_positive\": \"Good — what would you add or emphasise differently?\",\n"
            "           \"if_defensive\": \"Where does my picture differ from yours?\",\n"
            "           \"if_uncertain\": \"What would you want me to verify with others?\"\n"
            "         },\n"
            "         \"peer_referral\": \"Who else should I speak to for a full picture? "
            "I'm looking for upstream input providers, downstream executors, governance "
            "stakeholders, and data or IT owners.\",\n"
            "         \"forward_roadmap\": \"If you were shaping the improvement roadmap "
            "for this cluster, where would you start — quick wins in 6 months, or building "
            "foundations for 2 years? And what's your biggest concern?\",\n"
            "         // L0 ONLY — omit for L1 and L2:\n"
            "         \"portfolio_options\": \"Following discovery interviews, I'll present three "
            "portfolio options: Option A (Sequential) — [L1a] established first, then [L1b]; "
            "Option B (Parallel) — both transform simultaneously; Option C (Phased with gates) — "
            "both begin with defined decision gates at [milestones]. Which framing resonates? "
            "Or is there a fourth option you would add?\",\n"
            "         \"sponsorship_check\": \"Can we count on your support to unblock barriers "
            "as they emerge — particularly [specific barrier from the interview]?\"\n"
            "       },\n"
            "       \"closing_message\": \"...\"\n"
            "     }\n"
            "   }\n"
            "   The scale labels must be SPECIFIC to the dimension — not generic. "
            "E.g. for 'Evidence-base' in an L2 risk decision: 0='Risk decisions are gut-feel "
            "with no documented evidence', 4='Risk scoring is driven by real-time sensor data "
            "and predictive models'. Make each label a concrete description of that state "
            "in the client's operational context.\n"
            "   Use SQLiteStateTool with operation='write', key='interview_scripts', "
            "agent_name='interaction_designer' to save this.\n\n"
            "11. Save INTERVIEW SUMMARIES as five separate artefacts:\n"
            "   a) AUDIT INTERVIEW SUMMARIES (one per auditor/regulator, produced in step 9e):\n"
            "      { \"<node_label>\": { <fields from Audit Interview Summary Template> } }\n"
            "      Use SQLiteStateTool with operation='write', key='audit_interview_summaries', "
            "agent_name='interaction_designer' to save this.\n"
            "   b) CUSTOMER INTERVIEW SUMMARIES (one per segment, produced in step 8e):\n"
            "      { \"<node_label>\": { <fields from Customer Interview Summary Template> } }\n"
            "      Use SQLiteStateTool with operation='write', key='customer_interview_summaries', "
            "agent_name='interaction_designer' to save this.\n"
            "   c) L0 INTERVIEW SUMMARIES (one per L0 node, produced in step 4e):\n"
            "      { \"<node_label>\": { <fields from L0 Interview Summary Template> } }\n"
            "      Use SQLiteStateTool with operation='write', key='l0_interview_summaries', "
            "agent_name='interaction_designer' to save this.\n"
            "   d) L1 INTERVIEW SUMMARIES (one per L1 node, produced in step 5g):\n"
            "      { \"<node_label>\": { <fields from L1 Interview Summary Template> } }\n"
            "      Use SQLiteStateTool with operation='write', key='l1_interview_summaries', "
            "agent_name='interaction_designer' to save this.\n"
            "   e) L2 INTERVIEW SUMMARIES (one per L2 node, produced in step 6g):\n"
            "      { \"<node_label>\": { <fields from L2 Interview Summary Template> } }\n"
            "      Use SQLiteStateTool with operation='write', key='l2_interview_summaries', "
            "agent_name='interaction_designer' to save this.\n\n"
            "12. Use HumanInputTool with prompt: 'Assessment instruments saved. Please review:\n"
            "   • outputs/interview_scripts.json — integrated scripts for all L0, L1, L2, L3, C, and A nodes.\n"
            "   For Audit (A) scripts, check:\n"
            "     FRAMING BLOCK\n"
            "     - Does positioning explicitly state this is NOT a defensive exercise —\n"
            "       that we want the independent assessment, not validation of our narrative?\n"
            "     - Do context_setting bullets cover all 5 dimensions: doing what we say,\n"
            "       controls adequacy, governance observations, material gaps, biggest concerns?\n"
            "     - Do dual_lenses cover controls effectiveness AND material gap identification?\n"
            "     SECTIONS\n"
            "     - Are all 10 sections present in order with appropriate target_minutes?\n"
            "     - Do questions probe from the AUDITOR'S independent stance (controls, evidence,\n"
            "       patterns) not from management's framing (strategy, plans, intentions)?\n"
            "     - Does S3 probe budget variance history, separation of duties, and overrun cases?\n"
            "     - Does S4 probe data integrity concerns AND independent verification?\n"
            "     - Does S6 probe data completeness, governance controls, and strategic trust?\n"
            "     - Does S7 probe whether ISS/DXI performance is independently verified?\n"
            "     - Are there NO maturity_rating blocks in any audit section?\n"
            "     - Do evasion_signals flag diplomatic non-answers ('generally adequate',\n"
            "       'we monitor it', 'no major concerns')?\n"
            "     SYNTHESIS CHECK\n"
            "     - Does synthesis_prompt cover governance maturity + material control gaps +\n"
            "       compliance status + data integrity + vendor management + transformation\n"
            "       readiness + risk rating? Is it customised, not a template?\n"
            "     - Does forward_roadmap cover: key findings for board, recommendations,\n"
            "       remediation plan, and re-assessment timeline?\n"
            "   For Customer (C) scripts, check:\n"
            "     FRAMING BLOCK\n"
            "     - Does positioning make it explicit this is NOT a complaint session or performance review?\n"
            "     - Does context_setting cover all 5 dimensions (what works, friction, what would help,\n"
            "       constraints, data/planning impact) with client-specific language?\n"
            "     - Do dual_lenses capture friction (current pain) AND aspiration (what excellent looks like)?\n"
            "     SECTIONS\n"
            "     - Are all 8 sections present in order with appropriate target_minutes?\n"
            "     - Do questions probe from the CUSTOMER'S operational lens (not from our internal view)?\n"
            "     - Does S2 push for quantified friction (hours/week, frequency, £ impact)?\n"
            "     - Does S4 ask both the 1–10 satisfaction question AND the below-5 risk question?\n"
            "     - Are there NO maturity_rating blocks in any customer section?\n"
            "     - Do evasion_signals flag diplomatic non-answers ('generally fine', 'no real complaints')?\n"
            "     SYNTHESIS CHECK\n"
            "     - Does synthesis_prompt restate friction + impact + what would help + satisfaction rating?\n"
            "       Is it customised (no placeholders)?\n"
            "     - Does forward_roadmap preview proposed improvements for customer validation?\n"
            "     - Does peer_referral invite ongoing engagement AND ask for additional customer contacts?\n"
            "   For L0 scripts, check:\n"
            "     FRAMING BLOCK\n"
            "     - Does positioning frame this as a PORTFOLIO assessment (not a single-L1 review)?\n"
            "     - Do context_setting bullets cover strategic coherence, capital efficiency, risk,\n"
            "       governance, and competitive positioning — with client-specific L1 names?\n"
            "     - Are dual_lenses named investment health AND transformation potential?\n"
            "     SECTIONS\n"
            "     - Are all 6 sections present (no selection/omission)?\n"
            "     - Do questions probe portfolio logic, capital allocation, ROI, governance?\n"
            "     - Are there NO maturity_rating blocks in any L0 section?\n"
            "     - Does S3 probe ROI expectations, downside tolerance, and value tracking?\n"
            "     - Does S5 probe accountability, review cadence, and kill criteria?\n"
            "     SYNTHESIS CHECK\n"
            "     - Does synthesis_prompt cover portfolio role + total investment + ROI + constraint\n"
            "       + execution risk + board decision? Is it customised (no placeholders)?\n"
            "     - Are portfolio_options A/B/C present with the client's L1 capability names?\n"
            "     - Does sponsorship_check name a specific barrier from the interview?\n"
            "   For L1 scripts, check:\n"
            "     FRAMING BLOCK\n"
            "     - Does the positioning frame the capability as a STRATEGIC ASSET (not a process map)?\n"
            "     - Are the context_setting bullets the capability health check agenda (strategic clarity,\n"
            "       competitive position, maturity trajectory, digital readiness, transformation roadmap)?\n"
            "     - Do the dual_lenses cover capability health AND transformation potential?\n"
            "     SECTIONS\n"
            "     - Are S1, S2, and S3 present and mandatory?\n"
            "     - Are the right optional sections selected for this node's strategic context?\n"
            "     - Do questions probe at strategic level (mandate, value, maturity) not operational?\n"
            "     - Does S3 cover all five maturity dimensions (Data, Decision, Process, Tech, Org)?\n"
            "     - Do scale labels echo the narrative language (not generic CMMI terms)?\n"
            "     SYNTHESIS CHECK\n"
            "     - Does synthesis_prompt cover mandate + composite maturity + binding constraint\n"
            "       + value opportunity + critical path + biggest risk? Is it customised, not templated?\n"
            "     - Does peer_referral name CFO, CTO, HR/OD, COO, and relevant external partners?\n"
            "     - Does forward_roadmap ask both the 90-day question AND the commitment check?\n"
            "   For L2 scripts, check:\n"
            "     FRAMING BLOCK\n"
            "     - Does the positioning sentence correctly name the L2 cluster, its L3 inputs,\n"
            "       and the decisions it feeds?\n"
            "     - Are the context_setting bullets specific to this node's upstream/downstream\n"
            "       relationships (not generic)?\n"
            "     - Do the dual_lenses statements feel natural for an interviewer to speak aloud?\n"
            "     SECTIONS\n"
            "     - Are the right sections selected for this node's priority and context?\n"
            "     - Each rating prompt reads naturally after the section's narrative questions\n"
            "     - Scale labels echo the narrative language (not CMMI/COBIT jargon)\n"
            "     - The probe_on_mismatch phrase is usable by the interviewer in conversation\n"
            "     SYNTHESIS CHECK\n"
            "     - Is the synthesis_prompt customised (not a template) and plausible for this node?\n"
            "     - Do the response_probes cover the three reply types (positive, defensive, uncertain)?\n"
            "     - Is the peer_referral question specific about the four triangulation perspectives?\n"
            "   For L3 scripts, check:\n"
            "     - No framing_block, no synthesis_check, no maturity_rating blocks\n"
            "     - Exactly 8 sections in prescribed order with correct target_minutes\n"
            "   • outputs/audit_interview_summaries.json — governance assessment per auditor/regulator\n"
            "   • outputs/customer_interview_summaries.json — customer persona per segment\n"
            "   • outputs/l0_interview_summaries.json — portfolio logic prep per L0 node\n"
            "   • outputs/l1_interview_summaries.json — capability strategy prep per L1 node\n"
            "   • outputs/l2_interview_summaries.json — decision architecture prep per L2 node\n"
            "   Reply \"approved\" to proceed, or provide revision notes.'\n"
            "13. If revision notes received, revise and call HumanInputTool again. "
            "Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "Six artefacts saved via SQLiteStateTool: (1) interview_scripts.json — one "
            "integrated script per L0, L1, L2, L3, C (customer), and A (audit) node; L0, L1, L2, "
            "C, and A scripts include framing_block and synthesis_check; L0 synthesis_check also "
            "includes portfolio_options and sponsorship_check; L1 and L2 sections include "
            "maturity_rating blocks; L0, L3, C, and A sections have no maturity_rating blocks; "
            "L3 scripts have exactly 8 fixed sections with no framing_block or synthesis_check; "
            "C scripts have exactly 8 fixed sections with framing_block and synthesis_check; "
            "A scripts have exactly 10 fixed sections with framing_block and synthesis_check; "
            "(2) audit_interview_summaries.json — one governance assessment per auditor/regulator "
            "covering governance maturity, compliance status, financial controls, KPI integrity, "
            "risk management, data quality, third-party management, transformation readiness, "
            "overall risk rating, and prioritised recommendations; "
            "(3) customer_interview_summaries.json — one customer persona per segment covering "
            "friction points, satisfaction (1–10 Property and Fleet), unmet needs, data/partnership "
            "quality, change readiness, competitive context, champion/detractor classification, and "
            "key quotes for the business case; "
            "(4) l0_interview_summaries.json — one L0 Interview Summary per L0 node covering "
            "portfolio logic, competitive context, capital allocation & ROI, execution risk, "
            "governance, board alignment, cross-level misalignments, portfolio option resonance, "
            "and sponsorship assessment; (5) l1_interview_summaries.json — one L1 Interview Summary "
            "per L1 node covering strategic mandate, competitive position, five-dimension maturity, "
            "value architecture, digital readiness, three-horizon roadmap, CSFs, and peer interview "
            "priorities; (6) l2_interview_summaries.json — one L2 Interview Summary per L2 node "
            "covering decision architecture, data landscape, orchestration friction, and monetised "
            "opportunity. No separate questionnaire artefact. All approved by human reviewer."
        ),
        agent=agent,
    )
