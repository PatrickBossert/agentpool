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
export function moveContribution(
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

export function updateDescription(
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
