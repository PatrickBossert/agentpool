// ui/src/__tests__/AgentConfigSection.test.tsx
//
// The shared agent configuration section: what it shows, and - the half that matters - what
// it SENDS.
//
// CLAUDE.md records twelve assertions on recent branches that passed without testing what
// they were named for, and the shape that keeps recurring is "a control was tested as
// rendered, not as sent". Every test below that names a save drives it through to the body
// `agentConfigApi.put` receives.
//
// The sharpest property here is one a rendering test cannot see at all: the form edits
// **overrides**, never resolved values. Saving a resolved default would freeze today's
// default as this project's own choice, and the agent would silently stop following a rename
// in agents/identity.py - a screen that looks identical either way.
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import AgentConfigSection from '../components/tabs/AgentConfigSection'
import { agentConfigApi } from '../api/agentConfig'
import { projectsApi } from '../api/endpoints'
import type { AgentConfig } from '../api/agentConfig'
import type { MyPermissions } from '../types'

vi.mock('../api/agentConfig', () => ({
  agentConfigApi: { get: vi.fn(), put: vi.fn() },
}))

vi.mock('../api/endpoints', () => ({
  projectsApi: { getMyPermissions: vi.fn() },
}))

// The voice picker makes its own call; this file is about the section, and the picker has its
// own. Left unmocked it would reach the network from inside a component under test.
vi.mock('../components/tabs/VoicePicker', () => ({
  default: ({ onChoose }: { onChoose: (id: string, name: string) => void }) => (
    <button type="button" onClick={() => onChoose('chosen-voice-id', 'Chosen Voice')}>
      pick a voice
    </button>
  ),
}))

const DEFAULTS = {
  display_name: 'Avery Singh',
  image_url: '/agents/avery-singh.jpg',
  voice_id: 'default-voice-id',
  language: 'en',
  country_code: 'GB',
  model_id: 'eleven_turbo_v2',
}

const NO_OVERRIDES = {
  display_name: null, image_url: null, voice_id: null,
  language: null, country_code: null, model_id: null,
}

function config(overrides: Partial<AgentConfig['overrides']> = {}): AgentConfig {
  const merged = { ...NO_OVERRIDES, ...overrides }
  return {
    agent_id: 'stakeholder_interviewer',
    configured: Object.values(merged).some((v) => v !== null),
    defaults: DEFAULTS,
    overrides: merged,
    resolved: {
      ...DEFAULTS,
      ...Object.fromEntries(Object.entries(merged).filter(([, v]) => v !== null)),
    },
  }
}

const PERMISSIONS: MyPermissions = {
  can_review: true,
  can_approve: true,
  can_grant_roles: false,
  can_issue_invite_links: false,
  can_change_platform_tier_settings: false,
  platform_tier_settings: [],
  can_administer_project: true,
  writable_knowledge_tiers: ['project'],
}

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AgentConfigSection slug="acme" agentName="Stakeholder Interviewer" />
    </QueryClientProvider>,
  )
}

const name = () => screen.getByLabelText('Display name')
const save = () => screen.getByRole('button', { name: /save configuration/i })

beforeEach(() => {
  // Every assertion below reads `put.mock.calls[0]`, and without this the calls accumulate
  // across the file - so each test would be asserting against the *first* test's save. It
  // fails in the direction that hides work rather than the direction that reports it: the
  // first test passes, and the ones after it pass or fail on a body they never sent.
  vi.clearAllMocks()
  vi.mocked(projectsApi.getMyPermissions).mockResolvedValue(PERMISSIONS)
  vi.mocked(agentConfigApi.put).mockImplementation(async (_s, _a, overrides) =>
    config(overrides),
  )
})

