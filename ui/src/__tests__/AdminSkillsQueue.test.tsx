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
    // The value `insert_skill` writes on every proposal. Spelled out rather than defaulted in
    // the factory, so a test wanting the other one has to say so.
    scope: 'project',
    flag_reason: null,
    flag_suggestion: null,
    created_at: '2026-09-01T09:00:00',
    reviewed_at: null,
    reviewed_by: null,
    ...over,
  }
}

/**
 * The Approve button, found by what it starts with rather than by its whole label.
 *
 * The label is not constant any more: it reads "Approve for this engagement" or "Approve
 * everywhere" according to the scope selected, because a button that said "everywhere" while
 * filing a rule for one engagement would be wrong in a way nobody reports. A locator is not an
 * assertion, so it deliberately matches both - the label itself is asserted below, where it
 * can fail for the right reason.
 */
const APPROVE = /^Approve/

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
function makeAdapter(pending: AgentSkill[], sent: Sent[], approved: AgentSkill[] = []) {
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
    else if (method === 'GET' && url.includes('status=approved')) data = approved
    else if (method === 'GET' && url.includes('/occurrences')) data = EVIDENCE
    else if (method === 'PATCH') data = { ...pending[0], status: 'approved' }

    return Promise.resolve({
      data, status: 200, statusText: 'OK', headers: {}, config,
    } as AxiosResponse)
  }
}

