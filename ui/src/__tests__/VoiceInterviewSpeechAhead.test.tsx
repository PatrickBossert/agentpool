// ui/src/__tests__/VoiceInterviewSpeechAhead.test.tsx
//
// Synthesising the next question while the participant answers this one.
//
// Finding 2 of the 17 September interview was audio breaking up over the first few questions.
// **The cache is not the cause of that** - it was cold for the whole interview rather than only
// at the start, and the stored bytes are intact early and late alike - but the measurement made
// on the way to finding that out is a defect of its own, and this is the fix for it:
//
//   95 of the 96 speak calls that interview made were **cache misses**. Every question was
//   synthesised live with the participant waiting, because `prewarm_script_audio` on the
//   server has no production caller and the cache key includes the voice, so sp62's per-project
//   voice invalidated the 78 entries a March run had left behind.
//
// The idle time to hide it in is real and large: an utterance plays for fifteen to twenty
// seconds and the answer to it takes twenty more, against a synthesis of a few. So one
// utterance is requested ahead - and **one**, after the current blob is in hand, so the
// prefetch never competes with the request somebody is waiting on.
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, afterEach, vi } from 'vitest'

import VoiceInterview, { scriptedSpeech } from '../pages/VoiceInterview'
import type { InterviewScript } from '../types'

const WELCOME = 'Welcome to this conversation about order fulfilment.'
const Q1 = 'What slows the connections down, in your experience?'
const BRANCH = 'And who decides the order the works are done in?'
const Q2 = 'What would you change first, if it were yours to change?'
const CLOSING = 'Thank you very much for your time this afternoon.'

function script(overrides: Partial<InterviewScript> = {}): InterviewScript {
  return {
    script_id: 'SC-014', node_label: 'Order Fulfilment', level: 'L2', perspective: null,
    research_brief: '', study_objectives: [], welcome_message: WELCOME,
    sections: [{
      section_id: 'S1', title: 'Operations',
      questions: [
        {
          id: 'q1', text: Q1, follow_up_count: 1,
          probing_instructions: '', follow_up_branches: [BRANCH], evasion_signals: [],
        },
        {
          id: 'q2', text: Q2, follow_up_count: 0,
          probing_instructions: '', follow_up_branches: [], evasion_signals: [],
        },
      ],
    }],
    closing_message: CLOSING,
    ...overrides,
  } as InterviewScript
}

describe('the plan of what will be said', () => {
  it('lists the scripted utterances in the order the interview speaks them', () => {
    expect(scriptedSpeech(script())).toEqual([WELCOME, Q1, BRANCH, Q2, CLOSING])
  })

  it('lists only the positioning line of a framing block, as the interview does', () => {
    // The loop speaks `positioning` and nothing else: the bullets and both lenses were dropped
    // because they made a minute of preamble after a welcome that had already covered purpose.
    // A plan that listed them would prefetch audio nobody ever hears, and - worse - the cursor
    // would stop matching from the second utterance onwards.
    const withFraming = script({
      framing_block: {
        positioning: 'This is about how the work actually gets done.',
        context_setting: ['A bullet nobody reads aloud.'],
        dual_lenses: { efficiency: 'Not spoken.', effectiveness: 'Not spoken either.' },
      },
    })
    expect(scriptedSpeech(withFraming)).toEqual([
      WELCOME, 'This is about how the work actually gets done.', Q1, BRANCH, Q2, CLOSING,
    ])
  })

  it('lists only the peer referral from a synthesis check, because the rest is withdrawn', () => {
    // Withdrawn on 4 September and still withdrawn: the synthesis prompt summarised a
    // conversation before it had happened. Only the peer referral is spoken.
    const withSynthesis = script({
      synthesis_check: {
        synthesis_prompt: 'Withdrawn.',
        peer_referral: 'Who else should I be speaking to about this?',
        forward_roadmap: 'Withdrawn.',
      },
    } as Partial<InterviewScript>)
    const plan = scriptedSpeech(withSynthesis)
    expect(plan).toContain('Who else should I be speaking to about this?')
    expect(plan).not.toContain('Withdrawn.')
    expect(plan[plan.length - 1]).toBe(CLOSING)
  })

  it('lists a maturity rating prompt, which the interview speaks at the end of its section', () => {
    const withRating = script()
    withRating.sections[0].maturity_rating = {
      dimension: 'Capability',
      prompt: 'How mature would you say that is, from nought to four?',
      scale: { '0': 'Absent', '1': 'Initial', '2': 'Repeatable', '3': 'Defined', '4': 'Optimised' },
      capture_after: '', probe_on_mismatch: '',
    }
    expect(scriptedSpeech(withRating)).toEqual([
      WELCOME, Q1, BRANCH, Q2, 'How mature would you say that is, from nought to four?', CLOSING,
    ])
  })

  it('lists no more branches than the question allows', () => {
    // `follow_up_count` is the condition the loop asks, so a script carrying three branches and
    // allowing one must list one - otherwise two utterances that are never spoken sit between
    // the cursor and the next real question, and the prefetch runs a question behind for ever.
    const capped = script()
    capped.sections[0].questions[0].follow_up_count = 1
    capped.sections[0].questions[0].follow_up_branches = [BRANCH, 'Never asked.', 'Nor this.']
    expect(scriptedSpeech(capped)).toEqual([WELCOME, Q1, BRANCH, Q2, CLOSING])
  })
})

