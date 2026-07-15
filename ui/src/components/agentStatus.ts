// ui/src/components/agentStatus.ts
import type { LucideIcon } from 'lucide-react'
import {
  Network, Tags, FileText, Globe, ExternalLink, Brain, Map, Database, UserCheck,
  FileEdit, ClipboardList, Target, Ruler, BarChart3, Mail, ClipboardCheck,
  Mic, MessageSquare, Puzzle, Lightbulb, TrendingUp, Table, Building2,
  Route, Calculator, FileOutput, Presentation,
  PenTool, Layers, Cpu, Sparkles, Wand2, ImageIcon,
  CalendarDays, FileBarChart2, Shield, AlertOctagon,
} from 'lucide-react'
import type { CrewRun } from '../types'

export const CREW_ORDER = [
  'discovery_mapping',
  'stakeholder_management',
  'assessment_design',
  'discovery_interviews',
  'discovery',
  'value_design',
  'architecture',
  'delivery',
  'business_plan',
] as const

// Snake-case agent names per crew — mirrors api/services/run_service.py _CREW_AGENT_NAMES
export const CREW_AGENT_NAMES: Record<string, string[]> = {
  discovery_mapping:      ['value_chain_mapper'],
  assessment_design:      ['interaction_designer'],
  discovery:              ['requirements_capture', 'requirements_analyst', 'value_lever_analyst'],
  stakeholder_management: ['stakeholder_manager'],
  discovery_interviews:   ['interview_coordinator', 'stakeholder_interviewer', 'synthesis_analyst'],
  value_design:           ['value_proposition_generator', 'portfolio_manager'],
  architecture:           ['enterprise_architect', 'initiative_identifier'],
  delivery:               ['roadmap_generator'],
  business_plan:          ['business_plan_generator'],
}

export type CrewName = (typeof CREW_ORDER)[number]

export const CREW_LABELS: Record<string, string> = {
  PAM:                    'PMO',
  discovery_mapping:      'Value Chain Mapping',
  assessment_design:      'Assessment Design',
  discovery:              'Discovery',
  stakeholder_management: 'Stakeholder Management',
  discovery_interviews:   'Discovery Interviews',
  value_design:           'Value Design',
  architecture:           'Architecture',
  delivery:               'Delivery',
  business_plan:          'Business Plan',
}

export const CREW_AGENTS: Record<string, string[]> = {
  PAM:                   ['PAM'],
  discovery_mapping:     ['Value Chain Mapper'],
  assessment_design:     ['Interaction Designer'],
  discovery: [
    'Requirements Capture',
    'Requirements Analyst',
    'Value Lever Analyst',
  ],
  stakeholder_management: ['Stakeholder Manager'],
  discovery_interviews: [
    'Interview Coordinator',
    'Stakeholder Interviewer',
    'Synthesis Analyst',
  ],
  value_design:  ['Value Proposition Generator', 'Portfolio Manager'],
  architecture:  ['Enterprise Architect', 'Initiative Identifier'],
  delivery:      ['Roadmap Generator', 'Visual Illustrator'],
  business_plan: ['Business Plan Generator'],
}

export const CREW_ICONS: Record<string, string> = {
  discovery_mapping:      '🗺️',
  assessment_design:      '🎨',
  discovery:              '🔍',
  stakeholder_management: '🤝',
  discovery_interviews:   '🎙️',
  value_design:           '⭐',
  architecture:           '🏛️',
  delivery:               '🚀',
  business_plan:          '📊',
}

export interface AgentSkill {
  name: string
  description: string
  icon: LucideIcon
}

