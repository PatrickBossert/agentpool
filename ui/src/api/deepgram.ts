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
//
// **The one exception, and it is an exception for a stated reason.** `encoding` and `sample_rate`
// are decided here, because the server cannot observe an `AudioContext`'s sample rate and they
// are a pairing in exactly the way `model` and `keyterm` are: an encoding declared apart from the
// rate that goes with it is the same defect one axis over. So both are set in one place, from the
// live context, and `deepgram_listen_params` declares neither -
// `tests/test_interview_keyterms.py` asserts the server's silence so the pair cannot be split
// later by somebody adding "just the encoding" to the server's dict.
import { PCM_BATCH_FRAMES, PCM_CHANNELS, PCM_ENCODING, floatTo16BitPcm } from './pcm'

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
 *
 * **`sampleRate` is required and is measured, never assumed.** It is 48000 on most machines and
 * 44100 on plenty of real ones, and the browser is the only end that can see which - so it is
 * read off the live `AudioContext` and passed in here rather than defaulted. A wrong rate does
 * not error: Deepgram's documentation requires `sample_rate` whenever `encoding` is given, so
 * omitting it is refused, but a rate that is merely *wrong* opens the socket, streams the audio,
 * decodes it at the wrong speed and returns a transcript that is gibberish or empty, with
 * nothing raised at either end. Taking it as a required argument is what stops a caller
 * defaulting it to the common case.
 */