// ---------------------------------------------------------------------------------------
// The interview, driven. A correct plan nobody requests ahead of is no prefetch at all.
// ---------------------------------------------------------------------------------------

const VOICE = { elevenlabs_voice_id: 'V', language: 'en', country_code: 'GB', model_id: 'm' }
const SESSION = {
  id: 1, stakeholder_id: 1, node_label: 'Order Fulfilment',
  session_token: 'tok', status: 'pending', voice_config: VOICE,
}

/** What was asked of the speak door, in the order it was asked, for this interview. */
let spoken: string[] = []
/** Which of those had already been asked for before they were needed. */
let speakFailsFor: string | null = null

function installFetch(scriptBody: InterviewScript) {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/interviews/tok')) {
      return new Response(
        JSON.stringify({
          session: SESSION, script: scriptBody, speech_policy: 'browser_permitted',
        }),
        { status: 200 },
      )
    }
    if (url.endsWith('/speak')) {
      const text = String(JSON.parse(String(init!.body)).text)
      spoken.push(text)
      if (text === speakFailsFor) return new Response('nope', { status: 503 })
      return new Response(new Blob([new Uint8Array([1, 2, 3])]), { status: 200 })
    }
    return new Response('{}', { status: 200 })
  }))
}

function installTheInterviewsSurroundings() {
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
          results: [Object.assign(
            [{ transcript: 'An answer long enough that nobody would press for more of it.' }],
            { isFinal: true },
          )],
        })
        this.onerror?.({ error: 'no-speech' })
        this.onend?.()
      }, 0)
    }
    stop() { this.onend?.() }
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).SpeechRecognition = FakeRecognition
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
      enumerateDevices: async () => [
        { kind: 'audioinput', deviceId: 'mic-1', label: 'Built-in Microphone' },
      ],
      getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }),
    },
  })
}

async function runWholeInterview(scriptBody: InterviewScript) {
  spoken = []
  installFetch(scriptBody)
  installTheInterviewsSurroundings()
  render(
    <MemoryRouter initialEntries={['/interview/tok']}>
      <Routes>
        <Route path="/interview/:sessionToken" element={<VoiceInterview />} />
      </Routes>
    </MemoryRouter>,
  )
  await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))
  // Settled inside the test that started it: an interview that outlives its test goes on
  // asking the speak door through the *next* test's stub, and `spoken` cannot tell them apart.
  await screen.findByText(/thank you/i, {}, { timeout: 10000 })
}

afterEach(() => {
  cleanup()
  speakFailsFor = null
  vi.stubGlobal('fetch', async () => new Response('{}', { status: 200 }))
})

