// ui/src/__tests__/VoiceInterviewReviewStep.test.tsx
//
// The last screen a participant meets: review, correct, finish. Findings 7 and 8 of the
// 4 September walkthrough - 39 minutes, 59 answers - both live here.
//
// Every assertion below is made on the *request* or on a *queried control*, never on a hover
// and never on a snapshot, and each choice is a defect this project has already shipped once:
//
//  - Finding 7 was an affordance that existed and was not found: a `text-gray-300` pencil,
//    per answer, fifty-nine of them. A test that hovered would have passed against the pencil.
//    So the fields are asked for by role and name instead.
//
//  - Finding 8 was `POST /interviews/{token}/email-transcript` answering `{"sent": true}` to a
//    participant who never received anything - `dev_mode` holds project mail and `FROM_EMAIL`
//    names a domain Resend has not verified. It is the only path in the product where the
//    person who triggered the action is told it worked. So the assertion is that **no request
//    is made**: deleting the checkbox and leaving the post would satisfy a rendering assertion
//    perfectly, and would fix nothing at all.
//
//  - And an edit has to *arrive*. It reached the server only inside the email post's body, so
//    a participant who did not tick the box corrected their transcript into a state variable
//    that was then discarded. Removing the post without replacing the route would have turned
//    the whole correction step into decoration - with a green suite, because the corrected text
//    renders in the box either way. Every assertion here reads the body that was sent.
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import VoiceInterview from '../pages/VoiceInterview'

/** Three questions in one section, so the review step carries three answers to correct. */
const SCRIPT = {
  script_id: 'SC-014',
  node_label: 'Order Fulfilment',
  level: 'L2',
  research_brief: '',
  study_objectives: [],
  welcome_message: 'Welcome.',
  sections: [
    {
      section_id: 'S1',
      title: 'Operations',
      questions: [1, 2, 3].map(n => ({
        id: `q${n}`,
        text: `Question ${n}?`,
        follow_up_count: 0,
        probing_instructions: '',
        follow_up_branches: [],
        evasion_signals: [],
      })),
      // A rating the interview collects and the review step never shows. It is here because
      // the corrections are re-submitted to the same door that stores the ratings, and that
      // door writes `ratings_json` unconditionally - so a resubmission that forgot them would
      // correct the transcript and silently discard every rating, answering 200 either way.
      maturity_rating: {
        dimension: 'Capability',
        prompt: 'How mature is this, nought to four?',
        scale: { '0': 'Absent', '1': 'Initial', '2': 'Repeatable', '3': 'Defined', '4': 'Optimised' },
      },
    },
  ],
  closing_message: 'Thank you.',
}

const VOICE = { elevenlabs_voice_id: 'V', language: 'en', country_code: 'GB', model_id: 'm' }

const SESSION = {
  id: 1,
  stakeholder_id: 1,
  node_label: 'Order Fulfilment',
  session_token: 'tok',
  status: 'pending',
  voice_config: VOICE,
}

/** Every request the page made, in order: method, url, and the parsed body. */
type SentRequest = { method: string; url: string; body: Record<string, unknown> | null }
let sent: SentRequest[] = []

function urlsSent(): string[] {
  return sent.map(r => r.url)
}

/** The bodies of every PATCH to `/complete`, in order. The transcript's only route to the server. */
function completionBodies(): Record<string, unknown>[] {
  return sent.filter(r => r.url.endsWith('/complete')).map(r => r.body as Record<string, unknown>)
}

/**
 * How `/complete` answers, switched *after* the review step has been reached.
 *
 * **Both fetch fakes in this suite answered 200 for `/complete` unconditionally**, which is why
 * finding I4 - a Finish button that claimed success whatever the server said - could not be seen
 * by any test. A fake that only ever succeeds cannot distinguish a page that reports the outcome
 * from one that ignores it. The switch is deliberately flipped after the first, successful
 * submission, because that is the real scenario: the interview was recorded, and it is the
 * *corrections* that are at risk.
 */
let completeResponds: 'ok' | 'refused' | 'offline' = 'ok'

function installFetch() {
  return vi.fn(async (url: string, init?: RequestInit) => {
    let body: Record<string, unknown> | null = null
    if (init?.body) {
      try { body = JSON.parse(String(init.body)) } catch { body = null }
    }
    sent.push({ method: init?.method ?? 'GET', url, body })

    if (url.endsWith('/complete')) {
      // Two ways it fails, and the page swallowed both. A 5xx is a server that answered; a
      // thrown fetch is connectivity gone, which is the scenario in the finding - forty-five
      // minutes on the page, the network dropped, three answers corrected.
      if (completeResponds === 'offline') throw new TypeError('Failed to fetch')
      if (completeResponds === 'refused') return new Response('{"detail":"nope"}', { status: 503 })
      return new Response('{}', { status: 200 })
    }

    if (url.endsWith('/interviews/tok')) {
      // Declared, because the page fails closed on an absent policy - see the note in
      // `support/voiceInterviewFakes.tsx`. This is a standard engagement.
      return new Response(
        JSON.stringify({ session: SESSION, script: SCRIPT, speech_policy: 'browser_permitted' }),
        { status: 200 },
      )
    }
    if (url.endsWith('/speak')) {
      return new Response(new Blob([new Uint8Array([1, 2, 3])]), { status: 200 })
    }
    return new Response('{}', { status: 200 })
  })
}

