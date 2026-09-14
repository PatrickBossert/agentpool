// ui/src/__tests__/VoiceInterviewKeyterms.test.tsx
//
// What the interview portal actually sends to Deepgram.
//
// Asserted on the **socket**, never on the helper. `GET /api/interviews/{token}/deepgram-token`
// had existed since SP10f and nothing in `ui/src` had ever called it - a perfect helper with no
// caller is precisely how this path came to exist, so a test that drove `deepgramListenUrl` and
// stopped there would reproduce the defect it is meant to close. Every assertion below reads the
// URL handed to `new WebSocket` by a rendered, running interview.
import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import {
  FLUSH_TIMEOUT_MS,
  deepgramListenUrl,
  fetchDeepgramGrant,
  openDeepgramSocket,
  startPcmCapture,
} from '../api/deepgram'
import {
  FakeAudioContext,
  FakeAudioWorkletNode,
  FakeSocket,
  SCRIPT_TWO_QUESTIONS,
  completionPosted,
  completionsPosted,
  firstSocket,
  forgetCompletion,
  installAudioAndMic,
  installFetch,
  installSpeechRecognition,
  installStreaming,
  fakeAudioContext,
  fakeStream,
  recognisersBuiltSoFar,
  startInterview,
} from './support/voiceInterviewFakes'

// The vocabulary the *server* answered with. Nothing in the component may name any of these -
// that is what makes the assertions about a project's own words rather than about a constant.
const OUR_KEYTERMS = ['Renewals CapEx Allocation', 'Iberdrola', 'SP Energy Networks']

function paramsOf(url: string) {
  return new URL(url).searchParams
}

/**
 * Wait for the completion **this** interview posted, identified by what its own recogniser heard.
 *
 * `completionPosted()` alone is unsound in this file: an earlier test's interview outlives its
 * test and posts through the current `fetch` stub, so the latest completion may be a stranger's.
 * Scanning for this test's own transcript is the only thing that tells them apart, and a
 * completion that never arrives fails on the timeout rather than passing on somebody else's.
 */
async function answersOfInterviewHearing(expected: string): Promise<string> {
  let answers = ''
  await waitFor(() => {
    const mine = completionsPosted()
      .map(body => (body.qa_pairs ?? []).map(pair => pair.answer).join(' '))
      .find(joined => joined.includes(expected))
    expect(mine, `no completion carried ${JSON.stringify(expected)}`).toBeTruthy()
    answers = mine!
  }, { timeout: 15000 })
  return answers
}

