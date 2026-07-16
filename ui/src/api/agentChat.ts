// ui/src/api/agentChat.ts
import { apiClient } from './client'

export interface ChatMessage {
  role: 'user' | 'agent'
  content: string
}

export interface InjectedDoc {
  doc_id: number
  original_name: string
  preview_text: string
  is_image: boolean
}

export interface InjectedLink {
  url: string
  label: string
  content_preview: string
}

export interface UploadResult {
  doc_id: number
  filename: string
  original_name: string
  preview_text: string
  is_image: boolean
}

export interface LinkResult {
  url: string
  label: string
  content_preview: string
}

export const agentChatApi = {
  send: async (
    slug: string,
    agentName: string,
    message: string,
    history: { role: string; content: string }[],
    injectedDocs: InjectedDoc[] = [],
    injectedLinks: InjectedLink[] = [],
  ): Promise<string> => {
    const res = await apiClient.post(`/projects/${slug}/agent-chat`, {
      agent_name: agentName,
      message,
      history,
      injected_docs: injectedDocs,
      injected_links: injectedLinks,
    })
    return res.data.response as string
  },

  uploadFile: async (
    slug: string,
    agentName: string,
    file: File,
  ): Promise<UploadResult> => {
    const form = new FormData()
    form.append('agent_name', agentName)
    form.append('file', file)
    const res = await apiClient.post(`/projects/${slug}/agent-chat/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return res.data as UploadResult
  },

  addLink: async (
    slug: string,
    agentName: string,
    url: string,
    label: string,
  ): Promise<LinkResult> => {
    const res = await apiClient.post(`/projects/${slug}/agent-chat/link`, {
      agent_name: agentName,
      url,
      label,
    })
    return res.data as LinkResult
  },
}
