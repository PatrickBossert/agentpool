// ui/src/__tests__/VoiceInterviewDefaultVoice.test.tsx
//
// The interview portal's fallback voice, asserted as *sent* rather than as *declared*.
//
// The first guard on this property read the TSX source from the Python suite and checked two
// things: that Rachel's id was absent, and that the literal `elevenlabs_voice_id:
// 'onwK4e9ZLuTAKqWW03F9'` was present. Neither says the component *uses* DEFAULT_VOICE_CONFIG.
// Repointing the use - `session.voice_config ?? { ...DEFAULT_VOICE_CONFIG, elevenlabs_voice_id:
// 'JBFqnCBsd6RMkjVDRZzb' }` - left the backend suite, the frontend suite and tsc all green
// while the portal spoke as George. That is CLAUDE.md's recurring failure mode exactly: "a
// radio tested as rendered; not as sent", landing on the one test relied on to justify letting
// a second declaration of the voice stand.
//
// So this reads the voice id off the body of the POST /speak request, which is the only place
// the answer is unambiguous. Two cases, and the pair is the point: a session that carries no
// voice_config falls back to Avery's default, and a session that carries one is spoken in that
// instead. Without the second, a portal that ignored the session entirely would pass the first.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import VoiceInterview from '../pages/VoiceInterview'

// Avery's default, and the one value in this file that must equal the server's. The Python
// guard `test_the_interview_portals_fallback_is_averys_default_voice` holds it equal to
// `AGENT_IDENTITY['stakeholder_interviewer'].voice_id`; this file holds it equal to what is
// actually spoken. Neither claim is worth much without the other.
const AVERY_DEFAULT_VOICE = 'onwK4e9ZLuTAKqWW03F9'

// ElevenLabs' stock Rachel - the female voice the first completed interview was conducted in -
// and George, the voice the rehearsal dialog declared under Avery's name. Named so the
// assertions can say "not these" without reading either from the source they are checking.
const RACHEL = '21m00Tcm4TlvDq8ikWAM'
const GEORGE = 'JBFqnCBsd6RMkjVDRZzb'

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
          probing_instructions: '',
          follow_up_branches: [],
          evasion_signals: [],
        },
      ],
    },
  ],
  closing_message: 'Thank you.',
}

function sessionWith(voiceConfig: unknown) {
  return {
    id: 1,
    stakeholder_id: 1,
    node_label: 'Order Fulfilment',
    session_token: 'tok',
    status: 'pending',
    voice_config: voiceConfig,
  }
}

/** Every voice id that reached POST /speak, in order. */
let voicesUsed: string[] = []
/** Whether the interview reached its end, so a test cannot pass on an interview that never ran. */
let completed = false

function installFetch(session: unknown) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/interviews/tok')) {
      return new Response(JSON.stringify({ session, script: SCRIPT }), { status: 200 })
    }
    if (url.endsWith('/speak')) {
      voicesUsed.push(JSON.parse(String(init?.body)).voice_id)
      return new Response(new Blob([new Uint8Array([1, 2, 3])]), { status: 200 })
    }
    if (url.endsWith('/complete')) {
      completed = true
      return new Response('{}', { status: 200 })
    }
    return new Response('{}', { status: 200 })
  })
}

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

async function runInterview(voiceConfig: unknown) {
  voicesUsed = []
  completed = false
  vi.stubGlobal('fetch', installFetch(sessionWith(voiceConfig)))
  installSpeechRecognition('A clear answer about picking.')
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
  await waitFor(() => expect(completed).toBe(true), { timeout: 5000 })
}

describe('the voice the interview portal actually speaks in', () => {
  beforeEach(() => { vi.restoreAllMocks() })
  afterEach(() => { vi.unstubAllGlobals() })

  it("falls back to Avery's default when the session carries no voice_config", async () => {
    await runInterview(null)

    expect(voicesUsed.length).toBeGreaterThan(0)
    expect(new Set(voicesUsed)).toEqual(new Set([AVERY_DEFAULT_VOICE]))
    expect(voicesUsed).not.toContain(RACHEL)
    expect(voicesUsed).not.toContain(GEORGE)
  })

  it('speaks in the session\'s own voice when it carries one', async () => {
    // The control for the test above. A portal that ignored the session and always used the
    // fallback would pass that one and be broken for every real interview, which is the same
    // shape as an implementation that resolves only defaults passing every override test.
    await runInterview({ elevenlabs_voice_id: 'STAMPED-ON-THE-SESSION', language: 'en', country_code: 'GB' })

    expect(new Set(voicesUsed)).toEqual(new Set(['STAMPED-ON-THE-SESSION']))
  })
})
