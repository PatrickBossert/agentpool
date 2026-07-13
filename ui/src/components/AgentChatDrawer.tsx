// ui/src/components/AgentChatDrawer.tsx
import { useState, useEffect, useRef } from 'react'
import { agentChatApi } from '../api/agentChat'
import { AGENT_AVATAR } from './agentStatus'

interface Message {
  role: 'user' | 'agent'
  content: string
}

export interface AgentChatDrawerProps {
  slug: string
  agentName: string | null   // null = drawer closed
  onClose: () => void
}

export default function AgentChatDrawer({ slug, agentName, onClose }: AgentChatDrawerProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Reset conversation when a different agent is opened
  useEffect(() => {
    setMessages([])
    setInput('')
  }, [agentName])

  // Auto-scroll to bottom when messages update
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, loading])

  if (!agentName) return null

  const avatar = AGENT_AVATAR[agentName as string] ?? { emoji: '🤖', gradient: 'from-gray-400 to-gray-600' }
  const firstName = (agentName as string).split(' ')[0]

  async function sendMessage() {
    if (!input.trim() || loading) return
    const userMessage = input.trim()
    setInput('')
    // Convert message history to the format the backend expects
    const history = messages.map(m => ({
      role: m.role === 'agent' ? 'assistant' : 'user',
      content: m.content,
    }))
    setMessages(prev => [...prev, { role: 'user', content: userMessage }])
    setLoading(true)
    try {
      const response = await agentChatApi.send(slug, agentName as string, userMessage, history)
      setMessages(prev => [...prev, { role: 'agent', content: response }])
    } catch {
      setMessages(prev => [...prev, {
        role: 'agent',
        content: 'Sorry, I could not process that request. Please try again.',
      }])
    } finally {
      setLoading(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/20 z-40" onClick={onClose} />

      {/* Drawer */}
      <div className="fixed right-0 top-0 bottom-0 w-[420px] bg-white shadow-2xl z-50 flex flex-col">
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-200 flex-shrink-0">
          <div
            className={`w-10 h-10 rounded-full bg-gradient-to-br ${avatar.gradient} flex items-center justify-center text-xl flex-shrink-0`}
          >
            {avatar.emoji}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-900 truncate">{agentName}</p>
            <p className="text-xs text-gray-400">AI Agent</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none flex-shrink-0"
            aria-label="Close chat"
          >
            ✕
          </button>
        </div>

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.length === 0 && (
            <p className="text-xs text-gray-400 text-center py-8">
              Ask {firstName} anything about this project…
            </p>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap ${
                  msg.role === 'user'
                    ? 'bg-teal-600 text-white rounded-br-sm'
                    : 'bg-gray-100 text-gray-800 rounded-bl-sm'
                }`}
              >
                {msg.content}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-gray-100 rounded-2xl rounded-bl-sm px-4 py-2">
                <span className="text-gray-400 text-sm animate-pulse">···</span>
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <div className="border-t border-gray-200 px-4 py-3 flex-shrink-0">
          <div className="flex gap-2 items-end">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`Ask ${firstName} something…`}
              rows={2}
              className="flex-1 resize-none border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-teal-500"
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || loading}
              className="bg-teal-600 hover:bg-teal-700 disabled:opacity-40 text-white text-sm font-medium px-3 py-2 rounded-lg transition-colors flex-shrink-0"
            >
              Send
            </button>
          </div>
          <p className="text-[10px] text-gray-400 mt-1">Enter to send · Shift+Enter for newline</p>
        </div>
      </div>
    </>
  )
}
