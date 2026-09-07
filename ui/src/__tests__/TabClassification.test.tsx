// ui/src/__tests__/TabClassification.test.tsx
//
// Each tab means one thing, stated as a property rather than as a comment.
//
// | Tab | What it holds |
// |-----|---------------|
// | Agents | who the agent is and how they behave |
// | Setup | how the engagement is configured |
// | Status | what the engagement is doing |
//
// Six panels were on the Agents tab because their components were named after agents -
// PamSetupTab, AlexSetupTab, MayaSetupTab, TaylorSetupTab, JordanSetupTab, AverySetupTab - and
// asked the question this file exists to keep asking (**if this agent were renamed or replaced,
// would this content move with them?**) five of them answered no.
//
// **Absence is the half that fails silently**, and it is harder here than it looks: the Output,
// Setup and Agents tabs are all rendered `hidden` rather than unmounted, so a screen-level
// `queryByText` finds content on an inactive tab and says nothing whatever about where it is.
// Every assertion below is scoped with `within` to the tab's own panel, and every one of them
// is made *after* all three tabs have been opened - the state a real reader reaches, and the
// only state in which the absence half can fail. Asserting absence on an unopened tab would
// pass against the mount latch instead of against the classification.
//
// The clock is pinned because the PMO crew's Setup tab mounts ProjectScheduleSetup, which
// reaches milestoneVariance - see milestoneClockDiscipline.test.ts.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, beforeEach, beforeAll, afterAll, vi } from 'vitest'

import AgentDetailPanel, {
  CREW_SETUP_SECTION, CREW_STATUS_SECTION,
} from '../components/AgentDetailPanel'
import { AGENT_SETUP_SECTION } from '../components/tabs/CrewAgentsTab'
import { CREW_AGENTS } from '../components/agentStatus'
import { milestonesApi, projectsApi, stakeholdersApi } from '../api/endpoints'

const FIXED_TODAY = new Date('2026-08-14T09:00:00Z')
beforeAll(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); vi.setSystemTime(FIXED_TODAY) })
afterAll(() => { vi.useRealTimers() })

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    token: 'test-token',
    user: { sub: 'classification-tester', role: 'reviewer', exp: 9999999999 },
    login: vi.fn(),
    logout: vi.fn(),
  }),
}))

vi.mock('../api/agentConfig', () => ({
  agentConfigApi: {
    get: vi.fn().mockResolvedValue(null),
    put: vi.fn(), uploadImage: vi.fn(),
    getAll: vi.fn().mockResolvedValue({ agents: {} }),
  },
}))

