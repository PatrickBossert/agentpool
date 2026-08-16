// ui/src/__tests__/StakeholderFormGrantableRoles.test.tsx
//
// project_admin and governor became grantable in sp44, and the form has to offer them only
// to a caller the server would accept - GET /my-permissions' can_grant_roles. A checkbox
// that always 403s is worse than no checkbox.
//
// The second half matters more than the first, and is the part a "does it render?" test
// cannot see: a caller who may *not* grant must not send the two keys at all. The form posts
// its whole state, so an org_admin editing a job title on somebody who already holds
// project_admin would otherwise resend is_project_admin: true - a grant they are refused,
// on a request that changed nothing about the role. Asserting on what is *sent* rather than
// on what is rendered is the same distinction CLAUDE.md records for the radio that was
// tested as rendered and not as sent.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import StakeholderForm from '../pages/StakeholderForm'
import { projectsApi, stakeholdersApi } from '../api/endpoints'

vi.mock('../api/endpoints', () => ({
  valueChainApi: { get: vi.fn().mockResolvedValue({ model: { parties: [] } }) },
  projectsApi: {
    getSettings: vi.fn().mockResolvedValue({ stakeholder_groups: [] }),
    getValueChainRegistry: vi.fn().mockResolvedValue({ activities: [] }),
    getMyPermissions: vi.fn(),
  },
  stakeholdersApi: { list: vi.fn(), create: vi.fn(), update: vi.fn() },
}))

const EXISTING = {
  id: 7,
  name: 'Rae Bell',
  job_title: 'Head of Audit',
  organisation: '',
  email: 'rae@example.com',
  slack_handle: '',
  mobile: '',
  stakeholder_groups: [],
  project_role: 'recipient',
  value_streams: [],
  value_chain_stage: '',
  activity: '',
  disposition: 'neutral',
  location: '',
  country_code: '',
  timezone: '',
  preferred_language: '',
  currency: '',
  level: '',
  entity: '',
  comms_channel: 'email',
  is_participant: false,
  is_reviewer: true,
  is_approver: false,
  // Already holds it. This is the row the "do not resend" assertion turns on.
  is_project_admin: true,
  is_governor: false,
  interview_status: null,
  interview_invited_at: null,
  interview_completed_at: null,
  created_at: '2026-08-01',
}

function renderEditForm() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/acme/stakeholders/7']}>
        <Routes>
          <Route path="/:slug/stakeholders/:id" element={<StakeholderForm />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('StakeholderForm: the two grantable roles', () => {
  beforeEach(() => {
    // clearAllMocks, not merely re-stubbing the return values: this project does not set
    // `clearMocks` globally, so call history accumulates across tests in a file. Without
    // it the last test below read `update.mock.calls[0]` and got the *previous* test's
    // call - the one made by a caller who may grant - and failed against a payload the
    // code under test never produced. A green run on that arrangement would have been
    // worse than the red one.
    vi.clearAllMocks()
    vi.mocked(stakeholdersApi.list).mockResolvedValue([EXISTING] as never)
    vi.mocked(stakeholdersApi.update).mockResolvedValue(EXISTING as never)
  })

  it('offers the two roles to a caller who may grant them', async () => {
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue(
      { can_review: true, can_approve: true, can_grant_roles: true } as never,
    )
    renderEditForm()

    expect(await screen.findByText('Project Administrator')).toBeInTheDocument()
    expect(screen.getByText('Governor')).toBeInTheDocument()
  })

  it('hides them from a caller who may not, rather than offering a control that 403s', async () => {
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue(
      { can_review: true, can_approve: true, can_grant_roles: false } as never,
    )
    renderEditForm()

    // The three unconditional roles establish the form actually rendered - without this the
    // assertion below would pass on a blank page.
    expect(await screen.findByText('Milestone Approver')).toBeInTheDocument()
    expect(screen.queryByText('Project Administrator')).not.toBeInTheDocument()
    expect(screen.queryByText('Governor')).not.toBeInTheDocument()
  })

  it('sends the two flags when the caller may grant them', async () => {
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue(
      { can_review: true, can_approve: true, can_grant_roles: true } as never,
    )
    renderEditForm()
    await screen.findByText('Project Administrator')

    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => expect(stakeholdersApi.update).toHaveBeenCalled())
    const body = vi.mocked(stakeholdersApi.update).mock.calls[0][2]
    expect(body).toHaveProperty('is_project_admin', true)
    expect(body).toHaveProperty('is_governor', false)
  })

  it('omits them entirely when the caller may not, so an unrelated edit is not a refused grant', async () => {
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue(
      { can_review: true, can_approve: true, can_grant_roles: false } as never,
    )
    renderEditForm()
    await screen.findByText('Milestone Approver')

    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => expect(stakeholdersApi.update).toHaveBeenCalled())
    const body = vi.mocked(stakeholdersApi.update).mock.calls[0][2]
    // Not "is false" - absent. The server treats a key it was not sent as "leave that
    // column alone", and sending `false` here would silently revoke a role this caller
    // never asked to touch, on a job-title edit.
    expect(body).not.toHaveProperty('is_project_admin')
    expect(body).not.toHaveProperty('is_governor')
    // And the rest of the record still goes, so this is an omission rather than a broken save.
    expect(body).toHaveProperty('is_reviewer', true)
    expect(body).toHaveProperty('name', 'Rae Bell')
  })
})
