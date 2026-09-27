// ui/src/__tests__/VoiceInterviewElapsed.test.tsx
//
// How long the interview has been going, and how long it was supposed to take.
//
// Finding 5 of the 17 September live interview: *"it would help to see elapsed time in the
// centre of the bar at the top - the interview felt very long, but it was probably within the
// asked-for timebox - I wanted a way of checking."* Both halves of that sentence are the
// requirement: elapsed alone answers "how long", and only the timebox answers "is that a lot".
//
// **Every assertion on the bar reads `textContent` exactly, never `toHaveTextContent`.** That
// matcher is a substring test, and "30:00 of 40:00" contains "0:00 of 40:00" - so the mutation
// that starts the clock when the page loads rather than when the participant taps Start passed
// against it. Found by power-checking, which is the only thing that could have found it.
//
// **The clock is passed, never read.** `CLAUDE.md` is emphatic about this and has the scar to
// go with it: three tests in `milestoneVariance.test.ts` defaulted `today` to `new Date()`, one
// detonated on 19 August 2026 and two more were dated to follow it within the week - while the
// block below them in the same file already carried a comment saying the clock is passed
// explicitly "so these are deterministic". So `elapsedLabel` takes both ends of the interval,
// `ElapsedTime` takes `now` as a prop, and nothing here is true only today.
import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, afterEach, vi } from 'vitest'

import VoiceInterview, { elapsedLabel, scriptTimeboxMinutes } from '../pages/VoiceInterview'

const MINUTE = 60_000
/** An arbitrary, fixed instant. Nothing below is true only on the day it was written. */
const T0 = 1_756_000_000_000

describe('what the clock says', () => {
  it('counts from the start of the interview, in minutes and seconds', () => {
    expect(elapsedLabel(T0, T0, 0)).toBe('0:00')
    expect(elapsedLabel(T0, T0 + 1_000, 0)).toBe('0:01')
    expect(elapsedLabel(T0, T0 + 61_000, 0)).toBe('1:01')
    // Minutes are unbounded rather than rolling into hours: against a target written "40:00",
    // "72:15" is read at a glance and "1:12:15" has to be converted first.
    expect(elapsedLabel(T0, T0 + 72 * MINUTE + 15_000, 0)).toBe('72:15')
  })

  it('shows the timebox beside it when the script declares one', () => {
    expect(elapsedLabel(T0, T0 + 18 * MINUTE + 42_000, 40)).toBe('18:42 of 40:00')
    // And nothing beside it when the script does not. **The control that matters most here**:
    // a target invented in the front end is worse than no target, because a participant would
    // pace themselves against a number nobody set.
    expect(elapsedLabel(T0, T0 + 18 * MINUTE + 42_000, 0)).toBe('18:42')
  })

  it('reads zero when the clock goes backwards', () => {
    // A device correcting itself over NTP mid-interview. "-1:-3" is the alternative.
    expect(elapsedLabel(T0, T0 - 90_000, 0)).toBe('0:00')
    expect(elapsedLabel(T0, T0 - 90_000, 40)).toBe('0:00 of 40:00')
  })
})

describe('the timebox this script asks for', () => {
  it('sums the sections, which is where the number lives', () => {
    // The live `sp-gs-am` shape: `target_minutes` per section, never once for the script. The
    // twelve scripts in `interview_scripts_v9` total between 34 and 54 minutes; this is one.
    expect(scriptTimeboxMinutes([
      { target_minutes: 8 }, { target_minutes: 6 }, { target_minutes: 8 },
      { target_minutes: 7 }, { target_minutes: 6 }, { target_minutes: 5 },
    ])).toBe(40)
  })

  it('answers nothing at all when any section does not say', () => {
    // Not "sum what is there". A script half of whose sections declare a target would answer a
    // number smaller than the interview it describes, and a participant pacing themselves
    // against it would think they were overrunning from the middle onwards.
    expect(scriptTimeboxMinutes([{ target_minutes: 8 }, {}])).toBe(0)
    expect(scriptTimeboxMinutes([])).toBe(0)
    expect(scriptTimeboxMinutes([
      { target_minutes: 8 }, { target_minutes: Number.NaN },
    ])).toBe(0)
  })
})

// ---------------------------------------------------------------------------------------
// The page, driven. A correct label nobody renders is the defect, not the fix.
// ---------------------------------------------------------------------------------------

const VOICE = { elevenlabs_voice_id: 'V', language: 'en', country_code: 'GB', model_id: 'm' }
const SESSION = {
  id: 1, stakeholder_id: 1, node_label: 'Order Fulfilment',
  session_token: 'tok', status: 'pending', voice_config: VOICE,
}

