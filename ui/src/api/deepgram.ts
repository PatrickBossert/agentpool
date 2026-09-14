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

/**
 * What the token door answers: a short-lived grant, and the parameters to open the socket with.
 *
 * The vocabulary arrives **inside** `listen_params`, under whichever parameter name the server's
 * chosen model takes, and not as a list of its own beside it. A second copy would be payload
 * nothing reads and a second place an auditor has to check to see what leaves the deployment.
 */
export interface DeepgramGrant {
  token: string
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

/**
 * The container to record in - and `null` when the browser has been asked and said no to all of
 * them.
 *
 * **Three answers, not two.** `undefined` is "this browser will not say", which is a reason to
 * try its default and see; `null` is "this browser has said it records none of these", which is
 * a reason not to try at all. Collapsing them - which is what `.find()` returning `undefined`
 * did - builds the recorder with whatever container the browser prefers and streams it to a
 * socket configured for webm/opus.
 *
 * **Safari, including on iOS, records MP4/AAC and answers false to all three**, which is the
 * device a participant is most likely to be holding. If Deepgram answers that stream with no
 * transcripts rather than closing the socket, nothing fires `onDropped` and the participant
 * gets a countdown and an empty answer - the silent failure this branch exists to remove.
 * Declining here costs Safari nothing: it has `webkitSpeechRecognition`, so the fallback works.
 */
function recorderMimeType(): string | null | undefined {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus']
  const supported = (MediaRecorder as unknown as { isTypeSupported?: (t: string) => boolean }).isTypeSupported
  if (typeof supported !== 'function') return undefined
  return candidates.find(type => supported.call(MediaRecorder, type)) ?? null
}

/**
 * Why this browser cannot stream to Deepgram, asked before an interview begins - or `null` when
 * it can.
 *
 * **The second half of the probe, and the half that has nothing to do with Deepgram.** On an
 * engagement that forbids the browser's own recogniser there is no fallback, so "this browser
 * records only MP4/AAC" and "Deepgram refused our key" have the same consequence and must both
 * be found at device setup rather than at the participant's first question.
 *
 * It answers the same three-way question `recorderMimeType` does and collapses it to the two
 * that matter here: a browser that *will not say* what it supports has refused nothing, so it is
 * allowed to try - declining there would take Deepgram away from every browser with no
 * `isTypeSupported`, which is the control `openDeepgramSocket` already keeps.
 *
 * The strings are the closed vocabulary `POST /{token}/speech-failure` accepts. They are reasons,
 * not sentences: that door is unauthenticated and its output reaches an administrator's alert, so
 * the wording is composed on the server.
 */
export function browserStreamingObstacle(): 'no_streaming_support' | 'unsupported_container' | null {
  if (!browserCanStream()) return 'no_streaming_support'
  return recorderMimeType() === null ? 'unsupported_container' : null
}

/** How often a chunk of audio is handed to the socket. Small enough to feel live. */
const CHUNK_MS = 250
/** A handshake that has not completed by now is one the participant is waiting on. */
const OPEN_TIMEOUT_MS = 6000
/**
 * How long the answer waits for Deepgram's last words after `CloseStream`.
 *
 * A ceiling rather than a cost. Deepgram answers `CloseStream` with whatever it has left and
 * then closes, so the ordinary wait is one round trip; this only runs out when the socket has
 * gone away without saying so, and a participant must never be held on a dead one.
 */
export const FLUSH_TIMEOUT_MS = 1500

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
    let closeRequested = false
    let finished = false
    // **A drop is reported at most once.** The WebSocket specification fires `error` and then
    // `close` for an abnormal post-open failure, so the two handlers below are two views of one
    // event - and the caller's response to a drop is to start a recogniser, which is not a thing
    // to do twice. Doing it twice put two browser recognisers on one microphone, both writing
    // into the same answer, with the first orphaned beyond the reach of `stop()` and restarting
    // itself for the rest of the interview.
    //
    // The flag is here rather than in the page deliberately. "error then close" is knowledge
    // about WebSockets, and this file is the only one that has to hold it; and `onDropped` is a
    // hook both engines share, so making it at-most-once **once** is what lets every caller -
    // including `startWebSpeech`'s - treat it as an event rather than a level.
    let dropped = false
    let recorder: MediaRecorder | null = null
    let flushTimer: ReturnType<typeof setTimeout> | null = null
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

