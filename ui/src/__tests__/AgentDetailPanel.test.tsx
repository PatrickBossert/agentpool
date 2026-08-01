// ui/src/__tests__/AgentDetailPanel.test.tsx
//
// The panel itself, not its tab components in isolation.
//
// AgentOutputTab.test.tsx and AgentStatusTab.test.tsx both hand their child a fixture array
// they built themselves, so neither can see what the panel does to that array on the way in -
// and the panel's own filtering is where Maya's entire Output tab went missing. Every
// assertion here therefore mounts AgentDetailPanel and reads what a user would actually see.
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import AgentDetailPanel from '../components/AgentDetailPanel'
import type { AgentOutput } from '../types'

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    token: 'test-token',
    user: { sub: 'panel-tester', role: 'reviewer', exp: 9999999999 },
    login: vi.fn(),
    logout: vi.fn(),
  }),
}))

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getOutputContent: vi.fn().mockResolvedValue({ content: '{}', output_type: 'json' }),
    review: vi.fn(),
    revertOutput: vi.fn(),
    getInterviewScripts: vi.fn().mockResolvedValue({}),
  },
  valueChainApi: {
    get: vi.fn().mockResolvedValue({ model: null }),
    save: vi.fn(),
    migrate: vi.fn(),
  },
  interviewsApi: {
    listSessions: vi.fn().mockResolvedValue({ sessions: [] }),
  },
}))

vi.mock('../api/agentChat', () => ({
  agentChatApi: {
    getHistory: vi.fn().mockResolvedValue([]),
    clearHistory: vi.fn().mockResolvedValue(undefined),
    send: vi.fn(),
  },
}))

vi.mock('../api/skills', () => ({
  skillsApi: {
    list: vi.fn().mockResolvedValue([]),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    extract: vi.fn(),
    extractMany: vi.fn(),
  },
}))

// Maya's real shape, taken from data/sp-gs-am.db: four `interview_scripts` rows (her declared
// primary), a spread of `interview_scripts_*` siblings, and the `*_interview_summaries` rows
// that are not her deliverable at all. Every one of these matches the hidden prefix or the
// hidden suffix, which is exactly why filtering before the tabs see the array emptied both.
const MAYA_OUTPUTS: AgentOutput[] = [
  { id: 1, agent_name: 'interaction_designer', output_type: 'interview_scripts',
    version: 4, is_current: true, review_status: 'approved', created_at: '2026-08-01 10:00:00', file_path: 'scripts_v4.json' },
  { id: 2, agent_name: 'interaction_designer', output_type: 'interview_scripts',
    version: 3, is_current: false, review_status: 'approved', created_at: '2026-07-31 10:00:00', file_path: 'scripts_v3.json' },
  { id: 3, agent_name: 'interaction_designer', output_type: 'interview_scripts_l2_1',
    version: 1, is_current: true, review_status: 'approved', created_at: '2026-07-30 10:00:00', file_path: 'l2_1.json' },
  { id: 4, agent_name: 'interaction_designer', output_type: 'l1_interview_summaries',
    version: 1, is_current: true, review_status: 'approved', created_at: '2026-07-29 10:00:00', file_path: 'l1.json' },
]

function renderPanel(overrides: {
  crewKey?: string
  outputs?: AgentOutput[]
  initialTab?: string
} = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AgentDetailPanel
          slug="t"
          crewKey={overrides.crewKey ?? 'assessment_design'}
          crewRun={undefined}
          outputs={overrides.outputs ?? MAYA_OUTPUTS}
          logs={[]}
          isPipelineActive={false}
          initialTab={overrides.initialTab ?? 'output'}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => localStorage.clear())

describe('AgentDetailPanel - Output tab', () => {
  it("shows Maya's primary artefact rather than the empty state", async () => {
    renderPanel()
    expect(await screen.findByTestId('primary-output-interview_scripts')).toBeVisible()
    expect(screen.queryByTestId('no-primary-output')).not.toBeInTheDocument()
  })
})

describe('AgentDetailPanel - Status tab', () => {
  it("lists Maya's primary version history, which the panel's own filter used to empty", async () => {
    renderPanel({ initialTab: 'status' })
    expect(await screen.findByTestId('output-version-3')).toBeInTheDocument()
  })

  it('lists the script siblings rather than hiding them', async () => {
    // The spec's call: the twenty sibling types are an instruction-following defect to fix at
    // source, and showing them here is more honest than the rug the hiding prefix provided.
    renderPanel({ initialTab: 'status' })
    expect(await screen.findByTestId('output-type-interview_scripts_l2_1')).toBeInTheDocument()
  })

  it("still hides the summaries, which are not Maya's deliverable at all", async () => {
    renderPanel({ initialTab: 'status' })
    await screen.findByTestId('output-type-interview_scripts_l2_1')
    expect(screen.queryByTestId('output-type-l1_interview_summaries')).not.toBeInTheDocument()
  })
})
