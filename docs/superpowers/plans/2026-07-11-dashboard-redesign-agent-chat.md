# Dashboard Redesign + Agent Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dark OrgChart dashboard with a clean white agent grid (illustrated avatars, live status, chat buttons) and add a slide-in chat drawer backed by Claude Haiku with per-agent personas and live project data.

**Architecture:** Flip Tailwind surface tokens to light values, replace `OrgChart` with new `AgentGrid` on the Dashboard, and wire a new `AgentChatDrawer` to a `POST /projects/{slug}/agent-chat` endpoint that builds a persona-aware system prompt, fetches live DB context, and calls Claude Haiku.

**Tech Stack:** React 18, TypeScript, Tailwind CSS v3, FastAPI, aiosqlite, Anthropic Python SDK (`claude-haiku-4-5-20251001`)

---

## File Map

| Action | Path |
|---|---|
| Modify | `ui/tailwind.config.js` |
| Modify | `ui/src/components/AppLayout.tsx` |
| Modify | `ui/src/pages/Dashboard.tsx` |
| Create | `ui/src/components/agentStatus.ts` |
| Create | `ui/src/components/AgentGrid.tsx` |
| Create | `ui/src/api/agentChat.ts` |
| Create | `ui/src/components/AgentChatDrawer.tsx` |
| Create | `api/services/agent_chat_service.py` |
| Create | `api/routers/agent_chat.py` |
| Create | `tests/test_agent_chat.py` |
| Modify | `api/main.py` |

---

## Task 1: Light Theme — Tailwind tokens + AppLayout

**Files:**
- Modify: `ui/tailwind.config.js`
- Modify: `ui/src/components/AppLayout.tsx`

- [ ] **Step 1: Flip surface tokens to light values in `ui/tailwind.config.js`**

Replace lines 13-17:

```js
surface: {
  DEFAULT: '#f9fafb',
  raised: '#ffffff',
  card: '#ffffff',
},
```

- [ ] **Step 2: Rewrite `ui/src/components/AppLayout.tsx` with light-theme classes**

Replace the entire file with:

