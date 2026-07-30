// ui/src/components/ContributionPanel.tsx
//
// Read-only detail for one selected contribution: the tasks that belong to it, plus the
// propositions that attach to its activity as a whole. Editing these arrives with the
// grid in a later project - this panel only ever reads the model it is given.
import type { ValueChainModel } from '../utils/valueChainModel'

export interface ContributionPanelProps {
  model: ValueChainModel
  activityId: string
  partyId: string
}

export function ContributionPanel({ model, activityId, partyId }: ContributionPanelProps) {
  const activity = model.activities.find((a) => a.id === activityId)
  const party = model.parties.find((p) => p.id === partyId)
  const contribution = model.contributions.find(
    (c) => c.activity_id === activityId && c.party_id === partyId,
  )

  const tasks = model.tasks.filter((t) => t.activity_id === activityId && t.party_id === partyId)
  const propositions = model.propositions.filter((p) => p.activity_id === activityId)

  return (
    <div data-testid="contribution-panel" className="bg-surface-card rounded-xl p-4">
      <h4 className="text-sm font-medium text-primary">
        {activity?.label ?? activityId}
        {party && <span className="text-muted font-normal"> - {party.label}</span>}
      </h4>
      {contribution?.description && (
        <p className="text-muted text-xs mt-1">{contribution.description}</p>
      )}

      <section className="mt-4">
        <h5 className="text-xs font-medium text-secondary uppercase tracking-wide mb-2">Tasks</h5>
        {tasks.length === 0 ? (
          <p className="text-muted text-xs italic">No tasks recorded for this contribution yet.</p>
        ) : (
          <ul className="space-y-2">
            {tasks.map((task) => (
              <li key={task.id} data-testid={`task-${task.id}`}>
                <p className="text-sm font-medium text-primary">{task.label ?? task.id}</p>
                {task.description && <p className="text-muted text-xs">{task.description}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-4">
        <h5 className="text-xs font-medium text-secondary uppercase tracking-wide mb-2">Propositions</h5>
        {propositions.length === 0 ? (
          <p className="text-muted text-xs italic">No propositions recorded for this activity yet.</p>
        ) : (
          <ul className="space-y-2">
            {propositions.map((proposition) => {
              const propositionParty = proposition.party_id
                ? model.parties.find((p) => p.id === proposition.party_id)
                : undefined
              return (
                <li key={proposition.id} data-testid={`proposition-${proposition.id}`}>
                  <p className="text-sm text-primary">{proposition.description}</p>
                  {propositionParty && (
                    <p className="text-muted text-xs">{propositionParty.label}</p>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>
    </div>
  )
}

export default ContributionPanel
