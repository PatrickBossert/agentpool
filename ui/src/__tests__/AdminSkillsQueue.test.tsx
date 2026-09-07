// ui/src/__tests__/AdminSkillsQueue.test.tsx
//
// The review queue an agent's proposals land in. Three properties, and only one of them is
// about what the page draws.
//
// **What is sent, not what renders.** The page is driven against a swapped axios adapter that
// records the real, fully-assembled request - the same technique as agentChatUpload.test.ts -
// rather than a mock of `skillsApi`. A mocked client would prove the mock was called and
// nothing about what left the browser, and CLAUDE.md records eleven tests on this project
// that passed while asserting something one layer away from the property they were named for.
// Approving must send `status: "approved"` on a PATCH to that skill's id; rejecting must send
// `status: "rejected"`. Those two calls are what change an agent's behaviour, and a "the
// button is in the document" test cannot tell one from the other.
//
// **The order is the server's, and this file does not claim to prove it.** The queue sorts by
// `occurrences` descending, in `fetch_skills`, asserted over HTTP in
// `tests/test_skill_queue_order.py`. A frontend test handed an already-sorted list and
// asserting it appears sorted would be exactly the vacuous shape above. What this file proves
// is the complementary half: given a response, the page renders it **in the order received**
// and never re-sorts. So the response below is deliberately handed over in an order no client
// could have chosen, and the page is required to keep it.
//
// **The consequence copy is bound to the button, not merely near it.** Approval is global -
// `_fetch_skill_notes` picks an approved skill up on the next run of that agent on every
// engagement. The note saying so is reached through the Approve button's `aria-describedby`,
// so what is asserted is the association the DOM holds rather than proximity in the layout.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { AxiosRequestConfig, AxiosResponse } from 'axios'

import AdminSkills from '../pages/AdminSkills'
import { apiClient } from '../api/client'
import type { AgentSkill, SkillOccurrence } from '../api/skills'

function skill(over: Partial<AgentSkill>): AgentSkill {
  return {
    id: 1,
    agents: ['Interaction Designer'],
    name: 'A rule',
    description: 'The rule, stated generally.',
    source: 'revision',
    source_project: 'acme-rail',
    source_ref: 'SC-014',
    proposed_by_agent: 'interaction_designer',
    occurrences: 1,
    status: 'pending',
    flag_reason: null,
    flag_suggestion: null,
    created_at: '2026-09-01T09:00:00',
    reviewed_at: null,
    reviewed_by: null,
    ...over,
  }
}

const THRICE = skill({
  id: 31, name: 'Welcome carries privacy', occurrences: 3,
  description: 'The welcome carries privacy and tone; the framing carries the purpose.',
})
const TWICE = skill({ id: 22, name: 'Name the recipient', occurrences: 2 })
const ONCE = skill({ id: 13, name: 'Avoid double negatives', occurrences: 1 })

const EVIDENCE: SkillOccurrence[] = [
  {
    id: 1, skill_id: 31,
    description: 'Keep confidentiality in the welcome and purpose in the framing',
    source_project: 'acme-rail', source_ref: 'SC-014',
    proposed_by_agent: 'interaction_designer', created_at: '2026-09-01T09:00:00',
  },
  {
    id: 2, skill_id: 31,
    description: 'The opening should state privacy; the framing states what it covers',
    source_project: 'borough-water', source_ref: 'SC-031',
    proposed_by_agent: 'interaction_designer', created_at: '2026-09-03T14:00:00',
  },
]

interface Sent { method: string; url: string; body: unknown }

/**
 * Swap the transport for one that records every request and answers the queue.
 *
 * `pending` is served in the order given, so a caller can hand the page an order and assert
 * the page kept it.
 */
function makeAdapter(pending: AgentSkill[], sent: Sent[]) {
  return (config: AxiosRequestConfig): Promise<AxiosResponse> => {
    const url = apiClient.getUri(config)
    const method = (config.method || 'get').toUpperCase()
    sent.push({
      method,
      url,
      body: typeof config.data === 'string' ? JSON.parse(config.data) : config.data,
    })

    let data: unknown = []
    if (method === 'GET' && url.includes('status=pending')) data = pending
    else if (method === 'GET' && url.includes('status=approved')) data = []
    else if (method === 'GET' && url.includes('/occurrences')) data = EVIDENCE
    else if (method === 'PATCH') data = { ...pending[0], status: 'approved' }

    return Promise.resolve({
      data, status: 200, statusText: 'OK', headers: {}, config,
    } as AxiosResponse)
  }
}

