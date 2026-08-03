// ui/src/components/ContributionPanel.tsx
//
// Read-only detail for one selected contribution: the tasks that belong to it, plus the
// propositions that attach to its activity as a whole. Editing these arrives with the
// grid in a later project - this panel only ever reads the model it is given. Rendered as
// a modal dialog by the Structure tab, which owns whether it is mounted at all.
import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import {
  updateActivityLabel,
  updateTaskLabel,
  type ValueChainModel,
} from '../utils/valueChainModel'

export interface ContributionPanelProps {
  model: ValueChainModel
  activityId: string
  partyId: string
}

export function ContributionPanel({
  model,
  activityId,
  partyId,
  onChange,
  onClose,
}: ContributionPanelProps & {
  // Absent means read-only, which is the same convention the card uses - no separate flag
  // that could disagree with whether a handler exists.
  onChange?: (model: ValueChainModel) => void
  onClose: () => void
}) {
  const activity = model.activities.find((a) => a.id === activityId)
  const party = model.parties.find((p) => p.id === partyId)
  const contribution = model.contributions.find(
    (c) => c.activity_id === activityId && c.party_id === partyId,
  )

  const tasks = model.tasks.filter((t) => t.activity_id === activityId && t.party_id === partyId)
  const propositions = model.propositions.filter((p) => p.activity_id === activityId)

  // This is a modal dialog covering the whole grid, so a keyboard-only user landed nowhere
  // when it opened and nowhere useful when it closed. Focus moves in on open and back to
  // whatever had it on close - which is the card header that opened this, since selecting a
  // contribution is what mounts the panel. Deliberately not a focus trap: Escape closes from
  // anywhere, and the cost of a home-made trap is higher than what it buys here.
  const dialog = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    dialog.current?.focus()
    return () => opener?.focus?.()
  }, [])

  return (
    <div
      data-testid="contribution-panel-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        // The activity's label, not its bare ID - "1.1 detail" told a screen reader nothing.
        aria-label={
          party
            ? `${activity?.label ?? activityId} - ${party.label} detail`
            : `${activity?.label ?? activityId} detail`
        }
        tabIndex={-1}
        data-testid="contribution-panel"
        className="bg-surface-raised rounded-xl max-w-lg w-full max-h-[80vh] overflow-y-auto p-5 outline-none"
        // The backdrop closes on click; the dialog itself must not, or every interaction
        // inside it would dismiss the thing being interacted with.
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <h4 className="text-sm font-medium text-primary">
            <span className="font-mono text-muted">{activityId}</span>{' '}
            {onChange ? (
              <input
                type="text"
                data-testid={`edit-activity-label-${activityId}`}
                value={activity?.label ?? ''}
                onChange={(e) => onChange(updateActivityLabel(model, activityId, e.target.value))}
                className="bg-surface rounded px-2 py-1 text-sm text-primary"
              />
            ) : (
              activity?.label ?? ''
            )}
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
                <li key={task.id} data-testid={`task-${task.id}`} className="rounded p-2">
                  <p className="text-sm font-medium text-primary flex items-baseline gap-2">
                    <span className="font-mono text-muted shrink-0">{task.id}</span>
                    {onChange ? (
                      <input
                        type="text"
                        data-testid={`edit-task-label-${task.id}`}
                        // Controlled, never defaultValue - the same defence that guards the
                        // card's description. An uncontrolled field shows the keystroke and
                        // loses it on save.
                        value={task.label ?? task.description ?? ''}
                        onChange={(e) => onChange(updateTaskLabel(model, task.id, e.target.value))}
                        className="flex-1 min-w-0 bg-surface rounded px-2 py-1 text-sm text-primary"
                      />
                    ) : (
                      <span>{task.label ?? ''}</span>
                    )}
                  </p>
                  {task.description && <p className="text-muted text-xs mt-1">{task.description}</p>}
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
