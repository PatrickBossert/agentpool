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
            "Design integrated interview scripts for every active L1, L2, and L3 value chain node. "
            "All levels use a single script artefact — maturity ratings are embedded within each "
            "section as maturity_rating blocks, captured after the narrative discussion. There is "
            "no separate questionnaire artefact. L3 nodes do not include maturity_rating blocks.\n\n"
            + _CONCEPTUAL_SHIFT + "\n"
            + _L2_L3_FRAMEWORK + "\n"
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
            "Collect every entry where active=true and level is 'L1', 'L2', or 'L3'.\n"
            "2. Use SQLiteStateTool with operation='read', key='value_chain_summary', "
            "agent_name='interaction_designer' to understand the client's operations.\n"
            "3. Use ChromaQueryTool with collection='project' to gather corporate context "
            "(governance posture, known capability gaps, adopted standards, language used).\n\n"

            "── L1 NODES (strategic / portfolio level — GMs and value-stream owners) ────────\n"
            "4. For each L1 node, apply all 10 L1 Interview Principles from your backstory. "
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
            "5. For each L2 node, apply all 10 L2 Interview Principles from your backstory. "
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
            "by node_label. L2 scripts include framing_block and synthesis_check fields. "
            "L1 and L2 sections include a maturity_rating block. L3 sections do not. "
            "This is the ONLY script artefact — there is no separate questionnaire.\n"
            "   {\n"
            "     \"<node_label>\": {\n"
            "       \"node_label\": \"<node_label>\",\n"
            "       \"level\": \"L1\" | \"L2\" | \"L3\",\n"
            "       \"research_brief\": \"...\",\n"
            "       \"study_objectives\": [\"...\"],\n"
            "       \"welcome_message\": \"...\",\n"
            "       // L1 and L2 — framing block spoken before any questions:\n"
            "       \"framing_block\": {   // PRESENT for L1 and L2; OMIT for L3\n"
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
            "       ],\n"
            "       // L1 and L2 — synthesis check spoken after all sections, before closing:\n"
            "       \"synthesis_check\": {   // PRESENT for L1 and L2; OMIT for L3\n"
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
            "foundations for 2 years? And what's your biggest concern?\"\n"
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
            "8. Save INTERVIEW SUMMARIES as two separate artefacts:\n"
            "   a) L1 INTERVIEW SUMMARIES (one per L1 node, produced in step 4g):\n"
            "      { \"<node_label>\": { <fields from L1 Interview Summary Template> } }\n"
            "      Use SQLiteStateTool with operation='write', key='l1_interview_summaries', "
            "agent_name='interaction_designer' to save this.\n"
            "   b) L2 INTERVIEW SUMMARIES (one per L2 node, produced in step 5g):\n"
            "      { \"<node_label>\": { <fields from L2 Interview Summary Template> } }\n"
            "      Use SQLiteStateTool with operation='write', key='l2_interview_summaries', "
            "agent_name='interaction_designer' to save this.\n\n"
            "9. Use HumanInputTool with prompt: 'Assessment instruments saved. Please review:\n"
            "   • outputs/interview_scripts.json — integrated scripts for all L1, L2, and L3 nodes.\n"
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
            "   • outputs/l1_interview_summaries.json — capability strategy prep per L1 node\n"
            "   • outputs/l2_interview_summaries.json — decision architecture prep per L2 node\n"
            "   Reply \"approved\" to proceed, or provide revision notes.'\n"
            "10. If revision notes received, revise and call HumanInputTool again. "
            "Repeat at most 3 times total.\n"
        ),
        expected_output=(
            "Three artefacts saved via SQLiteStateTool: (1) interview_scripts.json — one "
            "integrated script per L1, L2, and L3 node; L1 and L2 scripts include framing_block "
            "and synthesis_check; L1, L2 sections include maturity_rating blocks with "
            "dimension-specific scale labels captured after narrative; L3 scripts have exactly "
            "8 sections with no framing_block, no synthesis_check, no maturity_rating; "
            "(2) l1_interview_summaries.json — one L1 Interview Summary per L1 node covering "
            "strategic mandate, competitive position, five-dimension maturity, value architecture, "
            "digital readiness, three-horizon roadmap, CSFs, and peer interview priorities; "
            "(3) l2_interview_summaries.json — one L2 Interview Summary per L2 node covering "
            "decision architecture, data landscape, orchestration friction, and monetised opportunity. "
            "No separate questionnaire artefact. All approved by human reviewer."
        ),
        agent=agent,
    )
