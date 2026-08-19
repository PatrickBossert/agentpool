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
  /** 'pending' | 'ingested' | 'failed'. `ingested` is the same fact as a boolean. */
  ingest_status?: string
  /** Why it failed, when it did. Null otherwise. */
  ingest_error?: string | null
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
  /**
   * Removes hosted inference from whatever this project's mode grants, so every agent runs
   * on the local models while the documents stay where the mode puts them. It narrows only;
   * it does not move the vector store.
   *
   * Declared here, and that declaration is load-bearing rather than tidy. Before it, the
   * field survived a save purely as an untyped extra key that `setForm({ ...DEFAULTS,
   * ...settings })` happened to copy - so any refactor that built the request body from this
   * type (a pick, a typed constructor, a stricter lint rule) would have dropped it silently.
   * A dropped key is `false` on the server, and clearing this flag is the one transition
   * here that *widens* where an engagement's prompts may go: an org_admin saving an
   * unrelated field would have put a project back onto hosted inference with nothing said.
   * Never make it optional - `force_local_inference?: boolean` reopens exactly that.
   */
  force_local_inference: boolean
  sector: string
  stakeholder_groups: string[]
  value_stream_labels: string[]
  roadmap_time_axis: 'quarters' | 'years' | 'horizons'
  review_gates: boolean
  slack_channel: string
  discovery_brief: string
  discovery_links: DiscoveryLink[]
  discovery_document_ids: number[]
  interview_method: 'agent' | 'none'
  /** How long Avery waits for a follow-up during a live interview before moving on. */
  elaboration_press_timeout_seconds: number
  /** Hosted fast model, used for coordination and live follow-ups. */
  anthropic_fast_model: string
  /** Hosted deep model, used for analysis across a whole campaign. */
  anthropic_deep_model: string
  local_fast_model: string
  local_fast_url: string
  local_deep_model: string
  local_deep_url: string
  brand_header_image_url?: string
  brand_primary_color?: string
  brand_text_color?: string
  standards_references?: string
  preferred_questionnaire_sections?: number
  preferred_questions_per_section?: number
  locale?: string
  sched_start?: string | null
  sched_duration_weeks?: number | null
  client_name?: string
  /** Closed vertical axis for interview section tags; Casey groups maturity themes by it. */
  disciplines?: string[]
  service_categories?: string
  key_vendors?: string
  applicable_regulations?: string
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

// POST /auth/accept's response - unlike /auth/login, accepting an invite does not always
// mint a session: redeeming one for an email that already has a login only grants the
// project membership, since that person already holds credentials and must sign in with
// them (see api/routers/invites.py's CRITICAL note). access_token is null in that case.
export interface AcceptResponse {
  access_token: string | null
  token_type: string
  already_registered?: boolean
  detail?: string
}

// POST /auth/users/{id}/reset-link's response - the administrator door onto the same reset
// machinery /auth/reset-request drives. It returns the raw token because there is no wired
// outbound-email path yet, so the administrator delivers the link by hand (the same
// arrangement the invite loop runs on). username is what the token was minted against and
// email is where to send it - they are the same for every invite-created login, but need
// not be for one an administrator created.
export interface ResetLinkResponse {
  reset_token: string
  username: string
  email: string
}

// POST /projects/{slug}/stakeholders/{id}/resend-invite's response. The raw token, for the
// same reason ResetLinkResponse carries one: no outbound-email path is wired for invites,
// so an administrator delivers the link by hand. The body is a redeemable credential, which
// is why the door stayed on the platform tier when sp44 widened the rest of its router -
// see MyPermissions.can_issue_invite_links.
export interface InviteLinkResponse {
  invite_token: string
}