```tsx
// ui/src/components/AppLayout.tsx
import { useState } from 'react'
import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import NewProjectModal from './NewProjectModal'
import type { Project } from '../types'

export default function AppLayout() {
  const { slug } = useParams<{ slug?: string }>()
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [showModal, setShowModal] = useState(false)

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    refetchInterval: 10_000,
  })

  const { data: reviews = [] } = useQuery({
    queryKey: ['reviews', slug],
    queryFn: () => projectsApi.listReviews(slug!),
    enabled: !!slug,
    refetchInterval: 5000,
  })
  const pendingReviewCount = reviews.length

  function handleLogout() {
    logout()
    navigate('/login')
  }

  type NavItem = { to: string; label: string; end?: boolean; badge?: number }

  const navItems: NavItem[] = slug
    ? [
        { to: `/${slug}`, label: 'Dashboard', end: true },
        { to: `/${slug}/value-chain`, label: 'Value Chain' },
        { to: `/${slug}/discovery`, label: 'Discovery' },
        { to: `/${slug}/value-propositions`, label: 'Value Propositions' },
        { to: `/${slug}/roadmap`, label: 'Roadmap' },
        { to: `/${slug}/business-plan`, label: 'Business Plan' },
        { to: `/${slug}/stakeholders`, label: 'Stakeholders' },
        { to: `/${slug}/templates`, label: 'Templates' },
        { to: `/${slug}/reviews`, label: 'Reviews', badge: pendingReviewCount > 0 ? pendingReviewCount : undefined },
        { to: `/${slug}/runs`, label: 'Runs' },
        { to: `/${slug}/documents`, label: 'Documents' },
      ]
    : [{ to: '/', label: 'Dashboard', end: true }]

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Top nav */}
      <header className="bg-white border-b border-gray-200 px-4 h-12 flex items-center gap-6">
        <span className="font-bold text-brand text-sm tracking-wide">FutureMomentum</span>
        <nav className="flex gap-4 overflow-x-auto">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `text-sm pb-0.5 border-b-2 transition-colors flex items-center gap-1.5 whitespace-nowrap ${
                  isActive
                    ? 'text-brand border-brand'
                    : 'text-gray-500 border-transparent hover:text-gray-800'
                }`
              }
            >
              {item.label}
              {item.badge !== undefined && (
                <span className="bg-amber-500 text-white text-xs font-bold rounded-full px-1.5 leading-4 min-w-[18px] text-center">
                  {item.badge}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 flex-shrink-0">
          {slug && (
            <>
              <a
                href="http://localhost:8001"
                target="_blank"
                rel="noreferrer"
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                Chainlit ↗
              </a>
              <a
                href="http://localhost:5678"
                target="_blank"
                rel="noreferrer"
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                n8n ↗
              </a>
            </>
          )}
          <span className="text-xs text-gray-400">{user?.sub}</span>
          <button onClick={handleLogout} className="text-xs text-gray-400 hover:text-gray-600">
            Sign out
          </button>
        </div>
      </header>

      <div className="flex flex-1">
        {/* Sidebar */}
        <aside className="w-44 bg-white border-r border-gray-200 p-3 flex flex-col gap-1 flex-shrink-0">
          <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">
            Projects
          </p>
          {projects.map((p) => (
            <div key={p.slug} className="flex items-center gap-1">
              <button
                onClick={() => navigate(`/${p.slug}`)}
                className={`flex-1 text-left text-sm px-2 py-1.5 rounded-lg transition-colors ${
                  slug === p.slug
                    ? 'bg-teal-50 text-teal-700 font-medium'
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                }`}
              >
                {p.slug}
              </button>
              {slug === p.slug && (
                <button
                  onClick={() => navigate(`/${p.slug}/settings`)}
                  className="text-gray-400 hover:text-gray-600 text-sm px-1 flex-shrink-0"
                  title="Settings"
                >
                  ⚙
                </button>
              )}
            </div>
          ))}
          {projects.length === 0 && (
            <p className="text-xs text-gray-400 px-2">No projects yet</p>
          )}

          {/* Admin nav */}
          {(user?.role === 'sysadmin' || user?.role === 'org_admin') && (
            <div className="mt-auto pt-3 border-t border-gray-200">
              <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-2 px-2">
                Admin
              </p>
              {user.role === 'sysadmin' && (
                <button
                  onClick={() => navigate('/admin')}
                  className="w-full text-left text-sm px-2 py-1.5 rounded-lg transition-colors text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                >
                  Admin Panel
                </button>
              )}
              {user.role === 'org_admin' && (
                <button
                  onClick={() => navigate('/org')}
                  className="w-full text-left text-sm px-2 py-1.5 rounded-lg transition-colors text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                >
                  Team
                </button>
              )}
              <button
                onClick={() => navigate('/admin/users')}
                className="w-full text-left text-sm px-2 py-1.5 rounded-lg transition-colors text-gray-600 hover:bg-gray-100 hover:text-gray-900"
              >
                Users
              </button>
            </div>
          )}

          {/* New Project button */}
          <div className={user?.role === 'sysadmin' || user?.role === 'org_admin' ? 'pt-3' : 'mt-auto pt-3'}>
            <button
              onClick={() => setShowModal(true)}
              className="w-full text-xs text-gray-500 hover:text-gray-700 border border-gray-200 hover:border-gray-400 rounded-lg px-2 py-1.5 transition-colors text-left"
            >
              + New Project
            </button>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-auto bg-gray-50">
          <Outlet />
        </main>
      </div>

      {showModal && <NewProjectModal onClose={() => setShowModal(false)} />}
    </div>
  )
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add ui/tailwind.config.js ui/src/components/AppLayout.tsx
git commit -m "feat: switch app shell to light white theme"
```

---

## Task 2: Agent Status Utility

**Files:**
- Create: `ui/src/components/agentStatus.ts`

- [ ] **Step 1: Create `ui/src/components/agentStatus.ts`**

