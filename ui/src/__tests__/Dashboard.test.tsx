// ui/src/__tests__/Dashboard.test.tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import Dashboard from '../pages/Dashboard'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    list: vi.fn().mockResolvedValue([
      { id: 1, slug: 'acme-rail', llm_mode: 'standard', sector: 'transport', status: 'created' },
    ]),
    status: vi.fn().mockResolvedValue({
      project_slug: 'acme-rail',
      project_status: 'created',
      crew_runs: [
        {
          id: 1,
          project_id: 1,
          // 'completed' rather than 'queued': getCrewStatus derives "queued" from
          // the orchestration run being active, not from a crew run's own status,
          // so a queued row on an idle pipeline renders as idle and asserts nothing
          // about the run. 'completed' maps straight from the row to a badge.
          crew_name: 'discovery',
          status: 'completed',
          result_json: null,
          started_at: null,
          finished_at: null,
          created_at: '2026-04-13T10:00:00',
        },
      ],
    }),
    outputs: vi.fn().mockResolvedValue([]),
  },
}))

function Wrapper({ slug }: { slug?: string }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={[slug ? `/${slug}` : '/']}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/:slug" element={<Dashboard />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

describe('Dashboard', () => {
  it('shows no-project message when no slug', () => {
    render(<Wrapper />)
    expect(screen.getByText(/select a project/i)).toBeInTheDocument()
  })

  it('shows crew run status when project selected', async () => {
    render(<Wrapper slug="acme-rail" />)
    // Exact strings, not /discovery/i: the board gained a "Discovery Interviews"
    // crew alongside "Discovery", so a loose match now finds both.
    expect(await screen.findByText('Discovery')).toBeInTheDocument()
    expect(await screen.findByText('Done')).toBeInTheDocument()
  })
})
