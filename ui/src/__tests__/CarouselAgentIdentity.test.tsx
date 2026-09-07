// ui/src/__tests__/CarouselAgentIdentity.test.tsx
//
// **The assertion that would have caught the defect.**
//
// Patrick uploaded a portrait for Jordan on `sp-gs-am` on 7 September. The upload door
// downscaled and stored the file, `project_agent_config.image_url` recorded
// `/projects/sp-gs-am/agents/stakeholder_manager/image`, that URL served 200 - and every face on
// the dashboard was unchanged, because the carousel read a static map and nothing else did.
//
// This file is worth more than `useAgentIdentity.test.tsx` beside it, and the reason is the
// state the product was actually in: **the resolution can be perfect and unused.** Every layer
// below this one was already correct. A test of the hook alone passes against the bug exactly as
// shipped, because the bug was never in a resolution - it was in nine sites that never asked.
//
// So the assertions here are made on the `<img>` the carousel renders, from a component tree
// mounted the way the Dashboard mounts it, and the only thing standing between the mocked door
// and the rendered `src` is the production code path.
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import CrewCarousel from '../components/CrewCarousel'
import { agentConfigApi } from '../api/agentConfig'
import { AGENT_AVATAR_IMAGE } from '../components/agentStatus'
import type { AgentConfig, AgentConfigOverrides } from '../api/agentConfig'

vi.mock('../api/agentConfig', () => ({
  agentConfigApi: { getAll: vi.fn() },
}))

const SLUG = 'sp-gs-am'

// The address Patrick's row actually held, written out rather than assembled from parts so this
// test cannot agree with a defect in whatever builds it.
const JORDANS_PORTRAIT = '/projects/sp-gs-am/agents/stakeholder_manager/image'

const NO_OVERRIDES: AgentConfigOverrides = {
  display_name: null, image_url: null, voice_id: null,
  language: null, country_code: null, model_id: null,
}

function entry(agentId: string, overrides: Partial<AgentConfigOverrides> = {}): AgentConfig {
  const merged = { ...NO_OVERRIDES, ...overrides }
  const defaults = {
    display_name: 'Server Default', image_url: '/agents/server-default.jpg', voice_id: null,
    language: 'en', country_code: 'GB', model_id: 'eleven_turbo_v2',
  }
  return {
    agent_id: agentId,
    configured: Object.values(merged).some((v) => v !== null),
    defaults,
    overrides: merged,
    resolved: {
      ...defaults,
      ...Object.fromEntries(Object.entries(merged).filter(([, v]) => v !== null)),
    } as AgentConfig['resolved'],
    // Stipulated, not derived from the id: the roster of who interviews lives in one place in
    // Python. Nothing in these cases reads it.
    is_interviewer: false,
  }
}

function renderCarousel() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <CrewCarousel
          slug={SLUG}
          crewRuns={[]}
          isPipelineActive={false}
          logs={[]}
          hitlReviews={[]}
          selectedCrew="stakeholder_management"
          onSelectCrew={() => {}}
          onRunCrew={() => {}}
          onRerunCrew={() => {}}
          onRunPipeline={() => {}}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(agentConfigApi.getAll).mockReset()
})

describe('the carousel draws the project its faces belong to', () => {
  it("shows the portrait this project uploaded for Jordan, not the roll's", async () => {
    // The reported defect, at the site that reported it.
    vi.mocked(agentConfigApi.getAll).mockResolvedValue({
      agents: { stakeholder_manager: entry('stakeholder_manager', {
        image_url: JORDANS_PORTRAIT,
      }) },
    })

    renderCarousel()

    // By `alt`, which is the agent's first name, because the carousel renders nineteen faces
    // and this has to be *Jordan's*. `getAllByAltText` would let another agent's `<img>` satisfy
    // it, which is the mistake a single-image assertion invites on a screen full of images.
    await waitFor(() =>
      expect(screen.getByAltText('Jordan')).toHaveAttribute('src', JORDANS_PORTRAIT),
    )
  })

  it("still shows the roll's portrait for an agent this project has not configured", async () => {
    // The control, in the **same response** as the override above rather than in a separate
    // test with an empty roll - a component that read the configuration and lost the fallback
    // would pass the first test and break the other seventeen faces on the board, which is a
    // worse screen than the bug being fixed.
    vi.mocked(agentConfigApi.getAll).mockResolvedValue({
      agents: {
        stakeholder_manager: entry('stakeholder_manager', { image_url: JORDANS_PORTRAIT }),
        value_chain_mapper: entry('value_chain_mapper'),
      },
    })

    renderCarousel()

    await waitFor(() =>
      expect(screen.getByAltText('Jordan')).toHaveAttribute('src', JORDANS_PORTRAIT),
    )
    expect(screen.getByAltText('Alex')).toHaveAttribute(
      'src', AGENT_AVATAR_IMAGE['Value Chain Mapper'],
    )
  })

  it('uses the name this project gave the agent, on the face and on the label beneath it',
    async () => {
      // Both, because they are two reads in the component and were two separate static-map
      // lookups before. A rename that reached the portrait's `alt` and not the caption would
      // put one person's face under another person's name.
      //
      // The new **first** name has to differ from the old one. 'Jordan Okafor' was the first
      // spelling of this fixture and it made the test unfalsifiable: both halves render the
      // first name, so a component still reading `AGENT_HUMAN_NAME['Stakeholder Manager']`
      // produced 'Jordan' too and every assertion passed. It survived the power-check that
      // failed the four tests around it, which is how it was found.
      vi.mocked(agentConfigApi.getAll).mockResolvedValue({
        agents: { stakeholder_manager: entry('stakeholder_manager', {
          display_name: 'Robin Okafor',
        }) },
      })

      renderCarousel()

      await waitFor(() => expect(screen.getByAltText('Robin')).toBeInTheDocument())
      // The caption under a single-agent card is the first name.
      expect(screen.getByText('Robin')).toBeInTheDocument()
      expect(screen.queryByAltText('Jordan')).not.toBeInTheDocument()
    })

  it("draws the project's portrait for Pamela too, whose card is written separately", async () => {
    // PAM's card is not a `CrewCard` - it is `PamCard`, hand-written, and it held its own
    // `AGENT_AVATAR_IMAGE['PAM']` lookup. A sweep that replaced the shared face component and
    // stopped there would leave exactly this one behind, still on the static map, and every
    // other assertion in this file would pass.
    const PAMS_PORTRAIT = '/projects/sp-gs-am/agents/pam/image'
    vi.mocked(agentConfigApi.getAll).mockResolvedValue({
      agents: { pam: entry('pam', { image_url: PAMS_PORTRAIT }) },
    })

    renderCarousel()

    await waitFor(() =>
      expect(screen.getByAltText('Pamela')).toHaveAttribute('src', PAMS_PORTRAIT),
    )
  })

  it('renders initials rather than a broken image when a project clears a portrait', async () => {
    // `''` is the project saying "no portrait", and it must not be handed to an `<img src>`:
    // a browser resolves an empty `src` against the page and re-requests the document itself.
    vi.mocked(agentConfigApi.getAll).mockResolvedValue({
      agents: { stakeholder_manager: entry('stakeholder_manager', { image_url: '' }) },
    })

    renderCarousel()

    await waitFor(() => expect(screen.queryByAltText('Jordan')).not.toBeInTheDocument())
    expect(screen.getByText('JW')).toBeInTheDocument()
  })
})
