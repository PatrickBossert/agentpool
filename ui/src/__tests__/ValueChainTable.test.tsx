import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import { ValueChainTable, type ValueChainModel } from '../components/ValueChainTable'

const MODEL: ValueChainModel = {
  model_version: 1,
  parties: [
    { id: 'sp', label: 'SP-GS', colour: '#1a5276' },
    { id: 'iss', label: 'ISS', colour: '#c0392b' },
  ],
  segments: [{ id: '1', label: 'PROPERTY', description: '' }],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Reactive Maintenance', description: '', active: true },
    { id: '1.2', segment_id: '1', label: 'Planned Works', description: '', active: true },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: 'Raises the order', attribution: 'stated' },
    { activity_id: '1.1', party_id: 'iss', column: 10, description: 'Executes it', attribution: 'stated' },
    { activity_id: '1.2', party_id: 'sp', column: 30, description: '', attribution: 'derived' },
  ],
  tasks: [], propositions: [], links: [],
}

// Columns are sparse so an insert between two neighbours can pick an intermediate value
// rather than renumbering the segment, which is exactly what produces a column that is not
// a multiple of ten. 15 sits between 10 and 20.
const INTERMEDIATE_MODEL: ValueChainModel = {
  model_version: 1,
  parties: [{ id: 'sp', label: 'SP-GS', colour: '#1a5276' }],
  segments: [{ id: '1', label: 'PROPERTY', description: '' }],
  activities: [
    { id: '1.1', segment_id: '1', label: 'First', description: '', active: true },
    { id: '1.4', segment_id: '1', label: 'Inserted', description: '', active: true },
    { id: '1.2', segment_id: '1', label: 'Second', description: '', active: true },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: '', attribution: 'stated' },
    { activity_id: '1.4', party_id: 'sp', column: 15, description: '', attribution: 'stated' },
    { activity_id: '1.2', party_id: 'sp', column: 20, description: '', attribution: 'stated' },
  ],
  tasks: [], propositions: [], links: [],
}

describe('ValueChainTable', () => {
  it('shows a lane per party within the segment', () => {
    render(<ValueChainTable model={MODEL} />)
    expect(screen.getByText('SP-GS')).toBeInTheDocument()
    expect(screen.getByText('ISS')).toBeInTheDocument()
  })

  it('places both parties of one activity in the same column', () => {
    render(<ValueChainTable model={MODEL} />)
    const sp = screen.getByTestId('cell-sp-10')
    const iss = screen.getByTestId('cell-iss-10')
    expect(sp.textContent).toContain('Reactive Maintenance')
    expect(iss.textContent).toContain('Reactive Maintenance')
  })

  it('renders a gap where a lane has no contribution', () => {
    render(<ValueChainTable model={MODEL} />)
    // SP-GS occupies 10 and 30; column 20 is a gap in both lanes.
    expect(screen.getByTestId('cell-sp-20').textContent).toBe('')
    expect(screen.getByTestId('cell-iss-30').textContent).toBe('')
  })

  it('marks a derived attribution so a wrong default is findable', () => {
    render(<ValueChainTable model={MODEL} />)
    expect(screen.getByTestId('cell-sp-30').textContent).toMatch(/derived/i)
  })

  it('does not mark a stated attribution', () => {
    render(<ValueChainTable model={MODEL} />)
    expect(screen.getByTestId('cell-sp-10').textContent).not.toMatch(/derived/i)
  })

  it('renders a contribution at an intermediate column rather than hiding it', () => {
    // A range built as min, min+10, min+20… never contains 15, so the contribution there
    // rendered nowhere: invisible and uneditable, while still present in the saved model
    // and still counted by validation.
    render(<ValueChainTable model={INTERMEDIATE_MODEL} />)
    expect(screen.getByTestId('cell-sp-10').textContent).toContain('First')
    expect(screen.getByTestId('cell-sp-15').textContent).toContain('Inserted')
    expect(screen.getByTestId('cell-sp-20').textContent).toContain('Second')
  })

  it('renders every occupied column exactly once and in order', () => {
    render(<ValueChainTable model={INTERMEDIATE_MODEL} />)
    const rendered = Array.from(document.querySelectorAll('[data-testid^="cell-sp-"]')).map(
      (cell) => Number(cell.getAttribute('data-testid')!.replace('cell-sp-', '')),
    )
    expect(rendered).toEqual([10, 15, 20])
  })

  it('keeps rendering a gap between two occupied columns', () => {
    const gapped: ValueChainModel = {
      ...INTERMEDIATE_MODEL,
      contributions: [
        { activity_id: '1.1', party_id: 'sp', column: 10, description: '', attribution: 'stated' },
        { activity_id: '1.2', party_id: 'sp', column: 30, description: '', attribution: 'stated' },
      ],
    }
    render(<ValueChainTable model={gapped} />)
    expect(screen.getByTestId('cell-sp-20').textContent).toBe('')
    expect(screen.getByTestId('cell-sp-30').textContent).toContain('Second')
  })

  it('renders nothing rather than crashing on an empty model', () => {
    const empty: ValueChainModel = {
      model_version: 1, parties: [], segments: [], activities: [],
      contributions: [], tasks: [], propositions: [], links: [],
    }
    render(<ValueChainTable model={empty} />)
    expect(screen.getByTestId('value-chain-empty')).toBeInTheDocument()
  })
}
)
