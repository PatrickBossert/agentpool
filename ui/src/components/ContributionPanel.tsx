// ui/src/components/ContributionPanel.tsx
//
// Read-only detail for one selected contribution: the tasks that belong to it, plus the
// propositions that attach to its activity as a whole. Editing these arrives with the
// grid in a later project - this panel only ever reads the model it is given. Rendered as
// a modal dialog by the Structure tab, which owns whether it is mounted at all.
import { X } from 'lucide-react'
import type { ValueChainModel } from '../utils/valueChainModel'

export interface ContributionPanelProps {
  model: ValueChainModel
  activityId: string
  partyId: string
}

export function ContributionPanel({
  model,
  activityId,
  partyId,
  onClose,
}: ContributionPanelProps & { onClose: () => void }) {
  const activity = model.activities.find((a) => a.id === activityId)
  const party = model.parties.find((p) => p.id === partyId)
  const contribution = model.contributions.find(
    (c) => c.activity_id === activityId && c.party_id === partyId,
  )

  const tasks = model.tasks.filter((t) => t.activity_id === activityId && t.party_id === partyId)
  const propositions = model.propositions.filter((p) => p.activity_id === activityId)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${activityId} detail`}
        data-testid="contribution-panel"
        className="bg-surface-raised rounded-xl max-w-lg w-full max-h-[80vh] overflow-y-auto p-5"
        // The backdrop closes on click; the dialog itself must not, or every interaction
        // inside it would dismiss the thing being interacted with.
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <h4 className="text-sm font-medium text-primary">
            {activity?.label ?? activityId}
            {party && <span className="text-muted font-normal"> - {party.label}</span>}
          </h4>
          <button
            type="button"
            data-testid="close-contribution-panel"
            aria-label="Close"
            onClick={onClose}
            className="text-secondary hover:text-primary shrink-0"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
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
    </div>
  )
}

export default ContributionPanel
