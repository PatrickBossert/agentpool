// ui/src/__tests__/CrewScopedSetup.test.tsx
//
// Configuration belongs to an agent, and a crew can hold several. When it holds one - Alex in
// discovery_mapping, Jordan in stakeholder_management - naming a tab after that agent reads as
// personal and happens to be right. When it holds four, whichever agent's name went on the tab
// was going to be wrong for the other three.
//
// That is how Taylor's invite chase rules came to be registered against Jordan's crew:
// TaylorSetupTab was CREW_SETUP_OVERRIDE['stakeholder_management']. One agent defining
// another's configuration, in a tab named for a third crew's member.
//
// So configuration is registered per AGENT and assembled per crew, in the crew's own agent
// order. Renaming the file fixes today's instance; keying on the agent fixes the class.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import { CrewAgentsTab, AGENT_SETUP_SECTION } from '../components/tabs/CrewAgentsTab'

function renderAgents(crewKey: string, initialAgent?: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CrewAgentsTab crewKey={crewKey} slug="acme" initialAgent={initialAgent} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

vi.mock('../api/agentConfig', () => ({
  agentConfigApi: { get: vi.fn().mockResolvedValue(null), put: vi.fn(), uploadImage: vi.fn() },
}))

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getSettings: vi.fn().mockResolvedValue({}),
    updateSettings: vi.fn().mockResolvedValue({}),
    outputs: vi.fn().mockResolvedValue([]),
    // Jordan's section, which is a real section on stakeholder_management now. Left out,
    // its queries would throw inside react-query and the section below would be asserted
    // against a component that never got past its first render.
    getAssignment: vi.fn().mockResolvedValue({ assignments: [], stakeholders: [] }),
    getValueChainRegistry: vi.fn().mockResolvedValue({ schema_version: 1, activities: [] }),
    listRuns: vi.fn().mockResolvedValue([]),
    saveAssignment: vi.fn().mockResolvedValue({ saved: 0 }),
    getMyPermissions: vi.fn().mockResolvedValue({
      can_review: false, can_approve: false, can_grant_roles: false,
      can_issue_invite_links: false, can_change_platform_tier_settings: false,
      can_administer_project: true, platform_tier_settings: [], writable_knowledge_tiers: [],
    }),
  },
  stakeholdersApi: { list: vi.fn().mockResolvedValue([]) },
  campaignsApi: { listReminderEmails: vi.fn().mockResolvedValue([]) },
}))

describe('an agent-scoped Agents tab', () => {
  it('gives each agent that has bespoke configuration its own named section', () => {
    renderAgents('discovery_interviews')
    // Both are in this crew. Neither owns the tab, so both are headed by their own agent.
    expect(screen.getByTestId('setup-section-Interview Coordinator')).toBeInTheDocument()
    expect(screen.getByTestId('setup-section-Stakeholder Interviewer')).toBeInTheDocument()
  })

  it("heads an agent's block with their name, so ownership is on the screen", () => {
    renderAgents('discovery_interviews')
    const panel = screen.getByTestId('agent-panel-Interview Coordinator')
    expect(within(panel).getByText(/Taylor Brooks/)).toBeInTheDocument()
  })

  it("does not put one crew's configuration under another crew", () => {
    // The defect. Taylor's chase rules were registered against stakeholder_management,
    // which is Jordan's crew and contains no interview coordinator at all.
    renderAgents('stakeholder_management')
    expect(screen.queryByTestId('setup-section-Interview Coordinator')).toBeNull()
    // Jordan's own configuration is what belongs there, and does render.
    expect(screen.getByTestId('setup-section-Stakeholder Manager')).toBeInTheDocument()
  })

  it("renders sections in the crew's own agent order", () => {
    // The order work happens in: coordinate, interview, synthesise. Alphabetical or
    // registration order would read as arbitrary to anyone following the process.
    renderAgents('discovery_interviews')
    const rendered = screen.getAllByTestId(/^setup-section-/)
      .map((el) => el.getAttribute('data-testid'))
    expect(rendered).toEqual([
      'setup-section-Interview Coordinator',
      'setup-section-Stakeholder Interviewer',
    ])
  })

  it('still configures every agent of a crew whose agents have no bespoke section', () => {
    // The old assertion here was that the component rendered *nothing* for such a crew, so
    // the Setup tab could fall through to the crew's reads and produces. There is nothing to
    // fall through to now: name, image, voice and synthesis model belong to all eighteen
    // agents by the same rule, so a crew with no bespoke section still has two agents to
    // configure. Asserting emptiness here would now assert the tab was broken.
    renderAgents('value_design')
    expect(screen.queryByTestId(/^setup-section-/)).toBeNull()
    expect(screen.getByTestId('agent-panel-Value Proposition Generator')).toBeInTheDocument()
    expect(screen.getByTestId('agent-panel-Portfolio Manager')).toBeInTheDocument()
  })

  it('registers every section against an agent, never against a crew', () => {
    // A crew key here would reintroduce exactly the confusion this replaces. 'PAM' is
    // excluded from the comparison because it is genuinely both - the orchestrator is an
    // agent and its own one-agent crew - which is why the list is spelled out rather than
    // taken from CREW_AGENTS wholesale.
    const crewKeys = [
      'discovery_interviews', 'stakeholder_management', 'discovery_mapping',
      'assessment_design', 'requirements', 'value_design', 'capabilities',
      'delivery', 'business_plan',
    ]
    for (const key of Object.keys(AGENT_SETUP_SECTION)) {
      expect(crewKeys).not.toContain(key)
    }
  })
})

describe('one agent at a time', () => {
  it('shows the selected agent and keeps the rest mounted but out of sight', async () => {
    // Hidden, not unmounted: every block holds form state committed only by an explicit
    // Save, and a selector that unmounted would throw away a half-typed display name on the
    // way past. `getByTestId` ignores visibility, so both halves are asserted.
    const user = userEvent.setup()
    renderAgents('discovery_interviews')

    expect(screen.getByTestId('agent-panel-Interview Coordinator')).toBeVisible()
    expect(screen.getByTestId('agent-panel-Synthesis Analyst')).toBeInTheDocument()
    expect(screen.getByTestId('agent-panel-Synthesis Analyst')).not.toBeVisible()

    await user.click(screen.getByTestId('agent-selector-Synthesis Analyst'))

    expect(screen.getByTestId('agent-panel-Synthesis Analyst')).toBeVisible()
    expect(screen.getByTestId('agent-panel-Interview Coordinator')).not.toBeVisible()
  })

  it('offers no selector to a crew of one, whose heading already names them', () => {
    renderAgents('stakeholder_management')
    expect(screen.queryByTestId('agent-selector')).toBeNull()
    expect(screen.getByTestId('agent-panel-Stakeholder Manager')).toBeVisible()
  })
})
