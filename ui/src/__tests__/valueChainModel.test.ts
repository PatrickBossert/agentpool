// ui/src/__tests__/valueChainModel.test.ts
import { describe, it, expect } from 'vitest'

import {
  COLUMN_STEP,
  columnRange,
  moveContribution,
  updateDescription,
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
