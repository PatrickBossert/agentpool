import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect } from 'vitest'

import { ValueChainGrid } from '../components/ValueChainGrid'
import type { ValueChainModel } from '../utils/valueChainModel'

const MODEL: ValueChainModel = {
  model_version: 1,
  parties: [
    { id: 'sp', label: 'SP-GS', colour: '#1a5276' },
    { id: 'iss', label: 'ISS', colour: '#c0392b' },
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
  tasks: [
    { activity_id: '1.1', party_id: 'sp', id: '1.1.1', label: 'Set strategy' },
    { activity_id: '1.1', party_id: 'sp', id: '1.1.2', label: 'Agree budget' },
  ],
  propositions: [{ id: 'p1', activity_id: '1.1', description: 'Paperless' }],
  links: [],
}

// The page owns the model; the grid reports changes upwards. Tests that edit must mirror
// that, or they assert against a prop that never updates.
function Stateful({ initial = MODEL }: { initial?: ValueChainModel }) {
  const [model, setModel] = useState(initial)
  return <ValueChainGrid model={model} onChange={setModel} onSelect={() => {}} />
}

function fieldValue(activityId: string, partyId: string): string {
  return (screen.getByTestId(`description-${activityId}-${partyId}`) as HTMLInputElement).value
}

describe('ValueChainGrid layout', () => {
  it('names the segment in a band above its columns, not as a heading', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('segment-band-1')).toHaveTextContent('Property Value Chain')
  })

  it("shows each lane's party and its contribution count for the segment", () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('lane-sp')).toHaveTextContent('SP-GS')
    expect(screen.getByTestId('lane-iss')).toHaveTextContent('ISS')
    expect(screen.getByTestId('lane-count-sp')).toHaveTextContent('2')
    expect(screen.getByTestId('lane-count-iss')).toHaveTextContent('1')
  })

  it('labels every column with its position number, so a gap is legible as a position', () => {
    render(<ValueChainGrid model={MODEL} />)
    for (const column of [10, 20, 30, 40]) {
      expect(screen.getByTestId(`column-header-1-${column}`)).toHaveTextContent(String(column))
    }
  })

  it('renders an unoccupied column as an empty cell rather than collapsing it', () => {
    render(<ValueChainGrid model={MODEL} />)
    // Column 30 is occupied by nobody: SP-GS stops at 20 and ISS starts at 40. It must
    // still exist in both lanes, because the gap is what shows the handoff.
    expect(screen.getByTestId('cell-1-sp-30')).toBeInTheDocument()
    expect(screen.getByTestId('cell-1-sp-30')).toHaveTextContent('')
    expect(screen.getByTestId('cell-1-iss-30')).toBeInTheDocument()
  })

  it('renders a column that is not a multiple of ten', () => {
    // Sparse columns exist so an insert picks an intermediate value. An implementation
    // generating min, min+10, min+20... hides 15 entirely - it happened on this branch.
    const model = structuredClone(MODEL)
    model.contributions.push({
      activity_id: '1.2', party_id: 'iss', column: 15, attribution: 'stated',
    })
    render(<ValueChainGrid model={model} />)
    expect(screen.getByTestId('cell-1-iss-15')).toBeInTheDocument()
    expect(screen.getByTestId('card-1.2-iss')).toBeInTheDocument()
  })

  it('places both parties of one activity in the same column', () => {
    // Transferred from ValueChainTable.test.tsx: two contributions with different parties
    // but the same column are how a joint hand-off is represented, and each lane must show
    // its own card there without either party's cell going empty or borrowing the other's.
    const shared: ValueChainModel = structuredClone(MODEL)
    shared.contributions.push({
      activity_id: '1.1', party_id: 'iss', column: 10, description: 'joint', attribution: 'stated',
    })
    render(<ValueChainGrid model={shared} />)
    expect(screen.getByTestId('cell-1-sp-10')).toHaveTextContent('Strategy')
    expect(screen.getByTestId('cell-1-iss-10')).toHaveTextContent('Strategy')
    expect(screen.getByTestId('card-1.1-sp')).toBeInTheDocument()
    expect(screen.getByTestId('card-1.1-iss')).toBeInTheDocument()
  })

  it('shows an empty state when nothing has been mapped', () => {
    const empty: ValueChainModel = { ...MODEL, segments: [], activities: [], contributions: [] }
    render(<ValueChainGrid model={empty} />)
    expect(screen.getByTestId('value-chain-empty')).toBeInTheDocument()
  })
})

