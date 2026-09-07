// ui/src/__tests__/useAgentIdentity.test.tsx
//
// The hook that resolves an agent's name and face for one project.
//
// **Both arms, always.** A hook that ignored the configuration entirely passes every fallback
// test, and a hook that ignored the fallback passes every override test - and the product's
// actual state on 7 September was the first of those: the configuration was written, stored and
// served, and nothing drew it. So each property below is asserted with an agent that *has* an
// override and an agent that has none, in the same render.
//
// This file is deliberately not the load-bearing test of this task. `CarouselAgentIdentity.
// test.tsx` is, because a hook can be perfect and unused.
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { useAgentIdentity } from '../hooks/useAgentIdentity'
import { agentConfigApi } from '../api/agentConfig'
import { AGENT_AVATAR_IMAGE, AGENT_HUMAN_NAME } from '../components/agentStatus'
import type { AgentConfig, AgentConfigOverrides } from '../api/agentConfig'

vi.mock('../api/agentConfig', () => ({
  agentConfigApi: { getAll: vi.fn() },
}))

// The address the upload door answers. Written out rather than derived, so this cannot agree
// with a defect in whatever builds it.
const JORDANS_PORTRAIT = '/projects/sp-gs-am/agents/stakeholder_manager/image'

const NO_OVERRIDES: AgentConfigOverrides = {
  display_name: null, image_url: null, voice_id: null,
  language: null, country_code: null, model_id: null,
}

// A portrait promoted for the whole deployment - level 2, served from its own door. Written out
// rather than assembled, and **nothing in the production code may key on the `/api/` prefix**:
// the server names this level in a field of its own, which is what makes the hook's fallback a
// read rather than a rule restated in TypeScript.
const PROMOTED_PORTRAIT = '/api/agents/value_chain_mapper/image'

function entry(
  agentId: string,
  overrides: Partial<AgentConfigOverrides> = {},
  promotedDefaultImageUrl: string | null = null,
): AgentConfig {
  const merged = { ...NO_OVERRIDES, ...overrides }
  const defaults = {
    display_name: 'Default Name',
    // Folded, exactly as `agent_defaults` folds it on the wire: a promoted default *is* the
    // agent's default image. So a hook reading `defaults.image_url` would pass the promotion
    // test below and break the other seventeen agents, which is what the control catches.
    image_url: promotedDefaultImageUrl ?? '/agents/default.jpg',
    voice_id: null,
    language: 'en',
    country_code: 'GB',
    model_id: 'eleven_turbo_v2',
  }
  return {
    agent_id: agentId,
    configured: Object.values(merged).some((v) => v !== null),
    defaults,
    overrides: merged,
    // Deliberately the server's rule - NULL means the default, `''` does not - so a hook that
    // wrongly read `resolved` instead of `overrides` would render `/agents/default.jpg`, an
    // address that 404s under the `/dashboard` base, and this file would say so.
    resolved: {
      ...defaults,
      ...Object.fromEntries(Object.entries(merged).filter(([, v]) => v !== null)),
    } as AgentConfig['resolved'],
    // Stipulated, not derived from the id: the roster of who interviews lives in one place in
    // Python. Nothing in these cases reads it.
    is_interviewer: false,
    promoted_default_image_url: promotedDefaultImageUrl,
  }
}

