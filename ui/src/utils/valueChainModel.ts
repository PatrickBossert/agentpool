// ui/src/utils/valueChainModel.ts
// The value chain model and every pure operation on it. No React import: the operations are
// what the views are built from, and keeping them here means they can be tested without
// rendering anything, and that deleting a view does not move the types.

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

// Links aren't rendered by the grid; keep the shape loose.
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

export const COLUMN_STEP = 10

// Columns are sparse, assigned in steps of ten. The range is built from the columns
// actually used by lanes in a segment, with the steps between them filled in, so a gap
// between two used columns stays visible rather than collapsing away.
//
// It cannot be generated as min, min+10, min+20… : columns are sparse precisely so that
// inserting between two neighbours picks an intermediate value rather than renumbering the
// segment, so a column that is not congruent to the minimum modulo ten is expected. Such a
// column used to fall outside the sequence and render nowhere - invisible and uneditable,
// while still present in the saved model and still counted by validation. Every occupied
// column therefore appears exactly once, in order, whatever its value.
export function columnRange(usedColumns: number[]): number[] {
  const used = Array.from(new Set(usedColumns)).sort((a, b) => a - b)
  if (used.length === 0) return []

  const range: number[] = [used[0]]
  for (const column of used.slice(1)) {
    // Fill the whole steps between the previous occupied column and this one; each is a
    // real position that happens to be unoccupied, which is what a gap is.
    for (let filler = range[range.length - 1] + COLUMN_STEP; filler < column; filler += COLUMN_STEP) {
      range.push(filler)
    }
    range.push(column)
  }
  return range
}

// THE LANE-UNIQUENESS INVARIANT, which every mutation below must hold: no two
// contributions of the same party within the same segment share a column. A lane is one
// party's row within one segment, and the grid renders one card per (lane, column) cell -
// so a second contribution in an occupied cell simply never appears, while validate_model
// still counts it and refuses every subsequent save.
//
// "Within the same segment" is load-bearing, not decoration: columns restart at 10 in every
// segment, so an unscoped occupant search would reach into a neighbouring segment and yank
// a card out of it.
function segmentIdOf(model: ValueChainModel, activityId: string): string | undefined {
  return model.activities.find((a) => a.id === activityId)?.segment_id
}

// Whatever already sits in one column of one party's lane, other than the named activity's
// own contribution. The single place the invariant's scope is expressed, so a mutation
// cannot hold a subtly different version of it.
function laneOccupant(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
  column: number,
): ValueChainContribution | undefined {
  const segmentId = segmentIdOf(model, activityId)
  const segmentActivityIds = new Set(
    model.activities.filter((a) => a.segment_id === segmentId).map((a) => a.id),
  )
  return model.contributions.find(
    (c) =>
      c.party_id === partyId &&
      segmentActivityIds.has(c.activity_id) &&
      c.activity_id !== activityId &&
      c.column === column,
  )
}

// Moving a contribution changes only .column fields - never an activity, party,
// description, attribution or anything else. The target is the adjacent step
// (column ± COLUMN_STEP). If another contribution in the same lane and segment already
// sits there, the two exchange columns - each keeps every other field - otherwise the mover
// simply takes the target, which holds the lane-uniqueness invariant above. A move into an
// empty column steps into the gap rather than jumping over it: a gap is a real position, not
// blank space, so leapfrogging past one to the next occupied column would silently discard it.
export function moveContribution(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
  direction: 'left' | 'right',
): ValueChainModel {
  const next = structuredClone(model)
  const contribution = find(next, activityId, partyId)
  if (!contribution) return next

  const target = contribution.column + (direction === 'right' ? COLUMN_STEP : -COLUMN_STEP)
  const occupant = laneOccupant(next, activityId, partyId, target)

  if (occupant) occupant.column = contribution.column
  contribution.column = target

  return next
}

// Dragging lands on an arbitrary column rather than the adjacent step, so this is its own
// operation - but it holds the same lane-uniqueness invariant. If the target is taken, the
// two exchange columns; otherwise the mover simply takes it.
export function moveToColumn(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
  column: number,
): ValueChainModel {
  const next = structuredClone(model)
  const contribution = find(next, activityId, partyId)
  if (!contribution || contribution.column === column) return next

  const occupant = laneOccupant(next, activityId, partyId, column)

  if (occupant) occupant.column = contribution.column
  contribution.column = column
  return next
}

export function updateDescription(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
  description: string,
): ValueChainModel {
  const next = structuredClone(model)
  const contribution = find(next, activityId, partyId)
  if (contribution) contribution.description = description
  return next
}

export interface ValueChainSelection {
  activityId: string
  partyId: string
  // Set when the selection came from clicking one n.n.n activity on a card, so the detail
  // dialog can open on that activity. Absent when the card header opened it, which selects
  // the contribution without singling out any of its activities.
  taskId?: string
}

// A contribution's identity is the composite (activity_id, party_id) - deliberately not a
// new ID space needing its own never-reuse discipline. This is also the React key for a
// card: keying on column instead lets a move change which contribution sits behind a key,
// and React then reuses a dirty input against the wrong one.
export function contributionKey(activityId: string, partyId: string): string {
  return `${activityId}@${partyId}`
}

