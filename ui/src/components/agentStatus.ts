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
