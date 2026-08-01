// ui/src/__tests__/ValueChainSave.test.tsx
//
// Covers the Save control's contract with the backend: every problem in a 422 response
// must be shown, not just the first, and the "unsaved changes" indicator must track the
// real state of the working copy - present after an edit, gone after a successful save.
//
// Migrated from mounting the retired ValueChain page to mounting StructureTab directly -
// StructureTab is now registered as Alex's Output tab editor (CREW_OUTPUT_EDITOR in
// AgentDetailPanel.tsx), so there is no more "Structure" tab button to click into first.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import StructureTab from '../components/StructureTab'
import AgentDetailPanel from '../components/AgentDetailPanel'
import { AuthProvider } from '../context/AuthContext'
import { valueChainApi } from '../api/endpoints'
import type { ValueChainModel } from '../utils/valueChainModel'
import type { AgentOutput } from '../types'

const MODEL: ValueChainModel = {
  model_version: 1,
  parties: [{ id: 'sp', label: 'SP-GS', colour: '#1a5276' }],
  segments: [{ id: '1', label: 'PROPERTY', description: '' }],
  activities: [{ id: '1.1', segment_id: '1', label: 'Reactive', description: '', active: true }],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: 'first', attribution: 'stated' },
  ],
  tasks: [], propositions: [], links: [],
}

vi.mock('../api/endpoints', () => ({
  valueChainApi: {
    get: vi.fn(),
    save: vi.fn(),
    migrate: vi.fn(),
  },
  // Needed only by the AgentDetailPanel-mounted tests below - AlexSetupTab (Alex's Setup tab)
  // reads project settings and documents when the panel's Setup tab is visited.
  projectsApi: {
    getSettings: vi.fn().mockResolvedValue({}),
    documents: vi.fn().mockResolvedValue([]),
    updateSettings: vi.fn(),
  },
}))

// AgentDetailPanel loads chat history unconditionally on mount, regardless of which tab is
// active, so this has to be mocked for the AgentDetailPanel-mounted tests below even though
// none of them touch Chat.
vi.mock('../api/agentChat', () => ({
  agentChatApi: {
    getHistory: vi.fn().mockResolvedValue([]),
    clearHistory: vi.fn().mockResolvedValue(undefined),
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

// discovery_mapping's primary output type is still 'value_chain' in this task (see
// AgentOutputTab.test.tsx's own note - a later task repoints it to 'value_chain_model'), so
// a current output of that type is what makes AgentOutputTab hand off to the registered
// editor (StructureTab) at all.
const PANEL_OUTPUTS: AgentOutput[] = [{
  id: 1, agent_name: 'value_chain_mapper', output_type: 'value_chain',
  version: 1, is_current: true, review_status: 'approved',
  created_at: '2026-08-01 10:00:00', file_path: 'value_chain.json',
}]

function PanelWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter>
          <AgentDetailPanel
            slug="acme-rail"
            crewKey="discovery_mapping"
            crewRun={undefined}
            outputs={PANEL_OUTPUTS}
            logs={[]}
            isPipelineActive={false}
          />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

async function editDescription() {
  render(<Wrapper />)
  const field = await screen.findByTestId('description-1.1-sp')
  await userEvent.type(field, ' more')
  return field
}

beforeEach(() => {
  vi.mocked(valueChainApi.get).mockResolvedValue({ model: structuredClone(MODEL) })
  vi.mocked(valueChainApi.save).mockReset()
})

describe('ValueChain save', () => {
  it('surfaces every problem from a 422 response, not just the first', async () => {
    vi.mocked(valueChainApi.save).mockRejectedValue(
      Object.assign(new Error('Unprocessable'), {
        isAxiosError: true,
        response: {
          status: 422,
          data: {
            detail: {
              problems: [
                "two contributions occupy column 20 in party 'sp'’s lane",
                'contribution names unknown party ghost',
              ],
            },
          },
        },
      }),
    )

    await editDescription()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(/two contributions occupy column 20/)).toBeInTheDocument()
    expect(await screen.findByText(/unknown party ghost/)).toBeInTheDocument()
  })

  it('shows the unsaved-changes indicator after an edit and clears it once saved', async () => {
    vi.mocked(valueChainApi.save).mockResolvedValue({ output_id: 1 })

    await editDescription()
    expect(screen.getByTestId('unsaved-changes')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(screen.queryByTestId('unsaved-changes')).not.toBeInTheDocument()
    })
  })

  // Only the Save button is disabled while the request is in flight - the description
  // inputs, the drag handles and the party menus all stay live. The request carries the
  // working copy as it stood when Save was pressed, so anything typed after that was never
  // sent; clearing the unsaved flag on success then let the reseed effect overwrite the
  // working copy with the pre-keystroke server model, and the UI reported success.
  it('keeps an edit typed while a save is in flight, and still calls it unsaved', async () => {
    let release: (result: { output_id: number }) => void = () => {}
    vi.mocked(valueChainApi.save).mockImplementation(
      () => new Promise((resolve) => { release = resolve }),
    )

    const field = await editDescription()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await userEvent.type(field, ' again')

    release({ output_id: 1 })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
    })

    expect((screen.getByTestId('description-1.1-sp') as HTMLInputElement).value).toBe(
      'first more again',
    )
    expect(screen.getByTestId('unsaved-changes')).toBeInTheDocument()
  })
})

// The two tests below - "keeps a description edit when Setup is visited and Output is
// returned to" and "still reports the edit as unsaved after the round trip through Setup" -
// exercised the old ValueChain page's `hidden` (not unmounted) rendering of the Structure
// tab, which is what let a person switch to Setup and back without losing the working copy.
// That switch was internal to the retired page, so they can't be moved onto StructureTab
// itself - it has no sibling Setup/Structure toggle of its own any more. The concern they
// guard against now sits one level up, at AgentDetailPanel's own Output/Status/Chat/Setup/
// Skills tabs, so that is where they are re-anchored: AgentDetailPanel.tsx's Output branch
// is kept mounted and merely hidden (`hidden={tab !== 'output'}`) rather than conditionally
// rendered, specifically so this pair keeps passing.
describe('unsaved Structure edits across an AgentDetailPanel tab change', () => {
  async function editDescriptionInThePanel() {
    render(<PanelWrapper />)
    const field = await screen.findByTestId('description-1.1-sp')
    await userEvent.type(field, ' more')
    return field
  }

  it('keeps a description edit when Setup is visited and Output is returned to', async () => {
    await editDescriptionInThePanel()

    await userEvent.click(screen.getByRole('button', { name: 'Setup' }))
    // Proves the click actually navigated, not just that nothing crashed - Setup's own
    // content (Alex's Research Brief section) has to be on screen before switching back.
    await screen.findByText('Research Brief')
    await userEvent.click(screen.getByRole('button', { name: /^Output/ }))

    const field = (await screen.findByTestId('description-1.1-sp')) as HTMLInputElement
    expect(field.value).toBe('first more')
  })

  it('still reports the edit as unsaved after the round trip through Setup', async () => {
    // Losing the indicator is worse than losing the edit: it says the working copy matches
    // the server when it does not.
    await editDescriptionInThePanel()
    expect(screen.getByTestId('unsaved-changes')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Setup' }))
    await screen.findByText('Research Brief')
    await userEvent.click(screen.getByRole('button', { name: /^Output/ }))

    expect(screen.getByTestId('unsaved-changes')).toBeInTheDocument()
  })
})
