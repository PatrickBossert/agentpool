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

  it('moving a contribution changes only its column', async () => {
    render(<ValueChainTable model={MODEL} onChange={onChange} />)
    await userEvent.click(screen.getByTestId('move-right-1.1-sp'))

    const latest = onChange.mock.calls.at(-1)![0] as ValueChainModel
    const moved = latest.contributions.find((c) => c.activity_id === '1.1')!
    const other = latest.contributions.find((c) => c.activity_id === '1.2')!
    expect(moved.column).toBeGreaterThan(10)
    expect(other.column).toBe(20)
    expect(moved.description).toBe('first')
  })

  it('is read-only when no onChange is given', () => {
    render(<ValueChainTable model={MODEL} />)
    expect(screen.queryByTestId('description-1.1-sp')).not.toBeInTheDocument()
  })
})
