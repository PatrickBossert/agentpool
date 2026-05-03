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

  getSettings: (slug: string): Promise<ProjectSettings> =>
    apiClient.get<ProjectSettings>(`/projects/${slug}/settings`).then((r) => r.data),

  updateSettings: (slug: string, data: ProjectSettings): Promise<ProjectSettings> =>
    apiClient.patch<ProjectSettings>(`/projects/${slug}/settings`, data).then((r) => r.data),

  getOutputContent: (slug: string, outputId: number): Promise<OutputContent> =>
    apiClient.get<OutputContent>(`/projects/${slug}/outputs/${outputId}/content`).then((r) => r.data),

  roadmapData: (slug: string): Promise<RoadmapData> =>
    apiClient.get<RoadmapData>(`/projects/${slug}/roadmap-data`).then((r) => r.data),

  financialSummary: (slug: string): Promise<FinancialSummary> =>
    apiClient.get<FinancialSummary>(`/projects/${slug}/financial-summary`).then((r) => r.data),
}
