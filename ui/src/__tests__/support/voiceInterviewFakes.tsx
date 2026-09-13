// ui/src/__tests__/support/voiceInterviewFakes.tsx
//
// The fakes a rendered interview needs: a Deepgram socket, a MediaRecorder, the browser's own
// recogniser, the interview API, and the audio and microphone the page reaches for.
//
// **Shared rather than copied, because a fake is a claim about an external system.** Two copies
// of "how a WebSocket fails" or "when a MediaRecorder hands over its last chunk" are two
// declarations free to drift, and the whole of sp66's final review turned on fakes that were
// more forgiving than the real thing. One copy, so a correction reaches every test at once.
//
// Not collected by vitest: the include pattern is `**/*.{test,spec}.*`, and this is neither.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, vi } from 'vitest'

import VoiceInterview from '../../pages/VoiceInterview'

/** A script with as many questions as a test needs, in one section. */
export function scriptWithQuestions(...texts: string[]) {
  return {
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
        questions: texts.map((text, i) => ({
          id: `q${i + 1}`,
          text,
          follow_up_count: 0,
          probing_instructions: '',
          follow_up_branches: [],
          evasion_signals: [],
        })),
      },
    ],
    closing_message: 'Thank you.',
  }
}

export const SCRIPT = scriptWithQuestions('What slows connections down?')

/**
 * A script with a second question, so an assertion can be made **while the interview is still
 * running**.
 *
 * The recogniser notice is rendered only in the interviewing phase. On the one-question script,
 * an answer ends the interview, so `queryByTestId('recogniser-notice')` answers null from the
 * review screen whether or not a notice was ever set - which is a control that cannot fail.
 * Found by mutation: deleting the requested-stop guard left the one-question version green. The
 * second question keeps the phase open across the assertion.
 */
export const SCRIPT_TWO_QUESTIONS = scriptWithQuestions(
  'What slows connections down?',
  'And who decides the order of works?',
)

export const SCRIPT_THREE_QUESTIONS = scriptWithQuestions(
  'What slows connections down?',
  'And who decides the order of works?',
  'And what would you change first?',
)

export const STAMP = { elevenlabs_voice_id: 'V', language: 'en', country_code: 'GB', model_id: 'm' }

// ── Fakes ────────────────────────────────────────────────────────────────────

export class FakeSocket {
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

export class FakeRecorder {
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

export function installStreaming() {
  FakeSocket.opened = []
  vi.stubGlobal('WebSocket', FakeSocket)
  vi.stubGlobal('MediaRecorder', FakeRecorder)
}

/**
 * How many browser recognisers this interview has built.
 *
 * One microphone, so more than one per answer is the defect the socket adapter's `dropped`
 * flag exists to prevent - and a second one is invisible to any assertion about transcripts,
 * because both write into the same answer and the orphan is beyond the reach of `stop()`.
 * Counted rather than inferred, for the same reason the handover test counts occurrences.
 */
let recognisersBuilt = 0
export function recognisersBuiltSoFar(): number {
  return recognisersBuilt
}

/**
 * The browser's own recogniser - the fallback, and what every interview used before sp66.
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
export function installSpeechRecognition(
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
export function completionPosted() {
  return completedBody
}
export function forgetCompletion() {
  completedBody = null
}

export function installFetch(grant: unknown | 'refused', script: unknown = SCRIPT) {
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

export function installAudioAndMic() {
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

export async function startInterview() {
  render(
    <MemoryRouter initialEntries={['/interview/tok']}>
      <Routes>
        <Route path="/interview/:sessionToken" element={<VoiceInterview />} />
      </Routes>
    </MemoryRouter>,
  )
  await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))
}

/**
 * The nth socket a running interview opened, once it is open.
 *
 * **Counting sockets is only sound in a test file whose earlier tests have all finished.**
 * `cleanup()` unmounts the page and cannot stop the interview - it is an async loop over
 * closures - so a previous test's interview goes on listening, opens sockets of its own, and
 * fetches its grants from whatever `fetch` stub is installed *now*. Neither the index nor the
 * grant can tell those apart from this test's. It is not theoretical: "one drop latches
 * Deepgram off for the rest of the interview" survived mutation in a shared file because a
 * stray socket satisfied the assertion, and failed immediately when run alone. Anything that
 * counts sockets across questions belongs in a file of its own.
 */
export async function socketAt(index: number): Promise<FakeSocket> {
  await waitFor(() => expect(FakeSocket.opened.length).toBeGreaterThan(index), { timeout: 10000 })
  const socket = FakeSocket.opened[index]
  await waitFor(() => expect(socket.readyState).toBe(FakeSocket.OPEN))
  return socket
}

/** The first socket a running interview opened, once it is open. */
export function firstSocket(): Promise<FakeSocket> {
  return socketAt(0)
}