/** A recogniser that hears the same thing every time, so the answers are known text. */
function installSpeechRecognition(transcript: string) {
  class FakeRecognition {
    continuous = false
    interimResults = false
    lang = ''
    onresult: ((e: unknown) => void) | null = null
    onend: (() => void) | null = null
    onerror: ((e: { error: string }) => void) | null = null

    start() {
      setTimeout(() => {
        this.onresult?.({
          resultIndex: 0,
          results: [Object.assign([{ transcript }], { isFinal: true })],
        })
        this.onerror?.({ error: 'no-speech' })
        this.onend?.()
      }, 0)
    }

    stop() { this.onend?.() }
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).SpeechRecognition = FakeRecognition
}

function installAudioAndMic() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).Audio = class {
    onended: (() => void) | null = null
    onerror: (() => void) | null = null
    play() {
      setTimeout(() => this.onended?.(), 0)
      return Promise.resolve()
    }
  }
  URL.createObjectURL = vi.fn(() => 'blob:fake')
  URL.revokeObjectURL = vi.fn()
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      enumerateDevices: async () => [
        { kind: 'audioinput', deviceId: 'mic-1', label: 'Built-in Microphone' },
      ],
      getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }),
    },
  })
}

/**
 * Walk the participant's path to the review step: start, answer three questions, tap the
 * maturity rating, and arrive where the corrections are made.
 *
 * Driven end to end rather than rendered in isolation, because the transcript the review step
 * corrects is a snapshot of what the interview captured - a hand-built props object would let
 * this file pass against a page that never populated it.
 */
async function reachTheReviewStep(spoken = 'The recogniser heard this.') {
  sent = []
  completeResponds = 'ok'
  vi.stubGlobal('fetch', installFetch())
  installSpeechRecognition(spoken)
  installAudioAndMic()

  render(
    <MemoryRouter initialEntries={['/interview/tok']}>
      <Routes>
        <Route path="/interview/:sessionToken" element={<VoiceInterview />} />
      </Routes>
    </MemoryRouter>,
  )

  await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))

  // The section's maturity rating, tapped rather than spoken.
  const three = await screen.findByRole('button', { name: /^3\b/ }, { timeout: 5000 })
  await userEvent.click(three)

  // The interview has been submitted once, unedited, and the review step is showing.
  await waitFor(() => expect(completionBodies().length).toBe(1), { timeout: 5000 })
  await screen.findByRole('button', { name: /^finish$/i })
}

const finishTheReview = async () => {
  await userEvent.click(screen.getByRole('button', { name: /^finish$/i }))
  await screen.findByText(/may now close this window/i)
}