describe('ContributionCard content', () => {
  it('shows the activity ID and label', () => {
    render(<ValueChainGrid model={MODEL} />)
    const card = screen.getByTestId('card-1.1-sp')
    expect(card).toHaveTextContent('1.1')
    expect(card).toHaveTextContent('Strategy')
  })

  it('shows the task and proposition counts, including a zero', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('task-count-1.1-sp')).toHaveTextContent('2')
    expect(screen.getByTestId('proposition-count-1.1')).toHaveTextContent('1')
    // A zero is information: it says this activity has no propositions recorded.
    expect(screen.getByTestId('task-count-1.2-sp')).toHaveTextContent('0')
  })

  it('marks a derived attribution and leaves a stated one unmarked', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('derived-1.5-iss')).toBeInTheDocument()
    expect(screen.queryByTestId('derived-1.1-sp')).not.toBeInTheDocument()
  })
})

describe('ValueChainGrid editing', () => {
  it('reports an edited description without mutating the model it was given', async () => {
    const original = structuredClone(MODEL)
    render(<Stateful />)
    await userEvent.type(screen.getByTestId('description-1.1-sp'), '!')
    expect(MODEL).toEqual(original)
    expect(fieldValue('1.1', 'sp')).toBe('first!')
  })

  it('keeps descriptions with the right activities after a move', async () => {
    // The defect this guards: cards keyed by column meant a move changed which
    // contribution sat behind a key, React reused the input node, and the field showed the
    // wrong activity's text while the next keystroke overwrote another's description.
    render(<Stateful />)
    await userEvent.clear(screen.getByTestId('description-1.1-sp'))
    await userEvent.type(screen.getByTestId('description-1.1-sp'), 'revised')
    await userEvent.click(screen.getByTestId('move-right-1.1-sp'))

    expect(fieldValue('1.1', 'sp')).toBe('revised')
    expect(fieldValue('1.2', 'sp')).toBe('second')
  })

  it("does not overwrite a neighbour's description with the next keystroke after a move", async () => {
    render(<Stateful />)
    await userEvent.clear(screen.getByTestId('description-1.1-sp'))
    await userEvent.type(screen.getByTestId('description-1.1-sp'), 'revised')
    await userEvent.click(screen.getByTestId('move-right-1.1-sp'))
    await userEvent.type(screen.getByTestId('description-1.2-sp'), 'X')

    expect(fieldValue('1.2', 'sp')).toBe('secondX')
    expect(fieldValue('1.1', 'sp')).toBe('revised')
  })

  it('moving a contribution changes only its column', async () => {
    let latest: ValueChainModel = MODEL
    function Capture() {
      const [model, setModel] = useState(MODEL)
      latest = model
      return <ValueChainGrid model={model} onChange={setModel} />
    }
    render(<Capture />)
    await userEvent.click(screen.getByTestId('move-right-1.1-sp'))

    const moved = latest.contributions.find((c) => c.activity_id === '1.1')!
    expect(moved).toEqual({ ...MODEL.contributions[0], column: 20 })
  })

  it('typing in a description does not move the card', async () => {
    // The move handler is on the card header, never on the card container - a handler above
    // a text input swallows keystrokes typed into it.
    render(<Stateful />)
    const field = screen.getByTestId('description-1.1-sp')
    await userEvent.click(field)
    await userEvent.keyboard('{ArrowRight}{ArrowRight}')
    expect(screen.getByTestId('cell-1-sp-10')).toContainElement(screen.getByTestId('card-1.1-sp'))
  })

  it('is read-only when no onChange is given', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.queryByTestId('move-right-1.1-sp')).not.toBeInTheDocument()
    expect(screen.getByTestId('description-1.1-sp')).toHaveAttribute('readonly')
  })
})

const TWO_SEGMENTS: ValueChainModel = {
  model_version: 1,
  parties: [
    { id: 'sp', label: 'SP-GS', colour: '#1a5276' },
    { id: 'iss', label: 'ISS', colour: '#c0392b' },
  ],
  segments: [
    { id: '1', label: 'Property' },
    { id: '2', label: 'Fleet' },
  ],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Strategy' },
    { id: '1.2', segment_id: '1', label: 'Acquisition' },
    { id: '2.1', segment_id: '2', label: 'Maintenance' },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, attribution: 'stated' },
    { activity_id: '1.2', party_id: 'iss', column: 20, attribution: 'stated' },
    // Segment 2's column 10 is a DIFFERENT physical column from segment 1's.
    { activity_id: '2.1', party_id: 'sp', column: 10, attribution: 'stated' },
  ],
  tasks: [], propositions: [], links: [],
}

