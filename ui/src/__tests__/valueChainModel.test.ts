// ui/src/__tests__/valueChainModel.test.ts
import { describe, it, expect } from 'vitest'

import {
  COLUMN_STEP,
  columnRange,
  moveContribution,
  moveToColumn,
  updateDescription,
  addParty,
  removeParty,
  confirmAttribution,
  contributionKey,
  taskCount,
  propositionCount,
  partiesNotContributing,
  isLastContribution,
  type ValueChainModel,
} from '../utils/valueChainModel'

function model(): ValueChainModel {
  return {
    model_version: 1,
    parties: [
      { id: 'sp', label: 'SP-GS', colour: '#1a5276' },
      { id: 'iss', label: 'ISS', colour: '#c0392b' },
    ],
    segments: [{ id: '1', label: 'Property Value Chain' }],
    activities: [
      { id: '1.1', segment_id: '1', label: 'Strategy' },
      { id: '1.2', segment_id: '1', label: 'Acquisition' },
      { id: '1.3', segment_id: '1', label: 'Delivery' },
    ],
    contributions: [
      { activity_id: '1.1', party_id: 'sp', column: 10, description: 'first', attribution: 'stated' },
      { activity_id: '1.2', party_id: 'sp', column: 20, description: 'second', attribution: 'stated' },
      { activity_id: '1.3', party_id: 'sp', column: 30, description: 'third', attribution: 'derived' },
    ],
    tasks: [],
    propositions: [],
    links: [],
  }
}

describe('columnRange', () => {
  it('is empty for no columns', () => {
    expect(columnRange([])).toEqual([])
  })

  it('fills whole steps between occupied columns so a gap stays visible', () => {
    expect(columnRange([10, 30])).toEqual([10, 20, 30])
  })

  it('includes a column that is not a multiple of the step', () => {
    // Sparse columns exist so an insert between neighbours picks an intermediate value.
    // An implementation generating min, min+10, min+20... drops 15 entirely.
    expect(columnRange([10, 15, 20])).toEqual([10, 15, 20])
  })

  it('deduplicates and sorts, so lane order in the model does not matter', () => {
    expect(columnRange([30, 10, 30])).toEqual([10, 20, 30])
  })
})

describe('moveContribution', () => {
  it('does not mutate the model it was given', () => {
    const before = model()
    const snapshot = structuredClone(before)
    moveContribution(before, '1.1', 'sp', 'right')
    expect(before).toEqual(snapshot)
  })

  it('exchanges columns with an occupant and changes nothing else on either side', () => {
    const next = moveContribution(model(), '1.1', 'sp', 'right')
    const moved = next.contributions.find((c) => c.activity_id === '1.1')!
    const swapped = next.contributions.find((c) => c.activity_id === '1.2')!
    expect(moved).toEqual({ ...model().contributions[0], column: 20 })
    expect(swapped).toEqual({ ...model().contributions[1], column: 10 })
  })

  it('never collides two contributions in a three-column lane moving right', () => {
    // A two-column fixture cannot discriminate the correct behaviour from the leapfrog
    // arithmetic that shipped first on this branch: with columns 10 and 20 both produce 30.
    const next = moveContribution(model(), '1.1', 'sp', 'right')
    const columns = next.contributions.map((c) => c.column)
    expect(new Set(columns).size).toBe(columns.length)
    expect(columns.sort((a, b) => a - b)).toEqual([10, 20, 30])
  })

  it('never collides two contributions in a three-column lane moving left', () => {
    const next = moveContribution(model(), '1.3', 'sp', 'left')
    const columns = next.contributions.map((c) => c.column)
    expect(new Set(columns).size).toBe(columns.length)
    expect(columns.sort((a, b) => a - b)).toEqual([10, 20, 30])
  })

  it('steps into an empty column rather than leapfrogging to the next occupied one', () => {
    const m = model()
    m.contributions = [
      { activity_id: '1.1', party_id: 'sp', column: 10, attribution: 'stated' },
      { activity_id: '1.3', party_id: 'sp', column: 30, attribution: 'stated' },
    ]
    const next = moveContribution(m, '1.1', 'sp', 'right')
    expect(next.contributions.find((c) => c.activity_id === '1.1')!.column).toBe(20)
  })

  it('ignores an occupant in another party lane', () => {
    const m = model()
    m.contributions.push({
      activity_id: '1.2', party_id: 'iss', column: 20, attribution: 'stated',
    })
    const next = moveContribution(m, '1.1', 'sp', 'right')
    expect(next.contributions.find((c) => c.activity_id === '1.2' && c.party_id === 'iss')!.column).toBe(20)
  })
})

