// ui/src/__tests__/VoiceInterviewSpeechPolicy.test.tsx
//
// An engagement that keeps its material on the premises does not hand the interview to Google.
//
// The page has two recognisers, and the second one is the finding. When Deepgram cannot be
// reached the page falls back to the browser's own `SpeechRecognition` - and Chrome streams that
// audio to Google, Safari to Apple, with no contract and no retention undertaking. On an
// engagement not granted hosted inference that fallback is refused outright: the page probes at
// device setup, and an interview that cannot be transcribed does not happen.
//
// **Every refusal here is asserted on what the participant gets AND on the wire.** A status-only
// assertion - or a screen-only one - passes a page that refuses in words and then listens anyway,
// which is the exact defect being closed. So each one checks that no `WebSocket` was constructed
// *and* that no `SpeechRecognition` was ever started.
//
// **And the control is load-bearing.** A change that refused everybody would satisfy every
// refusal assertion in this file. `a standard engagement still falls back` is what distinguishes
// the fix from a page that has simply stopped working, and it is deliberately driven through the
// same failing probe.
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import VoiceInterview from '../pages/VoiceInterview'
import {
  FakeRecorder,
  FakeSocket,
  SCRIPT_THREE_QUESTIONS,
  SCRIPT_TWO_QUESTIONS,
  firstSocket,
  forgetCompletion,
  installAudioAndMic,
  installFetch,
  installSpeechRecognition,
  installStreaming,
  recognisersBuiltSoFar,
  socketAt,
} from './support/voiceInterviewFakes'

const GRANT = { token: 'jwt', listen_params: { model: 'nova-3', language: 'en' } }

/** Render the page without clicking Start - the refusals are about Start not being there. */
function renderInterview() {
  render(
    <MemoryRouter initialEntries={['/interview/tok']}>
      <Routes>
        <Route path="/interview/:sessionToken" element={<VoiceInterview />} />
      </Routes>
    </MemoryRouter>,
  )
}

/**
 * A browser that records only MP4/AAC - Safari, and therefore every iPhone and iPad.
 *
 * `isTypeSupported` answering false to all three containers is what `f914bc56` made decline the
 * Deepgram socket rather than stream a container it was not opened for. On a standard engagement
 * that costs nothing, because the browser's own recogniser picks it up. Here it is fatal, and
 * that is the accepted operational constraint rather than a defect: the alternative is the
 * participant's voice going to Apple.
 */
function installSafariRecorder() {
  vi.stubGlobal('MediaRecorder', class {
    static isTypeSupported = () => false
    start() {}
    stop() {}
  })
}

/** Every request the page made, as [method, url] pairs. */
function requestsFrom(spy: ReturnType<typeof installFetch>): [string, string][] {
  return spy.mock.calls.map(([url, init]) => [
    (init as RequestInit | undefined)?.method ?? 'GET',
    String(url),
  ])
}

/** Nothing at all listened, on either engine. The half a screen assertion cannot see. */
function expectNothingListened() {
  expect(FakeSocket.opened).toEqual([])
  expect(recognisersBuiltSoFar()).toBe(0)
}

