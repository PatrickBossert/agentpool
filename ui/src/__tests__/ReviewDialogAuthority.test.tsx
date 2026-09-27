// ui/src/__tests__/ReviewDialogAuthority.test.tsx
// Who is offered the three decision controls, and what the others are told instead.
//
// A newly created engagement has no stakeholders, and `caller_roles` reads content authority
// from a stakeholder row - so on a fresh project nobody holds it, including the consultant who
// created the engagement, configured it and started the run. They hold total administration and
// no content authority, which is both axes working exactly as designed and unusable where they
// meet: the owner of a live client engagement clicked Approve and was refused by his own
// product. The server side of that state is pinned in
// tests/test_new_project_approval_bootstrap.py, including the repair the note below names.
//
// Two properties, and neither is enough alone. Offering an action that is certain to be refused
// is its own defect - but hiding it silently is worse, because the reviewer is then left with a
// paused crew, no control, and nothing at all to read. So the controls are gated **and** the
// absence is explained, in the shape CLAUDE.md prescribes for a locked control: a note whose
// `data-explains` names what it accounts for, rather than a sentence that happens to sit nearby.
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import ReviewDialog from '../components/ReviewDialog'

let permissions: () => Promise<unknown>
const resolveReview = vi.fn().mockResolvedValue({})

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    resolveReview: (...a: unknown[]) => resolveReview(...a),
    getMyPermissions: () => permissions(),
  },
}))

const review = {
  id: 3, crew_name: 'discovery_mapping', prompt: 'Please review the value chain.',
  decision: 'pending',
}

// The three decision controls, by the id each renders under. Named here rather than located by
// their labels because the note declares the same three in `data-explains`, and the last test
// holds the two sets equal - a control found by its wording could not participate in that.
const CONTROLS = ['reject', 'revise', 'approve']

function renderDialog() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ReviewDialog slug="helia-digital-tau" review={review as never} outputs={[]} onClose={vi.fn()} />
    </QueryClientProvider>,
  )
}

const note = () => document.querySelector('[data-explains]')
const control = (id: string) => document.getElementById(id)

