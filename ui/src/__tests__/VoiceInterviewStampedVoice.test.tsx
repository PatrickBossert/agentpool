// ui/src/__tests__/VoiceInterviewStampedVoice.test.tsx
//
// The interview portal no longer decides, or even names, the voice - asserted as *sent*.
//
// This file was `VoiceInterviewDefaultVoice.test.tsx` and asserted the opposite property: that
// a session carrying no `voice_config` fell back to Avery's default. That fallback is deleted.
// A session is stamped with its interviewer's resolved voice and model at creation, so a
// session without one is a bug, and a fallback would hide it by putting a stranger in front of
// a participant - which is exactly what it did for the whole life of `DEFAULT_VOICE_CONFIG`,
// whose value was ElevenLabs' stock Rachel for an interviewer described as male everywhere.
//
// The history is worth keeping because it is why this reads the *request* rather than the
// source. The first guard on this property read the TSX from the Python suite and checked that
// Rachel's id was absent and Avery's present. Neither says what the component uses: repointing
// the use left the backend suite, the frontend suite and tsc all green while the portal spoke
// as George. "A radio tested as rendered; not as sent."
//
// Two cases, and the pair is the point. A stamped session is conducted and sends no voice at
// all - the server reads the stamp. An unstamped session is refused before a single word is
// spoken, rather than being spoken in something invented here.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import VoiceInterview from '../pages/VoiceInterview'

// ElevenLabs' stock Rachel - the female voice the first completed interview was conducted in -
// George, the voice the rehearsal dialog declared under Avery's name, and Avery's own default.
// All three are named so the assertions can say "none of these" without reading any of them
// from the source they are checking. Avery's is in the list deliberately: the portal must not
// name the *right* voice either, because the last two were also right when they were written.
const RACHEL = '21m00Tcm4TlvDq8ikWAM'
const GEORGE = 'JBFqnCBsd6RMkjVDRZzb'
const AVERY_DEFAULT_VOICE = 'onwK4e9ZLuTAKqWW03F9'

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

/** The server's answer for who is speaking. Resolved from the session's stamp, never here. */
const LAURA = { interviewer_name: 'Laura Nelson', interviewer_image_url: '', interviewer_tagline: '' }

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

/** Every body that reached POST /speak, parsed, in order. */
let speakBodies: Record<string, unknown>[] = []
/** Whether the interview reached its end, so a test cannot pass on an interview that never ran. */
let completed = false

function installFetch(session: unknown, branding?: unknown) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/interviews/tok')) {
      return new Response(JSON.stringify({ session, script: SCRIPT, branding }), { status: 200 })
    }
    if (url.endsWith('/speak')) {
      speakBodies.push(JSON.parse(String(init?.body)))
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

async function startInterview(voiceConfig: unknown, branding?: unknown) {
  speakBodies = []
  completed = false
  vi.stubGlobal('fetch', installFetch(sessionWith(voiceConfig), branding))
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
}

describe('the voice the interview portal speaks in', () => {
  beforeEach(() => { vi.restoreAllMocks() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('names no voice at all when the session carries a stamp', async () => {
    await startInterview({
      elevenlabs_voice_id: 'STAMPED-ON-THE-SESSION',
      language: 'en',
      country_code: 'GB',
      model_id: 'eleven_multilingual_v2',
    })
    await waitFor(() => expect(completed).toBe(true), { timeout: 5000 })

    // It spoke, so the assertions below are about a real interview rather than about silence.
    expect(speakBodies.length).toBeGreaterThan(0)
    // And it spoke without saying who in. The whole request body is inspected rather than one
    // key, because a portal that renamed the field would pass a `voice_id` check while still
    // deciding the voice.
    const keys = new Set(speakBodies.flatMap(b => Object.keys(b)))
    expect(keys).toEqual(new Set(['text']))
    const serialised = JSON.stringify(speakBodies)
    for (const id of [RACHEL, GEORGE, AVERY_DEFAULT_VOICE, 'STAMPED-ON-THE-SESSION']) {
      expect(serialised).not.toContain(id)
    }
  })

  it('refuses to conduct a session that carries no stamp, rather than inventing a voice', async () => {
    // The control for the test above, and the case the deleted fallback used to swallow. A
    // portal that simply ignored `voice_config` would pass the first test and fail this one,
    // which is why "sends no voice" is not enough on its own.
    await startInterview(null)

    await waitFor(() => expect(screen.getByText(/cannot be conducted/i)).toBeTruthy())
    expect(speakBodies).toEqual([])
    expect(completed).toBe(false)
  })
})


describe('the interviewer a participant reads', () => {
  beforeEach(() => { vi.restoreAllMocks() })
  afterEach(() => { vi.unstubAllGlobals() })

  it("names whoever the server says is speaking, on both screens that name anybody", async () => {
    // The portal declared "Avery Singh" twice and his photograph once, and `interviewer_selection`
    // defaults to `random` over a roster of two - so roughly half of every project's participants
    // would have heard Laura and read Avery. The name is the server's answer now, resolved from
    // the session's stamp, and this asserts what is *rendered* rather than what is declared.
    //
    // **Both phases, because they are two separate renders of the name.** The first version of
    // this test clicked Start before asserting, so it only ever saw the interviewing header -
    // and a power-check that hardcoded "Avery Singh" back into the *ready* screen's persona
    // block passed it. One of the two literals was invisible to the test written to forbid it.
    vi.stubGlobal('fetch', installFetch(
      sessionWith({ elevenlabs_voice_id: 'V', language: 'en', country_code: 'GB', model_id: 'm' }),
      LAURA,
    ))
    installSpeechRecognition('A clear answer about picking.')
    installAudioAndMic()

    render(
      <MemoryRouter initialEntries={['/interview/tok']}>
        <Routes>
          <Route path="/interview/:sessionToken" element={<VoiceInterview />} />
        </Routes>
      </MemoryRouter>,
    )

    // The ready screen.
    const start = await screen.findByRole('button', { name: /start interview/i })
    expect(screen.getByText('Laura Nelson')).toBeTruthy()
    expect(screen.queryByText('Avery Singh')).toBeNull()

    // And the interviewing screen.
    await userEvent.click(start)
    expect(await screen.findByText('Laura Nelson')).toBeTruthy()
    expect(screen.queryByText('Avery Singh')).toBeNull()
    expect(document.body.innerHTML).not.toContain('avery-singh')
  })

  it('shows initials rather than somebody else\'s photograph when there is no headshot', async () => {
    // Laura is the first agent with `image: None`, which agents/identity.py has always said is a
    // legitimate state. The portal used to fall back to `/agents/avery-singh-hires.jpg`, which put
    // one person's face on another person's name.
    await startInterview(
      { elevenlabs_voice_id: 'V', language: 'en', country_code: 'GB', model_id: 'm' },
      LAURA,
    )

    // Two of them - the ready screen's 24px circle and the interviewing panel's 160px one -
    // and neither may be somebody else's photograph.
    expect((await screen.findAllByText('LN')).length).toBeGreaterThan(0)
    expect(document.querySelector('img[src*="avery"]')).toBeNull()
  })
})