// Hoisted: `vi.mock`'s factory is lifted above every top-level binding in this file, so a
// plain const here is not yet initialised when the factory runs.
const { MILESTONES } = vi.hoisted(() => ({ MILESTONES: [
  { slug: 'acme', id: 1, milestone_key: 'project_initiation', title: 'Project initiation',
    description: '', notes: '', created_at: '2026-07-01', sort_order: 1,
    due_date: '2026-08-01', baseline_date: '2026-08-01', status: 'complete',
    completed_at: '2026-08-01' },
  { slug: 'acme', id: 2, milestone_key: 'discovery_docs', title: 'Discovery documents',
    description: '', notes: '', created_at: '2026-07-01', sort_order: 2,
    due_date: '2026-08-28', baseline_date: '2026-08-28', status: 'pending',
    completed_at: null },
] }))

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getSettings: vi.fn().mockResolvedValue({ locale: 'GB', standards_references: 'ISO 55001', disciplines: ['data'] }),
    // Resolved, not bare: the schedule infers a start date from the milestones on first
    // mount and calls `.catch` on the result, so `vi.fn()` alone crashes the whole panel.
    updateSettings: vi.fn().mockResolvedValue({}),
    getMyPermissions: vi.fn().mockResolvedValue({
      can_review: false, can_approve: false, can_grant_roles: false,
      can_issue_invite_links: false, can_change_platform_tier_settings: false,
      platform_tier_settings: [], can_administer_project: true, writable_knowledge_tiers: [],
    }),
    outputs: vi.fn().mockResolvedValue([]),
    documents: vi.fn().mockResolvedValue([]),
    listRuns: vi.fn().mockResolvedValue([]),
    getAssignment: vi.fn().mockResolvedValue({ assignments: [], stakeholders: [] }),
    getValueChainRegistry: vi.fn().mockResolvedValue({ schema_version: 1, activities: [] }),
    saveAssignment: vi.fn(),
    getOutputContent: vi.fn().mockResolvedValue({ content: '{}', output_type: 'json' }),
    getInterviewScripts: vi.fn().mockResolvedValue({}),
    getPamReport: vi.fn().mockResolvedValue(null),
    review: vi.fn(), revertOutput: vi.fn(),
  },
  valueChainApi: { get: vi.fn().mockResolvedValue({ model: null }), save: vi.fn(), migrate: vi.fn() },
  stakeholdersApi: {
    list: vi.fn().mockResolvedValue([
      { id: 1, name: 'Rhona Baird', job_title: 'Analyst', organisation: 'GS UK' },
    ]),
    importCsv: vi.fn(),
  },
  campaignsApi: { listReminderEmails: vi.fn().mockResolvedValue([]) },
  interviewsApi: { listSessions: vi.fn().mockResolvedValue({ sessions: [] }) },
  milestonesApi: {
    list: vi.fn().mockResolvedValue(MILESTONES),
    update: vi.fn().mockResolvedValue({}), remove: vi.fn(), create: vi.fn(), seed: vi.fn(),
  },
  nonworkingApi: { list: vi.fn().mockResolvedValue([]), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
  commitsApi: { readiness: vi.fn().mockResolvedValue({}) },
  // The PMO crew's Overview and Status both render PamReportView, and an unmocked export
  // means the panel does not render at all - which shows up as "no tab called Agents"
  // rather than as anything about the report.
  pamReportApi: { get: vi.fn().mockResolvedValue(null), send: vi.fn() },
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
    create: vi.fn(), update: vi.fn(), remove: vi.fn(), extract: vi.fn(), extractMany: vi.fn(),
  },
}))

// Production's own defaults, from main.tsx, and this matters for the request-count assertion:
// a client built per test with the library default `staleTime: 0` refetches whenever a second
// observer mounts, so the count would be about React Query rather than about the query key.
function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 5_000 } } })
}

