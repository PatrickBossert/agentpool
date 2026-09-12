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

// `getAll` is on the mock because the section asks `useAgentIdentity` what face and name to
// hand the rehearsal dialog, rather than re-deriving "override, then the static map" itself -
// the rule that hook exists to state once. Left off, the hook's query throws and every agent
// silently falls back to the static answer, which is the one case these tests must not be run
// under.
vi.mock('../api/agentConfig', () => ({
  agentConfigApi: { get: vi.fn(), getAll: vi.fn(), put: vi.fn(), uploadImage: vi.fn() },
}))

// The dialog itself is driven in TestInterviewPerInterviewer.test.tsx. Here it is a stub that
// records what it was handed, because the property this file is about is what the section
// SENDS to it - a dialog opened for the wrong agent renders perfectly and rehearses somebody
// else, which is the whole defect sp63 repairs.
vi.mock('../components/tabs/TestInterviewDialog', () => ({
  default: (props: {
    slug: string
    agentId: string
    displayName: string
    imageUrl: string | null
    locale?: string
  }) => (
    <div
      data-testid="rehearsal-dialog"
      data-slug={props.slug}
      data-agent-id={props.agentId}
      data-display-name={props.displayName}
      data-image-url={props.imageUrl ?? ''}
      data-locale={props.locale ?? ''}
    />
  ),
}))

vi.mock('../api/endpoints', () => ({
  projectsApi: { getMyPermissions: vi.fn() },
}))

// The voice picker makes its own call; this file is about the section, and the picker has its
// own. Left unmocked it would reach the network from inside a component under test.
// The section names the stored voice from the catalogue, so this door is now on its path even
// when the picker is never opened. Two entries and one deliberate absence: `unknown-voice-id`
// is in no listing, which is what a voice removed from the account looks like.
vi.mock('../api/voices', () => ({
  voicesApi: {
    list: vi.fn().mockResolvedValue({
      account: [
        { voice_id: 'default-voice-id', name: 'Daniel - Steady Broadcaster', accent: 'british', gender: 'male' },
        { voice_id: 'chosen-voice-id', name: 'Alice - Clear, Engaging Educator', accent: 'british', gender: 'female' },
      ],
      library: [],
      accent_options: ['british'],
    }),
  },
}))

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
    // What the server answers for this agent. It is stipulated here rather than worked out
    // from the id: the roster of who interviews lives in one place in Python, and a fixture
    // that re-derived it would be a second copy of it on the side nothing is watching.
    is_interviewer: true,
    // Level 2 of the four - `null` because this agent's default is the portrait shipped in the
    // repository, which is true of all eighteen agents on the roll today. The promotion rule
    // has no live subject; `tests/test_agent_default_image.py` synthesises one.
    promoted_default_image_url: null,
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

function renderSection(agentName = 'Stakeholder Interviewer') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AgentConfigSection slug="acme" agentName={agentName} />
    </QueryClientProvider>,
  )
}

const name = () => screen.getByLabelText('Display name')
const save = () => screen.getByRole('button', { name: /save configuration/i })
const chooser = () => screen.getByLabelText(/choose image/i) as HTMLInputElement

/** A file of a stated size, so an assertion about what the administrator is told is real. */
function photograph(bytes: number, filename = 'headshot.jpg'): File {
  return new File(['x'.repeat(bytes)], filename, { type: 'image/jpeg' })
}

function choose(file: File) {
  fireEvent.change(chooser(), { target: { files: [file] } })
}

const STORED = { url: '/api/projects/acme/agents/stakeholder_interviewer/image',
                 bytes: 74_000, original_bytes: 8_200_000 }

