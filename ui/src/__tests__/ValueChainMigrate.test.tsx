// ui/src/__tests__/ValueChainMigrate.test.tsx
//
// Migrated from mounting the retired ValueChain page (`../pages/ValueChain`) to mounting
// StructureTab directly. StructureTab is now registered as Alex's Output tab editor
// (CREW_OUTPUT_EDITOR['discovery_mapping'] in AgentDetailPanel.tsx), so there is no more
// "Structure" tab button to click into first - the component under test IS the tab content.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import StructureTab from '../components/StructureTab'
import { valueChainApi } from '../api/endpoints'

vi.mock('../api/endpoints', () => ({
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
      <StructureTab slug="acme-rail" />
    </QueryClientProvider>
  )
}

// Moved from ValueChain.test.tsx - "offers to migrate the existing diagram when no model
// has been saved". The old page hid Structure behind a tab switch and only opened on it
// once a legacy diagram or model was known to exist; the editor now IS the Output tab's
// entire content, so the button is simply there as soon as the model 404s.
describe('the migrate affordance', () => {
  it('shows the migrate button when no model has been saved for the project', async () => {
    render(<Wrapper />)
    expect(
      await screen.findByRole('button', { name: /migrate from the existing diagram/i }),
    ).toBeInTheDocument()
  })
})

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

    render(<Wrapper />)
    await userEvent.click(
      await screen.findByRole('button', { name: /migrate from the existing diagram/i }),
    )

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

    render(<Wrapper />)
    await userEvent.click(
      await screen.findByRole('button', { name: /migrate from the existing diagram/i }),
    )

    expect(await screen.findByText(/expected at least one L1 entry/i)).toBeInTheDocument()
  })
})
