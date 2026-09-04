// ui/src/components/agentStatus.ts
import type { LucideIcon } from 'lucide-react'
import {
  Network, Tags, FileText, Globe, ExternalLink, Brain, Map, Database, UserCheck,
  FileEdit, ClipboardList, Target, Ruler, BarChart3, Mail, ClipboardCheck,
  Mic, MessageSquare, Puzzle, Lightbulb, TrendingUp, Table,
  Route, Calculator, FileOutput, Presentation, Quote,
  PenTool, Layers, Cpu, Sparkles, Wand2, ImageIcon,
  CalendarDays, FileBarChart2, Shield, AlertOctagon,
} from 'lucide-react'
import type { CrewRun } from '../types'

// Display order. CREW_DEPENDENCIES in api/services/crew_graph.py is what actually gates a
// run; this is what the board shows, and the two must agree - an order contradicting the
// graph shows a crew as next when it cannot run, and the reader acts on it.
//
// Jordan was shown before Maya while the graph required Maya first, which is the drift a
// test now catches.
export const CREW_ORDER = [
  'discovery_mapping',
  'assessment_design',
  'stakeholder_management',
  'discovery_interviews',
  'value_design',
  'capabilities',
  'requirements',
  'delivery',
  'business_plan',
] as const

// Snake-case agent names per crew — mirrors api/services/run_service.py _CREW_AGENT_NAMES
export const CREW_AGENT_NAMES: Record<string, string[]> = {
  discovery_mapping:      ['value_chain_mapper', 'value_lever_analyst'],
  assessment_design:      ['interaction_designer'],
  requirements:              ['requirements_capture', 'requirements_analyst'],
  stakeholder_management: ['stakeholder_manager'],
  discovery_interviews:   ['interview_coordinator', 'stakeholder_interviewer', 'second_interviewer', 'synthesis_analyst'],
  value_design:           ['value_proposition_generator', 'portfolio_manager'],
  capabilities:           ['enterprise_architect', 'initiative_identifier'],
  delivery:               ['roadmap_generator'],
  business_plan:          ['business_plan_generator', 'visual_illustrator'],
}

export type CrewName = (typeof CREW_ORDER)[number]

// What each crew is called on screen. The only copy in the front end: Dashboard.tsx and
// ReviewDialog.tsx each carried their own, and all three disagreed - `discovery_mapping` was
// shown as "Value Chain Mapper" (the agent, not the crew) in one, `capabilities` as
// "Architecture" in another, and `delivery` as "Delivery Planning" in both.
//
// CREW_LABEL in agents/identity.py is the source of record, and
// test_the_frontend_and_the_backend_agree_about_crew_labels holds this map against it.
//
// PAM is the exception and is excluded from that check: it is a card on the board and an
// orchestrator, not a crew anything dispatches - the same exclusion CREW_AGENTS already
// carries below.
export const CREW_LABELS: Record<string, string> = {
  PAM:                    'PMO',
  discovery_mapping:      'Value Chain Mapping',
  assessment_design:      'Assessment Design',
  requirements:              'Requirements',
  stakeholder_management: 'Stakeholder Management',
  discovery_interviews:   'Discovery Interviews',
  value_design:           'Value Design',
  capabilities:           'Capabilities',
  delivery:               'Delivery',
  business_plan:          'Business Plan',
}

export const CREW_AGENTS: Record<string, string[]> = {
  PAM:                   ['PAM'],
  discovery_mapping:     ['Value Chain Mapper', 'Value Lever Analyst'],
  assessment_design:     ['Interaction Designer'],
  requirements: [
    'Requirements Capture',
    'Requirements Analyst',
  ],
  stakeholder_management: ['Stakeholder Manager'],
  discovery_interviews: [
    'Interview Coordinator',
    'Stakeholder Interviewer',
    'Second Interviewer',
    'Synthesis Analyst',
  ],
  value_design:  ['Value Proposition Generator', 'Portfolio Manager'],
  capabilities:  ['Enterprise Architect', 'Initiative Identifier'],
  delivery:      ['Roadmap Generator'],
  business_plan: ['Business Plan Generator', 'Visual Illustrator'],
}

export interface AgentSkill {
  name: string
  description: string
  icon: LucideIcon
}

