// ui/src/__tests__/JordanOutputExtra.test.tsx
//
// A reply nobody sees is a reply lost, so what is asserted here is that the reply is on the
// screen - the text, the person who sent it, and the unread count - and that the panel is
// wired to the crew a human would go looking under.
//
// Nothing here proves a reply was ever received. taskreimagination.ai is not a verified
// sender domain in Resend, so nothing sends and nothing receives; the backend half is
// asserted against synthetic payloads in tests/test_inbound_replies.py.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import JordanOutputExtra from '../components/tabs/JordanOutputExtra'
import { CREW_OUTPUT_EXTRA } from '../components/AgentDetailPanel'
import { inboundRepliesApi } from '../api/endpoints'

vi.mock('../api/endpoints', () => ({
  inboundRepliesApi: { list: vi.fn(), markRead: vi.fn() },
  projectsApi: {},
  agentChatApi: {},
}))

const REPLY = {
  id: 7,
  stakeholder_id: 3,
  stakeholder_name: 'Harriet Okonkwo',
  stakeholder_email: 'harriet.okonkwo@example.test',
  subject: 'Re: GS Asset Management - A quick reminder',
  body: 'Thursday afternoon suits me. Could we do 3pm?',
  truncated: false,
  attachment_count: 0,
  received_at: '2026-08-18 09:00:00',
  read_at: null as string | null,
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('JordanOutputExtra', () => {
  beforeEach(() => {
    vi.mocked(inboundRepliesApi.list).mockReset()
    vi.mocked(inboundRepliesApi.markRead).mockReset()
  })

  it('shows what the participant wrote, and who wrote it', async () => {
    vi.mocked(inboundRepliesApi.list).mockResolvedValue({ replies: [REPLY], unread: 1 })

    render(<Wrapper><JordanOutputExtra slug="p" /></Wrapper>)

    expect(await screen.findByText(/Thursday afternoon suits me/)).toBeInTheDocument()
    expect(screen.getByText('Harriet Okonkwo')).toBeInTheDocument()
    expect(screen.getByText('1 unread')).toBeInTheDocument()
  })

  it('marks a reply read against the project it is on', async () => {
    // The slug is the assertion. A markRead that dropped it would still turn the button
    // green here while writing to whichever project the server guessed - which is exactly
    // the shape that sent a sensitive project's answers to a hosted model.
    vi.mocked(inboundRepliesApi.list).mockResolvedValue({ replies: [REPLY], unread: 1 })
    vi.mocked(inboundRepliesApi.markRead).mockResolvedValue({ ok: true, changed: true })

    render(<Wrapper><JordanOutputExtra slug="gs-am" /></Wrapper>)
    await userEvent.click(await screen.findByRole('button', { name: /mark read/i }))

    await waitFor(() => {
      expect(inboundRepliesApi.markRead).toHaveBeenCalledWith('gs-am', 7)
    })
  })

  it('says an attachment was not stored rather than implying it was', async () => {
    // The count is all the endpoint keeps - see api/services/inbound_mail.py. A bare
    // paperclip would read as "the file is here".
    vi.mocked(inboundRepliesApi.list).mockResolvedValue({
      replies: [{ ...REPLY, attachment_count: 2 }], unread: 1,
    })

    render(<Wrapper><JordanOutputExtra slug="p" /></Wrapper>)

    expect(await screen.findByText(/not\s+stored, ask the sender/)).toBeInTheDocument()
  })

  it('renders the reply as text, never as markup', async () => {
    // The webhook is unauthenticated. The server stores plain text for exactly this reason,
    // and this component must not be the place that undoes it.
    vi.mocked(inboundRepliesApi.list).mockResolvedValue({
      replies: [{ ...REPLY, body: '<img src=x onerror=alert(1)> hello' }], unread: 1,
    })

    const { container } = render(<Wrapper><JordanOutputExtra slug="p" /></Wrapper>)

    await screen.findByText(/hello/)
    expect(container.querySelector('img')).toBeNull()
  })

  it('says so when the replies could not be loaded', async () => {
    // "No replies yet" over a failed request is the reassuring lie - it looks exactly like
    // a quiet inbox, which is the one thing this panel exists to distinguish.
    vi.mocked(inboundRepliesApi.list).mockRejectedValue(new Error('boom'))

    render(<Wrapper><JordanOutputExtra slug="p" /></Wrapper>)

    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument()
    expect(screen.queryByText(/No replies yet/)).not.toBeInTheDocument()
  })

  it('is the extra panel the stakeholder management crew renders', async () => {
    // The component being correct and unreachable is the same defect as the component being
    // wrong. Asserted on the map the Output tab actually reads.
    expect(CREW_OUTPUT_EXTRA.stakeholder_management).toBe(JordanOutputExtra)
  })
})