describe('the agent configuration section - what it shows', () => {
  it("shows the agent's default in an empty box, marked as a default", async () => {
    // An administrator has to know whether they are looking at a choice or an inheritance.
    // A default rendered as a filled-in value is indistinguishable from a saved one, and the
    // two behave differently the next time the default changes.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    renderSection()

    await waitFor(() => expect(name()).toBeInTheDocument())
    expect(name()).toHaveValue('')
    expect(name()).toHaveAttribute('placeholder', 'Avery Singh')
    expect(screen.getAllByText(/^default - Avery Singh$/)).toHaveLength(1)
  })

  it('marks a field the project has set as set for this project', async () => {
    vi.mocked(agentConfigApi.get).mockResolvedValue(config({ display_name: 'Ellie Marsh' }))
    renderSection()

    await waitFor(() => expect(name()).toHaveValue('Ellie Marsh'))
    expect(screen.getAllByText('set for this project').length).toBeGreaterThan(0)
    expect(screen.queryByText(/^default - Avery Singh$/)).toBeNull()
  })

  it('labels the synthesis model for what it is, never as "Model"', async () => {
    // Two different things in this product are called a model id and one of them is a
    // security control. The six on the Settings page decide where this engagement's prompts
    // are sent and 403 a project_admin; this one decides which ElevenLabs model speaks. A
    // field labelled "Model" here is read as that other one by the consultant who set it a
    // screen away.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    renderSection()

    await waitFor(() => expect(screen.getByLabelText('Speech synthesis model')).toBeInTheDocument())
    expect(screen.queryByLabelText('Model')).toBeNull()
  })

  it('offers no editable control to somebody who may not administer the project', async () => {
    // The door refuses them with `caller_may_administer_project`, so a control that always
    // 403s is worse than one that says why it is greyed out.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      ...PERMISSIONS, can_administer_project: false,
    })
    renderSection()

    await waitFor(() => expect(screen.getByTestId('agent-config-locked')).toBeInTheDocument())
    expect(name()).toBeDisabled()
    expect(save()).toBeDisabled()
  })
})

describe('the agent configuration section - what it sends', () => {
  it('sends only the fields this project has actually overridden', async () => {
    // The property a rendering test cannot see. Six boxes are on the screen showing six
    // resolved values; five of them are inheritances and must go to the server as null, or
    // this project is pinned to today's defaults for ever with nothing to say so.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    renderSection()

    await waitFor(() => expect(name()).toBeInTheDocument())
    await waitFor(() => expect(name()).toBeEnabled())
    fireEvent.change(name(), { target: { value: 'Ellie Marsh' } })
    fireEvent.click(save())

    await waitFor(() => expect(agentConfigApi.put).toHaveBeenCalled())
    expect(vi.mocked(agentConfigApi.put).mock.calls[0][2]).toEqual({
      display_name: 'Ellie Marsh',
      image_url: null,
      voice_id: null,
      language: null,
      country_code: null,
      model_id: null,
    })
  })

  it('sends null - not an empty string - when a box is cleared back to the default', async () => {
    // The two are different states on the server: NULL means "use the default", '' means
    // "this project says nothing goes here". A cleared box is the first, and sending the
    // second would leave the agent nameless on the interview page.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config({ display_name: 'Ellie Marsh' }))
    renderSection()

    await waitFor(() => expect(name()).toHaveValue('Ellie Marsh'))
    // Enabled, not merely present. `fireEvent.change` on a disabled input is silently
    // ignored, so without this the test races the permissions query and passes or fails on
    // which promise resolved first - a defect CLAUDE.md records this page's own tests having.
    await waitFor(() => expect(name()).toBeEnabled())
    fireEvent.change(name(), { target: { value: '' } })
    fireEvent.click(save())

    await waitFor(() => expect(agentConfigApi.put).toHaveBeenCalled())
    expect(vi.mocked(agentConfigApi.put).mock.calls[0][2].display_name).toBeNull()
  })

  it('sends the voice the picker chose, against the right agent id', async () => {
    // Two assertions in one because they fail together in practice: a voice saved against the
    // wrong agent_id answers 200 and reaches no interview.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    renderSection()

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /choose a voice/i })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: /choose a voice/i }))
    fireEvent.click(screen.getByRole('button', { name: 'pick a voice' }))
    fireEvent.click(save())

    await waitFor(() => expect(agentConfigApi.put).toHaveBeenCalled())
    const [, agentId, sent] = vi.mocked(agentConfigApi.put).mock.calls[0]
    expect(agentId).toBe('stakeholder_interviewer')
    expect(sent.voice_id).toBe('chosen-voice-id')
  })

  it('sends null for the voice when it is returned to the default', async () => {
    vi.mocked(agentConfigApi.get).mockResolvedValue(config({ voice_id: 'a-chosen-voice' }))
    renderSection()

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /use the default voice/i })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: /use the default voice/i }))
    fireEvent.click(save())

    await waitFor(() => expect(agentConfigApi.put).toHaveBeenCalled())
    expect(vi.mocked(agentConfigApi.put).mock.calls[0][2].voice_id).toBeNull()
  })

  it("says why a save was refused in the server's own words", async () => {
    // describeError, imported rather than copied. Several of this API's refusals say
    // something no fixed string can - here, which authority the caller is missing.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    vi.mocked(agentConfigApi.put).mockRejectedValue({
      isAxiosError: true,
      response: { data: { detail: 'Project administration required - org admin or above' } },
    })
    renderSection()

    await waitFor(() => expect(name()).toBeEnabled())
    fireEvent.click(save())
    expect(await screen.findByText(/Project administration required/)).toBeInTheDocument()
  })
})
