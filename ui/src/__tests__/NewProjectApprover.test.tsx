// ui/src/__tests__/NewProjectApprover.test.tsx
//
// The approver a new engagement is created with, asserted as **sent** rather than as rendered.
//
// That distinction is the whole reason this file exists rather than a couple of "the field is
// on screen" checks. CLAUDE.md records a radio tested as rendered and not as sent, and the
// consequence here would be the worst available: `projectsApi.create` posts an object literal,
// so a field the form collects and forgets to include produces a 422 the consultant reads as
// the product being broken - or, if the server ever relaxed, a project created with no
// approver, which is the dead end the whole change exists to close. So every test below
// inspects the request body.
//
// Both directions throughout, because a form that refuses everything satisfies every
// "incomplete input is refused" assertion perfectly.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AxiosError, AxiosHeaders } from 'axios'
import { describe, it, expect, beforeEach, vi } from 'vitest'

import NewProjectModal from '../components/NewProjectModal'
import { projectsApi } from '../api/endpoints'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

function renderModal() {
  const onClose = vi.fn()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NewProjectModal onClose={onClose} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { onClose }
}

/** Fill the whole form, overriding whichever fields a test wants wrong or absent. */
async function fillForm(
  user: ReturnType<typeof userEvent.setup>,
  overrides: Partial<Record<'slug' | 'sector' | 'name' | 'email', string>> = {},
) {
  const values = {
    slug: 'helia-digital-tau',
    sector: 'energy',
    name: 'Rosalind Achebe',
    email: 'rosalind.achebe@client.test',
    ...overrides,
  }
  if (values.slug) await user.type(screen.getByPlaceholderText('acme-rail'), values.slug)
  if (values.sector) await user.type(screen.getByPlaceholderText('logistics'), values.sector)
  if (values.name) await user.type(screen.getByLabelText('Name'), values.name)
  if (values.email) await user.type(screen.getByLabelText('Email'), values.email)
  await user.click(screen.getByRole('button', { name: 'Create' }))
}

beforeEach(() => {
  vi.restoreAllMocks()
  navigate.mockClear()
})

describe('the approver a new engagement is created with', () => {
  it('sends the name and the email in the creation request', async () => {
    const create = vi
      .spyOn(projectsApi, 'create')
      .mockResolvedValue({ slug: 'helia-digital-tau' } as never)
    const user = userEvent.setup()
    renderModal()

    await fillForm(user)

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    // On the body, not on the call happening. A form that collects both fields and posts
    // neither reaches this line and would pass a test that only counted calls.
    expect(create.mock.calls[0][0]).toMatchObject({
      client_slug: 'helia-digital-tau',
      sector: 'energy',
      approver_name: 'Rosalind Achebe',
      approver_email: 'rosalind.achebe@client.test',
    })
  })

  it('trims both before sending them', async () => {
    const create = vi
      .spyOn(projectsApi, 'create')
      .mockResolvedValue({ slug: 'helia-digital-tau' } as never)
    const user = userEvent.setup()
    renderModal()

    await fillForm(user, {
      name: '  Rosalind Achebe  ',
      email: '  rosalind.achebe@client.test  ',
    })

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    // Every door that later finds this person matches `users.username` exactly under SQLite's
    // binary collation, so an address sent with a stray space is one none of them can match.
    // The server trims too; sending it untrimmed would merely mean the browser and the stored
    // row disagreed about what the consultant typed.
    expect(create.mock.calls[0][0]).toMatchObject({
      approver_name: 'Rosalind Achebe',
      approver_email: 'rosalind.achebe@client.test',
    })
  })

  it.each([
    ['the name', { name: '' }, 'approver_name'],
    ['the email', { email: '' }, 'approver_email'],
  ])('sends nothing at all when %s is missing', async (_what, overrides, _field) => {
    const create = vi.spyOn(projectsApi, 'create').mockResolvedValue({} as never)
    const user = userEvent.setup()
    renderModal()

    await fillForm(user, overrides)

    expect(await screen.findByText('Required')).toBeInTheDocument()
    // The important half: no request was made. A form that showed the error *and* posted
    // would create the engagement the error says it refused to.
    expect(create).not.toHaveBeenCalled()
  })

  it.each([
    'rosalind.achebe',
    'rosalind@client',
    'rosalind achebe@client.test',
    '@client.test',
  ])('refuses %s as an address and sends nothing', async (address) => {
    const create = vi.spyOn(projectsApi, 'create').mockResolvedValue({} as never)
    const user = userEvent.setup()
    renderModal()

    await fillForm(user, { email: address })

    expect(await screen.findByText('Enter a valid email address')).toBeInTheDocument()
    expect(create).not.toHaveBeenCalled()
  })

  it.each([
    'rosalind.achebe@client.test',
    'r.a+approvals@sub.client.test',
  ])('accepts %s and sends it', async (address) => {
    // The other direction. Without these two the four cases above are satisfied by a form
    // that refuses every address, and the plus-tag is here so a future tightening of the
    // pattern cannot quietly refuse addresses real people use.
    const create = vi
      .spyOn(projectsApi, 'create')
      .mockResolvedValue({ slug: 'helia-digital-tau' } as never)
    const user = userEvent.setup()
    renderModal()

    await fillForm(user, { email: address })

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    expect(create.mock.calls[0][0]).toMatchObject({ approver_email: address })
  })

  it("puts the server's own refusal in front of the consultant", async () => {
    // `describeError`, imported rather than copied. This door's refusals say things a fixed
    // string cannot, and "Failed to create project" reads as a transient fault that retrying
    // will clear - which for a refusal it will not.
    const sentence =
      'approver_email must be a valid address - the approver named at creation is sent the ' +
      'invite that gives them access to this engagement'
    const refusal = new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, null, {
      status: 422,
      statusText: 'Unprocessable Entity',
      data: { detail: sentence },
      headers: new AxiosHeaders(),
      config: { headers: new AxiosHeaders() },
    })
    vi.spyOn(projectsApi, 'create').mockRejectedValue(refusal)
    const user = userEvent.setup()
    const { onClose } = renderModal()

    await fillForm(user)

    expect(await screen.findByText(sentence)).toBeInTheDocument()
    // And the modal stays open on a refusal, so the consultant can correct the field rather
    // than retype the whole form.
    expect(onClose).not.toHaveBeenCalled()
    expect(navigate).not.toHaveBeenCalled()
  })

  it('explains what the approver is for, since a required field people resent is one they fill with a@b.c', async () => {
    renderModal()

    expect(screen.getByText('First approver')).toBeInTheDocument()
    expect(
      screen.getByText(/invited as an approver and can be changed later/i),
    ).toBeInTheDocument()
  })
})
