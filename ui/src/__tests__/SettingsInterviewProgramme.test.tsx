// ui/src/__tests__/SettingsInterviewProgramme.test.tsx
//
// `interviewer_selection` and `interview_accent` - the two settings that decide who conducts
// this project's interviews and in what accent.
//
// Both were real `ProjectSettings` fields on the server with **no control anywhere and no
// declaration in types.ts**, surviving a save only as untyped extra keys the
// `{ ...DEFAULTS, ...settings }` spread happened to copy. That is exactly the state
// `force_local_inference` was in, and then `dev_mode` one field over, so this file asserts
// the same two properties those earned:
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
  interview_accent: 'british',
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

const accent = () => screen.getByLabelText('Interview accent')
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

describe("the interview programme's two settings", () => {
  it('renders the stored values rather than the shipped defaults', async () => {
    vi.mocked(projectsApi.getSettings).mockResolvedValue({
      ...BASE, interviewer_selection: 'always_female', interview_accent: 'scottish',
    })
    renderSettings()

    await waitFor(() => expect(accent()).toHaveValue('scottish'))
    expect(who()).toHaveValue('always_female')
  })

  it('carries a stored Scottish accent through an unrelated save', async () => {
    // The defect this closes, in the form it would actually have arrived in: nobody touches
    // the accent, somebody edits the follow-up budget, and the next interview is conducted in
    // the wrong accent by a system that reported success. There is no error and no 403 -
    // neither of these fields is platform-tier - so a dropped key is simply the server's own
    // default written over the project's choice.
    vi.mocked(projectsApi.getSettings).mockResolvedValue({
      ...BASE, interviewer_selection: 'always_female', interview_accent: 'scottish',
    })
    renderSettings()

    await waitFor(() => expect(budget()).toBeEnabled())
    await waitFor(() => expect(budget()).toHaveValue(8))
    fireEvent.change(budget(), { target: { value: '15' } })
    fireEvent.click(save())

    await waitFor(() => expect(projectsApi.updateSettings).toHaveBeenCalled())
    expect(sent().interview_accent).toBe('scottish')
    expect(sent().interviewer_selection).toBe('always_female')
    // Present as keys, not merely equal by coincidence: an absent key and a key holding the
    // default are indistinguishable when the stored value happens to be the default, and this
    // is the assertion that stays honest if the fixture ever changes.
    expect(Object.keys(sent())).toContain('interview_accent')
    expect(Object.keys(sent())).toContain('interviewer_selection')
  })

  it('sends the accent that was typed, not the one that was rendered', async () => {
    vi.mocked(projectsApi.getSettings).mockResolvedValue(BASE)
    renderSettings()

    await waitFor(() => expect(accent()).toBeEnabled())
    fireEvent.change(accent(), { target: { value: 'irish' } })
    fireEvent.click(save())

    await waitFor(() => expect(projectsApi.updateSettings).toHaveBeenCalled())
    expect(sent().interview_accent).toBe('irish')
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

  it('lets the accent be cleared to every accent', async () => {
    // `''` is a real value on the server - it means "search every accent" - so the control
    // has to be able to reach it. A control that could not would make the empty state
    // unreachable from the only place it is offered.
    vi.mocked(projectsApi.getSettings).mockResolvedValue({ ...BASE, interview_accent: 'irish' })
    renderSettings()

    await waitFor(() => expect(accent()).toHaveValue('irish'))
    fireEvent.change(accent(), { target: { value: '' } })
    fireEvent.click(save())

    await waitFor(() => expect(projectsApi.updateSettings).toHaveBeenCalled())
    expect(sent().interview_accent).toBe('')
  })

  it('leaves both editable for a caller refused the platform-tier fields', async () => {
    // Neither is on `_PLATFORM_TIER_SETTINGS`: they decide the tone of a conversation, not
    // where this engagement's material is sent. A project_admin configures their own
    // interview programme, and gating these would have been a rule invented on this page that
    // the server does not hold.
    vi.mocked(projectsApi.getSettings).mockResolvedValue(BASE)
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      ...PERMISSIONS, can_change_platform_tier_settings: false,
    })
    renderSettings()

    await waitFor(() => expect(accent()).toBeEnabled())
    expect(who()).toBeEnabled()
    // The control that proves the fixture really is a refused caller. Without it, "these two
    // are enabled" would pass just as well against a page that locks nothing at all.
    expect(screen.getByLabelText('LLM Mode')).toBeDisabled()
  })
})