function installTransport(pending: AgentSkill[]): Sent[] {
  const sent: Sent[] = []
  apiClient.defaults.adapter = makeAdapter(pending, sent)
  return sent
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AdminSkills />
    </QueryClientProvider>,
  )
}

/** The card holding one proposal, found by its name rather than by position. */
function cardFor(name: string): HTMLElement {
  const heading = screen.getByText(name)
  const card = heading.closest('div.rounded-xl')
  if (!card) throw new Error(`no card around ${name}`)
  return card as HTMLElement
}

describe('the skills review queue', () => {
  const realAdapter = apiClient.defaults.adapter

  afterEach(() => {
    apiClient.defaults.adapter = realAdapter
  })

  it('renders the queue in the order the server sent it, and never re-sorts', async () => {
    // Handed over most-evidenced first, which is what the server sends. The page must not
    // reverse it, alphabetise it, or fall back to the created_at order the ids imply.
    installTransport([THRICE, TWICE, ONCE])
    renderPage()

    await screen.findByText('Welcome carries privacy')
    const names = screen.getAllByText(/Welcome carries privacy|Name the recipient|Avoid double negatives/)
      .map(n => n.textContent)

    expect(names).toEqual([
      'Welcome carries privacy', 'Name the recipient', 'Avoid double negatives',
    ])
  })

  it('keeps an order no client rule would have produced', async () => {
    // The control on the test above. If the page sorted by anything of its own - id, name,
    // occurrences recomputed - this arrangement would come back rearranged. It is ascending
    // by nothing: not id (13, 31, 22), not name, not occurrences.
    installTransport([ONCE, THRICE, TWICE])
    renderPage()

    await screen.findByText('Avoid double negatives')
    const names = screen.getAllByText(/Welcome carries privacy|Name the recipient|Avoid double negatives/)
      .map(n => n.textContent)

    expect(names).toEqual([
      'Avoid double negatives', 'Welcome carries privacy', 'Name the recipient',
    ])
  })

  it('shows how many times each rule has been proposed', async () => {
    installTransport([THRICE, ONCE])
    renderPage()

    await screen.findByText('Welcome carries privacy')

    expect(within(cardFor('Welcome carries privacy')).getByText('Seen 3 times')).toBeInTheDocument()
    expect(within(cardFor('Avoid double negatives')).getByText('Seen once')).toBeInTheDocument()
  })

  it('fetches the provenance only when a reviewer asks for it, and lists every sighting', async () => {
    const sent = installTransport([THRICE])
    renderPage()
    await screen.findByText('Welcome carries privacy')

    // Not requested on load - a queue of twenty proposals is still one request.
    expect(sent.filter(s => s.url.includes('/occurrences'))).toHaveLength(0)

    await userEvent.click(within(cardFor('Welcome carries privacy')).getByText('Show the evidence'))

    await waitFor(() => {
      expect(sent.filter(s => s.url === '/admin/skills/31/occurrences')).toHaveLength(1)
    })
    // Every sighting, with the engagement and the output each was corrected on. The wordings
    // differ between occurrences - that is what "duplicate by meaning" produces - so a panel
    // showing only the stored description would tell a reviewer nothing they did not have.
    expect(
      await screen.findByText('Keep confidentiality in the welcome and purpose in the framing'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('The opening should state privacy; the framing states what it covers'),
    ).toBeInTheDocument()
    expect(screen.getByText(/borough-water · SC-031/)).toBeInTheDocument()
    expect(screen.getByText(/acme-rail · SC-014/)).toBeInTheDocument()
  })

  it('sends an approval as a PATCH of that skill to status approved', async () => {
    const sent = installTransport([THRICE, ONCE])
    renderPage()
    await screen.findByText('Welcome carries privacy')

    await userEvent.click(
      within(cardFor('Welcome carries privacy')).getByRole('button', { name: /Approve everywhere/ }),
    )

    await waitFor(() => expect(sent.some(s => s.method === 'PATCH')).toBe(true))
    const patch = sent.find(s => s.method === 'PATCH')!
    // The id matters as much as the status: approving the wrong row changes the wrong agent.
    expect(patch.url).toBe('/admin/skills/31')
    expect(patch.body).toMatchObject({
      status: 'approved',
      name: 'Welcome carries privacy',
      agents: ['Interaction Designer'],
    })
  })

  it('sends a rejection as status rejected, and not as an approval', async () => {
    // The distinguishing test. Both buttons PATCH the same URL, so a test that only checked
    // "a PATCH went out" would pass with the two wired to each other.
    const sent = installTransport([THRICE])
    renderPage()
    await screen.findByText('Welcome carries privacy')

    await userEvent.click(
      within(cardFor('Welcome carries privacy')).getByRole('button', { name: /Reject/ }),
    )

    await waitFor(() => expect(sent.some(s => s.method === 'PATCH')).toBe(true))
    const patch = sent.find(s => s.method === 'PATCH')!
    expect(patch.url).toBe('/admin/skills/31')
    expect((patch.body as { status: string }).status).toBe('rejected')
  })

  it('sends the reviewer edits alongside the approval, not the stored wording', async () => {
    // The Approve button carries the edit buffer. A reviewer who rewords a proposal and then
    // approves must have the rewording stored, or the edit silently does nothing.
    const sent = installTransport([THRICE])
    renderPage()
    await screen.findByText('Welcome carries privacy')

    const card = within(cardFor('Welcome carries privacy'))
    await userEvent.click(card.getByRole('button', { name: 'Edit' }))
    const nameField = card.getByDisplayValue('Welcome carries privacy')
    await userEvent.clear(nameField)
    await userEvent.type(nameField, 'Welcome carries privacy and tone')
    await userEvent.click(card.getByRole('button', { name: /Approve everywhere/ }))

    await waitFor(() => expect(sent.some(s => s.method === 'PATCH')).toBe(true))
    expect(sent.find(s => s.method === 'PATCH')!.body).toMatchObject({
      status: 'approved',
      name: 'Welcome carries privacy and tone',
    })
  })

  it('binds the approve button to a note saying the change reaches every engagement', async () => {
    // Reached through aria-describedby, so the association is something the DOM holds. A note
    // asserted by proximity is satisfied by any note anywhere in the card - the failure mode
    // CLAUDE.md records for the "why is this greyed out" explanation asserted per section.
    installTransport([THRICE])
    renderPage()
    await screen.findByText('Welcome carries privacy')

    const approve = within(cardFor('Welcome carries privacy'))
      .getByRole('button', { name: /Approve everywhere/ })
    const noteId = approve.getAttribute('aria-describedby')
    expect(noteId).toBeTruthy()

    const note = document.getElementById(noteId!)
    expect(note).not.toBeNull()
    expect(note!.textContent).toContain('every engagement')
    expect(note!.textContent).toContain('Interaction Designer')
    // Names the engagement it came from, so "not only there" is a statement about something.
    expect(note!.textContent).toContain('acme-rail')
  })

  it('names the proposal path rather than showing the raw column value', async () => {
    installTransport([THRICE])
    renderPage()
    await screen.findByText('Welcome carries privacy')

    // The unmapped fallback renders the raw column - "revision · acme-rail". SOURCE_LABEL had
    // no key for the source `propose_skill` writes, so every proposal showed it.
    expect(cardFor('Welcome carries privacy').textContent)
      .toContain('Proposed after a revision · acme-rail')
  })

  it('shows the server sentence when an approval is refused', async () => {
    // describeError, imported rather than copied. The page had no error surface at all: a
    // refused approval left the row in the queue with nothing said, which reads as a click
    // that did not register.
    const sent: Sent[] = []
    const serveQueue = makeAdapter([THRICE], sent)
    apiClient.defaults.adapter = (config: AxiosRequestConfig) => {
      if ((config.method || 'get').toUpperCase() === 'PATCH') {
        return Promise.reject(
          Object.assign(new Error('Request failed'), {
            isAxiosError: true,
            config,
            response: {
              status: 403, statusText: 'Forbidden', headers: {}, config,
              data: { detail: 'Only a sysadmin may approve a skill' },
            },
          }),
        )
      }
      return serveQueue(config)
    }
    renderPage()
    await screen.findByText('Welcome carries privacy')

    await userEvent.click(
      within(cardFor('Welcome carries privacy')).getByRole('button', { name: /Approve everywhere/ }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Only a sysadmin may approve a skill',
    )
  })
})