function installTransport(pending: AgentSkill[], approved: AgentSkill[] = []): Sent[] {
  const sent: Sent[] = []
  apiClient.defaults.adapter = makeAdapter(pending, sent, approved)
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
      within(cardFor('Welcome carries privacy')).getByRole('button', { name: APPROVE }),
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
    await userEvent.click(card.getByRole('button', { name: APPROVE }))

    await waitFor(() => expect(sent.some(s => s.method === 'PATCH')).toBe(true))
    expect(sent.find(s => s.method === 'PATCH')!.body).toMatchObject({
      status: 'approved',
      name: 'Welcome carries privacy and tone',
    })
  })

  it('binds the approve button to a note, and by default it says this engagement alone', async () => {
    // Reached through aria-describedby, so the association is something the DOM holds. A note
    // asserted by proximity is satisfied by any note anywhere in the card - the failure mode
    // CLAUDE.md records for the "why is this greyed out" explanation asserted per section.
    //
    // The binding is what this test used to assert on its own, and it still does. What has
    // changed is that the consequence is no longer one sentence: an approval means different
    // things at the two scopes, so a note that said "every engagement" whatever was selected
    // would be false half the time. Its pair below asserts the other half.
    installTransport([THRICE])
    renderPage()
    await screen.findByText('Welcome carries privacy')

    const approve = within(cardFor('Welcome carries privacy'))
      .getByRole('button', { name: APPROVE })
    const noteId = approve.getAttribute('aria-describedby')
    expect(noteId).toBeTruthy()

    const note = document.getElementById(noteId!)
    expect(note).not.toBeNull()
    // Names the engagement, so "and nothing else changes" is a statement about something.
    expect(note!.textContent).toContain('acme-rail')
    expect(note!.textContent).toContain('Interaction Designer')
    expect(note!.textContent).toContain('alone')
    // The words the widened note carries, which this one must not: a reviewer who has widened
    // nothing must not be told their click reaches everywhere.
    expect(note!.textContent).not.toContain('every engagement')
  })

  it('says what widening means once the reviewer widens it', async () => {
    // The same note, the same binding, the other scope. Approving a global rule changes that
    // agent on engagements this reviewer has never seen, and the sentence saying so has to
    // arrive with the choice rather than sit in the release notes.
    installTransport([THRICE])
    renderPage()
    await screen.findByText('Welcome carries privacy')

    const card = within(cardFor('Welcome carries privacy'))
    await userEvent.click(card.getByRole('radio', { name: 'Applies everywhere' }))

    const approve = card.getByRole('button', { name: APPROVE })
    const note = document.getElementById(approve.getAttribute('aria-describedby')!)
    expect(note!.textContent).toContain('every engagement')
    expect(note!.textContent).toContain('never seen')
    expect(note!.textContent).toContain('Interaction Designer')
    expect(note!.textContent).toContain('acme-rail')
  })

  it('tells a reviewer when a narrow approval would reach no engagement at all', async () => {
    // A proposal with no `source_project` - what `POST /admin/skills` and the import door
    // write. Approved narrowly it is a rule that reaches nothing: present in the library,
    // correct-looking, injected nowhere. The reviewer is the only person who can tell that
    // from a working approval, so the note says it rather than leaving them to find out.
    installTransport([skill({ id: 44, name: 'A rule from nowhere', source_project: null })])
    renderPage()
    await screen.findByText('A rule from nowhere')

    const approve = within(cardFor('A rule from nowhere')).getByRole('button', { name: APPROVE })
    const note = document.getElementById(approve.getAttribute('aria-describedby')!)
    expect(note!.textContent).toContain('names no engagement')
    expect(note!.textContent).toContain('reaches none')
  })

  it('labels the approve button with what the click will actually do', async () => {
    // "Approve everywhere" was true of every approval until a rule had a scope. A button that
    // keeps saying it while filing a narrow rule is wrong in the direction nobody reports -
    // the reviewer believes they have published a rule to the library and they have not.
    installTransport([THRICE])
    renderPage()
    await screen.findByText('Welcome carries privacy')

    const card = within(cardFor('Welcome carries privacy'))
    expect(card.getByRole('button', { name: APPROVE })).toHaveTextContent(
      'Approve for this engagement',
    )

    await userEvent.click(card.getByRole('radio', { name: 'Applies everywhere' }))

    expect(card.getByRole('button', { name: APPROVE })).toHaveTextContent('Approve everywhere')
  })

  it('sends the scope the reviewer chose', async () => {
    // What is **sent**, not what the radio renders. CLAUDE.md records a radio asserted as
    // rendered rather than as sent, among eleven assertions on this project that passed while
    // testing something one layer away from what they were named for. The body that leaves
    // the browser is the only thing that widens a rule.
    const sent = installTransport([THRICE])
    renderPage()
    await screen.findByText('Welcome carries privacy')

    const card = within(cardFor('Welcome carries privacy'))
    await userEvent.click(card.getByRole('radio', { name: 'Applies everywhere' }))
    await userEvent.click(card.getByRole('button', { name: APPROVE }))

    await waitFor(() => expect(sent.some(s => s.method === 'PATCH')).toBe(true))
    const patch = sent.find(s => s.method === 'PATCH')!
    expect(patch.url).toBe('/admin/skills/31')
    expect(patch.body).toMatchObject({ status: 'approved', scope: 'global' })
  })

  it('sends the narrow scope when the reviewer touches nothing', async () => {
    // The control on the test above, and the one that catches the opposite defect: a form
    // that always sent `global` would pass it perfectly. Between them the two say the request
    // follows the control rather than a constant.
    const sent = installTransport([THRICE])
    renderPage()
    await screen.findByText('Welcome carries privacy')

    await userEvent.click(
      within(cardFor('Welcome carries privacy')).getByRole('button', { name: APPROVE }),
    )

    await waitFor(() => expect(sent.some(s => s.method === 'PATCH')).toBe(true))
    expect(sent.find(s => s.method === 'PATCH')!.body).toMatchObject({
      status: 'approved', scope: 'project',
    })
  })

  it('starts from the scope the row already carries', async () => {
    // A rule that is already global - one of the fifty-three, sent back to the queue - shows
    // global, so a reviewer re-approving it does not silently demote it. The control is
    // narrow because the *stored value* is narrow on a proposal, not because the page picks a
    // side, and a page that hardcoded either would fail one of these two.
    installTransport([skill({ id: 55, name: 'An already global rule', scope: 'global' })])
    renderPage()
    await screen.findByText('An already global rule')

    const card = within(cardFor('An already global rule'))
    expect(card.getByRole('radio', { name: 'Applies everywhere' })).toBeChecked()
    expect(card.getByRole('radio', { name: 'Applies to this engagement' })).not.toBeChecked()
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
      within(cardFor('Welcome carries privacy')).getByRole('button', { name: APPROVE }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Only a sysadmin may approve a skill',
    )
  })
})

