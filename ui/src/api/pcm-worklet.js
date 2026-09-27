// ui/src/api/pcm-worklet.js
//
// The audio thread's half of the capture: batch the graph's samples and post them out.
//
// Plain JavaScript and no imports, because this file is loaded by `AudioWorklet.addModule` into
// the `AudioWorkletGlobalScope` rather than by the bundler - there is no `window`, no
// `document`, and nothing this module could import from `src/`. `deepgram.ts` addresses it with
// `new URL('./pcm-worklet.js', import.meta.url)` so that Vite emits it as an asset and rewrites
// the address under the `/dashboard` base; a bare absolute path would 404 in the browser, which
// is a trap this repository has been caught by three times.
//
// **Nothing is decided here.** The batch size arrives in `processorOptions` from
// `PCM_BATCH_FRAMES` in `pcm.ts`, and the conversion to 16-bit happens on the main thread in
// `floatTo16BitPcm`. This file holds no number and no format knowledge of its own, so there is
// nothing in it that can drift from the module that declares them.

class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super()
    const batchFrames = options && options.processorOptions && options.processorOptions.batchFrames
    if (!batchFrames || batchFrames < 1) {
      // **Refused rather than defaulted.** A missing batch size would give a zero-length buffer
      // that never fills and therefore never posts: a capture that runs perfectly, sends
      // nothing, and reports no error anywhere. Throwing here fires `processorerror` on the
      // node, which `startPcmCapture` treats as "this browser cannot capture" and falls back.
      throw new Error('pcm-capture: processorOptions.batchFrames is required')
    }
    this._batch = new Float32Array(batchFrames)
    this._filled = 0
    this.port.onmessage = event => {
      if (event.data && event.data.type === 'flush') {
        // The tail first, then the acknowledgement. `deepgram.ts` sends Deepgram's `CloseStream`
        // when the acknowledgement arrives, so this order is what keeps the last words of an
        // answer: a `MessagePort` delivers in order, so the samples are on the wire before the
        // socket is asked to close. Reversing these two lines is the regression that cost a
        // participant the end of any sentence they were still speaking when they tapped "Done".
        this._emit()
        this.port.postMessage({ type: 'flushed' })
      }
    }
  }

  /** Hand over whatever has been collected, and start again. Silent when there is nothing. */
  _emit() {
    if (this._filled === 0) return
    // A copy rather than the batch itself: the buffer is transferred, so it is detached at this
    // end the moment it is posted and could not be written into again.
    const out = this._batch.slice(0, this._filled)
    this._filled = 0
    this.port.postMessage(out.buffer, [out.buffer])
  }

  /**
   * One render quantum from the graph.
   *
   * The length is read off the block rather than assumed to be 128, and **that has stopped being
   * merely defensive**. 128 was the render quantum everywhere until Chrome 153 shipped
   * `AudioContextOptions.renderSizeHint` in September 2026, which lets a context be built at
   * `"hardware"` or at an explicit size; the Web Audio specification now calls 128 the default
   * rather than the value. This code does not pass the hint, so it gets 128 today - but a
   * processor that hardcoded it would read past the end of a smaller block and silently drop the
   * tail of a larger one, which is a transcript that is quietly wrong rather than absent.
   *
   * One channel. A microphone is normally mono and `channels=1` is what the socket is opened
   * for; taking channel 0 is what makes that declaration true rather than hopeful, on a device
   * that hands over two.
   *
   * Returns `true` unconditionally, so the processor stays alive across a silent passage. It
   * writes nothing to `outputs`, so what reaches the graph's destination is silence - see the
   * zero-gain node in `startPcmCapture` for the other half of that argument.
   */
  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (!channel) return true
    for (let i = 0; i < channel.length; i += 1) {
      this._batch[this._filled] = channel[i]
      this._filled += 1
      if (this._filled === this._batch.length) this._emit()
    }
    return true
  }
}

registerProcessor('pcm-capture', PcmCaptureProcessor)
