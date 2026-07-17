// ui/src/types.ts

export interface Project {
  id: number
  slug: string
  llm_mode: string
  sector: string
  status: string
}

export interface CrewRun {
  id: number
  project_id: number
  crew_name: string
  status: 'pending' | 'queued' | 'running' | 'completed' | 'failed'
  result_json: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface OrchestrationRun {
  id: number
  status: string  // 'running' | 'completed' | 'failed'
  started_at: string | null
  completed_at: string | null
  error_detail: string | null
}

export interface ProjectStatus {
  project_slug: string
  project_status: string
  crew_runs: CrewRun[]
  latest_orchestration_run: OrchestrationRun | null
}

export interface AgentOutput {
  id: number
  agent_name: string
  output_type: string
  file_path: string
  version: number
  review_status: string
  is_current: boolean
  reviewer_notes?: string | null
  revision_notes?: string | null
  created_at: string
}

export interface ClientDocument {
  id: number
  project_id: number
  filename: string
  original_name: string
  file_path: string
  content_type: string
  size_bytes: number
  ingested: boolean
  uploaded_at: string
}

export interface DiscoveryLink {
  url: string
  label: string
}

// Used by VoiceInterview.tsx (SP12b Task 3)
export interface InterviewBranding {
  header_image_url: string
  primary_color: string
  text_color: string
  interviewer_image_url?: string
  interviewer_name?: string
  interviewer_tagline?: string
}

export interface NonWorkingRange {
  id: number
  slug: string
  label: string
  start_date: string
  end_date: string
  created_at: string
}

export interface ProjectSettings {
  llm_mode: 'standard' | 'sensitive' | 'fallback'
  sector: string
  stakeholder_groups: string[]
  value_stream_labels: string[]
  roadmap_time_axis: 'quarters' | 'years' | 'horizons'
  crews_enabled: string[]
  review_gates: boolean
  slack_channel: string
  discovery_brief: string
  discovery_links: DiscoveryLink[]
  discovery_document_ids: number[]
  interview_method: 'agent' | 'none'
  brand_header_image_url?: string
  brand_primary_color?: string
  brand_text_color?: string
  standards_references?: string
  preferred_questionnaire_sections?: number
  preferred_questions_per_section?: number
  locale?: string
  sched_start?: string | null
  sched_duration_weeks?: number | null
}

export interface OutputContent {
  content: string
  output_type: string
}

export interface Review {
  id: number
  output_id: number
  decision: string
  notes: string
}

export interface HumanReview {
  id: number
  prompt: string
  crew_run_id: number
  crew_name?: string
  decision: string
  reviewed_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface UserPayload {
  sub: string
  role: 'sysadmin' | 'org_admin' | 'reviewer'
  org_id?: number
  exp: number
}

export interface CapabilityUplift {
  dimension: 'people' | 'data' | 'systems' | 'organisation' | 'partnership' | 'architectural' | 'operating_model'
  description: string
}

export interface CostEstimate {
  low: number
  high: number
  currency: string
  rationale: string
}

export interface Initiative {
  id: string
  title: string
  description: string
  proposition_ids: string[]
  capability_uplifts: CapabilityUplift[]
  initiative_type: 'enabler' | 'change_activity'
  enabler_dependencies: string[]
  change_dependencies: string[]
  complexity_score: number
  complexity_rationale: string
  cost_estimate: CostEstimate
  related_requirements: string[]
  // Roadmap fields (added by roadmap_generator)
  category?: string
  value_streams?: string[]
  period?: string
}

export interface RoadmapData {
  periods: string[]
  value_streams: string[]
  stakeholder_groups: string[]
  initiatives: Initiative[]
  propositions: unknown[]
}

export interface FinancialSummary {
  npv: number | null
  irr: number | null
  payback_period: string | null
  max_borrowing: number | null
  total_investment: number | null
  total_benefits: number | null
}

export interface RunCrewSummary {
  crew_name: string
  status: string
}

export interface OrchestrationRunHistory {
  id: number
  status: string
  started_at: string | null
  completed_at: string | null
  crew_runs: RunCrewSummary[]
}

export interface Stakeholder {
  id: number
  name: string
  job_title: string
  organisation: string
  email: string
  slack_handle: string
  mobile: string
  stakeholder_groups: string[]
  project_role: 'recipient' | 'governing' | 'actor'
  value_streams: string[]
  value_chain_stage: string
  activity: string
  disposition: 'champion' | 'supporter' | 'neutral' | 'skeptic' | 'blocker'
  location: string
  country_code: string
  timezone: string
  preferred_language: string
  currency: string
  // Engagement fields
  level: '' | 'L0' | 'L1' | 'L2' | 'L3'
  entity: string
  comms_channel: 'email' | 'slack' | 'sms'
  // Role flags (a stakeholder can hold all three simultaneously)
  is_participant: boolean
  is_reviewer: boolean
  is_approver: boolean
  interview_status: string | null
  interview_invited_at: string | null
  interview_completed_at: string | null
  created_at: string
}

export interface StakeholderNodeAssignment {
  id: number
  stakeholder_id: number
  node_key: string
}

export interface ValueChainRegistryActivity {
  id: string
  label: string
  level: 'L1' | 'L2' | 'L3'
  active: boolean
  parent_id: string | null
}

export interface ValueChainRegistry {
  schema_version: number
  activities: ValueChainRegistryActivity[]
}

export interface StakeholderImportResult {
  created: number
  updated: number
  errors: { row: number; reason: string }[]
}

export interface Campaign {
  id: number
  project_id: number
  value_stream_name: string
  campaign_name: string
  interview_start: string | null
  interview_close: string | null
  findings_summary: string
  created_at: string
}

export interface ReminderEmail {
  id: number
  project_id: number
  campaign_id: number
  stakeholder_id: number
  subject: string
  body: string
  escalation_level: 'gentle' | 'firm' | 'urgent'
  status: 'pending' | 'approved' | 'dismissed'
  created_at: string
}

export interface InterviewSummary {
  active_campaigns: {
    id: number
    value_stream_name: string
    total_stakeholders: number
    completed: number
    window_open: boolean
  }[]
  total_stakeholders: number
  total_completed: number
}

export interface ImportResult {
  updated?: number
  imported?: number
  skipped?: number
  unmatched?: number
}

export interface PortfolioItem {
  rank: number
  id: string
  title: string
  change_articulation: string
  impacted_stakeholder_groups: string[]
  value_estimate: 'High' | 'Medium' | 'Low'