```typescript
// ui/src/components/agentStatus.ts
import type { CrewRun } from '../types'

export const CREW_ORDER = [
  'discovery',
  'value_design',
  'architecture',
  'delivery',
  'business_plan',
] as const

export type CrewName = (typeof CREW_ORDER)[number] | 'discovery_interviews'

export const CREW_LABELS: Record<string, string> = {
  discovery:            'Discovery',
  discovery_interviews: 'Discovery Interviews',
  value_design:         'Value Design',
  architecture:         'Architecture',
  delivery:             'Delivery',
  business_plan:        'Business Plan',
}

export const CREW_AGENTS: Record<string, string[]> = {
  discovery: [
    'Value Chain Mapper',
    'Requirements Capture',
    'Requirements Analyst',
    'Value Lever Analyst',
  ],
  discovery_interviews: [
    'Interview Script Designer',
    'Interview Coordinator',
    'Stakeholder Interviewer',
    'Synthesis Analyst',
  ],
  value_design:  ['Value Proposition Generator', 'Portfolio Manager'],
  architecture:  ['Enterprise Architect', 'Initiative Identifier'],
  delivery:      ['Roadmap Generator'],
  business_plan: ['Business Plan Generator'],
}

export const CREW_ICONS: Record<string, string> = {
  discovery:            '🔍',
  discovery_interviews: '🎙️',
  value_design:         '⭐',
  architecture:         '🏛️',
  delivery:             '🚀',
  business_plan:        '📊',
}

export const AGENT_AVATAR: Record<string, { emoji: string; gradient: string }> = {
  'Value Chain Mapper':          { emoji: '🗺️', gradient: 'from-teal-400 to-cyan-600' },
  'Requirements Capture':        { emoji: '📋', gradient: 'from-indigo-400 to-blue-600' },
  'Requirements Analyst':        { emoji: '🔍', gradient: 'from-violet-400 to-purple-600' },
  'Value Lever Analyst':         { emoji: '⚖️', gradient: 'from-amber-400 to-orange-500' },
  'Interview Script Designer':   { emoji: '✍️', gradient: 'from-rose-400 to-pink-600' },
  'Interview Coordinator':       { emoji: '📅', gradient: 'from-emerald-400 to-teal-600' },
  'Stakeholder Interviewer':     { emoji: '🎙️', gradient: 'from-sky-400 to-blue-600' },
  'Synthesis Analyst':           { emoji: '🧩', gradient: 'from-purple-400 to-indigo-600' },
  'Value Proposition Generator': { emoji: '💡', gradient: 'from-yellow-400 to-amber-500' },
  'Portfolio Manager':           { emoji: '📊', gradient: 'from-green-400 to-emerald-600' },
  'Enterprise Architect':        { emoji: '🏛️', gradient: 'from-slate-400 to-gray-600' },
  'Initiative Identifier':       { emoji: '🎯', gradient: 'from-red-400 to-rose-600' },
  'Roadmap Generator':           { emoji: '🛣️', gradient: 'from-cyan-400 to-teal-600' },
  'Business Plan Generator':     { emoji: '📈', gradient: 'from-lime-400 to-green-600' },
}

export type AgentStatus = 'running' | 'completed' | 'queued' | 'idle'
export type CrewStatus  = 'running' | 'completed' | 'failed' | 'queued' | 'idle'

export function inferAgentStatuses(crewKey: string, logs: string[]): AgentStatus[] {
  const agents = CREW_AGENTS[crewKey] ?? []
  const joined = logs.join('\n').toLowerCase()
  let lastIdx = -1
  agents.forEach((agent, idx) => {
    if (joined.includes(agent.toLowerCase())) lastIdx = idx
  })
  return agents.map((_, idx) => {
    if (lastIdx === -1) return 'queued'
    if (idx < lastIdx) return 'completed'
    if (idx === lastIdx) return 'running'
    return 'queued'
  })
}

export function getCrewStatus(
  crewRun: CrewRun | undefined,
  isActive: boolean,
  isPipelineActive: boolean,
): CrewStatus {
  if (isActive) return 'running'
  if (crewRun?.status === 'completed') return 'completed'
  if (crewRun?.status === 'failed') return 'failed'
  if (isPipelineActive) return 'queued'
  return 'idle'
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add ui/src/components/agentStatus.ts
git commit -m "feat: add agentStatus utility (avatars, crews, status helpers)"
```

---

## Task 3: AgentGrid Component

**Files:**
- Create: `ui/src/components/AgentGrid.tsx`

- [ ] **Step 1: Create `ui/src/components/AgentGrid.tsx`**

```tsx
// ui/src/components/AgentGrid.tsx
import { useMemo } from 'react'
import type { CrewRun } from '../types'
import {
  CREW_ORDER, CREW_LABELS, CREW_AGENTS, CREW_ICONS, AGENT_AVATAR,
  inferAgentStatuses, getCrewStatus,
  type AgentStatus, type CrewStatus,
} from './agentStatus'

// ── Status dot ─────────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: AgentStatus }) {
  const dot =
    status === 'running'   ? 'bg-teal-500 animate-pulse' :
    status === 'completed' ? 'bg-green-500' :
    status === 'queued'    ? 'bg-gray-300' :
                             'bg-gray-200'
  const label =
    status === 'running'   ? 'running' :
    status === 'completed' ? 'done' :
    status === 'queued'    ? 'queued' :
                             'idle'
  return (
    <span className="flex items-center gap-1">
      <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${dot}`} />
      <span className="text-[10px] text-gray-400 leading-none">{label}</span>
    </span>
  )
}

// ── AgentCard ──────────────────────────────────────────────────────────────────

function AgentCard({ name, status, onClick }: {
  name: string
  status: AgentStatus
  onClick: () => void
}) {
  const avatar = AGENT_AVATAR[name] ?? { emoji: '🤖', gradient: 'from-gray-400 to-gray-600' }
  return (
    <button
      onClick={onClick}
      className="group bg-white border border-gray-100 rounded-xl p-4 flex flex-col items-center gap-2 shadow-sm hover:shadow-md hover:border-teal-200 transition-all w-full"
    >
      <div
        className={`w-14 h-14 rounded-full bg-gradient-to-br ${avatar.gradient} flex items-center justify-center text-2xl shadow-sm flex-shrink-0`}
      >
        {avatar.emoji}
      </div>
      <p className="text-xs font-semibold text-gray-700 text-center leading-tight line-clamp-2 w-full">
        {name}
      </p>
      <StatusDot status={status} />
      <span className="text-[10px] text-teal-600 opacity-0 group-hover:opacity-100 transition-opacity font-medium">
        Chat ↗
      </span>
    </button>
  )
}

