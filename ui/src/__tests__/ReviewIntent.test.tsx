// ui/src/__tests__/ReviewIntent.test.tsx
// The reviewer chooses in their own words. The default is the option that persists nothing,
// so a reviewer in a hurry cannot seed project truth or the global library by accident.
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import ReviewDialog from '../components/ReviewDialog'

const resolveReview = vi.fn().mockResolvedValue({})

vi.mock('../api/endpoints', () => ({
  projectsApi: { resolveReview: (...a: unknown[]) => resolveReview(...a) },
  skillNotesApi: { create: vi.fn().mockResolvedValue({}) },
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
    fireEvent.click(screen.getByRole('button', { name: /request revision/i }))
    expect(screen.getByLabelText(/fix this output/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/true of this client/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/every project/i)).toBeInTheDocument()
  })

  it('defaults to fixing this output', async () => {
    render(<Wrapper />)
    fireEvent.click(screen.getByRole('button', { name: /request revision/i }))
    expect(screen.getByLabelText(/fix this output/i)).toBeChecked()
  })

  it('sends the chosen intent', async () => {
    render(<Wrapper />)
    fireEvent.click(screen.getByRole('button', { name: /request revision/i }))
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
})