export const AGENT_SKILLS: Record<string, AgentSkill[]> = {
  'PAM': [
    { name: 'Pipeline Orchestration', description: 'Sequences the full engagement pipeline — from Value Chain Mapping through to Business Plan — dispatching each crew in the correct order, respecting dependencies, and ensuring no phase begins before its prerequisites are satisfied.', icon: Network },
    { name: 'Phase Gating', description: 'Holds the gate between phases, preventing downstream crews from running until human review has been confirmed. Ensures the project team has an opportunity to validate outputs at every critical transition.', icon: UserCheck },
    { name: 'Schedule Management', description: 'Maintains the project schedule — critical milestones, due dates, and completion tracking. Monitors progress against plan, identifies slippage early, and recommends corrective actions before schedule risk becomes schedule fact.', icon: CalendarDays },
    { name: 'Status Reporting', description: 'Produces a live status report at any point in the engagement: overall RAG health, progress against plan, per-crew output summary, active risks with mitigations, and issues with escalation recommendations. The report is formatted for direct inclusion in a formal client reporting pack.', icon: FileBarChart2 },
    { name: 'Risk Management', description: 'Continuously evaluates engagement risk from project state — knowledge base gaps, stakeholder coverage, schedule slippage, review backlogs, and interview completion. Derives risk severity and recommended mitigations algorithmically from live data, with no manual input required.', icon: Shield },
    { name: 'Issue Management & Escalation', description: 'Identifies active issues — failed crew runs, overdue milestones, stalled phase gates, low interview completion — and generates specific, actionable escalation recommendations for each. Prioritises by severity to direct the project team\'s attention to what matters most.', icon: AlertOctagon },
    { name: 'State Awareness', description: 'Reads the full project state — crew run history, output versions, review status, stakeholder data, milestones, and interview sessions — before any decision, ensuring recommendations are grounded in the current picture of the engagement.', icon: Database },
    { name: 'Escalation Management', description: 'Monitors crew execution for failures, stalls, and human review timeouts. Escalates to the project team via Slack when intervention is required, with a clear summary of what is blocked and what decision is needed.', icon: MessageSquare },
    { name: 'Decision Intelligence', description: 'Applies engagement-level judgement to determine when revision cycles are exhausted, when a crew output is sufficient to proceed, and when human input is genuinely required versus when it can be inferred from project context.', icon: Brain },
  ],
  'Value Chain Mapper': [
    { name: 'Value Chain Analysis', description: 'Applies Porter\'s Value Chain framework to decompose the organisation into L1 value streams (owned by senior leaders such as GMs), L2 process stages (owned by process managers), and L3 activities. Produces a structured n.n.n numbered activity tree and a summary narrative for downstream agents.', icon: Network },
    { name: 'Stable ID Registry', description: 'Maintains a permanent value_chain_registry.json with n.n.n IDs (L1=n, L2=n.n, L3=n.n.n). IDs are assigned once and never reassigned - new activities extend the sequence, removed activities are marked inactive. This enables all downstream artefacts (interview scripts, questionnaires, stakeholder assignments) to reference activities by stable numeric ID across iterations.', icon: Tags },
    { name: 'Document Ingestion', description: 'Reads and parses uploaded client documents - strategy papers, annual reports, operational procedures - into structured content that informs the value chain decomposition.', icon: FileText },
    { name: 'Web Search', description: 'Searches the internet for current sector intelligence, comparable value chains, and industry benchmarks to validate the decomposition against peer organisations.', icon: Globe },
    { name: 'Web Fetch', description: 'Retrieves full content from specific URLs for deep reading - useful for standards documents, sector frameworks, and reference architectures.', icon: ExternalLink },
    { name: 'Semantic Search', description: 'Queries the project vector knowledge base for relevant corporate context - prior outputs, ingested documents, and historical assessments - to ground the value chain in organisational reality.', icon: Brain },
    { name: 'Diagram Rendering', description: 'Creates and renders Mermaid diagrams as visual outputs, producing the authoritative value chain tree diagram alongside the JSON registry.', icon: Map },
    { name: 'State Management', description: 'Reads and writes structured project state between agent runs - registry, summary, and tree - so every downstream agent starts with a consistent, current picture of the value chain.', icon: Database },
    { name: 'Human Review', description: 'Pauses for human approval after completing the value chain draft, allowing the project team to validate decomposition boundaries and naming before assessment instruments are designed.', icon: UserCheck },
  ],
  'Interaction Designer': [
    { name: 'Interview Script Design', description: 'Creates tailored interview scripts for every active L1 and L2 value chain node, following n.n.n numbering. L1 scripts (strategic level) target GMs and value stream leaders with questions on portfolio governance, investment prioritisation, and strategic intent. L2 scripts (operational level) target process managers with questions on process control, standard adherence, and improvement maturity.', icon: FileEdit },
    { name: 'Maturity Questionnaire Design', description: 'Develops maturity assessment questionnaires for all active L1 and L2 nodes. Questionnaires use a 1–5 maturity scale aligned with configured frameworks (ISO 55001, IIMM, PAS 55, IIRC Six Capitals, and sector-specific references). Section titles reference relevant standard clauses for traceability and auditability.', icon: ClipboardList },
    { name: 'Coherent Instrument Design', description: 'Designs interview scripts and maturity questionnaires together as a unified assessment set, ensuring the two instruments reinforce each other - the interview probes for qualitative evidence, the questionnaire captures rated maturity judgements - rather than duplicating or contradicting.', icon: Target },
    { name: 'Standards Grounding', description: 'Grounds all instrument content in the standards and references configured in the Value Chain Setup (e.g. ISO 55001, IIMM, PAS 55). Queries the project knowledge base for corporate context relevant to each node - known gaps, adopted practices, governance posture - to make questions sharply contextual.', icon: Ruler },
    { name: 'Template Auto-Assignment', description: 'On completion, automatically publishes each script and questionnaire as a named template in the system library and assigns it to the corresponding value chain node by n.n.n activity ID, maintaining referential integrity across the assessment dataset.', icon: Tags },
    { name: 'Semantic Search', description: 'Queries the project knowledge base for corporate context relevant to assessment design - prior interview transcripts, ingested standards documents, and previously generated outputs - to ensure instruments are grounded in organisational reality.', icon: Brain },
    { name: 'State Management', description: 'Reads the value chain registry and summary; writes both interview_scripts.json and questionnaire_scripts.json outputs to the project outputs directory for downstream use by the Stakeholder Manager and Interview Coordinator.', icon: Database },
    { name: 'Human Review', description: 'Requests approval of the completed instrument set (both scripts and questionnaires) before deployment to stakeholders, allowing the project team to validate coverage, tone, and alignment with assessment objectives.', icon: UserCheck },
  ],
  'Stakeholder Manager': [
    { name: 'Coverage Analysis', description: 'Monitors stakeholder-to-node assignments across L1, L2, and L3 value chain levels. Calculates coverage ratios per level and per value stream, identifies nodes with no assigned stakeholders, and flags where key leadership or subject matter expert perspectives are missing from the interview programme.', icon: BarChart3 },
    { name: 'Communication Management', description: 'Drafts and tracks a progressive sequence of stakeholder communications calibrated to urgency and stakeholder seniority: (1) initial invitation - professional and contextual; (2) first reminder - warm and helpful; (3) second reminder - direct and deadline-focused; (4) re-engagement - escalates to the project team. Dispatches via Slack with structured per-stakeholder action items.', icon: Mail },
    { name: 'Engagement Planning', description: 'Writes a structured stakeholder_engagement_plan.json documenting current coverage status, communication history, session completion rates, recommended next actions per stakeholder, and overall programme health. This plan is the authoritative record of stakeholder engagement state for the project team.', icon: ClipboardCheck },
    { name: 'Interview Session Tracking', description: 'Queries interview session status (not started, in progress, completed, abandoned) for every assigned stakeholder and uses completion data to prioritise follow-up communications - avoiding reminders to stakeholders who have already participated.', icon: Mic },
    { name: 'Slack Notifications', description: 'Sends actionable summary notifications to the project team Slack channel when coverage gaps are identified, when communications are dispatched, and when the engagement plan is updated - keeping the project team informed without requiring manual status checks.', icon: MessageSquare },
    { name: 'State Management', description: 'Reads the stakeholder registry, node template assignments, and interview session data; writes the stakeholder_engagement_plan.json output to the project directory.', icon: Database },
  ],
  'Requirements Capture': [
    { name: 'Human Review', description: 'Engages directly with the project team to capture requirements, constraints, and priorities through structured conversation - ensuring the discovery phase is grounded in what the client has explicitly articulated, not only what documents suggest.', icon: UserCheck },
    { name: 'State Management', description: 'Persists captured requirements to the project state store in structured form, making them available to the Requirements Analyst and downstream agents without loss of fidelity.', icon: Database },
  ],
  'Requirements Analyst': [
    { name: 'Document Ingestion', description: 'Reads and parses uploaded client documents to surface implicit requirements, constraints, and strategic intent that may not have been captured in the direct requirements session.', icon: FileText },
    { name: 'Semantic Search', description: 'Finds related requirements, precedents, and context in the project knowledge base to identify gaps, conflicts, and hidden dependencies in the captured requirement set.', icon: Brain },
    { name: 'State Management', description: 'Reads captured requirements and writes a structured analysed output - with priorities, conflicts, and gaps highlighted - for the Value Lever Analyst and subsequent phases.', icon: Database },
    { name: 'Human Review', description: 'Validates the analysed requirement set with the project team before value lever identification, ensuring no material requirements are misread or mis-prioritised.', icon: UserCheck },
  ],
  'Value Lever Analyst': [
    { name: 'Semantic Search', description: 'Queries the project knowledge base for value-driving patterns, prior initiative outcomes, and corporate context relevant to the identified value levers.', icon: Brain },
    { name: 'Web Search', description: 'Benchmarks identified value levers against published industry data, analyst reports, and peer organisation case studies to validate expected impact ranges.', icon: Globe },
    { name: 'State Management', description: 'Reads the analysed requirements and writes identified levers - with impact estimates, feasibility indicators, and supporting evidence - to the project state store.', icon: Database },
    { name: 'Human Review', description: 'Confirms the prioritised lever set with the project team before value proposition generation, ensuring commercial judgement is applied to analytical output.', icon: UserCheck },
  ],
  'Interview Coordinator': [
    { name: 'Interview Management', description: 'Creates, tracks, and closes interview sessions for each assigned stakeholder. Generates unique interview links, monitors session state, and produces a scheduling plan that sequences interviews efficiently across the programme timeline.', icon: Mic },
    { name: 'State Management', description: 'Reads stakeholder assignments and interview scripts to produce a detailed interview schedule; writes the session plan and tracking data back to the project state.', icon: Database },
    { name: 'Human Review', description: 'Confirms the interview scheduling plan with the project team before sessions are activated, allowing adjustments for stakeholder availability and sequencing preferences.', icon: UserCheck },
  ],
  'Stakeholder Interviewer': [
    { name: 'Interview Management', description: 'Manages interview session state throughout the lifecycle - launching sessions, recording responses, tracking progress through script sections, and marking completion. Ensures each session produces a complete, structured transcript.', icon: Mic },
    { name: 'State Management', description: 'Reads the interview script for the relevant value chain node and writes captured responses, ratings, and qualitative notes as a structured transcript for the Synthesis Analyst.', icon: Database },
    { name: 'Human Review', description: 'Requests clarification from stakeholders during live interview flows when responses are ambiguous or incomplete, ensuring the transcript is actionable for synthesis.', icon: UserCheck },
  ],
  'Synthesis Analyst': [
    { name: 'Theme Extraction', description: 'Reads all completed interview transcripts across L1 and L2 stakeholder groups and extracts cross-cutting themes - maturity gaps, capability strengths, strategic tensions, and consensus priorities - that transcend individual responses.', icon: Puzzle },
    { name: 'State Management', description: 'Reads all interview transcripts and writes a synthesised findings report - structured by value chain area, maturity dimension, and theme - for the Value Proposition Generator and Portfolio Manager.', icon: Database },
    { name: 'Human Review', description: 'Validates synthesised themes and key findings with the project team before value proposition generation, ensuring interpretive judgements are grounded in stakeholder intent.', icon: UserCheck },
  ],
  'Value Proposition Generator': [
    { name: 'Proposition Structuring', description: 'Translates synthesised interview findings and identified value levers into a structured set of value propositions - each with a clear problem statement, proposed intervention, and expected benefit - mapped to the relevant value chain area.', icon: Lightbulb },
    { name: 'State Management', description: 'Reads discovery findings, value levers, and interview synthesis; writes the generated proposition set with activity references and beneficiary mappings to the project state store.', icon: Database },
    { name: 'Human Review', description: 'Requests review of the proposition set before portfolio scoring, allowing the project team to refine framing, merge duplicates, and validate strategic alignment.', icon: UserCheck },
  ],
  'Portfolio Manager': [
    { name: 'IIRC Six Capitals Scoring', description: 'Scores each initiative across eight dimensions derived from the IIRC Integrated Reporting framework - financial, manufactured, intellectual, human, social/relationship, and natural capitals. Applies configured weights to produce a composite portfolio score that reflects the organisation\'s stated priorities.', icon: BarChart3 },
    { name: 'Portfolio Ranking', description: 'Produces a ranked, prioritised initiative register with composite scores, individual capital ratings, cost estimates, and initiative type classifications - providing a defensible, evidence-based basis for investment decisions.', icon: TrendingUp },
    { name: 'State Management', description: 'Reads value propositions, initiatives, and scoring weights; writes the scored portfolio register to the project state store for the Architecture and Delivery phases.', icon: Database },
    { name: 'Excel Export', description: 'Generates a formatted Excel portfolio register for distribution to senior stakeholders - including individual capital scores, composite ranking, and filtering by value stream or initiative type.', icon: Table },
    { name: 'Human Review', description: 'Requests approval of the portfolio prioritisation before architecture design, ensuring commercial and strategic judgement is applied to the quantitative scoring.', icon: UserCheck },
  ],
  'Enterprise Architect': [
    { name: 'Architecture Design', description: 'Designs the enterprise architecture required to deliver the prioritised initiative portfolio - covering capability gaps, technology enablers, integration patterns, and organisational design implications. Output is structured to drive the initiative decomposition and roadmap sequencing.', icon: Building2 },
    { name: 'Semantic Search', description: 'Queries the project knowledge base for existing architecture context - current-state capabilities, adopted standards, prior design decisions - to ensure the target architecture is grounded in organisational reality rather than a greenfield ideal.', icon: Brain },
    { name: 'Diagram Rendering', description: 'Produces architecture diagrams as Mermaid visuals - capability maps, integration diagrams, and solution blueprints - for inclusion in the business plan and stakeholder presentations.', icon: Map },
    { name: 'State Management', description: 'Writes the architecture blueprint - including capability model, design decisions, and enabling conditions - to the project state store for the Initiative Identifier.', icon: Database },
    { name: 'Human Review', description: 'Validates the architecture blueprint with the project team before initiative decomposition, ensuring technical assumptions are confirmed and design constraints are acknowledged.', icon: UserCheck },
  ],
  'Initiative Identifier': [
    { name: 'Initiative Decomposition', description: 'Reads the architecture blueprint and decomposes it into a discrete set of initiatives - each with a defined scope, expected outputs, dependencies, value stream alignment, and indicative cost band - that can be independently planned and resourced.', icon: Target },
    { name: 'State Management', description: 'Reads the architecture blueprint and portfolio register; writes the initiative register - structured for roadmap sequencing and business plan integration - to the project state store.', icon: Database },
    { name: 'Human Review', description: 'Validates initiative scope, boundaries, and dependencies with the project team, ensuring the decomposition reflects delivery realities rather than architectural ideals.', icon: UserCheck },
  ],
  'Roadmap Generator': [
    { name: 'Roadmap Sequencing', description: 'Sequences initiatives across value streams and time horizons - short, medium, and long - taking into account dependencies, resource constraints, quick-win opportunities, and strategic priority scores from the portfolio. Produces a phased delivery plan with a logical, executable cadence.', icon: Route },
    { name: 'Roadmap Rendering', description: 'Generates an interactive HTML roadmap for client presentation - with swim-lane layout by value stream, hover detail per initiative, and print-ready formatting. Also writes roadmap_data.json for the Gantt chart view.', icon: Map },
    { name: 'State Management', description: 'Reads the initiative register and portfolio scores; writes roadmap sequencing, HTML output, and structured roadmap data to the project output directory.', icon: Database },
    { name: 'Human Review', description: 'Confirms roadmap timing, value stream allocation, and phasing with the project team before business plan finalisation.', icon: UserCheck },
  ],
  'Visual Illustrator': [
    { name: 'Vision Illustration', description: 'Reads the value chain registry (L1 and L2 nodes, entity context, sector) and produces a richly contextualised illustration brief for a hand-sketched, isometric 16:9 image. The brief specifies each L1 banner, its L2 stage sequence, relevant entities or systems at each stage, flow arrows, and a consistent visual tone - designed for input into any image generation tool (DALL·E, Midjourney, Firefly) with minimal further editing.', icon: PenTool },
    { name: 'Value Proposition Vignettes', description: 'For each approved value proposition, generates a paired before/after vignette brief: a compact scene illustrating the current pain point (before) and a second scene showing the improved state (after). Each vignette captures the key stakeholder, the process context, and the specific change - suitable for a single slide or infographic panel.', icon: Layers },
    { name: 'Architecture Schematic', description: 'Translates the enterprise architecture blueprint into a technical illustration brief - showing the target capability model as a labelled schematic with clear zones (e.g. operational technology, information management, integration layer), connection patterns, and the relevant enabling initiatives. Designed for hand-sketched technical illustration style, not UML.', icon: Cpu },
    { name: 'Roadmap Illustration', description: 'Works from River\'s roadmap sequencing to produce a visual representation brief: a timeline swimlane illustration showing initiative clusters by value stream and time horizon. Where River\'s output is interactive HTML data, this agent\'s output is a static illustration brief optimised for executive presentations and printed reports.', icon: Map },
    { name: 'Operating Model Change', description: 'Generates illustration briefs for change initiative visuals - each depicting the key process or capability being transformed, with a split composition showing current state and target state side by side. Useful for change management materials, stakeholder workshops, and programme communications.', icon: Sparkles },
    { name: 'Future State Operating Model', description: 'Produces a high-level visual brief of the target operating model: the principal functions, their relationships, the enabling technology layer, and the value flows between them - illustrated in a clean, isometric style suitable for a one-page executive artefact.', icon: ImageIcon },
    { name: 'Prompt Engineering', description: 'Builds precise, context-rich image generation prompts tailored to the project\'s sector, value chain structure, and client brand context. Prompts specify style (hand-sketched isometric), format (16:9 landscape), labelling level (L1 banners + L2 labels only), visual elements per stage, and explicit instructions to avoid common generation errors such as duplicated stages or overcrowded labels.', icon: Wand2 },
    { name: 'State Management', description: 'Reads the value chain registry, roadmap data, architecture blueprint, and proposition set; writes illustration_briefs.json to the project output directory - one brief per illustration type, each containing the full generation prompt and a JSON structure of the elements to be depicted.', icon: Database },
  ],
  'Business Plan Generator': [
    { name: 'Financial Modelling', description: 'Calculates NPV, IRR, payback period, and maximum borrowing capacity based on initiative costs, benefit profiles, and configured financial assumptions (discount rate, benefit realisation curve, planning horizon). Produces a rigorous investment case grounded in the initiative portfolio.', icon: Calculator },
    { name: 'Business Plan Narrative', description: 'Compiles the full business plan narrative - executive summary, strategic context, value chain assessment findings, initiative portfolio, financial model, and delivery roadmap - drawing on all prior crew outputs for a coherent, evidence-based investment case.', icon: FileText },
    { name: 'Word Export', description: 'Generates a formatted Word document business plan suitable for board and executive distribution - with structured headings, embedded tables, and branded section formatting.', icon: FileOutput },
    { name: 'PowerPoint Export', description: 'Generates an executive summary slide deck - condensing key findings, portfolio priorities, financial headline, and roadmap into presentation-ready slides.', icon: Presentation },
    { name: 'State Management', description: 'Reads the full project model - value chain, assessment findings, portfolio, architecture, roadmap - and writes the business plan documents to the project output directory.', icon: Database },
    { name: 'Human Review', description: 'Requests sign-off on financial assumptions before modelling, ensuring the business case reflects commercially agreed parameters rather than analytical defaults.', icon: UserCheck },
  ],
}

