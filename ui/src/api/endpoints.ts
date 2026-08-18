// ui/src/api/endpoints.ts
import { apiClient } from './client'
import type {
  Project,
  ProjectStatus,
  AgentOutput,
  ClientDocument,
  ProjectSettings,
  OutputContent,
  TokenResponse,
  AcceptResponse,
  RoadmapData,
  FinancialSummary,
  HumanReview,
  OrchestrationRunHistory,
  InviteLinkResponse,
  Stakeholder,
  StakeholderImportResult,
  ValueChainRegistry,
  PortfolioItem,
  AssignmentData,
  Milestone,
  PamReport,
  LineageResponse,
} from '../types'

export const authApi = {
  login: (username: string, password: string): Promise<TokenResponse> => {
    const form = new URLSearchParams()
    form.append('username', username)
    form.append('password', password)
    return apiClient.post<TokenResponse>('/auth/login', form).then((r) => r.data)
  },

  // Unauthenticated by design - accepting an invite is how a person gets a session in the
  // first place, so this must not rely on one already existing. access_token comes back
  // null when the invite named an email that already has a login: that redemption only
  // grants the membership, not a session - see AcceptResponse and api/routers/invites.py.
  accept: (token: string, password: string): Promise<AcceptResponse> =>
    apiClient.post<AcceptResponse>('/auth/accept', { token, password }).then((r) => r.data),

  // Unauthenticated by design, like accept: somebody who has forgotten their password
  // cannot sign in to ask for a new one.
  //
  // Resolves to nothing, and that is the contract rather than an omission. The server
  // answers 204 with an empty body whether or not the address has an account, so there is
  // no outcome to return - and a caller that had one would sooner or later branch on it,
  // which is precisely the account-existence oracle the 204 exists to prevent. Callers say
  // "if that address has an account, a link is on its way" and nothing more.
  requestReset: (email: string): Promise<void> =>
    apiClient.post('/auth/reset-request', { email }).then(() => undefined),

  // The redemption half. Unlike accept, this always mints a session when it succeeds: a
  // reset token can only have been asked for by the account owner, to their own address, so
  // redeeming one is an authentication event rather than a grant - see api/routers/
  // invites.py. A rejection (an expired, spent, or invented token) is a 400, which axios
  // raises, so callers handle it in catch.
  resetPassword: (token: string, password: string): Promise<TokenResponse> =>
    apiClient.post<TokenResponse>('/auth/reset', { token, password }).then((r) => r.data),
}

