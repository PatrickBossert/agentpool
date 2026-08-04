// ui/src/components/ValueChainGrid.tsx
// One CSS Grid per value chain, stacked vertically. Within a chain, rows are the party
// lanes that contribute to it, columns are that chain's own sparse positions, and a card
// sits at an explicit gridColumn/gridRow.
//
// Per chain rather than one continuous run, which is what this was until the three chains
// came back: laid end to end, seeing Fleet means scrolling past the whole of Property, and
// a party's lane spans chains it has nothing to do with. There is no shared column axis and
// so no column ruler - a stage in one chain has no counterpart in another.
//
// The layout mechanism is the point. Snapping needs no implementation because a grid cell
// is the only place a card can be - there are no arbitrary coordinates to snap from, and
// nothing "between" two lanes to drop into. A free canvas has to be taught what a lane is,
// which is where the previous React Flow attempt spent its time.
//
// Every cell renders whether occupied or not, so a gap is a real position - and, from Task
// 6, a real drop target - rather than an absence.
import { useEffect, useRef, useState } from 'react'
import { Minus, Plus } from 'lucide-react'

import {
  columnRange,
  contributionKey,
  moveToColumn,
  removeParty,
  type ValueChainModel,
  type ValueChainSelection,
} from '../utils/valueChainModel'
import { ContributionCard, partyMenuButtonId } from './ContributionCard'

const GUTTER = '10rem'
const COLUMN_WIDTH = '13rem'

// 325rem of chain at full size cannot be taken in at a glance, so zoom is a scale on the
// grid itself rather than a way of hiding parts of it - a person can stand back to see the
// whole shape, then step back in to work a segment. Rounded to one decimal place on every
// step because repeated 0.2 subtraction drifts in floating point (1 - 0.2 - 0.2 - 0.2 is
// not exactly 0.4) and an off-by-a-fraction zoom would never reach the floor.
const ZOOM_STEP = 0.2
const ZOOM_MIN = 0.4
const ZOOM_MAX = 1.4

