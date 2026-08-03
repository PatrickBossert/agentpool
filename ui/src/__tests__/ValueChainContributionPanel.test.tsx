// ui/src/__tests__/ValueChainContributionPanel.test.tsx
//
// Exercises the contribution panel through StructureTab, not by mounting ContributionPanel
// directly - a test that only rendered ContributionPanel with hand-supplied props would
// still pass even if nothing in the app ever selected a contribution for it to show.
//
// Migrated from mounting the retired ValueChain page to mounting StructureTab directly -
// StructureTab is now registered as Alex's Output tab editor (CREW_OUTPUT_EDITOR in
// AgentDetailPanel.tsx), so there is no more "Structure" tab button to click into first.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import StructureTab from '../components/StructureTab'
import type { ValueChainModel } from '../utils/valueChainModel'

// vi.mock factories are hoisted above the top of the file, so the fixture has to be
// built inside vi.hoisted rather than referenced as a plain top-level const.
const { MODEL } = vi.hoisted(() => ({
  MODEL: {
    model_version: 1,
    parties: [
      { id: 'sp', label: 'SP-GS', colour: '#1a5276' },
      { id: 'iss', label: 'ISS', colour: '#7d3c98' },
    ],
    segments: [{ id: '1', label: 'PROPERTY', description: '' }],
    activities: [
      { id: '1.1', segment_id: '1', label: 'Reactive', description: '', active: true },
      { id: '1.2', segment_id: '1', label: 'Planned', description: '', active: true },
    ],
    contributions: [
      { activity_id: '1.1', party_id: 'sp', column: 10, description: 'first', attribution: 'stated' },
      { activity_id: '1.1', party_id: 'iss', column: 15, description: 'joint', attribution: 'stated' },
      { activity_id: '1.2', party_id: 'sp', column: 20, description: 'second', attribution: 'stated' },
    ],
    // SP-GS gets three tasks deliberately. A one-task contribution cannot tell "highlights
    // the activity you clicked" from "highlights the first activity" - they are the same
    // one - so the highlight tests click the middle of three. t2 carries no label, which is
    // the shape every task in the live model has; the others carry one, which is the shape
    // every other fixture has. Both must render with the number leading.
    tasks: [
      { id: 't1', activity_id: '1.1', party_id: 'sp', label: 'Log the fault', description: 'Raise a ticket' },
      { id: 't2', activity_id: '1.1', party_id: 'sp', description: 'Assess the damage' },
      { id: 't3', activity_id: '1.1', party_id: 'sp', label: 'Close the job', description: 'Sign off' },
      { id: 't4', activity_id: '1.1', party_id: 'iss', label: 'Execute repair', description: 'Fix on site' },
    ],
    propositions: [
      { id: 'p1', activity_id: '1.1', description: 'Faster turnaround', party_id: 'sp' },
    ],
    links: [],
  } satisfies ValueChainModel,
}))

vi.mock('../api/endpoints', () => ({
  valueChainApi: {
    get: vi.fn().mockResolvedValue({ model: MODEL }),
    save: vi.fn(),
    migrate: vi.fn(),
  },
}))

function Wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <StructureTab slug="acme-rail" />
    </QueryClientProvider>
  )
}

async function openStructureTab() {
  render(<Wrapper />)
  await screen.findByTestId('card-header-1.1-sp')
}