export const projectsApi = {
  list: (): Promise<Project[]> =>
    apiClient.get<Project[]>('/projects').then((r) => r.data),

  create: (payload: {
    client_slug: string
    sector: string
    llm_mode?: string
  }): Promise<Project> =>
    apiClient.post<Project>('/projects', payload).then((r) => r.data),

  status: (slug: string): Promise<ProjectStatus> =>
    apiClient.get<ProjectStatus>(`/projects/${slug}/status`).then((r) => r.data),

  outputs: (slug: string): Promise<AgentOutput[]> =>
    apiClient.get<AgentOutput[]>(`/projects/${slug}/outputs`).then((r) => r.data),

  documents: (slug: string): Promise<ClientDocument[]> =>
    apiClient.get<ClientDocument[]>(`/projects/${slug}/documents`).then((r) => r.data),

  uploadDocument: (slug: string, file: File): Promise<ClientDocument> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient
      .post<ClientDocument>(`/projects/${slug}/documents/upload`, form)
      .then((r) => r.data)
  },

  deleteDocument: (slug: string, docId: number): Promise<void> =>
    apiClient.delete(`/projects/${slug}/documents/${docId}`).then(() => undefined),

  reingestDocument: (slug: string, docId: number): Promise<void> =>
    apiClient.post(`/projects/${slug}/documents/${docId}/reingest`).then(() => undefined),

  valueChain: (slug: string): Promise<AgentOutput[]> =>
    apiClient.get<AgentOutput[]>(`/projects/${slug}/value-chain`).then((r) => r.data),

  roadmap: (slug: string): Promise<AgentOutput[]> =>
    apiClient.get<AgentOutput[]>(`/projects/${slug}/roadmap`).then((r) => r.data),

  review: (slug: string, outputId: number, decision: string, notes = '') =>
    apiClient
      .post(`/projects/${slug}/review`, { output_id: outputId, decision, notes })
      .then((r) => r.data),

  orchestrate: (slug: string): Promise<{ orchestration_run_id: number; status: string }> =>
    apiClient.post(`/projects/${slug}/orchestrate`).then((r) => r.data),

  runCrew: (slug: string, crew: string): Promise<{ run_id: number; project_slug: string; crew: string; status: string }> =>
    apiClient.post(`/projects/${slug}/run`, { crew }).then((r) => r.data),

  runAgent: (slug: string, agent: string): Promise<{ run_id: number; project_slug: string; crew: string; status: string }> =>
    apiClient.post(`/projects/${slug}/run`, { agent }).then((r) => r.data),

  getSettings: (slug: string): Promise<ProjectSettings> =>
    apiClient.get<ProjectSettings>(`/projects/${slug}/settings`).then((r) => r.data),

  updateSettings: (slug: string, data: ProjectSettings): Promise<ProjectSettings> =>
    apiClient.patch<ProjectSettings>(`/projects/${slug}/settings`, data).then((r) => r.data),

  getOutputContent: (slug: string, outputId: number): Promise<OutputContent> =>
    apiClient.get<OutputContent>(`/projects/${slug}/outputs/${outputId}/content`).then((r) => r.data),

  revertOutput: (slug: string, outputId: number): Promise<AgentOutput> =>
    apiClient.post<AgentOutput>(`/projects/${slug}/outputs/${outputId}/revert`).then((r) => r.data),

  roadmapData: (slug: string): Promise<RoadmapData> =>
    apiClient.get<RoadmapData>(`/projects/${slug}/roadmap-data`).then((r) => r.data),

  getInterviewScripts: (slug: string): Promise<Record<string, import('../types').InterviewScript>> =>
    apiClient.get<Record<string, import('../types').InterviewScript>>(`/projects/${slug}/interview-scripts`).then((r) => r.data),

  financialSummary: (slug: string): Promise<FinancialSummary> =>
    apiClient.get<FinancialSummary>(`/projects/${slug}/financial-summary`).then((r) => r.data),

  portfolioRegister: (slug: string): Promise<PortfolioItem[]> =>
    apiClient.get<PortfolioItem[]>(`/projects/${slug}/portfolio-register`).then((r) => r.data),

  // An output is created review_status='pending'. This endpoint has always existed on the
  // server and nothing called it, so nothing could ever move an output off pending.
  submitOutputReview: (
    slug: string, outputId: number, decision: string, notes: string,
  ): Promise<void> =>
    apiClient
      .post(`/projects/${slug}/review`, { output_id: outputId, decision, notes })
      .then(() => undefined),

  listReviews: (slug: string): Promise<HumanReview[]> =>
    apiClient.get<HumanReview[]>(`/projects/${slug}/reviews`).then((r) => r.data),

  resolveReview: (
    slug: string,
    reviewId: number,
    decision: string,
    notes: string,
    intent: string = 'change_request',
  ): Promise<void> =>
    apiClient
      .patch(`/projects/${slug}/reviews/${reviewId}`, { decision, notes, intent })
      .then(() => undefined),

  deleteReview: (slug: string, reviewId: number): Promise<void> =>
    apiClient.delete(`/projects/${slug}/reviews/${reviewId}`).then(() => undefined),

  listRuns: (slug: string): Promise<OrchestrationRunHistory[]> =>
    apiClient.get<OrchestrationRunHistory[]>(`/projects/${slug}/runs`).then((r) => r.data),

  // The mapping is a project fact, so neither call takes an orchestration run - both
  // work before the first run and read the same rows after the tenth.
  getAssignment: (slug: string): Promise<AssignmentData> =>
    apiClient.get<AssignmentData>(`/projects/${slug}/assignment`).then((r) => r.data),

  saveAssignment: (
    slug: string,
    items: { stakeholder_id: number; node_id: string }[],
  ): Promise<{ saved: number }> =>
    apiClient.post<{ saved: number }>(`/projects/${slug}/assignment`, items).then((r) => r.data),

  advanceOrchestrationRun: (
    slug: string,
    orchestrationRunId: number,
  ): Promise<{ status: string }> =>
    apiClient
      .patch<{ status: string }>(`/projects/${slug}/orchestration-runs/${orchestrationRunId}/advance`)
      .then((r) => r.data),

  getValueChainRegistry: (slug: string): Promise<ValueChainRegistry> =>
    apiClient.get<ValueChainRegistry>(`/projects/${slug}/value-chain-registry`).then((r) => r.data),

  uploadBrandingImage: (slug: string, file: File): Promise<{ url: string }> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<{ url: string }>(`/projects/${slug}/branding/image`, form).then((r) => r.data)
  },

  lineage: (slug: string): Promise<LineageResponse> =>
    apiClient.get<LineageResponse>(`/projects/${slug}/lineage`).then((r) => r.data),

  getScriptLedger: (slug: string): Promise<import('../types').ScriptLedgerRow[]> =>
    apiClient.get(`/projects/${slug}/script-ledger`).then((r) => r.data),

  reviewScript: (slug: string, scriptId: string,
                 body: { decision: string; notes?: string; return_to?: string }) =>
    apiClient.post(`/projects/${slug}/script-ledger/${scriptId}/review`, body).then((r) => r.data),

  // Carries base_version so the server can refuse a save made against a version someone
  // else has already superseded - see PATCH /interview-scripts/{script_id}'s 409.
  patchInterviewScript: (slug: string, scriptId: string,
                         body: { script: unknown; base_version?: number | null }) =>
    apiClient.patch(`/projects/${slug}/interview-scripts/${scriptId}`, body).then((r) => r.data),

  getMyPermissions: (slug: string): Promise<import('../types').MyPermissions> =>
    apiClient.get(`/projects/${slug}/my-permissions`).then((r) => r.data),
}

