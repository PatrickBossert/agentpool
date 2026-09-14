// ui/src/__tests__/PcmCapture.test.ts
//
// The two halves of the capture that are pure enough to drive directly: the Float32 -> Int16
// conversion, and the worklet processor's batching and flush.
//
// **Both are driven as functions rather than through a rendered interview**, because every
// property here fails silently when it is wrong. A wrong sample rate, an unclamped sample, a
// byte order taken from the platform default and a flush that posts its acknowledgement before
// its tail all produce a socket that opens, audio that streams, and a transcript that is empty
// or wrong - with nothing thrown anywhere. A screen assertion cannot see any of them.
import { beforeAll, describe, expect, it, vi } from 'vitest'

import { PCM_BATCH_FRAMES, floatTo16BitPcm } from '../api/pcm'

/** The 16-bit samples the wire would carry, read back little-endian. */
function readLittleEndian(bytes: ArrayBuffer): number[] {
  const view = new DataView(bytes)
  const out: number[] = []
  for (let i = 0; i < bytes.byteLength; i += 2) out.push(view.getInt16(i, true))
  return out
}

describe('float samples as the bytes Deepgram decodes', () => {
  it('clamps a sample louder than full scale rather than letting it wrap', () => {
    // **The assertion the round trip cannot make.** `DataView.setInt16` takes its value modulo
    // 2^16, so without the clamp +1.5 arrives as -16386 and -1.5 as +16386: the loudest part of
    // a word inverts. It transcribes as noise, and nothing at either end reports anything.
    // Driven in both directions because a clamp written with one bound is a clamp in one
    // direction, and the suite would be green for the half that was written.
    const samples = readLittleEndian(floatTo16BitPcm(new Float32Array([2, -2, 1.5, -1.5])))

    expect(samples).toEqual([32767, -32768, 32767, -32768])
  })

  it('scales the two halves of the range by the two different maxima', () => {
    // Two's complement holds -32768 and only +32767. Scaling the positive half by 0x8000 makes a
    // legal full-scale positive sample wrap to the most negative one - the same inversion as
    // above, reached from an input that is entirely in range.
    expect(readLittleEndian(floatTo16BitPcm(new Float32Array([1, -1, 0])))).toEqual([32767, -32768, 0])
  })

  it('writes little-endian, which is what linear16 means', () => {
    // Read back big-endian, the bytes must be the other way round. Asserting only through
    // `getInt16(…, true)` would pass against a writer that also used the platform default, so
    // the control is a read that must disagree.
    const bytes = floatTo16BitPcm(new Float32Array([0.5]))
    const view = new DataView(bytes)

    expect(view.getInt16(0, true)).toBe(16383)
    expect(view.getInt16(0, false)).not.toBe(16383)
    // Spelled out as bytes, so the property is visible rather than inferred: 16383 is 0x3FFF,
    // and little-endian puts the low byte first.
    expect([...new Uint8Array(bytes)]).toEqual([0xff, 0x3f])
  })

  it('produces two bytes per sample and nothing else', () => {
    expect(floatTo16BitPcm(new Float32Array(1024)).byteLength).toBe(2048)
    expect(floatTo16BitPcm(new Float32Array(0)).byteLength).toBe(0)
  })
})

// ── The worklet processor ────────────────────────────────────────────────────

/**
 * The `MessagePort` the real `AudioWorkletProcessor` base class provides.
 *
 * A claim about an external system, so: the base class supplies `this.port` - a processor that
 * had to make its own would be testing something the browser does not do - and delivery to the
 * other end is ordered, which is the property the flush sequence depends on. Posts are recorded
 * in the order they were made for exactly that reason.
 */
class RecordingPort {
  posted: unknown[] = []
  onmessage: ((event: { data: unknown }) => void) | null = null
  postMessage(data: unknown, _transfer?: unknown[]) {
    this.posted.push(data)
  }
  /** A message arriving from the main thread. */
  deliver(data: unknown) {
    this.onmessage?.({ data })
  }
}

let PcmCaptureProcessor: new (options?: { processorOptions?: { batchFrames?: number } }) => {
  port: RecordingPort
  process: (inputs: Float32Array[][]) => boolean
}

beforeAll(async () => {
  // The worklet global scope, which has no `window` and no `document`. `registerProcessor` is how
  // a processor is published, so capturing it is how a test gets hold of the class at all.
  vi.stubGlobal('AudioWorkletProcessor', class { port = new RecordingPort() })
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.stubGlobal('registerProcessor', (name: string, ctor: any) => {
    expect(name).toBe('pcm-capture')
    PcmCaptureProcessor = ctor
  })
  await import('../api/pcm-worklet.js')
})

