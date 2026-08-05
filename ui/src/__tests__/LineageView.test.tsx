// ui/src/__tests__/LineageView.test.tsx
// Lineage is only worth recording if a reader can act on it. The case that matters is the
// one that went unnoticed for days: scripts built from a value chain since superseded.
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import LineageView from '../components/LineageView'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    lineage: vi.fn().mockResolvedValue({
      outputs: [
        { id: 1, agent_name: 'value_chain_mapper', output_type: 'value_chain_model',
          version: 9, is_current: 1, state: 'unknown', behind: [],
          input_output_ids: [], document_ids: [] },
        { id: 3, agent_name: 'interaction_designer', output_type: 'interview_scripts',
          version: 5, is_current: 1, state: 'stale',
          behind: [{ output_type: 'value_chain_model', built_from: 8, approved: 9 }],
          input_output_ids: [1], document_ids: [] },
        { id: 4, agent_name: 'value_lever_analyst', output_type: 'value_levers',
          version: 2, is_current: 1, state: 'unknown', behind: [],
          input_output_ids: [], document_ids: [3] },
      ],
      documents: { '3': 'SPUK_2025_Annual_Accounts.pdf' },
      blocked_writes: [
        { id: 1, agent_name: 'interaction_designer', key: 'value_chain_registry',
          owner: 'value_chain_mapper', reason: 'not the owner',
          attempted_at: '2026-08-04T15:53:29' },
      ],
    }),
  },
}))

function Wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <LineageView slug="acme" />
    </QueryClientProvider>
  )
}

describe('LineageView', () => {
  it('marks a stale output with the version it was built from', async () => {
    render(<Wrapper />)
    expect(await screen.findByTestId('lineage-3')).toHaveTextContent(/stale/i)
    expect(screen.getByTestId('lineage-3')).toHaveTextContent(/built from v8/i)
    expect(screen.getByTestId('lineage-3')).toHaveTextContent(/v9/)
  })

  it('does not mark an output with no ancestry as stale', async () => {
    // Morgan's levers have document ancestry and no state ancestry. Rendering that as stale
    // would cry wolf on every document-driven output in the project.
    render(<Wrapper />)
    expect(await screen.findByTestId('lineage-4')).not.toHaveTextContent(/stale/i)
  })

  it('names cited documents so the citation can be checked', async () => {
    render(<Wrapper />)
    expect(await screen.findByTestId('lineage-4'))
      .toHaveTextContent(/SPUK_2025_Annual_Accounts\.pdf/)
  })

  it('shows a blocked write as an upstream finding', async () => {
    render(<Wrapper />)
    const blocked = await screen.findByTestId('blocked-writes')
    expect(blocked).toHaveTextContent(/interaction_designer/)
    expect(blocked).toHaveTextContent(/value_chain_registry/)
  })
})