export const skillNotesApi = {
  create: (agentName: string, rawInput: string) =>
    apiClient.post('/agent-skill-notes', { agent_name: agentName, raw_input: rawInput })
      .then(r => r.data as { id: number; agent_name: string; note: string }),

  list: (agentName?: string) =>
    apiClient.get('/agent-skill-notes', { params: agentName ? { agent_name: agentName } : {} })
      .then(r => r.data as Array<{ id: number; agent_name: string; note: string; raw_input: string; created_at: string }>),
}

// What a stakeholder write may carry: the whole record bar its identity, with the two
// grantable role flags optional rather than required.
type StakeholderBody =
  Omit<Stakeholder, 'id' | 'created_at' | 'is_project_admin' | 'is_governor'>
  & Partial<Pick<Stakeholder, 'is_project_admin' | 'is_governor'>>

export const stakeholdersApi = {
  list: (slug: string): Promise<Stakeholder[]> =>
    apiClient.get<Stakeholder[]>(`/projects/${slug}/stakeholders`).then((r) => r.data),

  // StakeholderBody, not the full record: is_project_admin and is_governor are omitted
  // entirely by a caller who may not grant them (see StakeholderForm.handleSave), and the
  // server treats a key it was not sent as "leave that column alone" - neither flag is
  // declared on StakeholderIn/StakeholderPatch, so a write that does not mention them does
  // not touch them. Typing these as the whole record forced the form to send both.
  create: (slug: string, data: StakeholderBody): Promise<Stakeholder> =>
    apiClient.post<Stakeholder>(`/projects/${slug}/stakeholders`, data).then((r) => r.data),

  update: (
    slug: string,
    id: number,
    data: StakeholderBody,
  ): Promise<Stakeholder> =>
    apiClient.put<Stakeholder>(`/projects/${slug}/stakeholders/${id}`, data).then((r) => r.data),

  remove: (slug: string, id: number): Promise<void> =>
    apiClient.delete(`/projects/${slug}/stakeholders/${id}`).then(() => undefined),

  // Mints a fresh invite token onto this stakeholder's unredeemed invite and hands back the
  // raw value - there is no wired outbound-email path for invites, so the link is delivered
  // by hand. Asking again replaces the previous token, killing the earlier link.
  //
  // Offered only to a caller whose `can_issue_invite_links` is true: the door is
  // `require_org_admin_or_above` deliberately, and a project_admin gets a 403. It also
  // refuses when there is nothing to resend (404) or when the person can already log in on
  // this project (409), which is why the action is offered only for `access_state:
  // 'invited'`.
  resendInvite: (slug: string, id: number): Promise<InviteLinkResponse> =>
    apiClient
      .post<InviteLinkResponse>(`/projects/${slug}/stakeholders/${id}/resend-invite`)
      .then((r) => r.data),

  importCsv: (slug: string, file: File): Promise<StakeholderImportResult> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient
      .post<StakeholderImportResult>(`/projects/${slug}/stakeholders/import`, form)
      .then((r) => r.data)
  },
}

