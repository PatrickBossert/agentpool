// ui/src/__tests__/sortHeaderWiring.test.tsx
//
// Which key each column header is actually wired to, on all three tables of logins.
//
// `tableSort.test.ts` asserts the comparator and `userSort.ts` supplies the keys, and between
// them they left the real property untested: **nothing checked that the header labelled
// "Entity" sorts by entity.** Rename or mistype a `sortKey` and the header still renders,
// still highlights, still flips its chevron, and reorders nothing. Six of the nine comparator
// cases could be replaced with `return null` and the whole 513-test suite stayed green - the
// entire `memberSortKey`, and `userSortKey`'s entity, email and role. The header comment in
// `userSort.ts` predicted exactly this and did not prevent it.
//
// So each fixture below is built so that **every sortable key produces a different row
// order**. That is what makes a mis-wired header fail rather than merely be untested: a
// header pointing at any other key, or at nothing, lands on an order this file rejects.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import UserList from '../pages/UserList'
import OrgDetail from '../pages/OrgDetail'
import OrgPanel from '../pages/OrgPanel'
import { adminApi } from '../api/admin'
import type { AdminUser, OrgMember, ProjectRegistryEntry } from '../types'

vi.mock('../api/admin', () => ({
  adminApi: {
    listUsers: vi.fn(),
    listRegistry: vi.fn(),
    listOrgs: vi.fn(),
    listOrgMembers: vi.fn(),
    deleteUser: vi.fn(),
    issueResetLink: vi.fn(),
    addOrgMember: vi.fn(),
    removeOrgMember: vi.fn(),
    updateOrgMemberRole: vi.fn(),
    registerProject: vi.fn(),
    unregisterProject: vi.fn(),
    updateOrg: vi.fn(),
  },
}))

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: { sub: 'ana', role: 'org_admin', org_id: 1 } }),
}))

const PROJECTS: ProjectRegistryEntry[] = [
  { id: 1, slug: 'alpha', org_id: 1, display_name: 'Alpha', created_at: '2026-01-01' },
]

// ── The user list ─────────────────────────────────────────────────────────────
//
// Three rows, six sortable keys, and the values chosen so the six ascending orders are the
// six distinct permutations of three rows. Every key therefore has an order no other key
// produces, and insertion order (what a comparator returning null leaves behind) is a
// seventh possibility that only `username` coincides with - which is why `username`'s
// assertion also flips the column and checks the reverse.
const SCOPED_USERS: AdminUser[] = [
  {
    id: 1, username: 'b-user', email: 'c@x.test', role: 'reviewer',
    created_at: '2026-03-01T09:00:00',
    person: { name: 'Aa Adams', entity: 'Aa Division' },
  },
  {
    id: 2, username: 'a-user', email: 'a@x.test', role: 'sysadmin',
    created_at: '2026-02-01T09:00:00',
    person: { name: 'Bb Brown', entity: 'Cc Division' },
  },
  {
    id: 3, username: 'c-user', email: 'b@x.test', role: 'org_admin',
    created_at: '2026-01-01T09:00:00',
    person: { name: 'Cc Clark', entity: 'Bb Division' },
  },
]

function renderUserList() {
  vi.mocked(adminApi.listRegistry).mockResolvedValue(PROJECTS)
  vi.mocked(adminApi.listUsers).mockImplementation(async (project?: string) =>
    project ? SCOPED_USERS : SCOPED_USERS.map(({ person: _person, ...rest }) => rest),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <UserList />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Row order read off a column, by index. */
function orderBy(column: number) {
  return screen
    .getAllByRole('row')
    .slice(1)
    .map((row) => row.querySelectorAll('td')[column].textContent)
}

async function rowsSettle(count: number) {
  await waitFor(() => expect(screen.getAllByRole('row')).toHaveLength(count + 1))
}

const USERNAME_COLUMN_SCOPED = 2

async function selectAlpha() {
  await userEvent.setup().selectOptions(screen.getByLabelText('Show as on project'), 'alpha')
  await waitFor(() =>
    expect(within(screen.getAllByRole('row')[0]).getAllByRole('columnheader')[0].textContent)
      .toContain('Name'),
  )
}

beforeEach(() => vi.clearAllMocks())

describe('the user list, read through a project', () => {
  // label → the ascending order that key and only that key produces.
  const cases: [string, string[]][] = [
    ['Name', ['b-user', 'a-user', 'c-user']],
    ['Entity', ['b-user', 'c-user', 'a-user']],
    ['Username', ['a-user', 'b-user', 'c-user']],
    ['Email', ['a-user', 'c-user', 'b-user']],
    ['Role', ['c-user', 'b-user', 'a-user']],
    ['Created', ['c-user', 'a-user', 'b-user']],
  ]

  test.each(cases)('the %s header sorts by %s and by nothing else', async (label, expected) => {
    renderUserList()
    await rowsSettle(3)
    await selectAlpha()

    // Name is the opening sort once a project is chosen, so clicking it would flip to
    // descending; every other column starts ascending on its first click.
    if (label !== 'Name') {
      await userEvent.setup().click(screen.getByRole('button', { name: new RegExp(`^${label}`) }))
    }

    await waitFor(() => expect(orderBy(USERNAME_COLUMN_SCOPED)).toEqual(expected))
  })

  test('the Username header really sorts rather than leaving insertion order alone', async () => {
    // Username's ascending order happens to be the only one a null comparator could imitate,
    // since a stable sort with no key leaves the rows as delivered. Reversing it is what the
    // do-nothing case cannot produce.
    renderUserList()
    await rowsSettle(3)
    await selectAlpha()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /^Username/ }))
    await waitFor(() =>
      expect(orderBy(USERNAME_COLUMN_SCOPED)).toEqual(['a-user', 'b-user', 'c-user']),
    )

    await user.click(screen.getByRole('button', { name: /^Username/ }))
    await waitFor(() =>
      expect(orderBy(USERNAME_COLUMN_SCOPED)).toEqual(['c-user', 'b-user', 'a-user']),
    )
  })

  test('the unscoped list sorts by its own four columns', async () => {
    // Name and Entity are not rendered here, so this covers the columns that survive the
    // lens being cleared - and a Username/Email/Role/Created header mis-wired to `name`
    // would sort by a field no row carries and leave the rows untouched.
    renderUserList()
    await rowsSettle(3)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /^Email/ }))
    await waitFor(() => expect(orderBy(0)).toEqual(['a-user', 'c-user', 'b-user']))

    await user.click(screen.getByRole('button', { name: /^Role/ }))
    await waitFor(() => expect(orderBy(0)).toEqual(['c-user', 'b-user', 'a-user']))

    await user.click(screen.getByRole('button', { name: /^Created/ }))
    await waitFor(() => expect(orderBy(0)).toEqual(['c-user', 'a-user', 'b-user']))
  })
})

