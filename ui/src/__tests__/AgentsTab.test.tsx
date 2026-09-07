// ui/src/__tests__/AgentsTab.test.tsx
//
// The Agents tab: that the panel remembers it, that it opens on the right agent, and that
// Setup no longer holds anything agent-scoped.
//
// **The reload is the test that matters, not the render.** AgentDetailPanel used to state its
// tab list three times over - the `Tab` union, the `isTab` guard, and a chain of string
// comparisons in the saved-tab restore - plus the rendered row. A tab missing from the guard
// does not error: `isTab` simply refuses the saved value, the restore falls through to
// `output`, and the tab works perfectly until the reader reloads and then silently forgets
// where they were. Every rendering assertion in this repository would have stayed green. So
// the first test below goes through the restore, and the guard and the restore are now derived
// from one list.
//
// **Setup's absence is asserted, not only Agents' presence.** A test that checks the
// configuration renders under Agents passes just as happily with both tabs showing it, which
// is the state this split exists to end.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import AgentDetailPanel from '../components/AgentDetailPanel'
import { agentConfigApi } from '../api/agentConfig'
import { projectsApi, valueChainApi } from '../api/endpoints'

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    token: 'test-token',
    user: { sub: 'tabs-tester', role: 'reviewer', exp: 9999999999 },
    login: vi.fn(),
    logout: vi.fn(),
  }),
}))

vi.mock('../api/agentConfig', () => ({
  agentConfigApi: {
    get: vi.fn(), put: vi.fn(), uploadImage: vi.fn(),
    // Task 7: every face and name on the panel resolves through `useAgentIdentity`,
    // which reads this. An empty roll means the static map answers, which is what
    // these tests were written against.
    getAll: vi.fn().mockResolvedValue({ agents: {} }),
  },
}))

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getSettings: vi.fn().mockResolvedValue({}),
    updateSettings: vi.fn(),
    getMyPermissions: vi.fn().mockResolvedValue({
      can_review: false, can_approve: false, can_grant_roles: false,
      can_issue_invite_links: false, can_change_platform_tier_settings: false,
      platform_tier_settings: [], can_administer_project: true,
      writable_knowledge_tiers: [],
    }),
    outputs: vi.fn().mockResolvedValue([]),
    listRuns: vi.fn().mockResolvedValue([]),
    getAssignment: vi.fn().mockResolvedValue({ assignments: [], stakeholders: [] }),
    getValueChainRegistry: vi.fn().mockResolvedValue({ schema_version: 1, activities: [] }),
    saveAssignment: vi.fn(),
    getOutputContent: vi.fn().mockResolvedValue({ content: '{}', output_type: 'json' }),
    getInterviewScripts: vi.fn().mockResolvedValue({}),
    documents: vi.fn().mockResolvedValue([]),
    review: vi.fn(),
    revertOutput: vi.fn(),
  },
  valueChainApi: { get: vi.fn().mockResolvedValue({ model: null }), save: vi.fn(), migrate: vi.fn() },
  stakeholdersApi: { list: vi.fn().mockResolvedValue([]) },
  campaignsApi: { listReminderEmails: vi.fn().mockResolvedValue([]) },
  interviewsApi: { listSessions: vi.fn().mockResolvedValue({ sessions: [] }) },
  milestonesApi: { list: vi.fn().mockResolvedValue([]) },
  nonworkingApi: { list: vi.fn().mockResolvedValue([]) },
}))

vi.mock('../api/agentChat', () => ({
  agentChatApi: {
    getHistory: vi.fn().mockResolvedValue([]),
    clearHistory: vi.fn(), send: vi.fn(), uploadFile: vi.fn(),
  },
}))

vi.mock('../api/skills', () => ({
  skillsApi: {
    list: vi.fn().mockResolvedValue([]),
    create: vi.fn(), update: vi.fn(), remove: vi.fn(),
    extract: vi.fn(), extractMany: vi.fn(),
  },
}))

function config(agentId: string) {
  return {
    agent_id: agentId,
    configured: false,
    defaults: {
      display_name: 'Stub', image_url: null, voice_id: null,
      language: 'en', country_code: 'GB', model_id: 'eleven_turbo_v2',
    },
    overrides: {
      display_name: null, image_url: null, voice_id: null,
      language: null, country_code: null, model_id: null,
    },
    resolved: {
      display_name: 'Stub', image_url: null, voice_id: null,
      language: 'en', country_code: 'GB', model_id: 'eleven_turbo_v2',
    },
    // Stipulated, not derived from the id: the roster of who interviews lives in one place in
    // Python. Nothing in these cases reads it.
    is_interviewer: false,
  }
}