describe('updateDescription', () => {
  it('changes only the named contribution and does not mutate the input', () => {
    const before = model()
    const snapshot = structuredClone(before)
    const next = updateDescription(before, '1.2', 'sp', 'revised')
    expect(before).toEqual(snapshot)
    expect(next.contributions.find((c) => c.activity_id === '1.2')!.description).toBe('revised')
    expect(next.contributions.find((c) => c.activity_id === '1.1')!.description).toBe('first')
  })

  it('never promotes a derived attribution to stated', () => {
    // The distinction feeds stakeholder allocation and interview design later, so a
    // migration guess must not silently harden into a fact by being edited.
    const next = updateDescription(model(), '1.3', 'sp', 'revised')
    expect(next.contributions.find((c) => c.activity_id === '1.3')!.attribution).toBe('derived')
  })
})

describe('COLUMN_STEP', () => {
  it('is ten, matching the backend', () => {
    expect(COLUMN_STEP).toBe(10)
  })
})

function jointModel(): ValueChainModel {
  const m = model()
  m.tasks = [
    { activity_id: '1.2', party_id: 'sp', id: '1.2.1', label: 'Raise works order' },
    { activity_id: '1.2', party_id: 'sp', id: '1.2.2', label: 'Approve spend' },
  ]
  m.propositions = [{ id: 'p1', activity_id: '1.2', description: 'Paperless works orders' }]
  return m
}

describe('contributionKey', () => {
  it('is the composite identity, not a new ID space', () => {
    expect(contributionKey('1.1.2', 'sp')).toBe('1.1.2@sp')
  })
})

describe('addParty', () => {
  it('adds a contribution at the same column, because same column means concurrent', () => {
    const next = addParty(model(), '1.2', 'iss')
    const added = next.contributions.find((c) => c.activity_id === '1.2' && c.party_id === 'iss')!
    expect(added.column).toBe(20)
  })

  it('marks a human-created contribution stated, never derived', () => {
    // Only migration produces derived. A person attributing an activity is stating it.
    const next = addParty(model(), '1.2', 'iss')
    expect(next.contributions.find((c) => c.party_id === 'iss')!.attribution).toBe('stated')
  })

  it('leaves the existing contribution untouched', () => {
    const next = addParty(model(), '1.2', 'iss')
    expect(next.contributions.find((c) => c.activity_id === '1.2' && c.party_id === 'sp')).toEqual(
      model().contributions[1],
    )
  })

  it('does nothing when that party already contributes', () => {
    const next = addParty(model(), '1.2', 'sp')
    expect(next.contributions.filter((c) => c.activity_id === '1.2')).toHaveLength(1)
  })

  it('does not mutate the model it was given', () => {
    const before = model()
    const snapshot = structuredClone(before)
    addParty(before, '1.2', 'iss')
    expect(before).toEqual(snapshot)
  })
})

// Every test above adds iss to an activity in a fixture where iss has no other contribution
// at all, so "takes the sibling's column blindly" and "takes it only when it is free" give
// the same answer. This fixture is the one that can tell them apart: the party being added
// already contributes to a *different* activity in the same segment, at exactly the column
// its new contribution would take.
function collidingModel(): ValueChainModel {
  const m = model()
  m.contributions.push({
    activity_id: '1.3', party_id: 'iss', column: 20, description: 'partner', attribution: 'stated',
  })
  return m
}

