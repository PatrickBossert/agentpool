// ui/src/components/ContributionCard.tsx
// One party's contribution to one activity, as a card. Four sibling controls, never
// nested: the header (focus, move, open), the description input, the counts row, and -
// from Task 8 - the party menu. A handler on the card itself would fire on every
// interaction with any of them, and one placed above the input would swallow keystrokes
// typed into it.
//
// The party menu's open/closed state lives in the grid, not here, keyed on this card's
// (activityId, partyId) - one open menu at a time across the whole grid, so opening
// another card's menu closes this one rather than leaving both showing at once.
import { ChevronLeft, ChevronRight, ListTree, Lightbulb, Sparkles, Users } from 'lucide-react'

import {
  addParty,
  confirmAttribution,
  isLastContribution,
  moveContribution,
  partiesNotContributing,
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
  onRequestRemove,
  menuOpen = false,
  onToggleMenu,
}: {
  model: ValueChainModel
  activity: ValueChainActivity
  contribution: ValueChainContribution
  onChange?: (model: ValueChainModel) => void
  selected?: boolean
  onSelect?: (activityId: string, partyId: string) => void
  onRequestRemove?: (activityId: string, partyId: string) => void
  menuOpen?: boolean
  onToggleMenu?: () => void
}) {
  const { activity_id: activityId, party_id: partyId } = contribution
  const editable = !!onChange
  const available = partiesNotContributing(model, activityId)
  const lastOne = isLastContribution(model, activityId)

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
          draggable={editable}
          onDragStart={(e) => {
            // The payload carries the lane so the drop target can refuse a cross-lane drop
            // without needing any shared state.
            e.dataTransfer.setData('contributionActivityId', activityId)
            e.dataTransfer.setData('contributionPartyId', partyId)
            e.dataTransfer.effectAllowed = 'move'
          }}
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

        {contribution.attribution === 'derived' && editable && (
          <button
            type="button"
            data-testid={`confirm-attribution-${activityId}-${partyId}`}
            onClick={() => onChange!(confirmAttribution(model, activityId, partyId))}
            className="text-xs text-brand shrink-0"
          >
            Confirm
          </button>
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

      {editable && (
        <div className="mt-2 relative">
          <button
            type="button"
            data-testid={`party-menu-${activityId}-${partyId}`}
            aria-label={`Parties for ${activity.label}`}
            aria-expanded={menuOpen}
            onClick={() => onToggleMenu?.()}
            className="flex items-center gap-1 text-xs text-secondary hover:text-brand"
          >
            <Users className="w-3 h-3" aria-hidden="true" />
            Parties
          </button>

          {menuOpen && (
            <div className="absolute z-10 mt-1 bg-surface-raised rounded-lg p-2 shadow-lg min-w-[12rem]">
              {available.length === 0 ? (
                <p className="text-muted text-xs italic px-1 py-1">
                  Every party already contributes to this activity.
                </p>
              ) : (
                available.map((party) => (
                  <button
                    key={party.id}
                    type="button"
                    data-testid={`add-party-${activityId}-${partyId}-${party.id}`}
                    onClick={() => {
                      onChange!(addParty(model, activityId, party.id))
                      onToggleMenu?.()
                    }}
                    className="block w-full text-left text-xs text-primary px-1 py-1 hover:text-brand"
                  >
                    Add {party.label}
                  </button>
                ))
              )}

              <button
                type="button"
                data-testid={`remove-party-${activityId}-${partyId}`}
                disabled={lastOne}
                aria-describedby={lastOne ? `remove-why-${activityId}-${partyId}` : undefined}
                onClick={() => {
                  onRequestRemove?.(activityId, partyId)
                  onToggleMenu?.()
                }}
                className="block w-full text-left text-xs px-1 py-1 mt-1 border-t border-surface text-red-400 disabled:text-muted"
              >
                Remove this party
              </button>
              {lastOne && (
                <p id={`remove-why-${activityId}-${partyId}`} className="text-muted text-xs px-1">
                  The only party on this activity - removing it would make the activity
                  disappear from the chain.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
