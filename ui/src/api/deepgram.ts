// ui/src/api/deepgram.ts
//
// The participant's speech, streamed to Deepgram with the project's own vocabulary attached.
//
// This half of the path was built in SP10f and then left: `GET /api/interviews/{token}
// /deepgram-token` has existed since, and until now nothing in `ui/src` had ever called it - the
// recogniser in front of every participant was the browser's `webkitSpeechRecognition`, which
// has never heard of the client, its programmes, or its value chain. Client names came back as
// ordinary English words that sound like them.
//
// **Nothing here decides how Deepgram is configured.** The model, the language and the boost
// parameter arrive from the server in `listen_params`, because Nova-3 takes `keyterm` and
// Nova-2 takes `keywords` and that pairing is one fact - restating it in TypeScript would be a
// second declaration free to fall behind the first. What crosses is data: parameter names and
// values. This file knows only how to encode a query string and how to hold a socket open.

export const DEEPGRAM_LISTEN_URL = 'wss://api.deepgram.com/v1/listen'

/** What the token door answers: a short-lived grant, and the words to listen for. */
export interface DeepgramGrant {
  token: string
  keyterms: string[]
  listen_params: Record<string, string | string[]>
}

export interface RecogniserHooks {
  /** Anything at all was heard - resets the silence countdown. */
  onSpeechActivity: () => void
  /** A finished phrase, to be kept. */
  onFinal: (text: string) => void
  /** Words in progress, for the live caption only. */
  onInterim: (text: string) => void
  /** The recogniser has stopped for good and the answer is complete. */
  onClosed: () => void
  /** The recogniser failed. The answer so far is kept; the participant is told. */
  onDropped: (reason: 'microphone' | 'connection') => void
}

/** Anything that can be listening, from the page's point of view. */
export interface Recogniser {
  stop: () => void
}

/**
 * The address the browser opens, credential included.
 *
 * The grant is a JWT, and a JWT goes in `access_token` on the URL. The documented
 * `Sec-WebSocket-Protocol: token, <value>` form is for an API **key**; Deepgram answers 401 to a
 * JWT offered that way, because a JWT is a `Bearer` credential and a browser cannot set an
 * `Authorization` header on a handshake. Putting the key itself in the URL would be the
 * alternative and is exactly what the token door exists to avoid: this credential lives for
 * thirty seconds and grants transcription alone.
 *
 * An array value is repeated rather than joined - `keyterm=A&keyterm=B` - which is how Deepgram
 * spells a repeated parameter.
 */
export function deepgramListenUrl(grant: DeepgramGrant, base: string = DEEPGRAM_LISTEN_URL): string {
  const url = new URL(base)
  for (const [name, value] of Object.entries(grant.listen_params ?? {})) {
    if (Array.isArray(value)) {
      for (const one of value) url.searchParams.append(name, one)
    } else {
      url.searchParams.set(name, String(value))
    }
  }
  url.searchParams.set('access_token', grant.token)
  return url.toString()
}

/**
 * Ask the server for a grant and this project's vocabulary.
 *
 * Answers `null` for every reason a deployment might not have Deepgram - no key configured (the
 * door answers 503), an unreachable server, a malformed body - because all of them mean the same
 * thing to the caller: use the other recogniser. A grant with no token is `null` too; a socket
 * opened with `access_token=undefined` fails at Deepgram rather than here, which is a worse place
 * to find out.
 */
export async function fetchDeepgramGrant(
  base: string,
  sessionToken: string,
): Promise<DeepgramGrant | null> {
  try {
    const res = await fetch(`${base}/interviews/${sessionToken}/deepgram-token`)
    if (!res.ok) return null
    const data = await res.json()
    if (!data || typeof data.token !== 'string' || !data.token) return null
    return {
      token: data.token,
      keyterms: Array.isArray(data.keyterms) ? data.keyterms : [],
      listen_params: data.listen_params && typeof data.listen_params === 'object' ? data.listen_params : {},
    }
  } catch {
    return null
  }
}

/** Whether this browser could stream to Deepgram at all, asked before anything is fetched. */
export function browserCanStream(): boolean {
  return typeof WebSocket !== 'undefined' && typeof MediaRecorder !== 'undefined'
}

function recorderMimeType(): string | undefined {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus']
  const supported = (MediaRecorder as unknown as { isTypeSupported?: (t: string) => boolean }).isTypeSupported
  if (typeof supported !== 'function') return undefined
  return candidates.find(type => supported.call(MediaRecorder, type))
}

/** How often a chunk of audio is handed to the socket. Small enough to feel live. */
const CHUNK_MS = 250
/** A handshake that has not completed by now is one the participant is waiting on. */
const OPEN_TIMEOUT_MS = 6000

/**
 * Open the socket, start recording, and translate Deepgram's frames into the page's hooks.
 *
 * Answers `null` rather than throwing when the socket does not open in time or closes during the
 * handshake, because the caller's response to every one of those is the same: fall back. Once the
 * socket *is* open, a later failure is a different matter - the participant is mid-answer by
 * then - and that goes to `onDropped`, which keeps what was heard and says so.
 */
export function openDeepgramSocket(
  stream: MediaStream,
  url: string,
  hooks: RecogniserHooks,
): Promise<Recogniser | null> {
  return new Promise((resolve) => {
    let settled = false
    let opened = false
    let stopping = false
    let recorder: MediaRecorder | null = null
    let socket: WebSocket

    try {
      socket = new WebSocket(url)
    } catch {
      resolve(null)
      return
    }

    const timer = setTimeout(() => {
      if (opened) return
      settle(null)
      try { socket.close() } catch { /* already gone */ }
    }, OPEN_TIMEOUT_MS)

    function settle(value: Recogniser | null) {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve(value)
    }

    function stop() {
      if (stopping) return
      stopping = true
      try { recorder?.stop() } catch { /* already stopped */ }
      try {
        // Deepgram flushes and closes cleanly on this, so the last words of an answer are not
        // lost to a socket torn down mid-phrase.
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'CloseStream' }))
      } catch { /* the close below covers it */ }
      try { socket.close() } catch { /* already gone */ }
      hooks.onClosed()
    }

    socket.onopen = () => {
      opened = true
      try {
        const mimeType = recorderMimeType()
        recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
        recorder.ondataavailable = (event: BlobEvent) => {
          if (!event.data || event.data.size === 0) return
          if (socket.readyState !== WebSocket.OPEN) return
          socket.send(event.data)
        }
        recorder.start(CHUNK_MS)
      } catch {
        settle(null)
        try { socket.close() } catch { /* already gone */ }
        return
      }
      settle({ stop })
    }

    socket.onmessage = (event: MessageEvent) => {
      let frame: { channel?: { alternatives?: { transcript?: string }[] }; is_final?: boolean }
      try {
        frame = JSON.parse(String(event.data))
      } catch {
        return
      }
      const transcript = frame.channel?.alternatives?.[0]?.transcript ?? ''
      if (!transcript) return
      hooks.onSpeechActivity()
      if (frame.is_final) hooks.onFinal(transcript)
      else hooks.onInterim(transcript)
    }

    socket.onerror = () => {
      if (!opened) {
        settle(null)
        return
      }
      if (!stopping) hooks.onDropped('connection')
    }

    socket.onclose = () => {
      if (!opened) {
        settle(null)
        return
      }
      if (!stopping) hooks.onDropped('connection')
    }
  })
}