export function deepgramListenUrl(
  grant: DeepgramGrant,
  audio: { sampleRate: number },
  base: string = DEEPGRAM_LISTEN_URL,
): string {
  const url = new URL(base)
  for (const [name, value] of Object.entries(grant.listen_params ?? {})) {
    if (Array.isArray(value)) {
      for (const one of value) url.searchParams.append(name, one)
    } else {
      url.searchParams.set(name, String(value))
    }
  }
  // The browser's half of the configuration - see the note at the head of this file for why
  // these two are not the server's, and why they must not be separated from one another.
  url.searchParams.set('encoding', PCM_ENCODING)
  url.searchParams.set('sample_rate', String(audio.sampleRate))
  url.searchParams.set('channels', String(PCM_CHANNELS))
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

type AudioContextConstructor = new (options?: AudioContextOptions) => AudioContext

/** `AudioContext`, or Safari's old prefixed spelling, or `null` on a browser with neither. */
function audioContextConstructor(): AudioContextConstructor | null {
  const scope = globalThis as unknown as {
    AudioContext?: AudioContextConstructor
    webkitAudioContext?: AudioContextConstructor
  }
  return scope.AudioContext ?? scope.webkitAudioContext ?? null
}

/**
 * Why this browser cannot stream to Deepgram, asked before an interview begins - or `null` when
 * it can.
 *
 * **The second half of the probe, and the half that has nothing to do with Deepgram.** On an
 * engagement that forbids the browser's own recogniser there is no fallback, so "this browser
 * cannot capture audio for us" and "Deepgram refused our key" have the same consequence and must
 * both be found at device setup rather than at the participant's first question.
 *
 * **What it asks changed in sp67, and the shape did not.** It used to ask whether the browser
 * could produce one of three containers, because `MediaRecorder` negotiates a container and
 * Safari negotiates MP4/AAC - which meant an engagement requiring Deepgram could not be
 * interviewed on an iPhone or iPad. Raw PCM has no container, so the question is now whether the
 * browser has `AudioWorklet` at all. **Safari has had it since 14.1 on macOS and iOS 14.5**
 * (April 2021), so this arm no longer refuses any current device; what it still catches is a
 * genuinely old browser, where the honest answer is the same as it ever was.
 *
 * The strings are the closed vocabulary `POST /{token}/speech-failure` accepts. They are reasons,
 * not sentences: that door is unauthenticated and its output reaches an administrator's alert, so
 * the wording is composed on the server.
 */
export function browserStreamingObstacle(): 'no_streaming_support' | 'no_audio_worklet' | null {
  // No socket, or no Web Audio whatsoever - there is nothing to build a capture out of.
  if (typeof WebSocket === 'undefined' || audioContextConstructor() === null) {
    return 'no_streaming_support'
  }
  // Web Audio, but from before worklets. The graph can exist and nothing can read samples off it.
  return typeof AudioWorkletNode === 'undefined' ? 'no_audio_worklet' : null
}

/**
 * Whether this browser could stream to Deepgram at all, asked before anything is fetched.
 *
 * **Derived rather than declared.** It was a second list of the same capabilities, which is a
 * second declaration free to drift from the probe's - and drifting means the probe passing a
 * browser this refuses, or the reverse, with the participant on the far end of either.
 */
export function browserCanStream(): boolean {
  return browserStreamingObstacle() === null
}

/**
 * Where the worklet processor is served from.
 *
 * **`new URL(..., import.meta.url)` and never a bare path.** `ui/public` and the built assets are
 * served under the `/dashboard` base, so `'/pcm-worklet.js'` 404s in the browser - a trap this
 * repository records catching three separate pieces of work. This form is the one Vite rewrites:
 * the built bundle addresses `/dashboard/assets/pcm-worklet-<hash>.js`, verified against a real
 * `vite build` rather than against a test, because a test that stubs `addModule` cannot see a
 * 404.
 */
export const PCM_WORKLET_URL = new URL('./pcm-worklet.js', import.meta.url).href

/**
 * The capture graph, in the same shape `MediaRecorder` had - so that the flush machinery below
 * is the same machinery, with the tail arriving by a different route.
 *
 * `onbatch` is `ondataavailable`; `onflushed` is `onstop`; `flush()` is `stop()`. The one that
 * has no counterpart is `onerror`, and it is new because it has to be: a `MediaRecorder` that
 * dies fires an event, and a worklet processor that throws simply stops being called, which is
 * a participant talking into a graph that is no longer listening.
 */
export interface PcmCapture {
  /** The live context's rate, read rather than assumed. Goes on the URL as `sample_rate`. */
  readonly sampleRate: number
  /** A batch of audio, already the bytes the socket should carry. */
  onbatch: ((bytes: ArrayBuffer) => void) | null
  /** The worklet has handed over its last samples. Sent after the final `onbatch`. */
  onflushed: (() => void) | null
  /**
   * The capture has failed and no more audio is coming.
   *
   * Two things reach it: a processor that threw, and **a context that stopped running while the
   * participant was still speaking** - see the `statechange` watch in `startPcmCapture`.
   */
  onerror: (() => void) | null
  /** Connect the graph and begin. Separate from construction so nothing is captured early. */
  start: () => void
  /** Ask the worklet for whatever it still holds. `onflushed` follows it. */
  flush: () => void
  /** Tear the graph down. Does not close the context, which outlives one answer. */
  close: () => void
}

/**
 * Bring a context to `running`, which on iOS is not a formality.
 *
 * Safari suspends an `AudioContext` when the participant switches tabs, takes a call or lets the
 * screen lock, and reports a **fourth** state, `interrupted`, beside `suspended` and `closed`. It
 * does not come back on its own. So this asks whether the context is *running* rather than which
 * of the three ways it is not - a check written against `suspended` alone would walk straight
 * past an interrupted one, which is the state a participant who answered a phone call is in.
 *
 * **A suspended context is the silent failure this whole path exists to remove**: `process()` is
 * never called, no samples are posted, the socket stays open, and the answer comes back empty
 * with nothing raised anywhere. So the state is checked *after* the resume rather than trusted,
 * and a context that will not run refuses the capture - which reaches the participant as a
 * handover on a standard engagement and as a clean refusal on one that requires Deepgram, both
 * of which are better than silence.
 */
async function wakeAudioContext(context: AudioContext): Promise<boolean> {
  if (context.state === 'running') return true
  try {
    await context.resume()
  } catch {
    return false
  }
  // Re-read rather than assume: `resume()` resolving is not the same claim as the context
  // running, and the narrowing above is about the state before it was called.
  return (context.state as AudioContextState) === 'running'
}

/**
 * A context for the whole interview - or `null` when this browser has no Web Audio.
 *
 * One per interview rather than one per answer, held by the page beside the microphone stream
 * and for the same reasons it holds that: `addModule` is fetched once instead of per question,
 * and on iOS a context created inside the answer loop is created outside any user gesture, where
 * it starts suspended. Chrome caps a page at six concurrent contexts, which is a second reason
 * not to open one per answer and rely on `close()` keeping up.
 */
export function createAudioContext(): AudioContext | null {
  const Ctor = audioContextConstructor()
  if (!Ctor) return null
  try {
    // No `sampleRate` option, deliberately. Asking for a rate Deepgram likes would be the
    // browser resampling for us where it can and throwing where it cannot - Safari has
    // historically done the latter - when the alternative is simply telling Deepgram the rate we
    // have. Measure, do not negotiate.
    return new Ctor()
  } catch {
    return null
  }
}

/**
 * Build the capture graph on an existing context. `null` for every reason it cannot be built.
 *
 * **The graph must pull, or `process()` is never called.** An `AudioWorkletNode` with an input
 * and no path to `destination` may simply never be scheduled, so the node is connected onward -
 * through a gain node whose gain is **zero**. Connecting it straight to `destination` would put
 * the participant's own voice in their ears a fraction of a second late, which is the worst
 * possible interview experience and a mistake that is very easy to make while proving the graph
 * runs at all. The processor writes nothing to its outputs, so the zero gain is the second of
 * two reasons nothing is heard rather than the only one.
 */
/**
 * The `addModule` call for each context, so one interview fetches the processor once.
 *
 * `startPcmCapture` runs per answer, so a forty-question interview asked for the module forty
 * times. The browser's module map makes the repeats cheap, but "cheap" is a claim about the
 * browser and this removes the question rather than resting on it. A **rejection is not cached** -
 * it is deleted on the way out, so a transient failure to fetch the worklet costs one answer
 * rather than the rest of the interview.
 */
const _moduleLoads = new WeakMap<AudioContext, Promise<void>>()

function loadWorkletModule(context: AudioContext, moduleUrl: string): Promise<void> {
  const started = _moduleLoads.get(context)
  if (started) return started
  const loading = context.audioWorklet.addModule(moduleUrl).catch((err: unknown) => {
    _moduleLoads.delete(context)
    throw err
  })
  _moduleLoads.set(context, loading)
  return loading
}

export async function startPcmCapture(
  stream: MediaStream,
  context: AudioContext,
  moduleUrl: string = PCM_WORKLET_URL,
): Promise<PcmCapture | null> {
  if (typeof AudioWorkletNode === 'undefined') return null
  if (!(await wakeAudioContext(context))) return null
  try {
    await loadWorkletModule(context, moduleUrl)
    const node = new AudioWorkletNode(context, 'pcm-capture', {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      channelCount: PCM_CHANNELS,
      // **`explicit`, because `channelCount` alone does not downmix.** Under the default `max`
      // the count is ignored and a stereo microphone hands the processor two channels, of which
      // it reads the first - so the right channel is *discarded* rather than mixed, and half a
      // stereo capture is quieter and can be almost silent on a device that puts most of the
      // signal in one channel. `explicit` with `speakers` makes the node mix down to the one
      // channel `channels=1` promises Deepgram.
      channelCountMode: 'explicit',
      channelInterpretation: 'speakers',
      // Declared once in `pcm.ts` and passed in, so the processor holds no number of its own.
      processorOptions: { batchFrames: PCM_BATCH_FRAMES },
    })
    const source = context.createMediaStreamSource(stream)
    const silence = context.createGain()
    silence.gain.value = 0
    // Whether the graph is connected and samples are expected. The `statechange` watch below
    // reads it, so an interruption before `start()` or after `close()` reports nothing.
    let capturing = false

    const capture: PcmCapture = {
      get sampleRate() {
        // Read off the context every time rather than copied at construction: a copy is a second
        // declaration of the one number on this path that is silently wrong when it disagrees.
        return context.sampleRate
      },
      onbatch: null,
      onflushed: null,
      onerror: null,
      start() {
        source.connect(node)
        node.connect(silence)
        silence.connect(context.destination)
        capturing = true
      },
      flush() {
        node.port.postMessage({ type: 'flush' })
      },
      close() {
        capturing = false
        node.port.onmessage = null
        context.onstatechange = null
        for (const part of [source, node, silence]) {
          try { part.disconnect() } catch { /* already gone */ }
        }
      },
    }

    // **The answer that would otherwise come back empty with nothing raised.** The state is
    // checked before each answer, which catches a context that was already interrupted - but iOS
    // interrupts one *mid-answer* too, on an incoming call, the screen locking, or the tab going
    // to the background. `process()` then stops being called, no batches are posted, the socket
    // stays open, and the silence timer ends the answer three seconds later: an empty answer, no
    // notice, and a context the next answer quietly resumes, so it reads as somebody who said
    // nothing.
    //
    // It is a new exposure and it lands on the population this branch exists to serve - before
    // PCM, an iPhone was refused outright and could not reach this path at all. Routed to
    // `onerror`, which is the same drop the socket reports: a handover on a standard engagement,
    // an honest halt on one that requires Deepgram, and the answer so far kept either way.
    //
    // `onstatechange` rather than `addEventListener`, because one capture is live at a time and
    // the assignment is what makes that structural: a stale handler from the previous answer is
    // overwritten rather than accumulated, and `close()` clears the last one.
    context.onstatechange = () => {
      if (capturing && context.state !== 'running') capture.onerror?.()
    }

    node.port.onmessage = (event: MessageEvent) => {
      // The worklet posts Float32 and the conversion happens here, on the main thread, so that
      // it is a pure function a test can drive with a sample outside the range - which is the
      // only way to see the clamp. Batching is the worklet's half; the format is this one's.
      if (event.data instanceof ArrayBuffer) {
        capture.onbatch?.(floatTo16BitPcm(new Float32Array(event.data)))
        return
      }
      if (event.data && (event.data as { type?: string }).type === 'flushed') capture.onflushed?.()
    }
    node.onprocessorerror = () => capture.onerror?.()
    return capture
  } catch {
    return null
  }
}

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
 * Open the socket, start capturing, and translate Deepgram's frames into the page's hooks.
 *
 * Answers `null` rather than throwing when the capture cannot be built, the socket does not open
 * in time, or it closes during the handshake, because the caller's response to every one of those
 * is the same: fall back. Once the socket *is* open, a later failure is a different matter - the
 * participant is mid-answer by then - and that goes to `onDropped`, which keeps what was heard
 * and says so.
 *
 * **It takes a built capture rather than a stream and a context**, and the two calls are separate
 * for a reason the participant feels. The URL carries `sample_rate` and only the live context
 * knows it, so the capture has to exist first either way - but composing them *here* left the
 * caller unable to tell "this browser's audio engine would not start" from "Deepgram refused the
 * socket", and it reported the second. An operator then checks the key, the balance and the
 * network, all of which are fine. Two calls, two answers, and the page reports the half that
 * actually declined.
 *
 * Ownership passes with the capture: from here on every route that ends the answer - flushed,
 * deadline, error, close, and all four refusals - tears the graph down.
 */
export async function openDeepgramSocket(
  capture: PcmCapture,
  grant: DeepgramGrant,
  hooks: RecogniserHooks,
  base: string = DEEPGRAM_LISTEN_URL,
): Promise<Recogniser | null> {
  const url = deepgramListenUrl(grant, { sampleRate: capture.sampleRate }, base)
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
    let capturing = false
    let flushTimer: ReturnType<typeof setTimeout> | null = null
    let socket: WebSocket

    try {
      socket = new WebSocket(url)
    } catch {
      capture.close()
      resolve(null)
      return
    }

    // **Armed before the handshake rather than in `onopen`.** The graph exists from the moment
    // the capture was built, so a processor that throws - or a context iOS interrupts - during
    // the second or two the socket takes to open would otherwise reach a `null` handler and be
    // swallowed, leaving a participant talking into a dead capture on an open socket.
    capture.onerror = () => {
      if (stopping) return
      if (!opened) {
        settle(null)
        try { socket.close() } catch { /* already gone */ }
        return
      }
      reportDropped()
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
      // Answering `null` means no `Recogniser` reaches the caller, and `finishStop` - the only
      // other place the graph comes down - is reachable only through the `stop` on that object.
      // So this is the last chance to disconnect, on every one of the four routes that refuse:
      // the handshake deadline, an error before open, a close before open, and the `catch` in
      // `onopen`. A graph left connected holds the microphone and posts into nothing.
      if (value === null) capture.close()
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
     *   2. `capture.flush()`, and `CloseStream` only once the worklet's remaining samples have
     *      been sent - sending it earlier discards the very audio this exists to keep;
     *   3. the socket stays open until Deepgram closes it, or the deadline passes.
     *
     * **PCM has no `onstop`, so step 2 is a round trip rather than an event.** The worklet holds
     * up to a batch of samples that have not been posted, so it is asked for them
     * (`{type:'flush'}`), it posts the tail and then acknowledges, and the acknowledgement is
     * what sends `CloseStream`. A `MessagePort` delivers in order, so "the tail is on the wire
     * before the close" is a property of the port rather than of a timer - which is a stronger
     * guarantee than the `MediaRecorder` path had, where the final `dataavailable` and `onstop`
     * were two independently queued tasks. The deadline is unchanged and still bounds the whole
     * of it, because a worklet on a context that has been interrupted will never answer at all.
     */
    function stop() {
      if (stopping) return
      stopping = true
      flushTimer = setTimeout(finishStop, FLUSH_TIMEOUT_MS)
      if (!capturing) {
        requestCloseStream()
        return
      }
      // Fires after the worklet has posted its last samples - see the processor's `_emit` order.
      capture.onflushed = () => requestCloseStream()
      try {
        capture.flush()
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
      // The graph comes down here rather than in the page, because this is the only place that
      // knows the answer is over by every route - flushed, deadline, error and close alike. A
      // graph left connected goes on calling `process()` and posting batches into a closed
      // socket for the rest of the interview.
      capture.close()
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
      try {
        capture.onbatch = (bytes: ArrayBuffer) => {
          if (bytes.byteLength === 0) return
          // A real WebSocket **discards** a send on a socket that is no longer open rather than
          // throwing, so without this guard a batch arriving after a drop vanishes in the
          // quietest way there is - and the guard's absence is invisible to any assertion about
          // transcripts. It is asserted directly, on what reached the wire.
          if (socket.readyState !== WebSocket.OPEN) return
          socket.send(bytes)
        }
        capture.start()
        capturing = true
      } catch {
        // **The route the `dropped` flag did not cover, kept.** This `catch` answers the promise
        // with `null` - "fall back" - and then closes the socket, and that close arrives at a
        // socket which is open and not stopping, so `onclose` below called `reportDropped()`.
        // The caller then had two reasons to start a browser recogniser, the null answer and the
        // drop, and started one for each: two on one microphone, the first orphaned beyond the
        // reach of `stop()` and restarting itself for the rest of the interview.
        //
        // Claiming the drop here rather than suppressing it at `onclose` is deliberate: this is
        // the only place that knows the closure was ours, and a test on `onclose` for "was the
        // capture started?" would be the same knowledge written where it cannot be checked.
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
