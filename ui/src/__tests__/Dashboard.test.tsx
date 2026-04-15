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
          crew_name: 'discovery',
          status: 'queued',
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
    expect(await screen.findByText(/discovery/i)).toBeInTheDocument()
    expect(await screen.findByText(/queued/i)).toBeInTheDocument()
  })
})
