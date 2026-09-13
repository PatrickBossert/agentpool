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
import { deepgramListenUrl, fetchDeepgramGrant } from '../api/deepgram'

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

  send(data: unknown) { this.sent.push(data) }
  close() { this.readyState = FakeSocket.CLOSED; this.closed = true }

  /** A Deepgram transcript frame, as it arrives on the wire. */
  say(transcript: string, isFinal = true) {
    this.onmessage?.({
      data: JSON.stringify({ channel: { alternatives: [{ transcript }] }, is_final: isFinal }),
    })
  }

  /** The socket going away underneath a participant who is still talking. */
  drop() { this.readyState = FakeSocket.CLOSED; this.onclose?.() }
}

class FakeRecorder {
  static isTypeSupported = () => true
  ondataavailable: ((e: { data: { size: number } }) => void) | null = null
  constructor(public stream: unknown, public options?: unknown) {}
  start() { /* the socket assertions do not need audio bytes to flow */ }
  stop() { /* nothing to flush */ }
}

function installStreaming() {
  FakeSocket.opened = []
  vi.stubGlobal('WebSocket', FakeSocket)
  vi.stubGlobal('MediaRecorder', FakeRecorder)
}

/** The browser's own recogniser - the fallback, and what every interview used before this. */
function installSpeechRecognition(transcript: string | null) {
  if (transcript === null) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (window as any).SpeechRecognition
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (window as any).webkitSpeechRecognition
    return
  }
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

let completedBody: { qa_pairs?: { answer: string }[] } | null = null

function installFetch(grant: unknown | 'refused') {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/interviews/tok')) {
      return new Response(
        JSON.stringify({ session: { id: 1, session_token: 'tok', node_label: 'x', voice_config: STAMP }, script: SCRIPT }),
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
      keyterms: OUR_KEYTERMS,
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
      token: 'jwt', keyterms: theirs,
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
      token: 'jwt', keyterms: OUR_KEYTERMS,
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
      token: 'jwt', keyterms: [],
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
    installStreaming()
    installSpeechRecognition('An answer the browser heard.')
    vi.stubGlobal('fetch', installFetch('refused'))

    await startInterview()

    await waitFor(() => expect(completedBody).not.toBeNull(), { timeout: 15000 })
    expect(FakeSocket.opened).toEqual([])
    const answers = (completedBody?.qa_pairs ?? []).map(p => p.answer).join(' ')
    expect(answers).toContain('An answer the browser heard.')
    expect(screen.queryByTestId('recogniser-notice')).toBeNull()
  }, 20000)

  it('hands a dropped connection to the browser mid-answer, and says so', async () => {
    // The case that reaches a real person: a participant talking into a socket that has gone.
    // Both halves are required - what was already said is kept and they are told plainly - and
    // neither is enough on its own.
    installStreaming()
    installSpeechRecognition('and the rest of the sentence.')
    vi.stubGlobal('fetch', installFetch({
      token: 'jwt', keyterms: OUR_KEYTERMS, listen_params: { model: 'nova-3', keyterm: OUR_KEYTERMS },
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
})

// ── The URL builder and the grant reader, driven directly ────────────────────

describe('the address the browser opens', () => {
  it('repeats an array parameter and joins nothing', () => {
    const url = deepgramListenUrl({
      token: 'jwt',
      keyterms: [],
      listen_params: { model: 'nova-3', keyterm: ['A B', 'C'] },
    })
    const params = new URL(url).searchParams
    expect(params.getAll('keyterm')).toEqual(['A B', 'C'])
    expect(params.get('model')).toBe('nova-3')
    expect(params.get('access_token')).toBe('jwt')
  })

  it('encodes a term with a space or an ampersand rather than breaking the query', () => {
    const url = deepgramListenUrl({
      token: 'jwt', keyterms: [], listen_params: { keyterm: ['Transmission & Distribution'] },
    })
    expect(url).not.toContain('Transmission & Distribution')
    expect(new URL(url).searchParams.getAll('keyterm')).toEqual(['Transmission & Distribution'])
  })

  it('carries no keyterm key at all when the server sent none', () => {
    const url = deepgramListenUrl({ token: 'jwt', keyterms: [], listen_params: { model: 'nova-3' } })
    expect(url).not.toContain('keyterm')
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
      JSON.stringify({ token: 'jwt', keyterms: ['Iberdrola'], listen_params: { keyterm: ['Iberdrola'] } }),
      { status: 200 },
    ))
    const grant = await fetchDeepgramGrant('/api', 'tok')
    expect(grant?.token).toBe('jwt')
    expect(grant?.listen_params.keyterm).toEqual(['Iberdrola'])
  })
})
