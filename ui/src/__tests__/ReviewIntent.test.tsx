// ui/src/__tests__/ReviewIntent.test.tsx
// The reviewer chooses in their own words. The default is the option that persists nothing,
// so a reviewer in a hurry cannot seed project truth or the skills queue by accident.
//
// The third option's label moved in sp65 - from "Do this on every project" to "Make this a
// standing rule for this agent" - because what it does moved with it. It used to set a column
// nothing read; it now files a proposal that a human approves and scopes, defaulting to this
// engagement. A control promising to change an agent's behaviour everywhere is precisely what
// the scope decision exists to stop happening without anybody choosing it, so the locators
// below follow the copy rather than the copy being kept to suit them.
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import ReviewDialog from '../components/ReviewDialog'

const resolveReview = vi.fn().mockResolvedValue({})

// `can_review: true` is this file's premise, stated rather than assumed. The dialog's three
// decision controls render only when `GET /my-permissions` says the caller may resolve the
// review - the door they post to asks `caller_may_contribute` - so without this every test
// below would fail on a missing button rather than on anything to do with intent. What is
// asserted about gating lives in ReviewDialogAuthority.test.tsx.
const resolveGrant = { can_review: true, can_approve: true }

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    resolveReview: (...a: unknown[]) => resolveReview(...a),
    getMyPermissions: () => Promise.resolve(resolveGrant),
  },
}))

const review = {
  id: 1, crew_name: 'discovery_mapping', prompt: 'Please review the value chain.',
  decision: 'pending',
}

function Wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <ReviewDialog slug="acme" review={review as never} outputs={[]} onClose={() => {}} />
    </QueryClientProvider>
  )
}

describe('review intent', () => {
  beforeEach(() => resolveReview.mockClear())

  it("offers the three choices in the reviewer's language", async () => {
    render(<Wrapper />)
    fireEvent.click(await screen.findByRole('button', { name: /request revision/i }))
    expect(screen.getByLabelText(/fix this output/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/true of this client/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/standing rule for this agent/i)).toBeInTheDocument()
  })

  it('says the standing rule waits for a human, and does not promise it applies everywhere', async () => {
    // The old copy said "becomes a capability this agent uses everywhere", which was untrue in
    // both halves: nothing read the column it set, and a proposal now waits in a queue and is
    // scoped to this engagement unless a reviewer widens it. A reviewer choosing this option
    // is choosing to raise a suggestion, and the control has to say so.
    render(<Wrapper />)
    fireEvent.click(await screen.findByRole('button', { name: /request revision/i }))
    const option = screen.getByLabelText(/standing rule for this agent/i)
      .closest('label') as HTMLElement

    expect(option.textContent).toMatch(/until a reviewer approves it/i)
    expect(option.textContent).not.toMatch(/uses everywhere/i)
  })

  it('defaults to fixing this output', async () => {
    render(<Wrapper />)
    fireEvent.click(await screen.findByRole('button', { name: /request revision/i }))
    expect(screen.getByLabelText(/fix this output/i)).toBeChecked()
  })

  it('sends the chosen intent', async () => {
    render(<Wrapper />)
    fireEvent.click(await screen.findByRole('button', { name: /request revision/i }))
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'ISS only maintains property' },
    })
    fireEvent.click(screen.getByLabelText(/true of this client/i))
    fireEvent.click(screen.getByRole('button', { name: /submit revision request/i }))

    await waitFor(() =>
      expect(resolveReview).toHaveBeenCalledWith(
        'acme', 1, 'changes_requested', 'ISS only maintains property', 'correction',
      ),
    )
  })

  it('sends skill when the reviewer asks for a standing rule', async () => {
    // Asserted on what is **sent**, not on what the radio renders. It is the value the server
    // routes on: `intent='skill'` is what files the reviewer's sentence on the skills queue,
    // and a form that rendered the choice and sent `change_request` would look identical here
    // and file nothing at all - which is the state this option was in before sp65.
    render(<Wrapper />)
    fireEvent.click(await screen.findByRole('button', { name: /request revision/i }))
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Refer to investments by their purpose, never by their figure' },
    })
    fireEvent.click(screen.getByLabelText(/standing rule for this agent/i))
    fireEvent.click(screen.getByRole('button', { name: /submit revision request/i }))

    await waitFor(() =>
      expect(resolveReview).toHaveBeenCalledWith(
        'acme', 1, 'changes_requested',
        'Refer to investments by their purpose, never by their figure', 'skill',
      ),
    )
  })

  it('sends change_request when the reviewer submits without touching any radio', async () => {
    render(<Wrapper />)
    fireEvent.click(await screen.findByRole('button', { name: /request revision/i }))
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Looks mostly right, just tighten the summary' },
    })
    fireEvent.click(screen.getByRole('button', { name: /submit revision request/i }))

    await waitFor(() =>
      expect(resolveReview).toHaveBeenCalledWith(
        'acme', 1, 'changes_requested', 'Looks mostly right, just tighten the summary', 'change_request',
      ),
    )
  })
})
