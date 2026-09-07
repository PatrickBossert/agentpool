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
// **Being named after an agent is not the same as belonging to one.** Six panels arrived here
// on that reasoning and five of them left again: PamSetupTab held a project's schedule,
// AlexSetupTab its research brief, MayaSetupTab its disciplines and its interview programme,
// JordanSetupTab its stakeholder-to-activity mapping, TaylorSetupTab its roster and its chase
// rules. Apply the test - if this agent were renamed or replaced, would this content move with
// them? - and every one of those answers no. They are crew-scoped sections on Setup and Status
// now (see AgentDetailPanel's CREW_SETUP_SECTION / CREW_STATUS_SECTION), and what is left here
// is the only content that is genuinely about an agent rather than about the engagement.
//
// **The tab becoming thin is the correct outcome**, not a loss.
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
import AverySetupTab from './AverySetupTab'

export type SetupSectionFC = FC<{ slug: string }>

/**
 * Bespoke configuration sections, keyed by the agent that owns them - never by a crew.
 *
 * **One of eighteen agents has one**, and that is the honest count rather than a gap waiting
 * to be filled. Avery's interviewing style - how firmly he presses, how long he waits in a
 * silence - is how *he* conducts an interview, so it moves with him if he is renamed or
 * replaced. The other seventeen have their name, image, voice and synthesis model and nothing
 * else, because nothing else about them is theirs rather than the engagement's.
 *
 * The map stays keyed on the agent, and the entry for a second such panel goes here.
 */
export const AGENT_SETUP_SECTION: Record<string, SetupSectionFC> = {
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
                // The classification, in the DOM rather than in a comment. Every bespoke
                // panel carries `<tab>:<owner>`, and TabClassification.test.tsx holds the
                // set each tab may contain - so a panel registered anywhere without a
                // decision about which tab it belongs on fails rather than lands.
                data-panel-section={`agents:${agent}`}
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
