// ui/src/__tests__/TestInterviewPressSlug.test.tsx
//
// The dialog is opened from a project's Avery setup tab with that project's slug, and the
// consultant types real answers into it. It took the slug as a prop and threw it away
// (`{ slug: _slug, ... }`), so the press it posted carried no project - and with no project
// there is no llm_mode, and no llm_mode resolves to standard. A sensitive engagement's
// answers went to a hosted model.
//
// Asserted on the request body, because the prop being present in the signature is exactly
// what was true while the defect was live.
import { render, screen } from '@testing-library/react'
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
          evasion_signals: ['not sure'],
        },
      ],
    },
  ],
}

const EVASIVE_ANSWER = 'I am not sure really'

let pressBodies: Record<string, unknown>[] = []
let speakBodies: Record<string, unknown>[] = []

function installFetch() {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/script')) {
      return new Response(JSON.stringify(SCRIPT), { status: 200 })
    }
    if (url.endsWith('/speak')) {
      speakBodies.push(JSON.parse(String(init?.body)))
      return new Response(new Blob([new Uint8Array([1, 2, 3])]), { status: 200 })
    }
    if (url.endsWith('/elaboration-press')) {
      pressBodies.push(JSON.parse(String(init?.body)))
      return new Response(JSON.stringify({ press_text: 'Which step, specifically?' }), { status: 200 })
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
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).webkitSpeechRecognition = FakeRecognition
}

function installAudioAndMic() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).Audio = class {
    onended: (() => void) | null = null
    onerror: (() => void) | null = null
    pause() {}
    play() {
      setTimeout(() => this.onended?.(), 0)
      return Promise.resolve()
    }
  }
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

describe('the smoke-test dialog and the project it was opened from', () => {
  beforeEach(() => { vi.restoreAllMocks() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('sends that project slug with every elaboration press', async () => {
    pressBodies = []
    speakBodies = []
    vi.stubGlobal('fetch', installFetch())
    installSpeechRecognition(EVASIVE_ANSWER)
    installAudioAndMic()

    render(<TestInterviewDialog slug="secure-proj" onClose={() => {}} />)

    const toBriefing = await screen.findByRole('button', { name: /continue|start|begin/i })
    await userEvent.click(toBriefing)
    const start = await screen.findByRole('button', { name: /start test interview/i })
    await userEvent.click(start)

    await screen.findByText(/test interview complete/i, undefined, { timeout: 5000 })

    expect(pressBodies.length).toBeGreaterThan(0)
    for (const body of pressBodies) {
      expect(body.slug).toBe('secure-proj')
    }
  })

  it('names no voice of its own, and sends the slug so the server resolves one', async () => {
    // The dialog used to declare `const AVERY_VOICE_ID = 'JBFqnCBsd6RMkjVDRZzb'` - George -
    // and pass it on all three /speak calls. The server's own corrected default was therefore
    // unreachable from the only caller there is, so Avery rehearsed as one man and interviewed
    // as another, under the same variable name in two files, with every gate green.
    //
    // Asserted on the request body for the reason this file's header already gives about the
    // slug: a constant being absent from the source is not the same claim as a voice being
    // absent from the request, and it was the weaker of the two that let this survive.
    pressBodies = []
    speakBodies = []
    vi.stubGlobal('fetch', installFetch())
    installSpeechRecognition(EVASIVE_ANSWER)
    installAudioAndMic()

    render(<TestInterviewDialog slug="secure-proj" onClose={() => {}} />)

    const toBriefing = await screen.findByRole('button', { name: /continue|start|begin/i })
    await userEvent.click(toBriefing)
    const start = await screen.findByRole('button', { name: /start test interview/i })
    await userEvent.click(start)

    await screen.findByText(/test interview complete/i, undefined, { timeout: 5000 })

    expect(speakBodies.length).toBeGreaterThan(0)
    for (const body of speakBodies) {
      expect(body.voice_id).toBeUndefined()
      expect(body.slug).toBe('secure-proj')
    }
  })
})