describe('the review and correction step', () => {
  beforeEach(() => { vi.restoreAllMocks() })
  afterEach(() => {
    // Unmount BEFORE unstubbing, then leave a benign stub rather than restoring the real
    // `fetch`. The interview is an async loop that outlives the assertion, and Node cannot
    // parse a relative URL - which vitest reports as "this might cause false positive tests".
    cleanup()
    vi.stubGlobal('fetch', async () => new Response('{}', { status: 200 }))
  })

  it('offers every answer for editing without a click to reveal', async () => {
    await reachTheReviewStep()

    // Queried, not hovered. The defect was an affordance that existed and was not found: a
    // `text-gray-300` pencil, one per answer, on a screen that carried 59 of them.
    const fields = screen.getAllByRole('textbox', { name: /your answer/i })
    expect(fields).toHaveLength(3)
    // And each already holds its answer, so they are the answers' own fields rather than
    // three empty boxes beside three read-only paragraphs.
    for (const field of fields) {
      expect((field as HTMLTextAreaElement).value).toBe('The recogniser heard this.')
    }

    // The control that hid them is gone, and so is its tooltip.
    expect(screen.queryByRole('button', { name: /edit this response/i })).toBeNull()
    expect(document.querySelector('[title="Edit this response"]')).toBeNull()
  })

  it('sends the corrected answer, not the recorded one', async () => {
    await reachTheReviewStep()

    const fields = screen.getAllByRole('textbox', { name: /your answer/i })
    await userEvent.clear(fields[1])
    await userEvent.type(fields[1], 'Iberdrola, not ever brola.')

    await finishTheReview()

    // Read off the wire. The corrected text renders in the box whether or not it is ever
    // submitted, so asserting the box would pass against a page that discards the edit -
    // which is exactly what this page did for any participant who left the email box unticked.
    const bodies = completionBodies()
    expect(bodies).toHaveLength(2)
    const pairs = bodies[1].qa_pairs as { question: string; answer: string; question_id: string }[]
    expect(pairs.map(p => p.answer)).toEqual([
      'The recogniser heard this.',
      'Iberdrola, not ever brola.',
      'The recogniser heard this.',
    ])
    // With its address intact: `/complete` requires `question_id` on every pair, so a
    // correction sent as bare question-and-answer text would be refused at the door.
    expect(pairs.every(p => typeof p.question_id === 'string' && p.question_id.length > 0)).toBe(true)
  })

  it('re-states the ratings when it submits the corrections, rather than erasing them', async () => {
    // `complete_interview_session` writes `ratings_json` on every call, so a resubmission that
    // omitted the ratings would null them - the transcript corrected, the maturity ratings
    // gone, 200 both times. The interview collects one; both submissions must carry it.
    await reachTheReviewStep()
    await finishTheReview()

    const bodies = completionBodies()
    expect(bodies).toHaveLength(2)
    for (const body of bodies) {
      expect(body.ratings).toEqual([
        { section_title: 'Operations', dimension: 'Capability', rating: 3 },
      ])
    }
  })

  it('never posts to email-transcript', async () => {
    // Asserted on the request, not on the checkbox. The defect was a post that SUCCEEDED and
    // delivered nothing - `{"sent": true}` to a participant who never received it. Removing
    // the control and leaving the post would pass any assertion about what renders.
    await reachTheReviewStep()

    const fields = screen.getAllByRole('textbox', { name: /your answer/i })
    await userEvent.clear(fields[0])
    await userEvent.type(fields[0], 'Something worth mailing to myself.')

    await finishTheReview()

    expect(urlsSent().some(u => /email-transcript/.test(u))).toBe(false)
    // Nor is there a control asking for an address to send it to.
    expect(screen.queryByPlaceholderText(/email address/i)).toBeNull()
    expect(screen.queryByRole('checkbox')).toBeNull()
  })

  it('tells the participant the transcript is not emailed, and names the control that copies it', async () => {
    await reachTheReviewStep()

    expect(screen.getByText(/not emailed/i)).toBeTruthy()
    // The note names a Copy button, so the button has to exist - a note pointing at a control
    // nobody built is the same defect as a button that posts and delivers nothing.
    const copy = screen.getByRole('button', { name: /^copy$/i })

    const written: string[] = []
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: async (text: string) => { written.push(text) } },
    })
    await userEvent.click(copy)

    await waitFor(() => expect(written).toHaveLength(1))
    expect(written[0]).toContain('Question 2?')
    expect(written[0]).toContain('The recogniser heard this.')
    // And it says so, which is the half the case below is about.
    await screen.findByRole('button', { name: /copied/i })
  })

  it('does not say “Copied” when this browser has no clipboard for it to copy to', async () => {
    // `navigator.clipboard` is **undefined in any non-secure context** - a plain-http
    // on-premises deployment, which is exactly the secure-mode customer - and
    // `await navigator.clipboard?.writeText(...)` short-circuits to `undefined`. `await
    // undefined` does not throw, so the `catch` never ran and the button said "Copied" over an
    // empty clipboard. This branch removed the email route, so the button is a participant's
    // only path to their own transcript: they tap Copy, read "Copied", close the window, and
    // have nothing.
    await reachTheReviewStep()

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (navigator as any).clipboard
    await userEvent.click(screen.getByRole('button', { name: /^copy$/i }))

    expect(screen.queryByRole('button', { name: /^copied$/i })).toBeNull()
    await screen.findByRole('button', { name: /could not copy/i })
  })

  it('gives the participant the transcript to copy by hand when it cannot copy for them', async () => {
    // Withdrawing the false claim is necessary and not sufficient: a participant told "could
    // not copy" and left with 59 separate answer fields has still lost their transcript. The
    // whole text is offered in one selectable field, which is a route they can actually take.
    await reachTheReviewStep()

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (navigator as any).clipboard
    await userEvent.click(screen.getByRole('button', { name: /^copy$/i }))

    const offered = await screen.findByRole('textbox', { name: /your transcript/i })
    expect((offered as HTMLTextAreaElement).value).toContain('Question 2?')
    expect((offered as HTMLTextAreaElement).value).toContain('The recogniser heard this.')
    // Read-only: this is the copy, not a second place to correct the answers.
    expect((offered as HTMLTextAreaElement).readOnly).toBe(true)
  })

  // ── Finding I4: Finish claimed success whatever the server said ─────────────
  //
  // `postCompletion` swallowed a non-ok response and a thrown fetch alike, and
  // `handleFinishInterview` then set `finished` unconditionally - rendering "Your responses have
  // been recorded. You may now close this window." and unmounting the transcript behind it. A
  // participant forty-five minutes in, whose connection had gone, corrected three mangled answers,
  // tapped Finish, was told it worked, and closed the window.
  //
  // The original answers survive from the first submission, so what is lost is the *corrections* -
  // but it is the one button the participant triggers and is told about, which is the exact shape
  // this branch exists to remove.

  it.each([
    ['the server refuses', 'refused' as const],
    ['the connection has gone', 'offline' as const],
  ])('does not claim the corrections were saved when %s', async (_name, failure) => {
    await reachTheReviewStep()

    const fields = screen.getAllByRole('textbox', { name: /your answer/i })
    await userEvent.clear(fields[0])
    await userEvent.type(fields[0], 'The correction that must not be silently lost.')

    completeResponds = failure
    await userEvent.click(screen.getByRole('button', { name: /^finish$/i }))

    // The sentence that was the defect is absent.
    await waitFor(() =>
      expect(screen.queryByText(/may now close this window/i)).toBeNull(),
    )
    // And the truth is said, assertively - a participant about to close the tab must not have to
    // notice a polite live region.
    const problem = await screen.findByTestId('finish-error')
    expect(problem.textContent).toMatch(/could not save your corrections/i)
    // It says which is at risk: the interview is safe, the edits are not. Telling somebody their
    // whole interview was lost would be its own false claim.
    expect(problem.textContent).toMatch(/original answers are safe/i)
  })

  it('keeps the transcript on screen so the corrections can be sent again', async () => {
    // Telling the truth is necessary and not sufficient. The screen used to unmount every field
    // the moment `finished` was set, so a participant told it had failed would have had nothing
    // left to retry with - which is the same loss by a more honest route.
    await reachTheReviewStep()

    const fields = screen.getAllByRole('textbox', { name: /your answer/i })
    await userEvent.clear(fields[0])
    await userEvent.type(fields[0], 'The correction that must survive a failed save.')

    completeResponds = 'offline'
    await userEvent.click(screen.getByRole('button', { name: /^finish$/i }))
    await screen.findByTestId('finish-error')

    // Every field is still there, and still holds what was typed.
    const after = screen.getAllByRole('textbox', { name: /your answer/i })
    expect(after).toHaveLength(3)
    expect((after[0] as HTMLTextAreaElement).value).toBe('The correction that must survive a failed save.')

    // And there is something to press. Named for what it now does.
    await screen.findByRole('button', { name: /try again/i })
  })

  it('sends the corrections and reports success once the connection comes back', async () => {
    // **The control.** Without it, a change that never claimed success would pass every
    // assertion above - and would be a page nobody could ever finish. The retry is driven
    // through the same button, and the corrected text is asserted on the *body that was sent*
    // rather than on the screen, because a retry that showed the success screen without
    // resubmitting is the failure this pair is really about.
    await reachTheReviewStep()

    const fields = screen.getAllByRole('textbox', { name: /your answer/i })
    await userEvent.clear(fields[0])
    await userEvent.type(fields[0], 'The correction that eventually arrives.')

    completeResponds = 'offline'
    await userEvent.click(screen.getByRole('button', { name: /^finish$/i }))
    await screen.findByTestId('finish-error')

    const before = completionBodies().length
    completeResponds = 'ok'
    await userEvent.click(screen.getByRole('button', { name: /try again/i }))

    await screen.findByText(/may now close this window/i)
    const bodies = completionBodies()
    expect(bodies.length).toBeGreaterThan(before)
    const last = bodies[bodies.length - 1]
    expect(JSON.stringify(last.qa_pairs)).toContain('The correction that eventually arrives.')
    // The ratings ride along, as they must: `/complete` writes `ratings_json` unconditionally,
    // so a resubmission that omitted them would correct the transcript and discard every rating.
    expect(last.ratings).toBeTruthy()
    // And the notice is gone rather than left standing beside a success message.
    expect(screen.queryByTestId('finish-error')).toBeNull()
  })

  it('does not say “Copied” when the clipboard exists and refuses', async () => {
    // The other way the write fails, and the one the original `catch` did cover. Kept as a
    // control: a fix that only tested for the clipboard's *absence* would leave this arm
    // claiming a copy that a permission prompt had just refused.
    await reachTheReviewStep()

    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: async () => { throw new Error('refused by the user') } },
    })
    await userEvent.click(screen.getByRole('button', { name: /^copy$/i }))

    expect(screen.queryByRole('button', { name: /^copied$/i })).toBeNull()
    await screen.findByRole('button', { name: /could not copy/i })
  })
})