/** One render quantum, which is 128 frames - the number a real `process()` call carries. */
function quantum(value = 0.5, frames = 128): Float32Array[][] {
  return [[new Float32Array(frames).fill(value)]]
}

describe('the worklet processor', () => {
  it('posts nothing until a whole batch has been collected, then posts exactly one', () => {
    // 4096 frames is 32 render quanta. Unbatched this would be 32 socket frames instead of one,
    // and about 375 a second at 48 kHz.
    const processor = new PcmCaptureProcessor({ processorOptions: { batchFrames: PCM_BATCH_FRAMES } })
    const quanta = PCM_BATCH_FRAMES / 128

    for (let i = 0; i < quanta - 1; i += 1) processor.process(quantum())
    expect(processor.port.posted).toEqual([])

    processor.process(quantum())
    expect(processor.port.posted).toHaveLength(1)
    // Float32 in, so four bytes a frame on this side - the conversion to two happens on the main
    // thread, where it can be driven as the pure function above.
    expect((processor.port.posted[0] as ArrayBuffer).byteLength).toBe(PCM_BATCH_FRAMES * 4)
  })

  it('hands over its tail before it says it has flushed', () => {
    // **The order is the flush guarantee.** `deepgram.ts` sends Deepgram's `CloseStream` when
    // `flushed` arrives, so a processor that acknowledged first would have the socket closed
    // underneath the samples it was about to post - which is the tail of the sentence somebody
    // was still speaking when they tapped "Done". Asserted as a sequence, not as presence.
    const processor = new PcmCaptureProcessor({ processorOptions: { batchFrames: PCM_BATCH_FRAMES } })
    processor.process(quantum())

    processor.port.deliver({ type: 'flush' })

    expect(processor.port.posted).toHaveLength(2)
    expect(processor.port.posted[0]).toBeInstanceOf(ArrayBuffer)
    expect((processor.port.posted[0] as ArrayBuffer).byteLength).toBe(128 * 4)
    expect(processor.port.posted[1]).toEqual({ type: 'flushed' })
  })

  it('still acknowledges a flush it has nothing to hand over', () => {
    // The ordinary case at the end of a long silence, and the one that would hang the answer for
    // the whole flush deadline if the acknowledgement were conditional on there being a tail.
    const processor = new PcmCaptureProcessor({ processorOptions: { batchFrames: PCM_BATCH_FRAMES } })

    processor.port.deliver({ type: 'flush' })

    expect(processor.port.posted).toEqual([{ type: 'flushed' }])
  })

  it('reads the block length off the block rather than assuming 128', () => {
    // **Not a hypothetical any more.** Chrome 153 shipped `AudioContextOptions.renderSizeHint`
    // in September 2026, so 128 is the specification's *default* render quantum rather than its
    // value, and a context built at `"hardware"` hands over something else. This code does not
    // pass the hint and so gets 128 today; a processor that hardcoded it would read past a
    // smaller block and drop the tail of a larger one, both silently.
    const processor = new PcmCaptureProcessor({ processorOptions: { batchFrames: 256 } })

    processor.process(quantum(0.5, 100))
    processor.process(quantum(0.5, 100))
    expect(processor.port.posted).toEqual([])

    processor.process(quantum(0.5, 100))
    expect(processor.port.posted).toHaveLength(1)
    expect((processor.port.posted[0] as ArrayBuffer).byteLength).toBe(256 * 4)
  })

  it('carries on through a quantum with no input at all', () => {
    // A disconnected input hands over an empty array. Returning false, or reading channel 0 of
    // nothing, would end the processor for the rest of the answer.
    const processor = new PcmCaptureProcessor({ processorOptions: { batchFrames: PCM_BATCH_FRAMES } })

    expect(processor.process([])).toBe(true)
    expect(processor.process([[]])).toBe(true)
    expect(processor.process(quantum())).toBe(true)
  })

  it('refuses a missing batch size rather than capturing into a buffer that never fills', () => {
    // **The silent failure this throw exists to convert into a loud one.** A zero-length batch
    // never reaches its own length, so nothing is ever posted: a capture that runs, consumes the
    // microphone, sends not one byte, and reports nothing. `startPcmCapture` treats the
    // resulting `processorerror` as "this browser cannot capture" and falls back.
    expect(() => new PcmCaptureProcessor({ processorOptions: {} })).toThrow(/batchFrames/)
    expect(() => new PcmCaptureProcessor()).toThrow(/batchFrames/)
  })
})
