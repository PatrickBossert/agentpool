// ui/src/__tests__/UserListPerson.test.tsx
//
// The admin user list showed a username and an email address and left an administrator
// guessing who anybody was. It now reads the list through a selected project, and shows the
// name and entity that project records for each account.
//
// The lens, the subset rule and the scoping are server-side and are asserted there
// (tests/test_admin_user_identity.py) against real rows. What is asserted here is what this
// layer decides: that selecting a project **sends the slug**, that no project means no name
// columns at all rather than a column full of guesses, and that the headers sort.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import UserList from '../pages/UserList'
import { adminApi } from '../api/admin'
import type { AdminUser, ProjectRegistryEntry } from '../types'

vi.mock('../api/admin', () => ({
  adminApi: {
    listUsers: vi.fn(),
    listRegistry: vi.fn(),
    deleteUser: vi.fn(),
    issueResetLink: vi.fn(),
  },
}))

const PROJECTS: ProjectRegistryEntry[] = [
  { id: 1, slug: 'alpha', org_id: 1, display_name: 'Alpha Engagement', created_at: '2026-01-01' },
  { id: 2, slug: 'beta', org_id: 1, display_name: 'Beta Engagement', created_at: '2026-01-01' },
]

const UNSCOPED: AdminUser[] = [
  { id: 1, username: 'jane@example.com', email: 'jane@example.com', role: 'reviewer', created_at: '2026-03-04T09:00:00' },
  { id: 2, username: 'ruth@example.com', email: 'ruth@example.com', role: 'reviewer', created_at: '2026-01-02T09:00:00' },
  { id: 3, username: 'admin', email: '', role: 'sysadmin', created_at: '2025-12-01T09:00:00' },
]

// What the server sends for ?project=alpha: two members with names, the sysadmin kept for
// reachability with no person record, and nobody else.
const ON_ALPHA: AdminUser[] = [
  { ...UNSCOPED[0], person: { name: 'Jane Smith', entity: 'Group Finance' } },
  { ...UNSCOPED[1], person: { name: 'Ruth Kelly', entity: 'Group Risk' } },
  { ...UNSCOPED[2], person: null },
]

// The same account, recorded differently on the other engagement - the fact the lens exists
// for. Nothing here has to choose between the two, because each request asks about one.
const ON_BETA: AdminUser[] = [{ ...UNSCOPED[0], person: { name: 'J. Smith', entity: 'Retail Bank' } }]