// GET/PATCH/DELETE /admin/platform-settings. `source` is what tells an administrator
// whether `public_url` is a saved setting or the PUBLIC_URL the deployment booted with -
// the two behave differently the next time the environment changes, and a resolved value
// with no `source` beside it gives an administrator nothing to diagnose "the page looks
// right but the links are wrong" with.
export interface PlatformSettings {
  public_url: string
  source: 'stored' | 'environment'
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
  level: '' | 'L0' | 'L1' | 'L2' | 'L3' | 'C' | 'A' | 'F' | 'S'
  entity: string
  comms_channel: 'email' | 'slack' | 'sms'
  // Role flags - a stakeholder may hold any combination of them. The last two are the
  // administration and governance halves: project_admin configures this engagement and
  // its people, governor receives PAM's reports. Both are grantable only by a
  // project_admin (GET /my-permissions' can_grant_roles).
  is_participant: boolean
  is_reviewer: boolean
  is_approver: boolean
  is_project_admin: boolean
  is_governor: boolean
  interview_status: string | null
  interview_invited_at: string | null
  interview_completed_at: string | null
  created_at: string
  // Whether this person can actually reach the engagement, computed by the server - see
  // api/services/stakeholder_access.py. Two thirds of it (a linked login, an unredeemed
  // invite) live in system.db, which the browser cannot see at all, so this is not
  // derivable here even in principle.
  //
  // Optional because only the list door serves it: a create or update response is the row
  // as written, before anything has asked system.db about it.
  access_state?: AccessState
  // Seeded by scripts/seed_synthetic_stakeholders.py rather than a real person. Sixty of
  // sp-gs-am's sixty-two rows are, so a surface listing people by name says which.
  is_synthetic?: boolean
}

export type AccessState =
  // A login linked to this project.
  | 'has_login'
  // An unredeemed invite exists - the only state an invite link can be issued for.
  | 'invited'
  // Holds a role beyond participant with no deliverable address: cannot be invited at all
  // until the address is repaired.
  | 'unreachable'
  // Holds a deliverable role and has neither a login nor an invite. Roles granted before
  // the invite trigger existed have this shape; clearing the role and re-setting it is
  // what issues one.
  | 'not_invited'
  // Participant only. Interviews reach them by campaign link, so no login is needed.
  | 'no_login_needed'

// StakeholderNodeAssignment retired with stakeholder_node_assignments, the second
// assignment table. Its node_key was 'L2:Some Label' - a level and a label glued together,
// with no node id in it. The mapping is StakeholderAssignment below, keyed on the id.

