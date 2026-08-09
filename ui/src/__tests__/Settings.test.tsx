// ui/src/__tests__/Settings.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import Settings from '../pages/Settings'
import type { ProjectSettings } from '../types'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getSettings: vi.fn(),
    updateSettings: vi.fn(),
  },
}))

const BASE_SETTINGS: ProjectSettings = {
  llm_mode: 'standard',
  locale: 'GB',
  sector: '',
  stakeholder_groups: [],
  value_stream_labels: [],
  roadmap_time_axis: 'quarters',
  crews_enabled: [],
  review_gates: true,
  slack_channel: '',
  discovery_brief: '',
  discovery_links: [],
  discovery_document_ids: [],
  interview_method: 'none',
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
    fireEvent.change(input, { target: { value: 'qwen27b:reasoning' } })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() =>
      expect(saved).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ local_deep_model: 'qwen27b:reasoning' }),
      ))
  })
})
