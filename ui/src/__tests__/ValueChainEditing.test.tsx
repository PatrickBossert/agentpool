import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { ValueChainTable, type ValueChainModel } from '../components/ValueChainTable'

const MODEL: ValueChainModel = {
  model_version: 1,
  parties: [{ id: 'sp', label: 'SP-GS', colour: '#1a5276' }],
  segments: [{ id: '1', label: 'PROPERTY', description: '' }],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Reactive', description: '', active: true },
    { id: '1.2', segment_id: '1', label: 'Planned', description: '', active: true },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: 'first', attribution: 'stated' },
    { activity_id: '1.2', party_id: 'sp', column: 20, description: 'second', attribution: 'stated' },
  ],
  tasks: [], propositions: [], links: [],
}

// A three-occupied-column lane - the minimal fixture that can catch a move that leapfrogs
// past a neighbour instead of exchanging with it. A two-column fixture cannot distinguish
// the two: moving into an occupied adjacent column looks the same either way until a third
// column is there to land on by mistake.
const THREE_COLUMN_MODEL: ValueChainModel = {
  model_version: 1,
  parties: [{ id: 'sp', label: 'SP-GS', colour: '#1a5276' }],
  segments: [{ id: '1', label: 'PROPERTY', description: '' }],
  activities: [
    { id: '1.1', segment_id: '1', label: 'First', description: '', active: true },
    { id: '1.2', segment_id: '1', label: 'Second', description: '', active: true },
    { id: '1.3', segment_id: '1', label: 'Third', description: '', active: true },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: 'a', attribution: 'stated' },
    { activity_id: '1.2', party_id: 'sp', column: 20, description: 'b', attribution: 'stated' },
    { activity_id: '1.3', party_id: 'sp', column: 30, description: 'c', attribution: 'stated' },
  ],
  tasks: [], propositions: [], links: [],
}

const DERIVED_MODEL: ValueChainModel = {
  model_version: 1,
  parties: [{ id: 'sp', label: 'SP-GS', colour: '#1a5276' }],
  segments: [{ id: '1', label: 'PROPERTY', description: '' }],
  activities: [{ id: '1.1', segment_id: '1', label: 'Reactive', description: '', active: true }],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: 'a guess', attribution: 'derived' },
  ],
  tasks: [], propositions: [], links: [],
}

const onChange = vi.fn()
beforeEach(() => onChange.mockReset())

describe('ValueChainTable editing', () => {
  it('reports an edited description without mutating the model it was given', async () => {
    const original = structuredClone(MODEL)
    render(<ValueChainTable model={MODEL} onChange={onChange} />)

    const field = screen.getByTestId('description-1.1-sp')
    await userEvent.clear(field)
    await userEvent.type(field, 'revised')

    expect(onChange).toHaveBeenCalled()
    const latest = onChange.mock.calls.at(-1)![0] as ValueChainModel
    const edited = latest.contributions.find((c) => c.activity_id === '1.1')!
    expect(edited.description).toBe('revised')
    expect(MODEL).toEqual(original)
  })

  it('editing a derived contribution never promotes its attribution to stated', async () => {
    render(<ValueChainTable model={DERIVED_MODEL} onChange={onChange} />)

    const field = screen.getByTestId('description-1.1-sp')
    await userEvent.clear(field)
    await userEvent.type(field, 'confirmed by interview')

    const latest = onChange.mock.calls.at(-1)![0] as ValueChainModel
    const edited = latest.contributions.find((c) => c.activity_id === '1.1')!
    expect(edited.description).toBe('confirmed by interview')
    expect(edited.attribution).toBe('derived')
  })

  it('moving a contribution onto an occupied column exchanges columns, changing nothing else on either side', async () => {
    const originalMoved = structuredClone(
      MODEL.contributions.find((c) => c.activity_id === '1.1')!,
    )
    const originalOther = structuredClone(
      MODEL.contributions.find((c) => c.activity_id === '1.2')!,
    )
    render(<ValueChainTable model={MODEL} onChange={onChange} />)
    await userEvent.click(screen.getByTestId('move-right-1.1-sp'))

    const latest = onChange.mock.calls.at(-1)![0] as ValueChainModel
    const moved = latest.contributions.find((c) => c.activity_id === '1.1')!
    const other = latest.contributions.find((c) => c.activity_id === '1.2')!

    // 1.1 was at 10, 1.2 at 20: moving 1.1 right lands it exactly on 1.2's column, so
    // they exchange. Each contribution's own record changes only its column.
    expect(moved).toEqual({ ...originalMoved, column: 20 })
    expect(other).toEqual({ ...originalOther, column: 10 })
  })

  it('moving right in a three-column lane never collides two contributions onto one column', async () => {
    render(<ValueChainTable model={THREE_COLUMN_MODEL} onChange={onChange} />)
    await userEvent.click(screen.getByTestId('move-right-1.1-sp'))

    const latest = onChange.mock.calls.at(-1)![0] as ValueChainModel
    const spColumns = latest.contributions
      .filter((c) => c.party_id === 'sp')
      .map((c) => c.column)
    expect(new Set(spColumns).size).toBe(spColumns.length)
  })

  it('moving left in a three-column lane never collides two contributions onto one column', async () => {
    render(<ValueChainTable model={THREE_COLUMN_MODEL} onChange={onChange} />)
    await userEvent.click(screen.getByTestId('move-left-1.3-sp'))

    const latest = onChange.mock.calls.at(-1)![0] as ValueChainModel
    const spColumns = latest.contributions
      .filter((c) => c.party_id === 'sp')
      .map((c) => c.column)
    expect(new Set(spColumns).size).toBe(spColumns.length)
  })

  it('is read-only when no onChange is given', () => {
    render(<ValueChainTable model={MODEL} />)
    expect(screen.queryByTestId('description-1.1-sp')).not.toBeInTheDocument()
  })
})
