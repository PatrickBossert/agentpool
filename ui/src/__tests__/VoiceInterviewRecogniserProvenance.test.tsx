// ui/src/__tests__/VoiceInterviewRecogniserProvenance.test.tsx
//
// Which engine produced each answer, as it reaches the server.
//
// **The finding this exists for is that nobody could tell.** Two live interviews were
// transcribed end to end by the browser's fallback while every surface this product owns
// reported success, and what settled it was a third-party console showing the account's whole
// day as one second of an operator's own test tone. A 45-minute interview served entirely by the
// fallback and a perfect Deepgram run were indistinguishable from everything we own.
//
// So these assert on **what is posted**, never on what a ref holds or what renders. The
// provenance is only worth anything if it survives to the row a crew later reads.
//
// A file of its own, for the reason `VoiceInterviewDeepgramRecovery.test.tsx` states at length:
// `cleanup()` cannot stop an interview - it is an async loop over closures - so an earlier
// test's interview goes on answering and posts through whatever `fetch` stub is installed now.
// Every assertion below therefore scans the completions for the answer **its own** recogniser
// was given, rather than reading "the last completion".
import { cleanup, waitFor } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import { mergeRecognisers } from '../pages/VoiceInterview'
import {
  SCRIPT,
  completionsPosted,
  forgetCompletion,
  installAudioAndMic,
  installFetch,
  installSpeechRecognition,
  installStreaming,
  firstSocket,
} from './support/voiceInterviewFakes'

const GRANT = { token: 'jwt', listen_params: { model: 'nova-3', keyterm: ['Iberdrola'] } }

type Pair = { answer: string; recogniser?: string }

/** The completion carrying `answer` - this test's, rather than "the last one". */
function completionFor(answer: string): Pair[] | null {
  for (const body of completionsPosted()) {
    const pairs = (body.qa_pairs ?? []) as Pair[]
    if (pairs.some(p => p.answer.includes(answer))) return pairs
  }
  return null
}

/** The pair carrying `answer`, from this test's own completion. */
function pairFor(answer: string): Pair | null {
  return completionFor(answer)?.find(p => p.answer.includes(answer)) ?? null
}

/**
 * Every engine named across one interview's pairs.
 *
 * **Asserted as a set over the whole interview, not on one pair, and that was found the hard
 * way.** The primary pair is stamped twice - once when it is recorded and again when an
 * elaboration press is merged into it - so deleting the stamp at the recording site left the
 * primary pair correct and only the *follow-up* pair blank. A test reading one pair passed
 * against a build that attributed nothing. The property worth holding is that **no answer in a
 * completed interview is unattributed**, which is exactly what went wrong live.
 */
function enginesIn(pairs: Pair[]): Set<string> {
  return new Set(pairs.map(p => p.recogniser ?? ''))
}

describe('mergeRecognisers', () => {
  // Pure, so the rules can be driven directly rather than through an interview - the repair this
  // repository prescribes every time a guard's reach has turned out to be described.
  it('reports both engines when an answer was handed over mid-sentence', () => {
    // The flattering half is reporting only the engine that *finished* the answer, which would
    // describe a dropped socket as a clean Deepgram answer.
    expect(mergeRecognisers('deepgram', 'browser')).toBe('deepgram+browser')
    expect(mergeRecognisers('browser', 'deepgram')).toBe('deepgram+browser')
  })

  it('spells one fact one way', () => {
    // Two spellings of a handover would split every count an operator makes over this column.
    expect(mergeRecognisers('deepgram+browser', 'browser')).toBe('deepgram+browser')
    expect(mergeRecognisers('browser', 'deepgram+browser')).toBe('deepgram+browser')
  })

  it('lets a real engine absorb "nothing listened"', () => {
    // An answer partly heard is not an answer nothing heard.
    expect(mergeRecognisers('none', 'browser')).toBe('browser')
    expect(mergeRecognisers('deepgram', 'none')).toBe('deepgram')
  })

  it('keeps "nothing listened" apart from "not recorded"', () => {
    // The distinction the whole column exists for: a transcription failure must not be
    // indistinguishable from a build that never wrote anything down.
    expect(mergeRecognisers('none', 'none')).toBe('none')
    expect(mergeRecognisers('none', '')).toBe('none')
    expect(mergeRecognisers('', '')).toBe('')
  })
})

describe('the engine that produced each answer reaches the server', () => {
  beforeEach(() => {
    forgetCompletion()
    vi.restoreAllMocks()
    installAudioAndMic()
  })
  afterEach(() => {
    cleanup()
    vi.stubGlobal('fetch', async () => new Response('{}', { status: 200 }))
  })

  it('records the browser when Deepgram could not be reached', async () => {
    // The live case, and the one nothing could see: the grant door refuses, the interview runs
    // to completion on the fallback, and every surface reports success. The answer text is
    // identical either way - only this field distinguishes them.
    const { startInterview } = await import('./support/voiceInterviewFakes')
    installStreaming()
    installSpeechRecognition('Permits are the bottleneck.')
    vi.stubGlobal('fetch', installFetch('refused', SCRIPT))

    await startInterview()

    await waitFor(
      () => expect(completionFor('Permits are the bottleneck.')).not.toBeNull(),
      { timeout: 15000 },
    )
    // Every pair, so a single unattributed answer fails. `''` in this set is an answer the
    // system cannot account for, which is the state both live interviews were in throughout.
    expect(enginesIn(completionFor('Permits are the bottleneck.')!)).toEqual(new Set(['browser']))
  }, 20000)

  it('records Deepgram when Deepgram did the listening', async () => {
    // The control. Without it, a field hardcoded to `browser` - or one that simply never
    // changed - would satisfy the test above perfectly. A default and a write are
    // indistinguishable until something chooses the other value.
    const { startInterview } = await import('./support/voiceInterviewFakes')
    installStreaming()
    installSpeechRecognition('the fallback should not be used')
    vi.stubGlobal('fetch', installFetch(GRANT, SCRIPT))

    await startInterview()
    const socket = await firstSocket()
    socket.say('Permits, and the wayleave queue behind them.')

    const said = 'Permits, and the wayleave queue behind them.'
    await waitFor(() => expect(completionFor(said)).not.toBeNull(), { timeout: 15000 })
    expect(pairFor(said)!.recogniser).toBe('deepgram')
    expect(enginesIn(completionFor(said)!)).not.toContain('')
  }, 20000)

  it('records both when the socket drops and the browser finishes the answer', async () => {
    // The handover, which is the case an operator most needs to be able to see: the answer is
    // real, it was partly transcribed by an engine that has never heard of the client, and
    // nothing about the text says so.
    const { startInterview } = await import('./support/voiceInterviewFakes')
    installStreaming()
    installSpeechRecognition('and the wayleave queue behind them.')
    vi.stubGlobal('fetch', installFetch(GRANT, SCRIPT))

    await startInterview()
    const socket = await firstSocket()
    socket.say('Permits,')
    socket.drop()

    await waitFor(() => expect(completionFor('Permits,')).not.toBeNull(), { timeout: 15000 })
    expect(pairFor('Permits,')!.recogniser).toBe('deepgram+browser')
    expect(enginesIn(completionFor('Permits,')!)).not.toContain('')
  }, 20000)
})
