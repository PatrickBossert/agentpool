// ui/src/__tests__/StakeholdersInviteLink.test.tsx
//
// The stakeholder roster's two new jobs: saying whether each person can actually get into
// the engagement, and handing an administrator an invite link for the one state that has
// one to hand out.
//
// The gating is the part worth being careful about. `POST .../resend-invite` is
// `require_org_admin_or_above` deliberately - sp44 widened sixteen doors to project_admin
// and put this one back, because its response body is a redeemable credential - so the
// action must be offered only to a caller the server would actually serve. A button that
// 403s for the client's own project administrator is worse than no button, which is the
// same rule StakeholderFormGrantableRoles.test.tsx holds the two role checkboxes to.
//
// The request itself is asserted at the wire in inviteLinkApi.test.ts. Here the question is
// which stakeholder the page asks about: `resendInvite` takes an id, every row has one, and
// a page that passed the wrong one would mint a link for somebody else entirely while
// looking perfectly correct.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import Stakeholders from '../pages/Stakeholders'
import { projectsApi, stakeholdersApi } from '../api/endpoints'
import type { AccessState, Stakeholder } from '../types'

vi.mock('../api/endpoints', () => ({
  projectsApi: { getMyPermissions: vi.fn() },
  stakeholdersApi: { list: vi.fn(), resendInvite: vi.fn(), importCsv: vi.fn() },
}))

function person(id: number, name: string, access_state: AccessState): Stakeholder {
  return {
    id,
    name,
    job_title: '',
    organisation: '',
    email: `${name.toLowerCase().replace(/\s/g, '-')}@example.com`,
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
    is_project_admin: false,
    is_governor: false,
    interview_status: null,
    interview_invited_at: null,
    interview_completed_at: null,
    created_at: '2026-08-01',
    access_state,
  }
}

// One row in each state, so a test asking "is the action offered here?" is always asking it
// against the four states where it must not be, on the same page.
//
// The invited row sits in the middle deliberately. It was first, and that made the "asks
// about the row it was clicked on" assertion blind to half of what it claimed: sending
// `stakeholders[0].id` instead of `s.id` left the whole suite green, and only the
// last-row mutation could fail it. Neither end now stands in for the right answer.
const ROSTER: Stakeholder[] = [
  person(22, 'Lena Loggedin', 'has_login'),
  person(33, 'Una Unreachable', 'unreachable'),
  person(11, 'Ivy Invited', 'invited'),
  person(44, 'Nils Notinvited', 'not_invited'),
  person(55, 'Pat Participant', 'no_login_needed'),
]