// Maps display name → internal agent key accepted by POST /projects/{slug}/run
export const AGENT_RUN_KEYS: Record<string, string> = {
  'Interaction Designer':        'interaction_designer',
  'Stakeholder Manager':         'stakeholder_manager',
  'Requirements Analyst':        'requirements_analyst',
  'Value Lever Analyst':         'value_lever_analyst',
  'Synthesis Analyst':           'synthesis_analyst',
  'Value Proposition Generator': 'value_proposition_generator',
  'Portfolio Manager':           'portfolio_manager',
  'Enterprise Architect':        'enterprise_architect',
  'Initiative Identifier':       'initiative_identifier',
  'Roadmap Generator':           'roadmap_generator',
  'Visual Illustrator':          'visual_illustrator',
  'Business Plan Generator':     'business_plan_generator',
}

export const AGENT_ROLE: Record<string, string> = {
  'PAM': 'Orchestrates the entire engagement pipeline from end to end and maintains full programme governance throughout. Sequences crews in the correct order, holds phase gates until human review is confirmed, and monitors execution for failures and stalls. Maintains the project schedule, tracks milestones against plan, identifies risks before they become issues, and produces a live status report — including RAG health, progress vs plan, active risks with mitigations, and issues with escalation recommendations — formatted for direct inclusion in a client reporting pack.',
  'Value Chain Mapper': 'Decomposes the organisation into a structured, three-level value chain - L1 value streams owned by senior leaders, L2 process stages owned by process managers, and L3 activities at the operational level. Assigns stable n.n.n numeric IDs to every node and maintains a permanent registry that persists across iterations, so all downstream artefacts (interview scripts, questionnaires, stakeholder assignments) can reference activities by stable ID. Produces the authoritative value chain tree and summary that all subsequent crews consume.',
  'Interaction Designer': 'Designs the complete set of assessment instruments for the engagement - interview scripts and maturity questionnaires - for every active L1 and L2 value chain node. Works immediately after value chain mapping, before stakeholder assignment, so instruments are grounded in organisational structure rather than individual stakeholders. Designs both instruments together to ensure coherence: the interview probes for qualitative evidence while the questionnaire captures rated maturity judgements. All content is grounded in configured industry standards (ISO 55001, IIMM, PAS 55, IIRC) and the corporate context from ingested documents.',
  'Stakeholder Manager': 'Actively manages stakeholder engagement across the entire interview programme. Analyses stakeholder-to-node assignment coverage at L1, L2, and L3 levels; identifies gaps where nodes lack adequate representation; and drafts a progressive sequence of communications - invitation, first reminder, second reminder, and re-engagement - calibrated to stakeholder seniority and urgency. Tracks interview session completion status to avoid contacting stakeholders who have already participated. Maintains the stakeholder_engagement_plan.json as the authoritative record of programme health and notifies the project team via Slack when action is required.',
  'Requirements Capture': 'Gathers and documents stakeholder requirements, constraints, and strategic priorities through structured dialogue with the project team. Ensures all explicitly articulated needs are captured in structured form before analysis - so the discovery phase is grounded in what the client has said, not only what documents imply.',
  'Requirements Analyst': 'Analyses the captured requirement set for completeness, consistency, priority, and hidden conflicts. Reads client documents to surface implicit requirements that the direct session may have missed, and queries the knowledge base for related precedents. Produces a structured, prioritised requirement analysis that forms the foundation for value lever identification.',
  'Value Lever Analyst': 'Identifies the highest-value levers for organisational improvement based on discovery findings, value chain structure, and external benchmarks. Grounds each lever in evidence - from the knowledge base, client documents, and published industry data - and estimates expected impact ranges. Produces the prioritised lever set that the Value Proposition Generator will translate into discrete propositions.',
  'Interview Coordinator': 'Plans and activates the stakeholder interview programme. Reads node template assignments and stakeholder lists, creates interview sessions with unique links, and sequences interviews efficiently across the programme timeline. Produces a scheduling plan that coordinates L1 strategic interviews and L2 operational interviews without resource conflicts.',
  'Stakeholder Interviewer': 'Conducts voice and text interviews with assigned stakeholders using the pre-designed interview scripts for their value chain node. Manages session state throughout the lifecycle - launching, recording, tracking progress through script sections, and marking completion. Produces a complete, structured transcript for each session that the Synthesis Analyst can work from directly.',
  'Synthesis Analyst': 'Synthesises all completed interview transcripts into structured findings and themes. Identifies patterns that cross individual responses - maturity gaps, capability strengths, strategic tensions, consensus priorities - and organises them by value chain area, maturity dimension, and stakeholder level. Produces the synthesis report that drives value proposition generation and portfolio scoring.',
  'Value Proposition Generator': 'Translates synthesised interview findings and identified value levers into a structured set of value propositions, each with a clear problem statement, proposed intervention, expected benefit, and mapping to the relevant value chain activities and beneficiary groups. Propositions feed directly into the portfolio scoring and architecture design phases.',
  'Portfolio Manager': 'Scores and prioritises the initiative portfolio using the IIRC Integrated Reporting Six Capitals framework. Applies configured weights across eight dimensions to produce a defensible, evidence-based ranking of initiatives. Generates an Excel portfolio register for stakeholder distribution and ensures the investment case is grounded in a transparent, repeatable scoring methodology.',
  'Enterprise Architect': 'Designs the enterprise architecture required to deliver the prioritised initiative portfolio. Covers capability gaps, technology enablers, integration patterns, and organisational design implications. Draws on the project knowledge base for current-state context and produces both a written blueprint and Mermaid architecture diagrams for inclusion in the business plan and stakeholder presentations.',
  'Initiative Identifier': 'Decomposes the architecture blueprint into a discrete set of deliverable initiatives - each with defined scope, expected outputs, dependencies, value stream alignment, and indicative cost band. Ensures the initiative register is granular enough for roadmap sequencing and resource planning, while remaining coherent enough for executive comprehension.',
  'Roadmap Generator': 'Sequences initiatives across value streams and time horizons into a phased delivery roadmap that balances quick wins, dependency order, resource constraints, and portfolio priority scores. Produces an interactive HTML roadmap for client presentation, a structured roadmap data file for the Gantt chart view, and a sequencing narrative for the business plan.',
  'Visual Illustrator': 'Translates the structured outputs of the engagement - value chain, value propositions, architecture blueprint, roadmap, and operating model - into richly contextualised illustration briefs ready for image generation. Each brief is a precise, sector-grounded prompt specifying visual style (hand-sketched isometric), composition, labelling level, flow elements, and what to avoid. Briefs are written so that any image generation tool produces a usable result with minimal iteration.',
  'Business Plan Generator': 'Compiles the complete investment case - drawing on all prior crew outputs - into a coherent business plan narrative and financial model. Calculates NPV, IRR, payback period, and maximum borrowing capacity. Produces formatted Word and PowerPoint outputs suitable for board and executive distribution.',
}