describe('the recogniser is told the project’s own words', () => {
  beforeEach(() => {
    forgetCompletion()
    vi.restoreAllMocks()
    installAudioAndMic()
  })
  afterEach(() => {
    // Unmount before touching globals, and never restore the real `fetch`. The interview is an
    // async loop that outlives the assertion - it speaks the next question whether or not a
    // test is still watching - so `vi.unstubAllGlobals()` here let a late `speakText` reach the
    // real one, which cannot parse a relative URL in Node. It surfaced exactly as
    // VoiceInterviewStampedVoice.test.tsx warns: `Errors 1 error` beside a green run, under
    // vitest's own "this might cause false positive tests". Vitest isolates test files, so the
    // WebSocket and audio-graph stubs left standing here reach nothing else.
    cleanup()
    vi.stubGlobal('fetch', async () => new Response('{}', { status: 200 }))
  })

  // ── Step 4: what is sent on the socket ─────────────────────────────────────

  it('sends the project’s keyterms on the socket it opens', async () => {
    installStreaming()
    installSpeechRecognition('should not be reached')
    vi.stubGlobal('fetch', installFetch({
      token: 'jwt-from-the-server',
      listen_params: { model: 'nova-3', language: 'en', smart_format: 'true', keyterm: OUR_KEYTERMS },
    }))

    await startInterview()
    const socket = await firstSocket()
    const params = paramsOf(socket.url)

    expect(socket.url.startsWith('wss://api.deepgram.com/v1/listen?')).toBe(true)
    // Repeated, not joined: `keyterm=A&keyterm=B` is how Deepgram spells a list, and a single
    // comma-joined value would be one very long term that matches nothing.
    expect(params.getAll('keyterm')).toEqual(OUR_KEYTERMS)
    expect(params.get('model')).toBe('nova-3')
    // The JWT travels as `access_token`. Deepgram answers 401 to a JWT offered through
    // Sec-WebSocket-Protocol, which is the API-key form.
    expect(params.get('access_token')).toBe('jwt-from-the-server')
    // The legacy parameter belongs to Nova-2 and is silently ignored by Nova-3 - a connection
    // that succeeds and boosts nothing is the failure this whole task is about.
    expect(params.get('keywords')).toBeNull()
  })

  it('sends whatever the server answered, not a list of its own', async () => {
    // The control for the test above. A component carrying a hardcoded vocabulary would pass
    // that assertion on the one project whose words it happened to hold, and this one proves
    // the words came down the wire: a different engagement, different terms, same code.
    const theirs = ['Berth Allocation', 'Clydeport']
    installStreaming()
    installSpeechRecognition('should not be reached')
    vi.stubGlobal('fetch', installFetch({
      token: 'jwt',
      listen_params: { model: 'nova-3', language: 'en', keyterm: theirs },
    }))

    await startInterview()
    const params = paramsOf((await firstSocket()).url)

    expect(params.getAll('keyterm')).toEqual(theirs)
    for (const ours of OUR_KEYTERMS) expect(params.getAll('keyterm')).not.toContain(ours)
  })

  it('reads what comes back on the socket, and carries it into the transcript', async () => {
    // Opening a socket with the right words on it proves nothing if the transcripts coming back
    // are thrown away. This drives one interim frame and one final frame and follows both - the
    // caption the participant watches, and the answer that reaches /complete.
    installStreaming()
    installSpeechRecognition('the browser recogniser, which must not be what is recorded')
    vi.stubGlobal('fetch', installFetch({
      token: 'jwt',
      listen_params: { model: 'nova-3', keyterm: OUR_KEYTERMS },
    }))

    await startInterview()
    const socket = await firstSocket()

    socket.say('Iberdrola sets the', false)
    expect(await screen.findByText(/Iberdrola sets the/)).toBeTruthy()

    socket.say('Iberdrola sets the reporting calendar.', true)
    await userEvent.click(await screen.findByRole('button', { name: /done speaking/i }))

    const answers = await answersOfInterviewHearing('Iberdrola sets the reporting calendar.')
    expect(answers).not.toContain('the browser recogniser')
  }, 20000)

  // ── Step 5: a project with nothing still connects ──────────────────────────

  it('connects with no keyterms at all when the project has none', async () => {
    // Note the completion wait at the end. Without it this interview outlives its own test and
    // posts into the next one - see `answersOfInterviewHearing` above for what that cost.
    // The control without which a fix that never connected would pass every assertion above.
    installStreaming()
    installSpeechRecognition('should not be reached')
    vi.stubGlobal('fetch', installFetch({
      token: 'jwt',
      listen_params: { model: 'nova-3', language: 'en', smart_format: 'true' },
    }))

    await startInterview()
    const socket = await firstSocket()
    const params = paramsOf(socket.url)

    expect(params.getAll('keyterm')).toEqual([])
    expect(socket.url).not.toContain('keyterm')
    // It still connected, and it is still configured.
    expect(params.get('model')).toBe('nova-3')
    expect(params.get('access_token')).toBe('jwt')

    // Settled inside its own test. Left running, this interview answers the remaining question
    // and posts a completion through whatever `fetch` stub is installed by then - which lands in
    // a later test as an answer that test's recogniser never heard. It is what happened: an
    // extra `await` in `startDeepgram` shifted it one test to the right and failed an assertion
    // about the browser fallback that had nothing to do with the change.
    socket.say('An answer, so this interview finishes inside its own test.', true)
    await userEvent.click(await screen.findByRole('button', { name: /done speaking/i }))
    await answersOfInterviewHearing('An answer, so this interview finishes inside its own test.')
  }, 20000)

  // ── Step 6: the fallback a participant meets ───────────────────────────────

  it('falls back to the browser’s recogniser when the deployment has no Deepgram key', async () => {
    // 503 from the token door. The interview must happen - this is the deployment every
    // interview before this task ran on - and it must not be reported as broken.
    //
    // **The silence assertion is made mid-interview, on the second question.** It used to sit
    // after `completedBody`, on the review screen, where the notice is not rendered at all -
    // so it answered null however the code behaved. Mutation found it: making `no-speech`
    // report a failure, which would put an amber notice on every silent moment of every
    // interview, left the old version green.
    installStreaming()
    installSpeechRecognition('An answer the browser heard.')
    vi.stubGlobal('fetch', installFetch('refused', SCRIPT_TWO_QUESTIONS))

    await startInterview()

    // Still interviewing, and nothing has been said to the participant: the fallback is
    // silent, which is the whole of the first of the five cases.
    await screen.findByText(/who decides the order of works/i, undefined, { timeout: 10000 })
    expect(screen.queryByTestId('recogniser-notice')).toBeNull()

    const answers = await answersOfInterviewHearing('An answer the browser heard.')
    // Deepgram was never reached at all - the 503 is the whole of it.
    expect(FakeSocket.opened).toEqual([])
    expect(answers).toContain('An answer the browser heard.')
  }, 20000)

  it('hands a dropped connection to the browser mid-answer, and says so', async () => {
    // The case that reaches a real person: a participant talking into a socket that has gone.
    // Both halves are required - what was already said is kept and they are told plainly - and
    // neither is enough on its own.
    installStreaming()
    installSpeechRecognition('and the rest of the sentence.')
    vi.stubGlobal('fetch', installFetch({
      token: 'jwt', listen_params: { model: 'nova-3', keyterm: OUR_KEYTERMS },
    }))

    await startInterview()
    const socket = await firstSocket()
    socket.say('The first half of the answer', true)
    socket.drop()

    const notice = await screen.findByTestId('recogniser-notice')
    expect(notice.textContent).toMatch(/dropped out/i)
    expect(notice.textContent).toMatch(/kept/i)

    // No click: the browser's recogniser took over this same answer and ran it to its end, which
    // is the handover working. The participant was not asked to do anything.
    await waitFor(() => expect(completionPosted()).not.toBeNull(), { timeout: 15000 })
    const answers = (completionPosted()?.qa_pairs ?? []).map(p => p.answer).join(' ')
    // Kept, and continued.
    expect(answers).toContain('The first half of the answer')
    expect(answers).toContain('and the rest of the sentence.')
    // **Once.** `toContain` cannot tell one handover from two, and two is what a socket
    // failing the way the specification says it fails used to produce: `error` and `close`
    // both reached onDropped, each starting a recogniser of its own, both pushing into the
    // same answer. The participant's words appeared twice and one microphone was never
    // released. Counted rather than contained, so the assertion can see it.
    expect(answers.split('and the rest of the sentence.').length - 1).toBe(1)
    expect(answers.split('The first half of the answer').length - 1).toBe(1)
  }, 20000)

  it('does not claim a handover to a browser that cannot transcribe', async () => {
    // Firefox. The notice used to be set *before* `startWebSpeech` was called, and said "the
    // interview is carrying on using your browser to transcribe. Please continue." - to a
    // participant whose browser has no `SpeechRecognition` at all, who then kept talking into
    // nothing on the strength of that sentence. A claim about a handover is a claim about
    // something that has already happened.
    installStreaming()
    installSpeechRecognition(null)
    vi.stubGlobal('fetch', installFetch({
      token: 'jwt', listen_params: { model: 'nova-3', keyterm: OUR_KEYTERMS },
    }))

    await startInterview()
    const socket = await firstSocket()
    socket.say('The first half of the answer', true)
    socket.drop()

    const notice = await screen.findByTestId('recogniser-notice', undefined, { timeout: 10000 })
    expect(notice.textContent).not.toMatch(/carrying on using your browser/i)
    expect(notice.textContent).toMatch(/nothing you say from here is being recorded/i)
    // And the half that is still true is still said: what was heard is kept.
    expect(notice.textContent).toMatch(/already heard has been kept/i)
  }, 20000)

  it('tells the participant plainly when nothing in this browser can listen', async () => {
    // No Deepgram and no Web Speech. Before this task the interview carried on in silence,
    // recording nothing, and said so to nobody - the one outcome a participant cannot recover
    // from, because they find out after giving up an hour.
    installStreaming()
    installSpeechRecognition(null)
    vi.stubGlobal('fetch', installFetch('refused'))

    await startInterview()

    const notice = await screen.findByTestId('recogniser-notice', undefined, { timeout: 10000 })
    expect(notice.textContent).toMatch(/cannot transcribe speech/i)
    expect(notice.textContent).toMatch(/nothing you say is being recorded/i)
  }, 20000)

  // ── The fifth case: the fallback engine's own failures ─────────────────────
  //
  // Every one of these is a deployment with no DEEPGRAM_API_KEY - which is every deployment
  // before sp66 - so the browser's recogniser is not the fallback here, it is the whole of the
  // transcription. When it fails there is nothing to hand over to, and the participant kept
  // talking into a countdown while `onend` closed one empty answer after another.

  it('says so when the browser’s recogniser loses the transcription service', async () => {
    // Chrome's Web Speech streams audio to Google, so `network` is the routine failure and not
    // an exotic one: a connectivity blip on a deployment without Deepgram recorded all 59
    // answers empty and told the participant nothing.
    installStreaming()
    installSpeechRecognition('never heard', { failWith: 'network' })
    vi.stubGlobal('fetch', installFetch('refused', SCRIPT_TWO_QUESTIONS))

    await startInterview()

    const notice = await screen.findByTestId('recogniser-notice', undefined, { timeout: 10000 })
    expect(notice.textContent).toMatch(/stopped hearing you/i)
    // It must not claim a handover. There is no other engine - this *is* the other engine.
    expect(notice.textContent).not.toMatch(/carrying on using your browser/i)
  }, 20000)

  it('names the microphone when the browser’s recogniser cannot capture audio', async () => {
    // `audio-capture` is the device gone or taken by something else, which is a different
    // remedy from a transcription failure - so it must not be told in the same words.
    installStreaming()
    installSpeechRecognition('never heard', { failWith: 'audio-capture' })
    vi.stubGlobal('fetch', installFetch('refused', SCRIPT_TWO_QUESTIONS))

    await startInterview()

    const notice = await screen.findByTestId('recogniser-notice', undefined, { timeout: 10000 })
    expect(notice.textContent).toMatch(/microphone/i)
    expect(notice.textContent).not.toMatch(/stopped hearing you/i)
  }, 20000)

  it('leaves one recogniser on the microphone when the capture cannot be started', async () => {
    // The consequence of the route above, through the page that suffers it. The grant is good
    // and the socket opens; only the capture fails. The page then had two reasons to start a
    // browser recogniser - the null engine and the drop - and started one for each.
    //
    // Counted, because the transcript cannot tell one from two: both write into the same
    // answer, and the orphan is the one that outlives it, restarting itself through `onend`
    // and holding the microphone for the rest of the interview.
    installStreaming()
    vi.stubGlobal('AudioWorkletNode', class extends FakeAudioWorkletNode {
      connect(): void { throw new Error('this browser cannot connect this node') }
    })
    installSpeechRecognition('An answer the browser heard.')
    vi.stubGlobal('fetch', installFetch({
      token: 'jwt', listen_params: { model: 'nova-3', keyterm: OUR_KEYTERMS },
    }))

    await startInterview()
    await waitFor(() => expect(completionPosted()).not.toBeNull(), { timeout: 15000 })

    // **Two, and the two are nameable.** This script has one question, and the interview asks
    // for one section rating by voice at the end of it - one listen each, one recogniser each.
    // Three is the defect and nothing else: the third is the orphan, started by the drop the
    // capture failure used to report, which no `stop()` can reach and which restarts
    // itself through `onend` for the rest of the interview. Measured both ways - 2 with the
    // flag claimed in that `catch`, 3 without.
    expect(recognisersBuiltSoFar()).toBe(2)
  }, 20000)

  it('says nothing when the engine reports the stop the participant asked for', async () => {
    // The control, and the reason the fix reads the stop flag before setting it. An engine
    // interrupted by its own caller reports `aborted`, and a notice on every "Done speaking"
    // would put the amber box in front of every participant on every answer - which is the
    // failure mode of "fix C1 by reporting everything".
    //
    // **Asserted on the second question, not on the review screen.** The notice renders only
    // during the interview, so the first version of this read `queryByTestId` after the
    // interview had ended and answered null however the code behaved - it stayed green with
    // the guard deleted. The two-question script is what makes the absence an absence.
    installStreaming()
    installSpeechRecognition('An answer the browser heard.', { errorOnStop: 'aborted' })
    vi.stubGlobal('fetch', installFetch('refused', SCRIPT_TWO_QUESTIONS))

    await startInterview()
    await userEvent.click(await screen.findByRole('button', { name: /done speaking/i }))

    // Still interviewing: the second question is on screen, so the notice would be too.
    await screen.findByText(/who decides the order of works/i, undefined, { timeout: 10000 })
    expect(screen.queryByTestId('recogniser-notice')).toBeNull()
  }, 20000)
})

