// ui/src/__tests__/VoiceInterviewElaborationPress.test.tsx
//
// When the interviewer presses for more, and on which answers.
//
// Finding 4 of the 17 September live interview: *"I gave some very short answers for which
// there was no elaboration press."* The trigger was a literal substring match against
// `evasion_signals`, phrases Maya writes at design time - and the transcript of that interview
// settles what they are worth. **Ninety-one answers, and not one press fired**: there are 597
// signals across the 199 questions of `interview_scripts_v9`, and they are what a model
// imagines somebody will say ("we are on track", "the team manages it") rather than what
// somebody does.
//
// The same transcript settles two other things this file is built on:
//
//  - **Where the short answers were.** Sixty of the ninety-one answers were to scripted
//    follow-up branches, and *every* answer under nine words was one of them. The press had
//    never looked at a branch answer at all, so a brevity trigger on the primary answer alone -
//    the obvious repair - would have reached one of the eleven. That is this project's
//    recurring failure: the property asserted one layer away from where it holds.
//
//  - **Where to put the threshold.** The eleven answers under nine words are the ones a reader
//    would call unelaborated; at nine and above they are substantive. So the control below is a
//    long, non-evasive answer, without which a change that pressed on everything would pass.
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, afterEach, vi } from 'vitest'

import VoiceInterview, { BRIEF_ANSWER_WORDS, needsElaboration } from '../pages/VoiceInterview'

describe('whether an answer asks to be drawn out', () => {
  it('presses on brevity, and leaves a full answer alone', () => {
    // Both directions, from the live transcript. The first four are verbatim answers the
    // participant gave; the last two are verbatim answers they gave that nobody would press on.
    for (const brief of [
      'No',
      'It should do',
      "It's still being established",
      "Not that I'm aware of",
      'No all that information is taken on trust',
    ]) {
      expect(needsElaboration(brief, [])).toBe(true)
    }
    for (const full of [
      'I would say the controls are not very strong',
      'I think you have characterised that pretty well actually',
      'They are recurring observations there is a systemic governance gap to do with our asset',
    ]) {
      expect(needsElaboration(full, [])).toBe(false)
    }
  })

  it('puts the line exactly where the constant says', () => {
    // Pinned on both sides of the threshold rather than near it, so moving the constant by one
    // is a decision somebody makes rather than something that drifts.
    const words = (n: number) => Array.from({ length: n }, (_, i) => `w${i}`).join(' ')
    expect(needsElaboration(words(BRIEF_ANSWER_WORDS - 1), [])).toBe(true)
    expect(needsElaboration(words(BRIEF_ANSWER_WORDS), [])).toBe(false)
  })

  it('still presses on an evasion signal in a long answer', () => {
    // The trigger that was already there, kept and asserted independently. Deleting it would
    // leave every brevity case above green, which is what makes this a separate assertion
    // rather than a second example of the first one.
    const evasive =
      'It varies quite a lot depending on the season and on which contractor is on site'
    expect(needsElaboration(evasive, [])).toBe(false)
    expect(needsElaboration(evasive, ['it varies'])).toBe(true)
    // Matched case-insensitively, as it always was.
    expect(needsElaboration(evasive.toUpperCase(), ['It Varies'])).toBe(true)
  })

  it('does not press on silence', () => {
    // An empty answer means the recogniser heard nothing. The reprompt path exists for that;
    // asking somebody to expand on a silence is the wrong response to a microphone that failed.
    // Without this, brevity would have made *every* failed answer draw a press.
    expect(needsElaboration('', ['anything'])).toBe(false)
    expect(needsElaboration('   ', ['anything'])).toBe(false)
  })

  it('is not fooled by an empty evasion signal', () => {
    // `''.includes` is true of everything, so one blank signal in a script would press on every
    // answer in it. None of the 597 in the live corpus is blank, which is the reason to guard
    // rather than a reason not to.
    const full = 'I would say the controls are not very strong at all today'
    expect(needsElaboration(full, [''])).toBe(false)
    expect(needsElaboration(full, ['   '])).toBe(false)
  })
})

// ---------------------------------------------------------------------------------------
// The interview, driven. The predicate being right is not the same as the loop asking it.
// ---------------------------------------------------------------------------------------

const PRESS = 'What makes you say that?'
const VOICE = { elevenlabs_voice_id: 'V', language: 'en', country_code: 'GB', model_id: 'm' }

const SESSION = {
  id: 1, stakeholder_id: 1, node_label: 'Order Fulfilment',
  session_token: 'tok', status: 'pending', voice_config: VOICE,
}

