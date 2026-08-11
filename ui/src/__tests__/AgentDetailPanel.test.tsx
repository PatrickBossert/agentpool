// ui/src/__tests__/AgentDetailPanel.test.tsx
//
// The panel itself, not its tab components in isolation.
//
// AgentOutputTab.test.tsx and AgentStatusTab.test.tsx both hand their child a fixture array
// they built themselves, so neither can see what the panel does to that array on the way in -
// and the panel's own filtering is where Maya's entire Output tab went missing. Every
// assertion here therefore mounts AgentDetailPanel and reads what a user would actually see.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import AgentDetailPanel from '../components/AgentDetailPanel'
import { valueChainApi } from '../api/endpoints'
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
    getSettings: vi.fn().mockResolvedValue({}),
    updateSettings: vi.fn(),
    documents: vi.fn().mockResolvedValue([]),
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

// Alex's fixture: the value chain model that only the panel can put in front of the Status
// tab, plus a primary output row so the crew is not in its empty state.
const ALEX_MODEL = {
  model_version: 1,
  parties: [{ id: 'p1' }],
  segments: [{ id: 's1' }, { id: 's2' }, { id: 's3' }],
  activities: new Array(17).fill(0).map((_, i) => ({ id: `a${i}` })),
  contributions: new Array(17).fill(0).map((_, i) => ({ activity_id: `a${i}` })),
  tasks: new Array(59).fill(0).map((_, i) => ({ id: `t${i}` })),
  propositions: [],
  links: [],
}

const ALEX_OUTPUTS: AgentOutput[] = [
  { id: 10, agent_name: 'value_chain_mapper', output_type: 'value_chain_model',
    version: 2, is_current: true, review_status: 'approved', created_at: '2026-08-01 10:00:00', file_path: 'model_v2.json' },
]

beforeEach(() => {
  localStorage.clear()
  vi.mocked(valueChainApi.get).mockResolvedValue({ model: null })
})

describe('AgentDetailPanel - Output tab', () => {
  it("shows Maya's primary artefact rather than the empty state", async () => {
    renderPanel()
    expect(await screen.findByTestId('primary-output-interview_scripts')).toBeVisible()
    expect(screen.queryByTestId('no-primary-output')).not.toBeInTheDocument()
  })
})

describe('AgentDetailPanel - the Output branch is hidden, not unmounted', () => {
  // getByTestId ignores visibility, so every assertion that only reaches for the Output
  // content would stay green if `hidden={tab !== 'output'}` were inverted - the tab would
  // render nothing at all and 245 tests would say nothing. Both halves are needed: asserting
  // only that it is visible on Output would pass if the attribute were dropped entirely.
  it('shows the Output content while the Output tab is selected', async () => {
    renderPanel({ initialTab: 'output' })
    expect(await screen.findByTestId('primary-output-interview_scripts')).toBeVisible()
  })

  it('keeps it mounted but out of sight while another tab is selected', async () => {
    renderPanel({ initialTab: 'status' })
    const output = await screen.findByTestId('primary-output-interview_scripts')
    expect(output).toBeInTheDocument()
    expect(output).not.toBeVisible()
  })
})

describe('AgentDetailPanel - the empty state', () => {
  it('stays away when the crew has an extra panel to show instead', async () => {
    // The old condition was `crewOutputs.length === 0 && !CREW_OUTPUT_EXTRA[crewKey]`; the
    // second clause was lost in the move. Without it the three crews with an extra render
    // "No outputs yet / Run this crew to see results here" directly above a populated panel.
    // discovery_interviews has AveryOutputExtra and no output row of its primary type here.
    renderPanel({ crewKey: 'discovery_interviews', outputs: [] })
    expect(await screen.findByTestId('selected-crew-discovery_interviews')).toBeInTheDocument()
    expect(screen.queryByTestId('no-primary-output')).not.toBeInTheDocument()
  })

  it('still appears for a crew with nothing at all to show', async () => {
    // The negative half: 'capabilities' has neither an editor nor an extra, so suppressing
    // the empty state everywhere would not satisfy this.
    renderPanel({ crewKey: 'capabilities', outputs: [] })
    expect(await screen.findByTestId('no-primary-output')).toBeVisible()
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

  // Driven through the panel deliberately. AgentStatusTab's own test supplies primaryModel
  // itself, so it stayed green while no production caller ever passed the prop - the summary
  // card, the prop and its counts type were all unreachable.
  it("summarises Alex's value chain model, which only the panel can supply", async () => {
    vi.mocked(valueChainApi.get).mockResolvedValue({ model: ALEX_MODEL })
    renderPanel({ crewKey: 'discovery_mapping', outputs: ALEX_OUTPUTS, initialTab: 'status' })

    const card = await screen.findByTestId('output-summary')
    expect(card).toHaveTextContent('3 segments')
    expect(card).toHaveTextContent('17 activities')
    expect(card).toHaveTextContent('17 contributions')
    expect(card).toHaveTextContent('59 tasks')
  })

  it('shows no summary card for a crew whose primary is not a countable model', async () => {
    // The card is Alex's alone until another crew's artefact grows counts of its own; without
    // this, passing every crew the value chain model would satisfy the test above.
    vi.mocked(valueChainApi.get).mockResolvedValue({ model: ALEX_MODEL })
    renderPanel({ initialTab: 'status' })
    await screen.findByTestId('output-version-3')
    expect(screen.queryByTestId('output-summary')).not.toBeInTheDocument()
  })
})

describe('AgentDetailPanel - the Output tab badge', () => {
  it('counts distinct artefacts, not versions', async () => {
    // Thirteen versions of one artefact is not thirteen outputs - it read as a count of
    // interviews sitting one below the sixteen the tab listed.
    const outputs: AgentOutput[] = Array.from({ length: 13 }, (_, i) => ({
      id: i + 1,
      agent_name: 'interaction_designer',
      output_type: 'interview_scripts',
      version: i + 1,
      is_current: i === 12,
      review_status: 'approved',
      created_at: `2026-08-${String(i + 1).padStart(2, '0')} 10:00:00`,
      file_path: `scripts_v${i + 1}.json`,
    }))
    renderPanel({ outputs })

    expect(screen.queryByText('13')).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /^Output\s*1$/ })).toBeInTheDocument()
  })
})

describe('AgentDetailPanel - unsaved work across a tab change', () => {
  // beforeunload does not fire on an in-panel tab change, so a tab that holds a draft and is
  // rendered conditionally loses it the moment another tab is clicked, silently and with no
  // warning. Alex's Setup holds ten pieces of form state committed only by an explicit Save;
  // Avery's and Taylor's do the same.
  it('keeps a typed Setup brief when the user visits Output and comes back', async () => {
    const user = userEvent.setup()
    renderPanel({ crewKey: 'discovery_mapping', outputs: ALEX_OUTPUTS, initialTab: 'setup' })

    const brief = await screen.findByPlaceholderText(/The client operates primarily/i)
    await user.type(brief, 'Focus on depot operations')

    // The Output tab's label carries a count badge, so its accessible name is "Output 1".
    await user.click(screen.getByRole('button', { name: /^Output/ }))
    await user.click(screen.getByRole('button', { name: /^Setup$/ }))

    expect(await screen.findByPlaceholderText(/The client operates primarily/i))
      .toHaveValue('Focus on depot operations')
  })
})