function find(model: ValueChainModel, activityId: string, partyId: string) {
  return model.contributions.find(
    (c) => c.activity_id === activityId && c.party_id === partyId,
  )
}

// The column a further party's contribution to this activity would take: the lowest column
// any party already contributing to it occupies, or COLUMN_STEP when none does.
//
// Same column as a sibling, because two contributions of one activity in the same column
// mean the parties act concurrently - the reasonable default for "both of these parties do
// this". Dragging it aside afterwards turns it into a handoff.
//
// The lowest, specifically, when the activity already runs across several columns as a
// handoff. Taking whichever sibling came first in the array made the answer depend on
// storage order, which a save and reload can change; and the lowest column is where the
// activity begins, so it is the only choice that does not implicitly claim the joining
// party comes in partway through someone else's handoff.
export function addPartyColumn(model: ValueChainModel, activityId: string): number {
  const columns = model.contributions
    .filter((c) => c.activity_id === activityId)
    .map((c) => c.column)
  return columns.length > 0 ? Math.min(...columns) : COLUMN_STEP
}

// What stops a party being added to an activity, if anything: the party's own existing
// contribution already sitting in the column the new one would take, within that segment.
// Adding anyway would break the lane-uniqueness invariant, and the grid would render only
// one of the two - so the new card would not appear at all, and every save from then on
// would be refused with a 422 naming a column rather than an activity.
//
// Exposed so the UI can refuse before offering the action, the way Remove this party
// already does, rather than letting a person discover it at save time.
export interface AddPartyBlock {
  column: number
  /** The party's other activity already occupying that column of its lane. */
  activityId: string
}

export function addPartyBlock(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
): AddPartyBlock | null {
  if (find(model, activityId, partyId)) return null
  const column = addPartyColumn(model, activityId)
  const occupant = laneOccupant(model, activityId, partyId, column)
  return occupant ? { column, activityId: occupant.activity_id } : null
}

// Attributing a further party to an activity needs no new ID and does not touch the
// activity's own ID or its parentage. It refuses outright when the column is already taken
// in the new party's lane - it does not relocate to the next free column, because offset
// columns mean a handoff and inventing one would fabricate a claim nobody made, which is
// exactly the false claim the column semantics exist to prevent.
export function addParty(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
): ValueChainModel {
  const next = structuredClone(model)
  if (find(next, activityId, partyId)) return next
  if (addPartyBlock(next, activityId, partyId)) return next

  next.contributions.push({
    activity_id: activityId,
    party_id: partyId,
    column: addPartyColumn(next, activityId),
    description: '',
    // A person attributing an activity is stating it. Only migration produces 'derived'.
    attribution: 'stated',
  })
  return next
}

// Tasks are keyed (activity_id, party_id), so they belong to the contribution rather than
// to the activity. Removing the contribution without them leaves tasks that validate_model
// rejects - "task X belongs to contribution Y, which does not exist" - so they go together.
// Propositions attach to the activity and are left alone.
export function removeParty(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
): ValueChainModel {
  const next = structuredClone(model)
  next.contributions = next.contributions.filter(
    (c) => !(c.activity_id === activityId && c.party_id === partyId),
  )
  next.tasks = next.tasks.filter(
    (t) => !(t.activity_id === activityId && t.party_id === partyId),
  )
  return next
}

// An activity with no contribution appears in no lane, so it vanishes from the grid while
// remaining in model.activities, with no way to recover it. validate_model rejects that
// state; this is what lets the UI refuse before offering the action.
export function isLastContribution(model: ValueChainModel, activityId: string): boolean {
  return model.contributions.filter((c) => c.activity_id === activityId).length <= 1
}

// A derived attribution is the migration's guess. Someone checking the guess and saying so
// is the act that resolves it - without this the marker stays on forever and stops meaning
// anything. There is no reverse operation: nothing turns a stated attribution into a guess.
export function confirmAttribution(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
): ValueChainModel {
  const next = structuredClone(model)
  const contribution = find(next, activityId, partyId)
  if (contribution) contribution.attribution = 'stated'
  return next
}

// The tasks belonging to one contribution. A task's owner is the composite
// (activity_id, party_id) - the same identity the contribution itself carries, so a task
// filtered on activity alone would pick up every party's work on that activity.
export function contributionTasks(
  model: ValueChainModel,
  activityId: string,
  partyId: string,
): ValueChainTask[] {
  return model.tasks.filter((t) => t.activity_id === activityId && t.party_id === partyId)
}

export function propositionCount(model: ValueChainModel, activityId: string): number {
  return model.propositions.filter((p) => p.activity_id === activityId).length
}

export function partiesNotContributing(
  model: ValueChainModel,
  activityId: string,
): ValueChainParty[] {
  const contributing = new Set(
    model.contributions.filter((c) => c.activity_id === activityId).map((c) => c.party_id),
  )
  return model.parties.filter((p) => !contributing.has(p.id))
}
