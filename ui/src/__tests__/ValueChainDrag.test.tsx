// ui/src/__tests__/ValueChainDrag.test.tsx
import { useState } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import { ValueChainGrid } from '../components/ValueChainGrid'
import type { ValueChainModel } from '../utils/valueChainModel'

const MODEL: ValueChainModel = {
  model_version: 1,
  parties: [
    { id: 'sp', label: 'SP-GS' },
    { id: 'iss', label: 'ISS' },
  ],
  segments: [{ id: '1', label: 'Property Value Chain' }],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Strategy' },
    { id: '1.2', segment_id: '1', label: 'Acquisition' },
    { id: '1.5', segment_id: '1', label: 'Reactive Repair' },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: 'first', attribution: 'stated' },
    { activity_id: '1.2', party_id: 'sp', column: 20, description: 'second', attribution: 'stated' },
    { activity_id: '1.5', party_id: 'iss', column: 40, description: 'partner', attribution: 'derived' },
  ],
  tasks: [],
  propositions: [],
  links: [],
}

// jsdom implements no DataTransfer, so tests supply a stub. It has to behave like the real
// thing for the payload the component actually writes and reads, or the test proves nothing
// about the component's own use of it.
function dataTransfer() {
  const store = new Map<string, string>()
  return {
    setData: (key: string, value: string) => store.set(key, value),
    getData: (key: string) => store.get(key) ?? '',
    dropEffect: '',
    effectAllowed: '',
  }
}

function Stateful() {
  const [model, setModel] = useState(MODEL)
  return <ValueChainGrid model={model} onChange={setModel} />
}

function columnOf(testId: string): number | null {
  // Reads which cell currently contains the card, so assertions are on the rendered
  // position rather than on internal state.
  for (const cell of Array.from(document.querySelectorAll('[data-testid^="cell-"]'))) {
    if (cell.querySelector(`[data-testid="${testId}"]`)) {
      return Number(cell.getAttribute('data-testid')!.split('-').pop())
    }
  }
  return null
}

describe('dragging a card', () => {
  it('moves the card to an empty column in the same lane', () => {
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-sp-30'), { dataTransfer: dt })

    expect(columnOf('card-1.1-sp')).toBe(30)
  })

  it('exchanges columns when dropped on an occupied cell', () => {
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-sp-20'), { dataTransfer: dt })

    expect(columnOf('card-1.1-sp')).toBe(20)
    expect(columnOf('card-1.2-sp')).toBe(10)
  })

  it("refuses a drop into another party's lane", () => {
    // A contribution's identity is (activity, party). Dropping across lanes would not
    // reposition it - it would replace it with a different contribution and orphan its
    // tasks. Re-attribution is the party menu's job, explicitly.
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-iss-30'), { dataTransfer: dt })

    expect(columnOf('card-1.1-sp')).toBe(10)
    expect(screen.queryByTestId('card-1.1-iss')).not.toBeInTheDocument()
  })

  it('carries the description with the card rather than leaving it behind', () => {
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-sp-20'), { dataTransfer: dt })

    expect(
      (screen.getByTestId('description-1.1-sp') as HTMLInputElement).value,
    ).toBe('first')
    expect(
      (screen.getByTestId('description-1.2-sp') as HTMLInputElement).value,
    ).toBe('second')
  })

  it('does not make cards draggable when read-only', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('card-header-1.1-sp')).not.toHaveAttribute('draggable', 'true')
  })
})
