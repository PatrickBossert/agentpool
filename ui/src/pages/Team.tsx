// ui/src/pages/Team.tsx
import { useQuery } from '@tanstack/react-query'
import {
  CREW_ORDER, CREW_LABELS, CREW_AGENTS,
  AGENT_HUMAN_NAME, AGENT_AVATAR, AGENT_AVATAR_IMAGE,
  AGENT_ROLE, AGENT_BACKSTORY, AGENT_SKILLS,
} from '../components/agentStatus'
import { skillsApi } from '../api/skills'
import type { AgentSkill } from '../api/skills'

export default function Team() {
  const { data: pendingSkills = [] } = useQuery<AgentSkill[]>({
    queryKey: ['skills', 'pending'],
    queryFn: () => skillsApi.list({ status: 'pending' }),
  })

  return (
    <div className="px-6 py-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Agent Team</h1>
        <p className="text-sm text-gray-600 mt-1">
          All agents involved in the TaskReimagination.ai pipeline — their roles, skills, and backstories.
        </p>
      </div>

      {/* PAM — orchestrator, shown first across full width */}
      <div className="mb-6">
        <AgentCard
          agentName="PAM"
          crewLabel="Pipeline Orchestrator"
          pendingSkills={pendingSkills.filter(s => s.agents.includes('PAM'))}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {CREW_ORDER.flatMap(crewKey => {
          const agents = CREW_AGENTS[crewKey] ?? []
          return agents.map(agentName => (
            <AgentCard
              key={agentName}
              agentName={agentName}
              crewLabel={CREW_LABELS[crewKey]}
              pendingSkills={pendingSkills.filter(s => s.agents.includes(agentName))}
            />
          ))
        })}
      </div>
    </div>
  )
}

function AgentCard({
  agentName,
  crewLabel,
  pendingSkills,
}: {
  agentName: string
  crewLabel: string
  pendingSkills: AgentSkill[]
}) {
  const humanName = AGENT_HUMAN_NAME[agentName] ?? agentName
  const avatar    = AGENT_AVATAR[agentName] ?? { gradient: 'from-gray-400 to-gray-600', emoji: '🤖' }
  const imageSrc  = AGENT_AVATAR_IMAGE[agentName]
  const role      = AGENT_ROLE[agentName] ?? ''
  const backstory = AGENT_BACKSTORY[agentName] ?? ''
  const skills    = AGENT_SKILLS[agentName] ?? []

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden flex flex-col">
      <div className={`bg-gradient-to-br ${avatar.gradient} px-5 pt-5 pb-6 flex items-end gap-4`}>
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
      </div>

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

        {(skills.length > 0 || pendingSkills.length > 0) && (
          <div>
            <p className="text-[10px] font-bold text-gray-600 uppercase tracking-widest mb-2">Skills</p>

            {skills.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {skills.map(skill => (
                  <span
                    key={skill.name}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 border border-gray-200 text-[11px] font-medium text-gray-700"
                  >
                    <skill.icon size={10} className="flex-shrink-0 text-gray-400" />
                    {skill.name}
                  </span>
                ))}
              </div>
            )}

            {pendingSkills.length > 0 && (
              <div className={skills.length > 0 ? 'mt-3' : ''}>
                <p className="text-[9px] font-semibold text-blue-500 uppercase tracking-wider mb-1.5">
                  Skills in development
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {pendingSkills.map(skill => (
                    <span
                      key={skill.id}
                      className="inline-flex items-center px-2 py-0.5 rounded-full bg-blue-50 border border-blue-200 text-[11px] font-medium text-blue-700"
                    >
                      {skill.name}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
