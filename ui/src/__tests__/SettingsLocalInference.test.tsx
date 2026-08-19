// ui/src/__tests__/SettingsLocalInference.test.tsx
//
// The Settings tab's local-inference toggle, asserted on the request body that leaves the
// browser rather than on the control that renders. Same axios-adapter technique as
// client.test.ts and agentChatUpload.test.ts: the transport is swapped for one that records
// the fully-assembled request, and `../api/endpoints` is deliberately **not** mocked, so the
// page, the client function and the serialisation are all in the chain being proven. A test
// that mocked projectsApi.updateSettings would prove the mock was called and nothing about
// what the server receives - and what the server receives is the entire hazard here.
//
// The hazard, precisely. `force_local_inference` used to be absent from `ProjectSettings` in
// types.ts, and survived a save only as an untyped extra key that
// `setForm({ ...DEFAULTS, ...settings })` happened to copy. A dropped key is `false` on the
// server, and clearing this flag is the one transition in the body that *widens* where an
// engagement's prompts may go - so an org_admin saving a job title's worth of unrelated
// configuration would have moved a project back onto hosted inference with nothing said.
// `test_a_save_that_changes_something_else_carries_the_override_through` is the assertion
// that fails if anybody ever builds this body from a narrower type again.
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AxiosError, AxiosHeaders } from 'axios'
import type { AxiosRequestConfig, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import { apiClient } from '../api/client'
import Settings from '../pages/Settings'
import type { MyPermissions, ProjectSettings } from '../types'

const SLUG = 'acme-rail'

const BASE_SETTINGS: ProjectSettings = {
  llm_mode: 'standard',
  force_local_inference: false,
  locale: 'GB',
  sector: 'transport',
  stakeholder_groups: [],
  value_stream_labels: [],
  roadmap_time_axis: 'quarters',
  review_gates: true,
  slack_channel: '',
  discovery_brief: '',
  discovery_links: [],
  discovery_document_ids: [],
  interview_method: 'none',
  // Deliberately not DEFAULTS' 8. This is the load barrier every test below waits on,
  // and a barrier whose value the form already holds is satisfied before the query
  // resolves - which lets an edit race the load and be clobbered by it. Two of these
  // tests passed against a form still holding its defaults for exactly that reason.
  elaboration_press_timeout_seconds: 9,
  anthropic_fast_model: 'anthropic/claude-haiku-4-5-20251001',
  anthropic_deep_model: 'anthropic/claude-opus-4-6',
  local_fast_model: 'gemma4:fast',
  local_fast_url: 'http://localhost:11434/v1',
  local_deep_model: 'qwen27b:reasoning',
  local_deep_url: 'http://localhost:11434/v1',
}

// What GET /my-permissions answers for `platform_tier_settings` - the server's own
// _PLATFORM_TIER_SETTINGS, which api/routers/permissions.py serves rather than restates.
// A fixture standing in for the server's answer, not a second copy of the rule: the
// endpoint is held equal to the real tuple in
// tests/test_grantable_roles.py::test_my_permissions_serves_the_servers_own_platform_tier_list,
// so the two cannot drift without that failing.
//
// `dev_mode` is in the list and has no control on this page. That is deliberate and
// asserted below rather than filtered out here - the page must answer honestly about
// fields it does not render, and a fixture trimmed to what happens to be on screen could
// not tell a missing control from a correctly absent one.
const PLATFORM_TIER_SETTINGS = [
  'llm_mode', 'force_local_inference', 'dev_mode',
  'anthropic_fast_model', 'anthropic_deep_model',
  'local_fast_model', 'local_fast_url', 'local_deep_model', 'local_deep_url',
]

const PLATFORM_TIER: MyPermissions = {
  can_review: true,
  can_approve: true,
  can_grant_roles: false,
  can_issue_invite_links: true,
  can_change_platform_tier_settings: true,
  platform_tier_settings: PLATFORM_TIER_SETTINGS,
  writable_knowledge_tiers: ['project'],
}

// A project_admin: administers this engagement, and is refused every platform-tier field on
// this body. The one caller the toggle has to be careful about.
const PROJECT_ADMIN: MyPermissions = {
  ...PLATFORM_TIER,
  can_grant_roles: true,
  can_issue_invite_links: false,
  can_change_platform_tier_settings: false,
}

function ok(config: AxiosRequestConfig, data: unknown, status = 200): AxiosResponse {
  return { data, status, statusText: 'OK', headers: {}, config } as AxiosResponse
}

type Wire = {
  /** The bodies of every PATCH /settings this render sent, parsed as the server sees them. */
  patched: ProjectSettings[]
}

function serve(
  settings: ProjectSettings,
  permissions: MyPermissions,
  patchResult?: (config: AxiosRequestConfig) => Promise<AxiosResponse>,
): Wire {
  const wire: Wire = { patched: [] }
  apiClient.defaults.adapter = (config: AxiosRequestConfig) => {
    const url = apiClient.getUri(config)
    if (config.method?.toLowerCase() === 'patch') {
      // config.data is the serialised body - the actual bytes, which is the point of
      // reading it here rather than trusting an argument handed to a mocked function.
      wire.patched.push(JSON.parse(config.data as string) as ProjectSettings)
      if (patchResult) return patchResult(config)
      return Promise.resolve(ok(config, settings))
    }
    if (url.endsWith('/my-permissions')) return Promise.resolve(ok(config, permissions))
    if (url.endsWith('/settings')) return Promise.resolve(ok(config, settings))
    return Promise.resolve(ok(config, {}))
  }
  return wire
}

function renderSettings() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/${SLUG}/settings`]}>
        <Routes>
          <Route path="/:slug/settings" element={<Settings />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const toggle = () => screen.getByRole('switch', { name: /force local inference/i })
const save = () => screen.getByRole('button', { name: /save settings|saved|saving/i })
const budget = () => screen.getByLabelText(/follow-up time limit/i)

/** The loaded settings are in the form - not merely rendered, but no longer about to be
 *  overwritten by the query resolving. Every interaction below waits on this first. */
async function settingsHaveLoaded() {
  await waitFor(() => expect(budget()).toHaveValue(9))
}

describe('Settings - the local inference override reaches the wire', () => {
  const realAdapter = apiClient.defaults.adapter

  afterEach(() => {
    apiClient.defaults.adapter = realAdapter
  })

  it('sends force_local_inference true when an operator turns it on', async () => {
    const wire = serve(BASE_SETTINGS, PLATFORM_TIER)
    renderSettings()

    await settingsHaveLoaded()
    expect(toggle()).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(toggle())
    fireEvent.click(save())

    await waitFor(() => expect(wire.patched).toHaveLength(1))
    expect(wire.patched[0].force_local_inference).toBe(true)
  })

  it('sends force_local_inference false when an operator turns it off', async () => {
    // The clearing direction has to be expressible: the refusal this field carries belongs
    // to the server, not to a control that simply cannot send the value.
    const wire = serve({ ...BASE_SETTINGS, force_local_inference: true }, PLATFORM_TIER)
    renderSettings()

    await settingsHaveLoaded()
    expect(toggle()).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(toggle())
    fireEvent.click(save())

    await waitFor(() => expect(wire.patched).toHaveLength(1))
    expect(wire.patched[0].force_local_inference).toBe(false)
  })

  it('carries an existing override through a save that changes something else', async () => {
    // The one that matters. Nothing on this page is touching the flag; the operator edits an
    // unrelated field and saves the whole body, and the stored `true` has to survive the
    // round trip. If the key is ever dropped from the request the server reads `false` and
    // silently widens the engagement back onto hosted inference - a transition the
    // platform-tier guard permits for this caller, so nothing downstream would refuse it.
    const wire = serve({ ...BASE_SETTINGS, force_local_inference: true }, PLATFORM_TIER)
    renderSettings()

    await settingsHaveLoaded()
    expect(toggle()).toHaveAttribute('aria-checked', 'true')
    fireEvent.change(budget(), { target: { value: '15' } })
    fireEvent.click(save())

    await waitFor(() => expect(wire.patched).toHaveLength(1))
    expect(wire.patched[0].elaboration_press_timeout_seconds).toBe(15)
    expect(wire.patched[0].force_local_inference).toBe(true)
    // Present, not merely truthy: an omitted key and a `false` key mean different things to
    // this server, and `undefined` would satisfy neither of the assertions people write.
    expect(Object.keys(wire.patched[0])).toContain('force_local_inference')
  })

  it('reads a stored override back onto the control', async () => {
    serve({ ...BASE_SETTINGS, force_local_inference: true }, PLATFORM_TIER)
    renderSettings()

    await waitFor(() => expect(toggle()).toHaveAttribute('aria-checked', 'true'))
  })
})

describe('Settings - a caller who may not change where the prompts go', () => {
  const realAdapter = apiClient.defaults.adapter

  afterEach(() => {
    apiClient.defaults.adapter = realAdapter
  })

  it('offers no working toggle to a project_admin, and says who may', async () => {
    serve({ ...BASE_SETTINGS, force_local_inference: true }, PROJECT_ADMIN)
    renderSettings()

    // Both queries, not just one: `disabled` comes from /my-permissions and `aria-checked`
    // from /settings, and they land on different ticks.
    await waitFor(() => {
      expect(toggle()).toBeDisabled()
      // Still shown the state: which models this engagement runs on is something a project
      // administrator needs to be able to read, even where they may not change it.
      expect(toggle()).toHaveAttribute('aria-checked', 'true')
    })
    // Scoped to the toggle's own section, not the page: the same note now renders beside
    // every locked group, and a page-wide query would be satisfied by a note explaining
    // some other control.
    const section = toggle().closest('section')!
    expect(within(section).getByText(/only an org admin or above may change/i))
      .toBeInTheDocument()
  })

  it('still carries the stored override on that caller\'s own save', async () => {
    // A refused control must not become a dropped key. The server compares the *transition*,
    // so a project_admin's save is accepted precisely because the value it sends is the one
    // already stored - sending nothing, or sending `false`, would be refused as a change
    // they never asked to make.
    const wire = serve({ ...BASE_SETTINGS, force_local_inference: true }, PROJECT_ADMIN)
    renderSettings()

    await settingsHaveLoaded()
    fireEvent.change(budget(), { target: { value: '12' } })
    fireEvent.click(save())

    await waitFor(() => expect(wire.patched).toHaveLength(1))
    expect(wire.patched[0].force_local_inference).toBe(true)
  })

  it("shows the server's refusal, which names the field", async () => {
    // Through describeError, never a fixed string: the 403 says *which* platform-tier field
    // was refused and in which direction, and "Save failed. Please try again." both hides
    // that and reads as a transient fault worth retrying. This is the only thing that tells
    // an operator to go and ask somebody.
    const detail =
      'force_local_inference may only be changed by an org admin or above - a project_admin '
      + 'configures the engagement, not how it is run. Clearing the local-inference override '
      + 'widens where this project\'s prompts may go'
    serve({ ...BASE_SETTINGS, force_local_inference: true }, PROJECT_ADMIN, (config) => {
      // A real AxiosError, not a hand-rolled object: describeError gates on
      // axios.isAxiosError, so a plain Error carrying a `response` would fall through to the
      // fallback string and this test would pass while asserting the opposite property.
      const internal = config as InternalAxiosRequestConfig
      return Promise.reject(
        new AxiosError('Request failed with status code 403', 'ERR_BAD_REQUEST', internal, null, {
          data: { detail },
          status: 403,
          statusText: 'Forbidden',
          headers: new AxiosHeaders(),
          config: internal,
        }),
      )
    })
    renderSettings()

    await settingsHaveLoaded()
    fireEvent.change(budget(), { target: { value: '12' } })
    fireEvent.click(save())

    expect(await screen.findByText(detail)).toBeInTheDocument()
    expect(screen.queryByText(/save failed\. please try again\./i)).not.toBeInTheDocument()
  })
})

describe('Settings - the toggle says what it does not do', () => {
  const realAdapter = apiClient.defaults.adapter

  afterEach(() => {
    apiClient.defaults.adapter = realAdapter
  })

  it('tells the reader the documents do not move with the model calls', async () => {
    // The label is the deliverable here, not decoration. This flag exists *because* it is
    // not a fourth deployment mode: it narrows inference alone, and an operator who reads
    // "local" as "everything on-premises" would believe their Chroma Cloud documents had
    // moved. Asserted on the claim rather than on the sentence, so the copy can be rewritten
    // without the guarantee quietly going with it.
    serve(BASE_SETTINGS, PLATFORM_TIER)
    renderSettings()

    const blurb = await screen.findByText(/documents stay wherever the mode puts them/i)
    expect(blurb).toHaveTextContent(/chroma cloud/i)
    // And names the control that *does* move them, so the honest next question has an answer.
    expect(blurb).toHaveTextContent(/sensitive/i)
  })
})

// ── Every platform-tier field, not just the one this task added ──────────────────────────
//
// Gating exactly one of nine platform-tier fields was worse than gating none: it reads as
// though the other eight are permitted. These drive the whole set, and they are written
// against the *server's* list rather than a list of controls chosen here - so a tenth member
// added to `_PLATFORM_TIER_SETTINGS` is covered the moment its control follows the same
// `id={field}` pattern, with no change to this file.
describe('Settings - every platform-tier field the page renders is gated together', () => {
  const realAdapter = apiClient.defaults.adapter

  afterEach(() => {
    apiClient.defaults.adapter = realAdapter
  })

  /** The control for a settings field, found by the id the page gives it, or null when the
   *  page renders no control for that field at all. */
  const controlFor = (field: string) => document.getElementById(field)

  it('renders a control for every platform-tier field but dev_mode', async () => {
    // The split is asserted, not assumed. Without this, the disabled-check below would pass
    // vacuously for any field whose control silently disappeared - and "no control" and
    // "control that ignores the tier" look identical to a test that only asks about the
    // controls it finds.
    serve(BASE_SETTINGS, PLATFORM_TIER)
    renderSettings()
    await settingsHaveLoaded()

    const rendered = PLATFORM_TIER_SETTINGS.filter((f) => controlFor(f) !== null)
    expect(rendered.sort()).toEqual(
      PLATFORM_TIER_SETTINGS.filter((f) => f !== 'dev_mode').sort(),
    )
    expect(controlFor('dev_mode')).toBeNull()
  })

  it('disables every one of them for a project_admin', async () => {
    serve(BASE_SETTINGS, PROJECT_ADMIN)
    renderSettings()
    await waitFor(() => expect(controlFor('llm_mode')).toBeDisabled())

    for (const field of PLATFORM_TIER_SETTINGS) {
      const control = controlFor(field)
      if (control === null) continue  // dev_mode - asserted absent by the test above
      expect(control, `${field} is refused by the server and offered by the page`)
        .toBeDisabled()
    }
  })

  it('enables every one of them for an org admin', async () => {
    // The control, and the half that matters most: a test asserting only that things are
    // disabled passes just as happily against a page that disables them for everybody, which
    // would be a broken Settings tab rather than a gated one.
    serve(BASE_SETTINGS, PLATFORM_TIER)
    renderSettings()
    await settingsHaveLoaded()

    for (const field of PLATFORM_TIER_SETTINGS) {
      const control = controlFor(field)
      if (control === null) continue
      expect(control, `${field} is permitted by the server and refused by the page`)
        .toBeEnabled()
    }
  })

  it('says why the controls are greyed out, wherever they are greyed out', async () => {
    // A disabled control with no reason beside it reads as a bug, and the operator's next
    // move is to report the page rather than to ask somebody. One note per locked group -
    // the mode, the models, the override - rather than one per field.
    serve(BASE_SETTINGS, PROJECT_ADMIN)
    renderSettings()

    const notes = await screen.findAllByText(/only an org admin or above may change/i)
    expect(notes).toHaveLength(3)
  })

  it('shows no such note to a caller who may change them', async () => {
    serve(BASE_SETTINGS, PLATFORM_TIER)
    renderSettings()
    await settingsHaveLoaded()

    expect(screen.queryByText(/only an org admin or above may change/i)).not.toBeInTheDocument()
  })

  it('locks the controls until the answer arrives, rather than after', async () => {
    // An unanswered question locks. A control enabled for the moment /my-permissions takes
    // to answer is a control a project_admin can change and then be refused for - the exact
    // failure the gating exists to prevent, just narrower in time. Asserted before either
    // query is allowed to resolve.
    let releasePermissions: (() => void) | null = null
    const held = new Promise<void>((resolve) => { releasePermissions = resolve })
    apiClient.defaults.adapter = async (config: AxiosRequestConfig) => {
      if (apiClient.getUri(config).endsWith('/my-permissions')) {
        await held
        return ok(config, PLATFORM_TIER)
      }
      return ok(config, BASE_SETTINGS)
    }
    renderSettings()

    await waitFor(() => expect(controlFor('llm_mode')).toBeDisabled())
    expect(controlFor('force_local_inference')).toBeDisabled()

    releasePermissions!()
    await waitFor(() => expect(controlFor('llm_mode')).toBeEnabled())
  })
})
