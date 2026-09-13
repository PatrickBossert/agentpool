// ui/src/__tests__/VoiceInterviewKeyterms.test.tsx
//
// What the interview portal actually sends to Deepgram.
//
// Asserted on the **socket**, never on the helper. `GET /api/interviews/{token}/deepgram-token`
// had existed since SP10f and nothing in `ui/src` had ever called it - a perfect helper with no
// caller is precisely how this path came to exist, so a test that drove `deepgramListenUrl` and
// stopped there would reproduce the defect it is meant to close. Every assertion below reads the
// URL handed to `new WebSocket` by a rendered, running interview.
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import VoiceInterview from '../pages/VoiceInterview'
import { FLUSH_TIMEOUT_MS, deepgramListenUrl, fetchDeepgramGrant, openDeepgramSocket } from '../api/deepgram'

const SCRIPT = {
  script_id: 'SC-014',
  node_label: 'Connections Delivery',
  level: 'L2',
  research_brief: '',
  study_objectives: [],
  welcome_message: 'Welcome.',
  sections: [
    {
      section_id: 'S1',
      title: 'Operations',
      questions: [
        {
          id: 'q1',
          text: 'What slows connections down?',
          follow_up_count: 0,
          probing_instructions: '',
          follow_up_branches: [],
          evasion_signals: [],
        },
      ],
    },
  ],
  closing_message: 'Thank you.',
}

/**
 * A script with a second question, so an assertion can be made **while the interview is still
 * running**.
 *
 * The recogniser notice is rendered only in the interviewing phase. On the one-question script
 * above, an answer ends the interview, so `queryByTestId('recogniser-notice')` answers null
 * from the review screen whether or not a notice was ever set - which is a control that cannot
 * fail. Found by mutation: deleting the requested-stop guard left the one-question version
 * green. The second question keeps the phase open across the assertion.
 */
const SCRIPT_TWO_QUESTIONS = {
  script_id: 'SC-014',
  node_label: 'Connections Delivery',
  level: 'L2',
  research_brief: '',
  study_objectives: [],
  welcome_message: 'Welcome.',
  sections: [
    {
      section_id: 'S1',
      title: 'Operations',
      questions: [
        {
          id: 'q1',
          text: 'What slows connections down?',
          follow_up_count: 0,
          probing_instructions: '',
          follow_up_branches: [],
          evasion_signals: [],
        },
        {
          id: 'q2',
          text: 'And who decides the order of works?',
          follow_up_count: 0,
          probing_instructions: '',
          follow_up_branches: [],
          evasion_signals: [],
        },
      ],
    },
  ],
  closing_message: 'Thank you.',
}

const STAMP = { elevenlabs_voice_id: 'V', language: 'en', country_code: 'GB', model_id: 'm' }

// The vocabulary the *server* answered with. Nothing in the component may name any of these -
// that is what makes the assertions about a project's own words rather than about a constant.
const OUR_KEYTERMS = ['Renewals CapEx Allocation', 'Iberdrola', 'SP Energy Networks']

// ── Fakes ────────────────────────────────────────────────────────────────────