// ── The URL builder and the grant reader, driven directly ────────────────────

describe('the address the browser opens', () => {
  it('repeats an array parameter and joins nothing', () => {
    const url = deepgramListenUrl({
      token: 'jwt',
      listen_params: { model: 'nova-3', keyterm: ['A B', 'C'] },
    }, { sampleRate: 48000 })
    const params = new URL(url).searchParams
    expect(params.getAll('keyterm')).toEqual(['A B', 'C'])
    expect(params.get('model')).toBe('nova-3')
    expect(params.get('access_token')).toBe('jwt')
  })

  it('carries a parameter it has never heard of, so the server stays the only decider', () => {
    // `mip_opt_out` is the case this exists for - it opts the interview out of Deepgram's Model
    // Improvement Programme, whose default is opted *in*, and it is decided server-side beside
    // the model. The builder must forward it without knowing what it is: an allow-list here
    // would silently drop a privacy control while every server-side test stayed green, and the
    // failure would be invisible - a socket that opens, transcribes perfectly, and retains.
    // A fabricated name is asserted beside it so this cannot pass by `mip_opt_out` alone being
    // special-cased, which is the shape the real defect would take.
    const url = deepgramListenUrl({
      token: 'jwt',
      listen_params: { mip_opt_out: 'true', some_parameter_added_later: 'kept' },
    }, { sampleRate: 48000 })
    const params = new URL(url).searchParams
    expect(params.get('mip_opt_out')).toBe('true')
    expect(params.get('some_parameter_added_later')).toBe('kept')
  })

  it('encodes a term with a space or an ampersand rather than breaking the query', () => {
    const url = deepgramListenUrl({
      token: 'jwt', listen_params: { keyterm: ['Transmission & Distribution'] },
    }, { sampleRate: 48000 })
    expect(url).not.toContain('Transmission & Distribution')
    expect(new URL(url).searchParams.getAll('keyterm')).toEqual(['Transmission & Distribution'])
  })

  it('carries no keyterm key at all when the server sent none', () => {
    const url = deepgramListenUrl({ token: 'jwt', listen_params: { model: 'nova-3' } }, { sampleRate: 48000 })
    expect(url).not.toContain('keyterm')
  })
})

