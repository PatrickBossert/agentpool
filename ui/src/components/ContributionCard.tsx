// ui/src/components/ContributionCard.tsx
// One party's contribution to one activity, as a card. Three sibling controls, never
// nested: the header (focus, move, open), the description input, and - from Task 8 - the
// party menu. A handler on the card itself would fire on every interaction with any of
// them, and one placed above the input would swallow keystrokes typed into it.
import { ChevronLeft, ChevronRight, ListTree, Lightbulb, Sparkles } from 'lucide-react'

import {
  moveContribution,
  propositionCount,
  taskCount,
  updateDescription,
  type ValueChainActivity,
  type ValueChainContribution,
  type ValueChainModel,
} from '../utils/valueChainModel'

export function ContributionCard({
  model,
  activity,
  contribution,
  onChange,
  selected,
  onSelect,
}: {
  model: ValueChainModel
  activity: ValueChainActivity
  contribution: ValueChainContribution
  onChange?: (model: ValueChainModel) => void
  selected?: boolean
  onSelect?: (activityId: string, partyId: string) => void
}) {
  const { activity_id: activityId, party_id: partyId } = contribution
  const editable = !!onChange

  return (
    <div
      data-testid={`card-${activityId}-${partyId}`}
      className={`bg-surface-card rounded-lg p-3 border ${
        selected ? 'border-brand' : 'border-transparent'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          data-testid={`card-header-${activityId}-${partyId}`}
          onClick={() => onSelect?.(activityId, partyId)}
          onKeyDown={(e) => {
            if (!editable) return
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
              e.preventDefault()
              onChange!(
                moveContribution(model, activityId, partyId, e.key === 'ArrowLeft' ? 'left' : 'right'),
              )
            }
          }}
          className="text-left flex-1"
        >
          <span className="block text-xs font-mono text-muted">{activityId}</span>
          <span className="block text-sm font-medium text-primary">{activity.label}</span>
        </button>

        {contribution.attribution === 'derived' && (
          <span
            data-testid={`derived-${activityId}-${partyId}`}
            title="Attributed by inference during migration, not stated in the source"
            className="flex items-center gap-1 text-xs text-secondary shrink-0"
          >
            <Sparkles className="w-3 h-3" aria-hidden="true" />
            Derived
          </span>
        )}
      </div>

      <input
        type="text"
        data-testid={`description-${activityId}-${partyId}`}
        // Controlled, never defaultValue. Cards key on the contribution's identity so a
        // move cannot put a different contribution behind an existing input node, and this
        // is the second defence on the same defect - it silently corrupted saved data.
        value={contribution.description ?? ''}
        readOnly={!editable}
        placeholder={editable ? 'Describe this contribution' : ''}
        onChange={(e) =>
          onChange?.(updateDescription(model, activityId, partyId, e.target.value))
        }
        className="mt-2 w-full bg-surface rounded px-2 py-1 text-xs text-secondary"
      />

      <div className="mt-2 flex items-center gap-3 text-xs text-muted">
        <span data-testid={`task-count-${activityId}-${partyId}`} className="flex items-center gap-1">
          <ListTree className="w-3 h-3" aria-hidden="true" />
          {taskCount(model, activityId, partyId)}
        </span>
        <span data-testid={`proposition-count-${activityId}`} className="flex items-center gap-1">
          <Lightbulb className="w-3 h-3" aria-hidden="true" />
          {propositionCount(model, activityId)}
        </span>

        {editable && (
          <span className="ml-auto flex items-center gap-1">
            <button
              type="button"
              data-testid={`move-left-${activityId}-${partyId}`}
              aria-label={`Move ${activity.label} left`}
              onClick={() => onChange!(moveContribution(model, activityId, partyId, 'left'))}
              className="text-secondary hover:text-brand"
            >
              <ChevronLeft className="w-4 h-4" aria-hidden="true" />
            </button>
            <button
              type="button"
              data-testid={`move-right-${activityId}-${partyId}`}
              aria-label={`Move ${activity.label} right`}
              onClick={() => onChange!(moveContribution(model, activityId, partyId, 'right'))}
              className="text-secondary hover:text-brand"
            >
              <ChevronRight className="w-4 h-4" aria-hidden="true" />
            </button>
          </span>
        )}
      </div>
    </div>
  )
}
