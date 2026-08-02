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
    // 1.1 is jointly delivered: iss contributes to it too, at its own column. Without this,
    // no fixture can tell a correct cross-lane refusal apart from a bug that reaches for
    // party.id instead of the dragged party - moveToColumn no-ops either way when there is
    // no contribution to find, so the two behaviours look identical unless a real
    // same-activity contribution exists on the other side to be wrongly moved.
    { activity_id: '1.1', party_id: 'iss', column: 50, description: 'joint', attribution: 'stated' },
  ],
  tasks: [{ activity_id: '1.1', party_id: 'iss', id: 't-iss-1.1', label: 'Coordinate access' }],
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
    fireEvent.drop(screen.getByTestId('cell-1-sp-30'), { dataTransfer: dt })

    expect(columnOf('card-1.1-sp')).toBe(30)
  })

  it('exchanges columns when dropped on an occupied cell', () => {
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-1-sp-20'), { dataTransfer: dt })

    expect(columnOf('card-1.1-sp')).toBe(20)
    expect(columnOf('card-1.2-sp')).toBe(10)
  })

  it("refuses a drop into another party's empty lane cell", () => {
    // A contribution's identity is (activity, party). Dropping across lanes would not
    // reposition it - it would replace it with a different contribution and orphan its
    // tasks. Re-attribution is the party menu's job, explicitly.
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-1-iss-30'), { dataTransfer: dt })

    expect(columnOf('card-1.1-sp')).toBe(10)
    expect(screen.getByTestId('cell-1-iss-30').children.length).toBe(0)
  })

  it("leaves the other party's contribution to the same activity untouched on a cross-lane drop", () => {
    // 1.1 is jointly delivered by sp and iss. This is the fixture that can actually fail:
    // a bug that passes the target cell's party into moveToColumn instead of the dragged
    // party would find iss's real contribution to 1.1 here and move or swap it, rather than
    // silently no-opping the way it would against an activity iss has no stake in.
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-1-iss-50'), { dataTransfer: dt })

    expect(columnOf('card-1.1-sp')).toBe(10)
    expect(columnOf('card-1.1-iss')).toBe(50)
  })

  it('carries the description with the card rather than leaving it behind', () => {
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-1-sp-20'), { dataTransfer: dt })

    expect(
      (screen.getByTestId('description-1.1-sp') as HTMLTextAreaElement).value,
    ).toBe('first')
    expect(
      (screen.getByTestId('description-1.2-sp') as HTMLTextAreaElement).value,
    ).toBe('second')
  })

  it('does not make cards draggable when read-only', () => {
    // draggable="false", not merely "not true": the attribute being absent altogether would
    // satisfy not.toHaveAttribute('draggable', 'true') while telling us nothing. React does
    // render it, so the honest assertion is on its value.
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('card-header-1.1-sp')).toHaveAttribute('draggable', 'false')
  })

  it('ignores a drop with no payload, because nothing was ever dragged from this grid', () => {
    // An unrelated drag (a file, text from elsewhere) ending up over a grid cell is
    // reachable in a real browser - getData then returns '' for a key nobody set.
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.drop(screen.getByTestId('cell-1-sp-30'), { dataTransfer: dt })

    expect(columnOf('card-1.1-sp')).toBe(10)
    expect(screen.getByTestId('cell-1-sp-30').children.length).toBe(0)
  })

  it('ignores a drop naming an activity that does not exist', () => {
    render(<Stateful />)
    const dt = dataTransfer()
    dt.setData('contributionActivityId', 'does-not-exist')
    dt.setData('contributionPartyId', 'sp')
    fireEvent.drop(screen.getByTestId('cell-1-sp-30'), { dataTransfer: dt })

    expect(columnOf('card-1.1-sp')).toBe(10)
    expect(screen.getByTestId('cell-1-sp-30').children.length).toBe(0)
  })
})

