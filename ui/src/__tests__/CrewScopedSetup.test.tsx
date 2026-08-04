// ui/src/__tests__/CrewScopedSetup.test.tsx
//
// A Setup tab belongs to a crew, and a crew can hold several agents. When it holds one -
// Alex in discovery_mapping, Jordan in stakeholder_management - naming the tab after that
// agent reads as personal and happens to be right. When it holds three, whichever agent's
// name went on the tab was going to be wrong for the other two.
//
// That is how Taylor's invite chase rules came to be registered against Jordan's crew:
// TaylorSetupTab was CREW_SETUP_OVERRIDE['stakeholder_management']. One agent defining
// another's configuration, in a tab named for a third crew's member.
//
// So configuration is registered per AGENT and assembled per crew, in the crew's own agent
// order. Renaming the file fixes today's instance; keying on the agent fixes the class.
import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import { CrewSetupSections, AGENT_SETUP_SECTION } from '../components/tabs/CrewSetupSections'

function renderSections(crewKey: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CrewSetupSections crewKey={crewKey} slug="acme" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getSettings: vi.fn().mockResolvedValue({}),
    updateSettings: vi.fn().mockResolvedValue({}),
    outputs: vi.fn().mockResolvedValue([]),
  },
  stakeholdersApi: { list: vi.fn().mockResolvedValue([]) },
  campaignsApi: { listReminderEmails: vi.fn().mockResolvedValue([]) },
}))

describe('a crew-scoped Setup tab', () => {
  it('gives each agent that has configuration its own named section', () => {
    renderSections('discovery_interviews')
    // Both are in this crew. Neither owns the tab, so both are headed by their own agent.
    expect(screen.getByTestId('setup-section-Interview Coordinator')).toBeInTheDocument()
    expect(screen.getByTestId('setup-section-Stakeholder Interviewer')).toBeInTheDocument()
  })

  it("heads a section with the agent's name, so ownership is on the screen", () => {
    renderSections('discovery_interviews')
    const section = screen.getByTestId('setup-section-Interview Coordinator')
    expect(within(section).getByText(/Taylor Brooks/)).toBeInTheDocument()
  })

  it('does not put one crew\'s configuration under another crew', () => {
    // The defect. Taylor's chase rules were registered against stakeholder_management,
    // which is Jordan's crew and contains no interview coordinator at all.
    renderSections('stakeholder_management')
    expect(screen.queryByTestId('setup-section-Interview Coordinator')).toBeNull()
  })

  it('renders sections in the crew\'s own agent order', () => {
    // The order work happens in: coordinate, interview, synthesise. Alphabetical or
    // registration order would read as arbitrary to anyone following the process.
    renderSections('discovery_interviews')
    const rendered = screen.getAllByTestId(/^setup-section-/)
      .map((el) => el.getAttribute('data-testid'))
    expect(rendered).toEqual([
      'setup-section-Interview Coordinator',
      'setup-section-Stakeholder Interviewer',
    ])
  })

  it('renders nothing for a crew whose agents have no configuration', () => {
    // The caller falls back to its default in that case, so this must report emptiness
    // rather than render an empty shell that hides it.
    const { container } = renderSections('value_design')
    expect(container).toBeEmptyDOMElement()
  })

  it('registers every section against an agent, never against a crew', () => {
    // A crew key here would reintroduce exactly the confusion this replaces.
    const crewKeys = ['discovery_interviews', 'stakeholder_management', 'discovery_mapping']
    for (const key of Object.keys(AGENT_SETUP_SECTION)) {
      expect(crewKeys).not.toContain(key)
    }
  })
})