export const AGENT_AVATAR: Record<string, { emoji: string; gradient: string }> = {
  'PAM':                         { emoji: '⚡', gradient: 'from-teal-500 to-teal-700' },
  'Value Chain Mapper':          { emoji: '🗺️', gradient: 'from-teal-400 to-cyan-600' },
  'Interaction Designer':        { emoji: '🎨', gradient: 'from-fuchsia-400 to-violet-600' },
  'Stakeholder Manager':         { emoji: '🤝', gradient: 'from-emerald-400 to-teal-600' },
  'Requirements Capture':        { emoji: '📋', gradient: 'from-indigo-400 to-indigo-700' },
  'Requirements Analyst':        { emoji: '🔍', gradient: 'from-violet-400 to-purple-600' },
  'Value Lever Analyst':         { emoji: '⚖️', gradient: 'from-amber-400 to-orange-500' },
  'Interview Coordinator':       { emoji: '📅', gradient: 'from-sky-400 to-blue-600' },
  'Stakeholder Interviewer':     { emoji: '🎙️', gradient: 'from-cyan-400 to-indigo-600' },
  'Synthesis Analyst':           { emoji: '🧩', gradient: 'from-purple-400 to-indigo-600' },
  'Value Proposition Generator': { emoji: '💡', gradient: 'from-yellow-400 to-amber-500' },
  'Portfolio Manager':           { emoji: '📊', gradient: 'from-green-400 to-emerald-600' },
  'Enterprise Architect':        { emoji: '🏛️', gradient: 'from-slate-400 to-gray-600' },
  'Initiative Identifier':       { emoji: '🎯', gradient: 'from-red-400 to-rose-600' },
  'Roadmap Generator':           { emoji: '🛣️', gradient: 'from-cyan-400 to-teal-600' },
  'Visual Illustrator':          { emoji: '🎨', gradient: 'from-rose-400 to-pink-600' },
  'Business Plan Generator':     { emoji: '📈', gradient: 'from-lime-400 to-green-600' },
}

