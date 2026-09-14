// ui/src/__tests__/InterviewSessionsSpeechFailure.test.tsx
//
// The leg of the alert that reaches the person who would chase the participant.
//
// On an engagement not granted hosted inference, an interview that cannot reach Deepgram stops
// rather than falling back to the browser's own recogniser. Somebody has to know, and the
// somebody is the consultant running the engagement - not the deployment's administrator, who
// would fix the provider but has never met the interviewee.
//
// Nothing in this product notifies anyone: `send_project_mail` is held by `dev_mode`, which
// defaults to `True`, and an administrator's mailbox is not where a consultant looks. So the
// failure is recorded on the interview session row and rendered in the panel they already watch.
// A column, not a notification centre.
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, beforeEach, vi } from 'vitest'

import AveryOutputExtra from '../components/tabs/AveryOutputExtra'
import type { InterviewSessionStatus } from '../types'

const BASE: InterviewSessionStatus = {
  id: 1,
  stakeholder_id: 7,
  name: 'Fiona Marshall',
  node_label: 'Connections Delivery',
  session_token: 'tok-1',
  status: 'pending',
  speech_failure: null,
  interview_url: 'https://example.test/dashboard/interview/tok-1',
  started_at: null,
  completed_at: null,
  created_at: '2026-09-13T09:00:00Z',
}

function installSessions(sessions: InterviewSessionStatus[]) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(
    JSON.stringify({
      orchestration_run_id: 3,
      sessions,
      summary: { pending: sessions.length, active: 0, completed: 0, abandoned: 0 },
    }),
    { status: 200 },
  )))
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <AveryOutputExtra slug="locked-down" />
    </QueryClientProvider>,
  )
}

describe('the interview sessions panel', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('names why a participant could not be interviewed, in the words the operator needs', async () => {
    // The diagnosis, not "something went wrong". A refused key, an exhausted balance and a rate
    // limit are different problems with different remedies, and the whole reason the server
    // classifies the failure is so that the person reading this is not sent to check all three.
    installSessions([{
      ...BASE,
      speech_failure: {
        at: '2026-09-13T10:14:00+00:00',
        diagnosis: 'Deepgram reports this account has no credit (402) - the balance is exhausted or the card has expired',
      },
    }])

    renderPanel()

    const note = await screen.findByTestId('speech-failure-1')
    expect(note.textContent).toMatch(/Not interviewed/i)
    expect(note.textContent).toMatch(/no credit/i)
    // The remedy is in the sentence, which is what makes it worth rendering in full rather than
    // truncating it beside the name.
    expect(note.textContent).toMatch(/card has expired/i)
  })

  it('says nothing at all about a session that has no failure', async () => {
    // **The control.** A panel that rendered the amber note unconditionally would satisfy the
    // assertion above, and would put "Not interviewed" beside every stakeholder on every
    // engagement - which is how a real signal gets ignored.
    installSessions([BASE])

    renderPanel()

    await screen.findByText('Fiona Marshall')
    expect(screen.queryByTestId('speech-failure-1')).toBeNull()
    expect(screen.queryByText(/Not interviewed/i)).toBeNull()
  })

  it('never shows “Not interviewed” beside a completed interview', async () => {
    // The contradiction a consultant would have to resolve rather than act on. The server clears
    // the record when a grant is minted, so the two should not co-occur - but a row recorded
    // before that clearing shipped still carries one, and the panel must not put "completed"
    // and "Not interviewed" on the same line whatever the row says.
    installSessions([{
      ...BASE,
      status: 'completed',
      speech_failure: {
        at: '2026-09-13T09:00:00+00:00',
        diagnosis: 'Deepgram reports this account has no credit (402)',
      },
    }])

    renderPanel()

    await screen.findByText('Fiona Marshall')
    expect(screen.queryByTestId('speech-failure-1')).toBeNull()
    expect(screen.queryByText(/Not interviewed/i)).toBeNull()
    // The status is the fact, and it is still shown.
    expect(screen.getAllByText(/completed/i).length).toBeGreaterThan(0)
  })

  it('still shows it beside an abandoned interview, which is the case it is for', async () => {
    // The control for the suppression above: a halted interview lands at `abandoned`, and that
    // is precisely when the consultant needs to know why. Suppressing on any non-pending status
    // would pass the test above and hide the real signal.
    installSessions([{
      ...BASE,
      status: 'abandoned',
      speech_failure: {
        at: '2026-09-13T09:00:00+00:00',
        diagnosis: 'Deepgram reports this account has no credit (402)',
      },
    }])

    renderPanel()

    const note = await screen.findByTestId('speech-failure-1')
    expect(note.textContent).toMatch(/no credit/i)
  })

  it('marks only the sessions that failed when others in the same run did not', async () => {
    // The shape an engagement actually takes: one participant on an iPhone, the rest fine. A
    // panel keyed on anything but the row - a flag on the run, a banner at the top - would tell
    // the consultant the wrong person to ring.
    installSessions([
      { ...BASE, id: 1, name: 'Fiona Marshall', session_token: 'tok-1' },
      {
        ...BASE,
        id: 2,
        name: 'Duncan Reid',
        session_token: 'tok-2',
        speech_failure: {
          at: '2026-09-13T11:02:00+00:00',
          diagnosis: "this participant's browser records none of the audio containers Deepgram is opened for",
        },
      },
    ])

    renderPanel()

    await screen.findByText('Duncan Reid')
    await waitFor(() => expect(screen.getByTestId('speech-failure-2')).toBeTruthy())
    expect(screen.queryByTestId('speech-failure-1')).toBeNull()
  })
})
