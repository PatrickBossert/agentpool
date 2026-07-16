// ui/src/api/skills.ts
import { apiClient } from './client'

export interface AgentSkill {
  id: number
  agent_name: string
  name: string
  description: string
  source: string
  source_project: string | null
  status: 'pending' | 'approved' | 'rejected'
  flag_reason: string | null
  flag_suggestion: string | null
  created_at: string
  reviewed_at: string | null
  reviewed_by: string | null
}

export interface SkillExtract {
  name: string
  description: string
}

export interface ImportResult {
  imported: number
  skipped: number
}

export const skillsApi = {
  list: async (params?: { status?: string; agent_name?: string }): Promise<AgentSkill[]> => {
    const query = new URLSearchParams()
    if (params?.status) query.set('status', params.status)
    if (params?.agent_name) query.set('agent_name', params.agent_name)
    const res = await apiClient.get(`/admin/skills?${query}`)
    return res.data
  },

  create: async (data: {
    agent_name: string
    name: string
    description: string
    source?: string
    source_project?: string | null
  }): Promise<AgentSkill> => {
    const res = await apiClient.post('/admin/skills', data)
    return res.data
  },

  update: async (
    id: number,
    data: { status?: string; name?: string; description?: string },
  ): Promise<AgentSkill> => {
    const res = await apiClient.patch(`/admin/skills/${id}`, data)
    return res.data
  },

  remove: async (id: number): Promise<void> => {
    await apiClient.delete(`/admin/skills/${id}`)
  },

  extract: async (raw_input: string): Promise<SkillExtract> => {
    const res = await apiClient.post('/admin/skills/extract', { raw_input })
    return res.data
  },

  exportSkills: async (): Promise<AgentSkill[]> => {
    const res = await apiClient.get('/admin/skills/export')
    return res.data
  },

  importSkills: async (
    items: { agent_name: string; name: string; description: string }[],
  ): Promise<ImportResult> => {
    const res = await apiClient.post('/admin/skills/import', items)
    return res.data
  },

  seed: async (): Promise<{ seeded: number }> => {
    const res = await apiClient.post('/admin/skills/seed')
    return res.data
  },
}
