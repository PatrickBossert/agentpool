// ui/src/api/nodeTemplates.ts
import { apiClient } from './client'
import type { NodeTemplateAssignment } from '../types'

export const listNodeTemplates = (slug: string): Promise<NodeTemplateAssignment[]> =>
  apiClient.get<NodeTemplateAssignment[]>(`/projects/${slug}/node-templates`).then((r) => r.data)

export const putNodeTemplate = (
  slug: string,
  nodeLabel: string,
  body: { interview_template_id: number | null; questionnaire_template_id: number | null },
): Promise<{ ok: boolean }> =>
  apiClient
    .put<{ ok: boolean }>(`/projects/${slug}/node-templates/${encodeURIComponent(nodeLabel)}`, body)
    .then((r) => r.data)

export const publishNodeTemplate = (
  slug: string,
  nodeLabel: string,
  body: { name: string; description: string },
): Promise<{ template_id: number }> =>
  apiClient
    .post<{ template_id: number }>(
      `/projects/${slug}/node-templates/${encodeURIComponent(nodeLabel)}/publish`,
      body,
    )
    .then((r) => r.data)
