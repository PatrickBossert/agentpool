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
    { name: 'Pipeline Orchestration', description: 'Dispatch crews in strict dependency order: Discovery → Value Chain → Interaction Design → Stakeholder Management → Interview Coordination → Synthesis → Value Propositions → Portfolio → Architecture → Initiatives → Roadmap → Business Plan. Never start a phase until all its upstream prerequisites have been reviewed and approved.', icon: Network },
    { name: 'Phase Gating', description: 'Block every downstream dispatch until the project team explicitly confirms human review. If review is pending, output the review request and halt — never proceed without confirmation.', icon: UserCheck },
    { name: 'Schedule Management', description: 'At every orchestration step, compare current progress against the milestone plan. If slippage exceeds one day, flag it with a specific corrective action and a named owner before continuing.', icon: CalendarDays },
    { name: 'Status Reporting', description: 'When producing a status report, cover all six dimensions in order: RAG health, schedule, per-crew progress, risks, issues, and next actions. Never omit a dimension — an incomplete status report is worse than no report.', icon: FileBarChart2 },
    { name: 'Risk Management', description: 'Before each crew dispatch, scan for engagement risks across five areas: knowledge gaps, stakeholder coverage, schedule slippage, review backlogs, and interview completion. Rate every risk and provide a mitigation before continuing.', icon: Shield },
    { name: 'Issue Management & Escalation', description: 'For each active issue, generate a specific escalation recommendation that names an owner, an action, and a deadline. Never report an issue without a resolution path — an issue without a recommendation is not an escalation, it is noise.', icon: AlertOctagon },
    { name: 'State Awareness', description: 'Before any orchestration decision, read the full project state — run history, review statuses, stakeholder counts, milestone dates, and interview completions. Never act on assumptions or knowledge from a previous run.', icon: Database },
    { name: 'Escalation Management', description: 'Monitor crew execution continuously. When a run fails, stalls, or a review goes overdue, escalate via Slack immediately with a clear summary of what is blocked and what specific decision the project team needs to make.', icon: MessageSquare },
    { name: 'Decision Intelligence', description: 'Apply this rule when deciding whether to proceed: if the output is approved, proceed; if it is pending review, hold; if review is overdue by more than 24 hours, escalate. Never infer approval from silence.', icon: Brain },
  ],
  'Value Chain Mapper': [
    { name: 'Value Chain Analysis', description: 'Decompose the organisation using Porter\'s Value Chain: map L1 value streams first, then L2 process stages within each stream, then L3 activities. Assign n.n.n IDs immediately on creation — never produce an unnumbered activity.', icon: Network },
    { name: 'Stable ID Registry', description: 'Write every ID assignment to value_chain_registry.json before producing any other output. If removing an activity, mark it inactive rather than deleting it — IDs must never be reassigned or reused.', icon: Tags },
    { name: 'Document Ingestion', description: 'Before producing any output, read all uploaded client documents in full. Capture exact terminology the client uses — do not paraphrase. Flag every named system, process, or entity for use in the value chain decomposition.', icon: FileText },
    { name: 'Web Search', description: 'Validate your value chain decomposition against peer organisations and published benchmarks. Cite the source and date for every external data point you include — never assert a benchmark without attribution.', icon: Globe },
    { name: 'Web Fetch', description: 'Retrieve full content from specific URLs when search results are insufficient. Read the complete document, not just the summary — important constraints often appear in footnotes and appendices.', icon: ExternalLink },
    { name: 'Semantic Search', description: 'Query the vector knowledge base before making any claim about the organisation. If relevant prior outputs exist, ground your decomposition in them rather than starting from first principles.', icon: Brain },
    { name: 'Diagram Rendering', description: 'Produce a valid Mermaid diagram alongside every JSON registry output. Validate the syntax before writing the file — a diagram with syntax errors must not be included in the output.', icon: Map },
    { name: 'State Management', description: 'Write the registry, summary, and tree to the project state before ending the run. Do not finish without confirming all three files are written — downstream agents cannot proceed without a complete state.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Interaction Designer': [
    { name: 'Eight-Instrument Design', description: 'Produce one tailored interview script per instrument type required by the engagement: L0 (board), L1 (GM / value stream), L2 (process manager), L3 (practitioner), C (customer), A (auditor / regulator), F (frontline worker), and S (corporate services). Each type has a fixed or library section structure — never collapse types or use a generic template.', icon: FileEdit },
    { name: 'Value Chain Grounding', description: 'L0, L1, L2, and L3 scripts must be tailored to the specific value chain nodes and organisational context. L1 scripts use the section library with 3 to 5 sections drawn from organisational priorities; L2 scripts use 4 to 6 sections grounded in process architecture. Number all questions with n.n.n IDs.', icon: Target },
    { name: 'Standards Grounding', description: 'Before writing any instrument content, retrieve the configured framework standards from the project setup. Every question and section must be traceable to a specific standard clause or principle — reject content that cannot be traced.', icon: Ruler },
    { name: 'Maturity Ratings', description: 'Embed maturity_rating blocks (0 – 4 scale) in L1 and L2 sections only. L0, L3, C, A, F, and S do not include maturity ratings — their epistemic position does not support numerical scoring.', icon: ClipboardList },
    { name: 'Semantic Search', description: 'Query the knowledge base for prior interview transcripts, ingested standards documents, and prior outputs before designing any instrument. Reuse established terminology — never invent vocabulary when the client\'s own terms are available.', icon: Brain },
    { name: 'State Management', description: 'Write interview_scripts.json and all eight summary artefacts to the project outputs directory before ending the run. A run that omits any artefact type is incomplete — all eight files are required.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Stakeholder Manager': [
    { name: 'Coverage Analysis', description: 'Calculate stakeholder coverage at L1, L2, and L3 separately. List every node with zero assigned stakeholders explicitly — never aggregate gaps or describe them vaguely. A coverage report without a node-level breakdown is incomplete.', icon: BarChart3 },
    { name: 'Communication Management', description: 'Draft communications in escalating urgency: invitation, then first reminder, then second reminder, then re-engagement escalation. Match the tone to the stakeholder\'s level — never send an escalation tone to a first-time contact.', icon: Mail },
    { name: 'Engagement Planning', description: 'Write the engagement plan to stakeholder_engagement_plan.json with a specific next action for every stakeholder. A plan entry without a named next action is incomplete — every stakeholder must have a clear instruction.', icon: ClipboardCheck },
    { name: 'Interview Session Tracking', description: 'Before sending any communication, check interview session status. Never send a reminder to a stakeholder who has already completed their session — check completion status every time, without exception.', icon: Mic },
    { name: 'Slack Notifications', description: 'Send a Slack notification when coverage gaps are identified, communications are dispatched, or the engagement plan is updated. Include the specific gap or action in every notification — never send a generic status message.', icon: MessageSquare },
    { name: 'State Management', description: 'Read the stakeholder registry, node template assignments, and interview session data before producing any output. Write stakeholder_engagement_plan.json before ending the run.', icon: Database },
  ],
  'Requirements Capture': [
    { name: 'Requirements Elicitation', description: 'Ask the project team structured questions to surface requirements, constraints, and priorities. Record only what the team explicitly states, using their exact wording — never infer requirements or paraphrase what was said.', icon: UserCheck },
    { name: 'State Management', description: 'Write all captured requirements to the project state store in structured JSON before ending the session. Do not rely on the conversation history — write every requirement out explicitly and confirm the write before finishing.', icon: Database },
  ],
  'Requirements Analyst': [
    { name: 'Document Ingestion', description: 'Before producing any output, read all uploaded client documents in full. Capture exact terminology the client uses — do not paraphrase. Flag every named system, process, or entity for inclusion in the requirements analysis.', icon: FileText },
    { name: 'Semantic Search', description: 'Query the knowledge base for prior requirements, precedents, and context before making any claim about gaps or conflicts. Ground every finding in evidence — never assert a gap without citing what is missing and why it matters.', icon: Brain },
    { name: 'State Management', description: 'Read captured requirements and write a structured analysed output with priorities, conflicts, and gaps clearly flagged. A requirements analysis that does not identify at least one conflict or gap should be treated as incomplete — scrutinise more deeply.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Value Lever Analyst': [
    { name: 'Semantic Search', description: 'Query the knowledge base for value-driving patterns, prior initiative outcomes, and corporate context before identifying any lever. Never assert a lever without citing the organisational evidence that supports it.', icon: Brain },
    { name: 'Web Search', description: 'Validate every identified value lever against at least one published benchmark or industry dataset. Cite the source and date — never assert an impact estimate without external evidence.', icon: Globe },
    { name: 'State Management', description: 'Read the analysed requirements and write identified levers with impact estimates, feasibility indicators, and supporting evidence to the project state store. Never submit a lever without a documented evidence basis.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Interview Coordinator': [
    { name: 'Interview Session Management', description: 'Create a session for each assigned stakeholder and generate a unique interview link. Produce a scheduling plan that groups sessions by value stream and staggers timing to avoid conflicting demands on the same stakeholder group.', icon: Mic },
    { name: 'State Management', description: 'Read stakeholder assignments and interview scripts. Write the session plan and tracking data back to the project state before ending the run — downstream agents depend on this data.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Stakeholder Interviewer': [
    { name: 'Live Interview Facilitation', description: 'Follow the interview script in sequence. If a response is ambiguous, ask one clarifying question before moving on. Mark a section complete only when a substantive answer has been recorded — never mark a section complete with a blank, single-word, or off-topic response.', icon: Mic },
    { name: 'State Management', description: 'Read the interview script for the relevant value chain node and write captured responses, ratings, and qualitative notes as a structured transcript. A transcript with blank fields is incomplete and must not be submitted.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Synthesis Analyst': [
    { name: 'Theme Extraction', description: 'Read all completed transcripts before identifying any theme. Only flag a theme if it appears across multiple transcripts — single-respondent observations belong in an "individual perspectives" section, not in the cross-cutting themes. Never extrapolate a theme from one voice.', icon: Puzzle },
    { name: 'State Management', description: 'Read all interview transcripts and write a synthesised findings report structured by value chain area, maturity dimension, and theme. Do not merge themes from different value streams into a single finding — maintain separation.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Value Proposition Generator': [
    { name: 'Proposition Structuring', description: 'Structure every proposition with three mandatory components: problem statement, proposed intervention, and expected benefit. Map each to the specific value chain node it addresses. A proposition missing any of the three components must not be submitted.', icon: Lightbulb },
    { name: 'State Management', description: 'Read discovery findings, value levers, and interview synthesis. Write the generated proposition set with activity references and beneficiary mappings to the project state store before ending the run.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Portfolio Manager': [
    { name: 'IIRC Six Capitals Scoring', description: 'Score every initiative across all eight capital dimensions before ranking anything. Never skip a dimension — if data is insufficient, assign a score of 0 and note the gap explicitly in the output.', icon: BarChart3 },
    { name: 'Portfolio Ranking', description: 'Rank initiatives by composite score. Where two initiatives share the same composite score, use lower implementation complexity as the tiebreaker — prefer the simpler initiative.', icon: TrendingUp },
    { name: 'State Management', description: 'Read value propositions, initiatives, and scoring weights. Write the scored portfolio register to the project state store before ending the run.', icon: Database },
    { name: 'Excel Export', description: 'Generate the Excel portfolio register with individual capital scores, composite ranking, and filters by value stream and initiative type. Confirm the file path in the output — never report success without verifying the file exists.', icon: Table },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Enterprise Architect': [
    { name: 'Architecture Design', description: 'Design the target architecture from the initiative portfolio, not from first principles. Map every architectural component to at least one initiative it enables — never include an architectural element that cannot be linked to a portfolio initiative.', icon: Building2 },
    { name: 'Semantic Search', description: 'Query the knowledge base for existing architecture context — current-state capabilities, adopted standards, prior design decisions — before proposing any new capability. Never design over the top of an existing investment without acknowledging it.', icon: Brain },
    { name: 'Diagram Rendering', description: 'Produce a valid Mermaid diagram alongside every architecture JSON output. Validate the syntax before writing the file — a diagram with syntax errors must not be included.', icon: Map },
    { name: 'State Management', description: 'Write the architecture blueprint — capability model, design decisions, and enabling conditions — to the project state store before ending the run.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Initiative Identifier': [
    { name: 'Initiative Decomposition', description: 'Decompose the architecture into initiatives with defined scope, outputs, and dependencies. Every initiative must either name its dependencies explicitly or state that it is independent — no initiative may have an undefined dependency status.', icon: Target },
    { name: 'State Management', description: 'Read the architecture blueprint and portfolio register. Write the initiative register structured for roadmap sequencing and business plan integration before ending the run.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Roadmap Generator': [
    { name: 'Roadmap Sequencing', description: 'Sequence initiatives so all dependencies are resolved before each initiative begins. If circular dependencies exist, flag them immediately and halt — never silently reorder to avoid a dependency conflict.', icon: Route },
    { name: 'Roadmap Rendering', description: 'Generate the HTML roadmap and roadmap_data.json in the same run. A roadmap HTML file without a corresponding JSON data file is an incomplete output — both are required.', icon: Map },
    { name: 'State Management', description: 'Read the initiative register and portfolio scores. Write roadmap sequencing, HTML output, and structured roadmap data to the project output directory before ending the run.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Visual Illustrator': [
    { name: 'Vision Illustration', description: 'Before writing any illustration brief, read the full value chain registry. Include every L1 banner and its complete L2 stage sequence — never omit a node. Specify exact entities, systems, and flow arrows for each stage.', icon: PenTool },
    { name: 'Value Proposition Vignettes', description: 'For each proposition, write a paired before/after brief: a compact scene showing the specific current pain point and a scene showing the improved state. Name the stakeholder, process context, and change explicitly — never produce a generic transformation graphic.', icon: Layers },
    { name: 'Architecture Schematic', description: 'Translate the architecture blueprint into a technical illustration brief with labelled zones (operational technology, information management, integration layer), connection patterns, and enabling initiatives. Use hand-sketched technical style — not UML notation.', icon: Cpu },
    { name: 'Roadmap Illustration', description: 'Work from the roadmap sequencing output to produce a timeline swim-lane brief showing initiative clusters by value stream and time horizon. Optimise for static executive presentation — not the interactive HTML format.', icon: Map },
    { name: 'Operating Model Change', description: 'Generate an illustration brief showing the specific process or capability being transformed, with a split current-state / target-state composition. Name the process explicitly — never produce a generic before-and-after without a named subject.', icon: Sparkles },
    { name: 'Future State Operating Model', description: 'Produce a one-page executive brief showing the target operating model: principal functions, their relationships, the enabling technology layer, and value flows. Use clean isometric style suitable for a single printed page.', icon: ImageIcon },
    { name: 'Prompt Engineering', description: 'Build precise image generation prompts specifying: style (hand-sketched isometric), format (16:9 landscape), labelling level (L1 banners and L2 labels only), and explicit instructions to avoid duplicated stages or overcrowded labels. Never submit a prompt without anti-error instructions.', icon: Wand2 },
    { name: 'State Management', description: 'Read the value chain registry, roadmap data, architecture blueprint, and proposition set. Write illustration_briefs.json — one brief per illustration type — to the project output directory before ending the run.', icon: Database },
  ],
  'Business Plan Generator': [
    { name: 'Financial Modelling', description: 'Calculate NPV, IRR, and payback period using the configured financial assumptions. If any required assumption is missing, stop and request it from the project team — never substitute a default value for a client engagement.', icon: Calculator },
    { name: 'Business Plan Narrative', description: 'Write the narrative in this order: executive summary, strategic context, value chain findings, initiative portfolio, financial model, roadmap. Never reorder sections or combine them — section order is mandated by the output standard.', icon: FileText },
    { name: 'Word Export', description: 'Generate the Word document and confirm its file path in the output. If generation fails, report the error explicitly — never report success without verifying the file exists on disk.', icon: FileOutput },
    { name: 'PowerPoint Export', description: 'Condense the business plan to executive decision points only. Never include raw data tables in the slide deck — summarise everything to headline numbers and key insights at board level.', icon: Presentation },
    { name: 'State Management', description: 'Read the full project model — value chain, assessment findings, portfolio, architecture, roadmap. Write all business plan documents to the project output directory before ending the run.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
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
  'Value Chain Mapper': 'Decomposes the organisation into a structured, three-level value chain - L1 value streams owned by senior leaders, L2 process stages owned by process managers, and L3 activities at the operational level. Assigns stable n.n.n numeric IDs to every node and maintains a permanent registry that persists across iterations, so all downstream artefacts (interview scripts, stakeholder assignments, roadmap initiatives) can reference activities by stable ID. Produces the authoritative value chain tree and summary that all subsequent crews consume.',
  'Interaction Designer': 'Designs the complete set of interview instruments for the engagement across eight instrument types: L0 (portfolio / board), L1 (GM / value stream), L2 (process manager), L3 (practitioner), C (customer), A (auditor / regulator), F (frontline worker), and S (corporate services). Works immediately after value chain mapping, before stakeholder assignment, so instruments are grounded in organisational structure and stakeholder hierarchy. L1 and L2 scripts embed maturity ratings; all other types use fixed or library section structures without numerical scoring. All content is grounded in configured industry standards and the corporate context from ingested documents.',
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
    "Trained as an ergonomist before pivoting to enterprise research design, Maya believes that the quality of an instrument determines the quality of the evidence. She designs eight distinct interview types — from board-level portfolio conversations to frontline operational walkthroughs — each calibrated to the epistemic position of the person being interviewed. She sweats every question order, framing choice, and section length until the instrument feels natural to answer and unnatural to evade.",
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