/** One question with one scripted branch - the shape the live scripts actually have. */
function script(options: { branches?: string[]; evasionSignals?: string[] } = {}) {
  const branches = options.branches ?? []
  return {
    script_id: 'SC-014', node_label: 'Order Fulfilment', level: 'L2',
    research_brief: '', study_objectives: [], welcome_message: 'Welcome.',
    sections: [{
      section_id: 'S1', title: 'Operations',
      questions: [{
        id: 'q1', text: 'Question one?',
        follow_up_count: branches.length,
        probing_instructions: 'Ask about the evidence.',
        follow_up_branches: branches,
        evasion_signals: options.evasionSignals ?? [],
      }],
    }],
    closing_message: 'Thank you.',
  }
}

type Sent = { url: string; body: Record<string, unknown> | null }
let sent: Sent[] = []

/**
 * The presses **this** interview asked for.
 *
 * Scoped by `response_text`, for the reason `pairsOfInterviewHearing` gives below: an earlier
 * test's interview posts through whatever stub is installed now, and a press it asked for is
 * indistinguishable from one this test's interview asked for unless the answer says so. Every
 * transcript in this file is distinct for that reason.
 */
function pressesAbout(answers: string[]): Record<string, unknown>[] {
  return sent
    .filter(r => r.url.endsWith('/elaboration-press'))
    .map(r => r.body!)
    .filter(body => answers.includes(String(body.response_text)))
}

type Pair = { question: string; answer: string; question_id: string }

/**
 * The qa pairs of the completion **this** interview posted, found by what it heard.
 *
 * Never "the last completion". `cleanup()` unmounts the page and cannot stop the interview - it
 * is an async loop over closures - and the completion is posted after the review screen appears,
 * so one interview's `/complete` routinely lands in the *next* test's `fetch` stub. Reading the
 * last one is unsound in exactly the way this project has already been bitten by; scanning for
 * this interview's own first answer is the only thing that tells them apart, and a completion
 * that never arrives fails on the timeout rather than passing on a stranger's.
 */
async function pairsOfInterviewHearing(expected: string): Promise<Pair[]> {
  let found: Pair[] = []
  await waitFor(() => {
    const mine = sent
      .filter(r => r.url.endsWith('/complete'))
      .map(r => (r.body?.qa_pairs ?? []) as Pair[])
      .find(pairs => pairs.some(pair => pair.answer.includes(expected)))
    expect(mine, `no completion carried ${JSON.stringify(expected)}`).toBeTruthy()
    found = mine!
  }, { timeout: 10000 })
  return found
}

/**
 * Run one interview in which the recogniser hears `heard` in turn, one per answer.
 *
 * The transcripts differ per answer deliberately: the primary answer, the branch answer and a
 * press's own answer are three different things to this loop, and a recogniser that said the
 * same thing every time could not tell which pair carried which.
 */
