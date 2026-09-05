// ui/src/components/tabs/CrewSetupSections.tsx
// Configuration belongs to an agent; a Setup tab belongs to a crew.
//
// Those are different scopes, and conflating them is what put Taylor's invite chase rules
// under Jordan: TaylorSetupTab was registered as CREW_SETUP_OVERRIDE['stakeholder_management'],
// a crew Taylor is not in, so one agent defined another's configuration.
//
// It happened because a crew with one agent - Alex in discovery_mapping, Jordan in
// stakeholder_management - can have its tab named after that agent and read correctly. A
// crew with three cannot: whichever name went on the tab was wrong for the other two.
//
// So a section registers against an AGENT, and the crew's tab assembles whichever of its
// own agents have one, in the crew's own order. Renaming the file would have fixed today's
// instance; keying on the agent fixes the class.
import type { FC } from 'react'

import { CREW_AGENTS, AGENT_HUMAN_NAME } from '../agentStatus'
import AgentConfigSection from './AgentConfigSection'
import TaylorSetupTab from './TaylorSetupTab'
import AverySetupTab from './AverySetupTab'
import JordanSetupTab from './JordanSetupTab'

export type SetupSectionFC = FC<{ slug: string }>

/**
 * Configuration sections, keyed by the agent that owns them - never by a crew.
 *
 * An agent alone in its crew (Alex, Maya, PAM) keeps a bespoke tab through
 * CREW_SETUP_OVERRIDE for now; those are candidates to become sections too, at which point
 * the override map holds only genuinely whole-tab cases.
 */
export const AGENT_SETUP_SECTION: Record<string, SetupSectionFC> = {
  'Stakeholder Manager':     JordanSetupTab,
  'Interview Coordinator':   TaylorSetupTab,
  'Stakeholder Interviewer': AverySetupTab,
}

/**
 * Every configuration section belonging to this crew's own agents, headed by whose it is.
 *
 * Renders nothing at all when no agent in the crew has one, so the caller can fall through
 * to its default rather than showing an empty shell that hides the absence.
 */
export function CrewSetupSections({ crewKey, slug }: { crewKey: string; slug: string }) {
  const sections = (CREW_AGENTS[crewKey] ?? [])
    .map((agent) => ({ agent, Section: AGENT_SETUP_SECTION[agent] }))
    .filter((s): s is { agent: string; Section: SetupSectionFC } => Boolean(s.Section))

  if (sections.length === 0) return null

  return (
    <>
      {sections.map(({ agent, Section }) => (
        <section key={agent} data-testid={`setup-section-${agent}`} className="space-y-3">
          {/* Whose configuration this is, on the screen rather than in a filename. */}
          <div className="flex items-baseline gap-2 border-b border-surface-border pb-1">
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest">
              {AGENT_HUMAN_NAME[agent] ?? agent}
            </h3>
            <span className="text-[10px] text-gray-400">{agent}</span>
          </div>
          <Section slug={slug} />
        </section>
      ))}
    </>
  )
}

/**
 * The agent configuration section, for **every** agent this crew holds.
 *
 * Separate from `CrewSetupSections` above, and deliberately so. That map is a registry of
 * *bespoke* configuration - three agents have one and fifteen do not, and the caller falls
 * through to the crew's reads/produces metadata when none of its agents is in it. This is the
 * opposite: name, image and voice belong to every agent by the same rule, so there is nothing
 * to register and nothing to fall through to. Folding the two together would have made "this
 * crew has no bespoke configuration" unaskable, which is the question the caller asks.
 *
 * Rendered in the crew's own agent order, headed by whose it is, for the reason the sections
 * above are: a crew of four cannot have a tab named after one of them.
 */
export function CrewAgentConfiguration({ crewKey, slug }: { crewKey: string; slug: string }) {
  const agents = CREW_AGENTS[crewKey] ?? []
  if (agents.length === 0) return null

  return (
    <div className="space-y-4">
      <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest border-b border-surface-border pb-1">
        Agent configuration
      </h3>
      {agents.map((agent) => (
        <section key={agent} data-testid={`agent-config-section-${agent}`} className="space-y-3">
          <div className="flex items-baseline gap-2">
            <h4 className="text-xs font-semibold text-gray-600">
              {AGENT_HUMAN_NAME[agent] ?? agent}
            </h4>
            <span className="text-[10px] text-gray-400">{agent}</span>
          </div>
          <AgentConfigSection slug={slug} agentName={agent} />
        </section>
      ))}
    </div>
  )
}

export default CrewSetupSections
