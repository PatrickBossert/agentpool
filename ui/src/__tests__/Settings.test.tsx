// ui/src/__tests__/Settings.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import Settings from '../pages/Settings'
import type { ProjectSettings } from '../types'
import { PLATFORM_TIER_SETTINGS } from './fixtures/platformTierSettings'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getSettings: vi.fn(),
    updateSettings: vi.fn(),
    getMyPermissions: vi.fn(),
  },
}))

const BASE_SETTINGS: ProjectSettings = {
  llm_mode: 'standard',
  force_local_inference: false,
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
  dev_mode: true,
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

function Wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/acme-rail/settings']}>
        <Routes>
          <Route path="/:slug/settings" element={<Settings />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('Settings - press budget', () => {
  beforeEach(() => {
    vi.mocked(projectsApi.getSettings).mockResolvedValue(BASE_SETTINGS)
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      can_review: true,
      can_approve: true,
      can_grant_roles: false,
      can_issue_invite_links: true,
      can_change_platform_tier_settings: true,
      can_administer_project: true,
      // The server's real list. This caller may change them all, so nothing locks - but the
      // page now disables a control by asking this list, and a fixture that shipped an empty
      // one would exercise a page that never locks anything.
      platform_tier_settings: PLATFORM_TIER_SETTINGS,
      writable_knowledge_tiers: ['project'],
    })
  })

  it('sends the press budget when the form is saved', async () => {
    // Rendered is not sent. CLAUDE.md records a radio on this page that was tested as
    // rendered and shipped without ever being transmitted.
    const saved = vi.fn().mockResolvedValue({})
    vi.mocked(projectsApi.updateSettings).mockImplementation(saved)
    render(<Wrapper />)
    const input = await screen.findByLabelText(/follow-up time limit/i)
    // Wait for the loaded settings to land before editing, otherwise the query's
    // resolution can race the edit and clobber it back to the default.
    await waitFor(() => expect(input).toHaveValue(8))
    fireEvent.change(input, { target: { value: '15' } })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() =>
      expect(saved).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ elaboration_press_timeout_seconds: 15 }),
      ))
  })

  it('reads back a saved press budget', async () => {
    vi.mocked(projectsApi.getSettings).mockResolvedValue({
      ...BASE_SETTINGS,
      elaboration_press_timeout_seconds: 22,
    })
    render(<Wrapper />)
    const input = await screen.findByLabelText(/follow-up time limit/i)
    await waitFor(() => expect(input).toHaveValue(22))
  })

  it('sends the local deep model when the form is saved', async () => {
    // Rendered is not sent - see the comment on the press budget test above.
    const saved = vi.fn().mockResolvedValue({})
    vi.mocked(projectsApi.updateSettings).mockImplementation(saved)
    render(<Wrapper />)
    const input = await screen.findByLabelText(/local deep model/i)
    // This is a platform-tier field, so it renders disabled until /my-permissions says who
    // the caller is - an unanswered question locks. `fireEvent.change` on a disabled input
    // is silently ignored, so without this wait the edit would race the answer and the test
    // would assert against an unedited form. Same shape as the load barrier in
    // SettingsLocalInference.test.tsx.
    await waitFor(() => expect(input).toBeEnabled())
    fireEvent.change(input, { target: { value: 'qwen27b:reasoning' } })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() =>
      expect(saved).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ local_deep_model: 'qwen27b:reasoning' }),
      ))
  })
})