async function runInterview(scriptBody: object, heard: string[]) {
  sent = []
  let spoken = 0

  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    let body: Record<string, unknown> | null = null
    if (init?.body) { try { body = JSON.parse(String(init.body)) } catch { body = null } }
    sent.push({ url, body })
    if (url.endsWith('/interviews/tok')) {
      return new Response(
        JSON.stringify({
          session: SESSION, script: scriptBody, speech_policy: 'browser_permitted',
        }),
        { status: 200 },
      )
    }
    if (url.endsWith('/elaboration-press')) {
      return new Response(JSON.stringify({ press_text: PRESS }), { status: 200 })
    }
    if (url.endsWith('/speak')) {
      return new Response(new Blob([new Uint8Array([1, 2, 3])]), { status: 200 })
    }
    return new Response('{}', { status: 200 })
  }))

  class FakeRecognition {
    continuous = false
    interimResults = false
    lang = ''
    onresult: ((e: unknown) => void) | null = null
    onend: (() => void) | null = null
    onerror: ((e: { error: string }) => void) | null = null
    start() {
      // One transcript per recogniser, in order. Past the end it hears nothing, which ends the
      // answer rather than repeating the last thing said.
      const transcript = heard[spoken++] ?? ''
      setTimeout(() => {
        if (transcript) {
          this.onresult?.({
            resultIndex: 0,
            results: [Object.assign([{ transcript }], { isFinal: true })],
          })
        }
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

  render(
    <MemoryRouter initialEntries={['/interview/tok']}>
      <Routes>
        <Route path="/interview/:sessionToken" element={<VoiceInterview />} />
      </Routes>
    </MemoryRouter>,
  )
  await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))
  // Settle inside the test that started it: a completion arriving later posts through the next
  // test's stub and is evidence about nothing.
  await screen.findByText(/thank you/i, {}, { timeout: 10000 })
}

afterEach(() => {
  cleanup()
  vi.stubGlobal('fetch', async () => new Response('{}', { status: 200 }))
})

/**
 * Every transcript in this file is distinct, and that is load-bearing rather than tidy.
 *
 * An interview outlives the test that started it, and posts through whatever `fetch` stub is
 * installed now. What it *said* is the only thing that distinguishes its presses and its
 * completion from this test's, so no two interviews here may hear the same words.
 */
const SHORT_PRIMARY = 'Not really'
const FULL_PRIMARY = 'I would say the controls are not very strong at the moment'
const FULL_BRANCH = 'The head of asset management signs every one of them off personally'

describe('the interview presses where a person would', () => {
  it('presses on a short answer to the question itself', async () => {
    const drawnOut = 'Because the evidence is thin and nobody has ever owned it'
    await runInterview(script(), [SHORT_PRIMARY, drawnOut])

    const asked = pressesAbout([SHORT_PRIMARY])
    expect(asked).toHaveLength(1)
    expect(asked[0].question_text).toBe('Question one?')
    // The script's own line of enquiry travels with it - a press that asked "tell me more"
    // without it would be the same question on every engagement.
    expect(asked[0].probing_instructions).toBe('Ask about the evidence.')

    // And what came back is kept, both on its own pair and merged into the answer.
    const pairs = await pairsOfInterviewHearing(SHORT_PRIMARY)
    expect(pairs.map(pair => pair.question)).toContain(PRESS)
    const primary = pairs.find(pair => pair.question === 'Question one?')!
    expect(primary.answer).toContain(SHORT_PRIMARY)
    expect(primary.answer).toContain(drawnOut)
  }, 25000)

  it('presses on a short answer to a scripted follow-up branch', async () => {
    // **The layer the reported defect was actually on.** Sixty of the ninety-one answers in the
    // live interview were to branches, and every short one was. A press that only ever looked
    // at the primary answer passes the test above and fixes nothing the owner reported.
    const shortBranch = 'Nobody does'
    const drawnOut = 'Because it has never been assigned to anybody in particular'
    await runInterview(
      script({ branches: ['And who signs it off?'] }),
      [FULL_PRIMARY, shortBranch, drawnOut],
    )

    const asked = pressesAbout([shortBranch])
    expect(asked).toHaveLength(1)
    // Asked about the *branch*, not about the question - a press has to follow what was said
    // last, or it presses on an answer two turns old.
    expect(asked[0].question_text).toBe('And who signs it off?')
    // And the long primary answer beside it drew nothing, in the same interview.
    expect(pressesAbout([FULL_PRIMARY])).toEqual([])

    const pairs = await pairsOfInterviewHearing(shortBranch)
    const branchPair = pairs.find(pair => pair.question === 'And who signs it off?')!
    expect(branchPair.answer).toContain(shortBranch)
    expect(branchPair.answer).toContain(drawnOut)
  }, 25000)

  it('leaves a long, non-evasive answer alone at both layers', async () => {
    // **The control, and without it a change that pressed on everything would pass the two
    // tests above.** Driven with a branch as well, so "never presses" is asserted at both
    // layers rather than at the one that happened to be convenient.
    await runInterview(
      script({ branches: ['And who signs it off?'] }),
      [FULL_PRIMARY, FULL_BRANCH],
    )

    expect(pressesAbout([FULL_PRIMARY, FULL_BRANCH])).toEqual([])
    const pairs = await pairsOfInterviewHearing(FULL_PRIMARY)
    expect(pairs.map(pair => pair.question)).not.toContain(PRESS)
  }, 25000)

  it('does not press on a press', async () => {
    // The bound. A brief reply to a press must not draw another one, or a participant giving
    // short answers is interrogated rather than interviewed - the loop has no other stop.
    const shortPrimary = 'Not to my knowledge'
    const shortReply = 'It just is'
    await runInterview(script(), [shortPrimary, shortReply])

    expect(pressesAbout([shortPrimary])).toHaveLength(1)
    expect(pressesAbout([shortReply])).toEqual([])
  }, 25000)

  it('gives a press its own question id, distinct from the branch it sits beside', async () => {
    // Presses and branches are separate series in `capturedPair`, and a press used to be
    // numbered off the branch counter - which could not collide while a press could only happen
    // in one place, and can now. Stored answers cite these ids.
    //
    // **Two branches, because a press has always consumed a branch slot** - it asks what the
    // first scripted branch was there to ask. With one branch, a question that drew a press has
    // no branch left, so this could not have both series on screen at once.
    const shortPrimary = 'Hardly ever'
    const shortBranch = 'No one at all'
    await runInterview(
      script({ branches: ['Say more about that?', 'And who signs it off?'] }),
      [
        shortPrimary, 'Because the evidence for it has never been gathered',
        shortBranch, 'It has never been assigned to a named individual here',
      ],
    )

    const pairs = await pairsOfInterviewHearing(shortPrimary)
    const ids = pairs.map(pair => pair.question_id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids.filter(id => id.includes('.F')).length).toBe(2)
    expect(ids.filter(id => id.includes('.B')).length).toBe(1)
  }, 25000)
})