describe('the interview asks for the next utterance before it needs it', () => {
  it('asks for each utterance exactly once, and one ahead of speaking it', async () => {
    await runWholeInterview(script())

    // **Once each.** Two requests for the same words would mean the prefetch and the speak
    // raced rather than shared, which is worse than no prefetch: two live syntheses, one of
    // them while somebody waits.
    expect(spoken).toEqual([WELCOME, Q1, BRANCH, Q2, CLOSING])

    // And the order is the plan's, which is what "one ahead" looks like from the wire: the
    // request for Q1 goes out while the welcome is still being heard, so by the time the
    // interview wants Q1 there is nothing to wait for.
    expect(spoken).toEqual(scriptedSpeech(script()))
  }, 20000)

  it('asks for the next question before the answer to this one is finished', async () => {
    // The property stated as a *time* rather than as a count, because the count above is
    // satisfied by a page that asks for everything at the very end. The interview is stopped
    // mid-flight: the welcome has been spoken and the first answer is being given, and Q1 must
    // already have been asked for.
    spoken = []
    installFetch(script())
    installTheInterviewsSurroundings()
    render(
      <MemoryRouter initialEntries={['/interview/tok']}>
        <Routes>
          <Route path="/interview/:sessionToken" element={<VoiceInterview />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))

    // The moment the first question is on screen, the *branch* after it has been asked for.
    await screen.findByText(Q1)
    await screen.findByText(BRANCH, {}, { timeout: 10000 })
    expect(spoken.indexOf(Q2)).toBeGreaterThan(-1)

    await screen.findByText(/thank you/i, {}, { timeout: 10000 })
  }, 20000)

  it('does not remember that an utterance could not be had', async () => {
    // **A cached failure mutes a question for the rest of the interview.** The prefetch runs
    // unattended, so a refused request would otherwise be discovered only when the interviewer
    // reached that question and said nothing - and there would be no second attempt, because
    // the map holds the answer. Driven here as the closing message being refused once.
    speakFailsFor = CLOSING
    await runWholeInterview(script())

    // Asked twice: once ahead, refused; once when it was actually wanted.
    expect(spoken.filter(text => text === CLOSING)).toHaveLength(2)
  }, 20000)

  it('walks the plan exactly once even when a press is spoken in the middle of it', async () => {
    // An elaboration press is composed while the interview runs and is not on the plan, so it
    // must not be mistaken for the next planned utterance.
    //
    // **What this can and cannot see, stated rather than implied.** It sees a scripted
    // utterance requested twice or skipped, which is what a plan walked wrongly produces. It
    // does *not* see the cursor advancing on the press itself: because the prefetch runs
    // **ahead** of playback, an over-advanced cursor simply prefetches further ahead and
    // playback catches up on the cache, so every utterance is still requested exactly once.
    // The guard is kept because a cursor that does not mean "the next thing to be said" is a
    // cursor the next change will get wrong - not because this test proves it.
    const withPress = script()
    // No branch, so the sequence is plan, press, plan - a press consumes a branch slot, and a
    // branch that is listed and never reached would confound the counts with the subject.
    withPress.sections[0].questions[0].follow_up_count = 0
    withPress.sections[0].questions[0].follow_up_branches = []
    withPress.sections[0].questions[0].evasion_signals = []
    spoken = []
    installFetch(withPress)
    installTheInterviewsSurroundings()

    // A recogniser whose first answer is short enough to draw a press, and whose later answers
    // are not - so exactly one dynamic utterance enters the sequence.
    let answered = 0
    const heard = [
      'Not really',
      'Because the evidence for it has never been gathered anywhere',
      'The head of asset management signs every one of them off personally',
      'I would change the order in which the works are actually scheduled',
    ]
    class Answering {
      onresult: ((e: unknown) => void) | null = null
      onend: (() => void) | null = null
      onerror: ((e: { error: string }) => void) | null = null
      continuous = false
      interimResults = false
      lang = ''
      start() {
        const transcript = heard[answered++] ?? 'Nothing more to add about that one at all.'
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
    ;(window as any).SpeechRecognition = Answering

    render(
      <MemoryRouter initialEntries={['/interview/tok']}>
        <Routes>
          <Route path="/interview/:sessionToken" element={<VoiceInterview />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))
    await screen.findByText(/thank you/i, {}, { timeout: 10000 })

    // The press was spoken - so this test is about the case it says it is about - and every
    // scripted utterance was still asked for exactly once.
    const press = spoken.find(text => !scriptedSpeech(withPress).includes(text))
    expect(press, 'no press was spoken, so this proves nothing').toBeTruthy()
    for (const planned of scriptedSpeech(withPress)) {
      expect(spoken.filter(text => text === planned), planned).toHaveLength(1)
    }
  }, 25000)
})
