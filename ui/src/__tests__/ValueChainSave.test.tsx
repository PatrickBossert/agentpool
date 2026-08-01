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
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import StructureTab from '../components/StructureTab'
import { valueChainApi } from '../api/endpoints'
import type { ValueChainModel } from '../utils/valueChainModel'

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
}))

function Wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <StructureTab slug="acme-rail" />
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

// The two tests formerly here - "keeps a description edit when Setup is visited and
// Structure is returned to" and "still reports the edit as unsaved after the round trip
// through Setup" - exercised the old ValueChain page's `hidden` (not unmounted) rendering
// of the Structure tab, which is what let a person switch to Setup and back without losing
// the working copy. That switch was internal to the retired page; StructureTab has no
// sibling Setup/Structure toggle of its own to move the test onto.
//
// The same concern now sits one level up: AgentDetailPanel.tsx conditionally renders each
// of its own tabs with `{tab === 'output' && ...}` rather than hiding them, so navigating
// from Output to another panel tab and back unmounts StructureTab and discards its working
// copy exactly as the removed comment in StructureTab.tsx warns against. That is a real gap,
// not something this migration can paper over with a same-shape test - see the task report.