class FakeSocket {
  static opened: FakeSocket[] = []
  static OPEN = 1
  static CLOSED = 3
  readyState = 0
  sent: unknown[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  closed = false

  constructor(public url: string) {
    FakeSocket.opened.push(this)
    setTimeout(() => {
      this.readyState = FakeSocket.OPEN
      this.onopen?.()
    }, 0)
  }

  /** What Deepgram still has to say when it is asked to close. Set by a test before stopping. */
  tailOnClose: string | null = null

  /**
   * Deepgram answers `CloseStream` by flushing whatever transcript it has left **and then**
   * closing, in that order - which is the entire reason `stop()` waits rather than closing the
   * socket itself. The fake has to do both halves, in that order, or it cannot tell a
   * flush-aware `stop()` from the one it replaced.
   *
   * It also has to do the closing half at all: without it every "Done" in these tests would sit
   * out the full flush deadline, and the deadline would become the only path the suite ever
   * exercised - the one case that is *not* the ordinary one.
   */
  send(data: unknown) {
    this.sent.push(data)
    if (typeof data === 'string' && data.includes('CloseStream')) {
      setTimeout(() => {
        if (this.tailOnClose) this.say(this.tailOnClose, true)
        this.readyState = FakeSocket.CLOSED
        this.onclose?.()
      }, 0)
    }
  }

  /** A real socket fires `close` when it is closed. */
  close() {
    if (this.closed) return
    this.readyState = FakeSocket.CLOSED
    this.closed = true
    this.onclose?.()
  }

  /** A Deepgram transcript frame, as it arrives on the wire. */
  say(transcript: string, isFinal = true) {
    this.onmessage?.({
      data: JSON.stringify({ channel: { alternatives: [{ transcript }] }, is_final: isFinal }),
    })
  }

  /**
   * The socket going away underneath a participant who is still talking.
   *
   * **`error` then `close`, which is what the WebSocket specification requires** of an abnormal
   * post-open failure - and therefore what the real case looks like every time. The first
   * version of this fake fired `close` alone, so it exercised the one shape this code path does
   * not actually meet, and it could not see the handover running twice.
   */
  drop() {
    this.readyState = FakeSocket.CLOSED
    this.onerror?.()
    this.onclose?.()
  }
}

class FakeRecorder {
  static isTypeSupported = () => true
  ondataavailable: ((e: { data: { size: number } }) => void) | null = null
  onstop: (() => void) | null = null
  constructor(public stream: unknown, public options?: unknown) {}
  start() { /* the socket assertions do not need audio bytes to flow */ }
  /**
   * A real MediaRecorder hands over its final chunk and *then* fires `onstop`, which is the
   * signal `stop()` waits on before asking Deepgram to close. A fake that never fired it left
   * the flush deadline as the only way an answer could ever end.
   */
  stop() {
    this.ondataavailable?.({ data: { size: 4 } })
    setTimeout(() => this.onstop?.(), 0)
  }
}

function installStreaming() {
  FakeSocket.opened = []
  vi.stubGlobal('WebSocket', FakeSocket)
  vi.stubGlobal('MediaRecorder', FakeRecorder)
}

/**
 * The browser's own recogniser - the fallback, and what every interview used before this.
 *
 * **The fake has to be able to fail.** Until sp66's final review it only ever fired `no-speech`
 * after a successful result, so `network`, `audio-capture` and `aborted` had never executed -
 * and `network` is Chrome's *routine* failure, because Web Speech streams the audio to Google.
 * Every one of them recorded an empty answer and said nothing to the participant.
 *
 * `failWith` raises an error instead of hearing anything; `errorOnStop` raises one when the
 * engine is asked to stop, which is the control - `no-speech` and a stop we asked for must stay
 * silent, or the amber notice lands in front of every participant on every answer. A fake that
 * can only produce one of the two cannot tell the fix from a blanket notice.
 */
/**
 * How many browser recognisers this interview has built.
 *
 * One microphone, so more than one per answer is the defect the socket adapter's `dropped`
 * flag exists to prevent - and a second one is invisible to any assertion about transcripts,
 * because both write into the same answer and the orphan is beyond the reach of `stop()`.
 * Counted rather than inferred, for the same reason the handover test counts occurrences.
 */
let recognisersBuilt = 0

function installSpeechRecognition(
  transcript: string | null,
  options: { failWith?: string; errorOnStop?: string } = {},
) {
  recognisersBuilt = 0
  if (transcript === null) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (window as any).SpeechRecognition
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (window as any).webkitSpeechRecognition
    return
  }
  const { failWith, errorOnStop } = options
  class FakeRecognition {
    continuous = false
    interimResults = false
    lang = ''
    constructor() { recognisersBuilt += 1 }
    onresult: ((e: unknown) => void) | null = null
    onend: (() => void) | null = null
    onerror: ((e: { error: string }) => void) | null = null
    start() {
      setTimeout(() => {
        if (failWith) {
          // Nothing heard at all, which is what these failures look like: the engine reports
          // and stops, and the answer it closes is empty.
          this.onerror?.({ error: failWith })
          this.onend?.()
          return
        }
        this.onresult?.({
          resultIndex: 0,
          results: [Object.assign([{ transcript }], { isFinal: true })],
        })
        if (errorOnStop) return // stays listening, so a test can drive "Done speaking"
        this.onerror?.({ error: 'no-speech' })
        this.onend?.()
      }, 0)
    }
    stop() {
      if (errorOnStop) this.onerror?.({ error: errorOnStop })
      this.onend?.()
    }
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).SpeechRecognition = FakeRecognition
}

