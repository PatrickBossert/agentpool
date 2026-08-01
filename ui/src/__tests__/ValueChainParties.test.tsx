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
    // Same activity, a different party - this is what gives the removal test the power to
    // tell "deleted sp's tasks" apart from "deleted every task on the activity".
    { activity_id: '1.2', party_id: 'iss', id: '1.2.3', label: 'Inspect the site' },
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

    expect(screen.getByTestId('cell-1-iss-20')).toContainElement(screen.getByTestId('card-1.2-iss'))
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

// The sp-gs-am case, compressed: sp holds columns 10 and 20 of segment 1, and partner ISS
// has been dragged to column 20 to claim concurrency with sp's activity there. Adding sp to
// ISS's activity would put a second sp contribution in column 20, where the grid renders one
// card per cell - so the new card would never appear, and every save afterwards would be
// refused with a 422 naming column 20 and no activity.
const COLLIDING: ValueChainModel = {
  model_version: 1,
  parties: [
    { id: 'sp', label: 'SP-GS' },
    { id: 'iss', label: 'ISS' },
  ],
  segments: [{ id: '1', label: 'Property Value Chain' }],
  activities: [
    { id: '1.1', segment_id: '1', label: 'Strategy' },
    { id: '1.3', segment_id: '1', label: 'Planned Maintenance' },
    { id: '1.5', segment_id: '1', label: 'Reactive Repair' },
  ],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: '', attribution: 'stated' },
    { activity_id: '1.3', party_id: 'sp', column: 20, description: '', attribution: 'stated' },
    { activity_id: '1.5', party_id: 'iss', column: 20, description: '', attribution: 'stated' },
  ],
  tasks: [],
  propositions: [],
  links: [],
}

function StatefulColliding() {
  const [model, setModel] = useState(COLLIDING)
  latest = model
  return <ValueChainGrid model={model} onChange={setModel} />
}

describe('adding a party that already occupies that column', () => {
  it('offers the entry disabled rather than creating a card that renders nowhere', async () => {
    render(<StatefulColliding />)
    await userEvent.click(screen.getByTestId('party-menu-1.5-iss'))

    expect(screen.getByTestId('add-party-1.5-iss-sp')).toBeDisabled()
  })

  it('says which activity of that party is in the way, and in which column', async () => {
    render(<StatefulColliding />)
    await userEvent.click(screen.getByTestId('party-menu-1.5-iss'))

    expect(screen.getByTestId('add-party-1.5-iss-sp')).toHaveAccessibleDescription(
      /Planned Maintenance.*column 20/i,
    )
  })

  it('adds nothing when the disabled entry is clicked anyway', async () => {
    render(<StatefulColliding />)
    await userEvent.click(screen.getByTestId('party-menu-1.5-iss'))
    await userEvent.click(screen.getByTestId('add-party-1.5-iss-sp'))

    expect(screen.queryByTestId('card-1.5-sp')).not.toBeInTheDocument()
    expect(latest.contributions.filter((c) => c.party_id === 'sp')).toHaveLength(2)
    // The lane count is the only thing that moved when the card was hidden, so it is what
    // proves nothing was added behind the scenes.
    expect(screen.getByTestId('lane-count-sp')).toHaveTextContent('2')
  })

  it('leaves an entry whose column is free enabled', async () => {
    // Guards the refusal against overreach: nothing of iss sits in column 10.
    render(<StatefulColliding />)
    await userEvent.click(screen.getByTestId('party-menu-1.1-sp'))

    expect(screen.getByTestId('add-party-1.1-sp-iss')).toBeEnabled()
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

    // The sentence, not a bare '2'. The dialog also lists task IDs 1.2.1 and 1.2.2, which
    // both contain "2", so toHaveTextContent('2') could not fail whatever the count said.
    expect(screen.getByRole('dialog')).toHaveTextContent(/owns 2 tasks here/i)
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
    // iss's task on the same activity must survive - proves the deletion is scoped to the
    // removed party's contribution, not to every task on the activity.
    expect(latest.tasks.some((t) => t.id === '1.2.3')).toBe(true)
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

describe('the party menu', () => {
  it("opening one card's menu does not open another's", async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.1-sp'))
    expect(screen.getByTestId('add-party-1.1-sp-iss')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))

    expect(screen.getByTestId('add-party-1.2-sp-iss')).toBeInTheDocument()
    expect(screen.queryByTestId('add-party-1.1-sp-iss')).not.toBeInTheDocument()
  })
})

// Same gap as the contribution panel: a modal dialog covering the whole grid that a
// keyboard-only user was never moved into, and was left nowhere useful by. A full focus trap
// is out of scope.
describe('the removal dialog and the keyboard', () => {
  async function openRemovalDialog() {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('add-party-1.2-sp-iss'))
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('remove-party-1.2-sp'))
  }

  it('moves focus into the dialog when it opens', async () => {
    await openRemovalDialog()

    expect(screen.getByRole('dialog')).toHaveFocus()
  })

  it("returns focus to the card's Parties control when it closes", async () => {
    // Not to the Remove entry that opened it: that lives inside the menu, which closes as
    // part of making the request, so the menu button is the control still standing.
    await openRemovalDialog()
    await userEvent.click(screen.getByTestId('cancel-remove'))

    expect(screen.getByTestId('party-menu-1.2-sp')).toHaveFocus()
  })
})

describe('the removal dialog', () => {
  it("names the reopened card's party and activity, not the cancelled one's", async () => {
    render(<Stateful />)
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('add-party-1.2-sp-iss'))

    // Request removal of sp, see its details, then cancel without confirming.
    await userEvent.click(screen.getByTestId('party-menu-1.2-sp'))
    await userEvent.click(screen.getByTestId('remove-party-1.2-sp'))
    expect(screen.getByRole('dialog')).toHaveTextContent('SP-GS')
    await userEvent.click(screen.getByTestId('cancel-remove'))

    // Request removal of a different card - the dialog must not carry over the first
    // request's details.
    await userEvent.click(screen.getByTestId('party-menu-1.2-iss'))
    await userEvent.click(screen.getByTestId('remove-party-1.2-iss'))

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('ISS')
    expect(dialog).not.toHaveTextContent('SP-GS')
  })
})
