// ui/src/api/endpoints.ts
import { apiClient } from './client'
import type {
  Project,
  ProjectStatus,
  AgentOutput,
  ClientDocument,
  TokenResponse,
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

  review: (slug: string, outputId: number, decision: string): Promise<void> =>
    apiClient
      .post(`/projects/${slug}/outputs/${outputId}/review`, { decision })
      .then(() => undefined),
}