describe('ValueChain contribution panel wiring', () => {
  it('shows no dialog before a contribution is selected', async () => {
    await openStructureTab()

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('selecting a card in the grid shows that contribution in the panel', async () => {
    await openStructureTab()

    await userEvent.click(screen.getByTestId('edit-1.1-sp'))

    const panel = screen.getByTestId('contribution-panel')
    expect(screen.getByTestId('edit-task-label-t1')).toHaveValue('Log the fault')
    expect(panel).toHaveTextContent('Raise a ticket')
    expect(panel).toHaveTextContent('Faster turnaround')
    expect(panel).toHaveTextContent('SP-GS')
  })

  it('is keyboard reachable: focusing and activating the select control with the keyboard selects it', async () => {
    await openStructureTab()

    const selectControl = screen.getByTestId('edit-1.1-sp')
    selectControl.focus()
    await userEvent.keyboard('{Enter}')

    expect(screen.getByTestId('edit-task-label-t1')).toHaveValue('Log the fault')
  })

  it('shows the empty state, not a blank region, for a contribution with no tasks', async () => {
    await openStructureTab()

    await userEvent.click(screen.getByTestId('edit-1.2-sp'))

    const panel = screen.getByTestId('contribution-panel')
    expect(panel).toHaveTextContent(/no tasks recorded/i)
    expect(panel).toHaveTextContent(/no propositions recorded/i)
  })

  it('typing in a description field does not fight with cell selection', async () => {
    await openStructureTab()

    const field = screen.getByTestId('description-1.1-sp')
    await userEvent.type(field, ' more')

    expect(field).toHaveValue('first more')
    // Typing must never have been intercepted by a selection handler swallowing keys.
    expect(screen.queryByTestId('contribution-panel')).not.toBeInTheDocument()
  })

  it('opens as a dialog when the pencil is activated', async () => {
    await openStructureTab()
    await userEvent.click(await screen.findByTestId('edit-1.1-sp'))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByTestId('edit-task-label-t1')).toHaveValue('Log the fault')
  })

  it('closes on the close control', async () => {
    await openStructureTab()
    await userEvent.click(await screen.findByTestId('edit-1.1-sp'))
    await userEvent.click(screen.getByTestId('close-contribution-panel'))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    await openStructureTab()
    await userEvent.click(await screen.findByTestId('edit-1.1-sp'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('closes when the backdrop is clicked', async () => {
    await openStructureTab()
    await userEvent.click(await screen.findByTestId('edit-1.1-sp'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('contribution-panel-backdrop'))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('stays open when something inside the dialog body is clicked', async () => {
    await openStructureTab()
    await userEvent.click(await screen.findByTestId('edit-1.1-sp'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    // A real, non-interactive element inside the dialog body - not the close control,
    // which would close it regardless of whether propagation was stopped.
    await userEvent.click(screen.getByRole('heading', { name: 'Tasks' }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it("shows the tasks of the party whose card was opened, not the other party's", async () => {
    // Tasks belong to the contribution, so opening ISS's card on a jointly-delivered
    // activity must not show SP-GS's tasks.
    await openStructureTab()
    await userEvent.click(await screen.findByTestId('edit-1.1-sp'))

    // Asserted on which task rows exist, not on text: with the labels in inputs, a
    // not.toHaveTextContent assertion would pass whatever the dialog held.
    expect(screen.getByTestId('task-t1')).toBeInTheDocument()
    expect(screen.queryByTestId('task-t4')).toBeNull()
  })



  it('leads each activity with its number, then its label when there is one', async () => {
    await openStructureTab()
    await userEvent.click(screen.getByTestId('edit-1.1-sp'))

    // t1 has a label. The old `label ?? id` fallback rendered the label alone and dropped
    // the number - invisible only for as long as no task carries a label.
    expect(screen.getByTestId('task-t1')).toHaveTextContent('t1')
    expect(screen.getByTestId('edit-task-label-t1')).toHaveValue('Log the fault')
    // t2 has none: the number still leads, and the description stands in for the label.
    expect(screen.getByTestId('task-t2')).toHaveTextContent('t2')
    expect(screen.getByTestId('edit-task-label-t2')).toHaveValue('Assess the damage')
  })

  it('leads the dialog heading with the activity number', async () => {
    await openStructureTab()
    await userEvent.click(screen.getByTestId('edit-1.1-sp'))

    expect(screen.getByRole('heading', { name: /^1\.1 Reactive/ })).toBeInTheDocument()
  })
})

describe('the dialog edits', () => {
  it('edits the stage label and the change reaches the model', async () => {
    await openStructureTab()
    await userEvent.click(screen.getByTestId('edit-1.1-sp'))

    const field = screen.getByTestId('edit-activity-label-1.1')
    await userEvent.clear(field)
    await userEvent.type(field, 'Reactive Repair')

    // Controlled, never defaultValue - the same defence that guards the card's
    // description. An uncontrolled field shows every keystroke and loses them all on save,
    // which is how this class of defect corrupted saved data once already.
    expect(field).toHaveValue('Reactive Repair')
  })

  it('edits an activity label and the change reaches the model', async () => {
    await openStructureTab()
    await userEvent.click(screen.getByTestId('edit-1.1-sp'))

    const field = screen.getByTestId('edit-task-label-t2')
    await userEvent.type(field, '!')

    expect(field).toHaveValue('Assess the damage!')
  })

  it('edits one activity without disturbing its siblings', async () => {
    // A single-task contribution cannot tell "edits the one you typed in" from "edits
    // whichever it finds first". t2 is the middle of SP-GS's three.
    await openStructureTab()
    await userEvent.click(screen.getByTestId('edit-1.1-sp'))

    await userEvent.type(screen.getByTestId('edit-task-label-t2'), '!')

    expect(screen.getByTestId('edit-task-label-t1')).toHaveValue('Log the fault')
    expect(screen.getByTestId('edit-task-label-t3')).toHaveValue('Close the job')
  })
})

// The panel is a modal dialog covering the whole grid. A keyboard-only user landed nowhere
// when it opened, and nowhere useful when it closed. A full focus trap is out of scope.
describe('the contribution panel and the keyboard', () => {
  it('names the activity in its accessible name, not only its ID', async () => {
    // "1.1 detail" is what a screen reader announced. The activity's label is in scope.
    await openStructureTab()
    await userEvent.click(screen.getByTestId('edit-1.1-sp'))

    expect(screen.getByRole('dialog')).toHaveAccessibleName(/Reactive/)
  })

  it('moves focus into the dialog when it opens', async () => {
    await openStructureTab()
    await userEvent.click(screen.getByTestId('edit-1.1-sp'))

    expect(screen.getByTestId('contribution-panel')).toHaveFocus()
  })

  it('returns focus to the pencil that opened it when it closes', async () => {
    await openStructureTab()
    const opener = screen.getByTestId('edit-1.1-sp')
    await userEvent.click(opener)
    await userEvent.click(screen.getByTestId('close-contribution-panel'))

    expect(opener).toHaveFocus()
  })

})