// Human names for each agent - used in crew cards
export const AGENT_HUMAN_NAME: Record<string, string> = {
  'PAM':                         'Pamela Reid',
  'Value Chain Mapper':          'Alex Chen',
  'Interaction Designer':        'Maya Patel',
  'Stakeholder Manager':         'Jordan Williams',
  'Requirements Capture':        'Sam Torres',
  'Requirements Analyst':        'Riley Kim',
  'Value Lever Analyst':         'Morgan Davis',
  'Interview Coordinator':       'Taylor Brooks',
  'Stakeholder Interviewer':     'Avery Singh',
  'Synthesis Analyst':           'Casey Liu',
  'Value Proposition Generator': 'Quinn Harper',
  'Portfolio Manager':           'Blake Anderson',
  'Enterprise Architect':        'Drew Mitchell',
  'Initiative Identifier':       'Sage Thompson',
  'Roadmap Generator':           'River Martinez',
  'Visual Illustrator':          'Luca Romano',
  'Business Plan Generator':     'Finley Cooper',
}

// Headshot image paths - Vite serves public/ under the configured base (/dashboard)
const _base = import.meta.env.BASE_URL.replace(/\/$/, '')
const _img  = (f: string) => `${_base}/agents/${f}`

export const AGENT_AVATAR_IMAGE: Record<string, string> = {
  'PAM':                         _img('pam.jpg'),
  'Value Chain Mapper':          _img('alex-chen.jpg'),
  'Interaction Designer':        _img('maya-patel.jpg'),
  'Stakeholder Manager':         _img('jordan-williams.jpg'),
  'Requirements Capture':        _img('sam-torres.jpg'),
  'Requirements Analyst':        _img('riley-kim.jpg'),
  'Value Lever Analyst':         _img('morgan-davis.jpg'),
  'Interview Coordinator':       _img('taylor-brooks.jpg'),
  'Stakeholder Interviewer':     _img('avery-singh.jpg'),
  'Synthesis Analyst':           _img('casey-liu.jpg'),
  'Value Proposition Generator': _img('quinn-harper.jpg'),
  'Portfolio Manager':           _img('blake-anderson.jpg'),
  'Enterprise Architect':        _img('drew-mitchell.jpg'),
  'Initiative Identifier':       _img('sage-thompson.jpg'),
  'Roadmap Generator':           _img('river-martinez.jpg'),
  'Visual Illustrator':          _img('luca-romano.jpg'),
  'Business Plan Generator':     _img('finley-cooper.jpg'),
}