function renderList() {
  vi.mocked(adminApi.listRegistry).mockResolvedValue(PROJECTS)
  vi.mocked(adminApi.listUsers).mockImplementation(async (project?: string) => {
    if (project === 'alpha') return ON_ALPHA
    if (project === 'beta') return ON_BETA
    return UNSCOPED
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <UserList />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const selector = () => screen.getByLabelText('Show as on project')

async function rowsSettle(count: number) {
  await waitFor(() => expect(screen.getAllByRole('row')).toHaveLength(count + 1))
}

function columnHeaders() {
  return within(screen.getAllByRole('row')[0])
    .getAllByRole('columnheader')
    .map((th) => th.textContent?.trim())
    .filter(Boolean)
}

function bodyRows() {
  return screen.getAllByRole('row').slice(1)
}

/** The rendered row order, read off the Username column - whose index moves with the lens. */
function usernameOrder(usernameColumn: number) {
  return bodyRows().map((row) => row.querySelectorAll('td')[usernameColumn].textContent)
}

beforeEach(() => vi.clearAllMocks())

test('it opens unscoped, requesting no project and showing no name columns', async () => {
  renderList()
  await rowsSettle(3)

  expect(vi.mocked(adminApi.listUsers)).toHaveBeenCalledWith(undefined)
  // Absent, not full of dashes: without a project there is no question a name answers, and a
  // column of placeholders would read as data the server failed to supply.
  expect(columnHeaders()).toEqual(['Username', 'Email', 'Role', 'Created'])
  expect(screen.getByText(/Names live on a project/)).toBeInTheDocument()
})

test('choosing a project sends that slug and shows the names it records', async () => {
  renderList()
  await rowsSettle(3)
  await userEvent.setup().selectOptions(selector(), 'alpha')

  await waitFor(() => expect(vi.mocked(adminApi.listUsers)).toHaveBeenCalledWith('alpha'))
  await waitFor(() => expect(columnHeaders()).toEqual(
    ['Name', 'Entity', 'Username', 'Email', 'Role', 'Created'],
  ))
  const jane = bodyRows().find((r) => r.querySelectorAll('td')[2].textContent === 'jane@example.com')!
  expect(within(jane).getByText('Jane Smith')).toBeInTheDocument()
  expect(within(jane).getByText('Group Finance')).toBeInTheDocument()
})

test('the same account is named differently under a different project', async () => {
  renderList()
  await rowsSettle(3)
  const user = userEvent.setup()

  await user.selectOptions(selector(), 'alpha')
  await waitFor(() => expect(screen.getByText('Jane Smith')).toBeInTheDocument())

  await user.selectOptions(selector(), 'beta')
  await waitFor(() => expect(vi.mocked(adminApi.listUsers)).toHaveBeenCalledWith('beta'))
  await waitFor(() => expect(screen.getByText('J. Smith')).toBeInTheDocument())
  expect(screen.queryByText('Jane Smith')).toBeNull()
})

test('an account on the project with no person record reads as absent, not as a guess', async () => {
  renderList()
  await rowsSettle(3)
  await userEvent.setup().selectOptions(selector(), 'alpha')
  await waitFor(() => expect(columnHeaders()[0]).toBe('Name'))

  const sysadminRow = bodyRows().find((r) => r.querySelectorAll('td')[2].textContent === 'admin')!
  const cells = sysadminRow.querySelectorAll('td')
  expect(cells[0].textContent).toBe('-')
  expect(cells[1].textContent).toBe('-')
})

test('the selector offers exactly the projects the server said the caller may see', async () => {
  renderList()
  await rowsSettle(3)
  expect(
    within(selector()).getAllByRole('option').map((o) => (o as HTMLOptionElement).value),
  ).toEqual(['', 'alpha', 'beta'])
})

test('a scoped list sorts by name, and clicking a header reverses it', async () => {
  renderList()
  await rowsSettle(3)
  const user = userEvent.setup()
  await user.selectOptions(selector(), 'alpha')
  await waitFor(() => expect(columnHeaders()[0]).toBe('Name'))

  // Jane, Ruth, then the sysadmin - which has no name at all and stays out of the way at the
  // bottom rather than sorting as an empty string at the top.
  expect(usernameOrder(2)).toEqual(['jane@example.com', 'ruth@example.com', 'admin'])

  await user.click(screen.getByRole('button', { name: /^Name/ }))
  await waitFor(() =>
    expect(usernameOrder(2)).toEqual(['ruth@example.com', 'jane@example.com', 'admin']),
  )
})

test('the unscoped list sorts by a column it actually renders', async () => {
  // Carrying the scoped default over would have ordered this list by `name`, which nothing
  // here has and no header offers - a list in an order the reader cannot account for.
  renderList()
  await rowsSettle(3)
  expect(usernameOrder(0)).toEqual(['admin', 'jane@example.com', 'ruth@example.com'])

  await userEvent.setup().click(screen.getByRole('button', { name: /^Created/ }))
  await waitFor(() =>
    expect(usernameOrder(0)).toEqual(['admin', 'ruth@example.com', 'jane@example.com']),
  )
})

test('clearing the project puts the sort back on a rendered column', async () => {
  // The state the initial render cannot reach, and the one the rule exists for: leaving the
  // sort on `name` after the Name column has gone leaves the list ordered by a field the
  // reader can no longer see - and with every key null it would fall back to insertion order,
  // which looks like no sort at all rather than like a mistake.
  renderList()
  await rowsSettle(3)
  const user = userEvent.setup()

  await user.selectOptions(selector(), 'alpha')
  await waitFor(() => expect(columnHeaders()[0]).toBe('Name'))

  await user.selectOptions(selector(), '')
  await waitFor(() => expect(columnHeaders()[0]).toBe('Username'))
  expect(usernameOrder(0)).toEqual(['admin', 'jane@example.com', 'ruth@example.com'])
})