// The tab is saved per user, per project, per crew - the panel builds this key itself and a
// second spelling of it here would be a test of the test. Read from the panel's own rule.
const TAB_KEY = 'ap_panel_tab:tabs-tester:t:discovery_interviews'

function renderPanel(
  overrides: { crewKey?: string; initialTab?: string; initialAgent?: string } = {},
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AgentDetailPanel
          slug="t"
          crewKey={overrides.crewKey ?? 'discovery_interviews'}
          crewRun={undefined}
          outputs={[]}
          logs={[]}
          isPipelineActive={false}
          initialTab={overrides.initialTab}
          initialAgent={overrides.initialAgent}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  vi.mocked(agentConfigApi.get).mockImplementation(async (_slug: string, agentId: string) =>
    config(agentId),
  )
  vi.mocked(valueChainApi.get).mockResolvedValue({ model: null })
})

describe('the panel remembers the Agents tab', () => {
  it('is still the Agents tab after a reload', async () => {
    // Through the saved-tab restore, because that is the path a missing guard entry breaks.
    // Asserting the tab renders would pass against exactly the defect being prevented: an
    // `isTab` that does not know 'agents' still renders the tab, still lets it be clicked,
    // and only loses the reader's place on the next page load.
    localStorage.setItem(TAB_KEY, 'agents')
    renderPanel()

    expect(await screen.findByTestId('agents-tab-panel')).toBeVisible()
    // And the row agrees: a restore that silently fell back to output would leave the
    // Output tab marked active while the panel above still rendered something.
    expect(screen.getByTestId('active-tab-agents')).toBeInTheDocument()
  })

  it('saves the Agents tab when it is clicked, which is what the reload then reads', async () => {
    // The other half. A tab that is restored but never written is restored to nothing, and
    // a test seeding localStorage by hand cannot see that.
    const user = userEvent.setup()
    renderPanel({ initialTab: 'output' })

    await user.click(screen.getByRole('button', { name: 'Agents' }))

    expect(localStorage.getItem(TAB_KEY)).toBe('agents')
  })
})

describe('which agent the Agents tab opens on', () => {
  it('opens on the agent it was given, not on the first in the crew', async () => {
    // discovery_interviews is [Taylor, Avery, Laura, Casey] and Avery is asked for, so a
    // component that ignores the selection and one that honours it give different answers.
    // Asking for Taylor would be satisfied by both.
    renderPanel({ initialTab: 'agents', initialAgent: 'Stakeholder Interviewer' })

    expect(await screen.findByTestId('agent-panel-Stakeholder Interviewer')).toBeVisible()
    expect(screen.getByTestId('agent-panel-Interview Coordinator')).not.toBeVisible()
  })

  it('falls back to the first agent when it is given somebody outside this crew', async () => {
    // A stale selection must not leave the tab showing nobody at all.
    renderPanel({ initialTab: 'agents', initialAgent: 'Roadmap Generator' })

    expect(await screen.findByTestId('agent-panel-Interview Coordinator')).toBeVisible()
  })

  it('opens on the first agent when it is given nobody', async () => {
    renderPanel({ initialTab: 'agents' })

    expect(await screen.findByTestId('agent-panel-Interview Coordinator')).toBeVisible()
  })
})

