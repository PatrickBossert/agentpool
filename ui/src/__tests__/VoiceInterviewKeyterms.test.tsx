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

import { FLUSH_TIMEOUT_MS, deepgramListenUrl, fetchDeepgramGrant, openDeepgramSocket } from '../api/deepgram'
import {
  FakeRecorder,
  FakeSocket,
  SCRIPT_TWO_QUESTIONS,
  completionPosted,
  firstSocket,
  forgetCompletion,
  installAudioAndMic,
  installFetch,
  installSpeechRecognition,
  installStreaming,
  recognisersBuiltSoFar,
  startInterview,
} from './support/voiceInterviewFakes'

// The vocabulary the *server* answered with. Nothing in the component may name any of these -
// that is what makes the assertions about a project's own words rather than about a constant.
const OUR_KEYTERMS = ['Renewals CapEx Allocation', 'Iberdrola', 'SP Energy Networks']

function paramsOf(url: string) {
  return new URL(url).searchParams
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
    // WebSocket and MediaRecorder stubs left standing here reach nothing else.
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

    await waitFor(() => expect(completionPosted()).not.toBeNull(), { timeout: 15000 })
    const answers = (completionPosted()?.qa_pairs ?? []).map(p => p.answer).join(' ')
    expect(answers).toContain('Iberdrola sets the reporting calendar.')
    expect(answers).not.toContain('the browser recogniser')
  }, 20000)

  // ── Step 5: a project with nothing still connects ──────────────────────────

  it('connects with no keyterms at all when the project has none', async () => {
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
  })

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

    await waitFor(() => expect(completionPosted()).not.toBeNull(), { timeout: 15000 })
    expect(FakeSocket.opened).toEqual([])
    const answers = (completionPosted()?.qa_pairs ?? []).map(p => p.answer).join(' ')
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

  it('leaves one recogniser on the microphone when the recorder cannot be built', async () => {
    // The consequence of the route above, through the page that suffers it. The grant is good
    // and the socket opens; only the recorder fails. The page then had two reasons to start a
    // browser recogniser - the null engine and the drop - and started one for each.
    //
    // Counted, because the transcript cannot tell one from two: both write into the same
    // answer, and the orphan is the one that outlives it, restarting itself through `onend`
    // and holding the microphone for the rest of the interview.
    installStreaming()
    vi.stubGlobal('MediaRecorder', class {
      static isTypeSupported = () => true
      constructor() { throw new Error('this browser cannot record from this stream') }
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
    // constructor failure used to report, which no `stop()` can reach and which restarts
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
    })
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
    })
    const params = new URL(url).searchParams
    expect(params.get('mip_opt_out')).toBe('true')
    expect(params.get('some_parameter_added_later')).toBe('kept')
  })

  it('encodes a term with a space or an ampersand rather than breaking the query', () => {
    const url = deepgramListenUrl({
      token: 'jwt', listen_params: { keyterm: ['Transmission & Distribution'] },
    })
    expect(url).not.toContain('Transmission & Distribution')
    expect(new URL(url).searchParams.getAll('keyterm')).toEqual(['Transmission & Distribution'])
  })

  it('carries no keyterm key at all when the server sent none', () => {
    const url = deepgramListenUrl({ token: 'jwt', listen_params: { model: 'nova-3' } })
    expect(url).not.toContain('keyterm')
  })
})

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
    const stream = { getTracks: () => [] } as unknown as MediaStream
    const recogniser = await openDeepgramSocket(stream, 'wss://example.test/listen', hooks)
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
    const stream = { getTracks: () => [] } as unknown as MediaStream
    const recogniser = await openDeepgramSocket(stream, 'wss://example.test/listen', {
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

  it('sends the recorder’s last chunk before asking Deepgram to close', async () => {
    // **The assertion the flush repair never had.** `stop()` waits for `onstop` precisely so the
    // final `dataavailable` - which a real MediaRecorder queues as a task - goes out before
    // `CloseStream`. Nothing checked that the chunk reached the wire at all, so sending
    // `CloseStream` immediately after `recorder.stop()`, which is the defect the wait exists to
    // repair, passed every test in this file. Asserted as **order on the wire**.
    installStreaming()
    const { hooks } = hooksSpy()
    const closedAt: string[] = []
    const stream = { getTracks: () => [] } as unknown as MediaStream
    const recogniser = await openDeepgramSocket(stream, 'wss://example.test/listen', {
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
    const stream = { getTracks: () => [] } as unknown as MediaStream
    await openDeepgramSocket(stream, 'wss://example.test/listen', hooks)

    const socket = FakeSocket.opened[0]
    const recorder = FakeRecorder.built[0]
    socket.drop()
    const before = socket.sent.length

    recorder.deliver()

    expect(socket.sent).toHaveLength(before)
  })

  it('asks nothing of a socket that is no longer open, and ends the answer at once', async () => {
    // The `readyState` guard in `requestCloseStream`. A socket that has gone away silently -
    // `readyState` moved without `onclose` ever arriving - must not be sent a `CloseStream` and
    // then waited on: that is the participant held for the full flush deadline in front of a
    // dead socket, which is the one thing the deadline is a ceiling on rather than a cost.
    installStreaming()
    const { closed, hooks } = hooksSpy()
    const stream = { getTracks: () => [] } as unknown as MediaStream
    const recogniser = await openDeepgramSocket(stream, 'wss://example.test/listen', hooks)

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
    const stream = { getTracks: () => [] } as unknown as MediaStream
    const recogniser = await openDeepgramSocket(stream, 'wss://example.test/listen', hooks)
    const socket = FakeSocket.opened[0]
    // A socket that accepts CloseStream and then says nothing at all.
    socket.send = (data: unknown) => { socket.sent.push(data) }

    recogniser?.stop()
    expect(closed).toEqual([])
    await waitFor(() => expect(closed.length).toBe(1), { timeout: FLUSH_TIMEOUT_MS + 1500 })
  }, 10000)

  it('reports no drop when the recorder cannot be built, however the socket then closes', async () => {
    // The route the `dropped` flag did not cover. `new MediaRecorder(...)` throwing reaches a
    // `catch` that calls `settle(null)` **and** `socket.close()`, and that close arrives at a
    // socket which is open and not stopping - so it reported a drop, on a promise that had
    // already answered "fall back". The caller then started one recogniser for the null answer
    // and another for the drop: two on one microphone, the first orphaned beyond `stop()`.
    //
    // Asserted as the route rather than as the flag: the failure is driven through the
    // constructor, and both halves of the contract are checked - no drop reported, and the
    // promise still answers null so the caller does fall back.
    installStreaming()
    vi.stubGlobal('MediaRecorder', class {
      static isTypeSupported = () => true
      constructor() { throw new Error('this browser cannot record from this stream') }
    })
    const { dropped, hooks } = hooksSpy()
    const stream = { getTracks: () => [] } as unknown as MediaStream

    const recogniser = await openDeepgramSocket(stream, 'wss://example.test/listen', hooks)

    expect(recogniser).toBeNull()
    expect(dropped).toEqual([])
  })

  it('declines the socket when the browser records none of the containers it is configured for', async () => {
    // Safari, including on iOS: it records MP4/AAC and answers false to webm/opus, webm and
    // ogg/opus alike. `.find()` answering `undefined` was treated identically to "this browser
    // will not say", so the recorder was built with Safari's own container and streamed to a
    // socket configured for webm/opus. If Deepgram answers that with no transcripts rather than
    // closing, nothing fires `onDropped` and the participant gets a countdown and an empty
    // answer - on the device a participant is most likely to be holding.
    installStreaming()
    const built: unknown[] = []
    vi.stubGlobal('MediaRecorder', class {
      static isTypeSupported = () => false
      constructor(...args: unknown[]) { built.push(args) }
      start() {}
      stop() {}
    })
    const { dropped, hooks } = hooksSpy()
    const stream = { getTracks: () => [] } as unknown as MediaStream

    const recogniser = await openDeepgramSocket(stream, 'wss://example.test/listen', hooks)

    expect(recogniser).toBeNull()
    // Declined before anything was recorded, not after.
    expect(built).toEqual([])
    // And silently: this is the "socket will not open" case, which falls back without a notice.
    expect(dropped).toEqual([])
  })

  it('still records when the browser will not say what it supports', async () => {
    // The control, and the reason the answer has three values rather than two. A browser with no
    // `isTypeSupported` at all has refused nothing - declining there would take Deepgram away
    // from every browser that simply does not implement the probe.
    installStreaming()
    const built: unknown[] = []
    class NoProbe {
      ondataavailable: ((e: { data: { size: number } }) => void) | null = null
      onstop: (() => void) | null = null
      constructor(...args: unknown[]) { built.push(args) }
      start() {}
      stop() {}
    }
    vi.stubGlobal('MediaRecorder', NoProbe)
    const { dropped, hooks } = hooksSpy()
    const stream = { getTracks: () => [] } as unknown as MediaStream

    const recogniser = await openDeepgramSocket(stream, 'wss://example.test/listen', hooks)

    expect(recogniser).not.toBeNull()
    expect(built).toHaveLength(1)
    // Built with the browser's own default - no mimeType argument to impose one.
    expect(built[0]).toHaveLength(1)
    expect(dropped).toEqual([])
  })

  it('reports no drop at all when the caller stopped it', async () => {
    // The control: a `close` following our own `stop()` is the socket doing as it was told, and
    // reporting that as a failure would put the amber notice in front of every participant on
    // every answer.
    installStreaming()
    const { dropped, closed, hooks } = hooksSpy()
    const stream = { getTracks: () => [] } as unknown as MediaStream
    const recogniser = await openDeepgramSocket(stream, 'wss://example.test/listen', hooks)

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