export interface ValueChainRegistryActivity {
  id: string
  label: string
  // L0 belongs here: `0` is the organisation and `0.A` / `0.S` are its audit and corporate
  // services role nodes, all three registered ids. The assignment page used to invent a
  // virtual 'L0:Governance' node instead, because this union said they could not exist.
  level: 'L0' | 'L1' | 'L2' | 'L3'
  active: boolean
  parent_id?: string | null
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

// ValueChainNode retired with the `value_chain_tree` field of the assignment payload. It
// described value_chain_tree.json - a label, a level and children, and no id anywhere - so
// nothing could assign against it without keying on a label. The node ids come from
// ValueChainRegistryActivity, which is what the assignment surface reads.

// One stakeholder against one value chain node. The node is cited by its id, which is a
// permanent contract; `node_label` and `level` are resolved from the value chain registry
// on read and are never sent back.
export interface StakeholderAssignment {
  stakeholder_id: number
  node_id: string
  node_label?: string
  level?: string
}

export interface AssignmentData {
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
  /** Stable within its script. A citation to a title cites a string Maya may rewrite. */
  section_id?: string
  title: string
  target_minutes?: number
  questions: InterviewQuestion[]
  maturity_rating?: MaturityRating    // present for L1/L2 sections only; absent for L0, L3, C, and A
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
  portfolio_options?: string   // L0 only — interviewer presents sequencing options A/B/C
  sponsorship_check?: string   // L0 only — commitment test for executive sponsors
}

export interface SectionMaturityRating {
  section_title: string
  dimension: string
  rating: number                      // 0–4
  commentary?: string
}

export interface InterviewScript {
  /** Registered, opaque, never reused - stored answers cite scripts through it. */
  script_id?: string
  /** The stable value chain node this script is about; "0" is the L0 entity. */
  node_id?: string
  relationship?: 'internal' | 'customer' | 'regulator' | 'supplier' | 'partner'
  node_label: string
  /** The structural tier - L0 to L3 - even for a role-node script. */
  level: string
  /** Who the interviewee speaks as, on a role node: audit, corporate services, customer, or
   *  frontline. Null for an ordinary L0-L3 script. Separate from `level` so the same node
   *  files at one tier regardless of which role, if any, the script also carries. */
  perspective: 'A' | 'S' | 'C' | 'F' | null
  research_brief: string
  study_objectives: string[]
  welcome_message: string
  framing_block?: FramingBlock      // L0, L1, L2, C, and A — spoken before sections
  sections: InterviewSection[]
  synthesis_check?: SynthesisCheck  // L0, L1, L2, C, and A — spoken after sections, before closing
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

// Who a login is *on one project* - the name and entity from the stakeholder row its
// membership of that project points at (api/services/user_identity.py).
//
// Read through one project because that is what a stakeholder is: a person on an engagement.
// The same login on two engagements has two stakeholder rows and may be recorded differently
// on each, so there is no project-free answer, and the unscoped user list therefore carries
// no `person` field at all rather than an arbitrary one.
//
// `person: null` means the account is on the project but has no person record behind it - an
// administrator-granted membership, which carries no stakeholder_id. Rendered as absent,
// never guessed at.
export interface PersonDetails {
  name: string | null
  entity: string | null
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
  // Absent on the unscoped list; present (possibly null) once a project is selected.
  person?: PersonDetails | null
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
  // When it was actually reached, against due_date's plan. Null while outstanding.
  completed_at?: string | null
  baseline_date?: string | null
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
  // Optional because the exporter and its fixtures build a report by hand, and a report
  // predating this field is still a report. `build_pam_report` always returns it.
  assignment_coverage?: PamReportAssignmentCoverage
}

/** What the mapping covers, and what it leaves out. Counts only - the mapping itself is
 *  Jordan's engagement plan, not a project health report. */
export interface PamReportAssignmentCoverage {
  activities_total: number
  activities_covered: number
  activities_uncovered: number
  uncovered_node_ids: string[]
  uncovered_proportion: number
  roster_total: number
  stakeholders_assigned: number
  stakeholders_unassigned: number
  unassigned_stakeholders: { id: number; name: string; job_title: string }[]
  unassigned_proportion: number
  off_chain_total: number
  threshold: number
  uncovered_beyond_threshold: boolean
  unassigned_beyond_threshold: boolean
}

export interface LineageOutput {
  id: number
  agent_name: string
  output_type: string
  version: number
  is_current: number
  state: 'fresh' | 'stale' | 'unknown'
  behind: { output_type: string; built_from: number; approved: number }[]
  input_output_ids: number[]
  document_ids: number[]
}

export interface LineageResponse {
  outputs: LineageOutput[]
  documents: Record<string, string>
  blocked_writes: {
    id: number; agent_name: string; key: string; owner: string | null
    reason: string; attempted_at: string
  }[]
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
  // When it was actually reached. Null while outstanding.
  completed_at?: string | null
  // What it was promised, set at activation. due_date is what is currently expected.
  baseline_date?: string | null
  created_at: string
}

export interface ScriptLedgerRow {
  script_id: string
  node_id: string
  node_label: string
  // Every value record_script_review can write, plus 'pending' - the column's default and
  // the only one no decision produces. It sets review_status = decision, so this union must
  // stay a superset of script_review_service.VALID_DECISIONS: 'edited' was added there and
  // not here, and because a narrower union makes a Record<> over it look total, tsc reported
  // nothing while ICON['edited'] came back undefined and the row crashed on render.
  // tests/ScriptReviewRow.test.tsx now reads VALID_DECISIONS out of the Python and fails if
  // this drifts again.
  review_status: 'pending' | 'reviewed' | 'edited' | 'approved' | 'changes_requested'
  reviewed_at_version: number | null
  review_return_to: 'agent' | 'reviewer' | null
  last_version: number | null
  last_author: string
  review_count: number
}

// A structural finding a validator raised and did not refuse. Recorded when an agent
// writes, dispositioned by a reviewer, and carried back into the agent's next run unless
// dismissed.
export interface ValidationWarning {
  id: number
  source: string
  subject: string | null
  code: string
  detail: string
  measure: number | null
  disposition: 'open' | 'acknowledged' | 'dismissed'
  disposition_note: string | null
}

// What the caller may do on one project, asked once rather than inferred from a 403.
// Mirrors caller_roles' two questions (api/services/authority_service.py) - review
// authority is the wider of the two, approval authority the narrower.
export interface MyPermissions {
  can_review: boolean
  can_approve: boolean
  // Whether this caller may grant is_project_admin / is_governor on this project.
  // Narrower than administering it: an org_admin configures everything and still
  // cannot mint a project_admin.
  can_grant_roles: boolean
  // Whether this caller may retrieve an invite link for a stakeholder on this project.
  // The one permission here that is *narrower* than administering the engagement: the
  // response body of the door it reports on is a redeemable credential, so it asks the
  // platform tier (org_admin or sysadmin) and a project_admin is refused.
  can_issue_invite_links: boolean
  // Whether this caller may change the platform-tier fields on PATCH /{slug}/settings -
  // llm_mode, force_local_inference, dev_mode, and the six model ids, which decide where
  // this engagement's data is sent. Narrower than administering the project, like
  // can_issue_invite_links, and reported separately from it despite the two asking the same
  // predicate today: they report on different doors, and a shared key would make one follow
  // the other's tier change silently.
  can_change_platform_tier_settings: boolean
  // The knowledge tiers this caller may add material at on this project, broadest first -
  // some subset of 'sector', 'organisation', 'project'. What an upload tier picker offers,
  // and the whole of what it may offer: the rule is the server's
  // (authority_service.writable_tiers_on_project) and must not be restated here. A tier the
  // caller cannot write, or one that does not exist for this project - the organisation
  // tier of a project belonging to no organisation - is simply absent from the list.
  writable_knowledge_tiers: string[]
}

// One reply a participant sent back to the correspondent, resolved to the person who sent
// it. Arrives through the inbound webhook (api/services/inbound_mail.py), which stores it
// against the project and the stakeholder and does nothing else with it - reading it and
// deciding what it means is a human's job, and this is what they read it on.
//
// `body` is plain text and never markup: the webhook is unauthenticated, so what it stores
// must not be something a browser will later render. Render it as text.
export interface InboundReply {
  id: number
  stakeholder_id: number
  stakeholder_name: string
  stakeholder_email: string
  // Who actually wrote it, which is not the same question as which thread it routed to.
  // The reply token proves possession of an address and never authorship - and the two come
  // apart today, because dev_mode holds participant mail at DEV_MODE_ADDRESS with the
  // participant's live token on it. So the sender is always shown, and `sender_confirmed`
  // says whether it matches the stakeholder's address on file. The server computes it; a
  // second answer worked out in the browser could disagree with it.
  from_address: string
  sender_confirmed: boolean
  subject: string
  body: string
  // Whether the reply was longer than the endpoint stores. The full message is in the
  // mailbox; the panel says so rather than quietly showing a fragment as if it were whole.
  truncated: boolean
  // Attachments are counted and never stored - see api/services/inbound_mail.py. The count
  // is here so a reader knows to go and ask for the file.
  attachment_count: number
  received_at: string
  read_at: string | null
}

export interface InboundRepliesResponse {
  replies: InboundReply[]
  unread: number
}
