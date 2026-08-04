// ui/src/__tests__/Dashboard.test.tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import { IDLE_STATUSES } from '../components/agentStatus'
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
          crew_name: 'requirements',
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
    // Exact strings, not a loose match: the board carries "Discovery Interviews" as well,
    // and a regex would find both. The crew formerly labelled Discovery is now
    // Requirements - it enumerates requirements against initiatives and runs seventh.
    expect(await screen.findByText('Requirements')).toBeInTheDocument()
    // A finished crew is indicated by its re-run control, not by a "Done" badge.
    expect(await screen.findByTitle('Re-run')).toBeInTheDocument()
  })

  it('lets a finished crew rest instead of announcing it', async () => {
    render(<Wrapper slug="acme-rail" />)
    await screen.findByTitle('Re-run')
    expect(screen.queryByText('Done')).not.toBeInTheDocument()
  })

  it('returns a finished crew to its breathing idle activity', async () => {
    render(<Wrapper slug="acme-rail" />)
    // Asserted as "one of the idle activities" rather than the exact one. The activity is
    // chosen by hashing the crew key with the run id, so it changed when the crew was
    // renamed - and pinning a hash output couples this test to an implementation detail it
    // is not about. That the run is associated with its crew at all is covered by the
    // sibling test above, which asserts the completed badge.
    const shown = await screen.findAllByText(
      (text) => IDLE_STATUSES.includes(text as (typeof IDLE_STATUSES)[number]),
    )
    expect(shown.length).toBeGreaterThan(0)
  })
})