// stakeholderNodeAssignmentsApi retired. It was the only caller of GET/PUT
// /projects/{slug}/stakeholder-assignments, which wrote a second assignment table keyed on
// 'L2:Some Label' that no agent could read. The mapping is projectsApi.getAssignment /
// saveAssignment above, keyed on the value chain node id.

export const nonworkingApi = {
  list: (slug: string) =>
    apiClient.get(`/projects/${slug}/nonworking`).then(r => r.data as import('../types').NonWorkingRange[]),
  create: (slug: string, body: { label: string; start_date: string; end_date: string }) =>
    apiClient.post(`/projects/${slug}/nonworking`, body).then(r => r.data as import('../types').NonWorkingRange),
  update: (slug: string, id: number, body: { label: string; start_date: string; end_date: string }) =>
    apiClient.patch(`/projects/${slug}/nonworking/${id}`, body).then(r => r.data as import('../types').NonWorkingRange),
  remove: (slug: string, id: number) =>
    apiClient.delete(`/projects/${slug}/nonworking/${id}`).then(() => undefined),
}

export const pamReportApi = {
  get: (slug: string): Promise<PamReport> =>
    apiClient.get<PamReport>(`/projects/${slug}/pam-report`).then((r) => r.data),
}

export interface SchedulerHeartbeat {
  last_tick_at: string | null
  seconds_since: number | null
  alive: boolean
}

export const systemApi = {
  // A per-request timeout, not a global one on apiClient - other endpoints in this
  // app legitimately run long. If the API accepts the connection but never responds
  // (a hung worker, a proxy holding the request), this turns an indefinitely-pending
  // "Checking…" button into an axios error with no response, which the classifier
  // already maps to "unreachable".
  heartbeat: (): Promise<SchedulerHeartbeat> =>
    apiClient
      .get<SchedulerHeartbeat>('/system/heartbeat', { timeout: 10_000 })
      .then((r) => r.data),
}

export interface CrewReadiness {
  ready: boolean
  waiting_on: string[]
}

