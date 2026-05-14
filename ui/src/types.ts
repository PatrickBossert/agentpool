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
  interview_method: 'agent' | 'listenlabs' | 'none'
  brand_header_image_url?: string
  brand_primary_color?: string
  brand_text_color?: string
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
  decision: string
  reviewed_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface UserPayload {
  sub: string
  role: string
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
  interview_status: string | null
  interview_invited_at: string | null
  interview_completed_at: string | null
  created_at: string
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
  listenlabs_campaign_id: string
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

export interface InterviewSection {
  title: string
  questions: InterviewQuestion[]
}

export interface InterviewScript {
  node_label: string
  level: string
  research_brief: string
  study_objectives: string[]
  welcome_message: string
  closing_message: string
  sections: InterviewSection[]
}

export interface InterviewSession {
  id: number
  stakeholder_id: number
  node_label: string
  session_token: string
  status: string
  voice_config: VoiceConfig
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
