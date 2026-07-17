// ui/src/components/AgentChatDrawer.tsx
import { useState, useEffect, useRef, useMemo } from 'react'
import { Loader, Link, Paperclip, X } from 'lucide-react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { agentChatApi } from '../api/agentChat'
import type { InjectedDoc, InjectedLink } from '../api/agentChat'
import { AGENT_AVATAR, AGENT_SKILLS, AGENT_ROLE, CREW_AGENTS, getIdleStatus } from './agentStatus'
import type { CrewRun } from '../types'

// Configure marked for inline use - no async, GFM tables and line breaks enabled
marked.use({ async: false, gfm: true, breaks: true })

type Tab = 'status' | 'chat' | 'skills'

interface Message {
  role: 'user' | 'agent'
  content: string
}

type DocAttachment = { type: 'doc' } & InjectedDoc
type LinkAttachment = { type: 'link' } & InjectedLink
type Attachment = DocAttachment | LinkAttachment

interface StatusEvent {
  ts: number
  icon: string
  text: string
  sub?: string
}

export interface AgentChatDrawerProps {
  slug: string
  agentName: string | null
  onClose: () => void
  logs?: string[]
  crewRuns?: CrewRun[]
}

// ── Derive which crew this agent belongs to ────────────────────────────────────
function crewForAgent(agentName: string): string | null {
  for (const [crew, agents] of Object.entries(CREW_AGENTS)) {
    if (agents.includes(agentName)) return crew
  }
  return null
}

// ── Pretty-print tool names ────────────────────────────────────────────────────
const TOOL_LABELS: Record<string, string> = {
  ChromaQueryTool:        'Searching knowledge base',
  TavilySearchTool:       'Searching the web',
  WebFetchTool:           'Fetching web page',
  DocumentIngestionTool:  'Reading document',
  SQLiteStateTool:        'Reading project state',
  HumanInputTool:         'Requesting human input',
  MermaidRenderTool:      'Rendering diagram',
  HtmlRoadmapTool:        'Generating roadmap',
  ExcelOutputTool:        'Generating Excel file',
  WordOutputTool:         'Generating Word document',
  PowerPointOutputTool:   'Generating PowerPoint',
  FinancialModelTool:     'Running financial model',
  InterviewSessionTool:   'Managing interview session',
  RunCrewTool:            'Dispatching sub-crew',
  SlackNotifyTool:        'Sending Slack notification',
}

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? `Using ${name}`
}

// ── Parse WebSocket log events into human-readable status entries ──────────────
function parseStatusEvents(logs: string[], crewKey: string | null): StatusEvent[] {
  const events: StatusEvent[] = []
  for (const raw of logs) {
    try {
      const obj = JSON.parse(raw)
      if (crewKey && obj.crew && obj.crew !== crewKey) continue
      if (obj.type === 'crew_started') {
        events.push({ ts: Date.now(), icon: '▶', text: 'Started', sub: `Run #${obj.run_id}` })
      } else if (obj.type === 'crew_completed') {
        events.push({ ts: Date.now(), icon: '✓', text: 'Completed', sub: `Run #${obj.run_id}` })
      } else if (obj.type === 'crew_failed') {
        events.push({ ts: Date.now(), icon: '✗', text: 'Failed', sub: obj.error ?? '' })
      } else if (obj.type === 'agent_step') {
        events.push({ ts: Date.now(), icon: '💭', text: obj.text ?? 'Step complete', sub: obj.sub ?? undefined })
      } else if (obj.type === 'tool_use') {
        const label = toolLabel(obj.tool)
        events.push({ ts: Date.now(), icon: '🔧', text: label, sub: obj.input ?? undefined })
      }
    } catch {
      // plain text line - skip
    }
  }
  return events
}

// ── Markdown message bubble ────────────────────────────────────────────────────

function MessageBubble({ role, content }: { role: 'user' | 'agent'; content: string }) {
  const html = useMemo(() => {
    if (role !== 'agent') return null
    return DOMPurify.sanitize(marked.parse(content) as string)
  }, [role, content])
  if (role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm px-3 py-2 text-sm bg-teal-600 text-white whitespace-pre-wrap">
          {content}
        </div>
      </div>
    )
  }
  return (
    <div className="flex justify-start">
      <div
        className="max-w-[85%] rounded-2xl rounded-bl-sm px-3 py-2 text-sm bg-gray-100 text-gray-800 prose prose-sm prose-gray max-w-none"
        dangerouslySetInnerHTML={{ __html: html! }}
      />
    </div>
  )
}