    /**
     * End the answer, after giving Deepgram a bounded chance to send its last words.
     *
     * Three steps, and the order of all three is load-bearing. This used to be one step - stop
     * the recorder, send `CloseStream`, close the socket, resolve - with a comment claiming the
     * flush kept the tail of an answer. It did not: `close()` is immediate and `onClosed()`
     * resolved the answer synchronously, so any flushed `is_final` frame arrived after the
     * `resolve` and was pushed into an array nobody read. The recorder's last chunk of audio was
     * never sent at all, because `dataavailable` after `stop()` is asynchronous and the socket
     * had already gone.
     *
     * That was a **regression against the recogniser this replaced**: `recognition.stop()`
     * delivers a pending `onresult` before `onend`, so the browser's engine keeps the tail. It
     * cost a participant the end of any sentence they were still speaking when they tapped
     * "Done" or "Finish my last answer", which is exactly the moment somebody is mid-thought.
     *
     *   1. the deadline, first, so nothing below can hold a participant on a dead socket;
     *   2. `recorder.stop()`, and `CloseStream` only once its final `dataavailable` has been
     *      sent - sending it earlier discards the very audio this exists to keep;
     *   3. the socket stays open until Deepgram closes it, or the deadline passes.
     */
    function stop() {
      if (stopping) return
      stopping = true
      flushTimer = setTimeout(finishStop, FLUSH_TIMEOUT_MS)
      if (!recorder) {
        requestCloseStream()
        return
      }
      // `onstop` fires after the recorder has handed over its final chunk.
      recorder.onstop = () => requestCloseStream()
      try {
        recorder.stop()
      } catch {
        requestCloseStream()
      }
    }

    function requestCloseStream() {
      if (closeRequested) return
      closeRequested = true
      try {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'CloseStream' }))
          // And now wait. Deepgram answers with whatever transcript it has left and then closes,
          // which reaches `onclose` below.
          return
        }
      } catch { /* nothing to flush into - end it */ }
      finishStop()
    }

    function finishStop() {
      if (finished) return
      finished = true
      if (flushTimer) { clearTimeout(flushTimer); flushTimer = null }
      try { socket.close() } catch { /* already gone */ }
      hooks.onClosed()
    }

    function reportDropped() {
      if (dropped) return
      dropped = true
      hooks.onDropped('connection')
    }

    socket.onopen = () => {
      opened = true
      const mimeType = recorderMimeType()
      if (mimeType === null) {
        // Asked, and told no to every container this socket is configured for. Fall back rather
        // than stream something Deepgram was not asked to decode - see `recorderMimeType`. The
        // `dropped` claim is the same one the constructor failure makes below, for the same
        // reason: this closure is ours, and the caller has already been told to fall back.
        dropped = true
        settle(null)
        try { socket.close() } catch { /* already gone */ }
        return
      }
      try {
        recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
        recorder.ondataavailable = (event: BlobEvent) => {
          if (!event.data || event.data.size === 0) return
          if (socket.readyState !== WebSocket.OPEN) return
          socket.send(event.data)
        }
        recorder.start(CHUNK_MS)
      } catch {
        // **The route the flag above did not cover.** This `catch` answers the promise with
        // `null` - "fall back" - and then closes the socket, and that close arrives at a socket
        // which is open and not stopping, so `onclose` below called `reportDropped()`. The
        // caller then had two reasons to start a browser recogniser, the null answer and the
        // drop, and started one for each: two on one microphone, the first orphaned beyond the
        // reach of `stop()` and restarting itself for the rest of the interview. That is
        // verbatim the defect `dropped` was added to prevent, reached by a different door.
        //
        // Claiming the drop here rather than suppressing it at `onclose` is deliberate: this is
        // the only place that knows the closure was ours, and a test on `onclose` for "was the
        // recorder built?" would be the same knowledge written where it cannot be checked.
        dropped = true
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
      // Mid-flush, an error means there is nothing left to wait for: end the answer now rather
      // than sitting out the deadline in front of somebody who has already tapped Done.
      if (stopping) finishStop()
      else reportDropped()
    }

    socket.onclose = () => {
      if (!opened) {
        settle(null)
        return
      }
      if (stopping) finishStop()
      else reportDropped()
    }
  })
}