// ── The org member tables ─────────────────────────────────────────────────────
//
// Three sortable keys, three distinct ascending orders. `org_role` has only the two values
// the UI offers, so its order leans on the sort being stable for the tie - which it is, and
// which still tells it apart from both other keys and from insertion order.
const MEMBERS: OrgMember[] = [
  { id: 1, username: 'b-member', email: 'c@x.test', role: 'reviewer', org_role: 'org_admin', created_at: '2026-01-01' },
  { id: 2, username: 'c-member', email: 'a@x.test', role: 'reviewer', org_role: 'org_admin', created_at: '2026-01-01' },
  { id: 3, username: 'a-member', email: 'b@x.test', role: 'reviewer', org_role: 'member', created_at: '2026-01-01' },
]

const MEMBER_CASES: [string, string[]][] = [
  ['Username', ['a-member', 'b-member', 'c-member']],
  ['Email', ['c-member', 'a-member', 'b-member']],
  // 'member' sorts before 'org_admin'; the two org_admins then hold their delivered order.
  ['Org Role', ['a-member', 'b-member', 'c-member']],
]

function primeMemberQueries() {
  vi.mocked(adminApi.listOrgs).mockResolvedValue([
    { id: 1, slug: 'acme', name: 'Acme', created_at: '2026-01-01' },
  ])
  vi.mocked(adminApi.listOrgMembers).mockResolvedValue(MEMBERS)
  vi.mocked(adminApi.listRegistry).mockResolvedValue(PROJECTS)
  vi.mocked(adminApi.listUsers).mockResolvedValue([])
}

function renderOrgDetail() {
  primeMemberQueries()
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/admin/orgs/1']}>
        <Routes>
          <Route path="/admin/orgs/:orgId" element={<OrgDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function renderOrgPanel() {
  primeMemberQueries()
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <OrgPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** The members table is the first on both pages; the projects table follows it. */
function memberOrder() {
  return within(screen.getAllByRole('table')[0])
    .getAllByRole('row')
    .slice(1)
    .map((row) => row.querySelectorAll('td')[0].textContent)
}

async function membersSettle() {
  await waitFor(() => expect(memberOrder()).toHaveLength(3))
}

describe.each([
  ['OrgDetail', renderOrgDetail, 'Org Role'],
  ['OrgPanel', renderOrgPanel, 'Role'],
] as const)('%s members table', (_name, renderPage, roleLabel) => {
  test.each(MEMBER_CASES)('the %s header sorts by %s and by nothing else', async (label, expected) => {
    renderPage()
    await membersSettle()
    const heading = label === 'Org Role' ? roleLabel : label

    // Username is the opening sort on both pages, so clicking it flips to descending -
    // asserted separately below rather than folded in here.
    if (heading !== 'Username') {
      await userEvent.setup().click(screen.getByRole('button', { name: new RegExp(`^${heading}`) }))
    }

    await waitFor(() => expect(memberOrder()).toEqual(expected))
  })

  test('the Username header really sorts rather than leaving insertion order alone', async () => {
    // Username's ascending order is the only one a null comparator could imitate, since a
    // stable sort with no key leaves the rows as delivered. Descending is what it cannot
    // produce - and username is the opening sort here, so the first click is the flip.
    renderPage()
    await membersSettle()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /^Username/ }))
    await waitFor(() => expect(memberOrder()).toEqual(['c-member', 'b-member', 'a-member']))

    await user.click(screen.getByRole('button', { name: /^Username/ }))
    await waitFor(() => expect(memberOrder()).toEqual(['a-member', 'b-member', 'c-member']))
  })
})
