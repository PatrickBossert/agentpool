// ui/src/api/agentChat.ts

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
    const res = await fetch(`/api/projects/${slug}/agent-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_name: agentName, message, history }),
    })
    if (!res.ok) throw new Error(`Agent chat failed: ${res.status}`)
    const data = await res.json()
    return data.response as string
  },
}