// How far each buried card in a collision is stepped down. Its job is to leave the card
// beneath it showing its number and label line - the header, which is the drag handle that
// pulls the stack apart. Stated here rather than derived from the card's height, which is
// what the previous -mt-16 did by subtraction and which therefore changed every time the
// card did.
const STACK_STEP_REM = 2

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
  const [draggingSegment, setDraggingSegment] = useState<string | null>(null)
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

  // The grid, not the page, scales - the entity column and segment band are inside the
  // transformed element, so they shrink with the chain rather than drifting out of line
  // with it. The scroll container that wraps it is untransformed, so scrolling still works
  // in real (unscaled) pixels at any zoom level.
  const [zoom, setZoom] = useState(1)
  const zoomOut = () => setZoom((z) => Math.max(ZOOM_MIN, Math.round((z - ZOOM_STEP) * 10) / 10))
  const zoomIn = () => setZoom((z) => Math.min(ZOOM_MAX, Math.round((z + ZOOM_STEP) * 10) / 10))

  // A click anywhere else dismisses the open parties menu. The listener lives here rather
  // than in the card because the open menu is the grid's state - one at a time across the
  // whole grid - so the card has nothing to close.
  //
  // The trigger is excluded deliberately. Without that exclusion its mousedown would close
  // the menu and its own click would toggle it back open, so the control would appear
  // never to close anything.
  useEffect(() => {
    if (!openMenu) return
    const dismiss = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('[data-party-menu], [data-party-menu-trigger]')) return
      setOpenMenu(null)
    }
    document.addEventListener('mousedown', dismiss)
    return () => document.removeEventListener('mousedown', dismiss)
  }, [openMenu])

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

  // activity id -> segment id. A cell must scope by segment, or chain 1's column 10 and
  // chain 2's column 10 collapse into one.
  const segmentOf = (activityId: string) =>
    model.activities.find((a) => a.id === activityId)?.segment_id

  // One block per chain, stacked. Laid side by side on a single horizontal run - which is
  // what a shared column axis produces - seeing Fleet means scrolling past the whole of
  // Property, and one party's lane spans all three chains at once. That is meaningless
  // when the chains have different parties: ISS maintains property and DXI maintains
  // fleet, so neither belongs in the other's chain even as an empty row.
  const chains = model.segments
    .map((segment) => {
      const contributions = model.contributions.filter(
        (c) => segmentOf(c.activity_id) === segment.id,
      )
      const partyIds = new Set(contributions.map((c) => c.party_id))
      return {
        segment,
        contributions,
        // Each chain's columns start again at its own first. They are not slices of a
        // shared axis - a stage in one chain has no counterpart in another, which is why
        // there is no column ruler and no stage heading.
        columns: columnRange(contributions.map((c) => c.column)),
        // Only the parties that contribute in this chain. A party absent from it has no
        // row here: the view is for flow and who does what, in what order, and an
        // always-empty lane serves neither.
        //
        // Ordered by where each party's work starts, so the lanes read down in the order
        // the chain runs - the reader's eye goes top-left to bottom-right and follows the
        // flow. Not by contribution count, which would be a popularity ordering rather
        // than a positional one, and not by declaration order: the recovered model lists
        // the custodian last, which would bury the party that opens all three chains.
        // Ties keep declaration order, so parties starting together stay put.
        lanes: model.parties
          .filter((p) => partyIds.has(p.id))
          .map((party, order) => ({
            party,
            order,
            start: Math.min(
              ...contributions.filter((c) => c.party_id === party.id).map((c) => c.column),
            ),
          }))
          .sort((a, b) => a.start - b.start || a.order - b.order)
          .map((entry) => entry.party),
      }
    })
    .filter((chain) => chain.lanes.length > 0)

  return (
    <div
      className="space-y-8"
      onDragStart={
        onChange
          ? (e) => {
              setDraggingParty(e.dataTransfer.getData('contributionPartyId'))
              setDraggingSegment(segmentOf(e.dataTransfer.getData('contributionActivityId')) ?? null)
            }
          : undefined
      }
      onDragEnd={
        onChange
          ? () => {
              setDraggingParty(null)
              setDraggingSegment(null)
            }
          : undefined
      }
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          data-testid="zoom-out"
          onClick={zoomOut}
          disabled={zoom <= ZOOM_MIN}
          aria-label="Zoom out"
          className="p-1 rounded border border-surface text-secondary disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Minus className="w-4 h-4" />
        </button>
        <span data-testid="zoom-level" className="w-12 text-center text-xs text-muted font-mono">
          {Math.round(zoom * 100)}%
        </span>
        <button
          type="button"
          data-testid="zoom-in"
          onClick={zoomIn}
          disabled={zoom >= ZOOM_MAX}
          aria-label="Zoom in"
          className="p-1 rounded border border-surface text-secondary disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>

      {chains.map(({ segment, contributions, columns, lanes }) => (
        <section key={`chain-${segment.id}`} className="space-y-2">
          {/* The chain's name sits above its own block rather than inside the grid: with
              one grid per chain there is nothing to span, and no column ruler beneath it -
              a stage in one chain has no counterpart in another, so a shared heading row
              would assert an alignment that does not exist. */}
          <h3
            data-testid={`segment-band-${segment.id}`}
            className="text-sm font-medium text-secondary uppercase tracking-wide"
          >
            <span className="font-mono">{segment.id}</span> {segment.label}
          </h3>

          <div className="overflow-x-auto">
        <div
          data-testid={`chain-grid-${segment.id}`}
          className="grid gap-2 items-start"
          style={{
            gridTemplateColumns: `${GUTTER} repeat(${columns.length}, minmax(${COLUMN_WIDTH}, 1fr))`,
            transform: `scale(${zoom})`,
            transformOrigin: 'top left',
          }}
        >
          {lanes.map((party, laneIndex) => {
            const laneContributions = contributions.filter((c) => c.party_id === party.id)
            return [
              <div
                key={`lane-${party.id}`}
                data-testid={`lane-${segment.id}-${party.id}`}
                className="flex items-center gap-2 text-sm font-medium text-primary py-2"
                style={{ gridColumn: 1, gridRow: laneIndex + 1 }}
              >
                {party.colour && (
                  <span
                    aria-hidden="true"
                    className="inline-block w-2 h-2 rounded-full shrink-0"
                    style={{ backgroundColor: party.colour }}
                  />
                )}
                <span>{party.label}</span>
                <span data-testid={`lane-count-${segment.id}-${party.id}`} className="text-muted text-xs">
                  {laneContributions.length}
                </span>
              </div>,
              ...columns.map((column, index) => {
                // A cell may resolve to more than one contribution - the model is what says
                // so, not a rendering bug, and hiding all but the first would make the
                // remaining contributions both invisible and undraggable at once. Every
                // occupant renders, stacked with an offset, so each stays clickable and
                // draggable and the stack can be pulled apart.
                // laneContributions is already scoped to this chain, so the column alone
                // identifies the cell - no second segment check is needed here.
                const occupants = laneContributions.filter((contrib) => contrib.column === column)

                // A cell only invites a drop when it is in the dragged card's own lane and
                // own segment - the drop guard below refuses both a cross-lane and a
                // cross-segment drop, so highlighting either would promise a drop that
                // refusal is going to undo.
                const acceptsDrag = draggingParty === party.id && draggingSegment === segment.id
                const isDragOver =
                  acceptsDrag &&
                  hoverCell?.segmentId === segment.id &&
                  hoverCell?.partyId === party.id &&
                  hoverCell?.column === column

                return (
                  <div
                    key={`cell-${segment.id}-${party.id}-${column}`}
                    data-testid={`cell-${segment.id}-${party.id}-${column}`}
                    className={`relative min-h-[5rem] rounded-lg border border-dashed transition-colors ${
                      isDragOver ? 'border-brand bg-brand/5' : 'border-surface'
                    }`}
                    style={{ gridColumn: index + 2, gridRow: laneIndex + 1 }}
                    onDragOver={
                      onChange
                        ? (e) => {
                            if (!acceptsDrag) return
                            e.preventDefault()
                            e.dataTransfer.dropEffect = 'move'
                            setHoverCell({ segmentId: segment.id, partyId: party.id, column: column })
                          }
                        : undefined
                    }
                    onDragLeave={
                      onChange
                        ? () =>
                            setHoverCell((current) =>
                              current?.segmentId === segment.id &&
                              current?.partyId === party.id &&
                              current?.column === column
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
                            if (segmentOf(activityId) !== segment.id) return
                            onChange(moveToColumn(model, activityId, draggedParty, column))
                          }
                        : undefined
                    }
                  >
                    {occupants.length > 1 && (
                      // Amber is this codebase's warning convention. The number is the
                      // count sharing the cell, not a rank - a person decides which
                      // contribution belongs where; this only says a decision is owed.
                      <span
                        data-testid={`cell-overlap-${segment.id}-${party.id}-${column}`}
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
                        // The first occupant sits in normal flow and alone sizes the cell;
                        // every later one is taken out of flow and stepped diagonally over
                        // it, stacked higher in z-order, so a person can still see and
                        // reach each header to drag it apart - the model owns the overlap,
                        // not this offset. Out of flow rather than pulled up by a negative
                        // margin: that margin was subtracted from the card's height, so the
                        // step it produced was the leftover and grew every time the card
                        // did, and a 3-deep collision made its whole row three cards tall.
                        <div
                          key={contributionKey(activity.id, party.id)}
                          className={occupantIndex === 0 ? 'relative' : 'absolute inset-x-0'}
                          style={{
                            zIndex: occupantIndex + 1,
                            top:
                              occupantIndex > 0
                                ? `${occupantIndex * STACK_STEP_REM}rem`
                                : undefined,
                            marginLeft:
                              occupantIndex > 0 ? `${occupantIndex * 0.5}rem` : undefined,
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
          </div>
        </section>
      ))}

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