let completedBody: { qa_pairs?: { answer: string }[] } | null = null

function installFetch(grant: unknown | 'refused', script: unknown = SCRIPT) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/interviews/tok')) {
      return new Response(
        JSON.stringify({ session: { id: 1, session_token: 'tok', node_label: 'x', voice_config: STAMP }, script }),
        { status: 200 },
      )
    }
    if (url.endsWith('/deepgram-token')) {
      if (grant === 'refused') return new Response('{"detail":"no key"}', { status: 503 })
      return new Response(JSON.stringify(grant), { status: 200 })
    }
    if (url.endsWith('/speak')) return new Response(new Blob([new Uint8Array([1])]), { status: 200 })
    if (url.endsWith('/complete')) {
      completedBody = JSON.parse(String(init?.body))
      return new Response('{}', { status: 200 })
    }
    return new Response('{}', { status: 200 })
  })
}

function installAudioAndMic() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).Audio = class {
    onended: (() => void) | null = null
    onerror: (() => void) | null = null
    play() { setTimeout(() => this.onended?.(), 0); return Promise.resolve() }
  }
  URL.createObjectURL = vi.fn(() => 'blob:fake')
  URL.revokeObjectURL = vi.fn()
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      enumerateDevices: async () => [{ kind: 'audioinput', deviceId: 'mic-1', label: 'Built-in Microphone' }],
      getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }),
    },
  })
}

async function startInterview() {
  render(
    <MemoryRouter initialEntries={['/interview/tok']}>
      <Routes>
        <Route path="/interview/:sessionToken" element={<VoiceInterview />} />
      </Routes>
    </MemoryRouter>,
  )
  await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))
}

/** The first socket a running interview opened, once it is open. */
async function firstSocket(): Promise<FakeSocket> {
  await waitFor(() => expect(FakeSocket.opened.length).toBeGreaterThan(0), { timeout: 5000 })
  const socket = FakeSocket.opened[0]
  await waitFor(() => expect(socket.readyState).toBe(FakeSocket.OPEN))
  return socket
}

function paramsOf(url: string) {
  return new URL(url).searchParams
}

describe('the recogniser is told the project’s own words', () => {
  beforeEach(() => {
    completedBody = null
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

    await waitFor(() => expect(completedBody).not.toBeNull(), { timeout: 15000 })
    const answers = (completedBody?.qa_pairs ?? []).map(p => p.answer).join(' ')
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

    await waitFor(() => expect(completedBody).not.toBeNull(), { timeout: 15000 })
    expect(FakeSocket.opened).toEqual([])
    const answers = (completedBody?.qa_pairs ?? []).map(p => p.answer).join(' ')
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
    await waitFor(() => expect(completedBody).not.toBeNull(), { timeout: 15000 })
    const answers = (completedBody?.qa_pairs ?? []).map(p => p.answer).join(' ')
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
    await waitFor(() => expect(completedBody).not.toBeNull(), { timeout: 15000 })

    // **Two, and the two are nameable.** This script has one question, and the interview asks
    // for one section rating by voice at the end of it - one listen each, one recogniser each.
    // Three is the defect and nothing else: the third is the orphan, started by the drop the
    // constructor failure used to report, which no `stop()` can reach and which restarts
    // itself through `onend` for the rest of the interview. Measured both ways - 2 with the
    // flag claimed in that `catch`, 3 without.
    expect(recognisersBuilt).toBe(2)
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
