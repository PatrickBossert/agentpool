// ui/src/__tests__/TestInterviewLiveCaptions.test.tsx
//
// The rehearsal dialog shows what it is hearing, while it is hearing it.
//
// It set `interimResults = true` from the beginning and used the interim text for exactly one
// thing - pre-warming the elaboration press - so the consultant rehearsing an interview saw a
// countdown bar and no words, and could only find out what had been captured by opening the
// transcript afterwards. The participant page (`VoiceInterview.tsx`) had displayed it properly
// throughout; this is that display, not a second one.
//
// Three properties, one test each, because a mutation that kills two tests tells you less than
// three that each name one thing:
//
//   1. the caption appears while the interviewee is speaking;
//   2. it is gone once the answer resolves - **asserted while the next question is being
//      spoken**, which is the window the defect actually lives in;
//   3. the speculative elaboration press still reads the same interims, and is still the only
//      one of the two readers with a word threshold.
//
// Property 2 is the one worth explaining, because the obvious version of it does not work. The
// dialog clears the caption in two places - at the top of `listenForAnswer`, and in `finish`
// when an answer resolves - and between an answer resolving and the next listen starting the
// dialog **speaks the next question**. So a test that only looks once the next recogniser is
// running is satisfied by the top-of-listen clear alone, and deleting the clear in `finish`
// leaves it green: measured, not supposed. That is precisely the reported defect surviving its
// own test, because the previous answer's words sit under the new question for as long as the
// new question takes to speak.
//
// The fix is that this file **steps the utterances**. `FakeAudio.play()` registers and waits to
// be told to end, so the test can stand inside "question 2 is on screen, being read aloud" and
// assert the caption is already gone. The sibling dialog fakes auto-end in a `setTimeout(0)`,
// which is right for asserting what was spoken and useless for asserting anything about the
// window between two answers.
//
// The caption is read by `data-testid` rather than by its text. The transcript panel renders
// every answer given so far - clamped, but present in the DOM - so a text search for the previous
// answer would find it there and the absence assertion would fail against correct code.
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import TestInterviewDialog from '../components/tabs/TestInterviewDialog'

const SCRIPT = {
  node_label: 'Order Fulfilment',
  study_objectives: [],
  welcome_message: 'Welcome to the test.',
  closing_message: 'Thanks for testing.',
  sections: [
    {
      title: 'Operations',
      questions: [
        {
          id: 'q1',
          text: 'What slows fulfilment down?',
          follow_up_count: 0,
          probing_instructions: 'Ask for specifics.',
          follow_up_branches: [],
          // No evasion signal fires on either answer below, so no elaboration press is consumed
          // and the loop moves question to question. The press has its own file.
          evasion_signals: ['zzz-never-matches'],
        },
        {
          id: 'q2',
          text: 'Where does the handover go wrong?',
          follow_up_count: 0,
          probing_instructions: 'Ask for specifics.',
          follow_up_branches: [],
          evasion_signals: ['zzz-never-matches'],
        },
      ],
    },
  ],
}

// Deliberately sharing no words with each other or with either question, so a caption drawn from
// the wrong source cannot satisfy an assertion by coincidence.
const FIRST_INTERIM  = 'warehouse picking backlog'
const FIRST_FINAL    = 'warehouse picking backlog every Monday morning'
const SECOND_INTERIM = 'nobody countersigns the despatch note'

// ── Fakes the test steps ──────────────────────────────────────────────────────

/**
 * A recogniser the test drives, rather than one that runs to completion on its own.
 *
 * `emitFinal` reproduces the handshake a real browser performs on a quiet microphone, which is
 * what the sibling dialog fakes do and for the same reason: `no-speech` clears the dialog's
 * recogniser ref, and that is what stops `onend` restarting the recogniser for ever.
 */
class FakeRecognition {
  continuous = false
  interimResults = false
  lang = ''
  onresult: ((e: unknown) => void) | null = null
  onend: (() => void) | null = null
  onerror: ((e: { error: string }) => void) | null = null

  start() { recognisers.push(this) }
  stop() { this.onend?.() }

