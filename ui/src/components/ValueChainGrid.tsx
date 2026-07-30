// ui/src/components/ValueChainGrid.tsx
// One CSS Grid per segment: rows are party lanes, columns are the segment's sparse column
// positions, and a card sits at an explicit gridColumn/gridRow.
//
// The layout mechanism is the point. Snapping needs no implementation because a grid cell
// is the only place a card can be - there are no arbitrary coordinates to snap from, and
// nothing "between" two lanes to drop into. A free canvas has to be taught what a lane is,
// which is where the previous React Flow attempt spent its time.
//
// Every cell renders whether occupied or not, so a gap is a real position - and, from Task
// 6, a real drop target - rather than an absence.
import { useState } from 'react'

import {
  columnRange,
  contributionKey,
  moveToColumn,
  type ValueChainModel,
  type ValueChainSelection,
} from '../utils/valueChainModel'
import { ContributionCard } from './ContributionCard'

const GUTTER = '10rem'
const COLUMN_WIDTH = '13rem'

export function ValueChainGrid({
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
  // Which party is currently being dragged, and which cell the pointer is over - both
  // derived here, at the grid, rather than read fresh from dataTransfer in every cell's
  // onDragOver. A cell only shows the "this will accept the drop" cue when its own lane
  // matches the dragged party, which needs the dragged party known before the pointer ever
  // reaches a given cell.
  const [draggingParty, setDraggingParty] = useState<string | null>(null)
  const [hoverCell, setHoverCell] = useState<{ partyId: string; column: number } | null>(null)

  if (model.segments.length === 0) {
    return (
      <div data-testid="value-chain-empty" className="bg-surface-card rounded-xl p-8 text-center">
        <p className="text-muted text-sm">No value chain has been mapped yet.</p>
      </div>
    )
  }

  return (
    <div
      className="space-y-8"
      onDragStart={
        onChange
          ? (e) => setDraggingParty(e.dataTransfer.getData('contributionPartyId'))
          : undefined
      }
      onDragEnd={onChange ? () => setDraggingParty(null) : undefined}
    >
      {model.segments.map((segment) => {
        const activityIds = new Set(
          model.activities.filter((a) => a.segment_id === segment.id).map((a) => a.id),
        )
        const segmentContributions = model.contributions.filter((c) =>
          activityIds.has(c.activity_id),
        )
        const laneIds = Array.from(new Set(segmentContributions.map((c) => c.party_id)))
        const lanes = model.parties.filter((p) => laneIds.includes(p.id))
        const columns = columnRange(segmentContributions.map((c) => c.column))

        if (lanes.length === 0 || columns.length === 0) {
          return (
            <section key={segment.id} data-testid={`grid-segment-${segment.id}`}>
              <div data-testid={`segment-gutter-${segment.id}`} className="text-sm font-medium text-secondary uppercase tracking-wide">
                {segment.label}
              </div>
              <p className="text-muted text-sm italic mt-2">
                No activity has been mapped in this segment yet.
              </p>
            </section>
          )
        }

        return (
          <section key={segment.id} data-testid={`grid-segment-${segment.id}`} className="overflow-x-auto">
            <div
              className="grid gap-2 items-start"
              style={{
                gridTemplateColumns: `${GUTTER} repeat(${columns.length}, minmax(${COLUMN_WIDTH}, 1fr))`,
              }}
            >
              {/* Header row: the gutter names the segment, then a label per column. The
                  numbers are the model's real column values, which is what makes a gap
                  legible as a position rather than as whitespace. */}
              <div
                data-testid={`segment-gutter-${segment.id}`}
                className="text-sm font-medium text-secondary uppercase tracking-wide self-end pb-2"
                style={{ gridColumn: 1, gridRow: 1 }}
              >
                {segment.label}
              </div>
              {columns.map((column, index) => (
                <div
                  key={column}
                  data-testid={`column-header-${column}`}
                  className="text-xs text-muted font-mono pb-2 border-b border-surface"
                  style={{ gridColumn: index + 2, gridRow: 1 }}
                >
                  {column}
                </div>
              ))}

              {lanes.map((party, laneIndex) => {
                const laneContributions = segmentContributions.filter(
                  (c) => c.party_id === party.id,
                )
                return [
                  <div
                    key={`lane-${party.id}`}
                    data-testid={`lane-${party.id}`}
                    className="flex items-center gap-2 text-sm font-medium text-primary py-2"
                    style={{ gridColumn: 1, gridRow: laneIndex + 2 }}
                  >
                    {party.colour && (
                      <span
                        aria-hidden="true"
                        className="inline-block w-2 h-2 rounded-full shrink-0"
                        style={{ backgroundColor: party.colour }}
                      />
                    )}
                    <span>{party.label}</span>
                    <span data-testid={`lane-count-${party.id}`} className="text-muted text-xs">
                      {laneContributions.length}
                    </span>
                  </div>,
                  ...columns.map((column, index) => {
                    const contribution = laneContributions.find((c) => c.column === column)
                    const activity = contribution
                      ? model.activities.find((a) => a.id === contribution.activity_id)
                      : undefined

                    // A cell only invites a drop when it is in the dragged card's own lane -
                    // highlighting a foreign lane would promise a drop the guard below is
                    // going to refuse anyway.
                    const acceptsDrag = draggingParty === party.id
                    const isDragOver =
                      acceptsDrag && hoverCell?.partyId === party.id && hoverCell?.column === column

                    return (
                      <div
                        key={`cell-${party.id}-${column}`}
                        data-testid={`cell-${party.id}-${column}`}
                        className={`min-h-[5rem] rounded-lg border border-dashed transition-colors ${
                          isDragOver ? 'border-brand bg-brand/5' : 'border-surface'
                        }`}
                        style={{ gridColumn: index + 2, gridRow: laneIndex + 2 }}
                        onDragOver={
                          onChange
                            ? (e) => {
                                if (!acceptsDrag) return
                                e.preventDefault()
                                e.dataTransfer.dropEffect = 'move'
                                setHoverCell({ partyId: party.id, column })
                              }
                            : undefined
                        }
                        onDragLeave={
                          onChange
                            ? () =>
                                setHoverCell((current) =>
                                  current?.partyId === party.id && current?.column === column
                                    ? null
                                    : current,
                                )
                            : undefined
                        }
                        onDrop={
                          onChange
                            ? (e) => {
                                e.preventDefault()
                                setHoverCell(null)
                                const activityId = e.dataTransfer.getData('contributionActivityId')
                                const draggedParty = e.dataTransfer.getData('contributionPartyId')
                                // A card may only land in its own lane: a contribution's
                                // identity is (activity, party), so a cross-lane drop would
                                // change what it is rather than where it sits.
                                if (!activityId || draggedParty !== party.id) return
                                onChange(moveToColumn(model, activityId, draggedParty, column))
                              }
                            : undefined
                        }
                      >
                        {contribution && activity && (
                          // Keyed on the contribution's identity, never on the column. Key
                          // on column and a move changes which contribution sits behind a
                          // key, so React reuses a dirty input against the wrong one.
                          <ContributionCard
                            key={contributionKey(activity.id, party.id)}
                            model={model}
                            activity={activity}
                            contribution={contribution}
                            onChange={onChange}
                            onSelect={onSelect}
                            selected={
                              selected?.activityId === activity.id &&
                              selected?.partyId === party.id
                            }
                          />
                        )}
                      </div>
                    )
                  }),
                ]
              })}
            </div>
          </section>
        )
      })}
    </div>
  )
}