// ── Crew status badge ──────────────────────────────────────────────────────────

function CrewStatusBadge({ status }: { status: CrewStatus }) {
  if (status === 'idle') return null
  const cls =
    status === 'running'   ? 'bg-teal-50 text-teal-700 border-teal-200' :
    status === 'completed' ? 'bg-green-50 text-green-700 border-green-200' :
    status === 'failed'    ? 'bg-red-50 text-red-700 border-red-200' :
                             'bg-gray-50 text-gray-500 border-gray-200'
  const label =
    status === 'running'   ? '● Running' :
    status === 'completed' ? '✓ Done' :
    status === 'failed'    ? '✗ Failed' :
                             '○ Queued'
  return (
    <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${cls}`}>
      {label}
    </span>
  )
}

// ── AgentGrid ──────────────────────────────────────────────────────────────────

export interface AgentGridProps {
  crewRuns: CrewRun[]
  isPipelineActive: boolean
  logs: string[]
  onAgentChat: (agentName: string) => void
}

const ALL_CREWS = [...CREW_ORDER, 'discovery_interviews' as const]

export default function AgentGrid({ crewRuns, isPipelineActive, logs, onAgentChat }: AgentGridProps) {
  const runMap = useMemo(() => new Map(crewRuns.map(r => [r.crew_name, r])), [crewRuns])
  const activeCrewName = useMemo(() => crewRuns.find(r => r.status === 'running')?.crew_name, [crewRuns])
  const showDiscoveryInterviews = runMap.has('discovery_interviews') || activeCrewName === 'discovery_interviews'

  const crewsToShow = ALL_CREWS.filter(c => c !== 'discovery_interviews' || showDiscoveryInterviews)

  return (
    <div className="space-y-8">
      {crewsToShow.map(crewKey => {
        const crewRun = runMap.get(crewKey)
        const isActive = activeCrewName === crewKey
        const crewStatus = getCrewStatus(crewRun, isActive, isPipelineActive)
        const agents = CREW_AGENTS[crewKey] ?? []
        const agentStatuses: AgentStatus[] = isActive
          ? inferAgentStatuses(crewKey, logs)
          : crewStatus === 'completed'
            ? agents.map(() => 'completed' as AgentStatus)
            : agents.map(() => (isPipelineActive ? 'queued' : 'idle') as AgentStatus)

        return (
          <div key={crewKey}>
            <div className="flex items-center gap-2 mb-4">
              <span className="text-base leading-none">{CREW_ICONS[crewKey]}</span>
              <h3 className="text-xs font-bold text-gray-500 uppercase tracking-widest">
                {CREW_LABELS[crewKey]}
              </h3>
              <CrewStatusBadge status={crewStatus} />
            </div>
            <div
              className="grid gap-3"
              style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))' }}
            >
              {agents.map((agent, idx) => (
                <AgentCard
                  key={agent}
                  name={agent}
                  status={agentStatuses[idx]}
                  onClick={() => onAgentChat(agent)}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add ui/src/components/AgentGrid.tsx
git commit -m "feat: add AgentGrid component with illustrated agent cards"
```

---

## Task 4: Agent Chat API Client + Drawer Component

**Files:**
- Create: `ui/src/api/agentChat.ts`
- Create: `ui/src/components/AgentChatDrawer.tsx`

- [ ] **Step 1: Create `ui/src/api/agentChat.ts`**

```typescript
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
```

- [ ] **Step 2: Create `ui/src/components/AgentChatDrawer.tsx`**

```tsx
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

  const avatar = AGENT_AVATAR[agentName] ?? { emoji: '🤖', gradient: 'from-gray-400 to-gray-600' }
  const firstName = agentName.split(' ')[0]

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
      const response = await agentChatApi.send(slug, agentName, userMessage, history)
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
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add ui/src/api/agentChat.ts ui/src/components/AgentChatDrawer.tsx
git commit -m "feat: add AgentChatDrawer and agentChat API client"
```

---

## Task 5: Update Dashboard

**Files:**
- Modify: `ui/src/pages/Dashboard.tsx`

- [ ] **Step 1: Replace the entire `ui/src/pages/Dashboard.tsx`**

```tsx
// ui/src/pages/Dashboard.tsx
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import ReviewQueue from '../components/ReviewQueue'
import AgentGrid from '../components/AgentGrid'
import AgentChatDrawer from '../components/AgentChatDrawer'
import { useWebSocket } from '../hooks/useWebSocket'
import type { CrewRun } from '../types'

export default function Dashboard() {
  const { slug } = useParams<{ slug?: string }>()
  const navigate = useNavigate()
  const logs = useWebSocket(slug)
  const [activeAgent, setActiveAgent] = useState<string | null>(null)

  const { data: status } = useQuery({
    queryKey: ['status', slug],
    queryFn: () => projectsApi.status(slug!),
    enabled: !!slug,
    refetchInterval: 5_000,
  })

  const { data: outputs = [] } = useQuery({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.outputs(slug!),
    enabled: !!slug,
    refetchInterval: 5_000,
  })

  const { data: runs = [] } = useQuery({
    queryKey: ['runs', slug],
    queryFn: () => projectsApi.listRuns(slug!),
    enabled: !!slug,
  })

  const runMutation = useMutation({
    mutationFn: () => projectsApi.orchestrate(slug!),
    onSuccess: (data) => {
      navigate(`/${slug}/runs/${data.orchestration_run_id}`)
    },
  })

  if (!slug) {
    return (
      <div className="p-8 text-gray-400">
        <p>Select a project from the sidebar to begin.</p>
      </div>
    )
  }

  const crewRuns: CrewRun[] = status?.crew_runs ?? []
  const orch = status?.latest_orchestration_run
  const isPipelineActive = orch?.status === 'running'

  return (
    <div className="p-6 space-y-8">
      {/* Project header */}
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold text-gray-900">{slug}</h2>
        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={() => window.open(`/dashboard/${slug}/report`, '_blank')}
            className="text-xs px-3 py-1.5 rounded-lg bg-white border border-gray-200 text-gray-600 hover:text-gray-900 hover:border-gray-400 transition-colors"
          >
            Export Report
          </button>
          {(orch?.status === 'completed' || orch?.status === 'failed') && (
            <button
              onClick={() => navigate(`/${slug}/runs/${orch.id}`)}
              className="text-xs text-teal-600 hover:text-teal-700"
            >
              View Last Run →
            </button>
          )}
          {isPipelineActive ? (
            <span className="text-xs font-medium text-teal-600 animate-pulse">● Pipeline running</span>
          ) : (
            <button
              onClick={() => runMutation.mutate()}
              disabled={runMutation.isPending}
              className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-700 disabled:opacity-50 text-white transition-colors"
            >
              {runMutation.isPending ? 'Starting…' : '▶ Run Pipeline'}
            </button>
          )}
        </div>
      </div>

      {/* Agent grid */}
      <section>
        <AgentGrid
          crewRuns={crewRuns}
          isPipelineActive={isPipelineActive}
          logs={logs}
          onAgentChat={setActiveAgent}
        />
      </section>

      {/* Review queue */}
      <section>
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">
          Review Queue
        </h3>
        <ReviewQueue slug={slug} outputs={outputs} />
      </section>

      {/* Agent chat drawer — rendered at root of Dashboard so it overlays everything */}
      <AgentChatDrawer
        slug={slug}
        agentName={activeAgent}
        onClose={() => setActiveAgent(null)}
      />
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit
```

Expected: no errors (Dashboard no longer imports OrgChart or campaignsApi — those imports are cleanly removed)

- [ ] **Step 3: Commit**

```bash
git add ui/src/pages/Dashboard.tsx
git commit -m "feat: replace OrgChart with AgentGrid on Dashboard, add chat drawer"
```

---

## Task 6: Backend Tests (TDD — write failing tests first)

**Files:**
- Create: `tests/test_agent_chat.py`

- [ ] **Step 1: Create `tests/test_agent_chat.py` with failing tests**

```python
# tests/test_agent_chat.py
"""Tests for POST /projects/{slug}/agent-chat."""
import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock


@pytest_asyncio.fixture
async def chat_project():
    """Seed /tmp/agentpool_test/chatproj.db for agent chat tests."""
    db_path = Path("/tmp/agentpool_test/chatproj.db")
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                llm_mode TEXT NOT NULL DEFAULT 'standard',
                sector TEXT,
                config_json TEXT,
                status TEXT NOT NULL DEFAULT 'created',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS orchestration_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            );
            CREATE TABLE IF NOT EXISTS crew_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                crew_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                result_json TEXT,
                started_at TEXT,
                finished_at TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS stakeholders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                job_title TEXT NOT NULL DEFAULT '',
                organisation TEXT NOT NULL DEFAULT '',
                stakeholder_groups TEXT DEFAULT '[]',
                project_role TEXT DEFAULT 'recipient',
                value_streams TEXT DEFAULT '[]',
                value_chain_stage TEXT DEFAULT '',
                activity TEXT DEFAULT '',
                disposition TEXT DEFAULT 'neutral',
                location TEXT DEFAULT '',
                country_code TEXT DEFAULT '',
                timezone TEXT DEFAULT '',
                preferred_language TEXT DEFAULT '',
                currency TEXT DEFAULT '',
                email TEXT DEFAULT '',
                slack_handle TEXT DEFAULT '',
                interview_status TEXT,
                interview_invited_at DATETIME,
                interview_completed_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS interview_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                orchestration_run_id INTEGER,
                stakeholder_id INTEGER NOT NULL,
                node_label TEXT NOT NULL,
                session_token TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                voice_config TEXT,
                transcript_json TEXT,
                ratings_json TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("INSERT OR IGNORE INTO projects (slug) VALUES ('chatproj')")
        await conn.execute(
            "INSERT OR IGNORE INTO stakeholders "
            "(project_id, name, job_title, organisation, interview_status) "
            "VALUES (1, 'Alice', 'CFO', 'Acme Ltd', 'completed')"
        )
        await conn.execute(
            "INSERT OR IGNORE INTO stakeholders "
            "(project_id, name, job_title, organisation, interview_status) "
            "VALUES (1, 'Bob', 'COO', 'Acme Ltd', NULL)"
        )
        await conn.execute(
            "INSERT OR IGNORE INTO interview_sessions "
            "(project_id, stakeholder_id, node_label, session_token, status) "
            "VALUES (1, 1, 'Goods-in', 'chat-tok-alpha', 'completed')"
        )
        await conn.execute(
            "INSERT OR IGNORE INTO interview_sessions "
            "(project_id, stakeholder_id, node_label, session_token, status) "
            "VALUES (1, 2, 'Goods-in', 'chat-tok-beta', 'pending')"
        )
        await conn.commit()
    yield
    db_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_agent_chat_unknown_agent_returns_404(client, chat_project):
    resp = await client.post(
        "/projects/chatproj/agent-chat",
        json={"agent_name": "Nonexistent Agent", "message": "hello", "history": []},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_chat_project_not_found_returns_404(client, chat_project):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="hi")]
    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls:
        inst = AsyncMock()
        inst.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = inst
        resp = await client.post(
            "/projects/doesnotexist/agent-chat",
            json={"agent_name": "Roadmap Generator", "message": "hello", "history": []},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_chat_returns_claude_response(client, chat_project):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Bob has not been interviewed yet.")]
    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls:
        inst = AsyncMock()
        inst.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = inst
        resp = await client.post(
            "/projects/chatproj/agent-chat",
            json={
                "agent_name": "Interview Coordinator",
                "message": "Who hasn't been interviewed?",
                "history": [],
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["response"] == "Bob has not been interviewed yet."


@pytest.mark.asyncio
async def test_agent_chat_interview_context_in_system_prompt(client, chat_project):
    """System prompt for interview_sessions agents must include stakeholder + session data."""
    captured: dict = {}

    async def fake_create(**kwargs):
        captured["system"] = kwargs.get("system", "")
        captured["messages"] = kwargs.get("messages", [])
        r = MagicMock()
        r.content = [MagicMock(text="ok")]
        return r

    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls:
        inst = AsyncMock()
        inst.messages.create = fake_create
        mock_cls.return_value = inst
        await client.post(
            "/projects/chatproj/agent-chat",
            json={
                "agent_name": "Interview Coordinator",
                "message": "Status?",
                "history": [],
            },
        )

    assert "Alice" in captured["system"]
    assert "Bob" in captured["system"]
    assert "completed" in captured["system"].lower() or "pending" in captured["system"].lower()


@pytest.mark.asyncio
async def test_agent_chat_passes_history_to_claude(client, chat_project):
    """Conversation history should appear as prior messages to Claude."""
    captured: dict = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages", [])
        r = MagicMock()
        r.content = [MagicMock(text="I remember")]
        return r

    with patch("api.services.agent_chat_service.AsyncAnthropic") as mock_cls:
        inst = AsyncMock()
        inst.messages.create = fake_create
        mock_cls.return_value = inst
        await client.post(
            "/projects/chatproj/agent-chat",
            json={
                "agent_name": "Roadmap Generator",
                "message": "And now?",
                "history": [
                    {"role": "user", "content": "First message"},
                    {"role": "agent", "content": "First reply"},
                ],
            },
        )

    msgs = captured["messages"]
    # First two are history, last is new user message
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "First message"
    assert msgs[1]["role"] == "assistant"   # 'agent' converted to 'assistant'
    assert msgs[1]["content"] == "First reply"
    assert msgs[2]["role"] == "user"
    assert msgs[2]["content"] == "And now?"
```

- [ ] **Step 2: Run tests — confirm they all fail with ImportError (module not yet created)**

```bash
pytest tests/test_agent_chat.py -v
```

Expected: `ImportError: cannot import name 'agent_chat_service'` or similar — all 5 tests fail

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_agent_chat.py
git commit -m "test(agent-chat): write failing tests for chat endpoint (TDD)"
```

---

## Task 7: Backend Service + Router

**Files:**
- Create: `api/services/agent_chat_service.py`
- Create: `api/routers/agent_chat.py`

- [ ] **Step 1: Create `api/services/agent_chat_service.py`**

```python
# api/services/agent_chat_service.py
"""Agent chat — persona definitions, context fetching, and Claude call."""
from __future__ import annotations

from datetime import date
from anthropic import AsyncAnthropic

from api.database import get_connection, get_db_path, fetch_project


# ── Agent persona registry ─────────────────────────────────────────────────────

AGENT_PERSONAS: dict[str, dict] = {
    "Value Chain Mapper": {
        "role": "You map the organisation's value chain, identifying key processes, activities, and interdependencies across each stage.",
        "context_type": "outputs",
    },
    "Requirements Capture": {
        "role": "You gather and document stakeholder requirements from discovery interviews, ensuring all voices are heard.",
        "context_type": "stakeholders",
    },
    "Requirements Analyst": {
        "role": "You analyse captured requirements for consistency, gaps, conflicts, and priority.",
        "context_type": "outputs",
    },
    "Value Lever Analyst": {
        "role": "You identify the highest-value levers for organisational improvement based on discovery findings.",
        "context_type": "outputs",
    },
    "Interview Script Designer": {
        "role": "You design tailored interview scripts for each stakeholder and value chain node.",
        "context_type": "stakeholders",
    },
    "Interview Coordinator": {
        "role": "You coordinate the scheduling and tracking of stakeholder interviews across the project.",
        "context_type": "interview_sessions",
    },
    "Stakeholder Interviewer": {
        "role": "You conduct voice interviews with stakeholders and ensure their responses are captured accurately.",
        "context_type": "interview_sessions",
    },
    "Synthesis Analyst": {
        "role": "You synthesise interview transcripts into structured findings and themes.",
        "context_type": "interview_sessions",
    },
    "Value Proposition Generator": {
        "role": "You generate compelling value propositions from discovery findings.",
        "context_type": "outputs",
    },
    "Portfolio Manager": {
        "role": "You score and rank initiatives across the six capitals framework and manage the project portfolio.",
        "context_type": "outputs",
    },
    "Enterprise Architect": {
        "role": "You design the enterprise architecture required to deliver the roadmap initiatives.",
        "context_type": "outputs",
    },
    "Initiative Identifier": {
        "role": "You identify and define the key initiatives from the architecture blueprint.",
        "context_type": "outputs",
    },
    "Roadmap Generator": {
        "role": "You sequence initiatives across value streams and time horizons into a delivery roadmap.",
        "context_type": "outputs",
    },
    "Business Plan Generator": {
        "role": "You produce the financial model and business plan narrative for the initiative portfolio.",
        "context_type": "outputs",
    },
}


# ── Context fetchers ───────────────────────────────────────────────────────────

async def _stakeholder_context(conn, project_id: int) -> str:
    async with conn.execute(
        "SELECT name, job_title, organisation, interview_status, "
        "interview_invited_at, interview_completed_at "
        "FROM stakeholders WHERE project_id=? ORDER BY name ASC",
        (project_id,),
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        return "No stakeholders registered for this project yet."
    lines = ["STAKEHOLDERS", "-" * 40]
    for r in rows:
        status = r[3] or "not started"
        role_part = f", {r[1]}" if r[1] else ""
        org_part = f" ({r[2]})" if r[2] else ""
        lines.append(f"• {r[0]}{role_part}{org_part} — interview: {status}")
    return "\n".join(lines)


async def _interview_sessions_context(conn, project_id: int) -> str:
    async with conn.execute(
        """
        SELECT s.name, s.job_title, s.organisation,
               is_.node_label, is_.status, is_.started_at, is_.completed_at
        FROM interview_sessions is_
        LEFT JOIN stakeholders s ON s.id = is_.stakeholder_id
        WHERE is_.project_id = ?
        ORDER BY s.name ASC
        """,
        (project_id,),
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        return "No interview sessions have been created for this project yet."
    lines = ["INTERVIEW SESSIONS", "-" * 40]
    for r in rows:
        name = r[0] or "Unknown"
        role_part = f", {r[1]}" if r[1] else ""
        org_part = f" ({r[2]})" if r[2] else ""
        node = r[3]
        status = r[4]
        started = f", started {r[5]}" if r[5] else ""
        completed = f", completed {r[6]}" if r[6] else ""
        lines.append(f"• {name}{role_part}{org_part} — {node} — {status}{started}{completed}")
    return "\n".join(lines)


async def _outputs_context(conn, project_id: int) -> str:
    async with conn.execute(
        "SELECT crew_name, status, result_json FROM crew_runs "
        "WHERE project_id=? ORDER BY created_at DESC LIMIT 6",
        (project_id,),
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        return "No crew runs have completed for this project yet."
    lines = ["RECENT CREW OUTPUTS", "-" * 40]
    for r in rows:
        lines.append(f"Crew: {r[0]} — Status: {r[1]}")
        if r[2]:
            snippet = r[2][:800] + ("…" if len(r[2]) > 800 else "")
            lines.append(f"Output: {snippet}")
    return "\n".join(lines)


async def _fetch_context(conn, project_id: int, context_type: str) -> str:
    if context_type == "stakeholders":
        return await _stakeholder_context(conn, project_id)
    if context_type == "interview_sessions":
        return await _interview_sessions_context(conn, project_id)
    return await _outputs_context(conn, project_id)


# ── Main entry point ───────────────────────────────────────────────────────────

async def run_agent_chat(
    slug: str,
    agent_name: str,
    message: str,
    history: list[dict],
) -> str | None:
    """
    Returns the agent's reply string, or None if the project DB doesn't exist.
    Raises KeyError if agent_name is unknown (caller converts to 404).
    """
    persona = AGENT_PERSONAS[agent_name]  # KeyError → router returns 404

    if not get_db_path(slug).exists():
        return None

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        context_block = await _fetch_context(conn, project["id"], persona["context_type"])

    system_prompt = (
        f"You are {agent_name}, an AI agent within the FutureMomentum platform.\n\n"
        f"Your role: {persona['role']}\n\n"
        f"Project: {slug}\n"
        f"Today: {date.today().isoformat()}\n\n"
        f"{context_block}\n\n"
        "Answer the user's question helpfully and concisely. "
        "Use bullet points for lists. "
        "If you don't have the data to answer, say so — don't invent details."
    )

    # Convert history: frontend uses 'agent', Anthropic API requires 'assistant'
    messages = [
        {
            "role": "assistant" if m["role"] == "agent" else "user",
            "content": m["content"],
        }
        for m in history
    ]
    messages.append({"role": "user", "content": message})

    client = AsyncAnthropic()
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text.strip()
```

- [ ] **Step 2: Create `api/routers/agent_chat.py`**

```python
# api/routers/agent_chat.py
"""POST /projects/{slug}/agent-chat — interactive agent chat endpoint."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth import require_any_auth, check_project_access
from api.services.agent_chat_service import run_agent_chat, AGENT_PERSONAS

router = APIRouter(prefix="/projects", tags=["agent-chat"])


class ChatRequest(BaseModel):
    agent_name: str
    message: str
    history: list[dict] = []


@router.post("/{slug}/agent-chat")
async def agent_chat(
    slug: str,
    body: ChatRequest,
    payload: dict = Depends(require_any_auth),
):
    await check_project_access(slug, payload)

    if body.agent_name not in AGENT_PERSONAS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {body.agent_name!r}")

    result = await run_agent_chat(slug, body.agent_name, body.message, body.history)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    return {"response": result}
```

- [ ] **Step 3: Run the tests — they should all pass now**

```bash
pytest tests/test_agent_chat.py -v
```

Expected:
```
PASSED tests/test_agent_chat.py::test_agent_chat_unknown_agent_returns_404
PASSED tests/test_agent_chat.py::test_agent_chat_project_not_found_returns_404
PASSED tests/test_agent_chat.py::test_agent_chat_returns_claude_response
PASSED tests/test_agent_chat.py::test_agent_chat_interview_context_in_system_prompt
PASSED tests/test_agent_chat.py::test_agent_chat_passes_history_to_claude
```

If tests still fail with ImportError, check that `api/routers/agent_chat.py` imports from `api.services.agent_chat_service` correctly.

- [ ] **Step 4: Commit**

```bash
git add api/services/agent_chat_service.py api/routers/agent_chat.py
git commit -m "feat: add agent chat service and router (Claude Haiku + live DB context)"
```

---

## Task 8: Register Router + Full Verification

**Files:**
- Modify: `api/main.py`

- [ ] **Step 1: Add the agent_chat router import and registration in `api/main.py`**

After line `from api.routers import admin as admin_router`, add:

```python
from api.routers import agent_chat as agent_chat_router
```

After `app.include_router(admin_router.router)`, add:

```python
app.include_router(agent_chat_router.router)
```

- [ ] **Step 2: Run all tests to confirm nothing is broken**

```bash
pytest --tb=short -q
```

Expected: all existing tests pass + 5 new agent chat tests pass. Zero failures.

- [ ] **Step 3: TypeScript build check**

```bash
cd ui && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add api/main.py
git commit -m "feat(SP17c): register agent-chat router in main app"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Light theme: Tailwind tokens + AppLayout (Task 1)
- ✅ Agent avatars (illustrated, gradient circles with emoji): Task 2 + 3
- ✅ Agent grid with live status: Task 3
- ✅ Slide-in chat drawer: Task 4
- ✅ Dashboard updated (Run Pipeline in header): Task 5
- ✅ Backend: Claude Haiku with persona + live DB context: Task 7
- ✅ Backend: 3 context types (stakeholders, interview_sessions, outputs): Task 7
- ✅ Tests: 5 tests covering 404 paths, response passthrough, context content, history mapping: Task 6

**Type consistency:**
- `AgentGridProps.onAgentChat: (agentName: string) => void` — matches `setActiveAgent` in Dashboard ✅
- `AgentChatDrawerProps.agentName: string | null` — matches `activeAgent` state (initially `null`) ✅
- `agentChatApi.send` history param is `{ role: string; content: string }[]` — matches what Drawer passes ✅
- Backend: `history` entries with `role: 'agent'` are converted to `'assistant'` before Claude call ✅

**No placeholders:** all steps have complete code. ✅