describe('addParty when the column is already taken in that party lane', () => {
  it('refuses rather than hiding a card behind another', () => {
    // The grid renders one card per (lane, column), so a second contribution in an occupied
    // cell never appears - the only trace is the lane count going up - and every save is
    // then refused with a 422 naming a column, not an activity, with the offending card
    // nowhere on screen to correct.
    const next = addParty(collidingModel(), '1.2', 'iss')
    expect(next.contributions.filter((c) => c.activity_id === '1.2' && c.party_id === 'iss'))
      .toHaveLength(0)
  })

  it("never puts two of one party's contributions in one column of a segment", () => {
    const next = addParty(collidingModel(), '1.2', 'iss')
    const cells = next.contributions.map((c) => `${c.party_id}@${c.column}`)
    expect(new Set(cells).size).toBe(cells.length)
  })

  it('does not silently relocate to the next free column', () => {
    // Relocating would fabricate a handoff claim nobody made - offset columns mean a
    // handoff, which is exactly the false claim the column semantics exist to prevent.
    const next = addParty(collidingModel(), '1.2', 'iss')
    expect(next.contributions).toHaveLength(collidingModel().contributions.length)
  })

  it('still adds the party when that column is free in its lane', () => {
    // Guards the refusal against overreach: iss sits at 20, so joining 1.1 at 10 is fine.
    const next = addParty(collidingModel(), '1.1', 'iss')
    expect(next.contributions.find((c) => c.activity_id === '1.1' && c.party_id === 'iss')!.column)
      .toBe(10)
  })

  it('refuses when the no-sibling fallback column is taken in that lane', () => {
    // An activity carrying no contribution at all falls back to COLUMN_STEP, which can
    // collide the same way. validate_model rejects such an activity, but a crew-written
    // model reaches the grid without passing validate_model at all.
    const m = model()
    m.activities.push({ id: '1.4', segment_id: '1', label: 'Handover' })
    m.contributions.push({ activity_id: '1.1', party_id: 'iss', column: 10, attribution: 'stated' })
    const next = addParty(m, '1.4', 'iss')
    expect(next.contributions.filter((c) => c.activity_id === '1.4')).toHaveLength(0)
  })
})

describe('addParty when the activity already has contributions at several columns', () => {
  // .find() picked whichever sibling came first in the array, so the answer depended on
  // array order - which a save and reload can change. The rule is the lowest column: the
  // point at which the activity begins.
  function handoffModel(): ValueChainModel {
    const m = model()
    m.parties.push({ id: 'dxi', label: 'DXI' })
    m.contributions.push({ activity_id: '1.2', party_id: 'iss', column: 40, attribution: 'stated' })
    return m
  }

  it('joins at the lowest of the sibling columns, not partway through the handoff', () => {
    const next = addParty(handoffModel(), '1.2', 'dxi')
    expect(next.contributions.find((c) => c.party_id === 'dxi')!.column).toBe(20)
  })

  it('gives the same column whatever order the contributions are stored in', () => {
    const reversed = handoffModel()
    reversed.contributions.reverse()
    expect(addParty(reversed, '1.2', 'dxi').contributions.find((c) => c.party_id === 'dxi')!.column)
      .toBe(20)
  })
})