describe('an engagement that requires Deepgram', () => {
  beforeEach(() => {
    forgetCompletion()
    vi.restoreAllMocks()
    installAudioAndMic()
  })
  afterEach(() => {
    // Unmount first, then leave a benign fetch standing rather than restoring the real one: an
    // interview started by an earlier test is an async loop that outlives the assertion, and the
    // real `fetch` cannot parse a relative URL in Node. Same reason the keyterms file gives.
    cleanup()
    vi.stubGlobal('fetch', async () => new Response('{}', { status: 200 }))
  })

  // ── Half one of the probe: Deepgram itself ─────────────────────────────────

  it('refuses to start when Deepgram cannot be reached, and reaches no speech service', async () => {
    // The token door answers 503 - no key, a refused key, an exhausted balance. On a standard
    // engagement this is the routine case every deployment before sp66 ran in; here it means the
    // interview does not happen.
    installStreaming()
    installSpeechRecognition('the browser recogniser, which must never be reached')
    vi.stubGlobal('fetch', installFetch('refused', SCRIPT_TWO_QUESTIONS, 'required'))

    renderInterview()

    const notice = await screen.findByTestId('speech-unavailable-notice', undefined, { timeout: 10000 })
    expect(notice.textContent).toMatch(/not available at the moment/i)
    expect(notice.textContent).toMatch(/try your link again later/i)

    // The participant cannot start, which is the point - a warning beside a live button is not a
    // refusal.
    expect(screen.queryByRole('button', { name: /start interview/i })).toBeNull()
    expectNothingListened()
  }, 20000)

  it('never reaches the browser’s recogniser even when the browser has a perfectly good one', async () => {
    // The control for the assertion above, and the one that matters: the refusal must be the
    // policy rather than the absence of a fallback. A browser with `SpeechRecognition` sitting
    // right there, unused.
    installStreaming()
    installSpeechRecognition('An answer the browser heard.')
    vi.stubGlobal('fetch', installFetch('refused', SCRIPT_TWO_QUESTIONS, 'required'))

    renderInterview()
    await screen.findByTestId('speech-unavailable-notice', undefined, { timeout: 10000 })

    // Give the page every chance to change its mind before asserting an absence.
    await new Promise(resolve => setTimeout(resolve, 100))
    expectNothingListened()
    // And the amber "we are carrying on in your browser" notice is nowhere: that sentence is a
    // claim this engagement must never make.
    expect(screen.queryByTestId('recogniser-notice')).toBeNull()
  }, 20000)

  // ── Half two of the probe: the browser's container ─────────────────────────

  it('refuses an iPhone or iPad, on its own, before Deepgram is even asked', async () => {
    // **This half must refuse alone.** Deepgram is perfectly healthy here - the grant would be
    // answered - and the interview still cannot go ahead, because this browser cannot produce
    // audio the socket is opened for. `f914bc56` created this case and it lands on the device a
    // participant is most likely holding.
    installStreaming()
    installSafariRecorder()
    installSpeechRecognition('webkitSpeechRecognition, which Safari has and must not use')
    const fetchSpy = installFetch(GRANT, SCRIPT_TWO_QUESTIONS, 'required')
    vi.stubGlobal('fetch', fetchSpy)

    renderInterview()

    const notice = await screen.findByTestId('speech-unavailable-notice', undefined, { timeout: 10000 })
    expect(notice.textContent).toMatch(/cannot be conducted in this browser/i)
    // Named, because "try a different browser" is useless to somebody holding the only browser
    // their device has.
    expect(notice.textContent).toMatch(/iPhone or iPad/i)

    expect(screen.queryByRole('button', { name: /start interview/i })).toBeNull()
    expectNothingListened()

    // Asked in the right order: no grant was even fetched, because a browser that could never
    // have worked must not be reported to an administrator as a Deepgram outage.
    const urls = requestsFrom(fetchSpy).map(([, url]) => url)
    expect(urls.some(u => u.endsWith('/deepgram-token'))).toBe(false)
  }, 20000)

  it('tells the server which half failed, so the alert names the right problem', async () => {
    // The reason the browser reports at all: this is the half the server cannot see. The
    // vocabulary is closed - the sentence an administrator reads is composed server-side,
    // because this door is unauthenticated.
    installStreaming()
    installSafariRecorder()
    installSpeechRecognition(null)
    const fetchSpy = installFetch(GRANT, SCRIPT_TWO_QUESTIONS, 'required')
    vi.stubGlobal('fetch', fetchSpy)

    renderInterview()
    await screen.findByTestId('speech-unavailable-notice', undefined, { timeout: 10000 })

    await waitFor(() => {
      const reported = fetchSpy.mock.calls.find(([url]) => String(url).endsWith('/speech-failure'))
      expect(reported).toBeTruthy()
      const body = JSON.parse(String((reported![1] as RequestInit).body))
      expect(body.reason).toBe('unsupported_container')
    }, { timeout: 10000 })
  }, 20000)

  // ── Mid-interview ──────────────────────────────────────────────────────────

  it('stops the interview rather than falling back when the socket drops mid-answer', async () => {
    // Credit expiring at answer thirty, or a socket that will not reopen. Falling back to Google
    // is exactly what the probe exists to prevent, so it cannot be the mid-interview answer
    // either - and a participant who has been talking for forty minutes must be told, not left.
    installStreaming()
    installSpeechRecognition('the handover that must not happen')
    const fetchSpy = installFetch(GRANT, SCRIPT_TWO_QUESTIONS, 'required')
    vi.stubGlobal('fetch', fetchSpy)

    renderInterview()
    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))

    const socket = await firstSocket()
    socket.say('Half of an answer that must survive this.', true)
    socket.drop()

    const halted = await screen.findByTestId('speech-halted-notice', undefined, { timeout: 10000 })
    expect(halted.textContent).toMatch(/had to end the interview/i)
    expect(halted.textContent).toMatch(/have been saved/i)
    // **It must not invite a resumption that does not exist.** Nothing reads `checkpoint_json`
    // back, so "try your link again later" - which this said - would send a participant round
    // to question one. The answers are saved; the interview cannot be continued, and the screen
    // now says both.
    expect(halted.textContent).toMatch(/will not pick up where you left off/i)
    expect(halted.textContent).not.toMatch(/try your link again later/i)

    // No handover: the browser's recogniser was never built, on a page that has one available.
    expect(recognisersBuiltSoFar()).toBe(0)
    // And no second socket either - the page did not quietly retry its way back to a service it
    // has just been told is gone.
    expect(FakeSocket.opened).toHaveLength(1)
  }, 20000)

  it('preserves both the completed answer and the one being spoken, then reports', async () => {
    // `save_interview_checkpoint` exists for exactly this, and **the two halves are different
    // code paths**. A completed answer is in `qaRef`; the answer in flight is not, because the
    // interview loop builds its pair after the listen resolves - and a halt means it never will.
    //
    // The first version of this test dropped on question one and asserted the spoken words were
    // kept. It failed, correctly: only `qaRef` was being sent, so the participant's words went
    // with the socket. On the first question of an interview that is the whole interview.
    installStreaming()
    installSpeechRecognition('the handover that must not happen')
    const fetchSpy = installFetch(GRANT, SCRIPT_TWO_QUESTIONS, 'required')
    vi.stubGlobal('fetch', fetchSpy)

    renderInterview()
    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))

    // Question one, answered and committed.
    const first = await firstSocket()
    first.say('A finished answer to the first question.', true)
    await userEvent.click(await screen.findByRole('button', { name: /done speaking/i }))

    // Question two, half spoken when the service goes.
    await screen.findByText(/who decides the order of works/i, undefined, { timeout: 10000 })
    const second = await waitFor(() => {
      expect(FakeSocket.opened.length).toBeGreaterThan(1)
      return FakeSocket.opened[1]
    }, { timeout: 10000 })
    await waitFor(() => expect(second.readyState).toBe(FakeSocket.OPEN))
    second.say('Words spoken into a socket that is about to go.', true)
    second.drop()

    await screen.findByTestId('speech-halted-notice', undefined, { timeout: 10000 })

    await waitFor(() => {
      const calls = fetchSpy.mock.calls.filter(([url]) => String(url).endsWith('/checkpoint'))
      expect(calls.length).toBeGreaterThan(0)
      const body = JSON.parse(String((calls[calls.length - 1][1] as RequestInit).body))
      const kept = JSON.stringify(body.checkpoint)
      // The committed answer...
      expect(kept).toContain('A finished answer to the first question.')
      // ...and the one that had no pair yet, which is the half that was being lost.
      expect(kept).toContain('Words spoken into a socket that is about to go.')
    }, { timeout: 10000 })

    const reported = fetchSpy.mock.calls.find(([url]) => String(url).endsWith('/speech-failure'))
    expect(reported).toBeTruthy()
    const body = JSON.parse(String((reported![1] as RequestInit).body))
    expect(body.reason).toBe('socket_failed')
    // **The completed answers go with the report, and this is what makes the halt screen's
    // promise true.** The checkpoint holds the words with no question id; only these become
    // `interview_answers` rows, which is the only thing the crews read. A halt that sent the
    // report alone left the transcript empty behind a screen saying it had been saved.
    expect(JSON.stringify(body.qa_pairs)).toContain('A finished answer to the first question.')
  }, 25000)

  // ── The sequence nothing drove: the balance runs out mid-interview ─────────

  it('does not report a failure the token door has already diagnosed', async () => {
    // **The sequence, driven.** The grant succeeds at question one; the balance runs out before
    // question two, so `GET /deepgram-token` refuses - and that door has the HTTP status that
    // says "no credit (402) - the balance is exhausted or the card has expired", records it and
    // mails it. All this end knows is "no grant".
    //
    // Reporting `socket_failed` from here wrote "could not hold a streaming connection open -
    // it was refused, or it dropped" **over** the specific sentence, and mailed the operator a
    // second time for one incident. The consultant's panel - the only live leg while
    // ADMIN_ALERT_EMAIL is unset - then showed the vague one.
    //
    // `probeSpeech` has made exactly this judgement since the branch landed; this is it carried
    // into the listen loop.
    installStreaming()
    installSpeechRecognition('must not be reached')
    let grantsAnswered = 0
    const fetchSpy = vi.fn(async (url: string, _init?: RequestInit) => {
      if (url.endsWith('/interviews/tok')) {
        return new Response(JSON.stringify({
          session: { id: 1, session_token: 'tok', node_label: 'x', voice_config: { elevenlabs_voice_id: 'V', language: 'en', country_code: 'GB', model_id: 'm' } },
          script: SCRIPT_TWO_QUESTIONS,
          speech_policy: 'required',
        }), { status: 200 })
      }
      if (url.endsWith('/deepgram-token')) {
        grantsAnswered += 1
        // The probe and question one are answered; the balance runs out after that.
        if (grantsAnswered <= 2) return new Response(JSON.stringify(GRANT), { status: 200 })
        return new Response('{"detail":"Deepgram reports this account has no credit (402)"}', { status: 503 })
      }
      return new Response('{}', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchSpy)

    renderInterview()
    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))

    const first = await firstSocket()
    first.say('An answer given while there was still credit.', true)
    await userEvent.click(await screen.findByRole('button', { name: /done speaking/i }))

    // Question two: no grant, so the interview halts.
    await screen.findByTestId('speech-halted-notice', undefined, { timeout: 10000 })

    const reports = fetchSpy.mock.calls.filter(([url]) => String(url).endsWith('/speech-failure'))
    expect(reports).toHaveLength(1)
    const body = JSON.parse(String((reports[0][1] as RequestInit).body))
    // **`null`, not `socket_failed`.** The server records nothing further and does not alert a
    // second time, so its own specific diagnosis is what the consultant reads.
    expect(body.reason).toBeNull()
    // And the answers still travel, because preserving is not what is being suppressed.
    expect(JSON.stringify(body.qa_pairs)).toContain('An answer given while there was still credit.')
  }, 25000)

  it('does report when the socket itself failed, which the server never saw', async () => {
    // **The control.** A change that suppressed every mid-interview report would pass the test
    // above and would lose the one failure only this end can see: the grant was minted, so the
    // token door answered 200 and recorded nothing, and then the socket dropped.
    installStreaming()
    installSpeechRecognition('must not be reached')
    const fetchSpy = installFetch(GRANT, SCRIPT_TWO_QUESTIONS, 'required')
    vi.stubGlobal('fetch', fetchSpy)

    renderInterview()
    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))

    const socket = await firstSocket()
    socket.drop()

    await screen.findByTestId('speech-halted-notice', undefined, { timeout: 10000 })
    const reports = fetchSpy.mock.calls.filter(([url]) => String(url).endsWith('/speech-failure'))
    expect(reports).toHaveLength(1)
    expect(JSON.parse(String((reports[0][1] as RequestInit).body)).reason).toBe('socket_failed')
  }, 25000)

  it('reports when the grant was good and the socket would not start, which the server never saw', async () => {
    // **The control the drop test could not be.** That one goes through `onDropped`, which is a
    // different branch - so mutating the `!engine` arm to suppress everything left it green.
    // Found by power-check: `halt(null)` unconditionally passed all twelve tests.
    //
    // Here the token door answers 200, so the server records nothing and alerts nobody, and
    // `startDeepgram` still returns null because the recorder cannot be built. If this end also
    // stayed quiet, the incident would reach no one at all - the opposite failure from the
    // double report, and the reason the branch tests the *kind* rather than suppressing wholesale.
    installStreaming()
    vi.stubGlobal('MediaRecorder', class {
      static isTypeSupported = () => true
      constructor() { throw new Error('this browser cannot record from this stream') }
    })
    installSpeechRecognition('must not be reached')
    const fetchSpy = installFetch(GRANT, SCRIPT_TWO_QUESTIONS, 'required')
    vi.stubGlobal('fetch', fetchSpy)

    renderInterview()
    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))

    await screen.findByTestId('speech-halted-notice', undefined, { timeout: 10000 })

    const reports = fetchSpy.mock.calls.filter(([url]) => String(url).endsWith('/speech-failure'))
    expect(reports).toHaveLength(1)
    expect(JSON.parse(String((reports[0][1] as RequestInit).body)).reason).toBe('socket_failed')
  }, 25000)

  it('keeps the words carried across “Finish my last answer” when it then halts', async () => {
    // Minor 6, and the same class as the in-flight answer one closure further out.
    // `listenWithRestart` holds `carried` - everything said before the participant tapped
    // "Finish my last answer" - and `halt()` lives inside `listenForAnswer`, which cannot see
    // that local. Without the mirror, the participant who used that button lost the most.
    installStreaming()
    installSpeechRecognition('must not be reached')
    const fetchSpy = installFetch(GRANT, SCRIPT_THREE_QUESTIONS, 'required')
    vi.stubGlobal('fetch', fetchSpy)

    renderInterview()
    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))

    // Question one, answered and committed, so "Finish my last answer" is offered.
    const first = await firstSocket()
    first.say('The first answer.', true)
    await userEvent.click(await screen.findByRole('button', { name: /done speaking/i }))

    // Question two: say something, then tap "Finish my last answer" - those words become
    // `carried` rather than an answer.
    const second = await socketAt(1)
    second.say('Words that become carried rather than an answer.', true)
    await userEvent.click(await screen.findByRole('button', { name: /finish my last answer/i }))

    // The continuation listen opens another socket, and that is the one that dies.
    const third = await socketAt(2)
    third.drop()

    await screen.findByTestId('speech-halted-notice', undefined, { timeout: 10000 })

    await waitFor(() => {
      const checkpoints = fetchSpy.mock.calls.filter(([url]) => String(url).endsWith('/checkpoint'))
      expect(checkpoints.length).toBeGreaterThan(0)
      const body = JSON.parse(String((checkpoints[checkpoints.length - 1][1] as RequestInit).body))
      expect(JSON.stringify(body.checkpoint)).toContain('Words that become carried rather than an answer.')
    }, { timeout: 10000 })
  }, 30000)

  // ── An absent policy is the strict one ─────────────────────────────────────

  it('treats a payload with no policy at all as requiring Deepgram', async () => {
    // Fail closed. An older API, a truncated response, a field somebody drops later - every one
    // of those must cost an interview rather than silently stream a participant's voice to their
    // browser vendor. The opposite default is the defect this whole finding is about.
    installStreaming()
    installSpeechRecognition('must not be reached')
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/interviews/tok')) {
        return new Response(
          JSON.stringify({
            session: { id: 1, session_token: 'tok', node_label: 'x', voice_config: { elevenlabs_voice_id: 'V', language: 'en', country_code: 'GB', model_id: 'm' } },
            script: SCRIPT_TWO_QUESTIONS,
            // No speech_policy key at all.
          }),
          { status: 200 },
        )
      }
      if (url.endsWith('/deepgram-token')) return new Response('{"detail":"no key"}', { status: 503 })
      return new Response('{}', { status: 200 })
    }))

    renderInterview()

    await screen.findByTestId('speech-unavailable-notice', undefined, { timeout: 10000 })
    expectNothingListened()
  }, 20000)
})