beforeEach(() => {
  // Every assertion below reads `put.mock.calls[0]`, and without this the calls accumulate
  // across the file - so each test would be asserting against the *first* test's save. It
  // fails in the direction that hides work rather than the direction that reports it: the
  // first test passes, and the ones after it pass or fail on a body they never sent.
  vi.clearAllMocks()
  vi.mocked(projectsApi.getMyPermissions).mockResolvedValue(PERMISSIONS)
  // No project has overridden anybody, so `useAgentIdentity` answers from the static maps -
  // which is what the dashboard's other nine display sites do for an unconfigured agent.
  vi.mocked(agentConfigApi.getAll).mockResolvedValue({ agents: {} })
  vi.mocked(agentConfigApi.put).mockImplementation(async (_s, _a, overrides) =>
    config(overrides),
  )
  vi.mocked(agentConfigApi.uploadImage).mockResolvedValue(STORED)
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

describe('the agent configuration section - choosing a portrait', () => {
  // Patrick's instruction, 7 September: an Open… selector beside the field, and a large file
  // quietly becoming a small one is something the administrator is told about.
  //
  // Every test here that names the save drives it through to the two calls that leave the
  // browser, **and to the order between them**. CLAUDE.md records a radio tested as rendered
  // and not as sent; "the file input renders" is that same assertion wearing a new hat, and it
  // would pass against a section that uploaded nothing at all.

  it('offers a real file input, filtered to the types the door accepts', async () => {
    // A real focusable input rather than a button calling `.click()` on a hidden one: the
    // keyboard and the accessibility tree have to reach it, which is why it is styled out of
    // the way instead of removed. `accept` is asserted because the dialog should not offer a
    // TIFF the server is going to refuse - it is a convenience, and the server still validates.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    renderSection()

    await waitFor(() => expect(chooser()).toBeInTheDocument())
    expect(chooser().type).toBe('file')
    expect(chooser()).toHaveAttribute('accept', 'image/png,image/jpeg,image/webp')
  })

  it('names the chosen file and its size, and says nothing has been sent yet', async () => {
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    renderSection()

    await waitFor(() => expect(chooser()).toBeEnabled())
    choose(photograph(8_200_000, 'avery.jpg'))

    const note = await screen.findByTestId('pending-portrait')
    expect(note).toHaveTextContent('avery.jpg')
    expect(note).toHaveTextContent('8.2 MB')
    // Choosing is not uploading. One action, one outcome: an administrator who picks the wrong
    // file and navigates away has changed nothing on the server.
    expect(agentConfigApi.uploadImage).not.toHaveBeenCalled()
  })

  it('uploads the file BEFORE saving, and saves the URL the upload answered', async () => {
    // The whole of Step 8b, and the order is the half a "both were called" assertion misses.
    // Saving first and uploading afterwards would record an address for a file that may never
    // arrive, and every screen would look identical.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    renderSection()

    await waitFor(() => expect(chooser()).toBeEnabled())
    choose(photograph(8_200_000))
    fireEvent.click(save())

    await waitFor(() => expect(agentConfigApi.put).toHaveBeenCalled())
    const uploadedAt = vi.mocked(agentConfigApi.uploadImage).mock.invocationCallOrder[0]
    const savedAt = vi.mocked(agentConfigApi.put).mock.invocationCallOrder[0]
    expect(uploadedAt).toBeLessThan(savedAt)

    const [uploadSlug, uploadAgent, sentFile] = vi.mocked(agentConfigApi.uploadImage).mock.calls[0]
    expect(uploadSlug).toBe('acme')
    expect(uploadAgent).toBe('stakeholder_interviewer')
    expect(sentFile.name).toBe('headshot.jpg')

    // And the URL the door answered is what the row is given - not the file name, not a path
    // this component invented, and not the empty box the administrator was looking at.
    expect(vi.mocked(agentConfigApi.put).mock.calls[0][2].image_url).toBe(STORED.url)
  })

  it('saves the typed path unchanged when no file was chosen', async () => {
    // The control. Without it, a section that always sent the upload's URL - or always sent
    // null - would pass the test above, and the free-text field would have quietly stopped
    // working for every project that uses one.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config({ image_url: '/agents/avery-singh.jpg' }))
    renderSection()

    await waitFor(() => expect(save()).toBeEnabled())
    fireEvent.click(save())

    await waitFor(() => expect(agentConfigApi.put).toHaveBeenCalled())
    expect(agentConfigApi.uploadImage).not.toHaveBeenCalled()
    expect(vi.mocked(agentConfigApi.put).mock.calls[0][2].image_url).toBe('/agents/avery-singh.jpg')
  })

  it('does not save the configuration at all when the upload is refused', async () => {
    // The failure Step 8b asks to be driven. Continuing would write whatever `image_url` the
    // draft was already holding - a stale address, or nothing - while the administrator was
    // looking at the filename they had just chosen.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    vi.mocked(agentConfigApi.uploadImage).mockRejectedValue({
      isAxiosError: true,
      response: { data: { detail: 'Image exceeds the maximum allowed size of 10 MB.' } },
    })
    renderSection()

    await waitFor(() => expect(chooser()).toBeEnabled())
    choose(photograph(12_000_000))
    fireEvent.click(save())

    // Which half failed, said on the screen: a refused portrait means try another file, and a
    // refused save means ask for authority. Told the wrong one, an administrator goes looking
    // for a permissions problem that is not there.
    expect(await screen.findByText(/image could not be uploaded/i)).toBeInTheDocument()
    // The server's own sentence survives - it names the limit, and no fixed string can.
    expect(screen.getByText(/10 MB/)).toBeInTheDocument()
    expect(agentConfigApi.put).not.toHaveBeenCalled()
  })

  it('reports what the downscale cost once the portrait is stored', async () => {
    // The point of the whole task, said out loud. An administrator who is never told their
    // 8 MB photograph became 74 kB uploads the same 8 MB file again next time.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    renderSection()

    await waitFor(() => expect(chooser()).toBeEnabled())
    choose(photograph(8_200_000))
    fireEvent.click(save())

    const note = await screen.findByTestId('stored-portrait')
    expect(note).toHaveTextContent('8.2 MB')
    expect(note).toHaveTextContent('74 kB')
  })

  it('offers no portrait selector to somebody who may not administer the project', async () => {
    // The same rule as every other control in this section - the door refuses them with
    // `require_project_administration`, so a control that always 403s is worse than none.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      ...PERMISSIONS, can_administer_project: false,
    })
    renderSection()

    await waitFor(() => expect(screen.getByTestId('agent-config-locked')).toBeInTheDocument())
    expect(chooser()).toBeDisabled()
  })
})

