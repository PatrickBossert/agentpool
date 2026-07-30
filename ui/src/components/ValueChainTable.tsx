// ui/src/components/ValueChainTable.tsx
import { ChevronLeft, ChevronRight, Sparkles } from 'lucide-react'

import {
  columnRange,
  moveContribution,
  updateDescription,
  type ValueChainModel,
  type ValueChainSelection,
} from '../utils/valueChainModel'

// Re-exported for now: Task 5 deletes this component, and every importer moves to
// utils/valueChainModel then. Re-exporting here keeps this task a pure move with no
// behaviour change and no churn in files it does not otherwise touch.
export type { ValueChainModel, ValueChainSelection } from '../utils/valueChainModel'

export function ValueChainTable({
  model,
  onChange,
  selected,
  onSelect,
}: {
  model: ValueChainModel
  onChange?: (model: ValueChainModel) => void
  selected?: ValueChainSelection | null
  onSelect?: (activityId: string, partyId: string) => void
}) {
  if (model.segments.length === 0) {
    return (
      <div data-testid="value-chain-empty" className="bg-surface-card rounded-xl p-8 text-center">
        <p className="text-muted text-sm">No value chain has been mapped yet.</p>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {model.segments.map((segment) => {
        const activityIds = new Set(
          model.activities.filter((a) => a.segment_id === segment.id).map((a) => a.id),
        )
        const segmentContributions = model.contributions.filter((c) => activityIds.has(c.activity_id))
        const laneIds = Array.from(new Set(segmentContributions.map((c) => c.party_id)))
        const lanes = model.parties.filter((p) => laneIds.includes(p.id))
        const columns = columnRange(segmentContributions.map((c) => c.column))

        return (
          <section key={segment.id}>
            <h3 className="text-sm font-medium text-secondary uppercase tracking-wide mb-3">
              {segment.label}
            </h3>

            {lanes.length === 0 || columns.length === 0 ? (
              <p className="text-muted text-sm italic">No activity has been mapped in this segment yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm border-collapse">
                  <tbody>
                    {lanes.map((party) => (
                      <tr key={party.id} className="border-b border-surface">
                        <th
                          scope="row"
                          className="py-2 pr-4 text-left font-medium text-primary whitespace-nowrap align-top"
                        >
                          {party.colour && (
                            <span
                              aria-hidden="true"
                              className="inline-block w-2 h-2 rounded-full mr-2"
                              style={{ backgroundColor: party.colour }}
                            />
                          )}
                          {party.label}
                        </th>
                        {columns.map((column) => {
                          const contribution = segmentContributions.find(
                            (c) => c.party_id === party.id && c.column === column,
                          )
                          const activity = contribution
                            ? model.activities.find((a) => a.id === contribution.activity_id)
                            : undefined

                          const isSelected =
                            !!contribution &&
                            selected?.activityId === contribution.activity_id &&
                            selected?.partyId === contribution.party_id

                          return (
                            <td
                              key={column}
                              data-testid={`cell-${party.id}-${column}`}
                              className={`py-2 px-3 align-top border-l border-surface min-w-[10rem] ${
                                isSelected ? 'bg-brand/5' : ''
                              }`}
                            >
                              {contribution && activity && (
                                <div>
                                  {/* Selecting is its own control, separate from the description
                                      field below - so typing a description never bubbles into a
                                      selection handler, and selecting never steals input focus. */}
                                  {onSelect ? (
                                    <button
                                      type="button"
                                      data-testid={`select-${activity.id}-${party.id}`}
                                      aria-pressed={isSelected}
                                      onClick={() => onSelect(activity.id, party.id)}
                                      className={`block text-left font-medium rounded outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                                        isSelected ? 'text-brand' : 'text-primary hover:text-brand'
                                      }`}
                                    >
                                      {activity.label}
                                    </button>
                                  ) : (
                                    <p className="font-medium text-primary">{activity.label}</p>
                                  )}
                                  {onChange ? (
                                    <input
                                      type="text"
                                      data-testid={`description-${activity.id}-${party.id}`}
                                      // Controlled, not defaultValue. Cells are keyed by
                                      // column, so a move hands this same input node to a
                                      // different contribution - an uncontrolled field
                                      // would keep the old text, show it against the wrong
                                      // activity, and let the next keystroke save it there.
                                      value={contribution.description ?? ''}
                                      onChange={(e) =>
                                        onChange(
                                          updateDescription(model, activity.id, party.id, e.target.value),
                                        )
                                      }
                                      className="w-full bg-surface border border-surface rounded px-1.5 py-0.5 text-xs text-muted mt-0.5 outline-none focus:border-brand"
                                    />
                                  ) : (
                                    contribution.description && (
                                      <p className="text-muted text-xs mt-0.5">{contribution.description}</p>
                                    )
                                  )}
                                  {contribution.attribution === 'derived' && (
                                    <span className="inline-flex items-center gap-1 text-brand bg-brand/10 px-1.5 py-0.5 rounded text-xs font-medium mt-1">
                                      <Sparkles className="w-3 h-3" aria-hidden="true" />
                                      Derived
                                    </span>
                                  )}
                                  {onChange && (
                                    <div className="flex items-center gap-1 mt-1">
                                      <button
                                        type="button"
                                        data-testid={`move-left-${activity.id}-${party.id}`}
                                        aria-label={`Move ${activity.label} left for ${party.label}`}
                                        onClick={() =>
                                          onChange(moveContribution(model, activity.id, party.id, 'left'))
                                        }
                                        className="p-0.5 rounded text-secondary hover:text-brand hover:bg-brand/10"
                                      >
                                        <ChevronLeft className="w-3.5 h-3.5" aria-hidden="true" />
                                      </button>
                                      <button
                                        type="button"
                                        data-testid={`move-right-${activity.id}-${party.id}`}
                                        aria-label={`Move ${activity.label} right for ${party.label}`}
                                        onClick={() =>
                                          onChange(moveContribution(model, activity.id, party.id, 'right'))
                                        }
                                        className="p-0.5 rounded text-secondary hover:text-brand hover:bg-brand/10"
                                      >
                                        <ChevronRight className="w-3.5 h-3.5" aria-hidden="true" />
                                      </button>
                                    </div>
                                  )}
                                </div>
                              )}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}

export default ValueChainTable
