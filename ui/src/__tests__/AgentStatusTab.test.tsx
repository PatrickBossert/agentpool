// ui/src/__tests__/AgentStatusTab.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { AgentStatusTab } from '../components/AgentStatusTab'
import type { CrewStatus } from '../components/agentStatus'
import type { AgentOutput, CrewRun } from '../types'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getOutputContent: vi.fn(),
    review: vi.fn(),
    revertOutput: vi.fn(),
  },
}))

const OUTPUTS: AgentOutput[] = [
  { id: 1, agent_name: 'value_chain_mapper', output_type: 'value_chain',
    version: 3, is_current: true, review_status: 'approved', created_at: '2026-08-01 10:00:00', file_path: 'a.json' },
  { id: 2, agent_name: 'value_chain_mapper', output_type: 'value_chain',
    version: 2, is_current: false, review_status: 'approved', created_at: '2026-07-31 10:00:00', file_path: 'b.json' },
  { id: 3, agent_name: 'value_chain_mapper', output_type: 'value_chain_registry',
    version: 13, is_current: true, review_status: 'approved', created_at: '2026-08-01 09:00:00', file_path: 'c.json' },
]

function renderStatusTab(overrides: {
  crewRun?: CrewRun
  outputs?: AgentOutput[]
  primaryModel?: { segments: unknown[]; activities: unknown[]; contributions: unknown[]; tasks: unknown[] }
  crewStatus?: CrewStatus
} = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AgentStatusTab
        slug="t"
        crewKey="discovery_mapping"
        crewRun={overrides.crewRun}
        outputs={overrides.outputs ?? OUTPUTS}
        statusEvents={[]}
        primaryModel={overrides.primaryModel}
        crewStatus={overrides.crewStatus ?? 'idle'}
      />
    </QueryClientProvider>,
  )
}

describe('AgentStatusTab', () => {
  it('lists prior versions of the primary output', () => {
    renderStatusTab()
    expect(screen.getByTestId('output-version-2')).toBeInTheDocument()
  })

  it('lists non-primary output types, which the Output tab does not show', () => {
    renderStatusTab()
    expect(screen.getByTestId('output-type-value_chain_registry')).toBeInTheDocument()
  })

  it('offers revert on a prior version', () => {
    renderStatusTab()
    expect(screen.getByTestId('revert-2')).toBeInTheDocument()
  })

  it('does not offer revert on the current version - there is nothing to revert to', () => {
    renderStatusTab()
    expect(screen.queryByTestId('revert-1')).not.toBeInTheDocument()
  })

  it('keeps the run timestamps and the error detail', () => {
    const run: CrewRun & { error_detail?: string } = {
      id: 1, project_id: 1, crew_name: 'discovery_mapping', status: 'failed',
      result_json: null, started_at: '2026-08-01 10:00:00', finished_at: '2026-08-01 10:05:00',
      created_at: '2026-08-01 10:00:00', error_detail: 'boom',
    }
    renderStatusTab({ crewRun: run })
    expect(screen.getByText(/boom/)).toBeInTheDocument()
  })

  it('summarises a value chain model by counting what is in it', () => {
    // Computed from the artefact, so it cannot disagree with it.
    const model = {
      segments: [{ id: '1' }, { id: '2' }, { id: '3' }],
      activities: new Array(17).fill(0).map((_, i) => ({ id: `a${i}` })),
      contributions: new Array(17).fill(0).map((_, i) => ({ activity_id: `a${i}` })),
      tasks: new Array(59).fill(0).map((_, i) => ({ id: `t${i}` })),
      parties: [{ id: 'sp' }, { id: 'iss' }, { id: 'dxi' }],
      propositions: [], links: [], model_version: 1,
    }
    renderStatusTab({ primaryModel: model })
    const card = screen.getByTestId('output-summary')
    expect(card).toHaveTextContent('3 segments')
    expect(card).toHaveTextContent('17 activities')
    expect(card).toHaveTextContent('17 contributions')
    expect(card).toHaveTextContent('59 tasks')
  })

  it('does not show the working placeholder for a run waiting on a human, even though its row still says running', () => {
    // This product is built around review gates: the run row stays 'running' while a crew is
    // paused for HITL review, and only the resolved crewStatus (which factors in the waiting
    // set) can tell the two apart.
    const run: CrewRun = {
      id: 1, project_id: 1, crew_name: 'discovery_mapping', status: 'running',
      result_json: null, started_at: '2026-08-01 10:00:00', finished_at: null,
      created_at: '2026-08-01 10:00:00',
    }
    renderStatusTab({ crewRun: run, crewStatus: 'waiting' })
    expect(screen.queryByText(/is working/i)).not.toBeInTheDocument()
    expect(screen.getByText(/no activity yet/i)).toBeInTheDocument()
  })
})
