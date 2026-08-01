// ui/src/components/ValueChainGrid.tsx
// One continuous CSS Grid for the whole chain: rows are party lanes spanning every segment,
// columns are chainColumns(model) - every segment's sparse column positions laid end to end -
// and a card sits at an explicit gridColumn/gridRow.
//
// The layout mechanism is the point. Snapping needs no implementation because a grid cell
// is the only place a card can be - there are no arbitrary coordinates to snap from, and
// nothing "between" two lanes to drop into. A free canvas has to be taught what a lane is,
// which is where the previous React Flow attempt spent its time.
//
// Every cell renders whether occupied or not, so a gap is a real position - and, from Task
// 6, a real drop target - rather than an absence.
import { useEffect, useRef, useState } from 'react'

import {
  chainColumns,
  contributionKey,
  moveToColumn,
  removeParty,
  type ValueChainModel,
  type ValueChainSelection,
} from '../utils/valueChainModel'
import { ContributionCard, partyMenuButtonId } from './ContributionCard'

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
  const [hoverCell, setHoverCell] = useState<{
    segmentId: string
    partyId: string
    column: number
  } | null>(null)
  // The party a card asked to remove, pending confirmation. Held here rather than in the
  // card because the card cannot know the cost of removal in isolation - only the grid,
  // which has the whole model, can name the tasks that would go with it.
  const [pendingRemoval, setPendingRemoval] = useState<{
    activityId: string
    partyId: string
  } | null>(null)
  // Which card's party menu is open, if any - one at a time across the whole grid, keyed
  // on the contribution's identity rather than the card holding its own boolean, so
  // opening a second card's menu closes the first instead of leaving both open.
  const [openMenu, setOpenMenu] = useState<{ activityId: string; partyId: string } | null>(
    null,
  )

  // The removal dialog is modal and covers the whole grid, so a keyboard-only user landed
  // nowhere when it opened. Focus moves into it on open, and back to the card's Parties
  // button on close - not to the Remove entry that opened it, which lives inside the menu
  // that closes as part of making the request. Deliberately not a focus trap.
  const removalDialog = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!pendingRemoval) return
    const { activityId, partyId } = pendingRemoval
    removalDialog.current?.focus()
    return () => document.getElementById(partyMenuButtonId(activityId, partyId))?.focus()
  }, [pendingRemoval])

  if (model.segments.length === 0) {
    return (
      <div data-testid="value-chain-empty" className="bg-surface-card rounded-xl p-8 text-center">
        <p className="text-muted text-sm">No value chain has been mapped yet.</p>
      </div>
    )
  }

  const columns = chainColumns(model)

  // chainColumns emits every column of a segment consecutively, so a run is a contiguous
  // slice. Grouping rather than counting per segment keeps the band aligned even if a segment
  // contributes no columns at all - it simply produces no band.
  const bands: { segmentId: string; start: number; span: number }[] = []
  columns.forEach((c, i) => {
    const last = bands[bands.length - 1]
    if (last && last.segmentId === c.segmentId) last.span += 1
    else bands.push({ segmentId: c.segmentId, start: i, span: 1 })
  })

  // activity id -> segment id. A cell must scope by segment or segment 1's column 10 and
  // segment 2's column 10 collapse into one.
  const segmentOf = (activityId: string) =>
    model.activities.find((a) => a.id === activityId)?.segment_id

  // Every party contributing somewhere in the chain gets a row spanning the whole chain -
  // not every party on the roster. A party with no contribution anywhere would be an
  // always-empty row, which is noise rather than information.
  const contributingPartyIds = new Set(model.contributions.map((c) => c.party_id))
  const lanes = model.parties.filter((p) => contributingPartyIds.has(p.id))

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
      <section data-testid="chain-grid" className="overflow-x-auto">
        <div
          className="grid gap-2 items-start"
          style={{
            gridTemplateColumns: `${GUTTER} repeat(${columns.length}, minmax(${COLUMN_WIDTH}, 1fr))`,
          }}
        >
          {/* Row 1: a band per segment, spanning that segment's own columns. Row 2: a
              header per column, labelled with the model's real column value, which is what
              makes a gap legible as a position rather than as whitespace. */}
          {bands.map((b) => (
            <div
              key={`band-${b.segmentId}`}
              data-testid={`segment-band-${b.segmentId}`}
              className="text-sm font-medium text-secondary uppercase tracking-wide pb-2"
              style={{ gridColumn: `${b.start + 2} / span ${b.span}`, gridRow: 1 }}
            >
              {model.segments.find((s) => s.id === b.segmentId)?.label}
            </div>
          ))}
          {columns.map((c, index) => (
            <div
              key={`${c.segmentId}-${c.column}`}
              data-testid={`column-header-${c.segmentId}-${c.column}`}
              className="text-xs text-muted font-mono pb-2 border-b border-surface"
              style={{ gridColumn: index + 2, gridRow: 2 }}
            >
              {c.column}
            </div>
          ))}

          {lanes.map((party, laneIndex) => {
            const laneContributions = model.contributions.filter((c) => c.party_id === party.id)
            return [
              <div
                key={`lane-${party.id}`}
                data-testid={`lane-${party.id}`}
                className="flex items-center gap-2 text-sm font-medium text-primary py-2"
                style={{ gridColumn: 1, gridRow: laneIndex + 3 }}
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
              ...columns.map((c, index) => {
                // A cell may resolve to more than one contribution - the model is what says
                // so, not a rendering bug, and hiding all but the first would make the
                // remaining contributions both invisible and undraggable at once. Every
                // occupant renders, stacked with an offset, so each stays clickable and
                // draggable and the stack can be pulled apart.
                const occupants = laneContributions.filter(
                  (contrib) => contrib.column === c.column && segmentOf(contrib.activity_id) === c.segmentId,
                )

                // A cell only invites a drop when it is in the dragged card's own lane -
                // highlighting a foreign lane would promise a drop the guard below is
                // going to refuse anyway.
                const acceptsDrag = draggingParty === party.id
                const isDragOver =
                  acceptsDrag &&
                  hoverCell?.segmentId === c.segmentId &&
                  hoverCell?.partyId === party.id &&
                  hoverCell?.column === c.column

                return (
                  <div
                    key={`cell-${c.segmentId}-${party.id}-${c.column}`}
                    data-testid={`cell-${c.segmentId}-${party.id}-${c.column}`}
                    className={`relative min-h-[5rem] rounded-lg border border-dashed transition-colors ${
                      isDragOver ? 'border-brand bg-brand/5' : 'border-surface'
                    }`}
                    style={{ gridColumn: index + 2, gridRow: laneIndex + 3 }}
                    onDragOver={
                      onChange
                        ? (e) => {
                            if (!acceptsDrag) return
                            e.preventDefault()
                            e.dataTransfer.dropEffect = 'move'
                            setHoverCell({ segmentId: c.segmentId, partyId: party.id, column: c.column })
                          }
                        : undefined
                    }
                    onDragLeave={
                      onChange
                        ? () =>
                            setHoverCell((current) =>
                              current?.segmentId === c.segmentId &&
                              current?.partyId === party.id &&
                              current?.column === c.column
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
                            // A card may only land within its own segment: its segment
                            // comes from its activity, and moveToColumn writes only the
                            // .column field, so a cross-segment drop would not reposition
                            // the contribution - it would re-parent the activity under a
                            // numeric coincidence while leaving it recorded in the segment
                            // it was dragged from, reappearing somewhere the drop never
                            // touched. Reuses segmentOf rather than a second lookup.
                            if (segmentOf(activityId) !== c.segmentId) return
                            onChange(moveToColumn(model, activityId, draggedParty, c.column))
                          }
                        : undefined
                    }
                  >
                    {occupants.length > 1 && (
                      // Amber is this codebase's warning convention. The number is the
                      // count sharing the cell, not a rank - a person decides which
                      // contribution belongs where; this only says a decision is owed.
                      <span
                        data-testid={`cell-overlap-${c.segmentId}-${party.id}-${c.column}`}
                        className="absolute top-0 right-0 z-10 flex items-center justify-center w-4 h-4 rounded-full bg-amber-500 text-[10px] font-medium text-white"
                        title={`${occupants.length} contributions share this cell - drag each to reposition`}
                      >
                        {occupants.length}
                      </span>
                    )}
                    {occupants.map((occupant, occupantIndex) => {
                      const activity = model.activities.find(
                        (a) => a.id === occupant.activity_id,
                      )
                      if (!activity) return null
                      return (
                        // Keyed on the contribution's identity, never on the column or
                        // its index in this list. Key on either of those and a move
                        // changes which contribution sits behind a key, so React reuses
                        // a dirty input against the wrong one.
                        //
                        // The first occupant sits in normal flow, sizing the cell; every
                        // later one is offset diagonally over it, and stacked higher in
                        // z-order, so a person can still see and reach each header to
                        // drag it apart - the model owns the overlap, not this offset.
                        <div
                          key={contributionKey(activity.id, party.id)}
                          className={occupantIndex === 0 ? 'relative' : 'relative -mt-16'}
                          style={{
                            zIndex: occupantIndex + 1,
                            transform:
                              occupantIndex > 0
                                ? `translate(${occupantIndex * 0.5}rem, ${occupantIndex * 0.5}rem)`
                                : undefined,
                          }}
                        >
                          <ContributionCard
                            model={model}
                            activity={activity}
                            contribution={occupant}
                            onChange={onChange}
                            onSelect={onSelect}
                            onRequestRemove={(activityId, partyId) =>
                              setPendingRemoval({ activityId, partyId })
                            }
                            menuOpen={
                              openMenu?.activityId === activity.id &&
                              openMenu?.partyId === party.id
                            }
                            onToggleMenu={() =>
                              setOpenMenu((current) =>
                                current?.activityId === activity.id &&
                                current?.partyId === party.id
                                  ? null
                                  : { activityId: activity.id, partyId: party.id },
                              )
                            }
                            selected={
                              selected?.activityId === activity.id &&
                              selected?.partyId === party.id
                            }
                          />
                        </div>
                      )
                    })}
                  </div>
                )
              }),
            ]
          })}
        </div>
      </section>

      {pendingRemoval && (() => {
        const activity = model.activities.find((a) => a.id === pendingRemoval.activityId)
        const party = model.parties.find((p) => p.id === pendingRemoval.partyId)
        const doomed = model.tasks.filter(
          (t) =>
            t.activity_id === pendingRemoval.activityId &&
            t.party_id === pendingRemoval.partyId,
        )
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div
              ref={removalDialog}
              role="dialog"
              aria-modal="true"
              aria-label="Confirm removal"
              tabIndex={-1}
              className="bg-surface-raised rounded-xl max-w-md w-full p-5 outline-none"
            >
              <h3 className="text-sm font-medium text-primary">
                Remove {party?.label} from {activity?.label}?
              </h3>
              {/* Tasks belong to the contribution, so they go with it. Saying how many, and
                  which, is what makes this a decision rather than a surprise. */}
              {doomed.length > 0 && (
                <>
                  <p className="mt-2 text-xs text-secondary">
                    {party?.label} owns {doomed.length} task
                    {doomed.length === 1 ? '' : 's'} here. Removing the party deletes them.
                  </p>
                  <ul className="mt-2 text-xs text-muted space-y-1">
                    {doomed.map((task) => (
                      <li key={task.id}>
                        <span className="font-mono">{task.id}</span> {task.label ?? ''}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <p className="mt-3 text-xs text-muted">
                The saved version is unchanged until you save, so this can be reverted.
              </p>
              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  data-testid="cancel-remove"
                  onClick={() => setPendingRemoval(null)}
                  className="text-xs text-secondary px-3 py-1"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  data-testid="confirm-remove"
                  onClick={() => {
                    onChange!(
                      removeParty(model, pendingRemoval.activityId, pendingRemoval.partyId),
                    )
                    setPendingRemoval(null)
                  }}
                  className="text-xs bg-brand text-white rounded px-3 py-1"
                >
                  {doomed.length > 0
                    ? `Remove and delete ${doomed.length}`
                    : 'Remove'}
                </button>
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