/** The grant the direct-socket tests open with. The vocabulary is asserted through the page. */
const GRANT_FOR_SOCKET = { token: 'jwt', listen_params: { model: 'nova-3' } }

/**
 * A built capture, which `openDeepgramSocket` now takes instead of a stream and a context.
 *
 * The two are separate calls so the page can report *which half* declined - a browser whose
 * audio engine will not run and a Deepgram socket that was refused send an operator to
 * completely different places. Tests of the capture half call `startPcmCapture` directly.
 */
/** The last binary frame the socket was given - the audio, as opposed to `CloseStream`. */
function socketTail(socket: FakeSocket): ArrayBuffer {
  const binary = socket.sent.filter(sent => typeof sent !== 'string')
  expect(binary.length).toBeGreaterThan(0)
  return binary[binary.length - 1] as ArrayBuffer
}

async function captureOn(context: FakeAudioContext = new FakeAudioContext()) {
  const capture = await startPcmCapture(fakeStream(), context as unknown as AudioContext)
  expect(capture).not.toBeNull()
  return capture!
}

describe('the socket, driven directly', () => {
  // The page's handover is not idempotent by nature - it starts a recogniser - so "a dropped
  // socket reports itself once" has to be a property of the socket adapter rather than a habit
  // of its caller. Asserted here, on its own, because the through-the-page test above can only
  // see the consequence and this can see the cause.
  const hooksSpy = () => {
    const dropped: string[] = []
    const closed: number[] = []
    return {
      dropped,
      closed,
      hooks: {
        onSpeechActivity: () => {},
        onFinal: () => {},
        onInterim: () => {},
        onClosed: () => closed.push(1),
        onDropped: (reason: 'microphone' | 'connection') => dropped.push(reason),
      },
    }
  }

  afterEach(() => { vi.stubGlobal('fetch', async () => new Response('{}', { status: 200 })) })

  it('reports a drop once, however many events the failure fires', async () => {
    // error-then-close is what the WebSocket specification requires of an abnormal closure, so
    // this is the ordinary case and not an edge one.
    installStreaming()
    const { dropped, hooks } = hooksSpy()
    const recogniser = await openDeepgramSocket(await captureOn(), GRANT_FOR_SOCKET, hooks)
    expect(recogniser).not.toBeNull()

    const socket = FakeSocket.opened[0]
    socket.onerror?.()
    socket.onclose?.()

    expect(dropped).toEqual(['connection'])
  })

  it('keeps the tail of an answer that arrives after the participant tapped Done', async () => {
    // The regression this guards against was a comment: `stop()` sent `CloseStream` and then
    // closed and resolved in the same tick, so a flushed `is_final` frame landed after the
    // answer had already been handed over. The browser's recogniser - the thing this replaced -
    // does keep that tail, because `recognition.stop()` delivers a pending `onresult` before
    // `onend`. Asserted as *ordering*, not as "the frame was received": the point is that it
    // arrives while the answer is still open.
    installStreaming()
    const { hooks } = hooksSpy()
    const heard: string[] = []
    const events: string[] = []
    const recogniser = await openDeepgramSocket(await captureOn(), GRANT_FOR_SOCKET, {
      ...hooks,
      onFinal: (t) => { heard.push(t); events.push('final') },
      onClosed: () => events.push('closed'),
    })

    const socket = FakeSocket.opened[0]
    // The words Deepgram has not finalised yet at the moment Done is tapped. They come back on
    // the flush, which is the whole of what `stop()` waits for.
    socket.tailOnClose = 'and the last four words.'
    recogniser?.stop()

    await waitFor(() => expect(events).toContain('closed'))
    // The socket was asked to flush rather than simply torn down.
    expect(socket.sent.some(s => String(s).includes('CloseStream'))).toBe(true)
    expect(heard).toEqual(['and the last four words.'])
    expect(events).toEqual(['final', 'closed'])
  })

  it('sends the capture’s last samples before asking Deepgram to close', async () => {
    // **The assertion the flush repair never had.** `stop()` waits for the worklet's
    // acknowledgement precisely so the samples it was still holding go out before `CloseStream`.
    // Nothing checked that they reached the wire at all, so sending `CloseStream` immediately
    // after asking for the flush - which is the defect the wait exists to repair - passed every
    // test in this file. Asserted as **order on the wire**.
    //
    // PCM makes this stronger than the `MediaRecorder` path it replaces: there the final
    // `dataavailable` and `onstop` were two independently queued tasks, and here the tail and
    // the acknowledgement travel the same `MessagePort`, which delivers in order.
    installStreaming()
    const { hooks } = hooksSpy()
    const closedAt: string[] = []
    const recogniser = await openDeepgramSocket(await captureOn(), GRANT_FOR_SOCKET, {
      ...hooks,
      onClosed: () => closedAt.push('closed'),
    })

    const socket = FakeSocket.opened[0]
    recogniser?.stop()
    await waitFor(() => expect(closedAt).toContain('closed'))

    const chunk = socket.sent.findIndex(s => typeof s !== 'string')
    const close = socket.sent.findIndex(s => typeof s === 'string' && s.includes('CloseStream'))
    expect(chunk).toBeGreaterThanOrEqual(0)
    expect(close).toBeGreaterThan(chunk)
  })

  it('does not send a chunk that arrives after the socket has gone', async () => {
    // The `readyState` guard on `ondataavailable`, which nothing drove. A real WebSocket
    // discards a `send` on a closed socket silently rather than throwing, so an unguarded send
    // fails in the quietest way there is - and the encoder delivering a chunk after the socket
    // has dropped is the ordinary shape of a drop, not a contrivance.
    installStreaming()
    const { hooks } = hooksSpy()
    await openDeepgramSocket(await captureOn(), GRANT_FOR_SOCKET, hooks)

    const socket = FakeSocket.opened[0]
    const node = FakeAudioWorkletNode.built[0]
    socket.drop()
    const before = socket.sent.length

    node.deliver()
    await new Promise(resolve => setTimeout(resolve, 5))

    expect(socket.sent).toHaveLength(before)
  })

  it('asks nothing of a socket that is no longer open, and ends the answer at once', async () => {
    // The `readyState` guard in `requestCloseStream`. A socket that has gone away silently -
    // `readyState` moved without `onclose` ever arriving - must not be sent a `CloseStream` and
    // then waited on: that is the participant held for the full flush deadline in front of a
    // dead socket, which is the one thing the deadline is a ceiling on rather than a cost.
    installStreaming()
    const { closed, hooks } = hooksSpy()
    const recogniser = await openDeepgramSocket(await captureOn(), GRANT_FOR_SOCKET, hooks)

    const socket = FakeSocket.opened[0]
    socket.readyState = FakeSocket.CLOSED

    recogniser?.stop()

    // Promptly - the default `waitFor` window is well inside FLUSH_TIMEOUT_MS, so a stop that
    // sat out the deadline fails here rather than passing slowly.
    await waitFor(() => expect(closed.length).toBe(1))
    expect(socket.sent.some(s => String(s).includes('CloseStream'))).toBe(false)
  })

  it('ends the answer anyway when the socket never answers the flush', async () => {
    // The other half, and the reason the flush is bounded: a socket that has gone away without
    // saying so must not hold a participant. The deadline is a ceiling, never a cost - the test
    // above is the ordinary path and completes in a tick.
    installStreaming()
    const { closed, hooks } = hooksSpy()
    const recogniser = await openDeepgramSocket(await captureOn(), GRANT_FOR_SOCKET, hooks)
    const socket = FakeSocket.opened[0]
    // A socket that accepts CloseStream and then says nothing at all.
    socket.send = (data: unknown) => { socket.sent.push(data) }

    recogniser?.stop()
    expect(closed).toEqual([])
    await waitFor(() => expect(closed.length).toBe(1), { timeout: FLUSH_TIMEOUT_MS + 1500 })
  }, 10000)

  it('reports no drop when the capture cannot be started, however the socket then closes', async () => {
    // The route the `dropped` flag did not cover. A capture that fails to start reaches a
    // `catch` that calls `settle(null)` **and** `socket.close()`, and that close arrives at a
    // socket which is open and not stopping - so it reported a drop, on a promise that had
    // already answered "fall back". The caller then started one recogniser for the null answer
    // and another for the drop: two on one microphone, the first orphaned beyond `stop()`.
    //
    // Asserted as the route rather than as the flag: the failure is driven through the graph
    // connection, and both halves of the contract are checked - no drop reported, and the
    // promise still answers null so the caller does fall back.
    installStreaming()
    class RefusesToConnect extends FakeAudioWorkletNode {
      connect(): void { throw new Error('this browser cannot connect this node') }
    }
    vi.stubGlobal('AudioWorkletNode', RefusesToConnect)
    const { dropped, hooks } = hooksSpy()

    const recogniser = await openDeepgramSocket(await captureOn(), GRANT_FOR_SOCKET, hooks)

    expect(recogniser).toBeNull()
    expect(dropped).toEqual([])
  })

  it('declines before opening a socket when the worklet module will not load', async () => {
    // **The `/dashboard` base trap, driven as behaviour.** `ui/public` and the built assets are
    // served under that base, so a bare `/pcm-worklet.js` 404s in the browser and `addModule`
    // rejects. The old container check ran inside `onopen` and had to close a socket it had just
    // been handed; the capture is now built first, so a browser that cannot capture reaches no
    // speech service at all - which is the property, and the reason it is asserted on
    // `FakeSocket.opened` rather than on the return value alone.
    installStreaming()
    FakeAudioContext.resolves = () => false

    const capture = await startPcmCapture(fakeStream(), fakeAudioContext())

    expect(capture).toBeNull()
    // Nothing was opened, because the page asks for the capture first and stops when it is
    // refused - so a browser that cannot capture reaches no speech service at all.
    expect(FakeSocket.opened).toEqual([])
  })

  it('declines rather than capturing into a context that will not run', async () => {
    // **The silent failure this whole path exists to remove.** A suspended or interrupted
    // context never calls `process()`, so no samples are posted, the socket stays open, and the
    // answer comes back empty with nothing raised anywhere. iOS suspends a context whenever the
    // participant switches tabs or lets the screen lock, and reports a fourth state,
    // `interrupted`, that never clears on its own - so the state is checked after the resume
    // rather than trusted to it.
    installStreaming()
    class WillNotResume extends FakeAudioContext {
      async resume() { /* answers, and stays exactly where it was */ }
    }
    const capture = await startPcmCapture(
      fakeStream(), new WillNotResume() as unknown as AudioContext,
    )

    expect(capture).toBeNull()
    expect(FakeSocket.opened).toEqual([])
  })

  it('resumes a suspended context rather than assuming it is running', async () => {
    // The control for the test above. Every context starts suspended, so a capture that never
    // resumed would refuse every interview rather than only the broken ones - and the two
    // mistakes are indistinguishable from the return value alone.
    installStreaming()
    const context = new FakeAudioContext()
    expect(context.state).toBe('suspended')

    const recogniser = await openDeepgramSocket(await captureOn(context), GRANT_FOR_SOCKET, hooksSpy().hooks,
    )

    expect(recogniser).not.toBeNull()
    expect(context.state).toBe('running')
  })

  it('puts a zero-gain node between the capture and the participant’s ears', async () => {
    // **Two properties in one graph, and the second is the one that is easy to get wrong while
    // fixing the first.** An `AudioWorkletNode` with an input and no path to `destination` may
    // never be scheduled at all, so the node must be connected onward - and connecting it
    // straight to `destination` puts the participant's own voice back in their ears a fraction
    // of a second late, which is the worst possible interview experience.
    installStreaming()
    const context = new FakeAudioContext()

    await openDeepgramSocket(await captureOn(context), GRANT_FOR_SOCKET, hooksSpy().hooks,
    )

    const node = FakeAudioWorkletNode.built[0]!
    const gain = context.gains[0]!
    // The graph pulls: source -> worklet -> gain -> destination.
    expect(context.sources[0]!.connectedTo).toEqual([node])
    expect(node.connectedTo).toEqual([gain])
    expect(gain.connectedTo).toEqual([context.destination])
    // And nothing is audible. The node never reaches `destination` directly...
    expect(node.connectedTo).not.toContain(context.destination)
    // ...and the one thing that does is silent.
    expect(gain.gain.value).toBe(0)
  })

  it('tells Deepgram the rate the context reports, not the rate that is usually right', async () => {
    // **Measured, never assumed.** 48000 is the common answer and 44100 is an ordinary one, so a
    // hardcoded rate is invisible until somebody runs the interview on a machine that disagrees
    // - and then the socket opens, the audio streams, Deepgram decodes it at the wrong speed and
    // the transcript comes back as gibberish, with nothing raised at either end. Driven at both
    // rates, because an assertion made only against the fake's default cannot tell a read from a
    // constant that happens to match it.
    for (const rate of [44100, 48000]) {
      installStreaming()
      FakeAudioContext.reportedSampleRate = rate
      const context = new FakeAudioContext()

      await openDeepgramSocket(await captureOn(context), GRANT_FOR_SOCKET, hooksSpy().hooks,
      )

      const params = paramsOf(FakeSocket.opened[0]!.url)
      expect(params.get('sample_rate')).toBe(String(rate))
      expect(params.get('sample_rate')).toBe(String(context.sampleRate))
    }
  })

  it('declares the encoding beside the rate, because the two are one fact', async () => {
    // Deepgram requires `sample_rate` whenever `encoding` is given, and `linear16` is documented
    // as signed 16-bit little-endian PCM - so these three describe the bytes on the wire and
    // must travel together. The server declares none of them, which
    // `tests/test_interview_keyterms.py` holds, so this is the only place they are set.
    installStreaming()
    await openDeepgramSocket(await captureOn(), GRANT_FOR_SOCKET, hooksSpy().hooks)

    const params = paramsOf(FakeSocket.opened[0]!.url)
    expect(params.get('encoding')).toBe('linear16')
    expect(params.get('channels')).toBe('1')
    expect(params.get('sample_rate')).toBe('44100')
    // The server's own parameters are untouched beside them.
    expect(params.get('model')).toBe('nova-3')
    expect(params.get('access_token')).toBe('jwt')
  })

  it('addresses the worklet module relative to this module, never as a bare path', async () => {
    // `ui/public` and the built assets are served under the `/dashboard` base, so a bare
    // `/pcm-worklet.js` 404s in the browser - a trap this repository has been caught by three
    // times, and one a stubbed `addModule` cannot see. What a test *can* hold is that the
    // address is resolved against this module rather than written as a path, which is the form
    // Vite rewrites. The built bundle was checked separately and addresses
    // `/dashboard/assets/pcm-worklet-<hash>.js`.
    installStreaming()
    const context = new FakeAudioContext()

    await openDeepgramSocket(await captureOn(context), GRANT_FOR_SOCKET, hooksSpy().hooks,
    )

    expect(context.modulesRequested).toHaveLength(1)
    const requested = context.modulesRequested[0]!
    expect(requested).toMatch(/\/pcm-worklet\.js$/)
    // A resolved absolute URL, which is what `new URL(..., import.meta.url)` produces. The bare
    // path is the defect, and it would satisfy the assertion above on its own.
    expect(requested.startsWith('/')).toBe(false)
    expect(() => new URL(requested)).not.toThrow()
  })

  it('converts the samples on the way to the wire, not only when the converter is called', async () => {
    // **The assertion that was missing, and the exact shape CLAUDE.md keeps recording.**
    // `PcmCapture.test.ts` drives `floatTo16BitPcm` thoroughly - and nothing asserted it was
    // *applied at the seam*. Deleting the call, so the worklet's raw Float32 buffer went
    // straight to `socket.send`, left the whole frontend suite green: the only test reading the
    // wire checked `typeof s !== 'string'`, which a Float32 buffer satisfies perfectly.
    //
    // Live, the socket then carries 32-bit float bytes under `encoding=linear16`. Deepgram reads
    // two float samples as one Int16 pair, decodes noise at double speed, and returns empty or
    // gibberish - no error at either end. That is the silent-failure class this branch exists to
    // remove, asserted one layer away from where it holds.
    //
    // Asserted on **bytes, not length**, and driven with a sample outside ±1.0, so one assertion
    // covers four mutations: no conversion at all (four bytes a frame, and 2.0 as float32 is
    // `00 00 00 40`); no clamp (2.0 wrapping rather than pinning); the wrong scale (`0x8000`
    // giving `00 80`); and the wrong byte order (`7f ff`).
    installStreaming()
    const { hooks } = hooksSpy()
    await openDeepgramSocket(await captureOn(), GRANT_FOR_SOCKET, hooks)
    const socket = FakeSocket.opened[0]!
    const node = FakeAudioWorkletNode.built[0]!

    node.deliver(4, 2)
    await waitFor(() => expect(socket.sent.length).toBe(1))

    const sent = socket.sent[0] as ArrayBuffer
    // Two bytes a frame, which four raw Float32 samples could never be.
    expect(sent.byteLength).toBe(4 * 2)
    // +2.0 clamped to +1.0, scaled by 0x7fff, little-endian: 32767 is `ff 7f`.
    expect([...new Uint8Array(sent)]).toEqual([0xff, 0x7f, 0xff, 0x7f, 0xff, 0x7f, 0xff, 0x7f])
  })

  it('sends the tail of an answer converted too, not only the batches before it', async () => {
    // The flush path posts through the same `onmessage`, but it is the one that runs after the
    // participant has tapped Done - so it is the batch a conversion applied in the wrong place
    // would most plausibly miss. The bound is asserted elsewhere; this is about the bytes.
    installStreaming()
    const { hooks } = hooksSpy()
    const closedAt: string[] = []
    const recogniser = await openDeepgramSocket(await captureOn(), GRANT_FOR_SOCKET, {
      ...hooks,
      onClosed: () => closedAt.push('closed'),
    })

    recogniser?.stop()
    await waitFor(() => expect(closedAt).toContain('closed'))

    const tail = socketTail(FakeSocket.opened[0]!)
    // `FakeWorkletPort.tailFrames` is 128, so 256 bytes converted and 512 raw.
    expect(tail.byteLength).toBe(128 * 2)
  })

  it('reports an interruption mid-answer rather than letting it end as silence', async () => {
    // **A new silent path, on exactly the population this branch exists to serve.** The context's
    // state is checked before each answer, which catches one that was already interrupted. iOS
    // interrupts one *mid-answer* too - an incoming call, the screen locking, the tab going to
    // the background - and then `process()` simply stops being called: no batches, no error, the
    // socket still open, and the three-second silence timer ends the answer. An empty answer,
    // nothing said to the participant, and the next answer resumes the context so it self-heals
    // and reads as somebody who did not speak.
    //
    // Before this branch an iPhone was refused outright and could never reach this path, so the
    // exposure is created by the change. Routed to the same drop the socket reports: handover on
    // a standard engagement, honest halt on one that requires Deepgram.
    installStreaming()
    const { dropped, hooks } = hooksSpy()
    const context = new FakeAudioContext()
    await openDeepgramSocket(await captureOn(context), GRANT_FOR_SOCKET, hooks)

    context.interrupt()

    expect(dropped).toEqual(['connection'])
  })

  it('says nothing when a context comes back to running on its own', async () => {
    // **The control, and the first version of it could not fail.** It asserted that no drop was
    // reported after an ordinary `openDeepgramSocket` - but the resume that takes a context to
    // `running` happens inside `startPcmCapture`, before the graph is connected, so the watch is
    // dormant and a mutation reporting *every* state change stayed green. Power-check found it.
    //
    // Driven properly: a transition to `running` while the capture is live, which is what iOS
    // does when it hands the audio engine back after a call ends. That must be silent, or the
    // amber notice lands on every participant who recovers - the failure mode of "report
    // everything", which this project already met once on the browser recogniser's `onerror`.
    installStreaming()
    const context = new FakeAudioContext()
    const { dropped, hooks } = hooksSpy()
    await openDeepgramSocket(await captureOn(context), GRANT_FOR_SOCKET, hooks)
    await waitFor(() => expect(FakeAudioWorkletNode.built[0]!.connectedTo).not.toEqual([]))

    context.interrupt('running')

    expect(dropped).toEqual([])
  })

  it('stops watching the context once the answer has ended', async () => {
    // **Asserted as the detachment rather than as a silence, and deliberately.** A state change
    // arriving after the answer is additionally absorbed by the `stopping` guard on the handler,
    // so a test that only checked "no drop was reported" passes whether or not the watch was
    // ever taken down - which is what the first version of this did, and a mutation leaving the
    // handler attached stayed green.
    //
    // What the clearing buys is that one context serves the whole interview: the watch belongs
    // to the capture that installed it, and a handler outliving its capture is a closure over a
    // graph that no longer exists.
    installStreaming()
    const context = new FakeAudioContext()
    const { dropped, closed, hooks } = hooksSpy()
    const recogniser = await openDeepgramSocket(await captureOn(context), GRANT_FOR_SOCKET, hooks)
    expect(context.onstatechange).not.toBeNull()

    recogniser?.stop()
    await waitFor(() => expect(closed.length).toBe(1))

    expect(context.onstatechange).toBeNull()
    context.interrupt()
    expect(dropped).toEqual([])
  })

  it('fetches the worklet module once for a context, however many answers it serves', async () => {
    // `startPcmCapture` runs per answer, so a forty-question interview asked for the module forty
    // times. The browser's module map makes the repeats cheap - but that is a claim about the
    // browser, and this removes the question rather than resting on it.
    installStreaming()
    const context = new FakeAudioContext()

    await captureOn(context)
    await captureOn(context)
    await captureOn(context)

    expect(context.modulesRequested).toHaveLength(1)
  })

  it('asks again next answer when the module could not be fetched', async () => {
    // A rejection is not cached. A transient failure to fetch the worklet should cost one answer,
    // not condemn the rest of the interview to the browser's recogniser - which is what a stored
    // rejected promise would do, invisibly, because every later answer would reuse it.
    installStreaming()
    const context = new FakeAudioContext()
    FakeAudioContext.resolves = () => false

    expect(await startPcmCapture(fakeStream(), context as unknown as AudioContext)).toBeNull()

    FakeAudioContext.resolves = () => true
    expect(await startPcmCapture(fakeStream(), context as unknown as AudioContext)).not.toBeNull()
    expect(context.modulesRequested).toHaveLength(2)
  })

  it('mixes a stereo microphone down rather than discarding half of it', async () => {
    // `channelCount: 1` is ignored under the default `channelCountMode` of `max`: the node takes
    // whatever the source hands it, the processor reads channel 0, and the right channel is
    // **discarded** rather than mixed. On a device that puts most of the signal in one channel
    // that is a capture which is quiet or nearly silent - and `channels=1` on the URL would be a
    // promise to Deepgram that nothing kept.
    installStreaming()
    await captureOn()

    const options = FakeAudioWorkletNode.built[0]!.options as {
      channelCount?: number; channelCountMode?: string; channelInterpretation?: string
    }
    expect(options.channelCount).toBe(1)
    expect(options.channelCountMode).toBe('explicit')
    expect(options.channelInterpretation).toBe('speakers')
  })

  it('takes the graph down when the answer ends', async () => {
    // **One context serves the whole interview, so nothing else ever will.** A graph left
    // connected goes on running `process()` and posting batches into a socket that has closed,
    // for every remaining question - forty answers being forty live captures on one microphone.
    // The `MediaRecorder` path had no equivalent: a recorder that was stopped was finished with.
    installStreaming()
    const { closed, hooks } = hooksSpy()
    const context = new FakeAudioContext()
    const recogniser = await openDeepgramSocket(await captureOn(context), GRANT_FOR_SOCKET, hooks,
    )

    const node = FakeAudioWorkletNode.built[0]!
    expect(node.connectedTo).not.toEqual([])

    recogniser?.stop()
    await waitFor(() => expect(closed.length).toBe(1))

    expect(node.connectedTo).toEqual([])
    expect(context.sources[0]!.connectedTo).toEqual([])
    // And nothing is still listening on the port, so a late batch reaches no closure at all.
    expect(node.port.onmessage).toBeNull()
  })

  it('takes the graph down when it declines rather than handing one back', async () => {
    // The refusal routes - the handshake deadline, an error or a close before open, and a
    // capture that will not start - answer `null`, so no `Recogniser` reaches the caller and
    // `stop()` is never called. If the graph were only torn down there, every declined socket
    // would leave one connected, and the page falls straight on to the browser's recogniser -
    // two things on one microphone, which is the defect this file already counts recognisers for.
    //
    // Driven through the capture-start route, which is the one reachable without sitting out a
    // six-second handshake deadline; the teardown itself is the single `settle(null)` line that
    // serves all four.
    installStreaming()
    vi.stubGlobal('AudioWorkletNode', class extends FakeAudioWorkletNode {
      // Connects to the source and then refuses the onward leg, so the graph is half-built when
      // the failure lands - which is what makes the assertion below about the clean-up rather
      // than about nothing ever having been connected.
      connect(target: unknown): void {
        if (target instanceof FakeAudioWorkletNode) return
        throw new Error('this browser cannot connect this node')
      }
    })
    const context = new FakeAudioContext()

    const recogniser = await openDeepgramSocket(await captureOn(context), GRANT_FOR_SOCKET, hooksSpy().hooks,
    )

    expect(recogniser).toBeNull()
    const node = FakeAudioWorkletNode.built[0]!
    expect(context.sources[0]!.connectedTo).toEqual([])
    expect(node.port.onmessage).toBeNull()
  })

  it('reports no drop at all when the caller stopped it', async () => {
    // The control: a `close` following our own `stop()` is the socket doing as it was told, and
    // reporting that as a failure would put the amber notice in front of every participant on
    // every answer.
    installStreaming()
    const { dropped, closed, hooks } = hooksSpy()
    const recogniser = await openDeepgramSocket(await captureOn(), GRANT_FOR_SOCKET, hooks)

    recogniser?.stop()
    FakeSocket.opened[0].onclose?.()

    await waitFor(() => expect(closed.length).toBe(1))
    expect(dropped).toEqual([])
  })
})

