// ui/src/__tests__/CarouselFaceMovesAgentsTab.test.tsx
//
// Clicking an agent's face moves the Agents tab to that agent - driven the whole way, from
// the carousel through Dashboard's state to what the tab renders.
//
// **This is the join, and it is the thing neither neighbouring test could see.**
// `CrewCarouselAgentSelect.test.tsx` asserts the carousel *reports* the agent whose face was
// clicked; `AgentsTab.test.tsx` asserts the tab *opens on* the agent it is handed. Both were
// true and both stayed true while the behaviour between them did nothing at all - the exact
// "one layer either side of the property" shape CLAUDE.md catalogues. Two defects lived in
// that gap:
//
//  1. A face click bubbles to the card, deliberately, so `onSelectAgent` and `onSelectCrew`
//     both fire. Dashboard's crew handler cleared the agent unconditionally, so the agent it
//     had just been given was thrown away in the same event and the tab opened on the crew's
//     first agent every time.
//  2. `CrewAgentsTab` consumed `initialAgent` only in a `useState` initialiser, which runs
//     once per `crewKey` - so a second face on the same crew changed a prop nothing re-read.
//
// So every case below clicks a face that is **not** first in its crew, and the second click
// stays inside the crew the first one selected. `discovery_interviews` is [Interview
// Coordinator, Stakeholder Interviewer, Second Interviewer, Synthesis Analyst]; Taylor is
// never the agent under assertion, because "opened on the first" and "opened on the one I
// clicked" are the same screen whenever you click the first.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import Dashboard from '../pages/Dashboard'

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    token: 'test-token',
    user: { sub: 'face-clicker', role: 'reviewer', exp: 9999999999 },
    login: vi.fn(),
    logout: vi.fn(),
  }),
}))

// No socket: this test is about a click and a render, and a live handshake attempt is noise
// the assertions cannot be affected by but the console can.
vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: () => [] }))

vi.mock('../api/agentConfig', () => ({
  agentConfigApi: {
    get: vi.fn(), put: vi.fn(), uploadImage: vi.fn(),
    // An empty roll, so the static names and faces answer - which is what the titles below
    // are written against - and so nothing here reaches the network.
    getAll: vi.fn().mockResolvedValue({ agents: {} }),
  },
}))

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    status: vi.fn().mockResolvedValue({
      project_slug: 'acme-rail', project_status: 'created', crew_runs: [],
    }),
    outputs: vi.fn().mockResolvedValue([]),
    listReviews: vi.fn().mockResolvedValue([]),
    deleteReview: vi.fn(),
    getSettings: vi.fn().mockResolvedValue({}),
    updateSettings: vi.fn(),
    orchestrate: vi.fn(),
    runCrew: vi.fn(),
    getMyPermissions: vi.fn().mockResolvedValue({
      can_review: false, can_approve: false, can_grant_roles: false,
      can_issue_invite_links: false, can_change_platform_tier_settings: false,
      platform_tier_settings: [], can_administer_project: true,
      writable_knowledge_tiers: [],
    }),
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
  milestonesApi: { list: vi.fn().mockResolvedValue([]) },
  commitsApi: { readiness: vi.fn().mockResolvedValue({}) },
  valueChainApi: { get: vi.fn().mockResolvedValue({ model: null }), save: vi.fn(), migrate: vi.fn() },
  stakeholdersApi: { list: vi.fn().mockResolvedValue([]) },
  campaignsApi: { listReminderEmails: vi.fn().mockResolvedValue([]) },
  interviewsApi: { listSessions: vi.fn().mockResolvedValue({ sessions: [] }) },
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

function renderDashboard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/acme-rail']}>
        <Routes>
          <Route path="/:slug" element={<Dashboard />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
})

/** The panel showing exactly this agent, with every other one of the crew's hidden. */
async function expectAgentsTabShows(agent: string, notAgent: string) {
  await waitFor(() => expect(screen.getByTestId(`agent-panel-${agent}`)).toBeVisible())
  expect(screen.getByTestId(`agent-panel-${notAgent}`)).not.toBeVisible()
  // And the selector agrees. A panel made visible without the chip following it would leave
  // the reader looking at Laura under a row that says Avery is selected.
  expect(screen.getByTestId(`agent-selector-${agent}`)).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByTestId(`agent-selector-${notAgent}`)).toHaveAttribute('aria-pressed', 'false')
}

describe("clicking an agent's face moves the Agents tab to that agent", () => {
  it('opens on the face that was clicked, not on the crew first agent', async () => {
    // Defect 1, driven end to end: the bubbling crew selection used to clear the agent in the
    // same event, so this opened on Taylor however deliberately Avery had been clicked.
    const user = userEvent.setup()
    renderDashboard()

    await user.click(await screen.findByTitle('Configure Avery Singh'))
    await user.click(screen.getByRole('button', { name: 'Agents' }))

    await expectAgentsTabShows('Stakeholder Interviewer', 'Interview Coordinator')
  })

  it('moves to a second face clicked while the tab is already open', async () => {
    // Defect 2, and the finding this file exists for. The tab is open on Avery, and Laura's
    // face is clicked on the same card - the same crew, so nothing remounts and a `useState`
    // initialiser never runs again.
    const user = userEvent.setup()
    renderDashboard()

    await user.click(await screen.findByTitle('Configure Avery Singh'))
    await user.click(screen.getByRole('button', { name: 'Agents' }))
    await expectAgentsTabShows('Stakeholder Interviewer', 'Interview Coordinator')

    await user.click(screen.getByTitle('Configure Laura Nelson'))

    await expectAgentsTabShows('Second Interviewer', 'Stakeholder Interviewer')
  })

  it("comes back to a face after the tab's own selector has moved elsewhere", async () => {
    // The third click, and the one a fix confined to the carousel cannot serve. Once the chips
    // have moved the tab, the agent the carousel is still holding and the agent on show are
    // different - so clicking the held agent's face is not a change of prop, and only the tab
    // reporting its own selection back makes it one.
    const user = userEvent.setup()
    renderDashboard()

    await user.click(await screen.findByTitle('Configure Avery Singh'))
    await user.click(screen.getByRole('button', { name: 'Agents' }))
    await expectAgentsTabShows('Stakeholder Interviewer', 'Interview Coordinator')

    await user.click(screen.getByTestId('agent-selector-Second Interviewer'))
    await expectAgentsTabShows('Second Interviewer', 'Stakeholder Interviewer')

    await user.click(screen.getByTitle('Configure Avery Singh'))

    await expectAgentsTabShows('Stakeholder Interviewer', 'Second Interviewer')
  })

  it('leaves the reader on the tab they were on, rather than hijacking it', async () => {
    // The other half of the promise, and the half a fix reaching for `setTab('agents')` would
    // quietly break: a face click says *whose* panel, never *which tab*. A reader on Output
    // who clicks a face to select a crew stays on Output.
    const user = userEvent.setup()
    renderDashboard()

    await user.click(await screen.findByTitle('Configure Avery Singh'))

    await waitFor(() => expect(screen.getByTestId('active-tab-output')).toBeInTheDocument())
    expect(screen.getByTestId('agents-tab-panel')).not.toBeVisible()
  })
})