  private emit(transcript: string, isFinal: boolean) {
    this.onresult?.({
      resultIndex: 0,
      results: [Object.assign([{ transcript }], { isFinal })],
    })
  }

  emitInterim(text: string) { this.emit(text, false) }

  emitFinal(text: string) {
    this.emit(text, true)
    this.onerror?.({ error: 'no-speech' })
    this.onend?.()
  }
}

/** An utterance that keeps playing until the test ends it. */
class FakeAudio {
  onended: (() => void) | null = null
  onerror: (() => void) | null = null
  pause() {}
  play() { utterances.push(this); return Promise.resolve() }
  end() { this.onended?.() }
}

let recognisers: FakeRecognition[] = []
let utterances: FakeAudio[] = []
let recogniserCursor = 0
let utteranceCursor = 0

/**
 * The next recogniser the dialog starts, waited for rather than assumed.
 *
 * Counted rather than read off the end of the array, so a test asking for the second question's
 * recogniser cannot be handed the first one's and pass against a dialog that never moved on.
 */
async function nextRecogniser(): Promise<FakeRecognition> {
  await waitFor(
    () => expect(recognisers.length).toBeGreaterThan(recogniserCursor),
    { timeout: 5000 },
  )
  return recognisers[recogniserCursor++]
}

/** Let the interviewer finish saying the thing they are currently saying. */
async function endNextUtterance(): Promise<void> {
  await waitFor(
    () => expect(utterances.length).toBeGreaterThan(utteranceCursor),
    { timeout: 5000 },
  )
  const speaking = utterances[utteranceCursor++]
  await act(async () => { speaking.end() })
}

/** Wait until the interviewer has *started* saying something, without ending it. */
async function waitForUtteranceInProgress(): Promise<void> {
  await waitFor(
    () => expect(utterances.length).toBeGreaterThan(utteranceCursor),
    { timeout: 5000 },
  )
}

function installFetch() {
  return vi.fn(async (url: string) => {
    if (new URL(url, 'http://test').pathname.endsWith('/script')) {
      return new Response(JSON.stringify(SCRIPT), { status: 200 })
    }
    if (url.endsWith('/speak')) {
      return new Response(new Blob([new Uint8Array([1, 2, 3])]), { status: 200 })
    }
    if (url.endsWith('/elaboration-press')) {
      return new Response(JSON.stringify({ press_text: 'Which step, specifically?' }), { status: 200 })
    }
    return new Response('{}', { status: 200 })
  })
}

function installAudioAndMic() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).SpeechRecognition = FakeRecognition
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).webkitSpeechRecognition = FakeRecognition
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).Audio = FakeAudio
  // The dialog's spoken briefing runs through Web Audio so it keeps the user gesture. It is left
  // auto-ending: it belongs to the ready screen rather than to the interview, and nothing this
  // file asserts happens while it plays.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).AudioContext = class {
    destination = {}
    async decodeAudioData() { return {} }
    createBufferSource() {
      return {
        buffer: null,
        connect() {},
        onended: null as null | (() => void),
        start(this: { onended: null | (() => void) }) { setTimeout(() => this.onended?.(), 0) },
      }
    }
    createAnalyser() {
      return { fftSize: 0, frequencyBinCount: 8, getByteFrequencyData() {} }
    }
    createMediaStreamSource() { return { connect() {} } }
    async close() {}
  }
  URL.createObjectURL = vi.fn(() => 'blob:fake')
  URL.revokeObjectURL = vi.fn()
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      enumerateDevices: async () => [
        { kind: 'audioinput', deviceId: 'mic-1', label: 'Built-in Microphone' },
        { kind: 'audiooutput', deviceId: 'spk-1', label: 'Built-in Output' },
      ],
      getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }),
    },
  })
}