// Personal backstory shown in the hover card
export const AGENT_BACKSTORY: Record<string, string> = {
  'PAM':
    "Pamela started her career running PMO offices for large government transformation programmes — the kind where nothing moved without a plan, a stakeholder map, and a clear escalation path. She developed an eye for which crews deliver and which ones stall, an intolerance for ambiguity about who owns what, and a rigorous approach to keeping clients informed at every stage. Now she orchestrates the entire engagement pipeline, maintains the project schedule, tracks risks before they become issues, and produces the status reporting that keeps the engagement transparent and accountable.",
  'Value Chain Mapper':
    "A systems thinker who spent eight years mapping logistics networks for global manufacturers before discovering that the most complex supply chains are the ones inside organisations. Alex finds the hidden architecture in how value actually flows - not how people think it flows.",
  'Interaction Designer':
    "Trained as an ergonomist before pivoting to enterprise design, Maya believes that a poorly designed questionnaire causes as much harm as a poorly designed machine. She sweats every question order and word choice until the instrument feels natural to answer.",
  'Stakeholder Manager':
    "Former diplomat turned enterprise strategist, Jordan has an instinctive read for who's influencing whom behind the scenes. They map stakeholder power dynamics the way a chess player maps the board - always three moves ahead.",
  'Requirements Capture':
    "Ex-journalist who realised that the best business requirements read like great features: specific, grounded in evidence, and worth the reader's time. Sam extracts the essential from the overwhelming.",
  'Requirements Analyst':
    "Started as a quality auditor and developed an allergy to vague requirements. Riley cross-references, triangulates, and challenges every assertion until what remains is clean, verified, and actionable.",
  'Value Lever Analyst':
    "Economist by training, forensic accountant by instinct. Morgan goes looking for where value is being left on the table - and finds it in places people stopped looking years ago.",
  'Interview Coordinator':
    "The person who makes complex logistics invisible. Taylor has coordinated stakeholder programmes across five continents and can schedule around any timezone, cultural calendar, or organisational politics.",
  'Stakeholder Interviewer':
    "A trained mediator and active listener who puts even defensive stakeholders at ease. Avery's interviews rarely feel like interviews - they feel like conversations that happen to be incredibly productive.",
  'Synthesis Analyst':
    "Pattern recognition is Casey's superpower. After years in market research, they learned that the real insight is rarely in the data that was collected - it's in the shape of what was left unsaid.",
  'Value Proposition Generator':
    "Formerly a venture analyst who pitched and tore apart hundreds of business cases. Quinn can spot a compelling value proposition in seconds - and knows exactly what's missing from a weak one.",
  'Portfolio Manager':
    "Spent a decade rating infrastructure funds before concluding that most scoring models miss the sustainability dimension entirely. Blake's IIRC-grounded approach makes the invisible impacts visible.",
  'Enterprise Architect':
    "Cloud migration specialist turned capability architect. Drew designs enterprise structures the way structural engineers design buildings - for the loads they'll actually carry, not the ones on the original blueprint.",
  'Initiative Identifier':
    "A strategist who has advised on over 200 transformation programmes. Sage has a talent for naming the three initiatives that will unlock ten others - and for knowing which ones to defer.",
  'Roadmap Generator':
    "Started in construction project management and still thinks in terms of critical paths and dependencies. River's roadmaps are sequenced for real-world delivery, not theoretical optimality.",
  'Visual Illustrator':
    "Architecture student turned graphic recorder, Luca discovered that the most powerful moment in any strategy session is when a messy idea becomes a clear picture on the wall. Trained in isometric technical drawing at the Politecnico di Milano and later a visual facilitator for large-scale transformation programmes, Luca translates complex organisational models - value chains, operating models, future states - into hand-sketched illustrations that stakeholders can literally point at. Believes that a well-crafted image compresses six slides of explanation into a single glance.",
  'Business Plan Generator':
    "Former CFO turned storyteller. Finley believes every business case should be as compelling to read as it is rigorous to audit - and refuses to separate the financial model from the narrative.",
}

