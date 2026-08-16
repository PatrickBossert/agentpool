// ui/src/__tests__/StakeholderFormOrgs.test.tsx
//
// The organisation list on the stakeholder form used to be recovered by running regular
// expressions over value chain labels - "Custodian: …", "Maintainer: …", and a literal
// match on one client's supplier name. That only worked while labels happened to carry
// the parties inside their prose, and it hard-coded a company into an application meant
// for any client.
//
// Parties are first-class in the model. The list comes from there.
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import StakeholderForm from '../pages/StakeholderForm'

// vi.mock factories hoist above the top of the file, so the fixtures have to be built
// inside vi.hoisted rather than referenced as plain top-level consts.
const { MODEL, REGISTRY } = vi.hoisted(() => ({
  MODEL: {
  model_version: 1,
  parties: [
    { id: 'GSUK', label: 'Group Services (GS)' },
    { id: 'FM', label: 'Facilities Maintainer' },
    { id: 'LEASING', label: 'Leasing Partner' },
  ],
  segments: [{ id: '1', label: 'Property' }],
  activities: [{ id: '1.1', segment_id: '1', label: 'Strategy' }],
  contributions: [
    { activity_id: '1.1', party_id: 'GSUK', column: 10, attribution: 'stated' },
  ],
    tasks: [], propositions: [], links: [],
  },
  // Registry labels deliberately carry NO party names. Under the old prose parsing this
  // would yield an empty list, so the fixture discriminates: any organisation appearing
  // must have come from the model's parties.
  REGISTRY: {
    activities: [
      { id: '1', label: 'Property', level: 'L1', active: true },
      { id: '1.1', label: 'Strategy', level: 'L2', active: true, parent_id: '1' },
      { id: '1.1.1', label: 'Set the strategy', level: 'L3', active: true, parent_id: '1.1' },
    ],
  },
}))

vi.mock('../api/endpoints', () => ({
  valueChainApi: { get: vi.fn().mockResolvedValue({ model: MODEL }) },
  projectsApi: {
    getSettings: vi.fn().mockResolvedValue({ stakeholder_groups: ['Operations'] }),
    getValueChainRegistry: vi.fn().mockResolvedValue(REGISTRY),
    // The form asks this before deciding whether to offer the project_admin and
    // governor checkboxes. Stubbed so the query resolves rather than throwing on an
    // unmocked call - these tests are not about that gate, but an unmocked module
    // export is a rejected promise the component would otherwise be rendering under.
    getMyPermissions: vi.fn().mockResolvedValue(
      { can_review: false, can_approve: false, can_grant_roles: false },
    ),
  },
  stakeholdersApi: { list: vi.fn().mockResolvedValue([]) },
}))

function renderForm() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/acme/stakeholders/new']}>
        <Routes>
          <Route path="/:slug/stakeholders/new" element={<StakeholderForm />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the organisation list', () => {
  it('offers every party in the model, whatever the labels say', async () => {
    renderForm()
    await waitFor(() => {
      for (const label of ['Group Services (GS)', 'Facilities Maintainer', 'Leasing Partner']) {
        expect(screen.getByRole('option', { name: label })).toBeInTheDocument()
      }
    })
  })

  it('offers a party that contributes nowhere yet, because it is still a real party', async () => {
    // LEASING has no contribution in the fixture. The old parsing could only ever surface
    // an organisation that appeared inside some label, so a party on the roster and not
    // yet in the chain was invisible.
    renderForm()
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'Leasing Partner' })).toBeInTheDocument(),
    )
  })
})