function renderPanel(crewKey: string) {
  return render(
    <QueryClientProvider client={newClient()}>
      <MemoryRouter>
        <AgentDetailPanel
          slug="acme"
          crewKey={crewKey}
          crewRun={undefined}
          outputs={[]}
          logs={[]}
          isPipelineActive={false}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Open all three tabs, so nothing below can pass merely because a tab never mounted. */
async function openEveryTab(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => expect(projectsApi.getMyPermissions).toHaveBeenCalled())
  for (const name of ['Setup', 'Agents', 'Status'] as const) {
    await user.click(screen.getByRole('button', { name }))
  }
}

const setupTab  = () => screen.getByTestId('setup-tab-panel')
const statusTab = () => screen.getByTestId('status-tab-panel')
const agentsTab = () => screen.getByTestId('agents-tab-panel')

function sectionsIn(panel: HTMLElement): string[] {
  return [...panel.querySelectorAll('[data-panel-section]')]
    .map((el) => el.getAttribute('data-panel-section')!)
    .sort()
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

// ── Taylor: the two Patrick named ─────────────────────────────────────────────

describe("the interview crew's panels", () => {
  it('shows the stakeholder summary on Status and not on Agents', async () => {
    const user = userEvent.setup()
    renderPanel('discovery_interviews')
    await openEveryTab(user)

    expect(within(statusTab()).getByText(/Stakeholders ·/)).toBeInTheDocument()
    expect(within(agentsTab()).queryByText(/Stakeholders ·/)).toBeNull()
    expect(within(setupTab()).queryByText(/Stakeholders ·/)).toBeNull()
  })

  it('shows the invite rules on Setup and not on Agents', async () => {
    const user = userEvent.setup()
    renderPanel('discovery_interviews')
    await openEveryTab(user)

    expect(within(setupTab()).getByText('Interview Invite Rules')).toBeInTheDocument()
    expect(within(agentsTab()).queryByText('Interview Invite Rules')).toBeNull()
    expect(within(statusTab()).queryByText('Interview Invite Rules')).toBeNull()
  })

  it("keeps Avery's interviewing behaviour on Agents, where it belongs", async () => {
    // The one panel that survives the rename test, and the reason the test is a question
    // rather than a rule about component names: how firmly he presses is his, not the
    // project's. A version of this change that swept every bespoke panel off the tab would
    // pass every absence assertion above.
    const user = userEvent.setup()
    renderPanel('discovery_interviews')
    await openEveryTab(user)
    await user.click(screen.getByTestId('agent-selector-Stakeholder Interviewer'))

    expect(within(agentsTab()).getByText('Interview Style')).toBeInTheDocument()
    expect(within(setupTab()).queryByText('Interview Style')).toBeNull()
    expect(within(statusTab()).queryByText('Interview Style')).toBeNull()
  })
})

// ── The other four ────────────────────────────────────────────────────────────

describe('the value chain crew', () => {
  it('shows the research brief on Setup and not on Agents', async () => {
    const user = userEvent.setup()
    renderPanel('discovery_mapping')
    await openEveryTab(user)

    expect(within(setupTab()).getByText('Research Brief')).toBeInTheDocument()
    expect(within(agentsTab()).queryByText('Research Brief')).toBeNull()
  })
})

describe('the assessment design crew', () => {
  it('splits the disciplines onto Setup and the programme onto Status', async () => {
    const user = userEvent.setup()
    renderPanel('assessment_design')
    await openEveryTab(user)

    expect(within(setupTab()).getByText('Disciplines')).toBeInTheDocument()
    expect(within(statusTab()).queryByText('Disciplines')).toBeNull()
    expect(within(agentsTab()).queryByText('Disciplines')).toBeNull()

    expect(within(statusTab()).getByText('Interview Programme')).toBeInTheDocument()
    expect(within(setupTab()).queryByText('Interview Programme')).toBeNull()
    expect(within(agentsTab()).queryByText('Interview Programme')).toBeNull()
  })
})

describe('the stakeholder crew', () => {
  it('shows the value chain mapping on Setup and not on Agents', async () => {
    const user = userEvent.setup()
    renderPanel('stakeholder_management')
    await openEveryTab(user)

    expect(within(setupTab()).getByTestId('assignment-coverage')).toBeInTheDocument()
    expect(within(agentsTab()).queryByTestId('assignment-coverage')).toBeNull()
    expect(within(statusTab()).queryByTestId('assignment-coverage')).toBeNull()
  })
})

describe('the PMO crew', () => {
  it('splits the schedule onto Setup and its statistics onto Status', async () => {
    const user = userEvent.setup()
    renderPanel('PAM')
    await openEveryTab(user)

    // Editing the schedule is configuration.
    expect(within(setupTab()).getByText('Project start')).toBeInTheDocument()
    expect(within(setupTab()).getByText('Non-working periods')).toBeInTheDocument()
    expect(within(setupTab()).getByTestId('milestone-tick-1')).toBeInTheDocument()
    expect(within(statusTab()).queryByText('Project start')).toBeNull()
    expect(within(statusTab()).queryByTestId('milestone-tick-1')).toBeNull()

    // How it is going is not.
    expect(within(statusTab()).getByTestId('milestone-statistics')).toBeInTheDocument()
    expect(within(setupTab()).queryByTestId('milestone-statistics')).toBeNull()
    expect(within(agentsTab()).queryByTestId('milestone-statistics')).toBeNull()
  })

  it('reads the milestones once, however many tabs show them', async () => {
    // The schedule editor and the statistics are two views of one set of rows. Two query keys
    // would be a second request and, worse, two answers that can disagree while one is stale -
    // four complete on one tab and three on the other, with nothing to say which is right.
    // Counted rather than looked at: a duplicated fetch looks identical on screen.
    const user = userEvent.setup()
    renderPanel('PAM')
    await openEveryTab(user)
    await waitFor(() => expect(milestonesApi.list).toHaveBeenCalled())

    expect(vi.mocked(milestonesApi.list).mock.calls).toHaveLength(1)
  })
})

// ── The classification itself ─────────────────────────────────────────────────

/**
 * Every panel, and the tab it belongs on. `<tab>:<owner>` is what each renders as its
 * `data-panel-section`, so this is compared against what the DOM actually holds rather than
 * against the registries it was built from.
 */
const DECLARED: Record<string, { setup: string[]; status: string[]; agents: string[] }> = {
  PAM:                    { setup: ['setup:PAM'], status: ['status:PAM'], agents: [] },
  discovery_mapping:      { setup: ['setup:discovery_mapping'], status: [], agents: [] },
  assessment_design:      { setup: ['setup:assessment_design'], status: ['status:assessment_design'], agents: [] },
  requirements:           { setup: [], status: [], agents: [] },
  stakeholder_management: { setup: ['setup:stakeholder_management'], status: [], agents: [] },
  discovery_interviews:   {
    setup: ['setup:discovery_interviews'],
    status: ['status:discovery_interviews'],
    agents: ['agents:Stakeholder Interviewer'],
  },
  value_design:           { setup: [], status: [], agents: [] },
  capabilities:           { setup: [], status: [], agents: [] },
  delivery:               { setup: [], status: [], agents: [] },
  business_plan:          { setup: [], status: [], agents: [] },
}

describe('the classification, as a property', () => {
  it('covers every crew, so a new one cannot be left undeclared', () => {
    expect(Object.keys(DECLARED).sort()).toEqual(Object.keys(CREW_AGENTS).sort())
  })

  it.each(Object.keys(DECLARED))('holds exactly the declared panels on %s', async (crewKey) => {
    // Set equality per tab, not "is it there": a panel rendered on two tabs fails, a panel on
    // the wrong tab fails, and a seventh panel registered with no decision about which tab it
    // belongs on fails - which is what makes this a property rather than a list.
    const user = userEvent.setup()
    renderPanel(crewKey)
    await openEveryTab(user)

    const declared = DECLARED[crewKey]
    await waitFor(() => expect(sectionsIn(setupTab())).toEqual([...declared.setup].sort()))
    expect(sectionsIn(statusTab())).toEqual([...declared.status].sort())
    expect(sectionsIn(agentsTab())).toEqual([...declared.agents].sort())
  })

  it('registers agent-scoped panels against agents and crew-scoped panels against crews', () => {
    // The half the DOM cannot show. A crew key in AGENT_SETUP_SECTION is the confusion
    // CREW_SETUP_OVERRIDE made; an agent name in either crew map is the same mistake mirrored.
    const crewKeys = Object.keys(CREW_AGENTS)
    const agentNames = Object.values(CREW_AGENTS).flat()

    for (const key of Object.keys(AGENT_SETUP_SECTION)) expect(agentNames).toContain(key)
    for (const key of [...Object.keys(CREW_SETUP_SECTION), ...Object.keys(CREW_STATUS_SECTION)]) {
      expect(crewKeys).toContain(key)
    }
    // 'PAM' is both an agent and its own one-agent crew, so it is the one name that could
    // satisfy either test by accident. It is a crew key here and holds the project schedule.
    expect(AGENT_SETUP_SECTION['PAM']).toBeUndefined()
  })
})

describe('Agents holds nothing scoped to the engagement', () => {
  // The rename test read backwards: nothing on this tab may be something that stays put when
  // the agent is replaced.
  const ENGAGEMENT_CONTENT: [string, RegExp][] = [
    ['discovery_interviews', /Stakeholders ·/],
    ['discovery_interviews', /Interview Invite Rules/],
    ['discovery_mapping',    /Research Brief/],
    ['assessment_design',    /Disciplines/],
    ['assessment_design',    /Interview Programme/],
    ['stakeholder_management', /Who speaks for which value chain activity/],
    ['PAM',                  /Project start/],
  ]

  it.each(ENGAGEMENT_CONTENT)('keeps %s content off the Agents tab (%s)', async (crewKey, marker) => {
    const user = userEvent.setup()
    renderPanel(crewKey)
    await openEveryTab(user)

    // Present somewhere on the panel - so this cannot pass by the content having been deleted -
    // and absent from Agents.
    await waitFor(() => expect(screen.queryAllByText(marker).length).toBeGreaterThan(0))
    expect(within(agentsTab()).queryByText(marker)).toBeNull()
  })
})

describe('Setup holds nothing scoped to a person', () => {
  it.each(Object.keys(DECLARED))('holds no agent configuration on %s', async (crewKey) => {
    const user = userEvent.setup()
    renderPanel(crewKey)
    await openEveryTab(user)

    // The name, image, voice and synthesis model block, and any bespoke agent panel. Scoped,
    // because after Agents has been opened every one of them is in the document for good.
    expect(within(setupTab()).queryByTestId(/^agent-config-section-/)).toBeNull()
    expect(within(setupTab()).queryByTestId(/^setup-section-/)).toBeNull()
    expect(within(setupTab()).queryByTestId('agent-selector')).toBeNull()
  })

  it("holds none of Avery's interviewing behaviour", async () => {
    const user = userEvent.setup()
    renderPanel('discovery_interviews')
    await openEveryTab(user)
    await user.click(screen.getByTestId('agent-selector-Stakeholder Interviewer'))

    expect(within(setupTab()).queryByText('Follow-up Persistence')).toBeNull()
    expect(within(setupTab()).queryByText('Interviewing Guidance')).toBeNull()
  })
})

describe('Status holds nothing that configures the engagement', () => {
  // "Nothing editable" is the shorthand and it is very slightly too strong: the stakeholder
  // roster carries a CSV import, deliberately, because a roster is what the engagement *is*
  // and adding to it is not configuring how the engagement runs. What must never appear here
  // is a control that changes the configuration - a settings Save, a schedule date, a
  // discipline. Each marker below is a control that exists on some Setup tab.
  const CONFIGURATION_CONTROLS: [string, RegExp][] = [
    ['PAM',                  /Project start/],
    ['PAM',                  /Auto-assign milestone dates/],
    ['PAM',                  /Non-working periods/],
    ['assessment_design',    /Every interview section is tagged/],
    ['discovery_interviews', /Save Rules/],
    ['discovery_mapping',    /Research Brief/],
    ['stakeholder_management', /Save assignments/],
  ]

  it.each(CONFIGURATION_CONTROLS)('keeps %s configuration off Status (%s)', async (crewKey, marker) => {
    const user = userEvent.setup()
    renderPanel(crewKey)
    await openEveryTab(user)

    await waitFor(() => expect(within(setupTab()).queryAllByText(marker).length).toBeGreaterThan(0))
    expect(within(statusTab()).queryByText(marker)).toBeNull()
  })

  it('still lets the roster be added to, which is the declared exception', async () => {
    // Stated as a test rather than left as a comment, so the exception is a decision somebody
    // made rather than something that drifted in.
    const user = userEvent.setup()
    renderPanel('discovery_interviews')
    await openEveryTab(user)

    expect(within(statusTab()).getByText('Import CSV')).toBeInTheDocument()
    await waitFor(() => expect(stakeholdersApi.list).toHaveBeenCalled())
  })
})
