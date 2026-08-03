import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
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
  return (screen.getByTestId(`description-${activityId}-${partyId}`) as HTMLTextAreaElement).value
}

describe('ValueChainGrid layout', () => {
  it('names the segment in a band above its columns, not as a heading', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('segment-band-1')).toHaveTextContent('Property Value Chain')
  })

  it('leads the segment band with the segment number', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    // TWO_SEGMENTS' segment labels are 'Property' and 'Fleet'. Neither contains a digit,
    // so a substring match on the number genuinely discriminates here - it cannot pass on
    // the label alone, which is what the existing band tests assert.
    expect(screen.getByTestId('segment-band-1')).toHaveTextContent('1')
    expect(screen.getByTestId('segment-band-2')).toHaveTextContent('2')
  })

  it("shows each lane's party and its contribution count within that chain", () => {
    // Deliberately the opposite of what this asserted before the chains were separated.
    // A lane belongs to one chain now, so its count is that chain's - sp contributes once
    // in chain 1 and once in chain 2, and each lane says 1 rather than both saying 2.
    // A single-chain fixture cannot tell the two readings apart, so this uses TWO_SEGMENTS.
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    expect(screen.getByTestId('lane-1-sp')).toHaveTextContent('SP-GS')
    expect(screen.getByTestId('lane-1-iss')).toHaveTextContent('ISS')
    expect(screen.getByTestId('lane-count-1-sp')).toHaveTextContent('1')
    expect(screen.getByTestId('lane-count-2-sp')).toHaveTextContent('1')
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

  it('gives an unselected card a visible edge, so one card separates from the next', () => {
    render(<ValueChainGrid model={MODEL} onSelect={() => {}} />)
    // The defect was border-transparent: a card had a border box with no visible edge, so
    // it read as a floating patch of surface. Asserting only that a *selected* card is
    // border-brand passes on that broken behaviour, so the unselected case is the one that
    // has to be asserted.
    expect(screen.getByTestId('card-1.1-sp')).toHaveClass('border-surface')
    expect(screen.getByTestId('card-1.1-sp')).not.toHaveClass('border-transparent')
  })

  it('marks selection by the border colour, not by the border appearing', () => {
    render(
      <ValueChainGrid
        model={MODEL}
        onSelect={() => {}}
        selected={{ activityId: '1.1', partyId: 'sp' }}
      />,
    )
    expect(screen.getByTestId('card-1.1-sp')).toHaveClass('border-brand')
    // The neighbour still has an edge - selection changed a colour, it did not add an edge.
    expect(screen.getByTestId('card-1.2-sp')).toHaveClass('border-surface')
  })

  it('shows the description over three lines rather than one', () => {
    render(<ValueChainGrid model={MODEL} onSelect={() => {}} />)
    const field = screen.getByTestId('description-1.1-sp')
    expect(field.tagName).toBe('TEXTAREA')
    expect(field).toHaveAttribute('rows', '3')
  })

  it('keeps the description controlled after becoming a textarea', async () => {
    // The element changed; the SP22a defence must not have. A textarea rendered with
    // defaultValue would pass the tagName test above and silently corrupt saved data.
    render(<Stateful />)
    await userEvent.type(screen.getByTestId('description-1.1-sp'), '!')
    expect(fieldValue('1.1', 'sp')).toBe('first!')
  })
})