describe('the agent configuration section - when the read itself fails', () => {
  // Found in production on 7 September, and the diagnosis cost more than the fix. The API
  // had been running since 19 August, so it predated this branch and served no
  // `/projects/{slug}/agents/{agent_id}/config` at all - every section on every agent
  // answered 404. What an administrator saw was "Loading this agent's configuration…",
  // for ever, on all of them.
  //
  // The section consulted `data` alone, so a query that had FAILED and a query still in
  // FLIGHT rendered the same sentence. The save path already reported refusals in the
  // server's own words; the read path had no error branch at all, which is the half a
  // reader never checks because the other half is visibly careful.
  //
  // Asserted as the absence of the loading text as well as the presence of the error,
  // because a component that rendered both would still be telling an administrator to wait
  // for something that is never coming.
  it('says the configuration could not be loaded, and stops saying it is loading', async () => {
    vi.mocked(agentConfigApi.get).mockRejectedValue({
      isAxiosError: true,
      response: { status: 404, data: { detail: 'Not Found' } },
    })
    renderSection()

    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument()
    expect(screen.queryByText(/Loading this agent/i)).not.toBeInTheDocument()
    // The server's own words survive alongside the framing rather than replacing it. On the
    // save path describeError's sentence stands alone; here it is appended, because a bare
    // `Not Found` reads as deliberate and an administrator cannot act on it.
    expect(screen.getByText(/Not Found/)).toBeInTheDocument()
  })

  it('still says it is loading while the read is genuinely in flight', async () => {
    // The control. Without it, a component that reported an error unconditionally - or one
    // that simply deleted the loading branch - would pass the test above.
    vi.mocked(agentConfigApi.get).mockImplementation(() => new Promise(() => {}))
    renderSection()

    expect(await screen.findByText(/Loading this agent/i)).toBeInTheDocument()
    expect(screen.queryByText(/could not be loaded/i)).not.toBeInTheDocument()
  })
})


