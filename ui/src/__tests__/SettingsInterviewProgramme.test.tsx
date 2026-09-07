// ui/src/__tests__/SettingsInterviewProgramme.test.tsx
//
// `interviewer_selection` - the setting that decides who conducts this project's interviews.
//
// It was a real `ProjectSettings` field on the server with **no control anywhere and no
// declaration in types.ts**, surviving a save only as an untyped extra key the
// `{ ...DEFAULTS, ...settings }` spread happened to copy. That is exactly the state
// `force_local_inference` was in, and then `dev_mode` one field over, so this file asserts
// the same two properties those earned:
//
// `interview_accent` was the second field here and is **retired** in sp64, model and type
// together: it decided nothing about any interview, and its one effect was to open every
// voice picker filtered to `british`, showing 6 of the account's 41 voices. The accent now
// lives on the picker as an opt-in narrowing beside a language control, which is where the
// two properties below are asserted for it - on what the picker *sends*.
//
//   1. a stored value survives an **unrelated** save - the drop is silent and its
//      consequence is a Scottish engagement quietly reset to british;
//   2. a change made in the control is the value that goes **on the wire**, not merely the
//      one that renders. CLAUDE.md records a radio on this very page that was tested as
//      rendered and shipped without ever being transmitted.
//
// The declaration half is guarded from Python, in
// tests/test_settings_platform_tier_wiring.py: vitest strips types and can say nothing about
// them, which is precisely why the comment on the field was the whole guard last time.
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { projectsApi } from '../api/endpoints'
import Settings from '../pages/Settings'
import type { MyPermissions, ProjectSettings } from '../types'
import { PLATFORM_TIER_SETTINGS } from './fixtures/platformTierSettings'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getSettings: vi.fn(),
    updateSettings: vi.fn(),
    getMyPermissions: vi.fn(),
  },
}))

const BASE: ProjectSettings = {
  llm_mode: 'standard',
  force_local_inference: false,
  dev_mode: true,
  locale: 'GB',
  sector: '',
  stakeholder_groups: [],
  value_stream_labels: [],
  roadmap_time_axis: 'quarters',
  review_gates: true,
  slack_channel: '',
  discovery_brief: '',
  discovery_links: [],
  discovery_document_ids: [],
  interview_method: 'none',
  interviewer_selection: 'random',
  elaboration_press_timeout_seconds: 8,
  anthropic_fast_model: 'anthropic/claude-haiku-4-5-20251001',
  anthropic_deep_model: 'anthropic/claude-opus-4-6',
  local_fast_model: 'gemma4:fast',
  local_fast_url: 'http://localhost:11434/v1',
  local_deep_model: 'qwen27b:reasoning',
  local_deep_url: 'http://localhost:11434/v1',
}

const PERMISSIONS: MyPermissions = {
  can_review: true,
  can_approve: true,
  can_grant_roles: false,
  can_issue_invite_links: true,
  can_change_platform_tier_settings: true,
  platform_tier_settings: PLATFORM_TIER_SETTINGS,
  can_administer_project: true,
  writable_knowledge_tiers: ['project'],
}

function renderSettings() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/acme-rail/settings']}>
        <Routes>
          <Route path="/:slug/settings" element={<Settings />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const who = () => screen.getByLabelText('Who conducts the interview')
const budget = () => screen.getByLabelText(/follow-up time limit/i)
const save = () => screen.getByRole('button', { name: /save/i })

/** The body the page actually PATCHed. */
function sent(): ProjectSettings {
  return vi.mocked(projectsApi.updateSettings).mock.calls[0][1]
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(projectsApi.getMyPermissions).mockResolvedValue(PERMISSIONS)
  vi.mocked(projectsApi.updateSettings).mockResolvedValue(BASE)
})

describe("the interview programme's setting", () => {
  it('renders the stored value rather than the shipped default', async () => {
    vi.mocked(projectsApi.getSettings).mockResolvedValue({
      ...BASE, interviewer_selection: 'always_female',
    })
    renderSettings()

    await waitFor(() => expect(who()).toHaveValue('always_female'))
  })

  it('carries a stored choice of interviewer through an unrelated save', async () => {
    // The defect this closes, in the form it would actually have arrived in: nobody touches
    // who conducts the interview, somebody edits the follow-up budget, and the next session
    // is assigned by a coin toss by a system that reported success. There is no error and no
    // 403 - this field is not platform-tier - so a dropped key is simply the server's own
    // default written over the project's choice.
    vi.mocked(projectsApi.getSettings).mockResolvedValue({
      ...BASE, interviewer_selection: 'always_female',
    })
    renderSettings()

    await waitFor(() => expect(budget()).toBeEnabled())
    await waitFor(() => expect(budget()).toHaveValue(8))
    fireEvent.change(budget(), { target: { value: '15' } })
    fireEvent.click(save())

    await waitFor(() => expect(projectsApi.updateSettings).toHaveBeenCalled())
    expect(sent().interviewer_selection).toBe('always_female')
    // Present as a key, not merely equal by coincidence: an absent key and a key holding the
    // default are indistinguishable when the stored value happens to be the default, and this
    // is the assertion that stays honest if the fixture ever changes.
    expect(Object.keys(sent())).toContain('interviewer_selection')
  })

  it('no longer sends a retired interview accent', async () => {
    // The half of a retirement that is invisible without an assertion. A key left in
    // `DEFAULTS` or on `ProjectSettings` here still rides every save, reaches a server that
    // models no such field, and is silently dropped - which looks exactly like working.
    // Asserted on what is sent, because nothing renders either way.
    vi.mocked(projectsApi.getSettings).mockResolvedValue(BASE)
    renderSettings()

    await waitFor(() => expect(budget()).toBeEnabled())
    fireEvent.click(save())

    await waitFor(() => expect(projectsApi.updateSettings).toHaveBeenCalled())
    expect(Object.keys(sent())).not.toContain('interview_accent')
    expect(screen.queryByLabelText('Interview accent')).toBeNull()
  })

  it('sends the interviewer selection that was chosen', async () => {
    vi.mocked(projectsApi.getSettings).mockResolvedValue(BASE)
    renderSettings()

    await waitFor(() => expect(who()).toBeEnabled())
    fireEvent.change(who(), { target: { value: 'always_male' } })
    fireEvent.click(save())

    await waitFor(() => expect(projectsApi.updateSettings).toHaveBeenCalled())
    expect(sent().interviewer_selection).toBe('always_male')
  })

  it('leaves it editable for a caller refused the platform-tier fields', async () => {
    // It is not on `_PLATFORM_TIER_SETTINGS`: it decides the tone of a conversation, not
    // where this engagement's material is sent. A project_admin configures their own
    // interview programme, and gating this would have been a rule invented on this page that
    // the server does not hold.
    vi.mocked(projectsApi.getSettings).mockResolvedValue(BASE)
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      ...PERMISSIONS, can_change_platform_tier_settings: false,
    })
    renderSettings()

    await waitFor(() => expect(who()).toBeEnabled())
    // The control that proves the fixture really is a refused caller. Without it, "these two
    // are enabled" would pass just as well against a page that locks nothing at all.
    expect(screen.getByLabelText('LLM Mode')).toBeDisabled()
  })
})
