// ui/src/__tests__/ValueChainContributionPanel.test.tsx
//
// Exercises the contribution panel through the rendered page, not by mounting it
// directly - a test that only rendered ContributionPanel with hand-supplied props would
// still pass even if nothing in the app ever selected a contribution for it to show.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import ValueChain from '../pages/ValueChain'
import type { ValueChainModel } from '../utils/valueChainModel'

// vi.mock factories are hoisted above the top of the file, so the fixture has to be
// built inside vi.hoisted rather than referenced as a plain top-level const.
const { MODEL } = vi.hoisted(() => ({
  MODEL: {
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
    tasks: [
      { id: 't1', activity_id: '1.1', party_id: 'sp', label: 'Log the fault', description: 'Raise a ticket' },
    ],
    propositions: [
      { id: 'p1', activity_id: '1.1', description: 'Faster turnaround', party_id: 'sp' },
    ],
    links: [],
  } satisfies ValueChainModel,
}))

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    valueChain: vi.fn().mockResolvedValue([]),
  },
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
      <AuthProvider>
        <MemoryRouter initialEntries={['/acme-rail/value-chain']}>
          <Routes>
            <Route path="/:slug/value-chain" element={<ValueChain />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

async function openStructureTab() {
  render(<Wrapper />)
  await userEvent.click(await screen.findByRole('button', { name: 'Structure' }))
  await screen.findByTestId('card-header-1.1-sp')
}

describe('ValueChain contribution panel wiring', () => {
  it('shows a sensible placeholder before anything is selected', async () => {
    await openStructureTab()
    expect(screen.getByTestId('contribution-panel-placeholder')).toBeInTheDocument()
    expect(screen.queryByTestId('contribution-panel')).not.toBeInTheDocument()
  })

  it('selecting a cell in the table shows that contribution in the panel', async () => {
    await openStructureTab()

    await userEvent.click(screen.getByTestId('card-header-1.1-sp'))

    const panel = screen.getByTestId('contribution-panel')
    expect(panel).toHaveTextContent('Log the fault')
    expect(panel).toHaveTextContent('Raise a ticket')
    expect(panel).toHaveTextContent('Faster turnaround')
    expect(panel).toHaveTextContent('SP-GS')
  })

  it('is keyboard reachable: focusing and activating the select control with the keyboard selects it', async () => {
    await openStructureTab()

    const selectControl = screen.getByTestId('card-header-1.1-sp')
    selectControl.focus()
    await userEvent.keyboard('{Enter}')

    expect(screen.getByTestId('contribution-panel')).toHaveTextContent('Log the fault')
  })

  it('shows the empty state, not a blank region, for a contribution with no tasks', async () => {
    await openStructureTab()

    await userEvent.click(screen.getByTestId('card-header-1.2-sp'))

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
})
