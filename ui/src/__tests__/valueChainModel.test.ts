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