describe('rehearsing an interview, from the agent it belongs to', () => {
  // The rehearsal button used to live on Avery's own Setup tab, which is the only reason the
  // dialog could hardcode his face and his name and still look right. There is one route to it
  // now, on the section every agent renders, and which agents get it is `is_interviewer` on the
  // payload - never a list of agent ids restated in TypeScript, which would be a second roster
  // beside `interviewer_selection`'s with nothing comparing the two.
  const rehearse = () => screen.getByRole('button', { name: /test interview/i })

  it('offers a test interview for an interviewer and not for anybody else', async () => {
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    const interviewer = renderSection()
    await waitFor(() => expect(rehearse()).toBeInTheDocument())
    interviewer.unmount()

    // Both ways, in one test, because asserting only the true case passes against a section
    // that renders the button for all eighteen agents - and seventeen of them have no script,
    // no voice necessarily, and nothing to rehearse.
    vi.mocked(agentConfigApi.get).mockResolvedValue({
      ...config(),
      agent_id: 'stakeholder_manager',
      is_interviewer: false,
    })
    renderSection('Stakeholder Manager')
    await waitFor(() => expect(screen.getByLabelText('Display name')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /test interview/i })).toBeNull()
  })

  it('opens the dialog for this agent, with this agent’s name and face', async () => {
    // The half a "the button renders" assertion cannot see. `TestSpeakRequest.agent_id`
    // defaults to `stakeholder_interviewer` on the server, so a dialog opened without an
    // agent - or with the wrong one - answers 200 and rehearses Avery under Laura's heading.
    vi.mocked(agentConfigApi.get).mockResolvedValue({
      ...config(),
      agent_id: 'second_interviewer',
    })
    renderSection('Second Interviewer')

    await waitFor(() => expect(rehearse()).toBeInTheDocument())
    fireEvent.click(rehearse())

    const dialog = await screen.findByTestId('rehearsal-dialog')
    expect(dialog).toHaveAttribute('data-agent-id', 'second_interviewer')
    expect(dialog).toHaveAttribute('data-display-name', 'Laura Nelson')
    // Under the Vite base, and asserted with it rather than without. This is the difference
    // between `useAgentIdentity` and `config.resolved.image_url`, which is the tempting thing
    // to read since the section is already holding it: the server's resolved default is
    // `/agents/laura-nelson.jpg`, Vite serves `ui/public` under `/dashboard`, and drawing the
    // resolved value would 404 for every agent this project has not overridden. A test written
    // without the prefix would have passed against exactly that mistake.
    expect(dialog).toHaveAttribute('data-image-url', '/dashboard/agents/laura-nelson.jpg')
    expect(dialog).toHaveAttribute('data-slug', 'acme')
  })

  it('shows nothing until the button is pressed', async () => {
    // The control for the test above: a section that always mounted the dialog would pass it,
    // and would fire a /test/speak the moment anybody opened the Agents tab.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    renderSection()
    await waitFor(() => expect(rehearse()).toBeInTheDocument())
    expect(screen.queryByTestId('rehearsal-dialog')).toBeNull()
  })

  it('offers it to somebody who may not administer the project', async () => {
    // Deliberate, and the reason it is not wired to `mayAdminister` like every control above
    // it. `POST /api/interviews/test/speak` asks `check_project_access` and nothing more, so
    // rehearsing is reading rather than configuring - and greying it out would refuse somebody
    // the server would have served.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      ...PERMISSIONS, can_administer_project: false,
    })
    renderSection()

    await waitFor(() => expect(screen.getByTestId('agent-config-locked')).toBeInTheDocument())
    expect(rehearse()).toBeEnabled()
  })
})

describe('the voice a project has chosen, read by a person', () => {
  // An id is what the project stores and tells an administrator nothing about who they picked.
  // `Xb7hH8MSUJpSbSDYk0k2` was the whole of the answer unless the voice happened to be chosen
  // in the same session, which is the one case that was already handled.
  it('names the configured voice', async () => {
    vi.mocked(agentConfigApi.get).mockResolvedValue(config({ voice_id: 'chosen-voice-id' }))
    renderSection()
    expect(await screen.findByText('Alice - Clear, Engaging Educator')).toBeInTheDocument()
  })

  it('names the default when nothing is configured', async () => {
    // The provenance chip said `default - default-voice-id`. The default is inherited rather
    // than chosen, which makes naming it *more* useful, not less: nobody picked it, so nobody
    // has any reason to recognise the id.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    renderSection()
    // Scoped to the provenance chip. With no override the voice line names the default too -
    // correctly, since it is what the agent will speak with - so an unscoped query finds both
    // and cannot say which one this test is about.
    await waitFor(() =>
      expect(
        screen.getAllByTestId('provenance').some((chip) =>
          /Daniel - Steady Broadcaster/.test(chip.textContent ?? ''),
        ),
      ).toBe(true),
    )
  })

  it('still shows the id, so it stays quotable', async () => {
    // The id is what a database row and a support conversation will carry. Hiding it entirely
    // would trade one unreadable line for one unquotable one.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config({ voice_id: 'chosen-voice-id' }))
    renderSection()
    expect(await screen.findByTestId('voice-id')).toHaveTextContent('chosen-voice-id')
  })

  it('falls back to saying so when the catalogue does not know the voice', async () => {
    // The control, and a real state: a voice removed from the account, or a catalogue request
    // that failed. Showing nothing, or showing a stale name, would both be worse than saying
    // the id and admitting the name is unknown.
    vi.mocked(agentConfigApi.get).mockResolvedValue(config({ voice_id: 'unknown-voice-id' }))
    renderSection()
    expect(await screen.findByTestId('voice-id')).toHaveTextContent('unknown-voice-id')
    expect(screen.getByTestId('voice-name')).toHaveTextContent('Unknown voice')
  })
})
