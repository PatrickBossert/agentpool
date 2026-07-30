// ui/src/components/ValueChainTable.tsx
import { ChevronLeft, ChevronRight, Sparkles } from 'lucide-react'

export type ValueChainAttribution = 'stated' | 'derived'

export interface ValueChainParty {
  id: string
  label: string
  description?: string
  colour?: string
}

export interface ValueChainSegment {
  id: string
  label: string
  description?: string
}

export interface ValueChainActivity {
  id: string
  segment_id: string
  label: string
  description?: string
  active?: boolean
}

export interface ValueChainContribution {
  activity_id: string
  party_id: string
  column: number
  description?: string
  attribution: ValueChainAttribution
}

export interface ValueChainTask {
  activity_id: string
  party_id: string
  id: string
  label?: string
  description?: string
}

export interface ValueChainProposition {
  id: string
  activity_id: string
  description?: string
  // A proposition attaches to the activity as a whole, but may still name the party it
  // was raised about - shown by ContributionPanel when present, omitted otherwise.
  party_id?: string
}

// Links aren't rendered by this read-only table; keep the shape loose.
export type ValueChainLink = Record<string, unknown>

export interface ValueChainModel {
  model_version: number
  parties: ValueChainParty[]
  segments: ValueChainSegment[]
  activities: ValueChainActivity[]
  contributions: ValueChainContribution[]
  tasks: ValueChainTask[]
  propositions: ValueChainProposition[]
  links: ValueChainLink[]
}

const COLUMN_STEP = 10

// Columns are sparse, assigned in steps of ten. The union of columns actually used by
// lanes in a segment defines a range; every step within that range renders, whether or
// not a contribution occupies it, so a gap between two used columns stays visible rather
// than collapsing away.
function columnRange(usedColumns: number[]): number[] {
  if (usedColumns.length === 0) return []
  const min = Math.min(...usedColumns)
  const max = Math.max(...usedColumns)
  const range: number[] = []
  for (let column = min; column <= max; column += COLUMN_STEP) range.push(column)
  return range
}

// Moving a contribution changes only .column fields - never an activity, party,
// description, attribution or anything else. The invariant this must hold: after any
// move, no two contributions of the same party within the same segment share a column.
// The target is the adjacent step (column ± COLUMN_STEP). If another contribution in the
// same lane and segment already sits there, the two exchange columns - each keeps every
// other field - otherwise the mover simply takes the target. A move into an empty column
// steps into the gap rather than jumping over it: a gap is a real position, not blank
// space, so leapfrogging past one to the next occupied column would silently discard it.
// "Lane" is scoped to the party's row within the segment the moved activity belongs to,
// matching how the table itself groups contributions into rows.
function moveContribution(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
  direction: 'left' | 'right',
): ValueChainModel {
  const next = structuredClone(model)
  const contribution = next.contributions.find(
    (c) => c.activity_id === activityId && c.party_id === partyId,
  )
  if (!contribution) return next

  const activity = next.activities.find((a) => a.id === activityId)
  const segmentActivityIds = new Set(
    next.activities.filter((a) => a.segment_id === activity?.segment_id).map((a) => a.id),
  )

  const target = contribution.column + (direction === 'right' ? COLUMN_STEP : -COLUMN_STEP)

  const occupant = next.contributions.find(
    (c) =>
      c.party_id === partyId &&
      segmentActivityIds.has(c.activity_id) &&
      c.activity_id !== activityId &&
      c.column === target,
  )

  if (occupant) occupant.column = contribution.column
  contribution.column = target

  return next
}

function updateDescription(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
  description: string,
): ValueChainModel {
  const next = structuredClone(model)
  const contribution = next.contributions.find(
    (c) => c.activity_id === activityId && c.party_id === partyId,
  )
  if (contribution) contribution.description = description
  return next
}

export interface ValueChainSelection {
  activityId: string
  partyId: string
}

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
                                      defaultValue={contribution.description ?? ''}
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