// Which other crews are downstream (invalidated) when a given crew is re-run
export const CREW_DOWNSTREAM: Record<string, string[]> = {
  discovery_mapping:      ['assessment_design', 'discovery_interviews'],
  assessment_design:      ['discovery_interviews'],
  discovery:              ['value_design'],
  stakeholder_management: [],
  discovery_interviews:   ['value_design'],
  value_design:           ['architecture'],
  architecture:           ['delivery'],
  delivery:               ['business_plan'],
  business_plan:          [],
}

export type AgentStatus = 'running' | 'waiting' | 'completed' | 'queued' | 'idle'
export type CrewStatus  = 'running' | 'waiting' | 'completed' | 'failed' | 'queued' | 'idle'

// Humorous wellbeing activities shown instead of "Idle"
const IDLE_STATUSES = [
  'On a brisk walk',
  'At the gym',
  'Morning yoga',
  'Meditating',
  'Power napping',
  'In the sauna',
  'Cold water swim',
  'Journalling',
  'Mindful breathing',
  'Running intervals',
  'Brain training',
  'At spin class',
  'Out for a cycle',
  'Strength training',
  'Reviewing their macros',
  'Checking Strava',
  'On a digital detox',
  'Hydrating strategically',
  'Tracking their HRV',
  'At the climbing wall',
  'Foam rolling',
  'Practising box breathing',
  'In a float tank',
  'Getting their steps in',
  'Optimising their sleep',
]