describe('reading the grant', () => {
  // A benign stub rather than `vi.unstubAllGlobals()`, for the reason given above: an interview
  // started by an earlier test in this file may still be speaking.
  afterEach(() => { vi.stubGlobal('fetch', async () => new Response('{}', { status: 200 })) })

  it('answers null for every way a deployment can be without Deepgram', async () => {
    // All of them mean the same thing to the caller, and each fails somewhere different.
    vi.stubGlobal('fetch', async () => new Response('{"detail":"no key"}', { status: 503 }))
    expect(await fetchDeepgramGrant('/api', 'tok')).toBeNull()

    vi.stubGlobal('fetch', async () => new Response('{"keyterms":[]}', { status: 200 }))
    expect(await fetchDeepgramGrant('/api', 'tok')).toBeNull()

    vi.stubGlobal('fetch', async () => new Response('not json', { status: 200 }))
    expect(await fetchDeepgramGrant('/api', 'tok')).toBeNull()

    vi.stubGlobal('fetch', async () => { throw new Error('offline') })
    expect(await fetchDeepgramGrant('/api', 'tok')).toBeNull()
  })

  it('reads a real answer, so the nulls above are about the failures rather than the reader', async () => {
    vi.stubGlobal('fetch', async () => new Response(
      JSON.stringify({ token: 'jwt', listen_params: { keyterm: ['Iberdrola'] } }),
      { status: 200 },
    ))
    const grant = await fetchDeepgramGrant('/api', 'tok')
    expect(grant?.token).toBe('jwt')
    expect(grant?.listen_params.keyterm).toEqual(['Iberdrola'])
  })
})
