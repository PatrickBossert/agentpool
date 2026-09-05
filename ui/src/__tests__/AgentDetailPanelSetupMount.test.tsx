// ui/src/__tests__/AgentDetailPanelSetupMount.test.tsx
//
// When the agent configuration section mounts, and when it does not.
//
// The Setup tab is rendered `hidden` rather than unmounted - deliberately, so a half-typed
// discovery brief survives a trip to Output - which means everything on it is mounted from the
// moment the panel opens. The configuration block therefore asks the server for **every agent
// in the crew** as soon as anybody opens any agent panel, on whatever tab, unless something
// stops it. `setupOpened` is that something.
//
// It is written here because the behaviour was correct and **held by nothing**: review drove
// the four cases below at 393a6c7f, found all four passing, and then confirmed that removing
// the latch entirely left 700 tests green and `tsc` clean. That is this branch's own recurring
// failure mode in the one shape the discipline does not name - not a test asserting one layer
// away from the property, but a correct property with no test at all.
//
// The third case is the one worth the file. The obvious implementation latches in the tab's
// `onClick` handler, which passes the first two cases and fails only on a panel that *opens* on
// Setup - a deep link from a notification, or the tab this browser last used. It is an effect on
// `tab` for exactly that reason.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import AgentDetailPanel from '../components/AgentDetailPanel'
import { agentConfigApi } from '../api/agentConfig'
import { projectsApi, valueChainApi } from '../api/endpoints'

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    token: 'test-token',
    user: { sub: 'mount-tester', role: 'reviewer', exp: 9999999999 },
    login: vi.fn(),
    logout: vi.fn(),
  }),
}))

vi.mock('../api/agentConfig', () => ({
  agentConfigApi: { get: vi.fn(), put: vi.fn() },
}))

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getSettings: vi.fn().mockResolvedValue({}),
    updateSettings: vi.fn(),
    getMyPermissions: vi.fn().mockResolvedValue({
      can_review: false,
      can_approve: false,
      can_grant_roles: false,
      can_issue_invite_links: false,
      can_change_platform_tier_settings: false,
      platform_tier_settings: [],
      can_administer_project: true,
      writable_knowledge_tiers: [],
    }),
    outputs: vi.fn().mockResolvedValue([]),
    listRuns: vi.fn().mockResolvedValue([]),
    getAssignment: vi.fn().mockResolvedValue({ assignments: [], stakeholders: [] }),
    getValueChainRegistry: vi.fn().mockResolvedValue({ schema_version: 1, activities: [] }),
    saveAssignment: vi.fn(),
  },
  valueChainApi: { get: vi.fn(), save: vi.fn() },
  stakeholdersApi: { list: vi.fn().mockResolvedValue([]) },
  campaignsApi: { listReminderEmails: vi.fn().mockResolvedValue([]) },
}))

vi.mock('../api/agentChat', () => ({
  agentChatApi: {
    getHistory: vi.fn().mockResolvedValue([]),
    clearHistory: vi.fn(),
    send: vi.fn(),
    uploadFile: vi.fn(),
  },
}))

vi.mock('../api/skills', () => ({
  skillsApi: {
    list: vi.fn().mockResolvedValue([]),
    create: vi.fn(), update: vi.fn(), remove: vi.fn(),
    extract: vi.fn(), extractMany: vi.fn(),
  },
}))

const CONFIG = {
  agent_id: 'value_chain_mapper',
  configured: false,
  defaults: {
    display_name: 'Alex Chen', image_url: null, voice_id: null,
    language: 'en', country_code: 'GB', model_id: 'eleven_turbo_v2',
  },
  overrides: {
    display_name: null, image_url: null, voice_id: null,
    language: null, country_code: null, model_id: null,
  },
  resolved: {
    display_name: 'Alex Chen', image_url: null, voice_id: null,
    language: 'en', country_code: 'GB', model_id: 'eleven_turbo_v2',
  },
}

// `discovery_mapping` holds two agents and takes a whole-tab CREW_SETUP_OVERRIDE, so it also
// proves the block renders *beside* an override rather than only where there is none.
function renderPanel(initialTab: 'output' | 'setup') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AgentDetailPanel
          slug="t"
          crewKey="discovery_mapping"
          crewRun={undefined}
          outputs={[]}
          logs={[]}
          isPipelineActive={false}
          initialTab={initialTab}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const tab = (name: string) => screen.getByRole('button', { name })

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  vi.mocked(agentConfigApi.get).mockResolvedValue(CONFIG)
  vi.mocked(valueChainApi.get).mockResolvedValue({ model: null })
  vi.mocked(projectsApi.getSettings).mockResolvedValue({} as never)
})

describe('the agent configuration block only mounts once Setup has been opened', () => {
  it('asks the server for nothing when the panel opens on Output', async () => {
    // The property the latch exists for. Without it, opening any agent panel fetches one
    // configuration per agent in the crew for a tab nobody looked at - and the Setup tab is
    // rendered `hidden`, not unmounted, so nothing on screen would show it happening.
    renderPanel('output')
    // Settle: the panel's own queries resolve, so "never called" is a real answer rather than
    // an assertion made before anything could have happened.
    await waitFor(() => expect(projectsApi.getMyPermissions).toHaveBeenCalled())
    expect(agentConfigApi.get).not.toHaveBeenCalled()
  })

  it('asks once Setup is opened, for every agent in the crew', async () => {
    const user = userEvent.setup()
    renderPanel('output')
    await waitFor(() => expect(projectsApi.getMyPermissions).toHaveBeenCalled())

    await user.click(tab('Setup'))

    // Both of discovery_mapping's agents, by their permanent ids - the bridge doing its job.
    await waitFor(() => {
      const asked = vi.mocked(agentConfigApi.get).mock.calls.map(([, agentId]) => agentId)
      expect(new Set(asked)).toEqual(new Set(['value_chain_mapper', 'value_lever_analyst']))
    })
  })

  it('asks when a deep link opens the panel straight onto Setup', async () => {
    // The case the obvious implementation gets wrong. Latching in the tab's onClick handler
    // passes both tests above and fails this one, and the panel can genuinely open here: a
    // notification deep link carries `tab=setup`, and the panel otherwise restores whichever
    // tab this browser last used.
    renderPanel('setup')
    await waitFor(() => expect(agentConfigApi.get).toHaveBeenCalled())
  })

  it('does not ask again when Setup is left and returned to', async () => {
    // The other half of the latch: it is set once and never cleared, so the block stays
    // mounted and a half-typed display name survives a trip to Output exactly as the rest of
    // the tab's form state does. A latch that cleared on leaving would satisfy the first three
    // tests and quietly throw away the edit.
    const user = userEvent.setup()
    renderPanel('setup')
    await waitFor(() => expect(agentConfigApi.get).toHaveBeenCalled())
    const firstPass = vi.mocked(agentConfigApi.get).mock.calls.length

    await user.click(tab('Output'))
    await user.click(tab('Setup'))

    expect(vi.mocked(agentConfigApi.get).mock.calls.length).toBe(firstPass)
    // Mounted throughout, which is the thing the count alone cannot distinguish from a
    // component that unmounted and was served from the query cache on the way back.
    expect(screen.getByTestId('agent-config-value_chain_mapper')).toBeInTheDocument()
  })
})
