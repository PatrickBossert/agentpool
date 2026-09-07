// ui/src/components/tabs/CrewAgentsTab.tsx
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
// So a section registers against an AGENT, and this file assembles whichever of the crew's
// own agents have one, in the crew's own order. Renaming the file would have fixed today's
// instance; keying on the agent fixes the class.
//
// **The whole-tab overrides are gone.** `CREW_SETUP_OVERRIDE` replaced the Setup tab outright
// for three crews with PamSetupTab, AlexSetupTab and MayaSetupTab - components named after
// *agents*, configuring agents, occupying a crew's tab. They are ordinary entries in
// `AGENT_SETUP_SECTION` now, beside the agent each is named after, so everything agent-scoped
// is in one place whatever its shape rather than a rule about which shapes count.
//
// **One agent at a time.** The Setup tab stacked four full configurations under a heading
// that also held the crew's own settings - 3364px of it, measured on 7 September. An agent
// is chosen and the others are rendered `hidden`, not unmounted, for the reason the panel's
// own tabs are: every block below holds form state committed only by an explicit Save, and
// unmounting on a selector click throws away a half-typed display name with nothing to catch
// it. React Query keys each configuration by agent, so nothing refetches on a switch either.
import { useState, type FC } from 'react'

import { CREW_AGENTS, AGENT_AVATAR } from '../agentStatus'
import { useAgentIdentity } from '../../hooks/useAgentIdentity'
import AgentConfigSection from './AgentConfigSection'
import AlexSetupTab from './AlexSetupTab'
import AverySetupTab from './AverySetupTab'
import JordanSetupTab from './JordanSetupTab'
import MayaSetupTab from './MayaSetupTab'
import PamSetupTab from './PamSetupTab'
import TaylorSetupTab from './TaylorSetupTab'

export type SetupSectionFC = FC<{ slug: string }>

/**
 * Bespoke configuration sections, keyed by the agent that owns them - never by a crew.
 *
 * Six of eighteen agents have one; the other twelve have their name, image, voice and
 * synthesis model and nothing else. The three that arrived here from `CREW_SETUP_OVERRIDE`
 * (PAM, Alex, Maya) are the ones that used to replace a whole crew's tab.
 */
export const AGENT_SETUP_SECTION: Record<string, SetupSectionFC> = {
  'PAM':                     PamSetupTab,
  'Value Chain Mapper':      AlexSetupTab,
  'Interaction Designer':    MayaSetupTab,
  'Stakeholder Manager':     JordanSetupTab,
  'Interview Coordinator':   TaylorSetupTab,
  'Stakeholder Interviewer': AverySetupTab,
}

/** The face and first name of one agent, as the selector shows them. */
function AgentChip({ agent, slug }: { agent: string; slug: string }) {
  const { name: humanName, imageUrl: imageSrc } = useAgentIdentity(slug)(agent)
  const gradient = (AGENT_AVATAR[agent] ?? { gradient: 'from-gray-400 to-gray-600' }).gradient

  return (
    <>
      <span className="w-6 h-6 rounded-full overflow-hidden flex-shrink-0">
        {imageSrc ? (
          <img src={imageSrc} alt="" className="w-full h-full object-cover" />
        ) : (
          <span
            className={`w-full h-full bg-gradient-to-br ${gradient} flex items-center justify-center text-[10px] font-bold text-white`}
          >
            {humanName.split(' ').map((w) => w[0]).join('').slice(0, 2)}
          </span>
        )}
      </span>
      {humanName.split(' ')[0]}
    </>
  )
}

/**
 * Everything scoped to one agent of this crew: who they are, and anything peculiar to them.
 *
 * Keyed on `(project, agent)` and changed once at the start of an engagement, which is what
 * makes it a different tab from Setup - that is keyed on the crew and edited repeatedly
 * during delivery. Two objects, two keys, two clocks.
 */
export function CrewAgentsTab({
  crewKey,
  slug,
  initialAgent,
}: {
  crewKey: string
  slug: string
  /**
   * Which agent to open on. Ignored when it names somebody who is not in this crew, so a
   * stale selection cannot leave the tab showing nobody at all.
   */
  initialAgent?: string
}) {
  const agents = CREW_AGENTS[crewKey] ?? []
  const [selected, setSelected] = useState(
    () => (initialAgent && agents.includes(initialAgent) ? initialAgent : agents[0]) ?? '',
  )
  // Above the early return: a hook cannot be called conditionally.
  const identity = useAgentIdentity(slug)

  if (agents.length === 0) {
    return <p className="text-xs text-gray-400 text-center py-12">This crew has no agents.</p>
  }

  return (
    <div className="space-y-4">
      {/* A crew of one needs no selector - the heading below already names them, and a row
          of one button reads as a choice that is not being offered. */}
      {agents.length > 1 && (
        <div
          data-testid="agent-selector"
          className="flex flex-wrap items-center gap-1.5 border-b border-surface-border pb-2"
        >
          {agents.map((agent) => (
            <button
              key={agent}
              type="button"
              onClick={() => setSelected(agent)}
              aria-pressed={agent === selected}
              data-testid={`agent-selector-${agent}`}
              className={`flex items-center gap-1.5 rounded-full border pl-1 pr-2.5 py-1 text-[11px] font-medium transition-colors ${
                agent === selected
                  ? 'border-brand bg-brand/10 text-teal-700'
                  : 'border-gray-200 text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <AgentChip agent={agent} slug={slug} />
            </button>
          ))}
        </div>
      )}

      {agents.map((agent) => {
        const humanName = identity(agent).name
        const Section = AGENT_SETUP_SECTION[agent]
        return (
          <div
            key={agent}
            hidden={agent !== selected}
            data-testid={`agent-panel-${agent}`}
            className="space-y-4"
          >
            {/* Whose configuration this is, on the screen rather than in a filename. */}
            <div className="flex items-baseline gap-2 border-b border-surface-border pb-1">
              <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest">
                {humanName}
              </h3>
              <span className="text-[10px] text-gray-400">{agent}</span>
            </div>

            <section data-testid={`agent-config-section-${agent}`} className="space-y-3">
              <AgentConfigSection slug={slug} agentName={agent} />
            </section>

            {Section && (
              <section
                data-testid={`setup-section-${agent}`}
                className="space-y-3 border-t border-surface-border pt-4"
              >
                <h4 className="text-xs font-semibold text-gray-600">
                  {humanName.split(' ')[0]}&rsquo;s own settings
                </h4>
                <Section slug={slug} />
              </section>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default CrewAgentsTab