describe('removeParty', () => {
  it('removes the contribution and its tasks together', () => {
    // validate_model rejects a task whose contribution does not exist, so leaving the tasks
    // behind would turn into a 422 discovered long after the decision was made.
    const next = removeParty(jointModel(), '1.2', 'sp')
    expect(next.contributions.filter((c) => c.activity_id === '1.2')).toHaveLength(0)
    expect(next.tasks.filter((t) => t.activity_id === '1.2' && t.party_id === 'sp')).toHaveLength(0)
  })

  it("leaves another party's tasks on the same activity alone", () => {
    const m = jointModel()
    m.contributions.push({ activity_id: '1.2', party_id: 'iss', column: 20, attribution: 'stated' })
    m.tasks.push({ activity_id: '1.2', party_id: 'iss', id: '1.2.7', label: 'Execute repair' })
    const next = removeParty(m, '1.2', 'sp')
    expect(next.tasks.map((t) => t.id)).toEqual(['1.2.7'])
  })

  it("leaves the activity's propositions alone, because they attach to the activity", () => {
    const m = jointModel()
    m.contributions.push({ activity_id: '1.2', party_id: 'iss', column: 20, attribution: 'stated' })
    const next = removeParty(m, '1.2', 'sp')
    expect(next.propositions).toHaveLength(1)
  })

  it('does not mutate the model it was given', () => {
    const before = jointModel()
    const snapshot = structuredClone(before)
    removeParty(before, '1.2', 'sp')
    expect(before).toEqual(snapshot)
  })
})

describe('isLastContribution', () => {
  it('is true when the activity has exactly one contribution', () => {
    expect(isLastContribution(model(), '1.2')).toBe(true)
  })

  it('is false when two parties contribute', () => {
    expect(isLastContribution(addParty(model(), '1.2', 'iss'), '1.2')).toBe(false)
  })
})

describe('confirmAttribution', () => {
  it('promotes derived to stated', () => {
    const next = confirmAttribution(model(), '1.3', 'sp')
    expect(next.contributions.find((c) => c.activity_id === '1.3')!.attribution).toBe('stated')
  })

  it('changes nothing else on the contribution', () => {
    const next = confirmAttribution(model(), '1.3', 'sp')
    expect(next.contributions.find((c) => c.activity_id === '1.3')).toEqual({
      ...model().contributions[2],
      attribution: 'stated',
    })
  })

  it('does not mutate the model it was given', () => {
    const before = model()
    const snapshot = structuredClone(before)
    confirmAttribution(before, '1.3', 'sp')
    expect(before).toEqual(snapshot)
  })
})

describe('counts and available parties', () => {
  it("counts only that contribution's tasks", () => {
    const m = jointModel()
    m.contributions.push({ activity_id: '1.2', party_id: 'iss', column: 20, attribution: 'stated' })
    m.tasks.push({ activity_id: '1.2', party_id: 'iss', id: '1.2.7' })
    expect(taskCount(m, '1.2', 'sp')).toBe(2)
    expect(taskCount(m, '1.2', 'iss')).toBe(1)
  })

  it('counts propositions per activity, shared across its parties', () => {
    expect(propositionCount(jointModel(), '1.2')).toBe(1)
    expect(propositionCount(jointModel(), '1.1')).toBe(0)
  })

  it('lists only parties not already contributing to that activity', () => {
    expect(partiesNotContributing(model(), '1.2').map((p) => p.id)).toEqual(['iss'])
    expect(partiesNotContributing(addParty(model(), '1.2', 'iss'), '1.2')).toEqual([])
  })
})

