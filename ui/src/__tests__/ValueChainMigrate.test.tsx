// ui/src/__tests__/ValueChainMigrate.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import ValueChain from '../pages/ValueChain'
import { valueChainApi } from '../api/endpoints'

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

const notFound = () =>
  Object.assign(new Error('Not Found'), {
    response: { status: 404 },
    isAxiosError: true,
  })

beforeEach(() => {
  vi.mocked(valueChainApi.get).mockRejectedValue(notFound())
  vi.mocked(valueChainApi.migrate).mockReset()
})

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

async function openStructureAndMigrate() {
  render(<Wrapper />)
  await userEvent.click(await screen.findByRole('button', { name: 'Structure' }))
  await userEvent.click(
    await screen.findByRole('button', { name: /migrate from the existing diagram/i }),
  )
}

describe('ValueChain migration result', () => {
  it('shows what the migration produced, so a thin result is visible rather than silent', async () => {
    vi.mocked(valueChainApi.migrate).mockResolvedValue({
      created: true,
      counts: {
        parties: 3,
        segments: 3,
        activities: 17,
        contributions: 17,
        tasks: 59,
        derived: 2,
      },
    })

    await openStructureAndMigrate()

    const summary = await screen.findByTestId('migration-counts')
    expect(summary.textContent).toMatch(/3 segments/)
    expect(summary.textContent).toMatch(/17 activities/)
    expect(summary.textContent).toMatch(/17 contributions/)
  })

  it('reports a refused migration with the reason the server gave', async () => {
    // The registry's levels were not L1/L2/L3, so the migration produced nothing and was
    // refused rather than saved as an empty model. The server reports this the same
    // {"problems": [...]} shape PUT /value-chain-model already uses for a save refusal.
    vi.mocked(valueChainApi.migrate).mockRejectedValue(
      Object.assign(new Error('Unprocessable'), {
        isAxiosError: true,
        response: {
          status: 422,
          data: {
            detail: {
              problems: [
                'expected at least one L1 entry to become a segment, and found none: ' +
                  "3 registry entries carry levels ''",
              ],
            },
          },
        },
      }),
    )

    await openStructureAndMigrate()

    expect(await screen.findByText(/expected at least one L1 entry/i)).toBeInTheDocument()
  })
})