describe('the continuous chain', () => {
  it('renders one grid for the whole chain, not one per segment', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    expect(screen.getAllByTestId(/^chain-grid$/)).toHaveLength(1)
  })

  it('names each segment in a band above its own columns', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    expect(screen.getByTestId('segment-band-1')).toHaveTextContent('Property')
    expect(screen.getByTestId('segment-band-2')).toHaveTextContent('Fleet')
  })

  it('keeps two segments’ column 10 as two distinct cells', () => {
    // A single-segment fixture cannot tell a correct implementation from one that keys
    // cells on column alone - both put one card in one place.
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    expect(screen.getByTestId('cell-1-sp-10')).toContainElement(screen.getByTestId('card-1.1-sp'))
    expect(screen.getByTestId('cell-2-sp-10')).toContainElement(screen.getByTestId('card-2.1-sp'))
  })

  it('gives every party a row across the whole chain, even where it does nothing', () => {
    // ISS contributes only in segment 1. The per-segment grids gave it no row in segment 2
    // at all; here its absence is visible as empty cells.
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    expect(screen.getByTestId('lane-iss')).toBeInTheDocument()
    expect(screen.getByTestId('cell-2-iss-10')).toBeInTheDocument()
    expect(screen.getByTestId('cell-2-iss-10')).toHaveTextContent('')
  })
})

describe('a cell holding more than one contribution', () => {
  const COLLIDED: ValueChainModel = {
    ...TWO_SEGMENTS,
    activities: [
      { id: '1.1', segment_id: '1', label: 'A' },
      { id: '1.2', segment_id: '1', label: 'B' },
      { id: '1.3', segment_id: '1', label: 'C' },
    ],
    contributions: [
      { activity_id: '1.1', party_id: 'sp', column: 10, attribution: 'stated' },
      { activity_id: '1.2', party_id: 'sp', column: 10, attribution: 'stated' },
      { activity_id: '1.3', party_id: 'sp', column: 10, attribution: 'stated' },
    ],
  }

  it('renders every card in the cell, not just the first', () => {
    // Assert the count. "a card renders" is true of the broken behaviour too.
    //
    // Excludes card-header-* deliberately: ContributionCard's own header testid
    // (card-header-ACT-PARTY) also starts with "card-", so the unqualified prefix
    // selector matches both the card and its header and would double-count every
    // occupant regardless of whether this bug is fixed. Confirmed against today's
    // single-card baseline, which already returns 2 matches, not 1.
    render(<ValueChainGrid model={COLLIDED} />)
    const cell = screen.getByTestId('cell-1-sp-10')
    const cards = [...cell.querySelectorAll('[data-testid^="card-"]')].filter(
      (el) => !el.getAttribute('data-testid')?.startsWith('card-header-'),
    )
    expect(cards).toHaveLength(3)
  })

  it('marks how many share the cell', () => {
    render(<ValueChainGrid model={COLLIDED} />)
    expect(screen.getByTestId('cell-overlap-1-sp-10')).toHaveTextContent('3')
  })

  it('leaves each card individually draggable so the stack can be pulled apart', () => {
    render(<ValueChainGrid model={COLLIDED} onChange={() => {}} />)
    for (const id of ['1.1', '1.2', '1.3']) {
      expect(screen.getByTestId(`card-header-${id}-sp`)).toHaveAttribute('draggable', 'true')
    }
  })

  it('shows no overlap marker when a cell holds one contribution', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    expect(screen.queryByTestId('cell-overlap-1-sp-10')).not.toBeInTheDocument()
  })
})

describe('the live sp-gs-am fixture', () => {
  // This is the actual collision that made the model unsaveable: five real activities from
  // value_chain_mapper's output landed on segment 5, party GSUK, column 10. Exercising the
  // real file, not a contrived stand-in, is what proves this fixes the reported case rather
  // than just the synthetic one above.
  const FIXTURE_PATH = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    '../../../projects/sp-gs-am/outputs/value_chain_model_v2.json',
  )

  it('renders every card of the real five-way collision in segment 5, column 10', () => {
    const raw = JSON.parse(readFileSync(FIXTURE_PATH, 'utf-8'))
    const model: ValueChainModel = { model_version: 1, ...raw }
    render(<ValueChainGrid model={model} />)

    const cell = screen.getByTestId('cell-5-GSUK-10')
    const cards = [...cell.querySelectorAll('[data-testid^="card-"]')].filter(
      (el) => !el.getAttribute('data-testid')?.startsWith('card-header-'),
    )
    expect(cards).toHaveLength(5)
    expect(screen.getByTestId('cell-overlap-5-GSUK-10')).toHaveTextContent('5')
  })
})
