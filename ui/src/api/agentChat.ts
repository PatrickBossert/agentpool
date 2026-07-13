// ui/src/api/agentChat.ts
import { apiClient } from './client'

export interface ChatMessage {
  role: 'user' | 'agent'
  content: string
}

export const agentChatApi = {
  send: async (
    slug: string,
    agentName: string,
    message: string,
    history: { role: string; content: string }[],
  ): Promise<string> => {
    const res = await apiClient.post(`/projects/${slug}/agent-chat`, {
      agent_name: agentName,
      message,
      history,
    })
    return res.data.response as string
  },
}