/** Open the dialog, get past device setup and the briefing, and start the interview. */
async function openAndStart() {
  recognisers = []
  utterances = []
  recogniserCursor = 0
  utteranceCursor = 0
  vi.stubGlobal('fetch', installFetch())
  installAudioAndMic()

  render(<TestInterviewDialog
      slug="smoke"
      onClose={() => {}}
      agentId="stakeholder_interviewer"
      displayName="Avery Singh"
      imageUrl="/agents/avery-singh.jpg"
    />)

  await userEvent.click(await screen.findByRole('button', { name: /continue/i }))
  await userEvent.click(await screen.findByRole('button', { name: /start test interview/i }))

  // The welcome message, then the first question - the two utterances before anybody listens.
  await endNextUtterance()
  await endNextUtterance()
}

const pressCalls = () =>
  (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls
    .filter(c => String(c[0]).endsWith('/elaboration-press'))

describe('the rehearsal dialog shows what it is hearing', () => {
  beforeEach(() => { vi.restoreAllMocks() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('displays the interim text live while the answer is being given', async () => {
    await openAndStart()
    await screen.findByText('What slows fulfilment down?')

    const first = await nextRecogniser()
    act(() => { first.emitInterim(FIRST_INTERIM) })

    await waitFor(() =>
      expect(screen.getByTestId('live-caption')).toHaveTextContent(FIRST_INTERIM),
    )
  })

  it('has cleared the caption by the time the next question is being spoken', async () => {
    await openAndStart()
    await screen.findByText('What slows fulfilment down?')

    const first = await nextRecogniser()
    act(() => { first.emitInterim(FIRST_INTERIM) })
    await waitFor(() => expect(screen.getByTestId('live-caption')).toBeInTheDocument())

    // The answer resolves. From here the dialog puts question 2 on screen and reads it aloud,
    // and it is *that* window the reported defect lives in - not the one after the next
    // recogniser starts, which the top-of-listen clear would cover on its own.
    act(() => { first.emitFinal(FIRST_FINAL) })

    await screen.findByText('Where does the handover go wrong?')
    await waitForUtteranceInProgress()

    // Question 2 is on screen and being spoken, and nothing is listening yet.
    expect(screen.getByText('Where does the handover go wrong?')).toBeInTheDocument()
    expect(screen.queryByTestId('live-caption')).toBeNull()

    // And the caption is live again on this question - the display is a property of listening,
    // not something that happened once on the first question.
    await endNextUtterance()
    const second = await nextRecogniser()
    act(() => { second.emitInterim(SECOND_INTERIM) })
    await waitFor(() =>
      expect(screen.getByTestId('live-caption')).toHaveTextContent(SECOND_INTERIM),
    )
    expect(screen.getByTestId('live-caption')).not.toHaveTextContent(FIRST_FINAL)
  })

  it('still pre-warms the elaboration press from the same interim text', async () => {
    // Both readers take the same string, for different purposes, and the caption must not have
    // displaced the press. This test asserts **nothing** about the caption: with a caption
    // assertion in it, deleting the one line that feeds both failed it on the caption and said
    // nothing about the press.
    await openAndStart()
    await screen.findByText('What slows fulfilment down?')
    const first = await nextRecogniser()

    // Eleven words - past the press's own ten-word threshold.
    act(() => { first.emitInterim('one two three four five six seven eight nine ten eleven') })

    // The speculative fetch is debounced by 800ms, so the assertion is that it arrives.
    await waitFor(() => expect(pressCalls().length).toBeGreaterThan(0), { timeout: 4000 })
  })

  it('does not press on a short interim, so the caption is not merely the press firing', async () => {
    // The mirror of the test above, and what stops "feeds the caption" and "feeds the press"
    // being one assertion. A caption that appeared only once the press fired would satisfy the
    // first test perfectly; this one shows the caption on three words, which the press declines
    // to spend a request on.
    await openAndStart()
    await screen.findByText('What slows fulfilment down?')
    const first = await nextRecogniser()

    act(() => { first.emitInterim(FIRST_INTERIM) })
    await waitFor(() =>
      expect(screen.getByTestId('live-caption')).toHaveTextContent(FIRST_INTERIM),
    )

    // Well past the 800ms debounce, with no press spent.
    await new Promise(r => setTimeout(r, 1200))
    expect(pressCalls()).toHaveLength(0)
  })
})
