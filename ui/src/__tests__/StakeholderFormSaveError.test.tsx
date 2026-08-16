// ui/src/__tests__/StakeholderFormSaveError.test.tsx
//
// _validate_deliverable_role's 422 is the only thing in the product that tells an
// administrator they have just created a role nobody can be invited to - a reviewer or an
// approver with no address the invite could be delivered to. The form swallowed it into
// "Save failed. Please try again.", which reads as a transient fault and invites exactly
// the retry that reproduces it.
//
// Same describeError shape as ScriptReviewPanel.tsx and MayaOutputExtra.tsx: axios.isAxiosError
// for the narrowing, err.response?.data?.detail for the server's own words, a fixed string
// only when there are none.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AxiosError, AxiosHeaders } from 'axios'

import StakeholderForm from '../pages/StakeholderForm'

vi.mock('../api/endpoints', () => ({
  valueChainApi: { get: vi.fn().mockResolvedValue({ model: { parties: [] } }) },
  projectsApi: {
    getSettings: vi.fn().mockResolvedValue({ stakeholder_groups: ['Operations'] }),
    getValueChainRegistry: vi.fn().mockResolvedValue({ activities: [] }),
    // The form asks this before deciding whether to offer the project_admin and
    // governor checkboxes. Stubbed so the query resolves rather than throwing on an
    // unmocked call - these tests are not about that gate, but an unmocked module
    // export is a rejected promise the component would otherwise be rendering under.
    getMyPermissions: vi.fn().mockResolvedValue(
      { can_review: false, can_approve: false, can_grant_roles: false },
    ),
  },
  stakeholdersApi: { list: vi.fn().mockResolvedValue([]), create: vi.fn() },
}))

const UNDELIVERABLE =
  'email is required to invite a stakeholder holding a role beyond participant'

// A genuine AxiosError, not a hand-rolled object with a `.response` property: describeError
// narrows through axios.isAxiosError, which checks isAxiosError on the instance. A stand-in
// that merely looked the right shape would pass a test against a describeError written to
// read `.response` directly - and then fail against the real one, on the real request path.
function axios422(detail: string): AxiosError {
  const headers = new AxiosHeaders()
  const config = { headers }
  return new AxiosError(
    'Request failed with status code 422',
    'ERR_BAD_REQUEST',
    config as never,
    {},
    {
      status: 422,
      statusText: 'Unprocessable Entity',
      data: { detail },
      headers: {},
      config: config as never,
    },
  )
}

function renderForm() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/acme/stakeholders/new']}>
        <Routes>
          <Route path="/:slug/stakeholders/new" element={<StakeholderForm />} />
          <Route path="/:slug/stakeholders" element={<div>stakeholder-list</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function fillAndSave() {
  // The form's Field helper renders a <label> beside its input rather than around or for
  // it, so there is nothing for getByLabelText to follow - reached through the label's
  // text instead. Name is filled because handleSave refuses an empty one locally, and this
  // test is about what happens to the server's refusal, not the client's.
  await waitFor(() => expect(screen.getByText(/full name/i)).toBeInTheDocument())
  const name = screen.getByText(/full name/i).parentElement!.querySelector('input')!
  await userEvent.type(name, 'Dougie McCrone')
  await userEvent.click(screen.getByRole('button', { name: /save stakeholder/i }))
}

describe('a refused stakeholder save', () => {
  it("shows the server's reason rather than a fixed retry message", async () => {
    const { stakeholdersApi } = await import('../api/endpoints')
    vi.mocked(stakeholdersApi.create).mockRejectedValue(axios422(UNDELIVERABLE))

    renderForm()
    await fillAndSave()

    expect(await screen.findByText(UNDELIVERABLE)).toBeInTheDocument()
    expect(screen.queryByText(/please try again/i)).not.toBeInTheDocument()
  })

  it('falls back to the fixed string when the failure carries no explanation', async () => {
    // A network drop, or any non-axios throw: there is nothing to show, and inventing a
    // reason would be worse than admitting there is none.
    const { stakeholdersApi } = await import('../api/endpoints')
    vi.mocked(stakeholdersApi.create).mockRejectedValue(new Error('Network Error'))

    renderForm()
    await fillAndSave()

    expect(await screen.findByText(/save failed\. please try again\./i)).toBeInTheDocument()
  })
})
