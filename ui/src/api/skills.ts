// ui/src/api/skills.ts
import { apiClient } from './client'

/**
 * Where a rule applies: the engagement it came from, or all of them.
 *
 * `project` is the narrow one and the default every proposal is filed at - a rule reaches only
 * the engagement `source_project` names until a reviewer widens it at approval.
 */
export type SkillScope = 'project' | 'global'

export interface AgentSkill {
  id: number
  agents: string[]
  name: string
  description: string
  source: string
  source_project: string | null
  source_ref: string | null
  proposed_by_agent: string | null
  // **Required, never optional.** CLAUDE.md records four `ProjectSettings` fields that survived
  // a save only because the object was spread untyped, and the cost here is worse than any of
  // them: a dropped `scope` does not lose a setting, it silently widens one engagement's rule
  // onto every engagement. Declared required so that a construction site which forgets it is a
  // compile error rather than a rule applying somewhere nobody chose.
  scope: SkillScope
  // How many times an agent has proposed this same rule. The review queue is sent
  // occurrences-descending by the server, so a rule seen three times arrives above one seen
  // once - the page renders what it is given and never re-sorts.
  occurrences: number
  status: 'pending' | 'approved' | 'rejected'
  flag_reason: string | null
  flag_suggestion: string | null
  created_at: string
  reviewed_at: string | null
  reviewed_by: string | null
}

/** One recorded sighting of a skill's rule - the evidence behind `occurrences`. */
export interface SkillOccurrence {
  id: number
  skill_id: number
  description: string
  source_project: string | null
  source_ref: string | null
  proposed_by_agent: string | null
  created_at: string
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
    agents: string[]
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
    // `scope` is optional on the wire and its absence means "leave the stored value alone",
    // matching `SkillUpdate` on the server. The queue always sends it; a caller editing a
    // library entry's wording has no opinion about where the rule applies and must not
    // restate one.
    data: {
      status?: string
      name?: string
      description?: string
      agents?: string[]
      scope?: SkillScope
    },
  ): Promise<AgentSkill> => {
    const res = await apiClient.patch(`/admin/skills/${id}`, data)
    return res.data
  },

  occurrences: async (id: number): Promise<SkillOccurrence[]> => {
    const res = await apiClient.get(`/admin/skills/${id}/occurrences`)
    return res.data
  },

  remove: async (id: number): Promise<void> => {
    await apiClient.delete(`/admin/skills/${id}`)
  },

  extract: async (raw_input: string): Promise<SkillExtract> => {
    const res = await apiClient.post('/admin/skills/extract', { raw_input })
    return res.data
  },

  extractMany: async (raw_input: string): Promise<SkillExtract[]> => {
    const res = await apiClient.post('/admin/skills/extract-many', { raw_input })
    return res.data
  },

  exportSkills: async (): Promise<AgentSkill[]> => {
    const res = await apiClient.get('/admin/skills/export')
    return res.data
  },

  importSkills: async (
    items: { agents: string[]; name: string; description: string }[],
  ): Promise<ImportResult> => {
    const res = await apiClient.post('/admin/skills/import', items)
    return res.data
  },

  seed: async (force = false): Promise<{ seeded: number }> => {
    const res = await apiClient.post(`/admin/skills/seed?force=${force}`)
    return res.data
  },
}
