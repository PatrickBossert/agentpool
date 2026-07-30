// ui/src/__tests__/ValueChainParties.test.tsx
import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect } from 'vitest'

import { ValueChainGrid } from '../components/ValueChainGrid'
import type { ValueChainModel } from '../utils/valueChainModel'

const MODEL: ValueChainModel = {
  model_version: 1,
  parties: [
    { id: 'sp', label: 'SP-GS' },
    { id: 'iss', label: 'ISS' },
    { id: 'dxi', label: 'DXI' },
  ],
  segments: [{ id: '1', label: 'Property Value Chain' }],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Strategy' },
    { id: '1.2', segment_id: '1', label: 'Reactive Maintenance' },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: 'first', attribution: 'stated' },
    { activity_id: '1.2', party_id: 'sp', column: 20, description: 'second', attribution: 'derived' },
  ],
  tasks: [
    { activity_id: '1.2', party_id: 'sp', id: '1.2.1', label: 'Raise works order' },
    { activity_id: '1.2', party_id: 'sp', id: '1.2.2', label: 'Approve spend' },
  ],
  propositions: [],
  links: [],
}

let latest: ValueChainModel = MODEL

function Stateful() {
  const [model, setModel] = useState(MODEL)
  latest = model
  return <ValueChainGrid model={model} onChange={setModel} />
}

describe('adding a party', () => {
  it('offers only parties not already contributing to that activity', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))

    expect(screen.getByTestId('add-party-1.2-sp-iss')).toBeInTheDocument()
    expect(screen.getByTestId('add-party-1.2-sp-dxi')).toBeInTheDocument()
    expect(screen.queryByTestId('add-party-1.2-sp-sp')).not.toBeInTheDocument()
  })

  it('puts the new contribution in the same column, meaning concurrent delivery', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('add-party-1.2-sp-iss'))

    expect(screen.getByTestId('cell-iss-20')).toContainElement(screen.getByTestId('card-1.2-iss'))
  })

  it('marks the new contribution stated, because a person stated it', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('add-party-1.2-sp-iss'))

    expect(screen.queryByTestId('derived-1.2-iss')).not.toBeInTheDocument()
    expect(
      latest.contributions.find((c) => c.activity_id === '1.2' && c.party_id === 'iss')!.attribution,
    ).toBe('stated')
  })
})

describe('confirming a derived attribution', () => {
  it('offers Confirm on a derived contribution only', () => {
    render(<Stateful />)
    expect(screen.getByTestId('confirm-attribution-1.2-sp')).toBeInTheDocument()
    expect(screen.queryByTestId('confirm-attribution-1.1-sp')).not.toBeInTheDocument()
  })

  it('promotes it to stated and removes both the marker and the control', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('confirm-attribution-1.2-sp'))

    expect(screen.queryByTestId('derived-1.2-sp')).not.toBeInTheDocument()
    expect(screen.queryByTestId('confirm-attribution-1.2-sp')).not.toBeInTheDocument()
    expect(
      latest.contributions.find((c) => c.activity_id === '1.2')!.attribution,
    ).toBe('stated')
  })
})

describe('removing a party', () => {
  it("refuses when it is the activity's only contribution, and says why", async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.1-sp'))

    const remove = screen.getByTestId('remove-party-1.1-sp')
    expect(remove).toBeDisabled()
    expect(remove).toHaveAccessibleDescription(/only party|would disappear/i)
  })

  it('names how many tasks will be deleted before doing anything', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('add-party-1.2-sp-iss'))
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('remove-party-1.2-sp'))

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('2')
    expect(dialog).toHaveTextContent(/task/i)
  })

  it('removes the contribution and its tasks together on confirm', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('add-party-1.2-sp-iss'))
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('remove-party-1.2-sp'))
    await userEvent.click(screen.getByTestId('confirm-remove'))

    expect(screen.queryByTestId('card-1.2-sp')).not.toBeInTheDocument()
    expect(latest.tasks.filter((t) => t.party_id === 'sp')).toHaveLength(0)
    expect(latest.contributions.filter((c) => c.activity_id === '1.2')).toHaveLength(1)
  })

  it('changes nothing on cancel', async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('add-party-1.2-sp-iss'))
    const afterAdd = structuredClone(latest)

    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('remove-party-1.2-sp'))
    await userEvent.click(screen.getByTestId('cancel-remove'))

    expect(latest).toEqual(afterAdd)
    expect(screen.getByTestId('card-1.2-sp')).toBeInTheDocument()
  })
})
