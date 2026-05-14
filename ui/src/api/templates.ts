// ui/src/api/templates.ts
import { apiClient } from './client'
import type { TemplateListItem, TemplateDetail } from '../types'

const BASE = '/api/templates'

export const listTemplates = (type?: string): Promise<TemplateListItem[]> =>
  apiClient.get<TemplateListItem[]>(`${BASE}${type ? `?type=${type}` : ''}`).then((r) => r.data)

export const getTemplate = (id: number): Promise<TemplateDetail> =>
  apiClient.get<TemplateDetail>(`${BASE}/${id}`).then((r) => r.data)

export const createTemplate = (body: Partial<TemplateDetail>): Promise<TemplateListItem> =>
  apiClient.post<TemplateListItem>(BASE, body).then((r) => r.data)

export const updateTemplate = (id: number, body: Partial<TemplateDetail>): Promise<TemplateDetail> =>
  apiClient.patch<TemplateDetail>(`${BASE}/${id}`, body).then((r) => r.data)

export const deleteTemplate = (id: number): Promise<void> =>
  apiClient.delete(`${BASE}/${id}`).then(() => undefined)
