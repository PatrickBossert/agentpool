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
// The nine names live in one file and are held equal to the server's tuple by
// tests/test_settings_platform_tier_fixture.py - see that fixture's header for why they
// are no longer typed out here.
import {
  PLATFORM_TIER_FIELDS_WITH_A_CONTROL,
  PLATFORM_TIER_FIELDS_WITH_NO_CONTROL,
  PLATFORM_TIER_SETTINGS,
} from './fixtures/platformTierSettings'

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
  dev_mode: true,
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

  it('renders a control for every platform-tier field but the ones with none', async () => {
    // The split is asserted, not assumed. Without it the loops below could pass while a
    // control had silently vanished - "no control" and "control that ignores the tier" look
    // identical to a test that only asks about the controls it happens to find.
    serve(BASE_SETTINGS, PLATFORM_TIER)
    renderSettings()
    await settingsHaveLoaded()

    const rendered = PLATFORM_TIER_SETTINGS.filter((f) => controlFor(f) !== null)
    expect(rendered.sort()).toEqual([...PLATFORM_TIER_FIELDS_WITH_A_CONTROL].sort())
    for (const field of PLATFORM_TIER_FIELDS_WITH_NO_CONTROL) {
      expect(controlFor(field)).toBeNull()
    }
  })

  it('disables every one of them for a project_admin', async () => {
    // No `continue`. The earlier version skipped any field whose control it could not find,
    // so stripping `id={key}` from the six model inputs made both loops pass over all six in
    // silence - a suite that reported coverage it did not have. A missing control now fails
    // here, on the field's own name.
    serve(BASE_SETTINGS, PROJECT_ADMIN)
    renderSettings()
    await waitFor(() => expect(controlFor('llm_mode')).toBeDisabled())

    for (const field of PLATFORM_TIER_FIELDS_WITH_A_CONTROL) {
      expect(controlFor(field), `no control found for ${field}`).not.toBeNull()
      expect(controlFor(field), `${field} is refused by the server and offered by the page`)
        .toBeDisabled()
    }
  })

  it('enables every one of them for an org admin', async () => {
    // The control, and the half that matters most: a suite asserting only that things are
    // disabled passes just as happily against a page that disables them for everybody, which
    // would be a broken Settings tab rather than a gated one.
    serve(BASE_SETTINGS, PLATFORM_TIER)
    renderSettings()
    await settingsHaveLoaded()

    for (const field of PLATFORM_TIER_FIELDS_WITH_A_CONTROL) {
      expect(controlFor(field), `no control found for ${field}`).not.toBeNull()
      expect(controlFor(field), `${field} is permitted by the server and refused by the page`)
        .toBeEnabled()
    }
  })

  it('locks a field the server names that this task never anticipated', async () => {
    // The property the report claimed and the review disproved: the page must obey whatever
    // list it is served, not a set of controls somebody remembered to wire.
    //
    // `sector` is the reviewer's own probe. It is an ordinary project-configuration field
    // that a project_admin may change today, deliberately outside the tuple - so a page that
    // locks it *here*, given a server that says to, is a page deriving its gating rather
    // than hand-threading it. Nothing in Settings.tsx mentions `sector` in connection with
    // the tier, and nothing needs to.
    serve(BASE_SETTINGS, {
      ...PROJECT_ADMIN,
      platform_tier_settings: [...PLATFORM_TIER_SETTINGS, 'sector'],
    })
    renderSettings()

    // Wait on a control that must end up *enabled*. Waiting on `sector` being disabled is
    // satisfied instantly by the pre-answer state, where everything is locked - the same
    // barrier mistake this file has now made three times, in three disguises.
    await waitFor(() => expect(controlFor('slack_channel')).toBeEnabled())
    expect(controlFor('sector'), 'the page ignored a field the server named').toBeDisabled()
  })

  it('leaves a field the server stops naming editable', async () => {
    // The other direction. A page that hard-coded the nine would keep refusing a field the
    // server had released, which is the same defect wearing the opposite sign.
    serve(BASE_SETTINGS, {
      ...PROJECT_ADMIN,
      platform_tier_settings: PLATFORM_TIER_SETTINGS.filter((f) => f !== 'llm_mode'),
    })
    renderSettings()

    await waitFor(() => expect(controlFor('llm_mode')).toBeEnabled())
    expect(controlFor('local_deep_model')).toBeDisabled()
  })

  it('says why the controls are greyed out, wherever they are greyed out', async () => {
    // A disabled control with no reason beside it reads as a bug, and the operator's next
    // move is to report the page rather than to ask somebody. One note per locked group -
    // the mode, the models, the override - rather than one per field.
    serve(BASE_SETTINGS, PROJECT_ADMIN)
    renderSettings()
    // Settled first: before /my-permissions answers every control is locked, so every note
    // renders and the count is of the loading state rather than of the answer.
    await waitFor(() => expect(controlFor('slack_channel')).toBeEnabled())

    const notes = screen.getAllByText(/only an org admin or above may change/i)
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

// ── The form cannot be saved before it has been loaded ───────────────────────────────────
//
// This task's whole hazard analysis is "a value that goes missing means `false` on the
// server, and `false` widens". It stopped at refactors and never asked what the *unloaded
// form* sends. Until `GET /settings` answers, `form` holds DEFAULTS, and the body is a whole
// settings model - so an early Save does not save nothing, it saves standard mode, no
// override, a blank sector and stock model ids over whatever the project really is. A
// platform-tier caller's is accepted, because they genuinely may change all of it.
describe('Settings - an unloaded form cannot be saved over a loaded project', () => {
  const realAdapter = apiClient.defaults.adapter

  afterEach(() => {
    apiClient.defaults.adapter = realAdapter
  })

  const STORED: ProjectSettings = {
    ...BASE_SETTINGS,
    llm_mode: 'sensitive',
    force_local_inference: true,
    dev_mode: false,
    sector: 'defence',
    local_deep_model: 'a-model-somebody-chose',
  }

  it('refuses the click, rather than sending the defaults', async () => {
    const patched: ProjectSettings[] = []
    let releaseSettings: (() => void) | null = null
    const held = new Promise<void>((resolve) => { releaseSettings = resolve })
    apiClient.defaults.adapter = async (config: AxiosRequestConfig) => {
      const url = apiClient.getUri(config)
      if (config.method?.toLowerCase() === 'patch') {
        patched.push(JSON.parse(config.data as string) as ProjectSettings)
        return ok(config, STORED)
      }
      if (url.endsWith('/my-permissions')) return ok(config, PLATFORM_TIER)
      await held
      return ok(config, STORED)
    }
    renderSettings()

    // Platform tier, so nothing refuses this caller downstream - the button is the control.
    await waitFor(() => expect(save()).toBeDisabled())
    fireEvent.click(save())
    expect(patched, 'a Save before the settings arrived reached the server').toHaveLength(0)

    releaseSettings!()
    await waitFor(() => expect(save()).toBeEnabled())
  })

  it('sends what the project actually holds once it has loaded', async () => {
    // The control: the button is not simply dead. Asserted field by field, because the
    // failure this guards is precisely a body that is *well-formed and wrong*.
    const wire = serve(STORED, PLATFORM_TIER)
    renderSettings()
    await settingsHaveLoaded()

    fireEvent.click(save())

    await waitFor(() => expect(wire.patched).toHaveLength(1))
    expect(wire.patched[0]).toMatchObject({
      llm_mode: 'sensitive',
      force_local_inference: true,
      dev_mode: false,
      sector: 'defence',
      local_deep_model: 'a-model-somebody-chose',
    })
  })
})

// ── dev_mode: declared, and carried ──────────────────────────────────────────────────────
describe('Settings - dev_mode survives a save it has no control for', () => {
  const realAdapter = apiClient.defaults.adapter

  afterEach(() => {
    apiClient.defaults.adapter = realAdapter
  })

  it('carries a stored dev_mode: false through an unrelated save', async () => {
    // The same hazard as force_local_inference, one field over, and it was still open after
    // that one was closed: dev_mode is platform-tier, travels on this body, and had no
    // declaration and no test. Dropping it means `true` on the server - the outbound-mail
    // hold silently switches back on, which is the failure that looks exactly like the
    // setting working.
    const wire = serve({ ...BASE_SETTINGS, dev_mode: false }, PLATFORM_TIER)
    renderSettings()
    await settingsHaveLoaded()

    fireEvent.change(budget(), { target: { value: '15' } })
    fireEvent.click(save())

    await waitFor(() => expect(wire.patched).toHaveLength(1))
    expect(wire.patched[0].dev_mode).toBe(false)
    expect(Object.keys(wire.patched[0])).toContain('dev_mode')
  })
})

// ── The declarations themselves ──────────────────────────────────────────────────────────
//
// `tsc --noEmit` is the only thing that can see a type, and it had nothing to say about these
// two: deleting the field is caught loudly, but *optionalising* it - `force_local_inference?:
// boolean` - left tsc clean and the suite green, because vitest strips types. The comment on
// the field was the entire guard.
//
// These are compile-time assertions and carry no runtime behaviour. Making either field
// optional resolves MustBeRequired to `never`, and `const x: never = true` is an error - so
// the check fires in `npx tsc --noEmit`, not in this suite's output.
type MustBeRequired<T, K extends keyof T> = undefined extends T[K] ? never : true

const _forceLocalInferenceStaysRequired: MustBeRequired<
  ProjectSettings, 'force_local_inference'
> = true
const _devModeStaysRequired: MustBeRequired<ProjectSettings, 'dev_mode'> = true

describe('Settings - the fields that must not become optional', () => {
  it('holds force_local_inference and dev_mode as required on ProjectSettings', () => {
    // The assertions are the two consts above, checked by tsc rather than here. This test
    // exists so the mechanism is visible in the suite rather than being two unreferenced
    // declarations a tidy-up would delete as dead code.
    expect(_forceLocalInferenceStaysRequired && _devModeStaysRequired).toBe(true)
  })
})
