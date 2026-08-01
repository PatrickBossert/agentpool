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
  // discovery_mapping's registered editor (StructureTab) queries this directly, so it has to
  // be mocked here too now that CREW_OUTPUT_EDITOR is no longer empty - an unmocked call
  // would reach for `.get` on `undefined`.
  valueChainApi: {
    get: vi.fn().mockRejectedValue(Object.assign(new Error('Not Found'), { response: { status: 404 }, isAxiosError: true })),
    save: vi.fn(),
    migrate: vi.fn(),
  },
}))

// Two output types, one primary and one not. A crew with a single output type cannot
// distinguish "shows the primary" from "shows everything it has", so this fixture is the
// minimum that discriminates.
//
// discovery_mapping's primary type is 'value_chain_model' (CREW_OUTPUT_TYPE) - repointed
// from the retired 'value_chain' Mermaid diagram now that the value chain has its own
// structured model and grid editor.
const OUTPUTS: AgentOutput[] = [
  { id: 1, agent_name: 'value_chain_mapper', output_type: 'value_chain_model',
    version: 3, is_current: true, review_status: 'approved', created_at: '2026-08-01 10:00:00', file_path: 'a.json' },
  { id: 2, agent_name: 'value_chain_mapper', output_type: 'value_chain_model',
    version: 2, is_current: false, review_status: 'approved', created_at: '2026-07-31 10:00:00', file_path: 'b.json' },
  { id: 3, agent_name: 'value_chain_mapper', output_type: 'value_chain_registry',
    version: 13, is_current: true, review_status: 'approved', created_at: '2026-08-01 09:00:00', file_path: 'c.json' },
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
    expect(screen.getByTestId('primary-output-value_chain_model')).toBeInTheDocument()
    expect(screen.queryByTestId('primary-output-value_chain_registry')).not.toBeInTheDocument()
  })

  it('renders only the current version, not the version history', () => {
    renderOutputTab()
    expect(screen.getByTestId('primary-output-value_chain_model')).toHaveAttribute('data-version', '3')
    expect(screen.queryByTestId('output-version-2')).not.toBeInTheDocument()
  })

  it('shows no revert, reject or revise control - those live in Status', () => {
    renderOutputTab()
    expect(screen.queryByRole('button', { name: /revert/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /reject/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /revis/i })).not.toBeInTheDocument()
  })

  it("renders an agent's primary read-only when it has no declared editor", () => {
    // The case that proves this is a default and not a special case for Alex. Only
    // discovery_mapping has a registered editor (StructureTab) as of this task, so any other
    // crew - 'discovery' here, simply because it differs from the one above - still takes
    // this path.
    const outputs: AgentOutput[] = [{ ...OUTPUTS[0], agent_name: 'synthesis_analyst', output_type: 'discovery' }]
    renderOutputTab({ crewKey: 'discovery', outputs })
    expect(screen.getByTestId('primary-output-readonly')).toBeInTheDocument()
  })

  it('shows an empty state when the crew has no output of its primary type', () => {
    renderOutputTab({ outputs: [] })
    expect(screen.getByTestId('no-primary-output')).toBeInTheDocument()
  })

  it('does not show the empty state for a crew whose primary type has an output', () => {
    // Regression case: every fixture above uses a crew already present in CREW_OUTPUT_TYPE,
    // which is exactly why a crew missing from that map (assessment_design and
    // stakeholder_management both were) rendered the empty state unconditionally despite
    // having real outputs. stakeholder_management's primary is 'stakeholder_engagement_plan' -
    // verified against agentStatus.ts's own description of the Stakeholder Manager agent as
    // "the authoritative record of programme health".
    const outputs: AgentOutput[] = [{
      id: 4, agent_name: 'stakeholder_manager', output_type: 'stakeholder_engagement_plan',
      version: 1, is_current: true, review_status: 'approved', created_at: '2026-08-01 10:00:00', file_path: 'plan.json',
    }]
    renderOutputTab({ crewKey: 'stakeholder_management', outputs })
    expect(screen.queryByTestId('no-primary-output')).not.toBeInTheDocument()
    expect(screen.getByTestId('primary-output-stakeholder_engagement_plan')).toBeInTheDocument()
  })

  // Migrated from the retired ValueChain.test.tsx - "opens on Structure for a legacy
  // project with a diagram and no model". The old page auto-switched its own Structure tab
  // on whenever a legacy `value_chain` output existed; there is no such switch to test any
  // more, because Alex's Output tab renders StructureTab directly whenever the primary
  // output row exists at all.
  //
  // discovery_mapping's primary type is now 'value_chain_model' rather than the retired
  // `value_chain` diagram, so what reaches the Editor here is a current *model* output row -
  // e.g. one whose file went missing from disk after a save - not a legacy diagram. The
  // scenario being guarded is unchanged: whenever StructureTab's own GET 404s, the migrate
  // affordance still has to be reachable through the Output tab rather than swallowed by it.
  it("renders Alex's Structure editor, migrate affordance included, when the saved model can't be loaded", async () => {
    renderOutputTab()
    expect(
      await screen.findByRole('button', { name: /migrate from the existing diagram/i }),
    ).toBeInTheDocument()
  })
})
