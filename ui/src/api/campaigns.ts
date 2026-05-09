// ui/src/api/campaigns.ts
import { apiClient } from './client'
import type { Campaign, ReminderEmail, InterviewSummary, ImportResult } from '../types'

export const campaignsApi = {
  list: (slug: string): Promise<Campaign[]> =>
    apiClient.get<Campaign[]>(`/projects/${slug}/campaigns`).then((r) => r.data),

  create: (slug: string, data: Partial<Campaign>): Promise<Campaign> =>
    apiClient.post<Campaign>(`/projects/${slug}/campaigns`, data).then((r) => r.data),

  update: (slug: string, id: number, data: Partial<Campaign>): Promise<Campaign> =>
    apiClient.patch<Campaign>(`/projects/${slug}/campaigns/${id}`, data).then((r) => r.data),

  delete: (slug: string, id: number): Promise<void> =>
    apiClient.delete(`/projects/${slug}/campaigns/${id}`).then(() => undefined),

  exportTargets: (slug: string, id: number): string =>
    `${apiClient.defaults.baseURL}/projects/${slug}/campaigns/${id}/export-targets`,

  markInvited: (slug: string, id: number): Promise<{ marked: number }> =>
    apiClient.post<{ marked: number }>(`/projects/${slug}/campaigns/${id}/mark-invited`).then((r) => r.data),

  importProgress: (slug: string, id: number, file: File): Promise<ImportResult> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<ImportResult>(`/projects/${slug}/campaigns/${id}/import-progress`, form).then((r) => r.data)
  },

  importResults: (slug: string, id: number, file: File): Promise<ImportResult> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<ImportResult>(`/projects/${slug}/campaigns/${id}/import-results`, form).then((r) => r.data)
  },

  importSummary: (slug: string, id: number, file: File): Promise<{ ok: boolean }> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<{ ok: boolean }>(`/projects/${slug}/campaigns/${id}/import-summary`, form).then((r) => r.data)
  },

  generateReminders: (slug: string, id: number): Promise<{ created: number }> =>
    apiClient.post<{ created: number }>(`/projects/${slug}/campaigns/${id}/generate-reminders`).then((r) => r.data),

  interviewSummary: (slug: string): Promise<InterviewSummary> =>
    apiClient.get<InterviewSummary>(`/projects/${slug}/interview-summary`).then((r) => r.data),

  listReminderEmails: (slug: string): Promise<ReminderEmail[]> =>
    apiClient.get<ReminderEmail[]>(`/projects/${slug}/reminder-emails`).then((r) => r.data),

  updateReminderEmail: (
    slug: string,
    id: number,
    payload: { status: string; subject?: string; body?: string }
  ): Promise<{ ok: boolean }> =>
    apiClient.patch<{ ok: boolean }>(`/projects/${slug}/reminder-emails/${id}`, payload).then((r) => r.data),
}