describe('ContributionCard content', () => {
  it('shows the activity ID and label', () => {
    render(<ValueChainGrid model={MODEL} />)
    const card = screen.getByTestId('card-1.1-sp')
    expect(card).toHaveTextContent('1.1')
    expect(card).toHaveTextContent('Strategy')
  })

  it('shows the proposition count, including a zero', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('proposition-count-1.1')).toHaveTextContent('1')
    // A zero is information: it says this activity has no propositions recorded.
    // Propositions keep a count rather than a list because one attaches to the activity as
    // a whole, so listing them per card would repeat the same proposition across every
    // party in that column.
    expect(screen.getByTestId('proposition-count-1.2')).toHaveTextContent('0')
  })

  it("lists a contribution's n.n.n activities, rather than counting them", () => {
    render(<ValueChainGrid model={MODEL} />)
    // Assert the count of lines. "a task line renders" is also true of an implementation
    // that renders only the first of the two.
    expect(screen.getAllByTestId(/^task-line-.*-sp$/)).toHaveLength(2)
    expect(screen.getByTestId('task-line-1.1.1-sp')).toHaveTextContent('1.1.1')
    expect(screen.getByTestId('task-line-1.1.1-sp')).toHaveTextContent('Set strategy')
  })

  it('keeps a long activity line inside the card rather than letting it overflow', () => {
    const wordy = structuredClone(MODEL)
    wordy.tasks[0].label = 'A'.repeat(200)
    render(<ValueChainGrid model={wordy} />)
    // jsdom does no layout, so this asserts the mechanism rather than a measured width.
    // Both classes are needed together: truncate alone is inert on a flex item, whose
    // min-width defaults to auto and so refuses to shrink below its nowrap content.
    const line = screen.getByTestId('task-line-1.1.1-sp').querySelector('span:last-child')!
    expect(line.className).toContain('truncate')
    expect(line.className).toContain('min-w-0')
  })

  it('renders no task list for a contribution with no activities mapped', () => {
    render(<ValueChainGrid model={MODEL} />)
    expect(screen.getByTestId('task-list-1.1-sp')).toBeInTheDocument()
    expect(screen.queryByTestId('task-list-1.2-sp')).toBeNull()
  })

  it('reports the clicked activity upwards, not just its contribution', async () => {
    const seen: Array<[string, string, string | undefined]> = []
    render(<ValueChainGrid model={MODEL} onSelect={(a, p, t) => seen.push([a, p, t])} />)
    await userEvent.click(screen.getByTestId('task-line-1.1.2-sp'))
    expect(seen).toEqual([['1.1', 'sp', '1.1.2']])
  })

  it('reports no activity when the card header is clicked', async () => {
    const seen: Array<[string, string, string | undefined]> = []
    render(<ValueChainGrid model={MODEL} onSelect={(a, p, t) => seen.push([a, p, t])} />)
    await userEvent.click(screen.getByTestId('card-header-1.1-sp'))
    expect(seen).toEqual([['1.1', 'sp', undefined]])
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

describe('a chain block', () => {
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

  it('stacks colliding cards without the cell growing with the stack', () => {
    render(<ValueChainGrid model={COLLIDED} />)
    const cell = screen.getByTestId('cell-1-sp-10')
    // The card-header-* exclusion is not optional: ContributionCard's own header testid
    // also starts with "card-", so the unqualified prefix selector matches both the card
    // and its header and would return six elements for three occupants. The sibling test
    // above carries the same filter for the same reason.
    const wrappers = [...cell.querySelectorAll('[data-testid^="card-"]')]
      .filter((el) => !el.getAttribute('data-testid')?.startsWith('card-header-'))
      .map((card) => card.parentElement as HTMLElement)
    expect(wrappers).toHaveLength(3)

    // Only the first occupant sits in flow, so the cell is one card tall whatever the
    // stack depth. jsdom does no layout, so this asserts the mechanism that produces that
    // - the buried cards are taken out of flow - rather than a measured height, which
    // would read 0 here whether the fix is present or not.
    expect(wrappers[0].className).toContain('relative')
    expect(wrappers[0].className).not.toContain('absolute')
    expect(wrappers[1].className).toContain('absolute')
    expect(wrappers[2].className).toContain('absolute')

    // Each buried card is stepped down by a distinct amount, so its header - the drag
    // handle the stacking exists to keep reachable - is not hidden under its neighbour's.
    expect(wrappers[1].style.top).toBeTruthy()
    expect(wrappers[1].style.top).not.toBe(wrappers[2].style.top)
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

// This is the actual collision that made the model unsaveable: five real activities from
// value_chain_mapper's output landed on segment 5, party GSUK, column 10. Exercising the real
// file, not a contrived stand-in, is what proves this fixes the reported case rather than just
// the synthetic one above.
//
// projects/ is gitignored, so this fixture is not guaranteed to exist in every checkout - a
// fresh clone or CI would otherwise hit ENOENT from readFileSync and fail outright. Skipped
// rather than failed when absent, named the same way tests/test_value_chain_migration.py
// names its skip for the same fixture.
const SP_GS_AM_FIXTURE_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../projects/sp-gs-am/outputs/value_chain_model_v2.json',
)
const SP_GS_AM_FIXTURE_PRESENT = existsSync(SP_GS_AM_FIXTURE_PATH)

describe.skipIf(!SP_GS_AM_FIXTURE_PRESENT)(
  SP_GS_AM_FIXTURE_PRESENT
    ? 'the live sp-gs-am fixture'
    : 'the live sp-gs-am fixture (skipped: sp-gs-am fixture not present in this checkout)',
  () => {
    it('renders every card of the real five-way collision in segment 5, column 10', () => {
      const raw = JSON.parse(readFileSync(SP_GS_AM_FIXTURE_PATH, 'utf-8'))
      const model: ValueChainModel = { model_version: 1, ...raw }
      render(<ValueChainGrid model={model} />)

      const cell = screen.getByTestId('cell-5-GSUK-10')
      const cards = [...cell.querySelectorAll('[data-testid^="card-"]')].filter(
        (el) => !el.getAttribute('data-testid')?.startsWith('card-header-'),
      )
      expect(cards).toHaveLength(5)
      expect(screen.getByTestId('cell-overlap-5-GSUK-10')).toHaveTextContent('5')
    })
  },
)

describe('zoom', () => {
  it('starts at 100%', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    expect(screen.getByTestId('zoom-level')).toHaveTextContent('100%')
  })

  it('scales the grid down when zoomed out', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    fireEvent.click(screen.getByTestId('zoom-out'))
    expect(screen.getByTestId('chain-grid-1')).toHaveStyle({ transform: 'scale(0.8)' })
  })

  it('keeps cards interactive after zooming', () => {
    // A test asserting only the style would pass on a grid that scaled itself out of use.
    render(<ValueChainGrid model={TWO_SEGMENTS} onChange={() => {}} />)
    fireEvent.click(screen.getByTestId('zoom-out'))
    expect(screen.getByTestId('card-header-1.1-sp')).toHaveAttribute('draggable', 'true')
    expect(screen.getByTestId('description-1.1-sp')).not.toHaveAttribute('readonly')
  })

  it('does not zoom below the floor', () => {
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    for (let i = 0; i < 10; i++) fireEvent.click(screen.getByTestId('zoom-out'))
    expect(screen.getByTestId('zoom-level')).toHaveTextContent('40%')
  })

  it('does not zoom above the ceiling', () => {
    // Mirrors the floor test above: repeated 0.2 addition drifts in floating point just as
    // repeated subtraction does, so an off-by-a-fraction zoom could equally overshoot or
    // never reach ZOOM_MAX (1.4).
    render(<ValueChainGrid model={TWO_SEGMENTS} />)
    for (let i = 0; i < 10; i++) fireEvent.click(screen.getByTestId('zoom-in'))
    expect(screen.getByTestId('zoom-level')).toHaveTextContent('140%')
  })
})

// Three genuine value chains with different parties in each. A fixture where every party
// contributes everywhere cannot tell "lanes for the parties in this chain" from "lanes for
// every party", and a single-chain fixture cannot tell a stacked layout from a side-by-side
// one - the two questions this block exists to answer.
const THREE_CHAINS: ValueChainModel = {
  model_version: 1,
  parties: [
    { id: 'GSUK', label: 'GS UK', colour: '#1a5276' },
    { id: 'ISS', label: 'ISS', colour: '#c0392b' },
    { id: 'DXI', label: 'DXI', colour: '#27ae60' },
  ],
  segments: [
    { id: '1', label: 'Property' },
    { id: '2', label: 'Fleet' },
    { id: '3', label: 'Support Services' },
  ],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Strategy' },
    { id: '1.2', segment_id: '1', label: 'Works Delivery' },
    { id: '2.1', segment_id: '2', label: 'Fleet Strategy' },
    { id: '2.2', segment_id: '2', label: 'Fleet Maintenance' },
    { id: '3.1', segment_id: '3', label: 'Technology' },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'GSUK', column: 10, attribution: 'stated' },
    { activity_id: '1.2', party_id: 'ISS', column: 20, attribution: 'stated' },
    { activity_id: '2.1', party_id: 'GSUK', column: 10, attribution: 'stated' },
    { activity_id: '2.2', party_id: 'DXI', column: 20, attribution: 'stated' },
    { activity_id: '3.1', party_id: 'GSUK', column: 10, attribution: 'stated' },
  ],
  tasks: [], propositions: [], links: [],
}

describe('the chains stack', () => {
  it('renders one block per chain, each with its own columns', () => {
    render(<ValueChainGrid model={THREE_CHAINS} />)
    for (const id of ['1', '2', '3']) {
      expect(screen.getByTestId(`chain-grid-${id}`)).toBeInTheDocument()
    }
    // Not one continuous run: side by side, Fleet sits beyond the whole of Property.
    expect(screen.queryByTestId('chain-grid')).toBeNull()
  })

  it('gives a chain lanes only for the parties that contribute in it', () => {
    render(<ValueChainGrid model={THREE_CHAINS} />)
    expect(screen.getByTestId('lane-1-ISS')).toBeInTheDocument()
    // ISS does no fleet work. An empty lane would say so, and the decision is that it
    // should not be said - this view is for flow and who does what, in what order.
    expect(screen.queryByTestId('lane-2-ISS')).toBeNull()
    expect(screen.queryByTestId('lane-3-ISS')).toBeNull()
    expect(screen.getByTestId('lane-2-DXI')).toBeInTheDocument()
    expect(screen.queryByTestId('lane-1-DXI')).toBeNull()
    // GS UK is in all three, so a lane per chain rather than one spanning them.
    for (const id of ['1', '2', '3']) {
      expect(screen.getByTestId(`lane-${id}-GSUK`)).toBeInTheDocument()
    }
  })

  it('names each chain above its own block, number first', () => {
    render(<ValueChainGrid model={THREE_CHAINS} />)
    expect(screen.getByTestId('segment-band-2')).toHaveTextContent('2')
    expect(screen.getByTestId('segment-band-2')).toHaveTextContent('Fleet')
  })

  it('columns restart at the left in every chain', () => {
    render(<ValueChainGrid model={THREE_CHAINS} />)
    // Each chain has its own column 10. Side by side these would be one physical column
    // per chain laid end to end; stacked, each chain starts again at its own first.
    for (const id of ['1', '2', '3']) {
      expect(screen.getByTestId(`cell-${id}-GSUK-10`)).toBeInTheDocument()
    }
  })

  it('shows no column ruler, while still rendering an unoccupied column as a gap', () => {
    // The ruler goes; the gap does not. A column nobody occupies is a real position in the
    // flow, and removing the header must not remove the cell.
    const gapped = structuredClone(THREE_CHAINS)
    gapped.activities.push({ id: '1.3', segment_id: '1', label: 'Later' })
    gapped.contributions.push({
      activity_id: '1.3', party_id: 'GSUK', column: 30, attribution: 'stated',
    })
    render(<ValueChainGrid model={gapped} />)
    expect(screen.queryAllByTestId(/^column-header-/)).toHaveLength(0)
    expect(screen.getByTestId('cell-1-GSUK-20')).toBeInTheDocument()
    expect(screen.getByTestId('cell-1-GSUK-20')).toHaveTextContent('')
  })
})