// Every other fixture in this file and in the component tests has exactly one segment, so
// nothing proved that moveContribution and moveToColumn scope their occupant search to the
// moved card's own segment. Columns restart at 10 in every segment, so deleting that scoping
// would let a move in one segment reach into another and yank a card out of it - and no
// single-segment fixture can tell the two apart.
function twoSegmentModel(): ValueChainModel {
  return {
    model_version: 1,
    parties: [{ id: 'sp', label: 'SP-GS' }],
    segments: [
      { id: '1', label: 'Property Value Chain' },
      { id: '2', label: 'Corporate Services' },
    ],
    activities: [
      { id: '1.1', segment_id: '1', label: 'Strategy' },
      { id: '1.2', segment_id: '1', label: 'Acquisition' },
      { id: '2.1', segment_id: '2', label: 'Finance' },
      { id: '2.2', segment_id: '2', label: 'People' },
    ],
    contributions: [
      { activity_id: '1.1', party_id: 'sp', column: 10, description: 'one at ten', attribution: 'stated' },
      { activity_id: '1.2', party_id: 'sp', column: 20, description: 'one at twenty', attribution: 'stated' },
      { activity_id: '2.1', party_id: 'sp', column: 10, description: 'two at ten', attribution: 'stated' },
      { activity_id: '2.2', party_id: 'sp', column: 30, description: 'two at thirty', attribution: 'stated' },
    ],
    tasks: [],
    propositions: [],
    links: [],
  }
}

describe("a move is scoped to the moved card's own segment", () => {
  it('leaves the first segment untouched when a card in the second moves onto a shared column number', () => {
    // sp holds column 20 in segment 1 and nothing at 20 in segment 2, so moving 2.1 right
    // from 10 to 20 must find no occupant at all - 1.2 is in a different lane row entirely.
    const next = moveContribution(twoSegmentModel(), '2.1', 'sp', 'right')
    expect(next.contributions.find((c) => c.activity_id === '2.1')!.column).toBe(20)
    expect(next.contributions.filter((c) => c.activity_id.startsWith('1.'))).toEqual(
      twoSegmentModel().contributions.filter((c) => c.activity_id.startsWith('1.')),
    )
  })

  it('does not drag a card out of another segment when the target column is free in its own', () => {
    // Column 20 is free in segment 2 and occupied by 1.2 in segment 1. Dragging 2.2 to 20
    // must simply take it - not exchange columns with 1.2, which is not in this lane row and
    // would be pulled from 20 to 30, a change nobody asked for in a segment nobody touched.
    const next = moveToColumn(twoSegmentModel(), '2.2', 'sp', 20)
    expect(next.contributions.find((c) => c.activity_id === '2.2')!.column).toBe(20)
    expect(next.contributions.find((c) => c.activity_id === '1.2')!.column).toBe(20)
    expect(next.contributions.find((c) => c.activity_id === '1.1')!.column).toBe(10)
  })
})

describe('moveToColumn', () => {
  it('takes an empty column', () => {
    const next = moveToColumn(model(), '1.1', 'sp', 40)
    expect(next.contributions.find((c) => c.activity_id === '1.1')!.column).toBe(40)
  })

  it('exchanges columns with an occupant, changing nothing else on either side', () => {
    const next = moveToColumn(model(), '1.1', 'sp', 30)
    expect(next.contributions.find((c) => c.activity_id === '1.1')).toEqual({
      ...model().contributions[0], column: 30,
    })
    expect(next.contributions.find((c) => c.activity_id === '1.3')).toEqual({
      ...model().contributions[2], column: 10,
    })
  })

  it('leaves every column in the lane distinct, wherever the card lands', () => {
    for (const target of [10, 20, 30, 40, 15]) {
      const columns = moveToColumn(model(), '1.1', 'sp', target).contributions.map((c) => c.column)
      expect(new Set(columns).size).toBe(columns.length)
    }
  })

  it('is a no-op when the card is already there', () => {
    expect(moveToColumn(model(), '1.1', 'sp', 10)).toEqual(model())
  })

  it('ignores an occupant in another party lane', () => {
    const m = model()
    m.contributions.push({ activity_id: '1.2', party_id: 'iss', column: 40, attribution: 'stated' })
    const next = moveToColumn(m, '1.1', 'sp', 40)
    expect(next.contributions.find((c) => c.party_id === 'iss')!.column).toBe(40)
  })

  it('does not mutate the model it was given', () => {
    const before = model()
    const snapshot = structuredClone(before)
    moveToColumn(before, '1.1', 'sp', 40)
    expect(before).toEqual(snapshot)
  })
})