// The interviewers' capabilities, held once and shown for both of them.
//
// Avery and Laura run one brief between them - agents/discovery/stakeholder_interviewer.py is
// the single declaration of it - so a second list here would be a second description of the
// same job, free to drift from the first with nothing comparing them.
const INTERVIEWER_SKILLS: AgentSkill[] = [
  { name: 'Live Interview Facilitation', description: 'Follow the interview script in sequence. If a response is ambiguous, ask one clarifying question before moving on. Mark a section complete only when a substantive answer has been recorded — never mark a section complete with a blank, single-word, or off-topic response.', icon: Mic },
  { name: 'State Management', description: 'Read the interview script for the relevant value chain node and write captured responses, ratings, and qualitative notes as a structured transcript. A transcript with blank fields is incomplete and must not be submitted.', icon: Database },
  { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
]

// What the two interviewers do, held once for the same reason as the skills above.
const INTERVIEWER_ROLE =
  'Conducts voice and text interviews with assigned stakeholders using the pre-designed interview scripts for their value chain node. Manages session state throughout the lifecycle - launching, recording, tracking progress through script sections, and marking completion. Produces a complete, structured transcript for each session that the Synthesis Analyst can work from directly.'

export const AGENT_SKILLS: Record<string, AgentSkill[]> = {
  'PAM': [
    { name: 'Pipeline Orchestration', description: 'Dispatch crews in strict dependency order: Discovery → Value Chain → Interaction Design → Stakeholder Management → Interview Coordination → Synthesis → Value Propositions → Portfolio → Architecture → Initiatives → Roadmap → Business Plan. Never start a phase until all its upstream prerequisites have been reviewed and approved.', icon: Network },
    { name: 'Phase Gating', description: 'Block every downstream dispatch until the project team explicitly confirms human review. If review is pending, output the review request and halt — never proceed without confirmation.', icon: UserCheck },
    { name: 'Schedule Management', description: 'At every orchestration step, compare current progress against the milestone plan. If slippage exceeds one day, flag it with a specific corrective action and a named owner before continuing.', icon: CalendarDays },
    { name: 'Status Reporting', description: 'When producing a status report, cover all six dimensions in order: RAG health, schedule, per-crew progress, risks, issues, and next actions. Never omit a dimension — an incomplete status report is worse than no report.', icon: FileBarChart2 },
    { name: 'Risk Management', description: 'Before each crew dispatch, scan for engagement risks across five areas: knowledge gaps, stakeholder coverage, schedule slippage, review backlogs, and interview completion. Rate every risk and provide a mitigation before continuing.', icon: Shield },
    { name: 'Issue Management & Escalation', description: 'For each active issue, generate a specific escalation recommendation that names an owner, an action, and a deadline. Never report an issue without a resolution path — an issue without a recommendation is not an escalation, it is noise.', icon: AlertOctagon },
    { name: 'State Awareness', description: 'Before any orchestration decision, read the full project state — run history, review statuses, stakeholder counts, milestone dates, and interview completions. Never act on assumptions or knowledge from a previous run.', icon: Database },
    { name: 'Escalation Management', description: 'Monitor crew execution continuously. When a run fails, stalls, or a review goes overdue, escalate immediately with a clear summary of what is blocked and what specific decision the project team needs to make.', icon: MessageSquare },
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
    { name: 'State Management', description: 'Read the stakeholder registry, node template assignments, and interview session data before producing any output. Write stakeholder_engagement_plan.json before ending the run.', icon: Database },
  ],
  'Requirements Capture': [
    { name: 'Initiative-Scoped Enumeration', description: 'Work through every initiative in the register across all six requirement dimensions - data, people, process, decision flow, application, and technology. An initiative absent from the output reads as having no requirements rather than as one you did not reach, so cover every one.', icon: UserCheck },
    { name: 'Explicit Nil Returns', description: 'Where a dimension genuinely carries no requirement for an initiative, record it as "none identified" with a reason. Never omit it silently — a silent omission cannot be told apart from an oversight.', icon: ClipboardCheck },
    { name: 'State Management', description: 'Read the initiative register and the as-is capability register before writing anything, so every requirement is stated against what already exists. Write the captured requirements to the project state store in structured JSON and confirm the write before finishing.', icon: Database },
  ],
  'Requirements Analyst': [
    { name: 'Document Ingestion', description: 'Before producing any output, read all uploaded client documents in full. Capture exact terminology the client uses — do not paraphrase. Flag every named system, process, or entity for inclusion in the requirements analysis.', icon: FileText },
    { name: 'Semantic Search', description: 'Query the knowledge base for prior requirements, precedents, and context before making any claim about gaps or conflicts. Ground every finding in evidence — never assert a gap without citing what is missing and why it matters.', icon: Brain },
    { name: 'State Management', description: 'Read captured requirements and write a structured analysed output with priorities, conflicts, and gaps clearly flagged. A requirements analysis that does not identify at least one conflict or gap should be treated as incomplete — scrutinise more deeply.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Value Lever Analyst': [
    { name: 'Document Analysis', description: 'Read the client\'s own strategy, performance, and governance material to find the levers and KPIs the organisation already uses. Name the document every lever came from — a lever with no named source must not be submitted.', icon: FileText },
    { name: 'Hypothesis Framing', description: 'State every lever as a hypothesis the interviews will test, never as an established finding. Levers read out of documents are what the organisation claims to care about; presenting one as settled removes the interviews\' ability to contradict it.', icon: Lightbulb },
    { name: 'Web Search', description: 'Validate every identified value lever against at least one published benchmark or industry dataset. Cite the source and date — never assert an impact estimate without external evidence.', icon: Globe },
    { name: 'State Management', description: 'Read the value chain model so each lever names the activities it bears on, and write the levers with their hypotheses, KPIs, and sources to the project state store. Where the model is not yet written, leave the activity references empty rather than inventing IDs.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Interview Coordinator': [
    { name: 'Interview Session Management', description: 'Create a session for each assigned stakeholder and generate a unique interview link. Produce a scheduling plan that groups sessions by value stream and staggers timing to avoid conflicting demands on the same stakeholder group.', icon: Mic },
    { name: 'State Management', description: 'Read stakeholder assignments and interview scripts. Write the session plan and tracking data back to the project state before ending the run — downstream agents depend on this data.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Stakeholder Interviewer': INTERVIEWER_SKILLS,
  'Second Interviewer': INTERVIEWER_SKILLS,
  'Synthesis Analyst': [
    { name: 'Theme Extraction', description: 'Read all completed transcripts before identifying any theme. Only flag a theme if it appears across multiple transcripts — single-respondent observations belong in an "individual perspectives" section, not in the cross-cutting themes. Never extrapolate a theme from one voice.', icon: Puzzle },
    { name: 'Horizontal and Vertical Separation', description: 'Classify every theme as horizontal - running across the value chain, where digital transformation could improve efficiency or effectiveness - or vertical, running within a discipline such as governance, data, or a support service, where maturity could be raised. Never leave a theme unclassified.', icon: Route },
    { name: 'Evidence Citation', description: 'Attach at least two evidence entries from different stakeholders to every theme, each naming the person and the node they spoke about. A theme with one voice behind it is an individual perspective, and one with no evidence must not be submitted.', icon: Quote },
    { name: 'State Management', description: 'Read all interview transcripts and write activity insights and the classified theme set. Do not merge themes from different value streams into a single finding — maintain separation.', icon: Database },
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
    { name: 'As-Is Capability Compilation', description: 'Compile the capabilities the organisation has today across the data, technology, and organisation layers. Describe what exists, not what should exist — the uplift initiatives are derived from the gap between this register and each value proposition, and a current state written aspirationally makes that gap unmeasurable.', icon: Layers },
    { name: 'Document Ingestion', description: 'Read the architecture papers, org charts, system inventories, and technology registers the client has supplied. Capture the exact names the organisation uses for its own systems and functions — never substitute a generic industry term for a named one.', icon: FileText },
    { name: 'Semantic Search', description: 'Query the knowledge base for existing architecture context — adopted standards, prior design decisions, in-flight investments — before recording any capability. Never record a capability as absent without checking what is already in place.', icon: Brain },
    { name: 'State Management', description: 'Write the as-is capability register — capabilities, the layer each sits in, and the evidence for each — to the project state store before ending the run.', icon: Database },
    { name: 'Human Review Gate', description: 'At the end of every work phase, pause and request human review. Write a clear summary of what was produced and what the reviewer needs to validate. Do not allow downstream crews to proceed until review is confirmed.', icon: UserCheck },
  ],
  'Initiative Identifier': [
    { name: 'Gap Analysis', description: 'Derive each initiative from the gap between the as-is capability register and an approved value proposition - the "we need to be able to..." statement that closes it. Never propose an initiative that cannot be traced to a specific proposition and a specific missing capability.', icon: Target },
    { name: 'Initiative Decomposition', description: 'Give every initiative a defined scope, outputs, and dependencies. Each must either name its dependencies explicitly or state that it is independent — no initiative may have an undefined dependency status.', icon: Puzzle },
    { name: 'State Management', description: 'Read the as-is capability register, the value propositions, and the portfolio register. Write the initiative register structured for roadmap sequencing and business plan integration before ending the run.', icon: Database },
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
  'Stakeholder Manager': 'Actively manages stakeholder engagement across the entire interview programme. Analyses stakeholder-to-node assignment coverage at L1, L2, and L3 levels; identifies gaps where nodes lack adequate representation; and drafts a progressive sequence of communications - invitation, first reminder, second reminder, and re-engagement - calibrated to stakeholder seniority and urgency. Tracks interview session completion status to avoid contacting stakeholders who have already participated. Maintains the stakeholder_engagement_plan.json as the authoritative record of programme health and records where the project team must act.',
  'Requirements Capture': 'Enumerates what each approved initiative requires across six dimensions - data, people, process, decision flow, application, and technology - stated against the current-state capabilities that already exist. Works from the initiative register rather than an open brief, and records a dimension as "none identified" with a reason rather than omitting it, so a gap in the analysis can be told apart from a gap in the requirement.',
  'Requirements Analyst': 'Analyses the captured requirement set for completeness, consistency, priority, and hidden conflicts. Reads client documents to surface implicit requirements that the direct session may have missed, and queries the knowledge base for related precedents. Produces a structured, prioritised requirement analysis that forms the foundation for value lever identification.',
  'Value Lever Analyst': 'Reads the client\'s own strategy, performance, and governance material to surface the value levers and KPIs the organisation already talks about, and names the value chain activities each one bears on. Runs first, alongside value chain mapping and before the interview instruments are designed, so Maya can design against the measures the organisation itself uses rather than asking cold. Every lever is stated as a hypothesis for the interviews to test, never as an established finding - a lever presented as settled removes the interviews\' ability to contradict it.',
  'Interview Coordinator': 'Plans and activates the stakeholder interview programme. Reads node template assignments and stakeholder lists, creates interview sessions with unique links, and sequences interviews efficiently across the programme timeline. Produces a scheduling plan that coordinates L1 strategic interviews and L2 operational interviews without resource conflicts.',
  'Stakeholder Interviewer': INTERVIEWER_ROLE,
  'Second Interviewer': INTERVIEWER_ROLE,
  'Synthesis Analyst': 'Synthesises all completed interview transcripts into activity-level insights and the themes the evidence supports. Separates horizontal themes - running across the value chain, where digital transformation could improve efficiency or effectiveness - from vertical themes running within a discipline such as governance, data, or a support service, where maturity could be raised. Every theme names the stakeholders whose words evidence it, which is what lets a value proposition be traced back to something a person actually said.',
  'Value Proposition Generator': 'Translates synthesised interview findings and identified value levers into a structured set of value propositions, each with a clear problem statement, proposed intervention, expected benefit, and mapping to the relevant value chain activities and beneficiary groups. Propositions feed directly into the portfolio scoring and architecture design phases.',
  'Portfolio Manager': 'Scores and prioritises the initiative portfolio using the IIRC Integrated Reporting Six Capitals framework. Applies configured weights across eight dimensions to produce a defensible, evidence-based ranking of initiatives. Generates an Excel portfolio register for stakeholder distribution and ensures the investment case is grounded in a transparent, repeatable scoring methodology.',
  'Enterprise Architect': 'Compiles the organisation\'s as-is capabilities from its own documents - architecture papers, org charts, system inventories, and technology registers - across the data, technology, and organisation layers. Describes what exists rather than proposing what should, because the uplift initiatives are derived from the gap between these capabilities and each value proposition, and a current state written aspirationally makes that gap unmeasurable.',
  'Initiative Identifier': 'Derives the uplift initiatives from the gap between the as-is capability register and each approved value proposition - the "we need to be able to..." statements that close it. Each initiative carries defined scope, expected outputs, dependencies, value stream alignment, and an indicative cost band, granular enough for roadmap sequencing and resource planning while remaining coherent enough for executive comprehension.',
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
  'Second Interviewer':          { emoji: '🎙️', gradient: 'from-violet-400 to-indigo-600' },
  'Synthesis Analyst':           { emoji: '🧩', gradient: 'from-purple-400 to-indigo-600' },
  'Value Proposition Generator': { emoji: '💡', gradient: 'from-yellow-400 to-amber-500' },
  'Portfolio Manager':           { emoji: '📊', gradient: 'from-green-400 to-emerald-600' },
  'Enterprise Architect':        { emoji: '🏛️', gradient: 'from-slate-400 to-gray-600' },
  'Initiative Identifier':       { emoji: '🎯', gradient: 'from-red-400 to-rose-600' },
  'Roadmap Generator':           { emoji: '🛣️', gradient: 'from-cyan-400 to-teal-600' },
  'Visual Illustrator':          { emoji: '🎨', gradient: 'from-rose-400 to-pink-600' },
  'Business Plan Generator':     { emoji: '📈', gradient: 'from-lime-400 to-green-600' },
}

// The agent's own name, from whichever form of the name the caller holds.
//
// AGENT_HUMAN_NAME is keyed by display name ('Value Chain Mapper') while agent_outputs
// stores snake_case ('value_chain_mapper'), and PAM is stored as her key in both. Title
// casing alone would leave PAM as "PAM" while every other agent gained a name, so the
// direct lookup comes first.
export function agentDisplayName(agentName: string): string {
  const direct = AGENT_HUMAN_NAME[agentName]
  if (direct) return direct
  const titled = agentName
    .split('_')
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ')
  return AGENT_HUMAN_NAME[titled] ?? titled
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
  'Second Interviewer':          'Laura Nelson',
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

// Seventeen of the eighteen. 'Second Interviewer' is deliberately absent: Laura Nelson has no
// headshot yet, `AgentFace` falls back to her initials on a gradient, and a stand-in borrowed
// from somebody else would put one person's face on two names. `agents/identity.py` records the
// same absence as `image=None`, and the two are held equal by
// tests/test_persona_transcription.py - so this is one line to add when a portrait exists.
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
  'Second Interviewer':
    "Fifteen years in qualitative research, most of them in rooms where the interesting answer came after the polite one. Laura reads a pause the way other people read a sentence, and has a talent for making a stakeholder feel that the half-formed thought they nearly kept to themselves was the most useful thing they said all day.",
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
  requirements:              ['value_design'],
  stakeholder_management: [],
  discovery_interviews:   ['value_design'],
  value_design:           ['capabilities'],
  capabilities:           ['delivery'],
  delivery:               ['business_plan'],
  business_plan:          [],
}

export type AgentStatus = 'running' | 'waiting' | 'completed' | 'queued' | 'idle'
export type CrewStatus  = 'running' | 'waiting' | 'completed' | 'failed' | 'queued' | 'idle'

// Humorous wellbeing activities shown instead of "Idle"
export const IDLE_STATUSES = [
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

function hashSeed(seed: string): number {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (Math.imul(31, h) + seed.charCodeAt(i)) | 0
  return Math.abs(h)
}

export function getIdleStatus(key: string, runIndex = 0): string {
  return IDLE_STATUSES[hashSeed(key + runIndex) % IDLE_STATUSES.length]
}

function gcd(a: number, b: number): number {
  while (b !== 0) [a, b] = [b, a % b]
  return a
}

/**
 * The activity to show for an idle agent at a given rotation.
 *
 * A stride walk rather than seed advancement. Because the stride is coprime with the
 * list length it can never be congruent to zero, so no activity ever follows itself,
 * and the walk visits every activity before revisiting one. Checking for a repeat
 * after the fact would instead need the previously displayed value - which means
 * either storing it or walking the history, and the history grows without bound while
 * the page stays open.
 *
 * At rotation 0 this reduces to getIdleStatus, so a freshly loaded board is unchanged.
 */
export function getRotatedIdleStatus(key: string, runIndex: number, rotation: number): string {
  const n = IDLE_STATUSES.length
  if (n < 2) return IDLE_STATUSES[0]

  const base = hashSeed(key + runIndex) % n
  let stride = 1 + (hashSeed(`${key}${runIndex}:stride`) % (n - 1))
  while (gcd(stride, n) !== 1) stride = (stride % (n - 1)) + 1

  return IDLE_STATUSES[(base + rotation * stride) % n]
}

/**
 * The Ready label, or null when the crew's own status should speak instead.
 *
 * Ready is a resting state, so anything actually happening - or anything broken -
 * outranks it. A running crew that is also ready is simply running.
 */
export function crewStatusLabel(status: AgentStatus | CrewStatus, ready: boolean): string | null {
  if (!ready) return null
  return status === 'idle' ? 'Ready to run' : null
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