function renderRoster() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/acme/stakeholders']}>
        <Routes>
          <Route path="/:slug/stakeholders" element={<Stakeholders />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function rowFor(name: string): HTMLElement {
  return screen.getByText(name).closest('tr') as HTMLElement
}

describe('Stakeholders: invite state and the invite link', () => {
  beforeEach(() => {
    // clearAllMocks rather than merely re-stubbing: this project does not set `clearMocks`
    // globally, so call history accumulates across tests in a file and an assertion on
    // `mock.calls[0]` would read a previous test's call - see the same note in
    // StakeholderFormGrantableRoles.test.tsx, where that arrangement went green on a
    // payload the code under test had never produced.
    vi.clearAllMocks()
    vi.mocked(stakeholdersApi.list).mockResolvedValue(ROSTER)
    vi.mocked(stakeholdersApi.resendInvite).mockResolvedValue({ invite_token: 'tok-abc' })
  })

  it('says which state every stakeholder is in', async () => {
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      can_review: true, can_approve: true, can_grant_roles: false,
      can_issue_invite_links: true,
      // Not what these tests are about - the invite-link action does not read it.
      writable_knowledge_tiers: ['project'],
    })
    renderRoster()
    await screen.findByText('Ivy Invited')

    expect(within(rowFor('Ivy Invited')).getByText('Invited')).toBeInTheDocument()
    expect(within(rowFor('Lena Loggedin')).getByText('Has login')).toBeInTheDocument()
    // The row that motivated the feature: a role nobody can exercise, which until now
    // rendered identically to a working stakeholder.
    expect(within(rowFor('Una Unreachable')).getByText('Unreachable')).toBeInTheDocument()
    expect(within(rowFor('Nils Notinvited')).getByText('Not invited')).toBeInTheDocument()
    expect(within(rowFor('Pat Participant')).getByText('No login needed')).toBeInTheDocument()
  })

  it('shows nothing at all for a row the server sent no state for', async () => {
    // What a caller who may not be told the account-derived states receives: the field is
    // absent from those rows entirely. The page must not fill the gap - a dash or an
    // "unknown" badge would still confirm the row has a state being withheld.
    const { access_state: _dropped, ...withheld } = person(99, 'Withheld Row', 'invited')
    vi.mocked(stakeholdersApi.list).mockResolvedValue([...ROSTER, withheld as Stakeholder])
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      can_review: true, can_approve: true, can_grant_roles: false,
      can_issue_invite_links: true,
      // Not what these tests are about - the invite-link action does not read it.
      writable_knowledge_tiers: ['project'],
    })
    renderRoster()
    await screen.findByText('Withheld Row')

    const cells = within(rowFor('Withheld Row')).getAllByRole('cell')
    // The access cell sits between Roles and Comms; it is empty rather than placeheld.
    expect(cells[4]).toBeEmptyDOMElement()
    expect(
      within(rowFor('Withheld Row')).queryByRole('button', { name: 'Invite link' }),
    ).not.toBeInTheDocument()
  })

  it('offers the action only where the door has something to serve', async () => {
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      can_review: true, can_approve: true, can_grant_roles: false,
      can_issue_invite_links: true,
      // Not what these tests are about - the invite-link action does not read it.
      writable_knowledge_tiers: ['project'],
    })
    renderRoster()

    expect(await screen.findByRole('button', { name: 'Invite link' })).toBeInTheDocument()
    // Exactly one, and on the invited row. The other four answer 404 (nothing live),
    // 409 (already has a login) or nothing at all.
    expect(screen.getAllByRole('button', { name: 'Invite link' })).toHaveLength(1)
    expect(
      within(rowFor('Ivy Invited')).getByRole('button', { name: 'Invite link' }),
    ).toBeInTheDocument()
  })

  it('offers it to nobody when the caller is not on the platform tier', async () => {
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      // A project_admin: administers this engagement, and is refused this door.
      can_review: true, can_approve: true, can_grant_roles: true,
      can_issue_invite_links: false,
      // Not what these tests are about - the invite-link action does not read it.
      writable_knowledge_tiers: ['project'],
    })
    renderRoster()

    // The invited row establishes the page really rendered - without it the assertion
    // below would pass on a blank page, which is the whole hazard of a negative test.
    expect(await screen.findByText('Ivy Invited')).toBeInTheDocument()
    expect(within(rowFor('Ivy Invited')).getByText('Invited')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Invite link' })).not.toBeInTheDocument()
  })

  it('asks for the link of the row it was clicked on, and shows it for copying', async () => {
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      can_review: true, can_approve: true, can_grant_roles: false,
      can_issue_invite_links: true,
      // Not what these tests are about - the invite-link action does not read it.
      writable_knowledge_tiers: ['project'],
    })
    renderRoster()
    const button = await screen.findByRole('button', { name: 'Invite link' })

    await userEvent.click(button)

    // The slug from the route and Ivy's own id. She is neither the first row nor the last,
    // so neither end of the roster can stand in for the right answer - see ROSTER.
    expect(stakeholdersApi.resendInvite).toHaveBeenCalledTimes(1)
    expect(stakeholdersApi.resendInvite).toHaveBeenCalledWith('acme', 11)

    // Rendered into the page rather than into a toast: the server keeps only a digest, so
    // a link lost here is gone, and asking again would kill the one just issued.
    expect(await screen.findByText(/Invite link for Ivy Invited/)).toBeInTheDocument()
    expect(
      screen.getByText(`${window.location.origin}/dashboard/accept-invite/tok-abc`),
    ).toBeInTheDocument()
    // And it says nothing was sent, because the failure mode is an administrator assuming
    // the system did the sending.
    expect(screen.getByText(/Nothing has been emailed/)).toBeInTheDocument()
  })

  it('reports the server’s own refusal rather than a fixed sentence', async () => {
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      can_review: true, can_approve: true, can_grant_roles: false,
      can_issue_invite_links: true,
      // Not what these tests are about - the invite-link action does not read it.
      writable_knowledge_tiers: ['project'],
    })
    // The 409: this person accepted while the page was open. "Try again" would be wrong
    // advice - there is nothing to resend, and the state has genuinely moved on.
    vi.mocked(stakeholdersApi.resendInvite).mockRejectedValue(
      Object.assign(new Error('Request failed'), {
        isAxiosError: true,
        response: {
          status: 409,
          data: {
            detail:
              'this person already has a login linked to this project - nothing to resend',
          },
        },
      }),
    )
    renderRoster()

    await userEvent.click(await screen.findByRole('button', { name: 'Invite link' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'this person already has a login linked to this project - nothing to resend',
    )
  })
})