export const commitsApi = {
  readiness: (slug: string): Promise<Record<string, CrewReadiness>> =>
    apiClient.get<Record<string, CrewReadiness>>(`/projects/${slug}/crew-readiness`)
      .then((r) => r.data),
  create: (
    slug: string,
    crewName: string,
    notes = '',
    // Every field but commit_id is absent when autostart_failed is set: the endpoint
    // knows only that starting the next crew raised, not what was started, what is
    // waiting, or whether the project is active.
  ): Promise<{
    commit_id: number
    started?: { crew: string; run_id: number }[]
    skipped?: string[]
    // waiting_on holds crew slugs only. A blocker that is not an approval - Pamela
    // dispatching the crew, or missing project configuration - arrives as `reason`
    // with waiting_on empty.
    waiting?: { crew: string; waiting_on: string[]; reason?: string }[]
    inactive?: boolean
    autostart_failed?: boolean
  }> =>
    apiClient.post(`/projects/${slug}/commits`, {
      crew_name: crewName, notes,
    }).then((r) => r.data),
  committedCrews: (slug: string): Promise<string[]> =>
    apiClient.get<{ crew_name: string }[]>(`/projects/${slug}/commits`)
      .then((r) => [...new Set(r.data.map((c) => c.crew_name))]),
  changeCount: (slug: string, crewName: string): Promise<number> =>
    apiClient.get<unknown[]>(`/projects/${slug}/changes`, { params: { crew_name: crewName } })
      .then((r) => r.data.length),
  states: (slug: string): Promise<Record<string, 'working' | 'ready' | 'committed'>> =>
    apiClient.get<Record<string, 'working' | 'ready' | 'committed'>>(
      `/projects/${slug}/crew-states`,
    ).then((r) => r.data),
  submit: (slug: string, crewName: string, notes = ''): Promise<unknown> =>
    apiClient.post(`/projects/${slug}/submissions`, { crew_name: crewName, notes })
      .then((r) => r.data),
  activate: (slug: string): Promise<{ slug: string; status: string }> =>
    apiClient.post<{ slug: string; status: string }>(`/projects/${slug}/activate`)
      .then((r) => r.data),
}

export const milestonesApi = {
  list: (slug: string): Promise<Milestone[]> =>
    apiClient.get<Milestone[]>(`/projects/${slug}/milestones`).then((r) => r.data),

  seed: (slug: string): Promise<Milestone[]> =>
    apiClient.post<Milestone[]>(`/projects/${slug}/milestones/seed`).then((r) => r.data),

  create: (slug: string, data: { title: string; description?: string; due_date?: string | null; notes?: string }): Promise<Milestone> =>
    apiClient.post<Milestone>(`/projects/${slug}/milestones`, data).then((r) => r.data),

  update: (slug: string, id: number, data: Partial<{ title: string; description: string; due_date: string | null; status: string; notes: string; sort_order: number; completed_at: string | null }>): Promise<Milestone> =>
    apiClient.patch<Milestone>(`/projects/${slug}/milestones/${id}`, data).then((r) => r.data),

  remove: (slug: string, id: number): Promise<void> =>
    apiClient.delete(`/projects/${slug}/milestones/${id}`).then(() => undefined),
}

// What the migration recovered. Shown on the page so a thin result - a registry that
// yielded almost nothing - is visible rather than reported as a bare success.
export interface ValueChainMigrationResult {
  created: boolean
  counts: {
    parties: number
    segments: number
    activities: number
    contributions: number
    tasks: number
    derived: number
  }
}

export const validationsApi = {
  list: (slug: string, source?: string): Promise<import('../types').ValidationWarning[]> =>
    apiClient
      .get(`/projects/${slug}/validation-warnings`, { params: source ? { source } : {} })
      .then((r) => r.data),
  dispose: (
    slug: string,
    warningId: number,
    disposition: 'open' | 'acknowledged' | 'dismissed',
    note: string,
  ): Promise<{ id: number }> =>
    apiClient
      .patch(`/projects/${slug}/validation-warnings/${warningId}`, { disposition, note })
      .then((r) => r.data),
}

export const valueChainApi = {
  get: (slug: string): Promise<{ model: unknown }> =>
    apiClient.get(`/projects/${slug}/value-chain-model`).then((r) => r.data),
  save: (slug: string, model: unknown, summary = ''): Promise<{ output_id: number }> =>
    apiClient.put(`/projects/${slug}/value-chain-model`, { model, summary })
      .then((r) => r.data),
  migrate: (slug: string): Promise<ValueChainMigrationResult> =>
    apiClient.post(`/projects/${slug}/value-chain-model/migrate`).then((r) => r.data),
}
