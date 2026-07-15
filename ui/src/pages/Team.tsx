// ui/src/pages/Team.tsx
import { useState } from 'react'
import { Info, X } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import {
  CREW_ORDER, CREW_LABELS, CREW_AGENTS,
  AGENT_HUMAN_NAME, AGENT_AVATAR, AGENT_AVATAR_IMAGE,
  AGENT_ROLE, AGENT_BACKSTORY, AGENT_SKILLS,
  AGENT_RUN_KEYS,
} from '../components/agentStatus'
import { skillNotesApi } from '../api/endpoints'

export default function Team() {
  const { data: allNotes = [] } = useQuery({
    queryKey: ['agent-skill-notes'],
    queryFn: () => skillNotesApi.list(),
  })

  const pamNotes = allNotes.filter(n => n.agent_name === 'pam')

  return (
    <div className="px-6 py-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Agent Team</h1>
        <p className="text-sm text-gray-500 mt-1">
          All agents involved in the TaskReimagination.ai pipeline — their roles, skills, and backstories.
        </p>
      </div>

      {/* PAM — orchestrator, shown first across full width */}
      <div className="mb-6">
        <AgentCard agentName="PAM" crewLabel="Pipeline Orchestrator" notes={pamNotes} />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {CREW_ORDER.flatMap(crewKey => {
          const agents = CREW_AGENTS[crewKey] ?? []
          return agents.map(agentName => {
            const snakeKey = AGENT_RUN_KEYS[agentName] ?? agentName.toLowerCase().replace(/ /g, '_')
            const agentNotes = allNotes.filter(n => n.agent_name === snakeKey)
            return (
              <AgentCard key={agentName} agentName={agentName} crewLabel={CREW_LABELS[crewKey]} notes={agentNotes} />
            )
          })
        })}
      </div>
    </div>
  )
}

function AgentCard({
  agentName,
  crewLabel,
  notes,
}: {
  agentName: string
  crewLabel: string
  notes: Array<{ note: string; created_at: string }>
}) {
  const [infoOpen, setInfoOpen] = useState(false)

  const humanName = AGENT_HUMAN_NAME[agentName] ?? agentName
  const avatar    = AGENT_AVATAR[agentName] ?? { gradient: 'from-gray-400 to-gray-600', emoji: '🤖' }
  const imageSrc  = AGENT_AVATAR_IMAGE[agentName]
  const role      = AGENT_ROLE[agentName] ?? ''
  const backstory = AGENT_BACKSTORY[agentName] ?? ''
  const skills    = AGENT_SKILLS[agentName] ?? []

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden flex flex-col">
      {/* Header gradient with photo */}
      <div className={`bg-gradient-to-br ${avatar.gradient} px-5 pt-5 pb-6 flex items-end gap-4 relative`}>
        {imageSrc ? (
          <img
            src={imageSrc}
            alt={humanName}
            className="w-20 h-20 rounded-full object-cover border-2 border-white/60 shadow-md flex-shrink-0"
          />
        ) : (
          <div className="w-20 h-20 rounded-full bg-white/20 flex items-center justify-center text-2xl font-bold text-white border-2 border-white/60 flex-shrink-0">
            {humanName.split(' ').map(w => w[0]).join('').slice(0, 2)}
          </div>
        )}
        <div className="pb-1 min-w-0">
          <p className="text-white font-bold text-xl leading-tight">{humanName}</p>
          <p className="text-white/80 text-xs font-medium leading-snug mt-0.5">{crewLabel}</p>
          <p className="text-white/50 text-[10px] leading-snug mt-0.5">{agentName}</p>
        </div>

        {/* Info button — only shown when notes exist */}
        {notes.length > 0 && (
          <button
            onClick={() => setInfoOpen(v => !v)}
            aria-label={infoOpen ? 'Close skill development notes' : 'View skill development notes'}
            className="absolute top-3 right-3 w-6 h-6 rounded-full bg-white/20 hover:bg-white/30 flex items-center justify-center transition-colors"
          >
            <Info size={13} className="text-white" />
          </button>
        )}
      </div>

      {/* Info panel — skill development notes, toggled by (i) */}
      {infoOpen && notes.length > 0 && (
        <div className="px-5 py-4 bg-amber-50 border-b border-amber-100">
          <div className="flex items-center justify-between mb-2">
            <p className="text-[10px] font-bold text-amber-600 uppercase tracking-widest">Skills in development</p>
            <button
              onClick={() => setInfoOpen(false)}
              aria-label="Close"
              className="text-amber-400 hover:text-amber-600 transition-colors"
            >
              <X size={13} />
            </button>
          </div>
          <ul className="space-y-1.5">
            {notes.map((n, i) => (
              <li key={i} className="text-[11px] text-amber-800 leading-relaxed bg-white rounded-lg px-3 py-2 border border-amber-100">
                {n.note}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Body */}
      <div className="px-5 py-4 flex flex-col gap-4 flex-1">
        {role && (
          <div>
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Role</p>
            <p className="text-xs text-gray-700 leading-relaxed">{role}</p>
          </div>
        )}

        {backstory && (
          <div>
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Background</p>
            <p className="text-xs text-gray-600 leading-relaxed italic">{backstory}</p>
          </div>
        )}

        {skills.length > 0 && (
          <div>
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">Skills</p>
            <div className="flex flex-col gap-2">
              {skills.map(skill => (
                <div key={skill.name} className="flex items-start gap-2">
                  <skill.icon size={14} className="flex-shrink-0 mt-0.5 text-gray-400" />
                  <div>
                    <p className="text-[11px] font-semibold text-gray-700">{skill.name}</p>
                    <p className="text-[11px] text-gray-500 leading-relaxed">{skill.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
