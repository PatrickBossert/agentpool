// ui/src/components/AgentOutputTab.tsx
// One agent's current primary artefact, and nothing else.
//
// The Output tab is where you change the artefact; the Status tab is where you see what has
// happened to it. Version lists, thumbnails, revert, reject and revise all act on *a
// version* rather than on the current artefact, so they live in Status.
import { CREW_AGENTS, AGENT_AVATAR, AGENT_AVATAR_IMAGE, AGENT_HUMAN_NAME } from './agentStatus'
import { CREW_OUTPUT_TYPE } from './crewOutputs'
import { CREW_OUTPUT_EDITOR } from './AgentDetailPanel'
import type { AgentOutput } from '../types'

export interface AgentOutputTabProps {
  slug: string
  crewKey: string
  outputs: AgentOutput[]
  locale?: string
}

export function AgentOutputTab({ slug, crewKey, outputs }: AgentOutputTabProps) {
  const primaryType = CREW_OUTPUT_TYPE[crewKey]
  const current = primaryType
    ? outputs.find(o => o.output_type === primaryType && o.is_current)
    : undefined

  // Absent from CREW_OUTPUT_EDITOR is the default, not a special case - every crew arrives
  // here read-only until a bespoke editor is registered for it.
  const Editor = CREW_OUTPUT_EDITOR[crewKey]

  // A registered editor owns its own empty state - StructureTab's migrate prompt is exactly
  // this for discovery_mapping, and it is the only route to the migrate endpoint now that the
  // standalone value chain page is retired. A project with a legacy diagram and no migrated
  // model has no *current* row of the primary type, so mounting the editor here rather than
  // gating on `current` is what lets it reach that prompt at all. The no-outputs empty state
  // below is reserved for crews with no editor and nothing to show read-only.
  if (!current && !Editor) {
    const agents = CREW_AGENTS[crewKey] ?? []
    const primaryAgent = agents[0] ?? ''
    const primaryAvatar = AGENT_AVATAR[primaryAgent] ?? { gradient: 'from-gray-400 to-gray-600' }
    const primaryHumanName = AGENT_HUMAN_NAME[primaryAgent] ?? primaryAgent
    const firstName = primaryHumanName.split(' ')[0]

    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-center" data-testid="no-primary-output">
        <div className="w-16 h-16 rounded-full overflow-hidden opacity-30 flex-shrink-0">
          {AGENT_AVATAR_IMAGE[primaryAgent] ? (
            <img src={AGENT_AVATAR_IMAGE[primaryAgent]} alt={firstName} className="w-full h-full object-cover" />
          ) : (
            <div className={`w-full h-full bg-gradient-to-br ${primaryAvatar.gradient} flex items-center justify-center text-2xl`}>
              {firstName[0]}
            </div>
          )}
        </div>
        <p className="text-sm text-gray-400">No outputs yet</p>
        <p className="text-xs text-gray-300">Run this crew to see results here</p>
      </div>
    )
  }

  return (
    <div
      data-testid={`primary-output-${primaryType}`}
      {...(current ? { 'data-version': String(current.version) } : {})}
    >
      {Editor ? (
        <Editor slug={slug} />
      ) : current ? (
        // `current` is narrowed here by this ternary, not by the comment above - reordering
        // the guard or this branch can no longer produce a runtime crash the compiler stays
        // silent about. Reaching Editor-less with no current is impossible (the early return
        // above already covers `!current && !Editor`), so there is deliberately no third arm.
        <div
          data-testid="primary-output-readonly"
          className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-3 space-y-1"
        >
          <p className="text-xs font-semibold text-gray-700">{current.file_path}</p>
          <p className="text-[11px] text-gray-400">
            No editor registered for this output yet. See the Status tab for its version history.
          </p>
        </div>
      ) : null}
    </div>
  )
}