describe('Setup keeps only what a crew owns', () => {
  it('renders no agent configuration under Setup', async () => {
    // The absence, asserted directly. Checking only that Agents holds the configuration
    // passes with both tabs showing it, which is the state this task exists to end.
    //
    // Scoped to the Setup panel rather than to the screen, which is not fussiness: a
    // screen-wide `queryByTestId` here passes for the wrong reason - the mount latch means
    // nothing agent-scoped is in the document at all until Agents has been opened - so it
    // would assert the latch and say nothing whatever about Setup. The pair below drives
    // that apart.
    renderPanel({ initialTab: 'setup' })

    const setup = await screen.findByTestId('setup-tab-panel')
    expect(setup).toBeVisible()
    expect(within(setup).queryByTestId(/^agent-config-section-/)).toBeNull()
    expect(within(setup).queryByTestId(/^setup-section-/)).toBeNull()
    expect(within(setup).queryByTestId('agent-selector')).toBeNull()
  })

  it('still renders none of it after Agents has been opened', async () => {
    // The state a real reader reaches, and the one the test above cannot see. The Agents tab
    // is rendered `hidden` rather than unmounted, so once it has been opened every agent's
    // configuration is in the document for the rest of the session - and an unscoped absence
    // assertion would fail here whether or not Setup had anything to do with it.
    const user = userEvent.setup()
    renderPanel({ initialTab: 'agents' })
    await screen.findByTestId('agent-config-section-Interview Coordinator')

    await user.click(screen.getByRole('button', { name: 'Setup' }))

    const setup = await screen.findByTestId('setup-tab-panel')
    expect(within(setup).queryByTestId(/^agent-config-section-/)).toBeNull()
    // And the configuration really is still mounted, so the assertion above is a statement
    // about where it is rather than about whether it exists.
    expect(screen.getByTestId('agent-config-section-Interview Coordinator')).toBeInTheDocument()
  })

  it('keeps the crew note, its reads and its produces', async () => {
    // The positive half: Setup was narrowed, not emptied.
    renderPanel({ initialTab: 'setup' })

    const setup = await screen.findByTestId('setup-tab-panel')
    expect(setup).toHaveTextContent('Reads')
    expect(setup).toHaveTextContent('Produces')
    expect(setup).toHaveTextContent('interview_transcripts.json')
  })

  it('asks the server for nothing when the panel opens on Output', async () => {
    // Setup is rendered `hidden` rather than unmounted now, because it holds forms whose
    // fields are React state - so without the latch, opening any panel on any tab would fetch
    // this crew's assignment mapping and, on the PMO crew, a whole schedule that nobody
    // asked to see. The same property AgentDetailPanelAgentsMount.test.tsx holds
    // for the Agents tab, on the tab that has just started paying for queries.
    renderPanel({ crewKey: 'stakeholder_management', initialTab: 'output' })
    await waitFor(() => expect(projectsApi.getMyPermissions).toHaveBeenCalled())

    expect(projectsApi.getAssignment).not.toHaveBeenCalled()
  })

  it('asks once Setup has been opened, and not again on the way back', async () => {
    // The other half, and the half a latch set in the tab's onClick would fail: it is
    // latched, never cleared, so a half-typed brief survives a trip to Output.
    const user = userEvent.setup()
    renderPanel({ crewKey: 'stakeholder_management', initialTab: 'output' })
    await waitFor(() => expect(projectsApi.getMyPermissions).toHaveBeenCalled())

    await user.click(screen.getByRole('button', { name: 'Setup' }))
    await waitFor(() => expect(projectsApi.getAssignment).toHaveBeenCalled())
    const firstPass = vi.mocked(projectsApi.getAssignment).mock.calls.length

    await user.click(screen.getByRole('button', { name: 'Output' }))
    await user.click(screen.getByRole('button', { name: 'Setup' }))

    expect(vi.mocked(projectsApi.getAssignment).mock.calls.length).toBe(firstPass)
    // Mounted throughout, which the count alone cannot tell from a component that unmounted
    // and was served from the query cache on the way back.
    expect(screen.getByTestId('assignment-coverage')).toBeInTheDocument()
  })

  it('renders the agent configuration under Agents instead', async () => {
    renderPanel({ initialTab: 'agents' })

    // By the permanent agent id, which is what the configuration door is keyed on.
    expect(await screen.findByTestId('agent-config-interview_coordinator')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('agent-config-section-Synthesis Analyst')).toBeInTheDocument(),
    )
  })
})

describe("an agent's bespoke section moves with the agent", () => {
  it("shows Avery's own settings on the Agents tab", async () => {
    // Avery's interviewing style is the one panel that survives the rename test: how firmly
    // he presses and how long he waits in a silence is how *he* conducts an interview, so it
    // moves with him. Every other bespoke panel was the engagement's and left.
    renderPanel({ crewKey: 'discovery_interviews', initialTab: 'agents',
                  initialAgent: 'Stakeholder Interviewer' })

    expect(await screen.findByTestId('setup-section-Stakeholder Interviewer')).toBeVisible()
  })

  it("leaves nothing of it on that crew's Setup tab", async () => {
    renderPanel({ crewKey: 'discovery_interviews', initialTab: 'setup' })

    const setup = await screen.findByTestId('setup-tab-panel')
    expect(within(setup).queryByTestId('setup-section-Stakeholder Interviewer')).toBeNull()
    expect(setup).toHaveTextContent('interview_transcripts.json')
  })

  it("keeps nothing of Maya's on the Agents tab, because none of it was hers", async () => {
    // MayaSetupTab was a whole-tab override, then an AGENT_SETUP_SECTION, and neither was
    // right: a project's disciplines and the eight-instrument programme are the engagement's,
    // and outlive any change of designer. Both halves are asserted below rather than only the
    // absence, so this cannot pass by the content having been lost altogether.
    renderPanel({ crewKey: 'assessment_design', initialTab: 'agents' })

    await screen.findByTestId('agent-config-section-Interaction Designer')
    expect(screen.queryByTestId('setup-section-Interaction Designer')).toBeNull()
  })
})
