// ui/src/__tests__/StakeholdersSeededBadge.test.tsx
//
// A seeded row says so on the roster.
//
// `stakeholders.is_synthetic` is a column no ordinary edit can set or clear - the insert
// helper takes no such parameter and the updatable-field whitelist omits it - which is what
// makes the removal script's predicate trustworthy. It reached the client and was rendered
// nowhere, and this is the screen somebody audits before the real engagement begins: on the
// test project sixty of the sixty-two rows are seeded, and every one of them looked exactly
// like a real person.
import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import Stakeholders from '../pages/Stakeholders'
import { projectsApi, stakeholdersApi } from '../api/endpoints'
import type { Stakeholder } from '../types'

vi.mock('../api/endpoints', () => ({
  projectsApi: { getMyPermissions: vi.fn() },
  stakeholdersApi: { list: vi.fn(), resendInvite: vi.fn(), importCsv: vi.fn() },
}))

function person(id: number, name: string, is_synthetic?: boolean): Stakeholder {
  return { id, name, job_title: 'Analyst', entity: 'GS UK', is_synthetic } as Stakeholder
}

const ROSTER: Stakeholder[] = [
  person(1, 'Patrick Bossert'),
  person(2, 'Seeded Sam', true),
  person(3, 'Undeclared Una', false),
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

describe('Stakeholders: a seeded row says so', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(stakeholdersApi.list).mockResolvedValue(ROSTER)
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      can_review: true, can_approve: true, can_grant_roles: false,
      can_issue_invite_links: false,
      can_change_platform_tier_settings: false,
      platform_tier_settings: [],
      // Not what these tests are about - the invite-link action does not read it.
      writable_knowledge_tiers: ['project'],
    })
  })

  it('marks the seeded row and only the seeded row', async () => {
    renderRoster()
    await screen.findByText('Seeded Sam')

    expect(within(rowFor('Seeded Sam')).getByText('seeded')).toBeInTheDocument()
    expect(within(rowFor('Patrick Bossert')).queryByText('seeded')).not.toBeInTheDocument()
    expect(within(rowFor('Undeclared Una')).queryByText('seeded')).not.toBeInTheDocument()
  })
})