describe('drag-over visual cue', () => {
  // Cells are 13rem wide beside a 10rem gutter, and a gap is a meaningful position of its
  // own - so a person dragging has no way to tell which column they are over without a
  // cue. Only a cell that would actually accept the drop should show it: highlighting a
  // cell in another party's lane would promise a drop it is going to refuse.
  it("highlights a cell in the dragged card's own lane", () => {
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.dragOver(screen.getByTestId('cell-1-sp-30'), { dataTransfer: dt })

    expect(screen.getByTestId('cell-1-sp-30')).toHaveClass('border-brand')
  })

  it("does not highlight a cell in another party's lane", () => {
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })

    // Positive anchor first. Without it a cue mechanism broken everywhere would satisfy the
    // assertion below, which is exactly what "absent" proves nothing about on its own.
    fireEvent.dragOver(screen.getByTestId('cell-1-sp-30'), { dataTransfer: dt })
    expect(screen.getByTestId('cell-1-sp-30')).toHaveClass('border-brand')

    fireEvent.dragOver(screen.getByTestId('cell-1-iss-30'), { dataTransfer: dt })
    expect(screen.getByTestId('cell-1-iss-30')).not.toHaveClass('border-brand')
  })

  it('clears the cue once the pointer leaves the cell', () => {
    render(<Stateful />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })

    fireEvent.dragOver(screen.getByTestId('cell-1-sp-30'), { dataTransfer: dt })
    // The cue must exist between the dragOver and the dragLeave, or the assertion after the
    // dragLeave says nothing about clearing - only that the cue was never there.
    expect(screen.getByTestId('cell-1-sp-30')).toHaveClass('border-brand')

    fireEvent.dragLeave(screen.getByTestId('cell-1-sp-30'), { dataTransfer: dt })
    expect(screen.getByTestId('cell-1-sp-30')).not.toHaveClass('border-brand')
  })
})

// One continuous grid makes another segment's cell reachable by drag for the first time -
// before this task each segment was its own grid, so there was nothing to drop onto. A
// contribution's segment comes from its activity, and moveToColumn writes only .column, so
// an unguarded drop across segments would not reposition the card - it would set the column
// field to a number that happens to match, while the contribution stays recorded under its
// original activity's segment. That is a silent, unpredictable result, not a repositioning.
const TWO_SEGMENTS: ValueChainModel = {
  model_version: 1,
  parties: [{ id: 'sp', label: 'SP-GS' }],
  segments: [
    { id: '1', label: 'Property' },
    { id: '2', label: 'Fleet' },
  ],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Strategy' },
    { id: '1.2', segment_id: '1', label: 'Acquisition' },
    { id: '1.3', segment_id: '1', label: 'Disposal' },
    { id: '2.1', segment_id: '2', label: 'Maintenance' },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, attribution: 'stated' },
    { activity_id: '1.2', party_id: 'sp', column: 20, attribution: 'stated' },
    { activity_id: '1.3', party_id: 'sp', column: 30, attribution: 'stated' },
    // Segment 2's column 20 shares its numeric value with segment 1's own column 20 (1.2's).
    // That is the discriminating case: a guard that only compares column numbers would find
    // 1.2 as the "occupant" and swap 1.1 onto it - a visible move, in segment 1, nowhere near
    // where the card was actually dropped. A target column with no counterpart anywhere in
    // segment 1 could not tell that bug apart from a correct refusal.
    { activity_id: '2.1', party_id: 'sp', column: 20, attribution: 'stated' },
  ],
  tasks: [],
  propositions: [],
  links: [],
}

function StatefulTwoSegments() {
  const [model, setModel] = useState(TWO_SEGMENTS)
  return <ValueChainGrid model={model} onChange={setModel} />
}

describe('dragging across segments', () => {
  it("refuses a drop onto another segment's cell, even one sharing its column number", () => {
    render(<StatefulTwoSegments />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-2-sp-20'), { dataTransfer: dt })

    // Nothing moved: not the dragged card, not the card that a column-only check would have
    // mistaken for occupying the target, and not the segment 2 card the drop landed on.
    expect(columnOf('card-1.1-sp')).toBe(10)
    expect(columnOf('card-1.2-sp')).toBe(20)
    expect(screen.getByTestId('cell-2-sp-20')).toContainElement(screen.getByTestId('card-2.1-sp'))
  })

  it("does not highlight a same-party cell in another segment, because the drop would be refused", () => {
    // acceptsDrag checked only the dragged card's party, not its segment, so hovering a
    // same-party cell in a different segment showed the "will accept" cue and then the
    // guard above silently refused the drop anyway - a promise the cue should never make.
    render(<StatefulTwoSegments />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.dragOver(screen.getByTestId('cell-2-sp-20'), { dataTransfer: dt })

    expect(screen.getByTestId('cell-2-sp-20')).not.toHaveClass('border-brand')
  })

  it('still exchanges columns within the dragged card\'s own segment', () => {
    // Guards the refusal against overreach: a drop that stays inside segment 1 must still
    // work, or the first test could be satisfied by refusing every drop.
    render(<StatefulTwoSegments />)
    const dt = dataTransfer()
    fireEvent.dragStart(screen.getByTestId('card-header-1.1-sp'), { dataTransfer: dt })
    fireEvent.drop(screen.getByTestId('cell-1-sp-30'), { dataTransfer: dt })

    expect(columnOf('card-1.1-sp')).toBe(30)
    expect(columnOf('card-1.3-sp')).toBe(10)
  })
})
