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
  RoadmapData,
  FinancialSummary,
  HumanReview,
  OrchestrationRunHistory,
  Stakeholder,
  StakeholderImportResult,
  StakeholderNodeAssignment,
  ValueChainRegistry,
  PortfolioItem,
  AssignmentData,
  StakeholderAssignment,
  Milestone,
  PamReport,
} from '../types'

export const authApi = {
  login: (username: string, password: string): Promise<TokenResponse> => {
    const form = new URLSearchParams()
    form.append('username', username)
    form.append('password', password)
    return apiClient.post<TokenResponse>('/auth/login', form).then((r) => r.data)
  },
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

  financialSummary: (slug: string): Promise<FinancialSummary> =>
    apiClient.get<FinancialSummary>(`/projects/${slug}/financial-summary`).then((r) => r.data),

  portfolioRegister: (slug: string): Promise<PortfolioItem[]> =>
    apiClient.get<PortfolioItem[]>(`/projects/${slug}/portfolio-register`).then((r) => r.data),

  listReviews: (slug: string): Promise<HumanReview[]> =>
    apiClient.get<HumanReview[]>(`/projects/${slug}/reviews`).then((r) => r.data),

  resolveReview: (slug: string, reviewId: number, decision: string, notes: string): Promise<void> =>
    apiClient
      .patch(`/projects/${slug}/reviews/${reviewId}`, { decision, notes })
      .then(() => undefined),

  deleteReview: (slug: string, reviewId: number): Promise<void> =>
    apiClient.delete(`/projects/${slug}/reviews/${reviewId}`).then(() => undefined),

  listRuns: (slug: string): Promise<OrchestrationRunHistory[]> =>
    apiClient.get<OrchestrationRunHistory[]>(`/projects/${slug}/runs`).then((r) => r.data),

  getAssignment: (slug: string, orchestrationRunId: number): Promise<AssignmentData> =>
    apiClient
      .get<AssignmentData>(`/projects/${slug}/assignment/${orchestrationRunId}`)
      .then((r) => r.data),

  saveAssignment: (
    slug: string,
    orchestrationRunId: number,
    items: StakeholderAssignment[],
  ): Promise<{ saved: number }> =>
    apiClient
      .post<{ saved: number }>(`/projects/${slug}/assignment/${orchestrationRunId}`, items)
      .then((r) => r.data),

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
}

export const skillNotesApi = {
  create: (agentName: string, rawInput: string) =>
    apiClient.post('/agent-skill-notes', { agent_name: agentName, raw_input: rawInput })
      .then(r => r.data as { id: number; agent_name: string; note: string }),

  list: (agentName?: string) =>
    apiClient.get('/agent-skill-notes', { params: agentName ? { agent_name: agentName } : {} })
      .then(r => r.data as Array<{ id: number; agent_name: string; note: string; raw_input: string; created_at: string }>),
}

export const stakeholdersApi = {
  list: (slug: string): Promise<Stakeholder[]> =>
    apiClient.get<Stakeholder[]>(`/projects/${slug}/stakeholders`).then((r) => r.data),

  create: (slug: string, data: Omit<Stakeholder, 'id' | 'created_at'>): Promise<Stakeholder> =>
    apiClient.post<Stakeholder>(`/projects/${slug}/stakeholders`, data).then((r) => r.data),

  update: (
    slug: string,
    id: number,
    data: Omit<Stakeholder, 'id' | 'created_at'>,
  ): Promise<Stakeholder> =>
    apiClient.put<Stakeholder>(`/projects/${slug}/stakeholders/${id}`, data).then((r) => r.data),

  remove: (slug: string, id: number): Promise<void> =>
    apiClient.delete(`/projects/${slug}/stakeholders/${id}`).then(() => undefined),

  importCsv: (slug: string, file: File): Promise<StakeholderImportResult> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient
      .post<StakeholderImportResult>(`/projects/${slug}/stakeholders/import`, form)
      .then((r) => r.data)
  },
}

export const stakeholderNodeAssignmentsApi = {
  list: (slug: string): Promise<StakeholderNodeAssignment[]> =>
    apiClient.get<StakeholderNodeAssignment[]>(`/projects/${slug}/stakeholder-assignments`).then((r) => r.data),

  save: (slug: string, assignments: { stakeholder_id: number; node_key: string }[]): Promise<{ count: number }> =>
    apiClient
      .put<{ count: number }>(`/projects/${slug}/stakeholder-assignments`, { assignments })
      .then((r) => r.data),
}

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

export const milestonesApi = {
  list: (slug: string): Promise<Milestone[]> =>
    apiClient.get<Milestone[]>(`/projects/${slug}/milestones`).then((r) => r.data),

  seed: (slug: string): Promise<Milestone[]> =>
    apiClient.post<Milestone[]>(`/projects/${slug}/milestones/seed`).then((r) => r.data),

  create: (slug: string, data: { title: string; description?: string; due_date?: string | null; notes?: string }): Promise<Milestone> =>
    apiClient.post<Milestone>(`/projects/${slug}/milestones`, data).then((r) => r.data),

  update: (slug: string, id: number, data: Partial<{ title: string; description: string; due_date: string | null; status: string; notes: string; sort_order: number }>): Promise<Milestone> =>
    apiClient.patch<Milestone>(`/projects/${slug}/milestones/${id}`, data).then((r) => r.data),

  remove: (slug: string, id: number): Promise<void> =>
    apiClient.delete(`/projects/${slug}/milestones/${id}`).then(() => undefined),
}
