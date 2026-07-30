import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { ValueChainGrid } from '../components/ValueChainGrid'
import type { ValueChainModel } from '../utils/valueChainModel'

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

// The page lifts the working copy into state and feeds it straight back in, so a test that
// only inspects onChange's argument never sees what a person would actually be looking at.
// This harness reproduces that loop, which is the only way to assert on the rendered fields.
function StatefulTable({
  initial,
  onModelChange,
}: {
  initial: ValueChainModel
  onModelChange?: (model: ValueChainModel) => void
}) {
  const [model, setModel] = useState(initial)
  return (
    <ValueChainGrid
      model={model}
      onChange={(updated) => {
        setModel(updated)
        onModelChange?.(updated)
      }}
    />
  )
}

function fieldValue(activityId: string, partyId: string): string {
  return (screen.getByTestId(`description-${activityId}-${partyId}`) as HTMLInputElement).value
}

describe('ValueChainGrid editing', () => {
  it('reports an edited description without mutating the model it was given', async () => {
    const original = structuredClone(MODEL)
    // MODEL itself is handed in, not a clone, so the no-mutation assertion below still has
    // something to catch. The field is controlled, so typing has to be fed back through
    // state or the value it displays never advances past the first keystroke.
    render(<StatefulTable initial={MODEL} onModelChange={onChange} />)

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
    render(<StatefulTable initial={DERIVED_MODEL} onModelChange={onChange} />)

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
    render(<ValueChainGrid model={MODEL} onChange={onChange} />)
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
    render(<ValueChainGrid model={THREE_COLUMN_MODEL} onChange={onChange} />)
    await userEvent.click(screen.getByTestId('move-right-1.1-sp'))

    const latest = onChange.mock.calls.at(-1)![0] as ValueChainModel
    const spColumns = latest.contributions
      .filter((c) => c.party_id === 'sp')
      .map((c) => c.column)
    expect(new Set(spColumns).size).toBe(spColumns.length)
  })

  it('moving left in a three-column lane never collides two contributions onto one column', async () => {
    render(<ValueChainGrid model={THREE_COLUMN_MODEL} onChange={onChange} />)
    await userEvent.click(screen.getByTestId('move-left-1.3-sp'))

    const latest = onChange.mock.calls.at(-1)![0] as ValueChainModel
    const spColumns = latest.contributions
      .filter((c) => c.party_id === 'sp')
      .map((c) => c.column)
    expect(new Set(spColumns).size).toBe(spColumns.length)
  })

  it('shows each description against its own contribution after a move', async () => {
    // Cells are keyed by column, so a move hands the same input DOM node to a different
    // contribution. An uncontrolled field keeps whatever was typed into it and the
    // descriptions swap on screen while the model stays right - and the next keystroke in
    // either field then writes one contribution's text over the other's.
    render(<StatefulTable initial={structuredClone(MODEL)} />)

    const field = screen.getByTestId('description-1.1-sp')
    await userEvent.clear(field)
    await userEvent.type(field, 'revised')
    await userEvent.click(screen.getByTestId('move-right-1.1-sp'))

    expect(fieldValue('1.1', 'sp')).toBe('revised')
    expect(fieldValue('1.2', 'sp')).toBe('second')
  })

  it('writes a further keystroke after a move to the contribution being typed into', async () => {
    render(<StatefulTable initial={structuredClone(MODEL)} />)

    const field = screen.getByTestId('description-1.1-sp')
    await userEvent.clear(field)
    await userEvent.type(field, 'revised')
    await userEvent.click(screen.getByTestId('move-right-1.1-sp'))
    await userEvent.type(screen.getByTestId('description-1.2-sp'), 'X')

    // 1.2's own text gains the keystroke; 1.1's is untouched.
    expect(fieldValue('1.2', 'sp')).toBe('secondX')
    expect(fieldValue('1.1', 'sp')).toBe('revised')
  })

  it('is read-only when no onChange is given', () => {
    // The card keeps the field in the document with a readonly attribute rather than
    // omitting it - the table used to omit it outright, but the grid needs the field
    // present so a reader can still see the description text.
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.queryByTestId('move-right-1.1-sp')).not.toBeInTheDocument()
    expect(screen.getByTestId('description-1.1-sp')).toHaveAttribute('readonly')
  })
})
