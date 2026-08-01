// ui/src/__tests__/AgentOutputTab.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { AgentOutputTab } from '../components/AgentOutputTab'
import type { AgentOutput } from '../types'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getOutputContent: vi.fn(),
    review: vi.fn(),
    revertOutput: vi.fn(),
  },
}))

// Two output types, one primary and one not. A crew with a single output type cannot
// distinguish "shows the primary" from "shows everything it has", so this fixture is the
// minimum that discriminates.
//
// discovery_mapping's primary type is 'value_chain' (CREW_OUTPUT_TYPE, unrepointed by this
// task - a later task moves it to 'value_chain_model').
const OUTPUTS: AgentOutput[] = [
  { id: 1, agent_name: 'value_chain_mapper', output_type: 'value_chain',
    version: 3, is_current: 1, review_status: 'approved', created_at: '2026-08-01 10:00:00', file_path: 'a.json' },
  { id: 2, agent_name: 'value_chain_mapper', output_type: 'value_chain',
    version: 2, is_current: 0, review_status: 'approved', created_at: '2026-07-31 10:00:00', file_path: 'b.json' },
  { id: 3, agent_name: 'value_chain_mapper', output_type: 'value_chain_registry',
    version: 13, is_current: 1, review_status: 'approved', created_at: '2026-08-01 09:00:00', file_path: 'c.json' },
]

function renderOutputTab(overrides: { crewKey?: string; outputs?: AgentOutput[] } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AgentOutputTab
        slug="t"
        crewKey={overrides.crewKey ?? 'discovery_mapping'}
        outputs={overrides.outputs ?? OUTPUTS}
      />
    </QueryClientProvider>,
  )
}

describe('AgentOutputTab', () => {
  it('renders the declared primary output and not the others', () => {
    renderOutputTab()
    expect(screen.getByTestId('primary-output-value_chain')).toBeInTheDocument()
    expect(screen.queryByTestId('primary-output-value_chain_registry')).not.toBeInTheDocument()
  })

  it('renders only the current version, not the version history', () => {
    renderOutputTab()
    expect(screen.getByTestId('primary-output-value_chain')).toHaveAttribute('data-version', '3')
    expect(screen.queryByTestId('output-version-2')).not.toBeInTheDocument()
  })

  it('shows no revert, reject or revise control - those live in Status', () => {
    renderOutputTab()
    expect(screen.queryByRole('button', { name: /revert/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /reject/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /revis/i })).not.toBeInTheDocument()
  })

  it("renders an agent's primary read-only when it has no declared editor", () => {
    // The case that proves this is a default and not a special case for Alex. CREW_OUTPUT_EDITOR
    // is empty in this task, so every crew - not just one without a bespoke editor - takes this
    // path; 'discovery' is picked here simply because it is a different crew to the one above.
    const outputs: AgentOutput[] = [{ ...OUTPUTS[0], agent_name: 'synthesis_analyst', output_type: 'discovery' }]
    renderOutputTab({ crewKey: 'discovery', outputs })
    expect(screen.getByTestId('primary-output-readonly')).toBeInTheDocument()
  })

  it('shows an empty state when the crew has no output of its primary type', () => {
    renderOutputTab({ outputs: [] })
    expect(screen.getByTestId('no-primary-output')).toBeInTheDocument()
  })
})