describe('who may decide on a paused crew', () => {
  beforeEach(() => {
    resolveReview.mockClear()
    permissions = () => Promise.resolve({ can_review: true, can_approve: true })
  })

  it('offers all three controls to a caller the door accepts', async () => {
    renderDialog()
    for (const id of CONTROLS) await waitFor(() => expect(control(id)).not.toBeNull())
    expect(note()).toBeNull()
  })

  it('offers all three to a reviewer who is not an approver', async () => {
    // The predicate that decides this dialog is `can_review`, not `can_approve`, because all
    // three controls post to `PATCH /projects/{slug}/reviews/{id}` and that door asks
    // `caller_may_contribute` - `{reviewer, approver}`. A `reviewer` may therefore approve a
    // HITL gate, and gating on `can_approve` would hide the button from a caller the server
    // accepts. This is the test that distinguishes the two flags: it is the only shape under
    // which reading the wrong one is visible, since the fresh-project case has both false.
    // `DiscoveryReviewExtra` reads `can_approve` and is right to - its door asks
    // `caller_may_approve` - so "copy the neighbour" is the wrong instinct here.
    permissions = () => Promise.resolve({ can_review: true, can_approve: false })
    renderDialog()

    for (const id of CONTROLS) await waitFor(() => expect(control(id)).not.toBeNull())
    expect(note()).toBeNull()
  })

  it('withholds all three from a caller the door would refuse, and says why', async () => {
    permissions = () => Promise.resolve({ can_review: false, can_approve: false })
    renderDialog()

    const explanation = await waitFor(() => {
      const n = note()
      expect(n).not.toBeNull()
      return n as HTMLElement
    })
    for (const id of CONTROLS) expect(control(id)).toBeNull()

    // The two things a consultant in this state actually needs: which axis refused them, and
    // the door that grants it. Asserted on the substance rather than on the note existing -
    // an empty `<p data-explains="…">` would satisfy a presence check perfectly.
    expect(explanation.textContent).toMatch(/content role/i)
    expect(explanation.textContent).toMatch(/administering the project does not confer it/i)
    expect(explanation.textContent).toMatch(/stakeholders tab/i)
    expect(explanation.textContent).toMatch(/reviewer or approver/i)
    expect(explanation.textContent).toMatch(/invite/i)
  })

  it('never claims anything about who else holds the role', async () => {
    // This component knows what *this caller* may do and nothing about the roster - it makes one
    // request, to a per-caller endpoint. "Nobody on this engagement can approve anything" is the
    // more useful diagnosis and would be a claim it cannot support, so it must not be made here;
    // it needs a roster read, and the fix for that is a different change. Asserted because the
    // sentence is a tempting one to add and would read as authoritative.
    permissions = () => Promise.resolve({ can_review: false, can_approve: false })
    renderDialog()

    // The assertion goes *inside* `waitFor`, which is not a formality: `waitFor(() => note())`
    // resolves on the first tick with `null`, and every assertion after it would then be made
    // against nothing. The first version of this test did exactly that and failed noisily, which
    // was the lucky outcome - a `not.toMatch` against `null?.textContent` would have passed.
    const explanation = await waitFor(() => {
      const n = note()
      expect(n).not.toBeNull()
      return n as HTMLElement
    })
    expect(explanation.textContent).not.toMatch(/nobody|no one|no-one/i)
  })

  it('shows neither the controls nor the note while the answer is still in flight', async () => {
    // Three states, not two. Collapsing `undefined` into "not permitted" flashes a note telling
    // a reviewer they lack an authority they may well hold; collapsing it the other way gives a
    // button that appears and then refuses. Driven with a promise that never settles, so the
    // in-flight state is the whole of what is observed rather than a race that usually resolves
    // before the assertion.
    permissions = () => new Promise(() => {})
    renderDialog()

    // The dialog itself has rendered - so this is the in-flight state, not an empty render.
    expect(await screen.findByText(/awaiting your approval/i)).toBeInTheDocument()
    for (const id of CONTROLS) expect(control(id)).toBeNull()
    expect(note()).toBeNull()
  })

  it('offers nothing when the authority question itself fails, and says that is what happened', async () => {
    // Two properties, and this test is the reason the component has a fourth state at all. The
    // first version of the change handled "permitted" and "refused" and left `isError` to fall
    // through to the in-flight branch, so a failed permissions request rendered an **empty
    // footer** - no control, no explanation - which is the "greyed out with no reason" failure
    // the note exists to prevent, reintroduced by the fix for it.
    //
    // Failing closed on the control is the easy half. The half worth asserting is that the
    // sentence is the *right* one: telling a consultant to add a stakeholder when the truth is
    // that a request failed sends them to reconfigure an engagement that was never
    // misconfigured. So the refusal wording is asserted **absent** here, which is what makes
    // this test distinguish the two notes rather than merely count them.
    permissions = () => Promise.reject(new Error('network'))
    renderDialog()

    const explanation = await waitFor(() => {
      const n = note()
      expect(n).not.toBeNull()
      return n as HTMLElement
    })
    for (const id of CONTROLS) expect(control(id)).toBeNull()

    expect(explanation.textContent).toMatch(/could not be checked/i)
    // What the reviewer most needs to know: the crew is still waiting, so closing the dialog has
    // cost nothing and no half-decision has been recorded against the output.
    expect(explanation.textContent).toMatch(/nothing has been recorded/i)
    expect(explanation.textContent).not.toMatch(/stakeholders tab/i)
  })

  it('accounts for exactly the controls it withholds, by name', async () => {
    // The property that stops this explanation rotting into decoration, and the one CLAUDE.md
    // asks for by name: an assertion scoped to a container is not an assertion about its
    // contents. Without it, a fourth control added to this footer would be gated by the same
    // branch and explained by nothing, and every test above would still pass - the note would
    // be present, its text unchanged, and one action silently unaccounted for.
    //
    // Set equality in both directions, across the two states: the ids rendered when the caller
    // is permitted must be exactly the names declared when they are not. A name with no control
    // fails it as loudly as a control with no name.
    permissions = () => Promise.resolve({ can_review: true, can_approve: true })
    renderDialog()
    await waitFor(() => expect(control('approve')).not.toBeNull())
    const rendered = new Set(
      [...document.querySelectorAll('button[id]')].map((b) => b.id),
    )

    expect(rendered).toEqual(new Set(CONTROLS))

    permissions = () => Promise.resolve({ can_review: false, can_approve: false })
    renderDialog()
    const explanation = await waitFor(() => {
      const all = [...document.querySelectorAll('[data-explains]')]
      expect(all).toHaveLength(1)
      return all[0] as HTMLElement
    })
    const declared = new Set(
      (explanation.getAttribute('data-explains') ?? '').split(' ').filter(Boolean),
    )

    expect(declared).toEqual(rendered)
  })
})
