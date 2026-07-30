// ui/src/__tests__/ValueChain.test.tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import ValueChain from '../pages/ValueChain'
import { projectsApi, valueChainApi } from '../api/endpoints'
import type { AgentOutput, ProjectSettings } from '../types'
import type { ValueChainModel } from '../utils/valueChainModel'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    valueChain: vi.fn(),
    getSettings: vi.fn(),
    documents: vi.fn(),
  },
  valueChainApi: {
    get: vi.fn(),
    save: vi.fn(),
    migrate: vi.fn(),
  },
}))

const notFound = () =>
  Object.assign(new Error('Not Found'), { response: { status: 404 }, isAxiosError: true })

const LEGACY_OUTPUT = {
  id: 1,
  agent_name: 'enterprise_architect',
  output_type: 'value_chain',
  file_path: 'outputs/value_chain_v1.md',
  version: 1,
  review_status: 'approved',
  is_current: true,
  created_at: '2026-07-01T00:00:00Z',
} as AgentOutput

const MODEL: ValueChainModel = {
  model_version: 1,
  parties: [{ id: 'sp', label: 'SP-GS' }],
  segments: [{ id: '1', label: 'PROPERTY' }],
  activities: [{ id: '1.1', segment_id: '1', label: 'Reactive' }],
  contributions: [
    { activity_id: '1.1', party_id: 'sp', column: 10, description: 'first', attribution: 'stated' },
  ],
  tasks: [],
  propositions: [],
  links: [],
}

beforeEach(() => {
  vi.mocked(projectsApi.valueChain).mockResolvedValue([])
  vi.mocked(projectsApi.getSettings).mockResolvedValue({} as ProjectSettings)
  vi.mocked(projectsApi.documents).mockResolvedValue([])
  vi.mocked(valueChainApi.get).mockRejectedValue(notFound())
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

describe('ValueChain', () => {
  it('shows empty state heading', async () => {
    render(<Wrapper />)
    // Query the heading by role: the page body now also says "Value Chain Mapper"
    // and "each value chain node", so a bare text match finds three elements.
    expect(await screen.findByRole('heading', { name: 'Value Chain' })).toBeInTheDocument()
  })

  it('offers to migrate the existing diagram when no model has been saved', async () => {
    render(<Wrapper />)
    // With neither a legacy output nor a model, the page opens on Setup, so the empty state
    // has to be navigated to.
    await userEvent.click(await screen.findByRole('button', { name: 'Structure' }))
    expect(
      await screen.findByRole('button', { name: /migrate from the existing diagram/i }),
    ).toBeInTheDocument()
  })
})

// GET /projects/{slug}/value-chain is filtered to output_type="value_chain", which only
// MermaidRenderTool writes - and that tool is registered for enterprise_architect alone now,
// with value_chain_mapper carrying an explicit comment saying it was removed. A project
// mapped by a fresh crew run therefore has a model and no legacy output at all, so keying
// the auto-switch on outputs alone never opened it on Structure. Keying on the model alone
// would regress the other direction: "Migrate from the existing diagram" only exists inside
// the Structure tab, so a legacy project would have nothing to find. Both directions below.
describe('which tab the page opens on', () => {
  it('opens on Structure for a legacy project with a diagram and no model', async () => {
    vi.mocked(projectsApi.valueChain).mockResolvedValue([LEGACY_OUTPUT])

    render(<Wrapper />)

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /migrate from the existing diagram/i }),
      ).toBeVisible()
    })
  })

  it('opens on Structure for a fresh-pipeline project with a model and no diagram', async () => {
    vi.mocked(valueChainApi.get).mockResolvedValue({ model: structuredClone(MODEL) })

    render(<Wrapper />)

    await waitFor(() => {
      expect(screen.getByTestId('card-1.1-sp')).toBeVisible()
    })
  })

  it('opens on Setup when the project has neither, so nothing forces the tab', async () => {
    // The anchor for the two assertions above: without it, a page that always showed
    // Structure would satisfy both of them.
    render(<Wrapper />)

    expect(await screen.findByRole('heading', { name: 'Value Chain' })).toBeInTheDocument()
    // hidden: true, because the Structure tab stays mounted and merely hidden - the point
    // of the assertion is that it is present in the DOM and not showing.
    await waitFor(() => {
      expect(
        screen.getByRole('button', {
          name: /migrate from the existing diagram/i,
          hidden: true,
        }),
      ).not.toBeVisible()
    })
  })
})
