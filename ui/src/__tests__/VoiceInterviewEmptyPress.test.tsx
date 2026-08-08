// ui/src/__tests__/VoiceInterviewEmptyPress.test.tsx
//
// An over-budget elaboration press comes back as press_text: "". The page used to treat that
// as a press, because `"" ?? fallback` is `""`: it set the question to an empty string, spoke
// nothing, then started listening, so the interviewee sat recording in silence in front of a
// blank question - and an answer row was submitted with no question text at all.
//
// This drives the real interview loop rather than the helper that fetches the press, because
// the defect was half in the helper and half in the branch that consumed it. Asserting the
// helper's return value would have passed against the broken page.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import VoiceInterview from '../pages/VoiceInterview'

const SCRIPT = {
  script_id: 'SC-014',
  node_label: 'Order Fulfilment',
  level: 'L2',
  research_brief: '',
  study_objectives: [],
  welcome_message: 'Welcome.',
  sections: [
    {
      section_id: 'S1',
      title: 'Operations',
      questions: [
        {
          id: 'q1',
          text: 'What slows fulfilment down?',
          follow_up_count: 0,
          probing_instructions: 'Ask for specifics.',
          follow_up_branches: [],
          // The answer the fake microphone returns contains this, so the page decides the
          // answer is evasive and presses. Without it the branch under test never runs.
          evasion_signals: ['not sure'],
        },
      ],
    },
  ],
  closing_message: 'Thank you.',
}

const SESSION = {
  id: 1,
  stakeholder_id: 1,
  node_label: 'Order Fulfilment',
  session_token: 'tok',
  status: 'pending',
  voice_config: { elevenlabs_voice_id: 'v1', language: 'en', country_code: 'GB' },
}

const EVASIVE_ANSWER = 'I am not sure really'

/** Everything spoken, in order, so an empty utterance is visible rather than inferred. */
let spoken: string[] = []
/** The body of the PATCH /complete call - the answers that would reach the database. */
let submitted: { qa_pairs: { question: string; answer: string }[] } | null = null

function installFetch(pressText: unknown) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/interviews/tok')) {
      return new Response(JSON.stringify({ session: SESSION, script: SCRIPT }), { status: 200 })
    }
    if (url.endsWith('/speak')) {
      spoken.push(JSON.parse(String(init?.body)).text)
      return new Response(new Blob([new Uint8Array([1, 2, 3])]), { status: 200 })
    }
    if (url.endsWith('/elaboration-press')) {
      return new Response(JSON.stringify({ press_text: pressText }), { status: 200 })
    }
    if (url.endsWith('/complete')) {
      submitted = JSON.parse(String(init?.body))
      return new Response('{}', { status: 200 })
    }
    return new Response('{}', { status: 200 })
  })
}

/** A microphone that hears one fixed sentence and then stops, without any timers. */
function installSpeechRecognition(transcript: string) {
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
          results: [Object.assign([{ transcript }], { isFinal: true })],
        })
        // The page clears its recognition ref on an error and only then lets onend finish
        // the promise; without this, onend restarts the recogniser and the loop never
        // advances. 'no-speech' is the benign error the page treats exactly this way.
        this.onerror?.({ error: 'no-speech' })
        this.onend?.()
      }, 0)
    }

    stop() {
      this.onend?.()
    }
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).SpeechRecognition = FakeRecognition
}

function installAudioAndMic() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).Audio = class {
    onended: (() => void) | null = null
    onerror: (() => void) | null = null
    play() {
      setTimeout(() => this.onended?.(), 0)
      return Promise.resolve()
    }
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

async function runInterviewWithPress(pressText: unknown) {
  spoken = []
  submitted = null
  vi.stubGlobal('fetch', installFetch(pressText))
  installSpeechRecognition(EVASIVE_ANSWER)
  installAudioAndMic()

  render(
    <MemoryRouter initialEntries={['/interview/tok']}>
      <Routes>
        <Route path="/interview/:sessionToken" element={<VoiceInterview />} />
      </Routes>
    </MemoryRouter>,
  )

  const start = await screen.findByRole('button', { name: /start interview/i })
  await userEvent.click(start)
  await waitFor(() => expect(submitted).not.toBeNull(), { timeout: 5000 })
}

describe('an elaboration press that came back empty', () => {
  beforeEach(() => { vi.restoreAllMocks() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('is not spoken, so the interviewee is never left recording in silence', async () => {
    await runInterviewWithPress('')
    expect(spoken).not.toContain('')
    expect(spoken).toEqual(['Welcome.', 'What slows fulfilment down?', 'Thank you.'])
  })

  it('does not record an answer against an empty question', async () => {
    await runInterviewWithPress('')
    const questions = submitted!.qa_pairs.map(p => p.question)
    expect(questions).not.toContain('')
    expect(questions).toEqual(['What slows fulfilment down?'])
  })

  it('still presses when the press is a real one', async () => {
    // The control. Without it, a page that skipped every press - budget or not - would pass
    // both tests above, and the follow-up feature would be silently dead instead.
    await runInterviewWithPress('Which step, specifically?')
    expect(spoken).toContain('Which step, specifically?')
    expect(submitted!.qa_pairs.map(p => p.question)).toContain('Which step, specifically?')
  })
})