function script(targetMinutes?: number) {
  return {
    script_id: 'SC-014', node_label: 'Order Fulfilment', level: 'L2',
    research_brief: '', study_objectives: [], welcome_message: 'Welcome.',
    sections: [{
      section_id: 'S1', title: 'Operations',
      ...(targetMinutes === undefined ? {} : { target_minutes: targetMinutes }),
      questions: [1, 2].map(n => ({
        id: `q${n}`, text: `Question ${n}, asked at a length nobody would press on?`,
        follow_up_count: 0, probing_instructions: '', follow_up_branches: [],
        evasion_signals: [],
      })),
    }],
    closing_message: 'Thank you.',
  }
}

/** The recogniser, the audio element and the microphone an interview reaches for. */
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

function installFetch(scriptBody: object) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/interviews/tok')) {
      return new Response(
        JSON.stringify({
          session: SESSION, script: scriptBody, speech_policy: 'browser_permitted',
        }),
        { status: 200 },
      )
    }
    if (url.endsWith('/speak')) {
      return new Response(new Blob([new Uint8Array([1, 2, 3])]), { status: 200 })
    }
    return new Response('{}', { status: 200 })
  }))
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/interview/tok']}>
      <Routes>
        <Route path="/interview/:sessionToken" element={<VoiceInterview />} />
      </Routes>
    </MemoryRouter>,
  )
}

/**
 * Start an interview under fake timers, so the clock is this test's rather than the wall's.
 *
 * Two questions, so the interviewing phase - the only place the top bar exists - is still on
 * screen while the assertions are made. The recogniser answers at a length that draws no
 * elaboration press, because a press is another turn and this file is not about presses.
 */
async function startInterviewAt(scriptBody: object) {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(T0)
  installFetch(scriptBody)
  installTheInterviewsSurroundings()
  renderPage()
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  await user.click(await screen.findByRole('button', { name: /start interview/i }))
  await screen.findByTestId('elapsed-time')
}

/** Move the world on, and let the interval that reads the clock fire. */
async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms)
  })
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.stubGlobal('fetch', async () => new Response('{}', { status: 200 }))
})

describe('the top bar during an interview', () => {
  it('shows elapsed time against the timebox, and keeps counting', async () => {
    await startInterviewAt(script(40))

    expect(screen.getByTestId('elapsed-time').textContent).toBe('0:00 of 40:00')

    // Driven rather than waited for: the assertion is about what the bar says after ninety
    // seconds, not about how long this test takes.
    await advance(90_000)
    expect(screen.getByTestId('elapsed-time').textContent).toBe('1:30 of 40:00')
  }, 20000)

  it('shows elapsed time alone when the script declares no timebox', async () => {
    // The control. A page that printed a default target would pass the test above.
    await startInterviewAt(script(undefined))

    await advance(65_000)
    const shown = screen.getByTestId('elapsed-time')
    expect(shown.textContent).toBe('1:05')
    expect(shown.textContent).not.toContain(' of ')
  }, 20000)

  it('marks the time once the interview has run past its timebox', async () => {
    // "Was it within the timebox?" is the question that was asked, so the answer is on the
    // screen rather than left to be worked out from two numbers.
    await startInterviewAt(script(2))

    expect(screen.getByTestId('elapsed-time').className).not.toContain('amber')
    await advance(2 * MINUTE + 1_000)
    expect(screen.getByTestId('elapsed-time').textContent).toBe('2:01 of 2:00')
    expect(screen.getByTestId('elapsed-time').className).toContain('amber')
  }, 20000)

  it('counts from Start, not from when the link was opened', async () => {
    // A participant who opens the link and leaves the device-setup screen up over lunch has not
    // been interviewed for an hour, and arriving at question one on "58:12 of 40:00" would be a
    // worse answer than none.
    //
    // **The first version of this asserted the bar was absent on the setup screen, and that is
    // not an assertion about anything**: the top bar only exists in the interviewing phase, so
    // `queryByTestId` answers null however the clock behaves. It survived the mutation it was
    // written for - `startedAt ?? Date.now()`, the page-load clock - which is this project's
    // "a control asserted where it could never have been" arriving again. So the wait happens
    // *before* Start, and the assertion is on what the bar says once there is one.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(T0)
    installFetch(script(40))
    installTheInterviewsSurroundings()
    renderPage()
    const start = await screen.findByRole('button', { name: /start interview/i })

    // Half an hour on the setup screen.
    await advance(30 * MINUTE)

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await user.click(start)
    await screen.findByTestId('elapsed-time')

    expect(screen.getByTestId('elapsed-time').textContent).toBe('0:00 of 40:00')
  }, 20000)
})
