// ui/src/api/pcm.ts
//
// Raw PCM, and the two facts about it that fail silently.
//
// This is the whole of the audio format decision, held in one file so that the worklet, the
// socket and the query string cannot come to disagree about it. Everything here is a pure
// function or a constant: the AudioWorklet graph is in `deepgram.ts` and the processor itself is
// `pcm-worklet.js`, and neither of them holds a number this file does not declare.
//
// **Why raw PCM rather than a container.** `MediaRecorder` negotiates a container, and the
// browser decides which: Chrome and Firefox record webm/opus, Safari records MP4/AAC. A socket
// opened for one and fed the other does not error - Deepgram simply returns no transcripts - so
// the previous path had to ask `MediaRecorder.isTypeSupported` and decline Safari outright,
// which meant an engagement that requires Deepgram could not be interviewed on an iPhone or
// iPad. `AudioWorklet` hands over `Float32Array` samples straight from the graph, in the same
// shape on every browser, so there is nothing to negotiate and nothing to decline.

/**
 * How many frames of audio are batched before one is handed to the socket.
 *
 * **Declared once, here, and passed *into* the worklet** through `processorOptions` - the
 * processor reads it rather than restating it, so there is no second number free to drift from
 * this one.
 *
 * A worklet's `process()` call carries one render quantum, which is 128 frames - 2.67 ms at
 * 48 kHz, so an unbatched capture would post and send about 375 times a second. 4096 frames is
 * 85 ms at 48 kHz and 93 ms at 44.1 kHz, both inside the 50-100 ms window that keeps interim
 * transcripts feeling live without paying a socket frame per render quantum. It is a multiple of
 * 128 deliberately, so a batch is a whole number of render quanta at any rate and the processor
 * never has to reason about a partial block.
 */
export const PCM_BATCH_FRAMES = 4096

/**
 * What Deepgram is told the bytes on the socket are.
 *
 * **`encoding` and `sample_rate` are one decision and they are the browser's**, which is what
 * makes them different in kind from `model` and `keyterm` - those are the server's, because the
 * model and its boost parameter are one fact about Deepgram and restating them in TypeScript
 * would be a second declaration of a server-side pairing. This pairing runs the other way: the
 * server cannot observe an `AudioContext`'s sample rate, and an encoding declared apart from the
 * rate that goes with it is exactly the split this file exists to prevent. So both are set here,
 * by the same function, from the live context - and `deepgram_listen_params` declares neither,
 * which `tests/test_interview_keyterms.py` asserts so the pairing cannot be separated later.
 *
 * A mismatch is silent in the worst way available: the socket opens, audio streams, Deepgram
 * decodes the bytes at the wrong rate, and the transcript comes back as gibberish or empty.
 * Nothing errors at either end.
 */
export const PCM_ENCODING = 'linear16'

/** Deepgram is sent one channel, because the processor reads one - see `pcm-worklet.js`. */
export const PCM_CHANNELS = 1

/**
 * Float samples from the audio graph, as the signed 16-bit little-endian bytes Deepgram decodes.
 *
 * Three things here, and each of them is silent when it is wrong.
 *
 * **The clamp.** A sample from the graph is nominally within ±1.0 and is not guaranteed to be -
 * gain, summing and resampling all overshoot. `DataView.setInt16` takes the value modulo 2^16,
 * so an unclamped 1.5 becomes -16386: the loudest part of a word inverts, which transcribes as
 * noise rather than as clipping. Clamping first is the whole of the fix and it cannot be seen by
 * a round trip over in-range samples, which is why the test drives ±2.0 in both directions.
 *
 * **The asymmetric scale.** Two's complement holds -32768 but only +32767, so the negative half
 * scales by 0x8000 and the positive half by 0x7fff. Using 0x8000 for both makes a full-scale
 * positive sample wrap to the most negative one - the same inversion as above, reached from the
 * one input that is perfectly legal.
 *
 * **The endianness.** `linear16` is little-endian, which is `setInt16`'s third argument and is
 * `false` by default. A platform where the default happened to be right would never tell you it
 * was being relied on, so it is passed explicitly.
 */
export function floatTo16BitPcm(samples: Float32Array): ArrayBuffer {
  const bytes = new ArrayBuffer(samples.length * 2)
  const view = new DataView(bytes)
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]!))
    view.setInt16(i * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
  }
  return bytes
}