/** A probe that renders one agent's resolved identity, so the hook is driven as React runs it. */
function Probe({ slug, agents }: { slug?: string; agents: string[] }) {
  const identity = useAgentIdentity(slug)
  return (
    <ul>
      {agents.map((agent) => {
        const { name, imageUrl } = identity(agent)
        return (
          <li key={agent} data-testid={agent}>
            <span data-testid={`${agent}-name`}>{name}</span>
            {/* Three outcomes, three distinguishable strings. An address, a portrait this
                project cleared, and no portrait at all are different answers, and rendering
                the raw value would print the first as itself and the other two as nothing -
                so an assertion about clearing would pass against a hook that returned null. */}
            <span data-testid={`${agent}-image`}>
              {imageUrl === null ? '(null)' : imageUrl === '' ? '(cleared)' : imageUrl}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

/** Render the probe. `slug` has **no default**, deliberately: a default parameter is applied to
 *  an explicitly passed `undefined` too, so `renderProbe([...], undefined)` would silently have
 *  run with a slug and the no-project test would have asserted nothing. It did, once. */
function renderProbe(agents: string[], slug?: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <Probe slug={slug} agents={agents} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(agentConfigApi.getAll).mockReset()
})

describe('useAgentIdentity', () => {
  it('draws the configured portrait for an agent with one, and the static map for one without',
    async () => {
      // Both in a single response, so neither arm can be satisfied by a hook that ignores the
      // other. Jordan is the reported defect; Alex is the control beside him.
      vi.mocked(agentConfigApi.getAll).mockResolvedValue({
        agents: {
          stakeholder_manager: entry('stakeholder_manager', { image_url: JORDANS_PORTRAIT }),
          value_chain_mapper: entry('value_chain_mapper'),
        },
      })

      renderProbe(['Stakeholder Manager', 'Value Chain Mapper'], 'sp-gs-am')

      await waitFor(() =>
        expect(screen.getByTestId('Stakeholder Manager-image')).toHaveTextContent(
          JORDANS_PORTRAIT,
        ),
      )
      expect(screen.getByTestId('Value Chain Mapper-image')).toHaveTextContent(
        AGENT_AVATAR_IMAGE['Value Chain Mapper'],
      )
    })

  it('uses the configured name for an agent that has one, and the static map for one that has not',
    async () => {
      vi.mocked(agentConfigApi.getAll).mockResolvedValue({
        agents: {
          stakeholder_manager: entry('stakeholder_manager', { display_name: 'Jordan Okafor' }),
          value_chain_mapper: entry('value_chain_mapper'),
        },
      })

      renderProbe(['Stakeholder Manager', 'Value Chain Mapper'], 'sp-gs-am')

      await waitFor(() =>
        expect(screen.getByTestId('Stakeholder Manager-name')).toHaveTextContent('Jordan Okafor'),
      )
      expect(screen.getByTestId('Value Chain Mapper-name')).toHaveTextContent(
        AGENT_HUMAN_NAME['Value Chain Mapper'],
      )
    })

  it('never renders the resolved default address, which would 404 under the dashboard base',
    async () => {
      // The single most plausible wrong implementation: read `resolved` because it is the field
      // named "the one over the other". It is right about the *rule* and wrong about the
      // *address* - `AGENT_IDENTITY` stores `/agents/alex-chen.jpg` while Vite serves
      // `ui/public` under `/dashboard` - so it would break every agent with no override while
      // fixing the one that reported the bug.
      //
      // **Jordan is in the response only as a clock.** Without him this test asserted the
      // pre-load state: the hook answers the static map before the request returns, so
      // `waitFor` was satisfied on its first attempt and the test finished before the data it
      // was about ever arrived. It passed against the very mutation it exists to catch, and was
      // found by power-checking rather than by reading. Waiting for an override to land is the
      // only thing here that proves the response was applied at all.
      vi.mocked(agentConfigApi.getAll).mockResolvedValue({
        agents: {
          stakeholder_manager: entry('stakeholder_manager', { image_url: JORDANS_PORTRAIT }),
          value_chain_mapper: entry('value_chain_mapper'),
        },
      })

      renderProbe(['Stakeholder Manager', 'Value Chain Mapper'], 'sp-gs-am')

      await waitFor(() =>
        expect(screen.getByTestId('Stakeholder Manager-image')).toHaveTextContent(
          JORDANS_PORTRAIT,
        ),
      )
      expect(screen.getByTestId('Value Chain Mapper-image')).toHaveTextContent(
        AGENT_AVATAR_IMAGE['Value Chain Mapper'],
      )
      expect(screen.getByTestId('Value Chain Mapper-image')).not.toHaveTextContent(
        '/agents/default.jpg',
      )
    })

  it('draws a promoted deployment default over the static map, and only where there is one',
    async () => {
      // Level 2 over level 3. Alex carries a promotion and Jordan does not, in the same
      // response, because the wrong repair for this - reading `defaults.image_url`
      // unconditionally - draws Alex correctly and gives Jordan `/agents/default.jpg`, an
      // address that 404s under the `/dashboard` base.
      vi.mocked(agentConfigApi.getAll).mockResolvedValue({
        agents: {
          value_chain_mapper: entry('value_chain_mapper', {}, PROMOTED_PORTRAIT),
          stakeholder_manager: entry('stakeholder_manager'),
        },
      })

      renderProbe(['Value Chain Mapper', 'Stakeholder Manager'], 'sp-gs-am')

      await waitFor(() =>
        expect(screen.getByTestId('Value Chain Mapper-image')).toHaveTextContent(
          PROMOTED_PORTRAIT,
        ),
      )
      expect(screen.getByTestId('Stakeholder Manager-image')).toHaveTextContent(
        AGENT_AVATAR_IMAGE['Stakeholder Manager'],
      )
    })

  it("draws this project's own portrait over a promoted deployment default", async () => {
    // Level 1 over level 2. Without it, a hook that consulted the promotion first would pass
    // the test above while ignoring the portrait an administrator uploaded onto this
    // engagement - which is the reported defect again, wearing the repair as a disguise.
    vi.mocked(agentConfigApi.getAll).mockResolvedValue({
      agents: {
        value_chain_mapper: entry(
          'value_chain_mapper', { image_url: JORDANS_PORTRAIT }, PROMOTED_PORTRAIT,
        ),
      },
    })

    renderProbe(['Value Chain Mapper'], 'sp-gs-am')

    await waitFor(() =>
      expect(screen.getByTestId('Value Chain Mapper-image')).toHaveTextContent(
        JORDANS_PORTRAIT,
      ),
    )
  })

  it('treats a cleared portrait as cleared even when a promoted default exists', async () => {
    // `''` beats level 2 as decisively as it beats level 3, and it is the only input that can
    // tell `??` from `||` here: with `||`, the deployment's face would be reinstated over a
    // decision this project made.
    vi.mocked(agentConfigApi.getAll).mockResolvedValue({
      agents: {
        value_chain_mapper: entry('value_chain_mapper', { image_url: '' }, PROMOTED_PORTRAIT),
      },
    })

    renderProbe(['Value Chain Mapper'], 'sp-gs-am')

    await waitFor(() =>
      expect(screen.getByTestId('Value Chain Mapper-image')).toHaveTextContent('(cleared)'),
    )
  })

  it('treats a deliberately cleared portrait as cleared, not as an absent override', async () => {
    // `''` is the project saying "nothing"; NULL is the project saying nothing at all. The whole
    // configuration service is built on that line, and `||` here would quietly reinstate the
    // static map over a decision somebody made. The empty string is falsy, which is what makes
    // every call site's `imageSrc ? <img/> : <initials/>` do the right thing with it.
    vi.mocked(agentConfigApi.getAll).mockResolvedValue({
      agents: { stakeholder_manager: entry('stakeholder_manager', { image_url: '' }) },
    })

    renderProbe(['Stakeholder Manager'], 'sp-gs-am')

    await waitFor(() =>
      expect(screen.getByTestId('Stakeholder Manager-image')).toHaveTextContent('(cleared)'),
    )
    expect(screen.getByTestId('Stakeholder Manager-image')).not.toHaveTextContent(
      AGENT_AVATAR_IMAGE['Stakeholder Manager'],
    )
  })

  it('answers the static map immediately, before the configuration has arrived', async () => {
    // A face that is blank until a request returns is a worse screen than one that is briefly
    // the default, and the carousel draws nineteen of them. Asserted before any `waitFor`.
    let release: (value: { agents: Record<string, AgentConfig> }) => void = () => {}
    vi.mocked(agentConfigApi.getAll).mockReturnValue(
      new Promise((resolve) => { release = resolve }),
    )

    renderProbe(['Stakeholder Manager'], 'sp-gs-am')

    expect(screen.getByTestId('Stakeholder Manager-image')).toHaveTextContent(
      AGENT_AVATAR_IMAGE['Stakeholder Manager'],
    )
    release({ agents: {} })
  })

  it('asks for nothing when there is no project to resolve against', async () => {
    // Team.tsx lists the roll across the whole deployment and has no slug. It gets the static
    // answer rather than a request for a project that does not exist.
    renderProbe(['Stakeholder Manager'], undefined)

    await waitFor(() =>
      expect(screen.getByTestId('Stakeholder Manager-name')).toHaveTextContent('Jordan Williams'),
    )
    expect(agentConfigApi.getAll).not.toHaveBeenCalled()
  })
})
