// ui/src/__tests__/ValueChainSave.test.tsx
//
// Covers the Save control's contract with the backend: every problem in a 422 response
// must be shown, not just the first, and the "unsaved changes" indicator must track the
// real state of the working copy - present after an edit, gone after a successful save.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import ValueChain from '../pages/ValueChain'
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
  projectsApi: {
    valueChain: vi.fn().mockResolvedValue([]),
    getSettings: vi.fn().mockResolvedValue({}),
    documents: vi.fn().mockResolvedValue([]),
  },
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

async function editDescriptionAndOpenStructureTab() {
  render(<Wrapper />)
  await userEvent.click(await screen.findByRole('button', { name: 'Structure' }))
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

    await editDescriptionAndOpenStructureTab()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(/two contributions occupy column 20/)).toBeInTheDocument()
    expect(await screen.findByText(/unknown party ghost/)).toBeInTheDocument()
  })

  it('shows the unsaved-changes indicator after an edit and clears it once saved', async () => {
    vi.mocked(valueChainApi.save).mockResolvedValue({ output_id: 1 })

    await editDescriptionAndOpenStructureTab()
    expect(screen.getByTestId('unsaved-changes')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(screen.queryByTestId('unsaved-changes')).not.toBeInTheDocument()
    })
  })
})

describe('unsaved edits across a tab change', () => {
  // The Structure tab holds the working copy, the unsaved-changes flag, the change summary
  // and the selected contribution. Rendering it conditionally on the active tab unmounts it,
  // so one click on Setup discarded a drag, an added party and every description edit with
  // no warning at all - beforeunload does not fire on a tab change, and the unmount
  // unregisters it anyway.
  it('keeps a description edit when Setup is visited and Structure is returned to', async () => {
    await editDescriptionAndOpenStructureTab()

    await userEvent.click(screen.getByRole('button', { name: 'Setup' }))
    await userEvent.click(screen.getByRole('button', { name: 'Structure' }))

    const field = (await screen.findByTestId('description-1.1-sp')) as HTMLInputElement
    expect(field.value).toBe('first more')
  })

  it('still reports the edit as unsaved after the round trip through Setup', async () => {
    // Losing the indicator is worse than losing the edit: it says the working copy matches
    // the server when it does not.
    await editDescriptionAndOpenStructureTab()
    expect(screen.getByTestId('unsaved-changes')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Setup' }))
    await userEvent.click(screen.getByRole('button', { name: 'Structure' }))

    expect(screen.getByTestId('unsaved-changes')).toBeInTheDocument()
  })
})
