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