describe('the approved library', () => {
  // Finding I4 of the sp65 review: CLAUDE.md and the spec both say a reviewer demotes a rule
  // that turns out to have been about one engagement, and the library offered no way to see a
  // rule's reach, let alone change it. The fifty-three rows the migration affirmed `global`
  // were affirmed without anybody re-reading them, so this is the control that makes the
  // re-reading actionable.
  const realAdapter = apiClient.defaults.adapter

  afterEach(() => {
    apiClient.defaults.adapter = realAdapter
  })

  const WIDE = skill({
    id: 71, name: 'State the units', status: 'approved', scope: 'global',
    source_project: 'acme-rail', source: 'baseline',
  })
  const NARROW = skill({
    id: 72, name: 'The renewals programme', status: 'approved', scope: 'project',
    source_project: 'borough-water',
  })

  async function openLibrary(approved: AgentSkill[]): Promise<Sent[]> {
    const sent = installTransport([], approved)
    renderPage()
    await userEvent.click(screen.getByRole('button', { name: /Library/ }))
    await screen.findByText(approved[0].name)
    return sent
  }

  it('shows each rule\u2019s reach, and names the engagement a narrow one is held to', async () => {
    // A badge saying only "project" would be no help on a page listing every engagement's
    // rules at once - the question a reviewer is asking is *which* engagement.
    await openLibrary([WIDE, NARROW])

    expect(within(cardFor('State the units')).getByText('Applies everywhere')).toBeInTheDocument()
    expect(
      within(cardFor('The renewals programme')).getByText('Applies to borough-water'),
    ).toBeInTheDocument()
  })

  it('demotes a global rule to the engagement it came from, and sends the narrowing', async () => {
    // The action both documents describe. Asserted on the body that leaves the browser: a
    // radio that changed a local variable and a radio that changed the rule look identical on
    // screen, and only one of them is the feature.
    const sent = await openLibrary([WIDE])

    const card = within(cardFor('State the units'))
    await userEvent.click(card.getByRole('button', { name: 'Edit' }))
    await userEvent.click(card.getByRole('radio', { name: 'Applies to this engagement' }))
    await userEvent.click(card.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(sent.some(s => s.method === 'PATCH')).toBe(true))
    const patch = sent.find(s => s.method === 'PATCH')!
    expect(patch.url).toBe('/admin/skills/71')
    expect(patch.body).toMatchObject({ scope: 'project', name: 'State the units' })
    // Not an approval, and not a deletion. The library edit changes what the rule says and
    // where it applies; it must not restate a status it was not asked about.
    expect(patch.body).not.toHaveProperty('status')
  })

  it('keeps the reach a wording edit did not ask to change', async () => {
    // The control. A form that always sent `project` would pass the test above perfectly and
    // would silently demote all fifty-three the first time anybody fixed a typo.
    const sent = await openLibrary([WIDE])

    const card = within(cardFor('State the units'))
    await userEvent.click(card.getByRole('button', { name: 'Edit' }))
    const field = card.getByDisplayValue('State the units')
    await userEvent.clear(field)
    await userEvent.type(field, 'State the units on every figure')
    await userEvent.click(card.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(sent.some(s => s.method === 'PATCH')).toBe(true))
    expect(sent.find(s => s.method === 'PATCH')!.body).toMatchObject({
      name: 'State the units on every figure', scope: 'global',
    })
  })

  it('does not widen a narrow rule when somebody edits its wording', async () => {
    // The control the first round of this file was missing, and the gap was found by mutation
    // rather than by reading: seeding the library's scope control from the literal 'global'
    // instead of from `skill.scope` passed every other test here, because every other row in
    // this block happens to be global. So the only case that can catch it is the narrow one,
    // and it is the dangerous direction - a typo fix silently publishing one client's rule to
    // every engagement, with a green suite and a correct-looking card.
    const sent = await openLibrary([NARROW])

    const card = within(cardFor('The renewals programme'))
    await userEvent.click(card.getByRole('button', { name: 'Edit' }))
    expect(card.getByRole('radio', { name: 'Applies to this engagement' })).toBeChecked()

    const field = card.getByDisplayValue('The renewals programme')
    await userEvent.clear(field)
    await userEvent.type(field, 'The renewals programme, not the CapEx allocation')
    await userEvent.click(card.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(sent.some(s => s.method === 'PATCH')).toBe(true))
    expect(sent.find(s => s.method === 'PATCH')!.body).toMatchObject({ scope: 'project' })
  })

  it('binds Save to a note saying what the reach about to be saved means', async () => {
    // The same association the queue holds, for the same reason: proximity is not association.
    const sent = await openLibrary([WIDE])
    expect(sent).toBeTruthy()

    const card = within(cardFor('State the units'))
    await userEvent.click(card.getByRole('button', { name: 'Edit' }))

    const save = card.getByRole('button', { name: 'Save' })
    const wide = document.getElementById(save.getAttribute('aria-describedby')!)
    expect(wide!.textContent).toContain('every engagement')

    await userEvent.click(card.getByRole('radio', { name: 'Applies to this engagement' }))
    const narrow = document.getElementById(save.getAttribute('aria-describedby')!)
    expect(narrow!.textContent).toContain('acme-rail')
    expect(narrow!.textContent).not.toContain('every engagement')
  })

  it('warns that narrowing a rule with no engagement would leave it applying to none', async () => {
    // The imported and hand-typed rows. Narrowing one of these is not a demotion, it is a
    // retirement with no record that it happened.
    const orphan = skill({
      id: 73, name: 'A rule from nowhere', status: 'approved', scope: 'global',
      source_project: null,
    })
    await openLibrary([orphan])

    const card = within(cardFor('A rule from nowhere'))
    await userEvent.click(card.getByRole('button', { name: 'Edit' }))
    await userEvent.click(card.getByRole('radio', { name: 'Applies to this engagement' }))

    const save = card.getByRole('button', { name: 'Save' })
    const note = document.getElementById(save.getAttribute('aria-describedby')!)
    expect(note!.textContent).toContain('names no engagement')
    expect(note!.textContent).toContain('none')
  })
})
