// ui/src/__tests__/ValidationWarnings.test.tsx
//
// The review dialog is the load-bearing surface: it is where a reviewer chooses approve or
// changes_requested, and a warning they never see cannot inform that decision.
//
// The dismissal control is the part worth testing hardest. A dismissal with no reason is
// indistinguishable from nobody looking, so the UI must not let one be sent - the API
// refuses it, and a form that lets a reviewer try is a form that wastes their time.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import ValidationWarnings from '../components/ValidationWarnings'
import { validationsApi } from '../api/endpoints'

vi.mock('../api/endpoints', () => ({
  validationsApi: { list: vi.fn(), dispose: vi.fn() },
}))

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const WARNING = {
  id: 1,
  source: 'value_chain_tree',
  subject: null,
  code: 'missing_l0',
  detail: "the tree has no root node with id '0'",
  measure: null,
  disposition: 'open' as const,
  disposition_note: null,
}

beforeEach(() => vi.clearAllMocks())

describe('ValidationWarnings', () => {
  it('shows the detail and the code of an open warning', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([WARNING])
    wrap(<ValidationWarnings slug="p" source="value_chain_tree" />)
    expect(await screen.findByText(/no root node/)).toBeInTheDocument()
    expect(screen.getByText(/missing_l0/)).toBeInTheDocument()
  })

  it('renders nothing when there are no warnings', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([])
    const { container } = wrap(<ValidationWarnings slug="p" source="value_chain_tree" />)
    await waitFor(() => expect(validationsApi.list).toHaveBeenCalled())
    expect(container.textContent).toBe('')
  })

  it('sends the acknowledgement the reviewer chose', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([WARNING])
    vi.mocked(validationsApi.dispose).mockResolvedValue({ id: 1 })
    wrap(<ValidationWarnings slug="p" source="value_chain_tree" />)
    await userEvent.click(await screen.findByRole('button', { name: /acknowledge/i }))
    await waitFor(() =>
      expect(validationsApi.dispose).toHaveBeenCalledWith('p', 1, 'acknowledged', ''))
  })

  it('will not send a dismissal without a reason', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([WARNING])
    wrap(<ValidationWarnings slug="p" source="value_chain_tree" />)
    await userEvent.click(await screen.findByRole('button', { name: /dismiss/i }))
    const send = await screen.findByRole('button', { name: /^dismiss$/i })
    expect(send).toBeDisabled()
    expect(validationsApi.dispose).not.toHaveBeenCalled()
  })

  it('sends the dismissal once a reason is given', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([WARNING])
    vi.mocked(validationsApi.dispose).mockResolvedValue({ id: 1 })
    wrap(<ValidationWarnings slug="p" source="value_chain_tree" />)
    await userEvent.click(await screen.findByRole('button', { name: /dismiss/i }))
    await userEvent.type(await screen.findByRole('textbox'), 'single-entity client')
    await userEvent.click(await screen.findByRole('button', { name: /^dismiss$/i }))
    await waitFor(() =>
      expect(validationsApi.dispose).toHaveBeenCalledWith(
        'p', 1, 'dismissed', 'single-entity client'))
  })

  it('shows a dismissed warning with its recorded reason', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([
      { ...WARNING, disposition: 'dismissed' as const,
        disposition_note: 'single-entity client' },
    ])
    wrap(<ValidationWarnings slug="p" source="value_chain_tree" />)
    expect(await screen.findByText(/single-entity client/)).toBeInTheDocument()
  })

  it('says an acknowledged warning is carried into the next run', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([
      { ...WARNING, disposition: 'acknowledged' as const, disposition_note: 'real gap' },
    ])
    wrap(<ValidationWarnings slug="p" source="value_chain_tree" />)
    expect(await screen.findByText(/next run/i)).toBeInTheDocument()
  })

  it('offers no controls when read only', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([WARNING])
    wrap(<ValidationWarnings slug="p" source="value_chain_tree" readOnly />)
    await screen.findByText(/no root node/)
    expect(screen.queryByRole('button', { name: /acknowledge/i })).not.toBeInTheDocument()
  })

  it('names the node a subject-bearing warning is about', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([
      { ...WARNING, code: 'missing_role_node', subject: '1.F',
        detail: '1.F was in the previous registry' },
    ])
    wrap(<ValidationWarnings slug="p" source="value_chain_tree" />)
    // The subject appears both in the code line and inside the detail sentence, so assert
    // on the code line specifically - that is the label a reviewer scans.
    expect(await screen.findByText(/missing_role_node - 1\.F/)).toBeInTheDocument()
  })
})