// ── The control, in a file section of its own and last ───────────────────────
//
// It runs a whole interview to completion, and an interview is an async loop that outlives
// `cleanup()` - so it opens sockets and builds recognisers after the test that started it has
// finished. Every assertion above counts exactly those two things, which is why this goes at the
// end: `support/voiceInterviewFakes.tsx` warns that counting sockets is only sound in a file
// whose earlier tests have all stopped.

describe('a standard engagement is unaffected', () => {
  beforeEach(() => {
    forgetCompletion()
    vi.restoreAllMocks()
    installAudioAndMic()
  })
  afterEach(() => {
    cleanup()
    vi.stubGlobal('fetch', async () => new Response('{}', { status: 200 }))
  })

  it('still falls back to the browser’s recogniser on the very same failing probe', async () => {
    // **Without this, a change that refused everybody would pass every test above.** Same 503
    // from the token door, same browser, same script - and here the interview happens, because
    // this engagement permits it.
    installStreaming()
    installSpeechRecognition('An answer the browser heard.')
    vi.stubGlobal('fetch', installFetch('refused', SCRIPT_TWO_QUESTIONS, 'browser_permitted'))

    renderInterview()

    // The button is there, and there is no refusal.
    const start = await screen.findByRole('button', { name: /start interview/i }, { timeout: 10000 })
    expect(screen.queryByTestId('speech-unavailable-notice')).toBeNull()
    await userEvent.click(start)

    // It listened, on the engine this engagement permits.
    await waitFor(() => expect(recognisersBuiltSoFar()).toBeGreaterThan(0), { timeout: 10000 })
    await screen.findByText(/who decides the order of works/i, undefined, { timeout: 10000 })
    expect(screen.queryByTestId('speech-halted-notice')).toBeNull()
  }, 25000)

  it('shows the amber notice when a live socket drops, and carries on', async () => {
    // The other half of the control: the handover behaviour this branch built is untouched on an
    // engagement that permits it - the same drop that halts a required engagement hands over
    // here, keeps what was heard, and says so.
    installStreaming()
    installSpeechRecognition('and the rest of the sentence.')
    vi.stubGlobal('fetch', installFetch(GRANT, SCRIPT_TWO_QUESTIONS, 'browser_permitted'))

    renderInterview()
    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))

    const socket = await firstSocket()
    socket.say('The first half of the answer', true)
    socket.drop()

    const notice = await screen.findByTestId('recogniser-notice', undefined, { timeout: 10000 })
    expect(notice.textContent).toMatch(/carrying on using your browser/i)
    // And it did not halt: this engagement has somewhere to hand over to.
    expect(screen.queryByTestId('speech-halted-notice')).toBeNull()
    expect(FakeRecorder.built.length).toBeGreaterThan(0)
  }, 25000)
})