export default function AgentChatDrawer({
  slug, agentName, onClose, logs = [], crewRuns = [],
}: AgentChatDrawerProps) {
  const [tab, setTab] = useState<Tab>('status')
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [fileLoading, setFileLoading] = useState(false)
  const [showLinkInput, setShowLinkInput] = useState(false)
  const [linkUrl, setLinkUrl] = useState('')
  const [linkLabel, setLinkLabel] = useState('')
  const [linkLoading, setLinkLoading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const chatScrollRef = useRef<HTMLDivElement>(null)
  const statusScrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setMessages([]); setInput(''); setTab('status')
    setAttachments([]); setShowLinkInput(false); setLinkUrl(''); setLinkLabel('')
  }, [agentName])

  useEffect(() => {
    if (chatScrollRef.current) chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight
  }, [messages, loading])

  useEffect(() => {
    if (statusScrollRef.current) statusScrollRef.current.scrollTop = statusScrollRef.current.scrollHeight
  }, [logs])

  if (!agentName) return null

  const avatar = AGENT_AVATAR[agentName] ?? { emoji: '🤖', gradient: 'from-gray-400 to-gray-600' }
  const firstName = agentName.split(' ')[0]
  const crewKey = crewForAgent(agentName)
  const crewRun = crewKey ? crewRuns.find(r => r.crew_name === crewKey) : undefined
  const isRunning = crewRun?.status === 'running'
  const isDone = crewRun?.status === 'completed'
  const isFailed = crewRun?.status === 'failed'
  const role = AGENT_ROLE[agentName] ?? 'AI Agent'
  const skills = AGENT_SKILLS[agentName] ?? []
  const statusEvents = parseStatusEvents(logs, crewKey)

  async function sendMessage() {
    if (!input.trim() || loading) return
    const userMessage = input.trim()
    const currentAttachments = [...attachments]
    setInput('')
    setAttachments([])
    setShowLinkInput(false)
    setLinkUrl('')
    setLinkLabel('')
    const history = messages.map(m => ({ role: m.role === 'agent' ? 'assistant' : 'user', content: m.content }))
    setMessages(prev => [...prev, { role: 'user', content: userMessage }])
    setLoading(true)
    try {
      const injectedDocs = currentAttachments
        .filter((a): a is DocAttachment => a.type === 'doc')
        .map(({ doc_id, original_name, preview_text, is_image }) => ({ doc_id, original_name, preview_text, is_image }))
      const injectedLinks = currentAttachments
        .filter((a): a is LinkAttachment => a.type === 'link')
        .map(({ url, label, content_preview }) => ({ url, label, content_preview }))
      const { response } = await agentChatApi.send(slug, agentName!, agentName!, [agentName!], userMessage, history, injectedDocs, injectedLinks)
      setMessages(prev => [...prev, { role: 'agent', content: response }])
    } catch {
      setMessages(prev => [...prev, { role: 'agent', content: 'Sorry, I could not process that request. Please try again.' }])
    } finally {
      setLoading(false)
    }
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !agentName) return
    e.target.value = ''
    setFileLoading(true)
    try {
      const result = await agentChatApi.uploadFile(slug, agentName, file)
      setAttachments(prev => [...prev, { type: 'doc', ...result }])
    } catch {
      // silently fail — user can retry
    } finally {
      setFileLoading(false)
    }
  }

  async function handleAddLink() {
    if (!linkUrl.trim() || !agentName || linkLoading) return
    setLinkLoading(true)
    try {
      const result = await agentChatApi.addLink(slug, agentName, linkUrl.trim(), linkLabel.trim())
      setAttachments(prev => [...prev, { type: 'link', ...result }])
      setShowLinkInput(false)
      setLinkUrl('')
      setLinkLabel('')
    } catch {
      // silently fail
    } finally {
      setLinkLoading(false)
    }
  }

  function removeAttachment(index: number) {
    setAttachments(prev => prev.filter((_, i) => i !== index))
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'status', label: 'Status' },
    { key: 'chat',   label: 'Chat' },
    { key: 'skills', label: 'Skills' },
  ]

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />

      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
      <div className="bg-white rounded-2xl shadow-2xl flex flex-col w-full max-w-lg h-[85vh] pointer-events-auto">

        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-200 flex-shrink-0">
          <div className={`w-10 h-10 rounded-full bg-gradient-to-br ${avatar.gradient} flex items-center justify-center text-xl flex-shrink-0`}>
            {avatar.emoji}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-900 truncate">{agentName}</p>
            <p className="text-xs text-gray-400 truncate">{role.split('—')[0].trim()}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none flex-shrink-0" aria-label="Close">✕</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-200 flex-shrink-0">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex-1 py-2 text-xs font-semibold transition-colors ${
                tab === t.key
                  ? 'text-teal-700 border-b-2 border-teal-600 bg-teal-50/40'
                  : 'text-gray-500 hover:text-gray-700 border-b-2 border-transparent'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* ── STATUS TAB ──────────────────────────────────────────────────────── */}
        {tab === 'status' && (
          <div ref={statusScrollRef} className="flex-1 overflow-y-auto p-4 space-y-5">

            {/* Live status pill */}
            <div className="flex items-center gap-2">
              {isRunning ? (
                <span className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-teal-50 text-teal-700 border border-teal-200">
                  <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse inline-block" />
                  Running
                </span>
              ) : isDone ? (
                <span className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-green-50 text-green-700 border border-green-200">
                  ✓ Completed
                </span>
              ) : isFailed ? (
                <span className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-red-50 text-red-700 border border-red-200">
                  ✗ Failed
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-gray-50 text-gray-500 border border-gray-200">
                  {getIdleStatus(agentName ?? 'agent', crewRun?.id ?? 0)}
                </span>
              )}
              {crewRun?.started_at && (
                <span className="text-[10px] text-gray-400">
                  Started {new Date(crewRun.started_at + 'Z').toLocaleTimeString()}
                </span>
              )}
            </div>

            {/* Role card */}
            <div className="rounded-lg bg-gray-50 border border-gray-100 p-3">
              <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Role</p>
              <p className="text-xs text-gray-700 leading-relaxed">{role}</p>
            </div>

            {/* Activity feed */}
            {statusEvents.length > 0 ? (
              <div>
                <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">
                  Activity · {statusEvents.length} event{statusEvents.length !== 1 ? 's' : ''}
                </p>
                <div className="space-y-1.5">
                  {statusEvents.map((ev, i) => {
                    const isLast = i === statusEvents.length - 1
                    const isToolUse = ev.icon === '🔧'
                    return (
                      <div
                        key={i}
                        className={`flex gap-2 items-start rounded-lg px-2 py-1.5 ${
                          isLast && isRunning
                            ? 'bg-teal-50 border border-teal-100'
                            : isToolUse
                              ? 'bg-amber-50 border border-amber-100'
                              : 'bg-gray-50 border border-gray-100'
                        }`}
                      >
                        <span className="text-sm flex-shrink-0 mt-0.5 w-5 text-center">{ev.icon}</span>
                        <div className="min-w-0 flex-1">
                          <p className={`text-xs font-medium ${isLast && isRunning ? 'text-teal-800' : 'text-gray-800'}`}>
                            {ev.text}
                            {isLast && isRunning && (
                              <span className="ml-1.5 inline-block w-1 h-1 rounded-full bg-teal-500 animate-pulse align-middle" />
                            )}
                          </p>
                          {ev.sub && (
                            <p className="text-[10px] text-gray-500 mt-0.5 truncate" title={ev.sub}>{ev.sub}</p>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ) : isRunning ? (
              <div className="flex flex-col items-center gap-3 py-8 text-center">
                <div className={`w-16 h-16 rounded-full bg-gradient-to-br ${avatar.gradient} flex items-center justify-center text-3xl`}>
                  {avatar.emoji}
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-700 animate-pulse">{firstName} is working…</p>
                  <p className="text-xs text-gray-400 mt-1">Tool usage and step events will appear here</p>
                </div>
              </div>
            ) : (
              <p className="text-xs text-gray-400 text-center py-8">No activity yet - run the crew to see updates here.</p>
            )}
          </div>
        )}

        {/* ── CHAT TAB ────────────────────────────────────────────────────────── */}
        {tab === 'chat' && (
          <>
            <div ref={chatScrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
              {messages.length === 0 && (
                <p className="text-xs text-gray-400 text-center py-8">Ask {firstName} anything about this project…</p>
              )}
              {messages.map((msg, i) => (
                <MessageBubble key={i} role={msg.role} content={msg.content} />
              ))}
              {loading && (
                <div className="flex justify-start">
                  <div className="bg-gray-100 rounded-2xl rounded-bl-sm px-4 py-2">
                    <span className="text-gray-400 text-sm animate-pulse">···</span>
                  </div>
                </div>
              )}
            </div>
            <div className="border-t border-gray-200 px-4 py-3 flex-shrink-0">
              {/* Attachment chips */}
              {attachments.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {attachments.map((att, i) => (
                    <div key={i} className="flex items-center gap-1 bg-teal-50 border border-teal-200 rounded-full px-2 py-0.5 text-xs text-teal-700">
                      {att.type === 'doc' ? <Paperclip size={10} className="flex-shrink-0" /> : <Link size={10} className="flex-shrink-0" />}
                      <span className="max-w-[140px] truncate">
                        {att.type === 'doc' ? att.original_name : att.label}
                      </span>
                      <button onClick={() => removeAttachment(i)} className="text-teal-400 hover:text-teal-700 ml-0.5 flex-shrink-0">
                        <X size={10} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* URL input row */}
              {showLinkInput && (
                <div className="flex gap-1.5 mb-2">
                  <input
                    type="url"
                    value={linkUrl}
                    onChange={e => setLinkUrl(e.target.value)}
                    placeholder="https://…"
                    autoFocus
                    className="flex-1 border border-gray-200 rounded-lg px-2 py-1.5 text-xs text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-teal-500"
                    onKeyDown={e => { if (e.key === 'Enter') handleAddLink(); if (e.key === 'Escape') { setShowLinkInput(false); setLinkUrl(''); setLinkLabel('') } }}
                  />
                  <input
                    type="text"
                    value={linkLabel}
                    onChange={e => setLinkLabel(e.target.value)}
                    placeholder="Label"
                    className="w-24 border border-gray-200 rounded-lg px-2 py-1.5 text-xs text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-teal-500"
                  />
                  <button
                    onClick={handleAddLink}
                    disabled={!linkUrl.trim() || linkLoading}
                    className="bg-teal-600 text-white text-xs font-medium px-2.5 py-1.5 rounded-lg disabled:opacity-40 flex-shrink-0"
                  >
                    {linkLoading ? <Loader size={11} className="animate-spin" /> : 'Add'}
                  </button>
                  <button
                    onClick={() => { setShowLinkInput(false); setLinkUrl(''); setLinkLabel('') }}
                    className="text-gray-400 hover:text-gray-600 flex-shrink-0"
                  >
                    <X size={14} />
                  </button>
                </div>
              )}

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

              {/* Toolbar: attach file + add link */}
              <div className="flex items-center gap-2 mt-1.5">
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  onChange={handleFileChange}
                  accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp,.gif"
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={fileLoading}
                  title="Attach file (PDF, DOCX, TXT, image)"
                  className="flex items-center justify-center w-6 h-6 rounded text-gray-400 hover:text-teal-600 hover:bg-teal-50 transition-colors disabled:opacity-40"
                >
                  {fileLoading ? <Loader size={12} className="animate-spin" /> : <Paperclip size={12} />}
                </button>
                <button
                  onClick={() => setShowLinkInput(prev => !prev)}
                  title="Add web link"
                  className={`flex items-center justify-center w-6 h-6 rounded transition-colors ${showLinkInput ? 'text-teal-600 bg-teal-50' : 'text-gray-400 hover:text-teal-600 hover:bg-teal-50'}`}
                >
                  <Link size={12} />
                </button>
                <p className="text-[10px] text-gray-400 ml-auto">Enter to send · Shift+Enter for newline</p>
              </div>
            </div>
          </>
        )}

        {/* ── SKILLS TAB ──────────────────────────────────────────────────────── */}
        {tab === 'skills' && (
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {skills.length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-8">No skills defined for this agent.</p>
            ) : (
              <>
                <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
                  {skills.length} Skill{skills.length !== 1 ? 's' : ''}
                </p>
                {skills.map((skill, i) => (
                  <div key={i} className="flex gap-3 items-start rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5">
                    <skill.icon size={15} className="flex-shrink-0 mt-0.5 text-gray-400" />
                    <div>
                      <p className="text-xs font-semibold text-gray-800">{skill.name}</p>
                      <p className="text-[11px] text-gray-500 leading-relaxed mt-0.5">{skill.description}</p>
                    </div>
                  </div>
                ))}
              </>
            )}
          </div>
        )}

      </div>
      </div>
    </>
  )
}