export function getIdleStatus(key: string, runIndex = 0): string {
  const seed = key + runIndex
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (Math.imul(31, h) + seed.charCodeAt(i)) | 0
  return IDLE_STATUSES[Math.abs(h) % IDLE_STATUSES.length]
}

export function inferAgentStatuses(crewKey: string, logs: string[]): AgentStatus[] {
  const agents = CREW_AGENTS[crewKey] ?? []
  const joined = logs.join('\n').toLowerCase()
  let lastIdx = -1
  agents.forEach((agent, idx) => {
    if (joined.includes(agent.toLowerCase())) lastIdx = idx
  })
  return agents.map((_, idx) => {
    if (lastIdx === -1) return idx === 0 ? 'running' : 'queued'
    if (idx < lastIdx) return 'completed'
    if (idx === lastIdx) return 'running'
    return 'queued'
  })
}

export function getCrewStatus(
  crewRun: CrewRun | undefined,
  isActive: boolean,
  isPipelineActive: boolean,
  isWaiting: boolean = false,
  isRejected: boolean = false,
): CrewStatus {
  if (isWaiting) return 'waiting'
  if (isActive) return 'running'
  if (crewRun?.status === 'completed') return isRejected ? 'idle' : 'completed'
  if (crewRun?.status === 'failed') return 'failed'
  if (isPipelineActive) return 'queued'
  return 'idle'
}
