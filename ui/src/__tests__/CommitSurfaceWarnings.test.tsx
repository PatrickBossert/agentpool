// ui/src/__tests__/CommitSurfaceWarnings.test.tsx
//
// The A+B design assumed the review dialog was where a reviewer decides, and mounted the
// warnings there. These crews no longer raise a review: since a3906d15 they finish rather
// than blocking for a typed approval, and the review queue stays empty. The decision now
// happens on the commit surface, so that is where the disposition controls have to be -
// warnings mounted only on a surface nobody reaches are warnings nobody sees.
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { CrewApprovalRowWithChanges } from '../pages/Reviews'
import { validationsApi, commitsApi } from '../api/endpoints'

vi.mock('../api/endpoints', () => ({
  validationsApi: { list: vi.fn(), dispose: vi.fn() },
  commitsApi: { changeCount: vi.fn() },
  projectsApi: {},
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

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(commitsApi.changeCount).mockResolvedValue(0)
})

describe('warnings on the commit surface', () => {
  it('shows a crew its structural warnings before it is committed', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([WARNING])
    wrap(
      <CrewApprovalRowWithChanges
        slug="p" crewName="discovery_mapping" state="ready"
        onSubmit={() => {}} onApprove={() => {}}
      />,
    )
    expect(await screen.findByText(/no root node/)).toBeInTheDocument()
  })

  it('offers the disposition controls, because this is where the decision is made', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([WARNING])
    wrap(
      <CrewApprovalRowWithChanges
        slug="p" crewName="discovery_mapping" state="ready"
        onSubmit={() => {}} onApprove={() => {}}
      />,
    )
    expect(await screen.findByRole('button', { name: /acknowledge/i })).toBeInTheDocument()
  })

  it('asks for warnings from the source this crew owns', async () => {
    vi.mocked(validationsApi.list).mockResolvedValue([])
    wrap(
      <CrewApprovalRowWithChanges
        slug="p" crewName="discovery_interviews" state="ready"
        onSubmit={() => {}} onApprove={() => {}}
      />,
    )
    await waitFor(() =>
      expect(validationsApi.list).toHaveBeenCalledWith('p', 'theme_anchor'))
  })

  it('asks for nothing on a crew that raises no structural warnings', async () => {
    wrap(
      <CrewApprovalRowWithChanges
        slug="p" crewName="business_plan" state="ready"
        onSubmit={() => {}} onApprove={() => {}}
      />,
    )
    await waitFor(() => expect(commitsApi.changeCount).toHaveBeenCalled())
    expect(validationsApi.list).not.toHaveBeenCalled()
  })
})