  score_financial: number
  score_financial_rationale: string
  score_financial_unit: string

  score_manufactured: number
  score_manufactured_rationale: string
  score_manufactured_unit: string

  score_intellectual: number
  score_intellectual_rationale: string
  score_intellectual_unit: string

  score_human: number
  score_human_rationale: string
  score_human_unit: string

  score_social_relationship: number
  score_social_relationship_rationale: string
  score_social_relationship_unit: string

  score_natural: number
  score_natural_rationale: string
  score_natural_unit: string

  score_safety: number
  score_safety_rationale: string
  score_safety_unit: string

  score_performance: number
  score_performance_rationale: string
  score_performance_unit: string

  total_score: number
  weights_used: {
    financial: number
    manufactured: number
    intellectual: number
    human: number
    social_relationship: number
    natural: number
    safety: number
    performance: number
  }
}

export interface ValueChainNode {
  label: string
  level: 'L1' | 'L2' | 'L3'
  children?: ValueChainNode[]
}

export interface StakeholderAssignment {
  stakeholder_id: number
  level: string
  node_label: string
}

export interface AssignmentData {
  value_chain_tree: ValueChainNode[]
  assignments: StakeholderAssignment[]
  stakeholders: Stakeholder[]
}

export interface VoiceConfig {
  language: string
  country_code: string
  elevenlabs_voice_id: string
}

export interface InterviewQuestion {
  id: string
  text: string
  follow_up_count: number
  probing_instructions: string
  follow_up_branches: string[]
  evasion_signals: string[]
}

export interface MaturityRating {
  dimension: string
  prompt: string
  scale: Record<string, string>       // "0"–"4" → descriptor label
  capture_after: string
  probe_on_mismatch: string
}

export interface InterviewSection {
  title: string
  target_minutes?: number
  questions: InterviewQuestion[]
  maturity_rating?: MaturityRating    // present for L1/L2 sections; absent for L3
}

export interface FramingBlock {
  positioning: string
  context_setting: string[]
  dual_lenses: {
    efficiency: string
    effectiveness: string
  }
}

export interface SynthesisCheck {
  synthesis_prompt: string
  response_probes: {
    if_positive: string
    if_defensive: string
    if_uncertain: string
  }
  peer_referral: string
  forward_roadmap: string
}

export interface SectionMaturityRating {
  section_title: string
  dimension: string
  rating: number                      // 0–4
  commentary?: string
}

export interface InterviewScript {
  node_label: string
  level: string
  research_brief: string
  study_objectives: string[]
  welcome_message: string
  framing_block?: FramingBlock      // L1 and L2 — spoken before sections
  sections: InterviewSection[]
  synthesis_check?: SynthesisCheck  // L1 and L2 — spoken after sections, before closing
  closing_message: string
}

export interface InterviewSession {
  id: number
  stakeholder_id: number
  node_label: string
  session_token: string
  status: string
  voice_config: VoiceConfig | null
}

export interface SessionSummary {
  pending: number
  active: number
  completed: number
  abandoned: number
}

export interface InterviewSessionStatus {
  id: number
  stakeholder_id: number
  name: string
  node_label: string
  session_token: string
  status: 'pending' | 'active' | 'completed' | 'abandoned'
  interview_url: string
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface InterviewSessionsResponse {
  orchestration_run_id: number | null
  sessions: InterviewSessionStatus[]
  summary: SessionSummary
}

export interface NodeTemplateAssignment {
  node_label: string
  activity_id: string | null
  level?: 'L1' | 'L2' | 'L3'
  interview_template_id: number | null
  questionnaire_template_id: number | null
}

export interface TemplateListItem {
  id: number
  name: string
  description: string
  type: 'interview' | 'questionnaire'
  created_at: string
  updated_at: string
}

export interface InterviewTemplateSchema {
  welcome_message: string
  closing_message: string
  sections: {
    title: string
    questions: {
      id: string
      text: string
      follow_up_count: number
      probing_instructions: string
      follow_up_branches: string[]
      evasion_signals: string[]
    }[]
  }[]
}

export interface QuestionnaireScale {
  min: number
  max: number
  labels: Record<string, string>
}

export interface QuestionnaireTemplateSchema {
  scale: QuestionnaireScale
  sections: {
    id: string
    title: string
    description: string
    questions: { id: string; text: string }[]
  }[]
}

export interface TemplateDetail extends TemplateListItem {
  schema_json: InterviewTemplateSchema | QuestionnaireTemplateSchema
}

export interface SectionRatings {
  section_id: string
  section_title: string
  ratings: Record<string, number>  // question id → 0-4
  commentary: string
}

// ── Admin types ───────────────────────────────────────────────────────────────

export interface Organisation {
  id: number
  slug: string
  name: string
  created_at: string
}

export interface OrgMember {
  id: number
  username: string
  email: string
  role: string
  org_role: string
  created_at: string
}

export interface AdminUser {
  id: number
  username: string
  email: string
  role: string
  created_at: string
}

export interface ProjectRegistryEntry {
  id: number
  slug: string
  org_id: number
  display_name: string
  org_name?: string
  created_at: string
}

export interface ProjectMembership {
  id: number
  user_id: number
  project_slug: string
  created_at: string
}

// ── PAM status report ─────────────────────────────────────────────────────────

export interface PamReportCrewStatus {
  crew_key: string
  crew_label: string
  status: 'completed' | 'failed' | 'running' | 'not_started'
  last_run_at: string | null
  finished_at: string | null
  run_count: number
  outputs_count: number
  output_types: string[]
  pending_reviews: number
  error_detail: string | null
}

export interface PamReportRisk {
  severity: 'high' | 'medium' | 'low'
  title: string
  description: string
  mitigation: string
}

export interface PamReportIssue {
  severity: 'critical' | 'high' | 'medium'
  title: string
  description: string
  recommended_action: string
  crew: string | null
}

export interface PamReportMilestone {
  id: number
  milestone_key: string
  title: string
  due_date: string | null
  status: 'pending' | 'complete'
  rag: 'complete' | 'overdue' | 'due_soon' | 'on_track' | 'unscheduled'
  days_delta: number | null
  sort_order: number
}

export interface PamReport {
  generated_at: string
  project_slug: string
  client_name: string
  sector: string
  overall_health: 'red' | 'amber' | 'green'
  health_summary: string
  milestones: PamReportMilestone[]
  milestones_complete: number
  milestones_total: number
  crews: PamReportCrewStatus[]
  risks: PamReportRisk[]
  issues: PamReportIssue[]
  interview_tracker: {
    total: number
    complete: number
    active: number
    pending: number
    abandoned: number
    pct: number
  }
  pending_reviews: number
  stakeholder_count: number
  doc_count: number
}

export interface Milestone {
  id: number
  slug: string
  milestone_key: string
  title: string
  description: string
  due_date: string | null
  status: 'pending' | 'complete'
  notes: string
  sort_order: number
  created_at: string
}
